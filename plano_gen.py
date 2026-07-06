"""plano_gen.py — Plano de medidas para cliente y taller.

Dos generadores públicos:
  - generar_plano_cliente(meta, svg_text, paths_info, viewbox_w, viewbox_h,
                          real_width_cm, altura_cm=0, result=None) → bytes
  - generar_plano_taller (..., result, notas="") → bytes

Diseño:
  Pág 1 → SVG renderizado + badges numerados por pieza + subtítulo con
          dimensiones totales del proyecto. Sin cotas en el dibujo —
          mantenerlas legibles es imposible cuando hay 15-20+ piezas y
          mal distribuidas le quitan claridad al diseño cuando son pocas.
  Pág 2 → Listado tabular tipo "cards" del SVG en la UI:
            # · Tipo (Rectángulo / Círculo) · Medidas · Perímetro [· Material]
          Si la pieza pasa el test de "círculo" (bbox cuadrado +
          perímetro ≈ π·diámetro), se muestra "Ø D" en vez de "alto × ancho".

El dibujo se escala con el bbox CONJUNTO de las piezas conservadas, no con
el viewBox completo — para no quedar comprimido por el aire del artboard
de Illustrator.
"""

from __future__ import annotations

import io
import logging
import math
import os
import tempfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as _canvas

log = logging.getLogger("cotizador.plano")

# ─── Constantes de estilo ────────────────────────────────────────────────────

AZUL_DARK  = colors.HexColor("#1a2b4a")
GRIS_LIGHT = colors.HexColor("#aaaaaa")
GRIS_TXT   = colors.HexColor("#555555")
NARANJA    = colors.HexColor("#e87c2a")

LINE_COTA       = colors.black
LINE_EXT        = GRIS_LIGHT
LW_COTA         = 0.7
LW_EXT          = 0.4
ARROW_LEN_PT    = 4.5
FONT_NAME       = "Helvetica"
FONT_BOLD       = "Helvetica-Bold"
FS_COTA         = 8.5
FS_HEADER_TIT   = 14
FS_HEADER_SUB   = 9.0
FS_TABLE_TH     = 8.5
FS_TABLE_TC     = 8.0
FS_LEYENDA      = 8.0

DECIMALES_COTA = 2          # ← decisión del usuario
EPSILON_ALTOS  = 0.05       # 0.05 cm de tolerancia para "altos iguales"
MAX_PIEZAS_COTA_DISEÑO = 15  # umbral: arriba de esto, no cotas individuales en el dibujo,
                             # se muestran solo las globales y la tabla en pág. 2 hace de
                             # listado de medidas por pieza

MARGEN_HOJA    = 1.3 * cm
HEADER_H       = 2.0 * cm
PIE_H          = 0.5 * cm
BANDA_COTA_OUT = 2.2 * cm   # espacio reservado a cada lado para cotas + global
BANDA_COTA_IN  = 0.45 * cm  # banda inicial entre el dibujo y la 1ra fila de cotas
GAP_FILA_PT    = 11.0       # separación vertical entre filas escalonadas de cotas
GAP_GLOBAL_PT  = 8.0        # separación extra entre la última fila individual y la global

# Paleta para badges por material (mismo orden que pdf_gen._OT_MATERIAL_PALETTE)
_MAT_PALETTE = [
    "#1565C0", "#E65100", "#2E7D32", "#6A1B9A",
    "#C62828", "#00838F", "#558B2F", "#4527A0",
]


# ─── Helpers de bbox y consolidación ─────────────────────────────────────────

def _bbox_conjunto(paths_info: list) -> tuple[float, float, float, float]:
    """Devuelve (min_x, min_y, max_x, max_y) del bbox que envuelve a todas
    las piezas cerradas. Si no hay piezas, devuelve (0,0,0,0)."""
    cerrados = [p for p in paths_info if p.get("is_closed")]
    if not cerrados:
        return 0.0, 0.0, 0.0, 0.0
    xs0 = [p["bbox"]["x"] for p in cerrados]
    ys0 = [p["bbox"]["y"] for p in cerrados]
    xs1 = [p["bbox"]["x"] + p["bbox"]["w"] for p in cerrados]
    ys1 = [p["bbox"]["y"] + p["bbox"]["h"] for p in cerrados]
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _alturas_consolidadas(piezas_cm: list[tuple], eps: float = EPSILON_ALTOS) -> bool:
    """True si todas las piezas comparten la misma altura (dentro de eps)."""
    if not piezas_cm:
        return True
    altos = [alto for (_, _, alto) in piezas_cm]
    return (max(altos) - min(altos)) <= eps


