import time
from app.plugins import _PluginBase
from app.core.event import eventmanager, Event
from typing import Any, List, Dict, Tuple, Optional
from app.core.event import eventmanager, Event
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import NotificationType
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

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
    _webhook_msg_keys = {}

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
        }

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        """
        发送通知消息
        """
        if not self._enabled:
            return
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return

        # 消息标题
        message_title = event_info.title
        # 消息内容
        message_content = event_info.text
        # 时间
        current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))

        # 构建完整的消息内容
        full_message = f"{message_content}\n时间：{current_time}"

        # 发送消息
        self.post_message(mtype=NotificationType.Webhook,
                          title=message_title, text=full_message)

    def post_message(self, mtype: NotificationType, title: str, text: str, image: Optional[str] = None, link: Optional[str] = None):
        # 这里应该调用实际的通知发送逻辑，例如通过邮件、短信等
        print(f"Sending notification: {title} - {text}")

    def stop_service(self):
        """
        退出插件
        """
        pass

# 定义路由以处理POST请求
@app.post("/webhook")
async def webhook(request: Request):
    webhook_server = WebhookServer()
    data = await request.json()
    event = Event(event_type=EventType.WebhookMessage, event_data=WebhookEventInfo(title=data.get('title'), text=data.get('text')))
    webhook_server.send(event)
    return JSONResponse(content={"status": "success"}, status_code=200)