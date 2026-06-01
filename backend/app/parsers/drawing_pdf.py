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

from ..models import BeamMember, LocationHint, MemberSet, PositionRebar, Section, Source
from .base import Parser
from .pdf_cache import get_pages

_MARK_RE = re.compile(r"^(?:WCB|FCG|FCB|CGX|CGY|CG|CB|WB|FB|FG|B)\d+[A-Za-z]?$")
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
    """指定したセル領域内、y_center ± tol の語を x 昇順で返す。
    隣接セルから漏れ込んだ "-D??" だけの孤立トークン（直前に数値語が無いもの）は除去する。
    """
    out = [
        w for w in words
        if x_lo <= w["x0"] < x_hi and abs(float(w["top"]) - y_center) <= tol
    ]
    out.sort(key=lambda w: w["x0"])
    if not out:
        return out
    filtered: list[dict] = []
    for i, w in enumerate(out):
        t = w["text"]
        if t.startswith("-D"):
            # 直前語が数値（"3", "3/3" など）で、x 距離が近ければ正当
            if filtered and re.match(r"^\d+(?:/\d+)?$", filtered[-1]["text"]) and \
               (float(w["x0"]) - float(filtered[-1]["x0"]) - len(filtered[-1]["text"]) * 4) < 12:
                filtered.append(w)
            # else: orphan, drop
        else:
            filtered.append(w)
    return filtered


def _join_words(ws: list[dict]) -> str:
    return "".join(w["text"] for w in ws)


def _split_by_breaks(ws: list[dict], breaks: list[float]) -> list[str]:
    """与えられた x 分割境界（昇順）でセル内の語を区切って文字列化する。
    breaks=[] なら全部を 1 つにまとめる。breaks=[mid] なら2分割。
    """
    if not ws:
        return [""] * (len(breaks) + 1)
    if not breaks:
        return [_join_words(ws)]
    sorted_ws = sorted(ws, key=lambda w: float(w["x0"]))
    parts: list[list[dict]] = [[] for _ in range(len(breaks) + 1)]
    for w in sorted_ws:
        x = float(w["x0"])
        idx = 0
        for i, b in enumerate(breaks):
            if x < b:
                idx = i
                break
        else:
            idx = len(breaks)
        parts[idx].append(w)
    return [_join_words(p) for p in parts]


def _collect_pos_labels(words: list[dict], pos_y: float, x_min: float, x_max: float) -> list[tuple[float, str]]:
    """位置 行の位置ラベルを (中心x, テキスト) で返す。「中」「央」は結合。"""
    row = sorted(
        [w for w in words
         if abs(float(w["top"]) - pos_y) <= 4 and w["text"] != "位置"
         and x_min <= float(w["x0"]) <= x_max],
        key=lambda w: float(w["x0"]),
    )
    out: list[tuple[float, str]] = []
    skip = False
    for k, w in enumerate(row):
        if skip:
            skip = False
            continue
        if w["text"] == "中" and k + 1 < len(row) and row[k + 1]["text"] == "央":
            nx = row[k + 1]
            cx = (float(w["x0"]) + float(nx.get("x1", nx["x0"] + 6))) / 2
            out.append((cx, "中央"))
            skip = True
        else:
            cx = (float(w["x0"]) + float(w.get("x1", w["x0"] + 6))) / 2
            out.append((cx, w["text"]))
    return out


def _rebar_pairs(words: list[dict], y: float, x_min: float, x_max: float) -> list[tuple[float, str]]:
    """y 行・x 範囲内の鉄筋ペアを (中心x, 連結文字列) で返す。
    "N" + "-D??" (+ "@???") を1つの値とみなす。
    """
    ws = sorted(
        [w for w in words
         if abs(float(w["top"]) - y) <= 4 and x_min <= float(w["x0"]) <= x_max],
        key=lambda w: float(w["x0"]),
    )
    pairs: list[tuple[float, str]] = []
    i = 0
    while i < len(ws):
        w = ws[i]
        if re.match(r"^\d+(?:/\d+)?$", w["text"]) and i + 1 < len(ws) and ws[i + 1]["text"].startswith("-D"):
            nxt = ws[i + 1]
            toks = [w["text"], nxt["text"]]
            cx = (float(w["x0"]) + float(nxt.get("x1", nxt["x0"] + 8))) / 2
            j = i + 2
            if j < len(ws) and re.match(r"^@\d+$", ws[j]["text"]):
                toks.append(ws[j]["text"])
                j += 1
            pairs.append((cx, "".join(toks)))
            i = j
        else:
            i += 1
    return pairs


