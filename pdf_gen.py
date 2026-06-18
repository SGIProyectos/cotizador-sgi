import io
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

log = logging.getLogger("cotizador.pdf")

# Página carta: 21.59 cm ancho. Márgenes 2 cm c/lado → útil = 17.59 cm
PW = 17.59 * cm

AZUL_DARK  = colors.HexColor("#1a2b4a")
AZUL_MED   = colors.HexColor("#2d5986")
NARANJA    = colors.HexColor("#e87c2a")
VERDE      = colors.HexColor("#2e7d32")
GRIS_CLARO = colors.HexColor("#f2f4f7")
ROJO_CLARO = colors.HexColor("#ffebee")
VERDE_CLAR = colors.HexColor("#e8f5e9")
BLANCO     = colors.white

# ─── ESTILOS (instancias únicas a nivel de módulo) ───────────────────────────

S_EMPRESA = ParagraphStyle("sgi_empresa", fontSize=15, textColor=BLANCO,
                            fontName="Helvetica-Bold", alignment=TA_LEFT,  leading=18)
S_DOCTIPO  = ParagraphStyle("sgi_doctipo", fontSize=13, textColor=BLANCO,
                            fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=18)
S_H2       = ParagraphStyle("sgi_h2",   fontSize=11, textColor=AZUL_DARK,
                            fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3)
S_BODY     = ParagraphStyle("sgi_body", fontSize=9,  textColor=colors.black, leading=14)
S_SMALL    = ParagraphStyle("sgi_sml",  fontSize=8,  textColor=colors.grey,  leading=12)
S_PIE      = ParagraphStyle("sgi_pie",  fontSize=7.5,textColor=colors.grey,  alignment=TA_CENTER)
S_NARANJA  = ParagraphStyle("sgi_nar",  fontSize=12, textColor=NARANJA,
                            fontName="Helvetica-Bold", alignment=TA_RIGHT)
S_LBL      = ParagraphStyle("sgi_lbl",  fontSize=9,  textColor=AZUL_DARK,
                            fontName="Helvetica-Bold", leading=13)
S_VAL      = ParagraphStyle("sgi_val",  fontSize=9,  textColor=colors.black, leading=13)
S_VAL_SM   = ParagraphStyle("sgi_vsm",  fontSize=8.5,textColor=colors.black, leading=12)


def _estilos():
    """Compatibilidad con código existente que recibe un dict de estilos."""
    return {
        "title": S_EMPRESA, "doc": S_DOCTIPO, "sub": S_SMALL,
        "h2": S_H2, "body": S_BODY, "small": S_SMALL,
        "right": ParagraphStyle("sgi_r", fontSize=9, alignment=TA_RIGHT),
        "total": S_NARANJA, "bold": S_LBL, "pie": S_PIE,
    }


def _doc_base(buf, titulo_tipo: str):
    return SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm,
        title=titulo_tipo,
    )


def _p(texto: str, estilo=None) -> Paragraph:
    """Shortcut: convierte string a Paragraph (previene encimado)."""
    return Paragraph(str(texto), estilo or S_VAL)


