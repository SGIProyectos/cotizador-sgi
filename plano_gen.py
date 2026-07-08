"""plano_gen.py — Plano de medidas v2 (cliente y taller).

API pública (misma firma que v1, main.py no cambia):
  - generar_plano_cliente(meta, svg_text, paths_info, viewbox_w, viewbox_h,
                          real_width_cm, altura_cm=0, result=None,
                          artboard_w_cm_hint=0) → bytes
  - generar_plano_taller (..., result, notas="") → bytes

Diseño v2 — estilo plano técnico:
  Página 1 (ambas versiones):
    · Dibujo a escala con cotas técnicas (flechas + líneas de extensión).
    · Cota global de ancho ARRIBA y de alto a la IZQUIERDA, siempre.
    · Diseños sencillos (≤ MAX_PIEZAS_COTAS piezas): cota de ancho por pieza
      ABAJO, empacadas en ≤ MAX_FILAS_COTA filas escalonadas sin solaparse
      (el empaque considera el ancho real del texto). Cotas de alto: una por
      ALTURA DISTINTA (≤ MAX_COLS_ALTO columnas a la izquierda).
      Si el empaque no cabe → cae automáticamente a modo complejo.
    · Diseños complejos: solo cotas globales + badges numerados; las medidas
      individuales van a la tabla.
    · Columna derecha: tabla de piezas (# · medidas · perímetro).
    · Cajetín (title block) abajo-derecha: folio, cliente, fecha, escala y
      (versión cliente) casilla de firma de aprobación.
  Página 2 (taller siempre; cliente solo si la tabla no cupo en la pág. 1):
    · Taller: LISTA DE MATERIALES (BOM) + tabla técnica por pieza
      (material con bullet de color + módulos LED) + perfil lateral de la
      cercha + notas de fabricación.
    · Cliente: continuación de la tabla de piezas en 2 columnas.

El dibujo se escala con el bbox CONJUNTO de las piezas conservadas, no con
el viewBox completo — para no quedar comprimido por el aire del artboard.
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
GRIS_LIGHT = colors.HexColor("#9aa3ad")
GRIS_TXT   = colors.HexColor("#555555")
GRIS_ZEBRA = colors.HexColor("#f3f5f8")
GRIS_BORDE = colors.HexColor("#c9d0d8")

LINE_COTA    = colors.HexColor("#1f2937")
LINE_EXT     = colors.HexColor("#b0b7c0")
LW_COTA      = 0.7
LW_EXT       = 0.4
ARROW_LEN_PT = 4.0
FONT_NAME    = "Helvetica"
FONT_BOLD    = "Helvetica-Bold"
FS_COTA      = 7.5

DECIMALES_COTA = 1           # 1 decimal en cotas del dibujo (legibilidad);
DECIMALES_TAB  = 2           # 2 decimales en la tabla (precisión de taller)

MAX_PIEZAS_COTAS = 20        # arriba de esto → solo cotas globales
MAX_FILAS_COTA   = 3         # filas escalonadas de cotas de ancho (abajo)
MAX_COLS_ALTO    = 2         # columnas de cotas de alto individuales (izq)
EPS_ALTURAS_CM   = 0.5       # alturas que difieren menos de esto = "iguales"

MARGEN     = 0.9 * cm
HEADER_H   = 1.45 * cm
PIE_H      = 0.45 * cm
COL_TABLA_W  = 6.6 * cm      # columna derecha (tabla + cajetín)
GAP_COL      = 0.5 * cm      # separación dibujo ↔ columna derecha
CAJETIN_H    = 3.5 * cm

# Bandas de cotas alrededor del dibujo
BANDA_TOP        = 30.0                       # cota global de ancho
FILA_COTA_PT     = 16.0                       # alto de cada fila de cotas de ancho
COL_ALTO_PT      = 17.0                       # ancho de cada columna de cotas de alto
GAP_DIBUJO_COTA  = 7.0                        # aire entre el dibujo y la 1ª cota

# Paleta para badges por material (mismo orden que pdf_gen._OT_MATERIAL_PALETTE)
_MAT_PALETTE = [
    "#1565C0", "#E65100", "#2E7D32", "#6A1B9A",
    "#C62828", "#00838F", "#558B2F", "#4527A0",
]


# ─── Helpers geométricos ─────────────────────────────────────────────────────

def _bbox_conjunto(paths_info: list) -> tuple[float, float, float, float]:
    cerrados = [p for p in paths_info if p.get("is_closed")]
    if not cerrados:
        return 0.0, 0.0, 0.0, 0.0
    xs0 = [p["bbox"]["x"] for p in cerrados]
    ys0 = [p["bbox"]["y"] for p in cerrados]
    xs1 = [p["bbox"]["x"] + p["bbox"]["w"] for p in cerrados]
    ys1 = [p["bbox"]["y"] + p["bbox"]["h"] for p in cerrados]
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _text_width(txt: str, font: str = FONT_NAME, size: float = FS_COTA) -> float:
    try:
        from reportlab.pdfbase import pdfmetrics
        return pdfmetrics.stringWidth(txt, font, size)
    except Exception:
        return len(txt) * size * 0.55


def _pack_intervalos(intervalos: list[tuple[int, float, float]],
                     max_filas: int,
                     pad: float = 5.0) -> dict[int, int]:
    """Empaca intervalos [a, b] en el mínimo de filas sin solaparse.

    `intervalos` = lista de (idx, a, b). Devuelve {idx: fila} con fila 0 la
    más cercana al dibujo. Los intervalos que no caben en `max_filas` filas
    se OMITEN del resultado (su medida queda cubierta por la tabla); nunca
    se pinta una cota encimada. Greedy por inicio de intervalo (interval
    graph coloring).
    """
    filas: list[float] = []          # x-final ocupado por fila
    out: dict[int, int] = {}
    for idx, a, b in sorted(intervalos, key=lambda t: t[1]):
        colocado = False
        for f, fin in enumerate(filas):
            if a >= fin + pad:
                filas[f] = b
                out[idx] = f
                colocado = True
                break
        if not colocado and len(filas) < max_filas:
            filas.append(b)
            out[idx] = len(filas) - 1
    return out


def _escala_bonita(ratio: float) -> str:
    """Redondea la escala a un valor "de plano" (1:5, 1:10, 1:20, 1:25...)."""
    if ratio <= 0:
        return "—"
    candidatos = [1, 2, 2.5, 5, 7.5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200]
    mejor = min(candidatos, key=lambda c: abs(c - ratio))
    if mejor == int(mejor):
        return f"1:{int(mejor)}"
    return f"1:{mejor}"


# ─── Primitivas de cota ──────────────────────────────────────────────────────

def _flecha(c, x: float, y: float, hacia: str, size: float = ARROW_LEN_PT) -> None:
    p = c.beginPath()
    if hacia == "izq":
        p.moveTo(x, y); p.lineTo(x + size, y + size * 0.42); p.lineTo(x + size, y - size * 0.42)
    elif hacia == "der":
        p.moveTo(x, y); p.lineTo(x - size, y + size * 0.42); p.lineTo(x - size, y - size * 0.42)
    elif hacia == "arr":
        p.moveTo(x, y); p.lineTo(x - size * 0.42, y + size); p.lineTo(x + size * 0.42, y + size)
    else:
        p.moveTo(x, y); p.lineTo(x - size * 0.42, y - size); p.lineTo(x + size * 0.42, y - size)
    p.close()
    c.setFillColor(LINE_COTA)
    c.drawPath(p, fill=1, stroke=0)


def _cota_h(c, x1: float, x2: float, y: float, valor_cm: float,
            dec: int = DECIMALES_COTA, bold: bool = False) -> None:
    """Cota horizontal: flechas a ambos extremos, valor centrado encima.
    Si el texto no cabe entre las flechas, se dibuja a un costado."""
    if x2 <= x1:
        return
    c.setStrokeColor(LINE_COTA); c.setLineWidth(LW_COTA)
    c.line(x1, y, x2, y)
    _flecha(c, x1, y, "der")
    _flecha(c, x2, y, "izq")
    txt = f"{valor_cm:.{dec}f}"
    font = FONT_BOLD if bold else FONT_NAME
    tw = _text_width(txt, font, FS_COTA)
    c.setFillColor(LINE_COTA); c.setFont(font, FS_COTA)
    if tw + 6 <= (x2 - x1):
        c.drawCentredString((x1 + x2) / 2, y + 1.6, txt)
    else:
        c.drawString(x2 + 3, y - FS_COTA * 0.35, txt)


def _cota_v(c, x: float, y1: float, y2: float, valor_cm: float,
            dec: int = DECIMALES_COTA, bold: bool = False) -> None:
    """Cota vertical: flechas y valor rotado 90° al costado izquierdo."""
    if y2 <= y1:
        return
    c.setStrokeColor(LINE_COTA); c.setLineWidth(LW_COTA)
    c.line(x, y1, x, y2)
    _flecha(c, x, y1, "arr")
    _flecha(c, x, y2, "aba")
    txt = f"{valor_cm:.{dec}f}"
    font = FONT_BOLD if bold else FONT_NAME
    c.setFillColor(LINE_COTA); c.setFont(font, FS_COTA)
    c.saveState()
    c.translate(x - 2.0, (y1 + y2) / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, txt)
    c.restoreState()


def _ext_v(c, x: float, y_a: float, y_b: float) -> None:
    if abs(y_b - y_a) < 0.5:
        return
    c.setStrokeColor(LINE_EXT); c.setLineWidth(LW_EXT)
    c.setDash(2, 2)
    c.line(x, y_a, x, y_b)
    c.setDash()


def _ext_h(c, x_a: float, x_b: float, y: float) -> None:
    if abs(x_b - x_a) < 0.5:
        return
    c.setStrokeColor(LINE_EXT); c.setLineWidth(LW_EXT)
    c.setDash(2, 2)
    c.line(x_a, y, x_b, y)
    c.setDash()


# ─── Render del SVG ──────────────────────────────────────────────────────────

def _render_svg(c, svg_text: str, ox: float, oy: float, scale: float,
                offset_x_svg: float, offset_y_svg: float,
                bbox_h_svg: float) -> bool:
    """Dibuja el SVG escalado; (ox, oy) es la esquina INFERIOR-izquierda del
    bbox conjunto en el canvas. svglib entrega el Drawing ya con Y hacia
    arriba (mapea SVG(x,y) → rlg(x, rlg.height - y))."""
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
    cx = ox + (x_svg - offset_x_svg) * scale
    cy = oy + bbox_h_svg * scale - (y_svg - offset_y_svg) * scale
    return cx, cy


# ─── Cabecera, pie y cajetín ─────────────────────────────────────────────────

def _dibujar_header(c, titulo: str, PW: float, PH: float, subtitulo: str = "") -> None:
    c.setFillColor(AZUL_DARK)
    c.rect(0, PH - HEADER_H, PW, HEADER_H, fill=1, stroke=0)
    cy = PH - HEADER_H / 2
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 16)
    c.drawString(MARGEN, cy - 5, "SGI")
    c.setFont(FONT_NAME, 8)
    c.drawString(MARGEN + 32, cy - 5, "Impresión y Diseño")
    c.setFont(FONT_BOLD, 13)
    c.drawCentredString(PW / 2, cy - 4.5, titulo)
    if subtitulo:
        c.setFont(FONT_NAME, 8)
        c.drawRightString(PW - MARGEN, cy - 4, subtitulo)


def _dibujar_pie(c, PW: float, texto_izq: str = "", texto_der: str = "") -> None:
    c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 7)
    if texto_izq:
        c.drawString(MARGEN, PIE_H * 0.5, texto_izq)
    if texto_der:
        c.drawRightString(PW - MARGEN, PIE_H * 0.5, texto_der)


def _dibujar_cajetin(c, x: float, y: float, w: float, h: float,
                     meta: dict, escala_txt: str,
                     totales_txt: str, con_firma: bool) -> None:
    """Cajetín estilo plano arquitectónico: rejilla de datos + firma opcional."""
    folio   = meta.get("folio")   or "—"
    cliente = meta.get("cliente") or "—"
    fecha   = meta.get("fecha")   or datetime.now().strftime("%d/%m/%Y")

    c.setStrokeColor(AZUL_DARK); c.setLineWidth(1.0)
    c.setFillColor(colors.white)
    c.rect(x, y, w, h, fill=1, stroke=1)

    # Franja de título
    tit_h = 14
    c.setFillColor(AZUL_DARK)
    c.rect(x, y + h - tit_h, w, tit_h, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 8)
    c.drawString(x + 5, y + h - tit_h + 4, "SGI · IMPRESIÓN Y DISEÑO")
    c.setFont(FONT_NAME, 7)
    c.drawRightString(x + w - 5, y + h - tit_h + 4, "Cotas en cm")

    filas = [
        ("Cliente", cliente),
        ("Folio",   folio),
        ("Fecha",   fecha),
        ("Medidas", totales_txt),
        ("Escala",  escala_txt),
    ]
    zona_h  = h - tit_h - (26 if con_firma else 0)
    fila_h  = zona_h / len(filas)
    y_f     = y + h - tit_h - fila_h
    lbl_w   = 42
    for lbl, val in filas:
        c.setStrokeColor(GRIS_BORDE); c.setLineWidth(0.4)
        c.line(x, y_f, x + w, y_f)
        c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 6.5)
        c.drawString(x + 5, y_f + fila_h / 2 - 2.5, lbl.upper())
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 8)
        val_s = str(val)
        while _text_width(val_s, FONT_NAME, 8) > w - lbl_w - 10 and len(val_s) > 4:
            val_s = val_s[:-2]
        c.drawString(x + lbl_w, y_f + fila_h / 2 - 2.8, val_s)
        y_f -= fila_h

    if con_firma:
        y_firma = y + 4
        c.setStrokeColor(colors.black); c.setLineWidth(0.6)
        lin_w = w * 0.52
        c.line(x + 8, y_firma + 10, x + 8 + lin_w, y_firma + 10)
        c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 6.5)
        c.drawString(x + 8, y_firma + 2, "APROBADO POR EL CLIENTE (firma)")
        c.line(x + w - 8 - w * 0.28, y_firma + 10, x + w - 8, y_firma + 10)
        c.drawString(x + w - 8 - w * 0.28, y_firma + 2, "FECHA")


# ─── Badges numerados ────────────────────────────────────────────────────────

def _materiales_to_color(result) -> dict:
    if not result:
        return {}
    mats: list[str] = []
    for d in (result.desglose_letras or []):
        mid = d.get("material_cara_id") or ""
        if mid and mid not in mats:
            mats.append(mid)
    return {m: _MAT_PALETTE[i % len(_MAT_PALETTE)] for i, m in enumerate(mats)}


def _dibujar_badges(c, piezas_canvas: list, mat_color_por_svgid: dict,
                    color_default: str = "#44506b") -> None:
    if not piezas_canvas:
        return
    font_pt = 8.5
    c.saveState()
    c.setFont(FONT_BOLD, font_pt)
    colocados: list[tuple[float, float]] = []
    for num, cx, cy, svg_id in piezas_canvas:
        color_hex = mat_color_por_svgid.get(svg_id, color_default)
        num_str = str(num)
        pill_w = font_pt * 0.55 * len(num_str) + font_pt * 0.9
        pill_h = font_pt * 1.5
        # anti-colisión: si pisa un badge ya colocado, desplazar en vertical
        def _choca(x, y, w=pill_w, h=pill_h):
            return any(abs(x - px) < w + 2 and abs(y - py) < h + 2
                       for px, py in colocados)
        if _choca(cx, cy):
            for despl in (1, -1, 2, -2, 3, -3):
                if not _choca(cx, cy + despl * (pill_h + 3)):
                    cy = cy + despl * (pill_h + 3)
                    break
        colocados.append((cx, cy))
        c.setFillColor(colors.HexColor(color_hex))
        c.setStrokeColor(colors.white); c.setLineWidth(0.7)
        c.roundRect(cx - pill_w / 2, cy - pill_h / 2,
                    pill_w, pill_h, pill_h / 2, fill=1, stroke=1)
        c.setFillColor(colors.white)
        c.drawCentredString(cx, cy - font_pt * 0.33, num_str)
    c.restoreState()


# ─── Formas y tabla de piezas ────────────────────────────────────────────────

def _detectar_forma(alto: float, ancho: float, perim: float) -> tuple[str, float]:
    """("circulo", diametro) si bbox≈cuadrado y perímetro≈π·d, si no ("rect", 0)."""
    if ancho <= 0 or alto <= 0 or perim <= 0:
        return "rect", 0.0
    aspect = min(ancho, alto) / max(ancho, alto)
    if aspect < 0.95:
        return "rect", 0.0
    d = (ancho + alto) / 2
    if abs(perim - math.pi * d) / (math.pi * d) < 0.10:
        return "circulo", d
    return "rect", 0.0


def _filas_tabla_piezas(piezas_num: list[dict]) -> list[tuple[str, str, str]]:
    """[(num, medidas, perímetro)] listas para pintar."""
    out = []
    for pz in piezas_num:
        forma, diam = _detectar_forma(pz["alto_cm"], pz["ancho_cm"], pz["perim_cm"])
        if forma == "circulo":
            med = f"Ø {diam:.{DECIMALES_TAB}f}"
        else:
            med = f"{pz['alto_cm']:.{DECIMALES_TAB}f} × {pz['ancho_cm']:.{DECIMALES_TAB}f}"
        out.append((str(pz["num"]), med, f"{pz['perim_cm']:.{DECIMALES_TAB}f}"))
    return out


def _dibujar_tabla_piezas(c, x: float, y_top: float, w: float, alto_disp: float,
                          filas: list[tuple[str, str, str]]) -> int:
    """Tabla compacta # · Medidas (cm) · Perím. Devuelve cuántas filas cupieron."""
    th = 13
    rh = 11.5
    c.setFillColor(AZUL_DARK)
    c.rect(x, y_top - th, w, th, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 7)
    cols = [0.12, 0.56, 0.32]
    cx = [x + w * sum(cols[:i]) for i in range(4)]
    for i, htxt in enumerate(["#", "Medidas (cm)", "Perím. (cm)"]):
        c.drawString(cx[i] + 3, y_top - th + 3.5, htxt)
    y = y_top - th - rh
    n_pintadas = 0
    c.setFont(FONT_NAME, 7.5)
    for i, (num, med, per) in enumerate(filas):
        if y < y_top - alto_disp:
            break
        if i % 2 == 0:
            c.setFillColor(GRIS_ZEBRA)
            c.rect(x, y, w, rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.drawString(cx[0] + 3, y + 3, num)
        c.drawString(cx[1] + 3, y + 3, med)
        c.drawString(cx[2] + 3, y + 3, per)
        y -= rh
        n_pintadas += 1
    c.setStrokeColor(GRIS_BORDE); c.setLineWidth(0.5)
    c.rect(x, y + rh, w, y_top - (y + rh), fill=0, stroke=1)
    return n_pintadas


# ─── BOM (lista de materiales, solo taller) ──────────────────────────────────

def _construir_bom(result) -> list[tuple[str, str, str]]:
    """[(concepto, especificación, cantidad)] a partir del QuoteResult."""
    bom: list[tuple[str, str, str]] = []
    if result is None:
        return bom
    dl = result.desglose_letras or []

    # Caras — agrupadas por material (adaptativo por pieza)
    caras: dict[str, dict] = {}
    for d in dl:
        nom = d.get("material_cara_nombre") or (result.material_cara or {}).get("nombre", "")
        if not nom:
            continue
        g = caras.setdefault(nom, {"area": 0.0, "n": 0})
        g["area"] += float(d.get("area_bbox_cm2", 0) or 0)
        g["n"]    += 1
    if caras:
        for nom, g in caras.items():
            bom.append(("Cara", nom,
                        f"{g['area'] / 10000:.2f} m² · {g['n']} pza(s)"))
    elif (result.material_cara or {}).get("nombre"):
        bom.append(("Cara", result.material_cara["nombre"],
                    f"{result.area_cara_cm2 / 10000:.2f} m²"))
    if result.laminas_cara:
        bom.append(("", "Láminas de cara estimadas (122×244)", f"{result.laminas_cara} lám."))

    # Cercha (letras) / Sercha (caja)
    es_caja = getattr(result, "tipo", "") == "caja_luz"
    if result.cercha_area_cm2 > 0 and (result.material_cercha or {}).get("nombre"):
        ml = result.perimetro_total_cm / 100 * (1.0 if es_caja else 1.10)
        bom.append(("Sercha" if es_caja else "Cercha",
                    f"{result.material_cercha['nombre']} · "
                    f"prof. {result.cercha_altura_cm:.0f} cm",
                    f"{ml:.1f} m" + ("" if es_caja else " (+10% merma)")))
        if result.laminas_cercha:
            bom.append(("", "Láminas estimadas", f"{result.laminas_cercha} lám."))

    # Gráfico de caja: vinil de corte (cuadro) — el diseño NO se lista letra
    # por letra, se corta como un solo rectángulo de rollo
    cuadro = (result.material_cara or {}).get("cuadro_corte") if es_caja else None
    if cuadro:
        bom.append(("Gráfico",
                    f"Vinil de corte {cuadro.get('vinil_nombre', '')} — cuadro "
                    f"{cuadro['ancho_cm']:.0f} × {cuadro['alto_cm']:.0f} cm",
                    f"{cuadro.get('ml_rollo', 0):.2f} m de rollo"))

    # Cableado (caja): misma fórmula que cotizar_caja
    if es_caja:
        metros_led = max(5.0, round(result.perimetro_total_cm / 100 * 1.2, 1))
        bom.append(("Cableado", "Cable LED Radox cal 22 + POT cal 18",
                    f"{metros_led:.1f} m + 5 m"))

    # Fondo
    if result.costo_material_fondo > 0 and (result.material_fondo or {}).get("nombre"):
        bom.append(("Fondo", result.material_fondo["nombre"],
                    f"{result.area_cara_cm2 / 10000:.2f} m²"))

    # Iluminación
    if result.modulos_led > 0:
        bom.append(("Iluminación", (result.led or {}).get("nombre", "Módulos LED"),
                    f"{result.modulos_led} módulos · {result.watts_total:.0f} W"))
        f_nom = (result.fuente or {}).get("nombre", "")
        if f_nom and f_nom != "Sin fuente de poder":
            bom.append(("", f_nom, "1 pza"))

    # Pegamento
    peg = (result.pegamento or {}).get("nombre", "")
    if peg and result.costo_pegamento > 0:
        bom.append(("Pegamento", peg,
                    f"≈ {result.perimetro_total_cm / 100:.1f} m de cordón"))

    # Silvatrim
    if result.metros_silvatrim > 0 and (result.silvatrim or {}).get("nombre"):
        bom.append(("Acabado", result.silvatrim["nombre"],
                    f"{result.metros_silvatrim:.1f} m"))

    # Vinil en cercha
    if result.metros_vinil_cercha > 0 and (result.vinil_cercha or {}).get("nombre"):
        bom.append(("Acabado", result.vinil_cercha["nombre"],
                    f"{result.metros_vinil_cercha:.1f} m"))

    # Distanciadores (retro_halo)
    comp = result.desglose_costos_componentes or {}
    if comp.get("distanciadores", 0) > 0:
        bom.append(("Montaje", "Kit de distanciadores de pared (halo)",
                    f"{len(dl)} kit(s)"))
    return bom


def _dibujar_bom(c, x: float, y_top: float, w: float,
                 bom: list[tuple[str, str, str]]) -> float:
    """Tabla BOM. Devuelve la Y final (borde inferior)."""
    th = 15
    rh = 13
    c.setFillColor(AZUL_DARK)
    c.rect(x, y_top - th, w, th, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 8)
    cols = [0.16, 0.54, 0.30]
    cx = [x + w * sum(cols[:i]) for i in range(4)]
    for i, htxt in enumerate(["Concepto", "Material / Especificación", "Cantidad"]):
        c.drawString(cx[i] + 4, y_top - th + 4, htxt)
    y = y_top - th - rh
    for i, (concepto, espec, cant) in enumerate(bom):
        if i % 2 == 0:
            c.setFillColor(GRIS_ZEBRA)
            c.rect(x, y, w, rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(FONT_BOLD, 7.5)
        c.drawString(cx[0] + 4, y + 3.5, concepto)
        c.setFont(FONT_NAME, 7.5)
        c.drawString(cx[1] + 4, y + 3.5, espec[:70])
        c.drawString(cx[2] + 4, y + 3.5, cant)
        y -= rh
    c.setStrokeColor(GRIS_BORDE); c.setLineWidth(0.5)
    c.rect(x, y + rh, w, y_top - (y + rh), fill=0, stroke=1)
    return y + rh


# ─── Perfil lateral de cercha (taller) ───────────────────────────────────────

def _dibujar_perfil_cercha(c, x: float, y: float, w: float, h: float,
                           result) -> None:
    """Esquema lateral: pared, fondo/distanciador, cercha (profundidad) y cara."""
    tc = result.tipo_construccion or "cajon_luz"
    prof = result.cercha_altura_cm or 10
    es_halo = (tc == "retro_halo")
    tiene_fondo = result.costo_material_fondo > 0
    tiene_luz = result.modulos_led > 0

    c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 8)
    c.drawString(x, y + h - 8, "PERFIL LATERAL (esquema, sin escala)")

    # Zona de dibujo
    zx, zy = x + 10, y + 6
    zw, zh = w - 20, h - 26

    # Pared (derecha) con hachurado
    px = zx + zw - 8
    c.setStrokeColor(colors.black); c.setLineWidth(1.2)
    c.line(px, zy, px, zy + zh)
    c.setLineWidth(0.5)
    for i in range(int(zh // 7)):
        yy = zy + i * 7
        c.line(px, yy, px + 7, yy + 5)

    letra_h = zh * 0.72
    letra_y = zy + (zh - letra_h) / 2
    canal_w = zw * 0.34                       # profundidad de la cercha en el esquema
    gap_w   = zw * 0.14 if es_halo else 0     # separación de pared (halo)
    cara_x  = px - gap_w - canal_w

    # Distanciadores (halo): dos pernos
    if es_halo and gap_w > 0:
        c.setStrokeColor(GRIS_TXT); c.setLineWidth(2.0)
        for fy in (letra_y + letra_h * 0.22, letra_y + letra_h * 0.78):
            c.line(px - gap_w, fy, px, fy)

    # Fondo (si aplica): placa pegada a la parte trasera del canal
    trasera_x = px - gap_w
    c.setStrokeColor(colors.black); c.setLineWidth(1.0)
    if tiene_fondo:
        c.setFillColor(colors.HexColor("#e8e8e8"))
        c.rect(trasera_x - 3, letra_y, 3, letra_h, fill=1, stroke=1)

    # Cercha: paredes superior/inferior del canal
    c.setFillColor(colors.white)
    c.rect(cara_x, letra_y, canal_w, letra_h, fill=0, stroke=1)

    # Cara: placa al frente
    c.setFillColor(colors.HexColor("#cfe3f7"))
    c.rect(cara_x - 3.5, letra_y - 1.5, 3.5, letra_h + 3, fill=1, stroke=1)

    # LEDs
    if tiene_luz:
        c.setFillColor(colors.HexColor("#f9a825"))
        if es_halo:
            for fy in (letra_y + 4, letra_y + letra_h - 4):
                c.circle(trasera_x - 5, fy, 2.2, fill=1, stroke=0)
        else:
            for k in range(3):
                fy = letra_y + letra_h * (0.25 + 0.25 * k)
                c.circle(trasera_x - 5, fy, 2.2, fill=1, stroke=0)

    # Cota de profundidad del canal
    y_cota = letra_y - 9
    _cota_h(c, cara_x, cara_x + canal_w, y_cota, prof, dec=0)
    c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 6.5)
    c.drawString(cara_x - 3.5, letra_y + letra_h + 5, "cara")
    if es_halo:
        c.drawString(px - gap_w + 2, letra_y + letra_h + 5, "sep. pared")
    c.drawRightString(px + 7, zy - 1, "muro")


# ─── Núcleo común ────────────────────────────────────────────────────────────

def _construir_pdf(meta: dict, svg_text: str, paths_info: list,
                   viewbox_w: float, viewbox_h: float,
                   real_width_cm: float, altura_cm: float,
                   titulo: str, modo_taller: bool,
                   result=None, notas: str = "",
                   artboard_w_cm_hint: float = 0.0) -> bytes:
    PW, PH = landscape(letter)
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=landscape(letter))

    piezas_todas = [p for p in paths_info if p.get("is_closed")]
    # los huecos (contadores de letra, placa de fondo) se dibujan pero no se
    # numeran, ni llevan cota, ni entran a la tabla
    piezas = [p for p in piezas_todas if not p.get("es_hueco")] or piezas_todas
    if not piezas:
        _dibujar_header(c, titulo, PW, PH)
        c.setFillColor(colors.HexColor("#b00020")); c.setFont(FONT_BOLD, 12)
        c.drawCentredString(PW / 2, PH / 2, "No se detectaron piezas cerradas en el SVG.")
        c.save()
        return buf.getvalue()

    # escala/encuadre con TODAS las piezas cerradas (mismo contrato que main.py,
    # que pasa altura_cm = alto del bbox conjunto de las cerradas)
    minX, minY, maxX, maxY = _bbox_conjunto(piezas_todas)
    bbox_w_svg = maxX - minX
    bbox_h_svg = maxY - minY
    if bbox_w_svg <= 0 or bbox_h_svg <= 0:
        c.save()
        return buf.getvalue()

    # cm reales por unidad SVG (altura_cm = alto del bbox CONJUNTO, así lo pasa main.py)
    if altura_cm > 0:
        cm_per_unit = altura_cm / bbox_h_svg
    elif real_width_cm > 0:
        cm_per_unit = real_width_cm / bbox_w_svg
    elif artboard_w_cm_hint > 0 and viewbox_w > 0:
        cm_per_unit = artboard_w_cm_hint / viewbox_w
    else:
        cm_per_unit = 1.0

    n_piezas = len(piezas)
    modo_simple = n_piezas <= MAX_PIEZAS_COTAS

    # ── Geometría de la página 1 ─────────────────────────────────────────────
    banda_bot = (GAP_DIBUJO_COTA + MAX_FILAS_COTA * FILA_COTA_PT + 4) if modo_simple else 10
    # nº de alturas distintas (para reservar columnas de cotas de alto)
    alturas_cm = sorted({round(p["bbox"]["h"] * cm_per_unit / EPS_ALTURAS_CM)
                         for p in piezas})
    n_cols_alto = min(len(alturas_cm), MAX_COLS_ALTO) if modo_simple else 0
    # la global de alto siempre existe (columna más externa)
    banda_izq = GAP_DIBUJO_COTA + (n_cols_alto + 1) * COL_ALTO_PT + 4

    area_x0 = MARGEN + banda_izq
    area_y0 = MARGEN + PIE_H + banda_bot
    area_x1 = PW - MARGEN - COL_TABLA_W - GAP_COL
    area_y1 = PH - HEADER_H - MARGEN - BANDA_TOP
    area_w, area_h = area_x1 - area_x0, area_y1 - area_y0

    scale_draw = min(area_w / bbox_w_svg, area_h / bbox_h_svg)
    dibujo_w = bbox_w_svg * scale_draw
    dibujo_h = bbox_h_svg * scale_draw
    ox = area_x0 + (area_w - dibujo_w) / 2
    oy = area_y0 + (area_h - dibujo_h) / 2

    _dibujar_header(c, titulo, PW, PH,
                    subtitulo=f"{n_piezas} pieza(s)")
    _render_svg(c, svg_text, ox, oy, scale_draw, minX, minY, bbox_h_svg)

    # ── Posiciones canvas + medidas por pieza ────────────────────────────────
    datos: list[dict] = []
    for p in piezas:
        bb = p["bbox"]
        x_l, y_top = _svg_to_canvas_xy(bb["x"], bb["y"], ox, oy, scale_draw,
                                       minX, minY, bbox_h_svg)
        x_r, y_bot = _svg_to_canvas_xy(bb["x"] + bb["w"], bb["y"] + bb["h"],
                                       ox, oy, scale_draw, minX, minY, bbox_h_svg)
        datos.append({
            "svg_id":   p.get("svg_id") or p.get("id") or "",
            "x_l": x_l, "x_r": x_r, "y_bot": y_bot, "y_top": y_top,
            "cx": (x_l + x_r) / 2, "cy": (y_bot + y_top) / 2,
            "ancho_cm": bb["w"] * cm_per_unit,
            "alto_cm":  bb["h"] * cm_per_unit,
            "perim_cm": 0.0,
        })
    # perímetro real desde desglose (si hay result); fallback bbox
    perim_por_sid = {}
    for d in (result.desglose_letras or []) if result else []:
        sid = d.get("svg_id") or d.get("id") or ""
        if sid:
            perim_por_sid[sid] = float(d.get("perimetro_cm", 0) or 0)
    for dz in datos:
        dz["perim_cm"] = perim_por_sid.get(
            dz["svg_id"], 2 * (dz["ancho_cm"] + dz["alto_cm"]))

    # numeración L→R (y arriba→abajo como desempate)
    orden = sorted(range(n_piezas), key=lambda i: (datos[i]["x_l"], -datos[i]["y_top"]))
    for n, i in enumerate(orden, start=1):
        datos[i]["num"] = n
    piezas_num = sorted(datos, key=lambda d: d["num"])

    # ── Cotas ────────────────────────────────────────────────────────────────
    bbox_w_cm = bbox_w_svg * cm_per_unit
    bbox_h_cm = bbox_h_svg * cm_per_unit
    dib_x_l, dib_x_r = ox, ox + dibujo_w
    dib_y_b, dib_y_t = oy, oy + dibujo_h

    # Global ancho — arriba
    y_gw = dib_y_t + BANDA_TOP * 0.55
    _ext_v(c, dib_x_l, dib_y_t + 2, y_gw)
    _ext_v(c, dib_x_r, dib_y_t + 2, y_gw)
    _cota_h(c, dib_x_l, dib_x_r, y_gw, bbox_w_cm, bold=True)

    # Global alto — columna más externa a la izquierda
    x_gh = area_x0 - banda_izq + COL_ALTO_PT * 0.5
    _ext_h(c, x_gh, dib_x_l - 2, dib_y_b)
    _ext_h(c, x_gh, dib_x_l - 2, dib_y_t)
    _cota_v(c, x_gh, dib_y_b, dib_y_t, bbox_h_cm, bold=True)

    cotas_individuales = False
    if modo_simple:
        # Anchos por pieza — abajo, empacados en filas
        intervalos = []
        for i, dz in enumerate(datos):
            lbl_w = _text_width(f"{dz['ancho_cm']:.{DECIMALES_COTA}f}") + 8
            half = max((dz["x_r"] - dz["x_l"]), lbl_w) / 2
            intervalos.append((i, dz["cx"] - half, dz["cx"] + half))
        filas_w = _pack_intervalos(intervalos, MAX_FILAS_COTA)

        # Altos por pieza — una cota por altura DISTINTA, columnas a la izquierda
        alturas_vistas: dict[int, int] = {}   # clave de altura → idx representante
        for i, dz in enumerate(datos):
            k = round(dz["alto_cm"] / EPS_ALTURAS_CM)
            if k not in alturas_vistas:
                alturas_vistas[k] = i
        reps = list(alturas_vistas.values())
        # si solo hay 1 altura distinta y ≈ igual a la global, la global basta
        omitir_altos = (len(reps) == 1 and
                        abs(datos[reps[0]]["alto_cm"] - bbox_h_cm) < EPS_ALTURAS_CM)
        cols_h: dict[int, int] = {}
        if not omitir_altos:
            iv_h = []
            for i in reps:
                dz = datos[i]
                lbl_h = _text_width(f"{dz['alto_cm']:.{DECIMALES_COTA}f}") + 8
                half = max((dz["y_top"] - dz["y_bot"]), lbl_h) / 2
                cy = (dz["y_top"] + dz["y_bot"]) / 2
                iv_h.append((i, cy - half, cy + half))
            cols_h = _pack_intervalos(iv_h, MAX_COLS_ALTO)

        # anchos y altos son independientes: si un empaque no cabe, el otro
        # se pinta igual (la tabla siempre trae todas las medidas)
        if filas_w:
            cotas_individuales = True
            for i, fila in filas_w.items():
                dz = datos[i]
                y_c = dib_y_b - GAP_DIBUJO_COTA - fila * FILA_COTA_PT - 6
                _ext_v(c, dz["x_l"], dz["y_bot"] - 2, y_c)
                _ext_v(c, dz["x_r"], dz["y_bot"] - 2, y_c)
                _cota_h(c, dz["x_l"], dz["x_r"], y_c, dz["ancho_cm"])
        if cols_h:
            cotas_individuales = True
            for i, col in cols_h.items():
                dz = datos[i]
                x_c = dib_x_l - GAP_DIBUJO_COTA - (col + 1) * COL_ALTO_PT + COL_ALTO_PT * 0.4
                _ext_h(c, x_c, dz["x_l"] - 2, dz["y_bot"])
                _ext_h(c, x_c, dz["x_l"] - 2, dz["y_top"])
                _cota_v(c, x_c, dz["y_bot"], dz["y_top"], dz["alto_cm"])

    # ── Badges ───────────────────────────────────────────────────────────────
    mat_colors = _materiales_to_color(result)
    mat_color_por_svgid: dict[str, str] = {}
    for d in (result.desglose_letras or []) if result else []:
        sid = d.get("svg_id") or d.get("id") or ""
        mid = d.get("material_cara_id") or ""
        if sid and mid:
            mat_color_por_svgid[sid] = mat_colors.get(mid, "#44506b")
    piezas_canvas = [(dz["num"], dz["cx"], dz["cy"], dz["svg_id"])
                     for dz in piezas_num]
    _dibujar_badges(c, piezas_canvas, mat_color_por_svgid)

    # ── Columna derecha: tabla de piezas + cajetín ───────────────────────────
    col_x = PW - MARGEN - COL_TABLA_W
    tabla_top = PH - HEADER_H - MARGEN
    tabla_alto_disp = tabla_top - (MARGEN + PIE_H + CAJETIN_H + 10)
    filas_tabla = _filas_tabla_piezas(piezas_num)
    n_pintadas = _dibujar_tabla_piezas(c, col_x, tabla_top, COL_TABLA_W,
                                       tabla_alto_disp, filas_tabla)
    faltan = len(filas_tabla) - n_pintadas
    if faltan > 0:
        c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 7)
        c.drawString(col_x + 3, MARGEN + PIE_H + CAJETIN_H + 2,
                     f"... y {faltan} pieza(s) más en la página 2")

    # Cajetín
    # escala = cm reales por cm de papel: (cm_real/unidad) / (cm_papel/unidad)
    ratio = (cm_per_unit * cm / scale_draw) if scale_draw > 0 else 0
    escala_txt = _escala_bonita(ratio)
    totales_txt = f"{bbox_w_cm:.1f} × {bbox_h_cm:.1f} cm (ancho × alto)"
    _dibujar_cajetin(c, col_x, MARGEN + PIE_H, COL_TABLA_W, CAJETIN_H,
                     meta, escala_txt, totales_txt, con_firma=not modo_taller)

    nota_cotas = ("Cotas por pieza en el dibujo" if cotas_individuales
                  else "Medidas por pieza: ver tabla")
    hay_pag2 = modo_taller or faltan > 0
    _dibujar_pie(c, PW,
                 texto_izq=f"Página 1 de {2 if hay_pag2 else 1}",
                 texto_der=f"Escala {escala_txt} · Cotas en cm · {nota_cotas}")

    # ── Página 2 ─────────────────────────────────────────────────────────────
    if hay_pag2:
        c.showPage()
        if modo_taller:
            _pagina_taller(c, PW, PH, meta, result, piezas_num,
                           mat_colors, notas)
        else:
            _pagina_listado_cliente(c, PW, PH, meta, piezas_num)
        _dibujar_pie(c, PW, texto_izq="Página 2 de 2")

    c.save()
    return buf.getvalue()


