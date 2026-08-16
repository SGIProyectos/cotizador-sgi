"""Tests del motor de cotización de neón — puerto de los 10 smoke tests del JS.

Estos tests son CRÍTICOS: garantizan que el motor Python devuelve los mismos
precios que la calibración de taller del JS original (22 pares reales de
imagen+DST). Cualquier drift en los números aquí = drift en el precio real
que se cobra al cliente.

Tolerancias replicadas del smoke-test.mjs (línea eq()): 2% del valor esperado,
mínimo 0.02 absoluto — excepto TEST 6 que usa tolerancia absoluta 0.5.
"""
import pytest

from neon_calculator import (
    NEON_PARAMS_DEFAULTS as P,
)
from neon_calculator import (
    cotizar_neon,
    merge_neon_params,
)

PERFIL_BLANCO = {
    "id": "std-blanco", "nombre": "Neón Estándar 12mm",
    "color": "Blanco cálido", "precio_m": 240, "watts_m": 12, "altura_min_cm": 10,
}
PERFIL_ROJO = {
    "id": "std-rojo", "nombre": "Neón Estándar 12mm",
    "color": "Rojo", "precio_m": 260, "watts_m": 12, "altura_min_cm": 10,
}
FUENTE_100 = {"id": "f100", "nombre": "Fuente 100W estándar",
              "watts": 100, "precio": 380, "tipo": "fuente"}


def _base_by_id(bid: str) -> dict:
    return next(b for b in P["bases"] if b["id"] == bid)


def _forma_by_id(fid: str) -> dict:
    return next(f for f in P["formas"] if f["id"] == fid)


# ═══ TEST 1 · Modo lámina (calibración con corte externo) ═══════════════════
def test_01_modo_lamina_precio_iva():
    """Modo lámina: Lm=5, 120×40 cm, acrílico 3mm rect, con soporte + desperdicio.
    Los defaults nuevos ponen acrílico como aprovisionamiento='corto_afuera'
    (SGI tiene lámina, manda a cortar). El corte externo (380 $/m² × 0.48 m² =
    $182.40) entra al costo directo y se amplifica con merma 5% + margen 35% +
    IVA 16% → precio final ~$4548 (vs $4224.71 del modelo antiguo sin corte)."""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "material": _base_by_id("acr-3-tr"),
            "forma":    _forma_by_id("rect"),
            "incluir_soporte": True, "cobrar_desperdicio": True,
        },
        params=P, urgencia_mult=1,
    )
    assert r.modo_fabricacion == "lamina"
    assert r.aprovisionamiento == "corto_afuera"
    assert r.importe_corte_externo == pytest.approx(182.40, abs=1)
    assert r.precio_iva == pytest.approx(4548.60, abs=5)


# ═══ TEST 1B · Modo lámina con "corto_taller" (sin corte externo) ═══════════
def test_01b_corto_taller_sin_corte_externo():
    """Si el taller tiene su propia cortadora (aprovisionamiento='corto_taller'),
    NO se cobra corte externo. Comparado con TEST 1 debe salir más barato exactamente
    en el importe del corte + su amplificación por merma/margen/IVA."""
    material = dict(_base_by_id("acr-3-tr"))
    material["aprovisionamiento"] = "corto_taller"
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={"material": material, "forma": _forma_by_id("rect"),
              "incluir_soporte": True, "cobrar_desperdicio": True},
        params=P, urgencia_mult=1,
    )
    assert r.aprovisionamiento == "corto_taller"
    assert r.importe_corte_externo == 0
    # Sin corte externo = ~$4224.71 (el número histórico del smoke test JS)
    assert r.precio_iva == pytest.approx(4224.71, abs=5)


# ═══ TEST 1C · Modo "compro_pieza" (MDF, input manual) ═════════════════════
def test_01c_compro_pieza_manual():
    """MDF típico: SGI compra la pieza ya cortado. El usuario captura el costo
    de la pieza por cotización (pieza_costo_override); ese monto entra al desglose
    como una sola partida 'Base · MDF 6mm crudo (pieza cortada)'."""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "material": _base_by_id("mdf-6-crudo"),
            "forma":    _forma_by_id("rect"),
            "pieza_costo_override": 250,    # el usuario pagó $250 por la pieza
            "incluir_soporte": True,
        },
        params=P, urgencia_mult=1,
    )
    assert r.aprovisionamiento == "compro_pieza"
    assert r.importe_base == 250
    assert r.importe_corte_externo == 0        # sin corte propio ni externo
    assert r.importe_desperdicio == 0          # no aplica desperdicio si compras la pieza
    # La partida sale con concepto "(pieza cortada)" y cantidad=1 pza
    base_p = next(x for x in r.insumos if "Base" in x["concepto"])
    assert base_p["cantidad"] == 1
    assert base_p["unidad"] == "pza"
    assert "pieza cortada" in base_p["concepto"]


# ═══ TEST 1D · Override de aprovisionamiento por cotización ═════════════════
def test_01d_aprovisionamiento_override_por_cotizacion():
    """El catálogo dice acrílico='corto_afuera', pero para ESTA cotización el
    usuario compra la pieza ya cortado. `aprovisionamiento_override` fuerza el
    modo sin tocar el catálogo."""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "material": _base_by_id("acr-3-tr"),   # catálogo dice corto_afuera
            "forma":    _forma_by_id("rect"),
            "aprovisionamiento_override": "compro_pieza",
            "pieza_costo_override": 400,
        },
        params=P, urgencia_mult=1,
    )
    assert r.aprovisionamiento == "compro_pieza"
    assert r.importe_base == 400
    assert r.importe_corte_externo == 0


