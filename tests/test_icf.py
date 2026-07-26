"""Tests del motor ICF (Índice de Complejidad de Fabricación).

Los tests cubren tres capas:
  1. Primitivas geométricas — flattening + métricas de polilínea con figuras
     conocidas (círculo, cuadrado, letra sintética).
  2. Extracción de features desde SVGData — que respete huecos, tipo, etc.
  3. compute_icf — que los tiempos sean positivos, monótonos con las
     features y que el desglose sume al total.
  4. Regresión (golden) — un SVG fijo debe producir el mismo ICF ± tolerancia
     entre corridas; detecta cambios accidentales en flattening/constantes.
"""
import math

import pytest

from calculator import (
    ICFFeatures,
    _polyline_metrics,
    apply_icf_to_result,
    apply_scale,
    compute_icf,
    cotizar_letras,
    extract_icf_features,
    parse_svg,
)
from catalog_data import ICF_CONFIG

# ─── PRIMITIVAS GEOMÉTRICAS ─────────────────────────────────────────────────

def test_polyline_metrics_cuadrado_100mm():
    """Cuadrado 100×100: perímetro 400, 4 esquinas de 90°, κ=2π."""
    theta_rad = math.radians(15)
    # 4 lados como 5 puntos (último = primero cerrado)
    subpaths = [[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]]
    L, N_c, kappa, N_n = _polyline_metrics(subpaths, closed=True,
                                            corner_theta_rad=theta_rad, scale=1.0)
    assert L == pytest.approx(400.0, abs=0.01)
    assert N_c == 4
    # κ total de un cuadrado cerrado = 2π (una vuelta completa)
    assert kappa == pytest.approx(2 * math.pi, abs=0.01)
    assert N_n == 5


def test_polyline_metrics_circulo_aproximado():
    """Circulo 32-gon: κ ≈ 2π, N_c=0 (ángulos menores al umbral)."""
    theta_rad = math.radians(15)
    n = 32
    r = 50.0
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    pts.append(pts[0])   # cerrar
    L, N_c, kappa, _ = _polyline_metrics([pts], closed=True,
                                          corner_theta_rad=theta_rad, scale=1.0)
    # perímetro ≈ 2πr
    assert L == pytest.approx(2 * math.pi * r, rel=0.01)
    # Con 32 lados, ángulo por vértice ≈ 11.25° < 15° → 0 esquinas
    assert N_c == 0
    # κ total = 2π (una vuelta)
    assert kappa == pytest.approx(2 * math.pi, abs=0.05)


def test_polyline_metrics_scale():
    """El parámetro scale escala L pero NO ángulos (curvatura invariante)."""
    theta_rad = math.radians(15)
    subpaths = [[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]]
    L1, N_c1, kappa1, _ = _polyline_metrics(subpaths, True, theta_rad, scale=1.0)
    L2, N_c2, kappa2, _ = _polyline_metrics(subpaths, True, theta_rad, scale=10.0)
    assert L2 == pytest.approx(L1 * 10)
    assert N_c1 == N_c2
    assert kappa1 == pytest.approx(kappa2)


def test_polyline_metrics_abierto_no_cierra():
    """Polilínea abierta no agrega ángulo de cierre."""
    theta_rad = math.radians(15)
    subpaths = [[(0, 0), (100, 0), (100, 100)]]  # L-shape, 1 esquina
    _, N_c_open, kappa_open, _ = _polyline_metrics(subpaths, False, theta_rad, 1.0)
    _, N_c_closed, kappa_closed, _ = _polyline_metrics(subpaths, True, theta_rad, 1.0)
    assert N_c_open == 1
    assert N_c_closed == 2   # cierre agrega otra esquina
    assert kappa_closed > kappa_open


# ─── EXTRACCIÓN DE FEATURES DESDE SVGData ────────────────────────────────────

RECT_SVG = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="300" height="300">
  <rect x="50" y="50" width="200" height="200" fill="black"/>