def _text_width(txt: str, font: str = FONT_NAME, size: float = FS_COTA) -> float:
    """Ancho del string en pt, con fallback heurístico si no hay pdfmetrics."""
    try:
        from reportlab.pdfbase import pdfmetrics
        return pdfmetrics.stringWidth(txt, font, size)
    except Exception:
        return len(txt) * size * 0.55


def _empacar_cotas(items: list[tuple[int, float, float]],
                   lados: tuple[str, str],
                   padding_pt: float = 4.0
                   ) -> dict[int, tuple[str, int]]:
    """Empaca cotas en dos bandas opuestas (ej. arriba/abajo o izq/der),
    repartiendo solape alternando lado preferido y apilando en filas.

    `items` es una lista de (idx, centro, media_extension) ordenada por
    posición visual (L→R para anchos, abajo→arriba para altos).
    `lados` es una tupla con los dos identificadores de banda.
    `padding_pt` es la separación mínima horizontal entre cotas vecinas.

    Devuelve {idx: (lado, fila)} con fila=0 la más cercana al dibujo y filas
    crecientes hacia afuera.
    """
    asignaciones: dict[int, tuple[str, int]] = {}
    bandas: dict[str, list[list[tuple[float, float]]]] = {lados[0]: [], lados[1]: []}
    for n, (idx, centro, half) in enumerate(items):
        a, b = centro - half - padding_pt / 2, centro + half + padding_pt / 2
        preferido  = lados[n % 2]
        secundario = lados[(n + 1) % 2]
        elegido: tuple[str, int] | None = None
        for lado in (preferido, secundario):
            for row, ocupados in enumerate(bandas[lado]):
                # Sin solape si para todos los ya ubicados: b <= x1 o a >= x2
                if all(b <= x1 or a >= x2 for x1, x2 in ocupados):
                    bandas[lado][row].append((a, b))
                    elegido = (lado, row)
                    break
            if elegido is not None:
                break
        if elegido is None:
            # No hubo fila libre — abrir una nueva en el lado preferido
            bandas[preferido].append([(a, b)])
            elegido = (preferido, len(bandas[preferido]) - 1)
        asignaciones[idx] = elegido
    return asignaciones


# ─── Helpers de cotas (canvas, no Flowable) ──────────────────────────────────

def _flecha(c, x: float, y: float, hacia: str, size: float = ARROW_LEN_PT) -> None:
    """Dibuja una pequeña punta de flecha triangular rellena en (x,y).

    `hacia` ∈ {"izq", "der", "arr", "aba"}: dirección a la que apunta la
    punta (es decir, el lado del cual VIENE la línea de cota).
    """
    p = c.beginPath()
    if hacia == "izq":
        p.moveTo(x, y); p.lineTo(x + size, y + size * 0.45); p.lineTo(x + size, y - size * 0.45)
    elif hacia == "der":
        p.moveTo(x, y); p.lineTo(x - size, y + size * 0.45); p.lineTo(x - size, y - size * 0.45)
    elif hacia == "arr":
        p.moveTo(x, y); p.lineTo(x - size * 0.45, y + size); p.lineTo(x + size * 0.45, y + size)
    else:  # "aba"
        p.moveTo(x, y); p.lineTo(x - size * 0.45, y - size); p.lineTo(x + size * 0.45, y - size)
    p.close()
    c.setFillColor(LINE_COTA)
    c.drawPath(p, fill=1, stroke=0)


