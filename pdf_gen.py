import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

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
        ["Altura de letra",      f"{result.altura_letra_cm:.1f} cm"],
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
    doc = _doc_base(buf, "Orden de Trabajo")
    st  = _estilos()
    elements = []

    empresa = meta.get("empresa", "SGI Impresión y Diseño")
    folio   = meta.get("folio", "---")
    fecha   = meta.get("fecha", datetime.now().strftime("%d/%m/%Y"))
    cliente = meta.get("cliente") or "—"
    precio_final = result.precio_final or result.precio_venta_sugerido
    anticipo = round(precio_final * 0.50, 2)
    saldo    = round(precio_final - anticipo, 2)
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
    elements.append(Spacer(1, 0.4*cm))

    # Descripción autorizada
    elements.append(Paragraph("Descripción del Trabajo Autorizado", st["h2"]))
    desc_rows = [
        ["Producto",          tipo_label],
        ["Altura de letra",   f"{result.altura_letra_cm:.1f} cm"],
        ["Área total caras",  f"{result.area_cara_cm2:.1f} cm²"],
        ["Material cara",     result.material_cara.get("nombre", "—")],
        ["Material cercha",   result.material_cercha.get("nombre", "—")],
        ["Iluminación",       result.led.get("nombre", "Sin iluminación")],
        ["Tipo construcción", result.tipo_construccion.replace("_", " ").title()],
    ]
    elements.append(_tabla_kv(desc_rows))
    elements.append(Spacer(1, 0.3*cm))

    # Arte
    elements.append(Paragraph("Aprobación de Arte", st["h2"]))
    arte_data = [
        ["Arte aprobado:", "□ Sí  □ No  —  Archivo: ______________________________________"],
        ["Observaciones:", "________________________________________________________________"],
    ]
    elements.append(_tabla_kv(arte_data))
    elements.append(Spacer(1, 0.4*cm))

    # Condiciones de pago
    elements.append(Paragraph("Condiciones de Pago Acordadas", st["h2"]))
    pago_rows = [
        ["Total autorizado",  f"${precio_final:,.2f} MXN"],
        ["Anticipo (50%)",    f"${anticipo:,.2f} MXN"],
        ["Forma de pago",     "________________________________"],
        ["Fecha de anticipo", "________________________________"],
        ["Saldo pendiente",   f"${saldo:,.2f} MXN  (pagadero contra entrega)"],
    ]
    pago_tbl = Table(pago_rows, colWidths=[PW*0.42, PW*0.58])
    pago_tbl.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1), AZUL_DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("PADDING",        (0, 0), (-1, -1), 5),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR",      (1, 0), (1, 0),  NARANJA),
        ("FONTSIZE",       (0, 0), (-1, 0), 10),
    ]))
    elements.append(pago_tbl)
    elements.append(Spacer(1, 0.4*cm))

    # Compromisos
    elements.append(KeepTogether([
        Paragraph("Compromisos", st["h2"]),
        Paragraph(
            f"<b>{empresa}</b> se compromete a fabricar el anuncio conforme a las especificaciones y arte "
            "aprobado, en un plazo de <b>[__] días hábiles</b> a partir del anticipo y el arte final.<br/><br/>"
            "<b>El Cliente</b> declara haber revisado y aprobado las especificaciones, medidas, materiales "
            "y diseño de esta orden. Cambios posteriores a la firma podrán generar cargos adicionales y "
            "extensión del plazo.",
            st["body"]
        ),
        Spacer(1, 0.5*cm),
        HRFlowable(width="100%", color=AZUL_DARK, thickness=0.5),
        Spacer(1, 0.3*cm),
        Paragraph("Firmas de Conformidad", st["h2"]),
        Spacer(1, 0.2*cm),
        _firma_block(empresa, "Cliente", st),
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", color=colors.lightgrey, thickness=0.5),
        Paragraph(f"{empresa}  ·  Orden de Trabajo OT-{folio}", st["pie"]),
    ]))

    doc.build(elements)
    return buf.getvalue()


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
        ["Altura de letra",  f"{result.altura_letra_cm:.1f} cm"],
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
    except Exception:
        return "—"


# ─── PLANO DE MEDIDAS ────────────────────────────────────────────────────────

