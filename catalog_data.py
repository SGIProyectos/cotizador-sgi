import copy
import json
import logging
import os
from pathlib import Path

from neon_calculator import NEON_PARAMS_DEFAULTS, NEON_PERFILES_DEFAULTS

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
    "acrilico_3mm_transparente": {
        "nombre": "Acrílico Transparente 3mm",
        "precio": 1200,
        "ancho_cm": 122, "alto_cm": 244,
        "grosor_mm": 3,
        "uso": ["base_planas", "cara_caja"],
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
# Fuente: catálogo Signalux (jul-2026) — categorías cajas-de-luz-interior y
# cajas-de-luz-exterior. Cada LED lleva `tamano_caja` (pequena/mediana/grande/
# gigante) que usa recomendar_led_caja() para priorizar por lado_mayor real.
LEDS_CAJA = {
    "interior": [
        {
            "id": "sign_edge_01_int",
            "nombre": "Módulo LED Sign Edge 01",
            "tipo_led": "perimetral",
            # `espaciado_cm` = distancia entre CENTROS al instalar en perímetro.
            # NO es el largo del módulo (4.3 cm). En obra se separan ~15 cm para
            # cobertura estándar con haz 10°×65° (verificado con instalador real).
            "espaciado_cm": 15,
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
            "tamano_caja": "pequena",
            "voltaje": 12,
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
            "tamano_caja": "mediana",
            "voltaje": 24,
        },
        {
            "id": "edgelite_42",
            "nombre": "Barra LED Edgelite Osram 42",
            "tipo_led": "edgelite",
            "largo_cm": 42,
            "max_cara_cm": 120,
            "precio": 375.93,
            "watts": 15,   # el Excel dice 0.15W, imposible físicamente con 1650L
            "lumenes": 1650,
            "ip": "IP33",
            "profundidad_min": 10, "profundidad_max": 40,
            "vistas": 1,
            "tamano_caja": "grande",
            "voltaje": 24,
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
            "tamano_caja": "mediana",
            "voltaje": 12,
            "nota": "Barra de fondo — ideal para lona translúcida (1 vista).",
        },
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
            "tamano_caja": "mediana",
            "voltaje": 12,
            "nota": "RGB — requiere controlador RGB (accesorio).",
        },
        {
            "id": "signaflex_zigzag",
            "nombre": "Tira LED Signaflex ZIG-ZAG",
            "tipo_led": "backlite",
            "precio_tira_5m": 445.96,
            "precio": 445.96,
            "watts": 40,
            "lumenes": None,
            "ip": "IP20",
            "profundidad_min": 6, "profundidad_max": 20,
            "vistas": 1,
            "tamano_caja": "gigante",
            "voltaje": 12,
            "nota": "Tira flexible zig-zag — cubre áreas grandes/curvas.",
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
            "tamano_caja": "gigante",
            "voltaje": 24,
            "nota": "Tira 5m — CCT 2700-13000K ajustable.",
        },
    ],
    "exterior": [
        {
            "id": "sign_edge_01",
            "nombre": "Módulo LED Sign Edge 01",
            "tipo_led": "perimetral",
            # `espaciado_cm` = distancia entre CENTROS al instalar en perímetro.
            # NO es el largo del módulo (4.3 cm). En obra se separan ~15 cm para
            # cobertura estándar con haz 10°×65° (verificado con instalador real).
            "espaciado_cm": 15,
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
            "tamano_caja": "pequena",
            "voltaje": 12,
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
            "profundidad_min": 12, "profundidad_max": 40,
            "vistas": 2,
            "tamano_caja": "mediana",
            "voltaje": 24,
        },
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
            "tamano_caja": "grande",
            "voltaje": 24,
        },
        {
            "id": "sign_03_pro",
            "nombre": "Módulo LED Sign 03 PRO (grid)",
            "tipo_led": "modulo_panel",
            "densidad_modulos_m2": 25,
            "precio": 214.60,     # precio tira 20 módulos
            "precio_modulo": 10.73,
            "watts": 0.72,
            "lumenes": 100,
            "ip": "IP66",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
            "tamano_caja": "gigante",
            "voltaje": 12,
            "nota": "Solo para cajas gigantes (>200 cm) donde barra no alcanza.",
        },
        {
            "id": "sign_02_high",
            "nombre": "Módulo LED Sign 02 HIGH (grid)",
            "tipo_led": "modulo_panel",
            "densidad_modulos_m2": 25,
            "precio": 290.93,
            "precio_modulo": 14.55,
            "watts": 0.72,
            "lumenes": 110,
            "ip": "IP67",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
            "tamano_caja": "gigante",
            "voltaje": 12,
            "nota": "Solo para cajas gigantes con requerimiento alto IP.",
        },
        {
            "id": "sign_03_high",
            "nombre": "Módulo LED Sign 03 HIGH (grid)",
            "tipo_led": "modulo_panel",
            "densidad_modulos_m2": 25,
            "precio": 370.04,
            "precio_modulo": 18.50,
            "watts": 1.08,
            "lumenes": 165,
            "ip": "IP66",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
            "tamano_caja": "gigante",
            "voltaje": 12,
            "nota": "Solo para cajas gigantes (>200 cm) — grid 20x20 cm.",
        },
        {
            "id": "sign_03_ac",
            "nombre": "Módulo LED Sign 03 AC (110V directo)",
            "tipo_led": "modulo_panel",
            "densidad_modulos_m2": 25,
            "precio": 713.40,
            "precio_modulo": 35.67,
            "watts": 1.2,
            "lumenes": 165,
            "ip": "IP66",
            "profundidad_min": 8, "profundidad_max": 15,
            "vistas": 1,
            "tamano_caja": "gigante",
            "voltaje": 110,
            "nota": "110V directo — sin fuente externa. Solo cajas gigantes.",
        },
    ],
}