def _cota_horizontal(c, x_start: float, x_end: float, y: float,
                     valor_cm: float, dec: int = DECIMALES_COTA) -> None:
    """Línea de cota horizontal con flechas en ambos extremos y valor encima."""
    if x_end <= x_start:
        return
    c.setStrokeColor(LINE_COTA); c.setLineWidth(LW_COTA)
    c.line(x_start, y, x_end, y)
    _flecha(c, x_start, y, "der")
    _flecha(c, x_end,   y, "izq")
    c.setFillColor(LINE_COTA); c.setFont(FONT_NAME, FS_COTA)
    c.drawCentredString((x_start + x_end) / 2, y + 1.8, f"{valor_cm:.{dec}f}")


def _cota_vertical(c, x: float, y_bot: float, y_top: float,
                   valor_cm: float, dec: int = DECIMALES_COTA) -> None:
    """Línea de cota vertical con flechas y valor (rotado 90°) al lado."""
    if y_top <= y_bot:
        return
    c.setStrokeColor(LINE_COTA); c.setLineWidth(LW_COTA)
    c.line(x, y_bot, x, y_top)
    _flecha(c, x, y_bot, "arr")
    _flecha(c, x, y_top, "aba")
    cy = (y_bot + y_top) / 2
    c.setFillColor(LINE_COTA); c.setFont(FONT_NAME, FS_COTA)
    c.saveState()
    c.translate(x - 2.2, cy); c.rotate(90)
    c.drawCentredString(0, 0, f"{valor_cm:.{dec}f}")
    c.restoreState()


def _ext_vertical(c, x: float, y_a: float, y_b: float) -> None:
    """Línea fina vertical auxiliar (de extensión) entre la pieza y la cota."""
    if abs(y_b - y_a) < 0.5:
        return
    c.setStrokeColor(LINE_EXT); c.setLineWidth(LW_EXT)
    c.line(x, y_a, x, y_b)


def _ext_horizontal(c, x_a: float, x_b: float, y: float) -> None:
    if abs(x_b - x_a) < 0.5:
        return
    c.setStrokeColor(LINE_EXT); c.setLineWidth(LW_EXT)
    c.line(x_a, y, x_b, y)


# ─── Renderizado del SVG escalado ────────────────────────────────────────────

def _render_svg(c, svg_text: str, ox: float, oy: float, scale: float,
                offset_x_svg: float, offset_y_svg: float,
                bbox_h_svg: float) -> bool:
    """Dibuja el SVG escalado en el canvas, ubicando la esquina superior-
    izquierda del bbox conjunto SVG (offset_x_svg, offset_y_svg) en la
    esquina superior-izquierda del área dibujo del canvas
    (ox, oy + bbox_h_svg*scale), y la esquina inferior-derecha del bbox
    (offset_x_svg + bbox_w, offset_y_svg + bbox_h_svg) en (ox + bbox_w*scale,
    oy). Sin doble inversión de Y: svglib ya entrega el Drawing en sistema
    reportlab (Y hacia arriba), mapeando SVG(x,y) → rlg(x, rlg.height - y).

    Devuelve True si pudo dibujar, False si svglib no está o falló.
    """
    try:
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg
    except ImportError:
        return False
    try:
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".svg", mode="w", encoding="utf-8")
        tmp.write(svg_text); tmp.close()
        rlg = svg2rlg(tmp.name)
        os.unlink(tmp.name)
    except Exception:
        log.warning("plano: svg2rlg falló", exc_info=True)
        return False
    if not rlg or rlg.width <= 0 or rlg.height <= 0:
        return False

    # Mapeo deseado:
    #   SVG (offset_x, offset_y)              → canvas (ox, oy + bbox_h*scale)
    #   SVG (offset_x + bbox_w, offset_y + bbox_h) → canvas (ox + bbox_w*scale, oy)
    # Como svglib mapea SVG(x,y) → rlg(x, rlg.height - y) y luego se aplica
    # c.translate + c.scale(s,s) sin inversión:
    #   canvas_y(SVG point y_svg) = ty + (rlg.height - y_svg) * scale
    # Resolviendo para que SVG y_svg = offset_y + bbox_h caiga en oy:
    #   ty = oy - (rlg.height - offset_y - bbox_h) * scale
    maxY = offset_y_svg + bbox_h_svg
    tx = ox - offset_x_svg * scale
    ty = oy - (rlg.height - maxY) * scale

    c.saveState()
    c.translate(tx, ty)
    c.scale(scale, scale)
    renderPDF.draw(rlg, c, 0, 0)
    c.restoreState()
    return True


