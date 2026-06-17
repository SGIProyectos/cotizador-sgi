# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Cotizador SGI – Letras y Anuncios**: web-based quoting tool for fabricating illuminated 3D channel letters, flat letters, and light boxes. The user uploads an SVG design, enters real-world dimensions, and the app calculates material quantities and costs, then generates PDF business documents.

## Commands

```bash
# Install runtime dependencies (Python 3.10+)
pip install -r requirements.txt

# Install dev dependencies (pytest, ruff, pip-tools, httpx)
pip install -r requirements-dev.txt

# Run development server — preferred method (kills existing :8080, activates .venv if present, auto-opens browser)
run.bat
# Equivalent (no auto-reload):
uvicorn main:app --host 0.0.0.0 --port 8080
# Auto-reload only in dev (controlled by env var, NOT a CLI flag in prod):
#   set DEV_RELOAD=true   then re-run

# Server runs at http://localhost:8080

# Tests + lint (matches what CI runs)
python -m ruff check .
python -m pytest tests/ --cov=calculator --cov=main --cov=db --cov-report=term --cov-fail-under=70

# Run a single test
python -m pytest tests/test_calculator.py::test_<name> -v

# Regenerate requirements.lock from requirements.txt
pip-compile requirements.txt -o requirements.lock
```

Lint config: `pyproject.toml` (ruff, line-length 100, py310 target, rule sets E/W/F/I/B/UP/SIM). Tests live in `tests/` (pytest, 64 tests as of last count). CI: `.github/workflows/test.yml` runs ruff + pytest with coverage gate of 70% on push/PR to `main`.

## Deployment

Deployed to Render.com via `render.yaml` (Python 3.11, `uvicorn main:app --host 0.0.0.0 --port $PORT`). Local development uses Python 3.10+ with a `.venv` virtual environment.

## Architecture

### Request flow

1. **Upload SVG** → `POST /api/parse-svg` → `calculator.parse_svg()` extracts paths with perimeter, area, and bounding box in SVG pixels → stored in `_svg_store[session_id]` (in-memory; SVG is small and re-uploadable so RAM-only is fine)
2. **Quote** → `POST /api/cotizar/letras|caja|planas` → calls `cotizar_letras()` / `cotizar_caja()` / `cotizar_planas()`, which scale px→cm, select materials from catalog, compute costs → result written to SQLite via `db.save_quote()` and cached in `_quote_store[quote_id]`; metadata (cliente, notas, folio) cached at `_quote_store[quote_id + "_meta"]`
3. **PDF / Excel** → `GET /api/pdf/{quote_id}?cliente=X&notas=Y` (cotización), `/api/ot/{quote_id}` (orden de trabajo), `/api/entrega/{quote_id}` (acta de entrega + garantía), `/api/excel/{quote_id}` (XLSX export) — all written to `tmp/` directory
4. **History** → `GET /api/quotes` (list with filters), `GET /api/quotes/{id}/open` (re-open: rebuilds session + QuoteResult from DB), `DELETE /api/quotes/{id}`
5. **Clients** → `GET /api/clients?q=` (search), `POST /api/clients` (upsert), `DELETE /api/clients/{id}`
6. **Catalog** → `GET /api/catalog` returns current in-memory catalog; `POST /api/catalog` calls `catalog_apply()` + `catalog_save()` to persist to `catalog.json`
7. **Raster → SVG** → `POST /api/vectorize` (uploads JPG/PNG, runs `vectorizer.vectorize()` — flood-fill background removal + vtracer → produces a synthetic SVG that is then re-fed through `parse_svg`, populating `_svg_store` as if the user had uploaded it directly). Only the raster→SVG `vectorize()` survives — the abandoned `vectorize_with_ai` experiment was removed (see §7).

### Module responsibilities

