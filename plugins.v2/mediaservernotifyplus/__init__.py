"""MoviePilot V2 适配入口。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.core.event import Event, eventmanager
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaImageType, MediaType, NotificationType
from app.utils.web import WebUtils

from .core import MediaServerNotifyCore, build_library_records, merge_ip_location


class MediaServerNotifyPlus(MediaServerNotifyCore, _PluginBase):
    """支持按事件类型自定义字段的媒体服务器通知。"""

    plugin_name = "媒体库通知"
    plugin_desc = "极简配置可自定义的媒体库通知消息"
    plugin_icon = "mediaplay.png"
    plugin_version = "2.1.3"
    plugin_author = "changzhanghs"
    author_url = "https://github.com/changzhanghs"
    plugin_config_prefix = "mediaservernotifyplus_"
    plugin_order = 14
    auth_level = 1

    _notification_type = NotificationType.MediaServer

    def __init__(self) -> None:
        _PluginBase.__init__(self)
        self._initialize_core()

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event) -> None:
        self.handle_webhook(event)

    def _server_options(self) -> List[Dict[str, str]]:
        try:
            return [
                {"title": config.name, "value": config.name}
                for config in MediaServerHelper().get_configs().values()
            ]
        except Exception as error:
            logger.debug(f"读取媒体服务器配置失败：{error}")
            return []

    def _services(self, channel: Optional[str] = None) -> dict:
        try:
            return MediaServerHelper().get_services(
                type_filter=channel,
                name_filters=self._mediaservers or None,
            ) or {}
        except Exception as error:
            logger.debug(f"读取媒体服务器实例失败：{error}")
            return {}

    def _service_allowed(self, info: Any) -> bool:
        services = self._services(getattr(info, "channel", None))
        server_name = getattr(info, "server_name", None)
        return bool(services and (not server_name or server_name in services))

    def _service(self, server_name: Optional[str], channel: Optional[str] = None) -> Any:
        services = self._services(channel)
        if server_name and server_name in services:
            return services[server_name]
        return next(iter(services.values()), None)

    def _discover_libraries(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for server_name, service_info in self._services().items():
            try:
                instance = service_info.instance
                libraries = instance.get_librarys() or []
                virtual_libraries = []
                for method_name in ("get_emby_virtual_folders", "get_jellyfin_virtual_folders"):
                    method = getattr(instance, method_name, None)
                    if callable(method):
                        virtual_libraries = method() or []
                        break
            except Exception as error:
                logger.debug(f"读取 {server_name} 媒体库失败：{error}")
                continue
            records.extend(build_library_records(server_name, libraries, virtual_libraries))
        return records

    @staticmethod
    def _names(values: Any, limit: int = 5) -> str:
        if not isinstance(values, list):
            return str(values or "")
        names = []
        for value in values[:limit]:
            name = value.get("name") if isinstance(value, dict) else value
            if name:
                names.append(str(name))
        return "、".join(names)

    def _resolve_tmdb_id(self, info: Any) -> Optional[str]:
        tmdb_id = getattr(info, "tmdb_id", None)
        if tmdb_id:
            return str(tmdb_id)
        item = self._raw_item(info)
        provider_ids = item.get("ProviderIds") or {}
        if isinstance(provider_ids, dict) and provider_ids.get("Tmdb"):
            return str(provider_ids["Tmdb"])
        item_path = str(getattr(info, "item_path", "") or "")
        match = re.search(r"[\[{](?:tmdbid|tmdb)[=-](\d+)[\]}]", item_path, re.I)
        if match:
            return match.group(1)
        service_info = self._service(
            getattr(info, "server_name", None), getattr(info, "channel", None)
        )
        item_id = getattr(info, "item_id", None)
        if service_info and item_id:
            try:
                media_item = service_info.instance.get_iteminfo(item_id)
                value = getattr(media_item, "tmdbid", None)
                return str(value) if value else None
            except Exception as error:
                logger.debug(f"从媒体服务器解析 TMDB ID 失败：{error}")
        return None

    def _enrich_context(self, info: Any, context: Dict[str, Any]) -> None:
        action = str(context.get("_action") or "")
        if context.get("ip") and self._field_enabled(action, "ip"):
            try:
                location = WebUtils.get_location(str(context["ip"]))
                if location:
                    context["ip"] = merge_ip_location(context["ip"], location)
            except Exception as error:
                logger.debug(f"查询 IP 归属地失败：{error}")

        tmdb_id = self._resolve_tmdb_id(info)
        if not tmdb_id:
            return
        context["media_source"] = "themoviedb"
        context["media_id"] = tmdb_id
        kind = MediaType.MOVIE if str(getattr(info, "item_type", "")) == "MOV" else MediaType.TV
        context["tmdb_url"] = (
            f"https://www.themoviedb.org/movie/{tmdb_id}"
            if kind == MediaType.MOVIE else f"https://www.themoviedb.org/tv/{tmdb_id}"
        )
        if not any(self._field_enabled(action, field) for field in (
            "rating", "region", "actors", "overview",
        )):
            return

        # TMDB ID 指向剧集本身，通知标题也应始终使用剧名。
        # 不再用季详情覆盖剧集标题，否则会显示成“第 1 季”。
        tmdb = self.chain.tmdb_info(tmdbid=tmdb_id, mtype=kind) or {}
        title = tmdb.get("title") or tmdb.get("name")
        year = str(tmdb.get("release_date") or tmdb.get("first_air_date") or "")[:4]
        context["title"] = title or context["title"]
        context["year"] = year or context["year"]
        context["display_name"] = (
            f"{context['title']} ({context['year']})" if context.get("year") else context["title"]
        )
        context["overview"] = context.get("overview") or tmdb.get("overview") or ""
        vote = tmdb.get("vote_average")
        if vote not in (None, "", 0):
            context["rating"] = f"{float(vote):.1f}/10"
        credits = tmdb.get("credits") or {}
        context["actors"] = self._names(credits.get("cast") if isinstance(credits, dict) else [], 5)
        countries = tmdb.get("production_countries") or tmdb.get("origin_country") or []
        context["region"] = self._names(countries, 3)
        if not context.get("_image"):
            context["_image"] = self.chain.obtain_specific_image(
                mediaid=tmdb_id,
                mtype=kind,
                image_type=MediaImageType.Poster if kind == MediaType.MOVIE else MediaImageType.Backdrop,
                season=getattr(info, "season_id", None),
                episode=getattr(info, "episode_id", None),
            )

    @staticmethod
    def _log_debug(message: str) -> None:
        logger.debug(message)

    @staticmethod
    def _log_error(message: str) -> None:
        logger.error(message, exc_info=True)
