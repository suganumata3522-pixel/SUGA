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

import re

from .models import BeamMember, MemberSet, SlabMember, SlabSet


class DiffKind(str, Enum):
    ONLY_IN_DRAWING = "図のみ"
    ONLY_IN_CALC = "計算書のみ"
    SECTION_B_MISMATCH = "断面幅B不一致"
    REBAR_MISMATCH = "配筋不一致"
    NEEDS_REVIEW = "要目視確認"
    SLAB_THICKNESS_MISMATCH = "スラブ厚不一致"
    SLAB_REBAR_MISMATCH = "スラブ配筋不一致"


class Locator(BaseModel):
    """元PDF内の位置情報。UI側がハイライトAPIに渡す。"""
    page: int
    bbox: tuple[float, float, float, float] | None = None
    search: str | None = None  # bbox が無い時に使う検索語（通常は符号）


class FieldDiff(BaseModel):
    field: str
    drawing_value: str | None = None
    calc_value: str | None = None
    drawing_loc: Locator | None = None  # フィールド単位のハイライト
    calc_loc: Locator | None = None


class Diff(BaseModel):
    kind: DiffKind
    mark: str
    fields: list[FieldDiff] = []
    note: str | None = None  # 計算書側の備考（例: "1F 駐輪場・ENT"）など補助情報
    drawing_loc: Locator | None = None  # メンバ全体（"図のみ" 等）のハイライト
    calc_loc: Locator | None = None


def _aggregate_rebar(m: BeamMember, attr: str) -> set[str]:
    """同符号の全位置から指定の配筋値を集合化（順序非依存比較用）。"""
    out: set[str] = set()
    for p in m.positions:
        v = getattr(p, attr)
        if v:
            out.add(v.replace(" ", ""))
    return out


def _drawing_loc(d: BeamMember | None) -> Locator | None:
    if d is None or d.location is None:
        return None
    return Locator(page=d.location.page, bbox=d.location.bbox, search=d.mark)


def _calc_loc(c: BeamMember | None) -> Locator | None:
    if c is None or c.location is None:
        return None
    return Locator(page=c.location.page, bbox=c.location.bbox, search=c.mark)


def _field_loc(m: BeamMember | None, key: str) -> Locator | None:
    """フィールド単位の bbox。なければメンバ全体に fallback。"""
    if m is None or m.location is None:
        return None
    bbox = m.field_bboxes.get(key)
    if bbox is None:
        return Locator(page=m.location.page, bbox=m.location.bbox, search=m.mark)
    return Locator(page=m.location.page, bbox=bbox, search=m.mark)


def compare(drawing: MemberSet, calc: MemberSet) -> list[Diff]:
    d_map = {m.mark: m for m in drawing.members}
    c_map = {m.mark: m for m in calc.members}
    diffs: list[Diff] = []

    for mark, d in d_map.items():
        if mark not in c_map:
            diffs.append(Diff(
                kind=DiffKind.ONLY_IN_DRAWING, mark=mark, note=d.note,
                drawing_loc=_drawing_loc(d),
            ))
            continue
        c = c_map[mark]
        # B 比較（両方に値がある場合のみ）
        if d.section.B is not None and c.section.B is not None and d.section.B != c.section.B:
            diffs.append(Diff(
                kind=DiffKind.SECTION_B_MISMATCH, mark=mark, note=c.note,
                fields=[FieldDiff(
                    field="B", drawing_value=str(d.section.B), calc_value=str(c.section.B),
                    drawing_loc=_field_loc(d, "B"), calc_loc=_field_loc(c, "B"),
                )],
                drawing_loc=_drawing_loc(d), calc_loc=_calc_loc(c),
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
                    drawing_loc=_field_loc(d, attr),
                    calc_loc=_field_loc(c, attr),
                ))
        # 構造図側の抽出が不完全だと分かっている場合は「要目視確認」として出す
        # （配筋不一致と紛らわしい false positive を避ける）
        if d.needs_review:
            note_text = c.note or ""
            if d.review_note:
                note_text = f"{note_text} | {d.review_note}".strip(" |")
            diffs.append(Diff(
                kind=DiffKind.NEEDS_REVIEW, mark=mark, fields=rebar_fields,
                note=note_text,
                drawing_loc=_drawing_loc(d), calc_loc=_calc_loc(c),
            ))
        elif rebar_fields:
            diffs.append(Diff(
                kind=DiffKind.REBAR_MISMATCH, mark=mark, fields=rebar_fields, note=c.note,
                drawing_loc=_drawing_loc(d), calc_loc=_calc_loc(c),
            ))

    for mark, c in c_map.items():
        if mark not in d_map:
            diffs.append(Diff(
                kind=DiffKind.ONLY_IN_CALC, mark=mark, note=c.note,
                calc_loc=_calc_loc(c),
            ))

    return diffs


