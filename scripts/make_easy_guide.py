"""SUGA かんたん操作ガイド（初心者向け・図解）PDF を生成する。

PyMuPDF の組み込み日本語フォントで、画面モックアップ・矢印・
「ここをクリック」吹き出し付きのビジュアルガイドを作る。
出力: SUGA_かんたんガイド.pdf
"""
from __future__ import annotations

import fitz

# 色
BLUE = (0.145, 0.388, 0.922)
DARKBLUE = (0.12, 0.23, 0.54)
DARK = (0.13, 0.16, 0.22)
GRAY = (0.45, 0.48, 0.53)
LGRAY = (0.90, 0.91, 0.93)
LIGHT = (0.95, 0.97, 1.0)
BORDER = (0.78, 0.82, 0.88)
RED = (0.86, 0.15, 0.15)
YELLOW = (1.0, 0.96, 0.78)
YELLOWB = (0.85, 0.7, 0.2)
GREEN = (0.06, 0.5, 0.32)
WHITE = (1, 1, 1)
TITLEBAR = (0.86, 0.88, 0.92)

JP = "japan"
W, H = 595, 842
M = 42


def t(p, x, y, s, size=10, color=DARK, bold=False, font=JP):
    # 組み込み日本語フォントには太字が無く、render_mode による疑似ボールドは
    # 漢字が潰れるため使わない。強調は色・サイズで表現する。
    p.insert_text((x, y), s, fontsize=size, color=color, fontname=font)


def tc(p, cx, y, s, size=10, color=DARK, bold=False):
    """中央寄せテキスト（日本語幅を概算）。"""
    w = len(s) * size * 0.95
    t(p, cx - w / 2, y, s, size, color, bold)


def rect(p, r, fill=None, stroke=BORDER, width=0.8, radius=0):
    # PyMuPDF の draw_rect の radius は 0〜0.5 の比率指定のため、
    # 見た目の角丸は使わず常に直角で描く（ガイド用途には十分）。
    p.draw_rect(fitz.Rect(r), color=stroke, fill=fill, width=width)


def window(p, r, title):
    """ウィンドウ風の枠（タイトルバー付き）。"""
    rr = fitz.Rect(r)
    rect(p, rr, fill=WHITE, stroke=(0.6, 0.63, 0.68), width=1)
    bar = fitz.Rect(rr.x0, rr.y0, rr.x1, rr.y0 + 20)
    p.draw_rect(bar, fill=TITLEBAR, color=(0.6, 0.63, 0.68), width=1)
    for i, c in enumerate([(1, 0.37, 0.34), (1, 0.74, 0.18), (0.2, 0.78, 0.35)]):
        p.draw_circle((rr.x0 + 12 + i * 13, rr.y0 + 10), 4, fill=c, color=None)
    t(p, rr.x0 + 52, rr.y0 + 14, title, size=8, color=GRAY)
    return fitz.Rect(rr.x0, rr.y0 + 20, rr.x1, rr.y1)


def cursor(p, x, y):
    """マウスカーソル（矢印）を描く。"""
    pts = [(x, y), (x, y + 16), (x + 4, y + 12), (x + 7, y + 18),
           (x + 9.5, y + 17), (x + 6.5, y + 11), (x + 11, y + 11)]
    p.draw_polyline(pts, color=(0, 0, 0), fill=WHITE, width=1.2, closePath=True)


def redring(p, cx, cy, rx, ry=None):
    """強調の赤い楕円。"""
    ry = ry or rx
    p.draw_oval(fitz.Rect(cx - rx, cy - ry, cx + rx, cy + ry), color=RED, width=2.2)


def callout(p, x, y, w, lines, point):
    """黄色い吹き出し。point=(px,py) へ線を引く。"""
    h = 14 + len(lines) * 13
    box = fitz.Rect(x, y, x + w, y + h)
    p.draw_rect(box, fill=YELLOW, color=YELLOWB, width=1.2)
    # 引き出し線
    p.draw_line((x + w / 2, y + h), point, color=YELLOWB, width=1.4)
    p.draw_circle(point, 3, fill=RED, color=None)
    for i, ln in enumerate(lines):
        t(p, x + 10, y + 17 + i * 13, ln, size=8.5, color=DARK, bold=(i == 0))


