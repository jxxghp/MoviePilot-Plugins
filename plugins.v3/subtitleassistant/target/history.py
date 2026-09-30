"""整理历史目标查询与宿主目标事实投影。"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.db.models.transferhistory import TransferHistory
try:
    from app.foundation.text import cut as jieba_cut
except ImportError:  # MoviePilot V2 compatibility
    from app.utils.jieba import cut as jieba_cut

from ..schemas.config import PluginConfig
from ..schemas.target import ResolvedTarget, SearchTarget, SubtitleTarget
from .mapping import resolve_path
from .projection import target_from_history


@dataclass(slots=True)
class TransferHistoryPage:
    """宿主整理历史原始分页结果。"""

    items: list[TransferHistory]
    page: int
    page_size: int
    total: int


class TransferHistoryPort(Protocol):
    """整理历史查询所需的最小宿主端口。"""

    async def async_list_by_page(self, page: int, count: int, status: bool | None = None) -> list[TransferHistory]:
        """分页读取整理历史。"""

    async def async_list_by_title(
        self,
        title: str,
        page: int,
        count: int,
        status: bool | None = None,
        wildcard: bool = False,
    ) -> list[TransferHistory]:
        """按宿主历史搜索语义分页读取整理历史。"""

    async def async_count(self, status: bool | None = None) -> int:
        """统计整理历史数量。"""

    async def async_count_by_title(
        self,
        title: str,
        status: bool | None = None,
        wildcard: bool = False,
    ) -> int:
        """按宿主历史搜索语义统计整理历史数量。"""

    async def async_get(self, historyid: int) -> TransferHistory | None:
        """按编号读取整理历史。"""


class _TransferHistoryAdapter:
    """直接调用宿主整理历史模型的默认端口实现。

    不走 ``TransferHistoryOper``：宿主该操作器的 ``async_list_by_title``
    与 ``async_count_by_title`` 签名中没有 ``wildcard``，无法表达通配符查询。
    宿主自身的 ``history/transfer`` 端点同样绕开操作器直连模型。
    """

    async def async_list_by_page(
        self,
        page: int,
        count: int,
        status: bool | None = None,
    ) -> list[TransferHistory]:
        """按宿主模型分页读取整理历史。"""

        return await TransferHistory.async_list_by_page(None, page=page, count=count, status=status)

    async def async_list_by_title(
        self,
        title: str,
        page: int = 1,
        count: int = 30,
        status: bool | None = None,
        wildcard: bool = False,
    ) -> list[TransferHistory]:
        """按宿主模型实现支持通配符的标题、源路径和目标路径查询。"""

        return await TransferHistory.async_list_by_title(
            None,
            title=title,
            page=page,
            count=count,
            status=status,
            wildcard=wildcard,
        )

    async def async_count(self, status: bool | None = None) -> int:
        """按宿主模型统计整理历史数量。"""

        return int(await TransferHistory.async_count(None, status=status) or 0)

    async def async_count_by_title(
        self,
        title: str,
        status: bool | None = None,
        wildcard: bool = False,
    ) -> int:
        """按宿主模型统计支持通配符的历史查询结果。"""

        return int(
            await TransferHistory.async_count_by_title(
                None,
                title=title,
                status=status,
                wildcard=wildcard,
            )
            or 0
        )

    async def async_get(self, historyid: int) -> TransferHistory | None:
        """按宿主模型读取单条整理历史。"""

        return await TransferHistory.async_get(None, historyid)


def _glob_to_like(pattern: str) -> str:
    """把 MoviePilot 历史搜索使用的 glob 通配符转换为 SQL LIKE。

    与宿主 ``app/api/endpoints/history.py`` 的同名私有函数保持一致。
    """

    escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")


def _history_search_query(value: str | None) -> tuple[str | None, bool | None, bool]:
    """生成宿主历史查询的搜索文本、状态过滤和通配符标记。"""

    query = (value or "").strip()
    if not query:
        return None, None, False
    if query == "成功":
        return None, True, False
    if query == "失败":
        return None, False, False
    if "*" in query or "?" in query:
        return _glob_to_like(query), None, True
    return "%".join(jieba_cut(query, HMM=False)), None, False


class TargetCatalogService:
    """拥有整理历史分页、目标投影与实际字幕路径解析。"""

    def __init__(
        self,
        history_oper: TransferHistoryPort | None = None,
        batch_size: int = 100,
        config_provider: Callable[[], PluginConfig] | None = None,
    ) -> None:
        """创建目标目录服务。"""

        self._history_oper = history_oper or _TransferHistoryAdapter()
        self._batch_size = batch_size
        self._config_provider = config_provider or PluginConfig

    async def _histories(self) -> list[TransferHistory]:
        """分页读取全部成功整理历史。"""

        result: list[TransferHistory] = []
        page = 1
        while True:
            batch = await self._history_oper.async_list_by_page(page=page, count=self._batch_size, status=True)
            if not batch:
                break
            result.extend(batch)
            if len(batch) < self._batch_size:
                break
            page += 1
        return result

    def _to_target(self, history: TransferHistory | None) -> SearchTarget | None:
        """把一条成功的本地文件整理历史投影为插件目标。"""

        return target_from_history(history)

    async def list_targets(
        self,
        page: int = 1,
        page_size: int = 25,
        search: str | None = None,
    ) -> TransferHistoryPage:
        """按宿主历史语义查询并返回当前页原始整理历史。"""

        query, status, wildcard = _history_search_query(search)
        if query is None:
            if status is None:
                items = await self._history_oper.async_list_by_page(page=page, count=page_size)
            else:
                items = await self._history_oper.async_list_by_page(page=page, count=page_size, status=status)
            total = await self._history_oper.async_count(status=status)
        else:
            items = await self._history_oper.async_list_by_title(
                title=query,
                page=page,
                count=page_size,
                status=status,
                wildcard=wildcard,
            )
            total = await self._history_oper.async_count_by_title(
                title=query,
                status=status,
                wildcard=wildcard,
            )
        return TransferHistoryPage(items=items, page=page, page_size=page_size, total=int(total or 0))

    async def list_all_targets(self) -> Sequence[SearchTarget]:
        """返回按最新整理时间去重的有效历史目标。"""

        converted = [self._to_target(row) for row in await self._histories()]
        valid = sorted(
            (item for item in converted if item is not None), key=lambda item: item.transferred_at, reverse=True
        )
        unique: dict[str, SearchTarget] = {}
        for item in valid:
            key = os.path.normcase(os.path.abspath(item.context.target_path))
            unique.setdefault(key, item)
        return list(unique.values())

    async def get_target(self, history_id: int) -> SearchTarget | None:
        """按历史编号返回成功的本地文件目标快照。"""

        history = await self._history_oper.async_get(history_id)
        return self._to_target(history)

    def resolve_actual_subtitle_path(self, target: SubtitleTarget) -> ResolvedTarget:
        """仅在执行文件操作时按当前配置解析并冻结实际字幕目标。"""

        config = self._config_provider()
        resolution = resolve_path(target.target_path, getattr(config, "path_mappings", ()))
        return ResolvedTarget(
            original_path=resolution.original_path,
            resolved_path=resolution.resolved_path,
            mapping=resolution.mapping,
            title=target.title,
            original_title=target.original_title,
            english_title=target.english_title,
            year=target.year,
            media_type=target.media_type,
            season=target.season,
            episode=target.episode,
            tmdb_id=target.tmdb_id,
            imdb_id=target.imdb_id,
            target_file_name=target.target_file_name,
            target_storage=target.target_storage,
            target_type=target.target_type,
            target_extension=target.target_extension,
            target_container=target.target_container,
        )
