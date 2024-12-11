import time
from typing import Any, List, Dict, Optional
from app.core.event import eventmanager, Event
from app.helper.notification import NotificationHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from app.utils.web import WebUtils

class WebhookServer(_PluginBase):
    # 插件名称
    plugin_name = "Webhook Server"
    # 插件描述
    plugin_desc = "接收外部应用请求并推送消息。"
    # 插件图标
    plugin_icon = "forward.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp,KoWming"
    # 作者主页
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "webhookserver_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1
    # 私有属性
    _enabled = False
    _notification_helper = None

    def init_plugin(self, config: dict = None):
        self._notification_helper = NotificationHelper()
        if config:
            self._enabled = config.get("enabled")

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> List[dict]:
        return [
            {
                "type": "switch",
                "id": "enabled",
                "name": "启用插件",
                "default": False
            }
        ]

    def send_message(self, title: str, content: str, image: Optional[str] = None):
        if not self._enabled:
            return
        self._notification_helper.send_message(
            title=title,
            text=content,
            image=image
        )

    @eventmanager.register(EventType.ExternalMessage)
    def handle_external_message(self, event: Event):
        event_data = event.event_data or {}
        title = event_data.get("title")
        content = event_data.get("content")
        image = event_data.get("image")
        if title and content:
            self.send_message(title, content, image)

    def stop_service(self):
        pass