# ═══ TEST 2 · Modo 3D con g/m fallback ═══════════════════════════════════════
def test_02_modo_3d_gramos_fallback():
    """Sin sección de canal → usa peso_gr_m fallback (55 g/m × 5 m = 275 g)."""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={"modo_fabricacion": "3d",
              "fab3d": {"anclajes": 6, "puentes": 2, "tira_led_mm": 12}},
        params=P, urgencia_mult=1,
    )
    assert r.gramos == pytest.approx(275, abs=0.02 * 275)
    assert r.importe_base == 0
    assert r.anclajes == 6
    assert r.puentes == 2


# ═══ TEST 3 · 3D con sección de canal (auto-peso en U) ════════════════════════
def test_03_seccion_canal_auto_peso():
    """Sección en U 16×20×1.6 mm sobre 5 m → ~555 g de PETG.
       area_sec_cm² = (16·1.6 + 2·20·1.6)/100 = 0.896 cm²
       gramos = 0.896 × 500 cm × 1.24 g/cm³ = 555.52 g"""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "modo_fabricacion": "3d",
            "fab3d": {
                "canal_ancho_mm": 16, "canal_alto_mm": 20, "canal_pared_mm": 1.6,
                "anclajes": 6, "puentes": 2, "tira_led_mm": 12,
            },
        },
        params=P, urgencia_mult=1,
    )
    assert r.gramos_auto == pytest.approx(555.52, abs=1)


# ═══ TEST 4 · 3D con override manual (báscula real) ══════════════════════════
def test_04_override_gramos_y_horas():
    """gramos_override + horas_imp_override pisan los cálculos auto."""
    r = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "modo_fabricacion": "3d",
            "fab3d": {
                "canal_ancho_mm": 16, "canal_alto_mm": 20, "canal_pared_mm": 1.6,
                "gramos_override": 350, "horas_imp_override": 2.5,
                "anclajes": 6, "puentes": 2,
            },
        },
        params=P, urgencia_mult=1,
    )
    assert r.gramos == 350
    assert r.horas_imp == 2.5


# ═══ TEST 5 · Retrocompat: sin base ══════════════════════════════════════════
def test_05_sin_base_defaults_lamina():
    """Si no se pasa `base` → modo_fabricacion default = 'lamina'."""
    r = cotizar_neon(
        Lm=2, uniones=1, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 60, "alto_cm": 20},
        params=P, urgencia_mult=1,
    )
    assert r.modo_fabricacion == "lamina"


# ═══ TEST 6 · Urgencia express (×1.45) ═══════════════════════════════════════
def test_06_urgencia_express():
    """El multiplicador de urgencia se aplica sobre el precio (sin IVA)."""
    r_base = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={"modo_fabricacion": "3d",
              "fab3d": {"anclajes": 6, "puentes": 2, "tira_led_mm": 12}},
        params=P, urgencia_mult=1,
    )
    r_urg = cotizar_neon(
        Lm=5, uniones=3, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={"modo_fabricacion": "3d",
              "fab3d": {"anclajes": 6, "puentes": 2, "tira_led_mm": 12}},
        params=P, urgencia_mult=1.45,
    )
    assert r_urg.urgencia_mult == 1.45
    assert r_urg.precio == pytest.approx(r_base.precio * 1.45, abs=0.5)


# ═══ TEST 7 · Edge Lm=0 (no rompe) ═══════════════════════════════════════════
def test_07_edge_lm_cero():
    """Lm=0 no debe romper el cálculo — todo va a 0."""
    r = cotizar_neon(
        Lm=0, uniones=0, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        dimensiones={"ancho_cm": 0, "alto_cm": 0},
        base={"modo_fabricacion": "3d", "fab3d": {}},
        params=P, urgencia_mult=1,
    )
    assert r.lm == 0
    assert r.precio_iva == 0


# ═══ TEST 8 · Multi-color en 3D ══════════════════════════════════════════════
def test_08_multicolor_3d():
    """Dos tramos con perfiles distintos → 2 partidas de 'Neón LED' en el desglose."""
    r = cotizar_neon(
        Lm=5, uniones=4, perfil=PERFIL_BLANCO, fuente=FUENTE_100,
        tramos=[
            {"perfil": PERFIL_BLANCO, "Lm": 3},
            {"perfil": PERFIL_ROJO,   "Lm": 2},
        ],
        dimensiones={"ancho_cm": 120, "alto_cm": 40},
        base={
            "modo_fabricacion": "3d",
            "fab3d": {"canal_ancho_mm": 16, "canal_alto_mm": 20, "canal_pared_mm": 1.6,
                      "anclajes": 6, "puentes": 2, "tira_led_mm": 12},
        },
        params=P, urgencia_mult=1,
    )
    neon_partidas = [x for x in r.insumos if x["concepto"].startswith("Neón LED")]
    assert len(neon_partidas) == 2


# ═══ TEST 9 · merge_neon_params: raw sin fab3d ═══════════════════════════════
def test_09_merge_params_sin_fab3d():
    """Overrides sueltos deben mantener defaults de fab3d intactos."""
    raw = {"cable_m": 3.0, "margen": 0.40}
    m = merge_neon_params(raw)
    assert m["cable_m"] == 3.0
    assert m["margen"] == 0.40
    assert m["fab3d"]["filamento_mxn_g"] == 0.60
    assert len(m["fab3d"]["tiras_led"]) == 5


# ═══ TEST 10 · merge_neon_params: fab3d parcial ══════════════════════════════
def test_10_merge_params_fab3d_parcial():
    """Un override dentro de fab3d no debe borrar los demás campos."""
    raw = {"fab3d": {"filamento_mxn_g": 0.80}}
    m = merge_neon_params(raw)
    assert m["fab3d"]["filamento_mxn_g"] == 0.80
    assert m["fab3d"]["horas_mxn_hora"] == 25
