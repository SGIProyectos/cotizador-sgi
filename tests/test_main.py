"""
Smoke tests del flujo principal de endpoints en main.py.

Cubre: health, parse-svg, cotizar/*, catalog GET/POST con validación.
NO ejercita PDFs (requieren ReportLab + fuentes; ya hay smoke en cliente).
"""
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


# ─── HEALTH ──────────────────────────────────────────────────────────────────

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "caches" in body
    assert body["started_at"] is not None


# ─── PARSE SVG ───────────────────────────────────────────────────────────────

def test_parse_svg_rechaza_vacio(client):
    r = client.post("/api/parse-svg", files={"file": ("empty.svg", b"", "image/svg+xml")})
    assert r.status_code == 400

def test_parse_svg_rechaza_archivo_gigante(client):
    # Genera SVG por encima del límite (11 MB)
    big = b"<svg/>" + b" " * (11 * 1024 * 1024)
    r = client.post("/api/parse-svg",
                    files={"file": ("big.svg", big, "image/svg+xml")})
    assert r.status_code == 413

def test_parse_svg_devuelve_session_id(client, square_svg):
    r = client.post("/api/parse-svg",
                    files={"file": ("sq.svg", square_svg, "image/svg+xml")})
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert len(body["paths"]) == 1


# ─── COTIZAR ─────────────────────────────────────────────────────────────────

def _new_session(client, svg_bytes) -> str:
    r = client.post("/api/parse-svg",
                    files={"file": ("s.svg", svg_bytes, "image/svg+xml")})
    return r.json()["session_id"]


def test_cotizar_letras_flujo_completo(client, square_svg):
    sid = _new_session(client, square_svg)
    r = client.post("/api/cotizar/letras", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "altura_letra_cm": 50.0,
        "uso": "exterior",
        "tipo_cara": "auto",
        "tipo_cercha": "auto",
        "cercha_cm": 0.0,
        "margen_ganancia": 0.35,
        "tipo_construccion": "cajon_luz",
        "tipo_multiplicador": "acrilico_con_luz_std",
        "ajuste_pct": 0.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tipo"] == "letras_3d"
    assert body["costos"]["subtotal"] > 0
    assert body["costos"]["precio_venta_sugerido"] > 0
    assert "quote_id" in body


def test_excel_export(client, square_svg):
    sid = _new_session(client, square_svg)
    qid = client.post("/api/cotizar/letras", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "altura_letra_cm": 50.0,
    }).json()["quote_id"]
    r = client.get(f"/api/excel/{qid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    # Header XLSX = ZIP "PK\x03\x04"
    assert r.content[:4] == b"PK\x03\x04"
    assert "Cotizacion_" in r.headers.get("content-disposition", "")


def test_excel_export_quote_inexistente(client):
    r = client.get("/api/excel/no-existe")
    assert r.status_code == 404


# ─── PLANO TÉCNICO DE MEDIDAS ───────────────────────────────────────────────

def test_plano_cliente(client, square_svg):
    sid = _new_session(client, square_svg)
    qid = client.post("/api/cotizar/letras", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "altura_letra_cm": 50.0,
    }).json()["quote_id"]
    r = client.get(f"/api/plano/{qid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1024
    assert "Plano_" in r.headers.get("content-disposition", "")


def test_plano_taller(client, square_svg):
    sid = _new_session(client, square_svg)
    qid = client.post("/api/cotizar/letras", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "altura_letra_cm": 50.0,
    }).json()["quote_id"]
    r = client.get(f"/api/plano-taller/{qid}", params={"notas": "Test workshop"})
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1024
    assert "PlanoTaller_" in r.headers.get("content-disposition", "")


def test_plano_quote_inexistente(client):
    r = client.get("/api/plano/no-existe")
    assert r.status_code == 404
    r = client.get("/api/plano-taller/no-existe")
    assert r.status_code == 404


def test_cotizar_caja_flujo(client, caja_svg):
    sid = _new_session(client, caja_svg)
    r = client.post("/api/cotizar/caja", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "profundidad_cm": 15.0,
        "tipo_cara": "lona",
        "led_id": "auto",
        "uso": "exterior",
        "vistas": 1,
        "margen_ganancia": 0.35,
    })
    assert r.status_code == 200
    assert r.json()["tipo"] == "caja_luz"


