"""为 MoviePilot 内置 Bangumi 客户端配置数据与图片代理。"""

from __future__ import annotations

import weakref
from functools import wraps
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from app.log import logger
from app.plugins import _PluginBase


_SYNC_API_METHODS = (
    "search",
    "calendar",
    "detail",
    "credits",
    "subjects",
    "person_detail",
    "person_credits",
    "discover",
)
_ASYNC_API_METHODS = tuple(f"async_{name}" for name in _SYNC_API_METHODS)
_IMAGE_VALUE_KEYS = frozenset({"images", "image", "avatar"})
_BANGUMI_IMAGE_SUFFIXES = (".bgm.tv", ".bangumi.tv", ".bangumi.lol")
_BANGUMI_IMAGE_HOSTS = frozenset({"bgm.tv", "bangumi.tv", "bangumi.lol"})

_PATCH_LOCK = RLock()
_PATCH_STATE: Dict[str, Any] = {
    "api_class": None,
    "owner": None,
    "base_url": None,
    "methods": {},
}


def _active_owner() -> Optional["BangumiProxy"]:
    """返回当前控制 BangumiApi 补丁的插件实例。"""
    owner_ref = _PATCH_STATE["owner"]
    return owner_ref() if owner_ref else None


def _restore_patched_api() -> Optional[type]:
    """恢复被插件替换的 BangumiApi 类属性和方法。"""
    with _PATCH_LOCK:
        api_class = _PATCH_STATE["api_class"]
        if not api_class:
            return None

        api_class._base_url = _PATCH_STATE["base_url"]
        for method_name, method in _PATCH_STATE["methods"].items():
            setattr(api_class, method_name, method)

        _PATCH_STATE.update(
            api_class=None,
            owner=None,
            base_url=None,
            methods={},
        )
        return api_class


