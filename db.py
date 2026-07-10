import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

# COTIZADOR_DATA_DIR: carpeta de datos mutables (DB, catálogo, respaldos).
# En hosting con disco persistente (Render) apunta al punto de montaje; sin
# definir, todo vive junto al código como siempre (uso local del taller).
_DATA_DIR = Path(os.environ.get("COTIZADOR_DATA_DIR") or Path(__file__).parent)
DB_PATH = _DATA_DIR / "cotizador.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def ping() -> bool:
    """Devuelve True si la DB responde. Usado por /health.
    Lee sqlite_master (no 'SELECT 1'): SQLite abre el archivo de forma
    perezosa y un SELECT sin tablas ni siquiera valida el encabezado."""
    try:
        with _conn() as c:
            c.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return True
    except Exception:
        return False


def es_db_valida(path: Path) -> bool:
    """True si `path` es un archivo SQLite legible (para validar un respaldo
    ANTES de restaurarlo encima de la base viva). Abre en modo solo-lectura."""
    try:
        c = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            c.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            c.close()
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
        # Migración defensiva: pipeline de estados + pagos por cotización
        if "estado" not in cols:
            c.execute("ALTER TABLE quotes ADD COLUMN estado TEXT DEFAULT 'borrador'")
        if "pagado" not in cols:
            c.execute("ALTER TABLE quotes ADD COLUMN pagado REAL DEFAULT 0")
        if "estado_fecha" not in cols:
            c.execute("ALTER TABLE quotes ADD COLUMN estado_fecha TEXT DEFAULT ''")


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


def list_quotes(cliente: str = "", tipo: str = "", estado: str = "",
                limit: int = 150, offset: int = 0) -> list[dict]:
    sql = ("SELECT id, folio, tipo, cliente, fecha, precio_final, "
           "estado, pagado FROM quotes")
    params: list = []
    where: list[str] = []
    if tipo:
        where.append("tipo=?")
        params.append(tipo)
    if cliente:
        where.append("cliente LIKE ?")
        params.append(f"%{cliente}%")
    if estado:
        where.append("estado=?")
        params.append(estado)
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


# ─── ADMINISTRACIÓN ──────────────────────────────────────────────────────────

def db_stats() -> dict:
    """Números básicos de la base para el panel de administración."""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        sin_cliente = c.execute(
            "SELECT COUNT(*) FROM quotes WHERE TRIM(COALESCE(cliente,''))=''"
        ).fetchone()[0]
        clientes = c.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        ultima = c.execute("SELECT MAX(fecha) FROM quotes").fetchone()[0]
    p = Path(DB_PATH)
    return {
        "quotes": total,
        "quotes_sin_cliente": sin_cliente,
        "clients": clientes,
        "ultima_quote": ultima or "",
        "db_bytes": p.stat().st_size if p.exists() else 0,
    }


def clean_quotes(sin_cliente: bool = False, desde: str = "", hasta: str = "") -> int:
    """Borra cotizaciones según criterios combinados (AND). Exige al menos un
    criterio para no vaciar la tabla por accidente. Devuelve cuántas borró."""
    where: list[str] = []
    params: list = []
    if sin_cliente:
        where.append("TRIM(COALESCE(cliente,'')) = ''")
    if desde:
        where.append("fecha >= ?")
        params.append(desde)
    if hasta:
        where.append("fecha <= ?")
        params.append(hasta + " 23:59:59")
    if not where:
        raise ValueError("Se requiere al menos un criterio de limpieza")
    with _conn() as c:
        cur = c.execute("DELETE FROM quotes WHERE " + " AND ".join(where), params)
    return cur.rowcount


def vacuum() -> int:
    """Compacta el archivo .db recuperando espacio de registros borrados.
    Devuelve los bytes liberados. VACUUM no puede correr dentro de una
    transacción, por eso no usa el context manager de conexión."""
    p = Path(DB_PATH)
    antes = p.stat().st_size if p.exists() else 0
    c = _conn()
    try:
        c.execute("VACUUM")
    finally:
        c.close()
    despues = p.stat().st_size if p.exists() else 0
    return max(0, antes - despues)


# ─── PIPELINE DE ESTADOS Y PAGOS ─────────────────────────────────────────────
# Ciclo de vida de una cotización en el taller. El orden importa para el
# auto-avance por documentos: generar un documento nunca REGRESA el estado.

ESTADOS = ["borrador", "enviada", "autorizada", "fabricacion",
           "entregada", "cobrada", "perdida"]


def set_estado(qid: str, estado: str) -> bool:
    """Cambia el estado del pipeline. Devuelve False si el estado no existe
    o la cotización no está en la DB."""
    if estado not in ESTADOS:
        return False
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        cur = c.execute("UPDATE quotes SET estado=?, estado_fecha=? WHERE id=?",
                        (estado, ahora, qid))
    return cur.rowcount > 0


def avanzar_estado(qid: str, estado_min: str) -> None:
    """Auto-avance por documento: sube el estado hasta `estado_min` solo si el
    actual está ANTES en el pipeline (nunca regresa, nunca toca 'perdida')."""
    if estado_min not in ESTADOS:
        return
    row = get_quote(qid)
    if not row:
        return
    actual = row.get("estado") or "borrador"
    if actual == "perdida":
        return
    if ESTADOS.index(actual) < ESTADOS.index(estado_min):
        set_estado(qid, estado_min)


