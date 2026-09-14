"""为 MoviePilot 内置 Bangumi 客户端配置数据与图片代理。"""

from __future__ import annotations

import inspect
import weakref
from functools import wraps
from threading import RLock
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit

from app.plugins import _PluginBase
from app.sdk.logging import logger


_IMAGE_VALUE_KEYS: frozenset[str] = frozenset({"images", "image", "avatar"})

_BANGUMI_IMAGE_HOSTS: frozenset[str] = frozenset(
    {"bgm.tv", "bangumi.tv", "bangumi.lol"}
)
_BANGUMI_IMAGE_SUFFIXES: tuple[str, ...] = (
    ".bgm.tv",
    ".bangumi.tv",
    ".bangumi.lol",
)

# 不需要包装的方法。
_SKIP_METHODS: frozenset[str] = frozenset(
    {"clear_cache", "close", "set_proxy", "set_user_agent"}
)

# 进程级补丁状态，仅在 _PATCH_LOCK 保护下读写。
_PATCH_LOCK = RLock()
_PATCH_STATE: dict[str, Any] = {
    "api_class": None,
    "owner": None,
    "base_url": None,
    "methods": {},
}


def _active_owner() -> Optional["BangumiProxy"]:
    """返回当前持有 BangumiApi 补丁的插件实例。"""
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
    """通过可配置 Base URL 代理 Bangumi 数据与图片请求。"""

    plugin_name = "Bangumi代理"
    plugin_desc = (
        "为 MoviePilot 内置 Bangumi 动漫数据与图片请求配置自定义代理 Base URL。"
    )
    plugin_icon = "Bangumi_A.png"
    plugin_version = "2.0.0"
    plugin_author = "kiritoxjf"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "bangumiproxy_"
    plugin_order = 1
    auth_level = 1

    _enabled: bool = False
    _data_base_url: Optional[str] = None
    _image_base_url: Optional[str] = None
    _image_mode: str = "path"
    _installed: bool = False

    def init_plugin(self, config: dict | None = None) -> None:
        """读取配置并接管内置 BangumiApi，可重复调用。"""
        self.stop_service()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        data_base_url = str(config.get("data_base_url") or "").strip()
        image_base_url = str(config.get("image_base_url") or "").strip()

        self._data_base_url = self._normalize_base_url(
            data_base_url,
            trailing_slash=True,
        )
        self._image_base_url, self._image_mode = self._normalize_image_base_url(
            image_base_url,
        )

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

    def stop_service(self) -> None:
        """恢复内置 BangumiApi 并清理缓存，幂等。"""
        api_class: Optional[type] = None
        with _PATCH_LOCK:
            if _active_owner() is self:
                api_class = _restore_patched_api()

        self._installed = False

        if api_class:
            self._clear_bangumi_cache(api_class)

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        return []

    def get_api(self) -> list[dict[str, Any]]:
        return []

    def get_page(self) -> list[dict]:
        return []

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        """返回配置页面与默认配置。"""
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
                                            "placeholder": "https://proxy.example/ 或 https://proxy.example/?url=",
                                            "clearable": True,
                                            "hint": (
                                                "以 / 结尾仅替换主机；含 ? 按查询参数拼接；"
                                                "其它按路径拼接。"
                                            ),
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

    @staticmethod
    def _normalize_base_url(value: str, trailing_slash: bool) -> Optional[str]:
        """归一化数据代理 Base URL，只接受无查询参数的 HTTP(S) 地址。"""
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

    @staticmethod
    def _normalize_image_base_url(value: str) -> tuple[Optional[str], str]:
        """归一化图片代理 Base URL，返回 (Base URL, 模式)。

        - 含 ``?``：``query``，拼接 URL 编码后的原始地址。
        - 以 ``/`` 结尾：``host_only``，只替换主机，保留原始 path/query。
        - 其它：``path``，按 ``<Base URL>/<原始URL>`` 拼接。
        """
        if not value:
            return None, "path"
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None, "path"
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.fragment
        ):
            return None, "path"
        if parsed.query:
            return value, "query"
        if value.endswith("/"):
            return value.rstrip("/"), "host_only"
        return value, "path"

    def _install_proxy(self) -> None:
        """补丁化 BangumiApi 的所有公共方法，使图片 URL 重写覆盖所有入口。"""
        from app.modules.bangumi import bangumi as bangumi_module

        api_class = bangumi_module.BangumiApi

        with _PATCH_LOCK:
            owner = _active_owner()
            if owner and owner is not self:
                logger.warning(
                    "Bangumi代理：已有另一个实例正在接管 Bangumi 请求，本实例未生效"
                )
                return

            if not owner and _PATCH_STATE["api_class"]:
                stale_class = _restore_patched_api()
                if stale_class:
                    self._clear_bangumi_cache(stale_class)

            original_methods: dict[str, Callable[..., Any]] = {}
            wrapped_sync: list[str] = []
            wrapped_async: list[str] = []

            for method_name in dir(api_class):
                # 跳过魔术方法。
                if method_name.startswith("__") and method_name.endswith("__"):
                    continue
                # 跳过明确不需要包装的方法。
                if method_name in _SKIP_METHODS:
                    continue

                try:
                    method = getattr(api_class, method_name)
                except Exception:
                    continue
                if not callable(method):
                    continue
                # 跳过静态/类方法，避免误包装。
                if isinstance(
                    inspect.getattr_static(api_class, method_name, None),
                    (staticmethod, classmethod),
                ):
                    continue
                # 跳过 property。
                if isinstance(
                    inspect.getattr_static(api_class, method_name, None),
                    property,
                ):
                    continue

                original_methods[method_name] = method

                try:
                    is_coro = inspect.iscoroutinefunction(method)
                except Exception:
                    is_coro = method_name.startswith("async_")

                if is_coro:
                    setattr(
                        api_class,
                        method_name,
                        self._make_async_wrapper(method),
                    )
                    wrapped_async.append(method_name)
                else:
                    setattr(
                        api_class,
                        method_name,
                        self._make_sync_wrapper(method),
                    )
                    wrapped_sync.append(method_name)

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
            "Bangumi代理已启用：数据代理=%s，图片代理=%s（%s）",
            self._data_base_url or "原始地址",
            self._image_base_url or "原始地址",
            self._image_mode,
        )
        logger.info(
            "Bangumi代理：已包装同步方法 %d 个：%s",
            len(wrapped_sync),
            wrapped_sync,
        )
        logger.info(
            "Bangumi代理：已包装异步方法 %d 个：%s",
            len(wrapped_async),
            wrapped_async,
        )

    @staticmethod
    def _make_sync_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(method)
        def wrapped(api_self: Any, *args: Any, **kwargs: Any) -> Any:
            result = method(api_self, *args, **kwargs)
            owner = _active_owner()
            if owner is None:
                return result
            return owner._rewrite_image_urls(result)

        return wrapped

    @staticmethod
    def _make_async_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(method)
        async def wrapped(api_self: Any, *args: Any, **kwargs: Any) -> Any:
            result = await method(api_self, *args, **kwargs)
            owner = _active_owner()
            if owner is None:
                return result
            return owner._rewrite_image_urls(result)

        return wrapped

    @staticmethod
    def _clear_bangumi_cache(api_class: type) -> None:
        """清除旧代理地址对应的内置 Bangumi 缓存。"""
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
        """递归重写返回体中图片字段的 URL。"""
        if isinstance(value, str):
            return self._proxy_image_url(value) if image_value else value
        if isinstance(value, list):
            return [self._rewrite_image_urls(item, image_value) for item in value]
        if isinstance(value, tuple):
            return tuple(
                self._rewrite_image_urls(item, image_value) for item in value
            )
        if isinstance(value, dict):
            return {
                key: self._rewrite_image_urls(
                    item,
                    image_value or str(key).lower() in _IMAGE_VALUE_KEYS,
                )
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _is_bangumi_image_url(image_url: str) -> bool:
        """判断 URL 是否指向 Bangumi 图片主机。"""
        if not isinstance(image_url, str) or not image_url:
            return False
        try:
            parsed = urlsplit(image_url)
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        if hostname in _BANGUMI_IMAGE_HOSTS:
            return True
        return any(
            hostname.endswith(suffix) for suffix in _BANGUMI_IMAGE_SUFFIXES
        )

    def _proxy_image_url(self, image_url: str) -> str:
        """按配置拼接图片代理地址，支持查询参数、仅替换主机、路径拼接三种模式。"""
        if not self._image_base_url:
            return image_url
        if not self._is_bangumi_image_url(image_url):
            return image_url

        if self._image_mode == "query":
            if image_url.startswith(self._image_base_url):
                return image_url
            return f"{self._image_base_url}{quote(image_url, safe='')}"

        if self._image_mode == "host_only":
            parsed = urlsplit(image_url)
            proxy_host = (urlsplit(self._image_base_url).hostname or "").lower()
            if (parsed.hostname or "").lower() == proxy_host:
                return image_url
            path = parsed.path or ""
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{self._image_base_url}{path}{query}"

        if image_url.startswith(f"{self._image_base_url}/"):
            return image_url
        return f"{self._image_base_url}/{image_url}"