# ─── ACCESORIOS DE CAJAS DE LUZ (no LEDs, se cotizan aparte si aplica) ─────
ACCESORIOS_CAJA = [
    {
        "id": "controlador_rgb_inalambrico",
        "nombre": "Controlador LED RGB Inalámbrico + Amplificador",
        "precio": 0,          # "Consultar precio" en Signalux
        "aplicacion": "backlite_rgb",
        "nota": "Requerido para cualquier LED RGB.",
    },
    {
        "id": "accesorios_barras_osram",
        "nombre": "Accesorios Barras LED Osram 21-42",
        "precio": 8.70,
        "precio_max": 22.04,
        "aplicacion": "edgelite_21,edgelite_42",
        "nota": "Fijaciones y conectores para barras Edgelite Osram.",
    },
]

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
def categoria_caja(ancho_cm: float, alto_cm: float) -> str:
    """Clasifica la caja por lado mayor según práctica de rotulación Signalux."""
    lado_mayor = max(ancho_cm or 0, alto_cm or 0)
    if lado_mayor <= 0:
        return "mediana"
    if lado_mayor <= 60:
        return "pequena"
    if lado_mayor <= 120:
        return "mediana"
    if lado_mayor <= 200:
        return "grande"
    return "gigante"


# Preferencia por tamaño real de caja (basada en catálogo Signalux, jul-2026):
#   pequeña ≤ 60 cm    → perimetral > backlite > edgelite > modulo_panel
#   mediana 60-120     → edgelite > perimetral > backlite > modulo_panel
#   grande 120-200     → edgelite > modulo_panel > backlite > perimetral
#   gigante > 200      → modulo_panel > edgelite > backlite > perimetral
_PREF_POR_TAMANO = {
    "pequena": ["perimetral", "backlite", "edgelite", "modulo_panel"],
    "mediana": ["edgelite", "perimetral", "backlite", "modulo_panel"],
    "grande":  ["edgelite", "modulo_panel", "backlite", "perimetral"],
    "gigante": ["modulo_panel", "edgelite", "backlite", "perimetral"],
}


