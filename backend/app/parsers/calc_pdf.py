"""StructureSuite の小梁計算書PDFパーサー。

担当者によってブロック見出しの書き方が変わるため
（"No.1_B1(…)" / "①WB1" / "1_WB1" / "<1>B1 …" 等）、
見出し書式に依存せずに「断面計算表の構造」を直接アンカーとして
抽出する設計にしている。

抽出の流れ:
  1) 各ページの文字列を行ベースで走査する。
  2) "使用材料：コンクリート Fc.. 主筋 SD.. ST. SD.." 行を見つけたら
     直近の材料情報として記憶する。
  3) "符号 ..." 行を見つけたら、その符号行を起点に
     位置/断面 mm/主筋上/下/ST. の各行を読み出して BeamMember を作る。
     符号は符号行から、寸法は同ブロック内の "B x D = ..." から取る。
  4) note(配置場所のテキスト) は、見出しを正規表現で取れる場合のみ
     セットする。取れなくても抽出自体は通る。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import BeamMember, LocationHint, MemberSet, PositionRebar, Section, Source
from .base import Parser
from .pdf_cache import get_pages

__all__ = ["StructureSuitePdfParser", "SSCalcPdfParser"]

# 既知のブロック見出しパターン（note 抽出専用 — 抽出本体には不要）
# 抽出は符号行アンカーで行うため、ここに無い書式でも抽出は通る。
_CIRCLED_NUM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿"
_HEADER_PATTERNS = [
    # "No.1_B1（B1F 駐輪場・ENT）" / "No.5 B5 (RF 屋根)" / "No.21-1_S30(EVﾋﾟｯﾄ)"
    re.compile(r"^No\.\d+(?:-\d+)?[_ ]\s*([^\s（(]+)\s*[（(]([^）)]*)[）)]"),
    # "①WB1" / "④WB22(屋内階段受け)" / "⑥B1連梁-B1A"
    re.compile(rf"^[{_CIRCLED_NUM}]\s*([A-Za-z][^\s（(]*?)\s*(?:[（(]([^）)]*)[）)])?\s*$"),
    # "1_WB1" / "4_B1連梁" / "6-2_FB3-FCB1"
    re.compile(r"^\s*\d+(?:-\d+)?_([A-Za-z][^\s_（(]*)(?:_(.*))?$"),
    # "<1>B1 2-5SL 居室" / "<5>B4,B4A,B4B,B4C B1SL 駐車場"
    re.compile(r"^<\d+>\s*(\S+)\s*(.*)$"),
]

_RE_MATERIAL = re.compile(
    r"コンクリート\s*(Fc\d+).+?主筋\s*(SD\d+).+?ST\.?\s*(SD\d+)"
)
_RE_SECTION = re.compile(r"B\s*x\s*D\s*=\s*(\d+)\s*x\s*(\d+)")
_RE_MARK_LINE = re.compile(r"^符号\s+(.+)$")
_RE_POS_LINE = re.compile(r"^位置\s+(.+)$")
_RE_TOP_LINE = re.compile(r"^主筋\s*上\s+(.+)$")
_RE_BOT_LINE = re.compile(r"^下\s+(.+)$")
_RE_ST_LINE = re.compile(r"^ST\.\s+(.+)$")

# 梁符号の判定（行内に符号として混在する語かを判定するのに使う）
_BEAM_MARK_RE = re.compile(r"^(?:WCB|FCG|FCB|CGX|CGY|CG|CB|WB|FB|FG|B)\d+[A-Za-z]?$")


def _try_header(line: str) -> tuple[list[str], str] | None:
    """与えられた1行が既知のブロック見出しならば、(marks, note) を返す。
    どのパターンにも合致しなければ None。"""
    for pat in _HEADER_PATTERNS:
        m = pat.match(line)
        if not m:
            continue
        marks_field = m.group(1)
        note = (m.group(2) if m.lastindex and m.lastindex >= 2 else "") or ""
        marks = [s for s in re.split(r"[・,、]", marks_field) if s]
        return marks, note.strip()
    return None


def _tokens_top_bottom(line: str) -> list[str]:
    """主筋行の値を位置数に対応するトークンへ分割する。
    "4-D22 4-D22 4/2-D22" → ["4-D22", "4-D22", "4/2-D22"]
    """
    return re.findall(r"\d+(?:/\d+)?-D\d+", line)


def _tokens_st(line: str) -> list[str]:
    """ST. 行の値を位置数に対応するトークンへ分割する。
    "2-D10@150 2-D10@150 2-D10@150" → 各位置 "2-D10@150"
    """
    return re.findall(r"\d+-D\d+@\d+", line)


def _split_positions(label_line: str) -> list[str]:
    """位置行から位置ラベルの列を作る。
    "SX1端 中 央 SX2端 SX2端 中 央 SX3端" のように「中 央」が分かれているので結合する。
    """
    raw = re.split(r"\s+", label_line.strip())
    out: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok == "中" and i + 1 < len(raw) and raw[i + 1] == "央":
            out.append("中央")
            i += 2
        else:
            out.append(tok)
            i += 1
    return out


def _find_note_for_mark(lines: list[str], symbol_idx: int, mark: str, lookback: int = 40) -> str | None:
    """符号行から遡って、その符号(mark)を含む見出し風の行を見つけ、
    そこから note を抽出する。既知パターンで取れればそれを返し、
    取れなくても mark を含む短めの行があればそれを note 候補にする。
    """
    best_note = None
    for j in range(symbol_idx - 1, max(0, symbol_idx - lookback) - 1, -1):
        ln = lines[j].strip()
        if not ln:
            continue
        # 断面計算表内のラベル行・荷重項などは見出しではない
        if ln.startswith(("符号", "位置", "断面", "主筋", "下", "ST.", "dt", "pt", "ML", "Mcr", "pw", "QL", "α",
                          "応力", "荷重", "・", "L m", "B mm", "D mm", "φ", "CL", "MC", "QR", "δ", "D/L",
                          "断面計算", "使用材料", "変形")):
            continue
        if mark not in ln:
            continue
        # 既知の見出しパターンを試す
        hdr = _try_header(ln)
        if hdr and mark in hdr[0]:
            return hdr[1] or None
        # 見出しパターンに合致しない場合、mark 以外の部分を note 候補にする
        if best_note is None:
            stripped = ln.replace(mark, "", 1).strip(" 　（()）,、・-:_")
            if stripped and len(stripped) <= 60:
                best_note = stripped
    return best_note


class StructureSuitePdfParser(Parser):
    """StructureSuite (小梁) 計算書PDF用パーサー。

    ブロック見出しの書き方には依存せず、断面計算表の "符号" 行を
    アンカーとして抽出する。
    """

    source = Source.CALC

    def parse(self, pdf_path: Path) -> MemberSet:
        members: list[BeamMember] = []
        for pd in get_pages(pdf_path):
            page_idx = pd.index
            lines = [ln.rstrip() for ln in pd.text.splitlines()]
            page_words = pd.words
            # 直近の材料情報（ページ内で繰り返し上書きされる）
            cur_concrete: str | None = None
            cur_main: str | None = None
            cur_stirrup: str | None = None

            i = 0
            while i < len(lines):
                line = lines[i]

                # 使用材料の更新（どの行で出てきても拾う）
                mat = _RE_MATERIAL.search(line)
                if mat:
                    cur_concrete = mat.group(1)
                    cur_main = mat.group(2)
                    cur_stirrup = mat.group(3)

                # "符号 ..." 行を発見したら断面計算ブロックとして処理する。
                # 直前にブロック見出しが来ているかは問わない（書式非依存）。
                if line.startswith("符号"):
                    mark_match = _RE_MARK_LINE.match(line)
                    pos_line = lines[i + 1] if i + 1 < len(lines) else ""
                    if mark_match and pos_line.startswith("位置"):
                        marks_per_col = re.split(r"\s+", mark_match.group(1).strip())
                        # 符号行から梁符号として妥当なものだけを残す
                        marks_per_col = [m for m in marks_per_col if _BEAM_MARK_RE.match(m)]
                        if marks_per_col:
                            position_labels = _split_positions(_RE_POS_LINE.match(pos_line).group(1))
                            top_tokens, bottom_tokens, st_tokens, section_tokens = (
                                self._read_section_table(lines, i)
                            )
                            self._emit_members(
                                members, marks_per_col, position_labels,
                                top_tokens, bottom_tokens, st_tokens, section_tokens,
                                lines, i, page_idx,
                                cur_concrete, cur_main, cur_stirrup,
                            )
                            i += 2
                            continue

                i += 1

            # ページ単位で field_bboxes を補完
            _attach_field_bboxes(members, page_words, page_idx)

        return MemberSet(source=self.source, file_name=pdf_path.name, members=members)

    @staticmethod
    def _read_section_table(lines: list[str], symbol_idx: int) -> tuple[list[str], list[str], list[str], list[tuple[int, int]]]:
        """符号行(symbol_idx)の後続から、主筋上/下/ST./断面 mm を拾う。"""
        top_tokens: list[str] = []
        bottom_tokens: list[str] = []
        st_tokens: list[str] = []
        section_tokens: list[tuple[int, int]] = []
        for j in range(symbol_idx + 2, min(symbol_idx + 25, len(lines))):
            ln = lines[j]
            if not section_tokens:
                secs = _RE_SECTION.findall(ln)
                if secs:
                    section_tokens = [(int(b), int(d)) for b, d in secs]
            mt = _RE_TOP_LINE.match(ln)
            mb = _RE_BOT_LINE.match(ln)
            ms = _RE_ST_LINE.match(ln)
            if mt and not top_tokens:
                top_tokens = _tokens_top_bottom(mt.group(1))
            elif mb and not bottom_tokens:
                bottom_tokens = _tokens_top_bottom(mb.group(1))
            elif ms and not st_tokens:
                st_tokens = _tokens_st(ms.group(1))
            if top_tokens and bottom_tokens and st_tokens and section_tokens:
                break
        return top_tokens, bottom_tokens, st_tokens, section_tokens

    @staticmethod
    def _emit_members(
        members: list[BeamMember],
        marks_per_col: list[str],
        position_labels: list[str],
        top_tokens: list[str],
        bottom_tokens: list[str],
        st_tokens: list[str],
        section_tokens: list[tuple[int, int]],
        lines: list[str],
        symbol_idx: int,
        page_idx: int,
        concrete: str | None,
        main: str | None,
        stirrup: str | None,
    ) -> None:
        """断面計算表の1組を BeamMember として登録/マージする。"""
        n_pos = len(position_labels)
        n_marks = len(marks_per_col)
        per = max(1, n_pos // n_marks)
        for col_idx, mark in enumerate(marks_per_col):
            lo = col_idx * per
            hi = lo + per
            labels = position_labels[lo:hi]
            tops = top_tokens[lo:hi]
            bots = bottom_tokens[lo:hi]
            sts = st_tokens[lo:hi] if st_tokens else []
            positions = [
                PositionRebar(
                    location=labels[k] if k < len(labels) else "",
                    top=tops[k] if k < len(tops) else None,
                    bottom=bots[k] if k < len(bots) else None,
                    stirrup=sts[k] if k < len(sts) else (sts[-1] if sts else None),
                )
                for k in range(len(labels))
            ]
            existing = next((m for m in members if m.mark == mark), None)
            # 断面: 断面計算表の列ごとの (B, D) を採用。無ければ最終列のものに倒す。
            B = D = None
            if col_idx < len(section_tokens):
                B, D = section_tokens[col_idx]
            elif section_tokens:
                B, D = section_tokens[-1]
            if existing is None:
                note = _find_note_for_mark(lines, symbol_idx, mark)
                members.append(BeamMember(
                    mark=mark,
                    section=Section(B=B, D=D),
                    positions=positions,
                    concrete_grade=concrete,
                    rebar_grade_main=main,
                    rebar_grade_stirrup=stirrup,
                    source=Source.CALC,
                    location=LocationHint(page=page_idx),
                    note=note,
                ))
            else:
                existing.positions.extend(positions)


def _group_lines(words: list[dict], tol: float = 2.0) -> list[tuple[float, list[dict]]]:
    """y が近い語をグループ化して行に分ける。"""
    if not words:
        return []
    sorted_w = sorted(words, key=lambda w: float(w["top"]))
    rows: list[list[dict]] = []
    cur_y = float(sorted_w[0]["top"])
    cur: list[dict] = []
    for w in sorted_w:
        y = float(w["top"])
        if abs(y - cur_y) <= tol:
            cur.append(w)
        else:
            rows.append(cur)
            cur = [w]
            cur_y = y
    if cur:
        rows.append(cur)
    return [(sum(float(w["top"]) for w in r) / len(r), sorted(r, key=lambda w: float(w["x0"]))) for r in rows]


def _attach_field_bboxes(members: list[BeamMember], page_words: list[dict], page_idx: int) -> None:
    """断面計算ブロック（符号 X / 位置 / 断面 / 主筋 / 下 / ST.）から
    各 mark のフィールド単位 bbox を抽出し、当該 mark のメンバに付与する。
    """
    rows = _group_lines(page_words, tol=2.0)
    label_keys = {"位置": None, "断面": "B", "主筋": "top", "下": "bottom", "ST.": "stirrup"}

    for ri, (y, row_words) in enumerate(rows):
        if not row_words or row_words[0]["text"] != "符号":
            continue
        # マーク列を取得
        mark_words = [w for w in row_words[1:] if _BEAM_MARK_RE.match(w["text"])]
        if not mark_words:
            continue
        # 同一 mark が 2 個並ぶケース（"B1A B1A"）も含む。
        # 各 mark のセル x 範囲は隣接 mark との中点。
        mark_xs = sorted({float(w["x0"]) for w in mark_words})
        # ラベル行を符号行の直後から収集（次の "符号" or "No." まで）
        sub_label_y: dict[str, float] = {}
        for rj in range(ri + 1, len(rows)):
            y2, row2 = rows[rj]
            first = row2[0]["text"]
            if first in {"符号"} or first.startswith("No.") or first.startswith("断面計算"):
                break
            if first in label_keys and label_keys[first]:
                sub_label_y.setdefault(label_keys[first], y2)
            if all(k in sub_label_y for k in ("B", "top", "bottom", "stirrup")):
                break

        if not sub_label_y:
            continue

        # 左ラベル列(位置/断面/主筋/下/ST. 等)の左端 x
        label_x_lo = None
        for rj in range(ri + 1, len(rows)):
            y2, row2 = rows[rj]
            if not row2:
                continue
            first = row2[0]
            if first["text"] in label_keys:
                lx = float(first["x0"])
                if label_x_lo is None or lx < label_x_lo:
                    label_x_lo = lx
            if first["text"] in {"符号"} or first["text"].startswith("No.") or first["text"].startswith("断面計算"):
                break
        if label_x_lo is None:
            label_x_lo = float(row_words[0]["x0"])

        # mark ごとに、このページ内の全カラム x を集約して左右端を決める
        by_mark: dict[str, list[float]] = {}
        for mw in mark_words:
            by_mark.setdefault(mw["text"], []).append(float(mw["x0"]))
        # 同じ "符号" 行に他 mark のセル境界がある場合は、それを右端制限に使う
        all_mark_xs = sorted({float(mw["x0"]) for mw in mark_words})

        y_top = y - 5
        y_bot = max(sub_label_y.values()) + 18

        # 同一ページで該当 mark のメンバに最初に bbox を付与（既に付与済みならスキップ）
        for mark_text, xs in by_mark.items():
            target = next((m for m in members if m.mark == mark_text and not m.field_bboxes), None)
            if target is None:
                continue
            xs_sorted = sorted(xs)
            mark_lo = xs_sorted[0]
            mark_hi_x = xs_sorted[-1]
            # この mark の最右カラムの右端：同じ符号行で次の mark との中点、無ければ +135pt
            others_right = [x for x in all_mark_xs if x > mark_hi_x]
            if others_right:
                cell_hi = (mark_hi_x + others_right[0]) / 2
            else:
                cell_hi = mark_hi_x + 135
            # 左端：同じ符号行で左隣の mark があれば中点で区切る。無ければラベル列まで広げ、
            # 行頭の項目名（位置/断面/主筋/...）も枠内に入れる。
            others_left = [x for x in all_mark_xs if x < mark_lo]
            if others_left:
                x_lo = (others_left[-1] + mark_lo) / 2 - 3
            else:
                x_lo = min(label_x_lo, mark_lo) - 3
            x_hi = cell_hi + 4

            field_bboxes: dict[str, tuple[float, float, float, float]] = {}
            for key, ly in sub_label_y.items():
                # 各フィールド枠も左ラベル〜全カラムを横に含める（行頭の項目名と
                # 値が同時に見えるように）。縦はその行のみ。
                field_bboxes[key] = (x_lo, ly - 4, x_hi, ly + 12)
            target.field_bboxes = field_bboxes
            target.location = LocationHint(page=page_idx, bbox=(x_lo, y_top, x_hi, y_bot))


# 後方互換用
SSCalcPdfParser = StructureSuitePdfParser
