"""字幕任务生命周期与候选尝试公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, JsonValue

from .base import StrictModel, new_id, utc_now
from .candidate import PackageScope
from .event import SubtitleWrittenOperation
from .source import CandidateHandle, SubtitleSource
from .target import MediaType, PathMappingSnapshot, SubtitleTarget

if TYPE_CHECKING:
    from .attribution import CandidateMatchContext

__all__ = [
    "AttemptResult",
    "CandidateAttemptReasonCode",
    "SubtitleTask",
    "TaskStatus",
    "TaskTrigger",
    "TaskWorkItem",
]


class TaskStatus(StrEnum):
    """字幕任务顶层状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TaskTrigger(StrEnum):
    """字幕任务的稳定触发方式。"""

    TRANSFER_EVENT = "transfer_event"
    MANUAL_CANDIDATE = "manual_candidate"


class AttemptResult(StrEnum):
    """候选下载尝试的业务结论。"""

    SUCCESS = "success"
    DOWNLOAD_FAILED = "download_failed"
    EXTRACT_FAILED = "extract_failed"
    NO_MATCH = "no_match"
    WRITE_FAILED = "write_failed"
    INTERRUPTED = "interrupted"


class CandidateAttemptReasonCode(StrEnum):
    """字幕任务候选尝试失败时使用的稳定原因码。"""

    MANUAL_CANDIDATE_FAILED = "manual_candidate_failed"
    TARGET_DIRECTORY_UNAVAILABLE = "target_directory_unavailable"
    SUBTITLE_DESTINATION_CONFLICT = "subtitle_destination_conflict"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CANDIDATE_MISSING_TARGET_SUBTITLE = "candidate_missing_target_subtitle"


class _CandidateAttemptRetention(StrEnum):
    """候选尝试失败结果的保留策略。"""

    PRESERVE = "preserve"
    DISCARD = "discard"


class SubtitleTask(StrictModel):
    """持久化的字幕任务：身份与目标、终态结论、时间与手动上下文。"""

    id: str = Field(default_factory=new_id)
    trigger: TaskTrigger = TaskTrigger.TRANSFER_EVENT
    media_title: str
    year: int | None = None
    media_type: MediaType = MediaType.UNKNOWN
    season: int | None = None
    episode: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    target_file_name: str
    target_path: Path
    target_history_id: int | None = None
    history_target_path: Path | None = None
    matched_path_mapping: PathMappingSnapshot | None = None
    target_file_exists: bool | None = None
    target_storage: str | None = None

    status: TaskStatus = TaskStatus.QUEUED
    reason_code: str | None = None
    reason_message: str | None = None
    result_source: SubtitleSource | None = None
    result_package_scope: PackageScope | None = None
    result_format: str | None = None
    final_subtitle_path: Path | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None

    manual_source: SubtitleSource | None = None
    manual_candidate_key: str | None = None
    manual_candidate_summary: dict[str, JsonValue] = Field(default_factory=dict)
    actual_search_query: str | None = None

    @property
    def is_terminal(self) -> bool:
        """判断任务是否已经进入终态。"""

        return self.status in {
            TaskStatus.SUCCESS,
            TaskStatus.SKIPPED,
            TaskStatus.FAILED,
            TaskStatus.INTERRUPTED,
        }


@dataclass(slots=True)
class TaskWorkItem:
    """提交给任务能力的运行期工作项。"""

    context: SubtitleTarget
    match_context: CandidateMatchContext | None = None
    target_history_id: int | None = None
    history_target: bool | None = None
    manual_handle: CandidateHandle | None = None
    actual_search_query: str | None = None
    attempt_operation: SubtitleWrittenOperation | None = None
    attempt_retention: Literal["preserve", "discard"] | None = None
    task_id: str | None = None