# ─── Página 2 cliente: continuación del listado ──────────────────────────────

def _pagina_listado_cliente(c, PW: float, PH: float, meta: dict,
                            piezas_num: list[dict]) -> None:
    _dibujar_header(c, "LISTADO DE MEDIDAS POR PIEZA", PW, PH,
                    subtitulo=f"Folio: {meta.get('folio') or '—'}")
    filas = _filas_tabla_piezas(piezas_num)
    top = PH - HEADER_H - MARGEN
    alto = top - (MARGEN + PIE_H)
    col_w = (PW - 2 * MARGEN - GAP_COL) / 2
    cap = int((alto - 13) // 11.5)
    _dibujar_tabla_piezas(c, MARGEN, top, col_w, alto, filas[:cap])
    if len(filas) > cap:
        _dibujar_tabla_piezas(c, MARGEN + col_w + GAP_COL, top, col_w,
                              alto, filas[cap:cap * 2])


# ─── Página 2 taller: BOM + tabla técnica + perfil + notas ───────────────────

def _pagina_taller(c, PW: float, PH: float, meta: dict, result,
                   piezas_num: list[dict], mat_colors: dict,
                   notas: str) -> None:
    _dibujar_header(c, "TALLER — MATERIALES Y FABRICACIÓN", PW, PH,
                    subtitulo=f"Folio: {meta.get('folio') or '—'}")
    top = PH - HEADER_H - MARGEN
    mitad_w = (PW - 2 * MARGEN - GAP_COL) / 2

    # Izquierda: BOM
    c.setFillColor(AZUL_DARK); c.setFont(FONT_BOLD, 10)
    c.drawString(MARGEN, top - 9, "LISTA DE MATERIALES")
    bom = _construir_bom(result)
    y_bom_final = top - 16
    if bom:
        y_bom_final = _dibujar_bom(c, MARGEN, top - 16, mitad_w, bom)

    # Izquierda abajo: perfil de cercha (solo letras con cercha)
    if result is not None and result.cercha_area_cm2 > 0:
        perfil_h = 100
        y_perfil = y_bom_final - perfil_h - 14
        if y_perfil > MARGEN + PIE_H + 20:
            _dibujar_perfil_cercha(c, MARGEN, y_perfil, mitad_w * 0.75,
                                   perfil_h, result)

    # Derecha: tabla técnica por pieza
    x_der = MARGEN + mitad_w + GAP_COL
    c.setFillColor(AZUL_DARK); c.setFont(FONT_BOLD, 10)
    c.drawString(x_der, top - 9, "PIEZAS A FABRICAR")
    _dibujar_tabla_tecnica(c, x_der, top - 16, mitad_w,
                           top - 16 - (MARGEN + PIE_H + (26 if notas else 8)),
                           result, piezas_num, mat_colors)

    # Notas al pie (ancho completo)
    if notas:
        c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 8)
        c.drawString(MARGEN, MARGEN + PIE_H + 8, "NOTAS:")
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 8)
        c.drawString(MARGEN + 38, MARGEN + PIE_H + 8, notas[:200])


