# CLAUDE.md

Guía para Claude Code (claude.ai/code) al trabajar en este repo.

## Overview

**Cotizador SGI – Letras y Anuncios**: herramienta web para cotizar fabricación de letras de canal 3D, letras planas y cajas de luz. Sube un SVG, ingresa medidas reales, calcula materiales y costos, genera PDFs (cotización / OT / acta de entrega / plano).

## Commands

```bash
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # tests + lint

# Dev server (preferido — mata :8080 previo, activa .venv, abre browser)
run.bat
# Equivalente sin reload:
uvicorn main:app --host 0.0.0.0 --port 8080
# Auto-reload: set DEV_RELOAD=true antes de correr (no es CLI flag en prod)

# Tests + lint (lo que corre CI)
python -m ruff check .
python -m pytest tests/ --cov=calculator --cov=main --cov=db --cov-fail-under=70

# Test individual
python -m pytest tests/test_calculator.py::test_<name> -v

# Regenerar lockfile
pip-compile requirements.txt -o requirements.lock
```

Lint config en `pyproject.toml` (ruff, line-length 100, py310, rulesets E/W/F/I/B/UP/SIM). CI en `.github/workflows/test.yml`. Para verificar PDFs visualmente: renderiza páginas con PyMuPDF (`tmp/test_plano.py` es el harness).

## Deployment

Render.com (`render.yaml`, Python 3.11, plan starter + disco persistente en `/var/data`).

Env vars:
- **`COTIZADOR_DATA_DIR`** — carpeta para datos mutables (`cotizador.db`, `catalog.json`, `backups/`). Leído por `db.py`, `catalog_data.py` y `main.py` al import. Vacío = todo junto al código (uso taller local). En Render apunta a `/var/data`.
- **`ACCESS_PASSWORD`** (+ opcional `ACCESS_USER`, default `sgi`) — habilita HTTP Basic Auth sobre TODO el sitio (incluye `/static` y `/docs`). Solo `/health` queda abierto para el monitor del host. Vacío = sin auth. Comparación timing-safe (`secrets.compare_digest`). Stopgap pre-Fase 2 hasta multi-user real.

## Architecture

### Request flow

1. **Upload SVG** → `POST /api/parse-svg` → `calculator.parse_svg()` extrae *piezas* (`<path>`, `<rect>`, `<circle>`, `<ellipse>`, `<polygon>`, `<polyline>`, `<line>`) con perímetro/área/bbox en px. Guardado en `_svg_store[session_id]` (RAM); el texto SVG se persiste a `quotes.svg_text` al cotizar.
2. **Quote** → `POST /api/cotizar/letras|caja|planas` → `cotizar_letras()` / `cotizar_caja()` / `cotizar_planas()` → escala px→cm, elige materiales, calcula. Guardado en SQLite (`db.save_quote()`) + cache (`_quote_store[quote_id]`); meta (cliente/notas/folio) en `_quote_store[quote_id + "_meta"]`.
3. **PDF/Excel** → `GET /api/pdf/{id}` (cotización), `/api/ot/{id}` (OT + página landscape con badges por material), `/api/entrega/{id}` (acta + garantía 3 meses), `/api/plano/{id}` + `/api/plano-taller/{id}` (planos de medidas cliente/taller), `/api/excel/{id}`.
4. **History** → `GET /api/quotes` (list + filtros), `/api/quotes/{id}/open` (re-abre, rebuild), `DELETE /api/quotes/{id}`.
5. **Clients** → `GET /api/clients?q=`, `POST /api/clients`, `DELETE /api/clients/{id}`.
6. **Catalog** → `GET /api/catalog` (memoria), `POST /api/catalog` → `catalog_apply()` + `catalog_save()` a `catalog.json`.
7. **Admin** → `/api/admin/status`, backups (list/create/download/restore), limpieza, vacuum.
8. **Raster→SVG** → `POST /api/vectorize` (bilateral+median → K-means LAB → background por bordes → vtracer binario → re-alimenta `parse_svg`).

