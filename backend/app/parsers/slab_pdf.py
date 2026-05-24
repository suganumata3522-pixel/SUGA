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


# 符号名から推定する厚み: S18→180, CS25A→250, CS315→315 など
_MARK_THICK_RE = re.compile(r"^C?S(\d{2,3})[A-Z]?$")


def _thickness_from_mark(mark: str) -> int | None:
    """符号名から厚みを推定する。"S18"→180, "CS25A"→250, "CS315"→315。

    日本のRC構造図で広く使われる慣例: 符号 S/CS の後の数値が
    2桁なら ×10、3桁ならそのまま mm として扱う。
    """
    m = _MARK_THICK_RE.match(mark)
    if not m:
        return None
    n = int(m.group(1))
    return n * 10 if n < 100 else n


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


def _find_slab_header(words: list[dict]) -> list[dict] | None:
    """スラブリストのヘッダ行（"符号" と "主筋方向" を含む行）を返す。
    小梁リストのヘッダは "主筋方向" を持たないため区別できる。"""
    for line in _group_lines(words, tol=4.0):
        texts = [w["text"] for w in line]
        if "符号" in texts and any("主筋" in t for t in texts):
            return line
    return None


def _slab_columns(header: list[dict]) -> dict[str, dict | None]:
    """ヘッダ行から各列の語を得る。"""
    def col(pred) -> dict | None:
        return next((w for w in header if pred(w["text"])), None)
    return {
        "sym": col(lambda t: t == "符号"),
        "thick": col(lambda t: "スラブ" in t or t == "厚"),
        "pos": col(lambda t: t == "位置"),
        "main": col(lambda t: "主筋" in t),
        "dist": col(lambda t: "主筋" not in t and "筋方向" in t),
        "bikou": col(lambda t: t.startswith("備")),
    }


