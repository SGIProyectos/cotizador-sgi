"""Fixtures compartidas para los tests."""
import pytest

import db as _db


@pytest.fixture(scope="session", autouse=True)
def _db_de_prueba(tmp_path_factory):
    """Aísla los tests en una DB temporal. Sin esto, la suite escribe
    cotizaciones basura en el cotizador.db REAL del taller (consume folios
    y contamina el historial y el dashboard)."""
    _db.DB_PATH = tmp_path_factory.mktemp("db") / "test_cotizador.db"
    _db.init_db()


@pytest.fixture(scope="session", autouse=True)
def _backups_de_prueba(tmp_path_factory):
    """Aísla los respaldos en una carpeta temporal. El lifespan de la app
    respalda la DB al arrancar (cada TestClient), y sin esto llenaría el
    backups/ real del taller con copias de la DB de prueba."""
    import main as _main
    _main.BACKUP_DIR = tmp_path_factory.mktemp("backups")

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
