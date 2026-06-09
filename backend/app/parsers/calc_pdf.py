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
_BEAM_MARK_RE = re.compile(r"^(?:WCB|FCG|FCB|CGX|CGY|CPG|CG|CB|WB|FB|FG|B)\d+[A-Za-z]?$")

# Union System SS7 出力の小梁1行を抽出する正規表現。
# 例: "[ FB1 ] [B1SL X2 Y3 X3 Y4] 方向 Y 上端 4-D25 4-D25 4-D25 3-D13 MD ..."
#     "           下端 4-D25 4/2-D25 4-D25 @200 MA ..."
#     "B×D 500×1850 単スパン φI 1.000 L 8500 ..."
_RE_SS7_MARK = re.compile(r"^\s*\[\s*((?:WCB|FCG|FCB|CGX|CGY|CPG|CG|CB|WB|FB|FG|B)\d+[A-Za-z]?)\s*\]")
_RE_SS7_BXD = re.compile(r"B\s*[×x]\s*D\s+(\d+)\s*[×x]\s*(\d+)")
_RE_SS7_TOP = re.compile(r"上端\s+(.+)")
_RE_SS7_BOT = re.compile(r"下端\s+(.+)")

# 計算書ブロック内の注記による配筋上書きパターン。
# 例: "※ 6-4 突出部の検討 より、各階2段筋を追加し、上下共に 2/2-D16 とする。"
# 表のデフォルト値 (2-D16) を 2/2-D16 で上書きする旨の注記。
_RE_OVERRIDE_BOTH = re.compile(r"上下共?に?\s*(\d+(?:/\d+)?-D\d+)\s*とする")
_RE_OVERRIDE_TOP = re.compile(r"上端\s*(?:筋)?\s*(?:を|は)?\s*(\d+(?:/\d+)?-D\d+)\s*とする")
_RE_OVERRIDE_BOT = re.compile(r"下端\s*(?:筋)?\s*(?:を|は)?\s*(\d+(?:/\d+)?-D\d+)\s*とする")


def _try_header(line: str) -> tuple[list[str], str] | None:
    """与えられた1行が既知のブロック見出しならば、(marks, note) を返す。
    どのパターンにも合致しなければ None。

    "WCB1,1A" のように先頭符号のプレフィックス（"WCB"）が省略された
    続きの符号 ("1A" → "WCB1A") は、直前の有効符号からプレフィックス
    を補完する。"""
    for pat in _HEADER_PATTERNS:
        m = pat.match(line)
        if not m:
            continue
        marks_field = m.group(1)
        note = (m.group(2) if m.lastindex and m.lastindex >= 2 else "") or ""
        raw_marks = [s for s in re.split(r"[・,、]", marks_field) if s]
        marks: list[str] = []
        prefix = ""
        for tok in raw_marks:
            if _BEAM_MARK_RE.match(tok):
                marks.append(tok)
                pm = re.match(r"^([A-Z]+)\d", tok)
                if pm:
                    prefix = pm.group(1)
            elif prefix and _BEAM_MARK_RE.match(prefix + tok):
                marks.append(prefix + tok)
            else:
                marks.append(tok)
        return marks, note.strip()
    return None


def _parse_symbol_line(marks_field: str) -> list[list[str]]:
    """符号行を「列ごとの符号リスト」に分解する。

    列はスペース区切り、同一列内の符号はカンマ区切り。
    "WCB1,1A" のように後続符号でプレフィックスが省略されている場合は
    直前の有効符号からプレフィックスを補完して "WCB1A" に展開する。

    例:
      "B1 B2 B3"        → [['B1'], ['B2'], ['B3']]
      "WCB1,1A"         → [['WCB1', 'WCB1A']]
      "B1 WCB1,1A B2"   → [['B1'], ['WCB1', 'WCB1A'], ['B2']]
    """
    columns: list[list[str]] = []
    for chunk in re.split(r"\s+", marks_field.strip()):
        if not chunk:
            continue
        raw_tokens = [t for t in re.split(r"[,、・]", chunk) if t]
        marks: list[str] = []
        prefix = ""
        for tok in raw_tokens:
            if _BEAM_MARK_RE.match(tok):
                marks.append(tok)
                pm = re.match(r"^([A-Z]+)\d", tok)
                if pm:
                    prefix = pm.group(1)
            elif prefix and _BEAM_MARK_RE.match(prefix + tok):
                marks.append(prefix + tok)
        if marks:
            columns.append(marks)
    return columns


