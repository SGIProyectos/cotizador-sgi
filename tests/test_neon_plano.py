"""Tests del motor v2 de planeación de neón.

Valida que la descomposición topológica cumpla la matriz A-Z del Manual §5
y las microtécnicas del Cuaderno §A-F. Sin OCR — usa análisis topológico
sobre polilíneas parseadas de SVG sintéticos.
"""
from __future__ import annotations

from calculator import parse_svg
from neon_calculator import NEON_PERFILES_DEFAULTS
from neon_plano import Tecnica, construir_plan


def _perfil_std():
    return next(x for x in NEON_PERFILES_DEFAULTS if x["id"] == "std-blanco")


def _construir(svg_bytes: bytes, escala_cm_por_px: float = 0.1):
    data = parse_svg(svg_bytes)
    return construir_plan(data.paths, perfil=_perfil_std(),
                          escala_cm_por_px=escala_cm_por_px)


# ─── Casos por tipo topológico ────────────────────────────────────────────────

def test_o_circulo_es_loop_simple_con_seam():
    """Círculo → 1 pieza cerrada con CLOSED_SEAM (Manual §6.O)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<circle cx="50" cy="50" r="40" fill="none" stroke="red" id="O"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_piezas"] == 1
    assert plan.metricas["num_seam_points"] == 1
    p = plan.piezas[0]
    assert p.is_closed
    assert p.tipo_topologico == "loop_simple"
    assert p.tecnica_dominante == Tecnica.CLOSED_SEAM


def test_l_polyline_detecta_esquina_90_y_aplica_v_relief():
    """L → 1 pieza abierta + V_RELIEF_90 en la esquina de 90° (Manual §6.L)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<polyline points="20,20 20,80 80,80" fill="none" stroke="red" id="L"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_piezas"] == 1
    p = plan.piezas[0]
    assert not p.is_closed
    assert p.tipo_topologico == "trazo_con_esquinas"
    tipos_eventos = [e["tipo"] for e in p.eventos]
    assert Tecnica.V_RELIEF_90 in tipos_eventos


def test_x_dos_paths_separados_detecta_crossing_relief():
    """X con 2 <line> que se cruzan → 2 piezas separadas + CROSSING_RELIEF
    en ambas (Manual §6.X + Cuaderno §A)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<line x1="20" y1="20" x2="80" y2="80" stroke="red" id="d1"/>' \
          b'<line x1="20" y1="80" x2="80" y2="20" stroke="red" id="d2"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_piezas"] == 2
    # Ambas piezas deben tener CROSSING_RELIEF
    for p in plan.piezas:
        tipos = [e["tipo"] for e in p.eventos]
        assert Tecnica.CROSSING_RELIEF in tipos, f"{p.id} no tiene CROSSING_RELIEF"


def test_trazo_recto_no_agrega_v_relief():
    """C simple (arco muy abierto) → no debe forzar V_RELIEF."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<polyline points="20,20 20,80" fill="none" stroke="red" id="I"/></svg>'
    plan = _construir(svg)
    for p in plan.piezas:
        assert not any(e["tipo"] == Tecnica.V_RELIEF_90 for e in p.eventos)


# ─── Marcas de corte + snap a marca ──────────────────────────────────────────

def test_marcas_de_corte_generadas_a_lo_largo_del_trazo():
    """El motor v2 debe distribuir marcas cada cut_step_cm del perfil."""
    # Trazo de 60 unidades SVG × 0.1 cm/u = 6 cm real
    # std-blanco cut_step_cm = 3.75 → ~1 marca (a los 3.75 cm)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<polyline points="20,50 80,50" fill="none" stroke="red" id="rect"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_marcas_corte"] >= 1
    # Cada marca debe traer coord_svg + tangente_deg + long_cm
    p = plan.piezas[0]
    for m in p.marcas_corte:
        assert "coord_svg" in m and len(m["coord_svg"]) == 2
        assert "tangente_deg" in m
        assert "long_cm" in m and m["long_cm"] > 0