def stepnum(p, x, y, n, r=11):
    p.draw_circle((x, y), r, fill=RED, color=None)
    tc(p, x, y + 4, str(n), size=13, color=WHITE, bold=True)


def pagefooter(p, page_no, total):
    t(p, M, H - 30, "SUGA かんたんガイド", size=8, color=GRAY)
    t(p, W - M - 40, H - 30, f"{page_no} / {total}", size=8, color=GRAY)


def header(p, title, subtitle=""):
    p.draw_rect(fitz.Rect(0, 0, W, 56), fill=BLUE, color=None)
    t(p, M, 36, title, size=18, color=WHITE, bold=True)
    if subtitle:
        t(p, M + 6, 50, subtitle, size=9, color=(0.85, 0.92, 1.0))


def make() -> str:
    doc = fitz.open()
    TOTAL = 6

    # ============ ページ1: 表紙・全体像 ============
    p = doc.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(0, 0, W, H), fill=(0.97, 0.98, 1.0), color=None)
    p.draw_rect(fitz.Rect(0, 0, W, 150), fill=BLUE, color=None)
    tc(p, W / 2, 70, "SUGA", size=44, color=WHITE, bold=True)
    tc(p, W / 2, 100, "かんたん操作ガイド", size=20, color=WHITE, bold=True)
    tc(p, W / 2, 128, "構造図と計算書の整合チェックツール", size=11, color=(0.85, 0.92, 1.0))

    tc(p, W / 2, 200, "このガイドでわかること", size=14, color=BLUE, bold=True)

    # 2人の役割
    y = 230
    # IT担当
    b1 = fitz.Rect(M, y, W / 2 - 8, y + 150)
    rect(p, b1, fill=WHITE, stroke=BORDER, width=1, radius=8)
    tc(p, (b1.x0 + b1.x1) / 2, y + 28, "IT担当の人", size=12, color=GRAY, bold=True)
    tc(p, (b1.x0 + b1.x1) / 2, y + 44, "（最初の1回だけ）", size=8, color=GRAY)
    p.draw_line((b1.x0 + 16, y + 56), (b1.x1 - 16, y + 56), color=LGRAY, width=1)
    for i, s in enumerate(["アプリ本体（SUGA.exe）", "を作って、みんなに配る", "", "→ ガイドの 6ページ目"]):
        tc(p, (b1.x0 + b1.x1) / 2, y + 78 + i * 16, s, size=9,
           color=GRAY if i < 3 else BLUE)
    # あなた
    b2 = fitz.Rect(W / 2 + 8, y, W - M, y + 150)
    rect(p, b2, fill=LIGHT, stroke=BLUE, width=1.6, radius=8)
    tc(p, (b2.x0 + b2.x1) / 2, y + 28, "あなた（使う人）", size=12, color=BLUE, bold=True)
    tc(p, (b2.x0 + b2.x1) / 2, y + 44, "（毎回の作業）", size=8, color=BLUE)
    p.draw_line((b2.x0 + 16, y + 56), (b2.x1 - 16, y + 56), color=(0.75, 0.85, 1.0), width=1)
    for i, s in enumerate(["SUGA.exe をダブルクリック", "PDFをドラッグ＆ドロップ", "ボタンを押す → 結果を見る", "", "→ ガイドの 2〜5ページ目"]):
        tc(p, (b2.x0 + b2.x1) / 2, y + 76 + i * 15, s, size=9,
           color=DARKBLUE if i < 4 else BLUE, bold=(i < 3))

    # 大事なお知らせ
    y = 412
    note = fitz.Rect(M, y, W - M, y + 96)
    rect(p, note, fill=YELLOW, stroke=YELLOWB, width=1.2, radius=8)
    t(p, M + 16, y + 24, "★ 大事なこと", size=11, color=DARK, bold=True)
    for i, s in enumerate([
        "「SUGA.exe を作る」作業（6ページ目）は、パソコンに詳しい人向けです。",
        "むずかしいと感じたら、社内のIT担当の人に「1回だけ」おねがいしてください。",
        "あなたが毎回やるのは「できあがった SUGA.exe を使う」（2〜5ページ目）だけです。",
    ]):
        t(p, M + 16, y + 44 + i * 16, s, size=9, color=DARK)

    # 使う流れ
    y = 540
    tc(p, W / 2, y, "毎回の作業の流れ（かんたん4ステップ）", size=12, color=BLUE, bold=True)
    y += 22
    flow = ["SUGA.exe を\nダブルクリック", "PDFをここへ\nドラッグ", "整合チェック\n実行", "結果を見る\n（PDFで照合）"]
    bw = (W - 2 * M - 3 * 24) / 4
    for i, s in enumerate(flow):
        bx = M + i * (bw + 24)
        bb = fitz.Rect(bx, y, bx + bw, y + 70)
        rect(p, bb, fill=WHITE, stroke=BLUE, width=1, radius=6)
        stepnum(p, bx + bw / 2, y + 18, i + 1, r=10)
        for j, line in enumerate(s.split("\n")):
            tc(p, bx + bw / 2, y + 42 + j * 13, line, size=8.5, color=DARK)
        if i < 3:
            t(p, bx + bw + 7, y + 40, "→", size=14, color=BLUE)

    pagefooter(p, 1, TOTAL)

    # ============ ページ2: SUGA.exe を起動する ============
    p = doc.new_page(width=W, height=H)
    header(p, "【使い方 1】 アプリを起動する", "SUGA.exe をダブルクリックするだけ")

    t(p, M, 86, "手順1  パソコンの中の「SUGA.exe」をさがします。", size=11, color=DARK, bold=True)
    t(p, M, 104, "（IT担当の人からもらった場所。デスクトップや共有フォルダなど）", size=9, color=GRAY)

    # フォルダ画面モックアップ
    win = window(p, (M, 120, W - M, 290), "フォルダ")
    # ファイルアイコン3つ
    files = [("メモ.txt", LGRAY), ("SUGA.exe", (0.8, 0.9, 1.0)), ("写真.png", LGRAY)]
    fx = win.x0 + 60
    for i, (name, col) in enumerate(files):
        ix = fx + i * 150
        # アイコン
        rect(p, (ix, win.y0 + 36, ix + 46, win.y0 + 90), fill=col,
             stroke=(0.55, 0.6, 0.7), width=1, radius=4)
        if name == "SUGA.exe":
            tc(p, ix + 23, win.y0 + 68, "SUGA", size=9, color=BLUE, bold=True)
        tc(p, ix + 23, win.y0 + 104, name, size=8,
           color=DARK if name == "SUGA.exe" else GRAY,
           bold=(name == "SUGA.exe"))
    # SUGA.exe を強調
    sx = fx + 150 + 23
    redring(p, sx, win.y0 + 63, 40, 46)
    cursor(p, sx + 6, win.y0 + 58)
    callout(p, sx + 40, win.y0 + 4, 200,
            ["ここを「ダブルクリック」", "（すばやく2回クリック）"],
            (sx + 12, win.y0 + 60))

    t(p, M, 320, "手順2  少し待つと、自動でブラウザ（インターネットを見る画面）が開きます。", size=11, color=DARK, bold=True)

    # ブラウザが開くイメージ
    win2 = window(p, (M, 336, W - M, 540), "ブラウザ")
    # アドレスバー
    rect(p, (win2.x0 + 12, win2.y0 + 10, win2.x1 - 12, win2.y0 + 28),
         fill=(0.96, 0.96, 0.97), stroke=BORDER)
    t(p, win2.x0 + 20, win2.y0 + 23, "127.0.0.1:8000", size=8, color=GRAY)
    # アプリ画面（簡易）
    t(p, win2.x0 + 20, win2.y0 + 56, "SUGA", size=14, color=BLUE)
    t(p, win2.x0 + 92, win2.y0 + 56, "構造図・計算書 整合チェックツール", size=8, color=GRAY)
    rect(p, (win2.x0 + 20, win2.y0 + 70, win2.x1 - 20, win2.y0 + 92),
         fill=LIGHT, stroke=(0.75, 0.85, 1.0))
    t(p, win2.x0 + 30, win2.y0 + 84, "1 案件作成  →  2 PDFをえらぶ  →  3 チェック  →  4 結果", size=8, color=DARKBLUE)
    rect(p, (win2.x0 + 20, win2.y0 + 100, win2.x1 - 20, win2.y0 + 150),
         fill=WHITE, stroke=BORDER)
    t(p, win2.x0 + 32, win2.y0 + 120, "この画面が出れば起動成功です。", size=9, color=GREEN, bold=True)
    t(p, win2.x0 + 32, win2.y0 + 136, "次のページへ進んでください。", size=9, color=DARK)

    # 注意
    nb = fitz.Rect(M, 556, W - M, 620)
    rect(p, nb, fill=YELLOW, stroke=YELLOWB, width=1, radius=6)
    t(p, M + 14, 576, "● 黒い画面（コンソール）も一緒に出ますが、閉じないでください。", size=9, color=DARK)
    t(p, M + 14, 594, "  閉じるとアプリが止まります。使い終わったら閉じてOKです。", size=9, color=DARK)
    t(p, M + 14, 610, "● ブラウザが自動で開かないときは、別ページの案内を参照してください。", size=9, color=DARK)

    pagefooter(p, 2, TOTAL)

    # ============ ページ3: PDFを入れる ============
    p = doc.new_page(width=W, height=H)
    header(p, "【使い方 2】 PDFを入れる", "構造図・計算書PDFをドラッグ＆ドロップ")

    t(p, M, 88, "手順1  PDFファイルを、画面の枠の中へドラッグして放します。", size=11, color=DARK, bold=True)
    t(p, M, 106, "（クリックしてファイルを選んでもOK。複数ファイルもまとめて入れられます）", size=9, color=GRAY)

    win = window(p, (M, 122, W - M, 320), "ブラウザ - SUGA")
    rect(p, (win.x0 + 14, win.y0 + 12, win.x1 - 14, win.y1 - 12),
         fill=WHITE, stroke=BORDER)
    t(p, win.x0 + 26, win.y0 + 32, "PDFを入れる", size=10, color=BLUE, bold=True)
    # 2つのドロップゾーン
    zone_titles = ["構造図PDF（二次部材リスト）", "計算書PDF（StructureSuite）"]
    zw = (win.x1 - win.x0 - 52 - 16) / 2
    for i, zt in enumerate(zone_titles):
        zx = win.x0 + 26 + i * (zw + 16)
        t(p, zx, win.y0 + 52, zt, size=8, color=DARK, bold=True)
        dz = fitz.Rect(zx, win.y0 + 58, zx + zw, win.y0 + 130)
        p.draw_rect(dz, fill=(0.98, 0.98, 0.99), color=(0.55, 0.6, 0.7),
                    width=1.2, dashes="[3 2] 0")
        tc(p, zx + zw / 2, win.y0 + 86, "＋", size=18, color=(0.6, 0.66, 0.75))
        tc(p, zx + zw / 2, win.y0 + 102, "ここにPDFを", size=7.5, color=GRAY)
        tc(p, zx + zw / 2, win.y0 + 114, "ドラッグ＆ドロップ", size=7.5, color=GRAY)
        stepnum(p, zx + 6, win.y0 + 64, i + 1, r=9)
    # 構造図ゾーンに「ドラッグ中のPDF」を表現
    z1x = win.x0 + 26
    drag = fitz.Rect(z1x + zw - 30, win.y0 + 92, z1x + zw + 36, win.y0 + 120)
    p.draw_rect(drag, fill=(1, 0.9, 0.75), color=(0.85, 0.6, 0.2), width=1)
    tc(p, (drag.x0 + drag.x1) / 2, win.y0 + 109, "S4001.pdf", size=6.5, color=DARK)
    cursor(p, drag.x1 - 16, win.y0 + 110)
    callout(p, win.x0 + 60, win.y0 + 138, 240,
            ["PDFファイルをマウスでつかんで", "枠の中まで運んで放す（ドロップ）"],
            (z1x + zw / 2, win.y0 + 120))

    t(p, M, 348, "手順2  入れ終わったら「整合チェック実行」ボタンを押します。", size=11, color=DARK, bold=True)

    win2 = window(p, (M, 364, W - M, 500), "ブラウザ - SUGA")
    rect(p, (win2.x0 + 14, win2.y0 + 12, win2.x1 - 14, win2.y1 - 12),
         fill=WHITE, stroke=BORDER)
    # 入れたファイル一覧の例
    t(p, win2.x0 + 26, win2.y0 + 32, "入れたPDF（例）", size=8.5, color=DARK, bold=True)
    for i, fn in enumerate(["S4001.pdf", "計算書.pdf"]):
        fy = win2.y0 + 40 + i * 18
        fb = fitz.Rect(win2.x0 + 26, fy, win2.x0 + 200, fy + 14)
        rect(p, fb, fill=(0.95, 0.96, 0.97), stroke=BORDER)
        t(p, fb.x0 + 8, fy + 10, fn, size=7, color=DARK)
        t(p, fb.x1 - 14, fy + 10, "×", size=8, color=RED)
    t(p, win2.x0 + 210, win2.y0 + 52, "× を押すと取り消せます", size=7.5, color=GRAY)
    # 実行ボタン
    rb = fitz.Rect(win2.x0 + 26, win2.y0 + 86, win2.x0 + 180, win2.y0 + 110)
    rect(p, rb, fill=BLUE, stroke=BLUE)
    tc(p, (rb.x0 + rb.x1) / 2, win2.y0 + 102, "整合チェック実行", size=9, color=WHITE)
    redring(p, (rb.x0 + rb.x1) / 2, (rb.y0 + rb.y1) / 2, 86, 18)
    cursor(p, rb.x1 - 24, rb.y1 - 4)
    callout(p, win2.x0 + 210, win2.y0 + 78, 210,
            ["構造図・計算書を入れたら", "このボタンを押す（20〜30秒）"],
            ((rb.x0 + rb.x1) / 2, rb.y0))

    nb = fitz.Rect(M, 516, W - M, 566)
    rect(p, nb, fill=LIGHT, stroke=(0.75, 0.85, 1.0), width=1, radius=6)
    t(p, M + 14, 536, "● どのPDFが「構造図」「計算書」か分からないときは、", size=9, color=DARK)
    t(p, M + 14, 552, "  設計担当の人に確認してください。", size=9, color=DARK)

    pagefooter(p, 3, TOTAL)

    # ============ ページ4: 結果を見る ============
    p = doc.new_page(width=W, height=H)
    header(p, "【使い方 3】 結果を見る", "ボタンを押したあと、20〜30秒待ちます")

    t(p, M, 88, "「整合チェック実行」を押すと、下のような結果が出ます。", size=11, color=DARK, bold=True)
    t(p, M, 106, "（解析に20〜30秒かかります。そのまま待ってください）", size=9, color=GRAY)

    win = window(p, (M, 122, W - M, 360), "ブラウザ - SUGA")
    rect(p, (win.x0 + 14, win.y0 + 12, win.x1 - 14, win.y1 - 14),
         fill=WHITE, stroke=BORDER)
    t(p, win.x0 + 26, win.y0 + 32, "整合チェック結果 — 小梁", size=10, color=BLUE, bold=True)
    # 表
    cols = [win.x0 + 26, win.x0 + 110, win.x0 + 170, win.x0 + 380, win.x1 - 26]
    hy = win.y0 + 44
    p.draw_rect(fitz.Rect(cols[0], hy, cols[-1], hy + 16), fill=(0.93, 0.94, 0.96), color=BORDER)
    for cx, lab in zip(cols, ["種別", "符号", "差分の内容", "PDF確認"]):
        t(p, cx + 4, hy + 11, lab, size=7.5, color=DARK, bold=True)
    rows = [
        ("配筋不一致", RED, "CG1A", "STP 図2-D13@200 / 計算5-D13@200"),
        ("要目視確認", (0.71, 0.27, 0.05), "B3A", "3位置レイアウト — PDFで確認"),
        ("図のみ", GRAY, "CB3", "計算書側に該当なし"),
    ]
    for i, (kind, col, mark, desc) in enumerate(rows):
        ry = hy + 16 + i * 20
        p.draw_rect(fitz.Rect(cols[0], ry, cols[-1], ry + 20), color=BORDER, width=0.6)
        t(p, cols[0] + 4, ry + 13, kind, size=7.5, color=col, bold=True)
        t(p, cols[1] + 4, ry + 13, mark, size=7.5, color=DARK)
        t(p, cols[2] + 4, ry + 13, desc, size=7, color=GRAY)
        b1 = fitz.Rect(cols[3] + 4, ry + 4, cols[3] + 30, ry + 16)
        rect(p, b1, stroke=(0.58, 0.77, 0.99))
        tc(p, (b1.x0 + b1.x1) / 2, ry + 13, "図", size=7, color=BLUE)
        b2 = fitz.Rect(cols[3] + 36, ry + 4, cols[3] + 74, ry + 16)
        rect(p, b2, stroke=(0.58, 0.77, 0.99))
        tc(p, (b2.x0 + b2.x1) / 2, ry + 13, "計算", size=7, color=BLUE)
    # 強調: PDFボタン
    redring(p, cols[3] + 38, hy + 16 + 10, 48, 14)
    cursor(p, cols[3] + 20, hy + 16 + 14)
    callout(p, cols[3] - 30, hy + 70, 210,
            ["「図」「計算」ボタンを押すと", "元のPDFの場所が見られます"],
            (cols[3] + 16, hy + 16 + 20 * 1))

    # 種別の意味
    y = 386
    t(p, M, y, "結果の「種別」の意味", size=11, color=BLUE, bold=True)
    y += 12
    meanings = [
        (RED, "配筋不一致 / 断面幅不一致",
         "図と計算書で値が違います。直す必要があるかも。要チェック。"),
        ((0.71, 0.27, 0.05), "要目視確認",
         "アプリでは判断しきれない部分。PDFを開いて自分の目で確認。"),
        (GRAY, "図のみ / 計算書のみ",
         "どちらか片方にしかない符号。基礎部材などはチェックを外して隠せます。"),
    ]
    for col, name, desc in meanings:
        box = fitz.Rect(M, y, W - M, y + 46)
        rect(p, box, fill=WHITE, stroke=BORDER, radius=6)
        p.draw_circle((M + 16, y + 23), 6, fill=col, color=None)
        t(p, M + 30, y + 20, name, size=9.5, color=col, bold=True)
        t(p, M + 30, y + 36, desc, size=8.5, color=DARK)
        y += 54

    nb = fitz.Rect(M, y + 4, W - M, y + 54)
    rect(p, nb, fill=YELLOW, stroke=YELLOWB, width=1, radius=6)
    t(p, M + 14, y + 24, "● PDF確認の画面では、ちがう場所がオレンジ色の枠で", size=9, color=DARK)
    t(p, M + 14, y + 40, "  囲まれて表示されます。閉じるときは「閉じる」ボタン。", size=9, color=DARK)

    pagefooter(p, 4, TOTAL)

    # ============ ページ5: 終了・困ったとき ============
    p = doc.new_page(width=W, height=H)
    header(p, "【使い方 4】 終了する / 困ったとき", "")

    t(p, M, 90, "アプリを終了するには", size=12, color=BLUE, bold=True)
    win = window(p, (M, 106, W - M, 210), "コマンドプロンプト（黒い画面）")
    p.draw_rect(fitz.Rect(win.x0, win.y0, win.x1, win.y1), fill=(0.1, 0.1, 0.12), color=None)
    t(p, win.x0 + 14, win.y0 + 24, "SUGA - 構造図/計算書 整合チェック", size=8, color=(0.7, 0.9, 0.7))
    t(p, win.x0 + 14, win.y0 + 40, "起動中... ブラウザを開きます", size=8, color=(0.7, 0.9, 0.7))
    # 閉じるボタン（×）強調
    cb = fitz.Rect(win.x1 - 20, win.y0 - 20, win.x1, win.y0)
    redring(p, win.x1 - 10, win.y0 - 10, 14)
    cursor(p, win.x1 - 14, win.y0 - 16)
    callout(p, win.x1 - 250, win.y0 + 30, 220,
            ["黒い画面の右上「×」を押すと", "アプリが終了します"],
            (win.x1 - 10, win.y0 - 6))

    t(p, M, 250, "困ったとき", size=12, color=BLUE, bold=True)
    troubles = [
        ("ブラウザが自動で開かない",
         "ブラウザを自分で開き、アドレス欄に  127.0.0.1:8000  と入力。"),
        ("「このサイトにアクセスできません」と出る",
         "黒い画面（コンソール）が閉じていないか確認。閉じていたら SUGA.exe を再度ダブルクリック。"),
        ("整合チェックがなかなか終わらない",
         "20〜30秒は正常です。1分以上なら一度終了して、もう一度起動。"),
        ("結果がおかしい・差分が多すぎる",
         "PDFの選び間違いがないか確認。画面のチェックボックスで基礎部材などを隠せます。"),
        ("それでも解決しないとき",
         "黒い画面の文字をコピーして、開発担当に送ってください。"),
    ]
    y = 270
    for i, (q, a) in enumerate(troubles):
        box = fitz.Rect(M, y, W - M, y + 56)
        rect(p, box, fill=WHITE, stroke=BORDER, radius=6)
        t(p, M + 14, y + 20, "Q. " + q, size=9.5, color=DARK, bold=True)
        t(p, M + 14, y + 38, "A. " + a, size=8.5, color=GRAY)
        y += 64

    pagefooter(p, 5, TOTAL)

    # ============ ページ6: exe を作る（IT担当向け） ============
    p = doc.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(0, 0, W, 56), fill=GRAY, color=None)
    t(p, M, 32, "【参考】 アプリ本体（SUGA.exe）を作る", size=16, color=WHITE, bold=True)
    t(p, M + 6, 48, "この作業はパソコンに詳しい人（IT担当）向けです", size=9, color=(0.92, 0.92, 0.92))

    nb = fitz.Rect(M, 72, W - M, 116)
    rect(p, nb, fill=YELLOW, stroke=YELLOWB, width=1, radius=6)
    t(p, M + 14, 92, "このページの作業は「最初の1回だけ」。むずかしければ", size=9, color=DARK)
    t(p, M + 14, 108, "IT担当の人におねがいしてください。", size=9, color=DARK)

    y = 140
    t(p, M, y, "用意するもの（事前にインストール）", size=11, color=DARK, bold=True)
    for i, s in enumerate([
        "Python 3.11以上  …  python.org からダウンロード",
        "                       インストール時「Add Python to PATH」にチェック",
        "Node.js 20以上   …  nodejs.org の LTS版",
    ]):
        t(p, M + 14, y + 20 + i * 15, s, size=8.5, color=GRAY)

    y = 220
    t(p, M, y, "作る手順", size=11, color=DARK, bold=True)
    steps = [
        "GitHub から SUGA 一式をダウンロード（ZIP）して解凍する",
        "コマンドプロンプト（黒い画面）を開く（Windowsキー+R → cmd と入力）",
        "解凍したフォルダの中の  scripts\\build_exe.bat  を黒い画面にドラッグして Enter",
        "5〜10分待つ。SUCCESS と出れば backend\\dist\\SUGA.exe が完成",
        "できた SUGA.exe を共有フォルダに置いて、みんなに配る",
    ]
    yy = y + 18
    for i, s in enumerate(steps):
        stepnum(p, M + 10, yy + 4, i + 1, r=9)
        t(p, M + 28, yy + 8, s, size=8.7, color=DARK)
        yy += 28

    box = fitz.Rect(M, yy + 6, W - M, yy + 70)
    rect(p, box, fill=(1.0, 0.97, 0.97), stroke=(0.9, 0.7, 0.7), radius=6)
    t(p, M + 14, yy + 26, "エラーが出て止まったら", size=10, color=RED, bold=True)
    t(p, M + 14, yy + 44, "黒い画面に [ERROR] と出て止まります。その画面の文字を", size=8.7, color=DARK)
    t(p, M + 14, yy + 60, "全部コピー（右クリック→すべて選択→Enter）して開発担当へ送付。", size=8.7, color=DARK)

    pagefooter(p, 6, TOTAL)

    out = "SUGA_かんたんガイド.pdf"
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    print("生成:", make())
