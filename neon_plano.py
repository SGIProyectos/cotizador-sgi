"""Planeador de construcción para anuncios de neón LED (SGI).

Convierte geometría vectorial (SVG paths) en una SOLUCIÓN FÍSICA fabricable:
piezas físicas continuas, terminales, uniones eléctricas, cable oculto,
técnicas especiales por pieza y advertencias.

Basado en:
- Manual Técnico "Algoritmo experto de fabricación de neón flex" (§12 pseudocódigo)
- Cuaderno Práctico IA (schema de labels + microtécnicas A-F)

Es INDEPENDIENTE del motor de costos (`neon_calculator.py`). Ese cotiza;
este planifica. Ambos alimentan el endpoint /api/cotizar/neon y los PDFs.

Iteración actual: v1-shapely (2026-08-17)
- 1 pieza por path del SVG (no fusiona letras vecinas en 1 tira)
- Terminales snap a marca de corte válida (múltiplo de cut_step_cm del perfil)
- Paths cerrados → seam point ÓPTIMO por baja curvatura (no bbox right)
- Detección de curvaturas apretadas (radio < radio_min_cm del perfil) →
  agrega evento V_RELIEF_90 al pieza.eventos y warning legible
- Instrucciones humano-legibles por pieza (Manual §11.1) en pieza.instrucciones
- Uniones: pares vecinos por proximidad de bbox (cadena lineal, no MST)
- Cable posterior: polilínea recta terminal→terminal (hidden_ratio=1.0 asumido)

Iteración v2 (siguiente): MST real con Kruskal sobre grafo completo de
terminales compatibles + pesos calibrables de la función de costo + rutas
posteriores con hidden_ratio real vs. huella proyectada del neón.

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
    # v1-shapely (2026-08-17)
    instrucciones: list[str] = field(default_factory=list)  # texto humano Manual §11.1
    radio_min_encontrado_cm: float = 0.0  # radio local más apretado detectado (>0 si aplica)


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
    # v1.27.3 · Circuito eléctrico completo — entrada y salida a la fuente
    terminal_inicio_circuito: str = ""  # id del Terminal que recibe (+) de la fuente
    terminal_fin_circuito: str = ""     # id del Terminal que retorna (-) a la fuente


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


# ─── HELPERS v1-shapely (2026-08-17) ─────────────────────────────────────────

def _radio_por_3puntos(a: tuple[float, float],
                       b: tuple[float, float],
                       c: tuple[float, float]) -> float | None:
    """Radio del círculo que pasa por 3 puntos (fórmula clásica).
    None si son colineales (radio infinito, curva plana)."""
    ax, ay = a; bx, by = b; cx, cy = c
    area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    if area2 < 1e-6:
        return None
    d_ab = math.hypot(bx - ax, by - ay)
    d_bc = math.hypot(cx - bx, cy - by)
    d_ca = math.hypot(ax - cx, ay - cy)
    return (d_ab * d_bc * d_ca) / (2.0 * area2)


def _detectar_curvas_apretadas(polyline_subpaths: list,
                                escala_cm_por_px: float,
                                radio_min_cm: float,
                                ventana: int = 2,
                                angulo_esquina_min_deg: float = 45.0) -> tuple[list[dict], int]:
    """Recorre la polilínea con ventana ±N puntos y clasifica dónde el radio
    local cae por debajo del mínimo del perfil.

    Devuelve (eventos, num_puntos_curvatura_baja):
      - `eventos`: solo los puntos que son ESQUINAS definidas (ángulo entre
        vectores entrada/salida > `angulo_esquina_min_deg`). Estos SÍ son
        candidatos a V_RELIEF_90 (cortar V en trasera para forzar la esquina).
      - `num_puntos_curvatura_baja`: total de puntos con radio < mín (incluye
        curvas continuas tipo círculo). Si es alto pero eventos está vacío,
        significa "curva continua muy cerrada — cambia de perfil".
    """
    if radio_min_cm <= 0 or escala_cm_por_px <= 0:
        return [], 0
    eventos: list[dict] = []
    total_bajo_min = 0
    for sp in polyline_subpaths or []:
        if len(sp) < (2 * ventana + 1):
            continue
        # Cooldown para no emitir eventos consecutivos en el mismo doblez.
        last_i = -999
        for i in range(ventana, len(sp) - ventana):
            r_px = _radio_por_3puntos(sp[i - ventana], sp[i], sp[i + ventana])
            if r_px is None:
                continue
            r_cm = r_px * escala_cm_por_px
            if r_cm >= radio_min_cm:
                continue
            total_bajo_min += 1
            # Ángulo entre vector entrante y saliente
            v1x = sp[i][0] - sp[i - ventana][0]
            v1y = sp[i][1] - sp[i - ventana][1]
            v2x = sp[i + ventana][0] - sp[i][0]
            v2y = sp[i + ventana][1] - sp[i][1]
            m1 = math.hypot(v1x, v1y); m2 = math.hypot(v2x, v2y)
            if m1 <= 0 or m2 <= 0:
                continue
            cos_a = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (m1 * m2)))
            angulo_deg = round(math.degrees(math.acos(cos_a)), 1)
            # Solo esquinas definidas: ángulo entre vectores > umbral (45° default).
            # Curvas continuas (círculo, arco suave) tienen ángulo pequeño por
            # segmento aunque el radio sea chico — esas NO son V_RELIEF_90.
            if angulo_deg >= angulo_esquina_min_deg and (i - last_i) > ventana * 2:
                eventos.append({
                    "tipo": Tecnica.V_RELIEF_90,
                    "coord_svg": (sp[i][0], sp[i][1]),
                    "radio_cm": round(r_cm, 2),
                    "angulo_deg": angulo_deg,
                })
                last_i = i
    return eventos, total_bajo_min


def _snap_a_corte_cm(coord_cm: tuple[float, float],
                     cut_step_cm: float,
                     origin_cm: tuple[float, float] = (0.0, 0.0)) -> tuple[tuple[float, float], float]:
    """Redondea coord_cm al múltiplo de cut_step_cm más cercano (desde origin).
    Devuelve (coord_snapped, offset_cm). Simplificación: snap independiente
    por eje. En v2, cuando tengamos parametrización por longitud de arco,
    haremos snap a lo largo del path (más preciso)."""
    if cut_step_cm <= 0:
        return coord_cm, 0.0
    x = origin_cm[0] + round((coord_cm[0] - origin_cm[0]) / cut_step_cm) * cut_step_cm
    y = origin_cm[1] + round((coord_cm[1] - origin_cm[1]) / cut_step_cm) * cut_step_cm
    off = _dist(coord_cm, (x, y))
    return (x, y), off


def _seam_point_optimo(polyline_subpaths: list, bbox: dict,
                       escala_cm_por_px: float,
                       radio_min_cm: float) -> tuple[float, float]:
    """Para paths cerrados: elige el punto de la polilínea con MAYOR radio
    local (curvatura más suave = fácil de soldar y ocultar). Fallback al
    borde derecho del bbox si no hay polilínea usable."""
    fallback = (bbox["x"] + bbox["w"], bbox["y"] + bbox["h"] / 2)
    if not polyline_subpaths:
        return fallback
    mejor_r = -1.0
    mejor_pt = None
    for sp in polyline_subpaths:
        if len(sp) < 5:
            continue
        for i in range(2, len(sp) - 2):
            r_px = _radio_por_3puntos(sp[i - 2], sp[i], sp[i + 2])
            if r_px is None:
                # Colineal → excelente candidato (recta larga oculta bien la junta)
                r_px = 1e9
            if r_px > mejor_r:
                mejor_r = r_px
                mejor_pt = sp[i]
    return mejor_pt if mejor_pt is not None else fallback


def _instrucciones_pieza(pieza: Pieza, perfil: dict,
                         terms_por_id: dict[str, Terminal]) -> list[str]:
    """Genera texto humano-legible tipo Manual §11.1 para el operario.
    Cada bullet describe UN paso concreto de fabricación."""
    lines: list[str] = []
    perfil_nombre = perfil.get("nombre", "manguera")
    color = perfil.get("color", "")
    cut_step = float(perfil.get("cut_step_cm", 0) or 0)

    # Header: material + longitud
    resumen = f"{perfil_nombre}"
    if color:
        resumen += f" {color}"
    resumen += f" · {pieza.longitud_cm:.1f} cm"
    if cut_step > 0:
        # Redondear al corte real
        n_cortes = round(pieza.longitud_cm / cut_step)
        long_real = n_cortes * cut_step
        resumen += f" (corte real: {n_cortes} × {cut_step:g} cm = {long_real:.1f} cm)"
    lines.append(resumen)

    # Terminales
    ts = [terms_por_id.get(tid) for tid in pieza.terminales]
    ts = [t for t in ts if t is not None]
    if pieza.is_closed:
        seam = next((t for t in ts if t.tipo == "seam"), None)
        if seam:
            xcm = seam.coord_cm[0]; ycm = seam.coord_cm[1]
            lines.append(f"Path CERRADO · junta artificial (seam) en ({xcm:.1f}, {ycm:.1f}) cm")
            if seam.cut_offset_cm > 0.1:
                lines.append(f"  ↳ terminal ajustado {seam.cut_offset_cm:.1f} cm a marca de corte válida")
    else:
        start = next((t for t in ts if t.tipo == "start"), None)
        end = next((t for t in ts if t.tipo == "end"), None)
        if start:
            lines.append(f"Iniciar en {start.id} → ({start.coord_cm[0]:.1f}, {start.coord_cm[1]:.1f}) cm")
        lines.append("Recorrer siguiendo el trazo")
        if end:
            lines.append(f"Terminar en {end.id} → ({end.coord_cm[0]:.1f}, {end.coord_cm[1]:.1f}) cm")

    # Eventos técnicos (V_RELIEF_90, etc.)
    for ev in pieza.eventos:
        if ev.get("tipo") == Tecnica.V_RELIEF_90:
            r = ev.get("radio_cm", 0); a = ev.get("angulo_deg", 0)
            lines.append(
                f"⚠️ CORTE V EN TRASERA (V_RELIEF_90) — radio local {r:.1f} cm "
                f"< mín {perfil.get('radio_min_cm', 0):g} cm · ángulo ~{a:.0f}°"
            )

    # Instrucción de cable oculto (aparece si esta pieza inicia/termina una unión)
    lines.append("Sacar cable por atrás (perforación en el terminal)")

    return lines


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
    _ = prefs  # v1 aún no las usa

    # Filtrar huecos (contadores de letra, placas de fondo blancas)
    activos = [p for p in (path_infos or []) if not getattr(p, "es_hueco", False)]

    # Constantes del perfil (v1)
    radio_min_cm = float(perfil.get("radio_min_cm", 0) or 0)
    cut_step_cm  = float(perfil.get("cut_step_cm", 0) or 0)

    plan = ManufacturingPlan(
        perfil_id=perfil.get("id", ""),
        escala_cm_por_px=escala_cm_por_px,
        version_algoritmo="v1-shapely",
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

        # ── v1: Detección de esquinas apretadas (V_RELIEF_90) + curvas continuas ─
        polyline = getattr(pi, "polyline_px", []) or []
        if radio_min_cm > 0:
            eventos_curv, puntos_bajo_min = _detectar_curvas_apretadas(
                polyline, escala_cm_por_px, radio_min_cm,
                ventana=2, angulo_esquina_min_deg=45.0,
            )
            if eventos_curv:
                pieza.eventos.extend(eventos_curv)
                pieza.radio_min_encontrado_cm = min(e["radio_cm"] for e in eventos_curv)
                pieza.warnings.append(
                    f"{len(eventos_curv)} esquina(s) apretada(s): radio mín "
                    f"{pieza.radio_min_encontrado_cm:.2f} cm < perfil "
                    f"{radio_min_cm:.1f} cm — requiere V_RELIEF_90 en cara trasera"
                )
            # Curvas continuas (ej: círculo chico) NO son V_RELIEF_90 —
            # necesitan cambio de perfil o rediseño. Umbral: >5 puntos
            # bajo mínimo pero sin esquinas detectadas.
            if puntos_bajo_min > 5 and not eventos_curv:
                pieza.warnings.append(
                    f"Curvatura continua < mínimo ({puntos_bajo_min} puntos por debajo). "
                    f"Cambiar a perfil más flexible (radio_min ≤ requerido) o rediseñar."
                )

        # Terminales — paths cerrados llevan 1 seam point ÓPTIMO (baja curvatura),
        # abiertos 2 extremos reales de la polilínea.
        def _snap_terminal(coord_svg):
            """Aplica snap a marca de corte válida si el perfil define cut_step_cm."""
            coord_cm = (coord_svg[0] * escala_cm_por_px,
                        coord_svg[1] * escala_cm_por_px)
            if cut_step_cm > 0:
                snapped_cm, off_cm = _snap_a_corte_cm(coord_cm, cut_step_cm)
                return coord_svg, coord_cm, snapped_cm, off_cm
            return coord_svg, coord_cm, coord_cm, 0.0

        if is_closed:
            seam_svg = _seam_point_optimo(polyline, bbox, escala_cm_por_px, radio_min_cm)
            c_svg, c_cm, c_snap, off = _snap_terminal(seam_svg)
            t = Terminal(
                id=f"T-{pieza_id}-seam",
                pieza_id=pieza_id,
                tipo="seam",
                coord_svg=c_svg,
                coord_cm=c_snap,
                cut_valid=(off < 0.2),
                cut_offset_cm=round(off, 2),
            )
            plan.terminales.append(t)
            pieza.terminales.append(t.id)
        else:
            start, end = _polyline_endpoints(polyline)
            if start is None:
                start = _bbox_left_midpoint(bbox)
                end = _bbox_right_midpoint(bbox)
            for tipo, coord in [("start", start), ("end", end)]:
                c_svg, c_cm, c_snap, off = _snap_terminal(coord)
                t = Terminal(
                    id=f"T-{pieza_id}-{tipo}",
                    pieza_id=pieza_id,
                    tipo=tipo,
                    coord_svg=c_svg,
                    coord_cm=c_snap,
                    cut_valid=(off < 0.2),
                    cut_offset_cm=round(off, 2),
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

    # ── 3. Uniones entre piezas vecinas + INICIO/FIN del circuito (v1.27.3) ──
    # Orden piezas por centro-x del bbox (izquierda → derecha).
    piezas_orden = sorted(
        plan.piezas,
        key=lambda p: (_bbox_center(p.bbox_svg)[0], _bbox_center(p.bbox_svg)[1])
    )
    holgura = 1.15  # factor cable real vs distancia geométrica

    # INICIO del circuito: terminal más a la IZQUIERDA de la primera pieza
    # (por convención — el usuario podrá override en v2). Se reserva para la
    # fuente y NO se usa en uniones entre piezas.
    inicio_id = ""
    fin_id = ""
    if piezas_orden:
        pa0 = piezas_orden[0]
        ts_pa0 = [t for t in plan.terminales if t.pieza_id == pa0.id]
        if ts_pa0:
            inicio_t = min(ts_pa0, key=lambda t: t.coord_svg[0])
            inicio_id = inicio_t.id
        # FIN del circuito: terminal más a la DERECHA de la última pieza
        pn = piezas_orden[-1]
        ts_pn = [t for t in plan.terminales if t.pieza_id == pn.id]
        # Excluir el inicio si es la misma pieza (caso 1 sola pieza)
        candidatos_fin = [t for t in ts_pn if t.id != inicio_id]
        if candidatos_fin:
            fin_t = max(candidatos_fin, key=lambda t: t.coord_svg[0])
            fin_id = fin_t.id
    plan.terminal_inicio_circuito = inicio_id
    plan.terminal_fin_circuito = fin_id

    # Uniones entre piezas: par de MÍNIMA distancia entre terminales.
    # NO excluimos INICIO/FIN — en la vida real, si una pieza cerrada tiene
    # 1 solo seam point, ese punto físicamente RECIBE los 2 cables de la
    # fuente + el puente a la siguiente pieza (una junta múltiple). En el
    # render diferenciamos visualmente INICIO (círculo verde) de UNIÓN
    # (círculo rojo numerado) aunque coincidan en la coordenada.
    for i in range(len(piezas_orden) - 1):
        pa, pb = piezas_orden[i], piezas_orden[i + 1]
        ta, tb, d_cm = _par_terminales_mas_cercano(plan, pa, pb)
        if ta is None or tb is None:
            continue

        cable_cm = round(d_cm * holgura, 1)
        visible = False  # asume cable posterior — v2 valida contra huella
        costo, razones = _funcion_costo(
            dist_cm=d_cm, visible=visible,
            agujeros=2, cruces=0, riesgo=0.0, pesos=pesos,
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

        # Ruta oculta: línea recta por el reverso (v1 asume hidden_ratio=1.0)
        plan.rutas_ocultas.append(HiddenRoute(
            union_id=union.id,
            puntos_svg=[ta.coord_svg, tb.coord_svg],
            hidden_ratio=1.0,
            perforaciones=[ta.coord_svg, tb.coord_svg],
        ))

    # ── v1: Instrucciones humano-legibles por pieza (Manual §11.1) ───────────
    terms_por_id = {t.id: t for t in plan.terminales}
    for pieza in plan.piezas:
        pieza.instrucciones = _instrucciones_pieza(pieza, perfil, terms_por_id)

    # ── 4. Métricas agregadas ────────────────────────────────────────────────
    long_total_cm = sum(p.longitud_cm for p in plan.piezas)
    cable_total_cm = sum(u.cable_cm for u in plan.uniones)
    num_seam = sum(1 for t in plan.terminales if t.tipo == "seam")
    num_perf = sum(len(r.perforaciones) for r in plan.rutas_ocultas)
    hidden_avg = (
        sum(r.hidden_ratio for r in plan.rutas_ocultas) / len(plan.rutas_ocultas)
        if plan.rutas_ocultas else 1.0
    )

    num_v_relief = sum(
        sum(1 for e in p.eventos if e.get("tipo") == Tecnica.V_RELIEF_90)
        for p in plan.piezas
    )
    num_terminales_ajustados = sum(1 for t in plan.terminales if t.cut_offset_cm > 0.1)

    plan.metricas = {
        "num_piezas": len(plan.piezas),
        "num_uniones": len(plan.uniones),
        "num_soldaduras": len(plan.uniones) * 2,   # 2 por unión
        "num_seam_points": num_seam,
        "num_perforaciones": num_perf,
        "num_v_relief_90": num_v_relief,             # v1
        "num_terminales_snapped": num_terminales_ajustados,  # v1
        "cable_total_cm": round(cable_total_cm, 1),
        "longitud_neon_total_m": round(long_total_cm / 100, 2),
        "hidden_ratio_global": round(hidden_avg, 2),
    }
    plan.confianza = 0.75  # v1 con shapely + snap + seam óptimo

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


def _par_terminales_mas_cercano(
    plan: ManufacturingPlan, pa: Pieza, pb: Pieza,
    excluidos: set[str] | None = None,
) -> tuple[Terminal | None, Terminal | None, float]:
    """(v1.27.3) Devuelve el par (ta ∈ pa, tb ∈ pb, distancia_cm) de MÍNIMA
    distancia entre TODOS los terminales de ambas piezas.

    Antes usaba side='right' + side='left' que fallaba en letras con altura
    dispar o sub-trazos internos. Ahora evalúa las N×M combinaciones.
    El conjunto `excluidos` sirve para reservar terminales de INICIO/FIN del
    circuito (esos se conectan a la fuente, no entre piezas)."""
    exc = excluidos or set()
    tas = [t for t in plan.terminales if t.pieza_id == pa.id and t.id not in exc]
    tbs = [t for t in plan.terminales if t.pieza_id == pb.id and t.id not in exc]
    if not tas or not tbs:
        return None, None, 0.0
    mejor = (None, None, float("inf"))
    for ta in tas:
        for tb in tbs:
            d = _dist(ta.coord_cm, tb.coord_cm)
            if d < mejor[2]:
                mejor = (ta, tb, d)
    return mejor


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
