"""整合チェッカー（RC小梁向け）。

構造図（DRAWING）と計算書（CALC）の MemberSet を符号単位で突き合わせる。
- 構造図側に存在しない / 計算書側に存在しない
- 断面 B の不一致 (D は構造図側に数値テキストが無いため対象外)
- 配筋（上端・下端・STP・腹筋）の不一致
- コンクリート強度の不一致（計算書側のみ取得できる）
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .models import BeamMember, MemberSet


class DiffKind(str, Enum):
    ONLY_IN_DRAWING = "図のみ"
    ONLY_IN_CALC = "計算書のみ"
    SECTION_B_MISMATCH = "断面幅B不一致"
    REBAR_MISMATCH = "配筋不一致"


class FieldDiff(BaseModel):
    field: str
    drawing_value: str | None = None
    calc_value: str | None = None


class Diff(BaseModel):
    kind: DiffKind
    mark: str
    fields: list[FieldDiff] = []
    note: str | None = None  # 計算書側の備考（例: "1F 駐輪場・ENT"）など補助情報


def _aggregate_rebar(m: BeamMember, attr: str) -> set[str]:
    """同符号の全位置から指定の配筋値を集合化（順序非依存比較用）。"""
    out: set[str] = set()
    for p in m.positions:
        v = getattr(p, attr)
        if v:
            out.add(v.replace(" ", ""))
    return out


def compare(drawing: MemberSet, calc: MemberSet) -> list[Diff]:
    d_map = {m.mark: m for m in drawing.members}
    c_map = {m.mark: m for m in calc.members}
    diffs: list[Diff] = []

    for mark, d in d_map.items():
        if mark not in c_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_DRAWING, mark=mark, note=d.note))
            continue
        c = c_map[mark]
        # B 比較（両方に値がある場合のみ）
        if d.section.B is not None and c.section.B is not None and d.section.B != c.section.B:
            diffs.append(Diff(
                kind=DiffKind.SECTION_B_MISMATCH, mark=mark, note=c.note,
                fields=[FieldDiff(field="B", drawing_value=str(d.section.B), calc_value=str(c.section.B))],
            ))
        # 配筋比較
        rebar_fields: list[FieldDiff] = []
        for attr, label in [("top", "上端筋"), ("bottom", "下端筋"), ("stirrup", "STP"), ("web", "腹筋")]:
            ds = _aggregate_rebar(d, attr)
            cs = _aggregate_rebar(c, attr)
            if ds and cs and ds != cs:
                rebar_fields.append(FieldDiff(
                    field=label,
                    drawing_value=" / ".join(sorted(ds)),
                    calc_value=" / ".join(sorted(cs)),
                ))
        if rebar_fields:
            diffs.append(Diff(kind=DiffKind.REBAR_MISMATCH, mark=mark, fields=rebar_fields, note=c.note))

    for mark, c in c_map.items():
        if mark not in d_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_CALC, mark=mark, note=c.note))

    return diffs
