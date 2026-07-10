"""
Tests del módulo de administración: estado del sistema, respaldos
(crear/listar/descargar/restaurar) y mantenimiento de la base (limpieza
con respaldo previo, vacuum). Los respaldos van a una carpeta temporal
por test (además del aislamiento de sesión en conftest).
"""
import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "BACKUP_DIR", tmp_path / "backups")
    with TestClient(main.app) as c:
        yield c


def _guardar_quote(qid: str, cliente: str = "", fecha: str = "") -> None:
    db.save_quote(qid, f"SGI-2026-{qid}", "letras_3d", cliente, "",
                  {"total": 100.0}, {}, "", 100.0)
    if fecha:
        import sqlite3
        with sqlite3.connect(str(db.DB_PATH)) as c:
            c.execute("UPDATE quotes SET fecha=? WHERE id=?",
                      (fecha + " 12:00:00", qid))


def _limpiar_tabla() -> None:
    import sqlite3
    with sqlite3.connect(str(db.DB_PATH)) as c:
        c.execute("DELETE FROM quotes")


# ─── STATUS ──────────────────────────────────────────────────────────────────

def test_status_reporta_db_y_disco(client):
    r = client.get("/api/admin/status")
    assert r.status_code == 200
    data = r.json()
    assert data["db_ok"] is True
    assert data["db"]["quotes"] >= 0
    assert data["disco"]["total_gb"] > 0
    assert "retencion_dias" in data["backups"]


# ─── RESPALDOS ───────────────────────────────────────────────────────────────

def test_backup_manual_crea_y_lista(client):
    r = client.post("/api/admin/backup")
    assert r.status_code == 200
    creados = r.json()["creados"]
    assert any(n.startswith("cotizador_") and n.endswith(".db") for n in creados)

    lista = client.get("/api/admin/backups").json()["backups"]
    nombres = [b["nombre"] for b in lista]
    for n in creados:
        assert n in nombres
    tipos = {b["nombre"]: b["tipo"] for b in lista}
    assert all(tipos[n] == "base" for n in creados if n.endswith(".db"))


def test_backup_download(client):
    creados = client.post("/api/admin/backup").json()["creados"]
    nombre = next(n for n in creados if n.endswith(".db"))
    r = client.get(f"/api/admin/backups/{nombre}/download")
    assert r.status_code == 200
    assert nombre in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_backup_download_nombre_invalido(client):
    assert client.get("/api/admin/backups/malo;x.db/download").status_code == 400
    assert client.get("/api/admin/backups/..%2Fcotizador.db/download").status_code in (400, 404)
    assert client.get("/api/admin/backups/no_existe.db/download").status_code == 404


def test_restore_db_recupera_cotizacion_borrada(client):
    _limpiar_tabla()
    _guardar_quote("resta1", cliente="Cliente Real")
    creados = client.post("/api/admin/backup").json()["creados"]
    respaldo = next(n for n in creados if n.startswith("cotizador_"))

    db.delete_quote("resta1")
    assert db.get_quote("resta1") is None

    r = client.post("/api/admin/restore", json={"nombre": respaldo})
    assert r.status_code == 200
    data = r.json()
    assert data["tipo"] == "base"
    # la restauración misma dejó un respaldo del estado previo
    assert data["respaldo_previo"].startswith("pre_restaurar_")
    assert db.get_quote("resta1") is not None


def test_restore_respaldo_corrupto_rechazado(client):
    _limpiar_tabla()
    _guardar_quote("intacta")
    main.BACKUP_DIR.mkdir(exist_ok=True)
    (main.BACKUP_DIR / "cotizador_corrupto.db").write_bytes(b"esto no es sqlite")

    r = client.post("/api/admin/restore", json={"nombre": "cotizador_corrupto.db"})
    assert r.status_code == 400
    # la base original sigue viva y con sus datos
    assert db.ping() is True
    assert db.get_quote("intacta") is not None


# ─── LIMPIEZA ────────────────────────────────────────────────────────────────

def test_limpiar_sin_criterios_400(client):
    r = client.post("/api/admin/db/limpiar",
                    json={"sin_cliente": False, "desde": "", "hasta": ""})
    assert r.status_code == 400


def test_limpiar_fecha_invalida_400(client):
    r = client.post("/api/admin/db/limpiar", json={"desde": "10/07/2026"})
    assert r.status_code == 400


def test_limpiar_sin_cliente_respeta_las_nombradas(client):
    _limpiar_tabla()
    _guardar_quote("basura1")
    _guardar_quote("basura2")
    _guardar_quote("buena", cliente="Cliente Real")

    r = client.post("/api/admin/db/limpiar", json={"sin_cliente": True})
    assert r.status_code == 200
    assert r.json()["borradas"] == 2
    assert r.json()["restantes"] == 1
    assert db.get_quote("buena") is not None
    # y dejó respaldo previo automático
    lista = client.get("/api/admin/backups").json()["backups"]
    assert any(b["nombre"].startswith("cotizador_") for b in lista)


def test_clean_quotes_por_rango_de_fechas():
    _limpiar_tabla()
    _guardar_quote("vieja", fecha="2026-01-15")
    _guardar_quote("media", fecha="2026-03-10")
    _guardar_quote("nueva", fecha="2026-06-20")

    borradas = db.clean_quotes(desde="2026-02-01", hasta="2026-04-30")
    assert borradas == 1
    assert db.get_quote("media") is None
    assert db.get_quote("vieja") is not None
    assert db.get_quote("nueva") is not None


def test_clean_quotes_exige_criterio():
    with pytest.raises(ValueError):
        db.clean_quotes()


# ─── VACUUM ──────────────────────────────────────────────────────────────────

def test_vacuum_endpoint(client):
    r = client.post("/api/admin/db/vacuum")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["bytes_liberados"] >= 0
    assert data["db_bytes"] > 0