def recomendar_led_caja(
    ancho_cm: float,
    alto_cm: float,
    doble_vista: bool = False,
    uso: str = "exterior",
    profundidad_cm: float = 15,
) -> list:
    """
    Devuelve lista de LEDs recomendados para caja de luz, ordenada por idoneidad.

    Basado en el catálogo Signalux (jul-2026) — priorización por tamaño real
    de la caja (lado mayor):

    - **pequeña** (≤60 cm): perimetral (Sign Edge 01) — cabe hasta 60cm, económico.
    - **mediana** (60-120 cm): edgelite (barras Osram 21 / Eco Edgelite 24) — mejor
      distribución de luz para tamaños medios sin sobreiluminar.
    - **grande** (120-200 cm): edgelite (Osram 42 / Eco Edgelite 56) — más barras.
    - **gigante** (>200 cm): modulo_panel (Sign 03 HIGH grid) — grid disperso
      llena cara enorme donde una barra no alcanza al centro.

    Filtra por profundidad, `max_cara_cm` (para edgelite y perimetral) y para
    doble vista sólo LEDs con `vistas >= 2`.
    """
    pool = LEDS_CAJA.get(uso, LEDS_CAJA["exterior"])
    cat = categoria_caja(ancho_cm, alto_cm)
    lado_corto = min(ancho_cm, alto_cm) if ancho_cm > 0 and alto_cm > 0 else 9999

    # 1) Filtro base: profundidad compatible + vistas requeridas
    def _compatible(l: dict) -> bool:
        if not (l.get("profundidad_min", 0) <= profundidad_cm <= l.get("profundidad_max", 999)):
            return False
        if doble_vista and l.get("vistas", 1) < 2:
            return False
        # Edgelite y perimetral tienen `max_cara_cm` (la barra tiene que caber
        # en el lado corto de la caja). Modulo_panel y backlite no tienen tope.
        max_cara = l.get("max_cara_cm")
        return not (max_cara and lado_corto > max_cara)

    compatibles = [l for l in pool if _compatible(l)]
    if not compatibles:
        return []

    # 2) Ordenar por (a) preferencia de tipo según tamaño, (b) coincidencia de
    #    `tamano_caja` con la categoría real, (c) lúmenes descendente.
    orden_tipo = _PREF_POR_TAMANO.get(cat, _PREF_POR_TAMANO["mediana"])

    def _key(l: dict) -> tuple:
        try:
            idx_tipo = orden_tipo.index(l.get("tipo_led", ""))
        except ValueError:
            idx_tipo = 99
        match_tamano = 0 if l.get("tamano_caja") == cat else 1
        lum = -(l.get("lumenes") or 0)     # más lúmenes primero
        return (idx_tipo, match_tamano, lum)

    return sorted(compatibles, key=_key)


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
def categoria_letra(altura_letra_cm: float) -> str:
    """Clasifica letra 3D por altura para elegir LED de intensidad apropiada.

    Rangos calibrados con Signalux (los módulos de cada tamaño están optimizados
    para letras dentro del rango — poner un Sign 03 HIGH en letra de 15 cm es
    exceso de luz + gasto innecesario)."""
    if altura_letra_cm <= 0:
        return "mediana"
    if altura_letra_cm <= 15:
        return "pequena"
    if altura_letra_cm <= 40:
        return "mediana"
    if altura_letra_cm <= 100:
        return "grande"
    return "gigante"


