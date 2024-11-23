from app.plugins import _PluginBase
from app.core.event import eventmanager
from app.schemas.types import EventType
from app.utils.http import RequestUtils
from typing import Any, List, Dict, Tuple
from app.log import logger
from fastapi import APIRouter, Request, HTTPException

class HttpMessageForwarder(_PluginBase):
    # 插件名称
    plugin_name = "HTTP消息转发器"
    # 插件描述
    plugin_desc = "接收HTTP请求并将消息转发到指定的URL。"
    # 插件图标
    plugin_icon = "forward.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "KoWming"
    # 作者主页
    author_url = "https://github.com/KoWming/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "httpmessageforwarder_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _forward_url = None
    _method = None
    _enabled = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._forward_url = config.get("forward_url")
            self._method = config.get('request_method')

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/forward",
                "endpoint": self.forward_message,
                "method": "POST",
                "summary": "消息转发接口",
                "description": "接收HTTP POST请求并将请求体中的消息转发到指定URL。",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        request_options = ["POST", "GET"]
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
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'request_method',
                                            'label': '请求方式',
                                            'items': request_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'forward_url',
                                            'label': '目标URL'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "request_method": "POST",
            "forward_url": ""
        }

    def get_page(self) -> List[dict]:
        pass

    async def forward_message(self, request: Request):
        if not self._enabled or not self._forward_url:
            raise HTTPException(status_code=400, detail="转发服务未启用或目标URL未设置")

        body = await request.body()
        headers = request.headers

        try:
            if self._method == 'POST':
                response = RequestUtils(content_type=headers.get('Content-Type')).post_res(self._forward_url, data=body, headers=dict(headers))
            else:
                response = RequestUtils().get_res(self._forward_url, params=body, headers=dict(headers))

            if response and response.status_code == 200:
                return {"status": "success", "message": "消息已成功转发"}
            else:
                raise HTTPException(status_code=response.status_code, detail=f"转发失败: {response.text}")
        except Exception as e:
            logger.error(f"消息转发失败: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def stop_service(self):
        """
        退出插件
        """
        pass