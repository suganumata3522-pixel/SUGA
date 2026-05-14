"""計算書PDFパーサー（SS7 / SS3 / StructureSuite）。

現状はベクターPDFからの pdfplumber テキスト抽出で実装する想定。
実装は Phase 1 で部材リスト（柱・大梁）から着手し、徐々に小梁・壁・スラブを増やす。
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from ..models import MemberSet, Source
from .base import Parser


class _PdfCalcParserBase(Parser):
    source = Source.CALC

    def _extract_text_per_page(self, pdf_path: Path) -> list[str]:
        pages: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return pages


class SSCalcPdfParser(_PdfCalcParserBase):
    """ユニオンシステム SS7 / SS3 計算書PDF用パーサー。"""

    def parse(self, pdf_path: Path) -> MemberSet:
        # TODO: SS7/SS3 の出力PDFレイアウトに合わせた表抽出を実装
        _ = self._extract_text_per_page(pdf_path)
        return MemberSet(source=self.source, file_name=pdf_path.name, members=[])


class StructureSuitePdfParser(_PdfCalcParserBase):
    """StructureSuite 計算書PDF用パーサー。"""

    def parse(self, pdf_path: Path) -> MemberSet:
        # TODO: StructureSuite の出力PDFレイアウトに合わせた表抽出を実装
        _ = self._extract_text_per_page(pdf_path)
        return MemberSet(source=self.source, file_name=pdf_path.name, members=[])