### Módulos

| Archivo | Rol |
|---|---|
| `main.py` | FastAPI, handlers, caches en RAM, persistencia helpers |
| `calculator.py` | Parse SVG, lógica de cotización 3 tipos, `QuoteResult` |
| `db.py` | SQLite: `init_db`, `save_quote`, `list_quotes`, folio `SGI-YYYY-NNNN`, clients |
| `catalog_data.py` | Precios (LAMINAS, LEDS_CANAL, LEDS_CAJA, FUENTES, PEGAMENTOS, CABLES, SILVATRIM, VINILOS, TUBULARES, PRECIOS_BASE, TIPOS_CONSTRUCCION, GRUAS, ICF_CONFIG), auto-selección, persistencia |
| `pdf_gen.py` | ReportLab: cotización, OT, acta |
| `plano_gen.py` | Planos cliente/taller con sistema anti-solape |
| `excel_gen.py` | openpyxl XLSX (Resumen + Letras + Desglose) |
| `vectorizer.py` | Raster→SVG silueta (K-means LAB + vtracer binario). Solo `vectorize()` — no reintentar LLMs (§NO) |
| `nesting.py` | Nesting true-shape independiente del quoting (shapely + cv2 raster-NFP; DXF via ezdxf) |
| `static/index.html` | SPA single-file (vanilla JS + CSS inline; no build) |
| `catalog.json` | Overrides runtime; gana sobre defaults de `catalog_data.py` (ver §Catalog persistence) |
| `cotizador.db` | SQLite (quotes, folio_seq, clients); auto-creado por `init_db()` con migración defensiva |

## Reglas de negocio

### Costos de material

**Letras canal / planas** = **proporcional $/cm²** (área × precio/cm², no láminas × precio):

```python
def precio_cm2(mat):
    area = mat.get("ancho_cm", 122) * mat.get("alto_cm", 244)
    return mat.get("precio", 0) / area if area > 0 else 0.0
```

Cara adaptativa por pieza (`tipo_cara="auto"`): cada pieza elige material según su altura, así una placa de 38 cm + letra de 2 cm no paga todo al material caro. `cara_por_pieza` = lista `(mat_id, area, costo)` por pieza.

**Cajas** = **whole-sheet** para estructura (aluminio cal 18) y base (PVC): `lam × mat["precio"]`. Cara usa flat `$/m²` de `PRECIOS_CAJA_M2`.

### LEDs — letras canal

Depende de `modo_iluminacion` en `TIPOS_CONSTRUCCION`:
- **`cara`** (cajón): módulos por AREA. Cobertura ≈ `cercha × espaciado_led × 2`; por pieza `max(3, ceil(area / cobertura))`.
- **`halo`** (retro_halo): UNA corrida perimetral, `max(3, ceil(perimetro / _ESPACIADO_HALO_CM))` (15 cm en `calculator.py`).

Mínimo 3 módulos/pieza. `led_id="auto"` → `led_recomendado(cercha_cm, uso)`.

### LEDs — cajas

Catálogo Signalux (jul-2026): interior 7 productos, exterior 7. Cada LED tiene `tamano_caja` (`pequena`/`mediana`/`grande`/`gigante`).

**Prioridad por tamaño** (`_PREF_POR_TAMANO` en `catalog_data.py`, categoría según `lado_mayor` de la caja):

| Tamaño | Rango | Preferencia |
|---|---|---|
| pequeña | ≤ 60 cm | perimetral > backlite > edgelite > modulo_panel |
| mediana | 60-120 cm | edgelite > perimetral > backlite > modulo_panel |
| grande | 120-200 cm | edgelite > modulo_panel > backlite > perimetral |
| gigante | > 200 cm | modulo_panel > edgelite > backlite > perimetral |

Fórmulas de cantidad (siempre pisadas por lumen density: `2000 lm/m²` exterior / `1200 lm/m²` interior, × factor_vistas):

