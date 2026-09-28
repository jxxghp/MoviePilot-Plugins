from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase


class NotifyImage(_PluginBase):
    # 插件名称
    plugin_name = "通知高清图片"
    # 插件描述
    plugin_desc = "发送通知前将 TMDB 图片地址从 w500 升级为 w1280 高清尺寸，提升飞书等推送渠道的图片清晰度。"
    # 插件图标
    plugin_icon = "notifyimage.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "zf"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "notifyimage_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)

    def stop_service(self):
        pass

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    @staticmethod
    def get_api() -> List[Dict[str, Any]]:
        pass

    @staticmethod
    def get_form() -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件"
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

    @staticmethod
    def get_page() -> List[dict]:
        pass

    def get_module(self) -> Dict[str, Any]:
        return {"post_message": self.post_message}

    def post_message(self, message=None, **kwargs) -> None:
        """发送前升级通知图片分辨率，返回 None 交由系统模块继续发送。"""
        image = getattr(message, "image", None)
        if image and isinstance(image, str) and "/t/p/w500/" in image:
            message.image = image.replace("/t/p/w500/", "/t/p/w1280/")
            logger.info(f"通知图片已升级为高清：{message.image}")
        return None
