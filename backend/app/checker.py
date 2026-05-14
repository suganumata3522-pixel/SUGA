"""整合チェッカー。

構造図（DRAWING）と計算書（CALC）の MemberSet を突き合わせて差分を返す。
照合は (category, mark, floor) をキーにし、断面・配筋を比較する。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .models import Category, Member, MemberSet


class DiffKind(str, Enum):
    ONLY_IN_DRAWING = "図のみ"
    ONLY_IN_CALC = "計算書のみ"
    SECTION_MISMATCH = "断面不一致"
    REBAR_MISMATCH = "配筋不一致"
    THICKNESS_MISMATCH = "厚さ不一致"
    CONCRETE_MISMATCH = "コンクリート強度不一致"


class FieldDiff(BaseModel):
    field: str
    drawing_value: str | None = None
    calc_value: str | None = None


class Diff(BaseModel):
    kind: DiffKind
    category: Category
    mark: str
    floor: str | None
    fields: list[FieldDiff] = []
    drawing: Member | None = None
    calc: Member | None = None


def _key(m: Member) -> tuple[str, str, str]:
    return (m.category.value, m.mark, m.floor or "")


def _section_diffs(d: Member, c: Member) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    for field in ("b", "D", "thickness"):
        dv = getattr(d.section, field)
        cv = getattr(c.section, field)
        if dv != cv:
            diffs.append(FieldDiff(field=f"section.{field}", drawing_value=str(dv), calc_value=str(cv)))
    return diffs


def _rebar_diffs(d: Member, c: Member) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    for field in ("main", "hoop", "top", "bottom", "horizontal", "vertical"):
        dv = getattr(d.rebar, field)
        cv = getattr(c.rebar, field)
        if (dv or cv) and dv != cv:
            diffs.append(FieldDiff(field=f"rebar.{field}", drawing_value=dv, calc_value=cv))
    return diffs


def compare(drawing: MemberSet, calc: MemberSet) -> list[Diff]:
    d_map = {_key(m): m for m in drawing.members}
    c_map = {_key(m): m for m in calc.members}
    diffs: list[Diff] = []

    for key, d in d_map.items():
        if key not in c_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_DRAWING, category=d.category, mark=d.mark, floor=d.floor, drawing=d))
            continue
        c = c_map[key]
        sec = _section_diffs(d, c)
        rb = _rebar_diffs(d, c)
        if sec:
            kind = DiffKind.THICKNESS_MISMATCH if any(f.field == "section.thickness" for f in sec) else DiffKind.SECTION_MISMATCH
            diffs.append(Diff(kind=kind, category=d.category, mark=d.mark, floor=d.floor, fields=sec, drawing=d, calc=c))
        if rb:
            diffs.append(Diff(kind=DiffKind.REBAR_MISMATCH, category=d.category, mark=d.mark, floor=d.floor, fields=rb, drawing=d, calc=c))
        if d.concrete_grade and c.concrete_grade and d.concrete_grade != c.concrete_grade:
            diffs.append(Diff(
                kind=DiffKind.CONCRETE_MISMATCH, category=d.category, mark=d.mark, floor=d.floor,
                fields=[FieldDiff(field="concrete_grade", drawing_value=d.concrete_grade, calc_value=c.concrete_grade)],
                drawing=d, calc=c,
            ))

    for key, c in c_map.items():
        if key not in d_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_CALC, category=c.category, mark=c.mark, floor=c.floor, calc=c))

    return diffs
