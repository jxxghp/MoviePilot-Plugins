"""字幕落盘事件的 MoviePilot 宿主广播适配器。"""

from __future__ import annotations

from typing import Protocol

from app.core.event import eventmanager
from app.log import logger
from app.schemas.types import EventType

from ..schemas.event import SubtitleWrittenEvent


class _EventManagerPort(Protocol):
    """宿主广播管理器的最小测试替身协议。"""

    def send_event(self, event_type: object, data: object | None = None, priority: int | None = None) -> object | None:
        """把事件放入宿主广播队列。"""


class SubtitleEvents:
    """把应用层字幕落盘事件转换为宿主 PluginAction 广播。"""

    def __init__(self, event_manager: _EventManagerPort | None = None) -> None:
        """绑定宿主事件管理器，默认使用 MoviePilot 全局实例。"""

        self._event_manager = event_manager or eventmanager

    async def publish(self, event: SubtitleWrittenEvent) -> None:
        """尽力广播固定的 subtitle_written 插件动作。"""

        try:
            self._event_manager.send_event(EventType.PluginAction, _host_payload(event))
        except Exception as exc:  # noqa: BLE001 - 广播失败不得反馈到已提交业务
            logger.warning(f"字幕落盘插件动作广播失败，已保留成功业务结果；异常类型为 {type(exc).__name__}")


def _host_payload(event: SubtitleWrittenEvent) -> dict[str, str | None]:
    """把插件事件事实投影为 MoviePilot 的 PluginAction 数据。"""

    return {
        "plugin_id": event.plugin_id,
        "action": event.action,
        "operation": event.operation.value,
        "task_id": event.task_id,
        "record_id": event.record_id,
        "target_path": str(event.target_path),
        "subtitle_path": str(event.subtitle_path),
    }
