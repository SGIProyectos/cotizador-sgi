import json
from pathlib import Path

_CATALOG_FILE = Path(__file__).parent / "catalog.json"

# Catálogo completo extraído de CATALOGO LETRAS.xlsx

# ─── PEGAMENTOS POR COMBINACIÓN DE MATERIALES ───────────────────────────────
PEGAMENTOS = {
    # metros_por_envase: cuántos metros lineales de cordón cubre un envase
    ("aluminio", "aluminio"):  {"nombre": "Soudaflex 40FC",                      "precio_aprox": 180, "metros_por_envase": 3},
    ("aluminio", "acrilico"):  {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 5},
    ("acrilico", "acrilico"):  {"nombre": "Cloruro de Metileno",                 "precio_aprox":  60, "metros_por_envase": 8},
    ("acrilico", "alucobon"):  {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 5},
    ("alucobon", "alucobon"):  {"nombre": "Soudaflex 40FC",                      "precio_aprox": 180, "metros_por_envase": 3},
    ("aluminio", "pvc"):       {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 5},
    ("acrilico", "pvc"):       {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 5},
}

# ─── LÁMINAS DE MATERIAL (precio por lámina 122×244 cm) ─────────────────────
LAMINAS = {
    "acrilico_3mm": {
        "nombre": "Acrílico 3mm",
        "precio": 1200,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["cara_letra_pequena", "cara_letra_mediana", "cara_caja"],
    },
    "acrilico_6mm": {
        "nombre": "Acrílico 6mm",
        "precio": 1450,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 6,
        "uso": ["cara_letra_grande", "cara_caja_premium"],
    },
    "pvc_3mm": {
        "nombre": "PVC Espumado 3mm",
        "precio": 380,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["fondo_letra_interior", "señaletica"],
    },
    "pvc_6mm": {
        "nombre": "PVC Espumado 6mm",
        "precio": 520,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 6,
        "uso": ["fondo_letra_exterior", "fondo_caja"],
    },
    "aluminio_cal22": {
        "nombre": "Aluminio Calibre 22 (0.76mm)",
        "precio": 650,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 0.76,
        "uso": ["cercha_letra_pequena"],
    },
    "aluminio_cal20": {
        "nombre": "Aluminio Calibre 20 (0.9mm)",
        "precio": 780,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 0.9,
        "uso": ["cercha_letra_mediana"],
    },
    "aluminio_cal18": {
        "nombre": "Aluminio Calibre 18 (1.0mm)",
        "precio": 950,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 1.0,
        "uso": ["cercha_letra_grande", "estructura_caja"],
    },
    "alucobon_3mm": {
        "nombre": "Alucobon / Dibond 3mm",
        "precio": 1800,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["fondo_premium", "cara_caja_exterior"],
    },
    # ── Acrílico por acabado / color ──────────────────────────────────────────
    "acrilico_3mm_blanco": {
        "nombre": "Acrílico Blanco 3mm",
        "precio": 1200,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["cara_letra_pequena", "cara_letra_mediana", "cara_caja"],
    },
    "acrilico_3mm_colores": {
        "nombre": "Acrílico Color 3mm",
        "precio": 1100,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Rojo", "Amarillo", "Azul", "Azul Rey", "Verde", "Verde Pemex", "Negro", "Naranja"],
        "uso": ["cara_letra_pequena", "cara_letra_mediana", "cara_caja"],
    },
    "acrilico_3mm_translucido": {
        "nombre": "Acrílico Translúcido 3mm",
        "precio": 1250,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Verde", "Azul", "Rojo"],
        "uso": ["cara_letra_pequena", "cara_caja"],
    },
    "acrilico_3mm_espejo": {
        "nombre": "Acrílico Espejo 3mm",
        "precio": 1500,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Plata", "Dorado", "Rosa"],
        "uso": ["cara_letra", "decoracion"],
    },
    "acrilico_5mm": {
        "nombre": "Acrílico 5mm",
        "precio": 1740,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 5,
        "uso": ["cara_letra_grande"],
    },
    "acrilico_9mm": {
        "nombre": "Acrílico 9mm",
        "precio": 3016,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 9,
        "uso": ["cara_letra_premium"],
    },
    # ── Alucom (panel compuesto aluminio-polietileno) ─────────────────────────
    "alucom_base": {
        "nombre": "Alucom Color Base",
        "precio": 754,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Blanco", "Negro", "Rojo", "Azul Telecom", "Gris", "Verde Pemex", "Amarillo"],
        "uso": ["cara_letra", "fondo_premium", "cara_caja_exterior"],
    },
    "alucom_especial": {
        "nombre": "Alucom Acabado Especial",
        "precio": 1009,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Madera Cerezo", "Plata Satinado", "Plata Cepillado", "Dorado Cepillado"],
        "uso": ["cara_letra", "decoracion"],
    },
    "alucom_espejo": {
        "nombre": "Alucom Espejo",
        "precio": 1009,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "colores": ["Plata Espejo", "Dorado Espejo"],
        "uso": ["cara_letra", "decoracion"],
    },
}

