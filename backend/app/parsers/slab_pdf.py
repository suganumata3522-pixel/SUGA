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

from ..models import LocationHint, SlabMember, SlabSet, SlabStudy, Source
from .pdf_cache import get_pages

# スラブ符号: S18 / S25A / CS26 / CS315 など
_SLAB_MARK_RE = re.compile(r"^C?S\d+[A-Z]?$")
# 配筋トークン: D10@200 / D10D13@200 / D16@100 / D10,D13@200（カンマ区切り） など。
# 図面によっては "D10,D13@200" のように径間をカンマで区切るため許容する。
_SLAB_REBAR_RE = re.compile(r"(?:D\d+[,，]?)+@\d+")
_THICK_RANGE_RE = re.compile(r"(\d+)")


def _norm_rebar(tok: str) -> str:
    """配筋トークンのカンマ（半角/全角）を除去して表記を統一する。
    "D10,D13@200" → "D10D13@200"。"""
    return tok.replace(",", "").replace("，", "")


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
    main = col(lambda t: "主筋" in t)
    # 同一行に壁リスト等の「符号」が複数並ぶことがある。スラブリストの
    # 符号列は「主筋方向」の左側にあるため、主筋列より左で最も近い符号を採る。
    sym_candidates = [w for w in header if w["text"] == "符号"]
    sym: dict | None = None
    if main is not None and sym_candidates:
        main_x = float(main["x0"])
        left = [w for w in sym_candidates if float(w["x0"]) < main_x]
        if left:
            sym = max(left, key=lambda w: float(w["x0"]))  # 主筋列に最も近い左の符号
        else:
            sym = min(sym_candidates, key=lambda w: float(w["x0"]))
    elif sym_candidates:
        sym = sym_candidates[0]
    return {
        "sym": sym,
        "thick": col(lambda t: "スラブ" in t or t == "厚"),
        "pos": col(lambda t: t == "位置"),
        "main": main,
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
    if main is None:
        return []
    header_y = min(float(w["top"]) for w in header)

    # スラブ符号（S11 / CS12 等）の実際の列 x を求める。ヘッダ行に
    # 壁リスト等の「符号」しか無い場合があるため、ヘッダより下にある
    # スラブ符号語の最頻 x をスラブ符号列とみなす（main 列より左）。
    main_x = float(main["x0"])
    slab_mark_words = [
        w for w in words
        if _SLAB_MARK_RE.match(w["text"])
        and float(w["top"]) > header_y - 2
        and float(w["x0"]) < main_x
    ]
    if slab_mark_words:
        # 最も多く出現する x（±5pt 丸め）をスラブ符号列とする
        from collections import Counter
        xbin = Counter(round(float(w["x0"]) / 5) * 5 for w in slab_mark_words)
        sym_x = float(xbin.most_common(1)[0][0])
    elif sym is not None:
        sym_x = float(sym["x0"])
    else:
        return []

    # 各列の x レンジ（ヘッダ語を基準に相対オフセットで決める）
    thick_lo = float(thick["x0"]) - 25 if thick else sym_x + 12
    thick_hi = float(thick["x1"]) + 14 if thick else sym_x + 95
    pos_lo = float(pos["x0"]) - 8 if pos else None
    pos_hi = float(pos["x0"]) + 24 if pos else None
    rebar_lo = float(main["x0"]) - 32
    rebar_hi = (float(dist["x1"]) + 18) if dist else (float(main["x1"]) + 90)
    box_left = sym_x - 6
    # 部材枠の右端は配筋列の右端に合わせる。備考列がある場合でも配筋〜備考
    # 間の余白まで枠を広げると「枠が配筋の範囲を超えて右へ出る」ため、
    # 配筋列右端(rebar_hi)と備考列直前のうち内側を採る。
    box_right = rebar_hi + 6
    if bikou is not None:
        box_right = min(box_right, float(bikou["x0"]) - 4)

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

        # スラブ厚（厚さ列・符号行）。テーパー表記 "210〜180" は数値とチルダが
        # 別語に割れて x が重なって並ぶことがあるため、厚み列にある該当語を
        # すべて集めて x 昇順で連結してから解釈する。
        # テーパー表記 "210〜180" は上段/下段の2行に割れることがあるため
        # 縦許容を少し広め（±7）に取る。厚み列には他に数値が来ないので安全。
        thick_parts = [
            w for w in words
            if thick_lo <= float(w["x0"]) <= thick_hi
            and abs(float(w["top"]) - my) <= 7
            and re.match(r"^[\d〜～\-~]+$", w["text"])
        ]
        thick_word: dict | None = None
        thick_raw = None
        if thick_parts:
            thick_parts.sort(key=lambda w: float(w["x0"]))
            # テーパー表記が "180" "210" "~" のように数値とチルダが別語で
            # x が重なる場合がある。数値（2桁以上）だけを抽出し、複数あれば
            # 範囲として最大値を採れるよう "〜" で連結する。
            nums = [w["text"] for w in thick_parts if re.fullmatch(r"\d{2,3}", w["text"])]
            if nums:
                thick_raw = "〜".join(nums)
            else:
                thick_raw = "".join(w["text"] for w in thick_parts)
            thick_word = thick_parts[0]
        thickness, thick_disp = (_parse_thickness(thick_raw) if thick_raw else (None, None))
        # 厚み列のフォント/文字コードが不安定で "02〜000" "01〜800" のような
        # 化け値になり、現実離れした厚み (80mm未満 / 500mm超) になることがある。
        # その場合は符号名 (S18→180, CS25→250) から推定して置き換える。
        if thickness is None or not (80 <= thickness <= 500):
            est = _thickness_from_mark(mw["text"])
            if est is not None:
                thickness = est
                thick_disp = str(est) if not thick_raw else f"{thick_raw}→{est}(符号推定)"
            else:
                # 抽出値が壊れていて、かつ符号からも推定不可（CS2 のような
                # 1桁符号 等）の場合は厚みを不明扱いにする。
                # （壊れた値で偽の不一致を出さないため）
                thickness = None
                thick_disp = None

        def _rebar_at(y: float | None) -> list[str]:
            if y is None:
                return []
            vals: list[str] = []
            for w in words:
                if abs(float(w["top"]) - y) <= 3 and rebar_lo <= float(w["x0"]) <= rebar_hi:
                    vals.extend(_norm_rebar(t) for t in _SLAB_REBAR_RE.findall(w["text"]))
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
# 担当者によってブロック見出しの書き方が異なるため、見出し書式に依存せず、
# "lx = ..., t = NNNmm" の行（スラブ計算ブロックに必ず現れる）をアンカーに
# して抽出する。符号(mark)は直前の非空行から S/CS パターンで取り出す。

# 既知の見出しパターンから note を抽出するための補助（参考用）。
# パターンに合致しなくても抽出は通る。
_RE_SLAB_HEADER = re.compile(r"No\.\d+(?:-\d+)?[_ ]\s*([A-Z]+\d+[A-Z]?)\s*[（(]([^）)]*)[）)]")
_RE_SLAB_HEADER2 = re.compile(r"^\s*\d+(?:-\d+)?_([A-Z]+\d+[A-Z]?)_(.+?)\s*$")
_RE_SLAB_HEADER3 = re.compile(r"^\s*<\d+>\s*([A-Z]+\d+[A-Z]?)(?:[（(][^）)]*[）)])?\s+(.*)$")
# "t = 180mm" 形式と、mm 省略の "t = 180" 形式の両方に対応。
# 後者は "dt" や時刻表記との誤マッチを避けるため、続く文字が "," " " "/" "(" 等の
# 区切りであることを要求する。
_RE_T = re.compile(r"(?<![A-Za-z])t\s*=\s*(\d+)\s*(?:mm|(?=[\s,，)/]|$))")
_RE_FC = re.compile(r"Fc(\d+)")
_RE_SUPPORT = re.compile(r"支持条件：([^,、]+)")
# スラブ計算ブロックのアンカー: "lx = X.XXm" を含む行、または独立で "t = NNNmm" を含む行。
# Super Build/RC2次部材 形式の "Lx = NNN (cm)" や全角 "ｔ = NN (cm)" にも対応。
# "lx =" は短辺スパン。ただし "ly/lx = 1.30" のような辺長比の一部を
# 誤検出しないよう、直前が "/" や英字でない場合のみ短辺スパンとみなす。
_LX = r"(?<![/A-Za-z])lx\s*=\s*\d"
_RE_SLAB_ANCHOR = re.compile(rf"{_LX}|\bt\s*=\s*\d+\s*mm|\bLx\s*=\s*\d+\s*\(cm\)|ｔ\s*=\s*\d+\s*\(cm\)")
# 新ブロック開始とみなす主アンカー（lx= / Lx=(cm) / ｔ=(cm)）。
# 単独の "t = NNN mm" は lx= 行の折り返しであることがあるため主アンカーに含めない。
_RE_SLAB_PRIMARY_ANCHOR = re.compile(rf"{_LX}|\bLx\s*=\s*\d+\s*\(cm\)|ｔ\s*=\s*\d+\s*\(cm\)")
# Super Build/RC2次部材 のスラブ厚（cm単位、全角ｔ）
_RE_T_CM = re.compile(r"ｔ\s*=\s*(\d+)\s*\(cm\)")

# 補足・派生検討のブロック番号 "(34')" を検出する（プライム付き）。
# プライム文字は ASCII ' / 右シングルクォート ’ / プライム ′ を許容。
_RE_PRIME_BLOCK = re.compile(r"^\s*[\(（]\s*\d+\s*['’′]\s*[\)）]")

# Union System SS7 形式のスラブ1行: "S1← [ S1 ] [RSL X2 Y2 X3 Y3] 反転 短辺上 D13@200 ..."
# 行先頭の "S1←" の符号が図面に反映される「型符号」。"[ S1 ]" は計算上の ID で図面とは別。
_RE_SS7_SLAB_TYPE = re.compile(r"^\s*(C?S\d+[A-Za-z]?)\s*[←⇐]")
# SS7 の厚みは "t 200" 形式（mm無し）
_RE_SS7_T = re.compile(r"\bt\s+(\d{2,3})\b")


def _extract_mark_and_note_from_header(line: str) -> tuple[str | None, str | None]:
    """1行から (mark, note) を取り出す。

    既知の見出しパターンに合致すればそれを優先。合致しなくても
    最初に現れる S/CS パターンを mark として採用し、残りを note にする。
    """
    for pat in (_RE_SLAB_HEADER, _RE_SLAB_HEADER2, _RE_SLAB_HEADER3):
        m = pat.search(line)
        if m and _SLAB_MARK_RE.match(m.group(1)):
            return m.group(1), m.group(2)
    # 既知パターンに合致しない場合: 行内に出てくる最初の S/CS 符号を採る。
    # 行頭に丸数字（①②… / ㉑…）が符号に直接くっつく書式 "①CS11 （…）" に
    # 対応するため、先頭の丸数字をいったん除去してから分割する。
    _CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿"
    work = line.lstrip(_CIRCLED + " 　")
    # 区切り文字には半角/全角コロン（":" "："）と「.」（"1.S1" のような書式）も含める。
    # 例 "(1)S11：共用廊下" / "1.S1：一般階居室" / "①CS11 （…）" のような書式に対応。
    for tok in re.split(r"[\s,、・._（()）<>:：]+", work):
        if _SLAB_MARK_RE.match(tok):
            note = work.replace(tok, "", 1).strip(" 　_.（()）,、・-:：<>0123456789")
            return tok, (note or None)
    return None, None



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
    """計算書PDFからスラブを抽出する。

    見出し書式に依存せず、"lx = ..." または "t = NNNmm" を含む行を
    スラブ計算ブロックのアンカーとして扱う。符号は直前の非空行から
    S/CS パターンで取り出す。
    """
    slabs: dict[str, SlabMember] = {}
    for pd in get_pages(pdf_path):
        page_idx = pd.index
        # 「床のひび割れ」セクションは別フォーマットなので除外
        if "床のひび割れ" in pd.text:
            continue
        cur: dict | None = None
        line_groups = list(_group_lines(pd.words))
        for idx, lw in enumerate(line_groups):
            line = " ".join(w["text"] for w in lw)

            # アンカー行（lx=... or t=NNNmm）を起点として新ブロックを開始。
            # ただし "lx = …, t = 180mm, dt = 50mm" の1行が抽出時に2行へ
            # 折り返され、2行目が "t = 180mm, dt = 50mm" になると、これが
            # "t = NNN mm" として別アンカーに誤判定され、直前 lx= ブロックの
            # 複製（配筋なしの空検討）が作られてしまう。lx= や (cm) 形式で
            # 当たった行のみを「新ブロックの開始」とし、"t = NNN mm" だけで
            # 当たった継続行は、直前ブロックがまだ配筋を持たない場合は新
            # ブロックにせず厚み情報の補完として扱う。
            _is_primary_anchor = bool(_RE_SLAB_PRIMARY_ANCHOR.search(line))
            _only_t_mm_continuation = (
                not _is_primary_anchor
                and cur is not None
                and not (cur["top"] or cur["bottom"])
            )
            if _RE_SLAB_ANCHOR.search(line) and not _only_t_mm_continuation:
                mark = note = None
                header_bbox = None
                supplementary = False
                # 直前の非空行を数行遡って符号を含む見出しを探す
                # （"自主訂正No.X" 等の注記が間に挟まることがある）
                seen_non_empty = 0
                for back in range(idx - 1, -1, -1):
                    prev_line = " ".join(w["text"] for w in line_groups[back]).strip()
                    if not prev_line:
                        continue
                    seen_non_empty += 1
                    cand_mark, cand_note = _extract_mark_and_note_from_header(prev_line)
                    if cand_mark:
                        mark, note = cand_mark, cand_note
                        header_bbox = _span_bbox(line_groups[back])
                        # ブロック番号にプライム（"(34')"）が付く検討は、主検討
                        # （"(34)"）に対する補足・派生検討（先端庇など）。主検討の
                        # 配筋が代表値であり、補足検討の配筋を集約すると過剰な
                        # 配筋値が混入するため、補足検討フラグを立てる。
                        supplementary = bool(_RE_PRIME_BLOCK.match(prev_line))
                        break
                    if seen_non_empty >= 6:
                        break
                if not mark:
                    cur = None
                    continue
                # Super Build/RC2次部材 形式では "Lx = NNN (cm)" 行と
                # "ｔ = NN (cm)" 行が別行にあり、どちらも主アンカーに合致する。
                # 同一ブロック（同符号・同ページ・配筋未取得）で2本目以降の
                # アンカー行が来た場合は、新しい検討にせず情報の補完として扱う
                # （タイトルだけの空検討が量産されるのを防ぐ）。
                if (cur is not None and cur["mark"] == mark
                        and cur["page"] == page_idx
                        and not (cur["top"] or cur["bottom"])):
                    ab = _span_bbox(lw)
                    cur["anchor_bbox"] = _bbox_union([cur.get("anchor_bbox"), ab])
                    tm = _RE_T.search(line)
                    if tm and cur["t"] is None:
                        cur["t"] = int(tm.group(1))
                        tb = _thickness_word_bbox(lw)
                        if tb:
                            cur["bboxes"]["thickness"] = tb
                    else:
                        tcm = _RE_T_CM.search(line)
                        if tcm and cur["t"] is None:
                            cur["t"] = int(tcm.group(1)) * 10
                    fm = _RE_FC.search(line)
                    if fm and cur["fc"] is None:
                        cur["fc"] = f"Fc{fm.group(1)}"
                    sm = _RE_SUPPORT.search(line)
                    if sm and cur["support"] is None:
                        cur["support"] = sm.group(1)
                    _finalize_calc_slab(cur, slabs)
                    continue
                cur = {
                    "mark": mark,
                    "note": note,
                    "page": page_idx,
                    "t": None, "fc": None, "support": None,
                    "top": [], "bottom": [],
                    "bboxes": {},
                    "header_bbox": header_bbox,
                    # アンカー行（lx=/t= 行）自体の bbox。ヘッダ行が分割抽出されて
                    # 左端が欠けるケース（CS8）でも、部材全体枠がブロック本体の
                    # 左端まで届くように envelope に含める。
                    "anchor_bbox": _span_bbox(lw),
                    "supplementary": supplementary,
                }
                tm = _RE_T.search(line)
                if tm:
                    cur["t"] = int(tm.group(1))
                    tb = _thickness_word_bbox(lw)
                    if tb:
                        cur["bboxes"]["thickness"] = tb
                else:
                    # Super Build/RC2次部材: "ｔ = 20 (cm)" → 200mm
                    tcm = _RE_T_CM.search(line)
                    if tcm:
                        cur["t"] = int(tcm.group(1)) * 10
                fm = _RE_FC.search(line)
                if fm:
                    cur["fc"] = f"Fc{fm.group(1)}"
                sm = _RE_SUPPORT.search(line)
                if sm:
                    cur["support"] = sm.group(1)
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
            else:
                tcm = _RE_T_CM.search(line)
                if tcm and cur["t"] is None:
                    cur["t"] = int(tcm.group(1)) * 10
            fm = _RE_FC.search(line)
            if fm and cur["fc"] is None:
                cur["fc"] = f"Fc{fm.group(1)}"
            sm = _RE_SUPPORT.search(line)
            if sm and cur["support"] is None:
                cur["support"] = sm.group(1)
            # 配筋行のバリエーション:
            #   "上端筋 ..." (StructureSuite 標準)
            #   "上端 ..." (Super Build/RC2次部材)
            #   "配筋 上端 ..." (一部のスラブ計算書フォーマット)
            stripped = line.lstrip()
            if stripped.startswith("配筋"):
                stripped = stripped[2:].lstrip()
            if stripped.startswith("上端"):
                cur["top"] = [_norm_rebar(t) for t in _SLAB_REBAR_RE.findall(line)]
                rb = [w for w in lw if _SLAB_REBAR_RE.fullmatch(w["text"])]
                if rb:
                    cur["bboxes"]["top"] = _span_bbox(rb)
                _finalize_calc_slab(cur, slabs)
            elif stripped.startswith("下端"):
                cur["bottom"] = [_norm_rebar(t) for t in _SLAB_REBAR_RE.findall(line)]
                rb = [w for w in lw if _SLAB_REBAR_RE.fullmatch(w["text"])]
                if rb:
                    cur["bboxes"]["bottom"] = _span_bbox(rb)
                _finalize_calc_slab(cur, slabs)

        # SS7（Union System）形式のスラブを抽出
        _parse_ss7_slabs(line_groups, page_idx, slabs)
    return SlabSet(
        source=Source.CALC,
        file_name=pdf_path.name,
        slabs=list(slabs.values()),
    )


def _parse_ss7_slabs(line_groups: list[list[dict]], page_idx: int, slabs: dict) -> None:
    """SS7（Union System）形式のスラブを抽出する。

    1ブロック=4行程度の塊で、形式は:
        S1← [ S1 ] [RSL X2 Y2 X3 Y3] 反転 短辺上 D13@200 D13@200    MD ...
              二重上 1次=1                       無    下 D10@200    D10@200    MA ...
                  4辺固(RC規準)      w 7.1 t 200   長辺上 D10D13@250 D10D13@250 MD/MA ...
              Lx，Ly 3910 7700 λ 1.97 dt 47/46         下 D10@250    D10@250    たわみ ...

    符号は `[ MARK ]` から、厚みは `t NNN` (mm無し)、上端は短辺上＋長辺上の集合、
    下端は短辺と長辺の "下" の集合とする。
    """
    for idx, lw in enumerate(line_groups):
        line = " ".join(w["text"] for w in lw)
        m = _RE_SS7_SLAB_TYPE.match(line)
        if not m:
            continue
        mark = m.group(1)
        if mark in slabs:
            continue
        # 1ブロックは current_line から 5行先までスキャンする
        block_text = line
        for k in range(idx + 1, min(idx + 5, len(line_groups))):
            block_text += " " + " ".join(w["text"] for w in line_groups[k])
        # 厚み: "t 200" (mm無し)
        tm = _RE_SS7_T.search(block_text)
        thickness = int(tm.group(1)) if tm else None
        # 配筋: 短辺上 ... 下 ... 長辺上 ... 下 ...
        top_rebar: list[str] = []
        bottom_rebar: list[str] = []
        # 短辺・長辺の上下を分けて拾う
        for label, target in [("短辺上", top_rebar), ("長辺上", top_rebar)]:
            mm2 = re.search(rf"{label}\s+((?:[\sD0-9@]|D\d+@\d+)+?)(?=\s+(?:MD|MA|MD/MA|τ|たわみ|短辺|長辺|下|無)|$)", block_text)
            if mm2:
                target.extend(_norm_rebar(t) for t in _SLAB_REBAR_RE.findall(mm2.group(1)))
        # 下端は "下 D10@200" 形式（"下端" ではなく単独の "下"）。短辺と長辺で各1行。
        for mm2 in re.finditer(r"(?<![上端])\s下\s+((?:D\d+(?:D\d+)*@\d+\s*)+)", block_text):
            bottom_rebar.extend(_norm_rebar(t) for t in _SLAB_REBAR_RE.findall(mm2.group(1)))

        # 重複を取り除く（順序保持）
        def _dedup(xs: list[str]) -> list[str]:
            seen: set = set(); out: list[str] = []
            for x in xs:
                if x not in seen:
                    seen.add(x); out.append(x)
            return out
        top_rebar = _dedup(top_rebar)
        bottom_rebar = _dedup(bottom_rebar)

        # 異常厚みなら符号名から推定（既存のCID対策）
        if thickness is None or not (80 <= thickness <= 500):
            est = _thickness_from_mark(mark)
            if est is not None:
                thickness = est

        slabs[mark] = SlabMember(
            mark=mark,
            thickness=thickness,
            thickness_raw=str(thickness) if thickness else None,
            top_rebar=top_rebar,
            bottom_rebar=bottom_rebar,
            concrete_grade=None,
            support=None,
            source=Source.CALC,
            location=LocationHint(page=page_idx, bbox=_span_bbox(lw)),
            field_bboxes={"thickness": _span_bbox(lw)},
            note=None,
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
    anchor = cur.get("anchor_bbox")
    bboxes = dict(cur.get("bboxes", {}))  # フィールド枠はタイトのまま
    if existing is None:
        # 全体枠 = ヘッダ + アンカー行 + 各フィールドの和
        envelope = _bbox_union([header, anchor, *bboxes.values()])
        loc = LocationHint(page=cur["page"], bbox=envelope)
        study = SlabStudy(
            top_rebar=list(cur["top"]), bottom_rebar=list(cur["bottom"]),
            location=loc, note=cur["note"] or None,
            field_bboxes=dict(bboxes),
        )
        cur["_study"] = study
        slabs[mark] = SlabMember(
            mark=mark,
            thickness=cur["t"],
            thickness_raw=str(cur["t"]) if cur["t"] else None,
            top_rebar=list(cur["top"]),
            bottom_rebar=list(cur["bottom"]),
            concrete_grade=cur["fc"],
            support=cur["support"],
            source=Source.CALC,
            location=loc,
            field_bboxes=dict(bboxes),
            note=cur["note"] or None,
            studies=[study],
        )
    else:
        # 補足・派生検討（"(34')" 等）の配筋は主検討の代表値に集約しない。
        # 主検討（既存）の配筋を保持する。ただし補足検討の配筋が主検討と
        # 1つでも異なる場合は、安全側か否かに関わらず needs_review を立てて
        # 整合チェックで「要目視確認」を発出する（断面積による安全側判定は
        # 行わない＝補足検討に相違があれば必ず目視確認とする）。
        if cur.get("supplementary"):
            diff_vals = [v for v in cur["top"] if v not in existing.top_rebar]
            diff_vals += [v for v in cur["bottom"] if v not in existing.bottom_rebar]
            if diff_vals and not existing.needs_review:
                existing.needs_review = True
                existing.review_note = (
                    "補足検討（プライム付ブロック）の配筋が主検討と異なります"
                    f"（補足: {' / '.join(dict.fromkeys(diff_vals))}）。"
                    "計算書の各検討と図面を確認してください。"
                )
            # 集約はしないが、検討ブロックとしては記録して PDF照合・
            # 一括出力に全検討が表示されるようにする（CS8 のような
            # プライム付き補足検討が抽出されない問題への対応）。
            study = cur.get("_study")
            if study is None:
                env_s = _bbox_union([header, anchor, *bboxes.values()])
                study = SlabStudy(
                    location=LocationHint(page=cur["page"], bbox=env_s),
                    note=cur["note"] or None,
                )
                cur["_study"] = study
                existing.studies.append(study)
                if study.location is not None:
                    existing.extra_locations.append(study.location)
            study.top_rebar = list(cur["top"])
            study.bottom_rebar = list(cur["bottom"])
            study.field_bboxes = dict(bboxes)
            env_s = _bbox_union([header, anchor, *bboxes.values()])
            if env_s is not None and study.location is not None:
                study.location.bbox = env_s
            return
        # 検討ブロック単位で study を記録する。_finalize_calc_slab は1ブロック
        # につき複数回（アンカー/上端/下端）呼ばれるため、cur["_study"] で
        # 同一ブロックの study を使い回し、新規ブロックのときだけ追加する。
        study = cur.get("_study")
        if study is None:
            envelope2 = _bbox_union([header, anchor, *bboxes.values()])
            study = SlabStudy(
                location=LocationHint(page=cur["page"], bbox=envelope2),
                note=cur["note"] or None,
            )
            cur["_study"] = study
            existing.studies.append(study)
            if study.location is not None:
                existing.extra_locations.append(study.location)
        study.top_rebar = list(cur["top"])
        study.bottom_rebar = list(cur["bottom"])
        study.field_bboxes = dict(bboxes)
        # 検討ブロックの枠を、配筋行 bbox が揃うたびに拡張する（作成時は
        # ヘッダ＋厚みだけで小さいため、上端筋/下端筋まで届くよう更新）。
        env = _bbox_union([header, anchor, *bboxes.values()])
        if env is not None and study.location is not None:
            study.location.bbox = env  # extra_locations と同一オブジェクトなので両方更新される
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
        # 全体枠は新規に取れたフィールドだけを取り込んで拡張する。
        # ただし別ページのブロックとは統合しない（ページ跨ぎの枠は無意味なため）。
        if (existing.location is not None and new_bbs
                and existing.location.page == cur["page"]):
            nb = _bbox_union([existing.location.bbox, *new_bbs])
            if nb:
                existing.location = LocationHint(page=existing.location.page, bbox=nb)
