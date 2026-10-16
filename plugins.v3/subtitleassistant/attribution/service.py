"""字幕归属能力的组合实现。

该模块是文件归属的唯一业务实现边界。任务只提交通用文件请求并接收
``FileAttributionBatchResult``；归属只走规则路径（直传信任、信任包身份、
宿主识别），不再包含任何 AI 接管编排。
"""

from __future__ import annotations

from collections.abc import Mapping

from ..schemas.attribution import (
    CandidateAttributionSnapshot,
    CandidateMatchContext,
    FileAttributionBatchResult,
    FileAttributionEvidence,
    FileAttributionRequest,
    PackageAttributionStrategy,
)
from ..schemas.candidate import SubtitleCandidate
from ..schemas.target import SubtitleTarget
from .matching import MoviePilotMatcher


class AttributionService(MoviePilotMatcher):
    """提供候选识别与规则文件归属的统一 facade。"""

    def __init__(self, recognizer: object | None = None) -> None:
        """创建归属能力；宿主 matcher 只作为内部实现依赖。"""

        super().__init__()
        self._recognizer = recognizer

    def normalize_candidate(
        self, candidate: SubtitleCandidate, context: SubtitleTarget, match_context: CandidateMatchContext | None
    ) -> SubtitleCandidate | None:
        """委托候选识别实现执行自动候选归一化。"""

        method = getattr(self._recognizer, "normalize_candidate", None)
        if callable(method):
            return method(candidate, context, match_context)
        return super().normalize_candidate(candidate, context, match_context)

    def candidate_snapshot(self, candidate: SubtitleCandidate) -> CandidateAttributionSnapshot:
        """委托候选识别实现提取候选归属快照。"""

        method = getattr(self._recognizer, "candidate_snapshot", None)
        if callable(method):
            return method(candidate)
        return super().candidate_snapshot(candidate)

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
        """执行规则归属；测试或上游已有证据时只复用该稳定事实。"""

        if evidence_by_key:
            return FileAttributionBatchResult(evidence_by_key=dict(evidence_by_key))
        method = getattr(self._recognizer, "attribute_requests", None)
        if callable(method):
            return await method(context, candidate, snapshot, requests, strategy, evidence_by_key={})
        owner = self._recognizer if self._recognizer is not None else self
        method = getattr(owner, "attribute_file", None)
        if not callable(method):
            raise TypeError("文件归属能力未装配")
        result = FileAttributionBatchResult()
        for index, request in enumerate(requests, start=1):
            try:
                evidence = await method(
                    request.path,
                    request.logical_source_path,
                    context,
                    snapshot,
                    strategy,
                )
            except Exception:  # noqa: BLE001 - 单文件归属失败必须隔离
                result.error_count += 1
                result.reason_summary["adapter_error"] = result.reason_summary.get("adapter_error", 0) + 1
                continue
            if isinstance(evidence, FileAttributionEvidence):
                result.evidence_by_key[f"file_{index:04d}"] = evidence
            else:
                result.error_count += 1
                result.reason_summary["invalid_result"] = result.reason_summary.get("invalid_result", 0) + 1
        return result
