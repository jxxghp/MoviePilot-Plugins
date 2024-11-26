import time
from typing import Any
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from app.core.event import eventmanager, Event
from app.schemas import WebhookEventInfo, NotificationType
from app.log import logger

router = APIRouter()

class WebhookRequest(BaseModel):
    title: str
    text: str

class ExternalMessageNotifier(_PluginBase):
    # 插件基本信息
    plugin_name = "外部消息通知"  # 插件名称
    plugin_desc = "接收外部消息并通过当前通知渠道发送消息。"  # 插件描述
    plugin_icon = "forward.png"  # 插件图标
    plugin_version = "1.3"  # 插件版本
    plugin_author = "jxxghp,KoWming"  # 插件作者
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"  # 作者主页
    plugin_config_prefix = "externalmessagenotifier_"  # 插件配置项ID前缀
    plugin_order = 14  # 加载顺序
    auth_level = 1  # 可使用的用户级别

    # 私有属性定义
    _enabled = False  # 是否启用插件

    # 初始化插件方法
    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")  # 从配置中读取是否启用插件

    # 获取插件状态
    def get_state(self) -> bool:
        return self._enabled

    # 获取命令列表
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    # 获取API列表
    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/webhook",
                "endpoint": self.handle_webhook,
                "method": "POST",
                "summary": "处理Webhook消息",
                "description": "接收并处理自定义Webhook消息"
            }
        ]

    # 获取表单配置
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        # 返回表单配置和数据结构
        return [
            {
                'component': 'VForm',
                'content': [
                    # 启用插件开关
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
                    },
                    # 设置说明
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '此插件用于处理自定义Webhook请求并发送通知。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False
        }

    # 获取页面配置
    def get_page(self) -> List[dict]:
        pass

    # 注册事件处理器
    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        if not self._enabled:
            return
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return

        # 构建消息标题
        message_title = event_info.title

        # 构建消息内容
        message_content = event_info.text

        # 发送消息
        self.post_message(mtype=NotificationType.Webhook, title=message_title, text=message_content)

    # 处理Webhook请求
    async def handle_webhook(self, request: Request):
        try:
            data = await request.json()
            webhook_request = WebhookRequest(**data)
            event_info = WebhookEventInfo(
                event="custom",  # 自定义事件类型
                title=webhook_request.title,
                text=webhook_request.text
            )
            event = Event(event_type=EventType.WebhookMessage, event_data=event_info)
            self.send(event)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"处理Webhook请求时出错：{str(e)}")
            raise HTTPException(status_code=400, detail=str(e))

    # 发送消息
    def post_message(self, mtype: NotificationType, title: str, text: str):
        # 这里可以实现具体的发送消息逻辑，例如通过邮件、短信、推送等方式发送
        logger.info(f"发送消息：{title}\n{text}")

    # 停止服务
    def stop_service(self):
        pass