| File | Role |
|------|------|
| `main.py` | FastAPI app, route handlers, in-memory caches (`_svg_store`, `_quote_store`), persistence helpers |
| `calculator.py` | SVG parsing, quoting logic for all three product types, `QuoteResult` dataclass |
| `db.py` | SQLite persistence: `init_db()`, `save_quote()`, `list_quotes()`, `get_quote()`, `next_folio()` (SGI-YYYY-NNNN), client CRUD |
| `catalog_data.py` | All pricing data (LAMINAS, LEDS_CANAL, LEDS_CAJA, FUENTES, PEGAMENTOS, PRECIOS_BASE, TIPOS_CONSTRUCCION, GRUAS), auto-selection functions, catalog persistence |
| `pdf_gen.py` | ReportLab PDF generation for all three document types; purely presentational |
| `excel_gen.py` | openpyxl XLSX export of a `QuoteResult` (Resumen + Letras + Desglose sheets) |
| `vectorizer.py` | Raster→SVG pipeline: OpenCV flood-fill background removal + vtracer Bézier tracing. Only `vectorize()` is real; do NOT add LLM-based variants (see §7). |
| `static/index.html` | Single-file SPA (vanilla JS + inline CSS); no build step |
| `catalog.json` | Runtime price overrides; loaded at startup by `catalog_load()`, updated via `POST /api/catalog` |
| `cotizador.db` | SQLite database file (quotes, folio_seq, clients tables); auto-created by `db.init_db()` on startup |

### Material cost methodology (critical)

**Channel letters (`cotizar_letras`) and flat letters (`cotizar_planas`)** use **proportional $/cm²** — cost is area used × price per cm², not sheets × price. **Light boxes (`cotizar_caja`)** use **whole-sheet pricing** for structure (aluminio cal 18) and fondo (PVC) — `lam_struct * mat["precio"]` — because box construction always consumes full sheets. The face material in `cotizar_caja` uses flat $/m² from `PRECIOS_CAJA_M2`.

All channel letter material costs use **proportional $/cm²**, not whole-sheet rounding:

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

IVA is always 16% (`subtotal * 0.16`), hardcoded in `calculator.py`.

### Construction types (TIPOS_CONSTRUCCION)

| ID | Cara | Fondo PVC | LEDs | Distanciadores | Multiplicador default |
|----|------|-----------|------|----------------|-----------------------|
| `cajon_luz` | acrilico | ✓ | ✓ | ✗ | `acrilico_con_luz_std` (4.5) |
| `retro_halo` | aluminio | ✗ | ✓ | ✓ | `aluminio_con_luz` (2.5) |
| `sin_luz` | aluminio | ✓ | ✗ | ✗ | `aluminio_sin_luz` (2.0) |
| `abierta_luz` | ninguna | ✓ | ✓ | ✗ | `aluminio_con_luz` (2.5) |

When `tipo_construccion` changes in the UI, `onTipoConstruccionChange()` must sync the `tipo_multiplicador` select to `multiplicador_default`.

`DISTANCIADORES` cost is added only when `config["distanciadores"]` is True (i.e., `retro_halo`): `n_letras × DISTANCIADORES["precio"]`.

**Silvatrim** is added to every channel letter quote: `silvatrim_recomendado(cercha_cm)` auto-selects the profile; cost = `(perimeter_total / 100) m × sv["precio_ml"]`. The `desglose_letras[*]["cercha_total_cm"]` = perimeter × 1.10 (10% waste for cuts/bends).

### Light box (`cotizar_caja`) specifics

**Pricing formula**: Unlike channel letters, `cotizar_caja` does NOT use the height×price×multiplier formula. `precio_venta_sugerido = total / (1 - margen_ganancia)` directly. `precio_sin_ajuste`, `ajuste_pct`, and `desglose_letras` are empty/zero in caja results.

**Caja outline detection** — `_find_caja_outline()` identifies the box outline as the path that looks rectangular: `perimeter / (2*(w+h)) ≤ 2.5` (i.e. not a complex shape), picking the one with the largest bounding-box area among candidates. Returns `None` if no path passes the ratio check; caller then uses artboard/viewbox dimensions as the caja bounds. This is critical because interior design elements can have larger fill area than the outline, which would break the old "largest area = caja" assumption.