class BangumiProxy(_PluginBase):
    """通过兼容 MoonPlus 的 Base URL 规则代理 Bangumi 请求。"""

    plugin_name = "Bangumi代理"
    plugin_desc = "为 MoviePilot 内置 Bangumi 动漫数据与图片请求配置自定义代理 Base URL。"
    plugin_icon = "Bangumi_A.png"
    plugin_version = "1.0.0"
    plugin_author = "kiritoxjf"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "bangumiproxy_"
    plugin_order = 1
    auth_level = 1

    _enabled = False
    _data_base_url: Optional[str] = None
    _image_base_url: Optional[str] = None
    _installed = False

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并接管内置 BangumiApi 的请求地址与图片结果。"""
        self.stop_service()
        config = config or {}

        self._enabled = bool(config.get("enabled"))
        data_base_url = str(config.get("data_base_url") or "").strip()
        image_base_url = str(config.get("image_base_url") or "").strip()
        self._data_base_url = self._normalize_base_url(data_base_url, trailing_slash=True)
        self._image_base_url = self._normalize_base_url(image_base_url, trailing_slash=False)

        if data_base_url and not self._data_base_url:
            logger.warning("Bangumi代理：动漫数据代理 Base URL 无效，已忽略")
        if image_base_url and not self._image_base_url:
            logger.warning("Bangumi代理：动漫图片代理 Base URL 无效，已忽略")
        if not self._enabled:
            return
        if not self._data_base_url and not self._image_base_url:
            logger.warning("Bangumi代理已启用，但未配置有效的代理 Base URL")
            return

        self._install_proxy()

    def get_state(self) -> bool:
        """仅在补丁实际接管 BangumiApi 时报告插件运行中。"""
        return bool(self._enabled and self._installed)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "data_base_url",
                                            "label": "动漫数据代理 Base URL",
                                            "placeholder": "https://bangumi-proxy.example",
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "image_base_url",
                                            "label": "动漫图片代理 Base URL",
                                            "placeholder": "https://bangumi-proxy.example",
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "data_base_url": "",
            "image_base_url": "",
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self) -> None:
        """停用或重载时恢复内置 BangumiApi，避免代理状态泄漏。"""
        api_class = None
        with _PATCH_LOCK:
            if _active_owner() is self:
                api_class = _restore_patched_api()
        self._installed = False
        if api_class:
            self._clear_bangumi_cache(api_class)

    @staticmethod
    def _normalize_base_url(value: str, trailing_slash: bool) -> Optional[str]:
        """只接受无查询参数的 HTTP(S) Base URL，避免错误拼接请求地址。"""
        if not value:
            return None
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            return None
        normalized = value.rstrip("/")
        return f"{normalized}/" if trailing_slash else normalized

    def _install_proxy(self) -> None:
        """补丁化 BangumiApi，使所有内置同步/异步入口使用相同的代理规则。"""
        from app.modules.bangumi import bangumi as bangumi_module

        api_class = bangumi_module.BangumiApi
        with _PATCH_LOCK:
            owner = _active_owner()
            if owner and owner is not self:
                logger.warning("Bangumi代理：已有另一个实例正在接管 Bangumi 请求，本实例未生效")
                return
            if not owner and _PATCH_STATE["api_class"]:
                stale_class = _restore_patched_api()
                if stale_class:
                    self._clear_bangumi_cache(stale_class)

            original_methods: Dict[str, Callable[..., Any]] = {}
            for method_name in _SYNC_API_METHODS:
                method = getattr(api_class, method_name, None)
                if callable(method):
                    original_methods[method_name] = method
                    setattr(api_class, method_name, self._make_sync_wrapper(method))
            for method_name in _ASYNC_API_METHODS:
                method = getattr(api_class, method_name, None)
                if callable(method):
                    original_methods[method_name] = method
                    setattr(api_class, method_name, self._make_async_wrapper(method))

            _PATCH_STATE.update(
                api_class=api_class,
                owner=weakref.ref(self),
                base_url=getattr(api_class, "_base_url", None),
                methods=original_methods,
            )
            if self._data_base_url:
                api_class._base_url = self._data_base_url
            self._installed = True

        self._clear_bangumi_cache(api_class)
        logger.info(
            "Bangumi代理已启用：数据代理=%s，图片代理=%s",
            self._data_base_url or "原始地址",
            self._image_base_url or "原始地址",
        )

    @staticmethod
    def _make_sync_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
        """在不改变 BangumiApi 缓存和请求逻辑的前提下转换图片 URL。"""
        @wraps(method)
        def wrapped(api_self: Any, *args: Any, **kwargs: Any) -> Any:
            result = method(api_self, *args, **kwargs)
            owner = _active_owner()
            return owner._rewrite_image_urls(result) if owner else result

        return wrapped

    @staticmethod
    def _make_async_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
        """异步 BangumiApi 入口对应的图片 URL 转换包装器。"""
        @wraps(method)
        async def wrapped(api_self: Any, *args: Any, **kwargs: Any) -> Any:
            result = await method(api_self, *args, **kwargs)
            owner = _active_owner()
            return owner._rewrite_image_urls(result) if owner else result

        return wrapped

    @staticmethod
    def _clear_bangumi_cache(api_class: type) -> None:
        """代理地址切换后清除旧地址对应的内置 Bangumi 缓存。"""
        api = None
        try:
            api = api_class()
            clear_cache = getattr(api, "clear_cache", None)
            if callable(clear_cache):
                clear_cache()
        except Exception as err:
            logger.warning("Bangumi代理：清除 Bangumi 缓存失败：%s", err)
        finally:
            close = getattr(api, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as err:
                    logger.warning("Bangumi代理：关闭 Bangumi 缓存客户端失败：%s", err)

    def _rewrite_image_urls(self, value: Any, image_value: bool = False) -> Any:
        """仅重写 Bangumi 返回体中的图片字段，保持其它业务 URL 不变。"""
        if isinstance(value, str):
            return self._proxy_image_url(value) if image_value else value
        if isinstance(value, list):
            return [self._rewrite_image_urls(item, image_value) for item in value]
        if isinstance(value, tuple):
            return tuple(self._rewrite_image_urls(item, image_value) for item in value)
        if isinstance(value, dict):
            return {
                key: self._rewrite_image_urls(
                    item,
                    image_value or str(key).lower() in _IMAGE_VALUE_KEYS,
                )
                for key, item in value.items()
            }
        return value

    def _proxy_image_url(self, image_url: str) -> str:
        """按 MoonPlus 约定拼接 ``图片 Base URL/原始图片 URL``。"""
        if not self._image_base_url or image_url.startswith(f"{self._image_base_url}/"):
            return image_url
        try:
            parsed = urlsplit(image_url)
        except ValueError:
            return image_url
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or (
                hostname not in _BANGUMI_IMAGE_HOSTS
                and not hostname.endswith(_BANGUMI_IMAGE_SUFFIXES)
            )
        ):
            return image_url
        return f"{self._image_base_url}/{image_url}"