| tipo_led | n_modulos |
|---|---|
| `modulo_panel` | `max(area × densidad_m2, lumen_target/lum_por_led)` |
| `perimetral` | `perimetro / espaciado_cm` (Sign Edge 01 = 15 cm entre centros, NO 4.3 que es largo del módulo) |
| `edgelite` | `max(perimetro / largo_barra, lumen_target/lum_por_barra)` |
| `backlite` | `filas × barras_por_fila` |

**Precio**: si el LED tiene `precio_modulo` + `precio` (tira de N) y es `perimetral`/`modulo_panel` → agrupa: `n_tiras = ceil(n_modulos / modulos_tira)`, costo = `n_tiras × precio_tira` (así compra SGI). Si sólo `precio` (barras individuales) → `n_barras × precio`.

`QuoteResult` guarda:
- `modulos_led` = cantidad atómica (módulos o barras — nunca tiras)
- `tiras_led` = tiras compradas (>0 si aplica agrupación)
- `categoria_caja` = clasificación por lado mayor

Expuesto en `costos.iluminacion.modulos` / `.tiras` / `.categoria_caja`.

### Fuente

Proporcional a watts, floor 20%:
```python
fraccion = max(0.20, watts / fuente["watts"])
c_fuente = fuente["precio"] * fraccion
```

### Pegamento

Proporcional a metros de perímetro, floor 5%:
```python
metros = perimetro/100 * max(1, juntas)
envases = max(0.05, metros / metros_por_envase)
```
Rendimientos calibrados con campo: Soudaflex 11 m/envase, Silicón 11 m, Cloruro 60 m.

### Pricing letras canal / planas

```
precio_letra = altura_cm × precio_cm × multiplicador
precio_total = sum(precio_letra) × (1 + ajuste_pct/100)
```
`PRECIOS_BASE["precio_cm"]` default 10. Multiplicadores en `PRECIOS_BASE["multiplicadores"]` (`acrilico_con_luz_std`=4.5, etc.). IVA 16% hardcoded.

### Tipos de construcción (letras)

| ID | Cara | Fondo PVC | LEDs | Modo | Distanciadores | Multiplicador |
|---|---|---|---|---|---|---|
| `cajon_luz` | acrílico | ✓ | ✓ | cara | ✗ | `acrilico_con_luz_std` (4.5) |
| `retro_halo` | aluminio | ✗ | ✓ | halo | ✓ | `aluminio_con_luz` (2.5) |
| `sin_luz` | aluminio | ✓ | ✗ | — | ✗ | `aluminio_sin_luz` (2.0) |
| `abierta_luz` | ninguna | ✓ | ✓ | cara | ✗ | `aluminio_con_luz` (2.5) |

`DISTANCIADORES` sólo en `retro_halo`. Silvatrim opcional (`silvatrim_id`): `""`=none, `"auto"`→`silvatrim_recomendado(cercha_cm)` pero resuelve a none si `config["cara"] != "acrilico"`.

### Cajas — específicos

**Fórmula precio**: NO usa altura×precio×multiplicador. `precio_venta_sugerido = total / (1 - margen_ganancia)` directo. `desglose_letras` vacío para cajas.

**Detección outline** — `_find_caja_outline()` = path con `perimeter / (2*(w+h)) ≤ 4.5` (tope 4.5 acepta esquinas redondeadas) y mayor bbox. Si no hay outline: `caja_h_cm = viewbox_h × sf`. `caja_w_cm = real_width_cm` siempre. `design_paths` = todos excepto outline (para calcular cuadro de vinil).

**Cara (2 decisiones)** — regla del propietario jul-2026: caja = UNA pieza, no enumerar letras (OT sin badges en `caja_luz`):
- **`tipo_cara`**: `"lona"` o `"acrilico"` (legacy `"vinil_corte"`/`"acrilico_2vistas"` mapeados).
- **`grafico`**: `"impreso"` (en lona: sin costo extra; en acrílico: `vinil_impresion` $/m² × área × vistas) | `"vinil_corte"` (cobra el **cuadro de corte** — UN rectángulo enclosing todos los design_paths, incluye aire entre líneas; cost = ml de rollo × `precio_ml` de VINILOS[id], rollo 0.60 m; ambas orientaciones, gana la barata) | `"ninguno"`.