</svg>"""


def test_extract_features_rectangulo():
    """Rectángulo 20×20 cm real → 4 esquinas, P=800 mm, N_piezas=1."""
    data = apply_scale(parse_svg(RECT_SVG), real_width_cm=20, altura_cm=20)
    f = extract_icf_features(data, tipo="letras_3d", n_modulos_led=6,
                             material_cara_id="aluminio_cal22")
    assert f.N_piezas == 1
    assert f.N_esquinas == 4
    assert f.P_mm == pytest.approx(800.0, abs=1)
    assert f.A_mm2 == pytest.approx(40000.0, abs=100)
    assert f.N_huecos == 0
    assert f.kappa_total_rad == pytest.approx(2 * math.pi, abs=0.05)
    assert f.tipo == "letras_3d"
    # Masa: 0.04 m² × 2.7 kg/m² = 0.108 kg
    assert f.masa_kg == pytest.approx(0.108, abs=0.01)


LETRA_O_SVG = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
  <path d="M10,10 L190,10 L190,190 L10,190 Z" fill="black"/>
  <path d="M60,60 L140,60 L140,140 L60,140 Z" fill="white"/>
</svg>"""


def test_extract_features_ignora_huecos_en_perimetro():
    """Un hueco (fill blanco contenido) NO cuenta en P_mm/A_mm2 ni suma piezas.
    Sí cuenta en L_mm (longitud total de contornos = todos los paths)."""
    data = apply_scale(parse_svg(LETRA_O_SVG), real_width_cm=20)
    f = extract_icf_features(data, tipo="letras_3d")
    # Solo 1 pieza real (contador es hueco)
    assert f.N_piezas == 1
    assert f.N_huecos == 1
    # L incluye el hueco (se corta también), P solo el exterior
    assert f.L_mm > f.P_mm


def test_extract_features_planas_sin_sellado():
    """Letras planas no llevan cordón de sellado."""
    data = apply_scale(parse_svg(RECT_SVG), real_width_cm=20)
    f = extract_icf_features(data, tipo="letras_planas")
    assert f.P_sellable_mm == 0.0


def test_extract_features_letras_3d_sellado_2juntas():
    """Cajón de luz con fondo PVC: 2 juntas → P_sellable = 2 × P."""
    data = apply_scale(parse_svg(RECT_SVG), real_width_cm=20)
    f = extract_icf_features(data, tipo="letras_3d", tipo_construccion="cajon_luz")
    # Tolerancia de 0.1 mm: P_mm y P_sellable_mm se redondean por separado
    assert f.P_sellable_mm == pytest.approx(2 * f.P_mm, abs=0.1)


def test_extract_features_retro_halo_1junta():
    """Retro/halo no lleva fondo → 1 junta → P_sellable = P."""
    data = apply_scale(parse_svg(RECT_SVG), real_width_cm=20)
    f = extract_icf_features(data, tipo="letras_3d", tipo_construccion="retro_halo")
    assert f.P_sellable_mm == pytest.approx(f.P_mm, abs=0.1)


# ─── COMPUTE_ICF (tiempos por proceso) ──────────────────────────────────────

def _features_default():
    return ICFFeatures(
        L_mm=1000.0, P_mm=1000.0, A_mm2=50000.0,
        N_piezas=1, N_huecos=0, N_esquinas=4,
        kappa_total_rad=2 * math.pi, N_nodos=5,
        P_sellable_mm=2000.0, N_modulos_led=6,
        masa_kg=0.15, tipo="letras_3d",
    )


def test_compute_icf_todos_los_procesos_positivos():
    """Con features típicos, todo tiempo debe ser ≥ 0 y el total = suma."""
    r = compute_icf(_features_default())
    procesos = ["T_corte_min", "T_doblado_min", "T_sellado_min",
                "T_cableado_min", "T_armado_min", "T_manip_min"]
    for k in procesos:
        assert r[k] >= 0
    # Los tiempos individuales se redondean a 2 dp antes de sumar; el total
    # se calcula sobre valores no redondeados. Tolerancia = 0.06 min cubre 6 términos.
    total_expected = sum(r[k] for k in procesos)
    assert r["T_total_min"] == pytest.approx(total_expected, abs=0.06)


def test_compute_icf_monotonicidad_leds():
    """Más módulos LED → más tiempo de cableado y total."""
    f_bajo = _features_default()
    f_bajo.N_modulos_led = 3
    f_alto = _features_default()
    f_alto.N_modulos_led = 20
    r_bajo = compute_icf(f_bajo)
    r_alto = compute_icf(f_alto)
    assert r_alto["T_cableado_min"] > r_bajo["T_cableado_min"]
    assert r_alto["T_total_min"] > r_bajo["T_total_min"]