# ---------------------------------------------------------------------------
# スラブの整合チェック
# ---------------------------------------------------------------------------
def _slab_loc(s: SlabMember | None, key: str | None = None) -> Locator | None:
    if s is None or s.location is None:
        return None
    bbox = s.field_bboxes.get(key) if key else s.location.bbox
    return Locator(page=s.location.page, bbox=bbox or s.location.bbox, search=s.mark)


def _thickness_range(raw: str | None, fallback: int | None) -> tuple[int, int] | None:
    """スラブ厚表記から (min, max) を返す。"260〜260"->(260,260), "315〜285"->(285,315)。"""
    if raw:
        nums = [int(n) for n in re.findall(r"\d+", raw)]
        if nums:
            return (min(nums), max(nums))
    if fallback is not None:
        return (fallback, fallback)
    return None


def compare_slabs(drawing: SlabSet, calc: SlabSet) -> list[Diff]:
    """スラブの整合チェック。

    - スラブ厚: 構造図がテーパー範囲 (例 315〜285) の場合、計算書値が範囲内なら一致とみなす
    - 配筋: 構造図2値(主筋/配力筋方向) vs 計算書4値(端部/中央×短辺/長辺) で粒度が
      異なるため、順不同の集合として比較する
    """
    d_map = {s.mark: s for s in drawing.slabs}
    c_map = {s.mark: s for s in calc.slabs}
    diffs: list[Diff] = []

    for mark, d in d_map.items():
        if mark not in c_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_DRAWING, mark=mark, drawing_loc=_slab_loc(d)))
            continue
        c = c_map[mark]

        # スラブ厚
        d_rng = _thickness_range(d.thickness_raw, d.thickness)
        if d_rng and c.thickness is not None:
            lo, hi = d_rng
            if not (lo <= c.thickness <= hi):
                d_disp = d.thickness_raw or str(d.thickness)
                diffs.append(Diff(
                    kind=DiffKind.SLAB_THICKNESS_MISMATCH, mark=mark,
                    fields=[FieldDiff(
                        field="スラブ厚", drawing_value=d_disp, calc_value=f"{c.thickness}",
                        drawing_loc=_slab_loc(d, "thickness"), calc_loc=_slab_loc(c),
                    )],
                    drawing_loc=_slab_loc(d), calc_loc=_slab_loc(c),
                ))

        # 配筋（集合比較）
        rebar_fields: list[FieldDiff] = []
        for attr, label, key in [("top_rebar", "上端筋", "top"), ("bottom_rebar", "下端筋", "bottom")]:
            ds = {v.replace(" ", "") for v in getattr(d, attr)}
            cs = {v.replace(" ", "") for v in getattr(c, attr)}
            if ds and cs and ds != cs:
                rebar_fields.append(FieldDiff(
                    field=label,
                    drawing_value=" / ".join(sorted(ds)),
                    calc_value=" / ".join(sorted(cs)),
                    drawing_loc=_slab_loc(d, key),
                    calc_loc=_slab_loc(c),
                ))
        if rebar_fields:
            diffs.append(Diff(
                kind=DiffKind.SLAB_REBAR_MISMATCH, mark=mark, fields=rebar_fields,
                drawing_loc=_slab_loc(d), calc_loc=_slab_loc(c),
            ))

    for mark, c in c_map.items():
        if mark not in d_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_CALC, mark=mark, calc_loc=_slab_loc(c)))

    return diffs