def _svg_to_canvas_xy(x_svg: float, y_svg: float,
                       ox: float, oy: float, scale: float,
                       offset_x_svg: float, offset_y_svg: float,
                       bbox_h_svg: float) -> tuple[float, float]:
    """Convierte (x, y) en coords SVG a (x, y) en coords del canvas."""
    cx = ox + (x_svg - offset_x_svg) * scale
    cy = oy + bbox_h_svg * scale - (y_svg - offset_y_svg) * scale
    return cx, cy


# ─── Cabecera SGI estilo plano ───────────────────────────────────────────────

def _dibujar_header(c, meta: dict, titulo: str, PW: float, PH: float) -> None:
    """Cabecera azul oscuro en dos líneas:
        línea superior:  "SGI · Impresión y Diseño"    (izq)   |  TÍTULO  (centro)
        línea inferior:  Folio · Cliente · Fecha                (alineado a la derecha)
    Evita el choque entre el título centrado y la metadata cuando el folio es largo.
    """
    h = HEADER_H
    c.setFillColor(AZUL_DARK)
    c.rect(0, PH - h, PW, h, fill=1, stroke=0)

    # Línea superior — logo + título
    y_top = PH - h * 0.42
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 18)
    c.drawString(MARGEN_HOJA, y_top - 6, "SGI")
    c.setFont(FONT_NAME, FS_HEADER_SUB)
    c.drawString(MARGEN_HOJA + 38, y_top - 6, "Impresión y Diseño")
    c.setFont(FONT_BOLD, FS_HEADER_TIT)
    c.drawCentredString(PW / 2, y_top - 6, titulo)

    # Línea inferior — metadata del proyecto, alineada a la derecha
    folio   = meta.get("folio")   or "—"
    cliente = meta.get("cliente") or "—"
    fecha   = meta.get("fecha")   or datetime.now().strftime("%d/%m/%Y")
    c.setFont(FONT_NAME, FS_HEADER_SUB)
    txt = f"Folio: {folio}   ·   Cliente: {cliente}   ·   Fecha: {fecha}"
    c.drawRightString(PW - MARGEN_HOJA, PH - h * 0.85, txt)


def _dibujar_pie(c, PW: float, escala_txt: str, paginacion: str = "") -> None:
    """Pie discreto con la escala usada (a la derecha) y opcional indicador
    de paginación (a la izquierda)."""
    c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 7.5)
    if paginacion:
        c.drawString(MARGEN_HOJA, PIE_H * 0.5, paginacion)
    if escala_txt:
        c.drawRightString(PW - MARGEN_HOJA, PIE_H * 0.5,
                          f"Escala dibujo: {escala_txt}  ·  Cotas en cm")


# ─── Badges numerados sobre cada pieza ───────────────────────────────────────

def _materiales_to_color(result) -> dict:
    """Mapa material_id → color hex, estable por material distinto."""
    if not result:
        return {}
    mats: list[str] = []
    for d in (result.desglose_letras or []):
        mid = d.get("material_cara_id") or ""
        if mid and mid not in mats:
            mats.append(mid)
    return {m: _MAT_PALETTE[i % len(_MAT_PALETTE)] for i, m in enumerate(mats)}


def _dibujar_badges(c, piezas_canvas: list, mat_color_por_svgid: dict,
                    color_default: str = "#444444") -> None:
    """Dibuja un pill numerado en el centro de cada pieza.

    `piezas_canvas`: lista de tuplas (num, cx, cy, svg_id) en coords canvas.
    """
    if not piezas_canvas:
        return
    # Tamaño uniforme (mismo enfoque que UI/OT)
    font_pt = 9.0
    c.saveState()
    c.setFont(FONT_BOLD, font_pt)
    for num, cx, cy, svg_id in piezas_canvas:
        color_hex = mat_color_por_svgid.get(svg_id, color_default)
        num_str = str(num)
        pill_w = font_pt * 0.55 * len(num_str) + font_pt * 0.9
        pill_h = font_pt * 1.55
        c.setFillColor(colors.HexColor(color_hex))
        c.setStrokeColor(colors.white); c.setLineWidth(0.7)
        c.roundRect(cx - pill_w / 2, cy - pill_h / 2,
                     pill_w, pill_h, pill_h / 2, fill=1, stroke=1)
        c.setFillColor(colors.white)
        c.drawCentredString(cx, cy - font_pt * 0.33, num_str)
    c.restoreState()


