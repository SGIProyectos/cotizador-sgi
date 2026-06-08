"""Fixtures compartidas para los tests."""
import pytest

SQUARE_SVG = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
  <path d="M50,50 L150,50 L150,150 L50,150 Z" id="cuadrado"/>
</svg>"""


# Tres "letras" cuadradas idénticas, dispuestas horizontalmente con leve gap.
THREE_LETTERS_SVG = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200" width="600" height="200">
  <path d="M10,50 L110,50 L110,150 L10,150 Z" id="A"/>
  <path d="M210,50 L310,50 L310,150 L210,150 Z" id="B"/>
  <path d="M410,50 L510,50 L510,150 L410,150 Z" id="C"/>
</svg>"""


# Una "caja" con contorno rectangular grande + dos elementos de diseño dentro.
CAJA_SVG = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200" width="400" height="200">
  <path d="M10,10 L390,10 L390,190 L10,190 Z" id="outline"/>
  <path d="M50,80 L150,80 L150,120 L50,120 Z" id="dis1"/>
  <path d="M250,80 L350,80 L350,120 L250,120 Z" id="dis2"/>
</svg>"""


@pytest.fixture
def square_svg() -> bytes:
    return SQUARE_SVG


@pytest.fixture
def three_letters_svg() -> bytes:
    return THREE_LETTERS_SVG


@pytest.fixture
def caja_svg() -> bytes:
    return CAJA_SVG
