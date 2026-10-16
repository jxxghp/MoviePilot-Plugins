"""字幕来源查询与来源管理能力的调用侧契约。"""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from ..schemas.source import (
    CandidateHandle,
    DownloadedAsset,
    SourcePlanEntry,
    SourceSearchBatch,
    SubtitleSource,
)
from ..schemas.target import SubtitleTarget
from .conclusion import (
    SOURCE_NAMES,
    SOURCE_SKIP_REASONS,
    describe_source_run,
    source_run_is_warning,
)
from .service import SourceAdministration


class CandidatePool(Protocol):
    """按归一化字幕目标查询全部来源候选。"""

    async def query(
        self,
        context: SubtitleTarget,
        custom_queries: Mapping[SubtitleSource, str | None] | None = None,
    ) -> SourceSearchBatch:
        """查询全部来源并返回按来源分组的最小安全结果。"""

    async def close(self) -> None:
        """释放来源查询运行资源。"""

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """安全下载一个来源候选。"""

    def default_queries(self, source: SubtitleSource, context: SubtitleTarget) -> tuple[SourcePlanEntry, ...]:
        """返回来源结构化默认查询计划条目的安全预览。"""


__all__ = [
    "SOURCE_NAMES",
    "SOURCE_SKIP_REASONS",
    "CandidatePool",
    "SourceAdministration",
    "describe_source_run",
    "source_run_is_warning",
]