# ─── Generador común (cliente + taller) ──────────────────────────────────────

def _calcular_escala(bbox_w_svg: float, bbox_h_svg: float,
                     real_width_cm: float, altura_cm: float,
                     viewbox_w: float, artboard_w_cm_hint: float = 0.0) -> float:
    """Calcula cm por unidad SVG. Prioridad:
      1. altura_cm > 0 sobre el bbox_h_svg
      2. real_width_cm sobre bbox_w_svg
      3. hint del artboard sobre viewbox_w (cae a pt→cm si no hay nada)
      4. fallback 1.0
    """
    if altura_cm > 0 and bbox_h_svg > 0:
        return altura_cm / bbox_h_svg
    if real_width_cm > 0 and bbox_w_svg > 0:
        return real_width_cm / bbox_w_svg
    if artboard_w_cm_hint > 0 and viewbox_w > 0:
        return artboard_w_cm_hint / viewbox_w
    return 1.0


def _construir_pdf(meta: dict, svg_text: str, paths_info: list,
                   viewbox_w: float, viewbox_h: float,
                   real_width_cm: float, altura_cm: float,
                   titulo: str, modo_taller: bool,
                   result=None, notas: str = "",
                   artboard_w_cm_hint: float = 0.0) -> bytes:
    """Núcleo común: cabecera + dibujo + cotas + (tabla y notas en taller).

    Coordenadas:
      - Hoja carta horizontal: 792 × 612 pt (28.0 × 21.6 cm).
      - Origen del canvas: abajo-izquierda.
      - SVG: Y crece hacia abajo; _render_svg invierte la Y para colocarlo
        en el canvas con orientación correcta.
    """
    PW, PH = landscape(letter)
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=landscape(letter))

    # Cabecera y pie
    _dibujar_header(c, meta, titulo, PW, PH)

    # Filtrar piezas cerradas
    piezas = [p for p in paths_info if p.get("is_closed")]
    if not piezas:
        c.setFillColor(colors.HexColor("#b00020"))
        c.setFont(FONT_BOLD, 12)
        c.drawCentredString(PW / 2, PH / 2,
                             "No se detectaron piezas cerradas en el SVG.")
        c.save()
        return buf.getvalue()

    minX, minY, maxX, maxY = _bbox_conjunto(piezas)
    bbox_w_svg = maxX - minX
    bbox_h_svg = maxY - minY

    cm_per_unit = _calcular_escala(bbox_w_svg, bbox_h_svg,
                                    real_width_cm, altura_cm,
                                    viewbox_w, artboard_w_cm_hint)

    # En modo taller la tabla va a una página 2 dedicada para no comprimir
    # el dibujo. Página 1 = dibujo + cotas (idéntica a cliente).
    area_x0 = MARGEN_HOJA + BANDA_COTA_OUT
    area_y0 = MARGEN_HOJA + PIE_H + BANDA_COTA_OUT
    area_w  = PW - 2 * MARGEN_HOJA - 2 * BANDA_COTA_OUT
    area_h  = PH - HEADER_H - MARGEN_HOJA - PIE_H - 2 * BANDA_COTA_OUT
    if area_w <= 0 or area_h <= 0 or bbox_w_svg <= 0 or bbox_h_svg <= 0:
        c.save()
        return buf.getvalue()

    scale_draw = min(area_w / bbox_w_svg, area_h / bbox_h_svg) * 0.92
    dibujo_w_pt = bbox_w_svg * scale_draw
    dibujo_h_pt = bbox_h_svg * scale_draw
    ox = area_x0 + (area_w - dibujo_w_pt) / 2          # esquina izq del bbox conjunto
    oy = area_y0 + (area_h - dibujo_h_pt) / 2          # esquina inf del bbox conjunto

    # Renderizar SVG
    _render_svg(c, svg_text, ox, oy, scale_draw, minX, minY, bbox_h_svg)

    # Mapeos para cotas y badges
    mat_colors = _materiales_to_color(result)
    mat_color_por_svgid: dict[str, str] = {}
    for d in (result.desglose_letras or []) if result else []:
        sid = d.get("svg_id") or d.get("id") or ""
        mid = d.get("material_cara_id") or ""
        if sid and mid:
            mat_color_por_svgid[sid] = mat_colors.get(mid, "#444444")

    # Convertir cada pieza a coords canvas + cm reales para cotar
    piezas_cm: list[tuple] = []      # (svg_id, ancho_cm, alto_cm)
    piezas_pos: list[tuple] = []     # (svg_id, x_l, x_r, y_bot, y_top, cx, cy)
    for p in piezas:
        bb = p["bbox"]
        x_l, y_top = _svg_to_canvas_xy(bb["x"], bb["y"],
                                         ox, oy, scale_draw, minX, minY, bbox_h_svg)
        x_r, y_bot = _svg_to_canvas_xy(bb["x"] + bb["w"], bb["y"] + bb["h"],
                                         ox, oy, scale_draw, minX, minY, bbox_h_svg)
        ancho_cm = bb["w"] * cm_per_unit
        alto_cm  = bb["h"] * cm_per_unit
        cx = (x_l + x_r) / 2; cy = (y_bot + y_top) / 2
        sid = p.get("svg_id") or p.get("id") or ""
        piezas_cm.append((sid, ancho_cm, alto_cm))
        piezas_pos.append((sid, x_l, x_r, y_bot, y_top, cx, cy))

    # Ordenar por X de izquierda a derecha para numerar de forma natural
    orden = sorted(range(len(piezas_pos)), key=lambda i: piezas_pos[i][1])
    n_piezas = len(piezas_pos)

    # ── Badges numerados por pieza ───────────────────────────────────────────
    piezas_canvas: list[tuple] = []
    for n, i in enumerate(orden, start=1):
        sid, _xl, _xr, _yb, _yt, cx, cy = piezas_pos[i]
        piezas_canvas.append((n, cx, cy, sid))
    _dibujar_badges(c, piezas_canvas, mat_color_por_svgid)

    # ── Dimensiones totales como texto debajo del dibujo (sustituye cotas
    #     globales). Más legible y no compite con el diseño.
    bbox_w_cm = bbox_w_svg * cm_per_unit
    bbox_h_cm = bbox_h_svg * cm_per_unit
    c.setFillColor(AZUL_DARK); c.setFont(FONT_BOLD, 11)
    txt_totales = f"Dimensiones del proyecto: {bbox_w_cm:.2f} cm de ancho × {bbox_h_cm:.2f} cm de alto"
    c.drawCentredString(PW / 2, MARGEN_HOJA + PIE_H + 24, txt_totales)
    if n_piezas > 0 and result and result.desglose_letras:
        c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 8.5)
        c.drawCentredString(PW / 2, MARGEN_HOJA + PIE_H + 10,
                            f"{n_piezas} piezas — Medidas individuales en página 2")

    # Pie con escala (página 1)
    escala_txt = f"1:{round(1 / (scale_draw * cm_per_unit / cm))}"
    incluye_pag2 = bool(result and result.desglose_letras)
    pag_total    = "Página 1 de 2" if incluye_pag2 else ""
    _dibujar_pie(c, PW, escala_txt, paginacion=pag_total)

    # ── Página 2: listado tabular tipo "cards" de la UI ──────────────────────
    if incluye_pag2:
        c.showPage()
        titulo_pag2 = ("PIEZAS A FABRICAR — TABLA TÉCNICA" if modo_taller
                       else "LISTADO DE MEDIDAS POR PIEZA")
        _dibujar_header(c, meta, titulo_pag2, PW, PH)
        tabla_area_top    = PH - HEADER_H - MARGEN_HOJA
        tabla_area_bottom = MARGEN_HOJA + PIE_H + (1.2 * cm if notas else 0.4 * cm)
        _dibujar_listado_piezas(c, result, piezas_canvas, mat_colors,
                                MARGEN_HOJA, tabla_area_bottom,
                                PW - 2 * MARGEN_HOJA,
                                tabla_area_top - tabla_area_bottom,
                                notas, incluir_material=modo_taller)
        _dibujar_pie(c, PW, escala_txt="", paginacion="Página 2 de 2")

    c.save()
    return buf.getvalue()