def registrar_pago(qid: str, monto: float) -> dict | None:
    """Acumula un pago (anticipo o abono). Devuelve {pagado, saldo} o None."""
    row = get_quote(qid)
    if not row or monto <= 0:
        return None
    pagado = round((row.get("pagado") or 0) + monto, 2)
    with _conn() as c:
        c.execute("UPDATE quotes SET pagado=? WHERE id=?", (pagado, qid))
    saldo = round((row.get("precio_final") or 0) - pagado, 2)
    return {"pagado": pagado, "saldo": saldo}


# ─── DASHBOARD DE RESULTADOS ─────────────────────────────────────────────────

_ESTADOS_VENDIDA = {"autorizada", "fabricacion", "entregada", "cobrada"}


def resumen_dashboard(meses: int = 6) -> dict:
    """Métricas de negocio de los últimos N meses: cotizado vs vendido por mes
    (con conversión), margen real promedio, por cobrar, por tipo y top clientes.
    'Vendida' = el cliente autorizó (autorizada/fabricación/entregada/cobrada)."""
    hoy = datetime.now()
    # primer día del mes de arranque de la ventana
    m0 = hoy.month - (meses - 1)
    anio0 = hoy.year + (m0 - 1) // 12
    mes0 = (m0 - 1) % 12 + 1
    desde = f"{anio0:04d}-{mes0:02d}-01"

    with _conn() as c:
        rows = c.execute(
            "SELECT fecha, tipo, cliente, precio_final, estado, pagado, result_json "
            "FROM quotes WHERE fecha >= ? ORDER BY fecha", (desde,)
        ).fetchall()

    # esqueleto de meses (aunque estén vacíos)
    claves_mes: list[str] = []
    a, m = anio0, mes0
    for _ in range(meses):
        claves_mes.append(f"{a:04d}-{m:02d}")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    por_mes = {k: {"mes": k, "cotizadas": 0, "monto_cotizado": 0.0,
                   "vendidas": 0, "monto_vendido": 0.0}
               for k in claves_mes}

    por_tipo: dict[str, dict] = {}
    por_cliente: dict[str, float] = {}
    por_estado: dict[str, int] = {}
    por_cobrar = 0.0
    margenes: list[float] = []

    for r in rows:
        precio = r["precio_final"] or 0.0
        estado = r["estado"] or "borrador"
        vendida = estado in _ESTADOS_VENDIDA
        mes_k = (r["fecha"] or "")[:7]
        por_estado[estado] = por_estado.get(estado, 0) + 1
        if mes_k in por_mes:
            pm = por_mes[mes_k]
            pm["cotizadas"] += 1
            pm["monto_cotizado"] += precio
            if vendida:
                pm["vendidas"] += 1
                pm["monto_vendido"] += precio
        if vendida:
            # costo real estimado por el motor: total (c/IVA) + instalación
            try:
                res = json.loads(r["result_json"])
                costo = (res.get("total") or 0) + (res.get("inst_total") or 0)
            except Exception:
                costo = 0.0
            if precio > 0 and costo > 0:
                margenes.append((precio - costo) / precio * 100)
            t = por_tipo.setdefault(r["tipo"], {"tipo": r["tipo"], "vendidas": 0,
                                                "monto": 0.0, "margenes": []})
            t["vendidas"] += 1
            t["monto"] += precio
            if precio > 0 and costo > 0:
                t["margenes"].append((precio - costo) / precio * 100)
            nombre = (r["cliente"] or "").strip() or "(sin nombre)"
            por_cliente[nombre] = por_cliente.get(nombre, 0.0) + precio
            if estado != "cobrada":
                por_cobrar += max(0.0, precio - (r["pagado"] or 0))

    for pm in por_mes.values():
        pm["conversion_pct"] = round(pm["vendidas"] / pm["cotizadas"] * 100, 1) \
            if pm["cotizadas"] else 0.0
        pm["monto_cotizado"] = round(pm["monto_cotizado"], 2)
        pm["monto_vendido"] = round(pm["monto_vendido"], 2)

    tipos = []
    for t in por_tipo.values():
        margs = t.pop("margenes")
        t["monto"] = round(t["monto"], 2)
        t["margen_prom_pct"] = round(sum(margs) / len(margs), 1) if margs else None
        tipos.append(t)
    tipos.sort(key=lambda t: -t["monto"])

    top_clientes = sorted(por_cliente.items(), key=lambda kv: -kv[1])[:5]

    tot_cot = sum(pm["cotizadas"] for pm in por_mes.values())
    tot_ven = sum(pm["vendidas"] for pm in por_mes.values())
    return {
        "meses": [por_mes[k] for k in claves_mes],
        "totales": {
            "cotizadas": tot_cot,
            "monto_cotizado": round(sum(pm["monto_cotizado"] for pm in por_mes.values()), 2),
            "vendidas": tot_ven,
            "monto_vendido": round(sum(pm["monto_vendido"] for pm in por_mes.values()), 2),
            "conversion_pct": round(tot_ven / tot_cot * 100, 1) if tot_cot else 0.0,
            "margen_prom_pct": round(sum(margenes) / len(margenes), 1) if margenes else None,
            "por_cobrar": round(por_cobrar, 2),
        },
        "por_estado": por_estado,
        "por_tipo": tipos,
        "top_clientes": [{"cliente": n, "monto": round(m, 2)} for n, m in top_clientes],
    }


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