_STRADDLE_PENALTY = 40.0


def _partition_labels(labels: list[tuple[float, str]], mark_xs: list[float]) -> list[list[int]] | None:
    """位置ラベル(x昇順)をマーク(x昇順)へ「連続区間」で割り当てる。

    動的計画法で次のコストの総和を最小化する:
      ・担当ラベル群の中心とマーク x の距離
      ・「ラベル群がマークを左右から挟んでいない」ときのペナルティ
        （元端/先端 や 端部/中央 はマークを挟む。挟まない=誤割当の疑い。
          ただし「全断面」のような単独ラベルは 1 個でも正常）
    各マークに最低1ラベル。ラベル数 < マーク数 なら割当不能で None。
    返り値: マークごとのラベル index リスト。
    """
    n, m = len(labels), len(mark_xs)
    if m == 0 or n < m:
        return None
    label_xs = [c for c, _ in labels]
    label_txts = [t for _, t in labels]

    def _seg_cost(k: int, i: int, mark_x: float) -> float:
        xs = label_xs[k:i]
        center = sum(xs) / len(xs)
        cost = abs(center - mark_x)
        if len(xs) == 1:
            if "全断" not in label_txts[k]:
                cost += _STRADDLE_PENALTY
        else:
            has_l = any(x < mark_x - 5 for x in xs)
            has_r = any(x > mark_x + 5 for x in xs)
            if not (has_l and has_r):
                cost += _STRADDLE_PENALTY
        return cost

    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[-1] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for j in range(1, m + 1):
        for i in range(j, n - m + j + 1):
            for k in range(j - 1, i):
                if dp[k][j - 1] == INF:
                    continue
                c = dp[k][j - 1] + _seg_cost(k, i, mark_xs[j - 1])
                if c < dp[i][j]:
                    dp[i][j] = c
                    back[i][j] = k
    if dp[n][m] == INF:
        return None
    groups: list[list[int]] = []
    i, j = n, m
    while j > 0:
        k = back[i][j]
        groups.append(list(range(k, i)))
        i, j = k, j - 1
    groups.reverse()
    return groups


