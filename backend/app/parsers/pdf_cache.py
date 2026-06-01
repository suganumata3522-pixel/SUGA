"""PDFテキスト抽出のキャッシュ。

整合チェック1回につき、計算書PDFは「小梁用」と「スラブ用」で 2 回、
構造図PDFも同様に 2 回パースされる。pdfplumber の extract_text /
extract_words はページ数が多いと重いため、ファイル単位で抽出結果を
キャッシュして再利用する。

また一部の PDF はフォント/CID 設定が壊れており、表示は正しい漢字
（例: 符号）に見えても、抽出した Unicode が中国簡体字や Kangxi
部首コードポイント（例: 绍号、主筋⽅向）になっていることがある。
パーサーが「符号」等の文字列で行を識別できなくなるため、抽出した
text/word に対して既知の誤コードポイントを正しい字へ置換する。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass
class PageData:
    index: int                 # 1始まりのページ番号
    text: str                  # extract_text() の結果
    words: list[dict]          # extract_words(keep_blank_chars=False) の結果
    width: float
    height: float


# PDF CID マッピング不具合で出る誤コードポイントを正しい字へ戻す。
# 構造図/計算書では出てこない簡体字や Kangxi 部首だけを集めているので、
# 一般文書の漢字を壊す心配は無い。
_CID_FIX_TABLE = {
    # 簡体字/異体字グリフ → 正しい日本語の字
    "绍": "符",  # 绍号 → 符号
    "敋": "巾",  # 敋止筋 → 巾止筋
    "縌": "械",  # 機縌式 → 機械式
    "拙": "補",  # 拙強筋 → 補強筋
    "戄": "着",  # 定戄 → 定着
    "戼": "影",  # 水平投戼 → 水平投影
    "抛": "図",  # 雑詳細抛 → 雑詳細図
    "拘": "限",  # 特記なき拘り → 特記なき限り
    "戯": "領",  # 要戯 → 要領
    "拓": "線",  # 直拓 → 直線
    "扪": "越",  # 扪える → 越える
    "抖": "厚",  # 壁抖 → 壁厚
    "纾": "又",  # NS纾 → NS又
    "纮": "径",  # 主筋纮 → 主筋径
    "技": "段",  # 一技筋 → 一段筋
    "括": "配",  # 括⼒筋 → 配力筋 (FCGの括筋 → FCGの配筋)
    # Kangxi 部首ブロックの記号（U+2F00 台）→ 通常の CJK 統合漢字
    "⽅": "方",  # 主筋⽅向 → 主筋方向
    "⼒": "力",  # 配⼒筋 → 配力筋
    "⼆": "二",
    "⼀": "一",
    "⽔": "水",  # ⽔平 → 水平
    "⼩": "小",  # ⼩梁 → 小梁
    "⼤": "大",  # ⼤梁 → 大梁
    "⽚": "片",  # ⽚持 → 片持
    "⽌": "止",  # 巾⽌筋 → 巾止筋
    "⽇": "日",
    "⼟": "土",
    "⼯": "工",
    "⼨": "寸",
    "⾯": "面",  # 全断⾯ → 全断面
    "⾼": "高",
    "⻑": "長",  # ⻑期 → 長期
    "⾞": "車",  # ⾞庫 → 車庫
}

_CID_FIX_TRANS = str.maketrans(_CID_FIX_TABLE)


def normalize_pdf_text(s: str) -> str:
    """PDF抽出のテキストから既知の誤コードポイントを正しい字へ戻す。"""
    if not s:
        return s
    return s.translate(_CID_FIX_TRANS)


def _fix_reversed_digits(text: str) -> str:
    """縦書きで描画された多桁数字が逆順に抽出されるケースを補正する。

    一部の構造図PDF（dimension lineの数字を縦に1文字ずつ配置するもの）では、
    pdfplumber の extract_words が上から下に文字を連結するため
    "1050" が "0501"、"2000" が "0002" のように先頭ゼロ付きで取れる。

    工学的な数値はゼロ始まりにならない（"0" 単体を除く）ので、
    純数字のみで長さ2以上かつ先頭が "0" の語を逆順に直す。
    """
    if not text or not text.isdigit() or len(text) < 2 or text[0] != "0":
        return text
    reversed_text = text[::-1]
    # 逆順した結果が "0" 始まりにならないことを確認（"00..." のような場合は触らない）
    if reversed_text[0] == "0":
        return text
    return reversed_text


def _extract_annot_words(page, page_height: float) -> list[dict]:
    """PDFの注釈（コメント）から擬似的な単語リストを生成する。

    AutoCAD で `PDFSHX = 1` 設定で PDF 出力すると、SHX 文字が
    実テキストではなく Text 注釈（コメント）として埋め込まれる。
    pdfplumber の標準 extract_words はこれを拾わないので、
    `page.annots` から内容を取り出して単語として補完する。

    AutoCAD 2021 以前は SHX 文字を実テキスト化できず PDFSHX=1 が
    最大設定なので、この補完で構造図の符号・配筋値を抽出できる
    ようになる。
    """
    out: list[dict] = []
    try:
        annots = page.annots or []
    except Exception:
        return out
    for annot in annots:
        try:
            contents = annot.get("contents") or ""
        except Exception:
            continue
        if not contents or not isinstance(contents, str):
            continue
        # rect は [x0, y0_bot, x1, y1_top]（PDF座標、原点は左下）。
        # pdfplumber のwordは原点が左上なので y を反転する。
        try:
            x0, y0_bot, x1, y1_top = annot.get("x0"), annot.get("y0"), annot.get("x1"), annot.get("y1")
            if any(v is None for v in (x0, y0_bot, x1, y1_top)):
                rect = annot.get("rect") or [0, 0, 0, 0]
                x0, y0_bot, x1, y1_top = rect
            top = page_height - float(y1_top)
            bottom = page_height - float(y0_bot)
        except Exception:
            continue
        # 注釈の本文は複数語を含むことがあるので空白で分割
        for token in contents.split():
            out.append({
                "text": token,
                "x0": float(x0),
                "x1": float(x1),
                "top": top,
                "bottom": bottom,
            })
    return out


# 直近 N ファイル分のみ保持する簡易 LRU（メモリ肥大化を防ぐ）
_MAX_ENTRIES = 6
_cache: dict[tuple[str, float], list[PageData]] = {}


def get_pages(pdf_path: Path | str) -> list[PageData]:
    """PDFの全ページの抽出結果を返す。同一ファイルなら 2 回目以降はキャッシュを返す。"""
    path = str(pdf_path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime)

    cached = _cache.get(key)
    if cached is not None:
        return cached

    pages: list[PageData] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text() or ""
            raw_words = page.extract_words(keep_blank_chars=False)
            # CID不具合の正規化＋縦書き数字の逆順補正を適用
            for w in raw_words:
                w["text"] = _fix_reversed_digits(normalize_pdf_text(w["text"]))
            # AutoCAD PDFSHX=1 で埋め込まれたコメント注釈も単語として取り込む
            page_height = float(page.height)
            annot_words = _extract_annot_words(page, page_height)
            for w in annot_words:
                w["text"] = _fix_reversed_digits(normalize_pdf_text(w["text"]))
            if annot_words:
                raw_words = raw_words + annot_words
                # 注釈テキストも extract_text 相当に追記
                annot_text = "\n".join(w["text"] for w in annot_words)
                raw_text = (raw_text + "\n" + annot_text) if raw_text else annot_text
            pages.append(PageData(
                index=i,
                text=normalize_pdf_text(raw_text),
                words=raw_words,
                width=float(page.width),
                height=page_height,
            ))

    _cache[key] = pages
    while len(_cache) > _MAX_ENTRIES:
        oldest = next(iter(_cache))
        del _cache[oldest]
    return pages



