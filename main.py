import json
import uuid
import io
import os
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

from calculator import parse_svg, cotizar_letras, cotizar_caja, cotizar_planas, QuoteResult
from pdf_gen import generar_pdf, generar_pdf_ot, generar_pdf_entrega
from catalog_data import (
    LAMINAS, LEDS_CANAL, LEDS_CAJA, FUENTES, PEGAMENTOS,
    catalog_to_dict, catalog_save, catalog_apply, GRUAS,
)

app = FastAPI(title="Cotizador SGI - Letras y Anuncios")

BASE = Path(__file__).parent
STATIC = BASE / "static"
STATIC.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# Almacén en memoria de SVGs parseados (por sesión simple)
_svg_store: dict[str, dict] = {}
_quote_store: dict[str, QuoteResult] = {}


# ─── HTML PRINCIPAL ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


# ─── PARSEAR SVG ─────────────────────────────────────────────────────────────

@app.post("/api/parse-svg")
async def api_parse_svg(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")

    try:
        svg_data = parse_svg(content)
    except Exception as e:
        raise HTTPException(400, f"Error al parsear SVG: {e}")

    sid = str(uuid.uuid4())
    _svg_store[sid] = {
        "bytes": content.decode("utf-8", errors="replace"),
        "svg_data": svg_data,
    }

    paths_info = [
        {
            "id": p.id,
            "perimeter_px": round(p.perimeter_px, 2),
            "area_px": round(p.area_px, 2),
            "is_closed": p.is_closed,
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
        "svg_text": _svg_store[sid]["bytes"],
        "max_letter_height_px": round(svg_data.max_letter_height_px, 2),
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
    cliente: str = ""
    notas: str = ""

class CajaRequest(_InstMixin):
    session_id: str
    real_width_cm: float
    profundidad_cm: float
    tipo_cara: str = "lona"
    base_cara_vinil: str = "lona"
    led_id: str = "auto"
    uso: str = "exterior"
    vistas: int = 1
    margen_ganancia: float = 0.35
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


# ─── COTIZAR LETRAS 3D ───────────────────────────────────────────────────────

@app.post("/api/cotizar/letras")
async def api_cotizar_letras(req: LetrasRequest):
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
        )
    except Exception as e:
        raise HTTPException(500, f"Error en cálculo: {e}")

    _apply_instalacion(result, req)
    qid = str(uuid.uuid4())
    _quote_store[qid] = result
    _quote_store[qid + "_meta"] = {
        "cliente": req.cliente,
        "notas": req.notas,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "folio": qid[:8].upper(),
        "tipo": "letras_3d",
    }

    return _result_to_dict(result, qid)


# ─── COTIZAR CAJA DE LUZ ─────────────────────────────────────────────────────

@app.post("/api/cotizar/caja")
async def api_cotizar_caja(req: CajaRequest):
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
            led_id=req.led_id,
            uso=req.uso,
            vistas=req.vistas,
            margen_ganancia=req.margen_ganancia,
        )
    except Exception as e:
        raise HTTPException(500, f"Error en cálculo: {e}")

    _apply_instalacion(result, req)
    qid = str(uuid.uuid4())
    _quote_store[qid] = result
    _quote_store[qid + "_meta"] = {
        "cliente": req.cliente,
        "notas": req.notas,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "folio": qid[:8].upper(),
        "tipo": "caja_luz",
    }

    return _result_to_dict(result, qid)


# ─── COTIZAR LETRAS PLANAS ───────────────────────────────────────────────────

@app.post("/api/cotizar/planas")
async def api_cotizar_planas(req: PlanasRequest):
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
    qid = str(uuid.uuid4())
    _quote_store[qid] = result
    _quote_store[qid + "_meta"] = {
        "cliente": req.cliente,
        "notas": req.notas,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "folio": qid[:8].upper(),
        "tipo": "letras_planas",
    }
    return _result_to_dict(result, qid)


# ─── GENERAR PDF ─────────────────────────────────────────────────────────────

@app.get("/api/ot/{quote_id}")
async def api_ot(quote_id: str, cliente: str = "", notas: str = ""):
    result = _quote_store.get(quote_id)
    meta   = dict(_quote_store.get(quote_id + "_meta", {}))
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas
    pdf_bytes = generar_pdf_ot(result, meta)
    filename  = f"OT_{meta.get('folio','SGI')}_{meta.get('cliente','cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename), filename=filename, media_type="application/pdf")


@app.get("/api/entrega/{quote_id}")
async def api_entrega(quote_id: str, cliente: str = "", notas: str = ""):
    result = _quote_store.get(quote_id)
    meta   = dict(_quote_store.get(quote_id + "_meta", {}))
    if not result:
        raise HTTPException(404, "Cotización no encontrada")
    if cliente: meta["cliente"] = cliente
    if notas:   meta["notas"]   = notas
    pdf_bytes = generar_pdf_entrega(result, meta)
    filename  = f"Entrega_{meta.get('folio','SGI')}_{meta.get('cliente','cliente')}.pdf"
    return FileResponse(path=_write_tmp(pdf_bytes, filename), filename=filename, media_type="application/pdf")


@app.get("/api/pdf/{quote_id}")
async def api_pdf(quote_id: str, cliente: str = "", notas: str = ""):
    result = _quote_store.get(quote_id)
    meta   = dict(_quote_store.get(quote_id + "_meta", {}))
    if not result:
        raise HTTPException(404, "Cotización no encontrada")

    if cliente:
        meta["cliente"] = cliente
    if notas:
        meta["notas"] = notas

    pdf_bytes = generar_pdf(result, meta)
    nombre_cliente = meta.get("cliente") or "cliente"
    filename  = f"Cotizacion_{meta.get('folio','SGI')}_{nombre_cliente}.pdf"

    return FileResponse(
        path=_write_tmp(pdf_bytes, filename),
        filename=filename,
        media_type="application/pdf",
    )


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _write_tmp(data: bytes, name: str) -> str:
    p = BASE / "tmp"
    p.mkdir(exist_ok=True)
    out = p / name
    out.write_bytes(data)
    return str(out)


def _result_to_dict(r: QuoteResult, qid: str) -> dict:
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
        },
        "materiales": {
            "cara": {
                "nombre": r.material_cara.get("nombre"),
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
        "pdf_url": f"/api/pdf/{qid}",
    }


# ─── CATÁLOGO ────────────────────────────────────────────────────────────────

@app.get("/api/catalog")
async def api_get_catalog():
    return catalog_to_dict()


@app.post("/api/catalog")
async def api_save_catalog(data: dict):
    catalog_apply(data)
    catalog_save()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
