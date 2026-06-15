"""YHG ローカル起動ランチャー。

各自の PC で `python run.py`（またはパッケージ化した YHG.exe をダブルクリック）
すると、ローカルで API サーバを起動し、既定ブラウザで画面を開く。
"""
from __future__ import annotations

import os
import threading
import webbrowser

# import より前に製品種別を確定させる（config.py / main.py が起動時に参照）。
os.environ.setdefault("YHG_PRODUCT", "core")

import uvicorn  # noqa: E402

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def _open_browser() -> None:
    webbrowser.open(URL)


def main() -> None:
    print("=" * 56)
    print("  構造図・計算書 整合チェックツール（RC小梁・スラブ）")
    print(f"  起動中... ブラウザで {URL} を開きます")
    print("  終了するにはこのウィンドウを閉じてください")
    print("=" * 56)
    # アプリを直接 import して渡す。
    # PyInstaller でパッケージ化した場合、import 文字列 ("app.main:app")
    # 指定だとモジュールが再 import され、プロセス内キャッシュが共有
    # されないため、必ずオブジェクトを渡す。
    from app.main import app
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