def led_recomendado(profundidad_cm: float, uso: str = "exterior",
                    altura_letra_cm: float = 0,
                    led_color: str = "auto") -> dict:
    """Recomienda LED para letra 3D según cercha, uso, altura y color.

    Prioridad:
    1. Compatible con profundidad de cercha (obligatorio).
    2. IP >= 65 si uso exterior.
    3. 12V sobre 110V (110V solo si no hay alternativa).
    4. Filtro por `led_color`:
       - `"auto"` / `"blanco"`: excluye LEDs de color específico y RGB.
       - `"rojo"` / `"verde"` / `"azul"`: solo LEDs con `color` match.
       - `"rgb"`: solo LEDs RGB.
    5. Match con `tamano` del LED igual a `categoria_letra(altura)`.
    6. Empate → más lúmenes gana.
    """
    candidatos = [l for l in LEDS_CANAL
                  if l["profundidad_min"] <= profundidad_cm <= l["profundidad_max"]]
    if not candidatos:
        candidatos = list(LEDS_CANAL)
    if uso == "exterior":
        candidatos = [l for l in candidatos if int(l["ip"].replace("IP","")) >= 65] or candidatos

    color = (led_color or "auto").lower().strip()
    if color in ("auto", "blanco"):
        # Solo blancos — excluir color específico y RGB. Preferir 12V sobre 110V.
        candidatos = [l for l in candidatos
                      if (l.get("color") or "").lower() in ("", "blanco", "puro", "frio", "calido")]
        c12 = [l for l in candidatos if l.get("voltaje", 12) == 12]
        candidatos = c12 or candidatos
    elif color == "rgb":
        candidatos = [l for l in candidatos if (l.get("color") or "").lower() == "rgb"] or candidatos
    else:
        # rojo / verde / azul / amarillo / etc.
        candidatos = [l for l in candidatos if (l.get("color") or "").lower() == color] or candidatos

    cat = categoria_letra(altura_letra_cm)
    def _key(l):
        match_tam = 0 if l.get("tamano") == cat else 1
        return (match_tam, -(l.get("lumenes") or 0))
    return sorted(candidatos, key=_key)[0]

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


# ─── TUBULARES (PTR) — bastidor de cajas de luz de 2 vistas ──────────────────
# Precios de partida (jul-2026) tomados del rango de mercado nacional
# (CostoNet, Sodimac, MercadoLibre, Surtiaceros — PTR de acero). El propietario
# debe ajustarlos con su proveedor local de Parral cuando cotice.
#
# ¿Por qué acero y no aluminio? La industria mexicana de cajas de luz (Alumex,
# Neon Universal) usa PTR de acero galvanizado como bastidor interno; el
# aluminio se reserva para cajas muy grandes de azotea donde el peso importa.
# El bastidor va dentro — no se ve — así que el material es 100% estructural.
TUBULARES = {
    "ptr_acero_1x1_cal18_pintado": {
        "id":          "ptr_acero_1x1_cal18_pintado",
        "nombre":      "PTR acero pintado 1\"×1\" cal 18",
        "seccion":     "1\" × 1\"",
        "calibre":     18,
        "espesor_mm":  1.20,
        "peso_kg_m":   0.90,
        "precio_ml":   55.0,       # $/m lineal
        "uso_sugerido": "cajas chicas de interior (≤ 80 cm)",
    },
    "ptr_acero_1x1_cal14_galvanizado": {
        "id":          "ptr_acero_1x1_cal14_galvanizado",
        "nombre":      "PTR acero galvanizado 1\"×1\" cal 14",
        "seccion":     "1\" × 1\"",
        "calibre":     14,
        "espesor_mm":  1.90,
        "peso_kg_m":   1.41,
        "precio_ml":   85.0,
        "uso_sugerido": "estándar (cajas 80–150 cm, interior o exterior)",
    },
    "ptr_acero_2x2_cal14_galvanizado": {
        "id":          "ptr_acero_2x2_cal14_galvanizado",
        "nombre":      "PTR acero galvanizado 2\"×2\" cal 14",
        "seccion":     "2\" × 2\"",
        "calibre":     14,
        "espesor_mm":  1.90,
        "peso_kg_m":   2.97,
        "precio_ml":   175.0,
        "uso_sugerido": "cajas grandes (>150 cm) o azotea",
    },
}


def tubular_recomendado(caja_w_cm: float, caja_h_cm: float,
                        uso: str = "exterior") -> dict:
    """Auto-selecciona el PTR del bastidor según tamaño y uso.

    Regla derivada de práctica industrial (Alumex, Neon Universal, LightboxShop):
      · lado_mayor > 150 cm o azotea → PTR 2×2 cal 14 (soporta viento)
      · lado_mayor ≤ 80 cm y uso interior → PTR 1×1 cal 18 (económico)
      · resto (80–150 cm) → PTR 1×1 cal 14 (caballo de batalla)"""
    lado_mayor = max(caja_w_cm, caja_h_cm)
    if lado_mayor > 150 or uso == "azotea":
        return TUBULARES["ptr_acero_2x2_cal14_galvanizado"]
    if lado_mayor <= 80 and uso == "interior":
        return TUBULARES["ptr_acero_1x1_cal18_pintado"]
    return TUBULARES["ptr_acero_1x1_cal14_galvanizado"]