def _parse_drawing_page(words: list[dict], page_idx: int) -> list[SlabMember]:
    # スラブリストは構造図ごとに列 x が異なるため、ヘッダ行から列位置を検出する。
    header = _find_slab_header(words)
    if header is None:
        return []
    cols = _slab_columns(header)
    sym, thick, pos, main, dist, bikou = (
        cols["sym"], cols["thick"], cols["pos"], cols["main"], cols["dist"], cols["bikou"]
    )
    if sym is None or main is None:
        return []
    header_y = min(float(w["top"]) for w in header)
    sym_x = float(sym["x0"])

    # 各列の x レンジ（ヘッダ語を基準に相対オフセットで決める）
    thick_lo = float(thick["x0"]) - 25 if thick else sym_x + 30
    thick_hi = float(thick["x1"]) + 14 if thick else sym_x + 95
    pos_lo = float(pos["x0"]) - 8 if pos else None
    pos_hi = float(pos["x0"]) + 24 if pos else None
    rebar_lo = float(main["x0"]) - 32
    rebar_hi = (float(dist["x1"]) + 18) if dist else (float(main["x1"]) + 90)
    box_left = sym_x - 6
    box_right = (float(bikou["x0"]) - 4) if bikou else rebar_hi + 6

    # スラブ符号を符号列付近・ヘッダより下で検出
    mark_words = sorted(
        [w for w in words
         if _SLAB_MARK_RE.match(w["text"])
         and (sym_x - 7) <= float(w["x0"]) <= (sym_x + 34)
         and float(w["top"]) > header_y + 4],
        key=lambda w: float(w["top"]),
    )
    if not mark_words:
        return []

    # 上端筋/下端筋ラベル（位置列付近）
    label_words = [
        w for w in words
        if w["text"] in {"上端筋", "下端筋"}
        and (pos_lo is None or pos_lo <= float(w["x0"]) <= pos_hi)
    ]

    out: list[SlabMember] = []
    for mw in mark_words:
        my = float(mw["top"])
        band_labels = [lw for lw in label_words if abs(float(lw["top"]) - my) <= 9]
        top_y = next((float(lw["top"]) for lw in band_labels if lw["text"] == "上端筋"), None)
        bot_y = next((float(lw["top"]) for lw in band_labels if lw["text"] == "下端筋"), None)

        # スラブ厚（厚さ列・符号行）
        thick_raw = None
        thick_word: dict | None = None
        for w in words:
            if thick_lo <= float(w["x0"]) <= thick_hi and abs(float(w["top"]) - my) <= 4:
                if re.match(r"^[\d〜～\-]+$", w["text"]):
                    thick_raw = w["text"]
                    thick_word = w
                    break
        thickness, thick_disp = (_parse_thickness(thick_raw) if thick_raw else (None, None))
        # 厚み列のフォント/文字コードが不安定で "02〜000" "01〜800" のような
        # 化け値になり、現実離れした厚み (80mm未満 / 500mm超) になることがある。
        # その場合は符号名 (S18→180, CS25→250) から推定して置き換える。
        if thickness is None or not (80 <= thickness <= 500):
            est = _thickness_from_mark(mw["text"])
            if est is not None:
                thickness = est
                thick_disp = str(est) if not thick_raw else f"{thick_raw}→{est}(符号推定)"

        def _rebar_at(y: float | None) -> list[str]:
            if y is None:
                return []
            vals: list[str] = []
            for w in words:
                if abs(float(w["top"]) - y) <= 3 and rebar_lo <= float(w["x0"]) <= rebar_hi:
                    vals.extend(_SLAB_REBAR_RE.findall(w["text"]))
            return vals

        top_rebar = _rebar_at(top_y)
        bot_rebar = _rebar_at(bot_y)

        # フィールド単位の枠（差分の赤枠）は対象箇所のみをタイトに囲う。
        # 部材全体枠（橙）は location.bbox 側で符号〜配筋を覆う。
        # スラブ厚は厚さの数値だけを囲い、行全体を覆わない。
        sym_top, sym_bot = my, float(mw["bottom"])
        field_bboxes: dict[str, tuple[float, float, float, float]] = {}
        if thick_word is not None:
            field_bboxes["thickness"] = (
                float(thick_word["x0"]) - 3, float(thick_word["top"]) - 3,
                float(thick_word["x1"]) + 3, float(thick_word["bottom"]) + 3,
            )
        else:
            field_bboxes["thickness"] = (thick_lo, sym_top - 3, thick_hi, sym_bot + 3)
        if top_y is not None:
            field_bboxes["top"] = (box_left, top_y - 3, box_right, top_y + 7)
        if bot_y is not None:
            field_bboxes["bottom"] = (box_left, bot_y - 3, box_right, bot_y + 7)

        # 行全体の赤枠は「符号 + 上端筋行 + 下端筋行」を実測値で囲う。
        ys = [my, sym_bot]
        if top_y is not None:
            ys.append(top_y - 3)
        if bot_y is not None:
            ys.append(bot_y + 7)
        out.append(SlabMember(
            mark=mw["text"],
            thickness=thickness,
            thickness_raw=thick_disp,
            top_rebar=top_rebar,
            bottom_rebar=bot_rebar,
            source=Source.DRAWING,
            location=LocationHint(page=page_idx, bbox=(box_left, min(ys) - 2, box_right, max(ys) + 2)),
            field_bboxes=field_bboxes,
        ))
    return out


