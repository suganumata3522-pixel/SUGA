"""SUGA 作業手順ガイド PDF を生成する。

PyMuPDF の組み込み日本語フォント (fontname="japan") を使い、
画面モックアップ付きの操作ガイドを作る。
出力: SUGA_操作ガイド.pdf
"""
from __future__ import annotations

import fitz

BLUE = (0.145, 0.388, 0.922)
DARK = (0.12, 0.16, 0.22)
GRAY = (0.42, 0.45, 0.50)
LIGHT = (0.95, 0.97, 1.0)
BORDER = (0.80, 0.84, 0.90)
GREEN = (0.02, 0.47, 0.34)
RED = (0.73, 0.07, 0.07)
ORANGE = (0.71, 0.27, 0.05)

JP = "japan"


def text(page, x, y, s, size=10, color=DARK, font=JP, bold=False):
    page.insert_text((x, y), s, fontsize=size, color=color,
                     fontname=font, render_mode=2 if bold else 0,
                     border_width=0.3 if bold else 0)


def box(page, rect, fill=None, stroke=BORDER, width=0.8, radius=0):
    r = fitz.Rect(rect)
    page.draw_rect(r, color=stroke, fill=fill, width=width)


def heading(page, x, y, no, s):
    page.draw_circle((x + 8, y - 4), 9, color=None, fill=BLUE)
    text(page, x + 4.5, y - 0.5, no, size=11, color=(1, 1, 1), bold=True)
    text(page, x + 24, y, s, size=14, color=BLUE, bold=True)