**Caja dimensions**: `caja_w_cm = real_width_cm` is always the authoritative width. `caja_h_cm` is derived proportionally from the caja outline path's bbox aspect ratio (`real_width_cm × bbox_h / bbox_w`). When no outline is detected, `viewbox_h × scale_factor` is used.

**`design_paths`** = all paths except the identified caja outline. Used to compute vinil dimensions.

**Face types** (`tipo_cara`) and their pricing source (`PRECIOS_CAJA_M2`):
- `lona`, `acrilico` — flat $/m² × caja area
- `acrilico_2vistas` — separate $/m² entry for double-face boxes
- `vinil_corte` — base material (lona/acrilico, set by `base_cara_vinil`) for full area + vinil $/m² for design paths only (NOT the full caja area). Design paths are grouped into rows by `_group_design_paths_by_row()`, each row gets independent ancho_cm × alto_cm from its combined bbox, clamped to the caja outline bounds.

**`vistas` effect on fondo**: `vistas=1` → `alucobon_3mm` (rigid); `vistas=2` → `pvc_6mm` (exterior) / `pvc_3mm` (interior).

**LED types for cajas** (`tipo_led` field on each LED entry):
| tipo_led | Quantity formula |
|----------|-----------------|
| `backlite` | `filas = ceil(profundidad_cm / 18)` — one row of strips per 18 cm depth |
| `edgelite` | `tiras = ceil(perimetro / led["largo_cm"])` — bars along perimeter |
| `perimetral` | `tiras = ceil(perimetro / led["espaciado_cm"])` — modules every N cm |

`LEDS_CAJA` is split into `"interior"` and `"exterior"` keys. `recomendar_led_caja()` auto-selects based on dimensions, double-face, uso, and profundidad.

### Installation and labor (`_InstMixin`)

All three request models (`LetrasRequest`, `CajaRequest`, `PlanasRequest`) inherit `_InstMixin`, which adds:
- `mo_horas` / `mo_tarifa` → `result.mo_total = mo_horas × mo_tarifa`
- `inst_activa` — if True, populates installation fields
- `inst_lugar`, `inst_viaticos`, `inst_grua_id`, `inst_dias_grua`, `inst_extras`

`_apply_instalacion(result, req)` in `main.py` runs after each `cotizar_*()` call. It looks up `GRUAS[inst_grua_id]["precio_dia"]`, sets `result.inst_total = viaticos + costo_grua + extras`, and `result.precio_final = precio_venta_sugerido + inst_total`.

### PDF generation (ReportLab)

**Critical rules** to avoid overlapping / "enzimado" cells:
- All table cell text must be wrapped in `Paragraph` objects — plain strings do not word-wrap
- Use `_p(texto, estilo)` helper for all cells
- Column widths must be `PW * fraction` (actual points), never percentage strings like `"15%"`
- All `ParagraphStyle` objects are module-level constants with unique `sgi_*` prefixed names to prevent duplicate registration errors

Three generators:
- `generar_pdf(result, meta)` — customer quote (Cotización)
- `generar_pdf_ot(result, meta)` — internal work order (Orden de Trabajo, single-page portrait)
- `generar_pdf_entrega(result, meta)` — delivery receipt + warranty (Acta de Entrega)

### QuoteResult fields (key additions)

Beyond basic cost fields, `QuoteResult` includes:
- `tipo_construccion`, `tipo_multiplicador`, `multiplicador_valor`
- `precio_sin_ajuste` (formula total before % adjustment), `ajuste_pct`
- `precio_venta_costo` (cost floor = total / (1 - margin)), `precio_venta_sugerido` (formula-based)
- `mo_total` (labor), `inst_activa`, `inst_lugar`, `inst_viaticos`, `inst_grua`, `inst_costo_grua`, `inst_extras`, `inst_total`
- `precio_final = precio_venta_sugerido + inst_total`
- `desglose_letras` — per-letter breakdown with `alto_cm`, `ancho_cm`, `area_bbox_cm2`, `cercha_area_cm2`, `costo_cara`, `costo_cercha`, `costo_mat`, `precio_letra`
- `silvatrim`, `metros_silvatrim`, `costo_silvatrim` — Silvatrim profile selection and cost (channel letters only)
- `vinil_cercha`, `metros_vinil_cercha`, `costo_vinil_cercha` — optional vinyl wrap on cercha (set by `vinil_cercha_id` in `LetrasRequest`)

