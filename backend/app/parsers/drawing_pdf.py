"""構造図PDF（ベクター）パーサー。

部材リスト表（柱断面リスト・大梁リスト・小梁リスト・壁リスト・スラブリスト）から
符号・断面・配筋を抽出して Member に正規化する。
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from ..models import MemberSet, Source
from .base import Parser


class DrawingPdfParser(Parser):
    source = Source.DRAWING

    def parse(self, pdf_path: Path) -> MemberSet:
        # TODO: ベクターPDFから部材リスト表を抽出して Member に変換
        with pdfplumber.open(pdf_path) as pdf:
            for _page in pdf.pages:
                _ = _page.extract_tables()
        return MemberSet(source=self.source, file_name=pdf_path.name, members=[])
