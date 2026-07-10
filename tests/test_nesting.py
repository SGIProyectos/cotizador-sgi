"""
Tests del módulo de corte (nesting.py) y sus endpoints.

Reglas que se validan:
  - extracción de piezas con huecos (profundidad de contención)
  - separación mínima REAL entre contornos colocados >= gap pedido
  - piezas chicas caen dentro de huecos de piezas grandes
  - multi-lámina cuando no cabe, y reporte de piezas imposibles
  - DXF válido (se relee con ezdxf) en mm con capa CORTE
"""
import io

import ezdxf
import pytest
from fastapi.testclient import TestClient

import main
import nesting

# 3 cuadrados de 100x100 unidades, bbox conjunto 500 de ancho
TRES_CUADROS = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200">
  <path d="M10,50 L110,50 L110,150 L10,150 Z"/>
  <path d="M210,50 L310,50 L310,150 L210,150 Z"/>
  <path d="M410,50 L510,50 L510,150 L410,150 Z"/>
</svg>"""

# Dona: marco cuadrado 200x200 con hueco 120x120 (subpaths del MISMO path),
# y un cuadrito de 100x100 aparte que cabe dentro del hueco.
DONA_Y_CUADRITO = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
  <path d="M0,0 L200,0 L200,200 L0,200 Z M40,40 L160,40 L160,160 L40,160 Z"/>
  <path d="M250,50 L350,50 L350,150 L250,150 Z"/>
</svg>"""


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


# ─── EXTRACCIÓN DE PIEZAS ────────────────────────────────────────────────────

def test_piezas_desde_svg_escala_por_bbox():
    piezas = nesting.piezas_desde_svg(TRES_CUADROS, ancho_real_cm=100.0,
                                      fuente="t.svg")
    assert len(piezas) == 3
    # bbox conjunto = 500 unidades -> 100 cm; cada cuadro de 100 u -> 20 cm
    for p in piezas:
        w = p.poly.bounds[2] - p.poly.bounds[0]
        assert w == pytest.approx(20.0, abs=0.3)
        assert p.poly.area == pytest.approx(400.0, rel=0.05)


def test_piezas_copias():
    piezas = nesting.piezas_desde_svg(TRES_CUADROS, 100.0, "t.svg", copias=3)
    assert len(piezas) == 9
    assert "(2)" in piezas[3].etiqueta   # las copias van etiquetadas


def test_pieza_con_hueco():
    piezas = nesting.piezas_desde_svg(DONA_Y_CUADRITO, 175.0, "d.svg")
    assert len(piezas) == 2
    dona = max(piezas, key=lambda p: p.poly.bounds[2] - p.poly.bounds[0])
    assert len(dona.poly.interiors) == 1     # el hueco quedó como interior
    # área de la dona = marco - hueco (200²-120² u² escalado)
    assert dona.poly.area < (dona.poly.bounds[2] - dona.poly.bounds[0]) ** 2 * 0.7


def test_svg_sin_piezas():
    assert nesting.piezas_desde_svg(b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                    100.0, "v.svg") == []


def test_fondo_de_artboard_se_descarta():
    """Un rect del tamaño del lienzo que CONTIENE piezas es fondo (Illustrator),
    no una pieza a cortar. Un rectángulo solo sí se conserva."""
    con_fondo = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
      <path d="M0,0 L400,0 L400,200 L0,200 Z"/>
      <path d="M50,50 L150,50 L150,150 L50,150 Z"/>
    </svg>"""
    piezas = nesting.piezas_desde_svg(con_fondo, 100.0, "f.svg")
    assert len(piezas) == 1          # solo el cuadro interior
    solo_rect = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
      <path d="M0,0 L400,0 L400,200 L0,200 Z"/>
    </svg>"""
    assert len(nesting.piezas_desde_svg(solo_rect, 100.0, "r.svg")) == 1


# ─── NESTING ─────────────────────────────────────────────────────────────────

def _cuadros(n: int, lado_cm: float) -> list[nesting.PiezaNest]:
    from shapely.geometry import Polygon
    poly = Polygon([(0, 0), (lado_cm, 0), (lado_cm, lado_cm), (0, lado_cm)])
    return [nesting.PiezaNest(poly=poly, etiqueta=f"c{i}", fuente="test")
            for i in range(n)]


def test_nest_cuadros_en_una_lamina():
    laminas, sin_lugar = nesting.nest(_cuadros(8, 50.0), 244.0, 122.0)
    assert sin_lugar == []
    assert len(laminas) == 1
    assert len(laminas[0].colocaciones) == 8


def test_nest_respeta_gap():
    gap = 0.5
    laminas, _ = nesting.nest(_cuadros(8, 50.0), 244.0, 122.0, gap_cm=gap)
    cols = laminas[0].colocaciones
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            d = cols[i].poly.distance(cols[j].poly)
            assert d >= gap - 0.05, f"piezas {i} y {j} a {d:.2f} cm (< {gap})"