def _header(empresa: str, doc_label: str, st: dict):
    data = [[_p(empresa, S_EMPRESA), _p(doc_label, S_DOCTIPO)]]
    tbl = Table(data, colWidths=[PW * 0.62, PW * 0.38], rowHeights=[1.4*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), AZUL_DARK),
        ("LEFTPADDING",   (0, 0), (0, -1),  12),
        ("RIGHTPADDING",  (1, 0), (1, -1),  12),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _info_grid(rows: list, st: dict):
    """4 columnas etiqueta·valor·etiqueta·valor — todo como Paragraph."""
    para_rows = []
    for row in rows:
        pr = []
        for i, cell in enumerate(row):
            pr.append(_p(cell, S_LBL if i % 2 == 0 else S_VAL))
        para_rows.append(pr)

    tbl = Table(para_rows, colWidths=[PW*0.16, PW*0.34, PW*0.16, PW*0.34])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), GRIS_CLARO),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _tabla_kv(rows: list):
    """2 columnas clave-valor — todo como Paragraph."""
    para_rows = [[_p(r[0], S_LBL), _p(r[1], S_VAL_SM)] for r in rows]
    tbl = Table(para_rows, colWidths=[PW * 0.40, PW * 0.60])
    tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _firma_block(izq_nombre: str, der_nombre: str, st: dict):
    """Bloque de dos firmas lado a lado."""
    linea = "____________________________"
    linea_f = "___________________________________"
    data = [
        [_p(f"<b>{izq_nombre}</b>", S_BODY), _p(f"<b>{der_nombre}</b>", S_BODY)],
        [_p(linea_f, S_VAL),  _p(linea_f, S_VAL)],
        [_p("Nombre: ___________________________", S_VAL), _p("Nombre: ___________________________", S_VAL)],
        [_p("Firma:   ___________________________", S_VAL), _p("Firma:   ___________________________", S_VAL)],
        [_p("Fecha:   ___________________________", S_VAL), _p("Fecha:   ___________________________", S_VAL)],
    ]
    tbl = Table(data, colWidths=[PW * 0.50, PW * 0.50])
    tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


# ─── 1. COTIZACIÓN ──────────────────────────────────────────────────────────

