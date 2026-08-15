"""Motor de cotización de anuncios de neón LED (SGI).

Portado de `_handoff-neon/calcularNeon.js` — motor calibrado contra 22 pares
reales de imagen+DST del taller. Función pura sin efectos secundarios.

Soporta dos modos de fabricación:
  - "lamina" (tradicional): base cortada + kit soporte + desperdicio
  - "3d"    (Signflex-style): canal PETG impreso siguiendo el trazo,
                              reemplaza base por filamento + horas + anclajes + puentes

El input viene como dicts (perfil, base, params, fuente). No lee catálogos:
todo se pasa por argumentos para que el mismo motor sirva desde el endpoint
FastAPI y desde los tests pytest sin fixtures externos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _round2(n: float) -> float:
    """Round a 2 decimales — usa banker's rounding de Python (mismo resultado
    práctico que el `Math.round((n+EPSILON)*100)/100` del JS original para
    los rangos de precios que manejamos)."""
    return round(float(n), 2)


def _num(v, default: float = 0.0) -> float:
    """Convierte a float con fallback (JS: `Number(v) || default`)."""
    try:
        f = float(v)
        return f if f == f else default   # NaN check
    except (TypeError, ValueError):
        return default


def _pos_num(v, default: float = 0.0) -> float:
    """Como _num pero si el valor es <=0 devuelve default (JS: `Number(v) > 0 ? v : default`)."""
    f = _num(v, default)
    return f if f > 0 else default


# ─── RESULTADO ───────────────────────────────────────────────────────────────

@dataclass
class NeonQuoteResult:
    """Resultado de una cotización de neón. Se serializa a JSON via
    `dataclasses.asdict(...)` para persistir en SQLite (columna `result_json`)."""
    tipo: str = "neon"
    modo_fabricacion: str = "lamina"      # "lamina" | "3d"

    # Neón
    lm: float = 0.0
    uniones: int = 0
    watts_total: float = 0.0
    num_fuentes: int = 0
    fuente_nombre: str = ""
    fuente_watts: float = 0.0
    fuente_tipo: str = "fuente"

    # Dimensiones
    ancho_cm: float = 0.0
    alto_cm: float = 0.0
    area_m2: float = 0.0
    perim_m: float = 0.0

    # Base (modo lámina)
    base_mat: str = ""
    base_tipo: str = ""
    base_forma: str = ""
    importe_base: float = 0.0
    importe_base_auto: float = 0.0
    desperdicio_m2: float = 0.0
    desperdicio_tira_cm: float = 0.0
    importe_desperdicio: float = 0.0

    # Modo 3D
    gramos: float = 0.0
    gramos_auto: float = 0.0
    horas_imp: float = 0.0
    horas_imp_auto: float = 0.0
    anclajes: int = 0
    puentes: int = 0
    tira_led_mm: float = 0.0
    canal_ancho_mm: float = 0.0
    canal_alto_mm: float = 0.0
    canal_pared_mm: float = 0.0
    importe_filamento: float = 0.0
    importe_impresion: float = 0.0
    importe_anclajes: float = 0.0
    importe_puentes: float = 0.0

    # Comercial
    insumos: list[dict] = field(default_factory=list)
    total_insumos: float = 0.0
    horas: float = 0.0
    mano_obra: float = 0.0
    mano_obra_auto: float = 0.0
    costo_directo: float = 0.0
    merma: float = 0.0
    margen: float = 0.0
    urgencia_mult: float = 1.0
    subtotal: float = 0.0
    precio: float = 0.0
    iva: float = 0.0
    precio_iva: float = 0.0

    # Aliases requeridos por el ciclo de instalación de main._apply_instalacion
    # (por consistencia con los otros tipos que usan precio_venta_sugerido +
    # inst_total = precio_final).
    precio_venta_sugerido: float = 0.0
    mo_total: float = 0.0
    inst_activa: bool = False
    inst_lugar: str = ""
    inst_viaticos: float = 0.0
    inst_grua: str = ""
    inst_costo_grua: float = 0.0
    inst_extras: float = 0.0
    inst_total: float = 0.0
    precio_final: float = 0.0


# ─── MOTOR ───────────────────────────────────────────────────────────────────

def cotizar_neon(
    *,
    Lm: float = 0.0,
    uniones: int = 0,
    perfil: dict | None = None,
    tramos: list[dict] | None = None,
    fuente: dict | None = None,
    dimensiones: dict | None = None,
    base: dict | None = None,
    params: dict | None = None,
    urgencia_mult: float = 1.0,
    mano_obra_override: float | None = None,
) -> NeonQuoteResult:
    """Cotiza un anuncio de neón. Puerto fiel de `calcularNeon` (JS).

    Args:
      Lm: longitud lineal de neón en metros (usada si `tramos` está vacío).
      uniones: número de uniones entre tramos.
      perfil: dict de perfil {id, nombre, color, precio_m, watts_m}.
      tramos: lista de {perfil, Lm} para multi-color; si viene, ignora `Lm` global.
      fuente: dict de fuente {nombre, watts, precio, tipo}.
      dimensiones: {ancho_cm, alto_cm}.
      base: {material, forma, modo_fabricacion, fab3d, incluir_soporte, ...}.
      params: parámetros generales (ver NEON_PARAMS_DEFAULTS).
      urgencia_mult: multiplicador de urgencia (1.0 normal, 1.45 express, etc.).
      mano_obra_override: si se pasa, ignora el cálculo auto de MO.

    Returns:
      NeonQuoteResult con desglose completo (insumos, subtotal, precio, IVA).
    """
    p = params or NEON_PARAMS_DEFAULTS
    urg = max(0.01, _num(urgencia_mult, 1.0))
    dim = dimensiones or {"ancho_cm": 0, "alto_cm": 0}
    b_mat = (base or {}).get("material") or {"nombre": "Sin base", "precio_m2": 0}
    b_for = (base or {}).get("forma")    or {"nombre": "Rectangular", "factor_area": 1, "corte_m": 0}
    modo_fab = "3d" if (base or {}).get("modo_fabricacion") == "3d" else "lamina"
    cfg3d = p.get("fab3d") or NEON_PARAMS_DEFAULTS["fab3d"]

    # Fuente: si no viene, toma la primera activa del catálogo, o un fallback mínimo.
    F = fuente
    if not F:
        fuentes = p.get("fuentes") or []
        F = next((f for f in fuentes if f.get("activo") is not False), None)
    if not F:
        F = {"nombre": "Fuente", "watts": 100, "precio": 380}

    # ── Normalización de tramos (multi-color / multi-perfil) ──────────────────
    raw_tramos = tramos if (tramos and len(tramos) > 0) else [
        {"perfil": perfil or {"precio_m": 0, "watts_m": 0}, "Lm": Lm}
    ]
    grouped: dict[str, dict] = {}
    for t in raw_tramos:
        pf = t.get("perfil") or {"precio_m": 0, "watts_m": 0}
        key = pf.get("id") or (str(pf.get("nombre", "")) + "·" + str(pf.get("color", ""))) or "_"
        lm = max(0.0, _num(t.get("Lm"), 0.0))
        if key not in grouped:
            grouped[key] = {"perfil": pf, "Lm": 0.0}
        grouped[key]["Lm"] += lm

    g_tramos = [t for t in grouped.values() if t["Lm"] > 0]
    L = sum(t["Lm"] for t in g_tramos)
    un = max(0, int(_num(uniones, 0)))
    watts_total = sum(t["Lm"] * _num(t["perfil"].get("watts_m"), 0) for t in g_tramos)

    # ── Fuentes de poder (dimensionamiento por watts) ─────────────────────────
    cap_fuente = _num(F.get("watts"), 0) * _num(p.get("fuente_factor"), 0.8)
    if cap_fuente > 0:
        min_fuentes = 1 if L > 0 else 0
        num_fuentes = max(min_fuentes, math.ceil(watts_total / cap_fuente))
    else:
        num_fuentes = 0

    # ── Área y perímetro de la base ───────────────────────────────────────────
    ancho_cm = _num(dim.get("ancho_cm"), 0)
    alto_cm  = _num(dim.get("alto_cm"),  0)
    ancho_m = ancho_cm / 100
    alto_m  = alto_cm  / 100
    # Nota: `round2(x*100)/100` = 4 decimales — se mantiene la fórmula original
    # del JS para paridad exacta con la calibración de taller.
    area_rect_m2 = _round2(ancho_m * alto_m * 100) / 100
    area_m2      = _round2(area_rect_m2 * _num(b_for.get("factor_area"), 1) * 100) / 100
    perim_m      = _round2(2 * (ancho_m + alto_m) * 100) / 100

    # ── Bloque de base según modo de fabricación ──────────────────────────────
    importe_base = 0.0
    importe_base_auto = 0.0
    importe_desperdicio = 0.0
    desperdicio_m2 = 0.0
    desperdicio_tira_cm = 0.0
    tipo_base = b_mat.get("tipo_precio") or ("lamina" if b_mat.get("precio_lamina") else "pieza")

    if modo_fab == "3d":
        pass  # Sin base recortada — el canal se imprime siguiendo el trazo.
    elif tipo_base == "lamina":
        # Se compra por lámina completa; se prorratea al área usada.
        lW = _num(b_mat.get("lamina_w"), 120)
        lH = _num(b_mat.get("lamina_h"), 240)
        lamina_cm2 = lW * lH
        precio_lam = _num(b_mat.get("precio_lamina"), 0)
        precio_cm2 = precio_lam / lamina_cm2 if lamina_cm2 > 0 else 0
        area_cm2_util = area_m2 * 10000
        importe_base = _round2(area_cm2_util * precio_cm2)

        if (base or {}).get("cobrar_desperdicio") and ancho_cm > 0 and alto_cm > 0 and precio_cm2 > 0:
            gaps: list[float] = []
            if ancho_cm <= lW and alto_cm  <= lH: gaps.append(lW - ancho_cm)
            if alto_cm  <= lW and ancho_cm <= lH: gaps.append(lW - alto_cm)
            if gaps:
                desperdicio_tira_cm = min(gaps)
                umbral = _num(p.get("desperdicio_umbral_cm"), 30)
                if 0 < desperdicio_tira_cm <= umbral:
                    waste_cm2 = desperdicio_tira_cm * lH
                    desperdicio_m2      = _round2(waste_cm2 / 10000 * 100) / 100
                    importe_desperdicio = _round2(waste_cm2 * precio_cm2)
    else:
        # Se compra ya cortado a medida (MDF típicamente).
        importe_base_auto = _round2(area_m2 * _num(b_mat.get("precio_m2"), 0))
        override_pieza = _num((base or {}).get("pieza_costo_override"), 0)
        importe_base = _round2(override_pieza) if override_pieza > 0 else importe_base_auto

    importe_corte       = 0.0 if modo_fab == "3d" else _round2(perim_m * _num(b_for.get("corte_m"), 0))
    importe_corte_extra = 0.0 if modo_fab == "3d" else _round2(max(0, _num((base or {}).get("corte_extra"), 0)))
    importe_soporte = (_num(p.get("soporte_precio"), 0)
                       if (modo_fab != "3d" and (base or {}).get("incluir_soporte"))
                       else 0.0)

    # ── Partidas del modo 3D ──────────────────────────────────────────────────
    fab3d_in = (base or {}).get("fab3d") or {}
    canal_ancho_mm = _num(fab3d_in.get("canal_ancho_mm"), 0)
    canal_alto_mm  = _num(fab3d_in.get("canal_alto_mm"),  0)
    canal_pared_mm = _num(fab3d_in.get("canal_pared_mm"), 0)
    if canal_ancho_mm > 0 and canal_alto_mm > 0 and canal_pared_mm > 0:
        # Sección "en U": base + 2 paredes verticales
        # area (cm²) = (ancho·pared + 2·alto·pared) / 100  ← mm² a cm²
        area_sec_cm2 = (canal_ancho_mm * canal_pared_mm
                        + 2 * canal_alto_mm * canal_pared_mm) / 100
        densidad = _num(cfg3d.get("filamento_dens_g"), 1.24)
        gramos_auto = _round2(area_sec_cm2 * (L * 100) * densidad)
    else:
        gramos_auto = _round2(L * _num(cfg3d.get("peso_gr_m"), 55))

    gramos_ov = _num(fab3d_in.get("gramos_override"), 0)
    gramos = _round2(gramos_ov) if gramos_ov > 0 else gramos_auto

    hpmpm = _num(cfg3d.get("horas_m_por_hora"), 0)
    horas_imp_auto = _round2(L / hpmpm * 100) / 100 if hpmpm > 0 else 0.0
    horas_imp_ov = _num(fab3d_in.get("horas_imp_override"), 0)
    horas_imp = _round2(horas_imp_ov * 100) / 100 if horas_imp_ov > 0 else horas_imp_auto

    anclajes_n = max(0, int(_num(fab3d_in.get("anclajes"), 0)))
    puentes_n  = max(0, int(_num(fab3d_in.get("puentes"),  0)))
    tira_led_mm = _num(fab3d_in.get("tira_led_mm"), 0)

    filamento_precio_g = _num(cfg3d.get("filamento_mxn_g"), 0)
    impresion_mxn_hora = _num(cfg3d.get("horas_mxn_hora"),  0)
    anclo_precio       = _num(cfg3d.get("anclo_precio"),    0)
    puente_precio      = _num(cfg3d.get("puente_precio"),   0)

    importe_filamento = _round2(gramos * filamento_precio_g)
    importe_impresion = _round2(horas_imp * impresion_mxn_hora)
    importe_anclajes  = _round2(anclajes_n * anclo_precio)
    importe_puentes   = _round2(puentes_n * puente_precio)

    # ── Ensamble de partidas ──────────────────────────────────────────────────
    insumos: list[dict] = []
    for t in g_tramos:
        pf = t["perfil"]
        color = pf.get("color")
        nombre_perfil = pf.get("nombre", "Manguera")
        concepto = (f"Neón LED · {nombre_perfil} {color}"
                    if color else f"Neón LED · {nombre_perfil}")
        precio_m = _num(pf.get("precio_m"), 0)
        insumos.append({
            "concepto": concepto,
            "cantidad": _round2(t["Lm"]),
            "unidad": "m",
            "unit": precio_m,
            "importe": _round2(t["Lm"] * precio_m),
        })

    cable_m = _num(p.get("cable_m"), 0)
    acces_m = _num(p.get("acces_m"), 0)
    insumos.append({"concepto": "Cable",       "cantidad": _round2(L), "unidad": "m",
                    "unit": cable_m, "importe": _round2(L * cable_m)})
    insumos.append({"concepto": "Accesorios",  "cantidad": _round2(L), "unidad": "m",
                    "unit": acces_m, "importe": _round2(L * acces_m)})
    insumos.append({"concepto": F.get("nombre", "Fuente"),
                    "cantidad": num_fuentes, "unidad": "pza",
                    "unit": _num(F.get("precio"), 0),
                    "importe": _round2(num_fuentes * _num(F.get("precio"), 0))})

    if modo_fab == "3d":
        if importe_filamento > 0:
            concepto_fil = (f"Filamento PETG · canal para tira {int(tira_led_mm)} mm"
                            if tira_led_mm > 0
                            else "Filamento PETG · canal impreso")
            insumos.append({"concepto": concepto_fil, "cantidad": _round2(gramos),
                            "unidad": "g", "unit": filamento_precio_g,
                            "importe": importe_filamento})
        if importe_impresion > 0:
            insumos.append({"concepto": "Horas de impresora 3D",
                            "cantidad": _round2(horas_imp), "unidad": "h",
                            "unit": impresion_mxn_hora, "importe": importe_impresion})
        if importe_anclajes > 0:
            insumos.append({"concepto": "Anclajes (tornillo + taco)",
                            "cantidad": anclajes_n, "unidad": "pza",
                            "unit": anclo_precio, "importe": importe_anclajes})
        if importe_puentes > 0:
            insumos.append({"concepto": "Puentes (crossover entre trazos)",
                            "cantidad": puentes_n, "unidad": "pza",
                            "unit": puente_precio, "importe": importe_puentes})
    else:
        if importe_base > 0:
            if tipo_base == "lamina" and b_mat.get("precio_lamina"):
                lW = _num(b_mat.get("lamina_w"), 120)
                lH = _num(b_mat.get("lamina_h"), 240)
                unit_base = _round2((_num(b_mat.get("precio_lamina"), 0) / (lW * lH)) * 10000)
            else:
                unit_base = _num(b_mat.get("precio_m2"), 0)
            insumos.append({
                "concepto": f"Base · {b_mat.get('nombre', 'Base')} ({b_for.get('nombre', '')})",
                "cantidad": area_m2, "unidad": "m²",
                "unit": unit_base, "importe": importe_base,
            })
        if importe_desperdicio > 0:
            insumos.append({
                "concepto": f"Desperdicio de lámina (tira {int(desperdicio_tira_cm)} cm)",
                "cantidad": desperdicio_m2, "unidad": "m²",
                "unit": _round2(importe_desperdicio / (desperdicio_m2 or 1)),
                "importe": importe_desperdicio,
            })
        if importe_corte > 0:
            insumos.append({"concepto": f"Corte especial ({b_for.get('nombre', '')})",
                            "cantidad": perim_m, "unidad": "m",
                            "unit": _num(b_for.get("corte_m"), 0),
                            "importe": importe_corte})
        if importe_corte_extra > 0:
            insumos.append({"concepto": "Corte láser adicional (manual)",
                            "cantidad": 1, "unidad": "lote",
                            "unit": importe_corte_extra, "importe": importe_corte_extra})
        if importe_soporte > 0:
            insumos.append({"concepto": "Kit de separadores / soportes",
                            "cantidad": 1, "unidad": "kit",
                            "unit": _num(p.get("soporte_precio"), 0),
                            "importe": importe_soporte})

    # Consumibles como % sobre materiales (cianoacrilato, soldadura, varios)
    pct = max(0, _num(p.get("consumibles_pct"), 0))
    base_para_pct = sum(x["importe"] for x in insumos)
    importe_consum = _round2(base_para_pct * pct)
    if importe_consum > 0:
        insumos.append({
            "concepto": f"Consumibles (cianoacrilato + soldadura) · {round(pct * 100)}%",
            "cantidad": 1, "unidad": "lote",
            "unit": importe_consum, "importe": importe_consum,
        })
    total_insumos = _round2(sum(x["importe"] for x in insumos))

    # ── Mano de obra + margen + urgencia + IVA ────────────────────────────────
    m_por_min = _num(p.get("m_por_min"), 0)
    tarifa_h  = _num(p.get("tarifa_hora"), 0)
    horas = L / m_por_min / 60 if m_por_min > 0 else 0.0
    mano_obra_auto = _round2(horas * tarifa_h)

    if mano_obra_override is not None and mano_obra_override != "":
        mano_obra = _round2(max(0, _num(mano_obra_override, 0)))
    else:
        mano_obra = mano_obra_auto

    merma  = _num(p.get("merma"),  0)
    margen = _num(p.get("margen"), 0)
    costo_directo = _round2(total_insumos + mano_obra)
    subtotal = _round2(costo_directo * (1 + merma))
    precio   = _round2(subtotal * (1 + margen) * urg)
    iva      = _round2(precio * 0.16)
    precio_iva = _round2(precio + iva)

    return NeonQuoteResult(
        tipo="neon",
        modo_fabricacion=modo_fab,
        lm=L, uniones=un, watts_total=_round2(watts_total), num_fuentes=num_fuentes,
        fuente_nombre=F.get("nombre", ""),
        fuente_watts=_num(F.get("watts"), 0),
        fuente_tipo=F.get("tipo", "fuente"),
        ancho_cm=_num(dim.get("ancho_cm"), 0),
        alto_cm=_num(dim.get("alto_cm"), 0),
        area_m2=area_m2, perim_m=perim_m,
        base_mat=b_mat.get("nombre", ""),
        base_tipo=tipo_base,
        base_forma=b_for.get("nombre", ""),
        importe_base=importe_base,
        importe_base_auto=importe_base_auto,
        desperdicio_m2=desperdicio_m2,
        desperdicio_tira_cm=desperdicio_tira_cm,
        importe_desperdicio=importe_desperdicio,
        insumos=insumos, total_insumos=total_insumos,
        horas=_round2(horas * 100) / 100,
        mano_obra=mano_obra, mano_obra_auto=mano_obra_auto,
        costo_directo=costo_directo, merma=merma, margen=margen,
        urgencia_mult=urg, subtotal=subtotal, precio=precio, iva=iva, precio_iva=precio_iva,
        # Modo 3D
        gramos=gramos, gramos_auto=gramos_auto,
        horas_imp=horas_imp, horas_imp_auto=horas_imp_auto,
        anclajes=anclajes_n, puentes=puentes_n, tira_led_mm=tira_led_mm,
        canal_ancho_mm=canal_ancho_mm, canal_alto_mm=canal_alto_mm, canal_pared_mm=canal_pared_mm,
        importe_filamento=importe_filamento, importe_impresion=importe_impresion,
        importe_anclajes=importe_anclajes, importe_puentes=importe_puentes,
        # Compat con _apply_instalacion (precio_final = precio_venta_sugerido + inst_total)
        precio_venta_sugerido=precio_iva,
        precio_final=precio_iva,
    )


def merge_neon_params(raw: dict | None) -> dict:
    """Fusión profunda de params para uso con storage (mantiene defaults de fab3d
    si el usuario tenía un objeto viejo guardado). Equivalente al JS `mergeNeonParams`."""
    clean = dict(NEON_PARAMS_DEFAULTS)
    if raw:
        for k in NEON_PARAMS_DEFAULTS:
            if k in raw and raw[k] is not None:
                clean[k] = raw[k]
    clean["fab3d"] = {
        **NEON_PARAMS_DEFAULTS["fab3d"],
        **((raw or {}).get("fab3d") or {}),
    }
    return clean


# ─── DEFAULTS DEL CATÁLOGO ───────────────────────────────────────────────────
# Fuente: SGI (Puebla, México). Precios en MXN. Editables desde /api/catalog.

NEON_PERFILES_DEFAULTS: list[dict] = [
    {"id": "mini-blanco",  "nombre": "Neón Mini 6mm",       "color": "Blanco cálido",         "precio_m": 180, "watts_m":  8, "altura_min_cm":  5, "activo": True},
    {"id": "mini-azul",    "nombre": "Neón Mini 6mm",       "color": "Azul",                  "precio_m": 200, "watts_m":  8, "altura_min_cm":  5, "activo": True},
    {"id": "mini-rojo",    "nombre": "Neón Mini 6mm",       "color": "Rojo",                  "precio_m": 200, "watts_m":  8, "altura_min_cm":  5, "activo": True},
    {"id": "mini-verde",   "nombre": "Neón Mini 6mm",       "color": "Verde",                 "precio_m": 200, "watts_m":  8, "altura_min_cm":  5, "activo": True},
    {"id": "std-blanco",   "nombre": "Neón Estándar 12mm",  "color": "Blanco cálido",         "precio_m": 240, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-blancof",  "nombre": "Neón Estándar 12mm",  "color": "Blanco frío",           "precio_m": 240, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-azul",     "nombre": "Neón Estándar 12mm",  "color": "Azul",                  "precio_m": 260, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-rojo",     "nombre": "Neón Estándar 12mm",  "color": "Rojo",                  "precio_m": 260, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-rosa",     "nombre": "Neón Estándar 12mm",  "color": "Rosa",                  "precio_m": 280, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-morado",   "nombre": "Neón Estándar 12mm",  "color": "Morado",                "precio_m": 280, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-amarillo", "nombre": "Neón Estándar 12mm",  "color": "Amarillo",              "precio_m": 260, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-verde",    "nombre": "Neón Estándar 12mm",  "color": "Verde",                 "precio_m": 260, "watts_m": 12, "altura_min_cm": 10, "activo": True},
    {"id": "std-rgb",      "nombre": "Neón Estándar 12mm",  "color": "RGB",                   "precio_m": 420, "watts_m": 14, "altura_min_cm": 10, "activo": True},
    {"id": "prem-blanco",  "nombre": "Neón Premium 16mm",   "color": "Blanco cálido",         "precio_m": 340, "watts_m": 16, "altura_min_cm": 15, "activo": True},
    {"id": "prem-rgb",     "nombre": "Neón Premium 16mm",   "color": "RGB direccionable",     "precio_m": 580, "watts_m": 18, "altura_min_cm": 15, "activo": True},
]


NEON_PARAMS_DEFAULTS: dict = {
    # Insumos por metro lineal
    "cable_m":         2.5,     # MXN/m de cable (Radox 080-4 Cal.22, rollo 100 m ≈ $250)
    "acces_m":         35,      # MXN/m de accesorios (grapas, tornillos, conectores)
    "consumibles_pct": 0.08,    # 8% sobre materiales: cianoacrilato + soldadura + varios

    # Fuentes de poder
    "fuente_factor":   0.80,    # factor de seguridad (usar solo 80% de la capacidad nominal)

    # Mano de obra
    "m_por_min":       0.6,     # metros de neón instalados por minuto
    "tarifa_hora":     180,     # MXN/h del técnico

    # Comercial
    "merma":           0.05,    # 5% sobre insumos
    "margen":          0.35,    # 35% sobre costo directo
    "desperdicio_umbral_cm": 30, # tiras sobrantes ≤ 30 cm se cobran (no reutilizables)

    # Catálogo de fuentes / adaptadores / pilas
    "fuentes": [
        {"id": "f60",  "nombre": "Fuente 60W",                "watts":  60, "precio": 280, "tipo": "fuente",    "activo": True},
        {"id": "f100", "nombre": "Fuente 100W estándar",      "watts": 100, "precio": 380, "tipo": "fuente",    "activo": True},
        {"id": "f150", "nombre": "Fuente 150W",               "watts": 150, "precio": 520, "tipo": "fuente",    "activo": True},
        {"id": "f200", "nombre": "Fuente 200W",               "watts": 200, "precio": 680, "tipo": "fuente",    "activo": True},
        {"id": "f300", "nombre": "Fuente 300W",               "watts": 300, "precio": 980, "tipo": "fuente",    "activo": True},
        {"id": "ad12", "nombre": "Adaptador 12V 5A (60W)",    "watts":  60, "precio": 150, "tipo": "adaptador", "activo": True},
        {"id": "ad24", "nombre": "Adaptador 24V 3A (72W)",    "watts":  72, "precio": 220, "tipo": "adaptador", "activo": True},
        {"id": "p9v",  "nombre": "Pila 9V (portátil)",        "watts":   9, "precio":  80, "tipo": "pila",      "activo": True},
        {"id": "plit", "nombre": "Batería Li-ion recargable", "watts":  40, "precio": 450, "tipo": "pila",      "activo": True},
    ],

    # Consumibles (inventario + precios de referencia)
    "consumibles": [
        {"id": "ca-loctite", "nombre": "Cianoacrilato Loctite 401", "precio": 120, "unidad": "pza",   "activo": True},
        {"id": "ca-3m",      "nombre": "Cianoacrilato 3M",           "precio":  95, "unidad": "pza",   "activo": True},
        {"id": "ca-kola",    "nombre": "Kola Loka (genérico)",       "precio":  35, "unidad": "pza",   "activo": True},
        {"id": "sold-est",   "nombre": "Soldadura estaño 60/40 1mm", "precio": 180, "unidad": "rollo", "activo": True},
        {"id": "flux",       "nombre": "Flux para soldadura",        "precio":  80, "unidad": "pza",   "activo": True},
        {"id": "termo",      "nombre": "Termofit 3mm surtido",       "precio": 120, "unidad": "juego", "activo": True},
    ],

    # Materiales de base (modo lámina)
    #   tipo_precio="lamina" → precio por lámina completa, se prorratea al área usada
    #   tipo_precio="pieza"  → precio por m² directo (comprado ya cortado)
    "bases": [
        {"id": "acr-3-tr",    "nombre": "Acrílico transparente 3mm", "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 2450, "activo": True},
        {"id": "acr-6-tr",    "nombre": "Acrílico transparente 6mm", "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 4030, "activo": True},
        {"id": "acr-3-neg",   "nombre": "Acrílico negro 3mm",        "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 2590, "activo": True},
        {"id": "acr-6-neg",   "nombre": "Acrílico negro 6mm",        "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 4180, "activo": True},
        {"id": "mdf-6-crudo", "nombre": "MDF 6mm crudo",             "tipo_precio": "pieza",  "precio_m2": 280,  "activo": True},
        {"id": "mdf-6-pint",  "nombre": "MDF 6mm pintado",           "tipo_precio": "pieza",  "precio_m2": 520,  "activo": True},
        {"id": "mdf-9-pint",  "nombre": "MDF 9mm pintado",           "tipo_precio": "pieza",  "precio_m2": 680,  "activo": True},
        {"id": "pvc-3",       "nombre": "PVC espumado 3mm",          "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 1090, "activo": True},
        {"id": "pvc-6",       "nombre": "PVC espumado 6mm",          "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 1790, "activo": True},
        {"id": "trov-3",      "nombre": "Trovicel 3mm",              "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina":  980, "activo": True},
        {"id": "aluco-3",     "nombre": "Alucobond 3mm",             "tipo_precio": "lamina", "lamina_w": 120, "lamina_h": 240, "precio_lamina": 3600, "activo": True},
        {"id": "sin-base",    "nombre": "Sin base (solo neón)",      "tipo_precio": "pieza",  "precio_m2": 0,    "activo": True},
    ],

    # Formas de la base
    #   factor_area = fracción del rectángulo aprovechada (silueta calada aprovecha menos)
    #   corte_m     = MXN/m de corte extra en contorno (láser/CNC)
    "formas": [
        {"id": "rect",       "nombre": "Rectangular",             "factor_area": 1.00, "corte_m":  0},
        {"id": "silueta",    "nombre": "Silueta / calada",        "factor_area": 0.85, "corte_m": 35},
        {"id": "redondeada", "nombre": "Rectangular c/ esquinas", "factor_area": 0.98, "corte_m": 12},
    ],

    "soporte_precio": 180,   # MXN — kit separadores/soportes por anuncio

    "urgencias": [
        {"id": "normal",  "nombre": "Normal",  "dias": "7–10 días", "mult": 1.00},
        {"id": "rapido",  "nombre": "Rápido",  "dias": "4–5 días",  "mult": 1.20},
        {"id": "express", "nombre": "Express", "dias": "48–72 hrs", "mult": 1.45},
    ],

    # ── Modo Impresión 3D (canal PETG tipo Signflex3D / Neonflex) ────────────
    # Alternativa a la lámina cortada: el canal del neón se imprime en 3D
    # siguiendo el trazo. Reemplaza las partidas de base/desperdicio/corte
    # por: filamento (gramos), horas de impresora, anclajes y puentes.
    "fab3d": {
        "filamento_mxn_g":  0.60,     # MXN/g de filamento (PETG rollo 1kg ≈ $600)
        "filamento_dens_g": 1.24,     # g/cm³ del PETG (para auto-peso)
        "peso_gr_m":        55,       # g/m fallback (cuando no se define sección)
        "horas_m_por_hora": 4.5,      # metros de canal impresos por hora
        "horas_mxn_hora":   25,       # MXN/h de impresora (energía + amortización)
        "anclo_precio":     8,        # MXN por anclaje (tornillo + taco)
        "puente_precio":    12,       # MXN por puente (crossover entre trazos)
        "tiras_led": [
            {"id": "led4",  "mm":  4},
            {"id": "led6",  "mm":  6},
            {"id": "led8",  "mm":  8},
            {"id": "led12", "mm": 12},
            {"id": "led16", "mm": 16},
        ],
        "canal_default": {"ancho_mm": 16, "alto_mm": 20, "pared_mm": 1.6},
        "signflex3d_url": "https://signflex3d.com/generador.html",
    },
}
