"""MoviePilot 字幕助手插件公共入口。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

from .plugin import PluginRuntime, RuntimeInitializationError, build_runtime


class SubtitleAssistant(_PluginBase):
    """仅保留 MoviePilot 宿主接口并委托插件运行态。"""

    plugin_name = "字幕助手"
    plugin_desc = "覆盖搜索、匹配、下载、归属、落盘、维护与审计的字幕全生命周期管理。"
    plugin_icon = (
        "https://raw.githubusercontent.com/yubanmeiqin9048/MoviePilot-Plugins/main/icons/SubtitleAssistant.png"
    )
    plugin_version = "2.0.0"
    plugin_author = "yubanmeiqin9048"
    plugin_label = "字幕"
    plugin_config_prefix = "subtitleassistant_"
    plugin_order = 30
    auth_level = 1

    def __init__(self) -> None:
        """初始化宿主基类与空运行态。"""

        super().__init__()
        self._runtime: PluginRuntime | None = None

    def init_plugin(self, config: Mapping[str, object] | None = None) -> None:
        """停止旧运行态并通过唯一组合根装配新运行态。"""

        self.stop_service()
        try:
            self._runtime = build_runtime(self, config)
        except RuntimeInitializationError as exc:
            self._runtime = None
            logger.error(f"字幕助手插件未启动：{exc}")

    def get_state(self) -> bool:
        """返回当前运行态是否可接受任务。"""

        return self._runtime.get_state() if self._runtime is not None else False

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        """插件不提供远程命令。"""

        return []

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        """声明使用 Vue 联邦组件与构建产物目录。"""

        return "vue", "frontend/dist/assets"

    def get_sidebar_nav(self) -> list[dict[str, Any]]:
        """委托运行态返回工作台侧栏入口。"""

        return self._runtime.get_sidebar_nav() if self._runtime is not None else []

    def get_api(self) -> list[dict[str, Any]]:
        """委托运行态返回 Bearer API 定义。"""

        return self._runtime.get_api() if self._runtime is not None else []

    def get_form(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """委托运行态返回非敏感配置投影。"""

        return self._runtime.get_form() if self._runtime is not None else ([], {})

    def get_page(self) -> None:
        """详情页由完整工作台替代。"""

    @eventmanager.register(EventType.TransferComplete)
    async def on_transfer_complete(self, event: Event) -> None:
        """将宿主整理完成事件交给运行态投影和任务能力。"""

        if self._runtime is not None:
            await self._runtime.on_transfer_complete(event)

    def reset_data_sync(self) -> None:
        """委托运行态同步完成宿主数据重置前清理。"""

        if self._runtime is not None:
            self._runtime.reset_data_sync()

    def stop_service(self) -> None:
        """委托运行态停止任务与关联资源。"""

        if self._runtime is not None:
            self._runtime.stop_sync()


__all__ = ["SubtitleAssistant"]