def generar_pdf(result, meta: dict) -> bytes:
    buf = io.BytesIO()
    doc = _doc_base(buf, "Cotización")
    st  = _estilos()
    elements = []

    empresa = meta.get("empresa", "SGI Impresión y Diseño")

    # Encabezado
    elements.append(_header(empresa, "COTIZACIÓN", st))
    elements.append(Spacer(1, 0.3*cm))

    # Info general
    folio   = meta.get("folio", "---")
    fecha   = meta.get("fecha", datetime.now().strftime("%d/%m/%Y"))
    cliente = meta.get("cliente") or "—"
    tipo_label = {"letras_3d": "Letras 3D (Canal)", "letras_planas": "Letras Planas",
                  "caja_luz":  "Caja de Luz"}.get(result.tipo, result.tipo)

    elements.append(_info_grid([
        ["Folio:",   folio,    "Cliente:", cliente],
        ["Fecha:",   fecha,    "Tipo:",    tipo_label],
        ["Vigencia:", "15 días naturales", "Uso:", meta.get("uso", "—")],
    ], st))
    elements.append(Spacer(1, 0.4*cm))

    # Medidas
    elements.append(Paragraph("Medidas del diseño", st["h2"]))
    med = [
        ["Elementos detectados", str(result.paths_count)],
        ["Altura máx pieza",     f"{result.altura_letra_cm:.1f} cm"],
        ["Área total caras",     f"{result.area_cara_cm2:.1f} cm²  ({result.area_cara_cm2/10000:.4f} m²)"],
        ["Perímetro total",      f"{result.perimetro_total_cm:.1f} cm  ({result.perimetro_total_cm/100:.2f} m)"],
        ["Profundidad cercha",   f"{result.cercha_altura_cm:.1f} cm"],
        ["Área total cercha",    f"{result.cercha_area_cm2:.1f} cm²"],
    ]
    elements.append(_tabla_kv(med))
    elements.append(Spacer(1, 0.4*cm))

    # Materiales
    elements.append(Paragraph("Materiales", S_H2))
    S_TH = ParagraphStyle("sgi_th", fontSize=8.5, textColor=BLANCO, fontName="Helvetica-Bold")
    S_TC = ParagraphStyle("sgi_tc", fontSize=8.5, textColor=colors.black, leading=12)
    S_TR = ParagraphStyle("sgi_tr", fontSize=8.5, textColor=colors.black, leading=12, alignment=TA_RIGHT)
    mat_rows = [[_p("#", S_TH), _p("Material / Componente", S_TH),
                 _p("Cant.", S_TH), _p("Costo", S_TH)]]
    n = 1
    def _mrow(num, nombre, cant, costo):
        return [_p(str(num), S_TC), _p(nombre, S_TC), _p(cant, S_TC), _p(costo, S_TR)]
    if result.costo_material_cara > 0:
        mat_rows.append(_mrow(n, result.material_cara.get("nombre","—"),
                              f"{result.laminas_cara} lám.", f"${result.costo_material_cara:,.2f}")); n+=1
    if result.costo_material_cercha > 0:
        mat_rows.append(_mrow(n, result.material_cercha.get("nombre","—"),
                              f"{result.laminas_cercha} lám.", f"${result.costo_material_cercha:,.2f}")); n+=1
    if result.costo_material_fondo > 0:
        mat_rows.append(_mrow(n, result.material_fondo.get("nombre","—"),
                              f"{result.laminas_fondo} lám.", f"${result.costo_material_fondo:,.2f}")); n+=1
    if result.costo_led > 0:
        mat_rows.append(_mrow(n, result.led.get("nombre","—"),
                              f"{result.modulos_led} mód.", f"${result.costo_led:,.2f}")); n+=1
    if result.costo_fuente > 0:
        mat_rows.append(_mrow(n, result.fuente.get("nombre","—"), "1 pza",
                              f"${result.costo_fuente:,.2f}")); n+=1
    if result.costo_pegamento > 0:
        mat_rows.append(_mrow(n, result.pegamento.get("nombre","—"), "c/nec.",
                              f"${result.costo_pegamento:,.2f}"))

    mat_tbl = Table(mat_rows, colWidths=[PW*0.05, PW*0.57, PW*0.13, PW*0.25])
    mat_tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  AZUL_MED),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(mat_tbl)
    elements.append(Spacer(1, 0.4*cm))

    # Notas
    notas = meta.get("notas", "")
    if notas:
        elements.append(Paragraph("Notas", st["h2"]))
        elements.append(Paragraph(notas, st["body"]))
        elements.append(Spacer(1, 0.3*cm))

    elements.append(HRFlowable(width="100%", color=AZUL_DARK, thickness=1))
    elements.append(Spacer(1, 0.2*cm))

    # Totales
    precio_final = result.precio_final or result.precio_venta_sugerido
    S_TL  = ParagraphStyle("sgi_tl",  fontSize=9,  textColor=colors.black, leading=13)
    S_TLR = ParagraphStyle("sgi_tlr", fontSize=9,  textColor=colors.black, leading=13, alignment=TA_RIGHT)
    S_TVT = ParagraphStyle("sgi_tvt", fontSize=12, textColor=NARANJA, fontName="Helvetica-Bold", leading=16)
    S_TVR = ParagraphStyle("sgi_tvr", fontSize=12, textColor=NARANJA, fontName="Helvetica-Bold", leading=16, alignment=TA_RIGHT)

    def _trow(label, valor, bold=False):
        sl = S_TVT if bold else S_TL
        sr = S_TVR if bold else S_TLR
        return [_p(label, sl), _p(valor, sr)]

    tot_rows = [
        _trow("Subtotal materiales", f"${result.subtotal:,.2f}"),
        _trow("IVA 16%",             f"${result.iva:,.2f}"),
        _trow("Costo total c/IVA",   f"${result.total:,.2f}"),
    ]
    if result.mo_total > 0:
        tot_rows.append(_trow("Mano de obra", f"${result.mo_total:,.2f}"))
    if result.inst_total > 0:
        tot_rows.append(_trow("Instalación",  f"${result.inst_total:,.2f}"))
    tot_rows.append(_trow("PRECIO DE VENTA", f"${precio_final:,.2f}", bold=True))

    last = len(tot_rows) - 1
    tot_tbl = Table(tot_rows, colWidths=[PW * 0.70, PW * 0.30])
    tot_tbl.setStyle(TableStyle([
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LINEABOVE",      (0, last), (-1, last), 1.5, AZUL_DARK),
        ("BACKGROUND",     (0, last), (-1, last), GRIS_CLARO),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(tot_tbl)
    elements.append(Spacer(1, 0.5*cm))

    # Condiciones
    elements.append(KeepTogether([
        Paragraph("Condiciones", st["h2"]),
        Paragraph(
            "• 50% de anticipo para iniciar fabricación  • 50% restante contra entrega<br/>"
            "• Vigencia de esta cotización: 15 días naturales  • Precios en MXN con IVA incluido<br/>"
            "• Tiempo de entrega estimado: <b>[X días hábiles]</b> a partir del anticipo y arte aprobado",
            st["body"]
        ),
        Spacer(1, 0.4*cm),
        HRFlowable(width="100%", color=colors.lightgrey, thickness=0.5),
        Spacer(1, 0.1*cm),
        Paragraph(f"{empresa}  ·  Cotización válida 15 días  ·  Precios en MXN", st["pie"]),
    ]))

    doc.build(elements)
    return buf.getvalue()


# ─── 2. ORDEN DE TRABAJO ─────────────────────────────────────────────────────

def generar_pdf_ot(result, meta: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
        title="Orden de Trabajo",
    )

    st  = _estilos()
    elements = []

    empresa = meta.get("empresa", "SGI Impresión y Diseño")
    folio   = meta.get("folio", "---")
    fecha   = meta.get("fecha", datetime.now().strftime("%d/%m/%Y"))
    cliente = meta.get("cliente") or "—"
    tipo_label = {"letras_3d": "Letras 3D (Canal)", "letras_planas": "Letras Planas",
                  "caja_luz":  "Caja de Luz"}.get(result.tipo, result.tipo)

    # Encabezado
    elements.append(_header(empresa, "ORDEN DE TRABAJO", st))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(_info_grid([
        ["OT Núm.:",    f"OT-{folio}", "Ref. Cotización:", folio],
        ["Fecha:",       fecha,         "Cliente:",         cliente],
        ["Tipo trabajo:", tipo_label,   "Uso:",             meta.get("uso", "—")],
    ], st))
    elements.append(Spacer(1, 0.35*cm))

    # ── Especificación general ───────────────────────────────────────────────
    n_letras = result.paths_count or len(result.desglose_letras or [])
    elements.append(Paragraph("Especificación General", st["h2"]))
    desc_rows = [
        ["Producto",            tipo_label],
        ["Piezas a fabricar",   f"{n_letras}"],
        ["Altura máx pieza",    f"{result.altura_letra_cm:.1f} cm"],
        ["Área total caras",    f"{result.area_cara_cm2:.1f} cm²"],
        ["Material cara",       result.material_cara.get("nombre", "—")],
        ["Iluminación",         result.led.get("nombre", "Sin iluminación")],
        ["Tipo construcción",   result.tipo_construccion.replace("_", " ").title()],
    ]
    elements.append(_tabla_kv(desc_rows))
    elements.append(Spacer(1, 0.3*cm))

    # ── Desglose por letra (solo letras 3D / planas) ─────────────────────────
    desglose = result.desglose_letras or []
    if desglose and result.tipo in ("letras_3d", "letras_planas"):
        S_TH = ParagraphStyle("sgi_ot_th", fontSize=8.5, textColor=BLANCO,
                              fontName="Helvetica-Bold", alignment=TA_CENTER)
        S_TC = ParagraphStyle("sgi_ot_tc", fontSize=8.5, textColor=colors.black,
                              leading=11, alignment=TA_CENTER)
        S_TCB = ParagraphStyle("sgi_ot_tcb", fontSize=8.5, textColor=AZUL_DARK,
                               fontName="Helvetica-Bold", alignment=TA_CENTER)

        elements.append(Paragraph("Desglose por Pieza", st["h2"]))
        header = ["#", "Alto<br/>(cm)", "Ancho<br/>(cm)", "Perímetro<br/>cercha (cm)",
                  "Cercha c/merma<br/>10% (cm)", "Área cara<br/>(cm²)"]
        data = [[_p(h, S_TH) for h in header]]
        tot_alto = tot_ancho = tot_perim = tot_total = tot_area = 0.0
        for i, d in enumerate(desglose, 1):
            alto    = float(d.get("alto_cm", 0))
            ancho   = float(d.get("ancho_cm", 0))
            perim_n = float(d.get("cercha_neta_cm", d.get("perimetro_cm", 0)))
            perim_t = float(d.get("cercha_total_cm", 0))
            area_bx = float(d.get("area_bbox_cm2", 0))
            tot_alto  = max(tot_alto, alto)
            tot_ancho += ancho
            tot_perim += perim_n
            tot_total += perim_t
            tot_area  += area_bx
            data.append([
                _p(str(i), S_TC),
                _p(f"{alto:.1f}", S_TC),
                _p(f"{ancho:.1f}", S_TC),
                _p(f"{perim_n:.1f}", S_TC),
                _p(f"{perim_t:.1f}", S_TC),
                _p(f"{area_bx:.0f}", S_TC),
            ])
        # Fila TOTAL
        data.append([
            _p("TOTAL", S_TCB),
            _p(f"máx {tot_alto:.1f}", S_TCB),
            _p(f"{tot_ancho:.1f}", S_TCB),
            _p(f"{tot_perim:.1f}", S_TCB),
            _p(f"{tot_total:.1f}", S_TCB),
            _p(f"{tot_area:.0f}", S_TCB),
        ])
        widths = [PW*0.07, PW*0.13, PW*0.13, PW*0.22, PW*0.22, PW*0.16, PW*0.07]
        tbl = Table(data, colWidths=widths[:6])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), AZUL_DARK),
            ("ROWBACKGROUNDS",(0, 1), (-1, -2), [BLANCO, GRIS_CLARO]),
            ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#fff4e6")),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(tbl)
        elements.append(Spacer(1, 0.3*cm))

    # ── Especificación de cercha (solo letras 3D) ────────────────────────────
    if result.tipo == "letras_3d":
        elements.append(Paragraph("Especificación de Cercha", st["h2"]))
        sv_nombre = (result.silvatrim or {}).get("nombre", "—") if hasattr(result, "silvatrim") else "—"
        sv_metros = getattr(result, "metros_silvatrim", 0.0) or 0.0
        cmin = getattr(result, "cercha_min_cm", 0.0)
        cmax = getattr(result, "cercha_max_cm", 0.0)
        cat  = getattr(result, "categoria_letra", "") or "—"
        if cmin and cmax:
            prof_val = (f"<b>{result.cercha_altura_cm:.1f} cm</b>  "
                        f"(rango recomendado: <b>{cmin:.0f} – {cmax:.0f} cm</b> · {cat})")
        else:
            prof_val = f"{result.cercha_altura_cm:.1f} cm"
        cercha_rows = [
            ["Material cercha",            result.material_cercha.get("nombre", "—")],
            ["Profundidad / ancho fleje",  prof_val],
            ["Perímetro total (neto)",     f"{result.perimetro_total_cm:.1f} cm  ·  {result.perimetro_total_cm/100:.2f} m"],
            ["Cercha con merma (+10%)",    f"{result.perimetro_total_cm*1.10:.1f} cm  ·  {result.perimetro_total_cm*1.10/100:.2f} m"],
            ["Área total cercha",          f"{result.cercha_area_cm2:.0f} cm²"],
            ["Silvatrim (acabado borde)",  f"{sv_nombre}  ·  {sv_metros:.2f} m"],
        ]
        elements.append(_tabla_kv(cercha_rows))
        elements.append(Spacer(1, 0.3*cm))

    # ── Materiales a comprar ─────────────────────────────────────────────────
    elements.append(Paragraph("Materiales a Comprar / Habilitar", st["h2"]))
    mat_rows = []
    if result.material_cara.get("nombre"):
        lams = getattr(result, "laminas_cara", 0)
        mat_rows.append([f"Láminas {result.material_cara.get('nombre','—')} (cara)", f"{lams} pza"])
    if result.tipo == "letras_3d":
        lams_c = getattr(result, "laminas_cercha", 0)
        mat_rows.append([f"Láminas {result.material_cercha.get('nombre','—')} (cercha)", f"{lams_c} pza"])
    if result.material_fondo and result.material_fondo.get("nombre"):
        lams_f = getattr(result, "laminas_fondo", 0)
        if lams_f:
            mat_rows.append([f"Láminas {result.material_fondo.get('nombre','—')} (fondo)", f"{lams_f} pza"])
    if result.led and result.led.get("nombre"):
        mods = getattr(result, "modulos_led", 0)
        watts = getattr(result, "watts_total", 0)
        mat_rows.append(["LEDs",            f"{result.led.get('nombre','—')}  ·  {mods} módulos  ·  {watts:.1f} W"])
    if result.fuente and result.fuente.get("nombre"):
        mat_rows.append(["Fuente",          result.fuente.get("nombre","—")])
    if result.pegamento and result.pegamento.get("nombre"):
        mat_rows.append(["Pegamento",       result.pegamento.get("nombre","—")])
    inst_grua = getattr(result, "inst_grua", None)
    if inst_grua and (inst_grua or {}).get("nombre"):
        mat_rows.append(["Grúa instalación", f"{inst_grua.get('nombre','—')}  ·  {getattr(result,'inst_dias_grua',1)} día(s)"])
    if hasattr(result, "silvatrim") and result.silvatrim and result.silvatrim.get("nombre"):
        mat_rows.append(["Silvatrim",       f"{result.silvatrim.get('nombre','—')}  ·  {getattr(result,'metros_silvatrim',0):.2f} m"])
    if not mat_rows:
        mat_rows.append(["—", "—"])
    elements.append(_tabla_kv(mat_rows))
    elements.append(Spacer(1, 0.3*cm))

    # ── Plazos de producción ─────────────────────────────────────────────────
    elements.append(Paragraph("Plazos de Producción", st["h2"]))
    plazo_rows = [
        ["Inicio de fabricación",  "_______________________"],
        ["Entrega comprometida",   "_______________________"],
        ["Entregado el",           "_______________________"],
    ]
    elements.append(_tabla_kv(plazo_rows))
    elements.append(Spacer(1, 0.3*cm))

    # ── Notas para el taller ─────────────────────────────────────────────────
    elements.append(Paragraph("Notas para el Taller", st["h2"]))
    notas_txt = (meta.get("notas") or "").strip()
    if notas_txt:
        elements.append(_p(notas_txt, S_BODY))
    else:
        elements.append(_p(
            "________________________________________________________________"
            "<br/>________________________________________________________________"
            "<br/>________________________________________________________________",
            S_BODY))
    elements.append(Spacer(1, 0.3*cm))

    # ── Control de Producción (firmas por etapa) ─────────────────────────────
    elements.append(KeepTogether([
        Paragraph("Control de Producción", st["h2"]),
        _control_produccion_tbl(),
        Spacer(1, 0.4*cm),
        HRFlowable(width="100%", color=colors.lightgrey, thickness=0.5),
        Paragraph(f"{empresa}  ·  Orden de Trabajo OT-{folio}  ·  Documento interno de producción",
                  st["pie"]),
    ]))

    doc.build(elements)
    return buf.getvalue()


def _control_produccion_tbl():
    """Tabla de checkpoints de producción: etapa · responsable · fecha · observación."""
    S_TH = ParagraphStyle("sgi_cp_th", fontSize=8.5, textColor=BLANCO,
                          fontName="Helvetica-Bold", alignment=TA_CENTER)
    S_TL = ParagraphStyle("sgi_cp_tl", fontSize=8.5, textColor=AZUL_DARK,
                          fontName="Helvetica-Bold", leading=12)
    S_TC = ParagraphStyle("sgi_cp_tc", fontSize=8.5, textColor=colors.grey, leading=12)
    blank = "______________"
    blank_long = "________________________"
    etapas = [
        "Corte / Routeado",
        "Doblez de cercha",
        "Armado",
        "Conexión eléctrica",
        "Sellado / Acabados",
        "Control de calidad",
        "Empaque",
        "Entrega",
    ]
    rows = [[_p("Etapa", S_TH), _p("Responsable", S_TH),
             _p("Fecha", S_TH), _p("Observación", S_TH)]]
    for e in etapas:
        rows.append([_p(e, S_TL), _p(blank, S_TC), _p(blank, S_TC), _p(blank_long, S_TC)])
    tbl = Table(rows, colWidths=[PW*0.26, PW*0.22, PW*0.18, PW*0.34])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  AZUL_DARK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


# ─── 3. ACTA DE ENTREGA, RECEPCIÓN Y GARANTÍA ────────────────────────────────

def generar_pdf_entrega(result, meta: dict) -> bytes:
    buf = io.BytesIO()
    doc = _doc_base(buf, "Acta de Entrega")
    st  = _estilos()
    elements = []

    empresa     = meta.get("empresa", "SGI Impresión y Diseño")
    folio       = meta.get("folio", "---")
    fecha       = meta.get("fecha", datetime.now().strftime("%d/%m/%Y"))
    cliente     = meta.get("cliente") or "—"
    precio_final = result.precio_final or result.precio_venta_sugerido
    anticipo     = round(precio_final * 0.50, 2)
    saldo        = round(precio_final - anticipo, 2)
    tipo_label   = {"letras_3d": "Letras 3D (Canal)", "letras_planas": "Letras Planas",
                    "caja_luz":  "Caja de Luz"}.get(result.tipo, result.tipo)

    # Encabezado
    elements.append(_header(empresa, "ACTA DE ENTREGA Y GARANTÍA", st))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(_info_grid([
        ["Acta Núm.:", f"ENT-{folio}", "Ref. OT:",   f"OT-{folio}"],
        ["Fecha:",      fecha,          "Cliente:",    cliente],
        ["Tipo:",        tipo_label,    "Lugar entrega:", "________________________"],
    ], st))
    elements.append(Spacer(1, 0.4*cm))

    # Descripción entregada
    elements.append(Paragraph("Descripción del Trabajo Entregado", st["h2"]))
    desc_rows = [
        ["Producto",         tipo_label],
        ["Altura máx pieza", f"{result.altura_letra_cm:.1f} cm"],
        ["Material cara",    result.material_cara.get("nombre", "—")],
        ["Material cercha",  result.material_cercha.get("nombre", "—")],
        ["Iluminación",      result.led.get("nombre", "Sin iluminación")],
        ["Construcción",     result.tipo_construccion.replace("_", " ").title()],
    ]
    elements.append(_tabla_kv(desc_rows))
    elements.append(Spacer(1, 0.3*cm))

    # Declaración de recepción
    elements.append(Paragraph("Declaración de Recepción y Conformidad", st["h2"]))
    elements.append(Paragraph(
        "El Cliente declara que:<br/><br/>"
        "1. Ha recibido a su entera satisfacción el trabajo descrito en este documento.<br/>"
        "2. Verificó físicamente que el anuncio corresponde a las especificaciones acordadas.<br/>"
        "3. El trabajo fue revisado en presencia del Proveedor y no presenta defectos visibles "
        "al momento de la entrega.<br/>"
        "4. Ha realizado el pago total del servicio conforme a lo pactado.",
        st["body"]
    ))
    elements.append(Spacer(1, 0.3*cm))

    # Liquidación
    elements.append(Paragraph("Liquidación del Trabajo", st["h2"]))
    liq_rows = [
        ["Total del trabajo",   f"${precio_final:,.2f} MXN"],
        ["Anticipo pagado",     f"${anticipo:,.2f} MXN"],
        ["Saldo liquidado hoy", f"${saldo:,.2f} MXN"],
        ["Forma de pago",       "________________________________"],
        ["Folio comprobante",   "________________________________"],
    ]
    liq_tbl = Table(liq_rows, colWidths=[PW*0.42, PW*0.58])
    liq_tbl.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1), AZUL_DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("PADDING",        (0, 0), (-1, -1), 5),
    ]))
    elements.append(liq_tbl)
    elements.append(Spacer(1, 0.3*cm))

    # Garantía
    elements.append(KeepTogether([
        Paragraph("Garantía — 1 (un) año a partir de esta fecha", st["h2"]),
        _garantia_tbl(st),
        Spacer(1, 0.3*cm),
    ]))

    # Deslinde
    elements.append(KeepTogether([
        Paragraph("Deslinde de Responsabilidad", st["h2"]),
        Paragraph(
            "El Cliente reconoce que: (1) El Proveedor no se responsabiliza de daños causados por "
            "instalación incorrecta realizada sin su participación. (2) Si el Cliente o un tercero "
            "realizó la instalación, la responsabilidad sobre la sujeción y seguridad del anuncio "
            "recae íntegramente en quien la ejecutó. (3) El Proveedor no responde por pérdidas "
            "económicas ni perjuicios indirectos fuera del alcance de esta garantía. "
            "(4) El Cliente ha sido informado de las recomendaciones de mantenimiento básico: "
            "limpieza periódica, revisión de conexiones eléctricas y verificación de anclajes "
            "al menos una vez al año.",
            st["body"]
        ),
        Spacer(1, 0.5*cm),
        HRFlowable(width="100%", color=AZUL_DARK, thickness=0.5),
        Spacer(1, 0.3*cm),
        Paragraph(
            "Habiendo leído y entendido el contenido de esta acta, las partes la firman "
            "en dos ejemplares de igual valor.",
            st["small"]
        ),
        Spacer(1, 0.3*cm),
        _firma_block(empresa, "Cliente", st),
        Spacer(1, 0.2*cm),
        Paragraph("Testigo (si aplica): ____________________________  Firma: ____________________", st["small"]),
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", color=colors.lightgrey, thickness=0.5),
        Paragraph(f"{empresa}  ·  Acta de Entrega ENT-{folio}  ·  Garantía válida hasta {_un_ano(fecha)}", st["pie"]),
    ]))

    doc.build(elements)
    return buf.getvalue()