### Catalog persistence

- `catalog_load()` (called at module import) merges `catalog.json` into globals using `_catalog_merge()` — preserves Python defaults (e.g. `metros_por_envase`) not present in the JSON file
- `catalog_apply()` (called by `POST /api/catalog`) does a full replace (used by the catalog editor UI)
- PEGAMENTOS keys are tuples `(cercha_tipo, cara_tipo)`; serialized to JSON as `"aluminio|acrilico"`
- `NEON_FLEX` is defined in `catalog_data.py` (neon flex strips with prices and colors) but is **not yet used in any quoting logic** — it exists for future expansion

### SVG scale detection priority

1. `altura_letra_cm > 0` → scale from tallest letter's bounding box height
2. Illustrator SVG (has `enable-background` in style) → scale from artboard width in pt
3. Fallback → `real_width_cm / viewbox_w`

---

## Roadmap — pending features (as of 2026-06-01)

These are agreed improvements not yet implemented, ordered by priority.

Already shipped: SQLite persistence, quote history/list, re-open quote, client catalog, sequential folio `SGI-YYYY-NNNN`, **Excel export** (`/api/excel/{quote_id}`), **automated catalog + DB backups** (startup + every 24h + on every `POST /api/catalog`, retention 30 days), SQLite indexes on `quotes(fecha, cliente, folio, tipo)` and `clients(nombre)`.

### Important — daily operations
1. **SVG preview in UI** — display the uploaded SVG with paths color-coded (face = orange, vinyl = blue, caja outline = gray) so the user can verify detection before quoting.

### Useful — productivity
2. **Multi-SVG per quote** — support quoting multiple signs in one project (different SVGs, each with its own dimensions).
3. **Company info in PDFs** — address, phone, RFC, logo image embedded in all PDF types. Currently PDFs have no company branding.

### Lower priority
4. Authentication (multi-user over network).
5. Email quote to client directly from the app.
6. Integration API for ERP/invoicing systems.

---

# INFORME DE ESTADO Y ROADMAP (actualizado 2026-06-06)

> Este informe va dirigido a cualquier agente o desarrollador que tome el proyecto. Lee esta sección completa antes de proponer o hacer cambios. El contexto comercial cambia lo que es apropiado hacer.

## 1. Contexto comercial

### Intención del propietario
El propietario (SGI, rotulista en México) quiere convertir este cotizador en **software comercial vendible**, no solo uso interno. Objetivo: SaaS en nicho de fabricantes de anuncios y rotulistas en México / Latam.

### Modelo de negocio tentativo
- SaaS por suscripción mensual: ~$499 MXN básico / $999 MXN pro / $2,499 MXN empresa
- Alternativa B: licencia única instalada en taller del cliente ($5,000-15,000 MXN una vez)
- Validación de mercado pendiente (landing + ads de prueba antes de invertir más desarrollo)

### Fase actual
**MVP funcional para uso interno.** No es producto comercial todavía. Falta toda la capa de SaaS (auth, multi-tenant, pagos), seguridad endurecida, tests, y compliance legal.

---

## 2. Cambios recientes (2026-06-08) — Fase 1 de endurecimiento completada

### Claude Vision: revertido
Se quitó completamente todo el código de `vectorize_with_ai`. Decisión confirmada: los LLMs no pueden generar coordenadas SVG limpias, es limitación arquitectónica. No reintentar; usar API especializada (vectorizer.ai) si en el futuro se necesita.

