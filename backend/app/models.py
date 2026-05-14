"""共通データモデル（RC小梁 = 二次部材）。

構造図側・計算書側のパーサーは、ともに BeamMember の列に正規化して出力する。
checker はソース別にグループ化された BeamMember を符号ごとに突き合わせて差分を返す。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Source(str, Enum):
    DRAWING = "図"
    CALC = "計算書"


class Section(BaseModel):
    """断面寸法 (mm)。小梁では B×D。構造図側は B のみのことが多い。"""
    B: Optional[int] = None
    D: Optional[int] = None


class PositionRebar(BaseModel):
    """位置（端部/中央など）ごとの配筋。"""
    location: str  # 例: "全断面", "SX1端", "中央", "SX2端", "元端", "先端"
    top: Optional[str] = None       # 上端筋 例 "4-D22", "4/2-D22"
    bottom: Optional[str] = None    # 下端筋
    stirrup: Optional[str] = None   # ST. (あばら筋) 例 "2-D10@150"
    web: Optional[str] = None       # 腹筋 例 "2-D10"


class LocationHint(BaseModel):
    """元PDFの位置情報。差分表示時のハイライト用。"""
    page: int
    bbox: Optional[tuple[float, float, float, float]] = None


class BeamMember(BaseModel):
    """RC小梁1本（符号単位）。"""
    mark: str = Field(..., description="部材符号 例: B1, B1A, CG1, WCB2B")
    floor: Optional[str] = None
    section: Section = Field(default_factory=Section)
    positions: list[PositionRebar] = Field(default_factory=list)
    concrete_grade: Optional[str] = None  # 例 "Fc36"
    fc_code: Optional[str] = None         # 構造図上の表記コード 例 "006"
    rebar_grade_main: Optional[str] = None    # 例 "SD345"
    rebar_grade_stirrup: Optional[str] = None  # 例 "SD295"
    source: Source
    location: Optional[LocationHint] = None
    note: Optional[str] = None  # 計算書の備考 (例: "1F 駐輪場・ENT")


class MemberSet(BaseModel):
    """パース結果のコンテナ。"""
    source: Source
    file_name: str
    members: list[BeamMember] = Field(default_factory=list)
