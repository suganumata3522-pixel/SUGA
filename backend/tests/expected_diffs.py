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
            ("構造図のみ", "FG1"), ("構造図のみ", "FG1A"), ("構造図のみ", "FG1B"),
            ("構造図のみ", "FG2"), ("構造図のみ", "FG2A"), ("構造図のみ", "FG2B"),
            ("構造図のみ", "FG3"), ("構造図のみ", "FG4"), ("構造図のみ", "FG4A"),
            ("構造図のみ", "FG5"), ("構造図のみ", "FG6"), ("構造図のみ", "FG6A"),
            ("構造図のみ", "FG7"), ("構造図のみ", "FG8"), ("構造図のみ", "FG9"),
            ("構造図のみ", "FB2"), ("構造図のみ", "FCG1"),
        },
    },
    "project2": {
        "drawing_count": 16,
        "calc_count": 19,
        # B1/B3A は位置ラベルが通り芯を列挙する連梁。通り芯ごとに配筋が
        # 異なり自動照合が難しいため「要目視確認」とする。
        # WB1A/CB3/CB4 は計算書側に該当ブロックが無い。
        # FB系/FCG系 は計算書に基礎梁ブロックがあるが構造図(二次部材リスト)に無いため
        # 「計算書のみ」となる（基礎部材除外フィルタの対象）。
        "diff_keys": {
            ("要目視確認", "B1"),
            ("要目視確認", "B3A"),
            ("構造図のみ", "WB1A"),
            ("構造図のみ", "CB3"),
            ("構造図のみ", "CB4"),
            ("計算書のみ", "FB1"),
            ("計算書のみ", "FB2"),
            ("計算書のみ", "FB3"),
            ("計算書のみ", "FB5"),
            ("計算書のみ", "FCG2"),
            ("計算書のみ", "FCG3"),
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
            ("構造図のみ", "CS25A"),
            ("構造図のみ", "CS30"),
            ("計算書のみ", "CS21A"),
        },
    },
}
