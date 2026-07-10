"""
Tests del pipeline de estados, registro de pagos y dashboard.

Ciclo de vida: borrador → enviada → autorizada → fabricacion → entregada
→ cobrada (o perdida). Los documentos auto-avanzan el estado pero nunca
lo regresan; los pagos acumulan y liquidar marca 'cobrada'.
"""
import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _quote(client, square_svg) -> str:
    r = client.post("/api/parse-svg",
                    files={"file": ("s.svg", square_svg, "image/svg+xml")})
    sid = r.json()["session_id"]
    r = client.post("/api/cotizar/letras", json={
        "session_id": sid,
        "real_width_cm": 200.0,
        "altura_letra_cm": 50.0,
    })
    assert r.status_code == 200
    return r.json()["quote_id"]


# ─── ESTADOS ─────────────────────────────────────────────────────────────────

def test_cotizacion_nueva_nace_en_borrador(client, square_svg):
    qid = _quote(client, square_svg)
    row = db.get_quote(qid)
    assert (row["estado"] or "borrador") == "borrador"
    assert (row["pagado"] or 0) == 0


def test_set_estado_endpoint(client, square_svg):
    qid = _quote(client, square_svg)
    r = client.post(f"/api/quotes/{qid}/estado", json={"estado": "autorizada"})
    assert r.status_code == 200
    assert db.get_quote(qid)["estado"] == "autorizada"


def test_set_estado_invalido_400(client, square_svg):
    qid = _quote(client, square_svg)
    r = client.post(f"/api/quotes/{qid}/estado", json={"estado": "volando"})
    assert r.status_code == 400


def test_set_estado_quote_inexistente_404(client):
    r = client.post("/api/quotes/no-existe/estado", json={"estado": "enviada"})
    assert r.status_code == 404


def test_avanzar_estado_nunca_regresa(client, square_svg):
    qid = _quote(client, square_svg)
    db.set_estado(qid, "entregada")
    db.avanzar_estado(qid, "enviada")          # intento de regresión
    assert db.get_quote(qid)["estado"] == "entregada"


def test_avanzar_estado_no_toca_perdida(client, square_svg):
    qid = _quote(client, square_svg)
    db.set_estado(qid, "perdida")
    db.avanzar_estado(qid, "fabricacion")
    assert db.get_quote(qid)["estado"] == "perdida"


def test_documentos_auto_avanzan(client, square_svg):
    """Cotización PDF → enviada; OT → fabricacion; acta → entregada."""
    qid = _quote(client, square_svg)
    client.get(f"/api/pdf/{qid}")
    assert db.get_quote(qid)["estado"] == "enviada"
    client.get(f"/api/ot/{qid}")
    assert db.get_quote(qid)["estado"] == "fabricacion"
    client.get(f"/api/entrega/{qid}")
    assert db.get_quote(qid)["estado"] == "entregada"
    # Regenerar la cotización PDF NO regresa el estado
    client.get(f"/api/pdf/{qid}")
    assert db.get_quote(qid)["estado"] == "entregada"


def test_filtro_por_estado_en_historial(client, square_svg):
    qid = _quote(client, square_svg)
    db.set_estado(qid, "fabricacion")
    rows = client.get("/api/quotes", params={"estado": "fabricacion"}).json()
    assert any(r["id"] == qid for r in rows)
    assert all(r["estado"] == "fabricacion" for r in rows)


# ─── PAGOS ───────────────────────────────────────────────────────────────────

def test_pago_acumula_y_autoriza(client, square_svg):
    qid = _quote(client, square_svg)
    precio = db.get_quote(qid)["precio_final"]
    r = client.post(f"/api/quotes/{qid}/pago", json={"monto": 100.0})
    assert r.status_code == 200
    body = r.json()
    assert body["pagado"] == 100.0
    assert body["saldo"] == pytest.approx(precio - 100.0, abs=0.01)
    assert body["estado"] == "autorizada"    # pagar implica autorizar
    r = client.post(f"/api/quotes/{qid}/pago", json={"monto": 50.0})
    assert r.json()["pagado"] == 150.0


def test_pago_liquidado_marca_cobrada(client, square_svg):
    qid = _quote(client, square_svg)
    precio = db.get_quote(qid)["precio_final"]
    r = client.post(f"/api/quotes/{qid}/pago", json={"monto": precio})
    assert r.json()["saldo"] <= 0
    assert r.json()["estado"] == "cobrada"


def test_pago_monto_invalido_400(client, square_svg):
    qid = _quote(client, square_svg)
    r = client.post(f"/api/quotes/{qid}/pago", json={"monto": 0})
    assert r.status_code == 400
    r = client.post(f"/api/quotes/{qid}/pago", json={"monto": -5})
    assert r.status_code == 400


def test_pago_quote_inexistente_404(client):
    r = client.post("/api/quotes/no-existe/pago", json={"monto": 100.0})
    assert r.status_code == 404


def test_anticipo_del_acta_es_idempotente(client, square_svg):
    """El anticipo del acta = total pagado a la fecha; regenerar el acta
    con el mismo anticipo no duplica el pago."""
    qid = _quote(client, square_svg)
    client.get(f"/api/entrega/{qid}", params={"anticipo": 500.0})
    assert db.get_quote(qid)["pagado"] == 500.0
    client.get(f"/api/entrega/{qid}", params={"anticipo": 500.0})
    assert db.get_quote(qid)["pagado"] == 500.0
    # Un anticipo mayor solo registra la diferencia
    client.get(f"/api/entrega/{qid}", params={"anticipo": 800.0})
    assert db.get_quote(qid)["pagado"] == 800.0


# ─── DASHBOARD ───────────────────────────────────────────────────────────────

def test_dashboard_estructura(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert len(body["meses"]) == 6
    for k in ("cotizadas", "monto_cotizado", "vendidas", "monto_vendido",
              "conversion_pct", "por_cobrar"):
        assert k in body["totales"]
    assert "por_tipo" in body and "top_clientes" in body


def test_dashboard_cuenta_vendidas_y_por_cobrar(client, square_svg):
    qid = _quote(client, square_svg)
    precio = db.get_quote(qid)["precio_final"]
    antes = client.get("/api/dashboard").json()["totales"]
    db.set_estado(qid, "autorizada")
    db.registrar_pago(qid, 100.0)
    desp = client.get("/api/dashboard").json()["totales"]
    assert desp["vendidas"] == antes["vendidas"] + 1
    assert desp["monto_vendido"] == pytest.approx(antes["monto_vendido"] + precio, abs=0.01)
    assert desp["por_cobrar"] == pytest.approx(
        antes["por_cobrar"] + precio - 100.0, abs=0.01)
    # cobrada saca el saldo de 'por cobrar'
    db.set_estado(qid, "cobrada")
    final = client.get("/api/dashboard").json()["totales"]
    assert final["por_cobrar"] == pytest.approx(antes["por_cobrar"], abs=0.01)


def test_dashboard_meses_param(client):
    r = client.get("/api/dashboard", params={"meses": 12})
    assert len(r.json()["meses"]) == 12
    assert client.get("/api/dashboard", params={"meses": 0}).status_code == 422
    assert client.get("/api/dashboard", params={"meses": 99}).status_code == 422