def test_compute_icf_monotonicidad_esquinas():
    """Más esquinas → más tiempo de corte (dwell) y doblado."""
    f_pocos = _features_default()
    f_pocos.N_esquinas = 2
    f_muchas = _features_default()
    f_muchas.N_esquinas = 20
    r_pocos = compute_icf(f_pocos)
    r_muchas = compute_icf(f_muchas)
    assert r_muchas["T_corte_min"] > r_pocos["T_corte_min"]
    assert r_muchas["T_doblado_min"] > r_pocos["T_doblado_min"]


def test_compute_icf_planas_sin_doblado_ni_sellado():
    f = _features_default()
    f.tipo = "letras_planas"
    f.P_sellable_mm = 0.0
    r = compute_icf(f)
    assert r["T_doblado_min"] == 0.0
    assert r["T_sellado_min"] == 0.0


def test_compute_icf_caja_4dobleces_fijos():
    """En caja, doblado incluye 4 esquinas fijas (independiente del gráfico)."""
    f = _features_default()
    f.tipo = "caja_luz"
    f.N_esquinas = 0     # gráfico sin esquinas
    r = compute_icf(f)
    k = ICF_CONFIG["constantes"]
    esperado_min = (f.P_mm / k["v_b_mm_s"] + 4 * k["t_bend_s"]) / 60.0
    assert r["T_doblado_min"] == pytest.approx(esperado_min, abs=0.01)


def test_compute_icf_norm_positiva():
    """ICF normalizado sale > 0 y consistente (T_total / T_ref)."""
    r = compute_icf(_features_default())
    assert r["icf_norm"] > 0
    assert r["T_ref_min"] > 0
    assert r["icf_norm"] == pytest.approx(r["T_total_min"] / r["T_ref_min"], abs=0.001)


# ─── PIPELINE END-TO-END ─────────────────────────────────────────────────────

def test_apply_icf_pobla_quote_result():
    """apply_icf_to_result debe rellenar los campos icf_* del QuoteResult."""
    data = parse_svg(RECT_SVG)
    r = cotizar_letras(svg_data=data, real_width_cm=20, altura_letra_cm=20)
    apply_icf_to_result(data, r, mo_tarifa=150.0, material_cara_id="aluminio_cal22")
    assert r.icf_total_min > 0
    assert r.icf_features["N_piezas"] == 1
    assert r.icf_desglose_min["T_total_min"] == r.icf_total_min
    # $150/h × T_h = mo_costo_icf
    assert r.mo_costo_icf == pytest.approx(r.icf_total_min / 60.0 * 150.0, abs=0.5)


def test_apply_icf_inactivo_no_hace_nada():
    """Si ICF_CONFIG['activo']=False, deja los campos vacíos."""
    activo_original = ICF_CONFIG["activo"]
    try:
        ICF_CONFIG["activo"] = False
        data = parse_svg(RECT_SVG)
        r = cotizar_letras(svg_data=data, real_width_cm=20, altura_letra_cm=20)
        apply_icf_to_result(data, r, mo_tarifa=150.0)
        assert r.icf_total_min == 0.0
        assert r.icf_features == {}
    finally:
        ICF_CONFIG["activo"] = activo_original


# ─── GOLDEN TEST (regresión) ─────────────────────────────────────────────────

def test_icf_golden_rectangulo_30cm():
    """Un rectángulo 30×30 cm con las constantes por defecto debe dar valores
    conocidos. Si esta prueba se rompe: OJO — significa que se alteró el
    flattening, alguna constante o el modelo. Actualiza los números
    intencionalmente (nunca al azar)."""
    svg = b"""<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="300" height="300">
      <rect x="50" y="50" width="200" height="200" fill="black"/>
    </svg>"""
    data = apply_scale(parse_svg(svg), real_width_cm=30, altura_cm=30)
    f = extract_icf_features(data, tipo="letras_3d", n_modulos_led=8,
                             material_cara_id="acrilico_3mm")
    # Números fijados (jul-2026, defaults ICF industria):
    assert f.L_mm == pytest.approx(1200.0, abs=1)
    assert f.P_mm == pytest.approx(1200.0, abs=1)
    assert f.N_esquinas == 4
    assert f.kappa_total_rad == pytest.approx(6.283, abs=0.01)   # 2π
    # Masa: 0.09 m² × 3.6 kg/m² acrílico = 0.324 kg
    assert f.masa_kg == pytest.approx(0.324, abs=0.01)

    r = compute_icf(f)
    # T_total esperado ≈ 20.47 min con las constantes de fábrica
    assert r["T_total_min"] == pytest.approx(20.47, abs=0.5)