def test_terminales_snap_a_marca_de_corte():
    """Los terminales de un path abierto deben snappearse a marca real
    (cut_step_cm del perfil = 3.75 cm para std-blanco)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<polyline points="17,50 82,50" fill="none" stroke="red" id="r"/></svg>'
    plan = _construir(svg)
    # Al menos 1 terminal debe estar snappeado (offset > 0.1cm significa que se movió)
    assert plan.metricas["num_terminales_snapped"] >= 1


# ─── Circuito eléctrico + uniones ────────────────────────────────────────────

def test_multiples_piezas_generan_uniones_y_marca_inicio_fin():
    """N piezas separadas → N-1 uniones + INICIO en la más izquierda + FIN
    en la más derecha (patron del ejemplo `conectakarate.png`)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 100">' \
          b'<rect x="20"  y="30" width="40" height="40" fill="red" id="A"/>' \
          b'<rect x="120" y="30" width="40" height="40" fill="red" id="B"/>' \
          b'<rect x="220" y="30" width="40" height="40" fill="red" id="C"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_piezas"] == 3
    assert plan.metricas["num_uniones"] == 2   # N-1
    assert plan.terminal_inicio_circuito != ""
    assert plan.terminal_fin_circuito != ""
    # INICIO debe pertenecer a la pieza más a la izquierda
    tini = next(t for t in plan.terminales if t.id == plan.terminal_inicio_circuito)
    tfin = next(t for t in plan.terminales if t.id == plan.terminal_fin_circuito)
    assert tini.coord_svg[0] < tfin.coord_svg[0]


def test_par_terminales_mas_cercano_no_diagonal():
    """Dos rectángulos vecinos → la unión debe conectar el terminal
    izquierdo de uno con el derecho del otro, no los extremos opuestos."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">' \
          b'<rect x="10" y="30" width="30" height="40" fill="red" id="A"/>' \
          b'<rect x="70" y="30" width="30" height="40" fill="red" id="B"/></svg>'
    plan = _construir(svg)
    assert plan.metricas["num_uniones"] == 1
    u = plan.uniones[0]
    ta = next(t for t in plan.terminales if t.id == u.terminal_a)
    tb = next(t for t in plan.terminales if t.id == u.terminal_b)
    # La distancia entre los 2 terminales debe ser << distancia diagonal máxima
    from math import hypot
    d_elegida = hypot(tb.coord_cm[0] - ta.coord_cm[0], tb.coord_cm[1] - ta.coord_cm[1])
    # Peor caso teórico: rect A esquina izq (10,30) → rect B esquina der (100,70)
    d_peor = hypot(100 - 10, 70 - 30) * 0.1
    assert d_elegida < d_peor * 0.8


# ─── Instrucciones humano-legibles Manual §11.1 ─────────────────────────────

def test_instrucciones_por_pieza_contienen_material_y_longitud():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<circle cx="50" cy="50" r="30" fill="none" stroke="red" id="O"/></svg>'
    plan = _construir(svg)
    p = plan.piezas[0]
    assert p.instrucciones, "Debe generar instrucciones"
    header = p.instrucciones[0]
    assert "Estándar 12mm" in header or "Blanco cálido" in header
    assert "cm" in header
    # Path cerrado debe mencionar la junta (seam)
    texto_todo = "\n".join(p.instrucciones)
    assert "CERRADO" in texto_todo or "seam" in texto_todo.lower()


def test_instrucciones_mencionan_v_relief_con_angulo_y_profundidad():
    """L con esquina de 90° debe generar instrucción con parámetros reales
    (ángulo, profundidad calculada de fpcb_offset_mm del perfil)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<polyline points="20,20 20,80 80,80" fill="none" stroke="red" id="L"/></svg>'
    plan = _construir(svg)
    p = plan.piezas[0]
    texto = "\n".join(p.instrucciones)
    assert "V_RELIEF_90" in texto
    assert "profundidad" in texto
    assert "mm" in texto


# ─── Versión + confianza ────────────────────────────────────────────────────

def test_version_algoritmo_es_v2_topological():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<circle cx="50" cy="50" r="30" fill="none" stroke="red" id="O"/></svg>'
    plan = _construir(svg)
    assert plan.version_algoritmo == "v2-topological"
    assert plan.confianza >= 0.8


def test_plan_serializa_a_dict_sin_tuplas():
    """plan_a_dict debe devolver JSON válido (sin tuplas de Python)."""
    from neon_plano import plan_a_dict
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' \
          b'<circle cx="50" cy="50" r="30" fill="none" stroke="red" id="O"/></svg>'
    plan = _construir(svg)
    d = plan_a_dict(plan)
    import json
    # No debe explotar
    txt = json.dumps(d)
    assert len(txt) > 100
