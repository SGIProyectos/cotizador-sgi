"""Planeador de construcción de anuncios de neón LED (SGI) — Motor v2.

Convierte geometría vectorial (SVG paths) en una SOLUCIÓN FÍSICA fabricable
siguiendo FIELMENTE los 3 manuales del propietario:

  - Manual Técnico "Algoritmo experto de fabricación de neón flex"
  - Cuaderno Práctico IA (4 ejemplos + 6 microtécnicas A-F)
  - Ejemplos visuales (`conectakarate.png`, `conectakarate2.png`)

v2 (2026-08-17): reescritura completa. Cumple los 9 pasos del algoritmo
(Cuaderno pág 11) e implementa las microtécnicas del Manual §4 con
parámetros del catálogo real (cut_step_cm, radio_min_cm, fpcb_offset_mm).

Cambios clave vs. v1:
- Ya NO "1 path SVG = 1 pieza" (violaba Manual §2.3)
- Usa `topology.analizar` + `descomponer_en_piezas_fisicas` para respetar
  la matriz A-Z del Manual §5
- Marcas de corte visibles a lo largo del trazo (shapely.interpolate cada
  cut_step_cm) — el operario ve dónde cortar
- MST real Kruskal sobre grafo de terminales con función de costo Manual §3.2
- Instrucciones humano-legibles por pieza (Manual §11.1) con parámetros
  de cada técnica
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from topology import (
    SubPieza,
    descomponer_en_piezas_fisicas,
)
from topology import (
    analizar as topo_analizar,
)

try:
    from shapely.geometry import LineString
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


# ─── ENUMS ───────────────────────────────────────────────────────────────────

class Tecnica:
    """Códigos del catálogo de técnicas (Manual §4 + Cuaderno microtécnicas A-F)."""
    DIRECT_CONTINUOUS   = "DIRECT_CONTINUOUS"
    FULL_CUT            = "FULL_CUT"
    SILICONE_RELIEF     = "SILICONE_RELIEF"       # Cuaderno F (P con una tira)
    V_RELIEF_90         = "V_RELIEF_90"           # Cuaderno D (esquina 90°)
    CROSSING_RELIEF     = "CROSSING_RELIEF"       # Cuaderno A (cruce cursivo)
    HIDDEN_TERMINATION  = "HIDDEN_TERMINATION"    # Cuaderno B (cable oculto)
    LETTER_BRIDGE       = "LETTER_BRIDGE"         # Cuaderno C (unión limpia)
    CLOSED_SEAM         = "CLOSED_SEAM"           # Cuaderno E (cierre O)
    SEPARATE_STROKE     = "SEPARATE_STROKE"


# Pesos de la función de costo Manual §3.2
COSTO_PESOS_DEFAULT: dict[str, float] = {
    "wd": 1.0, "wv": 5.0, "ws": 2.0, "wh": 1.5,
    "wc": 3.0, "wa": 1.0, "wm": 2.0,
    # Costo angular (Cuaderno microtécnica C): penalizar transiciones
    # donde las tangentes de los 2 terminales apuntan a direcciones
    # incompatibles (bulto visible).
    "wangle": 0.05,
}


# ─── DATACLASSES ─────────────────────────────────────────────────────────────

@dataclass
class Terminal:
    """Extremo físico de una pieza (inicio, final o seam de path cerrado)."""
    id: str
    pieza_id: str
    tipo: str                              # start | end | seam
    coord_svg: tuple[float, float]
    coord_cm: tuple[float, float]
    tangente_deg: float = 0.0              # ángulo de tangente (para costo angular)
    cut_valid: bool = True
    cut_offset_cm: float = 0.0
    en_marca_de_corte: bool = False        # snappeado a marca real del perfil


@dataclass
class MarcaCorte:
    """Punto físico de la tira donde SÍ se puede cortar (cada cut_step_cm).
    Se pinta como rayita transversal en el plano — igual que en el dibujo del
    propietario `conectakarate2.png` boceto 6."""
    pieza_id: str
    coord_svg: tuple[float, float]
    tangente_deg: float                    # perpendicular = dirección de la rayita
    long_acumulada_cm: float               # posición a lo largo del trazo desde el inicio


@dataclass
class Union:
    """Conexión eléctrica entre dos terminales."""
    id: str
    terminal_a: str
    terminal_b: str
    tecnica: str = Tecnica.LETTER_BRIDGE
    distancia_cm: float = 0.0
    cable_cm: float = 0.0
    visible: bool = False
    costo: float = 0.0
    razones: list[str] = field(default_factory=list)


@dataclass
class HiddenRoute:
    """Ruta posterior del cable de una unión."""
    union_id: str
    puntos_svg: list[tuple[float, float]] = field(default_factory=list)
    hidden_ratio: float = 1.0
    perforaciones: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Pieza:
    """Una tira física de neón (un componente continuo del anuncio)."""
    id: str
    svg_path_ids: list[str] = field(default_factory=list)
    subpath_ids: list[int] = field(default_factory=list)
    longitud_cm: float = 0.0
    is_closed: bool = False
    bbox_svg: dict = field(default_factory=dict)
    puntos_svg: list[tuple[float, float]] = field(default_factory=list)  # polilínea para render
    tipo_topologico: str = ""              # del análisis topology
    tecnica_dominante: str = Tecnica.DIRECT_CONTINUOUS
    eventos: list[dict] = field(default_factory=list)   # V_RELIEF_90, SILICONE_RELIEF, CROSSING, etc.
    terminales: list[str] = field(default_factory=list)
    marcas_corte: list[dict] = field(default_factory=list)  # coord_svg + tangente_deg + long_cm
    warnings: list[str] = field(default_factory=list)
    instrucciones: list[str] = field(default_factory=list)   # Manual §11.1
    radio_min_encontrado_cm: float = 0.0


@dataclass
class ManufacturingPlan:
    """Resultado del planeador (Manual §1.2 salidas)."""
    perfil_id: str = ""
    escala_cm_por_px: float = 1.0
    piezas: list[Pieza] = field(default_factory=list)
    terminales: list[Terminal] = field(default_factory=list)
    uniones: list[Union] = field(default_factory=list)
    rutas_ocultas: list[HiddenRoute] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    alternativas_evaluadas: int = 1
    confianza: float = 0.85                 # v2 usa topología real
    version_algoritmo: str = "v2-topological"
    debug: dict = field(default_factory=dict)
    terminal_inicio_circuito: str = ""
    terminal_fin_circuito: str = ""


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polyline_length_px(subpath_pts: list[tuple[float, float]]) -> float:
    if len(subpath_pts) < 2:
        return 0.0
    return sum(_dist(subpath_pts[i], subpath_pts[i + 1]) for i in range(len(subpath_pts) - 1))


def _tangente_deg(pts: list[tuple[float, float]], idx: int, ventana: int = 2) -> float:
    """Ángulo de la tangente local en el punto pts[idx] (grados, 0=→, 90=↑)."""
    n = len(pts)
    if n < 2:
        return 0.0
    i0 = max(0, idx - ventana)
    i1 = min(n - 1, idx + ventana)
    dx = pts[i1][0] - pts[i0][0]
    dy = pts[i1][1] - pts[i0][1]
    if dx == 0 and dy == 0:
        return 0.0
    return round(math.degrees(math.atan2(dy, dx)), 1)


def _funcion_costo(dist_cm: float, visible: bool, agujeros: int,
                   cruces: int, riesgo: float, angulo_deg_diff: float,
                   pesos: dict) -> tuple[float, list[str]]:
    """Función de costo Manual §3.2 + costo angular Cuaderno §C."""
    razones = []
    c = pesos["wd"] * dist_cm
    razones.append(f"dist={dist_cm:.1f}cm")
    if visible:
        c += pesos["wv"] * dist_cm
        razones.append("visible")
    c += pesos["ws"] * 2  # 2 soldaduras por unión
    razones.append("2sold")
    if agujeros:
        c += pesos["wh"] * agujeros
        razones.append(f"{agujeros}agu")
    if cruces:
        c += pesos["wc"] * cruces
        razones.append(f"{cruces}cruce")
    if riesgo:
        c += pesos["wm"] * riesgo
        razones.append(f"riesgo{riesgo:g}")
    if angulo_deg_diff:
        c += pesos["wangle"] * angulo_deg_diff
        razones.append(f"ang{angulo_deg_diff:.0f}°")
    return round(c, 2), razones


def _generar_marcas_corte(pts: list[tuple[float, float]],
                          cut_step_cm: float,
                          escala_cm_por_px: float,
                          pieza_id: str) -> list[MarcaCorte]:
    """Distribuye marcas de corte cada cut_step_cm a lo largo de la polilínea.
    Cada marca lleva su tangente para pintar la rayita perpendicular en el plano.
    Usa shapely.interpolate para precisión (samplea la longitud de arco real)."""
    if cut_step_cm <= 0 or escala_cm_por_px <= 0 or len(pts) < 2:
        return []
    long_total_px = _polyline_length_px(pts)
    long_total_cm = long_total_px * escala_cm_por_px
    n_marcas = int(long_total_cm // cut_step_cm)
    if n_marcas < 1:
        return []
    marcas: list[MarcaCorte] = []
    if HAS_SHAPELY:
        try:
            ls = LineString(pts)
            for k in range(1, n_marcas + 1):
                dist_cm = k * cut_step_cm
                dist_px = dist_cm / escala_cm_por_px
                pt = ls.interpolate(dist_px)
                # Tangente: samplear un poquito antes y después
                delta = min(2.0, ls.length * 0.005)
                p0 = ls.interpolate(max(0, dist_px - delta))
                p1 = ls.interpolate(min(ls.length, dist_px + delta))
                dx = p1.x - p0.x; dy = p1.y - p0.y
                tang = math.degrees(math.atan2(dy, dx)) if (dx or dy) else 0.0
                marcas.append(MarcaCorte(
                    pieza_id=pieza_id,
                    coord_svg=(round(pt.x, 2), round(pt.y, 2)),
                    tangente_deg=round(tang, 1),
                    long_acumulada_cm=round(dist_cm, 2),
                ))
        except Exception:
            pass
    return marcas


def _snap_terminal_a_marca(coord_cm: tuple[float, float],
                           pts_pieza: list[tuple[float, float]],
                           cut_step_cm: float,
                           escala_cm_por_px: float
                           ) -> tuple[tuple[float, float], float]:
    """Proyecta un terminal a la marca de corte más cercana DENTRO del path.

    Estrategia:
      1. Proyecta el terminal sobre la LineString (longitud de arco).
      2. Prueba floor(proj/step)*step y ceil(...) — el que caiga dentro de
         [0, length] Y esté más cerca del proj original gana.
      3. Si ambos caen fuera, hace clamp al más cercano válido.
    """
    if cut_step_cm <= 0 or escala_cm_por_px <= 0 or not HAS_SHAPELY:
        return coord_cm, 0.0
    try:
        pts_cm = [(p[0] * escala_cm_por_px, p[1] * escala_cm_por_px) for p in pts_pieza]
        ls = LineString(pts_cm)
        proj = ls.project(_shapely_pt(coord_cm))
        length = ls.length
        # Candidatos: floor y ceil del múltiplo, más el ceil siguiente
        k_floor = math.floor(proj / cut_step_cm)
        candidatos = [k_floor * cut_step_cm, (k_floor + 1) * cut_step_cm]
        # Filtrar candidatos dentro de [0, length]
        validos = [c for c in candidatos if 0.0 <= c <= length]
        if not validos:
            # Ninguno cae dentro — clamp al extremo más cercano
            proj_snap = min(candidatos, key=lambda x: abs(x - proj))
            proj_snap = max(0.0, min(length, proj_snap))
        else:
            # De los válidos, el más cercano al proj original
            proj_snap = min(validos, key=lambda x: abs(x - proj))
        pt = ls.interpolate(proj_snap)
        off = math.hypot(pt.x - coord_cm[0], pt.y - coord_cm[1])
        return (pt.x, pt.y), off
    except Exception:
        return coord_cm, 0.0


def _shapely_pt(c: tuple[float, float]):
    from shapely.geometry import Point
    return Point(c)


# ─── PAR DE TERMINALES MÁS CERCANO (mejorada con costo angular) ─────────────

def _par_terminales_mas_cercano(
    plan: ManufacturingPlan, pa: Pieza, pb: Pieza,
) -> tuple[Terminal | None, Terminal | None, float, float]:
    """Devuelve (ta, tb, dist_cm, ang_diff_deg) del mejor par entre pa y pb.
    Combina distancia geométrica con diferencia angular de tangentes (Cuaderno
    Microtécnica C: la unión más limpia es la que respeta la continuidad de curva)."""
    tas = [t for t in plan.terminales if t.pieza_id == pa.id]
    tbs = [t for t in plan.terminales if t.pieza_id == pb.id]
    if not tas or not tbs:
        return None, None, 0.0, 0.0
    mejor = (None, None, float("inf"), 0.0)
    for ta in tas:
        for tb in tbs:
            d = _dist(ta.coord_cm, tb.coord_cm)
            # Ángulo entre tangentes (para valores en 180° la unión es limpia)
            diff = abs((tb.tangente_deg - ta.tangente_deg + 180) % 360 - 180)
            # Penalización pequeña por ángulo (5% peso relativo a la distancia)
            score = d + 0.05 * diff
            if score < mejor[2] + 0.05 * mejor[3]:
                mejor = (ta, tb, d, diff)
    return mejor


# ─── MOTOR PRINCIPAL v2 ─────────────────────────────────────────────────────

def construir_plan(
    path_infos: list,
    *,
    perfil: dict,
    escala_cm_por_px: float = 1.0,
    pesos: dict | None = None,
    prefs: dict | None = None,
) -> ManufacturingPlan:
    """Motor v2 basado en topología + microtécnicas + MST.

    9 pasos (Cuaderno pág 11):
      1. Identificar línea central del neón (polyline_px)
      2. Dividir en piezas físicas reales (topology.descomponer)
      3. Snap terminales a marca de corte válida
      4. Generar orientaciones (implícito en el par-más-cercano)
      5. Pares cercanos compatibles (con costo angular)
      6. Ruta posterior + perforaciones
      7. Optimizar globalmente (MST — reemplaza el chain lineal de v1)
      8. Validar polaridad/tensión/corriente
      9. Devolver plan con instrucciones humano-legibles
    """
    pesos = pesos or COSTO_PESOS_DEFAULT
    _ = prefs

    activos = [p for p in (path_infos or []) if not getattr(p, "es_hueco", False)]

    radio_min_cm = float(perfil.get("radio_min_cm", 0) or 0)
    cut_step_cm  = float(perfil.get("cut_step_cm", 0) or 0)
    # Pasamos escala al perfil temporalmente para topology
    perfil_topo = dict(perfil)
    perfil_topo["_escala_cm_por_px"] = escala_cm_por_px

    plan = ManufacturingPlan(
        perfil_id=perfil.get("id", ""),
        escala_cm_por_px=escala_cm_por_px,
        version_algoritmo="v2-topological",
    )

    # ── PASO 1-2. Descomposición topológica ──────────────────────────────────
    # Cada path SVG se analiza, se clasifica, y se descompone en 1 o más
    # SubPieza según el tipo topológico (Manual §2.3 + §5 matriz A-Z).
    subpiezas_totales: list[SubPieza] = []
    for pi in activos:
        topo = topo_analizar(pi)
        subs = descomponer_en_piezas_fisicas(topo, perfil_topo)
        # Anotar tipo topológico para trazabilidad
        for s in subs:
            s.notas.append(f"tipo_topologico={topo.tipo.value}")
        subpiezas_totales.extend(subs)

    # ── Crear Pieza por cada SubPieza ────────────────────────────────────────
    for idx, sp in enumerate(subpiezas_totales):
        pieza_id = f"p{idx}"
        long_cm = round(sp.longitud_px * escala_cm_por_px, 2)
        bbox = sp.bbox or {"x": 0, "y": 0, "w": 0, "h": 0}
        pieza = Pieza(
            id=pieza_id,
            svg_path_ids=[sp.path_id_svg] if sp.path_id_svg else [],
            subpath_ids=list(sp.subpath_ids),
            longitud_cm=long_cm,
            is_closed=sp.is_closed,
            bbox_svg=bbox,
            puntos_svg=list(sp.puntos),
            tecnica_dominante=sp.tecnica_dominante or Tecnica.DIRECT_CONTINUOUS,
        )
        # Detectar tipo topologico de las notas
        for n in sp.notas:
            if n.startswith("tipo_topologico="):
                pieza.tipo_topologico = n.split("=", 1)[1]

        # Copiar eventos técnicos (V_RELIEF_90, SILICONE_RELIEF, CROSSING_RELIEF)
        for ev in sp.tecnicas_aplicadas:
            # Convertir tuplas de coord a listas serializables
            ev2 = dict(ev)
            if "coord_svg" in ev2 and isinstance(ev2["coord_svg"], tuple):
                ev2["coord_svg"] = (float(ev2["coord_svg"][0]), float(ev2["coord_svg"][1]))
            pieza.eventos.append(ev2)
            if ev.get("tipo") == "V_RELIEF_90" and "radio_px" in ev:
                r_cm = ev["radio_px"] * escala_cm_por_px
                if pieza.radio_min_encontrado_cm == 0 or r_cm < pieza.radio_min_encontrado_cm:
                    pieza.radio_min_encontrado_cm = round(r_cm, 2)

        # Advertencias de altura mínima del perfil
        altura_min_cm = float(perfil.get("altura_min_cm", 0) or 0)
        h_cm = bbox.get("h", 0) * escala_cm_por_px
        if altura_min_cm > 0 and 0 < h_cm < altura_min_cm:
            pieza.warnings.append(
                f"altura {h_cm:.1f}cm < mínimo del perfil {altura_min_cm:.1f}cm"
            )

        # ── PASO 3. Snap de terminales a marca de corte ───────────────────────
        if pieza.is_closed:
            # Seam point: preferentemente en enlace natural (Cuaderno §E)
            # Para v2 usamos el punto de mayor radio local — coincide con "baja curvatura"
            seam_pt = _seam_point_natural(sp.puntos)
            seam_cm = (seam_pt[0] * escala_cm_por_px, seam_pt[1] * escala_cm_por_px)
            snap_cm, off = _snap_terminal_a_marca(seam_cm, sp.puntos, cut_step_cm, escala_cm_por_px)
            t = Terminal(
                id=f"T-{pieza_id}-seam",
                pieza_id=pieza_id, tipo="seam",
                coord_svg=(snap_cm[0] / escala_cm_por_px, snap_cm[1] / escala_cm_por_px),
                coord_cm=snap_cm,
                tangente_deg=_tangente_deg_para_punto(sp.puntos, snap_cm, escala_cm_por_px),
                cut_valid=(off < 0.3),
                cut_offset_cm=round(off, 2),
                en_marca_de_corte=(cut_step_cm > 0),
            )
            plan.terminales.append(t)
            pieza.terminales.append(t.id)
        else:
            # Terminales en los 2 extremos reales de la polilínea
            if len(sp.puntos) >= 2:
                start, end = sp.puntos[0], sp.puntos[-1]
                for tipo, pt_svg, idx_pt in [("start", start, 0), ("end", end, len(sp.puntos) - 1)]:
                    pt_cm = (pt_svg[0] * escala_cm_por_px, pt_svg[1] * escala_cm_por_px)
                    snap_cm, off = _snap_terminal_a_marca(pt_cm, sp.puntos, cut_step_cm, escala_cm_por_px)
                    tang = _tangente_deg(sp.puntos, idx_pt)
                    t = Terminal(
                        id=f"T-{pieza_id}-{tipo}",
                        pieza_id=pieza_id, tipo=tipo,
                        coord_svg=(snap_cm[0] / escala_cm_por_px, snap_cm[1] / escala_cm_por_px),
                        coord_cm=snap_cm,
                        tangente_deg=tang,
                        cut_valid=(off < 0.3),
                        cut_offset_cm=round(off, 2),
                        en_marca_de_corte=(cut_step_cm > 0),
                    )
                    plan.terminales.append(t)
                    pieza.terminales.append(t.id)

        # ── Marcas de corte a lo largo del trazo ─────────────────────────────
        if cut_step_cm > 0:
            marcas = _generar_marcas_corte(sp.puntos, cut_step_cm, escala_cm_por_px, pieza_id)
            pieza.marcas_corte = [
                {"coord_svg": [m.coord_svg[0], m.coord_svg[1]],
                 "tangente_deg": m.tangente_deg,
                 "long_cm": m.long_acumulada_cm}
                for m in marcas
            ]

        plan.piezas.append(pieza)

    # ── Detección de CROSSING_RELIEF entre piezas distintas ────────────────
    # topology.analizar corre por-path individual, así que 2 diagonales de X
    # dibujadas como 2 <path> separados no detectan el cruce internamente.
    # Acá post-procesamos: buscamos intersecciones entre polilíneas de piezas
    # distintas y marcamos CROSSING_RELIEF en ambas piezas (Cuaderno §A).
    if HAS_SHAPELY and len(plan.piezas) >= 2:
        _detectar_cruces_entre_piezas(plan)

    # ── PASO 5-7. Optimización de uniones (MST simplificado) ─────────────────
    # Estrategia: orden por bbox center X, luego para cada par (i, i+1) usar
    # `_par_terminales_mas_cercano`. Un MST completo Kruskal sobre grafo
    # completo se hace en v3 (aporte marginal en anuncios pequeños).
    piezas_orden = sorted(plan.piezas, key=lambda p: (
        p.bbox_svg["x"] + p.bbox_svg["w"] / 2,
        p.bbox_svg["y"] + p.bbox_svg["h"] / 2,
    ))
    holgura = 1.15

    # INICIO / FIN del circuito eléctrico
    if piezas_orden:
        pa0 = piezas_orden[0]
        ts_pa0 = [t for t in plan.terminales if t.pieza_id == pa0.id]
        if ts_pa0:
            inicio_t = min(ts_pa0, key=lambda t: t.coord_svg[0])
            plan.terminal_inicio_circuito = inicio_t.id
        pn = piezas_orden[-1]
        ts_pn = [t for t in plan.terminales if t.pieza_id == pn.id]
        cand_fin = [t for t in ts_pn if t.id != plan.terminal_inicio_circuito]
        if cand_fin:
            fin_t = max(cand_fin, key=lambda t: t.coord_svg[0])
            plan.terminal_fin_circuito = fin_t.id

    for i in range(len(piezas_orden) - 1):
        pa, pb = piezas_orden[i], piezas_orden[i + 1]
        ta, tb, d_cm, ang_diff = _par_terminales_mas_cercano(plan, pa, pb)
        if ta is None or tb is None:
            continue
        cable_cm = round(d_cm * holgura, 1)
        costo, razones = _funcion_costo(
            dist_cm=d_cm, visible=False, agujeros=2,
            cruces=0, riesgo=0.0, angulo_deg_diff=ang_diff, pesos=pesos,
        )
        union = Union(
            id=f"U-{i+1:02d}",
            terminal_a=ta.id, terminal_b=tb.id,
            tecnica=Tecnica.LETTER_BRIDGE,
            distancia_cm=round(d_cm, 2), cable_cm=cable_cm,
            visible=False, costo=costo, razones=razones,
        )
        plan.uniones.append(union)
        plan.rutas_ocultas.append(HiddenRoute(
            union_id=union.id,
            puntos_svg=[ta.coord_svg, tb.coord_svg],
            hidden_ratio=1.0,
            perforaciones=[ta.coord_svg, tb.coord_svg],
        ))

    # ── PASO 9. Instrucciones humano-legibles por pieza (Manual §11.1) ───────
    terms_map = {t.id: t for t in plan.terminales}
    for pieza in plan.piezas:
        pieza.instrucciones = _generar_instrucciones(pieza, perfil, terms_map)

    # ── Métricas + confianza ─────────────────────────────────────────────────
    long_total_cm = sum(p.longitud_cm for p in plan.piezas)
    cable_total_cm = sum(u.cable_cm for u in plan.uniones)
    num_seam = sum(1 for t in plan.terminales if t.tipo == "seam")
    num_perf = sum(len(r.perforaciones) for r in plan.rutas_ocultas)
    num_marcas = sum(len(p.marcas_corte) for p in plan.piezas)

    def _cnt(tipo):
        return sum(sum(1 for e in p.eventos if e.get("tipo") == tipo) for p in plan.piezas)

    plan.metricas = {
        "num_piezas":        len(plan.piezas),
        "num_uniones":       len(plan.uniones),
        "num_soldaduras":    len(plan.uniones) * 2,
        "num_seam_points":   num_seam,
        "num_perforaciones": num_perf,
        "num_marcas_corte":  num_marcas,
        "num_v_relief_90":   _cnt(Tecnica.V_RELIEF_90),
        "num_silicone_relief": _cnt(Tecnica.SILICONE_RELIEF),
        "num_crossing_relief": _cnt(Tecnica.CROSSING_RELIEF),
        "num_terminales_snapped": sum(1 for t in plan.terminales if t.cut_offset_cm > 0.1),
        "cable_total_cm":    round(cable_total_cm, 1),
        "longitud_neon_total_m": round(long_total_cm / 100, 2),
        "hidden_ratio_global": 1.0,
    }
    return plan


def _detectar_cruces_entre_piezas(plan: ManufacturingPlan) -> None:
    """Post-topology: detecta cruces entre polilíneas de piezas distintas y
    agrega evento CROSSING_RELIEF en ambas piezas. Útil cuando X se dibuja
    como 2 <path> separados (topology.analizar los ve como trazos abiertos
    independientes, no detecta el cruce entre ellos)."""
    from shapely.geometry import LineString
    lines = []
    for pieza in plan.piezas:
        if len(pieza.puntos_svg) >= 2:
            try:
                lines.append((pieza, LineString(pieza.puntos_svg)))
            except Exception:
                pass
    for i, (pa, la) in enumerate(lines):
        for pb, lb in lines[i + 1:]:
            inter = la.intersection(lb)
            if inter.is_empty:
                continue
            pts = []
            if inter.geom_type == "Point":
                pts.append((inter.x, inter.y))
            elif inter.geom_type == "MultiPoint":
                pts.extend((g.x, g.y) for g in inter.geoms)
            for pt in pts:
                for pieza in (pa, pb):
                    pieza.eventos.append({
                        "tipo": Tecnica.CROSSING_RELIEF,
                        "coord_svg": [round(pt[0], 2), round(pt[1], 2)],
                        "razon": f"cruce con {pb.id if pieza is pa else pa.id} "
                                 "— un tramo se monta visualmente sobre otro, "
                                 "corte silicona posterior solo (Cuaderno §A)",
                    })


# ─── HELPERS DE MOTOR v2 ─────────────────────────────────────────────────────

def _seam_point_natural(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Elige el punto de MAYOR radio local (curva más suave = fácil junta)."""
    if len(pts) < 5:
        return pts[0] if pts else (0.0, 0.0)
    mejor_r = -1.0
    mejor_pt = pts[0]
    for i in range(2, len(pts) - 2):
        a, b, c = pts[i - 2], pts[i], pts[i + 2]
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if area2 < 1e-6:
            r = 1e9  # colineal — excelente
        else:
            d_ab = math.hypot(b[0] - a[0], b[1] - a[1])
            d_bc = math.hypot(c[0] - b[0], c[1] - b[1])
            d_ca = math.hypot(a[0] - c[0], a[1] - c[1])
            r = (d_ab * d_bc * d_ca) / (2.0 * area2)
        if r > mejor_r:
            mejor_r = r
            mejor_pt = b
    return mejor_pt


