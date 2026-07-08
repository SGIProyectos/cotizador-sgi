"""
vectorizer.py — Imagen raster → SVG de silueta única para corte (láser/CNC).

Pipeline:
1. Filtro bilateral: aplana texturas sin borrar bordes.
2. K-means en espacio LAB: reduce la imagen a una paleta pequeña.
3. Fondo = clusters dominantes en el borde de la imagen (funciona con fondos
   texturizados, no solo lisos); colores casi idénticos al fondo se fusionan.
4. Clusters "sospechosos" (parecidos al fondo): sus componentes solo se
   conservan si tocan una figura confiable.
5. Silueta = unión de todo el primer plano, limpiada: componentes y huecos
   menores al área mínima se descartan.
6. vtracer en modo binario traza la silueta → SVG de un solo color.
"""
import io

import cv2
import numpy as np

_MAX_DIM = 1200          # se reduce la imagen para procesar (coords SVG escalan igual)
_BORDER_FRAC = 0.03      # ancho de la franja de borde usada para detectar fondo
_BORDER_BG_MIN = 0.10    # fracción mínima en el borde para marcar un cluster como fondo
_MIN_FG_FRAC = 0.01      # si el primer plano queda menor a esto, se usa el fallback


def _quantize(img: np.ndarray, n_colors: int) -> tuple[np.ndarray, np.ndarray]:
    """K-means en LAB. Devuelve (labels h×w, centers n×3 float32)."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(lab, n_colors, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    return labels.reshape(img.shape[:2]), centers


def _border_fractions(labels: np.ndarray, n_colors: int) -> np.ndarray:
    h, w = labels.shape
    m = max(2, int(min(h, w) * _BORDER_FRAC))
    border = np.concatenate([
        labels[:m, :].ravel(), labels[-m:, :].ravel(),
        labels[:, :m].ravel(), labels[:, -m:].ravel(),
    ])
    return np.bincount(border, minlength=n_colors) / border.size


def _detect_background(
    labels: np.ndarray, centers: np.ndarray, n_colors: int, merge_dist: float
) -> set[int]:
    frac = _border_fractions(labels, n_colors)
    bg = set(np.where(frac > _BORDER_BG_MIN)[0].tolist())
    if not bg:
        bg = {int(frac.argmax())}
    # colores casi idénticos al fondo (anti-aliasing, halos JPG) también son fondo
    for ci in range(n_colors):
        if ci in bg:
            continue
        dmin = min(float(np.linalg.norm(centers[ci] - centers[b])) for b in bg)
        if dmin < merge_dist:
            bg.add(ci)
    return bg


def _keep_big_components(mask: np.ndarray, min_area: float) -> np.ndarray:
    n, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[comp == i] = 255
    return keep


def _fill_small_holes(mask: np.ndarray, min_area: float) -> np.ndarray:
    """Rellena huecos interiores menores a min_area (poros de textura).
    Los huecos grandes (contadores de letras) se preservan."""
    h, w = mask.shape
    inv = (mask == 0).astype(np.uint8)
    n, comp, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    out = mask.copy()
    for i in range(1, n):
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        cw, ch = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        touches_border = x == 0 or y == 0 or x + cw == w or y + ch == h
        if not touches_border and stats[i, cv2.CC_STAT_AREA] < min_area:
            out[comp == i] = 255
    return out


def _silhouette_mask(
    img: np.ndarray, n_colors: int, merge_dist: float, suspect_dist: float,
    min_area: float,
) -> np.ndarray:
    """Máscara binaria (255 = figura) de todo el primer plano."""
    labels, centers = _quantize(img, n_colors)
    bg = _detect_background(labels, centers, n_colors, merge_dist)

    suspects, trusted = set(), set()
    for ci in range(n_colors):
        if ci in bg:
            continue
        dmin = min(float(np.linalg.norm(centers[ci] - centers[b])) for b in bg)
        (suspects if dmin < suspect_dist else trusted).add(ci)

    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    masks = {}
    trusted_union = np.zeros(labels.shape, np.uint8)
    for ci in suspects | trusted:
        m = (labels == ci).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k3)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k3)
        # umbral relajado por color: los trazos delgados de un diseño lineal
        # son componentes chicos; el filtro estricto se aplica sobre la unión
        masks[ci] = _keep_big_components(m, min_area * 0.5)
        if ci in trusted:
            trusted_union |= masks[ci]

    # los sospechosos solo cuentan si tocan una figura confiable
    if trusted:
        k7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        trusted_dil = cv2.dilate(trusted_union, k7)
        for ci in suspects:
            n, comp, _, _ = cv2.connectedComponentsWithStats(masks[ci], connectivity=8)
            keep = np.zeros_like(masks[ci])
            for i in range(1, n):
                sel = comp == i
                if (trusted_dil[sel] > 0).any():
                    keep[sel] = 255
            masks[ci] = keep

    union = np.zeros(labels.shape, np.uint8)
    for m in masks.values():
        union |= m

    # cierre suave (3×3): sella poros sin fundir trazos vecinos — los diseños
    # lineales (estilo neón) dependen de que los espacios entre líneas queden abiertos
    union = cv2.morphologyEx(union, cv2.MORPH_CLOSE, k3)
    # solo se rellenan poros diminutos; las celdas internas del diseño se preservan
    union = _fill_small_holes(union, max(9.0, min_area * 0.12))
    return _keep_big_components(union, min_area)


def vectorize(
    img_bytes:        bytes,
    bg_tol:           int = 38,
    filter_speckle:   int = 8,
    color_precision:  int = 3,
    layer_difference: int = 48,
) -> str:
    """
    Convierte imagen JPG/PNG/WEBP a SVG de silueta única (negro) para corte.

    Args:
        img_bytes:        bytes de la imagen
        bg_tol:           agresividad al quitar fondo (10-70): más alto absorbe
                          más colores parecidos al fondo
        filter_speckle:   ignora manchas menores a N píxeles al trazar (1-30)
        color_precision:  detalle del análisis de color (1-8): más alto separa
                          mejor figura de fondo en imágenes complejas
        layer_difference: tamaño mínimo de detalle conservado (4-64): más alto
                          descarta piezas y huecos más grandes
    """
    import vtracer

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo leer la imagen.")

    h, w = img.shape[:2]
    if max(h, w) > _MAX_DIM:
        s = _MAX_DIM / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]

    smooth = cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)
    smooth = cv2.bilateralFilter(smooth, d=9, sigmaColor=75, sigmaSpace=75)
    # la mediana borra el grano/grunge fino sin degradar bordes de trazos
    smooth = cv2.medianBlur(smooth, 5)

    n_colors = max(4, min(16, 3 * color_precision))
    merge_dist = bg_tol * 0.4
    suspect_dist = bg_tol * 1.45
    min_area = h * w * (layer_difference / 1000) / 100

    fg = _silhouette_mask(smooth, n_colors, merge_dist, suspect_dist, min_area)

    if np.count_nonzero(fg) < h * w * _MIN_FG_FRAC:
        # fallback: fondo = solo el color más común del borde, sin sospechosos
        labels, centers = _quantize(smooth, n_colors)
        frac = _border_fractions(labels, n_colors)
        fg = (labels != int(frac.argmax())).astype(np.uint8) * 255
        k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k3)
        fg = _fill_small_holes(fg, max(9.0, min_area * 0.12))
        fg = _keep_big_components(fg, min_area)

    canvas = np.full((h, w, 4), 255, np.uint8)
    canvas[fg > 0] = (0, 0, 0, 255)
    ok, png = cv2.imencode(".png", canvas)
    if not ok:
        raise ValueError("No se pudo codificar la máscara.")

    return vtracer.convert_raw_image_to_svg(
        io.BytesIO(png.tobytes()).getvalue(),
        img_format        = "png",
        colormode         = "binary",
        mode              = "spline",
        filter_speckle    = filter_speckle,
        corner_threshold  = 60,
        length_threshold  = 4.0,
        splice_threshold  = 45,
        path_precision    = 2,
    )
