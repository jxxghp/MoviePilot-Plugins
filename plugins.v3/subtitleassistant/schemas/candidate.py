"""字幕候选与人工识别公共契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, JsonValue

from .base import StrictModel
from .source import SubtitleSource

__all__ = [
    "CandidateRecognition",
    "CandidateRecognitionStatus",
    "PackageScope",
    "SubtitleCandidate",
    "TranslationType",
]


class CandidateRecognitionStatus(StrEnum):
    """人工候选对当前字幕目标的识别状态。"""

    RECOGNIZED = "recognized"
    UNRECOGNIZED = "unrecognized"


class PackageScope(StrEnum):
    """字幕候选覆盖的季集范围。"""

    SEASON_PACK = "season_pack"
    EPISODE = "episode"
    UNKNOWN = "unknown"


class TranslationType(StrEnum):
    """字幕候选的翻译类型。"""

    HUMAN = "human"
    UNKNOWN = "unknown"
    MACHINE = "machine"
    AI = "ai"


class SubtitleCandidate(StrictModel):
    """不含下载定位和敏感字段的统一字幕候选。"""

    candidate_key: str = Field(min_length=1)
    source: SubtitleSource
    name: str
    file_name: str | None = None
    format: str
    language: str
    translation_type: TranslationType = TranslationType.UNKNOWN
    hearing_impaired: bool = False
    foreign_parts_only: bool = False
    package_scope: PackageScope = PackageScope.UNKNOWN
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    seasons: list[int] = Field(default_factory=list)
    episodes: list[int] = Field(default_factory=list)
    tmdb_id: int | None = None
    imdb_id: str | None = None
    exact_id_match: bool = False
    site_id: int | None = None
    site_priority: int | None = None
    trusted: bool = False
    score: float | None = None
    votes: int | None = None
    download_count: int | None = None
    uploaded_at: datetime | None = None
    revision: int | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CandidateRecognition(StrictModel):
    """人工搜索候选及其对当前目标的识别状态。"""

    candidate: SubtitleCandidate
    status: CandidateRecognitionStatus
