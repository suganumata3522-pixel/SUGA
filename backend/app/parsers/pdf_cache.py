"""PDFテキスト抽出のキャッシュ。

整合チェック1回につき、計算書PDFは「小梁用」と「スラブ用」で 2 回、
構造図PDFも同様に 2 回パースされる。pdfplumber の extract_text /
extract_words はページ数が多いと重いため、ファイル単位で抽出結果を
キャッシュして再利用する。

また一部の PDF はフォント/CID 設定が壊れており、表示は正しい漢字
（例: 符号）に見えても、抽出した Unicode が中国簡体字や Kangxi
部首コードポイント（例: 绍号、主筋⽅向）になっていることがある。
パーサーが「符号」等の文字列で行を識別できなくなるため、抽出した
text/word に対して既知の誤コードポイントを正しい字へ置換する。
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF: 白塗りで隠されたテキストの検出に使う
import pdfplumber


@dataclass
class PageData:
    index: int                 # 1始まりのページ番号
    text: str                  # extract_text() の結果
    words: list[dict]          # extract_words(keep_blank_chars=False) の結果
    width: float
    height: float
    # テキストの上に貼られた大きなラスタ画像の矩形（上貼り編集の痕跡）。
    # PDF編集ソフトで表の一部を画像として貼り直すと、下に古いテキストが
    # 残ったまま見た目だけが変わる。抽出は下の古いテキストを読むため、
    # この領域に掛かる部材は「要目視確認」にする。
    overlay_rects: list[tuple[float, float, float, float]] = field(default_factory=list)


# PDF CID マッピング不具合で出る誤コードポイントを正しい字へ戻す。
# 構造図/計算書では出てこない簡体字や Kangxi 部首だけを集めているので、
# 一般文書の漢字を壊す心配は無い。
_CID_FIX_TABLE = {
    # 簡体字/異体字グリフ → 正しい日本語の字
    "绍": "符",  # 绍号 → 符号
    "敋": "巾",  # 敋止筋 → 巾止筋
    "縌": "械",  # 機縌式 → 機械式
    "拙": "補",  # 拙強筋 → 補強筋
    "戄": "着",  # 定戄 → 定着
    "戼": "影",  # 水平投戼 → 水平投影
    "抛": "図",  # 雑詳細抛 → 雑詳細図
    "拘": "限",  # 特記なき拘り → 特記なき限り
    "戯": "領",  # 要戯 → 要領
    "拓": "線",  # 直拓 → 直線
    "扪": "越",  # 扪える → 越える
    "抖": "厚",  # 壁抖 → 壁厚
    "纾": "又",  # NS纾 → NS又
    "纮": "径",  # 主筋纮 → 主筋径
    "技": "段",  # 一技筋 → 一段筋
    "括": "配",  # 括⼒筋 → 配力筋 (FCGの括筋 → FCGの配筋)
    # Kangxi 部首ブロックの記号（U+2F00 台）→ 通常の CJK 統合漢字
    "⽅": "方",  # 主筋⽅向 → 主筋方向
    "⼒": "力",  # 配⼒筋 → 配力筋
    "⼆": "二",
    "⼀": "一",
    "⽔": "水",  # ⽔平 → 水平
    "⼩": "小",  # ⼩梁 → 小梁
    "⼤": "大",  # ⼤梁 → 大梁
    "⽚": "片",  # ⽚持 → 片持
    "⽌": "止",  # 巾⽌筋 → 巾止筋
    "⽇": "日",
    "⼟": "土",
    "⼯": "工",
    "⼨": "寸",
    "⾯": "面",  # 全断⾯ → 全断面
    "⾼": "高",
    "⻑": "長",  # ⻑期 → 長期
    "⾞": "車",  # ⾞庫 → 車庫
}

_CID_FIX_TRANS = str.maketrans(_CID_FIX_TABLE)


def normalize_pdf_text(s: str) -> str:
    """PDF抽出のテキストから既知の誤コードポイントを正しい字へ戻す。"""
    if not s:
        return s
    return s.translate(_CID_FIX_TRANS)


def _fix_reversed_digits(text: str) -> str:
    """縦書きで描画された多桁数字が逆順に抽出されるケースを補正する。

    一部の構造図PDF（dimension lineの数字を縦に1文字ずつ配置するもの）では、
    pdfplumber の extract_words が上から下に文字を連結するため
    "1050" が "0501"、"2000" が "0002" のように先頭ゼロ付きで取れる。

    工学的な数値はゼロ始まりにならない（"0" 単体を除く）ので、
    純数字のみで長さ2以上かつ先頭が "0" の語を逆順に直す。
    """
    if not text or not text.isdigit() or len(text) < 2 or text[0] != "0":
        return text
    reversed_text = text[::-1]
    # 逆順した結果が "0" 始まりにならないことを確認（"00..." のような場合は触らない）
    if reversed_text[0] == "0":
        return text
    return reversed_text


def _extract_annot_words(page, page_height: float) -> list[dict]:
    """PDFの注釈（コメント）から擬似的な単語リストを生成する。

    AutoCAD で `PDFSHX = 1` 設定で PDF 出力すると、SHX 文字が
    実テキストではなく Text 注釈（コメント）として埋め込まれる。
    pdfplumber の標準 extract_words はこれを拾わないので、
    `page.annots` から内容を取り出して単語として補完する。

    AutoCAD 2021 以前は SHX 文字を実テキスト化できず PDFSHX=1 が
    最大設定なので、この補完で構造図の符号・配筋値を抽出できる
    ようになる。

    注釈内のテキストは元図面で縦書きされていた場合 "符 号" のように
    全角スペースで区切られて1つの注釈に入る。これを split() で
    分断するとパーサーが "符号" を見つけられなくなるため、注釈は
    1件あたり1単語として扱い、内部の空白類はすべて除去する。
    """
    import re as _re
    out: list[dict] = []
    try:
        annots = page.annots or []
    except Exception:
        return out
    for annot in annots:
        try:
            contents = annot.get("contents") or ""
        except Exception:
            continue
        if not contents or not isinstance(contents, str):
            continue
        # 注釈内の空白類（半角・全角・改行・タブ）を全て除去して1単語にする。
        # 縦書き SHX 文字が "符 号"・"断 面" のように分かれて入る対策。
        token = _re.sub(r"\s+", "", contents)
        if not token:
            continue
        # 座標を取得（pdfplumber の annot は x0/x1/top/bottom を保持）
        try:
            x0 = annot.get("x0")
            x1 = annot.get("x1")
            top = annot.get("top")
            bottom = annot.get("bottom")
            if any(v is None for v in (x0, x1, top, bottom)):
                # fallback: rect の値（PDF座標、左下原点）から変換
                rect = annot.get("rect") or [0, 0, 0, 0]
                rx0, ry0_bot, rx1, ry1_top = rect
                x0 = rx0; x1 = rx1
                top = page_height - float(ry1_top)
                bottom = page_height - float(ry0_bot)
        except Exception:
            continue
        out.append({
            "text": token,
            "x0": float(x0),
            "x1": float(x1),
            "top": float(top),
            "bottom": float(bottom),
        })
    return out


# リスト表の左ラベルとして現れる語。CAD によっては縦書き 2 文字が
# "符"+"号"・"位"+"置"・"断"+"面"・"腹"+"筋" のように同一行内の隣接
# する2語に分割されて抽出されることがある。これらを結合して 1 語に戻す。
_LABEL_MERGE_TARGETS = {
    ("符", "号"): "符号",
    ("位", "置"): "位置",
    ("断", "面"): "断面",
    ("腹", "筋"): "腹筋",
    # 位置ラベルが1文字ずつに割れるCAD出力（E棟形式など）への対応
    ("元", "端"): "元端",
    ("先", "端"): "先端",
    ("中", "央"): "中央",
    ("基", "端"): "基端",
}


def _merge_split_labels(words: list[dict]) -> list[dict]:
    """同一行で隣接する2語が既知のラベル（符号/位置/断面/腹筋）に
    なる場合に1語へ結合する。

    縦書き SHX 由来などで "符"+"号" のように 2 単語に割れたラベルを
    パーサーが認識できるよう復元する。配筋値や寸法には影響しない
    （結合対象は _LABEL_MERGE_TARGETS の漢字ペアのみ）。
    """
    if not words:
        return words
    # y(top) でグルーピングして同一行内の隣接ペアを調べる
    sorted_w = sorted(words, key=lambda w: (round(float(w["top"]) / 2), float(w["x0"])))
    consumed: set[int] = set()
    merged: list[dict] = []
    n = len(sorted_w)
    for i in range(n):
        if i in consumed:
            continue
        w = sorted_w[i]
        if i + 1 < n:
            nxt = sorted_w[i + 1]
            pair = (w["text"], nxt["text"])
            if (pair in _LABEL_MERGE_TARGETS
                    and abs(float(w["top"]) - float(nxt["top"])) <= 3
                    and 0 <= float(nxt["x0"]) - float(w["x1"]) <= 8):
                merged.append({
                    "text": _LABEL_MERGE_TARGETS[pair],
                    "x0": float(w["x0"]),
                    "x1": float(nxt["x1"]),
                    "top": min(float(w["top"]), float(nxt["top"])),
                    "bottom": max(float(w["bottom"]), float(nxt["bottom"])),
                })
                consumed.add(i + 1)
                continue
        merged.append(w)
    return merged


def _compose_text_from_words(words: list[dict], tol: float = 3.0) -> str:
    """語リストから extract_text() 相当のページテキストを合成する。

    pdfplumber の extract_text() はレイアウト解析が非常に重く
    （実測でパース時間全体の9割超）、その出力は「y(top) で行に
    まとめ、x0 順に空白1つで連結」したものとほぼ等価。既に抽出済みの
    extract_words() の結果から同じテキストを合成することで、
    ページあたりのパース時間を大幅に短縮する。

    行のまとめ方は pdfplumber の cluster（直前要素との差が tol 以内なら
    同じ行）に合わせる。
    """
    if not words:
        return ""
    sw = sorted(words, key=lambda w: float(w["top"]))
    lines: list[list[dict]] = []
    cur: list[dict] = [sw[0]]
    prev = float(sw[0]["top"])
    for w in sw[1:]:
        t = float(w["top"])
        if t - prev <= tol:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
        prev = t
    lines.append(cur)
    return "\n".join(
        " ".join(x["text"] for x in sorted(l, key=lambda x: float(x["x0"])))
        for l in lines
    )


def _hidden_chars(fz_page) -> list[tuple[float, float, str]]:
    """白塗り等の不透明な塗り矩形で「後から」覆われた文字を検出する。

    計算書PDFでは、不要になった検討ブロックを白い塗り矩形で覆って
    「削除」し、その上に別のテキストを載せる編集が行われることがある。
    覆われたテキストは見えないが PDF 内には残っており、そのまま抽出すると
    存在しない検討（例: CS9）を誤検出してしまう。

    描画順（seqno）を見て、テキストより後に描かれた不透明塗り矩形に
    中心が入る文字を「隠し文字」として (中心x, 中心y, 文字) で返す。
    文字より前に描かれた塗り（表の背景色など）は対象にしない。
    """
    try:
        covers: list[tuple[fitz.Rect, int]] = []
        for dr in fz_page.get_drawings():
            if dr.get("fill") is None:
                continue
            if (dr.get("fill_opacity") or 1.0) < 0.9:
                continue
            r = dr["rect"]
            # ごく小さい塗り（罫線・マーカー等）は覆い隠し目的ではない
            if r.width * r.height < 300:
                continue
            covers.append((r, int(dr.get("seqno") or 0)))
        if not covers:
            return []
        out: list[tuple[float, float, str]] = []
        for span in fz_page.get_texttrace():
            seq = int(span.get("seqno") or 0)
            rects = [r for (r, rs) in covers if rs > seq]
            if not rects:
                continue
            for ch in span["chars"]:
                bb = ch[3]
                cx = (bb[0] + bb[2]) / 2.0
                cy = (bb[1] + bb[3]) / 2.0
                if any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in rects):
                    out.append((cx, cy, chr(ch[0])))
        return out
    except Exception:
        return []


def _filter_hidden_words(words: list[dict], hidden: list[tuple[float, float, str]]) -> list[dict]:
    """隠し文字と位置・内容が一致する語を除外する。

    白塗りの上に別テキストが重ねて描かれている場合、位置の重なりだけで
    落とすと可視テキストまで巻き添えにするため、語の bbox 内にある
    隠し文字を連結した文字列と語のテキストが（8割以上）一致する場合のみ
    「隠し語」と判定して除外する。
    """
    if not hidden:
        return words
    out: list[dict] = []
    for w in words:
        x0, x1 = float(w["x0"]) - 0.5, float(w["x1"]) + 0.5
        t0, b0 = float(w["top"]) - 0.5, float(w["bottom"]) + 0.5
        inside = [(cx, ch) for (cx, cy, ch) in hidden
                  if x0 <= cx <= x1 and t0 <= cy <= b0]
        if not inside:
            out.append(w)
            continue
        wtext = re.sub(r"\s+", "", w["text"])
        htext = normalize_pdf_text("".join(ch for _, ch in sorted(inside)))
        if not wtext:
            continue  # 空白のみの語が隠し文字上にある → 除外
        from collections import Counter
        common = Counter(wtext) & Counter(htext)
        matched = sum(common.values())
        if matched >= max(1, int(len(wtext) * 0.8)):
            continue  # 隠し語として除外
        out.append(w)
    return out


# 直近 N ファイル分のみ保持する簡易 LRU（メモリ肥大化を防ぐ）
_MAX_ENTRIES = 6
_cache: dict[tuple[str, float], list[PageData]] = {}

# ---------------------------------------------------------------------------
# 抽出結果のディスクキャッシュ
# ---------------------------------------------------------------------------
# 同じPDF（内容ハッシュが同じ）はアプリ再起動後・再アップロード後でも
# 抽出をやり直さない。抽出は決定的なので、キャッシュの読み戻しは
# 初回抽出と完全に同一の結果になる（精度への影響はゼロ）。
#
# 重要: 抽出ロジック（このファイルの処理）を変更したときにキャッシュが
# 古い結果を返さないよう、キーに「バージョン文字列＋このソースの
# ハッシュ」を含める。ソースが読めない環境（PyInstaller onefile 等）では
# バージョン文字列のみで判定するため、抽出系を変更したら
# _EXTRACT_VERSION を必ず上げること。
_EXTRACT_VERSION = "v5"
_DISK_CACHE_KEEP = 24  # 直近 N ファイル分だけ保持


def _extract_salt() -> str:
    salt = _EXTRACT_VERSION
    try:
        salt += "-" + hashlib.md5(Path(__file__).read_bytes()).hexdigest()[:8]
    except Exception:
        pass
    return salt


_SALT = _extract_salt()


def _disk_cache_dir() -> Path | None:
    if os.environ.get("YHG_NO_DISK_CACHE") == "1":
        return None
    try:
        from ..config import UPLOAD_DIR
        d = UPLOAD_DIR.parent / "parse_cache"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


def _disk_cache_path(content_md5: str) -> Path | None:
    d = _disk_cache_dir()
    if d is None:
        return None
    return d / f"{content_md5}-{_SALT}.pkl"


def _disk_cache_load(p: Path | None) -> list[PageData] | None:
    if p is None or not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            pages = pickle.load(fh)
        # 型の軽い健全性チェック（壊れたキャッシュは捨てて再抽出）
        if isinstance(pages, list) and all(isinstance(x, PageData) for x in pages):
            try:
                os.utime(p)  # LRU 用に触っておく
            except OSError:
                pass
            return pages
    except Exception:
        pass
    try:
        p.unlink()
    except OSError:
        pass
    return None


def _disk_cache_save(p: Path | None, pages: list[PageData]) -> None:
    if p is None:
        return
    try:
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(pages, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, p)
        # 古いエントリを間引く（更新時刻の新しい順に N 件残す）
        entries = sorted(p.parent.glob("*.pkl"),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        for old in entries[_DISK_CACHE_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:
        pass  # キャッシュ保存の失敗は無視（次回も抽出するだけ）

# ページ並列抽出の設定。pdfplumber（pdfminer）の文字解釈は純Pythonで
# 非常に重く、ページ間に依存が無いためプロセス並列で線形に近く速くなる。
# 結果はページ単位で全く同じものを組み立て直すだけなので、逐次実行と
# ビット単位で同一になる。YHG_NO_MP=1 で並列を無効化できる。
_MP_MIN_PAGES = 8      # これ未満のページ数はプロセス起動コストの方が高い
_MP_MAX_WORKERS = 4


def _extract_pages_raw(path: str, indices: list[int], legacy_text: bool) -> list[dict]:
    """（子プロセスでも実行される）指定ページの生抽出結果を返す。

    重い pdfplumber の語抽出・注釈抽出だけを行い、正規化や隠しテキスト
    除去などの後処理は親側で行う（逐次実行と同一の結果を保証するため）。
    """
    out: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for i in indices:
            page = pdf.pages[i - 1]
            raw_words = page.extract_words(keep_blank_chars=False)
            # pickle 転送量を減らすため、パーサーが使うキーだけに絞る
            raw_words = [
                {"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]),
                 "top": float(w["top"]), "bottom": float(w["bottom"])}
                for w in raw_words
            ]
            page_height = float(page.height)
            out.append({
                "index": i,
                "words": raw_words,
                "annots": _extract_annot_words(page, page_height),
                "width": float(page.width),
                "height": page_height,
                "legacy_text": (page.extract_text() or "") if legacy_text else None,
            })
    return out


def _extract_all_pages(path: str) -> list[dict]:
    """全ページの生抽出。ページ数が多いときはプロセス並列で行う。"""
    legacy_text = os.environ.get("YHG_LEGACY_TEXT") == "1"
    try:
        with pdfplumber.open(path) as pdf:
            n_pages = len(pdf.pages)
    except Exception:
        n_pages = 0
    indices = list(range(1, n_pages + 1))
    workers = min(_MP_MAX_WORKERS, os.cpu_count() or 1)
    if (n_pages < _MP_MIN_PAGES or workers <= 1
            or os.environ.get("YHG_NO_MP") == "1"):
        return _extract_pages_raw(path, indices, legacy_text)
    # ラウンドロビンで分配（重いページの偏りを均す）
    chunks = [indices[k::workers] for k in range(workers)]
    chunks = [c for c in chunks if c]
    try:
        import concurrent.futures
        with concurrent.futures.ProcessPoolExecutor(max_workers=len(chunks)) as ex:
            futs = [ex.submit(_extract_pages_raw, path, c, legacy_text) for c in chunks]
            results: list[dict] = []
            for f in futs:
                results.extend(f.result())
        results.sort(key=lambda e: e["index"])
        if len(results) == n_pages:
            return results
    except Exception:
        pass  # 並列に失敗したら逐次にフォールバック（PyInstaller 環境の保険）
    return _extract_pages_raw(path, indices, legacy_text)


def _overlay_image_rects(fz_page) -> list[tuple[float, float, float, float]]:
    """テキストの上に「後から」描かれた大きなラスタ画像の矩形を検出する。

    PDF編集ソフトで計算書の一部を修正すると、修正後の表が画像として
    上貼りされ、下に修正前のテキストが残ることがある。テキスト抽出は
    下の古いテキストを読むため、見た目と抽出値が食い違い得る。

    描画順（get_bboxlog）を見て、先に描かれたテキストに重なる大きな
    画像のみを対象とする。背景スキャン（画像が先、テキストが後）や
    小さなスタンプ・ロゴ画像は対象にしない。
    """
    _MIN_AREA = 15000.0  # 検討ブロック級の画像のみ（スタンプ等は除外）
    out: list[tuple[float, float, float, float]] = []
    try:
        text_rects: list[fitz.Rect] = []
        for op, rect in fz_page.get_bboxlog():
            r = fitz.Rect(rect)
            if op in ("fill-text", "stroke-text", "clip-text", "ignore-text"):
                if not r.is_empty:
                    text_rects.append(r)
            elif op == "fill-image":
                if r.width * r.height < _MIN_AREA:
                    continue
                if any(r.intersects(t) for t in text_rects):
                    out.append((float(r.x0), float(r.y0), float(r.x1), float(r.y1)))
    except Exception:
        return []
    return out


def _hidden_chars_map(path: str) -> tuple[
    dict[int, list[tuple[float, float, str]]],
    dict[int, list[tuple[float, float, float, float]]],
]:
    """全ページの隠し文字（白塗りで覆われたテキスト）と上貼り画像矩形を
    まとめて検出する。

    pdfplumber の抽出（プロセス並列）と並行して別スレッドで走らせるため、
    (ページ番号 → 隠し文字リスト, ページ番号 → 上貼り画像矩形リスト) の
    辞書ペアとして返す。検出結果はページ単位で従来の逐次検出と同一。
    """
    hidden: dict[int, list[tuple[float, float, str]]] = {}
    overlays: dict[int, list[tuple[float, float, float, float]]] = {}
    try:
        doc = fitz.open(path)
    except Exception:
        return hidden, overlays
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            hc = _hidden_chars(page)
            if hc:
                hidden[i + 1] = hc
            ov = _overlay_image_rects(page)
            if ov:
                overlays[i + 1] = ov
    finally:
        doc.close()
    return hidden, overlays


def get_pages(pdf_path: Path | str) -> list[PageData]:
    """PDFの全ページの抽出結果を返す。同一ファイルなら 2 回目以降はキャッシュを返す。

    さらに内容ハッシュをキーにしたディスクキャッシュを持ち、アプリ再起動後や
    再アップロード後でも同じPDFなら抽出をやり直さない（抽出は決定的なので
    結果は初回抽出と同一）。
    """
    path = str(pdf_path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime)

    cached = _cache.get(key)
    if cached is not None:
        return cached

    # ディスクキャッシュ（内容ハッシュ一致なら即返す）
    disk_path = None
    if os.environ.get("YHG_LEGACY_TEXT") != "1":  # 検証モードはキャッシュ対象外
        try:
            content_md5 = hashlib.md5(Path(path).read_bytes()).hexdigest()
            disk_path = _disk_cache_path(content_md5)
        except Exception:
            disk_path = None
        pages = _disk_cache_load(disk_path)
        if pages is not None:
            _cache[key] = pages
            while len(_cache) > _MAX_ENTRIES:
                del _cache[next(iter(_cache))]
            return pages

    # 白塗り隠しテキストの検出（PyMuPDF）は、pdfplumber の抽出と依存が
    # 無いため別スレッドで並行実行する（結果は逐次実行と同一）。
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as tex:
        hidden_fut = tex.submit(_hidden_chars_map, path)
        entries = _extract_all_pages(path)
        hidden_map, overlay_map = hidden_fut.result()

    pages = []
    for entry in entries:
        i = entry["index"]
        raw_words = entry["words"]
        # 白塗り矩形で覆われた（見えない）テキストを除外。
        # テキスト合成より先に行うことで、白塗りで「削除」された検討
        # ブロックが行ベースのパーサー（pd.text 利用側）に漏れて
        # 存在しない部材を誤検出するのを防ぐ。
        hidden = hidden_map.get(i)
        if hidden:
            raw_words = _filter_hidden_words(raw_words, hidden)
        # extract_text() は非常に重いため、抽出済みの語から等価な
        # テキストを合成する（照合時間の大幅短縮）。
        # YHG_LEGACY_TEXT=1 のときは従来の extract_text() を使う
        # （新旧のパース結果を突き合わせる検証用）。
        if entry["legacy_text"] is not None:
            raw_text = entry["legacy_text"]
        else:
            raw_text = _compose_text_from_words(raw_words)
        # CID不具合の正規化＋縦書き数字の逆順補正を適用
        for w in raw_words:
            w["text"] = _fix_reversed_digits(normalize_pdf_text(w["text"]))
        # AutoCAD PDFSHX=1 で埋め込まれたコメント注釈も単語として取り込む
        annot_words = entry["annots"]
        for w in annot_words:
            w["text"] = _fix_reversed_digits(normalize_pdf_text(w["text"]))
        if annot_words:
            raw_words = raw_words + annot_words
            # 注釈テキストも extract_text 相当に追記
            annot_text = "\n".join(w["text"] for w in annot_words)
            raw_text = (raw_text + "\n" + annot_text) if raw_text else annot_text
        # 縦書きで割れたラベル（符 号 等）を1語に結合
        raw_words = _merge_split_labels(raw_words)
        pages.append(PageData(
            index=i,
            text=normalize_pdf_text(raw_text),
            words=raw_words,
            width=entry["width"],
            height=entry["height"],
            overlay_rects=overlay_map.get(i, []),
        ))

    _disk_cache_save(disk_path, pages)
    _cache[key] = pages
    while len(_cache) > _MAX_ENTRIES:
        oldest = next(iter(_cache))
        del _cache[oldest]
    return pages



