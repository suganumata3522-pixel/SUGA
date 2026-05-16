"""設定とパス解決。

通常実行 / PyInstaller でパッケージ化した実行ファイル のどちらでも
動くようにデータ保存先と静的ファイル配信元を解決する。
"""
import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """PyInstaller でパッケージ化された実行ファイルとして動いているか。"""
    return getattr(sys, "frozen", False)


def _app_dir() -> Path:
    """ユーザーデータ（DB・アップロード）を置く基準ディレクトリ。

    - .exe 実行時: 実行ファイルと同じ場所に SUGA-data/ を作る
    - 通常実行時: カレントディレクトリ
    """
    if _is_frozen():
        return Path(sys.executable).parent / "SUGA-data"
    return Path(os.environ.get("SUGA_DATA_DIR", "."))


def _bundle_dir() -> Path:
    """同梱リソース（フロントエンドのビルド成果物）の基準ディレクトリ。"""
    if _is_frozen():
        # PyInstaller は同梱ファイルを sys._MEIPASS に展開する
        return Path(getattr(sys, "_MEIPASS", "."))
    return Path(__file__).resolve().parent


_DATA_DIR = _app_dir()
_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.environ.get("SUGA_DB_URL", f"sqlite:///{(_DATA_DIR / 'data' / 'suga.db').as_posix()}")
(_DATA_DIR / "data").mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = Path(os.environ.get("SUGA_UPLOAD_DIR", str(_DATA_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# フロントエンドのビルド成果物 (app/static/)。build スクリプトが配置する。
STATIC_DIR = _bundle_dir() / "static"
