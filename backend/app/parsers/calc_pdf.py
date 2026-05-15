"""StructureSuite の小梁計算書PDFパーサー。

各小梁ごとに以下のブロックが繰り返される:

    No.1_B1・B1A（B1F 駐輪場・ENT）
    ... 荷重項 / 応力 ...
    使用材料：コンクリート Fc36 主筋 SD345 ST. SD295
    断面計算
    符号 B1A                B1A
    位置 SX1端 中 央 SX2端  SX2端 中 央 SX3端
    断面 mm B x D = 400 x 700  B x D = 400 x 700
    主筋 上 4-D22 4-D22 4/2-D22 4/2-D22 4-D22 4-D22
         下 4-D22 4-D22 4-D22 4-D22 4-D22 4-D22
    ST.  2-D10@150 ...
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from ..models import BeamMember, LocationHint, MemberSet, PositionRebar, Section, Source
from .base import Parser

_RE_BLOCK_HEADER = re.compile(r"No\.\d+_([^\s（(]+)\s*[（(]([^）)]*)[）)]")
_RE_MATERIAL = re.compile(
    r"コンクリート\s*(Fc\d+).+?主筋\s*(SD\d+).+?ST\.?\s*(SD\d+)"
)
_RE_SECTION = re.compile(r"B\s*x\s*D\s*=\s*(\d+)\s*x\s*(\d+)")
_RE_MARK_LINE = re.compile(r"^符号\s+(.+)$")
_RE_POS_LINE = re.compile(r"^位置\s+(.+)$")
_RE_TOP_LINE = re.compile(r"^主筋\s*上\s+(.+)$")
_RE_BOT_LINE = re.compile(r"^下\s+(.+)$")
_RE_ST_LINE = re.compile(r"^ST\.\s+(.+)$")


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


class StructureSuitePdfParser(Parser):
    """StructureSuite (小梁) 計算書PDF用パーサー。"""

    source = Source.CALC

    def parse(self, pdf_path: Path) -> MemberSet:
        members: list[BeamMember] = []
        with pdfplumber.open(pdf_path) as pdf:
            current_block: dict | None = None
            for page_idx, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                lines = [ln.rstrip() for ln in text.splitlines()]
                i = 0
                while i < len(lines):
                    line = lines[i]
                    # ブロック開始
                    m = _RE_BLOCK_HEADER.match(line)
                    if m:
                        marks_field = m.group(1)  # 例 "B1・B1A"
                        note = m.group(2)
                        block_marks = [s for s in re.split(r"[・,、]", marks_field) if s]
                        current_block = {
                            "marks": block_marks,
                            "note": note,
                            "page": page_idx,
                            "concrete": None,
                            "main": None,
                            "stirrup": None,
                            "sections": [],   # [(B,D), ...] 1ブロックに複数のスパン群
                        }
                        i += 1
                        continue

                    if current_block is None:
                        i += 1
                        continue

                    # 使用材料
                    mat = _RE_MATERIAL.search(line)
                    if mat:
                        current_block["concrete"] = mat.group(1)
                        current_block["main"] = mat.group(2)
                        current_block["stirrup"] = mat.group(3)

                    # 断面寸法
                    for sec in _RE_SECTION.finditer(line):
                        current_block["sections"].append((int(sec.group(1)), int(sec.group(2))))

                    # 断面計算ブロック: 符号 / 位置 / 主筋上 / 下 / ST.
                    if line.startswith("符号"):
                        mark_line = _RE_MARK_LINE.match(line).group(1)
                        marks_per_col = re.split(r"\s+", mark_line.strip())
                        # 次の行は位置
                        pos_line = lines[i + 1] if i + 1 < len(lines) else ""
                        if not pos_line.startswith("位置"):
                            i += 1
                            continue
                        position_labels = _split_positions(_RE_POS_LINE.match(pos_line).group(1))

                        # 主筋上下と ST. を後続から探す（数行先まで）
                        top_tokens: list[str] = []
                        bottom_tokens: list[str] = []
                        st_tokens: list[str] = []
                        for j in range(i + 2, min(i + 25, len(lines))):
                            ln = lines[j]
                            mt = _RE_TOP_LINE.match(ln)
                            mb = _RE_BOT_LINE.match(ln)
                            ms = _RE_ST_LINE.match(ln)
                            if mt and not top_tokens:
                                top_tokens = _tokens_top_bottom(mt.group(1))
                            elif mb and not bottom_tokens:
                                bottom_tokens = _tokens_top_bottom(mb.group(1))
                            elif ms and not st_tokens:
                                st_tokens = _tokens_st(ms.group(1))
                            if top_tokens and bottom_tokens and st_tokens:
                                break

                        # marks_per_col は通常 2つ（左セット/右セット）。
                        # 各セットの位置数で分配する。
                        n_pos = len(position_labels)
                        n_marks = len(marks_per_col)
                        if n_marks == 0:
                            i += 1
                            continue
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
                            # 既存メンバーにマージ or 新規追加
                            existing = next((m for m in members if m.mark == mark), None)
                            B = D = None
                            if current_block["sections"]:
                                # mark がブロック内の何番目かでセクションを引き当てる
                                bi = current_block["marks"].index(mark) if mark in current_block["marks"] else 0
                                if bi < len(current_block["sections"]):
                                    B, D = current_block["sections"][bi]
                                else:
                                    B, D = current_block["sections"][-1]
                            if existing is None:
                                members.append(BeamMember(
                                    mark=mark,
                                    section=Section(B=B, D=D),
                                    positions=positions,
                                    concrete_grade=current_block["concrete"],
                                    rebar_grade_main=current_block["main"],
                                    rebar_grade_stirrup=current_block["stirrup"],
                                    source=self.source,
                                    location=LocationHint(page=page_idx),
                                    note=current_block["note"] or None,
                                ))
                            else:
                                existing.positions.extend(positions)
                        i += 2
                        continue

                    i += 1

        return MemberSet(source=self.source, file_name=pdf_path.name, members=members)


# 後方互換用
SSCalcPdfParser = StructureSuitePdfParser
