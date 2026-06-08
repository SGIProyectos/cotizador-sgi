"""
Tests para calculator.py — núcleo de cálculo de cotizaciones.

Estos tests son CRÍTICOS: un error aquí afecta el precio que se cobra al cliente.
"""
import pytest

from calculator import (
    PathInfo,
    QuoteResult,
    _find_caja_outline,
    _group_design_paths_by_row,
    _parse_viewbox,
    _path_area_shoelace,
    apply_scale,
    cotizar_caja,
    cotizar_letras,
    cotizar_planas,
    laminas_necesarias,
    parse_svg,
    precio_cm2,
)
from catalog_data import LAMINAS, PRECIOS_BASE

# ─── PARSEO Y ESCALA ─────────────────────────────────────────────────────────

class TestParseSVG:
    def test_parses_square(self, square_svg):
        data = parse_svg(square_svg)
        assert data.viewbox_w == 200.0
        assert data.viewbox_h == 200.0
        assert len(data.paths) == 1
        p = data.paths[0]
        assert p.is_closed
        assert p.bbox["w"] == pytest.approx(100, abs=0.5)
        assert p.bbox["h"] == pytest.approx(100, abs=0.5)
        assert p.area_px == pytest.approx(10000, abs=200)
        assert p.perimeter_px == pytest.approx(400, abs=2)

    def test_three_letters_sorted_left_to_right(self, three_letters_svg):
        data = parse_svg(three_letters_svg)
        assert len(data.paths) == 3
        xs = [p.bbox["x"] for p in data.paths]
        assert xs == sorted(xs)
        assert all(p.id.startswith("Letra ") for p in data.paths)

    def test_max_letter_height_detected(self, three_letters_svg):
        data = parse_svg(three_letters_svg)
        assert data.max_letter_height_px == pytest.approx(100, abs=1)

    def test_empty_svg_does_not_crash(self):
        empty = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
        data = parse_svg(empty)
        assert data.paths == []
        assert data.viewbox_w == 10.0