# ---------------------------------------------------------------------------
# 計算書スラブ
# ---------------------------------------------------------------------------
# ブロック見出し。番号は "No.20" のほか "No.21-1"（枝番）もあり、
# 区切りはアンダースコアのほか半角スペースのこともある。
_RE_SLAB_HEADER = re.compile(r"No\.\d+(?:-\d+)?[_ ]\s*([A-Z]+\d+[A-Z]?)\s*[（(]([^）)]*)[）)]")
# 別書式の見出し: "1_S1_EV屋根" "2-1_CS1_階段屋根" のように
# "番号_符号_備考"（No. 無し・カッコ無し）の計算書もある。
_RE_SLAB_HEADER2 = re.compile(r"^\s*\d+(?:-\d+)?_([A-Z]+\d+[A-Z]?)_(.+?)\s*$")
# さらに別書式: "<1>S18 B1SL ﾄﾗﾝｸﾙｰﾑ" "<5>S20B(配力筋) B1SL 駐車場" のように
# "<番号>符号 場所" で始まる計算書もある（符号直後にカッコ書きが付くことも）。
_RE_SLAB_HEADER3 = re.compile(r"^\s*<\d+>\s*([A-Z]+\d+[A-Z]?)(?:[（(][^）)]*[）)])?\s+(.*)$")
_RE_T = re.compile(r"\bt\s*=\s*(\d+)\s*mm")
_RE_FC = re.compile(r"Fc(\d+)")
_RE_SUPPORT = re.compile(r"支持条件：([^,、]+)")


def _group_lines(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    """単語を y(top) で行にまとめ、各行を x0 昇順で返す。"""
    if not words:
        return []
    sw = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
    lines: list[list[dict]] = []
    cur: list[dict] = [sw[0]]
    cy = float(sw[0]["top"])
    for w in sw[1:]:
        wy = float(w["top"])
        if abs(wy - cy) <= tol:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: float(x["x0"])))
            cur = [w]
            cy = wy
    lines.append(sorted(cur, key=lambda x: float(x["x0"])))
    return lines


def _span_bbox(ws: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(float(w["x0"]) for w in ws),
        min(float(w["top"]) for w in ws),
        max(float(w["x1"]) for w in ws),
        max(float(w["bottom"]) for w in ws),
    )


def _thickness_word_bbox(lw: list[dict]) -> tuple[float, float, float, float] | None:
    """行内の "t = NNNmm" の語を見つけて bbox を返す（dt= は除外）。"""
    for i, w in enumerate(lw):
        if w["text"] == "t" and i + 2 < len(lw) and lw[i + 1]["text"] == "=" \
           and re.match(r"^\d+\s*mm", lw[i + 2]["text"]):
            return _span_bbox([lw[i], lw[i + 1], lw[i + 2]])
    return None


def parse_calc_slabs(pdf_path: Path) -> SlabSet:
    slabs: dict[str, SlabMember] = {}
    for pd in get_pages(pdf_path):
        page_idx = pd.index
        # 「床のひび割れ」セクションは別フォーマットなので除外
        if "床のひび割れ" in pd.text:
            continue
        cur: dict | None = None
        for lw in _group_lines(pd.words):
            line = " ".join(w["text"] for w in lw)
            hm = (_RE_SLAB_HEADER.search(line) or _RE_SLAB_HEADER2.match(line)
                  or _RE_SLAB_HEADER3.match(line))
            if hm:
                # 計算書には小梁ブロック(No.X_B1 等)も含まれる。スラブ符号
                # (S?? / CS??) 以外は小梁としてここでは扱わない。
                if not _SLAB_MARK_RE.match(hm.group(1)):
                    cur = None
                    continue
                cur = {
                    "mark": hm.group(1),
                    "note": hm.group(2),
                    "page": page_idx,
                    "t": None, "fc": None, "support": None,
                    "top": [], "bottom": [],
                    "bboxes": {},
                    # 符号を含むヘッダ行(No.X_Sxx ...)の bbox。各フィールド枠を
                    # 縦に伸ばして符号が必ず見えるようにするために使う。
                    "header_bbox": _span_bbox(lw),
                }
                tm = _RE_T.search(line)
                if tm:
                    cur["t"] = int(tm.group(1))
                    tb = _thickness_word_bbox(lw)
                    if tb:
                        cur["bboxes"]["thickness"] = tb
                _finalize_calc_slab(cur, slabs)
                continue
            if cur is None:
                continue
            tm = _RE_T.search(line)
            if tm and cur["t"] is None:
                cur["t"] = int(tm.group(1))
                tb = _thickness_word_bbox(lw)
                if tb:
                    cur["bboxes"]["thickness"] = tb
            fm = _RE_FC.search(line)
            if fm and cur["fc"] is None:
                cur["fc"] = f"Fc{fm.group(1)}"
            sm = _RE_SUPPORT.search(line)
            if sm and cur["support"] is None:
                cur["support"] = sm.group(1)
            if line.startswith("上端筋"):
                cur["top"] = _SLAB_REBAR_RE.findall(line)
                rb = [w for w in lw if _SLAB_REBAR_RE.fullmatch(w["text"])]
                if rb:
                    cur["bboxes"]["top"] = _span_bbox(rb)
                _finalize_calc_slab(cur, slabs)
            elif line.startswith("下端筋"):
                cur["bottom"] = _SLAB_REBAR_RE.findall(line)
                rb = [w for w in lw if _SLAB_REBAR_RE.fullmatch(w["text"])]
                if rb:
                    cur["bboxes"]["bottom"] = _span_bbox(rb)
                _finalize_calc_slab(cur, slabs)
    return SlabSet(
        source=Source.CALC,
        file_name=pdf_path.name,
        slabs=list(slabs.values()),
    )


