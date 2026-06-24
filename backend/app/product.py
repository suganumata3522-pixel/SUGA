"""製品ごとの設定。

`整合チェックツール(RC小梁・スラブ).exe` (core) と `YHG-Sleeve.exe` (sleeve) は同じ
コードベースを共有し、起動時に環境変数 `YHG_PRODUCT` を見て挙動を切り替える。

各エントリポイント (run.py / run_sleeve.py) が import 前に `YHG_PRODUCT` を
セットする想定。
"""
from __future__ import annotations

import os
from typing import Literal, TypedDict

ProductKind = Literal["core", "sleeve"]


class ProductInfo(TypedDict):
    kind: ProductKind
    name: str          # exe名 / 画面表示名
    subtitle: str      # 画面サブタイトル
    fastapi_title: str
    data_dirname: str  # exe と同じ場所に作るデータフォルダ名
    port: int
    mode: Literal["active", "stub"]  # stub: 機能準備中


_REGISTRY: dict[ProductKind, ProductInfo] = {
    "core": {
        "kind": "core",
        # 画面表示名。exe 名・データフォルダ名とは独立（exe 名は
        # yhg.spec の name=、データフォルダ名は data_dirname で別管理）。
        "name": "構造図・計算書 整合チェックツール（RC小梁・スラブ）",
        "subtitle": "",
        "fastapi_title": "構造図・計算書 整合チェック",
        "data_dirname": "整合チェックツール-data",
        "port": 8000,
        "mode": "active",
    },
    "sleeve": {
        "kind": "sleeve",
        "name": "YHG-Sleeve",
        "subtitle": "梁スリーブ貫通補強 整合チェックツール",
        "fastapi_title": "YHG-Sleeve - 梁スリーブ貫通補強整合チェック",
        "data_dirname": "YHG-Sleeve-data",
        "port": 8001,
        "mode": "stub",  # サンプル計算書PDFが手元に届き次第 active に切り替え
    },
}


def current() -> ProductInfo:
    kind = os.environ.get("YHG_PRODUCT", "core")
    if kind not in _REGISTRY:
        kind = "core"
    return _REGISTRY[kind]  # type: ignore[index]
