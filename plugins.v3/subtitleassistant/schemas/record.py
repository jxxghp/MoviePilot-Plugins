"""匹配记录、字幕库存、删除与改配公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from .attribution import (
    FileAttributionMethod,
    UnmatchedReason,
)
from .base import StrictModel, new_id, utc_now
from .candidate import PackageScope, TranslationType
from .source import SubtitleSource
from .target import MediaIdentityKind, MediaType, PathMappingSnapshot, SearchTarget

__all__ = [
    "BatchDeletePreflight",
    "BatchDeletePreflightItem",
    "BatchDeleteRecordConfirmation",
    "BatchDeleteResult",
    "BatchDeleteResultItem",
    "BatchDeleteStatus",
    "BatchRetargetPreview",
    "BatchRetargetPreviewItem",
    "BatchRetargetResult",
    "BatchRetargetResultItem",
    "CommittedFileFact",
    "DeleteMode",
    "DeleteRecordConfirmation",
    "DeleteRecordResult",
    "FileLocation",
    "InventoryConsumeResult",
    "MatchRecord",
    "RecordStatus",
    "RetargetHistoryEntry",
    "RetargetMapping",
    "RetargetPreview",
    "RetargetResult",
]


class RecordStatus(StrEnum):
    """字幕匹配记录状态。"""

    MATCHED = "matched"
    STAGED = "staged"
    UNMATCHED = "unmatched"


class FileLocation(StrEnum):
    """字幕文件保存位置。"""

    MEDIA_DIRECTORY = "media_directory"
    PLUGIN_DATA = "plugin_data"


class DeleteMode(StrEnum):
    """匹配记录删除的稳定模式。"""

    RECORD_ONLY = "record_only"
    RECORD_AND_FILE = "record_and_file"


class BatchDeleteStatus(StrEnum):
    """批量删除单条结果的稳定状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    NOT_EXECUTED = "not_executed"


class RetargetHistoryEntry(StrictModel):
    """一次成功改配目标的审计记录。"""

    operated_at: datetime = Field(default_factory=utc_now)
    old_target_history_id: int | None = None
    new_target_history_id: int | None = None
    old_history_target_path: Path | None = None
    new_history_target_path: Path | None = None
    old_target_path: Path | None = None
    new_target_path: Path
    new_matched_path_mapping: PathMappingSnapshot | None = None
    old_subtitle_path: Path
    new_subtitle_path: Path


class MatchRecord(StrictModel):
    """已落盘、暂存或未匹配字幕的持久记录。"""

    id: str = Field(default_factory=new_id)
    subtitle_file_name: str
    format: str
    size: int | None = None
    media_title: str | None = None
    year: int | None = None
    media_type: MediaType = MediaType.UNKNOWN
    season: int | None = None
    episode: int | None = None
    status: RecordStatus
    source: SubtitleSource
    package_scope: PackageScope = PackageScope.UNKNOWN
    location: FileLocation
    path: Path
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    staged_at: datetime | None = None
    consumed_at: datetime | None = None
    canonical_identity_type: MediaIdentityKind | None = None
    canonical_identity_value: str | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    target_history_id: int | None = None
    history_target_path: Path | None = None
    target_path: Path | None = None
    matched_path_mapping: PathMappingSnapshot | None = None
    target_file_exists: bool | None = None
    final_subtitle_path: Path | None = None
    source_task_id: str
    consumed_task_id: str | None = None
    candidate_key: str
    candidate_name: str | None = None
    logical_source_path: Path | None = None
    file_attribution_method: FileAttributionMethod | None = None
    unmatched_reason: UnmatchedReason | None = None
    language: str
    translation_type: TranslationType = TranslationType.UNKNOWN
    hearing_impaired: bool = False
    exact_id_match: bool = False
    site_priority: int | None = None
    trusted: bool = False
    score: float | None = None
    votes: int | None = None
    download_count: int | None = None
    uploaded_at: datetime | None = None
    revision: int | None = None
    retarget_history: list[RetargetHistoryEntry] = Field(default_factory=list)

    @property
    def inventory_key(self) -> tuple[str, MediaIdentityKind, str, int, int] | None:
        """返回暂存字幕的精确库存键。"""

        if (
            self.media_type is MediaType.UNKNOWN
            or not self.canonical_identity_type
            or not self.canonical_identity_value
            or self.season is None
            or self.episode is None
        ):
            return None
        return (
            self.media_type.value,
            self.canonical_identity_type,
            self.canonical_identity_value,
            self.season,
            self.episode,
        )


@dataclass(frozen=True, slots=True)
class CommittedFileFact:
    """一条媒体目录字幕与匹配记录已共同提交的文件事实。"""

    record: MatchRecord
    target_path: Path
    subtitle_path: Path


@dataclass(slots=True)
class InventoryConsumeResult:
    """字幕库存消费结果。"""

    matched: bool = False
    record: MatchRecord | None = None
    records: list[MatchRecord] = field(default_factory=list)
    committed_files: list[CommittedFileFact] = field(default_factory=list)
    warning: str | None = None

    def __post_init__(self) -> None:
        """同步单条和多条结果表示。"""

        if self.record is not None and not self.records:
            self.records = [self.record]
        elif self.records and self.record is None:
            self.record = self.records[0]
        self.matched = self.matched or bool(self.records)
        if not self.committed_files:
            self.committed_files = [
                CommittedFileFact(
                    record=record,
                    target_path=record.target_path or record.path,
                    subtitle_path=record.final_subtitle_path or record.path,
                )
                for record in self.records
                if record.status is RecordStatus.MATCHED and record.location is FileLocation.MEDIA_DIRECTORY
            ]