def tubular_por_id(tubular_id: str) -> dict:
    """Devuelve el tubular con ese id; fallback al 1×1 cal 14 estándar."""
    return TUBULARES.get(tubular_id, TUBULARES["ptr_acero_1x1_cal14_galvanizado"])


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


# ─── ÍNDICE DE COMPLEJIDAD DE FABRICACIÓN (ICF) ──────────────────────────────
# Auditoría de mano de obra basada en geometría del SVG. NO cambia el precio
# de venta — es una segunda opinión sobre cuánto TIEMPO real toma fabricar la
# pieza, contrastada con la MO manual del cotizador.
#
# Modelo por proceso (calculator.compute_icf):
#   T_corte    = L/v_c + N_esquinas·t_dwell + α·κ_total + N_piezas·t_pierce
#   T_doblado  = P/v_b + N_esquinas·t_bend
#   T_sellado  = P_sellable/v_s + N_piezas·t_setup_pistola
#   T_cableado = N_modulos·t_mod
#   T_armado   = N_piezas·t_base + N_huecos·t_hueco
#   T_manip    = N_piezas·t_handling + masa_kg·t_carga_kg
#
# Constantes: "typical industry" (Groover ch.22, catálogos Signalux/CAM). NO
# son las de tu taller. Se calibran con 3-5 piezas cronometradas resolviendo
# por mínimos cuadrados; hasta entonces `calibrado_taller=False` marca el
# resultado como referencia, no verdad.
ICF_CONFIG = {
    "activo": True,           # False = no calcular ni mostrar
    "calibrado_taller": False, # False = defaults industria; True cuando cronometres
    "constantes": {
        # Corte (láser / router / CNC)
        "v_c_mm_s":         8.0,   # feed rate de corte (mm/s) — típico láser CO₂ 60W
        "t_dwell_s":        0.5,   # dwell por esquina (s) — parada + reaceleración
        "alpha_s_rad":      0.3,   # penalización por curvatura acumulada (s/rad)
        "t_pierce_s":       0.5,   # perforación inicial por contorno (s) — solo láser
        # Doblado de sercha
        "v_b_mm_s":         33.3,  # velocidad dobladora (mm/s ≈ 2 m/min)
        "t_bend_s":         5.0,   # tiempo por doblez (s)
        # Sellado / pegado
        "v_s_mm_s":         50.0,  # velocidad de aplicación (mm/s ≈ 3 m/min)
        "t_setup_pistola_s": 60.0, # cambio/recarga de cartucho por pieza (s)
        # Cableado LED
        "t_mod_s":          60.0,  # instalar + conectar un módulo (s)
        # Armado
        "t_base_min":       5.0,   # armado base por pieza (min)
        "t_hueco_min":      2.0,   # penalización por hueco/contador (min)
        # Manipulación
        "t_handling_min":   2.0,   # movimiento por pieza (min)
        "t_carga_s_kg":     30.0,  # carga adicional por kg (s)
    },
    "umbrales": {
        "flatten_epsilon_mm": 0.1,  # tolerancia cuerda al aplanar Béziers
        "corner_theta_deg":   15.0, # ángulo mínimo para contar como esquina dura
        "densidad_kg_m2": {         # kg/m² por material (para estimar masa)
            "aluminio":  2.7,       # cal 22 (0.76mm) ≈ 2.05 kg/m² · usamos 2.7 promedio
            "acrilico":  3.6,       # 3 mm ≈ 3.6 kg/m²
            "pvc":       0.5,       # PVC espumado 3 mm ≈ 0.5 kg/m²
            "alucobon":  4.5,       # Alucobond 3 mm ≈ 4.5 kg/m²
            "lona":      0.5,       # lona translúcida ~0.5 kg/m²
        },
    },
    # Pieza canónica para ICF normalizado: letra O de 30 cm, cercha 6 cm,
    # cajón de luz, aluminio cal 22. Su T_ref se cronometra una sola vez;
    # hasta entonces se usa el valor derivado del modelo con estas features.
    "canonica": {
        "descripcion": "Letra 'O' de 30 cm, cercha 6 cm, cajón de luz, aluminio cal 22",
        "L_mm":         942.5,   # perímetro exterior de O de 30 cm (π·30·10 aprox)
        "P_mm":         942.5,   # cerrado = L
        "A_mm2":        70685.0, # área bbox 30×30 ≈ 90000, menos hueco
        "N_piezas":     1,
        "N_huecos":     1,       # el contador interior de la O
        "N_esquinas":   0,       # circular
        "kappa_total_rad": 12.566, # 2 vueltas: exterior + interior = 4π
        "P_sellable_mm": 1885.0, # 2P (cara-cercha + cercha-fondo)
        "N_modulos_led": 6,
        "masa_kg":       0.19,   # área ≈ 0.07 m² × 2.7 kg/m²
        # T_ref se calcula si es 0.0 (no cronometrada aún)
        "T_ref_min":     0.0,
    },
}


