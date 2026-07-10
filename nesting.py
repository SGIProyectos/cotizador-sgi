"""
Nesting: acomodo de piezas para corte optimizando lámina / rollo.

Módulo independiente del cotizador: recibe uno o varios SVG (cada uno con su
ancho real en cm y sus copias), extrae las piezas con su contorno REAL
(huecos de letras incluidos) y las acomoda en láminas minimizando material.

Algoritmo — NFP raster por convolución:
  1. SVG -> anillos muestreados (svgpathtools) -> piezas shapely con huecos,
     asignados por profundidad de contención par/impar (soporta huecos como
     subpaths del mismo path Y como paths separados).
  2. Colocación greedy bottom-left: piezas ordenadas por área descendente;
     para cada ángulo candidato la pieza se rasteriza (huecos libres) y
     cv2.matchTemplate prueba TODAS las posiciones de la lámina de golpe.
     El candidato viaja dilatado por el gap -> separación mínima garantizada;
     lo ya colocado se guarda sin dilatar -> los huecos de una pieza colocada
     quedan libres y piezas chicas caen dentro solitas.
  3. Si no cabe en ninguna lámina abierta se abre otra. Piezas que no caben
     ni en una lámina vacía se reportan (nunca se omiten en silencio).

Unidades: todo el módulo trabaja en cm. El DXF se exporta en mm (estándar
de talleres de corte).
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import cv2
import ezdxf
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
from svgpathtools import svg2paths2

# ─── Parámetros por defecto (los reales los manda la UI) ─────────────────────
RES_CM        = 0.25   # resolución del raster (2.5 mm por pixel)
PASO_ANGULO   = 15     # grados entre orientaciones candidatas
MIN_AREA_CM2  = 0.25   # anillos menores a esto son basura de muestreo
MAX_PIEZAS    = 400    # tope de seguridad (tiempo de cómputo)
MAX_LADO_CM   = 1500.0 # tope de lámina/rollo


@dataclass
class PiezaNest:
    poly: Polygon          # contorno en cm, con huecos
    etiqueta: str          # "archivo · pieza n (copia m)"
    fuente: str            # nombre del archivo de origen

    @property
    def area(self) -> float:
        return self.poly.area


@dataclass
class Colocacion:
    poly: Polygon          # ya girado y trasladado a coords de lámina (cm)
    etiqueta: str
    fuente: str
    angulo: float


@dataclass
class LaminaNest:
    idx: int
    ancho_cm: float
    alto_cm: float
    colocaciones: list[Colocacion] = field(default_factory=list)

    @property
    def area_piezas_cm2(self) -> float:
        return sum(c.poly.area for c in self.colocaciones)

    @property
    def util_pct(self) -> float:
        a = self.ancho_cm * self.alto_cm
        return self.area_piezas_cm2 / a * 100 if a > 0 else 0.0

    @property
    def franja_cm(self) -> float:
        """Alto realmente consumido (para retazos / largo de rollo)."""
        if not self.colocaciones:
            return 0.0
        return max(c.poly.bounds[3] for c in self.colocaciones)

    @property
    def util_franja_pct(self) -> float:
        a = self.ancho_cm * self.franja_cm
        return self.area_piezas_cm2 / a * 100 if a > 0 else 0.0


# ─── 1. SVG -> piezas ────────────────────────────────────────────────────────

def _muestrear_anillos(svg_bytes: bytes) -> tuple[list[Polygon], float, float]:
    """Subpaths cerrados -> anillos shapely (unidades SVG).
    Devuelve (anillos, ancho_bbox_conjunto, area_viewbox)."""
    paths, _attrs, svg_attrs = svg2paths2(io.StringIO(svg_bytes.decode("utf-8", "replace")))
    area_vb = 0.0
    try:
        vb = [float(v) for v in str(svg_attrs.get("viewBox", "")).replace(",", " ").split()]
        if len(vb) == 4:
            area_vb = vb[2] * vb[3]
    except ValueError:
        pass
    anillos: list[Polygon] = []
    for path in paths:
        for sub in path.continuous_subpaths():
            try:
                largo = sub.length()
            except Exception:
                continue
            if not largo or largo <= 0:
                continue
            cerrado = sub.isclosed() or abs(sub.start - sub.end) < 0.01 * largo
            if not cerrado:
                continue
            n = max(32, min(800, int(largo / 2)))
            pts = []
            for i in range(n):
                z = sub.point(i / n)
                pts.append((z.real, z.imag))
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            if poly.geom_type == "MultiPolygon":
                anillos.extend(Polygon(g.exterior) for g in poly.geoms)
            else:
                anillos.append(Polygon(poly.exterior))
    if not anillos:
        return [], 0.0, area_vb

    # Fondo/artboard: Illustrator suele exportar un rect del tamaño del lienzo.
    # Se descarta solo si cubre casi todo el viewBox Y contiene otros anillos
    # (un rectángulo solo que SÍ se quiere cortar no contiene nada).
    if area_vb > 0:
        filtrados = []
        for r in anillos:
            if r.area >= 0.85 * area_vb and any(
                o is not r and r.contains(o.representative_point())
                for o in anillos
            ):
                continue
            filtrados.append(r)
        anillos = filtrados
    if not anillos:
        return [], 0.0, area_vb

    x0 = min(r.bounds[0] for r in anillos)
    x1 = max(r.bounds[2] for r in anillos)
    return anillos, (x1 - x0), area_vb


def piezas_desde_svg(svg_bytes: bytes, ancho_real_cm: float,
                     fuente: str, copias: int = 1) -> list[PiezaNest]:
    """Extrae piezas con huecos. `ancho_real_cm` = ancho real del diseño
    completo (bbox conjunto de las piezas), igual que en el cotizador."""
    anillos, ancho_svg, _area_vb = _muestrear_anillos(svg_bytes)
    if not anillos or ancho_svg <= 0 or ancho_real_cm <= 0:
        return []
    esc = ancho_real_cm / ancho_svg
    anillos = [affinity.scale(r, xfact=esc, yfact=esc, origin=(0, 0))
               for r in anillos]
    anillos = [r for r in anillos if r.area >= MIN_AREA_CM2]
    anillos.sort(key=lambda r: -r.area)

    # Profundidad de contención: par = pieza, impar = hueco de la pieza
    # contenedora más chica (soporta anidado pieza-dentro-de-hueco).
    prof = []
    for i, r in enumerate(anillos):
        pt = r.representative_point()
        d = sum(
            1 for j, otro in enumerate(anillos)
            if j != i and otro.area > r.area
            and otro.bounds[0] <= pt.x <= otro.bounds[2]
            and otro.bounds[1] <= pt.y <= otro.bounds[3]
            and otro.contains(pt)
        )
        prof.append(d)

    piezas: list[Polygon] = []
    for i, r in enumerate(anillos):
        if prof[i] % 2 == 1:
            continue
        huecos = []
        for j, h in enumerate(anillos):
            if prof[j] != prof[i] + 1:
                continue
            hp = h.representative_point()
            if not r.contains(hp):
                continue
            # el hueco pertenece a la pieza contenedora MÁS CHICA de su nivel
            dueno_ok = all(
                not (k != i and prof[k] == prof[i] and o.area < r.area
                     and o.contains(hp))
                for k, o in enumerate(anillos)
            )
            if dueno_ok:
                huecos.append(list(h.exterior.coords))
        p = Polygon(list(r.exterior.coords), huecos)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            piezas.append(p)

    out: list[PiezaNest] = []
    for c in range(max(1, copias)):
        for n, p in enumerate(piezas, start=1):
            et = f"{fuente} p{n}" + (f" ({c + 1})" if copias > 1 else "")
            out.append(PiezaNest(poly=p, etiqueta=et, fuente=fuente))
    return out


# ─── 2. Nesting ──────────────────────────────────────────────────────────────

def _rasterizar(poly: Polygon, res_cm: float) -> tuple[np.ndarray, float, float]:
    """Polígono -> máscara uint8 con huecos en 0, trasladada a su bbox.
    Devuelve (mask, offx_cm, offy_cm) = coordenada real del pixel (0,0)."""
    minx, miny, maxx, maxy = poly.bounds
    w = int(math.ceil((maxx - minx) / res_cm)) + 1
    h = int(math.ceil((maxy - miny) / res_cm)) + 1
    mask = np.zeros((h, w), np.uint8)

    def ring_px(coords):
        # rint (no floor): el floor sesgaba la máscara hasta 1 px por lado
        return np.rint(np.array([[(x - minx) / res_cm, (y - miny) / res_cm]
                                 for x, y in coords])).astype(np.int32)

    geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
    for g in geoms:
        cv2.fillPoly(mask, [ring_px(g.exterior.coords)], 1)
        for hueco in g.interiors:
            cv2.fillPoly(mask, [ring_px(hueco.coords)], 0)
    return mask, minx, miny


def _dilatar(mask: np.ndarray, r_px: int) -> np.ndarray:
    if r_px <= 0:
        return mask
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r_px + 1, 2 * r_px + 1))
    return cv2.dilate(mask, k)


class _Lamina:
    def __init__(self, idx: int, w_cm: float, h_cm: float,
                 margen_cm: float, res_cm: float):
        self.res = res_cm
        self.gw = int(round(w_cm / res_cm))
        self.gh = int(round(h_cm / res_cm))
        m = max(1, int(round(margen_cm / res_cm)))
        self.occ = np.zeros((self.gh, self.gw), np.float32)
        self.occ[:m, :] = 1
        self.occ[-m:, :] = 1
        self.occ[:, :m] = 1
        self.occ[:, -m:] = 1
        self.datos = LaminaNest(idx=idx, ancho_cm=w_cm, alto_cm=h_cm)

    def intentar(self, pz: PiezaNest, mascaras: list) -> bool:
        """mascaras: [(ang, raw, tpl, offx, offy, rot_poly), ...] cacheadas.
        `tpl` = raw acolchonada con gap_px y dilatada (el gap viaja con el
        candidato); `raw` se estampa sin dilatar para dejar huecos usables."""
        mejor = None
        for ang, raw, tpl, offx, offy, rot in mascaras:
            th, tw = tpl.shape
            if th > self.gh or tw > self.gw:
                continue
            mapa = cv2.matchTemplate(self.occ, tpl, cv2.TM_CCORR)
            ys, xs = np.where(mapa < 0.5)
            if len(ys) == 0:
                continue
            i = np.lexsort((xs, ys))[0]  # bottom-left: min y, luego min x
            y, x = int(ys[i]), int(xs[i])
            score = (y + th, x)
            if mejor is None or score < mejor[0]:
                mejor = (score, ang, x, y, raw, tpl, offx, offy, rot)
        if mejor is None:
            return False
        _, ang, x, y, raw, tpl, offx, offy, rot = mejor
        # posición de la máscara cruda dentro del template acolchonado
        gp = (tpl.shape[1] - raw.shape[1]) // 2
        ry, rx = y + gp, x + gp
        mh, mw = raw.shape
        zona = self.occ[ry:ry + mh, rx:rx + mw]
        np.maximum(zona, raw.astype(np.float32), out=zona)
        movida = affinity.translate(rot, xoff=rx * self.res - offx,
                                    yoff=ry * self.res - offy)
        self.datos.colocaciones.append(
            Colocacion(poly=movida, etiqueta=pz.etiqueta,
                       fuente=pz.fuente, angulo=ang))
        return True


def nest(piezas: list[PiezaNest], ancho_cm: float, alto_cm: float,
         gap_cm: float = 0.5, margen_cm: float = 1.0,
         paso_angulo: int = PASO_ANGULO,
         res_cm: float = RES_CM) -> tuple[list[LaminaNest], list[PiezaNest]]:
    """Acomoda las piezas. Devuelve (láminas, piezas_que_no_caben)."""
    if len(piezas) > MAX_PIEZAS:
        raise ValueError(f"Demasiadas piezas ({len(piezas)}); máximo {MAX_PIEZAS}")
    ancho_cm = min(ancho_cm, MAX_LADO_CM)
    alto_cm = min(alto_cm, MAX_LADO_CM)
    # +1 px de seguridad: absorbe el error de rasterización para que la
    # separación REAL entre contornos nunca baje del gap pedido
    gap_px = max(1, int(math.ceil(gap_cm / res_cm)) + 1)
    angulos = list(range(0, 360, max(1, paso_angulo)))

    orden = sorted(piezas, key=lambda p: -p.area)
    laminas: list[_Lamina] = []
    sin_lugar: list[PiezaNest] = []
    cache_masc: dict[int, list] = {}

    for pz in orden:
        key = id(pz.poly)   # copias comparten el MISMO objeto Polygon
        mascaras = cache_masc.get(key)
        if mascaras is None:
            mascaras = []
            for ang in angulos:
                rot = affinity.rotate(pz.poly, ang, origin="centroid") if ang \
                    else pz.poly
                raw, offx, offy = _rasterizar(rot, res_cm)
                # acolchonar ANTES de dilatar: cv2.dilate recorta en los
                # bordes del arreglo y el gap se perdería en el contorno
                acolch = np.zeros((raw.shape[0] + 2 * gap_px,
                                   raw.shape[1] + 2 * gap_px), np.uint8)
                acolch[gap_px:-gap_px, gap_px:-gap_px] = raw
                tpl = _dilatar(acolch, gap_px).astype(np.float32)
                mascaras.append((ang, raw, tpl, offx, offy, rot))
            cache_masc[key] = mascaras

        for lam in laminas:
            if lam.intentar(pz, mascaras):
                break
        else:
            lam = _Lamina(len(laminas) + 1, ancho_cm, alto_cm, margen_cm, res_cm)
            if lam.intentar(pz, mascaras):
                laminas.append(lam)
            else:
                sin_lugar.append(pz)

    return [lam.datos for lam in laminas], sin_lugar


# ─── 3. Salidas: SVG, DXF ────────────────────────────────────────────────────

PALETA_NEST = ["#2CC5EC", "#ED4E97", "#F5C93B", "#41C983", "#9A7DF5",
               "#F2865F", "#5FA8F2", "#E36DC9", "#8FD14F", "#F25F5F"]


def _poly_d(poly: Polygon) -> str:
    def ring(coords):
        return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in coords) + " Z"
    d = ring(poly.exterior.coords)
    for h in poly.interiors:
        d += " " + ring(h.coords)
    return d


def lamina_svg(lam: LaminaNest, margen_cm: float = 1.0,
               con_etiquetas: bool = True) -> str:
    """SVG de la lámina acomodada (unidades = cm). Sirve de preview en la UI
    y de archivo de corte para plotter."""
    w, h = lam.ancho_cm, lam.alto_cm
    cuerpo = [
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#FDFCF8" '
        f'stroke="#444" stroke-width="0.3"/>',
        f'<rect x="{margen_cm}" y="{margen_cm}" width="{w - 2 * margen_cm}" '
        f'height="{h - 2 * margen_cm}" fill="none" stroke="#bbb" '
        f'stroke-width="0.12" stroke-dasharray="2 2"/>',
    ]
    if 0 < lam.franja_cm < h * 0.98:
        yl = lam.franja_cm
        cuerpo.append(f'<line x1="0" y1="{yl:.1f}" x2="{w}" y2="{yl:.1f}" '
                      f'stroke="#C93077" stroke-width="0.3" stroke-dasharray="3 2"/>')
    for i, c in enumerate(lam.colocaciones):
        color = PALETA_NEST[i % len(PALETA_NEST)]
        geoms = c.poly.geoms if c.poly.geom_type == "MultiPolygon" else [c.poly]
        for g in geoms:
            cuerpo.append(f'<path d="{_poly_d(g)}" fill="{color}" '
                          f'fill-opacity="0.72" fill-rule="evenodd" '
                          f'stroke="#222" stroke-width="0.2"/>')
        if con_etiquetas:
            pt = c.poly.representative_point()
            cuerpo.append(f'<text x="{pt.x:.1f}" y="{pt.y:.1f}" font-size="3.2" '
                          f'fill="#111" text-anchor="middle" '
                          f'font-family="monospace">{i + 1}</text>')
    vb_h = h + 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="-1 -1 {w + 2} {vb_h}">' + "".join(cuerpo) + "</svg>")


def lamina_dxf(lam: LaminaNest, incluir_borde: bool = True) -> bytes:
    """DXF de la lámina en MILÍMETROS (estándar de taller). Capas:
    CORTE = contornos de pieza (y sus huecos), LAMINA = borde de la lámina,
    ETIQUETAS = número de pieza (texto, no se corta)."""
    doc = ezdxf.new("R2010", setup=False)
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    doc.layers.add("CORTE", color=1)      # rojo
    doc.layers.add("LAMINA", color=8)     # gris
    doc.layers.add("ETIQUETAS", color=3)  # verde

    def mm(v: float) -> float:
        return round(v * 10.0, 3)

    if incluir_borde:
        w, h = mm(lam.ancho_cm), mm(lam.alto_cm)
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)],
                           close=True, dxfattribs={"layer": "LAMINA"})

    for i, c in enumerate(lam.colocaciones):
        geoms = c.poly.geoms if c.poly.geom_type == "MultiPolygon" else [c.poly]
        for g in geoms:
            # DXF con Y hacia arriba: se espeja verticalmente respecto al alto
            ext = [(mm(x), mm(lam.alto_cm - y)) for x, y in g.exterior.coords]
            msp.add_lwpolyline(ext, close=True, dxfattribs={"layer": "CORTE"})
            for hueco in g.interiors:
                pts = [(mm(x), mm(lam.alto_cm - y)) for x, y in hueco.coords]
                msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CORTE"})
        pt = c.poly.representative_point()
        txt = msp.add_text(str(i + 1), dxfattribs={"layer": "ETIQUETAS",
                                                   "height": 30.0})
        txt.dxf.insert = (mm(pt.x), mm(lam.alto_cm - pt.y))

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