### Fase 1 de endurecimiento (puntos 1-12 de la sección 5) — IMPLEMENTADO
- **Seguridad PDF**: `_safe_part()` sanitiza `cliente`/`folio` antes de filenames y headers (cierra C3, C4)
- **Upload limit**: 10 MB por upload, HTTP 413 si se excede (cierra C6)
- **`reload=True` eliminado**: ahora controlado por env var `DEV_RELOAD` (cierra C5)
- **Catálogo validado**: `CatalogPayload` Pydantic con `extra="forbid"` (cierra C8)
- **Backup diario**: lifespan corre `_backup_db()` al inicio + cada 24h → `backups/cotizador_YYYYMMDD_HHMMSS.db`, retención 30 días (cierra C10)
- **Logging estructurado**: `RotatingFileHandler` 5MB × 5 backups en `server.log` (cierra G5)
- **TTL caches**: `_svg_touch`/`_quote_touch` con purga horaria; SVGs expiran 24h, cotizaciones 7d (cierra G2)
- **Healthcheck**: `GET /health` verifica DB con `db.ping()`, devuelve 503 si falla (cierra G8)
- **Tests con pytest**: 62 tests, 90% cobertura en `calculator.py` (cierra G1)
- **CI**: `.github/workflows/test.yml` corre pytest en cada push/PR
- **Dockerfile + lockfile**: `Dockerfile` con python:3.11-slim + `requirements.lock` (181 deps pinneadas) (cierra D4, D5)
- **Sentry**: integración condicional al env var `SENTRY_DSN` (no falla si la lib no está instalada)

### Pendiente de Fase 1
- **#13 — Render con disco persistente**: NO se puede hacer desde código. Requiere configurar en el dashboard de Render.com (plan pago o disk attachment).
- Resolver advertencias menores del listado D (formatter, type checker)

---

## 3. Auditoría de ingeniería de software

Análisis honesto del estado actual. Marcado por criticidad.

### Lo que SÍ está bien
- SQL parametrizado en `db.py` (sin SQL injection)
- Separación modular: `calculator.py` (negocio), `db.py` (persistencia), `pdf_gen.py` (presentación), `catalog_data.py` (datos)
- Pydantic models para input de cotización
- Folio atómico con `INSERT ... ON CONFLICT DO UPDATE`
- FastAPI (estado del arte para APIs Python en 2026)
- CLAUDE.md bien documentado

### Crítico — bloqueadores legales y de seguridad (no comercializable así)
| # | Problema | Riesgo | Estado |
|---|---|---|---|
| C1 | Sin autenticación. Cualquiera con URL ve todo. | LFPDPPP / GDPR / demandas | Fase 2 |
| C2 | Sin multi-usuario. Catálogo y datos globales. | Multi-tenant imposible | Fase 2 |
| C3 | Path traversal en `_write_tmp(name)`. | Escritura arbitraria de archivos | ✅ Cerrado (`_safe_part`) |
| C4 | HTTP Response Splitting en `Content-Disposition`. | Inyección de headers | ✅ Cerrado (`_safe_part`) |
| C5 | `uvicorn.run(... reload=True)` en producción. | — | ✅ Cerrado (env `DEV_RELOAD`) |
| C6 | Sin límite de tamaño en uploads. | DoS trivial | ✅ Cerrado (10 MB) |
| C7 | Endpoint `/api/vectorize-ai` puede vaciar Anthropic. | Robo financiero | ✅ Cerrado (endpoint eliminado) |
| C8 | `POST /api/catalog` acepta `dict` libre. | Corrupción de datos | ✅ Cerrado (`CatalogPayload`) |
| C9 | Sin HTTPS, CORS, CSP. | XSS / MITM | Fase 2 (depende del despliegue) |
| C10 | Sin backup automatizado de `cotizador.db`. | Pérdida total | ✅ Cerrado (`_backup_db` diario) |
| C11 | **Render.com filesystem efímero**: redeploy borra DB. | Pérdida total | Pendiente: requiere config externa |