@dataclass(frozen=True, slots=True)
class DeleteRecordConfirmation:
    """用户确认删除时看到的记录版本快照。"""

    delete_mode: DeleteMode
    expected_status: RecordStatus
    expected_location: FileLocation
    expected_path: Path
    expected_updated_at: datetime

    def __post_init__(self) -> None:
        """把删除模式收敛为记录能力枚举。"""

        if not isinstance(self.delete_mode, DeleteMode):
            object.__setattr__(self, "delete_mode", DeleteMode(self.delete_mode))


@dataclass(frozen=True, slots=True)
class DeleteRecordResult:
    """匹配记录删除用例的领域结果。"""

    success: bool = False
    error_code: str | None = None
    message: str | None = None
    consistency_risk: bool = False


@dataclass(frozen=True, slots=True)
class BatchDeleteRecordConfirmation:
    """一条批量删除记录及其用户确认版本。"""

    record_id: str
    confirmation: DeleteRecordConfirmation


@dataclass(frozen=True, slots=True)
class BatchDeletePreflightItem:
    """批量删除中单条记录的预检结果。"""

    record_id: str
    record: MatchRecord | None = None
    error_code: str | None = None
    message: str | None = None

    @property
    def executable(self) -> bool:
        """返回该条记录是否已通过删除前置校验。"""

        return self.record is not None and self.error_code is None


@dataclass(frozen=True, slots=True)
class BatchDeletePreflight:
    """批量删除的完整预检结果。"""

    items: list[BatchDeletePreflightItem]

    @property
    def executable(self) -> bool:
        """返回整批是否可以开始执行。"""

        return bool(self.items) and all(item.executable for item in self.items)


@dataclass(frozen=True, slots=True)
class BatchDeleteResultItem:
    """批量删除中单条记录的执行结果。"""

    record_id: str
    status: BatchDeleteStatus
    error_code: str | None = None
    message: str | None = None
    consistency_risk: bool = False

    def __post_init__(self) -> None:
        """把批量删除状态收敛为记录能力枚举。"""

        if not isinstance(self.status, BatchDeleteStatus):
            object.__setattr__(self, "status", BatchDeleteStatus(self.status))


@dataclass(frozen=True, slots=True)
class BatchDeleteResult:
    """批量删除的预检与逐条执行汇总结果。"""

    preflight: BatchDeletePreflight
    items: list[BatchDeleteResultItem]
    started: bool

    @property
    def success_count(self) -> int:
        """返回已成功删除的记录数量。"""

        return sum(1 for item in self.items if item.status is BatchDeleteStatus.SUCCESS)

    @property
    def failure_count(self) -> int:
        """返回已执行但未成功删除的记录数量。"""

        return sum(1 for item in self.items if item.status is BatchDeleteStatus.FAILED)

    @property
    def not_executed_count(self) -> int:
        """返回因一致性风险而未开始执行的记录数量。"""

        return sum(1 for item in self.items if item.status is BatchDeleteStatus.NOT_EXECUTED)


@dataclass(frozen=True, slots=True)
class RetargetPreview:
    """改配确认前的当前路径解析结果。"""

    target_history_id: int
    history_target_path: Path
    target_path: Path
    final_subtitle_path: Path
    directory_available: bool
    directory_error: str | None = None


@dataclass(frozen=True, slots=True)
class RetargetResult:
    """改配目标的领域结果。"""

    record: MatchRecord | None = None
    preview: RetargetPreview | None = None
    error_code: str | None = None
    message: str | None = None
    consistency_risk: bool = False
    records: list[MatchRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        """同步单条和多条结果表示。"""

        if self.record is not None and not self.records:
            object.__setattr__(self, "records", [self.record])
        elif self.records and self.record is None:
            object.__setattr__(self, "record", self.records[0])

    @property
    def success(self) -> bool:
        """判断改配或预览是否完整成功。"""

        return (bool(self.records) or self.preview is not None) and self.error_code is None


@dataclass(frozen=True, slots=True)
class RetargetMapping:
    """一条匹配记录到整理历史目标的批量改配映射。"""

    record_id: str
    target_history_id: int | None = None


@dataclass(frozen=True, slots=True)
class BatchRetargetPreviewItem:
    """批量改配中单条映射的预检结果。"""

    record_id: str
    current_subtitle_path: Path | None = None
    target_history_id: int | None = None
    target: SearchTarget | None = None
    preview: RetargetPreview | None = None
    error_code: str | None = None
    message: str | None = None

    @property
    def executable(self) -> bool:
        """判断当前映射是否已经具备执行条件。"""

        return (
            self.target_history_id is not None
            and self.target is not None
            and self.preview is not None
            and self.preview.directory_available
            and self.error_code is None
        )


@dataclass(frozen=True, slots=True)
class BatchRetargetPreview:
    """批量改配的整体预检结果。"""

    items: list[BatchRetargetPreviewItem]

    @property
    def executable(self) -> bool:
        """判断整批映射是否都可以开始执行。"""

        return bool(self.items) and all(item.executable for item in self.items)


@dataclass(frozen=True, slots=True)
class BatchRetargetResultItem:
    """批量改配中单条映射的执行结果。"""

    record_id: str
    target_history_id: int
    result: RetargetResult


@dataclass(frozen=True, slots=True)
class BatchRetargetResult:
    """批量改配提交后的预检与逐条执行结果。"""

    preflight: BatchRetargetPreview
    items: list[BatchRetargetResultItem]
    started: bool

    @property
    def success_count(self) -> int:
        """返回成功完成改配的映射数量。"""

        return sum(1 for item in self.items if item.result.success)

    @property
    def failure_count(self) -> int:
        """返回执行失败的映射数量。"""

        return len(self.items) - self.success_count
