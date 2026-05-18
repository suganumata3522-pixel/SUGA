from app.checker import DiffKind, compare
from app.models import BeamMember, MemberSet, PositionRebar, Section, Source


def _m(mark, source, B=None, D=None, positions=None):
    return BeamMember(
        mark=mark,
        section=Section(B=B, D=D),
        positions=positions or [],
        source=source,
    )


def test_section_B_mismatch_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m("B1", Source.DRAWING, B=300, positions=[
            PositionRebar(location="全断面", top="4-D22", bottom="4-D22", stirrup="2-D10@150", web="2-D10"),
        ]),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m("B1", Source.CALC, B=400, D=700, positions=[
            PositionRebar(location="SX1端", top="4-D22", bottom="4-D22", stirrup="2-D10@150"),
        ]),
    ])
    diffs = compare(drawing, calc)
    assert any(d.kind == DiffKind.SECTION_B_MISMATCH for d in diffs)


def test_only_in_drawing_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m("B99", Source.DRAWING, B=300),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[])
    diffs = compare(drawing, calc)
    assert len(diffs) == 1
    assert diffs[0].kind == DiffKind.ONLY_IN_DRAWING


def test_rebar_mismatch_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m("B1", Source.DRAWING, B=400, positions=[
            PositionRebar(location="全断面", top="4-D22", bottom="4-D22"),
        ]),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m("B1", Source.CALC, B=400, D=700, positions=[
            PositionRebar(location="SX1端", top="5-D22", bottom="4-D22"),
        ]),
    ])
    diffs = compare(drawing, calc)
    assert any(d.kind == DiffKind.REBAR_MISMATCH for d in diffs)


def test_no_diff_when_identical_rebar_set():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m("B1A", Source.DRAWING, B=400, positions=[
            PositionRebar(location="全断面", top="4-D22", bottom="4-D22", stirrup="2-D10@150"),
            PositionRebar(location="SX2端", top="4/2-D22", bottom="4-D22", stirrup="2-D10@150"),
        ]),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m("B1A", Source.CALC, B=400, D=700, positions=[
            PositionRebar(location="SX1端", top="4-D22", bottom="4-D22", stirrup="2-D10@150"),
            PositionRebar(location="中央", top="4-D22", bottom="4-D22", stirrup="2-D10@150"),
            PositionRebar(location="SX2端", top="4/2-D22", bottom="4-D22", stirrup="2-D10@150"),
        ]),
    ])
    # B が同じ・配筋集合が同じなら不整合なし → 「一致」が1件出る
    diffs = compare(drawing, calc)
    assert len(diffs) == 1
    assert diffs[0].kind == DiffKind.MATCH
    assert diffs[0].mark == "B1A"