# ─── NEÓN LED (perfiles + parámetros) ────────────────────────────────────────
# Defaults viven en neon_calculator.py (para que el motor sea autocontenido y
# testeable sin este módulo). Aquí solo se hace la copia mutable que actúa
# como estado del catálogo — editable desde /api/catalog y persistida en
# catalog.json como el resto. Deep-copy para no mutar los defaults del motor.
NEON_PERFILES: list[dict] = copy.deepcopy(NEON_PERFILES_DEFAULTS)
NEON_PARAMS:   dict       = copy.deepcopy(NEON_PARAMS_DEFAULTS)


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
        "tubulares": dict(TUBULARES),
        "icf": {
            "activo": ICF_CONFIG["activo"],
            "calibrado_taller": ICF_CONFIG["calibrado_taller"],
            "constantes": dict(ICF_CONFIG["constantes"]),
            "umbrales": {
                "flatten_epsilon_mm": ICF_CONFIG["umbrales"]["flatten_epsilon_mm"],
                "corner_theta_deg":   ICF_CONFIG["umbrales"]["corner_theta_deg"],
                "densidad_kg_m2":     dict(ICF_CONFIG["umbrales"]["densidad_kg_m2"]),
            },
            "canonica": dict(ICF_CONFIG["canonica"]),
        },
        "neon_perfiles": copy.deepcopy(NEON_PERFILES),
        "neon_params":   copy.deepcopy(NEON_PARAMS),
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
    if "tipos_construccion" in raw:
        TIPOS_CONSTRUCCION.clear()
        TIPOS_CONSTRUCCION.update(raw["tipos_construccion"])
    if "gruas" in raw:
        GRUAS.clear()
        GRUAS.extend(raw["gruas"])
    if "tubulares" in raw and isinstance(raw["tubulares"], dict):
        TUBULARES.clear()
        TUBULARES.update(raw["tubulares"])
    if "icf" in raw:
        _apply_icf(raw["icf"])
    if isinstance(raw.get("neon_perfiles"), list):
        NEON_PERFILES.clear()
        NEON_PERFILES.extend(copy.deepcopy(raw["neon_perfiles"]))
    if isinstance(raw.get("neon_params"), dict):
        _apply_neon_params(raw["neon_params"], full_replace=True)


def _apply_neon_params(raw: dict, *, full_replace: bool) -> None:
    """Aplica overrides al dict NEON_PARAMS in-place.
    - full_replace=True (desde catalog_apply): reemplaza cada key top-level y
      el sub-dict fab3d completos.
    - full_replace=False (desde _catalog_merge): fusiona preservando defaults
      no presentes en `raw` — así se conservan campos nuevos añadidos al motor
      cuando el catalog.json es viejo."""
    if not isinstance(raw, dict):
        return
    for k, v in raw.items():
        if k == "fab3d":
            continue
        if full_replace or k not in NEON_PARAMS:
            NEON_PARAMS[k] = copy.deepcopy(v)
        elif isinstance(v, list):
            # listas del catálogo (fuentes, consumibles, bases, formas, urgencias)
            # se reemplazan completas — el frontend siempre manda la lista viva.
            NEON_PARAMS[k] = copy.deepcopy(v)
        else:
            NEON_PARAMS[k] = v
    if isinstance(raw.get("fab3d"), dict):
        if full_replace:
            NEON_PARAMS["fab3d"] = copy.deepcopy(raw["fab3d"])
        else:
            NEON_PARAMS["fab3d"].update(copy.deepcopy(raw["fab3d"]))