def _garantia_tbl(st: dict):
    cubre = (
        "✓ Desprendimiento de materiales por falla de adhesión de fabricación\n"
        "✓ Fallas estructurales en cercha o armazón por defecto de fabricación\n"
        "✓ Fallas en módulos LED o fuente por defecto de fábrica del componente\n"
        "✓ Deformaciones o roturas originadas por proceso de fabricación deficiente"
    )
    no_cubre = (
        "✗ Daños por mal uso, maltrato o manipulación indebida\n"
        "✗ Instalación incorrecta realizada por terceros ajenos al Proveedor\n"
        "✗ Decoloración u oxidación por exposición natural a la intemperie\n"
        "✗ Daños por fenómenos meteorológicos (granizo, vendaval, rayo, etc.)\n"
        "✗ Vandalismo, robo, accidentes de tráfico u eventos externos\n"
        "✗ Modificaciones realizadas sin autorización escrita del Proveedor\n"
        "✗ Fallas eléctricas de la instalación del cliente (voltaje, sobrecargas)\n"
        "✗ Falta de mantenimiento preventivo recomendado"
    )
    data = [
        [Paragraph("<b>QUÉ CUBRE</b>", ParagraphStyle("gc", fontSize=9, fontName="Helvetica-Bold", textColor=VERDE)),
         Paragraph("<b>QUÉ NO CUBRE</b>", ParagraphStyle("gnc", fontSize=9, fontName="Helvetica-Bold", textColor=colors.red))],
        [Paragraph(cubre.replace("\n", "<br/>"),
                   ParagraphStyle("cv", fontSize=8.5, leading=13)),
         Paragraph(no_cubre.replace("\n", "<br/>"),
                   ParagraphStyle("ncv", fontSize=8.5, leading=13))],
    ]
    tbl = Table(data, colWidths=[PW * 0.50, PW * 0.50])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (0, 0), VERDE_CLAR),
        ("BACKGROUND",  (1, 0), (1, 0), ROJO_CLARO),
        ("BACKGROUND",  (0, 1), (0, 1), VERDE_CLAR),
        ("BACKGROUND",  (1, 1), (1, 1), ROJO_CLARO),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("PADDING",     (0, 0), (-1, -1), 7),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _un_ano(fecha_str: str) -> str:
    try:
        d = datetime.strptime(fecha_str, "%d/%m/%Y")
        return d.replace(year=d.year + 1).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "—"


