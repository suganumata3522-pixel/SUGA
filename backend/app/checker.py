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
    ONLY_IN_DRAWING = "構造図のみ"
    ONLY_IN_CALC = "計算書のみ"
    SECTION_B_MISMATCH = "断面幅不一致"
    REBAR_MISMATCH = "配筋不一致"
    NEEDS_REVIEW = "要目視確認"
    SLAB_THICKNESS_MISMATCH = "スラブ厚不一致"
    SLAB_REBAR_MISMATCH = "スラブ配筋不一致"
    MATCH = "一致"


class Locator(BaseModel):
    """元PDF内の位置情報。UI側がハイライトAPIに渡す。"""
    page: int
    bbox: tuple[float, float, float, float] | None = None
    search: str | None = None  # bbox が無い時に使う検索語（通常は符号）
    file_id: str | None = None  # どのアップロードPDFか


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
    drawing_loc: Locator | None = None  # メンバ全体（"構造図のみ" 等）のハイライト
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
    return Locator(page=d.location.page, bbox=d.location.bbox, search=d.mark,
                   file_id=d.location.file_id)


def _calc_loc(c: BeamMember | None) -> Locator | None:
    if c is None or c.location is None:
        return None
    return Locator(page=c.location.page, bbox=c.location.bbox, search=c.mark,
                   file_id=c.location.file_id)


def _field_loc(m: BeamMember | None, key: str) -> Locator | None:
    """フィールド単位の bbox。なければメンバ全体に fallback。"""
    if m is None or m.location is None:
        return None
    bbox = m.field_bboxes.get(key) or m.location.bbox
    return Locator(page=m.location.page, bbox=bbox, search=m.mark,
                   file_id=m.location.file_id)


# 通り芯参照（X1 / Y2 等）の検出パターン。
_GRID_REF_RE = re.compile(r"[XYＸＹ][0-9０-９]")


def _is_continuous_beam(m: BeamMember | None) -> bool:
    """連梁（B3A 等）かどうか。

    B3A は位置ラベルが「X1,X3,X5,X8,X9,X11端」のように複数の通り芯を
    列挙し、左端/中央/右端で配筋が異なる。どの通り芯かで結果が変わり
    自動照合が難しいため「要目視確認」とする。
    判定: 位置ラベルが「連続」を含む、または通り芯参照を複数列挙
    （カンマ区切り）している。「SX2端」のような単一通り芯端は対象外。
    """
    if m is None:
        return False
    for p in m.positions:
        loc = p.location or ""
        if "連続" in loc:
            return True
        if _GRID_REF_RE.search(loc) and ("," in loc or "、" in loc):
            return True
    return False


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
        before = len(diffs)
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
        # 次のいずれかは「要目視確認」として出す（配筋不一致と紛らわしい
        # false positive を避ける）:
        #  ・構造図側の抽出が不完全だと分かっている場合
        #  ・連梁（通り芯ごとに配筋が異なり自動照合が難しい）の場合
        # 計算書側は全小梁を通り芯ごとの位置で持つため判定に使えない。
        # 構造図の位置ラベルが通り芯で枝分かれしているかで連梁を判定する。
        continuous = _is_continuous_beam(d)
        if d.needs_review or continuous:
            parts = [c.note or ""]
            if d.review_note:
                parts.append(d.review_note)
            if continuous:
                parts.append("連梁（通り芯により配筋が異なる）のため目視確認が必要")
            note_text = " | ".join(p for p in parts if p)
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
        # 不整合が1件も出なければ「一致」
        if len(diffs) == before:
            diffs.append(Diff(
                kind=DiffKind.MATCH, mark=mark, note=c.note,
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
    bbox = (s.field_bboxes.get(key) if key else s.location.bbox) or s.location.bbox
    return Locator(page=s.location.page, bbox=bbox, search=s.mark,
                   file_id=s.location.file_id)


def _ordered_unique(vals: list[str]) -> list[str]:
    """空白を除去しつつ、出現順を保って重複を除いたリストを返す。"""
    out: list[str] = []
    for v in vals:
        vv = v.replace(" ", "")
        if vv and vv not in out:
            out.append(vv)
    return out


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
        before = len(diffs)

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
                        drawing_loc=_slab_loc(d, "thickness"), calc_loc=_slab_loc(c, "thickness"),
                    )],
                    drawing_loc=_slab_loc(d), calc_loc=_slab_loc(c),
                ))

        # 配筋（集合で一致判定、表示は計算書/構造図の出現順を保つ）
        rebar_fields: list[FieldDiff] = []
        for attr, label, key in [("top_rebar", "上端筋", "top"), ("bottom_rebar", "下端筋", "bottom")]:
            d_list = _ordered_unique(getattr(d, attr))
            c_list = _ordered_unique(getattr(c, attr))
            ds, cs = set(d_list), set(c_list)
            if ds and cs and ds != cs:
                rebar_fields.append(FieldDiff(
                    field=label,
                    drawing_value=" / ".join(d_list),
                    calc_value=" / ".join(c_list),
                    drawing_loc=_slab_loc(d, key),
                    calc_loc=_slab_loc(c, key),
                ))
        if rebar_fields:
            diffs.append(Diff(
                kind=DiffKind.SLAB_REBAR_MISMATCH, mark=mark, fields=rebar_fields,
                drawing_loc=_slab_loc(d), calc_loc=_slab_loc(c),
            ))
        # 不整合が1件も出なければ「一致」
        if len(diffs) == before:
            diffs.append(Diff(
                kind=DiffKind.MATCH, mark=mark,
                drawing_loc=_slab_loc(d), calc_loc=_slab_loc(c),
            ))

    for mark, c in c_map.items():
        if mark not in d_map:
            diffs.append(Diff(kind=DiffKind.ONLY_IN_CALC, mark=mark, calc_loc=_slab_loc(c)))

    return diffs
