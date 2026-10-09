"""ASSRT 进程内滑动窗口限流器。"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import UTC, datetime, timedelta


class SlidingWindowLimiter:
    """限制连续窗口内请求数量并支持明确冷却。"""

    def __init__(self, limit: int = 5, window_seconds: float = 60.0) -> None:
        """创建滑动窗口限流器。"""

        self._limit = limit
        self._window = window_seconds
        self._requests: deque[float] = deque()
        self._cooldown_until = 0.0
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        """移除窗口外的请求时间。"""

        boundary = now - self._window
        while self._requests and self._requests[0] <= boundary:
            self._requests.popleft()

    def _delay(self, now: float) -> float:
        """计算下一次请求许可前的等待秒数。"""

        self._prune(now)
        cooldown_delay = max(0.0, self._cooldown_until - now)
        window_delay = 0.0
        if len(self._requests) >= self._limit:
            window_delay = max(0.0, self._requests[0] + self._window - now)
        return max(cooldown_delay, window_delay)

    async def acquire(self, wait: bool) -> datetime | None:
        """取得请求许可；非等待模式无许可时返回预计恢复时间。"""

        while True:
            async with self._lock:
                now = time.monotonic()
                delay = self._delay(now)
                if delay <= 0:
                    self._requests.append(now)
                    return None
                retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            if not wait:
                return retry_at
            await asyncio.sleep(delay)

    async def mark_limited(self, seconds: float = 60.0) -> datetime:
        """进入明确冷却并返回预计恢复时间。"""

        async with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)
        return datetime.now(UTC) + timedelta(seconds=seconds)

    async def retry_at(self) -> datetime | None:
        """返回当前受限时的预计恢复时间。"""

        async with self._lock:
            delay = self._delay(time.monotonic())
        if delay <= 0:
            return None
        return datetime.now(UTC) + timedelta(seconds=delay)

    async def reset(self) -> None:
        """清空窗口与冷却状态。"""

        async with self._lock:
            self._requests.clear()
            self._cooldown_until = 0.0
