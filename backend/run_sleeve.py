"""YHG-Sleeve ローカル起動ランチャー（梁スリーブ貫通補強チェック）。

YHG.exe と同じ FastAPI アプリを共有しつつ、`YHG_PRODUCT=sleeve` で
データフォルダ・画面タイトル・モード（stub/active）を切り替える。

サンプル計算書PDFが手元に届くまでは stub モードで起動し、画面側で
「実装準備中」を案内する。
"""
from __future__ import annotations

import os
import threading
import webbrowser

os.environ.setdefault("YHG_PRODUCT", "sleeve")

import uvicorn  # noqa: E402

HOST = "127.0.0.1"
PORT = 8001  # YHG.exe (8000) と同時起動できるよう別ポート
URL = f"http://{HOST}:{PORT}/"


def _open_browser() -> None:
    webbrowser.open(URL)


def main() -> None:
    print("=" * 56)
    print("  YHG-Sleeve - 梁スリーブ貫通補強 整合チェック")
    print(f"  起動中... ブラウザで {URL} を開きます")
    print("  終了するにはこのウィンドウを閉じてください")
    print("=" * 56)
    from app.main import app
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
