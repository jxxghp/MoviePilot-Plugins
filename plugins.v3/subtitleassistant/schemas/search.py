"""人工字幕搜索对外结果的公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .candidate import CandidateRecognition
from .source import SourceSearchResult
from .target import SearchTarget
from .task import SubtitleTask

__all__ = [
    "ManualSearchResult",
    "ManualSourceView",
    "ManualSubmitResult",
    "ManualSubmitStatus",
]


class ManualSubmitStatus(StrEnum):
    """人工候选提交的稳定结果状态。"""

    SUCCESS = "success"
    SESSION_NOT_FOUND = "session_not_found"
    CANDIDATE_NOT_FOUND = "candidate_not_found"
    REJECTED = "rejected"


@dataclass(slots=True)
class ManualSourceView:
    """人工搜索的一个来源结果：直用来源最小结果并附加该来源候选的识别标注。"""

    run: SourceSearchResult
    candidates: list[CandidateRecognition] = field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        """返回该来源展示给用户的候选数。"""

        return len(self.candidates)


@dataclass(slots=True)
class ManualSearchResult:
    """一次人工字幕搜索的安全汇总。"""

    session_id: str | None
    target: SearchTarget
    sources: list[ManualSourceView]


@dataclass(slots=True)
class ManualSubmitResult:
    """人工候选提交的稳定领域结果。"""

    status: ManualSubmitStatus
    task: SubtitleTask | None = None

    def __post_init__(self) -> None:
        """把边界处的提交状态收敛为搜索能力枚举。"""

        if not isinstance(self.status, ManualSubmitStatus):
            self.status = ManualSubmitStatus(self.status)
