"""字幕归属识别能力的调用侧契约。"""

from collections.abc import Mapping
from typing import Protocol

from ..schemas.attribution import (
    CandidateAttributionSnapshot,
    CandidateMatchContext,
    FileAttributionBatchResult,
    FileAttributionEvidence,
    FileAttributionRequest,
    PackageAttributionStrategy,
)
from ..schemas.candidate import CandidateRecognition, SubtitleCandidate
from ..schemas.target import SubtitleTarget


class CandidateRecognizer(Protocol):
    """识别人工候选与当前字幕目标的关系。"""

    def recognize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> CandidateRecognition:
        """返回候选识别结果。"""

    def candidate_snapshot(self, candidate: SubtitleCandidate) -> CandidateAttributionSnapshot:
        """提取可持久化的候选归属快照。"""

    def normalize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> SubtitleCandidate | None:
        """按自动任务规则归一化并筛选候选。"""


class FileAttributor:
    """按一般化请求批量归属字幕文件。"""

    def __init__(self, recognizer: object | None = None) -> None:
        """创建归属 facade 并隐藏内部实现。"""

        from .service import AttributionService

        self._service = AttributionService(recognizer=recognizer)

    def recognize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> CandidateRecognition:
        """识别人工候选与当前字幕目标的关系。"""

        return self._service.recognize_candidate(candidate, context, match_context)

    def candidate_snapshot(self, candidate: SubtitleCandidate) -> CandidateAttributionSnapshot:
        """提取可持久化的候选归属快照。"""

        return self._service.candidate_snapshot(candidate)

    def normalize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> SubtitleCandidate | None:
        """按自动任务规则归一化并筛选候选。"""

        return self._service.normalize_candidate(candidate, context, match_context)

    async def attribute_requests(
        self,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        snapshot: CandidateAttributionSnapshot,
        requests: list[FileAttributionRequest],
        strategy: PackageAttributionStrategy,
        *,
        evidence_by_key: Mapping[str, FileAttributionEvidence] | None = None,
    ) -> FileAttributionBatchResult:
        """返回每个字幕文件的规则归属证据。"""

        return await self._service.attribute_requests(
            context,
            candidate,
            snapshot,
            requests,
            strategy,
            evidence_by_key=evidence_by_key,
        )


__all__ = ["CandidateRecognizer", "FileAttributor"]
