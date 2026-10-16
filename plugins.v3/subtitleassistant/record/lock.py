"""匹配记录跨用例 mutation 的异步互斥边界。"""

from __future__ import annotations

import asyncio
from typing import Self


class ReentrantAsyncLock:
    """支持同一协程嵌套获取的异步锁。

    删除、改配和库存消费会共享这一把锁；删除服务在持锁期间还需要调用库存
    的索引方法，因此普通 ``asyncio.Lock`` 会发生自锁。锁只允许当前任务重入，
    其他任务仍会在底层互斥锁上等待。
    """

    def __init__(self) -> None:
        """创建未持有的可重入异步锁。"""

        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[object] | None = None
        self._depth = 0

    async def acquire(self) -> bool:
        """等待并获取锁；当前协程重复获取时只增加嵌套深度。"""

        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("异步锁必须在任务中获取")
        if self._owner is owner:
            self._depth += 1
            return True
        await self._lock.acquire()
        self._owner = owner
        self._depth = 1
        return True

    def release(self) -> None:
        """释放一次锁获取，并在最外层释放底层互斥锁。"""

        owner = asyncio.current_task()
        if owner is None or self._owner is not owner or self._depth <= 0:
            raise RuntimeError("异步锁由非持有协程释放")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()

    def locked(self) -> bool:
        """返回底层锁当前是否被任意任务持有。"""

        return self._lock.locked()

    async def __aenter__(self) -> Self:
        """异步上下文管理器入口。"""

        await self.acquire()
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        """异步上下文管理器出口。"""

        self.release()
