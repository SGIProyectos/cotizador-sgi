"""
vectorizer.py — Imagen raster → SVG para fabricación de anuncios.
Pipeline: flood-fill elimina fondo → PNG transparente → vtracer genera Bézier.
"""
import io

import cv2
import numpy as np
from PIL import Image as _PIL


def _remove_background(img: np.ndarray, tol: int = 38) -> np.ndarray:
    """Flood-fill desde bordes → máscara: 255=logo, 0=fondo."""
    h, w  = img.shape[:2]
    work  = img.copy()
    ff    = np.zeros((h + 2, w + 2), np.uint8)
    flags = cv2.FLOODFILL_MASK_ONLY | (1 << 8)
    lo = hi = (tol, tol, tol)
    step_x = max(1, w // 32)
    step_y = max(1, h // 32)
    seeds  = (
        [(0,   x) for x in range(0, w, step_x)] +
        [(h-1, x) for x in range(0, w, step_x)] +
        [(y,   0) for y in range(0, h, step_y)] +
        [(y, w-1) for y in range(0, h, step_y)]
    )
    for sy, sx in seeds:
        if ff[sy + 1, sx + 1] == 0:
            cv2.floodFill(work, ff, (sx, sy), (0, 0, 0), lo, hi, flags)
    fg = (ff[1:-1, 1:-1] == 0).astype(np.uint8) * 255
    if np.sum(fg > 0) < h * w * 0.04:
        fg = np.ones((h, w), np.uint8) * 255
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)
    return fg


def vectorize(
    img_bytes:        bytes,
    bg_tol:           int = 38,
    filter_speckle:   int = 8,
    color_precision:  int = 3,
    layer_difference: int = 48,
) -> str:
    """
    Convierte imagen JPG/PNG/WEBP a SVG vectorial.

    Args:
        img_bytes:        bytes de la imagen
        bg_tol:           tolerancia para detectar fondo (10-70)
        filter_speckle:   ignora manchas menores a N píxeles (1-30)
        color_precision:  número de bits de color por capa (1-8, menos = menos capas)
        layer_difference: umbral para fusionar capas de color similares (4-64)
    """
    import vtracer

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo leer la imagen.")

    fg   = _remove_background(img, tol=bg_tol)
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = fg

    pil = _PIL.fromarray(cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    png = buf.getvalue()

    return vtracer.convert_raw_image_to_svg(
        png,
        img_format        = "png",
        colormode         = "color",
        hierarchical      = "cutout",
        mode              = "spline",
        filter_speckle    = filter_speckle,
        color_precision   = color_precision,
        layer_difference  = layer_difference,
        corner_threshold  = 60,
        length_threshold  = 4.0,
        splice_threshold  = 45,
        path_precision    = 3,
    )
