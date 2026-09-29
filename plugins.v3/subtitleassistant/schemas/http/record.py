"""匹配记录、删除与改配 HTTP 请求响应模型。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from ...schemas.attribution import (
    FileAttributionMethod,
    PackageAttributionStrategy,
    UnmatchedReason,
)
from ...schemas.candidate import (
    PackageScope,
    TranslationType,
)
from ...schemas.record import (
    FileLocation,
    RecordStatus,
)
from ...schemas.source import (
    SubtitleSource,
)
from ...schemas.target import (
    MediaType,
)
from ..base import utc_now
from .base import ApiModel
from .page import PageSize
from .target import TargetListItem
from .task import PathMappingSnapshot

__all__ = [
    "BatchRecordDeleteConfirmation",
    "BatchRecordDeletePreflightItem",
    "BatchRecordDeleteRequest",
    "BatchRecordDeleteResponse",
    "BatchRecordDeleteResultItem",
    "BatchRetargetPreviewItem",
    "BatchRetargetPreviewMapping",
    "BatchRetargetPreviewRequest",
    "BatchRetargetPreviewResponse",
    "BatchRetargetResponse",
    "BatchRetargetResultItem",
    "BatchRetargetSubmitMapping",
    "BatchRetargetSubmitRequest",
    "RecordDeleteRequest",
    "RecordDetail",
    "RecordListItem",
    "RecordPage",
    "RetargetPreviewResponse",
    "RetargetRequest",
]


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


def _history_id_parser(value: object) -> object:
    """保留历史接口对十进制数字字符串的兼容校验。"""

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
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


_MediaType = Annotated[MediaType, BeforeValidator(_enum_parser(MediaType))]
_MediaTypeOptional = Annotated[MediaType | None, BeforeValidator(_enum_parser(MediaType))]
_RecordStatus = Annotated[RecordStatus, BeforeValidator(_enum_parser(RecordStatus))]
_SubtitleSource = Annotated[SubtitleSource, BeforeValidator(_enum_parser(SubtitleSource))]
_PackageScope = Annotated[PackageScope, BeforeValidator(_enum_parser(PackageScope))]
_FileLocation = Annotated[FileLocation, BeforeValidator(_enum_parser(FileLocation))]
_FileAttributionMethodOptional = Annotated[
    FileAttributionMethod | None,
    BeforeValidator(_enum_parser(FileAttributionMethod)),
]
_UnmatchedReasonOptional = Annotated[UnmatchedReason | None, BeforeValidator(_enum_parser(UnmatchedReason))]
_TranslationType = Annotated[TranslationType, BeforeValidator(_enum_parser(TranslationType))]
_PackageStrategy = Annotated[PackageAttributionStrategy, BeforeValidator(_enum_parser(PackageAttributionStrategy))]
_DateTime = Annotated[datetime, BeforeValidator(_datetime_parser)]
_DateTimeOptional = Annotated[datetime | None, BeforeValidator(_datetime_parser)]
_HistoryId = Annotated[int, BeforeValidator(_history_id_parser)]
_HistoryIdOptional = Annotated[int | None, BeforeValidator(_history_id_parser)]
_PageSize = Annotated[PageSize, BeforeValidator(_page_size_parser)]


class RetargetHistoryEntry(ApiModel):
    """一次成功改配目标审计记录的 HTTP 投影。"""

    operated_at: _DateTime = Field(default_factory=utc_now)
    old_target_history_id: _HistoryIdOptional = None
    new_target_history_id: _HistoryIdOptional = None
    old_history_target_path: str | None = None
    new_history_target_path: str | None = None
    old_target_path: str | None = None
    new_target_path: str
    new_matched_path_mapping: PathMappingSnapshot | None = None
    old_subtitle_path: str
    new_subtitle_path: str


class RecordListItem(ApiModel):
    """字幕匹配记录列表项。"""

    id: str
    subtitle_file_name: str
    format: str
    size: int | None
    media_title: str | None
    year: int | None
    media_type: _MediaType
    season: int | None
    episode: int | None
    status: _RecordStatus
    source: _SubtitleSource
    package_scope: _PackageScope
    location: _FileLocation
    path: str
    current_file_path: str = ""
    target_history_id: int | None
    history_target_path: str | None
    target_path: str | None
    created_at: _DateTime
    updated_at: _DateTime
    consumed_at: _DateTimeOptional


class RecordDetail(RecordListItem):
    """字幕匹配记录详情。"""

    canonical_identity_type: str | None
    canonical_identity_value: str | None
    tmdb_id: int | None
    imdb_id: str | None
    matched_path_mapping: PathMappingSnapshot | None
    target_file_exists: bool | None
    final_subtitle_path: str | None
    source_task_id: str
    consumed_task_id: str | None
    candidate_key: str
    candidate_name: str | None
    logical_source_path: str | None
    file_attribution_method: _FileAttributionMethodOptional
    unmatched_reason: _UnmatchedReasonOptional
    language: str
    translation_type: _TranslationType
    hearing_impaired: bool
    staged_at: _DateTimeOptional
    retarget_history: list[RetargetHistoryEntry]


class RecordDeleteRequest(ApiModel):
    """匹配记录删除请求及用户确认时看到的版本快照。"""

    delete_mode: Literal["record_only", "record_and_file"]
    expected_status: _RecordStatus
    expected_location: _FileLocation
    expected_path: str = Field(min_length=1, max_length=4096)
    expected_updated_at: _DateTime


class BatchRecordDeleteConfirmation(ApiModel):
    """批量删除中的一条匹配记录确认版本。"""

    record_id: str = Field(min_length=1, max_length=128)
    expected_status: _RecordStatus
    expected_location: _FileLocation
    expected_path: str = Field(min_length=1, max_length=4096)
    expected_updated_at: _DateTime


class BatchRecordDeleteRequest(ApiModel):
    """提交一批使用统一删除模式的匹配记录确认项。"""

    delete_mode: Literal["record_only", "record_and_file"]
    items: list[BatchRecordDeleteConfirmation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reject_duplicate_records(self) -> BatchRecordDeleteRequest:
        """拒绝同一匹配记录在一个删除批次中重复出现。"""

        record_ids = [item.record_id for item in self.items]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("同一匹配记录不能在批次中重复出现")
        return self


class BatchRecordDeletePreflightItem(ApiModel):
    """批量删除整体预检中的单条记录结果。"""

    record_id: str
    executable: bool
    error_code: str | None = None
    message: str | None = None


class BatchRecordDeleteResultItem(ApiModel):
    """批量删除执行后的单条记录结果。"""

    record_id: str
    status: Literal["success", "failed", "not_executed"]
    error_code: str | None = None
    message: str | None = None
    consistency_risk: bool = False


class BatchRecordDeleteResponse(ApiModel):
    """批量删除已开始执行后的逐条汇总响应。"""

    success_count: int
    failure_count: int
    not_executed_count: int
    items: list[BatchRecordDeleteResultItem]


class RetargetRequest(ApiModel):
    """改配目标请求。"""

    target_history_id: _HistoryId


class RetargetPreviewResponse(ApiModel):
    """改配目标弹窗的服务端路径预览。"""

    target_history_id: _HistoryId
    history_target_path: str
    target_path: str
    final_subtitle_path: str
    directory_available: bool
    directory_error: str | None = None


class BatchRetargetPreviewMapping(ApiModel):
    """批量改配预览中的一条记录与可空目标配对。"""

    record_id: str = Field(min_length=1, max_length=128)
    target_history_id: _HistoryIdOptional = None


class BatchRetargetPreviewRequest(ApiModel):
    """请求批量改配自动建议与路径预检。"""

    items: list[BatchRetargetPreviewMapping] = Field(min_length=1, max_length=100)


class BatchRetargetSubmitMapping(ApiModel):
    """批量改配提交中的一条已确认记录目标配对。"""

    record_id: str = Field(min_length=1, max_length=128)
    target_history_id: _HistoryId


class BatchRetargetSubmitRequest(ApiModel):
    """提交一批已经确认的改配映射。"""

    items: list[BatchRetargetSubmitMapping] = Field(min_length=1, max_length=100)


class BatchRetargetPreviewItem(ApiModel):
    """批量改配中单条映射的安全预览结果。"""

    record_id: str
    current_subtitle_path: str | None = None
    target_history_id: int | None = None
    target: TargetListItem | None = None
    preview: RetargetPreviewResponse | None = None
    executable: bool
    error_code: str | None = None
    message: str | None = None


class BatchRetargetPreviewResponse(ApiModel):
    """批量改配整体预检响应。"""

    executable: bool
    items: list[BatchRetargetPreviewItem]


class BatchRetargetResultItem(ApiModel):
    """批量改配中单条映射的执行响应。"""

    record_id: str
    target_history_id: _HistoryId
    success: bool
    error_code: str | None = None
    message: str | None = None
    consistency_risk: bool = False
    record: RecordDetail | None = None


class BatchRetargetResponse(ApiModel):
    """批量改配执行完成后的逐条结果响应。"""

    success_count: int
    failure_count: int
    items: list[BatchRetargetResultItem]


class RecordPage(ApiModel):
    """字幕匹配记录分页响应。"""

    items: list[RecordListItem]
    total: int
    page: int
    page_size: _PageSize
