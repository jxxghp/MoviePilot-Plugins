"""来源管理与批量查询的组合实现。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, Self

from app.core.cache import AsyncCache

from ..schemas.base import utc_now
from ..schemas.source import (
    CandidateHandle,
    DownloadedAsset,
    SourceHealth,
    SourcePlanEntry,
    SourceSearchBatch,
    SourceStatus,
    SubtitleSource,
)
from ..schemas.target import SubtitleTarget
from .base import SubtitleSourceBase


class SourceStorePort(Protocol):
    """来源组合服务所需的状态持久化端口。"""

    async def list_source_statuses(self) -> list[SourceStatus]:
        """读取来源状态。"""

    async def save_source_status(self, status: SourceStatus) -> None:
        """保存来源状态。"""


class SourceAdministration:
    """隐藏来源 adapter 字典并统一提供批量查询、下载与来源管理。"""

    def __init__(self, store: SourceStorePort | None = None) -> None:
        """创建来源能力组合，初始 adapter 集由重建入口装载。"""

        self._store = store
        self._adapters: dict[SubtitleSource, SubtitleSourceBase] = {}
        self._cache = AsyncCache(cache_type="ttl", maxsize=512)

    @classmethod
    def build(
        cls,
        *,
        moviepilot_enabled: bool,
        opensubtitles_enabled: bool,
        assrt_enabled: bool,
        opensubtitles_credentials: dict[str, str],
        assrt_credentials: dict[str, str],
        store: SourceStorePort | None = None,
    ) -> Self:
        """由组合根创建来源 adapter 并返回统一管理 facade。"""

        service = cls(store=store)
        service.rebuild(
            enabled={
                SubtitleSource.MOVIEPILOT: moviepilot_enabled,
                SubtitleSource.OPENSUBTITLES: opensubtitles_enabled,
                SubtitleSource.ASSRT: assrt_enabled,
            },
            credentials={
                SubtitleSource.OPENSUBTITLES: opensubtitles_credentials,
                SubtitleSource.ASSRT: assrt_credentials,
            },
        )
        return service

    def rebuild(
        self,
        *,
        enabled: Mapping[SubtitleSource, bool],
        credentials: Mapping[SubtitleSource, Mapping[str, str]],
    ) -> None:
        """以当前开关与持久化凭据整体重建 adapter 集与新缓存对象。

        重建是纯对象构造，不发起网络请求；旧 adapter 与旧缓存对象不取消、不关闭，
        进行中的查询在入口捕获的旧实例快照上自然跑完，其瞬态随重建消失。
        """

        from .assrt import AssrtSource
        from .moviepilot import MoviePilotSource
        from .opensubtitles import OpenSubtitlesSource

        cache = AsyncCache(cache_type="ttl", maxsize=512)
        self._cache = cache
        self._adapters = {
            SubtitleSource.MOVIEPILOT: MoviePilotSource(
                enabled=enabled[SubtitleSource.MOVIEPILOT],
                cache=cache,
            ),
            SubtitleSource.OPENSUBTITLES: OpenSubtitlesSource(
                enabled=enabled[SubtitleSource.OPENSUBTITLES],
                credentials=dict(credentials.get(SubtitleSource.OPENSUBTITLES, {})),
                cache=cache,
            ),
            SubtitleSource.ASSRT: AssrtSource(
                enabled=enabled[SubtitleSource.ASSRT],
                credentials=dict(credentials.get(SubtitleSource.ASSRT, {})),
                cache=cache,
            ),
        }

    async def query(
        self,
        context: SubtitleTarget,
        custom_queries: Mapping[SubtitleSource, str | None] | None = None,
    ) -> SourceSearchBatch:
        """并发查询全部来源候选，逐来源收敛为最小安全结果。"""

        queries = custom_queries or {}
        runs = await asyncio.gather(
            *(adapter.search(context, queries.get(source)) for source, adapter in self._adapters.items())
        )
        return SourceSearchBatch(sources={run.source: run for run in runs})

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """通过候选来源句柄下载字幕资产。"""

        adapter = self._adapters[handle.candidate.source]
        return await adapter.download(handle, directory)

    def default_queries(self, source: SubtitleSource, context: SubtitleTarget) -> tuple[SourcePlanEntry, ...]:
        """返回前端展示使用的来源结构化默认查询计划条目。"""

        adapter = self._adapters.get(source)
        if adapter is None:
            return ()
        return tuple(adapter.default_queries(context))

    async def statuses(self) -> list[SourceStatus]:
        """读取持久化来源状态。"""

        if self._store is None:
            return []
        return await self._store.list_source_statuses()

    def status_snapshot(self, source: SubtitleSource) -> SourceStatus:
        """返回来源当前配置与非敏感运行详情。"""

        adapter = self._adapters.get(source)
        if adapter is None:
            return SourceStatus(source=source, enabled=False, configured=False)
        return SourceStatus(
            source=source,
            enabled=adapter.enabled,
            configured=adapter.configured,
            details=adapter.runtime_details(),
        )

    async def refresh(self, manual: bool = False) -> list[SourceStatus]:
        """刷新全部来源并持久化状态。"""

        previous = {item.source: item for item in await self._store.list_source_statuses()} if self._store else {}
        results = await asyncio.gather(
            *(adapter.refresh(manual=manual) for adapter in self._adapters.values()), return_exceptions=True
        )
        statuses: list[SourceStatus] = []
        for source, result in zip(self._adapters, results, strict=True):
            if isinstance(result, SourceStatus):
                status = result
            else:
                adapter = self._adapters[source]
                status = SourceStatus(
                    source=source,
                    enabled=adapter.enabled,
                    configured=adapter.configured,
                    health=SourceHealth.ERROR,
                    last_checked_at=utc_now(),
                    last_error_at=utc_now(),
                    last_error_summary="字幕源状态刷新失败",
                )
            old = previous.get(source)
            if old is not None:
                status.last_success_at = status.last_success_at or old.last_success_at
                status.last_error_at = status.last_error_at or old.last_error_at
                status.last_error_summary = status.last_error_summary or old.last_error_summary
                status.details = {**old.details, **status.details}
            statuses.append(status)
            if self._store is not None:
                await self._store.save_source_status(status)
        return statuses

    async def close(self) -> None:
        """释放来源 adapter 与共享来源查询缓存。"""

        await asyncio.gather(*(adapter.close() for adapter in self._adapters.values()), return_exceptions=True)
        closer = getattr(self._cache, "close", None)
        if callable(closer):
            result = closer()
            if inspect.isawaitable(result):
                await result
