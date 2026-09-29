"""可选目标查询与人工字幕搜索会话服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.core.cache import AsyncCache
from app.log import logger

from ..attribution import CandidateRecognizer
from ..schemas.base import new_id
from ..schemas.candidate import CandidateRecognition, CandidateRecognitionStatus
from ..schemas.search import (
    ManualSearchResult,
    ManualSourceView,
    ManualSubmitResult,
    ManualSubmitStatus,
)
from ..schemas.source import (
    CandidateHandle,
    SourceSearchResult,
    SubtitleSource,
)
from ..schemas.target import SearchTarget
from ..schemas.task import SubtitleTask, TaskWorkItem
from ..source import SOURCE_NAMES, CandidatePool, describe_source_run, source_run_is_warning
from ..target import MediaResolver, TargetCatalog, enrich_search_target

SEARCH_SESSION_REGION = "subtitleassistant_manual_search"
SEARCH_SESSION_TTL_SECONDS = 30 * 60


@dataclass(slots=True)
class SessionCandidate:
    """搜索会话内可提交到下载队列的完整候选。"""

    handle: CandidateHandle
    recognition_status: CandidateRecognitionStatus
    actual_query: str | None = None


@dataclass(slots=True)
class ManualSearchSession:
    """由宿主短期缓存保存的人工搜索会话。"""

    target: SearchTarget
    candidates: dict[str, SessionCandidate]


class ManualSearchCachePort(Protocol):
    """人工搜索会话使用的最小异步缓存端口。"""

    async def get(self, key: str, region: str | None = None) -> object:
        """读取一个未经信任的缓存值。"""

    async def set(
        self,
        key: str,
        value: object,
        ttl: int | None = None,
        region: str | None = None,
    ) -> None:
        """保存一个人工搜索会话。"""

    async def clear(self, region: str | None = None) -> None:
        """清除指定缓存区域。"""


class ManualTaskCoordinatorPort(Protocol):
    """人工搜索提交依赖的最小任务协调端口。"""

    async def enqueue(self, item: TaskWorkItem) -> SubtitleTask | None:
        """在协调器锁与持久化流程内入队人工候选并返回任务快照。"""


class ManualSearchService:
    """读取共享来源候选并管理人工搜索短期会话。"""

    def __init__(
        self,
        targets: TargetCatalog,
        candidate_pool: CandidatePool,
        matcher: CandidateRecognizer,
        cache: ManualSearchCachePort | None = None,
        media_resolver: MediaResolver | None = None,
        coordinator: ManualTaskCoordinatorPort | None = None,
    ) -> None:
        """创建人工搜索服务。"""

        self._targets = targets
        self._candidate_pool = candidate_pool
        self._matcher = matcher
        self._cache = cache or AsyncCache(
            cache_type="ttl",
            maxsize=256,
            ttl=SEARCH_SESSION_TTL_SECONDS,
        )
        self._media_resolver = media_resolver
        self._coordinator = coordinator

    @staticmethod
    def _session_key(session_id: str) -> str:
        """构造独立区域内的结构化搜索会话键。"""

        return json.dumps({"session_id": session_id}, sort_keys=True, separators=(",", ":"))

    async def _enrich_target(self, target: SearchTarget) -> SearchTarget:
        """在英文标题缺失时尽力通过宿主媒体能力补充（委托 target 投影）。"""

        return await enrich_search_target(target, self._media_resolver)

    def _annotate_candidates(
        self,
        run: SourceSearchResult,
        target: SearchTarget,
    ) -> tuple[list[CandidateRecognition], list[CandidateHandle]]:
        """对手动来源候选逐条执行识别标注，不筛除任何候选。"""

        recognitions: list[CandidateRecognition] = []
        handles: list[CandidateHandle] = []
        for handle in run.candidates:
            try:
                recognition = self._matcher.recognize_candidate(
                    handle.candidate,
                    target.context,
                    target.match_context,
                )
            except Exception:  # noqa: BLE001 - 单候选异常必须降级且保留会话
                recognition = CandidateRecognition(
                    candidate=handle.candidate.model_copy(deep=True),
                    status=CandidateRecognitionStatus.UNRECOGNIZED,
                )
                logger.warning(f"人工字幕搜索候选 {handle.candidate.candidate_key} 识别异常，已按未识别候选保留")
            recognitions.append(recognition)
            handles.append(CandidateHandle(candidate=recognition.candidate, download_handle=handle.download_handle))
        return recognitions, handles

    @staticmethod
    def _log_source_result(history_id: int, run: SourceSearchResult) -> None:
        """为一次人工来源搜索记录归一后的中文业务结论。"""

        log = logger.warning if source_run_is_warning(run) else logger.info
        prefix = f"整理历史 {history_id} 的人工字幕搜索 {SOURCE_NAMES[run.source]} "
        log(f"{prefix}{describe_source_run(run)}")

    async def search(
        self,
        history_id: int,
        custom_queries: dict[SubtitleSource | str, str | None] | None = None,
    ) -> ManualSearchResult:
        """批量查询三个来源，有候选时创建三十分钟短期会话。"""

        target = await self._targets.get_target(history_id)
        if target is None:
            raise LookupError("目标整理历史不存在或已不可用")
        target = await self._enrich_target(target)
        values = custom_queries or {}
        ordered_sources = list(SubtitleSource)
        normalized_queries = {source: values.get(source, values.get(source.value)) for source in ordered_sources}
        batch = await self._candidate_pool.query(target.context, normalized_queries)
        runs = [batch.sources[source] for source in ordered_sources]
        for run in runs:
            self._log_source_result(history_id, run)
        recognitions_by_run: list[list[CandidateRecognition]] = []
        handles_by_run: list[list[CandidateHandle]] = []
        for run in runs:
            recognitions, handles = self._annotate_candidates(run, target)
            recognitions_by_run.append(recognitions)
            handles_by_run.append(handles)
        session_id = new_id() if any(run.candidates for run in runs) else None
        if session_id:
            candidates: dict[str, SessionCandidate] = {}
            for run, recognitions, handles in zip(
                runs,
                recognitions_by_run,
                handles_by_run,
                strict=True,
            ):
                for recognition, handle in zip(recognitions, handles, strict=True):
                    candidate_key = handle.candidate.candidate_key
                    if candidate_key not in candidates:
                        candidates[candidate_key] = SessionCandidate(
                            handle=handle,
                            recognition_status=recognition.status,
                            actual_query=run.matched_query,
                        )
            session = ManualSearchSession(target=target, candidates=candidates)
            await self._cache.set(
                self._session_key(session_id),
                session,
                ttl=SEARCH_SESSION_TTL_SECONDS,
                region=SEARCH_SESSION_REGION,
            )
        views = [
            ManualSourceView(run=run, candidates=recognitions)
            for run, recognitions in zip(runs, recognitions_by_run, strict=True)
        ]
        candidate_count = sum(len(item.candidates) for item in runs)
        if session_id:
            logger.info(
                f"整理历史 {history_id} 的人工字幕搜索完成，共返回 {candidate_count} 个候选，搜索会话为 {session_id}"
            )
        else:
            logger.warning(f"整理历史 {history_id} 的人工字幕搜索完成，但三个来源都没有返回可下载候选")
        return ManualSearchResult(session_id=session_id, target=target, sources=views)

    async def submit(self, session_id: str, candidate_key: str) -> ManualSubmitResult:
        """校验人工搜索会话并在协调器内提交用户选定候选。"""

        if not isinstance(candidate_key, str) or not candidate_key:
            return ManualSubmitResult(status=ManualSubmitStatus.CANDIDATE_NOT_FOUND)
        session = await self._cache.get(
            self._session_key(session_id),
            region=SEARCH_SESSION_REGION,
        )
        if not isinstance(session, ManualSearchSession):
            return ManualSubmitResult(status=ManualSubmitStatus.SESSION_NOT_FOUND)
        candidate = session.candidates.get(candidate_key)
        if candidate is None:
            return ManualSubmitResult(status=ManualSubmitStatus.CANDIDATE_NOT_FOUND)
        if self._coordinator is None:
            logger.warning("人工字幕候选提交失败：任务协调器当前不可用")
            return ManualSubmitResult(status=ManualSubmitStatus.REJECTED)
        task = await self._coordinator.enqueue(
            TaskWorkItem(
                context=session.target.context,
                match_context=session.target.match_context,
                target_history_id=session.target.history_id,
                history_target=True,
                manual_handle=candidate.handle,
                actual_search_query=candidate.actual_query,
            )
        )
        if task is None:
            return ManualSubmitResult(status=ManualSubmitStatus.REJECTED)
        return ManualSubmitResult(status=ManualSubmitStatus.SUCCESS, task=task)

    async def clear_sessions(self) -> None:
        """按显式管理请求清除人工搜索会话缓存区域。"""

        await self._cache.clear(region=SEARCH_SESSION_REGION)