def _tokens_top_bottom(line: str) -> list[str]:
    """主筋行の値を位置数に対応するトークンへ分割する。
    "4-D22 4-D22 4/2-D22" → ["4-D22", "4-D22", "4/2-D22"]
    一部 PDF は "3 -D25" のように本数と "-D??" の間に空白を含むため
    空白を許容し、抽出後の文字列からは空白を除去する。
    """
    return [re.sub(r"\s+", "", t) for t in re.findall(r"\d+(?:/\d+)?\s*-D\d+", line)]


def _tokens_st(line: str) -> list[str]:
    """ST. 行の値を位置数に対応するトークンへ分割する。
    "2-D10@150 2-D10@150 2-D10@150" → 各位置 "2-D10@150"
    一部 PDF は "2 -D10 @150" のように空白で分割されるため空白を許容する。
    """
    return [re.sub(r"\s+", "", t) for t in re.findall(r"\d+\s*-D\d+\s*@\d+", line)]


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
                        # 列はスペースで区切られ、1列内に "WCB1,1A" のように
                        # カンマで複数の符号がまとめられることがある。
                        # 同列の符号は同じ位置・配筋を共有する。
                        column_marks = _parse_symbol_line(mark_match.group(1).strip())
                        if column_marks:
                            position_labels = _split_positions(_RE_POS_LINE.match(pos_line).group(1))
                            top_tokens, bottom_tokens, st_tokens, section_tokens = (
                                self._read_section_table(lines, i)
                            )
                            self._emit_members(
                                members, column_marks, position_labels,
                                top_tokens, bottom_tokens, st_tokens, section_tokens,
                                lines, i, page_idx,
                                cur_concrete, cur_main, cur_stirrup,
                            )
                            i += 2
                            continue

                # SS7（Union System Super Build）形式の小梁1行を検出
                # 形式: "[ MARK ] [floor X Y X Y] 方向 X 上端 ... 下端 ... B×D NNN×NNN ..."
                ss7m = _RE_SS7_MARK.match(line)
                if ss7m:
                    self._emit_ss7_beam(
                        members, ss7m.group(1), lines, i, page_idx,
                        cur_concrete, cur_main, cur_stirrup,
                    )
                    i += 1
                    continue

                i += 1

            # ページ単位で field_bboxes を補完
            _attach_field_bboxes(members, page_words, page_idx)

        return MemberSet(source=self.source, file_name=pdf_path.name, members=members)

    @staticmethod
    def _emit_ss7_beam(
        members: list[BeamMember], mark: str, lines: list[str], idx: int, page_idx: int,
        concrete: str | None, main: str | None, stirrup: str | None,
    ) -> None:
        """SS7形式の小梁1ブロックを抽出して BeamMember を作る。

        ブロック例:
          [ FB1 ] [B1SL X2 Y3 X3 Y4] 方向 Y 上端 4-D25 4-D25 4-D25 3-D13 MD ...
             二重上 1次=1                       反転 無 下端 4-D25 4/2-D25 4-D25 @200 MA ...
          B×D 500×1850 単スパン  φI 1.000 L 8500 dt 83 83/105 83 ...
        """
        # 同じ符号で既に登録があればスキップ（最初の登場ブロックを採用）
        if any(m.mark == mark for m in members):
            return
        # 後続4行までスキャンして 上端/下端/B×D を拾う
        top_str = bottom_str = None
        stp_str = None
        B = D = None
        # 1行目（current）にも上端が来ることがある
        for k in range(idx, min(idx + 5, len(lines))):
            ln = lines[k]
            if top_str is None:
                mt = _RE_SS7_TOP.search(ln)
                if mt:
                    top_str = mt.group(1)
            if bottom_str is None:
                mb = _RE_SS7_BOT.search(ln)
                if mb:
                    bottom_str = mb.group(1)
            if B is None:
                ms = _RE_SS7_BXD.search(ln)
                if ms:
                    B, D = int(ms.group(1)), int(ms.group(2))
            if top_str and bottom_str and B is not None:
                break

        if top_str is None and bottom_str is None and B is None:
            return  # 何も拾えなければ登録しない

        def _rebar_first_tokens(s: str | None) -> tuple[str | None, str | None, str | None, str | None]:
            """上端/下端のトークン列を分解して 左端/中央/右端/あばら筋(or @ピッチ) を返す。
            SS7では 左 中 右 のあと、あばら筋本数-径 か @ピッチ単体が続く。"""
            if not s:
                return None, None, None, None
            toks = re.findall(r"\d+(?:/\d+)?-D\d+|\d+-D\d+@\d+|@\d+", s)
            l = toks[0] if len(toks) >= 1 else None
            c = toks[1] if len(toks) >= 2 else None
            r = toks[2] if len(toks) >= 3 else None
            st = toks[3] if len(toks) >= 4 else None
            return l, c, r, st

        tl, tc, tr, t_stp = _rebar_first_tokens(top_str)
        bl, bc, br, b_at = _rebar_first_tokens(bottom_str)
        # あばら筋: 上端側は "3-D13" 等本数-径、下端側は "@200" 等ピッチ。組合せて "3-D13@200" を作る。
        if t_stp and b_at and "@" in b_at and "@" not in t_stp:
            stp_str = f"{t_stp}{b_at}"
        elif t_stp and "@" in t_stp:
            stp_str = t_stp

        positions = [
            PositionRebar(location="左端", top=tl, bottom=bl, stirrup=stp_str),
            PositionRebar(location="中央", top=tc, bottom=bc, stirrup=stp_str),
            PositionRebar(location="右端", top=tr, bottom=br, stirrup=stp_str),
        ]
        members.append(BeamMember(
            mark=mark,
            section=Section(B=B, D=D),
            positions=positions,
            concrete_grade=concrete,
            rebar_grade_main=main,
            rebar_grade_stirrup=stirrup,
            source=Source.CALC,
            location=LocationHint(page=page_idx),
            note=None,
        ))

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
    def _find_overrides(lines: list[str], symbol_idx: int) -> tuple[str | None, str | None, str | None]:
        """符号行の前後で "...とする" 形式の主筋上書き注記を探す。

        戻り値は (上下共通, 上端のみ, 下端のみ)。次の符号行 / 次のブロックの
        境界に達したら走査を打ち切る。
        """
        both = top_only = bot_only = None
        # 後ろ40行までを走査。途中で次の "符号" or "(N)" 系見出しが来たら停止
        for j in range(symbol_idx + 1, min(symbol_idx + 50, len(lines))):
            ln = lines[j]
            if ln.startswith("符号") and j > symbol_idx + 2:
                break
            # 次のブロック見出し（"(N)" "<N>" "No.N" "①" 等）も区切り
            stripped = ln.lstrip()
            if (stripped.startswith(("No.", "<")) or
                (stripped[:1].isdigit() and "_" in stripped[:8]) or
                (stripped[:1] in _CIRCLED_NUM) or
                (stripped.startswith("(") and ")" in stripped[:5] and j > symbol_idx + 2)):
                break
            mb = _RE_OVERRIDE_BOTH.search(ln)
            if mb:
                both = mb.group(1)
                continue
            mt = _RE_OVERRIDE_TOP.search(ln)
            if mt:
                top_only = mt.group(1)
            mbt = _RE_OVERRIDE_BOT.search(ln)
            if mbt:
                bot_only = mbt.group(1)
        return both, top_only, bot_only

    @staticmethod
    def _emit_members(
        members: list[BeamMember],
        column_marks: list[list[str]],
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
        """断面計算表の1組を BeamMember として登録/マージする。

        column_marks は「列ごとの符号リスト」。同じ列内の符号
        （例: WCB1,WCB1A）は同じ位置/配筋を共有する。
        """
        n_pos = len(position_labels)
        n_cols = len(column_marks)
        per = max(1, n_pos // n_cols)
        # 断面計算表の後に "※ ... 上下共に 2/2-D16 とする" などの注記で
        # 主筋を上書きする計算書がある。符号行の前後数十行から拾う。
        override_both, override_top, override_bot = StructureSuitePdfParser._find_overrides(lines, symbol_idx)
        for col_idx, col_mark_group in enumerate(column_marks):
            lo = col_idx * per
            hi = lo + per
            labels = position_labels[lo:hi]
            tops = top_tokens[lo:hi]
            bots = bottom_tokens[lo:hi]
            sts = st_tokens[lo:hi] if st_tokens else []
            # 注記で上書きがあれば、全位置に適用する
            if override_both is not None:
                tops = [override_both] * max(len(labels), 1)
                bots = [override_both] * max(len(labels), 1)
            else:
                if override_top is not None:
                    tops = [override_top] * max(len(labels), 1)
                if override_bot is not None:
                    bots = [override_bot] * max(len(labels), 1)
            # 断面: 断面計算表の列ごとの (B, D) を採用。無ければ最終列のものに倒す。
            B = D = None
            if col_idx < len(section_tokens):
                B, D = section_tokens[col_idx]
            elif section_tokens:
                B, D = section_tokens[-1]
            # 同列内の各符号に同じ位置/配筋/断面を割り当てる
            for mark in col_mark_group:
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

    1つの符号行に複数の符号が並ぶ（例: "符号 FB5 FCB1"）場合、各符号は
    位置数 ÷ 符号数 = per 列ずつを担当する。符号名は自分の列グループの
    左端（最初の列の上）に置かれるため、符号名の x だけで列を分割すると
    左側の符号は右の列が枠から切れ、右側の符号は左隣の列まで枠に含めて
    しまう。これを避けるため、配筋値（主筋上/下/ST.）の実際の列位置を
    使って各符号の担当列範囲を決める。
    """
    rows = _group_lines(page_words, tol=2.0)
    # ラベル名 → フィールドキー（None は列構造の取得には使うが bbox キーにしない）
    label_keys = {"位置": None, "断面": "B", "主筋": "top", "下": "bottom", "ST.": "stirrup"}
    _REBAR_VAL = re.compile(r"^\d+(?:/\d+)?-D\d+(?:@\d+)?$")

    for ri, (y, row_words) in enumerate(rows):
        if not row_words or row_words[0]["text"] != "符号":
            continue
        # マーク列を取得（x 昇順）。同一 mark が複数並ぶケースもそのまま列数に数える。
        mark_words = sorted(
            [w for w in row_words[1:] if _BEAM_MARK_RE.match(w["text"])],
            key=lambda w: float(w["x0"]),
        )
        if not mark_words:
            continue
        n_marks = len(mark_words)

        # 符号行直後〜次の "符号"/"No."/"断面計算" までを走査し、
        # 各フィールドの行 y と、配筋値行の値語（列位置）を収集する。
        sub_label_y: dict[str, float] = {}
        value_rows: dict[str, list[dict]] = {}  # key -> 値語リスト（x 昇順）
        label_x_lo: float | None = None
        for rj in range(ri + 1, len(rows)):
            y2, row2 = rows[rj]
            if not row2:
                continue
            first = row2[0]["text"]
            if first == "符号" or first.startswith("No.") or first.startswith("断面計算"):
                break
            if first in label_keys:
                lx = float(row2[0]["x0"])
                label_x_lo = lx if label_x_lo is None else min(label_x_lo, lx)
                key = label_keys[first]
                if key:
                    sub_label_y.setdefault(key, y2)
                    if key in ("top", "bottom", "stirrup"):
                        vals = sorted(
                            [w for w in row2 if _REBAR_VAL.match(w["text"])],
                            key=lambda w: float(w["x0"]),
                        )
                        if vals:
                            value_rows.setdefault(key, vals)
        if not sub_label_y:
            continue
        if label_x_lo is None:
            label_x_lo = float(row_words[0]["x0"])

        # 列位置の決定：配筋値が n_marks の倍数になっている密な行を採用する。
        cols: list[dict] | None = None
        for key in ("top", "bottom", "stirrup"):
            vals = value_rows.get(key)
            if vals and len(vals) % n_marks == 0 and len(vals) >= n_marks:
                cols = vals
                break
        if cols is None:
            # 値行から列を取れない場合は符号名 x をフォールバックとして使う
            cols = mark_words
        per = max(1, len(cols) // n_marks)

        y_top = y - 5
        y_bot = max(sub_label_y.values()) + 18

        for mi, mw in enumerate(mark_words):
            mark_text = mw["text"]
            target = next((m for m in members if m.mark == mark_text and not m.field_bboxes), None)
            if target is None:
                continue
            grp = cols[mi * per:(mi + 1) * per]
            if not grp:
                continue
            grp_lo = min(float(w["x0"]) for w in grp)
            grp_hi = max(float(w["x1"]) for w in grp)
            # 左端：先頭マークはラベル列まで広げて行頭の項目名を含める。
            # それ以外は左隣グループとの中点で区切る。
            if mi == 0:
                x_lo = min(label_x_lo, grp_lo) - 3
            else:
                prev = cols[(mi - 1) * per:mi * per]
                prev_hi = max(float(w["x1"]) for w in prev) if prev else grp_lo - 6
                x_lo = (prev_hi + grp_lo) / 2
            # 右端：最終マークはグループ右端 + 余白。それ以外は右隣との中点。
            if mi == n_marks - 1:
                x_hi = grp_hi + 6
            else:
                nxt = cols[(mi + 1) * per:(mi + 2) * per]
                nxt_lo = min(float(w["x0"]) for w in nxt) if nxt else grp_hi + 12
                x_hi = (grp_hi + nxt_lo) / 2

            field_bboxes: dict[str, tuple[float, float, float, float]] = {}
            for key, ly in sub_label_y.items():
                field_bboxes[key] = (x_lo, ly - 4, x_hi, ly + 12)
            target.field_bboxes = field_bboxes
            target.location = LocationHint(page=page_idx, bbox=(x_lo, y_top, x_hi, y_bot))



# 後方互換用
SSCalcPdfParser = StructureSuitePdfParser