# ─── MÓDULOS LED PARA LETRAS DE CANAL ────────────────────────────────────────
# profundidad = altura de cercha en cm
LEDS_CANAL = [
    {
        "id": "micro_sign",
        "nombre": "Módulo LED Micro Sign",
        "precio_tira_20": 396.72,
        "precio_modulo": 9.92,
        "watts_modulo": 0.24,
        "lumenes": 25,
        "ip": "IP65",
        "profundidad_min": 2, "profundidad_max": 6,
        "tamano": "pequena",
        "voltaje": 12,
        "conectividad_serie": 40,
    },
    {
        "id": "mini_sign",
        "nombre": "Módulo LED Mini Sign",
        "precio_tira_20": 231.07,
        "precio_modulo": 11.55,
        "watts_modulo": 0.32,
        "lumenes": 20,
        "ip": "IP65",
        "profundidad_min": 2, "profundidad_max": 6,
        "tamano": "pequena",
        "voltaje": 12,
        "conectividad_serie": 20,
    },
    {
        "id": "sign_03_rgb",
        "nombre": "Módulo LED Sign 03 RGB",
        "precio_tira_20": 423.17,
        "precio_modulo": 21.16,
        "watts_modulo": 0.65,
        "lumenes": 20,
        "ip": "IP65",
        "profundidad_min": 3, "profundidad_max": 8,
        "tamano": "pequena",
        "voltaje": 12,
        "conectividad_serie": 20,
        "color": "RGB",
    },
    {
        "id": "signaflex_zigzag",
        "nombre": "Tira LED Signaflex ZIG-ZAG",
        "precio_tira_5m": 445.96,
        "precio_modulo": 4.46,       # $445.96 / 100 segmentos de 5 cm
        "watts_modulo": 0.5,          # 10 W/m × 0.05 m/segmento
        "lumenes": 0,
        "ip": "IP20",
        "profundidad_min": 3, "profundidad_max": 8,
        "tamano": "pequena",
        "voltaje": 24,
        "conectividad_serie": 100,
        "nota": "Solo interior. Tira 5 m / 500 cm. Corte cada 5 cm. Módulo = 5 cm.",
    },
    {
        "id": "sign_03",
        "nombre": "Módulo LED Sign 03",
        "precio_tira_20": 198.36,
        "precio_modulo": 9.92,
        "watts_modulo": 0.72,
        "lumenes": 75,
        "ip": "IP65",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "mediana",
        "voltaje": 12,
        "conectividad_serie": 20,
    },
    {
        "id": "sign_02_high",
        "nombre": "Módulo LED Sign 02 HIGH",
        "precio_tira_20": 290.93,
        "precio_modulo": 14.55,
        "watts_modulo": 0.72,
        "lumenes": 110,
        "ip": "IP67",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "mediana",
        "voltaje": 12,
        "conectividad_serie": 20,
    },
    {
        "id": "sign_03_green",
        "nombre": "Módulo LED 12v Sign 03 Verde",
        "precio_tira_20": 214.60,
        "precio_modulo": 10.73,
        "watts_modulo": 0.72,
        "lumenes": 35,
        "ip": "IP65",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "mediana",
        "voltaje": 12,
        "conectividad_serie": 20,
        "color": "Verde",
    },
    {
        "id": "sign_03_red",
        "nombre": "Módulo LED 12v Sign 03 Rojo",
        "precio_tira_20": 214.60,
        "precio_modulo": 10.73,
        "watts_modulo": 0.72,
        "lumenes": 15,
        "ip": "IP65",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "mediana",
        "voltaje": 12,
        "conectividad_serie": 20,
        "color": "Rojo",
    },
    {
        "id": "sign_03_blue",
        "nombre": "Módulo LED 12v Sign 03 Azul",
        "precio_tira_20": 214.60,
        "precio_modulo": 10.73,
        "watts_modulo": 0.72,
        "lumenes": 10,
        "ip": "IP65",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "mediana",
        "voltaje": 12,
        "conectividad_serie": 20,
        "color": "Azul",
    },
    {
        "id": "sign_03_high",
        "nombre": "Módulo LED Sign 03 HIGH",
        "precio_tira_20": 370.04,
        "precio_modulo": 18.51,
        "watts_modulo": 1.08,
        "lumenes": 165,
        "ip": "IP66",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "grande",
        "voltaje": 12,
        "conectividad_serie": 20,
    },
    {
        "id": "sign_03_pro",
        "nombre": "Módulo LED Sign 03 PRO",
        "precio_tira_20": 214.60,
        "precio_modulo": 10.73,
        "watts_modulo": 1.32,
        "lumenes": 128,
        "ip": "IP65",
        "profundidad_min": 8, "profundidad_max": 15,
        "tamano": "grande",
        "voltaje": 12,
        "conectividad_serie": 20,
    },
    {
        "id": "sign_03_ac",
        "nombre": "Módulo LED 110v Sign 03 AC",
        "precio_tira_20": 713.40,
        "precio_modulo": 35.67,
        "watts_modulo": 2.0,
        "lumenes": 150,
        "ip": "IP65",
        "profundidad_min": 6, "profundidad_max": 15,
        "tamano": "grande",
        "voltaje": 110,
        "conectividad_serie": 50,
    },
]

