"""Análisis topológico de paths SVG para el planeador de neón.

Este módulo cumple la regla del Manual §2.3 "No confundir topología visual
con despiece". Antes de decidir cuántas piezas físicas necesita una letra,
hay que ANALIZAR su topología — no basta con contar <path> del SVG.

Ejemplos que el motor debe manejar correctamente:
  - Letra A dibujada como 1 <path> cerrado (contorno + travesaño en un solo
    trazo) → topológicamente 1 loop_con_travesano → físicamente 2 piezas
  - Letra P dibujada como 2 <path> (poste + óvalo) → topológicamente 2
    componentes conectables → 1 pieza física con 2 alivios (Manual §6.P +
    Cuaderno Microtécnica F)
  - Letra X dibujada como 1 <path> con self-crossing → 2 piezas diagonales
    que se cruzan SIN unión eléctrica (Manual §6.X)
  - Letra O como path cerrado → 1 pieza con seam artificial en enlace natural
    (Manual §6.O + Cuaderno Microtécnica E)

NO usa OCR ni reconocimiento de letras — es análisis puramente geométrico
sobre la polilínea, robusto a fuentes decorativas.

Salida principal: `analizar(path_info) → TopoAnalysis` con:
  - tipo topológico clasificado
  - subpaths detectados (M internos)
  - esquinas duras localizadas (ángulo, coordenada, radio local)
  - intersecciones internas (self-crossings)
  - holes / agujeros por winding
  - bbox de cada subcomponente

`descomponer_en_piezas_fisicas(topo, perfil) → list[SubPieza]` traduce la
topología en piezas fabricables según reglas del Manual + Cuaderno.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

try:
    from shapely.geometry import LineString, Point, Polygon
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


# ─── ENUMS ───────────────────────────────────────────────────────────────────

class TipoTopologico(str, Enum):
    """Clasificación topológica de un path SVG. Determina la estrategia de
    descomposición en piezas físicas (Manual §5 matriz A-Z + §2.3)."""
    LOOP_SIMPLE          = "loop_simple"           # O, D — 1 pieza cerrada con seam
    LOOP_CON_TRAVESANO   = "loop_con_travesano"    # A, P, R, B, Q — loop + apéndice
    TRAZO_ABIERTO        = "trazo_abierto"         # C, J, L, S, U — sin cierre
    TRAZO_CON_ESQUINAS   = "trazo_con_esquinas"    # Z, N — abierto con dobleces marcados
    ZIGZAG               = "zigzag"                # M, W — múltiples cambios de dirección
    INTERSECTION_CROSSING = "intersection_crossing" # X, Y — self-crossing
    RAMIFICADO           = "ramificado"            # E, F, T, H, K — 3+ ramas desde nodo
    MULTI_SUBPATH        = "multi_subpath"         # M internos → varias islas
    UNKNOWN              = "unknown"


# ─── DATACLASSES ─────────────────────────────────────────────────────────────

@dataclass
class Esquina:
    """Punto donde el trazo cambia de dirección de forma marcada.
    Candidato a V_RELIEF_90 si el ángulo es agudo y el radio efectivo < mínimo."""
    coord_svg: tuple[float, float]
    angulo_deg: float             # ángulo entre vector entrante y saliente (0 = recta)
    radio_local_px: float         # radio del círculo por 3 puntos alrededor
    subpath_idx: int              # a qué subpath pertenece (0 si es único)
    idx_en_subpath: int           # posición dentro del subpath

    @property
    def es_esquina_dura(self) -> bool:
        """Ángulo >= 45° y radio pequeño = esquina que requiere V_RELIEF_90."""
        return self.angulo_deg >= 45.0


@dataclass
class Interseccion:
    """Cruce interno del propio path (self-crossing) o entre subpaths.
    Se maneja con CROSSING_RELIEF (Cuaderno Microtécnica A) — un tramo se
    monta visualmente sobre el otro sin cortar eléctricamente."""
    coord_svg: tuple[float, float]
    subpath_a_idx: int
    subpath_b_idx: int           # puede ser == subpath_a_idx si es self-crossing


@dataclass
class Subpath:
    """Un subpath dentro de un <path> SVG (separado por M internos)."""
    idx: int
    puntos: list[tuple[float, float]]
    is_closed: bool
    longitud_px: float
    bbox: dict                    # {x, y, w, h}


@dataclass
class TopoAnalysis:
    """Análisis topológico completo de un path SVG."""
    path_id: str
    tipo: TipoTopologico
    subpaths: list[Subpath] = field(default_factory=list)
    esquinas: list[Esquina] = field(default_factory=list)
    intersecciones: list[Interseccion] = field(default_factory=list)
    n_holes: int = 0                    # agujeros detectados por winding
    longitud_total_px: float = 0.0
    bbox_global: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SubPieza:
    """Una pieza física candidata resultante de la descomposición topológica.
    Es la entrada al motor de planeación en `neon_plano.py`. Cada SubPieza
    se convertirá en un objeto `Pieza` del plan final."""
    # Identidad
    subpath_ids: list[int] = field(default_factory=list)   # qué subpaths agrupa
    path_id_svg: str = ""
    # Geometría
    puntos: list[tuple[float, float]] = field(default_factory=list)
    is_closed: bool = False
    longitud_px: float = 0.0
    bbox: dict = field(default_factory=dict)
    # Análisis heredado
    esquinas_duras: list[Esquina] = field(default_factory=list)
    # Estrategia de fabricación (asignada por descomponer_en_piezas_fisicas)
    tecnica_dominante: str = ""       # DIRECT_CONTINUOUS, CLOSED_SEAM, etc.
    tecnicas_aplicadas: list[dict] = field(default_factory=list)  # eventos con params
    notas: list[str] = field(default_factory=list)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polyline_length(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def _bbox_from_points(points: list[tuple[float, float]]) -> dict:
    if not points:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"x": min(xs), "y": min(ys),
            "w": max(xs) - min(xs), "h": max(ys) - min(ys)}


def _radio_por_3puntos(a: tuple[float, float],
                       b: tuple[float, float],
                       c: tuple[float, float]) -> float | None:
    """Radio del círculo que pasa por 3 puntos. None si colineales."""
    ax, ay = a; bx, by = b; cx, cy = c
    area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    if area2 < 1e-6:
        return None
    d_ab = math.hypot(bx - ax, by - ay)
    d_bc = math.hypot(cx - bx, cy - by)
    d_ca = math.hypot(ax - cx, ay - cy)
    return (d_ab * d_bc * d_ca) / (2.0 * area2)


def _angulo_entre_vectores(v1: tuple[float, float], v2: tuple[float, float]) -> float:
    """Ángulo en grados entre 2 vectores. 0 = paralelos, 180 = opuestos."""
    m1 = math.hypot(*v1); m2 = math.hypot(*v2)
    if m1 <= 0 or m2 <= 0:
        return 0.0
    cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2)))
    return math.degrees(math.acos(cos_a))


# ─── ANÁLISIS PRINCIPAL ──────────────────────────────────────────────────────

def analizar(path_info) -> TopoAnalysis:
    """Analiza topológicamente un PathInfo del SVG parseado.

    Args:
        path_info: objeto con .polyline_px (lista de subpaths), .is_closed,
                   .svg_id, .id, .bbox

    Returns:
        TopoAnalysis con clasificación + esquinas + intersecciones + subpaths.
    """
    svg_id = getattr(path_info, "svg_id", "") or getattr(path_info, "id", "")
    polyline_px = getattr(path_info, "polyline_px", []) or []
    is_closed_pi = bool(getattr(path_info, "is_closed", False))

    topo = TopoAnalysis(path_id=svg_id, tipo=TipoTopologico.UNKNOWN)

    # 1. Extraer subpaths con metadatos
    for i, sp in enumerate(polyline_px):
        if not sp or len(sp) < 2:
            continue
        # Un subpath se considera cerrado si su primer y último punto coinciden
        # (o si el path original lo dice y solo hay un subpath).
        sub_closed = (_dist(sp[0], sp[-1]) < 0.5) or (is_closed_pi and len(polyline_px) == 1)
        topo.subpaths.append(Subpath(
            idx=i, puntos=list(sp), is_closed=sub_closed,
            longitud_px=_polyline_length(sp),
            bbox=_bbox_from_points(sp),
        ))
    topo.longitud_total_px = sum(s.longitud_px for s in topo.subpaths)
    if topo.subpaths:
        all_pts = [pt for s in topo.subpaths for pt in s.puntos]
        topo.bbox_global = _bbox_from_points(all_pts)

    if not topo.subpaths:
        return topo  # unknown, sin puntos

    # 2. Detectar esquinas duras y radios apretados en cada subpath
    _detectar_esquinas(topo)

    # 3. Detectar holes por winding (para loop_con_travesano tipo A, B)
    if HAS_SHAPELY:
        _detectar_holes(topo)

    # 4. Detectar intersecciones (self-crossing = X, Y; cross-subpath)
    if HAS_SHAPELY:
        _detectar_intersecciones(topo)

    # 5. Clasificar tipo topológico
    topo.tipo = _clasificar_tipo(topo)

    return topo


def _detectar_esquinas(topo: TopoAnalysis,
                       angulo_min_deg: float = 45.0,
                       ventana_max: int = 2) -> None:
    """Localiza puntos con cambio brusco de dirección. Alimenta candidatos
    a V_RELIEF_90 en la fase de descomposición.

    Usa ventana adaptativa (min 1, max `ventana_max`) para que polilíneas
    cortas (ej: L con 3 puntos, Z con 4 puntos) también se analicen.
    """
    for sp in topo.subpaths:
        pts = sp.puntos
        n = len(pts)
        if n < 3:
            continue
        # Ventana efectiva: no puede exceder (n-1)//2
        ventana = min(ventana_max, max(1, (n - 1) // 2))
        last_i = -999
        for i in range(ventana, n - ventana):
            v1 = (pts[i][0] - pts[i - ventana][0], pts[i][1] - pts[i - ventana][1])
            v2 = (pts[i + ventana][0] - pts[i][0], pts[i + ventana][1] - pts[i][1])
            ang = _angulo_entre_vectores(v1, v2)
            if ang < angulo_min_deg:
                continue
            # Cooldown para no repetir en la misma esquina densamente sampleada
            if (i - last_i) < max(2, ventana * 2):
                continue
            r_px = _radio_por_3puntos(pts[i - ventana], pts[i], pts[i + ventana])
            topo.esquinas.append(Esquina(
                coord_svg=(pts[i][0], pts[i][1]),
                angulo_deg=round(ang, 1),
                radio_local_px=round(r_px, 2) if r_px else 0.0,
                subpath_idx=sp.idx,
                idx_en_subpath=i,
            ))
            last_i = i


def _detectar_holes(topo: TopoAnalysis) -> None:
    """Cuenta agujeros topológicos. Un loop_con_travesano tipo A tiene 1 hole
    (el hueco entre las dos patas + travesaño). Un P tiene 1 hole (el óvalo)."""
    poligonos = []
    for sp in topo.subpaths:
        if not sp.is_closed or len(sp.puntos) < 4:
            continue
        try:
            poly = Polygon(sp.puntos)
            if poly.is_valid and poly.area > 1e-3:
                poligonos.append(poly)
        except Exception:
            pass
    if not poligonos:
        return
    # Si un polígono está DENTRO de otro, cuenta como hole
    for i, pa in enumerate(poligonos):
        for j, pb in enumerate(poligonos):
            if i == j:
                continue
            if pa.contains(pb):
                topo.n_holes += 1


def _detectar_intersecciones(topo: TopoAnalysis) -> None:
    """Detecta self-crossings y cross-subpath (indicador de X, Y, ★, etc.)."""
    # Convertimos cada subpath a LineString
    lines = []
    for sp in topo.subpaths:
        if len(sp.puntos) < 2:
            continue
        try:
            lines.append((sp.idx, LineString(sp.puntos)))
        except Exception:
            pass
    for i, (idx_a, la) in enumerate(lines):
        # Self-intersection (X dibujada como 1 solo path)
        if not la.is_simple:
            # shapely.ops no da directo los puntos — buscamos por chunk vs chunk
            inters = _self_intersections(la)
            for pt in inters:
                topo.intersecciones.append(Interseccion(
                    coord_svg=(pt.x, pt.y),
                    subpath_a_idx=idx_a, subpath_b_idx=idx_a,
                ))
        # Cross-subpath (X dibujada como 2 paths separados que se cruzan)
        for j, (idx_b, lb) in enumerate(lines[i + 1:], start=i + 1):
            inter = la.intersection(lb)
            if inter.is_empty:
                continue
            if inter.geom_type == "Point":
                topo.intersecciones.append(Interseccion(
                    coord_svg=(inter.x, inter.y),
                    subpath_a_idx=idx_a, subpath_b_idx=idx_b,
                ))
            elif inter.geom_type == "MultiPoint":
                for g in inter.geoms:
                    topo.intersecciones.append(Interseccion(
                        coord_svg=(g.x, g.y),
                        subpath_a_idx=idx_a, subpath_b_idx=idx_b,
                    ))


def _self_intersections(line: LineString) -> list[Point]:
    """Aproximación pragmática de self-intersections chunkeando el LineString.
    shapely no expone directamente esto; hacemos comparación por segmentos."""
    coords = list(line.coords)
    if len(coords) < 4:
        return []
    puntos = []
    for i in range(len(coords) - 1):
        seg_a = LineString([coords[i], coords[i + 1]])
        for j in range(i + 2, len(coords) - 1):
            # Evitar chequeo con el segmento anterior (comparte punto)
            if j == i + 1:
                continue
            seg_b = LineString([coords[j], coords[j + 1]])
            inter = seg_a.intersection(seg_b)
            if inter.is_empty:
                continue
            if inter.geom_type == "Point":
                puntos.append(inter)
    return puntos


def _clasificar_tipo(topo: TopoAnalysis) -> TipoTopologico:
    """Regla de clasificación según features detectados. Coherente con la
    matriz A-Z del Manual §5 pero sin asumir la letra específica."""
    n_sub = len(topo.subpaths)
    if n_sub == 0:
        return TipoTopologico.UNKNOWN

    n_cerrados = sum(1 for s in topo.subpaths if s.is_closed)
    n_abiertos = n_sub - n_cerrados
    n_esq = sum(1 for e in topo.esquinas if e.es_esquina_dura)
    n_inter = len(topo.intersecciones)

    # Multi-subpath prioritario (varias piezas separadas dibujadas en 1 <path>)
    if n_sub > 1 and n_inter == 0:
        # Si son 1 cerrado grande + 1 abierto = probablemente loop_con_travesano (A)
        if n_cerrados == 1 and n_abiertos >= 1:
            return TipoTopologico.LOOP_CON_TRAVESANO
        # 2 o más abiertos que no se cruzan = ramificado o multi_subpath
        return TipoTopologico.MULTI_SUBPATH

    # Self-crossing = X, Y, ★
    if n_inter > 0:
        return TipoTopologico.INTERSECTION_CROSSING

    # Un solo subpath cerrado sin ramificaciones
    if n_sub == 1 and topo.subpaths[0].is_closed:
        if topo.n_holes >= 1:
            return TipoTopologico.LOOP_CON_TRAVESANO   # P, B, D con hole visible
        return TipoTopologico.LOOP_SIMPLE              # O

    # Un solo subpath abierto
    if n_sub == 1 and not topo.subpaths[0].is_closed:
        if n_esq >= 3:
            return TipoTopologico.ZIGZAG               # M, W
        if n_esq >= 1:
            return TipoTopologico.TRAZO_CON_ESQUINAS   # Z, N, L
        return TipoTopologico.TRAZO_ABIERTO            # C, S, U, J

    return TipoTopologico.UNKNOWN


# ─── DESCOMPOSICIÓN EN PIEZAS FÍSICAS ────────────────────────────────────────

def descomponer_en_piezas_fisicas(topo: TopoAnalysis, perfil: dict) -> list[SubPieza]:
    """Traduce la topología a piezas físicas fabricables aplicando las reglas
    del Manual §5 (matriz A-Z) + §2.2 (buscar menor cantidad razonable).

    Reglas clave:
      LOOP_SIMPLE            → 1 pieza cerrada con CLOSED_SEAM
      LOOP_CON_TRAVESANO     → 1 pieza si radios permiten (P con SILICONE_RELIEF
                                 doble), 2 piezas si no (A: contorno + travesaño)
      TRAZO_ABIERTO          → 1 pieza DIRECT_CONTINUOUS
      TRAZO_CON_ESQUINAS     → 1 pieza + V_RELIEF_90 en cada esquina dura
      ZIGZAG                 → 1 pieza + V_RELIEF_90 en cada vértice si radio<mín
      INTERSECTION_CROSSING  → 2 piezas separadas + CROSSING_RELIEF en el cruce
      MULTI_SUBPATH          → 1 pieza por subpath (islas independientes)
      RAMIFICADO             → 1 pieza + puentes en las ramas
    """
    radio_min_px = 0.0
    escala_cm_por_px = perfil.get("_escala_cm_por_px", 1.0)
    if perfil.get("radio_min_cm") and escala_cm_por_px > 0:
        radio_min_px = float(perfil["radio_min_cm"]) / escala_cm_por_px

    if topo.tipo == TipoTopologico.LOOP_SIMPLE:
        return [_pieza_loop_simple(topo)]
    if topo.tipo == TipoTopologico.LOOP_CON_TRAVESANO:
        return _pieza_loop_con_travesano(topo, radio_min_px)
    if topo.tipo == TipoTopologico.TRAZO_ABIERTO:
        return [_pieza_trazo_abierto(topo)]
    if topo.tipo == TipoTopologico.TRAZO_CON_ESQUINAS:
        return [_pieza_trazo_con_esquinas(topo, radio_min_px)]
    if topo.tipo == TipoTopologico.ZIGZAG:
        return [_pieza_zigzag(topo, radio_min_px)]
    if topo.tipo == TipoTopologico.INTERSECTION_CROSSING:
        return _pieza_intersection(topo)
    if topo.tipo == TipoTopologico.MULTI_SUBPATH:
        return _piezas_multi_subpath(topo, radio_min_px)
    # Fallback: una pieza por subpath
    return _piezas_multi_subpath(topo, radio_min_px)


# ─── FÁBRICAS DE SUBPIEZA POR TIPO TOPOLÓGICO ────────────────────────────────

def _pieza_loop_simple(topo: TopoAnalysis) -> SubPieza:
    """O, D — 1 pieza cerrada. Aplicará CLOSED_SEAM en el planeador."""
    sp = topo.subpaths[0]
    return SubPieza(
        subpath_ids=[sp.idx], path_id_svg=topo.path_id,
        puntos=list(sp.puntos), is_closed=True,
        longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
        tecnica_dominante="CLOSED_SEAM",
        notas=[f"Loop simple: {int(sp.longitud_px)}px de contorno, "
               f"requiere seam artificial (Manual §6.O / Cuaderno Microtécnica E)"],
    )


def _pieza_loop_con_travesano(topo: TopoAnalysis, radio_min_px: float) -> list[SubPieza]:
    """A, P, B, R, Q — la decisión es: 1 pieza con alivios de silicona vs.
    2 piezas separadas. Depende de si los radios locales permiten fabricar la
    transición de un tramo al otro sin cortar la FPCB.

    Estrategia (Manual §6.P + Cuaderno Microtécnica F):
      - Si el path SVG es 1 subpath cerrado y hay 1 hole → intentar 1 pieza
        continua con SILICONE_RELIEF doble en la transición
      - Si son múltiples subpaths (dibujados separados) → tratarlos como
        piezas independientes conectadas con LETTER_BRIDGE
    """
    if len(topo.subpaths) == 1 and topo.n_holes >= 1:
        # Ej.: A dibujada como 1 solo path cerrado con hole interior
        # 1 pieza + 2 SILICONE_RELIEF en la transición contorno↔travesaño
        sp = topo.subpaths[0]
        pieza = SubPieza(
            subpath_ids=[sp.idx], path_id_svg=topo.path_id,
            puntos=list(sp.puntos), is_closed=True,
            longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
            tecnica_dominante="SILICONE_RELIEF",
            tecnicas_aplicadas=[
                {"tipo": "SILICONE_RELIEF", "n_alivios": 2,
                 "razon": "loop con travesaño interno — 2 alivios parciales para "
                          "recorrer contorno y travesaño con la misma tira "
                          "(Cuaderno Microtécnica F, letra P)"},
            ],
            notas=[f"Loop con travesaño: {topo.n_holes} hole(s) detectado(s)"],
        )
        # Si hay esquinas duras adicionales, sumarlas como V_RELIEF_90
        for e in topo.esquinas:
            if e.es_esquina_dura and e.radio_local_px < radio_min_px:
                pieza.tecnicas_aplicadas.append({
                    "tipo": "V_RELIEF_90",
                    "coord_svg": e.coord_svg,
                    "radio_px": e.radio_local_px,
                    "angulo_deg": e.angulo_deg,
                })
        return [pieza]
    # Dibujado como múltiples subpaths → una pieza por subpath
    return _piezas_multi_subpath(topo, radio_min_px)


def _pieza_trazo_abierto(topo: TopoAnalysis) -> SubPieza:
    """C, S, U, J — 1 pieza abierta continua."""
    sp = topo.subpaths[0]
    return SubPieza(
        subpath_ids=[sp.idx], path_id_svg=topo.path_id,
        puntos=list(sp.puntos), is_closed=False,
        longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
        tecnica_dominante="DIRECT_CONTINUOUS",
    )


def _pieza_trazo_con_esquinas(topo: TopoAnalysis, radio_min_px: float) -> SubPieza:
    """Z, N, L — 1 pieza con V_RELIEF_90 en cada esquina dura.

    Criterio: si el ángulo entre vectores entrada/salida es ≥ 60°, la esquina
    requiere V_RELIEF_90 independiente del "radio local" calculado — porque
    con 3 puntos que forman ángulo agudo el radio matemático es un artefacto
    (grande) que no representa el radio físico de doblez (~0 en vértice puntiagudo).
    El radio_local_px solo se usa para clasificar curvas suaves vs esquinas."""
    sp = topo.subpaths[0]
    pieza = SubPieza(
        subpath_ids=[sp.idx], path_id_svg=topo.path_id,
        puntos=list(sp.puntos), is_closed=sp.is_closed,
        longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
        tecnica_dominante="DIRECT_CONTINUOUS",
    )
    for e in topo.esquinas:
        # V_RELIEF_90 se aplica siempre en esquinas duras (>=60° entre vectores)
        # porque físicamente un vértice puntiagudo tiene radio efectivo cero.
        if e.angulo_deg >= 60.0:
            pieza.tecnicas_aplicadas.append({
                "tipo": "V_RELIEF_90",
                "coord_svg": e.coord_svg,
                "radio_px": e.radio_local_px,
                "angulo_deg": e.angulo_deg,
            })
    return pieza


def _pieza_zigzag(topo: TopoAnalysis, radio_min_px: float) -> SubPieza:
    """M, W — 1 pieza continua + V_RELIEF_90 en cada vértice apretado."""
    return _pieza_trazo_con_esquinas(topo, radio_min_px)


def _pieza_intersection(topo: TopoAnalysis) -> list[SubPieza]:
    """X, Y — 2 piezas que se cruzan visualmente SIN unión eléctrica.
    El cruce se marca con CROSSING_RELIEF (Cuaderno Microtécnica A)."""
    piezas: list[SubPieza] = []
    for sp in topo.subpaths:
        pieza = SubPieza(
            subpath_ids=[sp.idx], path_id_svg=topo.path_id,
            puntos=list(sp.puntos), is_closed=sp.is_closed,
            longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
            tecnica_dominante="DIRECT_CONTINUOUS",
        )
        # Marcar cruces que afectan a este subpath
        for it in topo.intersecciones:
            if sp.idx in (it.subpath_a_idx, it.subpath_b_idx):
                pieza.tecnicas_aplicadas.append({
                    "tipo": "CROSSING_RELIEF",
                    "coord_svg": it.coord_svg,
                    "razon": "cruce visual sin unión eléctrica — un tramo se "
                             "monta sobre el otro con corte en silicona posterior "
                             "(Cuaderno Microtécnica A)",
                })
        piezas.append(pieza)
    return piezas


def _piezas_multi_subpath(topo: TopoAnalysis, radio_min_px: float) -> list[SubPieza]:
    """Cada subpath = 1 pieza independiente (islas, tildes, puntos)."""
    piezas: list[SubPieza] = []
    for sp in topo.subpaths:
        pieza = SubPieza(
            subpath_ids=[sp.idx], path_id_svg=topo.path_id,
            puntos=list(sp.puntos), is_closed=sp.is_closed,
            longitud_px=sp.longitud_px, bbox=dict(sp.bbox),
            tecnica_dominante="CLOSED_SEAM" if sp.is_closed else "DIRECT_CONTINUOUS",
        )
        # Esquinas duras dentro de este subpath
        for e in topo.esquinas:
            if (e.subpath_idx == sp.idx and e.es_esquina_dura
                    and (radio_min_px <= 0 or e.radio_local_px < radio_min_px)):
                pieza.tecnicas_aplicadas.append({
                    "tipo": "V_RELIEF_90",
                    "coord_svg": e.coord_svg,
                    "radio_px": e.radio_local_px,
                    "angulo_deg": e.angulo_deg,
                })
        piezas.append(pieza)
    return piezas
