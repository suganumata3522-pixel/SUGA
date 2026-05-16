"""SUGA ローカル起動ランチャー。

各自の PC で `python run.py`（またはパッケージ化した SUGA.exe をダブルクリック）
すると、ローカルで API サーバを起動し、既定ブラウザで画面を開く。
"""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def _open_browser() -> None:
    webbrowser.open(URL)


def main() -> None:
    print("=" * 56)
    print("  SUGA - 構造図/計算書 整合チェック")
    print(f"  起動中... ブラウザで {URL} を開きます")
    print("  終了するにはこのウィンドウを閉じてください")
    print("=" * 56)
    # サーバ起動後にブラウザを開く
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
