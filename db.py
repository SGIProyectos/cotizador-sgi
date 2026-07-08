import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "cotizador.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def ping() -> bool:
    """Devuelve True si la DB responde. Usado por /health."""
    try:
        with _conn() as c:
            c.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS quotes (
                id           TEXT PRIMARY KEY,
                folio        TEXT NOT NULL,
                tipo         TEXT NOT NULL,
                cliente      TEXT DEFAULT '',
                notas        TEXT DEFAULT '',
                fecha        TEXT NOT NULL,
                result_json  TEXT NOT NULL,
                params_json  TEXT NOT NULL,
                svg_text     TEXT DEFAULT '',
                precio_final REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS folio_seq (
                year   INTEGER PRIMARY KEY,
                last_n INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS clients (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre    TEXT NOT NULL,
                rfc       TEXT DEFAULT '',
                email     TEXT DEFAULT '',
                telefono  TEXT DEFAULT '',
                direccion TEXT DEFAULT ''
            );
            -- Índices: aceleran filtros y orden del historial
            CREATE INDEX IF NOT EXISTS idx_quotes_fecha   ON quotes(fecha DESC);
            CREATE INDEX IF NOT EXISTS idx_quotes_cliente ON quotes(cliente);
            CREATE INDEX IF NOT EXISTS idx_quotes_folio   ON quotes(folio);
            CREATE INDEX IF NOT EXISTS idx_quotes_tipo    ON quotes(tipo);
            CREATE INDEX IF NOT EXISTS idx_clients_nombre ON clients(nombre);
        """)
        # Migración defensiva: DBs creadas antes de añadir svg_text al esquema
        cols = {r[1] for r in c.execute("PRAGMA table_info(quotes)").fetchall()}
        if "svg_text" not in cols:
            c.execute("ALTER TABLE quotes ADD COLUMN svg_text TEXT DEFAULT ''")
        # Migración defensiva: dirección del cliente (para acta de entrega)
        ccols = {r[1] for r in c.execute("PRAGMA table_info(clients)").fetchall()}
        if "direccion" not in ccols:
            c.execute("ALTER TABLE clients ADD COLUMN direccion TEXT DEFAULT ''")


def next_folio() -> str:
    year = datetime.now().year
    with _conn() as c:
        c.execute(
            "INSERT INTO folio_seq(year,last_n) VALUES(?,1) "
            "ON CONFLICT(year) DO UPDATE SET last_n=last_n+1",
            (year,)
        )
        row = c.execute("SELECT last_n FROM folio_seq WHERE year=?", (year,)).fetchone()
    return f"SGI-{year}-{row['last_n']:04d}"


def save_quote(qid: str, folio: str, tipo: str, cliente: str, notas: str,
               result_dict: dict, params_dict: dict,
               svg_text: str, precio_final: float):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO quotes
              (id, folio, tipo, cliente, notas, fecha,
               result_json, params_json, svg_text, precio_final)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (qid, folio, tipo, cliente, notas, fecha,
              json.dumps(result_dict, ensure_ascii=False),
              json.dumps(params_dict, ensure_ascii=False),
              svg_text, precio_final))


def list_quotes(cliente: str = "", tipo: str = "",
                limit: int = 150, offset: int = 0) -> list[dict]:
    sql = ("SELECT id, folio, tipo, cliente, fecha, precio_final "
           "FROM quotes")
    params: list = []
    where: list[str] = []
    if tipo:
        where.append("tipo=?")
        params.append(tipo)
    if cliente:
        where.append("cliente LIKE ?")
        params.append(f"%{cliente}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fecha DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_quote(qid: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
    return dict(row) if row else None


def delete_quote(qid: str):
    with _conn() as c:
        c.execute("DELETE FROM quotes WHERE id=?", (qid,))


# ─── CLIENTES ────────────────────────────────────────────────────────────────

def list_clients(q: str = "") -> list[dict]:
    sql = "SELECT * FROM clients"
    params: list = []
    if q:
        sql += " WHERE nombre LIKE ? OR rfc LIKE ? OR email LIKE ? OR telefono LIKE ?"
        params = [f"%{q}%"] * 4
    sql += " ORDER BY nombre COLLATE NOCASE"
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def save_client(nombre: str, rfc: str = "", email: str = "",
                telefono: str = "", direccion: str = "",
                client_id: int | None = None) -> int:
    with _conn() as c:
        if client_id:
            c.execute(
                "UPDATE clients SET nombre=?,rfc=?,email=?,telefono=?,direccion=? WHERE id=?",
                (nombre, rfc, email, telefono, direccion, client_id)
            )
            return client_id
        else:
            cur = c.execute(
                "INSERT INTO clients(nombre,rfc,email,telefono,direccion) VALUES(?,?,?,?,?)",
                (nombre, rfc, email, telefono, direccion)
            )
            return cur.lastrowid


def get_client_by_name(nombre: str) -> dict | None:
    """Cliente cuyo nombre coincide (sin distinguir mayúsculas); None si no hay.
    Es el enlace catálogo → documentos: el acta/OT jalan RFC, teléfono y
    dirección registrados a partir del nombre capturado en la cotización."""
    if not nombre or not nombre.strip():
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM clients WHERE nombre = ? COLLATE NOCASE "
            "ORDER BY id LIMIT 1", (nombre.strip(),)
        ).fetchone()
    return dict(row) if row else None


def delete_client(client_id: int):
    with _conn() as c:
        c.execute("DELETE FROM clients WHERE id=?", (client_id,))
