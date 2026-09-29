"""字幕源状态、来源查询结果与下载交接公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, JsonValue

from .base import StrictModel

if TYPE_CHECKING:
    from .candidate import SubtitleCandidate

__all__ = [
    "AssrtDownloadHandle",
    "CandidateHandle",
    "DownloadedAsset",
    "MoviePilotDownloadHandle",
    "OpenSubtitlesDownloadHandle",
    "SourceDetails",
    "SourceErrorCode",
    "SourceHealth",
    "SourcePlanEntry",
    "SourceSearchBatch",
    "SourceSearchResult",
    "SourceSearchStatus",
    "SourceStatus",
    "SubtitleSource",
]


class SubtitleSource(StrEnum):
    """首版字幕源。"""

    MOVIEPILOT = "moviepilot"
    OPENSUBTITLES = "opensubtitles"
    ASSRT = "assrt"


class SourceHealth(StrEnum):
    """字幕源当前健康状态。"""

    PENDING = "pending"
    HEALTHY = "healthy"
    LIMITED = "limited"
    ERROR = "error"
    DISABLED = "disabled"


class SourceSearchStatus(StrEnum):
    """单个字幕源一次查询的最小运行结果六态。"""

    SUCCESS = "success"
    PARTIAL = "partial"
    LIMITED = "limited"
    ERROR = "error"
    DISABLED = "disabled"
    UNCONFIGURED = "unconfigured"


class SourceErrorCode(StrEnum):
    """来源查询与下载可归类的安全错误码。"""

    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_REQUEST = "invalid_request"
    LIMITED = "limited"
    MALFORMED_RESPONSE = "malformed_response"
    REQUEST_FAILED = "request_failed"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"


type SourceDetails = dict[str, JsonValue]
type SourcePlanKind = Literal["id", "title", "filename", "fallback"]


@dataclass(frozen=True, slots=True)
class MoviePilotDownloadHandle:
    """MoviePilot 下载所需的受审计站点定位。"""

    site_id: int
    enclosure: str

    def __post_init__(self) -> None:
        """拒绝无法重新取得资源的站点定位。"""

        if self.site_id <= 0 or not self.enclosure:
            raise ValueError("MoviePilot 下载句柄无效")


@dataclass(frozen=True, slots=True)
class OpenSubtitlesDownloadHandle:
    """OpenSubtitles 下载所需的文件 ID。"""

    file_id: int

    def __post_init__(self) -> None:
        """拒绝无效的文件 ID。"""

        if self.file_id <= 0:
            raise ValueError("OpenSubtitles 下载句柄无效")


@dataclass(frozen=True, slots=True)
class AssrtDownloadHandle:
    """ASSRT 下载所需的字幕 ID。"""

    subtitle_id: int

    def __post_init__(self) -> None:
        """拒绝无效的字幕 ID。"""

        if self.subtitle_id <= 0:
            raise ValueError("ASSRT 下载句柄无效")


type SourceDownloadHandle = MoviePilotDownloadHandle | OpenSubtitlesDownloadHandle | AssrtDownloadHandle


@dataclass(frozen=True, slots=True)
class CandidateHandle:
    """来源交给任务的安全候选与强类型下载句柄。"""

    candidate: SubtitleCandidate
    download_handle: SourceDownloadHandle

    def __post_init__(self) -> None:
        """验证候选来源与白名单下载句柄一致。"""

        if not self._matches_source(self.candidate, self.download_handle):
            raise ValueError("候选与下载句柄来源不一致")

    @staticmethod
    def _matches_source(candidate: SubtitleCandidate, handle: SourceDownloadHandle) -> bool:
        """验证候选来源与其白名单句柄类型相符。"""

        return (
            (candidate.source is SubtitleSource.MOVIEPILOT and isinstance(handle, MoviePilotDownloadHandle))
            or (candidate.source is SubtitleSource.OPENSUBTITLES and isinstance(handle, OpenSubtitlesDownloadHandle))
            or (candidate.source is SubtitleSource.ASSRT and isinstance(handle, AssrtDownloadHandle))
        )


@dataclass(frozen=True, slots=True, init=False)
class DownloadedAsset:
    """字幕源下载到临时目录后的文件。"""

    path: Path
    file_name: str

    def __init__(self, path: Path, file_name: str) -> None:
        """创建并校验下载资产。"""

        object.__setattr__(self, "path", path)
        object.__setattr__(self, "file_name", file_name)
        self.__post_init__()

    def __post_init__(self) -> None:
        """保证下载结果名称与实际临时文件一致。"""

        if self.file_name != self.path.name:
            raise ValueError("下载结果文件名必须等于实际路径名称")


@dataclass(frozen=True, slots=True)
class SourcePlanEntry:
    """来源默认查询计划的展示条目：计划展示的唯一真源。"""

    kind: SourcePlanKind
    label: str
    query: str | None = None
    editable: bool = False


@dataclass(slots=True)
class SourceSearchResult:
    """单个字幕来源一次查询的最小安全结果。"""

    source: SubtitleSource
    status: SourceSearchStatus
    candidates: list[CandidateHandle] = field(default_factory=list)
    matched_query: str | None = None
    default_queries: list[SourcePlanEntry] = field(default_factory=list)
    cache_hit: bool = False
    duration_ms: int = 0
    error_summary: str | None = None
    error_code: SourceErrorCode | None = None
    retry_after_seconds: int | None = None
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        """把边界处的来源状态收敛为六态枚举。"""

        if not isinstance(self.status, SourceSearchStatus):
            self.status = SourceSearchStatus(self.status)


@dataclass(slots=True)
class SourceSearchBatch:
    """全部来源一次查询返回的逐来源结果。"""

    sources: dict[SubtitleSource, SourceSearchResult]


class SourceStatus(StrictModel):
    """字幕源当前状态与非敏感观测。"""

    source: SubtitleSource
    enabled: bool = False
    configured: bool = False
    health: SourceHealth = SourceHealth.PENDING
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_summary: str | None = None
    last_duration_ms: int | None = None
    details: SourceDetails = Field(default_factory=dict)
