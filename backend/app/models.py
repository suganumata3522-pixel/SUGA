"""共通データモデル。

構造図側・計算書側のパーサーは、ともに Member の列に正規化して出力する。
checker はソース別にグループ化された Member 群を突き合わせて差分を返す。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    COLUMN = "柱"
    GIRDER = "大梁"
    BEAM = "小梁"
    WALL = "壁"
    SLAB = "スラブ"


class Source(str, Enum):
    DRAWING = "図"
    CALC = "計算書"


class Section(BaseModel):
    """断面寸法 (mm)。柱・梁は b×D、壁・スラブは thickness を使う。"""
    b: Optional[int] = None
    D: Optional[int] = None
    thickness: Optional[int] = None


class Rebar(BaseModel):
    """配筋仕様。"""
    main: Optional[str] = None       # 主筋 例: "12-D25"
    hoop: Optional[str] = None       # 帯筋/あばら筋 例: "4-D13@100"
    top: Optional[str] = None        # 梁上端筋
    bottom: Optional[str] = None     # 梁下端筋
    horizontal: Optional[str] = None # 壁横筋
    vertical: Optional[str] = None   # 壁縦筋


class LocationHint(BaseModel):
    """元PDFの位置情報。差分表示時のハイライト用。"""
    page: int
    bbox: Optional[tuple[float, float, float, float]] = None
    raw_text: Optional[str] = None


class Member(BaseModel):
    category: Category
    mark: str = Field(..., description="部材符号 例: C1, G1, B1, W18, S15")
    floor: Optional[str] = None
    section: Section = Field(default_factory=Section)
    rebar: Rebar = Field(default_factory=Rebar)
    concrete_grade: Optional[str] = None  # 例 "Fc36"
    source: Source
    location: Optional[LocationHint] = None


class MemberSet(BaseModel):
    """パース結果のコンテナ。"""
    source: Source
    file_name: str
    members: list[Member] = Field(default_factory=list)