### Grave — bloqueadores de calidad operativa
| # | Problema | Estado |
|---|---|---|
| G1 | Cero tests. | ✅ Cerrado (62 tests, 90% cobertura en `calculator.py`) |
| G2 | Caches sin TTL. | ✅ Cerrado (24h SVG / 7d quote, purga horaria) |
| G3 | Estado global no thread-safe. | ✅ Cerrado (`threading.RLock` en `_state_lock` protege caches en `main.py`) |
| G4 | `except Exception` genéricos. | Parcial — `_safe_part` y validación catalog ya loguean. Resto en Fase 2. |
| G5 | Sin logging estructurado. | ✅ Cerrado (`RotatingFileHandler` + `logger 'cotizador'`) |
| G6 | Sin Alembic. | Pendiente (cuando migremos a PostgreSQL en Fase 2) |
| G7 | Sin índices en `quotes`. | ✅ Cerrado (`idx_quotes_fecha`, `_cliente`, `_folio`, `_tipo` + `idx_clients_nombre` en `db.init_db()`) |
| G8 | Sin healthcheck. | ✅ Cerrado (`GET /health`) |

### Deuda técnica — afecta velocidad de desarrollo
| # | Problema | Estado |
|---|---|---|
| D1 | `static/index.html` ~5,200 líneas. | Pendiente Fase 2 (Vue 3 + Vite) |
| D2 | Lógica de negocio mezclada en endpoints. | Pendiente Fase 2 |
| D3 | `_result_to_dict` mapeo manual. | Pendiente Fase 2 |
| D4 | Sin `requirements.lock`. | ✅ Cerrado (`requirements.lock` con pip-tools) |
| D5 | Sin Dockerfile. | ✅ Cerrado |
| D6 | Sin CI/CD. | ✅ Cerrado (`.github/workflows/test.yml`) |
| D7 | Sin formatter/type checker. | ✅ Cerrado — ruff (lint + format) y mypy (modo gradual) configurados en `pyproject.toml` |

### Falta para SaaS comercial
- Sistema de pagos (Stripe / MercadoPago)
- Onboarding de usuarios nuevos
- Panel admin para soporte
- Términos de servicio + aviso de privacidad (LFPDPPP México)
- Auditoría (quién hizo qué)
- Monitoreo (Sentry, Prometheus)
- Documentación al usuario final

---

## 4. Stack tecnológico: análisis y recomendaciones

| Capa | Tienes | Veredicto | Acción |
|---|---|---|---|
| Backend | Python + FastAPI | Estado del arte | NO cambiar |
| DB | SQLite | OK para MVP, no para SaaS | Migrar a **PostgreSQL** (Supabase/Neon/Railway) antes de Fase 2 |
| ORM | sqlite3 raw | Funcional | Migrar a **SQLAlchemy 2.0 async + Alembic** al cambiar DB |
| Frontend | HTML monolítico vanilla JS | **Deuda técnica grave** | Reconvertir a **Vue 3 + Vite + TypeScript** antes de Fase 2 |
| Estado frontend | Variables globales JS | Inmantenible | Pinia (cuando migre a Vue) |
| PDFs | ReportLab | Funcional pero verboso | Mantener; si se quiere facilitar diseño, **WeasyPrint** |
| SVG parsing | svgpathtools + svglib | OK | Mantener |
| Vectorización raster | opencv + vtracer | Bien para imágenes simples | Mantener. Quitar el experimento Claude Vision. |
| Vectorización compleja (futuro) | — | — | **Vectorizer.ai API** como feature premium |
| IA / LLM | Claude API (intento fallido) | No aplica a este problema | **Quitar** |
| Testing | Nada | Inaceptable | **pytest + pytest-asyncio + httpx + playwright** |
| Deployment | Render.com básico | OK para empezar | Añadir **Docker** + `requirements.lock` con `uv` |
| Errores en prod | Nada | Insuficiente | **Sentry** ($26 USD/mes) |
| Auth (futuro) | — | — | **fastapi-users** + JWT, o **Authlib** + OAuth |
| Pagos (futuro) | — | — | **Stripe** (internacional) o **MercadoPago** (México) |

