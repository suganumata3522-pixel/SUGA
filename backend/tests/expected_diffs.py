"""期待結果（ゴールデン値）。

各物件サンプルの想定差分を固定し、パーサ改修で意図せず壊れていないかを継続的に確認する。
構造図と計算書 PDF はそれぞれ tests/fixtures/<案件名>/{drawing.pdf, calc.pdf} に格納。

差分は (kind, mark) のセットで比較する（fields の詳細までは固定しない）。
新たに本物の不整合が見つかった場合は手動で expected を更新すること。
"""

EXPECTED: dict[str, dict] = {
    "yahagi_S_secondary": {
        "drawing_count": 21,
        "calc_count": 24,
        "diff_keys": {
            ("配筋不一致", "CG1A"),
            ("計算書のみ", "FB1"),
            ("計算書のみ", "FCG2"),
            ("計算書のみ", "FCG3"),
        },
    },
    "yahagi_S_with_foundation": {
        "drawing_count": 41,
        "calc_count": 24,
        "diff_keys": {
            ("配筋不一致", "CG1A"),
            # 17件の「図のみ」FG系/FB2/FCG1 (計算書の対象範囲外)
            ("図のみ", "FG1"), ("図のみ", "FG1A"), ("図のみ", "FG1B"),
            ("図のみ", "FG2"), ("図のみ", "FG2A"), ("図のみ", "FG2B"),
            ("図のみ", "FG3"), ("図のみ", "FG4"), ("図のみ", "FG4A"),
            ("図のみ", "FG5"), ("図のみ", "FG6"), ("図のみ", "FG6A"),
            ("図のみ", "FG7"), ("図のみ", "FG8"), ("図のみ", "FG9"),
            ("図のみ", "FB2"), ("図のみ", "FCG1"),
        },
    },
    "project2": {
        "drawing_count": 16,
        "calc_count": 13,
        # B3A は 左端/中央/右端(連続端) の3位置レイアウト。位置ラベルを
        # マークへ DP 割り当てすることで3位置とも抽出でき、計算書と一致する。
        # WB1A/CB3/CB4 は計算書側に該当ブロックが無い。
        "diff_keys": {
            ("図のみ", "WB1A"),
            ("図のみ", "CB3"),
            ("図のみ", "CB4"),
        },
    },
}

# スラブ整合チェックのゴールデン値。
# tests/fixtures/<案件名>/{drawing.pdf, calc.pdf} を parse_drawing_slabs /
# parse_calc_slabs にかけ、compare_slabs の (kind, mark) を比較する。
EXPECTED_SLAB: dict[str, dict] = {
    "project3_slab": {
        "drawing_slab_count": 20,
        "calc_slab_count": 19,
        "diff_keys": {
            ("スラブ配筋不一致", "S25A"),
            ("図のみ", "CS25A"),
            ("図のみ", "CS30"),
            ("計算書のみ", "CS21A"),
        },
    },
}
