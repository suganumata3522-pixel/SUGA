"""PDFハイライト画像レンダリング。

UI のハイライト表示と全件レポートPDFの両方から利用する。
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from fastapi import HTTPException


def render_highlight_png(
    pdf_path: Path,
    page: int,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    diff_bboxes: list[tuple[float, float, float, float]] | None = None,
    search: str | None = None,
    zoom: float = 2.0,
    crop: bool = True,
) -> bytes:
    """PDFハイライト画像(PNG bytes)を生成する。

    bbox: 部材全体の枠（橙、太め）
    diff_bboxes: 差分箇所の枠（赤、太め）のリスト — bbox 内側の強調表示用。
                 複数フィールドの差分を同じ画像にまとめて表示できる。
    crop=True かつ bbox 指定時は該当箇所の周辺だけを切り出す
    """
    doc = fitz.open(pdf_path)
    try:
        if page > doc.page_count:
            raise HTTPException(400, f"ページ {page} はPDFの範囲外です (max {doc.page_count})")
        pg = doc.load_page(page - 1)
        rects: list[fitz.Rect] = []
        if bbox is not None:
            rects.append(fitz.Rect(*bbox))
        elif search:
            for r in pg.search_for(search):
                rects.append(fitz.Rect(r.x0 - 10, r.y0 - 4, r.x1 + 80, r.y1 + 4))
        derotate = pg.derotation_matrix
        for r in rects:
            pg.draw_rect(r * derotate, color=(1, 0.5, 0), width=1.0)
        for db in diff_bboxes or ():
            pg.draw_rect(fitz.Rect(*db) * derotate, color=(0.85, 0.1, 0.1), width=1.5)

        render_zoom = max(zoom, 3.0) if (crop and bbox is not None) else zoom
        pix = pg.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False)
        png = pix.tobytes("png")

        if crop and bbox is not None:
            im = Image.open(io.BytesIO(png))
            bx0, bx1 = sorted((bbox[0], bbox[2]))
            by0, by1 = sorted((bbox[1], bbox[3]))
            m = 44
            box = (
                max(0, int(bx0 * render_zoom) - m),
                max(0, int(by0 * render_zoom) - m),
                min(im.width, int(bx1 * render_zoom) + m),
                min(im.height, int(by1 * render_zoom) + m),
            )
            buf = io.BytesIO()
            im.crop(box).save(buf, format="PNG")
            png = buf.getvalue()
        return png
    finally:
        doc.close()