---

## 5. Roadmap de comercialización

### Fase 1 — Endurecer para uso interno seguro (1-2 semanas)
**Objetivo:** que el propietario y su equipo lo usen sin sorpresas. Sin esto, no vale la pena ningún siguiente paso.

1. **Quitar código de Claude Vision** (admitir que no sirve)
2. Quitar `reload=True` de producción
3. Sanitizar nombres de archivo PDF (path traversal + response splitting): aplicar `re.sub(r'[^\w\s-]', '', x)` y trim de longitud al `cliente`/`folio` antes de usar en filenames y headers
4. Límite de tamaño de upload (10 MB): middleware FastAPI
5. Logging estructurado con `logging` stdlib + rotación de archivo (`RotatingFileHandler`)
6. Healthcheck `GET /health` que verifique DB
7. Backup automatizado de `cotizador.db` (script + cron diario a carpeta `backups/` con timestamp; rotación 30 días)
8. TTL en `_svg_store` y `_quote_store` (descartar entradas con >24h sin acceso)
9. Validación de schema Pydantic en `POST /api/catalog`
10. Tests con pytest:
    - `calculator.py`: 80% cobertura mínimo (los cálculos NO pueden fallar)
    - `db.py`: 70%
    - `main.py` (endpoints): smoke tests del flujo principal
11. **CI con GitHub Actions** (correr tests en cada push)
12. **Dockerfile** + `requirements.lock` con `uv`
13. **Sentry** para errores en producción
14. Documentar configuración de Render.com con disco persistente (para que SQLite no se borre en redeploy)

### Fase 2 — Mínimo para vender SaaS (3-4 semanas)
**Objetivo:** que un cliente externo pueda registrarse, pagar y usar.

15. Migrar SQLite → PostgreSQL con SQLAlchemy 2.0 async + Alembic
16. Reconvertir frontend a Vue 3 + Vite + TypeScript + Pinia
17. Sistema de autenticación con `fastapi-users` (registro, login, recuperación de contraseña, verificación de email)
18. Multi-tenancy: añadir `tenant_id` a `quotes`, `clients`, catálogo por tenant (separación lógica)
19. Pasarela de pago: **Stripe** o **MercadoPago** (cuál depende de mercado objetivo)
20. Rate limiting (`slowapi`)
21. Onboarding wizard al primer login
22. Términos de servicio + aviso de privacidad (LFPDPPP)
23. Landing page de venta

### Fase 3 — Producto comercial real (2-3 meses)
**Objetivo:** SaaS verdadero con clientes pagando.

24. Panel de admin para soporte
25. Suspensión automática por falta de pago
26. Tests E2E con Playwright
27. Monitoreo (Sentry para errores, Prometheus + Grafana para métricas)
28. Logs centralizados (BetterStack / Datadog)
29. Documentación de API pulida (OpenAPI ya viene con FastAPI)
30. Documentación al usuario final (in-app tutorial, videos)
31. Soporte por email + WhatsApp Business
32. SLA mínimo definido

---

## 6. Decisiones técnicas tomadas (no revisar sin razón)

| # | Decisión | Por qué |
|---|---|---|
| 1 | Mantener FastAPI | Es lo mejor en Python para 2026 |
| 2 | Migrar a PostgreSQL en Fase 2 | SQLite no escala para SaaS multi-tenant |
| 3 | Frontend Vue 3 + Vite + TypeScript | Curva más suave que React, más maduro que Svelte, apropiado para UIs complejas (modales SVG, previews) |
| 4 | Mantener ReportLab para PDFs | Funciona; reescribir es trabajo sin ROI inmediato |
| 5 | Quitar vectorización con Claude Vision | Demostrado que LLMs no pueden generar SVG limpio desde imagen |
| 6 | NO usar LLM para generación de coordenadas SVG | Limitación arquitectónica, no de prompt. No reintentar. |
| 7 | Vectorizer.ai como feature premium en futuro | Es la tecnología correcta para image→SVG complejo |
| 8 | Docker obligatorio antes de comercializar | Reproducibilidad del entorno |
| 9 | Tests con pytest, cobertura mínima en calculator.py: 80% | Los cálculos de precio son críticos para el negocio |
| 10 | Validar mercado antes de invertir en Fase 2 | Camino A del análisis: landing + ads de prueba antes de construir SaaS |

