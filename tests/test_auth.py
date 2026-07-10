"""
Tests de la llave de acceso (Basic Auth para exposición pública).

Sin ACCESS_PASSWORD definida el sitio queda abierto (uso local del taller);
con ella, todo exige credenciales excepto /health (monitoreo del hosting).
"""
import base64

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _basic(usuario: str, clave: str) -> dict:
    token = base64.b64encode(f"{usuario}:{clave}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_sin_llave_definida_todo_abierto(client):
    assert main.ACCESS_PASSWORD == ""  # el entorno de tests no la define
    assert client.get("/").status_code == 200
    assert client.get("/api/catalog").status_code == 200


def test_con_llave_exige_credenciales(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PASSWORD", "secreto123")
    r = client.get("/")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")
    assert client.get("/api/quotes").status_code == 401
    assert client.get("/static/index.html").status_code == 401


def test_credenciales_incorrectas_401(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PASSWORD", "secreto123")
    assert client.get("/", headers=_basic("sgi", "adivinada")).status_code == 401
    assert client.get("/", headers=_basic("otro", "secreto123")).status_code == 401
    assert client.get("/", headers={"Authorization": "Basic ###no-base64###"}).status_code == 401


def test_credenciales_correctas_entran(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PASSWORD", "secreto123")
    ok = _basic("sgi", "secreto123")
    assert client.get("/", headers=ok).status_code == 200
    assert client.get("/api/catalog", headers=ok).status_code == 200
    assert client.get("/api/admin/status", headers=ok).status_code == 200


def test_health_siempre_libre(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PASSWORD", "secreto123")
    assert client.get("/health").status_code == 200
