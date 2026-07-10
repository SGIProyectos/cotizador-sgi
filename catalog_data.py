import json
import logging
import os
from pathlib import Path

log = logging.getLogger("cotizador.catalog")

# Sigue a COTIZADOR_DATA_DIR (disco persistente en hosting); sin definir,
# catalog.json vive junto al código como siempre.
_CATALOG_FILE = Path(
    os.environ.get("COTIZADOR_DATA_DIR") or Path(__file__).parent
) / "catalog.json"

# Catálogo completo extraído de CATALOGO LETRAS.xlsx

# ─── PEGAMENTOS POR COMBINACIÓN DE MATERIALES ───────────────────────────────
PEGAMENTOS = {
    # metros_por_envase: cuántos metros lineales de cordón de 5 mm cubre un envase.
    # Rendimientos calibrados con datos de campo (cordón estanco, densidad industrial):
    #   Soudaflex 40FC 290–310 ml → 10–12 m (sellado estructural, alta viscosidad)
    #   Silicón Transparente Arquitectónico 280–300 ml → 10–12 m (sellado estético)
    #   Cloruro de Metileno 1 L → 50–70 m (capilaridad, no relleno)
    ("aluminio", "aluminio"):  {"nombre": "Soudaflex 40FC",                      "precio_aprox": 180, "metros_por_envase": 11},
    ("aluminio", "acrilico"):  {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 11},
    ("acrilico", "acrilico"):  {"nombre": "Cloruro de Metileno",                 "precio_aprox": 250, "metros_por_envase": 60},
    ("acrilico", "alucobon"):  {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 11},
    ("alucobon", "alucobon"):  {"nombre": "Soudaflex 40FC",                      "precio_aprox": 180, "metros_por_envase": 11},
    ("aluminio", "pvc"):       {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 11},
    ("acrilico", "pvc"):       {"nombre": "Silicón Transparente Arquitectónico", "precio_aprox":  90, "metros_por_envase": 11},
}

