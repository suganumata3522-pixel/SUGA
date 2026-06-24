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
      (整合チェックツール(RC小梁・スラブ).exe → 整合チェックツール-data/,
       YHG-Sleeve.exe → YHG-Sleeve-data/)
    - 通常実行時: カレントディレクトリ

    旧称データフォルダ ("YHG-data") が既に存在し、新称フォルダが
    まだ無い場合は、そのまま新名にリネームして履歴を引き継ぐ。
    """
    if _is_frozen():
        parent = Path(sys.executable).parent
        info = _current_product()
        new_dir = parent / info["data_dirname"]
        # 旧称データフォルダからの移行（破壊しない条件で）
        if not new_dir.exists():
            legacy = parent / ("YHG-data" if info["kind"] == "core"
                               else "YHG-Sleeve-data")
            if legacy.exists() and legacy != new_dir:
                try:
                    legacy.rename(new_dir)
                except OSError:
                    # リネーム失敗時は新フォルダを通常通り作成（履歴は引き継がれない）
                    pass
        return new_dir
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
