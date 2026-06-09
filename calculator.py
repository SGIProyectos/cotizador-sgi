import io
import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from svgpathtools import svg2paths2

from catalog_data import (
    DISTANCIADORES,
    LAMINAS,
    LEDS_CAJA,
    PEGAMENTOS,
    PRECIOS_BASE,
    PRECIOS_CAJA_M2,
    TIPOS_CONSTRUCCION,
    VINILOS_CERCHA,
    cercha_recomendada_cm,
    fuente_optima,
    led_recomendado,
    material_cara,
    material_cercha,
    recomendar_led_caja,
    silvatrim_recomendado,
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

@dataclass
class SVGData:
    paths: list[PathInfo]
    viewbox_w: float
    viewbox_h: float
    svg_unit: str           # "px" | "mm" | "cm" | "pt"
    scale_factor: float = 1.0
    max_letter_height_px: float = 0.0   # altura máx detectada de los paths (bbox h)
    artboard_w_cm: float = 0.0          # >0 si es SVG de Illustrator (viewBox en pt)


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


def _parse_viewbox(svg_root) -> tuple[float, float, str]:
    """Extrae dimensiones del SVG. Devuelve (ancho_px, alto_px, unidad)."""
    vb = svg_root.get("viewBox", "")
    width_attr  = svg_root.get("width", "")
    height_attr = svg_root.get("height", "")

    # Detectar unidad
    unit = "px"
    for u in ("mm", "cm", "in", "pt"):
        if u in width_attr:
            unit = u
            break

    def to_px(val: str) -> float:
        val = val.strip()
        conv = {"mm": 3.7795, "cm": 37.795, "in": 96.0, "pt": 1.3333, "px": 1.0}
        for u, f in conv.items():
            if val.endswith(u):
                return float(val.replace(u, "")) * f
        try:
            return float(val)
        except ValueError:
            return 0.0

    if vb:
        parts = vb.replace(",", " ").split()
        if len(parts) == 4:
            return float(parts[2]), float(parts[3]), unit

    w = to_px(width_attr)
    h = to_px(height_attr)
    return w or 500.0, h or 500.0, unit


def parse_svg(svg_bytes: bytes) -> SVGData:
    """Parsea un SVG y devuelve paths con perímetro y área en píxeles."""
    svg_text = svg_bytes.decode("utf-8", errors="replace")

    # Parse con svgpathtools para obtener paths
    try:
        paths_raw, attrs, svg_attrs = svg2paths2(io.StringIO(svg_text))
    except Exception:
        log.warning("svg2paths2 falló — el SVG no se pudo parsear; devolviendo lista vacía", exc_info=True)
        paths_raw, attrs = [], []
        svg_attrs = {}

    # Parse XML para viewBox
    ns = {"svg": "http://www.w3.org/2000/svg"}
    root = ET.fromstring(svg_text)
    vb_w, vb_h, unit = _parse_viewbox(root)

    path_infos = []
    for i, (path, attr) in enumerate(zip(paths_raw, attrs)):
        if not path:
            continue
        try:
            perimeter = path.length(error=1e-4)
        except Exception:
            perimeter = 0.0

        # Determinar si es cerrado (path con Z o figura convertida como rect)
        d = attr.get("d", "")
        if d.strip().upper().endswith("Z"):
            is_closed = True
        else:
            try:
                is_closed = abs(path[-1].end - path[0].start) < 1e-3
            except Exception:
                is_closed = False

        area = _path_area_shoelace(path) if is_closed else 0.0

        # Bounding box
        try:
            xmin, xmax, ymin, ymax = path.bbox()
            bbox = {"x": xmin, "y": ymin, "w": xmax - xmin, "h": ymax - ymin}
        except Exception:
            bbox = {"x": 0, "y": 0, "w": 0, "h": 0}

        orig_id = attr.get("id", f"path_{i}")
        path_infos.append(PathInfo(
            id=orig_id,
            perimeter_px=perimeter,
            area_px=area,
            bbox=bbox,
            is_closed=is_closed,
            svg_id=orig_id,
        ))

    # Ordenar por posición horizontal (izquierda → derecha) y renombrar
    path_infos.sort(key=lambda p: p.bbox["x"])
    for i, p in enumerate(path_infos):
        p.id = f"Letra {i + 1}"

    max_h_px = max((p.bbox["h"] for p in path_infos), default=0.0)

    # Detectar SVG de Illustrator: viewBox en puntos tipográficos (pt)
    # Marker: style="enable-background:..." en el elemento <svg>
    artboard_w_cm = 0.0
    svg_style = root.get("style", "")
    if "enable-background" in svg_style:
        PT_TO_CM = 2.54 / 72.0   # 1 pt = 0.035278 cm
        artboard_w_cm = vb_w * PT_TO_CM
        unit = "pt"

    return SVGData(
        paths=path_infos,
        viewbox_w=vb_w,
        viewbox_h=vb_h,
        svg_unit=unit,
        max_letter_height_px=max_h_px,
        artboard_w_cm=artboard_w_cm,
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
) -> QuoteResult:

    # Si el usuario conoce la altura, escalar desde ella (ignora márgenes del artboard).
    # Si no, escalar desde el ancho y auto-detectar altura.
    if altura_letra_cm > 0:
        svg_data = apply_scale(svg_data, real_width_cm, altura_cm=altura_letra_cm)
    else:
        svg_data = apply_scale(svg_data, real_width_cm)
        if svg_data.paths:
            max_h_px = max(p.bbox["h"] for p in svg_data.paths)
            altura_letra_cm = max_h_px * svg_data.scale_factor
        if altura_letra_cm <= 0:
            altura_letra_cm = 15.0

    # Filtrar solo paths cerrados con área significativa
    letras = [p for p in svg_data.paths if p.is_closed and p.area_cm2 > 1.0]
    if not letras:
        letras = svg_data.paths  # fallback: usar todos

    sf = svg_data.scale_factor
    # Cara: usamos bounding box (alto × ancho) por letra, como se corta en producción real
    area_cara_total   = sum(
        (p.bbox["h"] * sf) * (p.bbox["w"] * sf) for p in letras
    )
    perimetro_total   = sum(p.perimeter_cm for p in letras)

    # Cercha
    if cercha_cm <= 0:
        cercha_cm = cercha_recomendada_cm(altura_letra_cm)

    area_cercha_total = perimetro_total * cercha_cm

    config = TIPOS_CONSTRUCCION.get(tipo_construccion, TIPOS_CONSTRUCCION["cajon_luz"])

    # ── CARA ──────────────────────────────────────────────────────────────────
    if config["cara"] == "ninguna":
        mat_cara_id = None
        mat_cara    = {"nombre": "Sin cara frontal", "precio": 0, "ancho_cm": 122, "alto_cm": 244}
        lam_cara    = 0
        c_cara      = 0.0
    elif config["cara"] == "aluminio":
        mat_cara_id = material_cercha(altura_letra_cm) if tipo_cara == "auto" else tipo_cara
        mat_cara    = LAMINAS[mat_cara_id]
        lam_cara    = laminas_necesarias(area_cara_total, mat_cara_id)
        c_cara      = round(area_cara_total * precio_cm2(mat_cara), 2)
    else:  # acrilico
        mat_cara_id = material_cara(altura_letra_cm) if tipo_cara == "auto" else tipo_cara
        mat_cara    = LAMINAS[mat_cara_id]
        lam_cara    = laminas_necesarias(area_cara_total, mat_cara_id)
        c_cara      = round(area_cara_total * precio_cm2(mat_cara), 2)

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
    if config["leds"]:
        modulos = math.ceil(perimetro_total / espaciado_led_cm)
        led     = led_recomendado(cercha_cm, uso)
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
                {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox": 90, "metros_por_envase": 5}))
    # Cordón de pegamento en metros: perímetro total × cantidad de juntas (cara + fondo si aplica)
    juntas    = (1 if config["cara"] != "ninguna" else 0) + (1 if config["fondo_pvc"] else 0)
    metros_peg = perimetro_total / 100 * max(1, juntas)
    envases   = max(0.15, metros_peg / pegamento.get("metros_por_envase", 5))
    c_peg     = round(envases * pegamento["precio_aprox"], 2)

    # ── SILVATRIM ─────────────────────────────────────────────────────────────
    sv         = silvatrim_recomendado(cercha_cm)
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
    ppcm2_cara   = precio_cm2(mat_cara)   if mat_cara_id else 0.0
    ppcm2_cercha = precio_cm2(mat_cercha)
    ppcm2_fondo  = precio_cm2(mat_fondo)  if config["fondo_pvc"] else 0.0

    def _fmt_mat(nombre, lam, ppcm2, area):
        return f"{nombre} · {area:.0f} cm² × ${ppcm2:.4f}/cm² ({lam} lám.)"

    desglose = []
    if config["cara"] != "ninguna":
        desglose.append({"concepto": _fmt_mat(mat_cara["nombre"], lam_cara, ppcm2_cara, area_cara_total), "costo": c_cara})
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
    desglose.append({"concepto": desglose_sv, "costo": c_silvatrim})
    if vc:
        desglose.append({"concepto": f"Vinil cercha {vc['nombre']} · {metros_vc:.1f} m × ${vc['precio_ml']:.2f}/m", "costo": c_vinil_cercha})

    # ── Lógica de cotización (hoja COTIZANDO del Excel) ─────────────────────────
    # precio_letra = altura_real_cm × precio_cm × multiplicador
    precio_cm     = PRECIOS_BASE["precio_cm"]
    multiplicador = PRECIOS_BASE["multiplicadores"].get(tipo_multiplicador, 4.5)

    desglose_letras = []
    precio_formula_total = 0.0
    for p in letras:
        alto_cm    = round(p.bbox["h"] * svg_data.scale_factor, 2)
        ancho_cm   = round(p.bbox["w"] * svg_data.scale_factor, 2)
        area_bbox  = round(alto_cm * ancho_cm, 2)           # alto × ancho (bounding box)
        tira_neta  = round(p.perimeter_cm, 1)
        tira_total = round(p.perimeter_cm * 1.10, 1)
        cercha_area_letra = round(tira_neta * cercha_cm, 2)  # perímetro × profundidad

        costo_cara_letra   = round(area_bbox         * ppcm2_cara,   2) if mat_cara_id else 0.0
        costo_cercha_letra = round(cercha_area_letra * ppcm2_cercha, 2)
        costo_fondo_letra  = round(area_bbox         * ppcm2_fondo,  2)
        costo_mat_letra    = round(costo_cara_letra + costo_cercha_letra + costo_fondo_letra, 2)

        precio_letra = round(alto_cm * precio_cm * multiplicador, 2)
        precio_formula_total += precio_letra
        desglose_letras.append({
            "id":               p.id,
            "alto_cm":          alto_cm,
            "ancho_cm":         ancho_cm,
            "area_bbox_cm2":    area_bbox,
            "perimetro_cm":     tira_neta,
            "area_cm2":         round(p.area_cm2, 1),
            "cercha_neta_cm":   tira_neta,
            "cercha_total_cm":  tira_total,
            "cercha_area_cm2":  cercha_area_letra,
            "cercha_altura_cm": round(cercha_cm, 1),
            "costo_cara":       costo_cara_letra,
            "costo_cercha":     costo_cercha_letra,
            "costo_mat":        costo_mat_letra,
            "precio_letra":     precio_letra,
        })

    precio_formula_total   = round(precio_formula_total, 2)
    precio_formula_ajustado = round(precio_formula_total * (1 + ajuste_pct / 100), 2)
    precio_venta_costo      = round(total / (1 - margen_ganancia), 2)  # piso por costo

    return QuoteResult(
        tipo="letras_3d",
        paths_count=len(letras),
        altura_letra_cm=round(altura_letra_cm, 1),
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
    )


# ─── COTIZACIÓN LETRAS PLANAS ────────────────────────────────────────────────

def cotizar_planas(
    svg_data: SVGData,
    real_width_cm: float,
    material_id: str = "acrilico_3mm",
    margen_ganancia: float = 0.35,
    tipo_multiplicador: str = "aluminio_sin_luz",
    ajuste_pct: float = 0.0,
) -> QuoteResult:

    svg_data = apply_scale(svg_data, real_width_cm)

    letras = [p for p in svg_data.paths if p.is_closed and p.area_cm2 > 0.5]
    if not letras:
        letras = svg_data.paths

    sf_p = svg_data.scale_factor
    # Letras planas: bounding box para costo de material (equivale a la pieza cortada)
    area_total      = sum(
        (p.bbox["h"] * sf_p) * (p.bbox["w"] * sf_p) for p in letras
    )
    perimetro_total = sum(p.perimeter_cm for p in letras)

    if material_id not in LAMINAS:
        material_id = "acrilico_3mm"
    mat  = LAMINAS[material_id]
    lam  = laminas_necesarias(area_total, material_id)
    ppcm2_mat = precio_cm2(mat)
    c_mat = round(area_total * ppcm2_mat, 2)

    subtotal = c_mat
    iva      = subtotal * 0.16
    total    = subtotal + iva

    precio_cm     = PRECIOS_BASE["precio_cm"]
    multiplicador = PRECIOS_BASE["multiplicadores"].get(tipo_multiplicador, 2.0)

    desglose_letras = []
    precio_formula_total = 0.0
    for p in letras:
        alto_cm   = round(p.bbox["h"] * svg_data.scale_factor, 2)
        ancho_cm  = round(p.bbox["w"] * svg_data.scale_factor, 2)
        area_bbox = round(alto_cm * ancho_cm, 2)
        costo_mat = round(area_bbox * ppcm2_mat, 2)
        precio_letra = round(alto_cm * precio_cm * multiplicador, 2)
        precio_formula_total += precio_letra
        desglose_letras.append({
            "id":               p.id,
            "alto_cm":          alto_cm,
            "ancho_cm":         ancho_cm,
            "area_bbox_cm2":    area_bbox,
            "perimetro_cm":     round(p.perimeter_cm, 1),
            "area_cm2":         round(p.area_cm2, 1),
            "cercha_neta_cm":   0,
            "cercha_total_cm":  0,
            "cercha_area_cm2":  0,
            "cercha_altura_cm": 0,
            "costo_cara":       costo_mat,
            "costo_cercha":     0,
            "costo_mat":        costo_mat,
            "precio_letra":     precio_letra,
        })

    precio_formula_total    = round(precio_formula_total, 2)
    precio_formula_ajustado = round(precio_formula_total * (1 + ajuste_pct / 100), 2)
    precio_venta_costo      = round(total / (1 - margen_ganancia), 2)

    return QuoteResult(
        tipo="letras_planas",
        tipo_construccion="plana",
        paths_count=len(letras),
        altura_letra_cm=round(max((p.bbox["h"] * svg_data.scale_factor for p in letras), default=0), 1),
        area_cara_cm2=area_total,
        perimetro_total_cm=perimetro_total,
        cercha_altura_cm=0,
        cercha_area_cm2=0,
        material_cara=mat,
        material_cercha={"nombre": "N/A", "precio": 0},
        material_fondo={"nombre": "N/A", "precio": 0},
        laminas_cara=lam,
        laminas_cercha=0,
        laminas_fondo=0,
        led={"nombre": "Sin iluminación", "precio_modulo": 0, "watts_modulo": 0, "ip": "—", "lumenes": 0},
        modulos_led=0,
        watts_total=0.0,
        fuente={"nombre": "Sin fuente", "precio": 0},
        pegamento={"nombre": "N/A", "precio_aprox": 0},
        costo_material_cara=c_mat,
        costo_material_cercha=0.0,
        costo_material_fondo=0.0,
        costo_led=0.0,
        costo_fuente=0.0,
        costo_pegamento=0.0,
        subtotal=subtotal,
        iva=iva,
        total=total,
        precio_venta_sugerido=precio_formula_ajustado,
        precio_venta_costo=precio_venta_costo,
        tipo_multiplicador=tipo_multiplicador,
        multiplicador_valor=multiplicador,
        precio_sin_ajuste=precio_formula_total,
        ajuste_pct=ajuste_pct,
        desglose=[{"concepto": f"{mat['nombre']} · {area_total:.0f} cm² × ${ppcm2_mat:.4f}/cm² ({lam} lám.)", "costo": c_mat}],
        desglose_letras=desglose_letras,
    )


# ─── COTIZACIÓN CAJA DE LUZ ──────────────────────────────────────────────────

def _find_caja_outline(paths: list):
    """
    Identifica el contorno rectangular de la caja: el path con mayor bbox-área
    cuyo perímetro ≈ 2*(w+h) (ratio ≤ 2.5).
    Devuelve None si ningún path pasa el criterio rectangular — el caller
    debe usar artboard/viewbox como fallback.
    """
    if not paths:
        return None
    best, best_bbox_area = None, 0.0
    for candidate in paths:
        cw = candidate.bbox["w"]
        ch = candidate.bbox["h"]
        exp_perim = 2 * (cw + ch)
        if exp_perim <= 0:
            continue
        if candidate.perimeter_px / exp_perim <= 2.5:
            bbox_area = cw * ch
            if bbox_area > best_bbox_area:
                best_bbox_area = bbox_area
                best = candidate
    return best  # None cuando no hay path rectangular


def _group_design_paths_by_row(paths: list) -> list:
    """
    Agrupa paths en filas horizontales fusionando intervalos Y solapados.
    Devuelve lista de listas (una sublista por fila).
    """
    if not paths:
        return []
    ordered = sorted(paths, key=lambda p: p.bbox["y"])
    rows = [[ordered[0]]]
    cur_bottom = ordered[0].bbox["y"] + ordered[0].bbox["h"]
    for p in ordered[1:]:
        if p.bbox["y"] <= cur_bottom:          # solapado → misma fila
            rows[-1].append(p)
            cur_bottom = max(cur_bottom, p.bbox["y"] + p.bbox["h"])
        else:                                   # gap → nueva fila
            rows.append([p])
            cur_bottom = p.bbox["y"] + p.bbox["h"]
    return rows


def cotizar_caja(
    svg_data: SVGData,
    real_width_cm: float,
    profundidad_cm: float,
    tipo_cara: str = "lona",       # "lona" | "acrilico" | "acrilico_2vistas" | "vinil_corte"
    base_cara_vinil: str = "lona", # base cuando tipo_cara == "vinil_corte": "lona" | "acrilico"
    led_id: str = "auto",
    uso: str = "exterior",
    vistas: int = 1,
    margen_ganancia: float = 0.35,
) -> QuoteResult:

    svg_data = apply_scale(svg_data, real_width_cm)
    sf = svg_data.scale_factor

    caja_w_cm = real_width_cm

    # Determinar altura de la cara y paths del diseño
    if svg_data.paths:
        caja_path = _find_caja_outline(svg_data.paths)
        if caja_path is not None:
            # Hay contorno rectangular → usarlo para la relación de aspecto
            _bw = caja_path.bbox["w"] or 1
            caja_h_cm     = round(real_width_cm * (caja_path.bbox["h"] / _bw), 2)
            design_paths_all = [p for p in svg_data.paths if p is not caja_path]
            clamp_x, clamp_y = caja_path.bbox["x"], caja_path.bbox["y"]
            clamp_w, clamp_h = caja_path.bbox["w"], caja_path.bbox["h"]
        else:
            # Sin contorno rectangular → usar artboard/viewbox (Illustrator: viewBox en pt)
            caja_h_cm     = round(svg_data.viewbox_h * sf, 2)
            design_paths_all = list(svg_data.paths)
            clamp_x, clamp_y = 0.0, 0.0
            clamp_w, clamp_h = svg_data.viewbox_w, svg_data.viewbox_h
    else:
        caja_h_cm        = round(svg_data.viewbox_h * sf, 2)
        design_paths_all = []
        clamp_x, clamp_y = 0.0, 0.0
        clamp_w, clamp_h = svg_data.viewbox_w, svg_data.viewbox_h

    caja_area_cm2 = caja_w_cm * caja_h_cm
    area_m2       = caja_area_cm2 / 10000
    perimetro     = 2 * (caja_w_cm + caja_h_cm)

    # ── CARA ─────────────────────────────────────────────────────────────────
    vinil_filas: list[dict] = []

    if tipo_cara == "vinil_corte":
        precio_base_m2 = PRECIOS_CAJA_M2.get(base_cara_vinil, PRECIOS_CAJA_M2["lona"])
        c_cara_base = round(area_m2 * precio_base_m2, 2)

        # Solo paths cerrados con área real (excluye trazos/contornos abiertos como el cajón)
        vinil_design = [p for p in design_paths_all if p.is_closed and p.area_px > 0.0]
        if not vinil_design:
            vinil_design = [p for p in design_paths_all if p.is_closed]

        if vinil_design:
            filas_paths = _group_design_paths_by_row(vinil_design)
            total_area_cm2 = 0.0
            for fila_paths in filas_paths:
                raw_min_x = min(p.bbox["x"] for p in fila_paths)
                raw_min_y = min(p.bbox["y"] for p in fila_paths)
                raw_max_x = max(p.bbox["x"] + p.bbox["w"] for p in fila_paths)
                raw_max_y = max(p.bbox["y"] + p.bbox["h"] for p in fila_paths)
                cl_min_x  = max(raw_min_x, clamp_x)
                cl_min_y  = max(raw_min_y, clamp_y)
                cl_max_x  = min(raw_max_x, clamp_x + clamp_w)
                cl_max_y  = min(raw_max_y, clamp_y + clamp_h)
                fw = round(max(0.0, (cl_max_x - cl_min_x) * sf), 1)
                fh = round(max(0.0, (cl_max_y - cl_min_y) * sf), 1)
                fa = round(fw * fh / 10000, 4)
                total_area_cm2 += fw * fh
                vinil_filas.append({"ancho_cm": fw, "alto_cm": fh, "area_m2": fa})
            vinil_total_area_m2 = round(total_area_cm2 / 10000, 4)
        else:
            vinil_filas         = [{"ancho_cm": caja_w_cm, "alto_cm": caja_h_cm,
                                    "area_m2": round(caja_area_cm2 / 10000, 4)}]
            vinil_total_area_m2 = area_m2

        c_vinil = round(vinil_total_area_m2 * PRECIOS_CAJA_M2["vinil_corte"], 2)
        c_cara  = round(c_cara_base + c_vinil, 2)
    else:
        precio_m2 = PRECIOS_CAJA_M2.get(
            "acrilico_2vistas" if vistas == 2 else tipo_cara,
            PRECIOS_CAJA_M2["lona"]
        )
        c_cara              = round(area_m2 * precio_m2, 2)
        c_cara_base         = c_cara
        vinil_total_area_m2 = 0.0

    # Estructura (aluminio cal 18 para el cajón)
    mat_struct = LAMINAS["aluminio_cal18"]
    area_struct = perimetro * profundidad_cm
    lam_struct  = laminas_necesarias(area_struct, "aluminio_cal18")
    c_struct    = lam_struct * mat_struct["precio"]

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
    if tipo_led == "edgelite":
        largo_cm = led.get("largo_cm", 56)
        tiras    = max(1, math.ceil(perimetro / largo_cm))
        c_led    = round(tiras * led["precio"], 2)
    elif tipo_led == "perimetral":
        espaciado_cm = led.get("espaciado_cm", 4.3)
        tiras        = max(1, math.ceil(perimetro / espaciado_cm))
        c_led        = round(tiras * led.get("precio_modulo", led["precio"]), 2)
    else:  # backlite — filas horizontales cada 18 cm de profundidad
        filas_led = max(1, math.ceil(profundidad_cm / 18))
        tiras     = filas_led
        c_led     = round(tiras * led["precio"], 2)

    watts     = round(tiras * led["watts"], 2)
    fuente    = fuente_optima(watts, uso)
    fraccion_caja = max(0.20, watts / fuente["watts"]) if fuente["watts"] > 0 else 1.0
    c_fuente  = round(fuente["precio"] * fraccion_caja, 2)

    pegamento = PEGAMENTOS.get(("aluminio", "aluminio"),
                {"nombre": "Soudaflex 40FC", "precio_aprox": 180})
    c_peg = pegamento["precio_aprox"]

    subtotal = c_cara + c_struct + c_fondo + c_led + c_fuente + c_peg
    iva      = subtotal * 0.16
    total    = subtotal + iva
    venta    = total / (1 - margen_ganancia)

    if tipo_cara == "vinil_corte":
        if len(vinil_filas) == 1:
            fila_desc = f"{vinil_filas[0]['ancho_cm']:.0f}×{vinil_filas[0]['alto_cm']:.0f} cm"
        else:
            fila_desc = " + ".join(
                f"F{i+1}:{f['ancho_cm']:.0f}×{f['alto_cm']:.0f}"
                for i, f in enumerate(vinil_filas)
            )
        desglose = [
            {"concepto": f"Base cara ({base_cara_vinil}) {area_m2:.2f} m²", "costo": c_cara_base},
            {"concepto": f"Vinil de corte {fila_desc} ({vinil_total_area_m2:.3f} m²)", "costo": c_vinil},
        ]
    else:
        desglose = [
            {"concepto": f"Cara ({tipo_cara}) {area_m2:.2f} m²", "costo": c_cara},
        ]

    desglose += [
        {"concepto": f"Estructura cajón ({mat_struct['nombre']}) × {lam_struct} lám.", "costo": c_struct},
        {"concepto": f"Fondo ({mat_fondo['nombre']}) × {lam_fondo} lám.", "costo": c_fondo},
        {"concepto": f"{led['nombre']} × {tiras} {'barras' if tipo_led=='edgelite' else 'módulos' if tipo_led=='perimetral' else 'tiras'}", "costo": c_led},
        {"concepto": fuente["nombre"], "costo": c_fuente},
        {"concepto": f"Pegamento: {pegamento['nombre']}", "costo": c_peg},
    ]

    mat_cara_info: dict = {"nombre": tipo_cara, "precio": c_cara}
    if tipo_cara == "vinil_corte":
        mat_cara_info["base"]          = base_cara_vinil
        mat_cara_info["vinil_filas"]   = vinil_filas
        mat_cara_info["vinil_area_m2"] = vinil_total_area_m2

    return QuoteResult(
        tipo="caja_luz",
        paths_count=1,
        area_cara_cm2=caja_area_cm2,
        perimetro_total_cm=perimetro,
        cercha_altura_cm=profundidad_cm,
        cercha_area_cm2=area_struct,
        material_cara=mat_cara_info,
        material_cercha=mat_struct,
        material_fondo=mat_fondo,
        laminas_cara=1,
        laminas_cercha=lam_struct,
        laminas_fondo=lam_fondo,
        led=led,
        modulos_led=tiras,
        watts_total=watts,
        fuente=fuente,
        pegamento=pegamento,
        costo_material_cara=c_cara,
        costo_material_cercha=c_struct,
        costo_material_fondo=c_fondo,
        costo_led=c_led,
        costo_fuente=c_fuente,
        costo_pegamento=c_peg,
        subtotal=subtotal,
        iva=iva,
        total=total,
        precio_venta_sugerido=venta,
        desglose=desglose,
    )
