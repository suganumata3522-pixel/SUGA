"""PDFハイライト画像レンダリング。

UI のハイライト表示と全件レポートPDFの両方から利用する。

高速化のポイント:
- bbox 指定時はページ全体ではなく必要領域だけをクリップレンダリングする
  （ページ全体を高解像度で描画してから切り抜くのに比べ大幅に速い）。
- fitz のドキュメントを (path, mtime) 単位でキャッシュして開き直しを避ける。
  fitz は同一ドキュメントへの並行アクセスに弱いため、レンダリングは
  ロックで直列化する（クリップ描画は1回あたり数十msなので実用上問題ない）。
- 枠（橙/赤）はPDFページへ描き込まず、レンダリング後の画像に描く
  （キャッシュしたドキュメントを汚さないため）。
"""
from __future__ import annotations

import io
import os
import threading
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from fastapi import HTTPException

_ORANGE = (255, 128, 0)      # 部材全体枠
_RED = (217, 26, 26)         # 差分箇所枠

_render_lock = threading.Lock()
_doc_cache: dict[tuple[str, float], fitz.Document] = {}
_DOC_MAX = 4

# 生成済みハイライトPNGのLRUキャッシュ。
# レンダリングは入力（ファイル・ページ・枠座標・倍率）に対して決定的なので、
# キャッシュヒットは再レンダリングと完全に同一のバイト列を返す。
# 画面のPDF照合の再表示や、レポートの再生成が大幅に速くなる。
_png_cache: dict[tuple, bytes] = {}
_PNG_CACHE_MAX = 256
_png_cache_lock = threading.Lock()


def release_docs(path: str | Path | None = None) -> None:
    """キャッシュ中の fitz ドキュメントを閉じ、関連するPNGキャッシュを捨てる。

    Windows では開いているファイルを削除できないため、アップロードPDFを
    削除（個別削除・すべて消去）する前に必ず呼ぶこと。path=None で全解放。
    """
    p = str(path) if path is not None else None
    with _render_lock:
        for key in list(_doc_cache):
            if p is None or key[0] == p:
                try:
                    _doc_cache.pop(key).close()
                except Exception:
                    _doc_cache.pop(key, None)
    with _png_cache_lock:
        if p is None:
            _png_cache.clear()
        else:
            for k in list(_png_cache):
                if k[0] == p:
                    del _png_cache[k]


def _get_doc(pdf_path: Path) -> fitz.Document:
    key = (str(pdf_path), os.path.getmtime(str(pdf_path)))
    doc = _doc_cache.get(key)
    if doc is None:
        doc = fitz.open(str(pdf_path))
        _doc_cache[key] = doc
        while len(_doc_cache) > _DOC_MAX:
            old_key = next(iter(k for k in _doc_cache if k != key))
            try:
                _doc_cache.pop(old_key).close()
            except Exception:
                pass
    return doc


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
    if bbox is None:
        # 検索語ハイライト等のフォールバック（低頻度）。ページへ描き込むため
        # キャッシュを使わず毎回開く従来方式。
        return _render_search_legacy(pdf_path, page, search=search, zoom=zoom)

    # 決定的な入力に対する結果キャッシュ（同じ枠の再表示・レポート再生成用）
    try:
        _mt = os.path.getmtime(str(pdf_path))
    except OSError:
        _mt = 0.0
    cache_key = (str(pdf_path), _mt, page, tuple(bbox),
                 tuple(tuple(d) for d in (diff_bboxes or ())), zoom, crop)
    with _png_cache_lock:
        hit = _png_cache.pop(cache_key, None)
        if hit is not None:
            _png_cache[cache_key] = hit  # LRU: 末尾へ移動
            return hit

    render_zoom = max(zoom, 3.0) if crop else zoom
    bx0, bx1 = sorted((bbox[0], bbox[2]))
    by0, by1 = sorted((bbox[1], bbox[3]))
    margin_pt = 44.0 / render_zoom  # 旧実装の 44px マージンをページ座標に換算

    with _render_lock:
        doc = _get_doc(pdf_path)
        if page > doc.page_count:
            raise HTTPException(400, f"ページ {page} はPDFの範囲外です (max {doc.page_count})")
        pg = doc.load_page(page - 1)
        if crop:
            clip = fitz.Rect(bx0 - margin_pt, by0 - margin_pt,
                             bx1 + margin_pt, by1 + margin_pt) & pg.rect
        else:
            clip = pg.rect
        if clip.is_empty or clip.width < 1 or clip.height < 1:
            clip = pg.rect
        pix = pg.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom),
                            clip=clip, alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    draw = ImageDraw.Draw(im)

    def _rect_px(r: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x0, x1 = sorted((r[0], r[2]))
        y0, y1 = sorted((r[1], r[3]))
        return ((x0 - clip.x0) * render_zoom, (y0 - clip.y0) * render_zoom,
                (x1 - clip.x0) * render_zoom, (y1 - clip.y0) * render_zoom)

    draw.rectangle(_rect_px((bx0, by0, bx1, by1)), outline=_ORANGE, width=2)
    for db in diff_bboxes or ():
        draw.rectangle(_rect_px(db), outline=_RED, width=2)

    # 図面/計算書は実質白黒の線画＋橙/赤枠なので、適応パレット64色に
    # 量子化するとファイルサイズが約1/3になる（見た目の劣化はない）。
    # 画面表示のロードとレポートPDFのサイズ・生成時間の双方に効く。
    im = im.quantize(colors=64, method=Image.MEDIANCUT)

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    png = buf.getvalue()
    with _png_cache_lock:
        _png_cache[cache_key] = png
        while len(_png_cache) > _PNG_CACHE_MAX:
            del _png_cache[next(iter(_png_cache))]
    return png


def _render_search_legacy(pdf_path: Path, page: int, *, search: str | None,
                          zoom: float) -> bytes:
    """bbox が無い場合の従来レンダリング（検索語ハイライト・ページ全体）。"""
    doc = fitz.open(pdf_path)
    try:
        if page > doc.page_count:
            raise HTTPException(400, f"ページ {page} はPDFの範囲外です (max {doc.page_count})")
        pg = doc.load_page(page - 1)
        derotate = pg.derotation_matrix
        if search:
            for r in pg.search_for(search):
                rect = fitz.Rect(r.x0 - 10, r.y0 - 4, r.x1 + 80, r.y1 + 4)
                pg.draw_rect(rect * derotate, color=(1, 0.5, 0), width=0.7)
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
