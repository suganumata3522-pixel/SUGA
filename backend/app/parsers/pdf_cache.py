"""PDFテキスト抽出のキャッシュ。

整合チェック1回につき、計算書PDFは「小梁用」と「スラブ用」で 2 回、
構造図PDFも同様に 2 回パースされる。pdfplumber の extract_text /
extract_words はページ数が多いと重いため、ファイル単位で抽出結果を
キャッシュして再利用する。
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
            pages.append(PageData(
                index=i,
                text=page.extract_text() or "",
                words=page.extract_words(keep_blank_chars=False),
                width=float(page.width),
                height=float(page.height),
            ))

    _cache[key] = pages
    while len(_cache) > _MAX_ENTRIES:
        oldest = next(iter(_cache))
        del _cache[oldest]
    return pages