# ─── Listado tabular por pieza ───────────────────────────────────────────────

def _detectar_forma(d: dict) -> tuple[str, dict]:
    """Devuelve ("circulo", {"diametro": D, "radio": R}) o ("rectangulo", {}).

    Test de círculo:
      - bbox ≈ cuadrado (aspect ≥ 0.95)
      - perímetro ≈ π × ancho (tolerancia 10%)
    Una bbox cuadrada por sí sola no implica círculo (puede ser un cuadrado),
    el segundo test descarta cuadrados (perim = 4·lado ≠ π·lado).
    """
    ancho = float(d.get("ancho_cm", 0) or 0)
    alto  = float(d.get("alto_cm",  0) or 0)
    perim = float(d.get("perimetro_cm", 0) or 0)
    if ancho <= 0 or alto <= 0 or perim <= 0:
        return "rectangulo", {}
    aspect = min(ancho, alto) / max(ancho, alto)
    if aspect < 0.95:
        return "rectangulo", {}
    perim_circulo = math.pi * ancho
    if perim_circulo <= 0:
        return "rectangulo", {}
    if abs(perim - perim_circulo) / perim_circulo < 0.10:
        diametro = (ancho + alto) / 2
        return "circulo", {"diametro": diametro, "radio": diametro / 2}
    return "rectangulo", {}


