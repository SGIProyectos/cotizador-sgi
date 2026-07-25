import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from svgpathtools import parse_path

from catalog_data import (
    CABLES,
    DISTANCIADORES,
    LAMINAS,
    LEDS_CAJA,
    LEDS_CANAL,
    PEGAMENTOS,
    PRECIOS_BASE,
    PRECIOS_CAJA_M2,
    SILVATRIM,
    TIPOS_CONSTRUCCION,
    VINILOS_CERCHA,
    cercha_rango_cm,
    fuente_optima,
    led_recomendado,
    material_cara,
    material_cercha,
    material_sercha_caja,
    recomendar_led_caja,
    silvatrim_recomendado,
    vinil_por_id,
)

log = logging.getLogger("cotizador.calculator")

# ─── ESTRUCTURAS DE DATOS ────────────────────────────────────────────────────

@dataclass
class PathInfo:
    id: str
    perimeter_px: float
    area_px: float
    bbox: dict          # {x, y, w, h}
    is_closed: bool
    perimeter_cm: float = 0.0
    area_cm2: float = 0.0
    svg_id: str = ""    # original id attribute from the SVG element
    fill: str = ""      # fill resuelto (attr, style o clase CSS)
    es_hueco: bool = False   # contador de letra o placa de fondo (fill blanco)
    capa: str = ""      # capa nombrada del SVG: "" | "base" | "corte" | "luz"

@dataclass
class SVGData:
    paths: list[PathInfo]
    viewbox_w: float
    viewbox_h: float
    svg_unit: str           # "px" | "mm" | "cm" | "pt" | "in"
    scale_factor: float = 1.0
    max_pieza_height_px: float = 0.0    # altura máx detectada entre las piezas
    artboard_w_cm: float = 0.0          # >0 si la unidad real del SVG se puede mapear a cm
    capas_detectadas: dict = None       # {"base": n, "corte": n, "luz": n} para piezas con capa
    # — alias retro-compatible para callers viejos —
    @property
    def max_letter_height_px(self) -> float:
        return self.max_pieza_height_px


@dataclass
class QuoteResult:
    tipo: str
    paths_count: int
    area_cara_cm2: float
    perimetro_total_cm: float
    cercha_altura_cm: float
    cercha_area_cm2: float

    # Materiales
    material_cara: dict
    material_cercha: dict
    material_fondo: dict
    laminas_cara: int
    laminas_cercha: int
    laminas_fondo: int

    # Iluminación
    led: dict
    modulos_led: int
    watts_total: float
    fuente: dict

    # Pegamento
    pegamento: dict

    # Costos
    costo_material_cara: float
    costo_material_cercha: float
    costo_material_fondo: float
    costo_led: float
    costo_fuente: float
    costo_pegamento: float
    subtotal: float
    iva: float
    total: float

    # Precio de venta sugerido
    precio_venta_sugerido: float        # precio por fórmula Excel, con ajuste % aplicado
    desglose: list[dict] = field(default_factory=list)
    desglose_letras: list[dict] = field(default_factory=list)
    altura_letra_cm: float = 0.0
    # Rango recomendado de profundidad de cercha según altura (catálogo Signalux)
    cercha_min_cm: float = 0.0
    cercha_max_cm: float = 0.0
    categoria_letra: str = ""           # "Letra pequeña", "Letra mediana", etc.
    precio_venta_costo: float = 0.0     # precio mínimo por costo+margen (referencia)
    tipo_multiplicador: str = ""
    multiplicador_valor: float = 1.0
    precio_sin_ajuste: float = 0.0      # precio fórmula antes del ajuste %
    ajuste_pct: float = 0.0             # % de ajuste aplicado
    tipo_construccion: str = "cajon_luz"
    # Silvatrim
    silvatrim: dict = field(default_factory=dict)
    metros_silvatrim: float = 0.0
    costo_silvatrim: float = 0.0
    # Vinil en cercha
    vinil_cercha: dict = field(default_factory=dict)
    metros_vinil_cercha: float = 0.0
    costo_vinil_cercha: float = 0.0
    # Mano de obra e instalación
    mo_total: float = 0.0
    inst_activa: bool = False
    inst_lugar: str = ""
    inst_viaticos: float = 0.0
    inst_grua: str = ""
    inst_costo_grua: float = 0.0
    inst_extras: float = 0.0
    inst_total: float = 0.0
    precio_final: float = 0.0           # precio_venta_sugerido + inst_total

    # Fase G — Desglose interno (interno al dueño, no se imprime al cliente)
    desglose_costos_componentes: dict = field(default_factory=dict)  # {cara, cercha, leds, fuente, pegamento, dist, fondo, extras}
    warnings: list[str] = field(default_factory=list)                # avisos de inconsistencia (ej. "con luz + 0 LEDs")


# ─── PARSEO DE SVG ───────────────────────────────────────────────────────────

def _path_area_shoelace(path, samples: int = 500) -> float:
    """Área de un path cerrado usando fórmula del zapato."""
    try:
        pts = [path.point(t / samples) for t in range(samples)]
        x = [p.real for p in pts]
        y = [p.imag for p in pts]
        n = len(x)
        area = abs(sum(x[i] * y[(i+1) % n] - x[(i+1) % n] * y[i]
                       for i in range(n))) / 2.0
        return area
    except Exception:
        return 0.0


# ─── HELPERS: UNIDADES, CSS, TRANSFORMS, PRIMITIVAS ──────────────────────────

# Factores de conversión a centímetros para unidades SVG comunes.
_UNIT_TO_CM = {
    "mm": 0.1,
    "cm": 1.0,
    "in": 2.54,
    "pt": 2.54 / 72.0,
    "pc": 2.54 * 12 / 72.0,
    "px": 0.0,   # px no es físico; 0 = unidad no determinable
}

# Tag de namespace SVG → tag corto (sin namespace).
def _ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_length(val: str) -> tuple[float, str]:
    """'200mm' → (200.0, 'mm'). '1024' → (1024.0, '')."""
    if not val:
        return 0.0, ""
    val = val.strip()
    m = re.match(r"^([\-+]?\d*\.?\d+)\s*([a-zA-Z%]*)$", val)
    if not m:
        return 0.0, ""
    try:
        return float(m.group(1)), m.group(2).lower()
    except ValueError:
        return 0.0, ""


def _parse_viewbox(svg_root) -> tuple[float, float, str, float]:
    """Devuelve (vb_w, vb_h, unidad, factor_to_cm).

    factor_to_cm = cuántos cm reales vale 1 unidad del viewBox.
    Si es 0.0, la unidad es px sin información física → indeterminable.
    Casos manejados:
      - Illustrator (style="enable-background:..."): viewBox en pt
      - <svg width="200mm" height="...">: width define el ancho real físico
      - <svg width="2cm">: idem
      - Sin unidad explícita y sin marca Illustrator: px (factor=0)
    """
    vb = svg_root.get("viewBox", "")
    width_attr  = svg_root.get("width", "")
    height_attr = svg_root.get("height", "")
    style       = svg_root.get("style", "") or ""

    # Parse viewBox primero
    vb_w = vb_h = 0.0
    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            try:
                vb_w = float(parts[2])
                vb_h = float(parts[3])
            except ValueError:
                pass

    unit = "px"
    factor_to_cm = 0.0

    # Caso A: Illustrator (viewBox interpretado como pt)
    if "enable-background" in style:
        unit = "pt"
        factor_to_cm = _UNIT_TO_CM["pt"]
    else:
        # Caso B: width con unidad física → derivar el factor
        w_val, w_unit = _parse_length(width_attr)
        if w_val > 0 and w_unit in _UNIT_TO_CM and w_unit != "px":
            unit = w_unit
            w_cm = w_val * _UNIT_TO_CM[w_unit]
            if vb_w > 0:
                factor_to_cm = w_cm / vb_w
            else:
                factor_to_cm = _UNIT_TO_CM[w_unit]
                vb_w = w_val

    # Fallback: si no hay viewBox, usar width/height
    if vb_w <= 0:
        w_val, _ = _parse_length(width_attr)
        h_val, _ = _parse_length(height_attr)
        vb_w = w_val or 500.0
        vb_h = h_val or 500.0

    if vb_h <= 0:
        h_val, _ = _parse_length(height_attr)
        vb_h = h_val or vb_w

    return vb_w, vb_h, unit, factor_to_cm


def _parse_style_classes(svg_text: str) -> dict:
    """Lee bloques <style>...</style> y extrae .clase{fill:color}.

    Devuelve {clase: fill_color} para que los paths con class='clase' puedan
    resolver su fill efectivo. Maneja múltiples reglas y selectores agrupados.
    """
    mapping: dict[str, str] = {}
    for sty in re.findall(r"<style[^>]*>(.*?)</style>", svg_text, flags=re.DOTALL | re.IGNORECASE):
        for selector, body in re.findall(r"([^{]+)\{([^}]*)\}", sty):
            fill_m = re.search(r"\bfill\s*:\s*([^;]+)", body, flags=re.IGNORECASE)
            if not fill_m:
                continue
            fill_val = fill_m.group(1).strip()
            for sel in selector.split(","):
                sel = sel.strip()
                # solo selectores de clase simples (.clase)
                cls_m = re.match(r"\.([\w-]+)\s*$", sel)
                if cls_m:
                    mapping[cls_m.group(1)] = fill_val
    return mapping


