from typing import Any, Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase


class MusicCoverProxy(_PluginBase):
    """音乐封面代理插件。"""

    plugin_name = "音乐封面代理"
    plugin_desc = "将音乐探索封面图片 URL 重定向到自定义代理，解决 coverartarchive.org 无法访问导致的封面不显示问题。"
    plugin_icon = "music.png"
    plugin_version = "1.0.0"
    plugin_label = "媒体管理"
    plugin_author = "local"
    plugin_config_prefix = "musiccoverproxy_"
    plugin_order = 99
    auth_level = 1

    # 默认代理地址（留空，由用户自行配置）
    _proxy_base = ""
    _enabled = False

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态。"""
        self.stop_service()
        self._enabled = False
        self._proxy_base = ""
        if not config:
            return
        self._enabled = bool(config.get("enabled"))
        self._proxy_base = str(config.get("proxy_base") or "").rstrip("/")
        if self._enabled:
            self._apply_proxy()

    def _apply_proxy(self) -> None:
        """将音乐封面 URL 生成逻辑重定向到自定义代理。"""
        if not self._proxy_base:
            logger.warning("音乐封面代理：未配置代理地址，请先在插件配置中填写代理地址")
            return
        try:
            from app.modules.musicbrainz import MusicBrainzModule
            from app.modules.listenbrainz import ListenBrainzModule

            # 修改 MusicBrainz 模块的封面 URL 前缀
            MusicBrainzModule._cover_url = f"{self._proxy_base}/release-group"
            logger.info(f"音乐封面代理：MusicBrainz 封面 URL 已重定向到 {self._proxy_base}")

            # 修改 ListenBrainz 模块的封面 URL 前缀
            ListenBrainzModule._release_cover_url = f"{self._proxy_base}/release"
            ListenBrainzModule._release_group_cover_url = f"{self._proxy_base}/release-group"
            logger.info(f"音乐封面代理：ListenBrainz 封面 URL 已重定向到 {self._proxy_base}")
        except Exception as e:
            logger.error(f"音乐封面代理：应用代理失败 - {e}")

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表。"""
        return []

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "proxy_base",
                                            "label": "代理地址",
                                            "placeholder": "https://your-proxy.example.com",
                                            "hint": "用于代理 coverartarchive.org 封面的地址，例如 https://your-proxy.example.com（必填）",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "启用后，音乐探索的封面图片 URL 会重定向到配置的代理地址，解决 coverartarchive.org 无法访问导致的封面不显示问题。请填写你自己的代理地址。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "proxy_base": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页面。"""
        if not self._enabled:
            return None
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "success",
                    "text": f"音乐封面代理已启用，封面 URL 已重定向到 {self._proxy_base}",
                },
            }
        ]

    def stop_service(self) -> None:
        """停止插件后台服务并释放资源。"""
        return None
