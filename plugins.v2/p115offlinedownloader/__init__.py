from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase

from .client import P115HelperClient
from .magnet import mask_hash
from .torrent import normalize_download_content


DEFAULT_BASE_URL = "http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper"
PLUGIN_ICON = (
    "https://raw.githubusercontent.com/DDSRem-Dev/"
    "MoviePilot-Plugins/main/icons/u115.png"
)


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class P115OfflineDownloader(_PluginBase):
    plugin_name = "115离线下载器"
    plugin_desc = "将MoviePilot自定义下载器任务桥接到115网盘STRM助手。"
    plugin_icon = PLUGIN_ICON
    plugin_version = "0.1.0"
    plugin_author = "lijx"
    plugin_config_prefix = "p115offline_"
    plugin_order = 90
    auth_level = 1

    _enabled = False
    _downloader_type = "p115offline"
    _allow_torrent_conversion = True
    _include_trackers = True
    _debug = False
    _client: Optional[P115HelperClient] = None

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._enabled = _as_bool(config.get("enabled"), False)
        self._downloader_type = str(
            config.get("downloader_type") or "p115offline"
        ).strip().lower()
        self._allow_torrent_conversion = _as_bool(
            config.get("allow_torrent_conversion"), True
        )
        self._include_trackers = _as_bool(config.get("include_trackers"), True)
        self._debug = _as_bool(config.get("debug"), False)

        try:
            timeout = int(config.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30

        if self._client:
            self._client.close()
        self._client = P115HelperClient(
            base_url=str(config.get("helper_base_url") or DEFAULT_BASE_URL),
            token=str(config.get("api_token") or ""),
            timeout=timeout,
            verify_ssl=_as_bool(config.get("verify_ssl"), True),
        )

    def get_state(self) -> bool:
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        if not self._enabled:
            return {}
        return {"download": self.download}

    def download(
        self,
        content: Union[Path, str, bytes],
        download_dir: Path,
        cookie: str,
        episodes: Optional[Set[int]] = None,
        category: Optional[str] = None,
        label: Optional[str] = None,
        downloader: Optional[str] = None,
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], str]]:
        del download_dir, cookie, category, label

        if not self._enabled or not downloader:
            return None
        if not DownloaderHelper().is_downloader(
            service_type=self._downloader_type,
            name=downloader,
        ):
            if self._debug:
                logger.debug("【115离线下载器】当前下载器类型不匹配，跳过")
            return None

        logger.info(f"【115离线下载器】接收到下载请求：downloader={downloader}")
        normalized = normalize_download_content(
            content,
            allow_torrent_conversion=self._allow_torrent_conversion,
            include_trackers=self._include_trackers,
        )
        if normalized.error:
            logger.warning(f"【115离线下载器】输入校验失败：{normalized.error}")
            return downloader, None, None, normalized.error
        if not normalized.magnet or not normalized.info_hash:
            return downloader, None, None, "无法生成可提交115的磁力链接"

        logger.info(
            "【115离线下载器】解析下载内容成功："
            f"type={normalized.source_type}, hash={mask_hash(normalized.info_hash)}"
        )
        if episodes:
            logger.warning(
                "【115离线下载器】任务包含选集参数，"
                "115离线下载不支持文件级精确选集"
            )
        if not self._client:
            return downloader, None, None, "115离线下载器客户端未初始化"

        result = self._client.add_offline_task(normalized.magnet)
        if not result.success:
            logger.error(f"【115离线下载器】任务提交失败：{result.message}")
            return downloader, None, None, result.message

        logger.info(
            "【115离线下载器】任务提交成功："
            f"hash={mask_hash(normalized.info_hash)}"
        )
        return downloader, normalized.info_hash, "Original", result.message

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/test_connection",
                "endpoint": self.test_connection,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "测试P115StrmHelper连接",
            }
        ]

    def test_connection(self) -> Dict[str, Any]:
        if not self._client:
            return {"code": 1, "msg": "115离线下载器客户端未初始化"}
        result = self._client.test_connection()
        return {
            "code": 0 if result.success else 1,
            "msg": result.message,
            "data": result.data,
        }

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        form = [
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "allow_torrent_conversion",
                                            "label": "允许公开v1 Torrent转磁力",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "include_trackers",
                                            "label": "磁力包含Tracker/WebSeed",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "downloader_type",
                                            "label": "自定义下载器类型",
                                            "placeholder": "p115offline",
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
                                            "model": "helper_base_url",
                                            "label": "P115StrmHelper API根地址",
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
                                            "model": "api_token",
                                            "label": "MoviePilot API Token",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "timeout",
                                            "label": "请求超时（秒）",
                                            "type": "number",
                                            "min": 1,
                                            "max": 120,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "verify_ssl",
                                            "label": "验证HTTPS证书",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "debug",
                                            "label": "调试日志",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": (
                                                "请先创建类型为p115offline的非默认自定义下载器。"
                                                "私有Torrent、敏感Tracker和纯v2种子始终会被拒绝；"
                                                "连接测试使用已保存的配置。"
                                            ),
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "prepend-icon": "mdi-lan-check",
                                        },
                                        "text": "测试连接（请先保存）",
                                        "events": {
                                            "click": {
                                                "api": (
                                                    f"plugin/{self.__class__.__name__}/"
                                                    "test_connection"
                                                ),
                                                "method": "post",
                                            }
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
        defaults = {
            "enabled": False,
            "downloader_type": "p115offline",
            "helper_base_url": DEFAULT_BASE_URL,
            "api_token": "",
            "timeout": 30,
            "verify_ssl": True,
            "allow_torrent_conversion": True,
            "include_trackers": True,
            "debug": False,
        }
        return form, defaults

    def get_page(self) -> None:
        return None

    def stop_service(self) -> None:
        if self._client:
            self._client.close()
        self._client = None