def _quote_caja(client, caja_svg, **extra):
    sid = _new_session(client, caja_svg)
    body = {
        "session_id": sid, "real_width_cm": 250.0, "profundidad_cm": 18.0,
        "tipo_cara": "lona", "grafico": "vinil_corte", "vinil_id": "vinil_std",
        "uso": "exterior",
    }
    body.update(extra)
    r = client.post("/api/cotizar/caja", json=body)
    assert r.status_code == 200
    return r.json()["quote_id"]


def test_universo_caja_planos_y_acta(client, caja_svg):
    """El universo completo de la caja genera PDFs válidos: plano cliente,
    plano taller (2 páginas) y acta de entrega — sin enumerar letras."""
    qid = _quote_caja(client, caja_svg)
    for url in (f"/api/plano/{qid}", f"/api/plano-taller/{qid}",
                f"/api/entrega/{qid}", f"/api/ot/{qid}", f"/api/excel/{qid}"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert len(r.content) > 1024, url


def test_acta_enlaza_cliente_del_catalogo(client, caja_svg):
    """El acta jala RFC/teléfono/dirección del catálogo por nombre, y acepta
    fecha de entrega real, lugar y anticipo."""
    r = client.post("/api/clients", json={
        "nombre": "Cliente Enlace SA", "rfc": "CEN010101XX1",
        "telefono": "614 555 0000", "direccion": "Calle Uno 123",
    })
    assert r.status_code == 200
    qid = _quote_caja(client, caja_svg, cliente="Cliente Enlace SA")
    r = client.get(f"/api/entrega/{qid}", params={
        "fecha_entrega": "15/08/2026", "lugar": "Taller SGI", "anticipo": 1000.0,
    })
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"
    import db
    cli = db.get_client_by_name("cliente enlace sa")   # sin distinguir mayúsculas
    assert cli and cli["rfc"] == "CEN010101XX1" and cli["direccion"] == "Calle Uno 123"


def test_acta_garantia_tres_meses(client, caja_svg):
    qid = _quote_caja(client, caja_svg)
    r = client.get(f"/api/entrega/{qid}")
    assert r.status_code == 200
    # el PDF comprime el texto; validamos la regla de negocio en el generador
    from pdf_gen import _vence_garantia
    assert _vence_garantia("08/07/2026") == "08/10/2026"
    assert _vence_garantia("30/11/2026") == "28/02/2027"   # feb corto
    assert _vence_garantia("31/03/2026") == "30/06/2026"   # jun de 30 días


def test_cotizar_session_invalida(client):
    r = client.post("/api/cotizar/letras", json={
        "session_id": "no_existe",
        "real_width_cm": 100.0,
        "altura_letra_cm": 30.0,
    })
    assert r.status_code == 404


# ─── CATALOGO ────────────────────────────────────────────────────────────────

def test_catalog_get(client):
    r = client.get("/api/catalog")
    assert r.status_code == 200
    body = r.json()
    assert "laminas" in body
    assert "precios_base" in body


def test_catalog_post_rechaza_extra_keys(client):
    r = client.post("/api/catalog", json={"foobar": "x"})
    assert r.status_code == 422


def test_catalog_post_rechaza_tipo_erroneo(client):
    r = client.post("/api/catalog", json={"laminas": "no_es_dict"})
    assert r.status_code == 422


def test_catalog_post_rechaza_vacio(client):
    r = client.post("/api/catalog", json={})
    assert r.status_code == 400


def test_catalog_post_acepta_parcial(client):
    # Lee el valor actual y lo re-envía idéntico (no hay efecto persistente)
    actual = client.get("/api/catalog").json()
    r = client.post("/api/catalog", json={
        "precios_base": actual["precios_base"]
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ─── FILENAME SANITIZATION ───────────────────────────────────────────────────

def test_safe_part_remueve_path_traversal():
    assert "/" not in main._safe_part("../../etc/passwd")
    assert "\\" not in main._safe_part("..\\..\\windows")

def test_safe_part_remueve_newlines():
    # Response splitting: \r\n permitiría inyectar headers
    out = main._safe_part("cliente\r\nX-Evil: 1")
    assert "\r" not in out
    assert "\n" not in out

def test_safe_part_aplica_default_si_vacio():
    assert main._safe_part("") == "SGI"
    assert main._safe_part("   ") == "SGI"
    assert main._safe_part(None) == "SGI"

def test_safe_part_limita_longitud():
    out = main._safe_part("a" * 500)
    assert len(out) <= 60