_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _matmul(m1: tuple, m2: tuple) -> tuple:
    """Composición de transforms affine 2D. m_result(p) = m1(m2(p))."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(t_str: str) -> tuple:
    """Convierte un atributo transform='translate(x,y) scale(s) ...' en matriz affine.

    Maneja translate, scale, rotate, matrix, skewX, skewY. Operaciones
    desconocidas se ignoran (loguean warning). Devuelve la identidad si t_str
    es vacío o no parseable.
    """
    if not t_str:
        return _IDENTITY_MATRIX
    result = _IDENTITY_MATRIX
    for op, args_str in re.findall(r"([a-zA-Z]+)\s*\(\s*([^)]*)\)", t_str):
        try:
            args = [float(x) for x in re.split(r"[\s,]+", args_str.strip()) if x]
        except ValueError:
            continue
        op_lower = op.lower()
        if op_lower == "translate":
            tx = args[0] if args else 0
            ty = args[1] if len(args) > 1 else 0
            m = (1, 0, 0, 1, tx, ty)
        elif op_lower == "scale":
            sx = args[0] if args else 1
            sy = args[1] if len(args) > 1 else sx
            m = (sx, 0, 0, sy, 0, 0)
        elif op_lower == "matrix":
            if len(args) != 6:
                continue
            m = tuple(args)
        elif op_lower == "rotate":
            if not args:
                continue
            theta = math.radians(args[0])
            cs, sn = math.cos(theta), math.sin(theta)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                m = _matmul(
                    _matmul((1, 0, 0, 1, cx, cy), (cs, sn, -sn, cs, 0, 0)),
                    (1, 0, 0, 1, -cx, -cy),
                )
            else:
                m = (cs, sn, -sn, cs, 0, 0)
        elif op_lower == "skewx":
            if not args:
                continue
            t = math.tan(math.radians(args[0]))
            m = (1, 0, t, 1, 0, 0)
        elif op_lower == "skewy":
            if not args:
                continue
            t = math.tan(math.radians(args[0]))
            m = (1, t, 0, 1, 0, 0)
        else:
            log.warning("parse_svg: transform '%s' no soportado, ignorado", op)
            continue
        result = _matmul(result, m)
    return result


# Aproximación cúbica Bezier de un círculo/elipse. Constante de Kirchhoff.
_KAPPA = 0.5522847498307933


def _primitive_to_path_d(elem) -> tuple[str, bool]:
    """Convierte una primitiva SVG a (d_string, es_cerrado).

    Devuelve ('', False) si no se reconoce el tipo o le faltan atributos.
    """
    tag = _ns(elem.tag)
    g = elem.get

    def _num(k, default=0.0):
        v, _ = _parse_length(g(k, "") or str(default))
        return v

    if tag == "path":
        d = g("d", "") or ""
        return d.strip(), d.strip().upper().rstrip().endswith("Z")
    if tag == "rect":
        x, y = _num("x"), _num("y")
        w, h = _num("width"), _num("height")
        if w <= 0 or h <= 0:
            return "", False
        return f"M{x},{y} L{x + w},{y} L{x + w},{y + h} L{x},{y + h} Z", True
    if tag == "circle":
        cx, cy = _num("cx"), _num("cy")
        r = _num("r")
        if r <= 0:
            return "", False
        k = _KAPPA * r
        d = (
            f"M{cx - r},{cy} "
            f"C{cx - r},{cy - k} {cx - k},{cy - r} {cx},{cy - r} "
            f"C{cx + k},{cy - r} {cx + r},{cy - k} {cx + r},{cy} "
            f"C{cx + r},{cy + k} {cx + k},{cy + r} {cx},{cy + r} "
            f"C{cx - k},{cy + r} {cx - r},{cy + k} {cx - r},{cy} Z"
        )
        return d, True
    if tag == "ellipse":
        cx, cy = _num("cx"), _num("cy")
        rx, ry = _num("rx"), _num("ry")
        if rx <= 0 or ry <= 0:
            return "", False
        kx, ky = _KAPPA * rx, _KAPPA * ry
        d = (
            f"M{cx - rx},{cy} "
            f"C{cx - rx},{cy - ky} {cx - kx},{cy - ry} {cx},{cy - ry} "
            f"C{cx + kx},{cy - ry} {cx + rx},{cy - ky} {cx + rx},{cy} "
            f"C{cx + rx},{cy + ky} {cx + kx},{cy + ry} {cx},{cy + ry} "
            f"C{cx - kx},{cy + ry} {cx - rx},{cy + ky} {cx - rx},{cy} Z"
        )
        return d, True
    if tag in ("polygon", "polyline"):
        pts_str = g("points", "") or ""
        nums = [float(t) for t in re.split(r"[\s,]+", pts_str.strip()) if t]
        if len(nums) < 4 or len(nums) % 2 != 0:
            return "", False
        pairs = [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
        head = f"M{pairs[0][0]},{pairs[0][1]} "
        body = " ".join(f"L{x},{y}" for x, y in pairs[1:])
        closed = tag == "polygon"
        return head + body + (" Z" if closed else ""), closed
    if tag == "line":
        x1, y1 = _num("x1"), _num("y1")
        x2, y2 = _num("x2"), _num("y2")
        return f"M{x1},{y1} L{x2},{y2}", False
    return "", False


def _bbox_perim_area(path_obj, matrix: tuple, is_closed: bool, samples: int = 240):
    """Calcula bbox, perímetro y área de un path aplicando matrix.

    Si matrix es identidad, usa los métodos rápidos de svgpathtools. Si no,
    muestrea el path y transforma puntos para obtener métricas correctas.
    """
    a, b, c, d, e, f = matrix
    is_identity = matrix == _IDENTITY_MATRIX

    if is_identity:
        try:
            xmin, xmax, ymin, ymax = path_obj.bbox()
            bbox = {"x": xmin, "y": ymin, "w": xmax - xmin, "h": ymax - ymin}
        except Exception:
            bbox = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
        try:
            perimeter = path_obj.length(error=1e-4)
        except Exception:
            perimeter = 0.0
        if is_closed:
            try:
                pts = [path_obj.point(t / samples) for t in range(samples)]
                xs = [p.real for p in pts]
                ys = [p.imag for p in pts]
                n = len(xs)
                area = abs(sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i]
                               for i in range(n))) / 2.0
            except Exception:
                area = 0.0
        else:
            area = 0.0
        return bbox, perimeter, area

    # Camino con transform: muestrear y transformar puntos
    try:
        raw_pts = [path_obj.point(t / samples) for t in range(samples + 1)]
    except Exception:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}, 0.0, 0.0
    txs = [a * p.real + c * p.imag + e for p in raw_pts]
    tys = [b * p.real + d * p.imag + f for p in raw_pts]
    xmin, xmax = min(txs), max(txs)
    ymin, ymax = min(tys), max(tys)
    bbox = {"x": xmin, "y": ymin, "w": xmax - xmin, "h": ymax - ymin}
    perimeter = sum(
        math.hypot(txs[i + 1] - txs[i], tys[i + 1] - tys[i])
        for i in range(len(txs) - 1)
    )
    if is_closed:
        n = len(txs) - 1   # último punto = primero
        area = abs(sum(txs[i] * tys[(i + 1) % n] - txs[(i + 1) % n] * tys[i]
                       for i in range(n))) / 2.0
    else:
        area = 0.0
    return bbox, perimeter, area


# ─── PARSEO DE SVG ───────────────────────────────────────────────────────────

_SVG_PRIMITIVES = ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line")

_FILLS_BLANCOS = {"#fff", "#ffffff", "white", "rgb(255,255,255)"}


def _es_fill_blanco(fill: str) -> bool:
    return fill.strip().lower().replace(" ", "") in _FILLS_BLANCOS


def _bbox_contenido(interior: dict, exterior: dict, tol: float) -> bool:
    return (exterior["x"] - tol <= interior["x"]
            and exterior["y"] - tol <= interior["y"]
            and exterior["x"] + exterior["w"] + tol >= interior["x"] + interior["w"]
            and exterior["y"] + exterior["h"] + tol >= interior["y"] + interior["h"])


def _marcar_huecos(paths: list[PathInfo]) -> None:
    """Marca es_hueco en piezas con fill blanco que son contadores de letra
    (contenidas en el bbox de una pieza no-blanca) o placa de fondo del
    artboard (contienen a la mayoría de las demás piezas). Los SVG de
    rotulación pintan los huecos con el color del fondo (blanco); una pieza
    blanca aislada (p.ej. letra blanca real) NO se marca.

    IMPORTANTE: piezas con capa nombrada (`base`/`corte`/`luz`) NO se marcan
    aunque sean blancas. El usuario declaró explícitamente su rol en el SVG —
    la heurística de detección de huecos NO debe sobrescribir esa intención.
    Ejemplo: en letras planas, la capa `base` suele ser un rectángulo blanco
    (acrílico transparente) que envuelve todo — sin este bypass, se detectaría
    como placa de fondo y se excluiría del cobro."""
    cerrados = [p for p in paths if p.is_closed]
    if len(cerrados) < 2:
        return
    for p in cerrados:
        if not _es_fill_blanco(p.fill):
            continue
        if p.capa:  # capa nombrada → respetar intención del usuario
            continue
        tol = max(p.bbox["w"], p.bbox["h"]) * 0.02 + 0.5
        contador = any(
            q is not p and not _es_fill_blanco(q.fill)
            and _bbox_contenido(p.bbox, q.bbox, tol)
            for q in cerrados
        )
        if contador:
            p.es_hueco = True
            continue
        otras = [q for q in cerrados if q is not p]
        dentro = sum(1 for q in otras if _bbox_contenido(q.bbox, p.bbox, tol))
        if dentro / len(otras) >= 0.6:
            p.es_hueco = True


# Nombres reservados de capas (convención cotizador SGI):
#   base  → soporte/fondo (acrílico transparente, MDF, alucobond, etc.)
#   corte → piezas planas sin luz
#   luz   → piezas retroiluminadas halo (LEDs perimetrales + distanciadores)
# Match por PALABRA COMPLETA en el id / inkscape:label del <g> — evita falsos
# positivos tipo "basement" o "recorte".
_CAPA_KEYWORDS = {
    "base":  {"base", "fondo", "soporte"},
    "corte": {"corte", "cut"},
    "luz":   {"luz", "halo", "iluminado", "iluminacion", "iluminada", "iluminadas",
              "retro", "retroiluminado", "retroiluminada"},
}

_ACENTOS = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")

_INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


def _detectar_capa(nombre: str) -> str:
    """Devuelve 'base', 'corte', 'luz' o '' según el nombre de capa/grupo.
    Case-insensitive, tolera acentos y separadores (_-. espacio). Match por
    palabra COMPLETA, así 'basement' no dispara 'base'."""
    if not nombre:
        return ""
    normal = nombre.translate(_ACENTOS).lower()
    tokens = re.findall(r"[a-z]+", normal)
    if not tokens:
        return ""
    for capa, palabras in _CAPA_KEYWORDS.items():
        if any(t in palabras for t in tokens):
            return capa
    return ""


def _collect_primitives(elem, class_to_fill: dict, parent_matrix: tuple,
                        parent_class: str = "", parent_capa: str = "",
                        out: list | None = None) -> list:
    """Recorre el XML acumulando transforms y capa heredada. Devuelve lista
    de dicts con {elem, matrix, fill, tag, capa}."""
    if out is None:
        out = []
    # Acumular transform de este elemento
    own_t = _parse_transform(elem.get("transform", ""))
    matrix = _matmul(parent_matrix, own_t)
    tag = _ns(elem.tag)

    # Resolver fill
    own_class = elem.get("class", "") or parent_class
    own_fill  = elem.get("fill", "")
    if not own_fill:
        # buscar fill en style="fill:..."
        style = elem.get("style", "") or ""
        m = re.search(r"\bfill\s*:\s*([^;]+)", style)
        if m:
            own_fill = m.group(1).strip()
    if not own_fill and own_class:
        # resolver vía CSS class (puede ser una de varias)
        for cls in own_class.split():
            if cls in class_to_fill:
                own_fill = class_to_fill[cls]
                break

    # Resolver capa: si este elemento (típicamente un <g>) declara id/label
    # que matchea capa reservada, se convierte en la capa efectiva para todos
    # sus descendientes. Un hijo con su propio id de capa lo sobrescribe.
    capa = parent_capa
    if tag == "g":
        nombre_grupo = elem.get("id", "") or elem.get(_INKSCAPE_LABEL, "")
        c = _detectar_capa(nombre_grupo)
        if c:
            capa = c

    if tag in _SVG_PRIMITIVES:
        out.append({"elem": elem, "matrix": matrix, "fill": own_fill,
                    "tag": tag, "capa": capa})

    # Recursar en hijos
    for ch in elem:
        if _ns(ch.tag) in ("defs", "style", "title", "desc", "metadata"):
            continue
        _collect_primitives(ch, class_to_fill, matrix, own_class, capa, out)
    return out


def parse_svg(svg_bytes: bytes) -> SVGData:
    """Parsea un SVG arbitrario y devuelve piezas con geometría real.

    El universo del programa es objetos vectoriales 2D, no solo letras. Esta
    función trata por igual primitivas (<rect>, <circle>, <ellipse>,
    <polygon>, <polyline>, <line>) y <path>. Aplica transforms heredados de
    <g> y resuelve fills declarados por CSS class en <style>.
    """
    svg_text = svg_bytes.decode("utf-8", errors="replace")

    # 1. Parse XML
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        log.warning("parse_svg: XML inválido", exc_info=True)
        return SVGData(paths=[], viewbox_w=500.0, viewbox_h=500.0, svg_unit="px")

    # 2. viewBox + unidad real
    vb_w, vb_h, unit, factor_to_cm = _parse_viewbox(root)

    # 3. Resolver fills declarados en <style>
    class_to_fill = _parse_style_classes(svg_text)

    # 4. Recorrer el árbol recogiendo primitivas con su transform acumulado
    primitivas = _collect_primitives(root, class_to_fill, _IDENTITY_MATRIX)

    # 5. Por cada primitiva: construir d, parsear, aplicar transform, medir
    path_infos: list[PathInfo] = []
    for i, info in enumerate(primitivas):
        d, is_closed = _primitive_to_path_d(info["elem"])
        if not d:
            continue
        try:
            path_obj = parse_path(d)
        except Exception:
            log.warning("parse_svg: no se pudo parsear d='%s...'", d[:40], exc_info=True)
            continue
        if not path_obj:
            continue

        bbox, perimeter, area = _bbox_perim_area(path_obj, info["matrix"], is_closed)

        orig_id = info["elem"].get("id", f"path_{i}")
        path_infos.append(PathInfo(
            id=orig_id,
            perimeter_px=perimeter,
            area_px=area,
            bbox=bbox,
            is_closed=is_closed,
            svg_id=orig_id,
            fill=info["fill"],
            capa=info.get("capa", ""),
        ))

    _marcar_huecos(path_infos)

    # 6. Ordenar por X y renombrar a "Pieza N" — el universo son piezas, no letras
    path_infos.sort(key=lambda p: p.bbox["x"])
    for i, p in enumerate(path_infos):
        p.id = f"Pieza {i + 1}"

    # La pieza más alta para escalar excluye huecos: la placa de fondo blanca
    # no debe capturar la altura que el usuario captura ("la letra mide X cm")
    reales = [p for p in path_infos if p.is_closed and not p.es_hueco]
    max_h_px = max((p.bbox["h"] for p in (reales or path_infos)), default=0.0)

    # 7. Calcular ancho real del artboard en cm (si la unidad lo permite)
    artboard_w_cm = vb_w * factor_to_cm if factor_to_cm > 0 else 0.0

    # 8. Resumen de capas detectadas (para UI y validación de "tipo de anuncio")
    capas_detectadas = {"base": 0, "corte": 0, "luz": 0}
    for p in path_infos:
        if p.capa in capas_detectadas:
            capas_detectadas[p.capa] += 1

    return SVGData(
        paths=path_infos,
        viewbox_w=vb_w,
        viewbox_h=vb_h,
        svg_unit=unit,
        max_pieza_height_px=max_h_px,
        artboard_w_cm=artboard_w_cm,
        capas_detectadas=capas_detectadas,
    )


_PT_TO_CM = 2.54 / 72.0   # 1 punto tipográfico = 0.035278 cm


def apply_scale(svg_data: SVGData, real_width_cm: float,
                altura_cm: float = 0.0) -> SVGData:
    """
    Aplica escala.
    Prioridad:
      1. altura_cm > 0  → factor desde la letra más alta (usuario sabe la medida real)
      2. artboard_w_cm > 0 (Illustrator) → factor = (real_width / artboard) * PT_TO_CM
      3. fallback → real_width / viewbox_w
    """
    if altura_cm > 0 and svg_data.max_letter_height_px > 0:
        svg_data.scale_factor = altura_cm / svg_data.max_letter_height_px
    elif svg_data.artboard_w_cm > 0:
        # SVG de Illustrator: el viewBox está en puntos tipográficos.
        # Escalar relativo al artboard real para obtener cm exactos.
        svg_data.scale_factor = (real_width_cm / svg_data.artboard_w_cm) * _PT_TO_CM
    elif svg_data.viewbox_w > 0:
        svg_data.scale_factor = real_width_cm / svg_data.viewbox_w
    else:
        svg_data.scale_factor = 1.0

    for p in svg_data.paths:
        p.perimeter_cm = p.perimeter_px * svg_data.scale_factor
        p.area_cm2     = p.area_px     * (svg_data.scale_factor ** 2)

    return svg_data


# ─── CÁLCULO DE LÁMINAS ──────────────────────────────────────────────────────

def laminas_necesarias(area_cm2: float, mat_id: str) -> int:
    lam = LAMINAS[mat_id]
    area_lamina = lam["ancho_cm"] * lam["alto_cm"]
    return math.ceil(area_cm2 / area_lamina)


def precio_cm2(mat: dict) -> float:
    """Precio proporcional por cm² = precio_lámina / (ancho × alto)."""
    area = mat.get("ancho_cm", 122) * mat.get("alto_cm", 244)
    return mat.get("precio", 0) / area if area > 0 else 0.0


# ─── COTIZACIÓN LETRAS 3D ────────────────────────────────────────────────────

# Separación entre módulos en la corrida perimetral de letras halo (retroiluminadas).
# Un módulo cada ~15 cm sobre el perímetro da un resplandor uniforme contra la pared.
_ESPACIADO_HALO_CM = 15.0


def cotizar_letras(
    svg_data: SVGData,
    real_width_cm: float,
    altura_letra_cm: float,
    uso: str = "exterior",
    tipo_cara: str = "auto",
    tipo_cercha: str = "auto",
    cercha_cm: float = 0.0,
    espaciado_led_cm: float = 6.0,
    margen_ganancia: float = 0.35,
    tipo_construccion: str = "cajon_luz",
    tipo_multiplicador: str = "acrilico_con_luz_std",
    ajuste_pct: float = 0.0,
    vinil_cercha_id: str = "",
    silvatrim_id: str = "auto",
    led_id: str = "auto",
) -> QuoteResult:

    # Si el usuario conoce la altura, escalar desde ella (ignora márgenes del artboard).
    # Si no, escalar desde el ancho y auto-detectar altura como la pieza más alta.
    if altura_letra_cm > 0:
        svg_data = apply_scale(svg_data, real_width_cm, altura_cm=altura_letra_cm)
    else:
        svg_data = apply_scale(svg_data, real_width_cm)
        reales = [p for p in svg_data.paths if not p.es_hueco] or svg_data.paths
        if reales:
            max_h_px = max(p.bbox["h"] for p in reales)
            altura_letra_cm = max_h_px * svg_data.scale_factor
        if altura_letra_cm <= 0:
            altura_letra_cm = 15.0

    # Filtrar solo paths cerrados con área significativa; los huecos (contadores
    # de letra / placas de fondo pintados de blanco) no se fabrican ni se cobran
    letras = [
        p for p in svg_data.paths
        if p.is_closed and not p.es_hueco and p.area_cm2 > 1.0
    ]
    n_huecos = sum(1 for p in svg_data.paths if p.is_closed and p.es_hueco)
    if not letras:
        letras = svg_data.paths  # fallback: usar todos

    sf = svg_data.scale_factor
    # Cara: usamos bounding box (alto × ancho) por pieza, como se corta en producción real
    area_cara_total   = sum(
        (p.bbox["h"] * sf) * (p.bbox["w"] * sf) for p in letras
    )
    perimetro_total   = sum(p.perimeter_cm for p in letras)

    # Cercha — rango oficial Signalux según la altura máxima del proyecto.
    # La cercha sigue siendo GLOBAL (un solo perfil estructural para todas
    # las piezas) — lo que cambia en Fase D es el material CARA, que ahora
    # se elige por pieza individual.
    rango_cercha = cercha_rango_cm(altura_letra_cm)
    if cercha_cm <= 0:
        cercha_cm = rango_cercha["recomendado"]

    area_cercha_total = perimetro_total * cercha_cm

    config = TIPOS_CONSTRUCCION.get(tipo_construccion, TIPOS_CONSTRUCCION["cajon_luz"])

    # ── CARA — material por pieza individual ─────────────────────────────────
    # Fase D: cuando tipo_cara == "auto", cada pieza recibe el material
    # apropiado para su PROPIA altura, no la altura máxima del proyecto.
    # Un anuncio con placa de 38 cm + texto de 2 cm ya no se cobra todo
    # con el material más caro: cada pieza paga su material adecuado.
    # Si el usuario fija un material específico (no auto), se aplica a
    # todas las piezas (comportamiento legacy).
    cara_por_pieza: list[tuple] = []  # (mat_id, area_cm2, costo) por pieza
    if config["cara"] == "ninguna":
        cara_por_pieza = [(None, (p.bbox["h"] * sf) * (p.bbox["w"] * sf), 0.0)
                          for p in letras]
    else:
        for p in letras:
            alto_pz  = p.bbox["h"] * sf
            ancho_pz = p.bbox["w"] * sf
            area_pz  = alto_pz * ancho_pz
            if tipo_cara != "auto":
                mat_id = tipo_cara
            elif config["cara"] == "aluminio":
                mat_id = material_cercha(alto_pz)
            else:  # acrilico
                mat_id = material_cara(alto_pz)
            costo_pz = area_pz * precio_cm2(LAMINAS[mat_id])
            cara_por_pieza.append((mat_id, area_pz, costo_pz))

    # Agregaciones por material
    area_por_mat: dict[str, float]  = {}
    costo_por_mat: dict[str, float] = {}
    for mat_id, area, costo in cara_por_pieza:
        if mat_id is None:
            continue
        area_por_mat[mat_id]  = area_por_mat.get(mat_id, 0.0) + area
        costo_por_mat[mat_id] = costo_por_mat.get(mat_id, 0.0) + costo

    c_cara = round(sum(costo_por_mat.values()), 2)

    # Material representativo y láminas (para QuoteResult.material_cara y .laminas_cara)
    if not area_por_mat:
        mat_cara_id = None
        mat_cara    = {"nombre": "Sin cara frontal", "precio": 0,
                       "ancho_cm": 122, "alto_cm": 244}
        lam_cara    = 0
    else:
        primary_mat_id = max(area_por_mat, key=lambda k: area_por_mat[k])
        mat_cara_id    = primary_mat_id
        mat_cara_base  = LAMINAS[primary_mat_id]
        if len(area_por_mat) == 1:
            mat_cara = mat_cara_base
        else:
            # Hay mezcla → nombre indica que ver desglose
            nombres = [LAMINAS[mid]["nombre"] for mid in area_por_mat]
            mat_cara = {**mat_cara_base,
                        "nombre": f"Mixto ({len(area_por_mat)}): {', '.join(nombres)}"}
        lam_cara = sum(laminas_necesarias(a, mid) for mid, a in area_por_mat.items())

    # ── CERCHA ────────────────────────────────────────────────────────────────
    mat_cercha_id = material_cercha(altura_letra_cm) if tipo_cercha == "auto" else tipo_cercha
    mat_cercha    = LAMINAS[mat_cercha_id]
    lam_cercha    = laminas_necesarias(area_cercha_total, mat_cercha_id)
    c_cercha      = round(area_cercha_total * precio_cm2(mat_cercha), 2)

    # ── FONDO PVC ─────────────────────────────────────────────────────────────
    if config["fondo_pvc"]:
        mat_fondo_id = "pvc_6mm" if uso == "exterior" else "pvc_3mm"
        mat_fondo    = LAMINAS[mat_fondo_id]
        lam_fondo    = laminas_necesarias(area_cara_total, mat_fondo_id)
        c_fondo      = round(area_cara_total * precio_cm2(mat_fondo), 2)
    else:
        mat_fondo = {"nombre": "Sin fondo (retroiluminada)", "precio": 0}
        lam_fondo = 0
        c_fondo   = 0.0

    # ── LEDS Y FUENTE ─────────────────────────────────────────────────────────
    # modo_iluminacion "cara" (cajón de luz): los módulos iluminan la cara desde
    # dentro del canal → se distribuyen sobre el ÁREA. Cada módulo con apertura
    # 160° proyecta cobertura ≈ cercha × espaciado × 2, así que
    # modulos_por_letra = ceil(area_letra / cobertura_por_modulo).
    # modo_iluminacion "halo" (retroiluminada): los módulos apuntan a la pared →
    # basta UNA corrida perimetral, modulos_por_letra = ceil(perimetro / espaciado).
    # Mínimo 3 módulos por pieza para garantizar uniformidad en letras chicas.
    modo_ilum = config.get("modo_iluminacion", "cara")
    if config["leds"]:
        led     = None
        if led_id and led_id != "auto":
            led = next((l for l in LEDS_CANAL if l.get("id") == led_id), None)
        if led is None:
            led = led_recomendado(cercha_cm, uso)
        if modo_ilum == "halo":
            modulos = sum(
                max(3, math.ceil(p.perimeter_cm / _ESPACIADO_HALO_CM))
                for p in letras
            )
        else:
            cobertura_modulo = max(1.0, cercha_cm * espaciado_led_cm * 2)
            modulos = sum(
                max(3, math.ceil((p.bbox["h"] * sf) * (p.bbox["w"] * sf) / cobertura_modulo))
                for p in letras
            )
        watts   = modulos * led["watts_modulo"]
        fuente  = fuente_optima(watts, uso)
        c_led   = modulos * led["precio_modulo"]
        # Fuente: costo proporcional a los watts consumidos vs capacidad de la fuente.
        # Mínimo 20% del precio para cubrir el desgaste y la instalación del equipo.
        fraccion_fuente = max(0.20, watts / fuente["watts"]) if fuente["watts"] > 0 else 1.0
        c_fuente = round(fuente["precio"] * fraccion_fuente, 2)
    else:
        modulos  = 0
        led      = {"nombre": "Sin iluminación", "precio_modulo": 0, "watts_modulo": 0,
                    "ip": "—", "lumenes": 0}
        watts    = 0.0
        fuente   = {"nombre": "Sin fuente de poder", "precio": 0}
        c_led    = 0.0
        c_fuente = 0.0

    # ── DISTANCIADORES (retro/halo) ───────────────────────────────────────────
    n_letras_dist = len(letras) if config["distanciadores"] else 0
    c_dist        = n_letras_dist * DISTANCIADORES["precio"]

    # ── PEGAMENTO ─────────────────────────────────────────────────────────────
    # Pegamento se aplica a lo largo del perímetro (cercha-cara + cercha-fondo si aplica)
    if config["cara"] == "ninguna":
        mat_cara_tipo = "pvc" if config["fondo_pvc"] else "aluminio"
    elif mat_cara_id and "acrilico" in mat_cara_id:
        mat_cara_tipo = "acrilico"
    else:
        mat_cara_tipo = "aluminio"
    mat_cercha_tipo = "alucobon" if "alucobon" in mat_cercha_id else "aluminio"
    peg_key   = (mat_cercha_tipo, mat_cara_tipo)
    pegamento = PEGAMENTOS.get(peg_key, PEGAMENTOS.get((mat_cara_tipo, mat_cercha_tipo),
                {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox": 90, "metros_por_envase": 11}))
    # Cordón de pegamento en metros: perímetro total × cantidad de juntas (cara + fondo si aplica)
    juntas    = (1 if config["cara"] != "ninguna" else 0) + (1 if config["fondo_pvc"] else 0)
    metros_peg = perimetro_total / 100 * max(1, juntas)
    # Piso 5% = consumo mínimo realista por cotización (limpieza, descarga inicial, mermas).
    # Antes era 15% — inflaba el costo de letras chicas; cotizaciones medianas/grandes lo superan y no cambian.
    envases   = max(0.05, metros_peg / pegamento.get("metros_por_envase", 11))
    c_peg     = round(envases * pegamento["precio_aprox"], 2)

    # ── SILVATRIM (opcional) ──────────────────────────────────────────────────
    # silvatrim_id: ""=sin silvatrim · "auto"=recomendado por cercha · "<id>"=override
    # El silvatrim remata caras de ACRÍLICO (tapa el canto del canal donde asienta
    # la placa). Caras de aluminio/alupanel van soldadas o dobladas — no lo llevan.
    # En "auto" solo se agrega si la construcción tiene cara de acrílico; un id
    # explícito siempre se respeta (decisión manual del cotizador).
    if silvatrim_id == "auto" and config["cara"] != "acrilico":
        silvatrim_id = ""
    if silvatrim_id == "":
        sv = {}
        metros_sv = 0.0
        c_silvatrim = 0.0
        desglose_sv = ""
    else:
        if silvatrim_id == "auto":
            sv = silvatrim_recomendado(cercha_cm)
        else:
            sv = next((s for s in SILVATRIM if s["id"] == silvatrim_id),
                      silvatrim_recomendado(cercha_cm))
        metros_sv  = round(perimetro_total / 100, 2)   # cm → metros
        c_silvatrim = round(metros_sv * sv["precio_ml"], 2)
        desglose_sv = f"Silvatrim {sv['nombre']} · {metros_sv:.1f} m × ${sv['precio_ml']:.2f}/m"

    # ── VINIL CERCHA ──────────────────────────────────────────────────────────
    vc = next((v for v in VINILOS_CERCHA if v["id"] == vinil_cercha_id), None)
    metros_vc      = round(perimetro_total / 100, 2) if vc else 0.0
    c_vinil_cercha = round(metros_vc * vc["precio_ml"], 2) if vc else 0.0

    # ── TOTALES ───────────────────────────────────────────────────────────────
    subtotal = c_cara + c_cercha + c_fondo + c_led + c_fuente + c_dist + c_peg + c_silvatrim + c_vinil_cercha
    iva      = subtotal * 0.16
    total    = subtotal + iva
    venta    = total / (1 - margen_ganancia)

    # ── DESGLOSE ──────────────────────────────────────────────────────────────
    ppcm2_cercha = precio_cm2(mat_cercha)
    ppcm2_fondo  = precio_cm2(mat_fondo)  if config["fondo_pvc"] else 0.0

    def _fmt_mat(nombre, lam, ppcm2, area):
        return f"{nombre} · {area:.0f} cm² × ${ppcm2:.4f}/cm² ({lam} lám.)"

    desglose = []
    if config["cara"] != "ninguna" and area_por_mat:
        # Una línea por material distinto (Fase D: refleja material por pieza)
        for mat_id, area in area_por_mat.items():
            m_obj  = LAMINAS[mat_id]
            ppcm2  = precio_cm2(m_obj)
            costo  = costo_por_mat[mat_id]
            lams   = laminas_necesarias(area, mat_id)
            n_pzs  = sum(1 for mid, _, _ in cara_por_pieza if mid == mat_id)
            sufijo = f" ({n_pzs} pieza{'s' if n_pzs != 1 else ''})" if len(area_por_mat) > 1 else ""
            desglose.append({
                "concepto": _fmt_mat(m_obj["nombre"], lams, ppcm2, area) + sufijo,
                "costo": round(costo, 2),
            })
    desglose.append({"concepto": _fmt_mat(mat_cercha["nombre"], lam_cercha, ppcm2_cercha, area_cercha_total), "costo": c_cercha})
    if config["fondo_pvc"]:
        desglose.append({"concepto": _fmt_mat(mat_fondo["nombre"], lam_fondo, ppcm2_fondo, area_cara_total), "costo": c_fondo})
    if config["leds"]:
        desglose.append({"concepto": f"{led['nombre']} × {modulos} módulos ({watts:.1f}W)", "costo": c_led})
        fraccion_pct = int(max(0.20, watts / fuente["watts"]) * 100) if fuente["watts"] > 0 else 100
        desglose.append({"concepto": f"{fuente['nombre']} · {fraccion_pct}% de capacidad ({watts:.1f}W/{fuente['watts']}W)", "costo": c_fuente})
    if config["distanciadores"]:
        desglose.append({"concepto": f"{DISTANCIADORES['nombre']} × {n_letras_dist} letras", "costo": c_dist})
    desglose.append({"concepto": f"Pegamento {pegamento['nombre']} · {metros_peg:.1f}m ({envases:.2f} env.)", "costo": c_peg})
    if desglose_sv:
        desglose.append({"concepto": desglose_sv, "costo": c_silvatrim})
    if vc:
        desglose.append({"concepto": f"Vinil cercha {vc['nombre']} · {metros_vc:.1f} m × ${vc['precio_ml']:.2f}/m", "costo": c_vinil_cercha})

    # ── Lógica de cotización (hoja COTIZANDO del Excel) ─────────────────────────
    # precio_letra = altura_real_cm × precio_cm × multiplicador
    precio_cm     = PRECIOS_BASE["precio_cm"]
    multiplicador = PRECIOS_BASE["multiplicadores"].get(tipo_multiplicador, 4.5)

    # ── Fase G: desglose por pieza de TODOS los componentes (no prorrateo
    # falso). Cada pieza ya tiene su costo de cara (cara_por_pieza); aquí
    # añadimos cercha, fondo, leds, fuente, pegamento, dist, extras —
    # cada uno con su share REAL para esa pieza.
    desglose_letras = []
    precio_formula_total = 0.0
    # svg_id_for(p): para cards de UI / plano que usan svg_id como llave estable
    for i, p in enumerate(letras):
        alto_cm    = round(p.bbox["h"] * svg_data.scale_factor, 2)
        ancho_cm   = round(p.bbox["w"] * svg_data.scale_factor, 2)
        area_bbox  = round(alto_cm * ancho_cm, 2)
        perim_pz   = p.perimeter_cm
        tira_neta  = round(perim_pz, 1)
        tira_total = round(perim_pz * 1.10, 1)
        cercha_area_letra = round(tira_neta * cercha_cm, 2)

        pieza_mat_id, _, pieza_costo_cara_raw = cara_por_pieza[i]
        costo_cara_letra   = round(pieza_costo_cara_raw, 2)
        costo_cercha_letra = round(cercha_area_letra * ppcm2_cercha, 2)
        costo_fondo_letra  = round(area_bbox * ppcm2_fondo, 2)

        # Leds por pieza: ceil(perim/espaciado) si lleva luz
        if config["leds"]:
            esp_pz = _ESPACIADO_HALO_CM if modo_ilum == "halo" else espaciado_led_cm
            n_modulos_pz = max(3, math.ceil(perim_pz / esp_pz))
            watts_pz     = n_modulos_pz * led["watts_modulo"]
            costo_leds_pz = round(n_modulos_pz * led["precio_modulo"], 2)
        else:
            n_modulos_pz = 0
            watts_pz     = 0.0
            costo_leds_pz = 0.0

        # Fuente: share por watts. Pegamento/silvatrim/vinil: share por perímetro.
        share_perim = (perim_pz / perimetro_total) if perimetro_total > 0 else 0
        share_watts = (watts_pz / watts) if (config["leds"] and watts > 0) else 0
        costo_fuente_pz   = round(c_fuente   * share_watts, 2) if config["leds"] else 0.0
        costo_peg_pz      = round(c_peg      * share_perim, 2)
        costo_silvatrim_pz = round(c_silvatrim * share_perim, 2)
        costo_vinil_cercha_pz = round(c_vinil_cercha * share_perim, 2) if vc else 0.0
        costo_dist_pz     = round(DISTANCIADORES["precio"], 2) if config["distanciadores"] else 0.0
        costo_extras_pz   = round(costo_silvatrim_pz + costo_vinil_cercha_pz, 2)

        costo_mat_letra = round(costo_cara_letra + costo_cercha_letra + costo_fondo_letra, 2)
        costo_total_pz  = round(costo_cara_letra + costo_cercha_letra + costo_fondo_letra
                                + costo_leds_pz + costo_fuente_pz + costo_dist_pz
                                + costo_peg_pz + costo_extras_pz, 2)

        precio_letra = round(alto_cm * precio_cm * multiplicador, 2)
        precio_formula_total += precio_letra

        margen_pct = round((precio_letra - costo_total_pz) / precio_letra * 100, 1) if precio_letra > 0 else 0.0

        pieza_mat_nombre = LAMINAS[pieza_mat_id]["nombre"] if pieza_mat_id else "Sin cara"
        desglose_letras.append({
            "id":               p.id,
            "svg_id":           getattr(p, "svg_id", "") or p.id,
            "alto_cm":          alto_cm,
            "ancho_cm":         ancho_cm,
            "area_bbox_cm2":    area_bbox,
            "perimetro_cm":     tira_neta,
            "area_cm2":         round(p.area_cm2, 1),
            "cercha_neta_cm":   tira_neta,
            "cercha_total_cm":  tira_total,
            "cercha_area_cm2":  cercha_area_letra,
            "cercha_altura_cm": round(cercha_cm, 1),
            "material_cara_id":     pieza_mat_id or "",
            "material_cara_nombre": pieza_mat_nombre,
            # Receta — qué lleva ESTA pieza
            "lleva_cercha":     cercha_cm > 0,
            "lleva_luz":        config["leds"] and n_modulos_pz > 0,
            "lleva_fondo":      config["fondo_pvc"],
            "lleva_distanciadores": config["distanciadores"],
            "n_modulos_led":    n_modulos_pz,
            "watts":            round(watts_pz, 2),
            # Costos por componente (suma = costo_total_pieza)
            "costo_cara":           costo_cara_letra,
            "costo_cercha":         costo_cercha_letra,
            "costo_fondo":          costo_fondo_letra,
            "costo_leds":           costo_leds_pz,
            "costo_fuente":         costo_fuente_pz,
            "costo_pegamento":      costo_peg_pz,
            "costo_distanciadores": costo_dist_pz,
            "costo_extras":         costo_extras_pz,
            "costo_mat":            costo_mat_letra,   # solo cara+cercha+fondo (compat anterior)
            "costo_total":          costo_total_pz,    # NUEVO: costo real total per pieza
            "precio_letra":         precio_letra,
            "margen_real_pct":      margen_pct,
        })

    precio_formula_total   = round(precio_formula_total, 2)
    precio_formula_ajustado = round(precio_formula_total * (1 + ajuste_pct / 100), 2)
    precio_venta_costo      = round(total / (1 - margen_ganancia), 2)  # piso por costo

    # ── Fase G: desglose de costos por componente (totales globales reales) ─
    desglose_costos_componentes = {
        "cara":           round(c_cara, 2),
        "cercha":         round(c_cercha, 2),
        "fondo":          round(c_fondo, 2),
        "leds":           round(c_led, 2),
        "fuente":         round(c_fuente, 2),
        "pegamento":      round(c_peg, 2),
        "distanciadores": round(c_dist, 2),
        "silvatrim":      round(c_silvatrim, 2),
        "vinil_cercha":   round(c_vinil_cercha, 2),
        "total_material": round(subtotal, 2),
    }

    # ── Fase H: warnings de inconsistencia ──────────────────────────────────
    warnings: list[str] = []
    if "con_luz" in tipo_multiplicador and not config["leds"]:
        warnings.append(
            f"Multiplicador '{tipo_multiplicador}' (×{multiplicador}) implica iluminación, "
            f"pero el tipo de construcción '{tipo_construccion}' NO lleva LEDs. "
            f"Considera cambiar a un multiplicador sin luz para evitar cobrar al cliente por iluminación que no recibe."
        )
    if config["leds"] and modulos == 0:
        warnings.append("El tipo de construcción lleva LEDs pero el cálculo dio 0 módulos. Verifica el espaciado.")
    if cercha_cm <= 0:
        warnings.append("Profundidad de cercha es 0 cm — el costo de cercha se omite. Usa 'Perímetro total' en vez de 'Cercha total'.")
    if n_huecos:
        warnings.append(
            f"{n_huecos} pieza(s) con relleno blanco detectadas como hueco/placa de fondo "
            f"— excluidas del cobro (no se fabrican)."
        )

    return QuoteResult(
        tipo="letras_3d",
        paths_count=len(letras),
        altura_letra_cm=round(altura_letra_cm, 1),
        cercha_min_cm=rango_cercha["min"],
        cercha_max_cm=rango_cercha["max"],
        categoria_letra=rango_cercha["categoria"],
        area_cara_cm2=area_cara_total,
        perimetro_total_cm=perimetro_total,
        cercha_altura_cm=cercha_cm,
        cercha_area_cm2=area_cercha_total,
        material_cara=mat_cara,
        material_cercha=mat_cercha,
        material_fondo=mat_fondo,
        laminas_cara=lam_cara,
        laminas_cercha=lam_cercha,
        laminas_fondo=lam_fondo,
        led=led,
        modulos_led=modulos,
        watts_total=watts,
        fuente=fuente,
        pegamento=pegamento,
        costo_material_cara=c_cara,
        costo_material_cercha=c_cercha,
        costo_material_fondo=c_fondo,
        costo_led=c_led,
        costo_fuente=c_fuente,
        costo_pegamento=c_peg,
        subtotal=subtotal,
        iva=iva,
        total=total,
        precio_venta_sugerido=precio_formula_ajustado,
        precio_venta_costo=precio_venta_costo,
        tipo_multiplicador=tipo_multiplicador,
        multiplicador_valor=multiplicador,
        precio_sin_ajuste=precio_formula_total,
        ajuste_pct=ajuste_pct,
        tipo_construccion=tipo_construccion,
        silvatrim=sv,
        metros_silvatrim=metros_sv,
        costo_silvatrim=c_silvatrim,
        vinil_cercha=vc or {},
        metros_vinil_cercha=metros_vc,
        costo_vinil_cercha=c_vinil_cercha,
        desglose=desglose,
        desglose_letras=desglose_letras,
        desglose_costos_componentes=desglose_costos_componentes,
        warnings=warnings,
    )


# ─── COTIZACIÓN LETRAS PLANAS ────────────────────────────────────────────────

def _bbox_conjunto(piezas, sf) -> tuple[float, float]:
    """Devuelve (ancho_cm, alto_cm) del bbox que envuelve TODAS las piezas
    dadas. Refleja la lámina/pedazo mínimo del que se cortarían asumiendo que
    se acomodan lado a lado (mucho más realista que sumar bboxes individuales,
    que ignora que los recortes entre piezas casi nunca se reutilizan)."""
    if not piezas or sf <= 0:
        return (0.0, 0.0)
    xs_min = min(p.bbox["x"] for p in piezas)
    ys_min = min(p.bbox["y"] for p in piezas)
    xs_max = max(p.bbox["x"] + p.bbox["w"] for p in piezas)
    ys_max = max(p.bbox["y"] + p.bbox["h"] for p in piezas)
    return ((xs_max - xs_min) * sf, (ys_max - ys_min) * sf)


def _area_material_cm2(piezas, sf: float, modo: str) -> float:
    """Área total del material que se cobra según el modo:
      · 'areas' (default) → bbox conjunto (una placa envolvente).
      · 'pieza'           → suma de bboxes individuales (una placa por pieza)."""
    if not piezas or sf <= 0:
        return 0.0
    if modo == "pieza":
        return sum((p.bbox["h"] * sf) * (p.bbox["w"] * sf) for p in piezas)
    w, h = _bbox_conjunto(piezas, sf)
    return w * h


def cotizar_planas(
    svg_data: SVGData,
    real_width_cm: float,
    material_id: str = "acrilico_3mm",
    margen_ganancia: float = 0.35,
    tipo_multiplicador: str = "aluminio_sin_luz",
    ajuste_pct: float = 0.0,
    # ── Extensión: 3 capas nombradas en el SVG (base/corte/luz) ──────────
    real_height_cm: float = 0.0,
    incluye_base: bool = False,
    base_material_id: str = "",
    incluye_luz: bool = False,
    luz_material_id: str = "",
    luz_led_id: str = "auto",
    luz_cercha_cm: float = 0.0,               # 0 = sin cercha (default)
    luz_juegos_dist_por_pieza: int = 1,
    luz_tipo_multiplicador: str = "aluminio_con_luz",
    desperdicio_pct: float = 15.0,
    modo_corte: str = "areas",   # "areas" (default, bbox conjunto) | "pieza" (suma bboxes)
) -> QuoteResult:
    """
    Cotización de letras planas con soporte de 3 capas nombradas en el SVG:
      · base   → soporte/fondo (opcional; forma cualquiera)
      · corte  → piezas planas sin luz
      · luz    → piezas retroiluminadas halo (LEDs + distanciadores)

    Sin capas nombradas → todas las piezas se tratan como 'corte'.
    Los flags `incluye_base` / `incluye_luz` permiten activar el cobro incluso
    cuando el SVG no trae la capa correspondiente (útil con SVG sencillos).

    Modos de cobro del material (parametro `modo_corte`):
      · "areas"  (default) → bbox CONJUNTO de las piezas × precio × desperdicio.
                             Refleja que se acomodan juntas al cortar.
      · "pieza"           → suma de bboxes individuales × precio × desperdicio.
                             Aplica cuando cada pieza va en material distinto o
                             no se pueden acomodar juntas. Da un total mayor.
    """
    svg_data = apply_scale(svg_data, real_width_cm)

    # Si el SVG trae capa 'base', RE-ANCLAR la escala al bbox de la base.
    # Motivo: `real_width_cm` que da el usuario es el ancho REAL DE LA BASE,
    # no del viewBox/artboard del SVG. Sin este ajuste, cuando el diseño
    # tiene padding o el artboard es mayor que la base, todo el sistema
    # queda 2-3× más grande (la base ficticia mide más que la real).
    piezas_base_raw = [
        p for p in svg_data.paths
        if p.capa == "base" and p.is_closed and not p.es_hueco
    ]
    if piezas_base_raw and real_width_cm > 0:
        xs_min = min(p.bbox["x"] for p in piezas_base_raw)
        xs_max = max(p.bbox["x"] + p.bbox["w"] for p in piezas_base_raw)
        base_w_svg = xs_max - xs_min
        if base_w_svg > 0:
            nuevo_sf = real_width_cm / base_w_svg
            svg_data.scale_factor = nuevo_sf
            for p in svg_data.paths:
                p.perimeter_cm = p.perimeter_px * nuevo_sf
                p.area_cm2     = p.area_px     * (nuevo_sf ** 2)

    # Piezas válidas: cerradas, no huecos, área > 0.5 cm²
    piezas = [
        p for p in svg_data.paths
        if p.is_closed and not p.es_hueco and p.area_cm2 > 0.5
    ]
    n_huecos = sum(1 for p in svg_data.paths if p.is_closed and p.es_hueco)
    if not piezas:
        piezas = svg_data.paths

    # ── Separación por capa nombrada del SVG ─────────────────────────────
    piezas_base  = [p for p in piezas if p.capa == "base"]
    piezas_luz   = [p for p in piezas if p.capa == "luz"]
    piezas_corte = [p for p in piezas if p.capa in ("", "corte")]

    # Si el usuario NO activa "incluye luz" pero el SVG trae capa luz,
    # esas piezas se cotizan como corte plano (no se pierden). Da control
    # al operador: puede ver el precio "sin iluminación" activando/desactivando.
    if not incluye_luz and piezas_luz:
        piezas_corte.extend(piezas_luz)
        piezas_luz = []

    sf = svg_data.scale_factor
    factor_desperdicio = 1.0 + max(0.0, desperdicio_pct) / 100.0

    modo_corte = "pieza" if str(modo_corte).lower() == "pieza" else "areas"

    # ── MATERIAL DE CORTE (bbox conjunto o suma-por-pieza según modo_corte) ─
    if material_id not in LAMINAS:
        material_id = "acrilico_3mm"
    mat_corte    = LAMINAS[material_id]
    ppcm2_corte  = precio_cm2(mat_corte)

    corte_w_cm, corte_h_cm = _bbox_conjunto(piezas_corte, sf)   # bbox informativo
    corte_area_cm2 = _area_material_cm2(piezas_corte, sf, modo_corte)
    c_corte = round(corte_area_cm2 * ppcm2_corte * factor_desperdicio, 2)
    lam_corte = laminas_necesarias(corte_area_cm2, material_id) if corte_area_cm2 > 0 else 0

    # ── MATERIAL BASE (opcional) ─────────────────────────────────────────
    # Prioridad: 1) capa "base" del SVG · 2) incluye_base=True + medidas · 3) nada
    base_w_cm = base_h_cm = 0.0
    base_area_cm2 = 0.0
    c_base = 0.0
    mat_base = None
    base_fuente = ""   # "svg" | "manual" | ""
    _def_base = "acrilico_3mm_transparente" if "acrilico_3mm_transparente" in LAMINAS else material_id
    if piezas_base:
        base_w_cm, base_h_cm = _bbox_conjunto(piezas_base, sf)
        base_area_cm2 = _area_material_cm2(piezas_base, sf, modo_corte)
        mid = base_material_id or _def_base
        if mid not in LAMINAS:
            mid = _def_base
        mat_base = LAMINAS[mid]
        c_base = round(base_area_cm2 * precio_cm2(mat_base) * factor_desperdicio, 2)
        base_material_id = mid
        base_fuente = "svg"
    elif incluye_base:
        base_w_cm = real_width_cm
        if real_height_cm > 0:
            base_h_cm = real_height_cm
        else:
            # inferir alto del bbox conjunto de todas las piezas
            _w_todo, h_todo = _bbox_conjunto(piezas, sf)
            base_h_cm = h_todo if h_todo > 0 else corte_h_cm
        base_area_cm2 = base_w_cm * base_h_cm   # placa virtual: SIEMPRE una sola
        mid = base_material_id or _def_base
        if mid not in LAMINAS:
            mid = _def_base
        mat_base = LAMINAS[mid]
        c_base = round(base_area_cm2 * precio_cm2(mat_base) * factor_desperdicio, 2)
        base_material_id = mid
        base_fuente = "manual"

    # ── MATERIAL LUZ + LEDs + FUENTE + DISTANCIADORES ────────────────────
    luz_w_cm = luz_h_cm = 0.0
    luz_area_cm2 = 0.0
    c_luz_mat = c_luz_leds = c_luz_fuente = c_luz_dist = 0.0
    modulos_luz = 0
    watts_luz   = 0.0
    led_luz    = {"nombre": "Sin iluminación", "precio_modulo": 0,
                  "watts_modulo": 0, "ip": "—", "lumenes": 0}
    fuente_luz = {"nombre": "Sin fuente", "precio": 0}
    mat_luz    = None
    if piezas_luz:
        # Material: si no se especifica, usa el mismo del corte
        lmid = luz_material_id or material_id
        if lmid not in LAMINAS:
            lmid = material_id
        mat_luz = LAMINAS[lmid]
        luz_material_id = lmid
        luz_w_cm, luz_h_cm = _bbox_conjunto(piezas_luz, sf)
        luz_area_cm2 = _area_material_cm2(piezas_luz, sf, modo_corte)
        c_luz_mat = round(luz_area_cm2 * precio_cm2(mat_luz) * factor_desperdicio, 2)

        # LEDs modo halo: 1 corrida por perímetro, mín 3 por pieza
        led_sel = None
        if luz_led_id and luz_led_id != "auto":
            led_sel = next((l for l in LEDS_CANAL if l.get("id") == luz_led_id), None)
        if led_sel is None:
            # Sin cercha declarada → tamaño de canal "shallow" (~3 cm equivalente)
            led_sel = led_recomendado(max(luz_cercha_cm, 3.0), "interior")
        led_luz = led_sel
        modulos_luz = sum(
            max(3, math.ceil(p.perimeter_cm / _ESPACIADO_HALO_CM))
            for p in piezas_luz
        )
        watts_luz  = modulos_luz * led_luz["watts_modulo"]
        c_luz_leds = round(modulos_luz * led_luz["precio_modulo"], 2)

        fuente_luz = fuente_optima(watts_luz, "interior")
        frac_f = max(0.20, watts_luz / fuente_luz["watts"]) if fuente_luz.get("watts", 0) > 0 else 1.0
        c_luz_fuente = round(fuente_luz["precio"] * frac_f, 2)

        c_luz_dist = round(
            len(piezas_luz) * max(1, luz_juegos_dist_por_pieza) * DISTANCIADORES["precio"],
            2,
        )

    # ── SUBTOTAL / IVA / TOTAL ───────────────────────────────────────────
    subtotal = c_corte + c_base + c_luz_mat + c_luz_leds + c_luz_fuente + c_luz_dist
    iva      = subtotal * 0.16
    total    = subtotal + iva

    # ── PRECIO POR PIEZA (fórmula altura × precio_cm × multiplicador) ────
    precio_cm  = PRECIOS_BASE["precio_cm"]
    mult_corte = PRECIOS_BASE["multiplicadores"].get(tipo_multiplicador, 2.0)
    mult_luz   = PRECIOS_BASE["multiplicadores"].get(luz_tipo_multiplicador, 2.5)

    perimetro_total     = sum(p.perimeter_cm for p in piezas)

    desglose_letras = []
    precio_formula_total = 0.0
    for p in piezas:
        alto_cm   = round(p.bbox["h"] * sf, 2)
        ancho_cm  = round(p.bbox["w"] * sf, 2)
        area_bbox = round(alto_cm * ancho_cm, 2)

        if p in piezas_luz:
            mat_id_pz  = luz_material_id or material_id
            mat_nom_pz = (mat_luz or mat_corte)["nombre"]
            mult_pz    = mult_luz
            capa_pz    = "luz"
            ppcm2_pz   = precio_cm2(mat_luz or mat_corte)
            n_mod_pz   = max(3, math.ceil(p.perimeter_cm / _ESPACIADO_HALO_CM))
            watts_pz   = n_mod_pz * (led_luz.get("watts_modulo") or 0)
        elif p in piezas_base:
            mat_id_pz  = base_material_id or material_id
            mat_nom_pz = (mat_base or mat_corte)["nombre"]
            mult_pz    = mult_corte
            capa_pz    = "base"
            ppcm2_pz   = precio_cm2(mat_base or mat_corte)
            n_mod_pz   = 0
            watts_pz   = 0.0
        else:
            mat_id_pz  = material_id
            mat_nom_pz = mat_corte["nombre"]
            mult_pz    = mult_corte
            capa_pz    = "corte"
            ppcm2_pz   = ppcm2_corte
            n_mod_pz   = 0
            watts_pz   = 0.0

        # costo_mat_pz aquí es el costo de "esta pieza sola" (bbox individual).
        # Solo se cobra al total cuando modo_corte == 'pieza'. En modo 'areas'
        # queda como referencia informativa — el total del material lo
        # dominan c_corte/c_base/c_luz_mat calculados por bbox conjunto.
        costo_mat_pz = round(area_bbox * ppcm2_pz * factor_desperdicio, 2)
        precio_pz    = round(alto_cm * precio_cm * mult_pz, 2)
        precio_formula_total += precio_pz
        margen_pct = round((precio_pz - costo_mat_pz) / precio_pz * 100, 1) if precio_pz > 0 else 0.0

        desglose_letras.append({
            "id":               p.id,
            "svg_id":           getattr(p, "svg_id", "") or p.id,
            "capa":             capa_pz,
            "alto_cm":          alto_cm,
            "ancho_cm":         ancho_cm,
            "area_bbox_cm2":    area_bbox,
            "perimetro_cm":     round(p.perimeter_cm, 1),
            "area_cm2":         round(p.area_cm2, 1),
            "cercha_neta_cm":   0,
            "cercha_total_cm":  0,
            "cercha_area_cm2":  0,
            "cercha_altura_cm": luz_cercha_cm if capa_pz == "luz" else 0,
            "material_cara_id":     mat_id_pz,
            "material_cara_nombre": mat_nom_pz,
            "lleva_cercha":         capa_pz == "luz" and luz_cercha_cm > 0,
            "lleva_luz":            capa_pz == "luz",
            "lleva_fondo":          False,
            "lleva_distanciadores": capa_pz == "luz",
            "n_modulos_led":        n_mod_pz,
            "watts":                round(watts_pz, 1),
            "costo_cara":           costo_mat_pz,
            "costo_cercha":         0.0,
            "costo_fondo":          0.0,
            "costo_leds":           0.0,   # el total se factura en c_luz_leds (evita doble cobro)
            "costo_fuente":         0.0,
            "costo_pegamento":      0.0,
            "costo_distanciadores": 0.0,
            "costo_extras":         0.0,
            "costo_mat":            costo_mat_pz,
            "costo_total":          costo_mat_pz,
            # Flag para el frontend: cuando True, `costo_*` es referencia
            # (no forma parte del total cobrado). Solo aplica a planas.
            "costo_es_informativo": modo_corte == "areas",
            "precio_letra":         precio_pz,
            "margen_real_pct":      margen_pct,
        })

    precio_formula_total    = round(precio_formula_total, 2)
    precio_formula_ajustado = round(precio_formula_total * (1 + ajuste_pct / 100), 2)
    precio_venta_costo      = round(total / (1 - margen_ganancia), 2)

    # ── DESGLOSE POR COMPONENTE ──────────────────────────────────────────
    # Info estructurada por bloque para que la UI pinte un panel resumen
    # (Base / Corte / Luz) sin tener que reparsear el desglose humano.
    bloques_planas: dict = {}
    if c_corte > 0 or piezas_corte:
        bloques_planas["corte"] = {
            "activo":      True,
            "n_piezas":    len(piezas_corte),
            "w_cm":        round(corte_w_cm, 1),
            "h_cm":        round(corte_h_cm, 1),
            "area_cm2":    round(corte_area_cm2, 1),
            "material_id": material_id,
            "material":    mat_corte["nombre"],
            "modo":        modo_corte,
            "desperdicio_pct": round(desperdicio_pct, 1),
            "costo":       round(c_corte, 2),
        }
    if c_base > 0:
        bloques_planas["base"] = {
            "activo":      True,
            "n_piezas":    len(piezas_base) if piezas_base else 1,
            "w_cm":        round(base_w_cm, 1),
            "h_cm":        round(base_h_cm, 1),
            "area_cm2":    round(base_area_cm2, 1),
            "material_id": base_material_id,
            "material":    mat_base["nombre"] if mat_base else "",
            "fuente":      base_fuente,   # "svg" | "manual"
            "modo":        modo_corte if piezas_base else "areas",
            "desperdicio_pct": round(desperdicio_pct, 1),
            "costo":       round(c_base, 2),
        }
    if c_luz_mat > 0 or piezas_luz:
        perim_luz_total_cm = sum(p.perimeter_cm for p in piezas_luz)
        bloques_planas["luz"] = {
            "activo":      True,
            "n_piezas":    len(piezas_luz),
            "w_cm":        round(luz_w_cm, 1),
            "h_cm":        round(luz_h_cm, 1),
            "area_cm2":    round(luz_area_cm2, 1),
            "perimetro_total_cm": round(perim_luz_total_cm, 1),
            "metros_lineales":    round(perim_luz_total_cm / 100.0, 2),
            "material_id": luz_material_id,
            "material":    mat_luz["nombre"] if mat_luz else "",
            "modo":        modo_corte,
            "desperdicio_pct": round(desperdicio_pct, 1),
            "cercha_cm":   round(luz_cercha_cm, 1),
            "costo_material": round(c_luz_mat, 2),
            "led": {
                "nombre":       led_luz.get("nombre", ""),
                "id":           led_luz.get("id", ""),
                "modulos":      modulos_luz,
                "watts_por_modulo": led_luz.get("watts_modulo", 0),
                "watts_totales":round(watts_luz, 2),
                "costo":        round(c_luz_leds, 2),
            },
            "fuente": {
                "nombre":       fuente_luz.get("nombre", ""),
                "capacidad_w":  fuente_luz.get("watts", 0),
                "costo":        round(c_luz_fuente, 2),
            },
            "distanciadores": {
                "juegos_por_pieza": max(1, luz_juegos_dist_por_pieza),
                "n_piezas":         len(piezas_luz),
                "total_juegos":     len(piezas_luz) * max(1, luz_juegos_dist_por_pieza),
                "precio_juego":     DISTANCIADORES["precio"],
                "costo":            round(c_luz_dist, 2),
            },
            "costo_total":  round(c_luz_mat + c_luz_leds + c_luz_fuente + c_luz_dist, 2),
        }

    desglose_costos_componentes = {
        "cara":           round(c_corte, 2),
        "base":           round(c_base, 2),
        "luz":            round(c_luz_mat, 2),
        "cercha":         0.0,
        "fondo":          0.0,
        "leds":           round(c_luz_leds, 2),
        "fuente":         round(c_luz_fuente, 2),
        "pegamento":      0.0,
        "distanciadores": round(c_luz_dist, 2),
        "silvatrim":      0.0,
        "vinil_cercha":   0.0,
        "total_material": round(subtotal, 2),
        # Info estructurada para la UI (solo planas)
        "bloques":        bloques_planas,
    }

    # ── DESGLOSE LEGIBLE (renglones humanos para PDF) ────────────────────
    def _dim_txt(w, h, area, n_piezas, modo):
        if modo == "pieza":
            return f"{n_piezas} pieza(s) · {area:.0f} cm² sumados"
        return f"{w:.0f}×{h:.0f} cm ({area:.0f} cm²)"

    desglose_h = []
    if c_corte > 0:
        desglose_h.append({
            "concepto": (f"Corte · {mat_corte['nombre']} · "
                         f"{_dim_txt(corte_w_cm, corte_h_cm, corte_area_cm2, len(piezas_corte), modo_corte)}"
                         f" + {desperdicio_pct:.0f}% desperdicio"),
            "costo": c_corte,
        })
    if c_base > 0:
        n_base = len(piezas_base) if piezas_base else 1
        modo_base = modo_corte if piezas_base else "areas"
        desglose_h.append({
            "concepto": (f"Base · {mat_base['nombre']} · "
                         f"{_dim_txt(base_w_cm, base_h_cm, base_area_cm2, n_base, modo_base)}"
                         f" + {desperdicio_pct:.0f}% desperdicio"),
            "costo": c_base,
        })
    if c_luz_mat > 0:
        desglose_h.append({
            "concepto": (f"Luz (material) · {mat_luz['nombre']} · "
                         f"{_dim_txt(luz_w_cm, luz_h_cm, luz_area_cm2, len(piezas_luz), modo_corte)}"
                         f" + {desperdicio_pct:.0f}% desperdicio"),
            "costo": c_luz_mat,
        })
    if c_luz_leds > 0:
        desglose_h.append({
            "concepto": (f"LEDs {led_luz['nombre']} · {modulos_luz} módulos "
                         f"({watts_luz:.1f} W) para {len(piezas_luz)} pieza(s)"),
            "costo": c_luz_leds,
        })
    if c_luz_fuente > 0:
        desglose_h.append({
            "concepto": f"Fuente {fuente_luz['nombre']} ({watts_luz:.1f} W)",
            "costo": c_luz_fuente,
        })
    if c_luz_dist > 0:
        desglose_h.append({
            "concepto": (f"Distanciadores · {len(piezas_luz)} pieza(s) "
                         f"× {max(1, luz_juegos_dist_por_pieza)} juego(s)"),
            "costo": c_luz_dist,
        })

    # ── WARNINGS ─────────────────────────────────────────────────────────
    warnings: list[str] = []
    if n_huecos:
        warnings.append(
            f"{n_huecos} pieza(s) con relleno blanco detectadas como hueco/placa "
            f"— excluidas del cobro (no se fabrican)."
        )
    if incluye_base and not piezas_base and real_height_cm <= 0:
        warnings.append(
            "Se activó 'incluye base' sin dar el alto real; se infirió del bbox del diseño. "
            "Ingresa el alto real (cm) para mayor precisión."
        )
    orig_luz = sum(1 for p in piezas if p.capa == "luz")
    if orig_luz and not incluye_luz:
        warnings.append(
            f"El SVG trae {orig_luz} pieza(s) en capa 'luz' pero 'incluye iluminación' "
            f"está apagado — se cotizan como corte plano."
        )
    if not piezas_luz and mult_corte > 3.0:
        warnings.append(
            f"Multiplicador ×{mult_corte} es alto para letras planas sin luz (típico 1.5-2.5)."
        )
    if piezas_luz and mult_corte >= mult_luz:
        warnings.append(
            "El multiplicador 'con luz' no es mayor que el 'sin luz' — revisa la configuración."
        )

    lam_base = laminas_necesarias(base_w_cm * base_h_cm, base_material_id) if mat_base else 0

    return QuoteResult(
        tipo="letras_planas",
        tipo_construccion="plana",
        paths_count=len(piezas),
        altura_letra_cm=round(max((p.bbox["h"] * sf for p in piezas), default=0), 1),
        area_cara_cm2=corte_area_cm2,   # "cara" clásico ≡ corte para compatibilidad
        perimetro_total_cm=perimetro_total,
        cercha_altura_cm=luz_cercha_cm,
        cercha_area_cm2=0,
        material_cara=mat_corte,
        material_cercha={"nombre": "N/A", "precio": 0},
        material_fondo=mat_base if mat_base else {"nombre": "N/A", "precio": 0},
        laminas_cara=lam_corte,
        laminas_cercha=0,
        laminas_fondo=lam_base,
        led=led_luz,
        modulos_led=modulos_luz,
        watts_total=watts_luz,
        fuente=fuente_luz,
        pegamento={"nombre": "N/A", "precio_aprox": 0},
        costo_material_cara=c_corte,
        costo_material_cercha=0.0,
        costo_material_fondo=c_base,
        costo_led=c_luz_leds,
        costo_fuente=c_luz_fuente,
        costo_pegamento=0.0,
        subtotal=subtotal,
        iva=iva,
        total=total,
        precio_venta_sugerido=precio_formula_ajustado,
        precio_venta_costo=precio_venta_costo,
        tipo_multiplicador=tipo_multiplicador,
        multiplicador_valor=mult_corte,
        precio_sin_ajuste=precio_formula_total,
        ajuste_pct=ajuste_pct,
        desglose=desglose_h if desglose_h else [{"concepto": "Sin costo", "costo": 0.0}],
        desglose_letras=desglose_letras,
        desglose_costos_componentes=desglose_costos_componentes,
        warnings=warnings,
    )


# ─── COTIZACIÓN CAJA DE LUZ ──────────────────────────────────────────────────

def _find_caja_outline(paths: list, ratio_max: float = 4.5,
                       contain_pct: float = 0.70):
    """Identifica el contorno exterior del anuncio (placa, marco, caja).

    Dos heurísticas combinadas, lo que pase primero:

    1. Path con `perimetro / 2*(w+h) <= ratio_max` (forma cuasi-rectangular,
       incluyendo bordes redondeados). El umbral por defecto es 4.5, lo que
       cubre placas con esquinas redondeadas estándar tipo casselsvg. El
       umbral viejo de 2.5 rechazaba esas placas.

    2. Si no hay match por (1), buscar el path cuyo bbox CONTIENE los bboxes
       de >= contain_pct de los demás paths. Eso identifica un contorno
       exterior aunque su forma sea irregular (logo orgánico que envuelve
       texto, p.ej.).

    Devuelve None si ningún criterio aplica; el caller usa bbox conjunto
    como fallback.
    """
    if not paths:
        return None

    # Heurística 1: forma cuasi-rectangular, mayor bbox-área
    best, best_bbox_area = None, 0.0
    for candidate in paths:
        cw = candidate.bbox["w"]
        ch = candidate.bbox["h"]
        exp_perim = 2 * (cw + ch)
        if exp_perim <= 0:
            continue
        if candidate.perimeter_px / exp_perim <= ratio_max:
            bbox_area = cw * ch
            if bbox_area > best_bbox_area:
                best_bbox_area = bbox_area
                best = candidate
    if best is not None:
        return best

    # Heurística 2: contiene a la mayoría de los otros paths
    def _contains(outer, inner, eps: float = 0.5) -> bool:
        return (inner.bbox["x"] >= outer.bbox["x"] - eps
                and inner.bbox["y"] >= outer.bbox["y"] - eps
                and inner.bbox["x"] + inner.bbox["w"]
                    <= outer.bbox["x"] + outer.bbox["w"] + eps
                and inner.bbox["y"] + inner.bbox["h"]
                    <= outer.bbox["y"] + outer.bbox["h"] + eps)

    n_others = len(paths) - 1
    if n_others <= 0:
        return None
    for candidate in sorted(paths,
                            key=lambda p: p.bbox["w"] * p.bbox["h"],
                            reverse=True):
        contained = sum(1 for other in paths
                        if other is not candidate and _contains(candidate, other))
        if contained / n_others >= contain_pct:
            return candidate
    return None


def cotizar_caja(
    svg_data: SVGData,
    real_width_cm: float,
    profundidad_cm: float,
    tipo_cara: str = "lona",       # material base de la cara: "lona" | "acrilico"
    base_cara_vinil: str = "lona", # legacy: base cuando tipo_cara == "vinil_corte"
    grafico: str = "impreso",      # "ninguno" | "impreso" | "vinil_corte"
    vinil_id: str = "vinil_std",   # vinil del catálogo VINILOS para grafico="vinil_corte"
    led_id: str = "auto",
    uso: str = "exterior",
    vistas: int = 1,
    margen_ganancia: float = 0.35,
    # Maquila y flete — montos manuales por cotización (varían por proveedor)
    corte_laser: float = 0.0,
    corte_cnc: float = 0.0,
    corte_plotter: float = 0.0,
    flete_maquila: float = 0.0,
    # Mano de obra del taller — se mete al costo para que el margen aplique a ella
    mo_horas: float = 0.0,
    mo_tarifa: float = 0.0,
) -> QuoteResult:

    svg_data = apply_scale(svg_data, real_width_cm)
    sf = svg_data.scale_factor

    # Determinar dimensiones de la cara y paths del diseño.
    # FIX Fase C: caja_w_cm/caja_h_cm son las medidas REALES de la placa
    # exterior detectada, no del artboard completo. Para SVGs con aire
    # alrededor (Illustrator carta horizontal de 43×27 cm con placa de
    # 38×16 cm, p.ej.), antes la caja se "inflaba" al artboard.
    if svg_data.paths:
        caja_path = _find_caja_outline(svg_data.paths)
        if caja_path is not None:
            caja_w_cm     = round(caja_path.bbox["w"] * sf, 2)
            caja_h_cm     = round(caja_path.bbox["h"] * sf, 2)
            design_paths_all = [p for p in svg_data.paths if p is not caja_path]
            clamp_x, clamp_y = caja_path.bbox["x"], caja_path.bbox["y"]
            clamp_w, clamp_h = caja_path.bbox["w"], caja_path.bbox["h"]
        else:
            # Sin contorno detectado → bbox conjunto como caja (no viewBox).
            min_x = min(p.bbox["x"] for p in svg_data.paths)
            min_y = min(p.bbox["y"] for p in svg_data.paths)
            max_x = max(p.bbox["x"] + p.bbox["w"] for p in svg_data.paths)
            max_y = max(p.bbox["y"] + p.bbox["h"] for p in svg_data.paths)
            bbox_w = max_x - min_x
            bbox_h = max_y - min_y
            caja_w_cm     = round(bbox_w * sf, 2)
            caja_h_cm     = round(bbox_h * sf, 2)
            design_paths_all = list(svg_data.paths)
            clamp_x, clamp_y = min_x, min_y
            clamp_w, clamp_h = bbox_w, bbox_h
    else:
        caja_w_cm        = real_width_cm
        caja_h_cm        = round(svg_data.viewbox_h * sf, 2)
        design_paths_all = []
        clamp_x, clamp_y = 0.0, 0.0
        clamp_w, clamp_h = svg_data.viewbox_w, svg_data.viewbox_h

    caja_area_cm2 = caja_w_cm * caja_h_cm
    area_m2       = caja_area_cm2 / 10000
    perimetro     = 2 * (caja_w_cm + caja_h_cm)

    # ── CARA ─────────────────────────────────────────────────────────────────
    # Modelo de negocio: la cara se decide en DOS pasos —
    #   1. material base: lona translúcida o acrílico (× vistas)
    #   2. gráfico: "impreso" cubre la cara completa; "vinil_corte" cobra el
    #      CUADRO DE CORTE (un solo rectángulo que envuelve el diseño, costeado
    #      por metros lineales de rollo del catálogo VINILOS); "ninguno" = lisa.
    # Compat con peticiones/quotes viejas: tipo_cara == "vinil_corte" era
    # "base + vinil de corte"; "acrilico_2vistas" era acrílico con vistas=2.
    if tipo_cara == "vinil_corte":
        grafico, tipo_cara = "vinil_corte", base_cara_vinil
    if tipo_cara == "acrilico_2vistas":
        tipo_cara, vistas = "acrilico", 2
    cara_base = "acrilico" if tipo_cara == "acrilico" else "lona_translucida"
    caras = 2 if vistas == 2 else 1

    if cara_base == "acrilico":
        precio_base_m2 = (PRECIOS_CAJA_M2["acrilico_2vistas"] if caras == 2
                          else PRECIOS_CAJA_M2["acrilico"])
        c_cara_base = round(area_m2 * precio_base_m2, 2)
    else:
        c_cara_base = round(area_m2 * PRECIOS_CAJA_M2["lona_translucida"] * caras, 2)

    cuadro_corte: dict | None = None
    vinil: dict | None = None
    c_grafico = 0.0
    if grafico == "vinil_corte":
        vinil = vinil_por_id(vinil_id)
        # UN SOLO rectángulo que envuelve todo el diseño (así se corta y así se
        # cobra el material, aunque el diseño tenga varios renglones)
        vinil_design = [p for p in design_paths_all if p.is_closed and p.area_px > 0.0]
        if not vinil_design:
            vinil_design = [p for p in design_paths_all if p.is_closed]
        if vinil_design:
            raw_min_x = min(p.bbox["x"] for p in vinil_design)
            raw_min_y = min(p.bbox["y"] for p in vinil_design)
            raw_max_x = max(p.bbox["x"] + p.bbox["w"] for p in vinil_design)
            raw_max_y = max(p.bbox["y"] + p.bbox["h"] for p in vinil_design)
            cl_min_x  = max(raw_min_x, clamp_x)
            cl_min_y  = max(raw_min_y, clamp_y)
            cl_max_x  = min(raw_max_x, clamp_x + clamp_w)
            cl_max_y  = min(raw_max_y, clamp_y + clamp_h)
            cw = max(0.0, (cl_max_x - cl_min_x) * sf)
            ch = max(0.0, (cl_max_y - cl_min_y) * sf)
        else:
            cw, ch = caja_w_cm, caja_h_cm
        ancho_rollo_cm = vinil.get("ancho_rollo_m", 0.60) * 100

        # Metros lineales de rollo: el cuadro se acomoda en bandas del ancho
        # del rollo; se toma la orientación que consuma menos rollo.
        def _ml_rollo(largo_cm: float, transversal_cm: float) -> float:
            return math.ceil(transversal_cm / ancho_rollo_cm) * largo_cm / 100

        ml_rollo  = round(min(_ml_rollo(cw, ch), _ml_rollo(ch, cw)), 2)
        c_grafico = round(ml_rollo * vinil["precio_ml"] * caras, 2)
        cuadro_corte = {
            "ancho_cm":     round(cw, 1),
            "alto_cm":      round(ch, 1),
            "area_m2":      round(cw * ch / 10000, 4),
            "ml_rollo":     ml_rollo,
            "vinil_id":     vinil["id"],
            "vinil_nombre": vinil["nombre"],
        }
    elif grafico == "impreso" and cara_base == "acrilico":
        # Vinil impreso laminado sobre el acrílico — cubre la cara completa
        c_grafico = round(area_m2 * PRECIOS_CAJA_M2["vinil_impresion"] * caras, 2)
    # "impreso" sobre lona: la lona translúcida ya sale impresa (la impresión
    # es del taller); no hay material adicional al de la lona.

    c_cara = round(c_cara_base + c_grafico, 2)
    vinil_total_area_m2 = cuadro_corte["area_m2"] if cuadro_corte else 0.0

    # Sercha del cajón — calibre según tamaño y uso (cal 20 para caja chica de
    # interior, cal 18 para exterior o caja grande) — costo proporcional al
    # área usada, NO whole-sheet: la sobra de cada caja queda para la
    # siguiente, así que cobrar lámina entera infla el precio injustamente.
    mat_sercha  = LAMINAS[material_sercha_caja(caja_w_cm, caja_h_cm, uso)]
    area_sercha = perimetro * profundidad_cm
    lam_sercha  = laminas_necesarias(area_sercha, "aluminio_cal18")  # informativo
    c_sercha    = round(area_sercha * precio_cm2(mat_sercha), 2)

    # Fondo — Alucobon 3mm para 1 vista (rigidez), PVC para 2 vistas (peso)
    if vistas == 1:
        fondo_id  = "alucobon_3mm"
    else:
        fondo_id  = "pvc_6mm" if uso == "exterior" else "pvc_3mm"
    mat_fondo = LAMINAS[fondo_id]
    lam_fondo = laminas_necesarias(caja_area_cm2, fondo_id)
    c_fondo   = lam_fondo * mat_fondo["precio"]

    # LEDs — selección automática o manual
    all_leds = LEDS_CAJA["interior"] + LEDS_CAJA["exterior"]
    if led_id != "auto":
        led = next((l for l in all_leds if l["id"] == led_id), None)
    else:
        led = None
    if led is None:
        recs = recomendar_led_caja(caja_w_cm, caja_h_cm, vistas == 2, uso, profundidad_cm)
        led  = recs[0] if recs else (LEDS_CAJA[uso][0] if LEDS_CAJA[uso] else all_leds[0])

    tipo_led = led.get("tipo_led", "backlite")
    if tipo_led == "modulo_panel":
        # Módulos discretos en grid sobre el alucobon, asumiendo interior
        # ultra blanco. Densidad por defecto 25 mod/m² (grid 20×20 cm).
        # Para vistas==2 se duplica la densidad (ambas caras).
        densidad_m2 = led.get("densidad_modulos_m2", 25)
        if vistas == 2:
            densidad_m2 *= 2
        tiras = max(1, math.ceil(area_m2 * densidad_m2))
        c_led = round(tiras * led["precio"], 2)
    elif tipo_led == "edgelite":
        # Barras paralelas montadas en los lados largos del interior, espaciado
        # típico 40 cm entre centros (calibrado para interior ultra blanco con
        # buena reflexión, ~20-30% menos LEDs que el espaciado nominal de 30 cm).
        # Para vistas==2 se iluminan ambas caras → 4 filas en lugar de 2.
        espaciado_cm   = led.get("espaciado_barras_cm", 40)
        lado_largo_cm  = max(caja_w_cm, caja_h_cm)
        lados          = 4 if vistas == 2 else 2
        barras_por_lado = max(1, math.ceil(lado_largo_cm / espaciado_cm))
        tiras          = barras_por_lado * lados
        c_led          = round(tiras * led["precio"], 2)
    elif tipo_led == "perimetral":
        espaciado_cm = led.get("espaciado_cm", 4.3)
        tiras        = max(1, math.ceil(perimetro / espaciado_cm))
        c_led        = round(tiras * led.get("precio_modulo", led["precio"]), 2)
    else:  # backlite — filas horizontales paralelas a lo ancho de la caja
        # Filas espaciadas cada 25 cm a lo largo del lado vertical (eje corto).
        # Asume interior ultra blanco para extender el alcance vs el viejo
        # "1 fila cada 18 cm de profundidad" que era contraintuitivo.
        espaciado_filas_cm = led.get("espaciado_filas_cm", 25)
        lado_corto_cm      = min(caja_w_cm, caja_h_cm)
        filas_led          = max(1, math.ceil(lado_corto_cm / espaciado_filas_cm))
        tiras              = filas_led
        c_led              = round(tiras * led["precio"], 2)

    watts     = round(tiras * led["watts"], 2)
    fuente    = fuente_optima(watts, uso)
    fraccion_caja = max(0.20, watts / fuente["watts"]) if fuente["watts"] > 0 else 1.0
    c_fuente  = round(fuente["precio"] * fraccion_caja, 2)

    pegamento = PEGAMENTOS.get(("aluminio", "aluminio"),
                {"nombre": "Soudaflex 40FC", "precio_aprox": 180})
    c_peg = pegamento["precio_aprox"]

    # Maquila y flete — montos manuales por cotización (corte láser/CNC/plotter
    # y flete del maquilador). Se suman al costo c/IVA antes del margen para
    # que el margen también se aplique a estos costos.
    c_maquila = round(corte_laser + corte_cnc + corte_plotter, 2)
    c_flete   = round(flete_maquila, 2)

    # Cables — consumo basado en el perímetro de la caja.
    # LED: cable estañado calibre 22 (Radox) por dentro, perímetro × 1.2
    # (vuelta + ramal a la fuente). Mínimo 5 m para evitar tramos absurdos.
    # POT: cable cal 18 para acometida 110V, fijo 5 m.
    metros_cable_led = max(5.0, round(perimetro / 100 * 1.2, 1))
    metros_cable_pot = 5.0
    cable_led_mat    = CABLES["led_radox_cal22"]
    cable_pot_mat    = CABLES["pot_cal18"]
    c_cable_led      = round(metros_cable_led * cable_led_mat["precio_m"], 2)
    c_cable_pot      = round(metros_cable_pot * cable_pot_mat["precio_m"], 2)
    c_cable          = round(c_cable_led + c_cable_pot, 2)

    # Mano de obra del taller — se incluye al costo para que el margen aplique
    # (típico: 8 hrs × $62.50/hr = $500 para una caja mediana).
    c_mo = round(mo_horas * mo_tarifa, 2)

    # Costo real con IVA (precios del catálogo ya incluyen IVA del proveedor).
    # Se descompone en subtotal sin IVA + IVA para mostrar la factura,
    # pero el margen se aplica SOBRE el costo c/IVA (no se acumula doble).
    costo_con_iva = (c_cara + c_sercha + c_fondo + c_led + c_fuente + c_peg
                     + c_cable + c_mo + c_maquila + c_flete)
    subtotal = round(costo_con_iva / 1.16, 2)
    iva      = round(costo_con_iva - subtotal, 2)
    total    = round(costo_con_iva, 2)
    venta    = round(costo_con_iva / (1 - margen_ganancia), 2)

    cara_nombre = ("Acrílico blanco 3mm" if cara_base == "acrilico"
                   else "Lona translúcida")
    if grafico == "impreso" and cara_base != "acrilico":
        cara_nombre += " impresa"
    sufijo_vistas = " × 2 vistas" if caras == 2 else ""

    desglose = [
        {"concepto": f"Cara {cara_nombre} {area_m2:.2f} m²{sufijo_vistas}",
         "costo": c_cara_base},
    ]
    if cuadro_corte is not None:
        desglose.append({
            "concepto": (f"Vinil de corte ({cuadro_corte['vinil_nombre']}) — cuadro "
                         f"{cuadro_corte['ancho_cm']:.0f}×{cuadro_corte['alto_cm']:.0f} cm "
                         f"· {cuadro_corte['ml_rollo']:.2f} m de rollo{sufijo_vistas}"),
            "costo": c_grafico,
        })
    elif grafico == "impreso" and cara_base == "acrilico":
        desglose.append({
            "concepto": f"Vinil impreso {area_m2:.2f} m²{sufijo_vistas}",
            "costo": c_grafico,
        })

    desglose += [
        {"concepto": f"Sercha cajón ({mat_sercha['nombre']}) × {lam_sercha} lám.", "costo": c_sercha},
        {"concepto": f"Fondo ({mat_fondo['nombre']}) × {lam_fondo} lám.", "costo": c_fondo},
        {"concepto": f"{led['nombre']} × {tiras} {'barras' if tipo_led=='edgelite' else 'módulos' if tipo_led in ('perimetral','modulo_panel') else 'tiras'}", "costo": c_led},
        {"concepto": fuente["nombre"], "costo": c_fuente},
        {"concepto": f"Pegamento: {pegamento['nombre']}", "costo": c_peg},
        {"concepto": f"Cable LED Radox cal 22 · {metros_cable_led:.1f} m", "costo": c_cable_led},
        {"concepto": f"Cable POT cal 18 · {metros_cable_pot:.1f} m",       "costo": c_cable_pot},
    ]

    # Mano de obra del taller — opcional según horas/tarifa indicadas
    if c_mo > 0:
        desglose.append({
            "concepto": f"Mano de obra · {mo_horas:.1f} hrs × ${mo_tarifa:.2f}/hr",
            "costo":    c_mo,
        })

    # Líneas opcionales de maquila y flete (solo si > 0)
    if corte_laser > 0:
        desglose.append({"concepto": "Corte láser (maquila)",   "costo": round(corte_laser, 2)})
    if corte_cnc > 0:
        desglose.append({"concepto": "Corte CNC (maquila)",     "costo": round(corte_cnc, 2)})
    if corte_plotter > 0:
        desglose.append({"concepto": "Corte plotter (maquila)", "costo": round(corte_plotter, 2)})
    if flete_maquila > 0:
        desglose.append({"concepto": "Flete maquila",           "costo": round(flete_maquila, 2)})

    grafico_label = {"impreso": "impreso", "vinil_corte": "vinil de corte",
                     "ninguno": "lisa"}.get(grafico, grafico)
    mat_cara_info: dict = {
        "nombre":  f"{cara_nombre} · {grafico_label}",
        "precio":  c_cara,
        "base":    cara_base,
        "grafico": grafico,
    }
    if cuadro_corte is not None:
        mat_cara_info["cuadro_corte"]  = cuadro_corte
        # legacy: clientes viejos leen vinil_filas / vinil_area_m2
        mat_cara_info["vinil_filas"]   = [cuadro_corte]
        mat_cara_info["vinil_area_m2"] = vinil_total_area_m2

    # Fase G: desglose por componente para caja (cara, estructura, fondo, leds,
    # fuente, pegamento). La "caja" se trata como UNA pieza (la caja en sí); las
    # vinil_filas son sub-elementos de la cara, ya van dentro de c_cara.
    desglose_costos_componentes = {
        "cara":           round(c_cara, 2),
        "sercha":         round(c_sercha, 2),
        "fondo":          round(c_fondo, 2),
        "leds":           round(c_led, 2),
        "fuente":         round(c_fuente, 2),
        "pegamento":      round(c_peg, 2),
        "cables":         c_cable,
    }
    if c_mo > 0:
        desglose_costos_componentes["mano_obra"] = c_mo
    if c_maquila > 0:
        desglose_costos_componentes["maquila"] = c_maquila
    if c_flete > 0:
        desglose_costos_componentes["flete"]   = c_flete
    desglose_costos_componentes["total_material"] = round(subtotal, 2)

    # Fase H: warnings — caja con prof 0 es físicamente imposible
    warnings: list[str] = []
    if profundidad_cm <= 0:
        warnings.append("Profundidad de caja es 0 cm — una caja sin profundidad no es una caja. Verifica el valor.")
    if cuadro_corte is not None and not design_paths_all:
        warnings.append(
            "Vinil de corte sin diseño detectado en el SVG — el cuadro de corte "
            "se asumió del tamaño completo de la caja. Verifica el archivo."
        )

    return QuoteResult(
        tipo="caja_luz",
        paths_count=1,
        area_cara_cm2=caja_area_cm2,
        perimetro_total_cm=perimetro,
        cercha_altura_cm=profundidad_cm,
        cercha_area_cm2=area_sercha,
        material_cara=mat_cara_info,
        material_cercha=mat_sercha,
        material_fondo=mat_fondo,
        laminas_cara=1,
        laminas_cercha=lam_sercha,
        laminas_fondo=lam_fondo,
        led=led,
        modulos_led=tiras,
        watts_total=watts,
        fuente=fuente,
        pegamento=pegamento,
        costo_material_cara=c_cara,
        costo_material_cercha=c_sercha,
        costo_material_fondo=c_fondo,
        costo_led=c_led,
        costo_fuente=c_fuente,
        costo_pegamento=c_peg,
        subtotal=subtotal,
        iva=iva,
        total=total,
        precio_venta_sugerido=venta,
        desglose=desglose,
        desglose_costos_componentes=desglose_costos_componentes,
        warnings=warnings,
    )
