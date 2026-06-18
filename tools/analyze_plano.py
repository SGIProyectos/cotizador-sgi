"""tools/analyze_plano.py — Validación del algoritmo de detección de piezas.

Lee un SVG, reusa `calculator.parse_svg` (universo del programa: piezas
vectoriales arbitrarias, no solo letras), aplica filtros para descartar
basura del vectorizer (fondos, motas, duplicados), y emite un reporte JSON
con bbox y medidas reales en cm de cada pieza detectada.

Si el SVG declara su unidad real (pt para Illustrator, mm/cm/in explícitas
en width/height), el reporte muestra cm reales sin que tengas que pasar
`--ancho-cm` ni `--altura-cm`. Solo pasa esos flags si quieres ESCALAR el
diseño a un tamaño distinto al del archivo original.

Uso:
    python tools/analyze_plano.py EJEMPLOS/figuras.svg
    python tools/analyze_plano.py EJEMPLOS/casselsvg.svg
    python tools/analyze_plano.py EJEMPLOS/A.svg --altura-cm 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path as FsPath

# Permitir ejecución directa desde la raíz del repo o desde tools/.
sys.path.insert(0, str(FsPath(__file__).resolve().parent.parent))

from calculator import parse_svg  # noqa: E402

# ─── Parámetros del algoritmo (calibrables) ──────────────────────────────────

FONDO_BBOX_PCT = 0.95     # bbox ≥ 95% viewBox → fondo, descartar
MOTA_AREA_PCT  = 0.0001   # área ≤ 0.01% viewBox → mota, descartar
DUP_BBOX_TOL   = 0.01     # 1% delta en x, y, w, h → duplicado
DUP_PERIM_TOL  = 0.02     # 2% delta en perímetro → duplicado
ROW_TOL_PCT    = 0.30     # 30% de altura promedio para agrupar piezas en fila


def analyze(svg_path: str | FsPath, ancho_cm: float = 0.0,
            altura_cm: float = 0.0) -> dict:
    raw = FsPath(svg_path).read_bytes()
    data = parse_svg(raw)

    vb_w, vb_h = data.viewbox_w, data.viewbox_h
    viewbox_area = max(vb_w * vb_h, 1.0)

    # ── Fase 1: traducir PathInfo a candidatas ───────────────────────────────
    candidatas: list[dict] = []
    for p in data.paths:
        candidatas.append({
            "bbox": (p.bbox["x"], p.bbox["y"], p.bbox["w"], p.bbox["h"]),
            "perimetro_px": p.perimeter_px,
            "n_subpaths": 1,
            "tiene_hueco": False,
            "id_original": p.svg_id,
        })

    # ── Fase 2: filtrar fondo, motas, duplicados ─────────────────────────────
    descartadas: list[dict] = []
    conservadas: list[dict] = []
    for cand in candidatas:
        x, y, w, h = cand["bbox"]
        area = w * h
        if area >= FONDO_BBOX_PCT * viewbox_area:
            cand["motivo"] = f"fondo (bbox = {100 * area / viewbox_area:.1f}% del viewBox)"
            descartadas.append(cand)
            continue
        if area <= MOTA_AREA_PCT * viewbox_area:
            cand["motivo"] = f"mota (area = {100 * area / viewbox_area:.4f}% del viewBox)"
            descartadas.append(cand)
            continue
        is_dup = False
        for kept in conservadas:
            kx, ky, kw, kh = kept["bbox"]
            sx = max(vb_w, 1.0)
            sy = max(vb_h, 1.0)
            if (abs(kx - x) <= DUP_BBOX_TOL * sx
                    and abs(ky - y) <= DUP_BBOX_TOL * sy
                    and abs(kw - w) <= DUP_BBOX_TOL * max(kw, 1.0)
                    and abs(kh - h) <= DUP_BBOX_TOL * max(kh, 1.0)
                    and abs(kept["perimetro_px"] - cand["perimetro_px"])
                    <= DUP_PERIM_TOL * max(kept["perimetro_px"], 1.0)):
                is_dup = True
                break
        if is_dup:
            cand["motivo"] = "duplicado de pieza ya conservada"
            descartadas.append(cand)
            continue
        conservadas.append(cand)

    # ── Fase 3: escala (cm/unidad del viewBox) ───────────────────────────────
    # Prioridad:
    #   1. Si el usuario pasa --altura-cm o --ancho-cm → escala explícita
    #      basada en el bbox conjunto (escala el diseño).
    #   2. Si el SVG declara su unidad real (Illustrator pt, width="200mm"...)
    #      → respetar esa escala. Sin que el usuario ingrese nada.
    #   3. Sin nada de lo anterior → reportar solo px.
    cm_per_unit = 0.0
    if conservadas:
        xs = [c["bbox"][0] for c in conservadas]
        ys = [c["bbox"][1] for c in conservadas]
        xe = [c["bbox"][0] + c["bbox"][2] for c in conservadas]
        ye = [c["bbox"][1] + c["bbox"][3] for c in conservadas]
        bbox_x = min(xs)
        bbox_y = min(ys)
        bbox_w = max(xe) - bbox_x
        bbox_h = max(ye) - bbox_y

        if altura_cm > 0 and bbox_h > 0:
            cm_per_unit = altura_cm / bbox_h
            origen_escala = "altura-cm explícita"
        elif ancho_cm > 0 and bbox_w > 0:
            cm_per_unit = ancho_cm / bbox_w
            origen_escala = "ancho-cm explícito"
        elif data.artboard_w_cm > 0 and vb_w > 0:
            cm_per_unit = data.artboard_w_cm / vb_w
            origen_escala = f"unidad real del archivo ({data.svg_unit})"
        else:
            origen_escala = "ninguna (solo px disponibles)"
    else:
        bbox_x = bbox_y = bbox_w = bbox_h = 0.0
        origen_escala = "sin piezas conservadas"

    # ── Fase 4: ordenar por filas (lectura natural) ──────────────────────────
    alturas = [c["bbox"][3] for c in conservadas]
    h_avg = sum(alturas) / len(alturas) if alturas else 0
    row_tol = ROW_TOL_PCT * h_avg

    enriched = []
    for c in conservadas:
        _, y, _, h = c["bbox"]
        enriched.append({**c, "cy": y + h / 2})
    enriched.sort(key=lambda c: c["cy"])
    rows: list[list[dict]] = []
    for c in enriched:
        if rows and abs(c["cy"] - rows[-1][0]["cy"]) <= row_tol:
            rows[-1].append(c)
        else:
            rows.append([c])
    piezas_ordenadas = []
    for row in rows:
        row.sort(key=lambda c: c["bbox"][0])
        piezas_ordenadas.extend(row)

    # ── Fase 5: emitir reporte ───────────────────────────────────────────────
    def _to_cm(v: float) -> float | None:
        return round(v * cm_per_unit, 2) if cm_per_unit > 0 else None

    piezas_out = []
    for i, c in enumerate(piezas_ordenadas, start=1):
        x, y, w, h = c["bbox"]
        piezas_out.append({
            "n": i,
            "bbox_px": {"x": round(x, 2), "y": round(y, 2),
                        "w": round(w, 2), "h": round(h, 2)},
            "ancho_cm": _to_cm(w),
            "alto_cm":  _to_cm(h),
            "perimetro_cm": _to_cm(c["perimetro_px"]),
            "perimetro_px": round(c["perimetro_px"], 2),
            "id_original": c.get("id_original", ""),
        })

    return {
        "svg": str(svg_path),
        "viewbox": {"w": round(vb_w, 2), "h": round(vb_h, 2)},
        "unidad_archivo": data.svg_unit,
        "artboard_cm": round(data.artboard_w_cm, 2) if data.artboard_w_cm else None,
        "origen_escala": origen_escala,
        "cm_por_unidad": round(cm_per_unit, 6) if cm_per_unit else None,
        "bbox_conjunto_px": {"x": round(bbox_x, 2), "y": round(bbox_y, 2),
                              "w": round(bbox_w, 2), "h": round(bbox_h, 2)},
        "ancho_conjunto_cm": _to_cm(bbox_w),
        "alto_conjunto_cm":  _to_cm(bbox_h),
        "piezas_count": len(piezas_out),
        "piezas": piezas_out,
        "descartadas_count": len(descartadas),
        "descartadas": [
            {"motivo": d.get("motivo", ""),
             "bbox": [round(v, 2) for v in d["bbox"]]}
            for d in descartadas
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Detecta piezas fabricables en un SVG (validación del algoritmo).",
    )
    ap.add_argument("svg", help="Ruta al SVG")
    ap.add_argument("--ancho-cm", type=float, default=0.0,
                    help="Forzar ancho real del bbox conjunto (escala el diseño)")
    ap.add_argument("--altura-cm", type=float, default=0.0,
                    help="Forzar altura real del bbox conjunto (prioritaria sobre --ancho-cm)")
    args = ap.parse_args()
    report = analyze(args.svg, ancho_cm=args.ancho_cm, altura_cm=args.altura_cm)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