def _dibujar_tabla_tecnica(c, x: float, y_top: float, w: float,
                           alto_disp: float, result,
                           piezas_num: list[dict], mat_colors: dict) -> None:
    """Tabla taller: # · Medidas · Perím · Material · LEDs."""
    dl_por_sid = {}
    for d in (result.desglose_letras or []) if result else []:
        sid = d.get("svg_id") or d.get("id") or ""
        if sid:
            dl_por_sid[sid] = d

    th = 14
    n = len(piezas_num)
    rh = max(10.5, min(14, (alto_disp - th) / max(n, 1)))
    cols = [0.07, 0.26, 0.15, 0.38, 0.14]
    cx = [x + w * sum(cols[:i]) for i in range(6)]
    c.setFillColor(AZUL_DARK)
    c.rect(x, y_top - th, w, th, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 7)
    for i, htxt in enumerate(["#", "Medidas (cm)", "Perím.", "Material cara", "LEDs"]):
        c.drawString(cx[i] + 3, y_top - th + 4, htxt)
    y = y_top - th - rh
    for k, pz in enumerate(piezas_num):
        if y < y_top - alto_disp:
            c.setFillColor(GRIS_TXT); c.setFont(FONT_NAME, 7)
            c.drawString(x + 3, y + rh - 8, f"... y {n - k} pieza(s) más")
            break
        if k % 2 == 0:
            c.setFillColor(GRIS_ZEBRA)
            c.rect(x, y, w, rh, fill=1, stroke=0)
        d = dl_por_sid.get(pz["svg_id"], {})
        forma, diam = _detectar_forma(pz["alto_cm"], pz["ancho_cm"], pz["perim_cm"])
        med = (f"Ø {diam:.{DECIMALES_TAB}f}" if forma == "circulo"
               else f"{pz['alto_cm']:.{DECIMALES_TAB}f} × {pz['ancho_cm']:.{DECIMALES_TAB}f}")
        mat_nom = d.get("material_cara_nombre") or "—"
        mid     = d.get("material_cara_id") or ""
        leds    = d.get("n_modulos_led", 0)
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 7.5)
        c.drawString(cx[0] + 3, y + rh / 2 - 3, str(pz["num"]))
        c.drawString(cx[1] + 3, y + rh / 2 - 3, med)
        c.drawString(cx[2] + 3, y + rh / 2 - 3, f"{pz['perim_cm']:.1f}")
        if mid and mid in mat_colors:
            c.setFillColor(colors.HexColor(mat_colors[mid]))
            c.circle(cx[3] + 6, y + rh / 2, 2.4, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.drawString(cx[3] + 11, y + rh / 2 - 3, mat_nom[:32])
        else:
            c.drawString(cx[3] + 3, y + rh / 2 - 3, mat_nom[:34])
        c.drawString(cx[4] + 3, y + rh / 2 - 3, str(leds) if leds else "—")
        y -= rh
    c.setStrokeColor(GRIS_BORDE); c.setLineWidth(0.5)
    c.rect(x, y + rh, w, y_top - (y + rh), fill=0, stroke=1)


# ─── Plano de CAJA DE LUZ ────────────────────────────────────────────────────
# La caja se planifica como UNA pieza (regla del propietario): sin numerar el
# diseño letra por letra. Cotas: ancho y alto de la caja; si el gráfico es
# vinil de corte, el CUADRO DE CORTE punteado con sus medidas y su posición
# desde los bordes (para que el instalador centre el vinil).

def _dims_caja_cm(result) -> tuple[float, float]:
    """Ancho y alto reales de la caja despejados de P = 2(w+h) y A = w·h."""
    try:
        s = (result.perimetro_total_cm or 0) / 2
        a = result.area_cara_cm2 or 0
        disc = s * s - 4 * a
        if s <= 0 or a <= 0 or disc < 0:
            return 0.0, 0.0
        r = disc ** 0.5
        return (s + r) / 2, (s - r) / 2
    except Exception:
        return 0.0, 0.0


def _outline_y_diseno(paths_info: list):
    """(bbox_caja, bbox_diseño, piezas_diseño) en coords SVG.
    Caja = pieza cerrada cuyo bbox cubre ≥80% del bbox conjunto (la placa
    exterior); diseño = las demás cerradas no-hueco."""
    cerradas = [p for p in paths_info if p.get("is_closed")]
    if not cerradas:
        return None, None, []
    minX, minY, maxX, maxY = _bbox_conjunto(cerradas)
    area_total = (maxX - minX) * (maxY - minY)
    outline, best = None, 0.0
    for p in cerradas:
        bb = p["bbox"]
        a = bb["w"] * bb["h"]
        if area_total > 0 and a / area_total >= 0.8 and a > best:
            outline, best = p, a
    if outline is not None:
        caja = dict(outline["bbox"])
        diseno_p = [p for p in cerradas
                    if p is not outline and not p.get("es_hueco")]
    else:
        caja = {"x": minX, "y": minY, "w": maxX - minX, "h": maxY - minY}
        diseno_p = [p for p in cerradas if not p.get("es_hueco")]
    if diseno_p:
        dx0 = min(p["bbox"]["x"] for p in diseno_p)
        dy0 = min(p["bbox"]["y"] for p in diseno_p)
        dx1 = max(p["bbox"]["x"] + p["bbox"]["w"] for p in diseno_p)
        dy1 = max(p["bbox"]["y"] + p["bbox"]["h"] for p in diseno_p)
        diseno = {"x": dx0, "y": dy0, "w": dx1 - dx0, "h": dy1 - dy0}
    else:
        diseno = None
    return caja, diseno, diseno_p


def _filas_diseno(diseno: list) -> list[dict]:
    """Agrupa el diseño en RENGLONES (franjas horizontales que se solapan en Y)
    y devuelve el bbox de cada renglón, de arriba hacia abajo. El taller
    necesita cota por renglón ("CFE" arriba, "COMISIÓN FEDERAL" abajo…),
    no solo el cuadro global."""
    if not diseno:
        return []
    orden = sorted(diseno, key=lambda p: p["bbox"]["y"])
    filas: list[list[dict]] = [[orden[0]]]
    fondo = orden[0]["bbox"]["y"] + orden[0]["bbox"]["h"]
    for p in orden[1:]:
        if p["bbox"]["y"] <= fondo:          # solapa en Y → mismo renglón
            filas[-1].append(p)
            fondo = max(fondo, p["bbox"]["y"] + p["bbox"]["h"])
        else:
            filas.append([p])
            fondo = p["bbox"]["y"] + p["bbox"]["h"]
    out = []
    for grupo in filas:
        x0 = min(p["bbox"]["x"] for p in grupo)
        y0 = min(p["bbox"]["y"] for p in grupo)
        x1 = max(p["bbox"]["x"] + p["bbox"]["w"] for p in grupo)
        y1 = max(p["bbox"]["y"] + p["bbox"]["h"] for p in grupo)
        out.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return out


def _ficha_caja(result, caja_w: float, caja_h: float,
                pos_x_cm: float, pos_y_cm: float,
                filas_cm: list[tuple[float, float]] | None = None) -> list[tuple[str, str]]:
    """Filas (etiqueta, valor) de la ficha de la caja para tabla lateral."""
    prof = result.cercha_altura_cm or 0
    cuadro = (result.material_cara or {}).get("cuadro_corte")
    filas = [
        ("Caja",        f"{caja_w:.1f} × {caja_h:.1f} cm"),
        ("Profundidad", f"{prof:.0f} cm"),
        ("Cara",        (result.material_cara or {}).get("nombre", "—")),
        ("Sercha",      (result.material_cercha or {}).get("nombre", "—")),
        ("Fondo",       (result.material_fondo or {}).get("nombre", "—")),
    ]
    if cuadro:
        filas.append(("Cuadro corte",
                      f"{cuadro['ancho_cm']:.1f} × {cuadro['alto_cm']:.1f} cm"))
        filas.append(("Vinil",
                      f"{cuadro.get('vinil_nombre', '—')} · "
                      f"{cuadro.get('ml_rollo', 0):.2f} m rollo"))
        if pos_x_cm >= 0 and pos_y_cm >= 0:
            filas.append(("Posición",
                          f"{pos_x_cm:.1f} cm izq · {pos_y_cm:.1f} cm arriba"))
    # medidas por renglón del diseño (ancho × alto) — máx. 5 en la ficha
    for i, (w_cm, h_cm) in enumerate((filas_cm or [])[:5], start=1):
        filas.append((f"Renglón {i}", f"{w_cm:.1f} × {h_cm:.1f} cm"))
    if filas_cm and len(filas_cm) > 5:
        filas.append(("", f"… y {len(filas_cm) - 5} renglón(es) más"))
    if result.modulos_led > 0:
        filas.append(("Iluminación",
                      f"{result.modulos_led} × {(result.led or {}).get('nombre', 'LED')}"))
    return filas


def _dibujar_ficha_caja(c, x: float, y_top: float, w: float,
                        filas: list[tuple[str, str]]) -> None:
    th, rh = 15, 15
    c.setFillColor(AZUL_DARK)
    c.rect(x, y_top - th, w, th, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD, 8)
    c.drawString(x + 4, y_top - th + 4, "CAJA DE LUZ — 1 PIEZA")
    y = y_top - th - rh
    for i, (lbl, val) in enumerate(filas):
        if i % 2 == 0:
            c.setFillColor(GRIS_ZEBRA)
            c.rect(x, y, w, rh, fill=1, stroke=0)
        c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 6.5)
        c.drawString(x + 4, y + rh - 7, lbl.upper())
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 7.5)
        val_s = str(val)
        while _text_width(val_s, FONT_NAME, 7.5) > w - 8 and len(val_s) > 4:
            val_s = val_s[:-2]
        c.drawString(x + 4, y + 2.5, val_s)
        y -= rh
    c.setStrokeColor(GRIS_BORDE); c.setLineWidth(0.5)
    c.rect(x, y + rh, w, y_top - (y + rh), fill=0, stroke=1)


