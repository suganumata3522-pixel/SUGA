"""構造図PDF（二次部材リスト）パーサー。

小梁リスト部分をテキスト座標から読む。各符号は列状に配置されており、
ラベル列（左端 x≈49 もしくは x≈747）の y 位置でフィールドを識別する。

抽出できるもの:
    - 符号 (mark)
    - 位置 (location) - 全断面 / 元端 / 先端 / SX2端 など
    - B (断面行に書かれた数値) ※構造図では D は数値テキストでは出現しない
    - 上端筋 / 下端筋 / STP / 腹筋
    - Fc コード（断面行の上の数字。例 "006", "007"）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from ..models import BeamMember, LocationHint, MemberSet, PositionRebar, Section, Source
from .base import Parser

_MARK_RE = re.compile(r"^(?:B|CG|WCB)\d+[A-Z]?$")
# 主筋径は D10/D13/D16/D19/D22/D25/D29/D32/D35/D38/D41 を許容
_BAR_SIZE = r"(?:10|13|16|19|22|25|29|32|35|38|41)"
_REBAR_RE = re.compile(rf"\d+(?:/\d+)?-D{_BAR_SIZE}(?:@\d+)?")
_FCCODE_RE = re.compile(r"^\d{3}$")


@dataclass
class _LabelRow:
    """左ラベル列で検出した「行」。y_center とラベル名。"""
    y: float
    label: str


def _detect_label_rows(words: list[dict], label_x_max: float = 80.0) -> list[_LabelRow]:
    """左ラベル列（x < label_x_max）から (y, label) を抽出する。"""
    rows: list[_LabelRow] = []
    for w in words:
        if w["x0"] >= label_x_max:
            continue
        t = w["text"]
        if t in {"符号", "位置", "断面", "上端筋", "下端筋", "STP", "腹筋"}:
            rows.append(_LabelRow(y=float(w["top"]), label=t))
    rows.sort(key=lambda r: r.y)
    return rows


def _group_rows(label_rows: list[_LabelRow]) -> list[dict]:
    """ラベル列を「符号」をトリガーに行グループに分割する。
    1つの符号グループには {符号, 位置, 断面, 上端筋, 下端筋, STP, 腹筋} の各 y が入る。
    """
    groups: list[dict] = []
    cur: dict | None = None
    for r in label_rows:
        if r.label == "符号":
            cur = {"符号": r.y}
            groups.append(cur)
        elif cur is not None:
            cur[r.label] = r.y
    return groups


def _column_bounds(mark_words: list[dict], all_marks_x: list[float]) -> list[tuple[float, float]]:
    """符号位置から各セルの x 範囲を作る。"""
    xs = sorted(all_marks_x)
    bounds: list[tuple[float, float]] = []
    for i, x in enumerate(xs):
        lo = (xs[i - 1] + x) / 2 if i > 0 else x - 50
        hi = (x + xs[i + 1]) / 2 if i + 1 < len(xs) else x + 50
        bounds.append((lo, hi))
    return bounds


def _collect_at_y(words: list[dict], y_center: float, x_lo: float, x_hi: float, tol: float = 5.0) -> list[dict]:
    """指定したセル領域内、y_center ± tol の語を x 昇順で返す。"""
    out = [
        w for w in words
        if x_lo <= w["x0"] < x_hi and abs(float(w["top"]) - y_center) <= tol
    ]
    out.sort(key=lambda w: w["x0"])
    return out


def _join_words(ws: list[dict]) -> str:
    return "".join(w["text"] for w in ws)


def _split_subcolumns(ws: list[dict], x_lo: float, x_hi: float, n_sub: int) -> list[str]:
    """セル内の語を「位置サブ列」ごとに n_sub 個に分けて文字列化する。
    n_sub=1 なら全部をまとめる。n_sub=2 なら中央で左/右に分ける。
    """
    if not ws:
        return []
    if n_sub <= 1:
        return [_join_words(ws)]
    x_mid = (x_lo + x_hi) / 2
    left = [w for w in ws if w["x0"] < x_mid]
    right = [w for w in ws if w["x0"] >= x_mid]
    parts: list[str] = []
    parts.append(_join_words(left))
    parts.append(_join_words(right))
    return parts


class DrawingPdfParser(Parser):
    """二次部材リスト（小梁・スラブ・壁）PDF 用パーサ。現在は小梁のみ抽出。"""

    source = Source.DRAWING

    def parse(self, pdf_path: Path) -> MemberSet:
        members: list[BeamMember] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(keep_blank_chars=False)
                members.extend(self._parse_page(words, page_idx))
        return MemberSet(source=self.source, file_name=pdf_path.name, members=members)

    def _parse_page(self, words: list[dict], page_idx: int) -> list[BeamMember]:
        # ラベル列はページ上で複数現れる（左端 x≈49、中央 x≈747）。
        # それぞれのラベル列を起点に小梁リスト群を抽出する。
        results: list[BeamMember] = []
        label_xs = sorted({round(w["x0"]) for w in words if w["text"] == "符号" and w["x0"] < 1000})
        # 各ラベル列の x 起点をクラスタリング (±20)
        clusters: list[list[float]] = []
        for x in label_xs:
            placed = False
            for c in clusters:
                if abs(c[0] - x) <= 20:
                    c.append(x)
                    placed = True
                    break
            if not placed:
                clusters.append([x])

        for cluster in clusters:
            label_x0 = min(cluster)
            results.extend(self._parse_label_block(words, label_x0, page_idx))
        return results

    def _parse_label_block(self, words: list[dict], label_x0: float, page_idx: int) -> list[BeamMember]:
        # この label_x0 起点のラベル群と、その右側に並ぶ符号セル群を扱う。
        label_words = [w for w in words if abs(w["x0"] - label_x0) <= 5 or (label_x0 <= w["x0"] < label_x0 + 35 and w["text"] in {"符号", "位置", "断面", "上端筋", "下端筋", "STP", "腹筋"})]
        rows = _detect_label_rows(label_words, label_x_max=label_x0 + 40)
        groups = _group_rows(rows)
        if not groups:
            return []

        # 各グループの y 範囲：このグループの「符号 y」～次のグループの「符号 y」（または +200）
        out: list[BeamMember] = []
        for gi, grp in enumerate(groups):
            y_top = grp["符号"]
            y_bot = groups[gi + 1]["符号"] if gi + 1 < len(groups) else y_top + 150
            # この行帯にある符号語を、対応するラベル列 (label_x0) より右側で探す
            band = [
                w for w in words
                if (y_top - 2) <= float(w["top"]) <= (y_bot - 5)
                and w["x0"] > label_x0 + 30
                # 同じページ内で別のラベル列に到達したら止める
                and not (w["x0"] > label_x0 + 600 and w["text"] == "符号")
            ]
            # 符号行 (y≈grp["符号"]) の語を抽出
            mark_words = [
                w for w in band
                if abs(float(w["top"]) - grp["符号"]) <= 3 and _MARK_RE.match(w["text"])
            ]
            if not mark_words:
                continue
            # 列幅は次の符号と同列ラベル列の右端で決まる
            mark_xs = [float(w["x0"]) for w in mark_words]
            # 次のラベル列が右にあれば、その手前を上限とする
            other_label_xs = [w["x0"] for w in words if w["text"] == "符号" and w["x0"] > max(mark_xs) + 50]
            right_limit = min(other_label_xs) if other_label_xs else max(mark_xs) + 200
            bounds = _column_bounds(mark_words, mark_xs + [right_limit])
            # bounds は mark + 右端のダミーまで含むので末尾を除く
            bounds = bounds[:-1]
            # 左端セルがラベル列の本体を含まないよう、左下限をクランプ。
            # ラベル列の文字は概ね 25pt 幅で終わるため少しマージンを取って 27pt にする。
            min_left = label_x0 + 27
            bounds = [(max(lo, min_left), hi) for (lo, hi) in bounds]
            mark_words_sorted = sorted(mark_words, key=lambda w: float(w["x0"]))

            # 各 mark ごとに位置・配筋などを拾う
            for (x_lo, x_hi), mw in zip(bounds, mark_words_sorted):
                positions = self._extract_positions(words, grp, x_lo, x_hi)
                fc_code = self._extract_fc_code(words, grp, x_lo, x_hi)
                B = self._extract_section_B(words, grp, x_lo, x_hi)
                out.append(BeamMember(
                    mark=mw["text"],
                    section=Section(B=B, D=None),
                    positions=positions,
                    fc_code=fc_code,
                    source=self.source,
                    location=LocationHint(page=page_idx, bbox=(x_lo, y_top, x_hi, y_bot)),
                ))
        return out

    def _extract_positions(self, words, grp, x_lo, x_hi) -> list[PositionRebar]:
        # 位置ラベル → サブ列数の決定権を持つ
        pos_y = grp.get("位置")
        loc_words = _collect_at_y(words, pos_y, x_lo, x_hi, tol=4) if pos_y is not None else []
        # 位置ラベルの個数（語数）でサブ列数を判定する。
        # "全断面" は 1 語、"元端 先端" は 2 語、"SX2端 中央・終端" 等も 2 語。
        n_sub = len(loc_words) if loc_words else 1
        # 「中」「央」が分割されているケースは結合して 1 語扱い
        joined_locs = []
        skip = False
        for k, w in enumerate(loc_words):
            if skip:
                skip = False
                continue
            if w["text"] == "中" and k + 1 < len(loc_words) and loc_words[k + 1]["text"] == "央":
                joined_locs.append("中央")
                skip = True
            else:
                joined_locs.append(w["text"])
        n_sub = max(1, len(joined_locs))
        loc_parts = joined_locs if joined_locs else [""]

        def _row_parts(label: str) -> list[str]:
            y = grp.get(label)
            if y is None:
                return []
            ws = _collect_at_y(words, y, x_lo, x_hi, tol=4)
            if not ws:
                return []
            # この行の配筋トークン数を数え、サブ列数を決定する
            joined = _join_words(ws)
            n_tokens = len(_REBAR_RE.findall(joined))
            actual_sub = n_sub if n_tokens >= n_sub else 1
            parts = _split_subcolumns(ws, x_lo, x_hi, actual_sub)
            normalized = [self._normalize_rebar(p) for p in parts]
            # サブ列数 < n_sub のとき（共通値）、全位置に同じ値を入れる
            if actual_sub == 1 and n_sub > 1 and normalized:
                normalized = [normalized[0]] * n_sub
            return normalized

        top_parts = _row_parts("上端筋")
        bot_parts = _row_parts("下端筋")
        stp_parts = _row_parts("STP")
        web_parts = _row_parts("腹筋")

        n = max(len(loc_parts), len(top_parts), len(bot_parts), len(stp_parts), len(web_parts), 1)

        def _pick(parts: list[str], k: int) -> str | None:
            if not parts:
                return None
            if k < len(parts):
                return parts[k]
            return parts[-1]

        positions: list[PositionRebar] = []
        for k in range(n):
            positions.append(PositionRebar(
                location=_pick(loc_parts, k) or "",
                top=_pick(top_parts, k),
                bottom=_pick(bot_parts, k),
                stirrup=_pick(stp_parts, k),
                web=_pick(web_parts, k),
            ))
        return positions

    @staticmethod
    def _normalize_rebar(s: str) -> str:
        """配筋文字列を "4-D22", "2-D10@150" などの形に正規化。"""
        s = s.replace(" ", "")
        # 例 "4-D22" / "4/2-D22" / "2-D10@150" を抽出
        m = _REBAR_RE.findall(s)
        return "+".join(m) if m else s

    @staticmethod
    def _extract_fc_code(words, grp, x_lo, x_hi) -> str | None:
        # 位置と断面の間の y にある 3 桁数字
        y_pos = grp.get("位置", 0)
        y_sec = grp.get("断面", y_pos + 30)
        for w in words:
            if x_lo <= w["x0"] < x_hi and y_pos < float(w["top"]) < y_sec:
                if _FCCODE_RE.match(w["text"]):
                    return w["text"]
        return None

    @staticmethod
    def _extract_section_B(words, grp, x_lo, x_hi) -> int | None:
        # "断面" ラベルの直下に数値（B）が出る
        y_sec = grp.get("断面")
        if y_sec is None:
            return None
        candidates = [
            w for w in words
            if x_lo <= w["x0"] < x_hi
            and y_sec < float(w["top"]) <= y_sec + 12
            and w["text"].isdigit()
        ]
        if not candidates:
            return None
        # 複数あれば最も左に出る数値を採用
        candidates.sort(key=lambda w: w["x0"])
        try:
            return int(candidates[0]["text"])
        except ValueError:
            return None
