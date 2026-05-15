"""サンプルPDFに対するゴールデンテスト。

tests/fixtures/<案件名>/{drawing.pdf, calc.pdf} を投入し、
tests/expected_diffs.py の期待値と一致するかを検査する。
パーサ改修時の regression 防止用。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.checker import compare
from app.parsers import DrawingPdfParser, StructureSuitePdfParser

from .expected_diffs import EXPECTED

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("case_name", list(EXPECTED.keys()))
def test_golden_sample(case_name: str) -> None:
    case_dir = FIXTURES / case_name
    drawing_pdf = case_dir / "drawing.pdf"
    calc_pdf = case_dir / "calc.pdf"
    if not drawing_pdf.exists() or not calc_pdf.exists():
        pytest.skip(f"fixture missing: {case_dir}")

    drawing = DrawingPdfParser().parse(drawing_pdf)
    calc = StructureSuitePdfParser().parse(calc_pdf)
    expected = EXPECTED[case_name]

    assert len(drawing.members) == expected["drawing_count"], (
        f"drawing 部材数 mismatch: actual={len(drawing.members)} expected={expected['drawing_count']}"
    )
    assert len(calc.members) == expected["calc_count"], (
        f"calc 部材数 mismatch: actual={len(calc.members)} expected={expected['calc_count']}"
    )

    diffs = compare(drawing, calc)
    actual_keys = {(d.kind.value, d.mark) for d in diffs}
    expected_keys = expected["diff_keys"]
    extra = actual_keys - expected_keys
    missing = expected_keys - actual_keys
    assert not extra and not missing, (
        f"diff keys mismatch for {case_name}\n"
        f"  unexpected (パーサが拾った新差分): {sorted(extra)}\n"
        f"  missing (拾えなくなった差分): {sorted(missing)}"
    )