class DrawingPdfParser(Parser):
    """二次部材リスト（小梁・スラブ・壁）PDF 用パーサ。現在は小梁のみ抽出。"""

    source = Source.DRAWING

    def parse(self, pdf_path: Path) -> MemberSet:
        members: list[BeamMember] = []
        for pd in get_pages(pdf_path):
            members.extend(self._parse_page(pd.words, pd.index))
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
            # 右端セル等で隣接が無いとき幅が暴走するのを抑える。
            # 隣接マークの x 差の中央値 × 1.15 を最大幅とする。
            mark_xs_sorted = sorted(mark_xs)
            if len(mark_xs_sorted) >= 2:
                diffs = sorted(mark_xs_sorted[i + 1] - mark_xs_sorted[i] for i in range(len(mark_xs_sorted) - 1))
                median = diffs[len(diffs) // 2]
                max_w = median * 1.15
                new_bounds = []
                for (lo, hi), mw in zip(bounds, sorted(mark_words, key=lambda w: float(w["x0"]))):
                    mx = float(mw["x0"])
                    new_bounds.append((lo, min(hi, mx + max_w)))
                bounds = new_bounds
            mark_words_sorted = sorted(mark_words, key=lambda w: float(w["x0"]))

            # 位置ラベルをマークへ DP 割り当て（連続区間）
            pos_y = grp.get("位置")
            pos_labels = (
                _collect_pos_labels(words, pos_y, label_x0 + 30, right_limit)
                if pos_y is not None else []
            )
            partition = (
                _partition_labels(pos_labels, mark_xs_sorted)
                if pos_labels else None
            )

            # 各 mark ごとに位置・配筋などを拾う
            for mi, ((x_lo, x_hi), mw) in enumerate(zip(bounds, mark_words_sorted)):
                mark_x = float(mw["x0"])
                if partition is not None:
                    my_labels = [pos_labels[idx] for idx in partition[mi]]
                    positions = self._extract_mark_positions(words, grp, my_labels)
                    lxs = [cx for cx, _ in my_labels]
                    # 領域は「自分の位置ラベル群」を基準に決める。隣のマーク
                    # （特に B3A のような3断面の幅広セル）の中点で決めた x_lo に
                    # 引きずられて領域がずれないよう、セル境界は使わない。
                    if lxs:
                        terr_lo = min(min(lxs) - 28, mark_x - 8)
                        terr_hi = max(max(lxs) + 32, mark_x + 22)
                    else:
                        terr_lo, terr_hi = x_lo, x_hi
                    fc_lo, fc_hi = terr_lo, terr_hi
                    needs_review, review_note = False, None
                else:
                    positions = self._extract_positions(words, grp, x_lo, x_hi)
                    terr_lo, terr_hi = x_lo, x_hi
                    fc_lo, fc_hi = x_lo, x_hi
                    needs_review, review_note = self._detect_review_anomaly(
                        words, grp, x_lo, x_hi, positions)
                fc_code = self._extract_fc_code(words, grp, fc_lo, fc_hi)
                mark_center_x = (float(mw["x0"]) + float(mw["x1"])) / 2
                B = self._extract_section_B(words, grp, fc_lo, fc_hi, mark_center_x)
                field_bboxes = self._field_bboxes(grp, terr_lo, terr_hi)
                out.append(BeamMember(
                    mark=mw["text"],
                    section=Section(B=B, D=None),
                    positions=positions,
                    fc_code=fc_code,
                    source=self.source,
                    location=LocationHint(page=page_idx, bbox=(terr_lo, y_top - 5, terr_hi, y_bot - 2)),
                    field_bboxes=field_bboxes,
                    needs_review=needs_review,
                    review_note=review_note,
                ))
        return out

    def _extract_mark_positions(self, words, grp, my_labels) -> list[PositionRebar]:
        """DP で割り当てた位置ラベル群から、各位置の配筋を抽出する。
        位置ラベルと鉄筋値は同じ x に縦に並ぶため、各ラベル x に最も近い
        鉄筋ペアをその位置の値とする。
        """
        label_xs = [cx for cx, _ in my_labels]
        if not label_xs:
            return []
        win_lo = min(label_xs) - 28
        win_hi = max(label_xs) + 32

        def _vals(row_key: str) -> list[str | None]:
            y = grp.get(row_key)
            if y is None:
                return [None] * len(label_xs)
            pairs = _rebar_pairs(words, y, win_lo, win_hi)
            if not pairs:
                return [None] * len(label_xs)
            if len(pairs) == 1:
                # 1 値で全位置を覆う（STP・腹筋でよくある）
                v = self._normalize_rebar(pairs[0][1])
                return [v] * len(label_xs)
            out: list[str | None] = []
            for lx in label_xs:
                best = min(pairs, key=lambda pr: abs(pr[0] - lx))
                out.append(self._normalize_rebar(best[1]))
            return out

        tops = _vals("上端筋")
        bots = _vals("下端筋")
        stps = _vals("STP")
        webs = _vals("腹筋")
        return [
            PositionRebar(
                location=txt, top=tops[i], bottom=bots[i],
                stirrup=stps[i], web=webs[i],
            )
            for i, (_, txt) in enumerate(my_labels)
        ]

    @staticmethod
    def _detect_review_anomaly(words, grp, x_lo, x_hi, positions) -> tuple[bool, str | None]:
        """構造図の小梁リストレイアウトで完全抽出が困難なケースを検出する。

        検出する 2 パターン:
        (a) 位置ラベル数 > サブ位置数 ... 外端/中央/連続端 等の 3 位置レイアウトで
            3 番目の鉄筋値が物理的に隣セル領域に置かれて取得できないケース。
        (b) 上端筋の鉄筋ペア数 ≠ 下端筋の鉄筋ペア数 ... 隣セルから片方の行だけに
            値が漏れ込んでいるケース (例: B4 に B3A の値が下端筋だけ侵入)。
        """
        notes: list[str] = []

        # (a) 位置ラベル数 vs サブ位置数
        pos_y = grp.get("位置")
        if pos_y is not None:
            label_words = []
            for w in words:
                if abs(float(w["top"]) - pos_y) > 4:
                    continue
                if w["text"] == "位置":
                    continue
                wx0 = float(w["x0"])
                wx1 = float(w.get("x1", wx0 + 5))
                width = max(wx1 - wx0, 1.0)
                overlap = max(0.0, min(wx1, x_hi) - max(wx0, x_lo))
                if overlap / width >= 0.3:
                    label_words.append(w)
            label_count = 0
            skip = False
            label_words.sort(key=lambda w: float(w["x0"]))
            for k, w in enumerate(label_words):
                if skip:
                    skip = False
                    continue
                if w["text"] == "中" and k + 1 < len(label_words) and label_words[k + 1]["text"] == "央":
                    label_count += 1
                    skip = True
                else:
                    label_count += 1
            sub_count = len(positions)
            if label_count > sub_count and label_count >= 3:
                notes.append(
                    f"位置ラベル {label_count} 個 vs 抽出サブ位置 {sub_count} 個"
                    f"（外端/中央/連続端のような 3 位置レイアウトと推測。隣セル境界付近の値が取得困難）"
                )

        # (b) 上端筋・下端筋の鉄筋ペア数の不一致
        def _count_pairs(y):
            if y is None:
                return 0
            ws = _collect_at_y(words, y, x_lo, x_hi, tol=4)
            cnt = 0
            i = 0
            while i < len(ws):
                w = ws[i]
                if re.match(r"^\d+(?:/\d+)?$", w["text"]) and i + 1 < len(ws) and ws[i + 1]["text"].startswith("-D"):
                    cnt += 1
                    i += 2
                else:
                    i += 1
            return cnt

        top_pairs = _count_pairs(grp.get("上端筋"))
        bot_pairs = _count_pairs(grp.get("下端筋"))
        if top_pairs and bot_pairs and top_pairs != bot_pairs:
            notes.append(
                f"上端筋 {top_pairs} ペア vs 下端筋 {bot_pairs} ペア"
                f"（隣セルから片方の行のみに値が漏れ込んでいる可能性）"
            )

        if notes:
            return True, " / ".join(notes)
        return False, None

    @staticmethod
    def _field_bboxes(grp: dict, x_lo: float, x_hi: float) -> dict[str, tuple[float, float, float, float]]:
        """ラベル行 y 位置からフィールド単位の bbox を組み立てる。"""
        out: dict[str, tuple[float, float, float, float]] = {}
        spec = [
            ("B", "断面", -3, 13),
            ("top", "上端筋", -4, 9),
            ("bottom", "下端筋", -4, 9),
            ("stirrup", "STP", -4, 9),
            ("web", "腹筋", -4, 9),
        ]
        for key, label, top_off, bot_off in spec:
            y = grp.get(label)
            if y is None:
                continue
            out[key] = (x_lo, y + top_off, x_hi, y + bot_off)
        return out

    def _extract_positions(self, words, grp, x_lo, x_hi) -> list[PositionRebar]:
        # 戦略:
        # 1) 上端筋の行に並ぶ鉄筋ペア（"N(-D??)" or "N/N(-D??)" の対）の中心 x を
        #    サブ位置の基準とする。鉄筋値は位置ラベルと違って密に書かれるため
        #    クラスタ数 = サブ位置数として信頼できる。
        # 2) 各サブ位置に最も近い位置ラベル（ページ行全体から）を割り当てる。
        # 3) STP/腹筋など 1 値で全位置を覆うケースも兼用。
        top_y = grp.get("上端筋")
        rebar_centers: list[float] = []
        if top_y is not None:
            top_ws = _collect_at_y(words, top_y, x_lo, x_hi, tol=4)
            i = 0
            while i < len(top_ws):
                w = top_ws[i]
                if re.match(r"^\d+(?:/\d+)?$", w["text"]) and i + 1 < len(top_ws) and top_ws[i + 1]["text"].startswith("-D"):
                    nxt = top_ws[i + 1]
                    cx = (float(w["x0"]) + float(nxt.get("x1", nxt["x0"] + 8))) / 2
                    rebar_centers.append(cx)
                    i += 2
                else:
                    i += 1
        n_sub = max(1, len(rebar_centers))

        # 位置ラベルはページ全体の 位置 行から取得（中・央 結合）
        pos_y = grp.get("位置")
        pos_labels: list[tuple[float, str]] = []
        if pos_y is not None:
            row = [w for w in words if abs(float(w["top"]) - pos_y) <= 4 and w["text"] != "位置"]
            row.sort(key=lambda w: float(w["x0"]))
            skip = False
            for k, w in enumerate(row):
                if skip:
                    skip = False
                    continue
                if w["text"] == "中" and k + 1 < len(row) and row[k + 1]["text"] == "央":
                    cx = (float(w["x0"]) + float(row[k + 1].get("x1", row[k + 1]["x0"] + 6))) / 2
                    pos_labels.append((cx, "中央"))
                    skip = True
                else:
                    cx = (float(w["x0"]) + float(w.get("x1", w["x0"] + 6))) / 2
                    pos_labels.append((cx, w["text"]))

        # 各サブ位置に最も近いラベルを割り当て（ラベルは重複利用可）
        def _pick_label(sc: float) -> str:
            if not pos_labels:
                return ""
            best = min(pos_labels, key=lambda l: abs(l[0] - sc))
            return best[1]

        sub_locations = [_pick_label(sc) for sc in rebar_centers] if rebar_centers else [""]

        # サブ列分割境界 = 連続するサブ位置中心の中点
        sub_breaks = [(rebar_centers[i] + rebar_centers[i + 1]) / 2 for i in range(len(rebar_centers) - 1)]

        def _row_parts(label: str) -> list[str]:
            y = grp.get(label)
            if y is None:
                return []
            ws = _collect_at_y(words, y, x_lo, x_hi, tol=4)
            if not ws:
                return []
            joined = _join_words(ws)
            n_tokens = len(_REBAR_RE.findall(joined))
            breaks = sub_breaks if n_tokens >= n_sub else []
            parts = _split_by_breaks(ws, breaks)
            normalized = [self._normalize_rebar(p) for p in parts]
            if not breaks and n_sub > 1 and normalized:
                normalized = [normalized[0]] * n_sub
            return normalized

        top_parts = _row_parts("上端筋")
        bot_parts = _row_parts("下端筋")
        stp_parts = _row_parts("STP")
        web_parts = _row_parts("腹筋")

        n = max(len(sub_locations), len(top_parts), len(bot_parts), len(stp_parts), len(web_parts), 1)

        def _pick(parts: list[str], k: int) -> str | None:
            if not parts:
                return None
            if k < len(parts):
                return parts[k]
            return parts[-1]

        positions: list[PositionRebar] = []
        for k in range(n):
            positions.append(PositionRebar(
                location=_pick(sub_locations, k) or "",
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
    def _extract_section_B(words, grp, x_lo, x_hi, mark_center_x: float | None = None) -> int | None:
        """断面の幅 B を抽出する。

        梁リストの断面図には、上から順に
          ・梁天端レベル（"1SL-350" 等、基準レベルからの下がり）
          ・梁成 D（断面図の縦寸法）
          ・梁幅 B（断面図の最下段に書かれる横寸法。左右対称で同じ値が
            2 つ並ぶことが多い）
        が縦に並ぶ。したがって **梁幅 B は断面図領域の最下段（上端筋
        ラベルの直前）にある数値** とみなすのが最も確実。

        位置/断面ラベルの y は物件によって上下するため、探索域は
        「位置ラベル直下〜上端筋ラベル直前」とし、その中で最下段
        （top が最大）の妥当値（150〜1500mm）を採る。同じ段に複数
        あれば符号中心 x に最も近いものを採る。
        """
        y_sec = grp.get("断面")
        y_pos = grp.get("位置")
        y_top_label = grp.get("上端筋")
        if y_sec is None and y_pos is None:
            return None

        def _val(w):
            try: return int(w["text"])
            except ValueError: return -1

        # 探索域の上端：位置ラベル直下（無ければ断面ラベルの少し上）
        if y_pos is not None:
            lo = float(y_pos) + 4
        else:
            lo = float(y_sec) - 40
        # 探索域の下端：上端筋ラベル直前（無ければ断面ラベル + 100）
        if y_top_label is not None:
            hi = float(y_top_label) - 3
        elif y_sec is not None:
            hi = float(y_sec) + 100
        else:
            hi = lo + 120

        cands = [
            w for w in words
            if x_lo <= float(w["x0"]) < x_hi
            and lo < float(w["top"]) < hi
            and w["text"].isdigit()
            and 150 <= _val(w) <= 1500
        ]
        if not cands:
            return None
        # 最下段（top 最大）を優先。top を ±4pt でビン化して同段扱いにし、
        # 同段内では符号中心 x に最も近いものを採る。
        max_top = max(float(w["top"]) for w in cands)
        bottom_row = [w for w in cands if abs(float(w["top"]) - max_top) <= 4]
        if mark_center_x is not None:
            bottom_row.sort(key=lambda w: abs((float(w["x0"]) + float(w["x1"])) / 2 - mark_center_x))
        else:
            bottom_row.sort(key=lambda w: float(w["x0"]))
        try:
            return int(bottom_row[0]["text"])
        except ValueError:
            return None

