"""整理事件的合并与去抖。

一部剧整理时会连续触发几十次「整理完成」，每集一次。这里按分类把路径攒起来：
- 最后一次新增后安静 ``quiet`` 秒才提交（去抖）；
- 从第一次新增起最多等 ``max_wait`` 秒，避免持续有新事件时一直不刷新；
- 同一分类的路径合并，子目录被祖先目录覆盖的去掉；
- 路径太多时退化为刷新该分类目录本身。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .pathmap import merge_paths
from .router import Target


@dataclass
class Batch:
    """一次待提交的刷新：某分类下若干目录。"""

    library_id: str
    library_name: str
    paths: List[str]
    sources: List[str] = field(default_factory=list)


@dataclass
class _Pending:
    library_name: str
    library_dirs: set = field(default_factory=set)
    paths: set = field(default_factory=set)
    sources: list = field(default_factory=list)
    first_at: float = 0.0
    last_at: float = 0.0


class Batcher:
    """线程安全的去抖队列；时钟可注入，便于单测。"""

    def __init__(self, quiet: float = 60.0, max_wait: float = 300.0, max_paths: int = 20,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if quiet < 0 or max_wait < quiet:
            raise ValueError("要求 0 <= quiet <= max_wait")
        self.quiet = quiet
        self.max_wait = max_wait
        self.max_paths = max(1, int(max_paths))
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: Dict[str, _Pending] = {}

    def add(self, target: Target, source: str = "") -> None:
        """登记一个刷新目标。"""
        now = self._clock()
        with self._lock:
            item = self._pending.get(target.library_id)
            if item is None:
                item = _Pending(library_name=target.library_name, first_at=now)
                self._pending[target.library_id] = item
            item.library_dirs.add(target.library_dir)
            item.paths.add(target.path)
            if source and source not in item.sources and len(item.sources) < 50:
                item.sources.append(source)
            item.last_at = now

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def next_due_in(self) -> Optional[float]:
        """距离最早一批到期还有多少秒；没有待办返回 None。"""
        now = self._clock()
        with self._lock:
            if not self._pending:
                return None
            waits = [max(0.0, min(i.last_at + self.quiet, i.first_at + self.max_wait) - now)
                     for i in self._pending.values()]
        return min(waits)

    def pop_due(self, force: bool = False) -> List[Batch]:
        """取出已到期的批次（force=True 取出全部）。"""
        now = self._clock()
        batches: List[Batch] = []
        with self._lock:
            for library_id in list(self._pending):
                item = self._pending[library_id]
                due = force or now - item.last_at >= self.quiet or now - item.first_at >= self.max_wait
                if not due:
                    continue
                del self._pending[library_id]
                paths = merge_paths(item.paths)
                if len(paths) > self.max_paths:
                    paths = merge_paths(item.library_dirs)
                batches.append(Batch(library_id=library_id, library_name=item.library_name,
                                     paths=paths, sources=list(item.sources)))
        return batches
