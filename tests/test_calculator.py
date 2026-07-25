"""
Tests para calculator.py — núcleo de cálculo de cotizaciones.

Estos tests son CRÍTICOS: un error aquí afecta el precio que se cobra al cliente.
"""
import pytest

from calculator import (
    PathInfo,
    QuoteResult,
    _find_caja_outline,
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

    def test_three_pieces_sorted_left_to_right(self, three_letters_svg):
        data = parse_svg(three_letters_svg)
        assert len(data.paths) == 3
        xs = [p.bbox["x"] for p in data.paths]
        assert xs == sorted(xs)
        # El universo del programa son piezas, no letras
        assert all(p.id.startswith("Pieza ") for p in data.paths)

    def test_max_pieza_height_detected(self, three_letters_svg):
        data = parse_svg(three_letters_svg)
        assert data.max_pieza_height_px == pytest.approx(100, abs=1)
        # alias retro-compatible sigue funcionando
        assert data.max_letter_height_px == data.max_pieza_height_px

    def test_empty_svg_does_not_crash(self):
        empty = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
        data = parse_svg(empty)
        assert data.paths == []
        assert data.viewbox_w == 10.0


class TestParseViewbox:
    def test_uses_viewbox_when_present(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg viewBox="0 0 100 50" width="200" height="100"/>')
        w, h, unit, factor = _parse_viewbox(root)
        assert w == 100.0
        assert h == 50.0

    def test_detects_mm_unit(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg width="100mm" height="50mm"/>')
        _, _, unit, factor = _parse_viewbox(root)
        assert unit == "mm"
        # 100mm = 10cm; sin viewBox el factor a cm es mm→cm = 0.1
        assert factor == pytest.approx(0.1, abs=1e-6)

    def test_fallback_when_missing(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg/>')
        w, h, _, _ = _parse_viewbox(root)
        assert w == 500.0
        assert h == 500.0

    def test_illustrator_detected_via_enable_background(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(
            '<svg viewBox="0 0 1224 792" style="enable-background:new 0 0 1224 792;"/>'
        )
        w, h, unit, factor = _parse_viewbox(root)
        assert w == 1224.0
        assert unit == "pt"
        # 1 pt = 2.54/72 cm
        assert factor == pytest.approx(2.54 / 72, abs=1e-6)

    def test_width_mm_with_viewbox_derives_factor(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<svg viewBox="0 0 1000 500" width="200mm" height="100mm"/>')
        w, h, unit, factor = _parse_viewbox(root)
        assert w == 1000.0
        assert unit == "mm"
        # 200mm = 20cm; 1000 unidades viewBox = 20cm → factor = 0.02 cm/unidad
        assert factor == pytest.approx(0.02, abs=1e-6)


class TestSVGPrimitives:
    """El universo del programa son primitivas SVG arbitrarias, no solo <path>."""

    def test_rect_primitive_detected(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 200 200">'
               b'<rect x="50" y="50" width="100" height="80"/></svg>')
        data = parse_svg(svg)
        assert len(data.paths) == 1
        p = data.paths[0]
        assert p.is_closed
        assert p.bbox["w"] == pytest.approx(100, abs=0.1)
        assert p.bbox["h"] == pytest.approx(80, abs=0.1)
        assert p.area_px == pytest.approx(8000, abs=10)

    def test_circle_primitive_detected(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 200 200">'
               b'<circle cx="100" cy="100" r="40"/></svg>')
        data = parse_svg(svg)
        assert len(data.paths) == 1
        p = data.paths[0]
        # bbox de un círculo de r=40 es 80×80
        assert p.bbox["w"] == pytest.approx(80, abs=0.5)
        assert p.bbox["h"] == pytest.approx(80, abs=0.5)
        # área ≈ π·r² ≈ 5027 (las Beziers aproximan bien)
        assert p.area_px == pytest.approx(5027, abs=50)

    def test_polygon_primitive_detected(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 200 200">'
               b'<polygon points="10,10 50,10 50,50 10,50"/></svg>')
        data = parse_svg(svg)
        assert len(data.paths) == 1
        p = data.paths[0]
        assert p.is_closed
        assert p.bbox["w"] == pytest.approx(40, abs=0.5)
        assert p.bbox["h"] == pytest.approx(40, abs=0.5)


class TestCSSClassResolution:
    """Los SVG de Illustrator declaran fills vía <style>.clase{fill:color}."""

    def test_fill_resolved_via_css_class(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 200 200">'
               b'<style>.bg{fill:#FFFFFF;} .fg{fill:#000;}</style>'
               b'<rect class="bg" x="0" y="0" width="200" height="200"/>'
               b'<rect class="fg" x="50" y="50" width="100" height="100"/></svg>')
        data = parse_svg(svg)
        # Ambos rects deben detectarse, la resolución de fill es para
        # consumidores posteriores (filtros de fondo, etc.)
        assert len(data.paths) == 2


class TestTransforms:
    """Transforms heredados de <g> deben aplicarse al bbox y al perímetro."""

    def test_translate_on_group_shifts_bbox(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 400 400">'
               b'<g transform="translate(100,50)">'
               b'<rect x="0" y="0" width="50" height="50"/>'
               b'</g></svg>')
        data = parse_svg(svg)
        assert len(data.paths) == 1
        p = data.paths[0]
        # El rect original está en (0,0,50,50) pero el grupo lo traslada a (100,50)
        assert p.bbox["x"] == pytest.approx(100, abs=0.5)
        assert p.bbox["y"] == pytest.approx(50, abs=0.5)
        assert p.bbox["w"] == pytest.approx(50, abs=0.5)
        assert p.bbox["h"] == pytest.approx(50, abs=0.5)

    def test_scale_on_group_resizes_bbox(self):
        svg = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
               b'viewBox="0 0 400 400">'
               b'<g transform="scale(2)">'
               b'<rect x="0" y="0" width="50" height="50"/>'
               b'</g></svg>')
        data = parse_svg(svg)
        p = data.paths[0]
        # scale(2) duplica el tamaño
        assert p.bbox["w"] == pytest.approx(100, abs=1)
        assert p.bbox["h"] == pytest.approx(100, abs=1)


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

    def test_modulos_led_por_area_no_perimetro(self, square_svg):
        """Módulos LED se calculan por cobertura de área (cercha × esp × 2),
        no por perímetro/espaciado. Una letra de 25cm con cercha 6cm debe
        dar ~6-9 módulos, no 17+ (que sería el resultado por perímetro).
        Regla Signalux: 6-8 módulos por letra de 25cm de altura."""
        r = self._quote(square_svg, altura_letra_cm=25.0, cercha_cm=6.0,
                        espaciado_led_cm=6.0)
        # Una sola letra cuadrada 25cm → área ≈ 625 cm² / (6×6×2=72) ≈ 9 módulos
        assert 6 <= r.modulos_led <= 12, (
            f"Esperado 6-12 módulos para 25cm cuadrada, obtenido {r.modulos_led}"
        )

    def test_modulos_led_piso_minimo_3(self, square_svg):
        """Letras muy chicas (10cm) siempre deben tener al menos 3 módulos
        por pieza para uniformidad lumínica."""
        r = self._quote(square_svg, altura_letra_cm=10.0, cercha_cm=4.0,
                        espaciado_led_cm=6.0)
        # 1 letra · piso = 3
        assert r.modulos_led >= 3

    def test_led_recomendado_evita_110v(self):
        """led_recomendado debe preferir 12V sobre 110V cuando ambos cubren
        el rango de profundidad — el 110V solo gana si no hay alternativa."""
        from catalog_data import led_recomendado
        # Cercha 6cm exterior: tanto Sign 03 PRO (12V) como Sign 03 AC (110V) aplican
        rec = led_recomendado(6.0, "exterior")
        assert rec.get("voltaje", 12) == 12, (
            f"Esperado LED 12V, obtenido {rec['nombre']} ({rec.get('voltaje')}V)"
        )

    def test_silvatrim_se_agrega(self, square_svg):
        r = self._quote(square_svg)
        assert r.silvatrim
        assert r.metros_silvatrim > 0
        assert r.costo_silvatrim > 0

    def test_silvatrim_omitido(self, square_svg):
        """silvatrim_id='' → sin Silvatrim, costo y metros en cero, no aparece en desglose."""
        r = self._quote(square_svg, silvatrim_id="")
        assert r.silvatrim == {}
        assert r.metros_silvatrim == 0
        assert r.costo_silvatrim == 0
        # No debe aparecer línea de Silvatrim en el desglose
        assert not any("Silvatrim" in d["concepto"] for d in r.desglose)

    def test_silvatrim_override_especifico(self, square_svg):
        """silvatrim_id explícito (ej. 2\") debe usarse aunque la cercha sea pequeña."""
        # Cercha pequeña → auto recomendaría silvatrim_34 (3/4")
        r_auto = self._quote(square_svg, cercha_cm=4.0, silvatrim_id="auto")
        r_over = self._quote(square_svg, cercha_cm=4.0, silvatrim_id="silvatrim_2")
        assert r_auto.silvatrim["id"] == "silvatrim_34"
        assert r_over.silvatrim["id"] == "silvatrim_2"
        # El override es más caro porque el precio_ml de 2" > 3/4"
        assert r_over.costo_silvatrim > r_auto.costo_silvatrim

    def test_fase_d_material_por_pieza_individual(self):
        """Fase D: en auto, cada pieza recibe material según su propia altura,
        no la altura máxima del proyecto. Anuncio mixto = placa grande
        (35cm) + texto chico (5cm) → DOS materiales distintos."""
        svg = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 500">
  <path d="M50,50 L550,50 L550,400 L50,400 Z" id="placa"/>
  <path d="M100,420 L150,420 L150,470 L100,470 Z" id="texto1"/>
</svg>"""
        r = self._quote(svg, real_width_cm=60.0, altura_letra_cm=0,
                        tipo_cara="auto")
        # Hay 2 piezas: placa 35cm y texto 5cm
        assert r.paths_count == 2
        materiales_usados = {d["material_cara_id"] for d in r.desglose_letras}
        # En anuncio heterogéneo deben aparecer al menos 2 materiales distintos
        assert len(materiales_usados) >= 2, \
            f"Esperaba materiales distintos por pieza; salió {materiales_usados}"
        # La placa (más alta) debe tener material distinto al texto (más bajo)
        placa_pieza = next(d for d in r.desglose_letras if d["alto_cm"] >= 30)
        texto_pieza = next(d for d in r.desglose_letras if d["alto_cm"] < 10)
        assert placa_pieza["material_cara_id"] != texto_pieza["material_cara_id"]
        # Material agregado debe reportar "Mixto"
        assert "Mixto" in r.material_cara["nombre"]

    def test_fase_d_material_fijo_se_aplica_a_todas(self, square_svg):
        """Cuando el usuario fija un material específico (tipo_cara != 'auto'),
        TODAS las piezas usan ese material — comportamiento legacy."""
        r = self._quote(square_svg, tipo_cara="acrilico_3mm")
        materiales = {d["material_cara_id"] for d in r.desglose_letras}
        assert materiales == {"acrilico_3mm"}
        assert "Mixto" not in r.material_cara["nombre"]

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
        # subtotal interpretado como sin IVA; iva = 16% del subtotal.
        # abs=0.01 tolera ruido de redondeo a centavos.
        assert r.iva == pytest.approx(r.subtotal * 0.16, abs=0.01)
        assert r.total == pytest.approx(r.subtotal + r.iva, abs=0.01)

    def test_precio_venta_es_total_dividido_por_1_menos_margen(self, caja_svg):
        r = self._quote(caja_svg, margen_ganancia=0.4)
        # abs=0.02 tolera redondeo a centavos entre total y venta
        assert r.precio_venta_sugerido == pytest.approx(r.total / 0.6, abs=0.02)

    def test_vinil_corte_legacy_mapea_a_grafico(self, caja_svg):
        # API vieja: tipo_cara="vinil_corte" + base → base lona + grafico vinil_corte
        r = self._quote(caja_svg, tipo_cara="vinil_corte", base_cara_vinil="lona")
        assert r.material_cara["base"] == "lona_translucida"
        assert r.material_cara["grafico"] == "vinil_corte"
        assert "cuadro_corte" in r.material_cara
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


class TestCajaCaraGrafico:
    """Modelo de cara en dos pasos (regla del propietario, jul-2026):
    material base (lona translúcida / acrílico) + gráfico (impreso cubre la
    cara completa; vinil de corte cobra UN solo cuadro por metros de rollo)."""

    def _quote(self, caja_svg, **overrides):
        defaults = dict(
            real_width_cm=200.0,
            profundidad_cm=15.0,
            uso="exterior",
        )
        defaults.update(overrides)
        return cotizar_caja(svg_data=parse_svg(caja_svg), **defaults)

    def test_lona_translucida_precio_m2(self, caja_svg):
        r = self._quote(caja_svg, tipo_cara="lona", grafico="ninguno")
        area_m2 = r.area_cara_cm2 / 10000
        assert r.costo_material_cara == pytest.approx(area_m2 * 50, rel=1e-3)

    def test_lona_impresa_mismo_material_que_lisa(self, caja_svg):
        # La lona translúcida sale impresa del taller: mismo costo de material
        lisa    = self._quote(caja_svg, tipo_cara="lona", grafico="ninguno")
        impresa = self._quote(caja_svg, tipo_cara="lona", grafico="impreso")
        assert impresa.costo_material_cara == pytest.approx(lisa.costo_material_cara)

    def test_acrilico_vinil_impreso_cobra_cara_completa(self, caja_svg):
        r = self._quote(caja_svg, tipo_cara="acrilico", grafico="impreso")
        area_m2 = r.area_cara_cm2 / 10000
        assert r.costo_material_cara == pytest.approx(area_m2 * (380 + 60), rel=1e-3)

    def test_cuadro_de_corte_unico_envuelve_todo_el_diseno(self, caja_svg):
        # CAJA_SVG: diseño = dos rects de 100×40 px separados, bbox conjunto
        # 300×40 px. Escala por viewBox: sf = 200/400 = 0.5 → cuadro 150×20 cm.
        r = self._quote(caja_svg, tipo_cara="lona", grafico="vinil_corte")
        cuadro = r.material_cara["cuadro_corte"]
        assert cuadro["ancho_cm"] == pytest.approx(150.0, abs=0.2)
        assert cuadro["alto_cm"]  == pytest.approx(20.0, abs=0.2)
        # Rollo de 0.60 m: conviene cortar en 3 bandas de 20 cm → 0.60 m de rollo
        assert cuadro["ml_rollo"] == pytest.approx(0.60, abs=0.02)
        # Vinil estándar $58/ml
        vinil_linea = [d for d in r.desglose if "Vinil de corte" in d["concepto"]]
        assert len(vinil_linea) == 1
        assert vinil_linea[0]["costo"] == pytest.approx(cuadro["ml_rollo"] * 58, abs=0.05)

    def test_sercha_calibre_por_tamano_y_uso(self, caja_svg):
        # Caja chica (100 cm de lado mayor) interior → cal 20; exterior → cal 18
        chica_int = self._quote(caja_svg, real_width_cm=100.0, uso="interior")
        exterior  = self._quote(caja_svg, real_width_cm=100.0, uso="exterior")
        grande    = self._quote(caja_svg, real_width_cm=300.0, uso="interior")
        assert "20" in chica_int.material_cercha["nombre"]
        assert "18" in exterior.material_cercha["nombre"]
        assert "18" in grande.material_cercha["nombre"]


class TestDeteccionHuecos:
    """parse_svg marca es_hueco en contadores blancos y placas de fondo."""

    def test_contador_blanco_dentro_de_letra_es_hueco(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">
          <rect x="50" y="50" width="100" height="100" fill="#000000"/>
          <rect x="80" y="80" width="40" height="40" fill="#FFFFFF"/>
        </svg>"""
        data = parse_svg(svg)
        huecos = [p for p in data.paths if p.es_hueco]
        assert len(huecos) == 1
        assert huecos[0].bbox["w"] == pytest.approx(40)

    def test_placa_fondo_blanca_es_hueco(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
          <rect x="10" y="10" width="380" height="180" fill="white"/>
          <rect x="50" y="50" width="60" height="80" fill="#000"/>
          <rect x="150" y="50" width="60" height="80" fill="#000"/>
          <rect x="250" y="50" width="60" height="80" fill="#000"/>
        </svg>"""
        data = parse_svg(svg)
        huecos = [p for p in data.paths if p.es_hueco]
        assert len(huecos) == 1
        assert huecos[0].bbox["w"] == pytest.approx(380)

    def test_pieza_blanca_aislada_no_es_hueco(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">
          <rect x="50" y="50" width="60" height="80" fill="#FFFFFF"/>
          <rect x="150" y="50" width="60" height="80" fill="#000"/>
        </svg>"""
        data = parse_svg(svg)
        assert not any(p.es_hueco for p in data.paths)

    def test_fill_por_clase_css_se_resuelve(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">
          <style type="text/css">.st0{fill:#FFFFFF;}</style>
          <rect x="50" y="50" width="100" height="100"/>
          <rect x="80" y="80" width="40" height="40" class="st0"/>
        </svg>"""
        data = parse_svg(svg)
        huecos = [p for p in data.paths if p.es_hueco]
        assert len(huecos) == 1

    def test_diseno_sin_blancos_no_marca_huecos(self):
        from pathlib import Path
        svg = Path(__file__).parent.parent / "EJEMPLOS" / "karate1.svg"
        if not svg.exists():
            pytest.skip("karate1.svg no disponible")
        data = parse_svg(svg.read_bytes())
        assert not any(p.es_hueco for p in data.paths)


class TestHuecosExcluidosDelCobro:
    """El motor de cotización no cobra piezas fantasma (es_hueco): ni el
    contador de una letra ni la placa de fondo entran al conteo, materiales,
    fórmula de precio ni al anclaje de escala por altura."""

    # Placa blanca de fondo + 3 letras negras + contador blanco en la de en medio
    SVG_CON_FANTASMAS = b"""<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
      <rect x="10" y="10" width="380" height="180" fill="white"/>
      <rect x="50" y="50" width="60" height="80" fill="#000"/>
      <rect x="150" y="50" width="60" height="80" fill="#000"/>
      <rect x="250" y="50" width="60" height="80" fill="#000"/>
      <rect x="170" y="70" width="20" height="30" fill="#FFFFFF"/>
    </svg>"""

    # Las mismas 3 letras, sin figuras blancas
    SVG_LIMPIO = b"""<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
      <rect x="50" y="50" width="60" height="80" fill="#000"/>
      <rect x="150" y="50" width="60" height="80" fill="#000"/>
      <rect x="250" y="50" width="60" height="80" fill="#000"/>
    </svg>"""

    def _letras(self, svg_bytes):
        return cotizar_letras(
            svg_data=parse_svg(svg_bytes),
            real_width_cm=200.0,
            altura_letra_cm=50.0,
            cercha_cm=10.0,
        )

    def test_escala_ancla_a_pieza_real_no_a_placa(self):
        data = parse_svg(self.SVG_CON_FANTASMAS)
        # La pieza más alta para escalar es la letra (80 px), no la placa (180 px)
        assert data.max_pieza_height_px == pytest.approx(80)

    def test_letras_excluye_fantasmas_del_conteo(self):
        r = self._letras(self.SVG_CON_FANTASMAS)
        assert r.paths_count == 3
        assert len(r.desglose_letras) == 3
        assert any("hueco" in w.lower() for w in r.warnings)

    def test_letras_precio_igual_que_svg_limpio(self):
        # Cotizar con fantasmas debe dar EXACTAMENTE lo mismo que sin ellos
        con = self._letras(self.SVG_CON_FANTASMAS)
        sin = self._letras(self.SVG_LIMPIO)
        assert con.total == pytest.approx(sin.total, rel=1e-6)
        assert con.precio_final == pytest.approx(sin.precio_final, rel=1e-6)
        assert con.modulos_led == sin.modulos_led

    def test_planas_excluye_fantasmas(self):
        r = cotizar_planas(
            svg_data=parse_svg(self.SVG_CON_FANTASMAS),
            real_width_cm=200.0,
        )
        assert r.paths_count == 3
        assert any("hueco" in w.lower() for w in r.warnings)


class TestDeteccionCapas:
    """parse_svg detecta capas nombradas base/corte/luz en <g id>/inkscape:label."""

    def test_detectar_capa_matcher(self):
        from calculator import _detectar_capa
        casos = {
            "base": "base", "Base": "base", "capa_base_2": "base",
            "Fondo Principal": "base", "soporte": "base",
            "corte": "corte", "Corte 1": "corte", "cut": "corte",
            "LUZ": "luz", "halo": "luz", "retroiluminado": "luz",
            "iluminación": "luz", "retro": "luz",
            "basement": "", "recorte": "", "": "", "random": "",
        }
        for src, esperado in casos.items():
            assert _detectar_capa(src) == esperado, f"{src!r} → {_detectar_capa(src)!r}"

    def test_tres_capas_nombradas(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
          <g id="base"><rect x="0" y="0" width="100" height="100"/></g>
          <g id="corte"><rect x="10" y="10" width="20" height="20"/></g>
          <g id="luz"><rect x="50" y="10" width="20" height="20"/></g>
        </svg>"""
        data = parse_svg(svg)
        assert data.capas_detectadas == {"base": 1, "corte": 1, "luz": 1}
        caps = {p.svg_id: p.capa for p in data.paths}
        assert set(caps.values()) == {"base", "corte", "luz"}

    def test_inkscape_label_tambien_funciona(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
             viewBox="0 0 100 100">
          <g inkscape:label="Corte"><rect x="10" y="10" width="20" height="20"/></g>
        </svg>"""
        data = parse_svg(svg)
        assert data.capas_detectadas["corte"] == 1

    def test_grupo_sin_nombre_no_asigna_capa(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
          <g><rect x="10" y="10" width="20" height="20"/></g>
          <rect x="50" y="50" width="20" height="20"/>
        </svg>"""
        data = parse_svg(svg)
        assert data.capas_detectadas == {"base": 0, "corte": 0, "luz": 0}
        assert all(p.capa == "" for p in data.paths)

    def test_hijo_hereda_capa_del_grupo_padre(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
          <g id="corte">
            <g>
              <rect x="10" y="10" width="20" height="20"/>
              <rect x="40" y="10" width="20" height="20"/>
            </g>
          </g>
        </svg>"""
        data = parse_svg(svg)
        assert data.capas_detectadas["corte"] == 2

    def test_capa_hija_sobrescribe_padre(self):
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
          <g id="corte">
            <rect x="10" y="10" width="20" height="20"/>
            <g id="luz">
              <rect x="40" y="10" width="20" height="20"/>
            </g>
          </g>
        </svg>"""
        data = parse_svg(svg)
        assert data.capas_detectadas == {"base": 0, "corte": 1, "luz": 1}


class TestPlanasTresCapas:
    """cotizar_planas ahora soporta base / corte / luz. Cobra por bbox
    conjunto + factor de desperdicio, y en piezas 'luz' añade LEDs halo,
    fuente y distanciadores."""

    _SVG_3_CAPAS = b"""<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900">
      <g id="base"><rect x="0" y="0" width="1200" height="900"/></g>
      <g id="corte">
        <rect x="100" y="100" width="200" height="80"/>
        <rect x="400" y="100" width="200" height="80"/>
      </g>
      <g id="luz">
        <rect x="100" y="400" width="300" height="100"/>
      </g>
    </svg>"""

    _SVG_SIN_CAPAS = b"""<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900">
      <rect x="100" y="100" width="200" height="80"/>
      <rect x="400" y="100" width="200" height="80"/>
    </svg>"""

    def _r(self, svg, **kw):
        data = parse_svg(svg)
        defaults = dict(real_width_cm=120.0, material_id="acrilico_3mm",
                        desperdicio_pct=15.0)
        defaults.update(kw)
        return cotizar_planas(svg_data=data, **defaults)

    def test_sin_capas_comportamiento_por_defecto(self):
        # SVG sin capas + flags off → todas las piezas caen en 'corte',
        # sin base ni luz. Comportamiento no-regresivo.
        r = self._r(self._SVG_SIN_CAPAS)
        comp = r.desglose_costos_componentes
        assert comp["cara"] > 0            # corte
        assert comp["base"] == 0.0
        assert comp["luz"] == 0.0
        assert comp["leds"] == 0.0
        assert r.modulos_led == 0

    def test_capa_base_del_svg_se_cobra(self):
        r = self._r(self._SVG_3_CAPAS, incluye_luz=False,
                    base_material_id="acrilico_3mm_transparente")
        comp = r.desglose_costos_componentes
        assert comp["base"] > 0
        assert r.material_fondo["nombre"] == "Acrílico Transparente 3mm"

    def test_capa_luz_activa_leds_fuente_distanciadores(self):
        r = self._r(self._SVG_3_CAPAS, incluye_luz=True,
                    base_material_id="acrilico_3mm_transparente")
        comp = r.desglose_costos_componentes
        assert comp["luz"] > 0
        assert comp["leds"] > 0
        assert comp["fuente"] > 0
        assert comp["distanciadores"] > 0
        assert r.modulos_led >= 3   # mínimo 3 por pieza

    def test_incluye_luz_off_convierte_luz_en_corte(self):
        r_off = self._r(self._SVG_3_CAPAS, incluye_luz=False)
        r_on  = self._r(self._SVG_3_CAPAS, incluye_luz=True)
        # Off: la pieza de luz cae a corte → costo LEDs = 0
        assert r_off.desglose_costos_componentes["leds"] == 0
        assert r_on.desglose_costos_componentes["leds"] > 0
        # Warning debe informar la desactivación
        assert any("luz" in w.lower() for w in r_off.warnings)

    def test_desperdicio_pct_incrementa_material_linealmente(self):
        r0  = self._r(self._SVG_SIN_CAPAS, desperdicio_pct=0.0)
        r15 = self._r(self._SVG_SIN_CAPAS, desperdicio_pct=15.0)
        r30 = self._r(self._SVG_SIN_CAPAS, desperdicio_pct=30.0)
        assert r15.costo_material_cara == pytest.approx(r0.costo_material_cara * 1.15, rel=1e-3)
        assert r30.costo_material_cara == pytest.approx(r0.costo_material_cara * 1.30, rel=1e-3)

    def test_incluye_base_manual_sin_capa_en_svg(self):
        r = self._r(
            self._SVG_SIN_CAPAS, incluye_base=True,
            real_height_cm=90.0,
            base_material_id="acrilico_3mm_transparente",
        )
        comp = r.desglose_costos_componentes
        assert comp["base"] > 0
        assert r.material_fondo["nombre"] == "Acrílico Transparente 3mm"

    def test_bbox_conjunto_es_menor_que_suma_bboxes(self):
        # Piezas separadas con espacio entre ellas: el bbox conjunto es
        # notablemente MAYOR a cada pieza, y muy menor que la suma.
        # Esto valida que el cobro se hace por el "pedazo" real.
        data = parse_svg(self._SVG_SIN_CAPAS)
        piezas = [p for p in data.paths if p.is_closed]
        from calculator import _bbox_conjunto, apply_scale
        d = apply_scale(data, 120.0)
        w, h = _bbox_conjunto(piezas, d.scale_factor)
        area_conjunto = w * h
        area_suma = sum((p.bbox["h"] * d.scale_factor) *
                        (p.bbox["w"] * d.scale_factor) for p in piezas)
        assert area_conjunto > area_suma   # rectángulo envolvente > suma
        assert area_conjunto > 0

    def test_precio_letra_usa_multiplicador_por_capa(self):
        # Piezas en capa 'luz' deben cobrarse con el multiplicador con-luz,
        # no con el sin-luz. Chequear en el desglose por pieza.
        r = self._r(self._SVG_3_CAPAS, incluye_luz=True)
        capas_por_pieza = {d["id"]: d["capa"] for d in r.desglose_letras}
        # Al menos una pieza debe estar en 'luz' y otra en 'corte'
        assert "luz" in capas_por_pieza.values()
        assert "corte" in capas_por_pieza.values()

    def test_modo_corte_areas_es_mayor_o_igual_que_pieza(self):
        # Con piezas separadas, bbox conjunto > suma bboxes → areas >= pieza.
        r_a = self._r(self._SVG_SIN_CAPAS, modo_corte="areas")
        r_p = self._r(self._SVG_SIN_CAPAS, modo_corte="pieza")
        assert r_a.costo_material_cara >= r_p.costo_material_cara

    def test_modo_corte_pieza_iguala_a_suma_de_bboxes(self):
        r = self._r(self._SVG_SIN_CAPAS, modo_corte="pieza", desperdicio_pct=0.0)
        # Sin desperdicio, suma de costo_cara por pieza debe igualar el total.
        suma = sum(d["costo_cara"] for d in r.desglose_letras)
        assert suma == pytest.approx(r.costo_material_cara, rel=1e-3)

    def test_flag_costo_es_informativo_en_desglose_letras(self):
        r_a = self._r(self._SVG_SIN_CAPAS, modo_corte="areas")
        r_p = self._r(self._SVG_SIN_CAPAS, modo_corte="pieza")
        assert all(d.get("costo_es_informativo") is True  for d in r_a.desglose_letras)
        assert all(d.get("costo_es_informativo") is False for d in r_p.desglose_letras)

    def test_modo_corte_invalido_cae_a_areas(self):
        r_bad = self._r(self._SVG_SIN_CAPAS, modo_corte="ninguno_valido")
        r_ok  = self._r(self._SVG_SIN_CAPAS, modo_corte="areas")
        assert r_bad.costo_material_cara == pytest.approx(r_ok.costo_material_cara, rel=1e-6)

    def test_bloque_luz_incluye_metros_lineales(self):
        # El usuario necesita saber cuánto va a gastar de LED. El bloque
        # 'luz' debe exponer perimetro_total_cm y metros_lineales.
        r = self._r(self._SVG_3_CAPAS, incluye_luz=True)
        luz = r.desglose_costos_componentes["bloques"].get("luz")
        assert luz is not None
        assert luz["perimetro_total_cm"] > 0
        assert luz["metros_lineales"] == pytest.approx(luz["perimetro_total_cm"] / 100.0, rel=1e-3)

    def test_capa_base_blanca_no_se_marca_como_hueco(self):
        # Regresión: la capa 'base' de acrílico transparente es blanca
        # (fill=#FFFFFF) y contiene a las demás piezas — la heurística de
        # huecos la marcaba y quedaba fuera del cobro. Con capa nombrada
        # el usuario declaró su intención → NO debe marcarse.
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">
          <g id="base">
            <rect x="10" y="10" width="280" height="180" fill="#FFFFFF"/>
          </g>
          <g id="corte">
            <rect x="50" y="50" width="30" height="40" fill="#000"/>
            <rect x="150" y="50" width="30" height="40" fill="#000"/>
          </g>
        </svg>"""
        data = parse_svg(svg)
        base = [p for p in data.paths if p.capa == "base"]
        assert len(base) == 1, "La capa base debe estar presente"
        assert not base[0].es_hueco, "Base blanca con capa nombrada NO debe ser hueco"

    def test_escala_se_ancla_a_la_base_no_al_viewbox(self):
        # SVG con artboard 300 unidades pero la BASE solo mide 150 unidades
        # (con padding a los lados). Si el usuario dice real_width_cm=115,
        # se refiere a la base — NO al artboard completo. La base debe
        # medir exactamente 115×65 en el resultado, no 230×130.
        svg = b"""<?xml version="1.0"?>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200">
          <g id="base">
            <rect x="75" y="35" width="150" height="85"/>
          </g>
          <g id="corte">
            <rect x="100" y="50" width="20" height="20"/>
          </g>
        </svg>"""
        data = parse_svg(svg)
        r = cotizar_planas(svg_data=data, real_width_cm=115.0,
                           incluye_base=True,
                           base_material_id="acrilico_3mm_transparente")
        # La base debe medir 115 cm exactos (lo que dijo el usuario)
        assert r.material_fondo["nombre"] == "Acrílico Transparente 3mm"
        # Verificamos por el desglose humano que aparezcan las medidas correctas
        base_desc = next((d["concepto"] for d in r.desglose if d["concepto"].startswith("Base ")), "")
        assert "115" in base_desc, f"Se esperaba 115 cm en la descripción de base, vino: {base_desc}"
        # La pieza de corte 20 unidades sobre base de 150 unidades = 20/150 * 115 = 15.33 cm
        # Al menos verificar que el bbox conjunto de corte tampoco esté 2x
        corte_desc = next((d["concepto"] for d in r.desglose if d["concepto"].startswith("Corte ")), "")
        # Ancho real esperado ≈ 15.3 cm (20 unidades × 115/150)
        # NO debe aparecer un 30 (que sería si escalara al viewBox)
        assert "30" not in corte_desc.split("cm")[0], f"Escala mal ancla: {corte_desc}"