**Sercha**: `material_sercha_caja(w, h, uso)` → cal 20 (interior ≤ 122 cm) o cal 18. Cost proporcional.

**`vistas` (regla propietario jul-2026)**:
- **1 vista** → **Base cerrada** placa `alucobon_3mm` atrás del canal. Cobra `laminas × precio_hoja`. Label UI/PDF: **"Base"**.
- **2 vistas** → **Bastidor tubular perimetral** (PTR de acero, `tubular_recomendado(w,h,uso)`; sin placa cerrada, ambas caras translúcidas). Metros a cortar = `perimetro/100 × 1.25` (`_BASTIDOR_FACTOR` cubre refuerzos + retales + soldadura). Guardado en `material_bastidor`/`metros_bastidor`/`costo_bastidor`. `costo_material_fondo=0` en 2 vistas (excluyentes por diseño). Label: **"Bastidor tubular"**.

**Cables**: `CABLES` (Radox cal 22 LED, POT cal 18) costeados por perímetro × 1.2, mín 5 m.

**Maquila**: `corte_laser`/`corte_cnc`/`corte_plotter`/`flete_maquila` — montos manuales por cotización, entran al costo antes del margen.

**MO en cajas**: MO se inyecta dentro de `cotizar_caja` (no en `_apply_instalacion`) para que el margen aplique. `_apply_instalacion` **skip** `mo_total` cuando `tipo == "caja_luz"`.

**`PRECIOS_CAJA_M2`** (material sólo, sin markup): `lona_translucida` 50, `vinil_impresion` 60, `acrilico` 380, `acrilico_2vistas` 760. Vinil de corte NO va acá — se saca de VINILOS ($/ml).

### Planas (3 capas)

SVG con capas nombradas `base`, `corte`, `luz` (Illustrator `<g id="base">…`). Detección por regex sobre `id`/`inkscape:label` en `_detectar_capa`, keywords en `_CAPA_KEYWORDS`. Cada `PathInfo` lleva `capa`.

Categorías cobradas:
- **`base`**: placa completa por bbox × material_base.
- **`corte`**: piezas planas, cobradas por bbox conjunto × material_corte.
- **`luz`**: retroiluminadas (leds + fuente + distanciadores).
- **`""`**: sin capa nombrada, tratado como corte.

Base real detectada (`base_real_w_cm`/`base_real_h_cm` en respuesta `/api/parse-svg`): dimensión física de la placa base según unidades del SVG, no del artboard con padding.

### Instalación / MO (`_InstMixin`)

Los 3 request models (`LetrasRequest`, `CajaRequest`, `PlanasRequest`) heredan:
- `mo_horas`/`mo_tarifa` → `result.mo_total` (skip para caja, ver arriba)
- `inst_activa` + `inst_lugar`, `inst_viaticos`, `inst_grua_id`, `inst_dias_grua`, `inst_extras`

`_apply_instalacion()` en `main.py`: `inst_total = viaticos + costo_grua + extras`, `precio_final = precio_venta_sugerido + inst_total`.

### PDFs (ReportLab)

**Reglas anti-solape "enzimado"**:
- Todo texto de celda en `Paragraph` (strings no wrappean)
- Helper `_p(texto, estilo)` para cada celda
- Column widths `PW * fraction` (puntos), NUNCA `"15%"`
- `ParagraphStyle` module-level con prefijo `sgi_*` único