class TestParseViewbox:
    def test_uses_viewbox_when_present(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg viewBox="0 0 100 50" width="200" height="100"/>')
        w, h, unit = _parse_viewbox(root)
        assert w == 100.0
        assert h == 50.0

    def test_detects_mm_unit(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg width="100mm" height="50mm"/>')
        _, _, unit = _parse_viewbox(root)
        assert unit == "mm"

    def test_fallback_when_missing(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg/>')
        w, h, _ = _parse_viewbox(root)
        assert w == 500.0
        assert h == 500.0


class TestApplyScale:
    def test_scale_from_altura_cm(self, square_svg):
        data = parse_svg(square_svg)
        # bbox h ≈ 100 px → altura 50 cm → scale 0.5
        scaled = apply_scale(data, real_width_cm=200.0, altura_cm=50.0)
        assert scaled.scale_factor == pytest.approx(0.5, abs=0.01)
        assert scaled.paths[0].perimeter_cm == pytest.approx(200, abs=2)

    def test_scale_from_real_width_fallback(self, square_svg):
        data = parse_svg(square_svg)
        scaled = apply_scale(data, real_width_cm=100.0)
        # viewbox_w = 200 px → real 100 cm → scale 0.5
        assert scaled.scale_factor == pytest.approx(0.5, abs=0.01)

    def test_scale_factor_squared_for_area(self, square_svg):
        data = parse_svg(square_svg)
        scaled = apply_scale(data, real_width_cm=200.0)
        # scale = 1 → area_cm2 ≈ area_px
        assert scaled.paths[0].area_cm2 == pytest.approx(scaled.paths[0].area_px, rel=0.01)


# ─── HELPERS DE MATERIAL ─────────────────────────────────────────────────────

class TestLaminasNecesarias:
    def test_ceil_division(self):
        # Una lámina típica de PVC 122x244 = 29768 cm²
        mat_id = "pvc_3mm"
        area_lam = LAMINAS[mat_id]["ancho_cm"] * LAMINAS[mat_id]["alto_cm"]
        assert laminas_necesarias(area_lam, mat_id) == 1
        assert laminas_necesarias(area_lam + 1, mat_id) == 2
        assert laminas_necesarias(0, mat_id) == 0

    def test_uses_ceiling(self):
        mat_id = "pvc_3mm"
        area_lam = LAMINAS[mat_id]["ancho_cm"] * LAMINAS[mat_id]["alto_cm"]
        # 1.5 láminas → ceil = 2
        assert laminas_necesarias(area_lam * 1.5, mat_id) == 2


class TestPrecioCm2:
    def test_returns_price_per_cm2(self):
        mat = {"precio": 1000, "ancho_cm": 100, "alto_cm": 100}
        # 1000 / 10000 = 0.1
        assert precio_cm2(mat) == pytest.approx(0.1)

    def test_zero_area_returns_zero(self):
        assert precio_cm2({"precio": 100, "ancho_cm": 0, "alto_cm": 0}) == 0.0

    def test_default_dimensions(self):
        # Sin ancho_cm/alto_cm → usa default 122×244 (= 29768 cm²)
        mat = {"precio": 29768}
        assert precio_cm2(mat) == pytest.approx(1.0, rel=0.01)


# ─── ÁREA SHOELACE ───────────────────────────────────────────────────────────

class TestPathAreaShoelace:
    def test_handles_exception_gracefully(self):
        class FakePath:
            def point(self, t):
                raise RuntimeError("boom")
        assert _path_area_shoelace(FakePath()) == 0.0


# ─── CAJA: OUTLINE Y AGRUPAMIENTO ────────────────────────────────────────────

class TestFindCajaOutline:
    def _make_path(self, x, y, w, h, perimeter_factor=1.0):
        # perimeter rectangular base = 2*(w+h); factor multiplica para simular no-rect
        peri = 2 * (w + h) * perimeter_factor
        return PathInfo(
            id="p", perimeter_px=peri, area_px=w * h,
            bbox={"x": x, "y": y, "w": w, "h": h}, is_closed=True,
        )

    def test_picks_largest_rectangular_path(self):
        big   = self._make_path(0, 0, 200, 100)   # rect grande
        small = self._make_path(10, 10, 50, 50)   # rect chico
        out = _find_caja_outline([small, big])
        assert out is big

    def test_returns_none_when_only_complex_paths(self):
        # perimeter alto vs bbox → no rectangular
        weird = self._make_path(0, 0, 100, 100, perimeter_factor=5.0)
        assert _find_caja_outline([weird]) is None

    def test_empty_list(self):
        assert _find_caja_outline([]) is None


class TestGroupDesignPathsByRow:
    def _make(self, x, y, w=10, h=10):
        return PathInfo("", 0, 0, {"x": x, "y": y, "w": w, "h": h}, True)

    def test_groups_overlapping_y(self):
        a = self._make(0, 0)
        b = self._make(20, 5)   # solapa
        rows = _group_design_paths_by_row([a, b])
        assert len(rows) == 1
        assert len(rows[0]) == 2

    def test_separates_distant_rows(self):
        a = self._make(0, 0, h=10)
        b = self._make(0, 100, h=10)
        rows = _group_design_paths_by_row([a, b])
        assert len(rows) == 2

    def test_empty(self):
        assert _group_design_paths_by_row([]) == []


# ─── COTIZAR LETRAS 3D ───────────────────────────────────────────────────────

class TestCotizarLetras:
    def _quote(self, svg_bytes, **overrides):
        data = parse_svg(svg_bytes)
        defaults = dict(
            real_width_cm=200.0,
            altura_letra_cm=50.0,
            uso="exterior",
            tipo_cara="auto",
            tipo_cercha="auto",
            cercha_cm=0.0,
            margen_ganancia=0.35,
            tipo_construccion="cajon_luz",
            tipo_multiplicador="acrilico_con_luz_std",
            ajuste_pct=0.0,
        )
        defaults.update(overrides)
        return cotizar_letras(svg_data=data, **defaults)

    def test_returns_quote_result(self, square_svg):
        r = self._quote(square_svg)
        assert isinstance(r, QuoteResult)
        assert r.tipo == "letras_3d"
        assert r.paths_count == 1

    def test_iva_is_16_percent(self, square_svg):
        r = self._quote(square_svg)
        assert r.iva == pytest.approx(r.subtotal * 0.16, rel=1e-6)

    def test_total_equals_subtotal_plus_iva(self, square_svg):
        r = self._quote(square_svg)
        assert r.total == pytest.approx(r.subtotal + r.iva, rel=1e-6)

    def test_precio_venta_costo_uses_margin(self, square_svg):
        r = self._quote(square_svg, margen_ganancia=0.4)
        # piso por costo = total / (1 - 0.4) = total / 0.6
        assert r.precio_venta_costo == pytest.approx(round(r.total / 0.6, 2), abs=0.05)

    def test_precio_venta_formula(self, square_svg):
        # altura=50, precio_cm=10, mult=4.5 → 50*10*4.5 = 2250 por letra
        r = self._quote(square_svg, altura_letra_cm=50.0, ajuste_pct=0.0)
        mult = PRECIOS_BASE["multiplicadores"]["acrilico_con_luz_std"]
        precio_cm = PRECIOS_BASE["precio_cm"]
        esperado = 50.0 * precio_cm * mult  # una sola letra
        assert r.precio_venta_sugerido == pytest.approx(esperado, abs=1.0)

    def test_ajuste_pct_aplica(self, square_svg):
        sin = self._quote(square_svg, ajuste_pct=0.0)
        con = self._quote(square_svg, ajuste_pct=10.0)
        assert con.precio_venta_sugerido == pytest.approx(sin.precio_venta_sugerido * 1.10, rel=0.001)

    def test_tres_letras_proporcional(self, three_letters_svg):
        una = self._quote(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><path d="M10,50 L110,50 L110,150 L10,150 Z"/></svg>',
                          real_width_cm=600.0)
        tres = self._quote(three_letters_svg, real_width_cm=600.0)
        assert tres.paths_count == 3
        # Tres letras cuadradas idénticas → precio_venta ≈ 3× una sola
        assert tres.precio_venta_sugerido == pytest.approx(una.precio_venta_sugerido * 3, rel=0.05)

    def test_desglose_letras_no_vacio(self, three_letters_svg):
        r = self._quote(three_letters_svg, real_width_cm=600.0)
        assert len(r.desglose_letras) == 3
        for d in r.desglose_letras:
            assert d["alto_cm"] > 0
            assert d["precio_letra"] > 0

    def test_sin_luz_no_genera_costo_led(self, square_svg):
        r = self._quote(square_svg, tipo_construccion="sin_luz")
        assert r.costo_led == 0.0
        assert r.modulos_led == 0

    def test_silvatrim_se_agrega(self, square_svg):
        r = self._quote(square_svg)
        assert r.silvatrim
        assert r.metros_silvatrim > 0
        assert r.costo_silvatrim > 0

    def test_invalid_construction_falls_back(self, square_svg):
        # tipo_construccion no existente → no debe crashear, usa cajon_luz default
        r = self._quote(square_svg, tipo_construccion="no_existe")
        assert r.tipo == "letras_3d"

    def test_altura_auto_detectada_cuando_no_se_da(self, square_svg):
        r = self._quote(square_svg, altura_letra_cm=0.0)
        assert r.altura_letra_cm > 0


# ─── COTIZAR PLANAS ──────────────────────────────────────────────────────────

class TestCotizarPlanas:
    def _quote(self, svg_bytes, **overrides):
        data = parse_svg(svg_bytes)
        defaults = dict(
            real_width_cm=200.0,
            material_id="acrilico_3mm",
            margen_ganancia=0.35,
            tipo_multiplicador="aluminio_sin_luz",
            ajuste_pct=0.0,
        )
        defaults.update(overrides)
        return cotizar_planas(svg_data=data, **defaults)

    def test_returns_quote_result(self, square_svg):
        r = self._quote(square_svg)
        assert r.tipo == "letras_planas"

    def test_no_costo_iluminacion(self, square_svg):
        r = self._quote(square_svg)
        assert r.costo_led == 0.0
        assert r.costo_fuente == 0.0
        assert r.modulos_led == 0

    def test_iva_y_total(self, square_svg):
        r = self._quote(square_svg)
        assert r.iva == pytest.approx(r.subtotal * 0.16, rel=1e-6)
        assert r.total == pytest.approx(r.subtotal + r.iva, rel=1e-6)

    def test_material_invalido_usa_default(self, square_svg):
        r = self._quote(square_svg, material_id="material_inexistente")
        # cae a acrilico_3mm
        assert r.material_cara["nombre"] == LAMINAS["acrilico_3mm"]["nombre"]

    def test_costo_proporcional_a_area(self, square_svg):
        # Doblar el real_width_cm cuadruplica el área y el costo
        r1 = self._quote(square_svg, real_width_cm=100.0)
        r2 = self._quote(square_svg, real_width_cm=200.0)
        assert r2.costo_material_cara == pytest.approx(r1.costo_material_cara * 4, rel=0.05)


# ─── COTIZAR CAJA ────────────────────────────────────────────────────────────

class TestCotizarCaja:
    def _quote(self, svg_bytes, **overrides):
        data = parse_svg(svg_bytes)
        defaults = dict(
            real_width_cm=200.0,
            profundidad_cm=15.0,
            tipo_cara="lona",
            led_id="auto",
            uso="exterior",
            vistas=1,
            margen_ganancia=0.35,
        )
        defaults.update(overrides)
        return cotizar_caja(svg_data=data, **defaults)

    def test_returns_quote_result(self, caja_svg):
        r = self._quote(caja_svg)
        assert r.tipo == "caja_luz"

    def test_dimensiones_calculadas(self, caja_svg):
        # Outline path bbox: w=380, h=180 → ratio 380/180. Con real_width=200 → caja_h ≈ 200*180/380 ≈ 94.7
        r = self._quote(caja_svg, real_width_cm=200.0)
        # area = 200 × ~95 = ~19000 cm²
        assert 15000 < r.area_cara_cm2 < 22000

    def test_iva_y_total(self, caja_svg):
        r = self._quote(caja_svg)
        assert r.iva == pytest.approx(r.subtotal * 0.16, rel=1e-6)
        assert r.total == pytest.approx(r.subtotal + r.iva, rel=1e-6)

    def test_precio_venta_es_total_dividido_por_1_menos_margen(self, caja_svg):
        r = self._quote(caja_svg, margen_ganancia=0.4)
        assert r.precio_venta_sugerido == pytest.approx(r.total / 0.6, rel=1e-6)

    def test_vinil_corte_separa_base_y_vinil(self, caja_svg):
        r = self._quote(caja_svg, tipo_cara="vinil_corte", base_cara_vinil="lona")
        # debe registrar vinil_filas
        assert "vinil_filas" in r.material_cara
        assert r.material_cara["base"] == "lona"
        assert r.material_cara["vinil_area_m2"] > 0

    def test_dos_vistas_cambia_fondo(self, caja_svg):
        r1 = self._quote(caja_svg, vistas=1)
        r2 = self._quote(caja_svg, vistas=2)
        # vistas=1 usa alucobon, vistas=2 usa PVC
        assert r1.material_fondo["nombre"] != r2.material_fondo["nombre"]

    def test_outline_ausente_usa_viewbox(self):
        # SVG sin contorno claro: solo elementos de diseño
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200" width="300" height="200">
          <path d="M50,50 L100,50 L100,100 L50,100 Z"/>
        </svg>"""
        r = self._quote(svg, real_width_cm=300.0)
        # Sin outline detectado → usa viewbox completo, alto proporcional
        assert r.area_cara_cm2 > 0
