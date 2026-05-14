from app.checker import DiffKind, compare
from app.models import Category, Member, MemberSet, Rebar, Section, Source


def _m(cat, mark, floor, source, b=None, D=None, thickness=None, main=None, hoop=None):
    return Member(
        category=cat,
        mark=mark,
        floor=floor,
        section=Section(b=b, D=D, thickness=thickness),
        rebar=Rebar(main=main, hoop=hoop),
        source=source,
    )


def test_section_mismatch_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m(Category.COLUMN, "C1", "2F", Source.DRAWING, b=800, D=800, main="12-D25", hoop="4-D13@100"),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m(Category.COLUMN, "C1", "2F", Source.CALC, b=800, D=900, main="12-D25", hoop="4-D13@100"),
    ])
    diffs = compare(drawing, calc)
    assert any(d.kind == DiffKind.SECTION_MISMATCH for d in diffs)


def test_only_in_drawing_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m(Category.GIRDER, "G99", "RF", Source.DRAWING, b=400, D=700),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[])
    diffs = compare(drawing, calc)
    assert len(diffs) == 1
    assert diffs[0].kind == DiffKind.ONLY_IN_DRAWING


def test_rebar_mismatch_detected():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m(Category.BEAM, "B1", "3F", Source.DRAWING, b=300, D=600, main="4-D22"),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m(Category.BEAM, "B1", "3F", Source.CALC, b=300, D=600, main="5-D22"),
    ])
    diffs = compare(drawing, calc)
    assert any(d.kind == DiffKind.REBAR_MISMATCH for d in diffs)


def test_no_diff_when_identical():
    drawing = MemberSet(source=Source.DRAWING, file_name="d.pdf", members=[
        _m(Category.WALL, "W18", "2F", Source.DRAWING, thickness=180, main="D13@200"),
    ])
    calc = MemberSet(source=Source.CALC, file_name="c.pdf", members=[
        _m(Category.WALL, "W18", "2F", Source.CALC, thickness=180, main="D13@200"),
    ])
    assert compare(drawing, calc) == []