def _block_bbox(bboxes: dict) -> tuple[float, float, float, float] | None:
    """フィールド bbox 群を内包する矩形（スラブ厚〜配筋を覆う赤枠用）。"""
    if not bboxes:
        return None
    xs0 = [b[0] for b in bboxes.values()]
    ys0 = [b[1] for b in bboxes.values()]
    xs1 = [b[2] for b in bboxes.values()]
    ys1 = [b[3] for b in bboxes.values()]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _bbox_union(bboxes: list[tuple[float, float, float, float] | None]) -> tuple[float, float, float, float] | None:
    """bbox 群を内包する矩形。None や空は無視。"""
    bbs = [b for b in bboxes if b]
    if not bbs:
        return None
    return (min(b[0] for b in bbs), min(b[1] for b in bbs),
            max(b[2] for b in bbs), max(b[3] for b in bbs))


def _finalize_calc_slab(cur: dict, slabs: dict[str, SlabMember]) -> None:
    """同一符号が複数ブロックに登場するため、符号単位でマージする。

    field_bboxes は各フィールド（厚さ/上端筋/下端筋）の行のみをタイトに保持し、
    差分（赤枠）の表示に使う。location.bbox はヘッダ行（符号を含む）と全
    フィールドの和をとった部材全体枠（橙枠）として、PDF 照合の切り出し範囲・
    部材全体表示に使う。
    """
    mark = cur["mark"]
    existing = slabs.get(mark)
    header = cur.get("header_bbox")
    bboxes = dict(cur.get("bboxes", {}))  # フィールド枠はタイトのまま
    if existing is None:
        # 全体枠 = ヘッダ + 各フィールドの和
        envelope = _bbox_union([header, *bboxes.values()])
        slabs[mark] = SlabMember(
            mark=mark,
            thickness=cur["t"],
            thickness_raw=str(cur["t"]) if cur["t"] else None,
            top_rebar=list(cur["top"]),
            bottom_rebar=list(cur["bottom"]),
            concrete_grade=cur["fc"],
            support=cur["support"],
            source=Source.CALC,
            location=LocationHint(page=cur["page"], bbox=envelope),
            field_bboxes=dict(bboxes),
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
        # フィールド枠は最初に座標が取れたブロックを優先しつつ、欠けたフィールドを補完。
        # 同一スラブが複数ブロックに登場するため、既に bbox があるフィールドは
        # 上書きしない（最初のブロックの座標を採用）。
        new_bbs = [v for k, v in bboxes.items() if k not in existing.field_bboxes]
        for k, v in bboxes.items():
            existing.field_bboxes.setdefault(k, v)
        # 全体枠は新規に取れたフィールドだけを取り込んで拡張する
        if existing.location is not None and new_bbs:
            nb = _bbox_union([existing.location.bbox, *new_bbs])
            if nb:
                existing.location = LocationHint(page=existing.location.page, bbox=nb)