def _construir_pdf_caja(meta: dict, svg_text: str, paths_info: list,
                        titulo: str, modo_taller: bool,
                        result, notas: str = "") -> bytes:
    PW, PH = landscape(letter)
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=landscape(letter))

    caja_bb, dis_bb, diseno_p = _outline_y_diseno(paths_info)
    if caja_bb is None or caja_bb["w"] <= 0 or caja_bb["h"] <= 0:
        _dibujar_header(c, titulo, PW, PH)
        c.setFillColor(colors.HexColor("#b00020")); c.setFont(FONT_BOLD, 12)
        c.drawCentredString(PW / 2, PH / 2, "No se detectaron piezas cerradas en el SVG.")
        c.save()
        return buf.getvalue()

    caja_w_cm, caja_h_cm = _dims_caja_cm(result)
    cm_per_unit = caja_w_cm / caja_bb["w"] if caja_w_cm > 0 else 1.0
    if caja_h_cm <= 0:
        caja_h_cm = caja_bb["h"] * cm_per_unit
    prof   = result.cercha_altura_cm or 0
    cuadro = (result.material_cara or {}).get("cuadro_corte")
    con_cuadro = bool(cuadro and dis_bb)
    # renglones del diseño ("CFE" arriba, "COMISIÓN FEDERAL" abajo…): cada uno
    # lleva su propia cota de ancho y de alto — un solo cuadro confunde al taller
    filas_dis = _filas_diseno(diseno_p) if dis_bb else []

    # encuadre sobre el bbox conjunto de TODAS las cerradas (fidelidad visual)
    cerradas = [p for p in paths_info if p.get("is_closed")]
    minX, minY, maxX, maxY = _bbox_conjunto(cerradas)
    bbox_w_svg, bbox_h_svg = maxX - minX, maxY - minY

    # bandas: arriba = ancho caja · izquierda = [pos Y | alto caja] ·
    # abajo = anchos por renglón (escalonados) + posición X ·
    # derecha (antes de la tabla) = altos por renglón
    n_filas_bot = min(len(filas_dis), MAX_FILAS_COTA) + (1 if con_cuadro else 0)
    banda_izq = GAP_DIBUJO_COTA + (2 if con_cuadro else 1) * COL_ALTO_PT + 4
    banda_bot = (GAP_DIBUJO_COTA + n_filas_bot * FILA_COTA_PT + 4) if n_filas_bot else 10
    banda_der = (COL_ALTO_PT if filas_dis else 0)

    area_x0 = MARGEN + banda_izq
    area_y0 = MARGEN + PIE_H + banda_bot
    area_x1 = PW - MARGEN - COL_TABLA_W - GAP_COL - banda_der
    area_y1 = PH - HEADER_H - MARGEN - BANDA_TOP
    area_w, area_h = area_x1 - area_x0, area_y1 - area_y0

    scale_draw = min(area_w / bbox_w_svg, area_h / bbox_h_svg)
    dibujo_w, dibujo_h = bbox_w_svg * scale_draw, bbox_h_svg * scale_draw
    ox = area_x0 + (area_w - dibujo_w) / 2
    oy = area_y0 + (area_h - dibujo_h) / 2

    _dibujar_header(c, titulo, PW, PH, subtitulo="Caja de luz — 1 pieza")
    _render_svg(c, svg_text, ox, oy, scale_draw, minX, minY, bbox_h_svg)

    # esquinas de la caja y del cuadro en coords de canvas
    cj_xl, cj_yt = _svg_to_canvas_xy(caja_bb["x"], caja_bb["y"],
                                     ox, oy, scale_draw, minX, minY, bbox_h_svg)
    cj_xr, cj_yb = _svg_to_canvas_xy(caja_bb["x"] + caja_bb["w"],
                                     caja_bb["y"] + caja_bb["h"],
                                     ox, oy, scale_draw, minX, minY, bbox_h_svg)

    # cota ancho de caja (arriba) y alto de caja (columna externa izquierda)
    y_gw = cj_yt + BANDA_TOP * 0.55
    _ext_v(c, cj_xl, cj_yt + 2, y_gw)
    _ext_v(c, cj_xr, cj_yt + 2, y_gw)
    _cota_h(c, cj_xl, cj_xr, y_gw, caja_w_cm, bold=True)

    x_gh = area_x0 - banda_izq + COL_ALTO_PT * 0.5
    _ext_h(c, x_gh, cj_xl - 2, cj_yb)
    _ext_h(c, x_gh, cj_xl - 2, cj_yt)
    _cota_v(c, x_gh, cj_yb, cj_yt, caja_h_cm, bold=True)

    pos_x_cm = pos_y_cm = -1.0
    if con_cuadro:
        ds_xl, ds_yt = _svg_to_canvas_xy(dis_bb["x"], dis_bb["y"],
                                         ox, oy, scale_draw, minX, minY, bbox_h_svg)
        ds_xr, ds_yb = _svg_to_canvas_xy(dis_bb["x"] + dis_bb["w"],
                                         dis_bb["y"] + dis_bb["h"],
                                         ox, oy, scale_draw, minX, minY, bbox_h_svg)
        pos_x_cm = max(0.0, (dis_bb["x"] - caja_bb["x"]) * cm_per_unit)
        pos_y_cm = max(0.0, (dis_bb["y"] - caja_bb["y"]) * cm_per_unit)

        # cuadro de corte punteado (material a comprar; sus medidas van en la
        # ficha y el BOM — las cotas del dibujo son por renglón)
        c.saveState()
        c.setStrokeColor(colors.HexColor("#C05621")); c.setLineWidth(1.0)
        c.setDash(4, 3)
        c.rect(ds_xl, ds_yb, ds_xr - ds_xl, ds_yt - ds_yb, fill=0, stroke=1)
        c.restoreState()

        # posición del gráfico: desde el borde izq (última fila de abajo) y
        # desde arriba (columna interna izquierda)
        if pos_x_cm > 0.05:
            y_pos = cj_yb - GAP_DIBUJO_COTA - (n_filas_bot - 1) * FILA_COTA_PT - 6
            _ext_v(c, cj_xl, cj_yb - 2, y_pos)
            _ext_v(c, ds_xl, ds_yb - 2, y_pos)
            _cota_h(c, cj_xl, ds_xl, y_pos, pos_x_cm)
        if pos_y_cm > 0.05:
            x_py = area_x0 - GAP_DIBUJO_COTA - COL_ALTO_PT * 0.5
            _ext_h(c, x_py, cj_xl - 2, cj_yt)
            _ext_h(c, x_py, ds_xl - 2, ds_yt)
            _cota_v(c, x_py, ds_yt, cj_yt, pos_y_cm)

    # cotas POR RENGLÓN: ancho abajo (escalonado) y alto a la derecha — cada
    # renglón no se solapa en Y con los demás, así que una columna basta
    filas_cm: list[tuple[float, float]] = []
    for i, fb in enumerate(filas_dis):
        f_xl, f_yt = _svg_to_canvas_xy(fb["x"], fb["y"],
                                       ox, oy, scale_draw, minX, minY, bbox_h_svg)
        f_xr, f_yb = _svg_to_canvas_xy(fb["x"] + fb["w"], fb["y"] + fb["h"],
                                       ox, oy, scale_draw, minX, minY, bbox_h_svg)
        w_cm = fb["w"] * cm_per_unit
        h_cm = fb["h"] * cm_per_unit
        filas_cm.append((w_cm, h_cm))
        if i < MAX_FILAS_COTA:
            y_c = cj_yb - GAP_DIBUJO_COTA - i * FILA_COTA_PT - 6
            _ext_v(c, f_xl, f_yb - 2, y_c)
            _ext_v(c, f_xr, f_yb - 2, y_c)
            _cota_h(c, f_xl, f_xr, y_c, w_cm)
        x_ch = area_x1 + banda_der * 0.5
        _ext_h(c, x_ch, f_xr + 2, f_yb)
        _ext_h(c, x_ch, f_xr + 2, f_yt)
        _cota_v(c, x_ch, f_yb, f_yt, h_cm)

    # columna derecha: ficha + cajetín
    col_x = PW - MARGEN - COL_TABLA_W
    tabla_top = PH - HEADER_H - MARGEN
    filas = _ficha_caja(result, caja_w_cm, caja_h_cm, pos_x_cm, pos_y_cm, filas_cm)
    _dibujar_ficha_caja(c, col_x, tabla_top, COL_TABLA_W, filas)

    ratio = (cm_per_unit * cm / scale_draw) if scale_draw > 0 else 0
    escala_txt  = _escala_bonita(ratio)
    totales_txt = f"{caja_w_cm:.1f} × {caja_h_cm:.1f} × {prof:.0f} cm"
    _dibujar_cajetin(c, col_x, MARGEN + PIE_H, COL_TABLA_W, CAJETIN_H,
                     meta, escala_txt, totales_txt, con_firma=not modo_taller)

    _dibujar_pie(c, PW,
                 texto_izq=f"Página 1 de {2 if modo_taller else 1}",
                 texto_der=f"Escala {escala_txt} · Cotas en cm · "
                           f"{'Cuadro punteado = vinil de corte' if con_cuadro else 'Caja de luz'}")

    if modo_taller:
        c.showPage()
        _pagina_taller_caja(c, PW, PH, meta, result, filas, notas)
        _dibujar_pie(c, PW, texto_izq="Página 2 de 2")

    c.save()
    return buf.getvalue()