Generadores:
- `generar_pdf(result, meta)` — cotización cliente
- `generar_pdf_ot(result, meta)` — OT interna con página landscape del SVG + badges color-coded por material
- `generar_pdf_entrega(result, meta)` — acta + garantía **3 meses** (art. 77 LFPC 90-day min); `fecha_entrega` real (no fecha cotización); `lugar` y `anticipo` (default 50%) del modal "Datos de entrega". `_meta_con_cliente()` linkea cliente registrado (case-insensitive) para pintar RFC/tel/dirección. EL PROVEEDOR = `catalog_data.EMPRESA` (editable en `catalog.json["empresa"]`).

### Planos anti-solape (`plano_gen.py`)

`generar_plano_cliente()` / `generar_plano_taller()` comparten `_construir_pdf()`. Pág. 1: dibujo landscape + badges numerados + tabla piezas + cajetín. Pág. 2: taller siempre (BOM + ficha fabricación + cercha side-profile); cliente sólo si tabla desborda.

Cajas → dispatch a `_construir_pdf_caja()` (caja = UNA pieza, nunca enumerar vinilos). Cotas globales W/H + dashed orange cuadro de corte + position cotas + cotas por RENGLÓN (`_filas_diseno()` agrupa design paths por overlap Y).

Sistema anti-solape (requisito duro del propietario — cotas nunca "enzimadas"):
- **Contrato de escala**: `main.py` pasa `altura_cm` = h del joint bbox de TODAS las piezas cerradas en cm, así `cm_per_unit = altura_cm / bbox_h_svg` con el mismo bbox. Cambiar un lado = cambiar ambos.
- **Filtrado**: piezas = closed AND `not es_hueco`. Huecos se dibujan pero no numeran/miden.
- **Cotas por pieza** sólo si `n_piezas ≤ MAX_PIEZAS_COTAS` (20). Anchos abajo en ≤`MAX_FILAS_COTA` (3) rows staggered; altos a la izquierda, ≤`MAX_COLS_ALTO` (2). `_pack_intervalos()` (greedy interval-graph coloring con anchos reales de `pdfmetrics`) asigna rows; piezas que no caben se **omiten** (nunca se solapan) — la tabla siempre tiene toda medida.
- **Badges**: `_dibujar_badges` empuja verticalmente los que colisionan. Piezas circulares (bbox cuadrado + perim ≈ π·d) muestran "Ø D". Colores badge = misma paleta que OT.
- **Escala** en cajetín = cm reales por cm papel, redondeada a valor "plano-friendly" (1:2, 1:30, 1:50…) vía `_escala_bonita`.

### QuoteResult (campos clave)

Además de básicos: `tipo_construccion`, `tipo_multiplicador`, `multiplicador_valor`, `precio_sin_ajuste`, `ajuste_pct`, `precio_venta_costo`, `precio_venta_sugerido`, `mo_total`, `inst_*` + `inst_total`, `precio_final`, `desglose_letras` (por pieza con recipe + costos), `desglose_costos_componentes` (global por componente), `warnings` (inconsistencias detectadas), `silvatrim` + metros + costo, `vinil_cercha` + metros + costo, `material_bastidor` + metros + costo, `categoria_caja`, `tiras_led`.

### Nesting (`nesting.py`)

Independiente del quoting (UI tab "Corte", `/#corte`). 1-10 SVGs, mezclados en las mismas láminas. Presets: lámina 122×244, rollo 60 cm, retazo custom. Defaults: gap 5 mm, margen borde 10 mm, rotaciones cada 15°.

Algoritmo raster NFP por convolución: shapely polys con holes por depth even/odd; greedy bottom-left ordenado por área desc; per ángulo, mask piezas (holes vacíos) vs occupancy grid con `cv2.matchTemplate`. Dos correcciones aprendidas: (1) masks `np.rint` (no floor — sesgo shaveaba 1 px/lado); (2) mask candidato PADDED por gap antes de `cv2.dilate` (dilation clipa en bordes silenciosamente).

Endpoints: `POST /api/nest` (multipart + config JSON; **sync `def`** a propósito porque es CPU-bound, corre en threadpool, 15-90 s) → `{nest_id, laminas, sin_lugar}`. Downloads: PDF, SVG en cm, DXF en **mm** (`$INSUNITS=4`, capas CORTE/LAMINA/ETIQUETAS).