def generar_pdf_plano(meta: dict, svg_text: str,
                      real_width_cm: float, viewbox_w: float, viewbox_h: float,
                      paths: list) -> bytes:
    """Plano técnico de medidas — Landscape A4, cotas estilo ingeniería."""
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF as _rPDF
    except ImportError:
        raise RuntimeError("svglib no instalado — ejecuta: pip install svglib")

    import tempfile, os
    from reportlab.pdfgen import canvas as _cv
    from reportlab.lib.pagesizes import A4, landscape as _ls

    buf = io.BytesIO()
    PW, PH = _ls(A4)
    MAR = 1.1 * cm
    c = _cv.Canvas(buf, pagesize=(PW, PH))

    AZUL       = (0.10, 0.17, 0.29)
    DR, DG, DB = 0.12, 0.18, 0.52
    ER, EG, EB = 0.50, 0.56, 0.72
    GR, GG, GB = 0.60, 0.60, 0.60
    AH, AL     = 3.5, 8.0

    def get_bbox(p):
        return p.bbox if hasattr(p, "bbox") else (p.get("bbox") or {})

    sf_cm      = real_width_cm / viewbox_w if viewbox_w > 0 else 1.0
    real_h_cm  = real_width_cm * (viewbox_h / viewbox_w) if viewbox_w > 0 else 0.0
    proporcion = f"{real_width_cm / real_h_cm:.2f} : 1" if real_h_cm > 0 else "—"
    folio      = meta.get("folio", "")
    cliente    = meta.get("cliente") or "—"
    fecha      = (meta.get("fecha") or datetime.now().strftime("%Y-%m-%d"))[:10]

    # ── Agrupar paths en elementos lógicos ───────────────────────────────────
    # Prioridad 1: estructura <g> del SVG (refleja intención del diseñador).
    # Prioridad 2: solapamiento de bandas Y con restricción de relación de alturas.

    def _try_svg_groups(svg_str, path_infos):
        """Lee grupos <g> del SVG y fusiona bboxes de sus paths. Retorna None si no hay grupos reales."""
        try:
            import xml.etree.ElementTree as ET
            id_map = {}
            for p in (path_infos or []):
                sid = getattr(p, "svg_id", None) or getattr(p, "id", None) or ""
                if sid:
                    id_map[sid] = p
            if not id_map:
                return None
            root_el = ET.fromstring(svg_str)
        except Exception:
            return None

        def ns(t):
            return t.split("}", 1)[-1] if "}" in t else t

        def collect_ids(elem):
            ids = []
            if ns(elem.tag) in ("path", "circle", "ellipse", "rect", "polygon", "polyline"):
                eid = elem.get("id", "")
                if eid:
                    ids.append(eid)
            for ch in elem:
                ids.extend(collect_ids(ch))
            return ids

        def mbox(ids):
            ps = [id_map[i] for i in ids if i in id_map]
            if not ps:
                return None
            bb = lambda p: p.bbox
            xs = [bb(p).get("x", 0) for p in ps]
            ys = [bb(p).get("y", 0) for p in ps]
            x2 = [bb(p).get("x", 0) + bb(p).get("w", 0) for p in ps]
            y2 = [bb(p).get("y", 0) + bb(p).get("h", 0) for p in ps]
            return {"x": min(xs), "y": min(ys),
                    "w": max(x2) - min(xs), "h": max(y2) - min(ys)}

        def skip_wrap(elem, d=0):
            """Salta cadenas de <g> único (patrón artboard de Illustrator)."""
            gs  = [c for c in elem if ns(c.tag) == "g"]
            vis = [c for c in elem if ns(c.tag) not in
                   ("g", "defs", "style", "title", "metadata", "desc")]
            if len(gs) == 1 and not vis and d < 6:
                return skip_wrap(gs[0], d + 1)
            return elem

        content = skip_wrap(root_el)
        result  = []
        for ch in content:
            if ns(ch.tag) in ("defs", "style", "title", "desc", "metadata"):
                continue
            ids = collect_ids(ch)
            if not ids:
                continue
            bb = mbox(ids)
            if not bb:
                continue
            gid = ch.get("id", "") or f"g{len(result)}"
            mbbs = [dict(id_map[i].bbox) for i in ids if i in id_map]
            result.append({"x": bb["x"], "y": bb["y"], "w": bb["w"], "h": bb["h"],
                           "ids": ids, "n": len(ids), "group_id": gid,
                           "member_bbs": mbbs})

        # Solo considerar válido si hay al menos un grupo con múltiples paths
        return result if any(g["n"] > 1 for g in result) else None

    def _cluster_by_overlap(all_paths):
        """Agrupa paths cuyas bandas Y se solapan, sin mezclar elementos de alturas muy distintas."""
        if not all_paths:
            return []
        ordered = sorted(all_paths, key=lambda p: get_bbox(p).get("y", 0))
        clusters = []
        for p in ordered:
            bb  = get_bbox(p)
            py1 = bb.get("y", 0)
            py2 = py1 + bb.get("h", 0)
            ph  = max(py2 - py1, 1)
            added = False
            for cl in clusters:
                ov = min(py2, cl["bot"]) - max(py1, cl["top"])
                if ov > 0:
                    ch = max(cl["bot"] - cl["top"], 1)
                    # Solo unir si las alturas son similares (factor ≤ 2)
                    if max(ch, ph) / min(ch, ph) <= 2.0:
                        cl["members"].append(p)
                        cl["top"] = min(cl["top"], py1)
                        cl["bot"] = max(cl["bot"], py2)
                        added = True
                        break
            if not added:
                clusters.append({"members": [p], "top": py1, "bot": py2})
        result = []
        for cl in clusters:
            bbs   = [get_bbox(q) for q in cl["members"]]
            min_x = min(b.get("x", 0) for b in bbs)
            min_y = min(b.get("y", 0) for b in bbs)
            max_x = max(b.get("x", 0) + b.get("w", 0) for b in bbs)
            max_y = max(b.get("y", 0) + b.get("h", 0) for b in bbs)
            ids   = [getattr(q, "svg_id", None) or getattr(q, "id", None) or "?"
                     for q in cl["members"]]
            result.append({"x": min_x, "y": min_y,
                           "w": max_x - min_x, "h": max_y - min_y,
                           "ids": ids, "n": len(cl["members"]),
                           "member_bbs": bbs})   # bboxes individuales para cotas de ancho
        return result

    # Etapa 1: grupos del SVG; Etapa 2: solapamiento Y
    clusters_raw = (_try_svg_groups(svg_text, paths) if svg_text else None) \
                   or _cluster_by_overlap(paths or [])
    clusters = clusters_raw or []
    total_area = (viewbox_w or 1) * (viewbox_h or 1)
    min_w_px   = (viewbox_w or 0) * 0.04
    min_h_px   = (viewbox_h or 0) * 0.02

    # Excluir: demasiado pequeños O demasiado grandes (paths de fondo que cubren > 60 %)
    sig = sorted(
        [cl for cl in clusters
         if cl["w"] >= min_w_px and cl["h"] >= min_h_px
         and cl["w"] * cl["h"] <= total_area * 0.60],
        key=lambda cl: cl["w"] * cl["h"],
        reverse=True
    )[:6]
    N_e = len(sig)

    # ── Layout ────────────────────────────────────────────────────────────────
    HDR_H      = 28
    TABLE_H    = 148
    VSTEP      = 22
    TOP_ZONE   = 35        # solo la cota global de ancho
    RIGHT_ZONE = max(24, 14 + N_e * VSTEP) + 8
    LEFT_ZONE  = 34

    svg_left    = MAR + LEFT_ZONE
    svg_right   = PW  - MAR - RIGHT_ZONE
    svg_top_lyt = PH  - HDR_H - 6 - TOP_ZONE
    svg_bot     = TABLE_H
    avail_w     = svg_right  - svg_left
    avail_h     = svg_top_lyt - svg_bot

    # ── Header ────────────────────────────────────────────────────────────────
    c.setFillColorRGB(*AZUL)
    c.rect(0, PH - HDR_H, PW, HDR_H, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MAR, PH - HDR_H + 8, "SGI — PLANO DE MEDIDAS")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(PW - MAR, PH - HDR_H + 8,
                      f"{folio}   ·   {cliente}   ·   {fecha}")

    # ── Renderizar SVG ────────────────────────────────────────────────────────
    svg_x = svg_left; svg_y = svg_bot
    svg_rw = avail_w;  svg_rh = avail_h

    if svg_text:
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".svg",
                                              mode="w", encoding="utf-8")
            tmp.write(svg_text); tmp.close()
            rlg = svg2rlg(tmp.name)
            os.unlink(tmp.name)
        except Exception:
            rlg = None
        if rlg and rlg.width > 0 and rlg.height > 0:
            sc     = min(avail_w / rlg.width, avail_h / rlg.height)
            svg_rw = rlg.width  * sc
            svg_rh = rlg.height * sc
            svg_x  = svg_left + (avail_w - svg_rw) / 2
            svg_y  = svg_bot  + (avail_h - svg_rh) / 2
            rlg.width = svg_rw; rlg.height = svg_rh
            rlg.transform = (sc, 0, 0, sc, 0, 0)
            c.saveState()
            c.translate(svg_x, svg_y)
            _rPDF.draw(rlg, c, 0, 0)
            c.restoreState()

    c.setStrokeColorRGB(GR, GG, GB); c.setLineWidth(0.3)
    c.rect(svg_x, svg_y, svg_rw, svg_rh, stroke=1, fill=0)

    pdf_sc    = (svg_rw / viewbox_w) if viewbox_w > 0 else 1.0
    pdf_sc_y  = (svg_rh / viewbox_h) if viewbox_h > 0 else pdf_sc
    svg_top_y = svg_y + svg_rh

    # Offset del viewBox (min-x, min-y) — Illustrator exporta con origen ≠ 0.
    # svgpathtools devuelve coords absolutas; debemos restarle el origen del viewBox.
    vb_ox, vb_oy = 0.0, 0.0
    if svg_text:
        try:
            import xml.etree.ElementTree as _ET
            _svgr = _ET.fromstring(svg_text)
            _vbs  = _svgr.get("viewBox") or _svgr.get("viewbox") or ""
            _vbp  = _vbs.replace(",", " ").split()
            if len(_vbp) == 4:
                vb_ox, vb_oy = float(_vbp[0]), float(_vbp[1])
        except Exception:
            pass

    def to_pdf(bb):
        """bbox SVG → (px1, px2, py_bot, py_top) en pts PDF, corrigiendo offset viewBox."""
        bx = bb.get("x", 0) - vb_ox
        by = bb.get("y", 0) - vb_oy
        bw, bh = bb.get("w", 0), bb.get("h", 0)
        px1    = svg_x + bx * pdf_sc
        px2    = svg_x + (bx + bw) * pdf_sc
        py_top = svg_y + svg_rh - by * pdf_sc_y
        py_bot = svg_y + svg_rh - (by + bh) * pdf_sc_y
        return px1, px2, py_bot, py_top

    # ── Primitivas ────────────────────────────────────────────────────────────
    def _arrow(x, y, dx, dy):
        c.setFillColorRGB(DR, DG, DB)
        nx, ny = -dy, dx
        p = c.beginPath()
        p.moveTo(x, y)
        p.lineTo(x + dx*AL + nx*AH, y + dy*AL + ny*AH)
        p.lineTo(x + dx*AL - nx*AH, y + dy*AL - ny*AH)
        p.close()
        c.drawPath(p, fill=1, stroke=0)

    def hdim(x1, x2, y_line, label, ext_y=None, fsz=6.5):
        if ext_y is not None:
            c.setStrokeColorRGB(ER, EG, EB); c.setLineWidth(0.35)
            c.line(x1, ext_y, x1, y_line + 3)
            c.line(x2, ext_y, x2, y_line + 3)
        c.setStrokeColorRGB(DR, DG, DB); c.setLineWidth(0.75)
        c.line(x1 + AL, y_line, x2 - AL, y_line)
        _arrow(x1, y_line, -1, 0)
        _arrow(x2, y_line, +1, 0)
        span = x2 - x1
        if label and span > 22:
            c.setFont("Helvetica-Bold", fsz)
            lw = c.stringWidth(label, "Helvetica-Bold", fsz)
            mx = (x1 + x2) / 2
            if lw + 6 < span * 0.88:
                c.setFillColorRGB(1, 1, 1)
                c.rect(mx - lw/2 - 2, y_line + 1.5, lw + 4, fsz + 1.5, fill=1, stroke=0)
                c.setFillColorRGB(DR, DG, DB)
                c.drawCentredString(mx, y_line + 3, label)
            else:
                c.setFillColorRGB(1, 1, 1)
                c.rect(mx - lw/2 - 2, y_line + fsz + 4, lw + 4, fsz + 2, fill=1, stroke=0)
                c.setFillColorRGB(DR, DG, DB)
                c.drawCentredString(mx, y_line + fsz + 5, label)

    def vdim(x_line, y1, y2, label, ext_x=None, fsz=6.5, lbl_left=True):
        if ext_x is not None:
            c.setStrokeColorRGB(ER, EG, EB); c.setLineWidth(0.35)
            c.line(ext_x, y1, x_line + 3, y1)
            c.line(ext_x, y2, x_line + 3, y2)
        c.setStrokeColorRGB(DR, DG, DB); c.setLineWidth(0.75)
        c.line(x_line, y1 + AL, x_line, y2 - AL)
        _arrow(x_line, y1, 0, -1)
        _arrow(x_line, y2, 0, +1)
        if label and (y2 - y1) > 18:
            mid = (y1 + y2) / 2
            off = -(fsz + 6) if lbl_left else (fsz + 4)
            c.saveState()
            c.translate(x_line + off, mid)
            c.rotate(90)
            c.setFont("Helvetica-Bold", fsz)
            lw = c.stringWidth(label, "Helvetica-Bold", fsz)
            c.setFillColorRGB(1, 1, 1)
            c.rect(-lw/2 - 2, -1, lw + 4, fsz + 2.5, fill=1, stroke=0)
            c.setFillColorRGB(DR, DG, DB)
            c.drawCentredString(0, 1, label)
            c.restoreState()

    # ── COTA GLOBAL ANCHO (margen superior) ──────────────────────────────────
    hdim(svg_x, svg_x + svg_rw, svg_top_y + 22,
         f"{real_width_cm:.2f} cm", ext_y=svg_top_y, fsz=9)

    # ── COTA GLOBAL ALTO (margen izquierdo) ───────────────────────────────────
    vdim(svg_x - 24, svg_y, svg_top_y,
         f"{real_h_cm:.2f} cm", ext_x=svg_x, fsz=9, lbl_left=True)

    # ── COTAS POR GRUPO ───────────────────────────────────────────────────────
    # Ancho: una cota por ELEMENTO INDIVIDUAL (letra/path) dentro de cada fila.
    #        Si hay un solo elemento, muestra su cota directamente.
    # Alto:  una cota por FILA (alto fusionado), margen derecho apilado.
    vert_sorted = sorted(sig, key=lambda cl: cl["h"])

    for i, cl in enumerate(sig):
        # Obtener bboxes individuales; si no están, usar el bbox del cluster completo
        members = cl.get("member_bbs") or [cl]
        # Filtrar miembros con ancho significativo y ordenar de izquierda a derecha
        members = sorted(
            [m for m in members if m.get("w", 0) * sf_cm >= 0.5],
            key=lambda m: m.get("x", 0)
        )
        # Limitar a 10 para no saturar el plano
        for mbb in members[:10]:
            mpx1, mpx2, mpy_bot, mpy_top = to_pdf(mbb)
            wc = mbb.get("w", 0) * sf_cm
            if (mpx2 - mpx1) > 18:
                hdim(mpx1, mpx2, mpy_top, f"{wc:.1f} cm", ext_y=None, fsz=6.5)

    for level, cl in enumerate(vert_sorted):
        px1, px2, py_bot, py_top = to_pdf(cl)
        hc = cl["h"] * sf_cm
        if (py_top - py_bot) < 10:
            continue
        x_cota = svg_x + svg_rw + 14 + level * VSTEP
        vdim(x_cota, py_bot, py_top,
             f"{hc:.1f} cm", ext_x=px2, fsz=6.0, lbl_left=False)

    # ── CÍRCULOS NUMERADOS sobre la imagen ────────────────────────────────────
    for i, cl in enumerate(sig):
        px1, px2, py_bot, py_top = to_pdf(cl)
        cx, cy = (px1 + px2) / 2, (py_bot + py_top) / 2
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(DR, DG, DB)
        c.setLineWidth(1.3)
        c.circle(cx, cy, 7, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColorRGB(DR, DG, DB)
        c.drawCentredString(cx, cy - 2.5, str(i + 1))

    # ── TABLA (inferior izquierda) ─────────────────────────────────────────────
    TBL_TOP = TABLE_H - 6
    tl = MAR; tr = PW * 0.60
    cols_w = [22, 140, 62, 62, 68]
    row_h  = 11

    c.setFillColorRGB(*AZUL)
    c.rect(tl, TBL_TOP - 13, tr - tl, 14, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica-Bold", 7)
    c.drawString(tl + 4, TBL_TOP - 6, "ELEMENTOS DEL DISEÑO")

    def _row(vals, y, bold=False, shade=False):
        if shade:
            c.setFillColorRGB(0.95, 0.96, 0.98)
            c.rect(tl, y - row_h + 2, tr - tl, row_h, fill=1, stroke=0)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 6.5)
        c.setFillColorRGB(*(AZUL if bold else (0.1, 0.1, 0.1)))
        x = tl + 3
        for v, cw in zip(vals, cols_w):
            c.drawString(x, y - row_h + 4, str(v)); x += cw
        c.setStrokeColorRGB(GR, GG, GB); c.setLineWidth(0.25)
        c.line(tl, y - row_h + 2, tr, y - row_h + 2)

    ry = TBL_TOP - 14
    _row(["#", "Elemento", "Ancho (cm)", "Alto (cm)", "Área (cm²)"], ry, bold=True)
    ry -= row_h
    row_num = 1
    for i, cl in enumerate(sig):
        hc_cl = round(cl["h"] * sf_cm, 2)
        members = cl.get("member_bbs") or [cl]
        members = sorted(
            [m for m in members if m.get("w", 0) * sf_cm >= 0.5],
            key=lambda m: m.get("x", 0)
        )
        ids = cl.get("ids", [])
        gid = cl.get("group_id", "")
        base_label = gid if gid else (ids[0] if len(ids) == 1 else f"Grupo {i+1}")
        for j, mbb in enumerate(members[:10]):
            wc = round(mbb.get("w", 0) * sf_cm, 2)
            hc = round(mbb.get("h", 0) * sf_cm, 2) or hc_cl
            lbl = base_label if len(members) == 1 else f"{base_label} [{j+1}]"
            _row([f"{row_num}", lbl, f"{wc:.2f}", f"{hc:.2f}", f"{wc*hc:.2f}"],
                 ry, shade=(row_num % 2 == 0))
            row_num += 1
            ry -= row_h
            if ry < 8:
                break
        if ry < 8:
            break

    # ── RESUMEN + NOTAS (inferior derecha) ────────────────────────────────────
    RX = PW * 0.62; RW = PW - RX - MAR

    def _mini(title, rows, rx, ry_top, rw):
        c.setFillColorRGB(*AZUL)
        c.rect(rx, ry_top - 13, rw, 14, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica-Bold", 7)
        c.drawString(rx + 4, ry_top - 6, title)
        cy = ry_top - 13
        for k, v in rows:
            cy -= 11
            c.setFont("Helvetica-Bold", 6.5); c.setFillColorRGB(*AZUL)
            c.drawString(rx + 4, cy + 3, k)
            c.setFont("Helvetica", 6.5); c.setFillColorRGB(0.1, 0.1, 0.1)
            c.drawRightString(rx + rw - 4, cy + 3, v)
            c.setStrokeColorRGB(GR, GG, GB); c.setLineWidth(0.2)
            c.line(rx, cy, rx + rw, cy)
        return cy

    ry2 = TBL_TOP
    ry2 = _mini("RESUMEN GENERAL", [
        ("Medida total:", f"{real_width_cm:.2f} × {real_h_cm:.2f} cm"),
        ("Proporción:",   proporcion),
        ("Grupos:",       str(N_e)),
    ], RX, ry2, RW)
    ry2 -= 8
    _mini("NOTAS", [
        ("", "Todas las medidas en cm."),
        ("", "Verificar en obra antes de fabricar."),
    ], RX, ry2, RW)

    c.setFont("Helvetica", 5.5); c.setFillColorRGB(GR, GG, GB)
    c.drawCentredString(PW / 2, 4,
                        f"SGI Impresión y Diseño  ·  Plano {folio}  ·  {fecha}")
    c.save()
    return buf.getvalue()