# ─── LEDS PARA CAJAS DE LUZ ─────────────────────────────────────────────────
LEDS_CAJA = {
    "interior": [
        {
            "id": "backlite_rgb",
            "nombre": "Barra LED Backlite RGB",
            "tipo_led": "backlite",
            "precio": 93.52,
            "watts": 6,
            "lumenes": None,
            "ip": "IP20",
            "profundidad_min": 6, "profundidad_max": 18,
            "vistas": 1,
        },
        {
            "id": "backlite",
            "nombre": "Barra LED Backlite",
            "tipo_led": "backlite",
            "precio_serie_10": 551.00,
            "precio": 55.10,
            "watts": 5,
            "lumenes": 600,
            "ip": "IP33",
            "profundidad_min": 6, "profundidad_max": 20,
            "vistas": 1,
        },
        {
            "id": "signaflex_cct",
            "nombre": "Tira LED Signaflex CCT",
            "tipo_led": "backlite",
            "precio_tira_5m": 662.36,
            "precio": 662.36,
            "watts": 50,
            "lumenes": 5000,
            "ip": "IP20",
            "profundidad_min": 6, "profundidad_max": 20,
            "vistas": 1,
            "voltaje": 24,
            "nota": "Solo interior. Tira 5 m. CCT 2700-13000 K ajustable.",
        },
        {
            "id": "edgelite_42",
            "nombre": "Barra LED Edgelite Osram 42",
            "tipo_led": "edgelite",
            "max_cara_cm": 120,
            "precio": 375.93,
            "watts": 15,
            "lumenes": 1650,
            "ip": "IP33",
            "profundidad_min": 10, "profundidad_max": 40,
            "vistas": 1,
        },
        {
            "id": "edgelite_21",
            "nombre": "Barra LED Edgelite Osram 21",
            "tipo_led": "edgelite",
            "max_cara_cm": 90,
            "precio": 250.62,
            "watts": 7.5,
            "lumenes": 750,
            "ip": "IP33",
            "profundidad_min": 10, "profundidad_max": 40,
            "vistas": 1,
        },
    ],
    "exterior": [
        {
            "id": "eco_edgelite_56",
            "nombre": "Barra LED Eco Edgelite 56",
            "tipo_led": "edgelite",
            "max_cara_cm": 120,
            "precio": 399.90,
            "watts": 14,
            "lumenes": 1260,
            "ip": "IP65",
            "profundidad_min": 12, "profundidad_max": 40,
            "vistas": 2,
        },
        {
            "id": "eco_edgelite_24",
            "nombre": "Barra LED Eco Edgelite 24",
            "tipo_led": "edgelite",
            "max_cara_cm": 80,
            "precio": 196.25,
            "watts": 6,
            "lumenes": 540,
            "ip": "IP65",
            "profundidad_min": 12, "profundidad_max": 20,
            "vistas": 1,
        },
        {
            "id": "sign_edge_01",
            "nombre": "Módulo LED Sign Edge 01",
            "tipo_led": "edgelite",
            "max_cara_cm": 60,
            "precio": 330.60,
            "precio_modulo": 16.53,
            "watts": 1.32,
            "lumenes": 125,
            "ip": "IP67",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
        },
    ],
}

