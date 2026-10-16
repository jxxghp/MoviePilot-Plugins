"""整理历史目标 HTTP 响应模型。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

from ...schemas.source import SubtitleSource
from ...schemas.target import MediaType
from .base import ApiModel
from .page import PageSize

__all__ = ["TargetListItem", "TargetPage"]


def _enum_parser[EnumType: Enum](enum_type: type[EnumType]) -> Callable[[object], object]:
    """把 HTTP JSON 中的枚举值显式解析为对应枚举。"""

    def parse(value: object) -> object:
        if value is None or isinstance(value, enum_type):
            return value
        if isinstance(value, str):
            try:
                return enum_type(value)
            except ValueError:
                return value
        return value

    return parse


def _datetime_parser(value: object) -> object:
    """把 ISO-8601 字符串显式解析为时间值。"""

    if isinstance(value, datetime) or not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _path_parser(value: object) -> object:
    """把领域路径投影为 HTTP 字符串。"""

    return str(value) if isinstance(value, Path) else value


def _search_plans_parser(value: object) -> object:
    """把来源字符串键显式解析为来源枚举键。"""

    if not isinstance(value, dict):
        return value
    parsed: dict[object, object] = {}
    for key, plans in value.items():
        if isinstance(key, SubtitleSource):
            parsed[key] = plans
            continue
        if isinstance(key, str):
            try:
                parsed[SubtitleSource(key)] = plans
                continue
            except ValueError:
                pass
        parsed[key] = plans
    return parsed


def _page_size_parser(value: object) -> object:
    """把分页参数显式解析为允许的分页枚举。"""

    if isinstance(value, PageSize):
        return value
    if isinstance(value, (int, str)):
        try:
            return PageSize(int(value))
        except (TypeError, ValueError):
            return value
    return value


_MediaType = Annotated[MediaType, BeforeValidator(_enum_parser(MediaType))]
_DateTime = Annotated[datetime, BeforeValidator(_datetime_parser)]
_PathString = Annotated[str, BeforeValidator(_path_parser)]
_SearchPlans = Annotated[
    dict[SubtitleSource, list["SearchPlanItem"]],
    BeforeValidator(_search_plans_parser),
]
_PageSize = Annotated[PageSize, BeforeValidator(_page_size_parser)]


class SearchPlanItem(ApiModel):
    """整理目标中嵌入的安全查询计划投影。"""

    kind: Literal["id", "title", "filename", "fallback"]
    label: str
    query: str | None
    editable: bool


class TargetListItem(ApiModel):
    """人工字幕搜索可选的整理目标。"""

    history_id: int | str
    media_title: str
    year: int | None = None
    media_type: _MediaType
    season: int | None = None
    episode: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    target_file_name: str
    target_path: _PathString
    organized_at: _DateTime
    search_plans: _SearchPlans = Field(default_factory=dict)


class TargetPage(ApiModel):
    """MoviePilot 整理历史当前页原始响应。"""

    # 原始整理历史行由宿主定义；分页壳严格，行内开放字段保持兼容。
    items: list[dict[str, object]]
    page: int
    page_size: _PageSize
    total: int
