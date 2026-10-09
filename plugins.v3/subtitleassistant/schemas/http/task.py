"""字幕任务 HTTP 请求响应模型。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BeforeValidator, JsonValue

from ...schemas.candidate import PackageScope
from ...schemas.source import SubtitleSource
from ...schemas.target import MediaType
from ...schemas.task import TaskStatus, TaskTrigger
from .base import ApiModel
from .page import PageSize

__all__ = ["TaskDetail", "TaskListItem", "TaskPage"]


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


_TaskTrigger = Annotated[TaskTrigger, BeforeValidator(_enum_parser(TaskTrigger))]
_MediaType = Annotated[MediaType, BeforeValidator(_enum_parser(MediaType))]
_TaskStatus = Annotated[TaskStatus, BeforeValidator(_enum_parser(TaskStatus))]
_SubtitleSourceOptional = Annotated[SubtitleSource | None, BeforeValidator(_enum_parser(SubtitleSource))]
_PackageScopeOptional = Annotated[PackageScope | None, BeforeValidator(_enum_parser(PackageScope))]
_DateTime = Annotated[datetime, BeforeValidator(_datetime_parser)]
_DateTimeOptional = Annotated[datetime | None, BeforeValidator(_datetime_parser)]
_PageSize = Annotated[PageSize, BeforeValidator(_page_size_parser)]


class PathMappingSnapshot(ApiModel):
    """任务目标实际命中的整理历史路径映射投影。"""

    source_prefix: str
    target_prefix: str


class TaskListItem(ApiModel):
    """字幕任务列表项。"""

    id: str
    trigger: _TaskTrigger
    media_title: str
    year: int | None
    media_type: _MediaType
    season: int | None
    episode: int | None
    target_file_name: str
    target_path: str
    target_history_id: int | None
    history_target_path: str | None
    status: _TaskStatus
    reason_code: str | None
    reason_message: str | None
    result_source: _SubtitleSourceOptional
    result_package_scope: _PackageScopeOptional
    result_format: str | None
    created_at: _DateTime
    started_at: _DateTimeOptional
    finished_at: _DateTimeOptional
    duration_ms: int | None


class TaskDetail(TaskListItem):
    """字幕任务详情。"""

    tmdb_id: int | None
    imdb_id: str | None
    target_storage: str | None
    matched_path_mapping: PathMappingSnapshot | None
    target_file_exists: bool | None
    final_subtitle_path: str | None
    record_counts: dict[str, int]
    manual_source: _SubtitleSourceOptional
    manual_candidate_key: str | None
    manual_candidate_summary: dict[str, JsonValue]
    actual_search_query: str | None


class TaskPage(ApiModel):
    """字幕任务分页响应。"""

    items: list[TaskListItem]
    total: int
    page: int
    page_size: _PageSize