def _dibujar_listado_piezas(c, result, piezas_canvas: list, mat_colors: dict,
                             mar_l: float, y0: float, tabla_w: float,
                             tabla_h: float, notas: str,
                             incluir_material: bool = True) -> None:
    """Listado tabular tipo "cards" del SVG en la UI.

    Columnas: # · Tipo · Medidas · Perímetro [· Material · Notas]
      - Tipo = "Rectángulo" o "Círculo"
      - Medidas = "{alto} × {ancho} cm" para rect, "Ø {diametro} cm" para círculo
      - Material/Notas solo si `incluir_material` (plano taller)
    """
    if not result.desglose_letras:
        return
    if incluir_material:
        headers = ["#", "Tipo", "Medidas (cm)", "Perímetro (cm)", "Material", "Notas"]
        pesos   = [0.05, 0.13, 0.21, 0.14, 0.22, 0.25]
    else:
        headers = ["#", "Tipo", "Medidas (cm)", "Perímetro (cm)"]
        pesos   = [0.07, 0.20, 0.40, 0.33]
    cols_x  = [mar_l + tabla_w * sum(pesos[:i]) for i in range(len(pesos) + 1)]

    # Layout — el header de la página ya muestra "PIEZAS A FABRICAR — TABLA
    # TÉCNICA", así que aquí saltamos el subtítulo y arrancamos directo en
    # el header de columnas para maximizar filas visibles.
    n_filas = len(result.desglose_letras)
    th_h    = 18
    tr_h    = max(11, min(22, (tabla_h - th_h - 12) / max(n_filas, 1)))

    # Header
    y_th = y0 + tabla_h - th_h - 4
    c.setFillColor(AZUL_DARK)
    c.rect(mar_l, y_th, tabla_w, th_h, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, FS_TABLE_TH)
    for i, h_txt in enumerate(headers):
        ancho_col = cols_x[i + 1] - cols_x[i]
        c.drawString(cols_x[i] + 3, y_th + th_h / 2 - FS_TABLE_TH / 2.4, h_txt)
        c.setStrokeColor(colors.HexColor("#3c4d6e"))
        c.setLineWidth(0.3)
        c.line(cols_x[i + 1], y_th, cols_x[i + 1], y_th + th_h)

    # Filas
    y_row = y_th - tr_h
    c.setFont(FONT_NAME, FS_TABLE_TC)
    for idx, d in enumerate(result.desglose_letras):
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#f5f7fa"))
            c.rect(mar_l, y_row, tabla_w, tr_h, fill=1, stroke=0)
        # Encontrar el número de la pieza (mismo orden que badges = orden L→R)
        sid = d.get("svg_id") or d.get("id") or ""
        num = next((n for (n, _cx, _cy, s) in piezas_canvas if s == sid), idx + 1)

        forma, info = _detectar_forma(d)
        if forma == "circulo":
            tipo_txt    = "Círculo"
            medidas_txt = f"Ø {info['diametro']:.{DECIMALES_COTA}f}"
        else:
            tipo_txt    = "Rectángulo"
            medidas_txt = (f"{d.get('alto_cm', 0):.{DECIMALES_COTA}f} × "
                           f"{d.get('ancho_cm', 0):.{DECIMALES_COTA}f}")
        perim_txt = f"{d.get('perimetro_cm', 0):.{DECIMALES_COTA}f}"

        if incluir_material:
            mat_nombre = d.get("material_cara_nombre", "—")
            mid        = d.get("material_cara_id") or ""
            valores    = [str(num), tipo_txt, medidas_txt, perim_txt, None, ""]
        else:
            valores = [str(num), tipo_txt, medidas_txt, perim_txt]

        c.setFillColor(colors.black)
        for j, txt in enumerate(valores):
            if txt is not None:
                c.drawString(cols_x[j] + 3, y_row + tr_h / 2 - FS_TABLE_TC / 2.4, str(txt))
            c.setStrokeColor(colors.HexColor("#d6dbe0"))
            c.setLineWidth(0.2)
            c.line(cols_x[j + 1], y_row, cols_x[j + 1], y_row + tr_h)
        # Columna Material (solo modo taller): bullet de color + nombre
        if incluir_material:
            bullet_x = cols_x[4] + 6
            text_x   = cols_x[4] + 12
            if mid and mid in mat_colors:
                c.setFillColor(colors.HexColor(mat_colors[mid]))
                c.circle(bullet_x, y_row + tr_h / 2, 2.6, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.drawString(text_x, y_row + tr_h / 2 - FS_TABLE_TC / 2.4, mat_nombre)
        y_row -= tr_h
        if y_row < y0 + 18:
            break

    # Notas al pie
    if notas:
        c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 8.5)
        c.drawString(mar_l, y0 + 8, "Notas:")
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 8.5)
        c.drawString(mar_l + 28, y0 + 8, notas[:180])


