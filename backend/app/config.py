"""設定とパス解決。

通常実行 / PyInstaller でパッケージ化した実行ファイル のどちらでも
動くようにデータ保存先と静的ファイル配信元を解決する。
"""
import os
import sys
from pathlib import Path

from .product import current as _current_product


def _is_frozen() -> bool:
    """PyInstaller でパッケージ化された実行ファイルとして動いているか。"""
    return getattr(sys, "frozen", False)


def _app_dir() -> Path:
    """ユーザーデータ（アップロード）を置く基準ディレクトリ。

    - .exe 実行時: 実行ファイルと同じ場所に <製品名>-data/ を作る
      (YHG.exe → YHG-data/, YHG-Sleeve.exe → YHG-Sleeve-data/)
    - 通常実行時: カレントディレクトリ
    """
    if _is_frozen():
        return Path(sys.executable).parent / _current_product()["data_dirname"]
    return Path(os.environ.get("YHG_DATA_DIR", "."))


def _bundle_dir() -> Path:
    """同梱リソース（フロントエンドのビルド成果物）の基準ディレクトリ。"""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", "."))
    return Path(__file__).resolve().parent


_DATA_DIR = _app_dir()
_DATA_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = Path(os.environ.get("YHG_UPLOAD_DIR", str(_DATA_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = _bundle_dir() / "static"

if _is_frozen():
    ASSETS_DIR = _bundle_dir() / "app" / "assets"
else:
    ASSETS_DIR = Path(__file__).resolve().parent / "assets"
