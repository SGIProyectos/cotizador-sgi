"""Planeador de construcción para anuncios de neón LED (SGI).

Convierte geometría vectorial (SVG paths) en una SOLUCIÓN FÍSICA fabricable:
piezas físicas continuas, terminales, uniones eléctricas, cable oculto,
técnicas especiales por pieza y advertencias.

Basado en:
- Manual Técnico "Algoritmo experto de fabricación de neón flex" (§12 pseudocódigo)
- Cuaderno Práctico IA (schema de labels + microtécnicas A-F)

Es INDEPENDIENTE del motor de costos (`neon_calculator.py`). Ese cotiza;
este planifica. Ambos alimentan el endpoint /api/cotizar/neon y los PDFs.

Iteración actual: v0 (skeleton determinista simple)
- 1 pieza por path del SVG (no fusiona letras vecinas en 1 tira)
- Terminales en extremos de la polilínea (start/end de polyline_px)
- Paths cerrados → 1 terminal seam en punto más a la derecha
- Uniones: pares vecinos por proximidad de bbox (cadena lineal, no MST)
- Sin V_RELIEF_90, sin SILICONE_RELIEF (requieren análisis de curvatura)
- Cable posterior: polilínea recta terminal→terminal (hidden_ratio=1.0 asumido)
- Sin snap a cut_step_cm (los terminales quedan donde están geométricamente)

Iteración v1 (siguiente): shapely para radios locales, seam point óptimo,
snap a marca de corte válida, detección de intersecciones.

Iteración v2: MST real con Kruskal sobre grafo completo de terminales
compatibles + pesos calibrables de la función de costo.

Uso desde main.py:
    from neon_plano import construir_plan
    plan = construir_plan(path_infos, perfil=perfil_dict)
    # plan es dataclass; serializar con dataclasses.asdict(plan)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ─── ENUMS ───────────────────────────────────────────────────────────────────

class Tecnica:
    """Códigos del catálogo de técnicas (Manual §4). Strings para serializar
    directo a JSON sin conversión."""
    DIRECT_CONTINUOUS  = "DIRECT_CONTINUOUS"    # tira continua sin modificación
    FULL_CUT           = "FULL_CUT"             # fin eléctrico de una pieza
    SILICONE_RELIEF    = "SILICONE_RELIEF"      # alivio parcial (no cortar LED/FPCB)
    V_RELIEF_90        = "V_RELIEF_90"          # corte trasero en V para 90°
    CROSSING_RELIEF    = "CROSSING_RELIEF"      # cruce/superposición
    HIDDEN_TERMINATION = "HIDDEN_TERMINATION"   # cable sale por atrás
    LETTER_BRIDGE      = "LETTER_BRIDGE"        # puente entre piezas
    CLOSED_SEAM        = "CLOSED_SEAM"          # junta artificial en path cerrado
    SEPARATE_STROKE    = "SEPARATE_STROKE"      # trazo independiente (islas)


# ─── PESOS DE LA FUNCIÓN DE COSTO (Manual §3.2) ──────────────────────────────
# C = wd·distancia + wv·visibilidad + ws·soldaduras + wh·agujeros
#   + wc·cruces + wa·acceso + wm·riesgo
#
# Valores iniciales educated-guess. Se calibran con feedback del taller.
# Coherente con el patrón `calibrado_taller=False` de ICF.
COSTO_PESOS_DEFAULT: dict[str, float] = {
    "wd": 1.0,   # cm de cable — peso base
    "wv": 5.0,   # visibilidad — alto: cable visible es peor que largo
    "ws": 2.0,   # soldaduras — cada soldadura suma tiempo + falla
    "wh": 1.5,   # agujeros — cada perforación suma tiempo + estética
    "wc": 3.0,   # cruces — cable cruzando cable es difícil de mantener
    "wa": 1.0,   # acceso — dificultad de reparación
    "wm": 2.0,   # riesgo mecánico — tensión sobre pistas
}


# ─── DATACLASSES ─────────────────────────────────────────────────────────────

@dataclass
class Terminal:
    """Un extremo físico de una pieza (inicio, final o seam de path cerrado)."""
    id: str                            # ej: "T-p0-start"
    pieza_id: str                      # id de la Pieza a la que pertenece
    tipo: str                          # "start" | "end" | "seam"
    coord_svg: tuple[float, float]     # posición SVG px (sin escalar)
    coord_cm: tuple[float, float]      # posición real cm (post-escala)
    tangente_deg: float = 0.0          # ángulo de tangente (0 = →, 90 = ↑)
    cut_valid: bool = True             # coincide con marca de corte válida
    cut_offset_cm: float = 0.0         # cuánto se desplazó a marca real


@dataclass
class Union:
    """Conexión eléctrica entre dos terminales (Manual §4 · LETTER_BRIDGE)."""
    id: str                            # ej: "U-01"
    terminal_a: str                    # id del Terminal origen
    terminal_b: str                    # id del Terminal destino
    tecnica: str = Tecnica.LETTER_BRIDGE
    distancia_cm: float = 0.0          # euclidiana entre coords
    cable_cm: float = 0.0              # cable real con holgura (×1.15 default)
    visible: bool = False              # cable pasa por el frente?
    costo: float = 0.0                 # función de costo evaluada
    razones: list[str] = field(default_factory=list)  # trazabilidad del ranking


@dataclass
class HiddenRoute:
    """Ruta posterior del cable de una unión (Manual §4.1)."""
    union_id: str
    puntos_svg: list[tuple[float, float]] = field(default_factory=list)
    hidden_ratio: float = 1.0          # cubierto / total, target 1.0
    perforaciones: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Pieza:
    """Una tira física de neón (un componente continuo del anuncio)."""
    id: str                            # ej: "p0"
    svg_path_ids: list[str] = field(default_factory=list)  # svg_ids del path
    longitud_cm: float = 0.0
    perimetro_cm: float = 0.0
    is_closed: bool = False
    bbox_svg: dict = field(default_factory=dict)  # {x,y,w,h} en SVG px
    tecnica_dominante: str = Tecnica.DIRECT_CONTINUOUS
    eventos: list[dict] = field(default_factory=list)   # doblez/alivio/cruce/junta
    terminales: list[str] = field(default_factory=list)  # ids Terminal
    warnings: list[str] = field(default_factory=list)   # ej. "radio 2.4 < mín 3.0"


@dataclass
class ManufacturingPlan:
    """Resultado del planeador para un anuncio de neón (Manual §1.2 salidas)."""
    perfil_id: str = ""                # id del perfil neón usado
    escala_cm_por_px: float = 1.0      # factor SVG → cm

    piezas: list[Pieza] = field(default_factory=list)
    terminales: list[Terminal] = field(default_factory=list)
    uniones: list[Union] = field(default_factory=list)
    rutas_ocultas: list[HiddenRoute] = field(default_factory=list)

    # Métricas agregadas (para plano + cotización)
    metricas: dict = field(default_factory=dict)
    # {
    #   "num_piezas": int, "num_uniones": int, "num_soldaduras": int,
    #   "cable_total_cm": float, "hidden_ratio_global": float,
    #   "longitud_neon_total_m": float, "num_seam_points": int,
    #   "num_perforaciones": int,
    # }

    warnings: list[str] = field(default_factory=list)   # bloqueantes globales
    alternativas_evaluadas: int = 1
    confianza: float = 0.6              # 0-1, sube cuando shapely + calibrado
    version_algoritmo: str = "v0-skeleton"
    debug: dict = field(default_factory=dict)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia euclidiana."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polyline_length_px(polyline_subpaths: list) -> float:
    """Longitud total de una lista de subpaths [[(x,y),...],[...]] en px."""
    total = 0.0
    for sp in polyline_subpaths:
        if not sp or len(sp) < 2:
            continue
        for i in range(len(sp) - 1):
            total += _dist(sp[i], sp[i + 1])
    return total


def _polyline_endpoints(polyline_subpaths: list) -> tuple[tuple[float, float] | None,
                                                         tuple[float, float] | None]:
    """Extremos (primer y último punto) de un path abierto. None si vacío."""
    if not polyline_subpaths:
        return None, None
    flat = [pt for sp in polyline_subpaths for pt in sp]
    if not flat:
        return None, None
    return flat[0], flat[-1]


def _bbox_right_midpoint(bbox: dict) -> tuple[float, float]:
    """Punto medio del borde derecho de un bbox — seam point default para
    paths cerrados (baja visibilidad frontal, típico en la cola derecha de las
    letras). Refinar en v1 con curvatura real."""
    return (bbox["x"] + bbox["w"], bbox["y"] + bbox["h"] / 2)


def _bbox_left_midpoint(bbox: dict) -> tuple[float, float]:
    return (bbox["x"], bbox["y"] + bbox["h"] / 2)


def _bbox_center(bbox: dict) -> tuple[float, float]:
    return (bbox["x"] + bbox["w"] / 2, bbox["y"] + bbox["h"] / 2)


def _funcion_costo(dist_cm: float, visible: bool, agujeros: int,
                   cruces: int, riesgo: float, pesos: dict) -> tuple[float, list[str]]:
    """Evalúa la función de costo Manual §3.2 y devuelve (costo, razones)."""
    razones = []
    c = pesos["wd"] * dist_cm
    razones.append(f"dist={dist_cm:.1f}cm·{pesos['wd']:g}")
    if visible:
        c += pesos["wv"] * dist_cm     # visibilidad escala con la longitud
        razones.append(f"visible·{pesos['wv']:g}")
    c += pesos["ws"] * 2               # 2 soldaduras por unión (una por terminal)
    razones.append(f"2sold·{pesos['ws']:g}")
    if agujeros:
        c += pesos["wh"] * agujeros
        razones.append(f"{agujeros}agu·{pesos['wh']:g}")
    if cruces:
        c += pesos["wc"] * cruces
        razones.append(f"{cruces}cruce·{pesos['wc']:g}")
    if riesgo:
        c += pesos["wm"] * riesgo
        razones.append(f"riesgo{riesgo:g}·{pesos['wm']:g}")
    return c, razones


# ─── MOTOR PRINCIPAL ─────────────────────────────────────────────────────────

def construir_plan(
    path_infos: list,
    *,
    perfil: dict,
    escala_cm_por_px: float = 1.0,
    pesos: dict | None = None,
    prefs: dict | None = None,
) -> ManufacturingPlan:
    """Construye el plan de fabricación para un anuncio de neón.

    v0 skeleton (Manual §12 simplificado):
        1. Un componente = un path SVG (no fusiona vecinos aún)
        2. Genera terminales según is_closed
        3. Uniones = pares de piezas vecinas por proximidad de centros bbox
        4. Sin validación de radios ni snap a marcas de corte

    Args:
        path_infos: lista de calculator.PathInfo del SVG parseado. Los huecos
                    (es_hueco=True) se filtran — no llevan neón.
        perfil: dict del perfil neón con cut_step_cm, radio_min_cm, etc.
        escala_cm_por_px: factor de escala SVG px → cm real.
        pesos: override de COSTO_PESOS_DEFAULT (para calibración).
        prefs: preferencias del taller (todavía no usado en v0).

    Returns:
        ManufacturingPlan con piezas/terminales/uniones/métricas.
    """
    pesos = pesos or COSTO_PESOS_DEFAULT
    _ = prefs  # v0 no las usa

    # Filtrar huecos (contadores de letra, placas de fondo blancas)
    activos = [p for p in (path_infos or []) if not getattr(p, "es_hueco", False)]

    plan = ManufacturingPlan(
        perfil_id=perfil.get("id", ""),
        escala_cm_por_px=escala_cm_por_px,
    )

    # ── 1. Piezas + terminales ────────────────────────────────────────────────
    for idx, pi in enumerate(activos):
        pieza_id = f"p{idx}"
        # Longitud de la polilínea (más preciso que perimeter_px para paths abiertos)
        try:
            L_px = _polyline_length_px(getattr(pi, "polyline_px", []) or [])
        except Exception:
            L_px = 0.0
        if L_px <= 0:
            L_px = float(getattr(pi, "perimeter_px", 0.0) or 0.0)

        long_cm = L_px * escala_cm_por_px
        perim_cm = float(getattr(pi, "perimeter_cm", 0.0)
                         or getattr(pi, "perimeter_px", 0.0) * escala_cm_por_px)
        is_closed = bool(getattr(pi, "is_closed", False))
        bbox = dict(getattr(pi, "bbox", {}) or {"x": 0, "y": 0, "w": 0, "h": 0})

        pieza = Pieza(
            id=pieza_id,
            svg_path_ids=[getattr(pi, "svg_id", "") or getattr(pi, "id", "")],
            longitud_cm=round(long_cm, 2),
            perimetro_cm=round(perim_cm, 2),
            is_closed=is_closed,
            bbox_svg=bbox,
            tecnica_dominante=Tecnica.CLOSED_SEAM if is_closed else Tecnica.DIRECT_CONTINUOUS,
        )

        # Terminales — paths cerrados llevan 1 seam point, abiertos 2 extremos
        if is_closed:
            seam_svg = _bbox_right_midpoint(bbox)
            t = Terminal(
                id=f"T-{pieza_id}-seam",
                pieza_id=pieza_id,
                tipo="seam",
                coord_svg=seam_svg,
                coord_cm=(seam_svg[0] * escala_cm_por_px,
                          seam_svg[1] * escala_cm_por_px),
            )
            plan.terminales.append(t)
            pieza.terminales.append(t.id)
        else:
            start, end = _polyline_endpoints(getattr(pi, "polyline_px", []) or [])
            if start is None:
                start = _bbox_left_midpoint(bbox)
                end = _bbox_right_midpoint(bbox)
            for tipo, coord in [("start", start), ("end", end)]:
                t = Terminal(
                    id=f"T-{pieza_id}-{tipo}",
                    pieza_id=pieza_id,
                    tipo=tipo,
                    coord_svg=coord,
                    coord_cm=(coord[0] * escala_cm_por_px,
                              coord[1] * escala_cm_por_px),
                )
                plan.terminales.append(t)
                pieza.terminales.append(t.id)

        plan.piezas.append(pieza)

    # ── 2. Validación básica de radios ────────────────────────────────────────
    # v0 sólo advierte cuando altura de la pieza es menor al altura_min_cm del
    # perfil. No calcula radios locales todavía (necesita shapely para eso).
    altura_min_cm = float(perfil.get("altura_min_cm", 0) or 0)
    for pieza in plan.piezas:
        h_cm = pieza.bbox_svg.get("h", 0) * escala_cm_por_px
        if altura_min_cm > 0 and h_cm > 0 and h_cm < altura_min_cm:
            pieza.warnings.append(
                f"altura {h_cm:.1f}cm < mínimo del perfil {altura_min_cm:.1f}cm"
            )
            plan.warnings.append(
                f"{pieza.id}: pieza más chica que altura_min del perfil"
            )

    # ── 3. Uniones entre piezas vecinas (chain, no MST — eso viene en v2) ─────
    # Orden piezas por centro-x del bbox. Une consecutivos si están a distancia
    # razonable. Este es el mismo patrón del mock v2 pero calculado en Python
    # y con la función de costo del Manual §3.2 evaluada.
    piezas_orden = sorted(
        plan.piezas,
        key=lambda p: (_bbox_center(p.bbox_svg)[0], _bbox_center(p.bbox_svg)[1])
    )
    holgura = 1.15  # factor cable real vs distancia geométrica

    for i in range(len(piezas_orden) - 1):
        pa, pb = piezas_orden[i], piezas_orden[i + 1]
        # Terminal de salida (borde derecho de la izq)
        ta = _terminal_mas_a(plan, pa, "end", "seam", side="right")
        tb = _terminal_mas_a(plan, pb, "start", "seam", side="left")
        if ta is None or tb is None:
            continue

        d_cm = _dist(ta.coord_cm, tb.coord_cm)
        cable_cm = round(d_cm * holgura, 1)
        # Asume que el cable va por atrás (no visible) mientras el respaldo
        # cubra los dos terminales. v0 no valida esto — asume visible=False.
        visible = False
        costo, razones = _funcion_costo(
            dist_cm=d_cm, visible=visible,
            agujeros=2,  # una perforación por terminal (entrada+salida al reverso)
            cruces=0, riesgo=0.0, pesos=pesos,
        )

        union = Union(
            id=f"U-{i+1:02d}",
            terminal_a=ta.id,
            terminal_b=tb.id,
            tecnica=Tecnica.LETTER_BRIDGE,
            distancia_cm=round(d_cm, 2),
            cable_cm=cable_cm,
            visible=visible,
            costo=round(costo, 2),
            razones=razones,
        )
        plan.uniones.append(union)

        # Ruta oculta trivial: línea recta terminal→terminal por el reverso
        plan.rutas_ocultas.append(HiddenRoute(
            union_id=union.id,
            puntos_svg=[ta.coord_svg, tb.coord_svg],
            hidden_ratio=1.0,  # asumido — v1 lo mide contra huella del neón
            perforaciones=[ta.coord_svg, tb.coord_svg],
        ))

    # ── 4. Métricas agregadas ────────────────────────────────────────────────
    long_total_cm = sum(p.longitud_cm for p in plan.piezas)
    cable_total_cm = sum(u.cable_cm for u in plan.uniones)
    num_seam = sum(1 for t in plan.terminales if t.tipo == "seam")
    num_perf = sum(len(r.perforaciones) for r in plan.rutas_ocultas)
    hidden_avg = (
        sum(r.hidden_ratio for r in plan.rutas_ocultas) / len(plan.rutas_ocultas)
        if plan.rutas_ocultas else 1.0
    )

    plan.metricas = {
        "num_piezas": len(plan.piezas),
        "num_uniones": len(plan.uniones),
        "num_soldaduras": len(plan.uniones) * 2,   # 2 por unión
        "num_seam_points": num_seam,
        "num_perforaciones": num_perf,
        "cable_total_cm": round(cable_total_cm, 1),
        "longitud_neon_total_m": round(long_total_cm / 100, 2),
        "hidden_ratio_global": round(hidden_avg, 2),
    }

    return plan


# ─── UTILIDADES INTERNAS ─────────────────────────────────────────────────────

def _terminal_mas_a(plan: ManufacturingPlan, pieza: Pieza,
                    *tipos_pref: str, side: str = "right") -> Terminal | None:
    """Escoge el terminal de `pieza` que mejor sirve como salida (side=right)
    o entrada (side=left). Preferencia por los tipos indicados."""
    ts = [t for t in plan.terminales if t.pieza_id == pieza.id]
    if not ts:
        return None
    # Preferir tipos indicados si existen
    for tipo in tipos_pref:
        matching = [t for t in ts if t.tipo == tipo]
        if matching:
            ts = matching
            break
    if side == "right":
        return max(ts, key=lambda t: t.coord_svg[0])
    else:
        return min(ts, key=lambda t: t.coord_svg[0])


# ─── SERIALIZACIÓN ───────────────────────────────────────────────────────────

def plan_a_dict(plan: ManufacturingPlan) -> dict[str, Any]:
    """Serializa ManufacturingPlan a dict JSON-friendly. Convierte tuplas de
    coord a listas para JSON estricto."""
    from dataclasses import asdict
    d = asdict(plan)
    # tuplas → listas (JSON no tiene tuplas)
    for t in d.get("terminales", []):
        t["coord_svg"] = list(t["coord_svg"])
        t["coord_cm"] = list(t["coord_cm"])
    for r in d.get("rutas_ocultas", []):
        r["puntos_svg"] = [list(pt) for pt in r["puntos_svg"]]
        r["perforaciones"] = [list(pt) for pt in r["perforaciones"]]
    return d