# ─── NEÓN SEGUNDA GENERACIÓN ─────────────────────────────────────────────────
NEON_FLEX = {
    "12mm": {
        "nombre": "Neón Duo 2ª Gen 12mm",
        "precio_rollo_10m": 694.24,
        "precio_metro": 69.42,
        "watts_metro": 8,
        "ip": "IP64",
        "colores": ["Azul","Blanco cálido","Azul hielo","Verde claro",
                    "Blanco frío","Naranja","Morado"],
        "corte_cada_cm": 3,
    },
    "6mm": {
        "nombre": "Neón Duo 2ª Gen 6mm",
        "precio_rollo_10m": 449.57,
        "precio_metro": 44.96,
        "watts_metro": 8,
        "ip": "IP64",
        "colores": ["Verde fuerte","Blanco cálido","Blanco frío","Amarillo",
                    "Naranja","Verde claro","Azul hielo","Azul","Morado",
                    "Rosa claro","Rosa fuerte","Rojo"],
        "corte_cada_cm": 3,
    },
}

# ─── FUENTES DE PODER ────────────────────────────────────────────────────────
FUENTES = [
    {"nombre": "Fuente Exterior 60W",   "watts": 60,  "precio": 273.10,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 100W",  "watts": 100, "precio": 438.82,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 150W",  "watts": 150, "precio": 507.08,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente UL 60W",         "watts": 60,  "precio": 722.52,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente UL 100W",        "watts": 100, "precio": 828.58,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente UL 150W",        "watts": 150, "precio": 921.38,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente SLIM Interior 60W",  "watts": 60,  "precio": 689.38,  "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
    {"nombre": "Fuente SLIM Interior 100W", "watts": 100, "precio": 775.54,  "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
    {"nombre": "Fuente SLIM Interior 200W", "watts": 200, "precio": 1073.82, "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
]

# ─── LÓGICA DE PRECIOS BASE (hoja COTIZANDO) ─────────────────────────────────
# Formula: altura_cm × precio_cm × multiplicador
# Dict mutable: los cambios vía catálogo son visibles en tiempo real en calculator.py
PRECIOS_BASE = {
    "precio_cm": 10.0,
    "multiplicadores": {
        "aluminio_sin_luz":            2.0,
        "aluminio_con_luz":            2.5,
        "aluminio_acrilico_con_luz":   3.5,
        "acrilico_con_luz_std":        4.5,
        "acrilico_con_luz_premium":    5.5,
    },
}

PRECIOS_CAJA_M2 = {
    "lona":             1800,
    "vinil_corte":      1200,
    "acrilico":         2800,
    "acrilico_2vistas": 3500,
}

# ─── VINILOS ADHESIVOS ────────────────────────────────────────────────────────
# precio_ml: precio por metro lineal de rollo (ancho estándar 1.22 m)
# precio_m2 = precio_ml / ancho_rollo_m
VINILOS = [
    {
        "id": "vinil_std",
        "nombre": "Vinil Estándar",
        "precio_ml": 58.0,
        "ancho_rollo_m": 1.22,
        "acabado": "opaco",
        "colores": ["Brimstone Yellow", "Yellow", "Golden Yellow", "Orange", "Crimson",
                    "Red", "Cherry Red", "Pink", "Light Blue", "Middle Blue", "King Blue",
                    "Middle Green", "Lilac", "Dark Green", "Middle Grey", "Lightgrey",
                    "Light Brown", "Coffee Brown", "Azure Blue", "Dark Blue",
                    "Silver Metallic", "Gold Metallic", "Pale Pink"],
    },
    {
        "id": "vinil_std_plus",
        "nombre": "Vinil Estándar Plus",
        "precio_ml": 87.0,
        "ancho_rollo_m": 1.22,
        "acabado": "opaco",
        "colores": ["Ivory", "Grey Blue"],
    },
    {
        "id": "vinil_premium",
        "nombre": "Vinil Premium",
        "precio_ml": 120.0,
        "ancho_rollo_m": 1.22,
        "acabado": "opaco",
        "colores": ["Zinc Yellow", "Yellow Orange", "Dark Red", "Heather Red", "Violet",
                    "Intensive Blue", "Grass Green", "Gentian Blue", "Black", "White"],
    },
    {
        "id": "vinil_premium_alto",
        "nombre": "Vinil Premium Especial",
        "precio_ml": 180.0,
        "ancho_rollo_m": 1.22,
        "acabado": "metalico",
        "colores": ["Light Red", "Emerald", "Coral Red", "Gold"],
    },
]

# ─── DISTANCIADORES (letras retroiluminadas) ─────────────────────────────────
DISTANCIADORES = {
    "nombre": "Distanciadores acero inox (juego / letra)",
    "precio": 45.0,
}

# ─── TIPOS DE CONSTRUCCIÓN ───────────────────────────────────────────────────
TIPOS_CONSTRUCCION = {
    "cajon_luz": {
        "nombre": "Cajón con luz",
        "descripcion": "Cara acrílico · cercha aluminio · fondo PVC · LEDs adelante",
        "cara": "acrilico",
        "fondo_pvc": True,
        "leds": True,
        "fuente": True,
        "distanciadores": False,
        "multiplicador_default": "acrilico_con_luz_std",
        "altura_min_rec": 8.0,
    },
    "retro_halo": {
        "nombre": "Retroiluminada / Halo",
        "descripcion": "Cara aluminio opaco · cercha aluminio · sin fondo PVC · LEDs atrás · distanciadores",
        "cara": "aluminio",
        "fondo_pvc": False,
        "leds": True,
        "fuente": True,
        "distanciadores": True,
        "multiplicador_default": "aluminio_con_luz",
        "altura_min_rec": 0.0,
    },
    "sin_luz": {
        "nombre": "Sin luz (cajón)",
        "descripcion": "Cara aluminio · cercha aluminio · fondo PVC · sin iluminación",
        "cara": "aluminio",
        "fondo_pvc": True,
        "leds": False,
        "fuente": False,
        "distanciadores": False,
        "multiplicador_default": "aluminio_sin_luz",
        "altura_min_rec": 0.0,
    },
    "abierta_luz": {
        "nombre": "Abierta con luz",
        "descripcion": "Sin cara frontal · cercha aluminio visible · fondo PVC · LEDs expuestos",
        "cara": "ninguna",
        "fondo_pvc": True,
        "leds": True,
        "fuente": True,
        "distanciadores": False,
        "multiplicador_default": "aluminio_con_luz",
        "altura_min_rec": 30.0,
    },
}


def recomendar_tipo_construccion(altura_cm: float) -> str:
    """Recomienda tipo de construcción según altura de letra."""
    if altura_cm <= 0 or altura_cm >= 8:
        return "cajon_luz"
    return "retro_halo"


# ─── EQUIPOS DE ACCESO PARA INSTALACIÓN ─────────────────────────────────────
GRUAS = [
    {"id": "ninguna",      "nombre": "Sin equipo / acceso propio",           "precio_dia": 0},
    {"id": "andamio",      "nombre": "Andamio metálico",                     "precio_dia": 800},
    {"id": "elevador",     "nombre": "Elevador / Brazo hidráulico",          "precio_dia": 1800},
    {"id": "grua_pequena", "nombre": "Grúa telescópica pequeña (hasta 15m)", "precio_dia": 2500},
    {"id": "grua_mediana", "nombre": "Grúa telescópica mediana (15–30m)",    "precio_dia": 4500},
    {"id": "grua_grande",  "nombre": "Grúa articulada grande (>30m)",        "precio_dia": 8000},
]


# ─── LED RECOMENDADO PARA CAJA DE LUZ ────────────────────────────────────────
def recomendar_led_caja(
    ancho_cm: float,
    alto_cm: float,
    doble_vista: bool = False,
    uso: str = "exterior",
    profundidad_cm: float = 15,
) -> list:
    """
    Devuelve lista de LEDs recomendados para caja de luz, ordenados por idoneidad.
    Prioriza edgelite cuando el lado corto de la cara cabe dentro de max_cara_cm.
    Para doble vista fuerza LEDs con vistas >= 2.
    """
    pool = LEDS_CAJA.get(uso, LEDS_CAJA["exterior"])

    if doble_vista:
        candidatos = [l for l in pool if l.get("vistas", 1) >= 2]
        return candidatos or pool

    lado_corto = min(ancho_cm, alto_cm) if ancho_cm > 0 and alto_cm > 0 else 9999

    # Filtrar por profundidad compatible
    compatibles = [
        l for l in pool
        if l.get("profundidad_min", 0) <= profundidad_cm <= l.get("profundidad_max", 999)
    ]

    edgelite = sorted(
        [l for l in compatibles if l.get("tipo_led") == "edgelite" and lado_corto <= l.get("max_cara_cm", 0)],
        key=lambda x: x.get("lumenes") or 0,
        reverse=True,
    )
    backlite = [l for l in compatibles if l.get("tipo_led") != "edgelite"]

    # Edgelite primero cuando aplica; backlite como complemento o fallback
    return edgelite + backlite if edgelite else backlite or compatibles


# ─── CERCHA RECOMENDADA SEGÚN ALTURA DE LETRA ────────────────────────────────
def cercha_recomendada_cm(altura_letra_cm: float) -> float:
    if altura_letra_cm <= 10:
        return 3.0
    elif altura_letra_cm <= 20:
        return 5.0
    elif altura_letra_cm <= 35:
        return 8.0
    elif altura_letra_cm <= 60:
        return 12.0
    else:
        return 15.0

# ─── LED RECOMENDADO SEGÚN PROFUNDIDAD DE CERCHA ─────────────────────────────
def led_recomendado(profundidad_cm: float, uso: str = "exterior") -> dict:
    candidatos = [l for l in LEDS_CANAL
                  if l["profundidad_min"] <= profundidad_cm <= l["profundidad_max"]]
    if not candidatos:
        candidatos = LEDS_CANAL
    # Preferir exterior IP65+, mayor lúmenes
    if uso == "exterior":
        candidatos = [l for l in candidatos if int(l["ip"].replace("IP","")) >= 65] or candidatos
    return sorted(candidatos, key=lambda x: x["lumenes"], reverse=True)[0]

# ─── MATERIAL DE CERCHA SEGÚN ALTURA ─────────────────────────────────────────
def material_cercha(altura_letra_cm: float) -> str:
    if altura_letra_cm <= 15:
        return "aluminio_cal22"
    elif altura_letra_cm <= 30:
        return "aluminio_cal20"
    else:
        return "aluminio_cal18"

# ─── MATERIAL DE CARA SEGÚN ALTURA ───────────────────────────────────────────
def material_cara(altura_letra_cm: float) -> str:
    if altura_letra_cm <= 25:
        return "acrilico_3mm"
    else:
        return "acrilico_6mm"

# ─── FUENTE DE PODER ÓPTIMA ───────────────────────────────────────────────────
def fuente_optima(watts_total: float, uso: str = "exterior") -> dict:
    watts_con_margen = watts_total * 1.25  # 25% de margen de seguridad
    candidatas = [f for f in FUENTES if f["watts"] >= watts_con_margen]
    if uso == "interior":
        candidatas = [f for f in candidatas if f["uso"] in ("interior", "ambos")] or candidatas
    elif uso == "exterior":
        candidatas = [f for f in candidatas if f["uso"] in ("exterior", "ambos")] or candidatas
    if not candidatas:
        candidatas = FUENTES
    return min(candidatas, key=lambda f: f["precio"])


# ─── PERSISTENCIA DEL CATÁLOGO ───────────────────────────────────────────────

def catalog_to_dict() -> dict:
    return {
        "laminas": LAMINAS,
        "leds_canal": LEDS_CANAL,
        "leds_caja": {"interior": LEDS_CAJA["interior"], "exterior": LEDS_CAJA["exterior"]},
        "fuentes": FUENTES,
        "pegamentos": {f"{k[0]}|{k[1]}": v for k, v in PEGAMENTOS.items()},
        "precios_base": {
            "precio_cm": PRECIOS_BASE["precio_cm"],
            "multiplicadores": dict(PRECIOS_BASE["multiplicadores"]),
        },
        "precios_caja_m2": dict(PRECIOS_CAJA_M2),
        "vinilos": VINILOS,
        "tipos_construccion": TIPOS_CONSTRUCCION,
        "gruas": GRUAS,
    }


def catalog_save():
    """Persiste el catálogo en memoria a catalog.json."""
    _CATALOG_FILE.write_text(
        json.dumps(catalog_to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def catalog_apply(raw: dict):
    """Actualiza los globals del catálogo en lugar (in-place) con los datos de raw."""
    if "laminas" in raw:
        LAMINAS.clear()
        LAMINAS.update(raw["laminas"])
    if "leds_canal" in raw:
        LEDS_CANAL.clear()
        LEDS_CANAL.extend(raw["leds_canal"])
    if "leds_caja" in raw:
        for side in ("interior", "exterior"):
            if side in raw["leds_caja"]:
                LEDS_CAJA[side] = raw["leds_caja"][side]
    if "fuentes" in raw:
        FUENTES.clear()
        FUENTES.extend(raw["fuentes"])
    if "pegamentos" in raw:
        PEGAMENTOS.clear()
        for k_str, v in raw["pegamentos"].items():
            parts = [p.strip() for p in k_str.split("|")]
            if len(parts) == 2:
                PEGAMENTOS[tuple(parts)] = v
    if "precios_base" in raw:
        pb = raw["precios_base"]
        if "precio_cm" in pb:
            PRECIOS_BASE["precio_cm"] = float(pb["precio_cm"])
        if "multiplicadores" in pb:
            PRECIOS_BASE["multiplicadores"].clear()
            PRECIOS_BASE["multiplicadores"].update(pb["multiplicadores"])
    if "precios_caja_m2" in raw:
        PRECIOS_CAJA_M2.clear()
        PRECIOS_CAJA_M2.update({k: float(v) for k, v in raw["precios_caja_m2"].items()})
    if "vinilos" in raw:
        VINILOS.clear()
        VINILOS.extend(raw["vinilos"])


def _catalog_merge(raw: dict):
    """Fusiona raw con los globals sin borrar defaults de código."""
    if "laminas" in raw:
        LAMINAS.update(raw["laminas"])
    if "leds_canal" in raw:
        raw_by_id = {l["id"]: l for l in raw["leds_canal"] if "id" in l}
        for led in LEDS_CANAL:
            if led.get("id") in raw_by_id:
                led.update(raw_by_id[led["id"]])
        existing_ids = {l.get("id") for l in LEDS_CANAL}
        for led in raw["leds_canal"]:
            if led.get("id") not in existing_ids:
                LEDS_CANAL.append(led)
    if "leds_caja" in raw:
        for side in ("interior", "exterior"):
            if side in raw["leds_caja"]:
                raw_side = raw["leds_caja"][side]
                raw_by_id = {l.get("id"): l for l in raw_side if l.get("id")}
                for led in LEDS_CAJA[side]:
                    if led.get("id") in raw_by_id:
                        led.update(raw_by_id[led["id"]])
                existing_ids = {l.get("id") for l in LEDS_CAJA[side]}
                for led in raw_side:
                    if led.get("id") not in existing_ids:
                        LEDS_CAJA[side].append(led)
    if "fuentes" in raw:
        raw_by_name = {f["nombre"]: f for f in raw["fuentes"] if "nombre" in f}
        for fuente in FUENTES:
            if fuente.get("nombre") in raw_by_name:
                fuente.update(raw_by_name[fuente["nombre"]])
        existing_names = {f.get("nombre") for f in FUENTES}
        for fuente in raw["fuentes"]:
            if fuente.get("nombre") not in existing_names:
                FUENTES.append(fuente)
    if "pegamentos" in raw:
        for k_str, v in raw["pegamentos"].items():
            parts = [p.strip() for p in k_str.split("|")]
            if len(parts) == 2:
                key = tuple(parts)
                if key in PEGAMENTOS:
                    PEGAMENTOS[key].update(v)   # merge: preserva campos del código (metros_por_envase)
                else:
                    PEGAMENTOS[key] = v
    if "precios_base" in raw:
        pb = raw["precios_base"]
        if "precio_cm" in pb:
            PRECIOS_BASE["precio_cm"] = float(pb["precio_cm"])
        if "multiplicadores" in pb:
            PRECIOS_BASE["multiplicadores"].update(pb["multiplicadores"])
    if "precios_caja_m2" in raw:
        PRECIOS_CAJA_M2.update({k: float(v) for k, v in raw["precios_caja_m2"].items()})
    if "vinilos" in raw:
        raw_by_id = {v["id"]: v for v in raw["vinilos"] if "id" in v}
        for vinyl in VINILOS:
            if vinyl.get("id") in raw_by_id:
                vinyl.update(raw_by_id[vinyl["id"]])
        existing_ids = {v.get("id") for v in VINILOS}
        for vinyl in raw["vinilos"]:
            if vinyl.get("id") not in existing_ids:
                VINILOS.append(vinyl)


def catalog_load():
    """Carga catalog.json si existe y fusiona con defaults; si no, usa los defaults."""
    if _CATALOG_FILE.exists():
        try:
            _catalog_merge(json.loads(_CATALOG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


catalog_load()