def _apply_icf(raw: dict) -> None:
    """Aplica una sección `icf` del catálogo a ICF_CONFIG in-place.
    Valida tipos y descarta claves desconocidas para evitar corrupción."""
    if not isinstance(raw, dict):
        return
    if "activo" in raw:
        ICF_CONFIG["activo"] = bool(raw["activo"])
    if "calibrado_taller" in raw:
        ICF_CONFIG["calibrado_taller"] = bool(raw["calibrado_taller"])
    if isinstance(raw.get("constantes"), dict):
        for k, v in raw["constantes"].items():
            if k in ICF_CONFIG["constantes"]:
                try:
                    ICF_CONFIG["constantes"][k] = float(v)
                except (TypeError, ValueError):
                    log.warning("ICF constante %s: valor inválido %r ignorado", k, v)
    if isinstance(raw.get("umbrales"), dict):
        u = raw["umbrales"]
        for k in ("flatten_epsilon_mm", "corner_theta_deg"):
            if k in u:
                try:
                    ICF_CONFIG["umbrales"][k] = float(u[k])
                except (TypeError, ValueError):
                    pass
        if isinstance(u.get("densidad_kg_m2"), dict):
            for mat, dens in u["densidad_kg_m2"].items():
                try:
                    ICF_CONFIG["umbrales"]["densidad_kg_m2"][mat] = float(dens)
                except (TypeError, ValueError):
                    pass
    if isinstance(raw.get("canonica"), dict):
        for k, v in raw["canonica"].items():
            if k in ICF_CONFIG["canonica"]:
                # descripcion es str, todo lo demás es numérico
                if k == "descripcion":
                    ICF_CONFIG["canonica"][k] = str(v)
                else:
                    try:
                        ICF_CONFIG["canonica"][k] = float(v) if isinstance(ICF_CONFIG["canonica"][k], float) else int(v)
                    except (TypeError, ValueError):
                        pass


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
    if "tipos_construccion" in raw:
        for tid, tdata in raw["tipos_construccion"].items():
            if tid in TIPOS_CONSTRUCCION:
                TIPOS_CONSTRUCCION[tid].update(tdata)
            else:
                TIPOS_CONSTRUCCION[tid] = tdata
    if "gruas" in raw:
        raw_by_id = {g["id"]: g for g in raw["gruas"] if "id" in g}
        for grua in GRUAS:
            if grua.get("id") in raw_by_id:
                grua.update(raw_by_id[grua["id"]])
        existing_ids = {g.get("id") for g in GRUAS}
        for grua in raw["gruas"]:
            if grua.get("id") not in existing_ids:
                GRUAS.append(grua)
    if isinstance(raw.get("tubulares"), dict):
        for tid, tdata in raw["tubulares"].items():
            if tid in TUBULARES:
                TUBULARES[tid].update(tdata)   # merge — preserva peso_kg_m etc.
            else:
                TUBULARES[tid] = tdata
    if "icf" in raw:
        _apply_icf(raw["icf"])
    if isinstance(raw.get("neon_perfiles"), list):
        # perfiles: merge por id (preserva perfiles nuevos del código no en JSON)
        raw_by_id = {p["id"]: p for p in raw["neon_perfiles"] if "id" in p}
        for perfil in NEON_PERFILES:
            if perfil.get("id") in raw_by_id:
                perfil.update(raw_by_id[perfil["id"]])
        existing = {p.get("id") for p in NEON_PERFILES}
        for perfil in raw["neon_perfiles"]:
            if perfil.get("id") not in existing:
                NEON_PERFILES.append(copy.deepcopy(perfil))
    if isinstance(raw.get("neon_params"), dict):
        _apply_neon_params(raw["neon_params"], full_replace=False)


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
