"""サンプルPDFに対するゴールデンテスト。

tests/fixtures/<案件名>/{drawing.pdf, calc.pdf} を投入し、
tests/expected_diffs.py の期待値と一致するかを検査する。
パーサ改修時の regression 防止用。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.checker import compare, compare_slabs
from app.parsers import DrawingPdfParser, StructureSuitePdfParser, parse_calc_slabs, parse_drawing_slabs

from .expected_diffs import EXPECTED, EXPECTED_SLAB

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
    actual_keys = {(d.kind.value, d.mark) for d in diffs if d.kind.value != "一致"}
    expected_keys = expected["diff_keys"]
    extra = actual_keys - expected_keys
    missing = expected_keys - actual_keys
    assert not extra and not missing, (
        f"diff keys mismatch for {case_name}\n"
        f"  unexpected (パーサが拾った新差分): {sorted(extra)}\n"
        f"  missing (拾えなくなった差分): {sorted(missing)}"
    )


@pytest.mark.parametrize("case_name", list(EXPECTED_SLAB.keys()))
def test_golden_slab_sample(case_name: str) -> None:
    case_dir = FIXTURES / case_name
    drawing_pdf = case_dir / "drawing.pdf"
    calc_pdf = case_dir / "calc.pdf"
    if not drawing_pdf.exists() or not calc_pdf.exists():
        pytest.skip(f"fixture missing: {case_dir}")

    drawing = parse_drawing_slabs(drawing_pdf)
    calc = parse_calc_slabs(calc_pdf)
    expected = EXPECTED_SLAB[case_name]

    assert len(drawing.slabs) == expected["drawing_slab_count"], (
        f"drawing スラブ数 mismatch: actual={len(drawing.slabs)} expected={expected['drawing_slab_count']}"
    )
    assert len(calc.slabs) == expected["calc_slab_count"], (
        f"calc スラブ数 mismatch: actual={len(calc.slabs)} expected={expected['calc_slab_count']}"
    )

    diffs = compare_slabs(drawing, calc)
    actual_keys = {(d.kind.value, d.mark) for d in diffs if d.kind.value != "一致"}
    expected_keys = expected["diff_keys"]
    extra = actual_keys - expected_keys
    missing = expected_keys - actual_keys
    assert not extra and not missing, (
        f"slab diff keys mismatch for {case_name}\n"
        f"  unexpected: {sorted(extra)}\n"
        f"  missing: {sorted(missing)}"
    )