def test_nest_respeta_margen():
    margen = 1.0
    laminas, _ = nesting.nest(_cuadros(4, 50.0), 244.0, 122.0, margen_cm=margen)
    for c in laminas[0].colocaciones:
        x0, y0, x1, y1 = c.poly.bounds
        assert x0 >= margen - 0.3 and y0 >= margen - 0.3
        assert x1 <= 244.0 - margen + 0.3 and y1 <= 122.0 - margen + 0.3


def test_nest_multilaminas():
    # cuadros de 100: en lámina de 122x122 solo cabe 1 por lámina
    laminas, sin_lugar = nesting.nest(_cuadros(3, 100.0), 122.0, 122.0)
    assert sin_lugar == []
    assert len(laminas) == 3


def test_nest_pieza_imposible_se_reporta():
    laminas, sin_lugar = nesting.nest(_cuadros(1, 150.0), 122.0, 122.0)
    assert len(sin_lugar) == 1
    assert laminas == []


def test_nest_hueco_aprovechado():
    """El cuadrito debe caer DENTRO del hueco de la dona."""
    piezas = nesting.piezas_desde_svg(DONA_Y_CUADRITO, 175.0, "d.svg")
    laminas, sin_lugar = nesting.nest(piezas, 122.0, 122.0, gap_cm=0.5)
    assert sin_lugar == [] and len(laminas) == 1
    dona = max(laminas[0].colocaciones, key=lambda c: c.poly.area)
    chico = min(laminas[0].colocaciones, key=lambda c: c.poly.area)
    from shapely.geometry import Polygon
    hueco = Polygon(dona.poly.interiors[0])
    assert hueco.contains(chico.poly), "el cuadrito no quedó dentro del hueco"


def test_nest_franja_en_rollo():
    laminas, _ = nesting.nest(_cuadros(2, 30.0), 60.0, 500.0, gap_cm=0.5)
    assert len(laminas) == 1
    # 2 cuadros de 30 en rollo de 60 de ancho -> franja de ~62 cm, no 500
    assert laminas[0].franja_cm < 75


def test_nest_tope_de_piezas():
    with pytest.raises(ValueError):
        nesting.nest(_cuadros(nesting.MAX_PIEZAS + 1, 5.0), 122.0, 244.0)


# ─── SALIDAS ─────────────────────────────────────────────────────────────────

def test_dxf_valido_en_mm():
    laminas, _ = nesting.nest(_cuadros(2, 50.0), 122.0, 244.0)
    dxf_bytes = nesting.lamina_dxf(laminas[0])
    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("utf-8")))
    assert doc.header["$INSUNITS"] == 4          # mm
    polys = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"]
    en_corte = [e for e in polys if e.dxf.layer == "CORTE"]
    assert len(en_corte) == 2                    # un contorno por cuadro
    # coordenadas en mm: un cuadro de 50 cm mide 500 mm
    xs = [p[0] for p in en_corte[0].get_points()]
    assert max(xs) - min(xs) == pytest.approx(500.0, abs=15.0)


def test_lamina_svg_preview():
    laminas, _ = nesting.nest(_cuadros(2, 50.0), 122.0, 244.0)
    svg = nesting.lamina_svg(laminas[0])
    assert svg.startswith("<svg") and "path" in svg


def test_plano_corte_pdf():
    from plano_gen import generar_plano_corte
    laminas, sin_lugar = nesting.nest(_cuadros(3, 50.0), 122.0, 244.0)
    pdf = generar_plano_corte(laminas, sin_lugar,
                              {"ancho_cm": 122, "alto_cm": 244,
                               "gap_cm": 0.5, "margen_cm": 1.0})
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1500


# ─── ENDPOINTS ───────────────────────────────────────────────────────────────

def _post_nest(client, config: dict | None = None):
    import json as _json
    cfg = {"archivos": [{"ancho_cm": 100.0, "copias": 1}],
           "lamina": {"ancho_cm": 122, "alto_cm": 244}}
    if config:
        cfg.update(config)
    return client.post("/api/nest",
                       files=[("files", ("tres.svg", TRES_CUADROS, "image/svg+xml"))],
                       data={"config": _json.dumps(cfg)})


def test_api_nest_flujo_completo(client):
    r = _post_nest(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_piezas"] == 3
    assert len(body["laminas"]) == 1
    assert body["laminas"][0]["svg"].startswith("<svg")
    nid = body["nest_id"]

    r = client.get(f"/api/nest/{nid}/pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    r = client.get(f"/api/nest/{nid}/svg/1")
    assert r.status_code == 200 and b"<svg" in r.content
    r = client.get(f"/api/nest/{nid}/dxf/1")
    assert r.status_code == 200 and b"LWPOLYLINE" in r.content
    assert client.get(f"/api/nest/{nid}/dxf/9").status_code == 404


def test_api_nest_valida_config(client):
    assert _post_nest(client, {"gap_cm": 99}).status_code == 400
    assert _post_nest(client, {"lamina": {"ancho_cm": 1, "alto_cm": 244}}).status_code == 400
    assert _post_nest(client, {"archivos": [{"ancho_cm": 0}]}).status_code == 400
    assert _post_nest(client, {"paso_angulo": 7}).status_code == 400


def test_api_nest_expirado_404(client):
    assert client.get("/api/nest/no-existe/pdf").status_code == 404