# ─── API pública ─────────────────────────────────────────────────────────────

def generar_plano_cliente(meta: dict, svg_text: str, paths_info: list,
                          viewbox_w: float, viewbox_h: float,
                          real_width_cm: float, altura_cm: float = 0.0,
                          result=None,
                          artboard_w_cm_hint: float = 0.0) -> bytes:
    """Plano de medidas para CLIENTE: dibujo + cotas globales y por pieza
    consolidadas. Si `result` está y el SVG tiene más de
    MAX_PIEZAS_COTA_DISEÑO piezas, las medidas individuales se mueven a
    una página 2 con listado tabular."""
    return _construir_pdf(meta, svg_text, paths_info, viewbox_w, viewbox_h,
                          real_width_cm, altura_cm,
                          titulo="PLANO DE MEDIDAS",
                          modo_taller=False, result=result,
                          artboard_w_cm_hint=artboard_w_cm_hint)


def generar_plano_taller(meta: dict, svg_text: str, paths_info: list,
                         viewbox_w: float, viewbox_h: float,
                         real_width_cm: float, altura_cm: float = 0.0,
                         result=None, notas: str = "",
                         artboard_w_cm_hint: float = 0.0) -> bytes:
    """Plano de medidas para TALLER: dibujo + cotas + tabla técnica de
    piezas con material por pieza + sección de notas al pie."""
    return _construir_pdf(meta, svg_text, paths_info, viewbox_w, viewbox_h,
                          real_width_cm, altura_cm,
                          titulo="PLANO TÉCNICO DE FABRICACIÓN",
                          modo_taller=True,
                          result=result, notas=notas,
                          artboard_w_cm_hint=artboard_w_cm_hint)