def _pagina_taller_caja(c, PW: float, PH: float, meta: dict, result,
                        ficha: list[tuple[str, str]], notas: str) -> None:
    """Página 2 de caja: BOM + ficha de fabricación + perfil del cajón."""
    _dibujar_header(c, "TALLER — MATERIALES Y FABRICACIÓN", PW, PH,
                    subtitulo=f"Folio: {meta.get('folio') or '—'}")
    top = PH - HEADER_H - MARGEN
    mitad_w = (PW - 2 * MARGEN - GAP_COL) / 2

    c.setFillColor(AZUL_DARK); c.setFont(FONT_BOLD, 10)
    c.drawString(MARGEN, top - 9, "LISTA DE MATERIALES")
    bom = _construir_bom(result)
    y_bom_final = top - 16
    if bom:
        y_bom_final = _dibujar_bom(c, MARGEN, top - 16, mitad_w, bom)

    # perfil lateral del cajón (mismo esquema que cercha: cara/canal/fondo/muro)
    perfil_h = 100
    y_perfil = y_bom_final - perfil_h - 14
    if y_perfil > MARGEN + PIE_H + 20:
        _dibujar_perfil_cercha(c, MARGEN, y_perfil, mitad_w * 0.75, perfil_h, result)

    x_der = MARGEN + mitad_w + GAP_COL
    c.setFillColor(AZUL_DARK); c.setFont(FONT_BOLD, 10)
    c.drawString(x_der, top - 9, "FICHA DE FABRICACIÓN")
    _dibujar_ficha_caja(c, x_der, top - 16, mitad_w, ficha)

    if notas:
        c.setFillColor(GRIS_TXT); c.setFont(FONT_BOLD, 8)
        c.drawString(MARGEN, MARGEN + PIE_H + 8, "NOTAS:")
        c.setFillColor(colors.black); c.setFont(FONT_NAME, 8)
        c.drawString(MARGEN + 38, MARGEN + PIE_H + 8, notas[:200])


