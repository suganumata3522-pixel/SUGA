"""全件まとめPDFレポートの生成。

ハイライト画像（pdf_render.render_highlight_png）と日本語フォント
（assets/fonts/ipag.ttf）を使い、整合チェックの差分を1冊のPDFにする。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from .checker import Diff
from .config import ASSETS_DIR
from .pdf_render import render_highlight_png
from .storage import find_path

FONT_PATH = ASSETS_DIR / "fonts" / "ipag.ttf"
FONT_ALIAS = "jp"

# A4
P_W, P_H = 595.0, 842.0       # portrait
L_W, L_H = 842.0, 595.0       # landscape


def _font_kwargs() -> dict:
    if FONT_PATH.exists():
        return {"fontname": FONT_ALIAS, "fontfile": str(FONT_PATH)}
    return {"fontname": "helv"}  # フォントが無いとき(開発で未配置)の保険


def _T(page: fitz.Page, point: tuple[float, float], text: str,
       *, size: float = 10, color: tuple[float, float, float] = (0, 0, 0)) -> None:
    page.insert_text(point, text, fontsize=size, color=color, **_font_kwargs())


def _Tbox(page: fitz.Page, rect: fitz.Rect, text: str,
          *, size: float = 10, align: int = 0,
          color: tuple[float, float, float] = (0, 0, 0)) -> None:
    page.insert_textbox(rect, text, fontsize=size, align=align, color=color,
                        **_font_kwargs())


def _render_side(diff: Diff, side: str) -> tuple[bytes | None, int | None]:
    """差分の片側(構造図 or 計算書)のハイライト画像と元PDFページ番号を返す。

    主検討（先頭）のみを返す後方互換用。全検討は _render_side_all を使う。
    """
    imgs = _render_side_all(diff, side)
    return imgs[0] if imgs else (None, None)


def _render_side_all(diff: Diff, side: str) -> list[tuple[bytes | None, int | None]]:
    """差分の片側(構造図 or 計算書)の全検討ブロックのハイライト画像リストを返す。

    計算書内に同符号で複数検討がある場合、主検討＋各追加検討(extra_locs)の
    画像を順に返す。各要素は (png, 元PDFページ番号)。
    フィールド差分がある場合は全フィールドの赤枠を主検討画像にまとめる。
    """
    field_locs = []
    for f in diff.fields:
        l = f.drawing_loc if side == "drawing" else f.calc_loc
        if l:
            field_locs.append(l)
    if field_locs:
        primary = next((l for l in field_locs if l.bbox), None)
        if primary is None:
            return []
        diff_bbs = [l.diff_bbox for l in field_locs if l.diff_bbox]
    else:
        primary = diff.drawing_loc if side == "drawing" else diff.calc_loc
        if not primary or not primary.file_id or not primary.bbox:
            return []
        diff_bbs = [primary.diff_bbox] if primary.diff_bbox else []
    if not primary.file_id:
        return []
    out: list[tuple[bytes | None, int | None]] = []
    # 主検討（差分赤枠付き）
    path = find_path(primary.file_id)
    if path is not None:
        try:
            png = render_highlight_png(path, primary.page, bbox=primary.bbox,
                                       diff_bboxes=diff_bbs or None)
            out.append((png, primary.page))
        except Exception:
            out.append((None, primary.page))
    # 追加検討（別ブロック）。不整合の検討には diff_bbox（赤枠）が付く。
    for el in (primary.extra_locs or []):
        if not el.bbox or not el.file_id:
            continue
        p2 = find_path(el.file_id)
        if p2 is None:
            continue
        try:
            png = render_highlight_png(
                p2, el.page, bbox=el.bbox,
                diff_bboxes=[el.diff_bbox] if el.diff_bbox else None)
            out.append((png, el.page))
        except Exception:
            out.append((None, el.page))
    return out


def build_report(
    diffs: list[Diff],
    category: str,
    summary: dict,
    *,
    include_match: bool = False,
) -> bytes:
    """整合チェック結果(1カテゴリ分)を1冊のPDFにまとめる。

    category: "小梁" or "スラブ"
    diffs:    そのカテゴリの差分リスト（呼び出し側でフィルタ済み）
    summary:  表紙に載せる概要 (項目名 -> 値)
    include_match: True なら「一致」もページとして出力する（画面表示準拠）。
    """
    out = fitz.open()
    _add_cover(out, diffs, category, summary)
    targets = [d for d in diffs if include_match or _kind_str(d) != "一致"]
    total = len(targets)
    for index, d in enumerate(targets, start=1):
        _add_diff_page(out, d, category, index, total)
    pdf = out.tobytes()
    out.close()
    return pdf


def _kind_str(d: Diff) -> str:
    """DiffKind enum でも生 str でも安全に表示文字列を返す。"""
    k = d.kind
    return k.value if hasattr(k, "value") else str(k)


def _count_non_match(diffs: list[Diff]) -> int:
    return sum(1 for d in diffs if _kind_str(d) != "一致")


def _add_cover(out: fitz.Document, diffs: list[Diff],
               category: str, summary: dict) -> None:
    page = out.new_page(width=P_W, height=P_H)
    _T(page, (50, 60), f"YHG  整合チェック結果まとめ — {category}", size=22)
    _T(page, (50, 92), f"作成日時: {datetime.now():%Y-%m-%d %H:%M}",
       size=11, color=(0.35, 0.35, 0.35))

    y = 140
    _T(page, (50, y), "■ 概要", size=14); y += 26
    for k, v in summary.items():
        _T(page, (70, y), f"・{k}: {v}", size=11); y += 20

    # 種別の内訳
    counts: dict[str, int] = {}
    for d in diffs:
        k = _kind_str(d)
        counts[k] = counts.get(k, 0) + 1
    if counts:
        y += 16
        _T(page, (50, y), "■ 種別の内訳", size=14); y += 24
        for k, v in counts.items():
            _T(page, (70, y), f"・{k}: {v} 件", size=11); y += 20

    if _count_non_match(diffs) == 0:
        y += 16
        _T(page, (50, y),
           "（対象の不整合はありません。フィルタ条件をご確認ください。）",
           size=11, color=(0.4, 0.4, 0.4))


def _add_diff_page(out: fitz.Document, diff: Diff, category: str,
                   index: int, total: int) -> None:
    """差分1件分のページを追加する。

    計算書内に同符号で複数検討がある場合、計算書側は主検討＋各追加検討を
    それぞれ別ページ（継続ページ）に出力する。構造図側は各ページに同じ図を
    再掲する。1枚に収まらなくても全検討を出力する。
    """
    draw_imgs = _render_side_all(diff, "drawing")
    calc_imgs = _render_side_all(diff, "calc")
    draw0 = draw_imgs[0] if draw_imgs else (None, None)

    # 計算書の検討数（最低1）ぶんのページを出す。
    n_calc = max(1, len(calc_imgs))
    for k in range(n_calc):
        page = out.new_page(width=L_W, height=L_H)
        study_suffix = ""
        if n_calc > 1:
            study_suffix = f"　（計算書 検討 {k + 1}/{n_calc}）"
        # ヘッダ（左：分類・符号・種別／右：件数）
        _T(page, (28, 30),
           f"[{category}] {diff.mark}  ／  {_kind_str(diff)}{study_suffix}", size=15)
        _Tbox(page, fitz.Rect(L_W - 200, 18, L_W - 28, 34),
              f"{index} / {total}", size=10, align=fitz.TEXT_ALIGN_RIGHT,
              color=(0.45, 0.45, 0.45))

        y = 52
        if diff.note:
            _Tbox(page, fitz.Rect(28, y, L_W - 28, y + 28),
                  f"備考: {diff.note}", size=9, color=(0.35, 0.35, 0.35))
            y += 28
        if diff.fields:
            for f in diff.fields:
                line = (f"・{f.field}:  図 = {f.drawing_value or '—'}   "
                        f"／  計算 = {f.calc_value or '—'}")
                _Tbox(page, fitz.Rect(28, y, L_W - 28, y + 14), line, size=9)
                y += 13

        # 2 ペインの画像（左:構造図, 右:計算書 検討k）
        img_top = max(y + 8, 112)
        gap = 18
        pane_w = (L_W - 28 * 2 - gap) / 2
        pane_h = L_H - img_top - 24

        calc_k = calc_imgs[k] if k < len(calc_imgs) else (None, None)
        calc_label = "計算書" if n_calc == 1 else f"計算書（検討 {k + 1}）"
        panels = [("構造図", draw0), (calc_label, calc_k)]
        for i, (label, (png, page_no)) in enumerate(panels):
            x0 = 28 + i * (pane_w + gap)
            full_label = f"{label}　p.{page_no}" if page_no else label
            _T(page, (x0 + 4, img_top + 11), full_label, size=10, color=(0.3, 0.3, 0.3))
            img_rect = fitz.Rect(x0, img_top + 16, x0 + pane_w, img_top + 16 + pane_h)
            page.draw_rect(img_rect, color=(0.82, 0.82, 0.82), width=0.5)
            if png:
                page.insert_image(img_rect, stream=png, keep_proportion=True)
            else:
                _Tbox(page, img_rect, "該当する記載がありません",
                      size=11, align=fitz.TEXT_ALIGN_CENTER, color=(0.55, 0.55, 0.55))
