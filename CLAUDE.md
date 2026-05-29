# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Cotizador SGI – Letras y Anuncios**: web-based quoting tool for fabricating illuminated 3D channel letters, flat letters, and light boxes. The user uploads an SVG design, enters real-world dimensions, and the app calculates material quantities and costs, then generates PDF business documents.

## Commands

```bash
# Install dependencies (Python 3.10+)
pip install -r requirements.txt

# Run development server (auto-reload) — preferred method
run.bat
# Equivalent:
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Server runs at http://localhost:8080
```

No tests or linting configuration in this project.

## Architecture

### Request flow

1. **Upload SVG** → `POST /api/parse-svg` → `calculator.parse_svg()` extracts paths with perimeter, area, and bounding box in SVG pixels → stored in `_svg_store[session_id]` (in-memory)
2. **Quote** → `POST /api/cotizar/letras|caja|planas` → calls `cotizar_letras()` / `cotizar_caja()` / `cotizar_planas()`, which scale px→cm, select materials from catalog, compute costs using proportional $/cm² → result stored in `_quote_store[quote_id]`
3. **PDF** → `GET /api/pdf/{quote_id}?cliente=X&notas=Y` (cotización), `/api/ot/{quote_id}` (orden de trabajo), `/api/entrega/{quote_id}` (acta de entrega + garantía)

### Module responsibilities

| File | Role |
|------|------|
| `main.py` | FastAPI app, route handlers, in-memory stores (`_svg_store`, `_quote_store`) |
| `calculator.py` | SVG parsing, quoting logic for all three product types, `QuoteResult` dataclass |
| `catalog_data.py` | All pricing data (LAMINAS, LEDS_CANAL, LEDS_CAJA, FUENTES, PEGAMENTOS, PRECIOS_BASE, TIPOS_CONSTRUCCION, GRUAS), auto-selection functions, catalog persistence |
| `pdf_gen.py` | ReportLab PDF generation for all three document types; purely presentational |
| `static/index.html` | Single-file SPA (vanilla JS + inline CSS); no build step |
| `catalog.json` | Runtime price overrides; loaded at startup by `catalog_load()`, updated via `POST /api/catalog` |

### Material cost methodology (critical)

All material costs use **proportional $/cm²**, not whole-sheet rounding:

```python
def precio_cm2(mat: dict) -> float:
    area = mat.get("ancho_cm", 122) * mat.get("alto_cm", 244)
    return mat.get("precio", 0) / area if area > 0 else 0.0

# Face material: bounding box area per letter (h × w of cut rectangle)
area_cara_total = sum((p.bbox["h"] * sf) * (p.bbox["w"] * sf) for p in letras)
c_cara = area_cara_total * precio_cm2(mat_cara)

# Cercha: perimeter × depth
area_cercha_total = perimeter_total * cercha_cm
c_cercha = area_cercha_total * precio_cm2(mat_cercha)
```

`laminas_necesarias()` is still computed for display (how many sheets needed) but cost is NOT `laminas × precio`.

### Fuente (power supply) cost

Proportional to watts consumed, minimum 20% of unit price:
```python
fraccion_fuente = max(0.20, watts / fuente["watts"]) if fuente["watts"] > 0 else 1.0
c_fuente = round(fuente["precio"] * fraccion_fuente, 2)
```

### Pegamento cost

Proportional to linear meters of perimeter:
```python
metros_peg = perimetro_total / 100 * max(1, juntas)   # juntas = seams (cara + fondo)
envases = max(0.15, metros_peg / pegamento["metros_por_envase"])
c_peg = envases * pegamento["precio_aprox"]
```

### Pricing formula (COTIZANDO sheet)

```
precio_letra = altura_cm × precio_cm × multiplicador
precio_total = sum(precio_letra for all letters) × (1 + ajuste_pct/100)
```

`PRECIOS_BASE["precio_cm"]` defaults to 10. Multiplicadores are defined in `PRECIOS_BASE["multiplicadores"]` and keyed by `tipo_multiplicador` (e.g. `"acrilico_con_luz_std"` = 4.5).

### Construction types (TIPOS_CONSTRUCCION)

| ID | Cara | Fondo PVC | LEDs | Multiplicador default |
|----|------|-----------|------|-----------------------|
| `cajon_luz` | acrilico | ✓ | ✓ | `acrilico_con_luz_std` (4.5) |
| `retro_halo` | aluminio | ✗ | ✓ | `aluminio_con_luz` (2.5) |
| `sin_luz` | aluminio | ✓ | ✗ | `aluminio_sin_luz` (2.0) |
| `abierta_luz` | ninguna | ✓ | ✓ | `aluminio_con_luz` (2.5) |

When `tipo_construccion` changes in the UI, `onTipoConstruccionChange()` must sync the `tipo_multiplicador` select to `multiplicador_default`.

### PDF generation (ReportLab)

**Critical rules** to avoid overlapping / "enzimado" cells:
- All table cell text must be wrapped in `Paragraph` objects — plain strings do not word-wrap
- Use `_p(texto, estilo)` helper for all cells
- Column widths must be `PW * fraction` (actual points), never percentage strings like `"15%"`
- All `ParagraphStyle` objects are module-level constants with unique `sgi_*` prefixed names to prevent duplicate registration errors

Three generators:
- `generar_pdf(result, meta)` — customer quote (Cotización)
- `generar_pdf_ot(result, meta)` — internal work order (Orden de Trabajo)
- `generar_pdf_entrega(result, meta)` — delivery receipt + warranty (Acta de Entrega)

### QuoteResult fields (key additions)

Beyond basic cost fields, `QuoteResult` includes:
- `tipo_construccion`, `tipo_multiplicador`, `multiplicador_valor`
- `precio_sin_ajuste` (formula total before % adjustment), `ajuste_pct`
- `precio_venta_costo` (cost floor = total / (1 - margin)), `precio_venta_sugerido` (formula-based)
- `mo_total` (labor), `inst_activa`, `inst_lugar`, `inst_viaticos`, `inst_grua`, `inst_costo_grua`, `inst_extras`, `inst_total`
- `precio_final = precio_venta_sugerido + inst_total`
- `desglose_letras` — per-letter breakdown with `alto_cm`, `ancho_cm`, `area_bbox_cm2`, `cercha_area_cm2`, `costo_cara`, `costo_cercha`, `costo_mat`, `precio_letra`

### Catalog persistence

- `catalog_load()` (called at module import) merges `catalog.json` into globals using `_catalog_merge()` — preserves Python defaults (e.g. `metros_por_envase`) not present in the JSON file
- `catalog_apply()` (called by `POST /api/catalog`) does a full replace (used by the catalog editor UI)
- PEGAMENTOS keys are tuples `(cercha_tipo, cara_tipo)`; serialized to JSON as `"aluminio|acrilico"`

### SVG scale detection priority

1. `altura_letra_cm > 0` → scale from tallest letter's bounding box height
2. Illustrator SVG (has `enable-background` in style) → scale from artboard width in pt
3. Fallback → `real_width_cm / viewbox_w`