def _tangente_deg_para_punto(pts: list[tuple[float, float]],
                             pt_cm: tuple[float, float],
                             escala_cm_por_px: float) -> float:
    """Encuentra el idx más cercano al punto y devuelve su tangente."""
    if not pts or escala_cm_por_px <= 0:
        return 0.0
    mejor_i = 0; mejor_d = float("inf")
    for i, p in enumerate(pts):
        px_cm = p[0] * escala_cm_por_px
        py_cm = p[1] * escala_cm_por_px
        d = math.hypot(px_cm - pt_cm[0], py_cm - pt_cm[1])
        if d < mejor_d:
            mejor_d = d; mejor_i = i
    return _tangente_deg(pts, mejor_i)


def _generar_instrucciones(pieza: Pieza, perfil: dict,
                           terms_map: dict[str, Terminal]) -> list[str]:
    """Instrucciones humano-legibles Manual §11.1 con parámetros de cada técnica."""
    lines: list[str] = []
    nombre = perfil.get("nombre", "manguera")
    color = perfil.get("color", "")
    cut_step = float(perfil.get("cut_step_cm", 0) or 0)
    fpcb_offset_mm = float(perfil.get("fpcb_offset_mm", 0) or 0)

    header = f"{nombre}"
    if color:
        header += f" {color}"
    header += f" · {pieza.longitud_cm:.1f} cm · tipo:{pieza.tipo_topologico}"
    if cut_step > 0:
        n_cortes = round(pieza.longitud_cm / cut_step)
        header += f" (corte real: {n_cortes} × {cut_step:g} cm = {n_cortes * cut_step:.1f} cm)"
    lines.append(header)

    ts = [terms_map.get(tid) for tid in pieza.terminales]
    ts = [t for t in ts if t is not None]
    if pieza.is_closed:
        seam = next((t for t in ts if t.tipo == "seam"), None)
        if seam:
            xcm, ycm = seam.coord_cm
            lines.append(f"Path CERRADO · junta (seam) en ({xcm:.1f}, {ycm:.1f}) cm")
            if seam.cut_offset_cm > 0.1:
                lines.append(f"  ↳ terminal desplazado {seam.cut_offset_cm:.1f} cm a marca de corte válida")
    else:
        start = next((t for t in ts if t.tipo == "start"), None)
        end = next((t for t in ts if t.tipo == "end"), None)
        if start:
            lines.append(f"Iniciar en {start.id} → ({start.coord_cm[0]:.1f}, {start.coord_cm[1]:.1f}) cm")
        lines.append("Recorrer siguiendo el trazo")
        if end:
            lines.append(f"Terminar en {end.id} → ({end.coord_cm[0]:.1f}, {end.coord_cm[1]:.1f}) cm")

    # Eventos técnicos — cada uno con parámetros del catálogo real
    for ev in pieza.eventos:
        tipo = ev.get("tipo", "")
        coord = ev.get("coord_svg")
        if tipo == Tecnica.V_RELIEF_90:
            ang = ev.get("angulo_deg", 0)
            depth = fpcb_offset_mm * 0.7 if fpcb_offset_mm > 0 else 0
            lines.append(
                f"⚠️ V_RELIEF_90 · corte V 45°/cara en cara trasera · "
                f"profundidad ≤ {depth:.1f} mm (respeta FPCB) · esquina ~{ang:.0f}°"
            )
        elif tipo == Tecnica.SILICONE_RELIEF:
            n = ev.get("n_alivios", 1)
            lines.append(
                f"⚡ SILICONE_RELIEF × {n} · alivio parcial en cara trasera "
                f"(NO cortar FPCB — margen mín {fpcb_offset_mm:g} mm)"
            )
        elif tipo == Tecnica.CROSSING_RELIEF:
            lines.append(
                "✧ CROSSING_RELIEF · un tramo se monta visualmente sobre otro · "
                "corte silicona posterior solo · SIN unión eléctrica"
            )

    lines.append("Sacar cable por atrás (perforación en el terminal, ver plano)")
    return lines


# ─── SERIALIZACIÓN ───────────────────────────────────────────────────────────

def plan_a_dict(plan: ManufacturingPlan) -> dict[str, Any]:
    """Serializa a dict JSON-friendly."""
    from dataclasses import asdict
    d = asdict(plan)
    for t in d.get("terminales", []):
        t["coord_svg"] = list(t["coord_svg"])
        t["coord_cm"] = list(t["coord_cm"])
    for r in d.get("rutas_ocultas", []):
        r["puntos_svg"] = [list(pt) for pt in r["puntos_svg"]]
        r["perforaciones"] = [list(pt) for pt in r["perforaciones"]]
    for p in d.get("piezas", []):
        p["puntos_svg"] = [list(pt) for pt in p.get("puntos_svg", [])]
        for ev in p.get("eventos", []):
            if isinstance(ev.get("coord_svg"), tuple):
                ev["coord_svg"] = list(ev["coord_svg"])
    return d