### Administración (`/#admin`)

Endpoints `/api/admin/*`. Backups siguen `db.DB_PATH` (no path fijo — así los tests con conftest redirigen DB_PATH + BACKUP_DIR sin tocar producción). Restore valida DB antes de sobreescribir (`db.es_db_valida()` lee `sqlite_master`) y snapshot pre-restaurar auto-revierte on failure. Limpieza `POST /api/admin/db/limpiar` con criterios ANDed, mín 1 (nunca vacía por accidente). VACUUM fuera de transacción.

**Gotcha aprendido**: `SELECT 1` NO valida SQLite (lazy open). `db.ping()` lee `sqlite_master` — mantener así.

### Catálogo — persistencia

- `catalog_load()` (al import) merge `catalog.json` sobre defaults de `catalog_data.py` (`_catalog_merge` preserva defaults no presentes en JSON). **Consecuencia**: **cambiar precios en `catalog_data.py` NO surte efecto si `catalog.json` los tiene**. Editar los DOS o borrar `catalog.json` y regenerar vía `catalog_save()`.
- `catalog_apply()` (via `POST /api/catalog`) = full replace, valida con `CatalogPayload` Pydantic (`extra="forbid"`).
- Prices calibrados contra "Todo para el Anunciero" feb-2026 y Signalux jul-2026.
- `PEGAMENTOS` keys son tuples `(cercha_tipo, cara_tipo)`, serializados como `"aluminio|acrilico"`.
- `NEON_FLEX` definido pero no usado en cotización todavía (futuro).

### ICF — Índice de Complejidad de Fabricación

`calculator.compute_icf` corre después de cotizar (`apply_icf_to_result` en `main.py`). **NO cambia precio** — auditoría de MO por geometría. Modelo por proceso (Groover cap 22):

```
T_corte    = L/v_c + N_esquinas·t_dwell + α·κ_total + N_piezas·t_pierce
T_doblado  = P/v_b + N_esquinas·t_bend
T_sellado  = P_sellable/v_s + N_piezas·t_setup_pistola
T_cableado = N_modulos·t_mod
T_armado   = N_piezas·t_base + N_huecos·t_hueco
T_manip    = N_piezas·t_handling + masa_kg·t_carga_kg
```

Constantes en `ICF_CONFIG.constantes` (editables por catálogo). Flag `ICF_CONFIG.calibrado_taller=False` marca en UI que son defaults industria hasta cronometrar 3 piezas reales. `ICF_norm = T_total / T_ref` (referencia = letra "O" 30 cm cajón). Rellena `QuoteResult.icf_features` / `icf_desglose_min` / `icf_total_min` / `mo_costo_icf` / `icf_calibrado`.

### SVG parsing + detección de huecos

`parse_svg()` = universo de piezas: `<path>`, `<rect>`, `<circle>`, `<ellipse>`, `<polygon>`, `<polyline>`, `<line>`. Cada `PathInfo` con `svg_id` (id original del SVG — key estable UI/planos) y `fill` (resuelto de attr, style o CSS class). `SVGData` con `svg_unit` (px/mm/cm/in/pt detectado) y `artboard_w_cm` (> 0 si el SVG declara unidad física).

**⚠ Orden**: `parse_svg` **reordena `path_infos` por `bbox["x"]`** (línea 746). El frontend recibe paths en X-order, NO en DOM order. Consecuencia: NO usar el índice para matchear con three.js SVGLoader (que sí es DOM order). En `_buildPlanas` (visor 3D) se parsea el SVG con `DOMParser` en JS para armar el capa-por-índice en DOM order.