def make() -> str:
    doc = fitz.open()

    # ===== ページ1: アプリの使い方 =====
    p = doc.new_page(width=595, height=842)  # A4
    M = 48
    text(p, M, 60, "SUGA 操作ガイド", size=22, color=BLUE, bold=True)
    text(p, M, 80, "構造図・計算書 整合チェックツール — 画面の使い方", size=11, color=GRAY)
    p.draw_line((M, 92), (595 - M, 92), color=BLUE, width=1.5)

    # 4ステップ帯
    y = 116
    box(p, (M, y, 595 - M, y + 38), fill=LIGHT, stroke=(0.75, 0.85, 1.0))
    steps = ["案件を作成", "PDFを2つ選ぶ", "チェック実行", "差分を確認"]
    sx = M + 16
    for i, s in enumerate(steps, 1):
        p.draw_circle((sx + 8, y + 19), 9, fill=BLUE)
        text(p, sx + 4.5, y + 23, str(i), size=11, color=(1, 1, 1), bold=True)
        text(p, sx + 22, y + 23, s, size=10, color=(0.12, 0.23, 0.54), bold=True)
        if i < 4:
            text(p, sx + 108, y + 23, "→", size=12, color=BLUE)
        sx += 130

    # 画面モックアップ
    y = 180
    text(p, M, y, "■ 画面イメージ", size=11, color=DARK, bold=True)
    mock = fitz.Rect(M, y + 8, 595 - M, y + 300)
    box(p, mock, fill=(0.98, 0.98, 0.99), stroke=BORDER)
    mx = M + 14
    # ヘッダ
    text(p, mx, y + 30, "SUGA", size=15, color=BLUE, bold=True)
    text(p, mx + 52, y + 30, "構造図・計算書 整合チェックツール", size=8, color=GRAY)
    # カード1
    c1 = fitz.Rect(mx, y + 44, 595 - M - 14, y + 96)
    box(p, c1, fill=(1, 1, 1), stroke=BORDER)
    p.draw_circle((mx + 18, y + 60), 7, fill=BLUE)
    text(p, mx + 15, y + 63, "1", size=8, color=(1, 1, 1), bold=True)
    text(p, mx + 32, y + 63, "案件（プロジェクト）", size=9, color=BLUE, bold=True)
    box(p, (mx + 14, y + 72, mx + 230, y + 88), fill=(1, 1, 1))
    text(p, mx + 20, y + 83, "案件名（例: ○○マンション 新築工事）", size=7, color=GRAY)
    box(p, (mx + 238, y + 72, mx + 300, y + 88), fill=BLUE, stroke=BLUE)
    text(p, mx + 252, y + 83, "新規作成", size=7, color=(1, 1, 1))
    # カード2
    c2 = fitz.Rect(mx, y + 104, 595 - M - 14, y + 180)
    box(p, c2, fill=(1, 1, 1), stroke=BORDER)
    p.draw_circle((mx + 18, y + 120), 7, fill=BLUE)
    text(p, mx + 15, y + 123, "2", size=8, color=(1, 1, 1), bold=True)
    text(p, mx + 32, y + 123, "PDFアップロード", size=9, color=BLUE, bold=True)
    for i, lab in enumerate(["構造図PDF（二次部材リスト）", "計算書PDF（StructureSuite）"]):
        yy = y + 134 + i * 20
        box(p, (mx + 14, yy, mx + 180, yy + 15), fill=(0.96, 0.96, 0.97))
        text(p, mx + 20, yy + 11, lab, size=6.5, color=GRAY)
        text(p, mx + 188, yy + 11, "ファイルを選択", size=6.5, color=BLUE)
    box(p, (mx + 14, y + 176 - 0, mx + 110, y + 192), fill=BLUE, stroke=BLUE)
    text(p, mx + 30, y + 187, "整合チェック実行", size=7.5, color=(1, 1, 1), bold=True)
    # カード3（結果）
    c3 = fitz.Rect(mx, y + 200, 595 - M - 14, y + 280)
    box(p, c3, fill=(1, 1, 1), stroke=BORDER)
    p.draw_circle((mx + 18, y + 216), 7, fill=BLUE)
    text(p, mx + 15, y + 219, "3", size=8, color=(1, 1, 1), bold=True)
    text(p, mx + 32, y + 219, "整合チェック結果（小梁／スラブ）", size=9, color=BLUE, bold=True)
    # 結果テーブル風
    cols = [mx + 14, mx + 90, mx + 150, mx + 320, 595 - M - 14]
    rows = [
        ("配筋不一致", "CG1A", "STP 図2-D13@200 / 計算5-D13@200", RED),
        ("要目視確認", "B3A", "外端/中央/連続端の3位置 — PDFで確認", ORANGE),
        ("図のみ", "CB3", "計算書側に該当なし", GRAY),
    ]
    text(p, cols[0] + 2, y + 233, "種別", size=6.5, color=DARK, bold=True)
    text(p, cols[1] + 2, y + 233, "符号", size=6.5, color=DARK, bold=True)
    text(p, cols[2] + 2, y + 233, "差分内容", size=6.5, color=DARK, bold=True)
    text(p, cols[3] + 2, y + 233, "PDF確認", size=6.5, color=DARK, bold=True)
    for i, (kind, mark, desc, col) in enumerate(rows):
        ry = y + 240 + i * 13
        text(p, cols[0] + 2, ry + 9, kind, size=6.5, color=col, bold=True)
        text(p, cols[1] + 2, ry + 9, mark, size=6.5, color=DARK)
        text(p, cols[2] + 2, ry + 9, desc, size=6.5, color=GRAY)
        box(p, (cols[3] + 2, ry + 1, cols[3] + 30, ry + 11), stroke=(0.58, 0.77, 0.99))
        text(p, cols[3] + 8, ry + 9, "図", size=6, color=BLUE)
        box(p, (cols[3] + 34, ry + 1, cols[3] + 70, ry + 11), stroke=(0.58, 0.77, 0.99))
        text(p, cols[3] + 40, ry + 9, "計算", size=6, color=BLUE)

    # 各ステップ説明
    y = 500
    items = [
        ("1", "案件を作成する", "物件ごとに案件名を入力し「新規作成」。一覧から「選ぶ」で対象を切り替え。"),
        ("2", "PDFを2つアップロード", "構造図PDF（二次部材リスト）と計算書PDF（StructureSuite）を選択。"),
        ("3", "「整合チェック実行」を押す", "解析に20〜30秒かかります。終わると小梁・スラブの差分が表示されます。"),
        ("4", "差分を確認する", "各行の「図」「計算」ボタンで元PDFの該当箇所がオレンジ枠付きで開きます。"),
    ]
    for no, t, d in items:
        p.draw_circle((M + 8, y - 4), 9, fill=BLUE)
        text(p, M + 4.5, y - 0.5, no, size=11, color=(1, 1, 1), bold=True)
        text(p, M + 26, y, t, size=11, color=DARK, bold=True)
        text(p, M + 26, y + 15, d, size=9, color=GRAY)
        y += 38

    # 差分種別の凡例
    box(p, (M, y, 595 - M, y + 78), fill=(0.99, 0.98, 0.95), stroke=(0.92, 0.86, 0.7))
    text(p, M + 12, y + 18, "差分種別の見かた", size=10, color=DARK, bold=True)
    legend = [
        ("配筋不一致 / 断面幅B不一致", "図と計算書で値が食い違う。要修正候補。", RED),
        ("要目視確認", "ツールで確定できない（3位置レイアウト等）。PDFで目視確認。", ORANGE),
        ("図のみ / 計算書のみ", "片方にしか無い符号。基礎部材などはフィルタで除外可。", GRAY),
    ]
    ly = y + 34
    for name, desc, col in legend:
        text(p, M + 16, ly, "●", size=8, color=col)
        text(p, M + 28, ly, name, size=8.5, color=col, bold=True)
        text(p, M + 180, ly, desc, size=8.5, color=GRAY)
        ly += 15

    text(p, M, 812, "SUGA 操作ガイド  —  1 / 2", size=8, color=GRAY)

    # ===== ページ2: 導入・配布 =====
    p = doc.new_page(width=595, height=842)
    text(p, M, 60, "導入・配布ガイド", size=22, color=BLUE, bold=True)
    text(p, M, 80, "「あなたの作業」— アプリを社内に配るまでの手順", size=11, color=GRAY)
    p.draw_line((M, 92), (595 - M, 92), color=BLUE, width=1.5)

    y = 124
    heading(p, M, y, "1", "ビルド担当者の作業（1人が1回だけ）")
    text(p, M, y + 22, "SUGA.exe を作成します。Windows PC に下記をインストールしておきます。", size=9.5, color=DARK)
    reqs = [
        "Python 3.11 以上 … python.org からダウンロード（「Add Python to PATH」にチェック）",
        "Node.js 20 以上 … nodejs.org の LTS 版",
    ]
    yy = y + 40
    for r in reqs:
        text(p, M + 14, yy, "・" + r, size=9, color=GRAY)
        yy += 16
    box(p, (M, yy + 4, 595 - M, yy + 52), fill=(0.96, 0.98, 0.96), stroke=(0.7, 0.85, 0.7))
    text(p, M + 12, yy + 22, "手順", size=9.5, color=GREEN, bold=True)
    text(p, M + 12, yy + 38, "scripts\\build_exe.bat をダブルクリック → 5〜10分で", size=9, color=DARK)
    text(p, M + 12, yy + 50, "backend\\dist\\SUGA.exe が生成されます。", size=9, color=DARK)

    y = 320
    heading(p, M, y, "2", "動作確認")
    checks = [
        "SUGA.exe をダブルクリック → 数秒でブラウザが自動で開く",
        "案件を作成し、構造図・計算書PDFをアップロード",
        "「整合チェック実行」→ 小梁・スラブの差分が表示されるか確認",
        "差分行の「図」「計算」ボタンでPDFハイライトが出るか確認",
        "終了はコンソール窓（黒い画面）を閉じるだけ",
    ]
    yy = y + 22
    for c in checks:
        text(p, M + 14, yy, "□ " + c, size=9, color=DARK)
        yy += 17

    y = 452
    heading(p, M, y, "3", "配布（各自のPCで使う）")
    text(p, M, y + 22, "SUGA.exe を 1 ファイルだけ社内共有フォルダ等に置き、各自がコピーして使います。", size=9.5, color=DARK)
    dist = [
        "利用者のPCに Python や Docker は不要",
        "SUGA.exe をダブルクリックするだけで起動",
        "データ（案件・PDF）は exe と同じ場所の SUGA-data フォルダに保存される",
        "別PDFで使う場合も同じ操作。案件ごとに分けて管理できる",
    ]
    yy = y + 40
    for d in dist:
        text(p, M + 14, yy, "・" + d, size=9, color=GRAY)
        yy += 16

    box(p, (M, yy + 8, 595 - M, yy + 56), fill=(1.0, 0.97, 0.97), stroke=(0.9, 0.7, 0.7))
    text(p, M + 12, yy + 26, "うまくいかないとき", size=9.5, color=RED, bold=True)
    text(p, M + 12, yy + 42, "build_exe.bat が途中で止まったら、黒い画面の文字をコピーして開発担当へ連絡。", size=9, color=DARK)

    text(p, M, 812, "SUGA 操作ガイド  —  2 / 2", size=8, color=GRAY)

    out = "SUGA_操作ガイド.pdf"
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    print("生成:", make())
