"""字幕候选与文件归属的公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import Field, JsonValue

from .base import StrictModel
from .candidate import PackageScope
from .target import MediaIdentityKind, MediaType, SubtitleTarget

__all__ = [
    "AttributionEvidence",
    "CandidateAttributionSnapshot",
    "CandidateMatchContext",
    "FileAttributionBatchResult",
    "FileAttributionEvidence",
    "FileAttributionMethod",
    "FileAttributionRequest",
    "PackageAttributionStrategy",
    "UnmatchedReason",
]


class PackageAttributionStrategy(StrEnum):
    """压缩包内字幕的归属策略。"""

    TRUST_PACKAGE = "trust_package"
    HOST_RECOGNITION = "host_recognition"


class FileAttributionMethod(StrEnum):
    """具体字幕文件实际采用的归属方式。"""

    DIRECT_FILE = "direct_file"
    TRUST_PACKAGE = "trust_package"
    HOST_RECOGNITION = "host_recognition"


class AttributionEvidence(StrEnum):
    """具体字幕季集字段的证据来源。"""

    PATH = "path"
    CANDIDATE_SNAPSHOT = "candidate_snapshot"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class UnmatchedReason(StrEnum):
    """具体字幕无法完整归属的稳定原因。"""

    MEDIA_UNRECOGNIZED = "media_unrecognized"
    SEASON_AMBIGUOUS = "season_ambiguous"
    EPISODE_AMBIGUOUS = "episode_ambiguous"
    CANDIDATE_FILE_SCOPE_CONFLICT = "candidate_file_scope_conflict"
    UNSUPPORTED_FORMAT = "unsupported_format"


class CandidateAttributionSnapshot(StrictModel):
    """下载前只由候选自身事实形成的不可变归属快照。"""

    media_type: MediaType = MediaType.UNKNOWN
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    seasons: list[int] = Field(default_factory=list)
    episodes: list[int] = Field(default_factory=list)
    package_scope: PackageScope = PackageScope.UNKNOWN
    evidence: list[str] = Field(default_factory=list)

    @property
    def canonical_identity(self) -> tuple[MediaIdentityKind, str] | None:
        """返回候选自身可比较的规范媒体身份。"""

        if self.tmdb_id is not None:
            return MediaIdentityKind.TMDB, str(self.tmdb_id)
        if self.imdb_id:
            return MediaIdentityKind.IMDB, self.imdb_id.strip().lower()
        return None


class FileAttributionEvidence(StrictModel):
    """一个下载后字幕文件的安全归属证据。"""

    logical_source_path: Path
    method: FileAttributionMethod
    belongs_to_target_media: bool | None = None
    media_type: MediaType = MediaType.UNKNOWN
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    season: int | None = None
    episode: int | None = None
    season_values: list[int] = Field(default_factory=list)
    episode_values: list[int] = Field(default_factory=list)
    season_evidence: AttributionEvidence = AttributionEvidence.UNKNOWN
    episode_evidence: AttributionEvidence = AttributionEvidence.UNKNOWN
    unmatched_reason: UnmatchedReason | None = None
    host_recognition_summary: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateMatchContext:
    """供宿主匹配 adapter 使用的插件自有媒体事实快照。"""

    title: str
    aliases: tuple[str, ...] = ()
    original_title: str | None = None
    year: int | None = None
    media_type: MediaType = MediaType.UNKNOWN
    tmdb_id: int | None = None
    imdb_id: str | None = None
    douban_id: str | None = None
    bangumi_id: int | None = None
    anilist_id: int | None = None
    season_years: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class FileAttributionRequest:
    """任务提交给文件归属 facade 的一般化单文件输入。"""

    path: Path
    logical_source_path: Path
    target: SubtitleTarget
    candidate_snapshot: CandidateAttributionSnapshot
    strategy: PackageAttributionStrategy


@dataclass(slots=True)
class FileAttributionBatchResult:
    """文件归属 facade 返回的批量证据与稳定结果。"""

    evidence_by_key: dict[str, FileAttributionEvidence] = field(default_factory=dict)
    reason_summary: dict[str, int] = field(default_factory=dict)
    request_count: int = 0
    submitted_count: int = 0
    error_count: int = 0