# ─── API pública ─────────────────────────────────────────────────────────────

def generar_plano_cliente(meta: dict, svg_text: str, paths_info: list,
                          viewbox_w: float, viewbox_h: float,
                          real_width_cm: float, altura_cm: float = 0.0,
                          result=None,
                          artboard_w_cm_hint: float = 0.0) -> bytes:
    """Plano de medidas para CLIENTE: dibujo con cotas técnicas, tabla de
    piezas, cajetín con firma de aprobación. Las cajas de luz usan su propio
    plano de UNA pieza (caja + cuadro de corte), sin numerar letras."""
    if result is not None and getattr(result, "tipo", "") == "caja_luz":
        return _construir_pdf_caja(meta, svg_text, paths_info,
                                   titulo="PLANO DE MEDIDAS",
                                   modo_taller=False, result=result)
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
    """Plano para TALLER: dibujo con cotas + página 2 con lista de materiales
    (BOM), tabla técnica por pieza, perfil de cercha y notas. Las cajas de luz
    usan su propio plano de UNA pieza con ficha de fabricación."""
    if result is not None and getattr(result, "tipo", "") == "caja_luz":
        return _construir_pdf_caja(meta, svg_text, paths_info,
                                   titulo="PLANO TÉCNICO DE FABRICACIÓN",
                                   modo_taller=True, result=result, notas=notas)
    return _construir_pdf(meta, svg_text, paths_info, viewbox_w, viewbox_h,
                          real_width_cm, altura_cm,
                          titulo="PLANO TÉCNICO DE FABRICACIÓN",
                          modo_taller=True,
                          result=result, notas=notas,
                          artboard_w_cm_hint=artboard_w_cm_hint)
