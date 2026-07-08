"""Tests del pipeline raster → SVG de silueta (vectorizer.py).

Usa imágenes sintéticas generadas con OpenCV — no depende de archivos externos.
"""
import cv2
import numpy as np
import pytest

from calculator import parse_svg
from vectorizer import vectorize

W, H = 400, 300


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _fondo_liso(color=(255, 255, 255)) -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = color
    return img


def _fondo_texturizado() -> np.ndarray:
    """Fondo azul con ruido fuerte (simula fondos tipo fotografía/acuarela)."""
    rng = np.random.default_rng(42)
    base = np.array([180, 90, 30], np.float32)  # BGR azul
    noise = rng.normal(0, 35, (H, W, 3)).astype(np.float32)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def _piezas_cerradas(svg_text: str):
    data = parse_svg(svg_text.encode())
    return [p for p in data.paths if p.is_closed]


def test_figura_solida_sobre_fondo_liso():
    img = _fondo_liso()
    cv2.rectangle(img, (100, 75), (300, 225), (0, 0, 0), -1)
    svg = vectorize(_png(img))
    piezas = _piezas_cerradas(svg)
    assert len(piezas) == 1
    bbox = piezas[0].bbox
    assert bbox["w"] == pytest.approx(200, rel=0.08)
    assert bbox["h"] == pytest.approx(150, rel=0.08)


def test_figura_sobre_fondo_texturizado():
    """El caso que rompía al vectorizador viejo: fondo NO uniforme."""
    img = _fondo_texturizado()
    cv2.rectangle(img, (100, 75), (300, 225), (255, 255, 255), -1)
    svg = vectorize(_png(img))
    piezas = _piezas_cerradas(svg)
    assert len(piezas) == 1
    bbox = piezas[0].bbox
    assert bbox["w"] == pytest.approx(200, rel=0.10)
    assert bbox["h"] == pytest.approx(150, rel=0.10)


def test_manchas_pequenas_se_descartan():
    img = _fondo_liso()
    cv2.rectangle(img, (100, 75), (300, 225), (0, 0, 0), -1)
    for x, y in [(30, 30), (370, 30), (30, 270), (370, 270)]:
        cv2.circle(img, (x, y), 2, (0, 0, 0), -1)
    svg = vectorize(_png(img))
    assert len(_piezas_cerradas(svg)) == 1


def test_hueco_grande_se_preserva():
    """Contadores de letras (hueco de la R, O…) deben sobrevivir al corte."""
    img = _fondo_liso()
    cv2.rectangle(img, (100, 75), (300, 225), (0, 0, 0), -1)
    cv2.rectangle(img, (170, 120), (230, 180), (255, 255, 255), -1)
    svg = vectorize(_png(img))
    # vtracer binario emite el hueco como subpath: al menos 2 'M' en el path
    d_attrs = [seg for seg in svg.split('d="')[1:]]
    total_m = sum(d.split('"')[0].count("M") for d in d_attrs)
    assert total_m >= 2


def test_celdas_internas_de_diseno_lineal_se_preservan():
    """Diseños estilo neón (enrejados, tramas): las celdas entre trazos NO
    deben rellenarse — son geometría de corte para anuncios luminosos."""
    img = _fondo_liso()
    cv2.rectangle(img, (100, 75), (300, 225), (0, 0, 0), -1)
    for cx in range(130, 280, 30):
        for cy in range(105, 200, 30):
            cv2.rectangle(img, (cx, cy), (cx + 6, cy + 6), (255, 255, 255), -1)
    svg = vectorize(_png(img))
    d_attrs = svg.split('d="')[1:]
    total_m = sum(d.split('"')[0].count("M") for d in d_attrs)
    assert total_m >= 10  # rect + al menos 9 de las 20 celdas de 7×7 px


def test_multiples_piezas_separadas():
    img = _fondo_liso()
    cv2.rectangle(img, (40, 100), (110, 200), (0, 0, 0), -1)
    cv2.rectangle(img, (160, 100), (230, 200), (0, 0, 0), -1)
    cv2.circle(img, (330, 150), 45, (0, 0, 0), -1)
    svg = vectorize(_png(img))
    assert len(_piezas_cerradas(svg)) == 3


def test_imagen_invalida_lanza_valueerror():
    with pytest.raises(ValueError):
        vectorize(b"esto no es una imagen")


def test_imagen_grande_se_reduce_sin_fallar():
    img = np.full((2400, 3200, 3), 255, np.uint8)
    cv2.rectangle(img, (800, 600), (2400, 1800), (0, 0, 0), -1)
    svg = vectorize(_png(img))
    piezas = _piezas_cerradas(svg)
    assert len(piezas) == 1
    # coordenadas reescaladas a <= _MAX_DIM
    assert piezas[0].bbox["w"] <= 1200