---

## 7. Aprendizajes y qué NO hacer

1. **No intentes generar SVG con LLMs** (Claude, GPT). Es una limitación fundamental, no se resuelve con mejor prompt ni con thinking más alto. Ya se gastaron ~$0.50 USD demostrándolo. Si se necesita vectorización avanzada, usar API especializada (vectorizer.ai, recraft.ai).
2. **No reescribas el backend.** FastAPI es lo correcto.
3. **No persigas features visibles** (botones nuevos, IA, etc.) antes de endurecer las bases. Es lo que pasó las primeras 3 días — error de priorización confirmado.
4. **No despliegues a Render.com plan free** sin disco persistente. El filesystem es efímero y SQLite se borra en cada redeploy.
5. **No actives `reload=True` en producción.**
6. **No uses `except Exception`** sin loggear el traceback completo.
7. **No agregues dependencias** sin actualizar `requirements.lock` (cuando exista) y sin revisar licencia.
8. **No expongas el endpoint `/api/vectorize-ai`** públicamente sin auth + rate limiting estricto, o cualquiera puede vaciar la cuenta Anthropic. (Esto es razón adicional para quitarlo).

---

## 8. Estado actual del repositorio (snapshot al 2026-06-16)

Fase 1 de endurecimiento cerrada (commits `18155a3`, `7fd86c2`, `d9bf8a5`, `603f068`, `ed59cad`, `da8776e`, `e4cc9a1`, `e4e1d76`). Lo que sigue documentado como pendiente arriba ya **NO** está pendiente: Dockerfile, `requirements.lock`, CI, ruff, mypy, índices SQLite, backup automático, thread-safety, logging exhaustivo, Excel export, vectorización Claude removida — todo committed.

**Archivos siempre untracked (locales, NO commitear):**
- `cotizador.db`, `server.log`, `server_err.log`, `tmp_check.py`
- `.env`, `materiales.xlsx`
- `EJEMPLOS/` (SVGs y PDFs de prueba que usa el propietario)

El `.gitignore` ya cubre estos casos — si aparece algo nuevo en `git status` que parezca personal/temporal, agrégalo al `.gitignore` antes de commitear.

**Próximos pasos sugeridos al retomar:**
1. Render con disco persistente (#13 / C11 — único pendiente de Fase 1, requiere config externa al repo).
2. Empezar Fase 2 por el punto que el propietario priorice (auth, multi-tenant, migración a Postgres, o reescritura del frontend a Vue). Validar mercado **antes** de invertir en Fase 2 (decisión técnica #10).

---

## 9. Contacto y contexto del propietario

- **Email:** elmuroparral@gmail.com
- **Negocio:** SGI — rotulación / fabricación de letras y anuncios
- **Ubicación:** México
- **Conocimiento técnico:** No es desarrollador. Sabe el dominio del negocio (rotulación, materiales, precios) a profundidad. Trabaja con asistente IA (Claude Code) para implementación.
- **Tiempo invertido a la fecha:** ~3 días de iteración con Claude Code
- **Inversión a la fecha:** $5 USD en créditos Anthropic + tiempo del propietario
- **Restricción de presupuesto:** moderado. Decisiones técnicas deben justificar costo.
- **Estilo de colaboración preferido:** plan ANTES de tocar código. El propietario aprueba o corrige antes de cualquier cambio.

---

> **Para el agente que retome:** lee primero la sección 1 (contexto comercial) y la sección 7 (qué NO hacer). Luego la auditoría (sección 3). El roadmap (sección 5) está priorizado. No hagas suposiciones — si algo no está claro, pregunta al propietario antes de actuar.