# ─── LÁMINAS DE MATERIAL (precio por lámina 122×244 cm) ─────────────────────
# Precios calibrados con catálogo del proveedor "Todo para el Anunciero" feb-2026
LAMINAS = {
    "acrilico_3mm": {
        "nombre": "Acrílico 3mm",
        "precio": 1290,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["cara_letra_pequena", "cara_letra_mediana", "cara_caja"],
    },
    "acrilico_6mm": {
        "nombre": "Acrílico 6mm",
        "precio": 2615,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 6,
        "uso": ["cara_letra_grande", "cara_caja_premium"],
    },
    "pvc_3mm": {
        "nombre": "PVC Espumado 3mm",
        "precio": 365,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["fondo_letra_interior", "señaletica"],
    },
    "pvc_6mm": {
        "nombre": "PVC Espumado 6mm",
        "precio": 575,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 6,
        "uso": ["fondo_letra_exterior", "fondo_caja"],
    },
    "aluminio_cal22": {
        "nombre": "Aluminio Calibre 22 (0.76mm)",
        "precio": 1190,
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
        "precio": 904.80,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["fondo_premium", "cara_caja_exterior"],
    },
    # ── Acrílico por acabado / color ──────────────────────────────────────────
    "acrilico_3mm_blanco": {
        "nombre": "Acrílico Blanco Translúcido 3mm",
        "precio": 1390,
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
        "precio": 1510,
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
    # ── Aluminio sólido con acabado (cara de letra estilo corporativo) ────────
    "aluminio_plata_cepillado": {
        "nombre": "Aluminio Plata Cepillado cal 23",
        "precio": 3990,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 0.6,
        "uso": ["cara_letra", "decoracion"],
    },
    "aluminio_oro_cepillado": {
        "nombre": "Aluminio Oro Cepillado cal 23",
        "precio": 4270,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 0.6,
        "uso": ["cara_letra", "decoracion"],
    },
    "aluminio_espejo": {
        "nombre": "Aluminio Espejo cal 23",
        "precio": 4470,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 0.6,
        "colores": ["Plata Espejo", "Oro Espejo"],
        "uso": ["cara_letra", "decoracion"],
    },
}

# ─── MÓDULOS LED PARA LETRAS DE CANAL ────────────────────────────────────────
# profundidad = altura de cercha en cm
LEDS_CANAL = [
    {
        "id": "micro_sign",
        "nombre": "Módulo LED Micro Sign",
        "precio_tira_20": 70.00,
        "precio_modulo": 3.50,
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
        "precio_tira_20": 70.00,
        "precio_modulo": 3.50,
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
        "precio_tira_20": 170.00,
        "precio_modulo": 8.50,
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
        "precio_tira_20": 94.00,
        "precio_modulo": 4.70,
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
        "precio_tira_20": 106.00,
        "precio_modulo": 5.30,
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
        "precio_tira_20": 108.00,
        "precio_modulo": 5.40,
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
        "precio_tira_20": 108.00,
        "precio_modulo": 5.40,
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
        "precio_tira_20": 108.00,
        "precio_modulo": 5.40,
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
        "precio_tira_20": 119.00,
        "precio_modulo": 5.95,
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
        "precio_tira_20": 119.00,
        "precio_modulo": 5.95,
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
        "precio_tira_20": 236.00,
        "precio_modulo": 11.80,
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
            "largo_cm": 42,
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
            "largo_cm": 21,
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
            "largo_cm": 56,
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
            "largo_cm": 24,
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
            "tipo_led": "perimetral",
            "espaciado_cm": 4.3,
            "largo_modulo_cm": 4.3,
            "modulos_tira": 20,
            "max_cara_cm": 60,
            "precio": 330.60,
            "precio_modulo": 16.53,
            "watts": 1.32,
            "lumenes": 125,
            "ip": "IP67",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
        },
        {
            "id": "sign_03_high_panel",
            "nombre": "Módulo LED Sign 03 HIGH (grid panel)",
            "tipo_led": "modulo_panel",
            # 25 módulos por m² = grid 20×20 cm, calibrado para interior
            # ultra blanco (alucobon blanco brillante reduce ~25% el número de
            # módulos necesarios vs el grid 15×15 estándar).
            "densidad_modulos_m2": 25,
            "precio": 5.95,
            "watts": 1.08,
            "lumenes": 165,
            "ip": "IP66",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
            "nota": "Default para cajas medianas/grandes con interior ultra blanco.",
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

# ─── SILVATRIM (moldura de acabado para letras de canal) ─────────────────────
# precio_ml: precio por metro lineal   |   metros_rollo: longitud del rollo
# Ancho = cara visible del trim (la que tapa el canto de la cercha)
SILVATRIM = [
    {
        "id": "silvatrim_34",
        "nombre": "Silvatrim Gemini 3/4\"",
        "ancho_pulg": 0.75,
        "ancho_mm": 19,
        "precio_rollo": 2100,
        "metros_rollo": 45.7,
        "precio_ml": 45.95,
        "colores": ["Blanco", "Negro", "Rojo", "Azul", "Plata Metálico", "Plata Cepillado", "Dorado"],
        "uso_recomendado": "Letras con cercha hasta 5 cm de profundidad",
    },
    {
        "id": "silvatrim_1",
        "nombre": "Silvatrim Gemini 1\"",
        "ancho_pulg": 1.0,
        "ancho_mm": 25,
        "precio_rollo": 2400,
        "metros_rollo": 45.7,
        "precio_ml": 52.52,
        "colores": ["Blanco", "Negro", "Rojo", "Azul", "Plata Metálico", "Plata Cepillado", "Dorado"],
        "uso_recomendado": "Letras con cercha de 5–12 cm de profundidad",
    },
    {
        "id": "silvatrim_2",
        "nombre": "Silvatrim Gemini 2\"",
        "ancho_pulg": 2.0,
        "ancho_mm": 50,
        "precio_rollo": 2800,
        "metros_rollo": 45.7,
        "precio_ml": 61.27,
        "colores": ["Blanco", "Negro", "Plata Metálico"],
        "uso_recomendado": "Letras grandes con cercha mayor a 12 cm",
    },
    {
        "id": "silvatrim_gen",
        "nombre": "Silvatrim Rollo Económico 2cm",
        "ancho_pulg": 0.79,
        "ancho_mm": 20,
        "precio_rollo": 399,
        "metros_rollo": 40.0,
        "precio_ml": 9.98,
        "colores": ["Plata", "Negro", "Blanco", "Verde", "Azul", "Amarillo"],
        "uso_recomendado": "Uso interior o presupuesto ajustado",
    },
]


def silvatrim_recomendado(cercha_cm: float) -> dict:
    """Selecciona el ancho de Silvatrim según profundidad de cercha."""
    if cercha_cm <= 5:
        return next(s for s in SILVATRIM if s["id"] == "silvatrim_34")
    elif cercha_cm <= 12:
        return next(s for s in SILVATRIM if s["id"] == "silvatrim_1")
    else:
        return next(s for s in SILVATRIM if s["id"] == "silvatrim_2")


# ─── CABLES ─────────────────────────────────────────────────────────────────
# Precios por metro lineal con IVA. Rollo típico 100 m.
CABLES = {
    "led_radox_cal22": {
        "nombre": "Cable LED Radox cal 22 estañado",
        "precio_m": 3.50,    # rollo 100 m = $350
        "uso": "interno (LEDs ↔ fuente)",
    },
    "pot_cal18": {
        "nombre": "Cable POT cal 18",
        "precio_m": 4.00,    # rollo 100 m = $400
        "uso": "acometida 110V (fuente ↔ toma)",
    },
}


# ─── FUENTES DE PODER ────────────────────────────────────────────────────────
# Precios calibrados con catálogo "Todo para el Anunciero" feb-2026
FUENTES = [
    {"nombre": "Fuente Exterior 60W",   "watts": 60,  "precio": 280,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 100W",  "watts": 100, "precio": 365,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 150W",  "watts": 150, "precio": 590,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 200W",  "watts": 200, "precio": 575,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente Exterior 300W",  "watts": 300, "precio": 725,  "ip": "IP68", "uso": "exterior", "voltaje": 12},
    {"nombre": "Fuente UL 60W",         "watts": 60,  "precio": 470,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente UL 100W",        "watts": 100, "precio": 725,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente UL 150W",        "watts": 150, "precio": 990,  "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente UL 200W",        "watts": 200, "precio": 1185, "ip": "IP67", "uso": "ambos",    "voltaje": 12},
    {"nombre": "Fuente SLIM Interior 60W",  "watts": 60,  "precio": 165, "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
    {"nombre": "Fuente SLIM Interior 100W", "watts": 100, "precio": 190, "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
    {"nombre": "Fuente SLIM Interior 200W", "watts": 200, "precio": 310, "ip": "IP20", "uso": "interior", "voltaje": "12/24"},
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
    # Costo real del material por m² (con IVA). NO son precios de venta — el
    # margen al cliente se aplica en cotizar_caja. La paquetería del proveedor
    # se captura por trabajo en el campo "flete_maquila".
    "lona_translucida": 50,    # lona translúcida (impresa o lisa) — dato del propietario jul-2026
    "vinil_impresion":  60,    # vinil de impresión (gráfico impreso sobre acrílico)
    "acrilico":         380,   # acrílico blanco 3mm — $1127.52/lám ÷ 2.9768 m²
    "acrilico_2vistas": 760,   # 2 caras de acrílico
    # legacy (cotizaciones viejas re-abiertas): "lona" y "vinil_corte" ya no se
    # usan — la lona es lona_translucida y el vinil de corte se costea por
    # metro lineal de rollo del catálogo VINILOS.
}

# ─── VINILOS ADHESIVOS ────────────────────────────────────────────────────────
# precio_ml: precio por metro lineal de rollo (ancho estándar 0.60 m — dato del propietario)
# precio_m2 = precio_ml / ancho_rollo_m
VINILOS = [
    {
        "id": "vinil_std",
        "nombre": "Vinil Estándar",
        "precio_ml": 58.0,
        "ancho_rollo_m": 0.60,
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
        "ancho_rollo_m": 0.60,
        "acabado": "opaco",
        "colores": ["Ivory", "Grey Blue"],
    },
    {
        "id": "vinil_premium",
        "nombre": "Vinil Premium",
        "precio_ml": 120.0,
        "ancho_rollo_m": 0.60,
        "acabado": "opaco",
        "colores": ["Zinc Yellow", "Yellow Orange", "Dark Red", "Heather Red", "Violet",
                    "Intensive Blue", "Grass Green", "Gentian Blue", "Black", "White"],
    },
    {
        "id": "vinil_premium_alto",
        "nombre": "Vinil Premium Especial",
        "precio_ml": 180.0,
        "ancho_rollo_m": 0.60,
        "acabado": "metalico",
        "colores": ["Light Red", "Emerald", "Coral Red", "Gold"],
    },
]

# ─── VINILOS PARA CERCHA (cara lateral de letras 3D) ─────────────────────────
# Rollos angostos (0.30–0.61 m), precio por metro lineal del rollo
VINILOS_CERCHA = [
    {
        "id": "vc_std",
        "nombre": "Vinil Cercha Estándar",
        "precio_ml": 48.0,
        "ancho_rollo_m": 0.61,
        "acabado": "opaco",
        "colores": ["Blanco", "Negro", "Rojo", "Azul Rey", "Verde", "Amarillo", "Naranja", "Gris", "Café"],
    },
    {
        "id": "vc_metalico",
        "nombre": "Vinil Cercha Metálico",
        "precio_ml": 75.0,
        "ancho_rollo_m": 0.61,
        "acabado": "metalico",
        "colores": ["Plata Cromado", "Dorado", "Bronce", "Cobre"],
    },
    {
        "id": "vc_premium",
        "nombre": "Vinil Cercha Premium",
        "precio_ml": 98.0,
        "ancho_rollo_m": 0.61,
        "acabado": "opaco",
        "colores": ["Negro Mate", "Blanco Mate", "Rojo Oscuro", "Azul Marino", "Verde Pemex"],
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
        "modo_iluminacion": "cara",
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
        # halo: los módulos apuntan a la pared → una corrida perimetral,
        # NO cobertura de área como en cajón de luz
        "modo_iluminacion": "halo",
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
        "modo_iluminacion": "cara",
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

    Prioridad (taller SGI, ajustado con NotebookLM):
    1. modulo_panel — default para cajas medianas/grandes con interior ultra blanco
       (Sign 03 HIGH grid 20×20 cm, 25 mod/m²). Más económico que edgelite.
    2. edgelite — barras perimetrales (cuando el cliente las prefiere o la caja
       es delgada y se necesita proyección hacia adelante).
    3. perimetral — módulos discretos en el perímetro (Sign Edge 01).
    4. backlite — barras de fondo (cajas con tela, 1 vista interior).

    Para doble vista filtra solo LEDs con vistas >= 2.
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

    modulo_panel = [l for l in compatibles if l.get("tipo_led") == "modulo_panel"]
    edgelite = sorted(
        [l for l in compatibles if l.get("tipo_led") == "edgelite" and lado_corto <= l.get("max_cara_cm", 0)],
        key=lambda x: x.get("lumenes") or 0,
        reverse=True,
    )
    perimetral = [l for l in compatibles if l.get("tipo_led") == "perimetral"]
    backlite   = [l for l in compatibles if l.get("tipo_led") == "backlite"]

    # Orden de preferencia: modulo_panel > edgelite > perimetral > backlite
    if modulo_panel:
        return modulo_panel + edgelite + perimetral + backlite
    if edgelite:
        return edgelite + perimetral + backlite
    if perimetral:
        return perimetral + backlite
    return backlite or compatibles


# ─── CERCHA RECOMENDADA SEGÚN ALTURA DE LETRA ────────────────────────────────
def cercha_rango_cm(altura_letra_cm: float) -> dict:
    """Rango de profundidad de cercha recomendado según altura de letra.

    Basado en el catálogo Signalux (rangos de profundidad de LEDs por tamaño
    de aplicación) más heurística estándar de fabricación de letras 3D.
    Devuelve un dict con min, max, recomendado y categoría textual.
    """
    if altura_letra_cm <= 15:
        return {"min": 2.0,  "max": 6.0,  "recomendado": 4.0,
                "categoria": "Letra pequeña"}
    elif altura_letra_cm <= 30:
        return {"min": 4.0,  "max": 10.0, "recomendado": 6.0,
                "categoria": "Letra pequeña-mediana"}
    elif altura_letra_cm <= 60:
        return {"min": 8.0,  "max": 15.0, "recomendado": 10.0,
                "categoria": "Letra mediana"}
    elif altura_letra_cm <= 120:
        return {"min": 10.0, "max": 20.0, "recomendado": 15.0,
                "categoria": "Letra grande"}
    else:
        return {"min": 12.0, "max": 25.0, "recomendado": 18.0,
                "categoria": "Letra gigante"}


def cercha_recomendada_cm(altura_letra_cm: float) -> float:
    """Valor único recomendado dentro del rango (compatibilidad)."""
    return cercha_rango_cm(altura_letra_cm)["recomendado"]

# ─── LED RECOMENDADO SEGÚN PROFUNDIDAD DE CERCHA ─────────────────────────────
def led_recomendado(profundidad_cm: float, uso: str = "exterior") -> dict:
    candidatos = [l for l in LEDS_CANAL
                  if l["profundidad_min"] <= profundidad_cm <= l["profundidad_max"]]
    if not candidatos:
        candidatos = LEDS_CANAL
    # Preferir exterior IP65+
    if uso == "exterior":
        candidatos = [l for l in candidatos if int(l["ip"].replace("IP","")) >= 65] or candidatos
    # Preferir 12V (estándar) sobre 110V — el 110V requiere instalación eléctrica
    # especial y solo gana si NO hay alternativa de 12V para el rango de profundidad.
    candidatos_12v = [l for l in candidatos if l.get("voltaje", 12) == 12]
    candidatos = candidatos_12v or candidatos
    # Mayor lúmenes
    return sorted(candidatos, key=lambda x: x["lumenes"], reverse=True)[0]

# ─── MATERIAL DE CERCHA SEGÚN ALTURA ─────────────────────────────────────────
def material_cercha(altura_letra_cm: float) -> str:
    if altura_letra_cm <= 15:
        return "aluminio_cal22"
    elif altura_letra_cm <= 30:
        return "aluminio_cal20"
    else:
        return "aluminio_cal18"

# ─── MATERIAL DE SERCHA DE CAJA SEGÚN TAMAÑO Y USO ──────────────────────────
def material_sercha_caja(caja_w_cm: float, caja_h_cm: float, uso: str) -> str:
    """Calibre del aluminio para el cajón (sercha de caja de luz).
    Estándar de la industria: lámina de ~1.0 mm (cal 18) es el caballo de
    batalla para gabinetes; 0.9 mm (cal 20) alcanza en cajas chicas de
    interior (menos viento y menos claro que cubrir), y ahorra costo/peso."""
    lado_mayor = max(caja_w_cm, caja_h_cm)
    if uso == "interior" and lado_mayor <= 122:
        return "aluminio_cal20"
    return "aluminio_cal18"


def vinil_por_id(vinil_id: str) -> dict:
    """Vinil del catálogo VINILOS por id; fallback al primero (estándar)."""
    for v in VINILOS:
        if v["id"] == vinil_id:
            return v
    return VINILOS[0]


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


# ─── DATOS DE LA EMPRESA (impresos en documentos oficiales) ──────────────────
# Editar aquí o en catalog.json (sección "empresa"). Los campos vacíos salen
# como línea en blanco en los PDFs para llenarse a mano.
EMPRESA = {
    "razon_social": "SGI Impresión y Diseño",
    "rfc": "",
    "direccion": "",
    "telefono": "",
    "email": "",
}


# ─── PERSISTENCIA DEL CATÁLOGO ───────────────────────────────────────────────

def catalog_to_dict() -> dict:
    return {
        "empresa": dict(EMPRESA),
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
        "cables": dict(CABLES),
        "silvatrim": SILVATRIM,
        "vinilos": VINILOS,
        "vinilos_cercha": VINILOS_CERCHA,
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
    if "empresa" in raw:
        EMPRESA.update({k: str(v) for k, v in raw["empresa"].items() if k in EMPRESA})
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
    if "cables" in raw:
        for cid, cdata in raw["cables"].items():
            if cid in CABLES:
                CABLES[cid].update(cdata)
            else:
                CABLES[cid] = cdata
    if "silvatrim" in raw:
        SILVATRIM.clear()
        SILVATRIM.extend(raw["silvatrim"])
    if "vinilos" in raw:
        VINILOS.clear()
        VINILOS.extend(raw["vinilos"])
    if "vinilos_cercha" in raw:
        VINILOS_CERCHA.clear()
        VINILOS_CERCHA.extend(raw["vinilos_cercha"])


def _catalog_merge(raw: dict):
    """Fusiona raw con los globals sin borrar defaults de código."""
    if "empresa" in raw:
        EMPRESA.update({k: str(v) for k, v in raw["empresa"].items() if k in EMPRESA})
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
    if "cables" in raw:
        for cid, cdata in raw["cables"].items():
            if cid in CABLES:
                CABLES[cid].update(cdata)
            else:
                CABLES[cid] = cdata
    if "silvatrim" in raw:
        raw_by_id = {s["id"]: s for s in raw["silvatrim"] if "id" in s}
        for sv in SILVATRIM:
            if sv.get("id") in raw_by_id:
                sv.update(raw_by_id[sv["id"]])
        existing = {s.get("id") for s in SILVATRIM}
        for sv in raw["silvatrim"]:
            if sv.get("id") not in existing:
                SILVATRIM.append(sv)
    if "vinilos" in raw:
        raw_by_id = {v["id"]: v for v in raw["vinilos"] if "id" in v}
        for vinyl in VINILOS:
            if vinyl.get("id") in raw_by_id:
                vinyl.update(raw_by_id[vinyl["id"]])
        existing_ids = {v.get("id") for v in VINILOS}
        for vinyl in raw["vinilos"]:
            if vinyl.get("id") not in existing_ids:
                VINILOS.append(vinyl)
    if "vinilos_cercha" in raw:
        raw_by_id = {v["id"]: v for v in raw["vinilos_cercha"] if "id" in v}
        for vinyl in VINILOS_CERCHA:
            if vinyl.get("id") in raw_by_id:
                vinyl.update(raw_by_id[vinyl["id"]])
        existing_ids = {v.get("id") for v in VINILOS_CERCHA}
        for vinyl in raw["vinilos_cercha"]:
            if vinyl.get("id") not in existing_ids:
                VINILOS_CERCHA.append(vinyl)


def catalog_load():
    """Carga catalog.json si existe y fusiona con defaults; si no, usa los defaults."""
    if _CATALOG_FILE.exists():
        try:
            _catalog_merge(json.loads(_CATALOG_FILE.read_text(encoding="utf-8")))
        except Exception:
            log.exception(
                "catalog.json no se pudo cargar — se usarán los precios por defecto. "
                "Revisa el archivo si los precios mostrados son los antiguos."
            )


catalog_load()
