"""RCスラブのパーサー。

- 構造図: スラブリスト表（符号が縦に並ぶ）。各符号は スラブ厚 と
  上端筋/下端筋（主筋方向・配力筋方向の2値）を持つ。
- 計算書(StructureSuite): "No.X_<符号>(...)" ブロック。t と
  上端筋/下端筋（短辺端部・短辺中央・長辺端部・長辺中央の4値）と Fc を持つ。

方向の対応（主筋方向=短辺方向 / 配力筋方向=長辺方向）が崩れやすく、
構造図2値 vs 計算書4値で粒度も異なるため、配筋は順不同の集合として扱う。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import LocationHint, SlabMember, SlabSet, Source
from .pdf_cache import get_pages

# スラブ符号: S18 / S25A / CS26 / CS315 など
_SLAB_MARK_RE = re.compile(r"^C?S\d+[A-Z]?$")
# 配筋トークン: D10@200 / D10D13@200 / D16@100 など
_SLAB_REBAR_RE = re.compile(r"(?:D\d+)+@\d+")
_THICK_RANGE_RE = re.compile(r"(\d+)")


def _parse_thickness(raw: str) -> tuple[int | None, str]:
    """スラブ厚表記をパース。"180" -> (180,"180"), "260〜260" -> (260,...), "210〜180" -> (210,...)。
    代表値は最大値（critical section 寄り）を採る。
    """
    nums = [int(n) for n in _THICK_RANGE_RE.findall(raw)]
    if not nums:
        return None, raw
    return max(nums), raw


# ---------------------------------------------------------------------------
# 構造図スラブリスト
# ---------------------------------------------------------------------------
def parse_drawing_slabs(pdf_path: Path) -> SlabSet:
    slabs: list[SlabMember] = []
    for pd in get_pages(pdf_path):
        slabs.extend(_parse_drawing_page(pd.words, pd.index))
    return SlabSet(source=Source.DRAWING, file_name=pdf_path.name, slabs=slabs)


def _parse_drawing_page(words: list[dict], page_idx: int) -> list[SlabMember]:
    # スラブ符号を符号列（左端 x<110）で検出
    mark_words = [
        w for w in words
        if _SLAB_MARK_RE.match(w["text"]) and float(w["x0"]) < 110
    ]
    if not mark_words:
        return []
    mark_words.sort(key=lambda w: float(w["top"]))

    # 上端筋/下端筋ラベルの位置（x≈162）
    label_words = [w for w in words if w["text"] in {"上端筋", "下端筋"} and 150 <= float(w["x0"]) <= 180]

    out: list[SlabMember] = []
    for mw in mark_words:
        my = float(mw["top"])
        # この符号バンドの 上端筋/下端筋 ラベル（my ± 8）
        band_labels = [lw for lw in label_words if abs(float(lw["top"]) - my) <= 9]
        top_y = next((float(lw["top"]) for lw in band_labels if lw["text"] == "上端筋"), None)
        bot_y = next((float(lw["top"]) for lw in band_labels if lw["text"] == "下端筋"), None)

        # スラブ厚（x 105〜150、my±4）
        thick_raw = None
        for w in words:
            if 103 <= float(w["x0"]) <= 152 and abs(float(w["top"]) - my) <= 4:
                if re.match(r"^[\d〜～\-]+$", w["text"]):
                    thick_raw = w["text"]
                    break
        thickness, thick_disp = (_parse_thickness(thick_raw) if thick_raw else (None, None))

        def _rebar_at(y: float | None) -> list[str]:
            if y is None:
                return []
            vals: list[str] = []
            for w in words:
                if abs(float(w["top"]) - y) <= 3 and 180 <= float(w["x0"]) <= 320:
                    for m in _SLAB_REBAR_RE.findall(w["text"]):
                        vals.append(m)
            return vals

        top_rebar = _rebar_at(top_y)
        bot_rebar = _rebar_at(bot_y)

        field_bboxes: dict[str, tuple[float, float, float, float]] = {
            "thickness": (103.0, my - 4, 152.0, my + 6),
        }
        if top_y is not None:
            field_bboxes["top"] = (180.0, top_y - 3, 330.0, top_y + 7)
        if bot_y is not None:
            field_bboxes["bottom"] = (180.0, bot_y - 3, 330.0, bot_y + 7)

        out.append(SlabMember(
            mark=mw["text"],
            thickness=thickness,
            thickness_raw=thick_disp,
            top_rebar=top_rebar,
            bottom_rebar=bot_rebar,
            source=Source.DRAWING,
            location=LocationHint(page=page_idx, bbox=(60.0, my - 9, 330.0, my + 9)),
            field_bboxes=field_bboxes,
        ))
    return out


# ---------------------------------------------------------------------------
# 計算書スラブ
# ---------------------------------------------------------------------------
_RE_SLAB_HEADER = re.compile(r"No\.\d+_([A-Z]+\d+[A-Z]?)\s*[（(]([^）)]*)[）)]")
_RE_T = re.compile(r"\bt\s*=\s*(\d+)\s*mm")
_RE_FC = re.compile(r"Fc(\d+)")
_RE_SUPPORT = re.compile(r"支持条件：([^,、]+)")


def parse_calc_slabs(pdf_path: Path) -> SlabSet:
    slabs: dict[str, SlabMember] = {}
    for pd in get_pages(pdf_path):
        page_idx = pd.index
        text = pd.text
        # 「床のひび割れ」セクションは別フォーマットなので除外
        if "床のひび割れ" in text:
            continue
        lines = [ln.rstrip() for ln in text.splitlines()]
        cur: dict | None = None
        for line in lines:
            hm = _RE_SLAB_HEADER.search(line)
            if hm:
                cur = {
                    "mark": hm.group(1),
                    "note": hm.group(2),
                    "page": page_idx,
                    "t": None, "fc": None, "support": None,
                    "top": [], "bottom": [],
                }
                # ヘッダ行内に t / Fc がある場合もある
                tm = _RE_T.search(line)
                if tm:
                    cur["t"] = int(tm.group(1))
                _finalize_calc_slab(cur, slabs)
                continue
            if cur is None:
                continue
            tm = _RE_T.search(line)
            if tm and cur["t"] is None:
                cur["t"] = int(tm.group(1))
            fm = _RE_FC.search(line)
            if fm and cur["fc"] is None:
                cur["fc"] = f"Fc{fm.group(1)}"
            sm = _RE_SUPPORT.search(line)
            if sm and cur["support"] is None:
                cur["support"] = sm.group(1)
            if line.startswith("上端筋"):
                cur["top"] = _SLAB_REBAR_RE.findall(line)
                _finalize_calc_slab(cur, slabs)
            elif line.startswith("下端筋"):
                cur["bottom"] = _SLAB_REBAR_RE.findall(line)
                _finalize_calc_slab(cur, slabs)
    return SlabSet(
        source=Source.CALC,
        file_name=pdf_path.name,
        slabs=list(slabs.values()),
    )


def _finalize_calc_slab(cur: dict, slabs: dict[str, SlabMember]) -> None:
    """同一符号が複数ブロックに登場するため、符号単位でマージする。"""
    mark = cur["mark"]
    existing = slabs.get(mark)
    if existing is None:
        slabs[mark] = SlabMember(
            mark=mark,
            thickness=cur["t"],
            thickness_raw=str(cur["t"]) if cur["t"] else None,
            top_rebar=list(cur["top"]),
            bottom_rebar=list(cur["bottom"]),
            concrete_grade=cur["fc"],
            support=cur["support"],
            source=Source.CALC,
            location=LocationHint(page=cur["page"]),
            note=cur["note"] or None,
        )
    else:
        # 値を補完（後から見つかったブロックの情報を足す）
        if existing.thickness is None and cur["t"]:
            existing.thickness = cur["t"]
            existing.thickness_raw = str(cur["t"])
        if not existing.concrete_grade and cur["fc"]:
            existing.concrete_grade = cur["fc"]
        if not existing.support and cur["support"]:
            existing.support = cur["support"]
        for v in cur["top"]:
            if v not in existing.top_rebar:
                existing.top_rebar.append(v)
        for v in cur["bottom"]:
            if v not in existing.bottom_rebar:
                existing.bottom_rebar.append(v)
