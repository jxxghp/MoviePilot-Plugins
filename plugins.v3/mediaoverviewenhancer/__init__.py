"""影视简介增强插件：为电影与剧集分集补全更详细的简介并写回 Emby。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.sdk.plugin import _PluginBase
from app.schemas.types import EventType, MessageType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger

from .api import build_api_routes
from .enhancer import DEFAULT_CONFIG, OverviewEnhancer, normalize_config


class MediaOverviewEnhancer(_PluginBase):
    """影视简介增强插件主类。"""

    plugin_name = "影视简介增强"
    plugin_desc = (
        "把电影简介写得更详细，并让剧集每集都有独立简介：TMDB 中文简介优先，"
        "缺失时翻译英文简介或由 AI 依剧集上下文生成；MV 库则依据曲目信息由 AI 生成中文简介，"
        "结果写回 Emby 并锁定字段。"
    )
    plugin_icon = (
        "https://raw.githubusercontent.com/jxxghp/MoviePilot-Frontend/refs/heads/v2/"
        "src/assets/images/misc/edit.png"
    )
    plugin_version = "1.10.0"
    plugin_label = "元数据,媒体库,AI"
    plugin_author = "miguelito39721"
    plugin_config_prefix = "mediaoverviewenhancer_"
    plugin_order = 62
    auth_level = 1

    _enabled = False
    _config: Dict[str, Any] = dict(DEFAULT_CONFIG)
    _engine: Optional[OverviewEnhancer] = None
    _media_server_helper: Any = None

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态与引擎。"""
        self.stop_service()
        self._config = normalize_config(config)
        self._enabled = bool(self._config.get("enabled"))
        try:
            from app.sdk.services import MediaServerHelper

            self._media_server_helper = MediaServerHelper()
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：媒体服务器服务不可用：{err}")
            self._media_server_helper = None
        try:
            self._engine = OverviewEnhancer(
                config=self._config,
                data_dir=self.get_data_path(),
                media_server_helper=self._media_server_helper,
                notify=self._send_notify,
            )
        except Exception as err:  # noqa: BLE001
            logger.error(f"影视简介增强：引擎初始化失败：{err}")
            self._engine = None
        if self._enabled:
            logger.info("影视简介增强插件已启用")

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明插件使用 Vue 联邦组件渲染界面。"""
        return "vue", "dist/assets"

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 路由。"""
        return build_api_routes(self)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """Vue 联邦模式下返回默认配置模型。"""
        return [], dict(self._config or DEFAULT_CONFIG)

    def get_page(self) -> List[dict]:
        """Vue 联邦模式下详情页由远程 Page 组件渲染。"""
        return []

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """声明主界面侧栏入口（可在配置中关闭）。"""
        if not self.get_state() or not self._config.get("show_sidebar_nav"):
            return []
        return [
            {
                "nav_key": "main",
                "title": "影视简介增强",
                "icon": "mdi-text-box-edit-outline",
                "section": "organize",
                "permission": "manage",
                "order": 62,
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时补漏扫描与每日汇总通知服务。"""
        if not self.get_state():
            return []
        services: List[Dict[str, Any]] = []
        hours = int(self._config.get("schedule_hours") or 0)
        if hours > 0:
            services.append(
                {
                    "id": f"{self.__class__.__name__}Scan",
                    "name": "影视简介补漏扫描",
                    "trigger": "interval",
                    "func": self._scheduled_scan,
                    "kwargs": {"hours": max(1, hours)},
                }
            )
        if self._config.get("notify_daily"):
            time_text = str(self._config.get("notify_daily_time") or "21:00")
            try:
                hour, minute = (int(part) for part in time_text.split(":")[:2])
            except (TypeError, ValueError):
                hour, minute = 21, 0
            hour = max(0, min(23, hour))
            minute = max(0, min(59, minute))
            services.append(
                {
                    "id": f"{self.__class__.__name__}DailyNotify",
                    "name": "影视简介增强每日汇总通知",
                    "trigger": CronTrigger.from_crontab(f"{minute} {hour} * * *"),
                    "func": self._daily_notify,
                    "kwargs": {},
                }
            )
        return services

    def stop_service(self) -> None:
        """停止后台任务并释放资源。"""
        if self._engine is not None:
            self._engine.stop()

    # ------------------------------------------------------------------ 事件

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event) -> None:
        """整理入库完成后延迟补全该媒体简介。"""
        if not self.get_state() or self._engine is None:
            return
        try:
            result = self._engine.handle_transfer_event(getattr(event, "event_data", None))
            if result.get("queued"):
                logger.info(f"影视简介增强：{result.get('message')}")
        except Exception as err:  # noqa: BLE001
            logger.error(f"影视简介增强：入库事件处理失败：{err}")

    def _scheduled_scan(self) -> None:
        """定时补漏扫描入口。"""
        if self._engine is None:
            return
        self._engine.start_run({"trigger": "schedule", "media_type": "all"})

    def _daily_notify(self) -> None:
        """每日汇总通知入口。"""
        if self._engine is None:
            return
        result = self._engine.send_daily_summary()
        if not result.get("sent"):
            logger.info(f"影视简介增强：每日汇总未发送：{result.get('message')}")

    def _send_notify(self, title: str, text: str) -> None:
        """发送插件通知；是否发送由引擎按通知类型判断。"""
        try:
            self.post_message(mtype=MessageType.Plugin, title=title, text=text)
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：通知发送失败：{err}")

    # ------------------------------------------------------------------ API 支撑

    @property
    def engine(self) -> Optional[OverviewEnhancer]:
        """返回简介增强引擎实例。"""
        return self._engine

    def engine_config(self) -> Dict[str, Any]:
        """返回当前生效配置，供前端表单初始化。"""
        return dict(self._config or DEFAULT_CONFIG)

    def engine_status(self) -> Dict[str, Any]:
        """返回引擎状态，插件未初始化时给出降级信息。"""
        if self._engine is None:
            return {"enabled": False, "message": "引擎未初始化", "logs": []}
        return self._engine.status()

    def engine_servers(self) -> Dict[str, Any]:
        """返回可用 Emby 服务器清单。"""
        if self._engine is None:
            return {"servers": [], "message": "引擎未初始化"}
        return {"servers": self._engine.server_status()}

    def engine_preview(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """试跑：返回计划处理的条目清单。"""
        if self._engine is None:
            return {"items": [], "errors": ["引擎未初始化"]}
        return self._engine.preview(payload or {})

    def engine_run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """启动后台补全任务。"""
        if self._engine is None:
            return {"started": False, "message": "引擎未初始化"}
        if not self.get_state():
            return {"started": False, "message": "插件未启用"}
        return self._engine.start_run(payload or {})

    def engine_cancel(self) -> Dict[str, Any]:
        """停止当前任务。"""
        if self._engine is None:
            return {"cancelled": False, "message": "引擎未初始化"}
        return self._engine.cancel_run()

    def engine_clear(self) -> Dict[str, Any]:
        """清空处理记录与失败清单（保留回滚备份）。"""
        if self._engine is None:
            return {"cleared": 0, "message": "引擎未初始化"}
        return self._engine.clear_records()

    def engine_retry_failures(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """重试失败条目。"""
        if self._engine is None:
            return {"started": False, "message": "引擎未初始化"}
        if not self.get_state():
            return {"started": False, "message": "插件未启用"}
        return self._engine.retry_failures()

    def engine_rollback(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """把简介回滚到写入前版本。"""
        if self._engine is None:
            return {"rolled_back": 0, "failed": 0, "message": "引擎未初始化"}
        return self._engine.rollback(payload or {})

    def engine_save_config(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """保存前端提交的配置。"""
        data = normalize_config(payload or {})
        self.update_config(data)
        self.init_plugin(data)
        return {"saved": True, "config": data}