**Huecos (`es_hueco`)**: `_marcar_huecos()` marca True si pieza cerrada blanca está: (a) contenida bbox en otra pieza no-blanca (contador letra), o (b) contiene ≥60% de las otras cerradas (placa fondo). Pieza blanca aislada NO se marca. Nesting geométrico even-odd no funciona (knockouts hacen todo "outside") — el fill blanco es la señal. Filtros: planos, OT, UI (gris punteado sin número), **y motor de cotización** (`cotizar_letras`/`cotizar_planas` excluyen huecos; `parse_svg` calcula `max_pieza_height_px` sin huecos → `altura_letra_cm` ancla a pieza REAL más alta). `cotizar_caja` NO filtra (el rectángulo blanco ES el outline).

Escala prioridad (`apply_scale()`):
1. `altura_letra_cm > 0` → escala por altura de pieza no-hueco más alta (ancla real).
2. `artboard_w_cm > 0` (Illustrator) → `(real_width_cm / artboard_w_cm) × PT_TO_CM`.
3. Fallback: `real_width_cm / viewbox_w`.

## Qué NO hacer

1. **No generes SVG con LLMs** (Claude, GPT). Limitación arquitectónica, no de prompt. Si necesitás vectorización avanzada: vectorizer.ai o recraft.ai. El experimento se removió y hay memoria explícita.
2. **No pongas `reload=True`** en producción (usar env `DEV_RELOAD`).
3. **No hagas `except Exception`** sin loggear traceback.
4. **No agregues deps** sin regenerar `requirements.lock` (`pip-compile`) y revisar licencia.
5. **No toques el visor 3D three.js** en `static/index.html` sin permiso explícito. Excepciones autorizadas: 3D letras planas (base+piezas+separadores+explode) y 3D cajas (LEDs internos + explode).
6. **No despliegues a Render free** sin disco persistente (filesystem efímero borra SQLite en redeploy).
7. **No cambies precios en `catalog_data.py`** esperando que surta efecto — `catalog.json` gana. Editar los dos.

## Roadmap pendiente

Ya shipped: SQLite + folio + history + clientes + Excel + backups auto + índices + SVG preview interactivo + planos v2 anti-solape + huecos detection + OT landscape con badges + SVG en DB + catálogo Signalux jul-2026 + ICF + LEDs caja con engineering real (categoria_caja + tiras_led) + planas 3 capas + 3D planas base/corte/luz/explode + 3D caja LEDs internos/explode + bastidor tubular 2 vistas.

**Pendientes útiles**:
1. Render con disco persistente (config externa al repo — dashboard Render).
2. Multi-SVG por cotización (múltiples letreros en un proyecto).
3. Datos de empresa (logo, RFC completo, etc.) embebidos en PDFs.

**Pendientes lower priority**:
4. Auth multi-usuario (Fase 2 — pre-requisito SaaS).
5. Email cotización directo desde app.
6. API de integración con ERP/facturación.

**Roadmap SaaS Fase 2** (si se valida mercado): migrar SQLite → PostgreSQL + Alembic + SQLAlchemy async; reescritura frontend a Vue 3 + Vite + TypeScript + Pinia; auth con `fastapi-users`; multi-tenant (`tenant_id` en quotes/clients/catálogo); pagos Stripe o MercadoPago; rate limiting; landing + T&C + LFPDPPP.

## Owner context

- **Email**: elmuroparral@gmail.com
- **Negocio**: SGI — rotulación en México
- **Perfil**: dueño del dominio del negocio (materiales, precios, procesos), no dev. Trabaja con Claude Code para implementación.
- **Estilo**: **plan ANTES de tocar código**. Aprueba o corrige antes de cualquier cambio no trivial. Prefiere lenguaje de ingeniería rigurosa (no "rezar", no "esperemos que"). Cuando pregunta algo, quiere razonamiento técnico no sólo el fix.
- **Presupuesto**: moderado. Justificar costo de cambios grandes.

---

> **Al retomar**: lee este archivo entero primero, después ejecuta `git log --oneline -15` para ver los últimos cambios. Si algo no está claro en el código, pregunta al propietario antes de asumir.
