import asyncio
import dataclasses
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

import db
from calculator import QuoteResult, cotizar_caja, cotizar_letras, cotizar_planas, parse_svg
from catalog_data import (
    GRUAS,
    catalog_apply,
    catalog_save,
    catalog_to_dict,
)
from excel_gen import generar_xlsx
from pdf_gen import generar_pdf, generar_pdf_entrega, generar_pdf_ot
from plano_gen import generar_plano_cliente, generar_plano_taller

BASE = Path(__file__).parent
STATIC = BASE / "static"
STATIC.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Cargar variables de .env (parser mínimo, sin dependencias extra)
_ENV_FILE = BASE / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _v = _v.strip().strip('"').strip("'")
        if _v:
            os.environ.setdefault(_k.strip(), _v)

# ─── LOGGING ─────────────────────────────────────────────────────────────────

LOG_FILE = BASE / "server.log"
_log_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[_log_handler, logging.StreamHandler()],
)
log = logging.getLogger("cotizador")

# Sentry: solo se activa si SENTRY_DSN está definido. No falla si el paquete no
# está instalado (es opcional en requirements).
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.environ.get("SENTRY_ENV", "production"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.0")),
            send_default_pii=False,
            integrations=[
                FastApiIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
        )
        log.info("Sentry inicializado")
    except ImportError:
        log.warning("SENTRY_DSN definido pero sentry-sdk no está instalado")
    except Exception:
        log.exception("Error inicializando Sentry")

# ─── CACHES EN MEMORIA ───────────────────────────────────────────────────────
#
# Estos diccionarios son estado mutable compartido entre handlers async,
# handlers sync (thread-pool de FastAPI) y la tarea de purga periódica.
# `_state_lock` los protege contra interleaving DENTRO del mismo proceso.
# Para correr múltiples workers de uvicorn hace falta externalizar a Redis u
# otro store — un Lock de threading no cruza procesos.

_state_lock = threading.RLock()

# Almacén en memoria de SVGs parseados (por sesión simple)
_svg_store: dict[str, dict] = {}
# Caché en memoria de cotizaciones (QuoteResult + meta) — respaldado por SQLite
_quote_store: dict[str, QuoteResult] = {}

# Timestamps de último acceso por clave (para TTL)
_svg_touch:   dict[str, float] = {}
_quote_touch: dict[str, float] = {}

SVG_TTL_SECONDS   = 24 * 3600        # 24 h — SVGs son re-subibles, expiran rápido
QUOTE_TTL_SECONDS = 7 * 24 * 3600    # 7 d  — cotizaciones se recargan desde SQLite si hace falta
CLEANUP_INTERVAL  = 3600             # 1 h


def _touch_svg(sid: str) -> None:
    with _state_lock:
        _svg_touch[sid] = time.time()


def _touch_quote(qid: str) -> None:
    with _state_lock:
        _quote_touch[qid] = time.time()


def _purge_expired_caches() -> None:
    now = time.time()
    with _state_lock:
        svg_dead = [k for k, t in _svg_touch.items() if now - t > SVG_TTL_SECONDS]
        for k in svg_dead:
            _svg_store.pop(k, None)
            _svg_touch.pop(k, None)
        q_dead = [k for k, t in _quote_touch.items() if now - t > QUOTE_TTL_SECONDS]
        for k in q_dead:
            _quote_store.pop(k, None)
            _quote_store.pop(k + "_meta", None)
            _quote_touch.pop(k, None)
    if svg_dead or q_dead:
        log.info("TTL purge: %d svgs, %d quotes", len(svg_dead), len(q_dead))

# ─── BACKUPS ─────────────────────────────────────────────────────────────────

BACKUP_DIR    = BASE / "backups"
DB_FILE       = BASE / "cotizador.db"
CATALOG_FILE  = BASE / "catalog.json"
BACKUP_RETENTION_DAYS = 30
BACKUP_INTERVAL = 24 * 3600  # diario


def _rotate_backups(prefix: str) -> None:
    """Borra archivos backups/<prefix>_*.* anteriores al periodo de retención."""
    cutoff = time.time() - BACKUP_RETENTION_DAYS * 86400
    for old in BACKUP_DIR.glob(f"{prefix}_*.*"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            log.warning("No se pudo borrar backup antiguo %s", old.name, exc_info=True)


def _backup_file(src: Path, prefix: str) -> None:
    """Copia src a backups/<prefix>_YYYYMMDD_HHMMSS<extension>, rota antiguos."""
    if not src.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{prefix}_{ts}{src.suffix}"
    try:
        shutil.copy2(src, dest)
        log.info("Backup creado: %s", dest.name)
    except Exception:
        log.exception("Backup falló para %s", src.name)
        return
    _rotate_backups(prefix)


def _backup_db() -> None:
    _backup_file(DB_FILE, "cotizador")


def _backup_catalog() -> None:
    _backup_file(CATALOG_FILE, "catalog")

# ─── LIFESPAN ────────────────────────────────────────────────────────────────

async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            _purge_expired_caches()
        except Exception:
            log.exception("Cleanup de caches falló")


async def _periodic_backup() -> None:
    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        try:
            _backup_db()
            _backup_catalog()
        except Exception:
            log.exception("Backup periódico falló")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Cotizador SGI iniciando…")
    app.state.started_at = datetime.now().isoformat(timespec="seconds")
    db.init_db()
    _backup_db()
    _backup_catalog()
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    backup_task  = asyncio.create_task(_periodic_backup())
    try:
        yield
    finally:
        log.info("Cotizador SGI deteniéndose…")
        cleanup_task.cancel()
        backup_task.cancel()


app = FastAPI(title="Cotizador SGI - Letras y Anuncios", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ─── HTML PRINCIPAL ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    content = (STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})


# ─── HEALTHCHECK ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Verifica DB y caches. Devuelve 503 si la DB no responde."""
    db_ok = db.ping()
    body = {
        "status": "ok" if db_ok else "degraded",
        "db":     "ok" if db_ok else "error",
        "caches": {
            "svgs":   len(_svg_store),
            "quotes": len(_quote_touch),
        },
        "started_at": getattr(app.state, "started_at", None),
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


# ─── PARSEAR SVG ─────────────────────────────────────────────────────────────

@app.post("/api/parse-svg")
async def api_parse_svg(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Archivo demasiado grande (máximo {MAX_UPLOAD_BYTES // (1024*1024)} MB)")

    try:
        svg_data = parse_svg(content)
    except Exception as e:
        raise HTTPException(400, f"Error al parsear SVG: {e}")

    sid = str(uuid.uuid4())
    svg_text_decoded = content.decode("utf-8", errors="replace")
    with _state_lock:
        _svg_store[sid] = {
            "bytes": svg_text_decoded,
            "svg_data": svg_data,
        }
        _svg_touch[sid] = time.time()

    paths_info = [
        {
            "id": p.id,
            "svg_id": p.svg_id,
            "perimeter_px": round(p.perimeter_px, 2),
            "area_px": round(p.area_px, 2),
            "is_closed": p.is_closed,
            "es_hueco": p.es_hueco,
            "bbox": p.bbox,
        }
        for p in svg_data.paths
    ]

    return {
        "session_id": sid,
        "paths": paths_info,
        "viewbox_w": svg_data.viewbox_w,
        "viewbox_h": svg_data.viewbox_h,
        "svg_unit": svg_data.svg_unit,
        "svg_text": svg_text_decoded,
        "max_pieza_height_px": round(svg_data.max_pieza_height_px, 2),
        # alias retro-compatible para clientes viejos que aún lean el nombre anterior
        "max_letter_height_px": round(svg_data.max_pieza_height_px, 2),
        "artboard_w_cm": round(svg_data.artboard_w_cm, 2),
    }


# ─── MODELOS DE PETICIÓN ─────────────────────────────────────────────────────

class _InstMixin(BaseModel):
    mo_horas: float = 0.0
    mo_tarifa: float = 150.0
    inst_activa: bool = False
    inst_lugar: str = ""
    inst_viaticos: float = 0.0
    inst_grua_id: str = "ninguna"
    inst_dias_grua: int = 1
    inst_extras: float = 0.0

class LetrasRequest(_InstMixin):
    session_id: str
    real_width_cm: float
    altura_letra_cm: float = 0.0
    uso: str = "exterior"
    tipo_cara: str = "auto"
    tipo_cercha: str = "auto"
    cercha_cm: float = 0.0
    espaciado_led_cm: float = 6.0
    margen_ganancia: float = 0.35
    tipo_construccion: str = "cajon_luz"
    tipo_multiplicador: str = "acrilico_con_luz_std"
    ajuste_pct: float = 0.0
    vinil_cercha_id: str = ""
    silvatrim_id: str = "auto"
    led_id: str = "auto"
    cliente: str = ""
    notas: str = ""

class CajaRequest(_InstMixin):
    session_id: str
    real_width_cm: float
    profundidad_cm: float
    tipo_cara: str = "lona"          # material base: "lona" | "acrilico" (legacy: "vinil_corte", "acrilico_2vistas")
    base_cara_vinil: str = "lona"    # legacy, solo con tipo_cara="vinil_corte"
    grafico: str = "impreso"         # "ninguno" | "impreso" | "vinil_corte"
    vinil_id: str = "vinil_std"      # vinil del catálogo para grafico="vinil_corte"
    led_id: str = "auto"
    uso: str = "exterior"
    vistas: int = 1
    margen_ganancia: float = 0.35
    # Maquila y flete (montos manuales por cotización, suelen variar por proveedor)
    corte_laser: float = 0.0
    corte_cnc: float = 0.0
    corte_plotter: float = 0.0
    flete_maquila: float = 0.0
    cliente: str = ""
    notas: str = ""

class PlanasRequest(_InstMixin):
    session_id: str
    real_width_cm: float
    material_id: str = "acrilico_3mm"
    margen_ganancia: float = 0.35
    tipo_multiplicador: str = "aluminio_sin_luz"
    ajuste_pct: float = 0.0
    cliente: str = ""
    notas: str = ""


# ─── INSTALACIÓN / MANO DE OBRA ──────────────────────────────────────────────

def _apply_instalacion(result: QuoteResult, req: _InstMixin) -> QuoteResult:
    # Para caja_luz la MO se inyecta dentro de cotizar_caja (entra al costo y
    # el margen se aplica). NO la duplicamos como línea separada — eso causaría
    # doble cobro en el PDF.
    if result.tipo != "caja_luz":
        result.mo_total = round(req.mo_horas * req.mo_tarifa, 2)
    if req.inst_activa:
        grua = next((g for g in GRUAS if g["id"] == req.inst_grua_id), {"precio_dia": 0})
        costo_grua = round(grua["precio_dia"] * req.inst_dias_grua, 2)
        result.inst_activa    = True
        result.inst_lugar     = req.inst_lugar
        result.inst_viaticos  = round(req.inst_viaticos, 2)
        result.inst_grua      = req.inst_grua_id
        result.inst_costo_grua = costo_grua
        result.inst_extras    = round(req.inst_extras, 2)
        result.inst_total     = round(req.inst_viaticos + costo_grua + req.inst_extras, 2)
    result.precio_final = round(result.precio_venta_sugerido + result.inst_total, 2)
    return result


# ─── HELPERS DE PERSISTENCIA ─────────────────────────────────────────────────

_QUOTE_FIELDS = {f.name for f in dataclasses.fields(QuoteResult)}


def _load_quote_from_db(quote_id: str) -> bool:
    """Carga una cotización de SQLite al caché en memoria. Devuelve True si se encontró."""
    row = db.get_quote(quote_id)
    if not row:
        return False
    try:
        result_data = json.loads(row["result_json"])
        result = QuoteResult(**{k: v for k, v in result_data.items() if k in _QUOTE_FIELDS})
        try:
            fecha_display = datetime.strptime(row["fecha"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y")
        except ValueError:
            fecha_display = row["fecha"]
        with _state_lock:
            _quote_store[quote_id] = result
            _quote_store[quote_id + "_meta"] = {
                "cliente": row["cliente"],
                "notas":   row["notas"],
                "fecha":   fecha_display,
                "folio":   row["folio"],
                "tipo":    row["tipo"],
            }
            _quote_touch[quote_id] = time.time()
    except Exception:
        log.exception("Error cargando cotización %s desde DB", quote_id)
        return False
    return True


def _ensure_quote_in_memory(quote_id: str) -> QuoteResult | None:
    """Devuelve QuoteResult desde caché o SQLite. None si no existe."""
    with _state_lock:
        cached = _quote_store.get(quote_id)
    if cached is None:
        _load_quote_from_db(quote_id)
        with _state_lock:
            cached = _quote_store.get(quote_id)
    return cached


def _save_to_db(qid: str, folio: str, tipo: str,
                result: QuoteResult, req, svg_text: str):
    """Persiste cotización a SQLite."""
    result_dict  = dataclasses.asdict(result)
    params_dict  = req.model_dump(exclude={"session_id"})
    db.save_quote(
        qid, folio, tipo,
        getattr(req, "cliente", ""),
        getattr(req, "notas", ""),
        result_dict, params_dict,
        svg_text, result.precio_final,
    )


# ─── COTIZAR LETRAS 3D ───────────────────────────────────────────────────────

@app.post("/api/cotizar/letras")
async def api_cotizar_letras(req: LetrasRequest):
    with _state_lock:
        store = _svg_store.get(req.session_id)
    if not store:
        raise HTTPException(404, "Sesión no encontrada, sube el SVG de nuevo")

    svg_data = store["svg_data"]

    try:
        result = cotizar_letras(
            svg_data=svg_data,
            real_width_cm=req.real_width_cm,
            altura_letra_cm=req.altura_letra_cm,
            uso=req.uso,
            tipo_cara=req.tipo_cara,
            tipo_cercha=req.tipo_cercha,
            cercha_cm=req.cercha_cm,
            espaciado_led_cm=req.espaciado_led_cm,
            margen_ganancia=req.margen_ganancia,
            tipo_construccion=req.tipo_construccion,
            tipo_multiplicador=req.tipo_multiplicador,
            ajuste_pct=req.ajuste_pct,
            vinil_cercha_id=req.vinil_cercha_id,
            silvatrim_id=req.silvatrim_id,
            led_id=req.led_id,
        )
    except Exception as e:
        raise HTTPException(500, f"Error en cálculo: {e}")

    _apply_instalacion(result, req)

    folio = db.next_folio()
    qid   = str(uuid.uuid4())
    with _state_lock:
        _quote_store[qid] = result
        _quote_store[qid + "_meta"] = {
            "cliente": req.cliente,
            "notas":   req.notas,
            "fecha":   datetime.now().strftime("%d/%m/%Y"),
            "folio":   folio,
            "tipo":    "letras_3d",
        }
        _quote_touch[qid] = time.time()
    _save_to_db(qid, folio, "letras_3d", result, req, store["bytes"])

    return _result_to_dict(result, qid)


# ─── COTIZAR CAJA DE LUZ ─────────────────────────────────────────────────────

@app.post("/api/cotizar/caja")
async def api_cotizar_caja(req: CajaRequest):
    with _state_lock:
        store = _svg_store.get(req.session_id)
    if not store:
        raise HTTPException(404, "Sesión no encontrada")

    svg_data = store["svg_data"]

    try:
        result = cotizar_caja(
            svg_data=svg_data,
            real_width_cm=req.real_width_cm,
            profundidad_cm=req.profundidad_cm,
            tipo_cara=req.tipo_cara,
            base_cara_vinil=req.base_cara_vinil,
            grafico=req.grafico,
            vinil_id=req.vinil_id,
            led_id=req.led_id,
            uso=req.uso,
            vistas=req.vistas,
            margen_ganancia=req.margen_ganancia,
            corte_laser=req.corte_laser,
            corte_cnc=req.corte_cnc,
            corte_plotter=req.corte_plotter,
            flete_maquila=req.flete_maquila,
            mo_horas=req.mo_horas,
            mo_tarifa=req.mo_tarifa,
        )
    except Exception as e:
        raise HTTPException(500, f"Error en cálculo: {e}")

    _apply_instalacion(result, req)

    folio = db.next_folio()
    qid   = str(uuid.uuid4())
    with _state_lock:
        _quote_store[qid] = result
        _quote_store[qid + "_meta"] = {
            "cliente": req.cliente,
            "notas":   req.notas,
            "fecha":   datetime.now().strftime("%d/%m/%Y"),
            "folio":   folio,
            "tipo":    "caja_luz",
        }
        _quote_touch[qid] = time.time()
    _save_to_db(qid, folio, "caja_luz", result, req, store["bytes"])

    return _result_to_dict(result, qid)


# ─── COTIZAR LETRAS PLANAS ───────────────────────────────────────────────────

@app.post("/api/cotizar/planas")
async def api_cotizar_planas(req: PlanasRequest):
    with _state_lock:
        store = _svg_store.get(req.session_id)
    if not store:
        raise HTTPException(404, "Sesión no encontrada")
    svg_data = store["svg_data"]
    try:
        result = cotizar_planas(
            svg_data=svg_data,
            real_width_cm=req.real_width_cm,
            material_id=req.material_id,
            margen_ganancia=req.margen_ganancia,
            tipo_multiplicador=req.tipo_multiplicador,
            ajuste_pct=req.ajuste_pct,
        )
    except Exception as e:
        raise HTTPException(500, f"Error en cálculo: {e}")

    _apply_instalacion(result, req)

    folio = db.next_folio()
    qid   = str(uuid.uuid4())
    with _state_lock:
        _quote_store[qid] = result
        _quote_store[qid + "_meta"] = {
            "cliente": req.cliente,
            "notas":   req.notas,
            "fecha":   datetime.now().strftime("%d/%m/%Y"),
            "folio":   folio,
            "tipo":    "letras_planas",
        }
        _quote_touch[qid] = time.time()
    _save_to_db(qid, folio, "letras_planas", result, req, store["bytes"])

    return _result_to_dict(result, qid)


# ─── HISTORIAL DE COTIZACIONES ───────────────────────────────────────────────

@app.get("/api/quotes")
async def api_list_quotes(
    cliente: str = Query(""),
    tipo:    str = Query(""),
    limit:   int = Query(150),
    offset:  int = Query(0),
):
    return db.list_quotes(cliente=cliente, tipo=tipo, limit=limit, offset=offset)


@app.get("/api/quotes/{quote_id}/open")
async def api_open_quote(quote_id: str):
    row = db.get_quote(quote_id)
    if not row:
        raise HTTPException(404, "Cotización no encontrada")

    # Reconstruir QuoteResult en memoria
    if not _load_quote_from_db(quote_id):
        raise HTTPException(500, "No se pudo reconstruir la cotización")
    with _state_lock:
        result = _quote_store[quote_id]

    # Re-parsear SVG para crear nueva sesión válida
    new_sid      = None
    paths_info   = []
    vb_w = vb_h  = 0.0
    artboard_cm  = 0.0
    max_h_px     = 0.0

    svg_text = row.get("svg_text") or ""
    if svg_text:
        try:
            svg_data = parse_svg(svg_text.encode("utf-8"))
            new_sid = str(uuid.uuid4())
            with _state_lock:
                _svg_store[new_sid] = {"bytes": svg_text, "svg_data": svg_data}
                _svg_touch[new_sid] = time.time()
            vb_w        = svg_data.viewbox_w
            vb_h        = svg_data.viewbox_h
            artboard_cm = svg_data.artboard_w_cm
            max_h_px    = svg_data.max_letter_height_px
            paths_info  = [
                {
                    "id":           p.id,
                    "svg_id":       p.svg_id,
                    "perimeter_px": round(p.perimeter_px, 2),
                    "area_px":      round(p.area_px, 2),
                    "is_closed":    p.is_closed,
                    "bbox":         p.bbox,
                }
                for p in svg_data.paths
            ]
        except Exception:
            log.exception("Re-parse del SVG falló al re-abrir cotización %s", quote_id)

    params = json.loads(row["params_json"])

    return {
        "session_id":        new_sid,
        "params":            params,
        "paths":             paths_info,
        "viewbox_w":         vb_w,
        "viewbox_h":         vb_h,
        "artboard_w_cm":     artboard_cm,
        "max_letter_height_px": max_h_px,
        "svg_text":          svg_text,
        **_result_to_dict(result, quote_id),
    }


@app.delete("/api/quotes/{quote_id}")
async def api_delete_quote(quote_id: str):
    if not db.get_quote(quote_id):
        raise HTTPException(404, "Cotización no encontrada")
    db.delete_quote(quote_id)
    with _state_lock:
        _quote_store.pop(quote_id, None)
        _quote_store.pop(quote_id + "_meta", None)
        _quote_touch.pop(quote_id, None)
    return {"ok": True}


# ─── GENERAR PDF ─────────────────────────────────────────────────────────────

def _get_meta(quote_id: str) -> dict:
    with _state_lock:
        return dict(_quote_store.get(quote_id + "_meta", {}))


@app.get("/api/ot/{quote_id}")
async def api_ot(quote_id: str, cliente: str = "", notas: str = ""):
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas

    # Recuperar SVG persistido para añadir página landscape con el diseño
    # + badges numerados por material en la OT.
    svg_text = ""
    vb_w = vb_h = 0.0
    paths_info: list = []
    row = db.get_quote(quote_id)
    if row:
        svg_text = row.get("svg_text") or ""
        if svg_text:
            try:
                svg_data = parse_svg(svg_text.encode("utf-8"))
                vb_w = svg_data.viewbox_w
                vb_h = svg_data.viewbox_h
                # Caja de luz: se fabrica como UNA pieza — sin badges numerados
                # por letra en la página de diseño (el diseño se ve tal cual).
                if result.tipo != "caja_luz":
                    paths_info = [
                        {"svg_id": p.svg_id, "id": p.id, "bbox": p.bbox,
                         "is_closed": p.is_closed, "es_hueco": p.es_hueco}
                        for p in svg_data.paths
                    ]
            except Exception:
                log.warning("OT %s: no se pudo parsear SVG persistido", quote_id,
                            exc_info=True)
                svg_text = ""

    pdf_bytes = generar_pdf_ot(result, meta, svg_text=svg_text,
                               viewbox_w=vb_w, viewbox_h=vb_h,
                               paths_info=paths_info)
    filename  = f"OT_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename), filename=filename, media_type="application/pdf")


@app.get("/api/entrega/{quote_id}")
async def api_entrega(quote_id: str, cliente: str = "", notas: str = ""):
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas
    pdf_bytes = generar_pdf_entrega(result, meta)
    filename  = f"Entrega_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename), filename=filename, media_type="application/pdf")


# ─── PLANO TÉCNICO DE MEDIDAS ────────────────────────────────────────────────

def _cargar_svg_para_plano(quote_id: str, result) -> tuple[str, list, float, float, float, float]:
    """Recupera SVG persistido de db.get_quote y deriva las medidas en cm
    necesarias para plano_gen. Devuelve:
      (svg_text, paths_info, viewbox_w, viewbox_h, bbox_w_cm, bbox_h_cm)
    bbox_*_cm = ancho/alto del bbox conjunto de las piezas cerradas en cm,
    derivado del scale_factor implícito en result.altura_letra_cm. Devuelve
    valores vacíos / 0 si no hay SVG o el parseo falla.
    """
    row = db.get_quote(quote_id) or {}
    svg_text = row.get("svg_text") or ""
    if not svg_text:
        return "", [], 0.0, 0.0, 0.0, 0.0
    try:
        svg_data = parse_svg(svg_text.encode("utf-8"))
    except Exception:
        log.warning("plano %s: parse_svg falló", quote_id, exc_info=True)
        return "", [], 0.0, 0.0, 0.0, 0.0

    paths_info = [
        {"svg_id": p.svg_id, "id": p.id, "bbox": p.bbox, "is_closed": p.is_closed,
         "es_hueco": p.es_hueco}
        for p in svg_data.paths
    ]
    cerrados = [p for p in svg_data.paths if p.is_closed]
    if not cerrados:
        return svg_text, paths_info, svg_data.viewbox_w, svg_data.viewbox_h, 0.0, 0.0

    # scale_factor (cm por unidad SVG) = altura_letra_cm / max_h_px
    altura_cm  = getattr(result, "altura_letra_cm", 0.0) or 0.0
    max_h_px   = max(p.bbox["h"] for p in cerrados)
    cm_per_unit = (altura_cm / max_h_px) if (max_h_px > 0 and altura_cm > 0) else 0.0

    if cm_per_unit > 0:
        xs0 = [p.bbox["x"] for p in cerrados]
        ys0 = [p.bbox["y"] for p in cerrados]
        xs1 = [p.bbox["x"] + p.bbox["w"] for p in cerrados]
        ys1 = [p.bbox["y"] + p.bbox["h"] for p in cerrados]
        bbox_w_cm = (max(xs1) - min(xs0)) * cm_per_unit
        bbox_h_cm = (max(ys1) - min(ys0)) * cm_per_unit
    else:
        bbox_w_cm = bbox_h_cm = 0.0

    return (svg_text, paths_info, svg_data.viewbox_w, svg_data.viewbox_h,
            bbox_w_cm, bbox_h_cm)


@app.get("/api/plano/{quote_id}")
async def api_plano(quote_id: str, cliente: str = "", notas: str = ""):
    """Plano de medidas para el CLIENTE: dibujo + cotas globales y por pieza."""
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas

    svg_text, paths_info, vb_w, vb_h, bbox_w_cm, bbox_h_cm = \
        _cargar_svg_para_plano(quote_id, result)
    if not svg_text:
        raise HTTPException(404, "Esta cotización no tiene SVG persistido para generar el plano")

    pdf_bytes = generar_plano_cliente(
        meta=meta, svg_text=svg_text, paths_info=paths_info,
        viewbox_w=vb_w, viewbox_h=vb_h,
        real_width_cm=bbox_w_cm, altura_cm=bbox_h_cm,
        result=result,
    )
    filename = f"Plano_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename),
                        filename=filename, media_type="application/pdf")


@app.get("/api/plano-taller/{quote_id}")
async def api_plano_taller(quote_id: str, cliente: str = "", notas: str = ""):
    """Plano de fabricación para el TALLER: dibujo + cotas + tabla técnica
    con material por pieza (Fase D) + sección de notas al pie."""
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas

    svg_text, paths_info, vb_w, vb_h, bbox_w_cm, bbox_h_cm = \
        _cargar_svg_para_plano(quote_id, result)
    if not svg_text:
        raise HTTPException(404, "Esta cotización no tiene SVG persistido para generar el plano")

    pdf_bytes = generar_plano_taller(
        meta=meta, svg_text=svg_text, paths_info=paths_info,
        viewbox_w=vb_w, viewbox_h=vb_h,
        real_width_cm=bbox_w_cm, altura_cm=bbox_h_cm,
        result=result, notas=(notas or meta.get("notas", "")),
    )
    filename = f"PlanoTaller_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename),
                        filename=filename, media_type="application/pdf")


@app.get("/api/pdf/{quote_id}")
async def api_pdf(quote_id: str, cliente: str = "", notas: str = ""):
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")

    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas

    pdf_bytes = generar_pdf(result, meta)
    filename  = f"Cotizacion_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.pdf"

    return FileResponse(
        path=_write_tmp(pdf_bytes, filename),
        filename=filename,
        media_type="application/pdf",
    )


@app.get("/api/excel/{quote_id}")
async def api_excel(quote_id: str, cliente: str = "", notas: str = ""):
    """Exporta la cotización a .xlsx con hojas Resumen / Letras / Desglose."""
    result = _ensure_quote_in_memory(quote_id)
    meta   = _get_meta(quote_id)
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas

    xlsx_bytes = generar_xlsx(result, meta)
    filename = f"Cotizacion_{_safe_part(meta.get('folio'))}_{_safe_part(meta.get('cliente'), default='cliente')}.xlsx"
    return FileResponse(
        path=_write_tmp(xlsx_bytes, filename),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _safe_part(s: str, default: str = "SGI", max_len: int = 60) -> str:
    """Sanitiza un fragmento de nombre de archivo: elimina separadores de ruta,
    caracteres de control e inyección de headers. Limita longitud."""
    if not s:
        return default
    cleaned = re.sub(r"[^\w\s.-]", "", str(s), flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned[:max_len] or default)


def _write_tmp(data: bytes, name: str) -> str:
    p = BASE / "tmp"
    p.mkdir(exist_ok=True)
    safe_name = Path(name).name
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)[:120] or "documento.pdf"
    out = p / safe_name
    out.write_bytes(data)
    return str(out)


def _result_to_dict(r: QuoteResult, qid: str) -> dict:
    with _state_lock:
        meta = _quote_store.get(qid + "_meta", {})
    return {
        "quote_id": qid,
        "folio": meta.get("folio", ""),
        "tipo": r.tipo,
        "medidas": {
            "paths_detectados": r.paths_count,
            "altura_letra_cm": round(r.altura_letra_cm, 1),
            "area_cara_cm2": round(r.area_cara_cm2, 2),
            "area_cara_m2": round(r.area_cara_cm2 / 10000, 4),
            "perimetro_total_cm": round(r.perimetro_total_cm, 2),
            "cercha_altura_cm": round(r.cercha_altura_cm, 1),
            "cercha_area_cm2": round(r.cercha_area_cm2, 2),
            "cercha_min_cm": getattr(r, "cercha_min_cm", 0.0),
            "cercha_max_cm": getattr(r, "cercha_max_cm", 0.0),
            "categoria_letra": getattr(r, "categoria_letra", ""),
        },
        "materiales": {
            "cara": {
                "nombre": r.material_cara.get("nombre"),
                "base": r.material_cara.get("base"),
                "grafico": r.material_cara.get("grafico"),
                "cuadro_corte": r.material_cara.get("cuadro_corte"),
                "vinil_filas":   r.material_cara.get("vinil_filas"),
                "vinil_area_m2": r.material_cara.get("vinil_area_m2"),
                "laminas": r.laminas_cara,
                "costo": round(r.costo_material_cara, 2),
            },
            "cercha": {
                "nombre": r.material_cercha.get("nombre"),
                "laminas": r.laminas_cercha,
                "costo": round(r.costo_material_cercha, 2),
            },
            "fondo": {
                "nombre": r.material_fondo.get("nombre"),
                "laminas": r.laminas_fondo,
                "costo": round(r.costo_material_fondo, 2),
            },
        },
        "iluminacion": {
            "led": r.led.get("nombre"),
            "modulos": r.modulos_led,
            "watts_total": round(r.watts_total, 2),
            "fuente": r.fuente.get("nombre"),
            "costo_led": round(r.costo_led, 2),
            "costo_fuente": round(r.costo_fuente, 2),
        },
        "pegamento": {
            "nombre": r.pegamento.get("nombre"),
            "costo": round(r.costo_pegamento, 2),
        },
        "vinil_cercha": {
            "nombre": r.vinil_cercha.get("nombre", ""),
            "metros": round(r.metros_vinil_cercha, 2),
            "costo": round(r.costo_vinil_cercha, 2),
        },
        "costos": {
            "subtotal": round(r.subtotal, 2),
            "iva": round(r.iva, 2),
            "total": round(r.total, 2),
            "precio_venta_sugerido": round(r.precio_venta_sugerido, 2),
            "precio_sin_ajuste": round(r.precio_sin_ajuste, 2),
            "ajuste_pct": round(r.ajuste_pct, 2),
            "precio_venta_costo": round(r.precio_venta_costo, 2),
            "tipo_multiplicador": r.tipo_multiplicador,
            "multiplicador_valor": r.multiplicador_valor,
            "tipo_construccion": r.tipo_construccion,
            "mo_total": round(r.mo_total, 2),
            "inst_total": round(r.inst_total, 2),
            "precio_final": round(r.precio_final, 2),
        },
        "instalacion": {
            "activa": r.inst_activa,
            "lugar": r.inst_lugar,
            "viaticos": round(r.inst_viaticos, 2),
            "grua": r.inst_grua,
            "costo_grua": round(r.inst_costo_grua, 2),
            "extras": round(r.inst_extras, 2),
            "total": round(r.inst_total, 2),
        },
        "desglose": [
            {"concepto": d["concepto"], "costo": round(d["costo"], 2)}
            for d in r.desglose if d["costo"] > 0
        ],
        "desglose_letras": r.desglose_letras,
        "desglose_costos_componentes": r.desglose_costos_componentes,
        "warnings": r.warnings,
        "pdf_url": f"/api/pdf/{qid}",
    }


# ─── CLIENTES ────────────────────────────────────────────────────────────────

@app.get("/api/clients")
async def api_list_clients(q: str = Query("")):
    return db.list_clients(q)


@app.post("/api/clients")
async def api_upsert_client(data: dict):
    client_id = db.save_client(
        nombre=data.get("nombre", "").strip(),
        rfc=data.get("rfc", "").strip(),
        email=data.get("email", "").strip(),
        telefono=data.get("telefono", "").strip(),
        client_id=data.get("id"),
    )
    return {"ok": True, "id": client_id}


@app.delete("/api/clients/{client_id}")
async def api_delete_client(client_id: int):
    db.delete_client(client_id)
    return {"ok": True}


# ─── CATÁLOGO ────────────────────────────────────────────────────────────────

@app.get("/api/catalog")
async def api_get_catalog():
    return catalog_to_dict()


class CatalogPayload(BaseModel):
    """Valida el shape de primer nivel del catálogo. Bloquea typos y tipos
    erróneos; no prescribe el schema interno (que cambia con frecuencia)."""
    model_config = ConfigDict(extra="forbid")

    laminas:            dict | None = None
    leds_canal:         list | None = None
    leds_caja:          dict | None = None
    fuentes:            list | None = None
    pegamentos:         dict | None = None
    precios_base:       dict | None = None
    precios_caja_m2:    dict | None = None
    silvatrim:          list | None = None
    vinilos:            list | None = None
    vinilos_cercha:     list | None = None
    tipos_construccion: dict | None = None
    gruas:              dict | None = None


@app.post("/api/catalog")
async def api_save_catalog(payload: CatalogPayload):
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Catálogo vacío: no se aplicaron cambios")
    # Backup ANTES de aplicar — si algo sale mal hay copia para revertir
    _backup_catalog()
    try:
        catalog_apply(data)
        catalog_save()
    except Exception:
        log.exception("Error al aplicar catálogo")
        raise HTTPException(400, "Catálogo inválido: revisa la estructura")
    log.info("Catálogo actualizado: claves=%s", list(data.keys()))
    return {"ok": True, "claves_actualizadas": list(data.keys())}


# ─── VECTORIZAR IMAGEN ────────────────────────────────────────────────────────

@app.post("/api/vectorize")
async def api_vectorize(
    file:             UploadFile = File(...),
    bg_tol:           int = Query(38, ge=10, le=70),
    filter_speckle:   int = Query(8,  ge=1,  le=30),
    color_precision:  int = Query(3,  ge=1,  le=8),
    layer_difference: int = Query(48, ge=4,  le=64),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Archivo demasiado grande (máximo {MAX_UPLOAD_BYTES // (1024*1024)} MB)")

    try:
        from vectorizer import vectorize as _vec
        svg_text = _vec(
            content,
            bg_tol=bg_tol,
            filter_speckle=filter_speckle,
            color_precision=color_precision,
            layer_difference=layer_difference,
        )
    except ImportError as e:
        raise HTTPException(500, f"Dependencia faltante: {e}. Ejecuta: pip install opencv-python vtracer")
    except Exception as e:
        raise HTTPException(400, f"Error al vectorizar: {e}")

    try:
        svg_data = parse_svg(svg_text.encode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"SVG generado inválido: {e}")

    sid = str(uuid.uuid4())
    with _state_lock:
        _svg_store[sid] = {"bytes": svg_text, "svg_data": svg_data}
        _svg_touch[sid] = time.time()

    paths_info = [
        {
            "id":           p.id,
            "svg_id":       p.svg_id,
            "perimeter_px": round(p.perimeter_px, 2),
            "area_px":      round(p.area_px, 2),
            "is_closed":    p.is_closed,
            "bbox":         p.bbox,
        }
        for p in svg_data.paths
    ]

    return {
        "session_id":           sid,
        "paths":                paths_info,
        "viewbox_w":            svg_data.viewbox_w,
        "viewbox_h":            svg_data.viewbox_h,
        "svg_unit":             svg_data.svg_unit,
        "svg_text":             svg_text,
        "max_letter_height_px": round(svg_data.max_letter_height_px, 2),
        "artboard_w_cm":        round(svg_data.artboard_w_cm, 2),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    reload = os.environ.get("DEV_RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
