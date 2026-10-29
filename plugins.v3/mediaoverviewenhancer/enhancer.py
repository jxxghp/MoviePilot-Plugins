"""影视简介增强核心引擎：扫描媒体库条目、生成更详细的简介并写回媒体服务器。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import threading
import time
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from uuid import uuid4

from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from app.agent.llm.helper import LLMHelper

# 三种处理目标：电影、剧集分集、MV（音乐视频）
MOVIE = "movie"
EPISODE = "episode"
# MV 没有 TMDB/IMDb 条目，简介只能由 AI 依据曲目线索生成
MV = "mv"

# 简介来源标记
SOURCE_TMDB = "tmdb"
SOURCE_TRANSLATE = "translate"
SOURCE_AI = "ai"
# 仅补充演员（People）而不改动简介
SOURCE_PEOPLE = "people"
# 仅维护派生产物（NFO 文件、演员头像），不改动简介内容
SOURCE_MAINTENANCE = "maintenance"

# 状态文件治理：记录上限、外部查询缓存上限、落盘节流
_RECORDS_MAX = 5000
_CACHE_MAX = 3000
_PERSON_IMAGE_MAX = 3000
_CACHE_DAYS = 30
_STATE_SAVE_INTERVAL = 5.0
# 同一条目连续失败达到该次数后，自动扫描不再重试（手动重试/强制重写不受限）
_FAILURE_RETRY_LIMIT = 3
# TMDB 详情在一次运行内的复用窗口（秒）
_TMDB_DETAIL_TTL = 1800.0
# 质量闸门判定为「中文占比过低」时用于区分可重试失败与素材缺失
_UNTRANSLATED_PREFIX = "简介中文占比过低"

# MusicBrainz：MV 没有 TMDB 演职员数据，团体成员只能取自这里
MB_API = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = (
    "MoviePilot-MediaOverviewEnhancer/1.0 "
    "(+https://github.com/jxxghp/MoviePilot-Plugins)"
)
MB_GROUP_TYPES = {"Group", "Orchestra", "Choir"}

# Wikidata：成员数据的第二来源，可直接取到中文标签
WD_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WD_MEMBER_QUERY = (
    "SELECT ?memberLabel ?memberEn WHERE {"
    '  ?group rdfs:label "%s"@en .'
    "  ?group wdt:P527 ?member ."
    '  OPTIONAL { ?member rdfs:label ?memberEn FILTER(lang(?memberEn) = "en") }'
    '  SERVICE wikibase:label { bd:serviceParam wikibase:language "zh-hans,zh,en". }'
    "} LIMIT 40"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    # 媒体服务器与媒体库范围（留空表示全部 Emby 与全部电影/剧集库）
    "servers": [],
    "libraries": [],
    # 触达方式
    "auto_on_transfer": True,
    "post_transfer_delay": 120,
    "schedule_hours": 0,
    # 电影
    "movie_enabled": True,
    "movie_mode": "expand",
    "movie_min_chars": 120,
    "movie_target_chars": 320,
    # 剧集分集
    "episode_enabled": True,
    "episode_mode": "auto",
    "episode_min_chars": 80,
    "episode_target_chars": 160,
    "episode_always_rewrite": False,
    "skip_specials": True,
    # MV（音乐视频）
    "mv_enabled": True,
    "mv_libraries": ["mv"],
    "mv_min_chars": 60,
    "mv_target_chars": 110,
    "mv_write_people": True,
    "mv_people_role": "演唱",
    "mv_member_enabled": True,
    "mv_member_role": "成员",
    "mv_member_translate": True,
    "mv_member_name_mode": "zh",
    "mv_member_source": "both",
    "mv_write_nfo": True,
    "mv_people_avatar": True,
    # 合作署名拆分：把「A & B」「A feat. B」拆成单个艺人，各自取人物头像
    "mv_split_collab": True,
    # MV 派生产物自检：NFO 缺失/过期、演员头像缺失也会被补
    "mv_self_heal": True,
    # NFO 根元素：movie 兼容 Emby/Kodi 视频库，musicvideo 供 Kodi 音乐视频库
    "mv_nfo_root": "movie",
    "nfo_path_map": "/media/:/medias/media/",
    # 数据源与写入
    "translate_foreign": True,
    "ai_generate_when_missing": True,
    "ai_when_source_short": False,
    "tmdb_title_fallback": False,
    "duplicate_detect": True,
    "lock_overview": True,
    "force_rewrite": False,
    # 质量闸门：中文占比、技术词、超长/过短、模板句
    "quality_gate": True,
    "quality_min_cjk_ratio": 0.25,
    # 大模型失败重试次数（指数退避）与旧简介备份保留
    "llm_retries": 2,
    "backup_days": 30,
    "rollback_max": 200,
    # 运行控制
    "concurrency": 2,
    "max_items_per_run": 200,
    # 增量扫描天数（0 表示全库；只对电影/剧集生效）
    "scan_days": 0,
    "notify": True,
    "notify_failure": True,
    "notify_daily": False,
    "notify_daily_time": "21:00",
    "show_sidebar_nav": True,
}


def _as_str_list(value: Any) -> List[str]:
    """把配置值规整成去重的字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n，]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    result: List[str] = []
    for part in parts:
        text = str(part).strip()
        if text and text not in result:
            result.append(text)
    return result


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """把配置值规整成指定区间内的整数。"""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    """把配置值规整成指定区间内的浮点数。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _normalize_hhmm(value: Any, default: str = "21:00") -> str:
    """把配置值规整成 HH:MM 形式的每日通知时间。"""
    match = re.match(r"^(\d{1,2}):(\d{1,2})(?::\d{1,2})?$", str(value or "").strip())
    if not match:
        return default
    hour = _bounded_int(match.group(1), 21, 0, 23)
    minute = _bounded_int(match.group(2), 0, 0, 59)
    if int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return default
    return f"{hour:02d}:{minute:02d}"


def _people_names(value: Any) -> List[str]:
    """提取条目 People 字段中已有的人员名称。"""
    if not isinstance(value, list):
        return []
    names: List[str] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("Name") or "").strip()
            if name:
                names.append(name)
    return names


def normalize_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把外部配置规整成引擎可用的完整配置。"""
    data: Dict[str, Any] = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        data.update(config)
    data["servers"] = _as_str_list(data.get("servers"))
    data["libraries"] = _as_str_list(data.get("libraries"))
    if data.get("movie_mode") not in {"expand", "translate", "ai"}:
        data["movie_mode"] = "expand"
    if data.get("episode_mode") not in {"auto", "tmdb", "ai"}:
        data["episode_mode"] = "auto"
    data["post_transfer_delay"] = _bounded_int(data.get("post_transfer_delay"), 120, 0, 3600)
    data["schedule_hours"] = _bounded_int(data.get("schedule_hours"), 0, 0, 8760)
    data["movie_min_chars"] = _bounded_int(data.get("movie_min_chars"), 120, 0, 4000)
    data["movie_target_chars"] = _bounded_int(data.get("movie_target_chars"), 320, 80, 2000)
    data["episode_min_chars"] = _bounded_int(data.get("episode_min_chars"), 80, 0, 2000)
    data["episode_target_chars"] = _bounded_int(data.get("episode_target_chars"), 160, 40, 1000)
    data["mv_libraries"] = _as_str_list(data.get("mv_libraries")) or ["mv"]
    data["mv_min_chars"] = _bounded_int(data.get("mv_min_chars"), 60, 0, 2000)
    data["mv_target_chars"] = _bounded_int(data.get("mv_target_chars"), 110, 40, 1000)
    data["mv_nfo_root"] = (
        "musicvideo"
        if str(data.get("mv_nfo_root") or "").strip().lower() in {"musicvideo", "music-video", "mv"}
        else "movie"
    )
    data["mv_people_role"] = str(data.get("mv_people_role") or "").strip()[:20] or "演唱"
    data["mv_member_role"] = str(data.get("mv_member_role") or "").strip()[:20] or "成员"
    if data.get("mv_member_name_mode") not in {"zh", "original", "both"}:
        data["mv_member_name_mode"] = (
            "original" if data.get("mv_member_translate") is False else "zh"
        )
    if data.get("mv_member_source") not in {"musicbrainz", "wikidata", "both"}:
        data["mv_member_source"] = "both"
    data["nfo_path_map"] = str(data.get("nfo_path_map") or "").strip() or "/media/:/medias/media/"
    data["quality_min_cjk_ratio"] = _bounded_float(
        data.get("quality_min_cjk_ratio"), 0.25, 0.0, 1.0
    )
    data["llm_retries"] = _bounded_int(data.get("llm_retries"), 2, 0, 5)
    data["backup_days"] = _bounded_int(data.get("backup_days"), 30, 0, 3650)
    data["rollback_max"] = _bounded_int(data.get("rollback_max"), 200, 10, 2000)
    data["concurrency"] = _bounded_int(data.get("concurrency"), 2, 1, 8)
    data["max_items_per_run"] = _bounded_int(data.get("max_items_per_run"), 200, 1, 5000)
    data["scan_days"] = _bounded_int(data.get("scan_days"), 0, 0, 3650)
    data["notify_daily_time"] = _normalize_hhmm(data.get("notify_daily_time"))
    for key in (
        "enabled",
        "auto_on_transfer",
        "movie_enabled",
        "episode_enabled",
        "mv_enabled",
        "mv_write_people",
        "mv_member_enabled",
        "mv_member_translate",
        "mv_write_nfo",
        "mv_people_avatar",
        "mv_split_collab",
        "mv_self_heal",
        "episode_always_rewrite",
        "skip_specials",
        "translate_foreign",
        "ai_generate_when_missing",
        "ai_when_source_short",
        "tmdb_title_fallback",
        "duplicate_detect",
        "lock_overview",
        "force_rewrite",
        "quality_gate",
        "notify",
        "notify_failure",
        "notify_daily",
        "show_sidebar_nav",
    ):
        data[key] = bool(data.get(key))
    return data


def clean_text(text: Any, limit: int = 4000) -> str:
    """清洗模型或接口返回的简介文本。"""
    if text is None:
        return ""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""
    value = value.replace("```", "")
    value = re.sub(r"^\s*(简介|剧情简介|介绍|概述)\s*[:：]\s*", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = value.strip().strip('"').strip("“”").strip()
    return value[:limit]


def visible_length(text: Any) -> int:
    """统计去除空白后的可见字符数。"""
    return len(re.sub(r"\s+", "", str(text or "")))


def text_signature(text: Any) -> str:
    """计算简介文本指纹，用于幂等去重。"""
    normalized = re.sub(r"\s+", "", str(text or ""))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _normalize_title(text: Any) -> str:
    """把标题规整成只保留字母与中日韩文字的小写形式，用于标题匹配。"""
    value = str(text or "").lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "", value)


# 只由技术/文件信息构成的「标题」，例如 1080p、1080i、4K、WEB-DL
_JUNK_TITLE_PATTERN = re.compile(
    r"(?i)^(?:2160p|1080[pi]|720p|480p|4k|uhd|web-?dl|webrip|bluray|blu-?ray|bdrip|"
    r"hdtv|hevc|avc|x264|x265|h\.?264|h\.?265|aac|ac3|eac3|dts|flac|remux|proper|repack|"
    r"extended|unrated|trailer|sample|featurette|bonus|extras?|cd\d|disc\d|part\d)$"
)


def is_usable_title(title: Any) -> bool:
    """判断标题是否足以用于 TMDB 标题匹配。

    纯画质、编码、片源等文件信息（``1080p``、``4K``、``WEB-DL``）或纯数字会被判为
    不可用：这类条目名无法对应真实作品，拿它去搜 TMDB 会命中同名影片并写入
    完全无关的简介。
    """
    raw = str(title or "").strip()
    normalized = _normalize_title(raw)
    if len(normalized) < 2:
        return False
    if normalized.isdigit():
        return False
    compact = re.sub(r"[\s._\-\[\]()]+", "", raw).lower()
    if _JUNK_TITLE_PATTERN.match(compact):
        return False
    # 分辨率与编码连写（1080PX264、720p.H264）同样不是作品名
    if MV_COMPACT_NOISE_PATTERN.fullmatch(compact):
        return False
    # 去掉技术噪声后仍有实际文字，才算可用标题
    stripped = MV_NOISE_PATTERN.sub("", compact)
    return len(re.sub(r"[^0-9a-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "", stripped)) >= 2


def _base_series_title(title: Any) -> str:
    """去掉「第 N 季/部」「Season N」「S01」等季标记，得到剧集基础名。"""
    value = str(title or "").strip()
    value = re.sub(r"(?i)\b(s\d{1,2}|season\s*\d{1,2})\b", " ", value)
    value = re.sub(r"第\s*[0-9一二三四五六七八九十]+\s*[季部期]", " ", value)
    value = re.sub(r"[0-9]+\s*(?=季)", "", value)
    return value.strip(" -—_·:：")


def run_coroutine(coro: Any) -> Any:
    """在没有事件循环的线程中执行协程（必要时另开线程避免嵌套循环）。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Dict[str, Any] = {}
    failure: Dict[str, BaseException] = {}

    def _runner() -> None:
        """在独立线程中运行协程并回传结果。"""
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as err:  # noqa: BLE001 - 需要把异常带回调用线程
            failure["value"] = err

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure["value"]
    return result.get("value")


def event_value(source: Any, *keys: str, default: Any = None) -> Any:
    """从字典或对象中按候选键名读取事件字段。"""
    if source is None:
        return default
    for key in keys:
        if isinstance(source, dict):
            if key in source and source[key] not in (None, ""):
                return source[key]
        else:
            value = getattr(source, key, None)
            if value not in (None, ""):
                return value
    return default


class EmbyClient:
    """Emby 媒体服务器读写客户端。"""

    def __init__(self, name: str, host: str, api_key: str, timeout: int = 30):
        """记录连接信息并准备请求工具。"""
        normalized = str(host or "").strip()
        if normalized and not normalized.startswith(("http://", "https://")):
            normalized = f"http://{normalized}"
        self.name = name
        self._host = normalized.rstrip("/") + "/" if normalized else ""
        self._api_key = api_key
        self._timeout = timeout
        self._user = ""
        self._user_id = ""
        # Emby 的写入接口要求 JSON 请求体，必须显式指定 content_type
        self._request = RequestUtils(content_type="application/json")

    def set_user(self, user: Optional[str] = None) -> None:
        """设置用于读取条目的 Emby 用户名，并清空已缓存的用户 ID。"""
        self._user = str(user or "").strip()
        self._user_id = ""

    @property
    def ready(self) -> bool:
        """判断连接信息是否完整。"""
        return bool(self._host and self._api_key)

    def _url(self, path: str) -> str:
        """拼接 Emby API 地址。"""
        return f"{self._host}emby/{str(path).lstrip('/')}"

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """构造带 api_key 的查询参数。"""
        params: Dict[str, Any] = {"api_key": self._api_key}
        if extra:
            params.update({key: value for key, value in extra.items() if value is not None})
        return params

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """执行 GET 请求并返回 JSON。"""
        response = self._request.get_res(
            url=self._url(path), params=self._params(params), timeout=self._timeout
        )
        if response is None:
            logger.debug(f"影视简介增强：{self.name} GET {path} 无响应")
            return None
        if response.status_code >= 300:
            logger.debug(f"影视简介增强：{self.name} GET {path} HTTP {response.status_code}")
            return None
        try:
            return response.json()
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：{self.name} GET {path} 解析失败 {err}")
            return None

    def list_libraries(self) -> List[Dict[str, Any]]:
        """读取 Emby 媒体库清单。"""
        data = self._get("Library/VirtualFolders")
        return [item for item in data or [] if isinstance(item, dict)]

    def resolve_library_ids(self, names: List[str]) -> List[Optional[str]]:
        """按配置解析视频库的父级 ID。

        Emby 的部分媒体库不返回 CollectionType，因此这里只排除音乐、书籍等
        明确非视频库，其余库一律纳入候选，最终由 IncludeItemTypes 决定取什么。
        """
        targets: List[Optional[str]] = []
        for library in self.list_libraries():
            collection_type = str(library.get("CollectionType") or "").lower()
            if collection_type in {"music", "books", "boxsets"}:
                continue
            if collection_type == "homevideos" and not names:
                continue
            library_name = str(library.get("Name") or "")
            if names and library_name not in names:
                continue
            library_id = str(library.get("ItemId") or library.get("Id") or "")
            if library_id:
                targets.append(library_id)
        return targets

    def iter_items(
        self,
        item_types: str,
        parents: Optional[List[Optional[str]]] = None,
        max_items: int = 20000,
        page_size: int = 200,
        extra_fields: str = "",
        min_date: str = "",
    ) -> Iterator[Dict[str, Any]]:
        """按媒体库分页遍历指定类型的条目。"""
        fields = (
            "ProviderIds,Overview,ProductionYear,PremiereDate,Genres,"
            "SeriesId,SeriesName,ParentIndexNumber,IndexNumber,Name,Type,DateCreated"
        )
        if extra_fields:
            fields = f"{fields},{extra_fields}"
        scanned = 0
        for parent in parents or [None]:
            start = 0
            while scanned < max_items:
                params: Dict[str, Any] = {
                    "Recursive": "true",
                    "IncludeItemTypes": item_types,
                    "Fields": fields,
                    "StartIndex": start,
                    "Limit": page_size,
                    "EnableTotalRecordCount": "false",
                    "ImageTypeLimit": 0,
                }
                if parent:
                    params["ParentId"] = parent
                data = self._get("Items", params)
                items = [item for item in (data or {}).get("Items", []) if isinstance(item, dict)]
                if not items:
                    break
                for item in items:
                    scanned += 1
                    # 增量扫描：只处理最近入库的条目，老条目分页仍推进，避免死循环
                    if min_date and str(item.get("DateCreated") or "")[:10] < min_date:
                        continue
                    yield item
                    if scanned >= max_items:
                        return
                if len(items) < page_size:
                    break
                start += page_size

    def get_item(self, item_id: str, fields: str = "ProviderIds,Overview,Name,ProductionYear") -> Dict[str, Any]:
        """读取单个条目的详情（走 Ids 批量接口，Emby 的 Items/{id} 可能不可用）。"""
        return self.get_items_by_ids([item_id], fields).get(str(item_id), {})

    def get_items_by_ids(
        self,
        ids: List[str],
        fields: str = "ProviderIds,Overview,Name,ProductionYear",
    ) -> Dict[str, Dict[str, Any]]:
        """按 ID 批量读取条目，返回 {item_id: item} 映射。"""
        result: Dict[str, Dict[str, Any]] = {}
        wanted = [str(value) for value in ids if value]
        for index in range(0, len(wanted), 50):
            chunk = wanted[index:index + 50]
            data = self._get(
                "Items",
                {"Ids": ",".join(chunk), "Fields": fields, "Recursive": "true"},
            )
            for item in (data or {}).get("Items", []) or []:
                if isinstance(item, dict) and item.get("Id"):
                    result[str(item["Id"])] = item
        return result

    def search_items(
        self,
        term: str,
        item_types: str = "Movie,Series",
        limit: int = 8,
        year: Optional[str] = None,
        parent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按标题搜索条目（用于入库后自动补全）。"""
        params: Dict[str, Any] = {
            "SearchTerm": term,
            "Recursive": "true",
            "IncludeItemTypes": item_types,
            "Fields": "ProviderIds,Overview,ProductionYear,SeriesId,ParentIndexNumber,IndexNumber,Name,Type",
            "Limit": limit,
            "EnableTotalRecordCount": "false",
        }
        if year:
            params["Years"] = str(year)
        if parent:
            params["ParentId"] = parent
        data = self._get("Items", params)
        return [item for item in (data or {}).get("Items", []) if isinstance(item, dict)]

    def resolve_user_id(self) -> str:
        """解析用于读取条目的 Emby 用户 ID（优先匹配配置里的用户名）。"""
        cached = getattr(self, "_user_id", None)
        if cached:
            return str(cached)
        data = self._get("Users")
        users = [item for item in (data or []) if isinstance(item, dict)]
        chosen = ""
        for user in users:
            if self._user and str(user.get("Name") or "") == self._user:
                chosen = str(user.get("Id") or "")
                break
        if not chosen and users:
            chosen = str(users[0].get("Id") or "")
        self._user_id = chosen
        return chosen

    def get_item_detail(
        self,
        item_id: str,
        fields: str = "ProviderIds,Overview,LockedFields,Name,ProductionYear",
    ) -> Dict[str, Any]:
        """读取单个条目详情，兼容不同 Emby 版本的单条读取路由。"""
        user_id = self.resolve_user_id()
        paths = [f"Users/{user_id}/Items/{item_id}"] if user_id else []
        paths.append(f"Items/{item_id}")
        for path in paths:
            data = self._get(path, {"Fields": fields})
            if isinstance(data, dict) and data:
                return data
        return {}

    def get_full_dto(self, item_id: str) -> Dict[str, Any]:
        """读取条目完整 DTO（不裁剪 Fields），用于安全回写。

        Emby 的 ``UpdateItem`` 会把请求体里缺失的可编辑字段置空，所以写入前必须
        拿到完整条目信息，只修改简介相关字段后再整体提交。
        """
        user_id = self.resolve_user_id()
        paths = [f"Users/{user_id}/Items/{item_id}"] if user_id else []
        paths.append(f"Items/{item_id}")
        for path in paths:
            data = self._get(path)
            if isinstance(data, dict) and data.get("Id"):
                return data
        return {}

    def update_overview(
        self,
        item_id: str,
        overview: str,
        lock: bool = True,
        people: Optional[List[Dict[str, Any]]] = None,
        lock_people: bool = False,
        drop_people: Optional[List[str]] = None,
        dedupe_only: bool = False,
        prune_role: str = "",
        dto: Optional[Dict[str, Any]] = None,
        verify_sink: Optional[Dict[str, Any]] = None,
        unlock_overview: bool = False,
    ) -> Tuple[bool, str]:
        """写入条目的简介，并按需补充演员（People）信息。

        Emby 的 UpdateItem 会整份覆盖条目字段，缺失 ``ProviderIds`` 会直接报 400，
        缺失 ``Name``/``IndexNumber`` 则会被清空。因此这里先读回完整条目，
        只替换简介、演员与锁定字段后整体回写。
        """
        payload = (
            copy.deepcopy(dto)
            if isinstance(dto, dict) and dto.get("Id")
            else self.get_full_dto(item_id)
        )
        if not payload:
            return False, "无法读取条目当前信息，已跳过以避免清空字段"
        provider_ids = payload.get("ProviderIds")
        payload["ProviderIds"] = provider_ids if isinstance(provider_ids, dict) else {}
        # UserData 是每个用户各自的播放状态投影，不属于条目元数据，回写时剔除
        payload.pop("UserData", None)
        payload["Id"] = item_id
        payload["Overview"] = overview
        locked = payload.get("LockedFields") or []
        locked_fields = [str(value) for value in locked if value] if isinstance(locked, list) else []
        if lock:
            if "Overview" not in locked_fields:
                locked_fields.append("Overview")
        elif unlock_overview and "Overview" in locked_fields:
            locked_fields = [value for value in locked_fields if value != "Overview"]
        added_people: List[str] = []
        drop_names = {
            str(name).strip().casefold() for name in (drop_people or []) if str(name).strip()
        }
        if people or drop_names or dedupe_only or prune_role:
            current_people = payload.get("People")
            merged = (
                [dict(item) for item in current_people if isinstance(item, dict)]
                if isinstance(current_people, list)
                else []
            )
            if drop_names:
                merged = [
                    item for item in merged
                    if str(item.get("Name") or "").strip().casefold() not in drop_names
                ]
            # 按角色清理：移除「成员」角色里不在期望名单中的历史写入（如上一轮的旧译名）
            if prune_role:
                expected_names = {
                    str(item.get("Name") or "").strip().casefold() for item in (people or [])
                }
                merged = [
                    item for item in merged
                    if str(item.get("Role") or "").strip() != prune_role
                    or str(item.get("Name") or "").strip().casefold() in expected_names
                ]
            # 按名称去重：Emby 会规范化人员名（大小写不同也算同一人），
            # 历史重试若不去重会堆叠出重复演职员。
            deduped: List[Dict[str, Any]] = []
            seen: set = set()
            for item in merged:
                key = str(item.get("Name") or "").strip().casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            merged = deduped
            names = {str(item.get("Name") or "").strip().casefold() for item in merged}
            for person in people or []:
                if not isinstance(person, dict):
                    continue
                name = str(person.get("Name") or "").strip()
                if not name or name.casefold() in names:
                    continue
                merged.append(dict(person))
                names.add(name.casefold())
                added_people.append(name)
            payload["People"] = merged
            # Emby 的演职员锁字段名是 Cast（不是 People），写错名称时会被直接忽略
            if lock_people and "Cast" not in locked_fields:
                locked_fields.append("Cast")
        # 关闭自动锁定只表示不新增锁，不解除用户已有的字段锁。
        payload["LockedFields"] = locked_fields
        response = self._request.post_res(
            url=self._url(f"Items/{item_id}"),
            params=self._params(),
            json=payload,
            timeout=self._timeout,
        )
        if response is None:
            return False, "请求失败或无响应"
        if response.status_code >= 300:
            return False, f"HTTP {response.status_code}: {str(getattr(response, 'text', '') or '')[:160]}"
        # 写入后回读校验，确认简介真的落库且名称未被破坏
        verify = self.get_item_detail(item_id, "Overview,Name,People")
        if isinstance(verify_sink, dict):
            verify_sink.clear()
            verify_sink.update(verify)
        written = clean_text(verify.get("Overview"))
        if text_signature(written) != text_signature(overview):
            return False, "写入后回读不一致"
        if not verify.get("Name"):
            return False, "写入后条目名称为空"
        if added_people:
            written_names = {
                str(item.get("Name") or "").strip().casefold()
                for item in (verify.get("People") or [])
                if isinstance(item, dict)
            }
            missing = [name for name in added_people if name.casefold() not in written_names]
            if missing:
                return False, f"写入后回读缺少演员信息：{'、'.join(missing[:3])}"
        return True, ""

    def set_remote_image(
        self, item_id: str, image_url: str, image_type: str = "Primary"
    ) -> Tuple[bool, str]:
        """让 Emby 从远程地址抓取并保存条目图片（用于人物头像）。"""
        if not item_id or not image_url:
            return False, "缺少条目或图片地址"
        response = self._request.post_res(
            url=self._url(f"Items/{item_id}/RemoteImages/Download"),
            params=self._params({"Type": image_type, "ImageUrl": image_url}),
            json={},
            timeout=self._timeout,
        )
        if response is None:
            return False, "请求失败或无响应"
        if response.status_code >= 300:
            return False, f"HTTP {response.status_code}"
        return True, ""

    def test_connection(self) -> Tuple[bool, str]:
        """测试 Emby 连接是否可用。"""
        info = self._get("System/Info/Public") or self._get("System/Info")
        if not info:
            return False, "无法读取 Emby 系统信息"
        return True, str(info.get("ServerName") or self.name)


class TmdbProvider:
    """TMDB 简介数据源，按语言缓存分集数据。"""

    def __init__(self) -> None:
        """初始化语言客户端与分集缓存。"""
        self._clients: Dict[str, Any] = {}
        self._season_cache: Dict[Tuple[int, int, str], Dict[int, Dict[str, Any]]] = {}
        self._detail_cache: Dict[Tuple[str, int, str], Tuple[float, Dict[str, Any]]] = {}

    def _client(self, language: str) -> Any:
        """获取指定语言的 TMDB 客户端。"""
        if language not in self._clients:
            from app.modules.themoviedb.tmdbapi import TmdbApi

            self._clients[language] = TmdbApi(language=language)
        return self._clients[language]

    def movie_detail(self, tmdb_id: Any, language: str = "zh-CN") -> Dict[str, Any]:
        """读取电影详情，失败时返回空字典。"""
        return self._detail("movie", tmdb_id, language)

    def tv_detail(self, tmdb_id: Any, language: str = "zh-CN") -> Dict[str, Any]:
        """读取剧集详情，失败时返回空字典。"""
        return self._detail("tv", tmdb_id, language)

    def _detail(self, kind: str, tmdb_id: Any, language: str) -> Dict[str, Any]:
        """按类型读取 TMDB 详情，同一轮内复用结果（分集处理会反复取同一部剧）。"""
        try:
            key = (kind, int(tmdb_id), language)
        except (TypeError, ValueError):
            return {}
        cached = self._detail_cache.get(key)
        if cached and time.time() - cached[0] < _TMDB_DETAIL_TTL:
            return cached[1]
        try:
            client = self._client(language)
            if kind == "movie":
                detail = client.movie.details(key[1]) or {}
            else:
                detail = client.tv.details(key[1]) or {}
        except Exception as err:  # noqa: BLE001
            label = "电影" if kind == "movie" else "剧集"
            logger.debug(f"影视简介增强：TMDB {label}详情读取失败 {tmdb_id} {err}")
            return {}
        data = detail if isinstance(detail, dict) else dict(detail)
        self._detail_cache[key] = (time.time(), data)
        return data

    def season_episodes(self, tmdb_id: Any, season: int, language: str = "zh-CN") -> Dict[int, Dict[str, Any]]:
        """读取某一季的分集信息（含每集简介），结果按语言缓存。"""
        try:
            key = (int(tmdb_id), int(season), language)
        except (TypeError, ValueError):
            return {}
        cached = self._season_cache.get(key)
        if cached is not None:
            return cached
        episodes: List[Any] = []
        try:
            data = self._client(language).season_obj.details(key[0], key[1]) or {}
            if isinstance(data, dict):
                episodes = data.get("episodes") or []
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：TMDB 分集读取失败 {key} {err}")
        result: Dict[int, Dict[str, Any]] = {}
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            try:
                index = int(episode.get("episode_number"))
            except (TypeError, ValueError):
                continue
            result[index] = {
                "name": str(episode.get("name") or ""),
                "overview": clean_text(episode.get("overview")),
                "air_date": str(episode.get("air_date") or ""),
            }
        self._season_cache[key] = result
        return result

    def search_movie_id(self, title: str, year: str = "") -> Optional[int]:
        """按标题搜索电影 TMDB ID。"""
        try:
            results = self._client("zh-CN").search_movies(title, year or "")
        except Exception:  # noqa: BLE001
            return None
        for item in results or []:
            value = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            if value:
                return int(value)
        return None

    def search_tv_id(self, title: str, year: str = "") -> Optional[int]:
        """按标题搜索剧集 TMDB ID。"""
        try:
            results = self._client("zh-CN").search_tvs(title, year or "")
        except Exception:  # noqa: BLE001
            return None
        for item in results or []:
            value = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            if value:
                return int(value)
        return None

    def match_tv_id(self, title: str, year: str = "", season: Optional[int] = None) -> Tuple[Optional[int], str]:
        """按标题匹配剧集 TMDB ID，返回 (id, 匹配到的标题)。

        安全性依赖两层校验，避免把 MV、无关剧集误配到同名影视作品：

        1. 标题必须高度一致：去符号后完全相等，或互为包含且短边不少于 5 个字符、
           长度比不低于 0.75（过滤 "Wife" 命中 "Chasing My Rejected Wife" 这类情况）；
        2. 给出季号时，要求候选剧集在 TMDB 确实存在该季分集数据；未给出季号时，
           退化为年份相差不超过一年。

        搜索时先去掉「第 N 季」等季标记，并按「不带年份 → 带年份」的顺序尝试。
        """
        if not is_usable_title(title):
            return None, ""
        full = _normalize_title(title)
        if not full:
            return None, ""
        base = _normalize_title(_base_series_title(title))
        wanted_year = 0
        try:
            wanted_year = int(str(year)[:4])
        except (TypeError, ValueError):
            wanted_year = 0
        terms: List[str] = [str(title or "").strip()]
        base_title = _base_series_title(title)
        if base_title and _normalize_title(base_title) != full:
            terms.append(base_title)

        seen_ids: set = set()
        for term in terms:
            if not term:
                continue
            for use_year in ("", year or ""):
                try:
                    results = self._client("zh-CN").search_tvs(term, use_year) or []
                except Exception:  # noqa: BLE001
                    continue
                for item in results:
                    if isinstance(item, dict):
                        candidate_id = item.get("id")
                        names = [item.get("name"), item.get("original_name")]
                        first_air = str(item.get("first_air_date") or "")
                    else:
                        candidate_id = getattr(item, "id", None)
                        names = [getattr(item, "name", None), getattr(item, "original_name", None)]
                        first_air = str(getattr(item, "first_air_date", "") or "")
                    if not candidate_id or int(candidate_id) in seen_ids:
                        continue
                    normalized_names = [value for value in (_normalize_title(name) for name in names) if value]
                    if not any(
                        self._title_matches(value, full, base) for value in normalized_names
                    ):
                        continue
                    if season is not None and int(season) > 0:
                        if not self.season_episodes(candidate_id, int(season)):
                            continue
                    else:
                        candidate_year = 0
                        try:
                            candidate_year = int(first_air[:4])
                        except (TypeError, ValueError):
                            candidate_year = 0
                        if wanted_year and candidate_year and abs(candidate_year - wanted_year) > 1:
                            continue
                    seen_ids.add(int(candidate_id))
                    return int(candidate_id), str(next((name for name in names if name), "") or "")
        return None, ""

    @staticmethod
    def _title_matches(candidate: str, full: str, base: str) -> bool:
        """判断候选标题是否与原标题（或其去季标记形式）高度一致。"""
        for target in {full, base}:
            if not target:
                continue
            if candidate == target:
                return True
            short, long = sorted((candidate, target), key=len)
            if len(short) < 5 or len(long) == 0:
                continue
            if short in long and len(short) / len(long) >= 0.75:
                return True
        return False

    def match_movie_id(self, title: str, year: str = "") -> Tuple[Optional[int], str]:
        """按标题严格匹配电影 TMDB ID，返回 (id, 匹配到的标题)。

        校验口径与剧集一致：标题去符号后必须高度一致，年份相差不超过一年，
        避免把同名但无关的影片（或 MV）误配成电影条目。
        """
        if not is_usable_title(title):
            return None, ""
        full = _normalize_title(title)
        if not full:
            return None, ""
        wanted_year = 0
        try:
            wanted_year = int(str(year)[:4])
        except (TypeError, ValueError):
            wanted_year = 0
        seen_ids: set = set()
        term = str(title or "").strip()
        if not term:
            return None, ""
        for use_year in ("", year or ""):
            try:
                results = self._client("zh-CN").search_movies(term, use_year) or []
            except Exception:  # noqa: BLE001
                continue
            for item in results:
                if isinstance(item, dict):
                    candidate_id = item.get("id")
                    names = [item.get("title"), item.get("original_title")]
                    release = str(item.get("release_date") or "")
                else:
                    candidate_id = getattr(item, "id", None)
                    names = [getattr(item, "title", None), getattr(item, "original_title", None)]
                    release = str(getattr(item, "release_date", "") or "")
                if not candidate_id or int(candidate_id) in seen_ids:
                    continue
                normalized = [value for value in (_normalize_title(name) for name in names) if value]
                if not any(self._title_matches(value, full, full) for value in normalized):
                    continue
                candidate_year = 0
                try:
                    candidate_year = int(release[:4])
                except (TypeError, ValueError):
                    candidate_year = 0
                if wanted_year and candidate_year and abs(candidate_year - wanted_year) > 1:
                    continue
                seen_ids.add(int(candidate_id))
                return int(candidate_id), str(next((name for name in names if name), "") or "")
        return None, ""


class MusicBrainzProvider:
    """MusicBrainz 艺人成员数据源：MV 没有 TMDB 演职员数据，团体成员只能取自这里。"""

    def __init__(self) -> None:
        """初始化带进程内缓存的提供者。"""
        self._request = RequestUtils(headers={"User-Agent": MB_USER_AGENT}, timeout=20)
        self._cache: Dict[str, List[str]] = {}

    def _get(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """请求 MusicBrainz JSON 接口，并遵守其 1 秒限流约定。"""
        try:
            response = self._request.get_res(
                url=f"{MB_API}/{path}", params={**params, "fmt": "json"}
            )
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：MusicBrainz 请求失败 {path} {err}")
            return None
        finally:
            time.sleep(1.05)
        if response is None or int(getattr(response, "status_code", 500) or 500) >= 300:
            return None
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, dict) else None

    def members(self, artist: str) -> List[str]:
        """按艺人名返回团体成员名单（个人艺人返回空列表）。"""
        key = str(artist or "").strip()
        if not key:
            return []
        cached = self._cache.get(key.casefold())
        if cached is not None:
            return list(cached)
        members = self._fetch_members(key)
        self._cache[key.casefold()] = members
        return list(members)

    def _fetch_members(self, artist: str) -> List[str]:
        """搜索艺人并读取「member of band」关系。"""
        search = self._get("artist", {"query": f'artist:"{artist}"', "limit": 5})
        if not search:
            return []
        group = next(
            (
                item
                for item in (search.get("artists") or [])
                if isinstance(item, dict) and str(item.get("type") or "") in MB_GROUP_TYPES
            ),
            None,
        )
        if not group or not group.get("id"):
            return []
        detail = self._get(f"artist/{group['id']}", {"inc": "artist-rels"})
        if not detail:
            return []
        members: List[str] = []
        for relation in detail.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            if str(relation.get("type") or "") != "member of band":
                continue
            if str(relation.get("direction") or "") != "backward":
                continue
            name = str((relation.get("artist") or {}).get("name") or "").strip()
            if name and name not in members:
                members.append(name)
        return members


class WikidataProvider:
    """Wikidata 成员数据源（P527「has part」），可直接返回中文标签。"""

    def __init__(self) -> None:
        """初始化带进程内缓存的提供者。"""
        self._request = RequestUtils(headers={"User-Agent": MB_USER_AGENT}, timeout=25)
        self._cache: Dict[str, List[Dict[str, str]]] = {}

    def members(self, artist: str) -> List[Dict[str, str]]:
        """返回 [{original: 原名, zh: 中文名}]，失败时为空列表。"""
        key = str(artist or "").strip()
        if not key:
            return []
        cached = self._cache.get(key.casefold())
        if cached is not None:
            return [dict(item) for item in cached]
        entries = self._fetch(key)
        self._cache[key.casefold()] = entries
        return [dict(item) for item in entries]

    def person_image(self, name: str) -> str:
        """查人物照片（P18），返回可直接下载的地址；未命中返回空字符串。"""
        key = str(name or "").strip()
        if not key:
            return ""
        for lang in ("zh", "en", "ko"):
            query = (
                "SELECT ?image WHERE {"
                f'  ?person rdfs:label "{key.replace(chr(34), "")}"@{lang} .'
                "  ?person wdt:P18 ?image ."
                "} LIMIT 1"
            )
            data = self._query(query)
            rows = (data.get("results") or {}).get("bindings") or []
            if rows:
                image = str(rows[0]["image"]["value"]).replace("http://", "https://")
                return image + ("&" if "?" in image else "?") + "width=480"
        return ""

    def _query(self, query: str) -> Dict[str, Any]:
        """执行任意 SPARQL 查询（带限流）。"""
        try:
            response = self._request.post_res(
                url=WD_SPARQL_ENDPOINT,
                data={"query": query, "format": "json"},
                timeout=40,
            )
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：Wikidata 查询失败 {err}")
            return {}
        finally:
            time.sleep(1.05)
        if response is None or int(getattr(response, "status_code", 500) or 500) >= 300:
            return {}
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _fetch(self, artist: str) -> List[Dict[str, str]]:
        """执行 SPARQL 查询并解析成员标签。"""
        query = WD_MEMBER_QUERY % artist.replace('"', "").replace("\\", "")
        try:
            response = self._request.get_res(
                url=WD_SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
            )
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：Wikidata 查询失败 {artist} {err}")
            return []
        finally:
            time.sleep(1.05)
        if response is None or int(getattr(response, "status_code", 500) or 500) >= 300:
            return []
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return []
        entries: List[Dict[str, str]] = []
        for binding in (data.get("results") or {}).get("bindings") or []:
            if not isinstance(binding, dict):
                continue
            zh = str((binding.get("memberLabel") or {}).get("value") or "").strip()
            original = str((binding.get("memberEn") or {}).get("value") or "").strip()
            if not zh and not original:
                continue
            entries.append({"original": original or zh, "zh": zh or original})
        return entries


class LLMTextWriter:
    """基于系统 LLM 的简介扩写、翻译与生成器。"""

    @staticmethod
    def available() -> bool:
        """判断宿主是否提供可用的 LLM 配置。"""
        return LLMHelper is not None

    async def _ainvoke(self, system_prompt: str, user_prompt: str) -> str:
        """异步调用系统 LLM 并返回纯文本。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = await LLMHelper.get_llm(streaming=False)
        try:
            # 元数据中的花括号是正文，不应被当作模板占位符解析。
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)
            ])
            content = getattr(response, "content", response)
            return clean_text(LLMHelper.extract_text_content(content, fallback_to_string=True))
        finally:
            try:
                await LLMHelper.close_llm(llm)
            except Exception:  # noqa: BLE001 - 释放失败不影响结果
                pass

    def generate(self, system_prompt: str, user_prompt: str, retries: int = 0) -> str:
        """同步调用 LLM 生成文本，失败时按指数退避重试，最终返回空字符串。"""
        if not self.available():
            return ""
        attempts = max(1, int(retries) + 1)
        self._empty_reply = False
        for attempt in range(attempts):
            try:
                text = str(run_coroutine(self._ainvoke(system_prompt, user_prompt)) or "").strip()
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：LLM 调用失败 {err}")
                text = ""
            if text:
                return text
            # 区分「调用异常」与「模型返回空内容」，后者多为限流/截断，重试后仍空才提示
            self._empty_reply = True
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 1.5 ** attempt))
        if self._empty_reply:
            logger.warning("影视简介增强：LLM 返回空内容（可能触发限流或内容被截断）")
        return ""

    def translate_names(self, names: List[str]) -> List[str]:
        """把艺人/成员名单批量翻译成简体中文译名，失败时返回原名。"""
        cleaned = [str(name).strip() for name in names if str(name).strip()]
        if not cleaned or not self.available():
            return cleaned
        raw = self.generate(
            MEMBER_TRANSLATE_SYSTEM,
            json.dumps(cleaned, ensure_ascii=False),
        )
        if not raw:
            return cleaned
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end <= start:
            return cleaned
        try:
            parsed = json.loads(raw[start : end + 1])
        except Exception:  # noqa: BLE001
            return cleaned
        if not isinstance(parsed, list) or len(parsed) != len(cleaned):
            return cleaned
        translated: List[str] = []
        for original, value in zip(cleaned, parsed):
            text = str(value or "").strip()
            translated.append(text or original)
        return translated


MOVIE_EXPAND_SYSTEM = (
    "你是资深影视资料编辑，负责把电影简介写得更完整、更有条理。\n"
    "要求：\n"
    "1. 只依据给定资料扩写，不得编造资料中没有的关键情节、人物关系或结局。\n"
    "2. 用客观流畅的简体中文写成一段连贯文字，不要小标题、不要列表、不要加“简介：”前缀。\n"
    "3. 可以补充类型、时代背景、主要人物处境与冲突等氛围信息，但不要剧透结局。\n"
    "4. 直接输出简介正文。"
)

MOVIE_AI_SYSTEM = (
    "你是资深影视资料编辑。请只依据给出的影片信息写一段客观的剧情简介。\n"
    "要求：\n"
    "1. 不确定的情节用概括性表述，不要编造具体细节、人物名字或结局。\n"
    "2. 简体中文、一段连贯文字，不要小标题或列表，不要加前缀。\n"
    "3. 直接输出简介正文。"
)

EPISODE_SYSTEM = (
    "你是剧集资料编辑，负责为单集写简介。\n"
    "要求：\n"
    "1. 只依据给定的剧集上下文撰写，不要编造未提供的具体情节、台词或结局。\n"
    "2. 简介必须只描述该集内容，不要写成整部剧的简介，也不要与其他集重复。\n"
    "3. 信息不足时用概括表述该集可能的推进方向，避免虚构细节。\n"
    "4. 简体中文、一段连贯文字，不要小标题或列表，不要加前缀，直接输出正文。\n"
    "5. 严禁任何套话开场：不要出现「第12集中」「本集延续」「本集中」「作为第一季…的一集」这类编号或"
    "自我指涉的引导语，直接从人物、事件或处境写起。"
)

# 在已有中文简介基础上扩写时使用：允许比 EPISODE_SYSTEM 更具体，但同样不得套话开场
EPISODE_EXPAND_SYSTEM = (
    "你是剧集资料编辑，负责把已有的一集简介补写得更完整。\n"
    "要求：\n"
    "1. 严格以「该集现有中文简介」为事实基础扩写，可以补充上下文里出现的类型、背景、人物处境与冲突，"
    "不得编造未提供的关键情节、台词或结局。\n"
    "2. 必须写清该集独有的具体事件与人物反应，不要写成整部剧的概述，也不要与其他集雷同。\n"
    "3. 禁止任何套话开场：「第几集中」「本集延续」「本集中」「作为…的一集」等编号或自我指涉的引导语一律不要，"
    "直接从人物、事件或处境写起，也不要提「上一集」「此前」这类跨集指代。\n"
    "4. 简体中文、一段连贯文字，不要小标题或列表，不要加前缀，直接输出正文。"
)

MV_AI_SYSTEM = (
    "你是音乐视频（MV）资料编辑，负责为单支 MV 写中文简介。\n"
    "要求：\n"
    "1. 只依据给出的曲目与发行信息撰写，不编造导演、演员、取景地或获奖等未提供的细节。\n"
    "2. 写清这是什么曲目、出自哪张专辑或何时发行（信息里有才写），以及 MV 的呈现方式与风格特点。\n"
    "3. 禁止提及分辨率、画质、编码格式、片源、字幕、音轨、文件大小等技术与文件信息。\n"
    "4. 无法确认画面内容时，只写曲目与发行层面的信息（艺人、年份、专辑、曲风、版本形式），"
    "不要凭空描述拍摄场景、服装、镜头或剪辑。\n"
    "5. 简体中文、一段连贯文字，不要小标题或列表，不要加前缀，直接输出正文。"
)

# 简介正文里不应出现的技术/文件类词，命中整句会被剔除
MV_TEXT_NOISE_PATTERN = re.compile(
    r"(?i)(2160p|1080[pi]|720p|576p|480[pi]|4k|uhd|web-?dl|blu-?ray|蓝光|hevc|avc|vp9|av1|aac|opus|flac|pcm|mp3|prores|"
    r"编码|码率|画质|超清|高清|分辨率|片源|压制|音轨|轨道|文件大小|webrip|hdtv)"
)

# MV 文件名里的画质、编码、来源等噪声词
MV_NOISE_PATTERN = re.compile(
    r"(?i)\b(2160p|1080[pi]|720p|576p|480[pi]|4k|uhd|web-?dl|webrip|bluray|blu-ray|bdrip|avc|hevc|h\.?264|h\.?265|"
    r"vp9|av1|aac|ac3|eac3|dts|opus|prores|pcm|mp3|flac|xvid|divx|10bits?|8bits?|60fps|\d+fps|hdtv|"
    r"gomtv|mnet|jtbc|official|music video|mv|demo|lg|umax|sbs|mbc|kbs|youtube|ytb)\b"
)

# 分辨率与编码连写成一体的噪声，例如 1080PX264、720pH264
MV_COMPACT_NOISE_PATTERN = re.compile(r"(?i)\b(?:2160|1080|720|576|480)[pi](?:x|h)?\.?26[45]\b")

# 合作署名分隔符：&、顿号、feat./ft.、with、A x B
MV_COLLAB_SPLIT_PATTERN = re.compile(
    r"\s*(?:&|＆|、|\b(?:feat|ft)\.?|\bwith\b|\s[xX×]\s)\s*",
    re.I,
)


def split_mv_artists(text: str, limit: int = 6) -> List[str]:
    """把「A & B」「A feat. B」这类合作署名拆成单个艺人名。

    只在拆出至少两个有效名字时返回结果；含逗号的整体名（例如
    ``Earth, Wind & Fire``）视为专有名词直接放弃拆分，避免把组合拆坏。
    拆不出来时返回空列表，由调用方保留原始署名。
    """
    raw = str(text or "").strip()
    if not raw or not MV_COLLAB_SPLIT_PATTERN.search(raw):
        return []
    names: List[str] = []
    seen: set = set()
    for part in MV_COLLAB_SPLIT_PATTERN.split(raw):
        name = part.strip(" .,;:_-&/|")
        if not name or len(name) < 2 or len(name) > 60:
            continue
        if "," in name or "，" in name:
            # 「Earth, Wind」这类逗号名多半是整体专名，拆开只会得到错误人名
            return []
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= limit:
            break
    return names if len(names) >= 2 else []

# 版本/形式标注，命中后作为素材提示传给 AI
MV_NOTE_LABELS = (
    (r"(?i)\blive\b", "现场演出"),
    (r"(?i)\bdance\b", "舞蹈版"),
    (r"(?i)\bvisuali[sz]er\b", "Visualiser"),
    (r"(?i)\blyric\b", "歌词版"),
    (r"(?i)\bremix\b", "Remix"),
    (r"(?i)\bacoustic\b", "Acoustic"),
    (r"(?i)\bbehind the scenes\b", "花絮"),
    (r"(?i)\bversion\b|\bver\.?\b", "特别版本"),
)


def strip_mv_file_noise_words(text: str) -> str:
    """去掉文本里的画质、编码、片源等噪声词，供提示词素材使用。"""
    cleaned = re.sub(MV_NOISE_PATTERN, " ", str(text or ""))
    cleaned = re.sub(r"[._]+", " ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -_")


def strip_mv_file_noise(text: str) -> str:
    """剔除 AI 简介里夹带技术/文件信息的整句，避免出现「2160p WEB-DL 高清画质」这类描述。

    逐句过滤；若过滤后剩余内容过短（说明模型主要在写文件信息），则保留原文，
    交给后续的字数校验决定是否采用。
    """
    sentences = re.split(r"(?<=[。！？!?；;])", str(text or ""))
    kept = [item for item in sentences if item.strip() and not MV_TEXT_NOISE_PATTERN.search(item)]
    result = "".join(kept).strip()
    if visible_length(result) >= 40:
        return result
    return str(text or "").strip()


def strip_technical_sentences(text: str, min_keep: int = 40) -> str:
    """剔除简介里夹带画质、编码、片源等文件信息的整句（适用于电影/剧集/MV）。"""
    sentences = re.split(r"(?<=[。！？!?；;])", str(text or ""))
    kept = [item for item in sentences if item.strip() and not MV_TEXT_NOISE_PATTERN.search(item)]
    result = "".join(kept).strip()
    if visible_length(result) >= min_keep:
        return result
    return str(text or "").strip()


def strip_template_opening(text: str, min_keep: int = 20) -> str:
    """去掉「第12集中，」「本集延续…」这类编号套话开场。

    只处理开头：把引导语连同紧跟的逗号一起去掉，保留其后的正文。
    套话可能叠两层（「作为第一季…的一集，本集延续…」），因此循环剥离；
    剥离后剩余正文过短（低于 ``min_keep``）时退回上一个可用版本，
    只有剩下几乎没有内容时才保留原文，避免把整段简介削没。
    """
    original = str(text or "").strip()
    body = original
    floor = max(1, min_keep)
    for _ in range(3):
        match = EPISODE_TEMPLATE_OPENING_PATTERN.match(body)
        if not match:
            break
        rest = body[match.end():].lstrip("，,、：: ")
        if visible_length(rest) < floor:
            break
        body = rest.strip()
    return body or original


def text_cjk_ratio(text: Any) -> float:
    """计算中文（含日韩汉字）字符在有效文字中的占比，用于识别未翻译的外文简介。"""
    body = str(text or "")
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", body))
    latin = len(re.findall(r"[A-Za-z]", body))
    total = cjk + latin
    return cjk / total if total else 0.0


TEMPLATE_SENTENCE_PATTERN = re.compile(
    r"^\s*(本片|本剧|该片|该剧|这部电影|这部电视剧|本作品|这段视频)\s*(主要)?\s*(讲述|围绕|呈现)"
)

# AI 生成分集简介时常见的「编号 + 套话」开场，例如
# 「第12集中，……」、「本集继续……」、「作为第一季推进至后半程的一集，……」
EPISODE_TEMPLATE_OPENING_PATTERN = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9一二三四五六七八九十百]+\s*[集中集话](?:中|里|，|,)?"
    r"|本集(?:延续|继续|围绕|聚焦|中|里|讲述|主要)"
    r"|这一集(?:中|里|延续|继续|围绕|聚焦)"
    r"|作为第\s*[0-9一二三四五六七八九十百]+\s*季[^，,。]{0,12}的一集"
    r"|在(?:本|这一)集中"
    r")"
)


def parse_mv_media(text: str) -> Dict[str, str]:
    """从 MV 文件名/路径解析艺人、曲名、年份与版本标注，作为 AI 生成简介的素材。

    MV 没有 TMDB/IMDb 条目，Emby 解析出的条目名也常残留画质与压制组信息，
    因此这里只做「线索」提取：解析不出就给空值，交给 AI 结合条目名与路径自行判断。
    """
    raw = str(text or "").strip()
    if not raw:
        return {"artist": "", "song": "", "year": "", "notes": ""}
    stem = Path(raw).stem
    origin = ""
    match = re.match(r"^\[(?P<origin>[^\]]+)\]\s*(?P<rest>.*)$", stem)
    if match:
        origin = match.group("origin").strip()
        stem = match.group("rest").strip()
    notes = [label for pattern, label in MV_NOTE_LABELS if re.search(pattern, stem)]
    # 文件名里可能有多个年份（曲名本身也可能像年份），发行年份取最后一个
    year_matches = list(re.finditer(r"(?:19|20)\d{2}", stem))
    year_match = year_matches[-1] if year_matches else None
    body = re.sub(r"-(PTerMV|CMTV|CMCT|FRDS|HHWEB|CornerMV|Amzv)\b.*$", "", stem, flags=re.I)
    parts = re.split(r"\s+[-–]\s+", body, maxsplit=1)
    if len(parts) == 1:
        # 没有空格包住的分隔符时，处理「艺人-曲名.版本」这类常见写法：
        # 仅当连字符左侧是中文名才拆，避免误伤 Anne-Marie、Jay-Z 这类英文艺名。
        compact_split = re.match(r"^([^-\s][^-]{1,60}?)-(.+)$", body)
        if compact_split and re.search(r"[\u4e00-\u9fff]", compact_split.group(1)):
            parts = [compact_split.group(1), compact_split.group(2)]
    artist = parts[0].strip(" ._-") if len(parts) > 1 else ""
    song = parts[1] if len(parts) > 1 else parts[0]
    song = _clean_mv_song(song, year_match.group(0) if year_match else "")
    artist = _strip_mv_date_prefix(re.sub(r"[._]+", " ", artist).strip(" -_"))
    # 方括号里的出品方常写成「艺人-曲名」，拆开后作为兜底
    origin_artist, origin_song = _split_mv_artist_song(origin)
    if not artist:
        artist = origin_artist or origin
    if origin_song and (not song or song == origin):
        song = _clean_mv_song(origin_song)
    return {
        "artist": artist,
        "song": song or origin or stem,
        "year": year_match.group(0) if year_match else "",
        "notes": "、".join(dict.fromkeys(notes)),
    }


def _clean_mv_song(text: str, year: str = "") -> str:
    """清理曲名里的分隔符、版本括注、画质编码与尾部压制组。"""
    song = re.sub(r"[._]+", " ", str(text or ""))
    song = re.sub(r"\[[^\]]*\]", " ", song)
    song = re.sub(r"\([^)]*\)", " ", song)
    song = MV_COMPACT_NOISE_PATTERN.sub(" ", song)
    song = re.sub(MV_NOISE_PATTERN, " ", song)
    # 去掉尾部「-压制组/尾标注」（如 -Unknown、-PTerMV），但曲名不为空时才删
    tail_stripped = re.sub(r"\s*-\s*[A-Za-z0-9]{2,20}$", "", song).strip(" -_")
    if tail_stripped:
        song = tail_stripped
    song = re.sub(r"\s{2,}", " ", song).strip(" -_")
    # 去掉曲名里的发行年份（年份已单独记录），但曲名本身就只剩年份时保留
    if year:
        without_year = re.sub(rf"\b{year}\b", " ", song).strip(" -_")
        without_year = re.sub(r"\s{2,}", " ", without_year)
        if without_year:
            song = without_year
    return song


def _split_mv_artist_song(text: str) -> Tuple[str, str]:
    """把「艺人 - 曲名」拆开，兼容无空格连字符（仅中文艺名）。"""
    value = str(text or "").strip()
    if not value:
        return "", ""
    parts = re.split(r"\s+[-–]\s+", value, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(" ._-"), parts[1].strip(" ._-")
    compact = re.match(r"^([^-\s][^-]{1,60}?)-(.+)$", value)
    if compact and re.search(r"[\u4e00-\u9fff]", compact.group(1)):
        return compact.group(1).strip(), compact.group(2).strip(" ._-")
    return "", ""


def _strip_mv_date_prefix(text: str) -> str:
    """去掉艺人名前的日期/期数前缀，例如 ``2012 03 28 2NE1`` → ``2NE1``。

    文件名里常带录制日期或期数（``2012 03.28``、``03.28``、``2012-03-28``），
    不处理时会被当成艺人写入 Emby。这里只剥离「年份/月日 + 分隔符」这种明确形态，
    避免影响以数字开头的正常艺名（如 ``2NE1``）；剥离后为空时保留原值。
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    patterns = (
        r"^(?:19|20)\d{2}(?:[\s._-]+\d{1,2}){0,2}[\s._-]+",
        r"^\d{1,2}[\s._-]+\d{1,2}[\s._-]+",
        r"^\d{1,2}月\d{1,2}日[\s._-]*",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", cleaned).strip(" -_")
        if candidate and candidate != cleaned:
            return candidate
    return cleaned


TRANSLATE_SYSTEM = (
    "你是影视作品简介翻译。把给定简介翻译成通顺的简体中文，"
    "保持原有信息量，不增删情节，不加小标题或列表，直接输出译文。"
)

MEMBER_TRANSLATE_SYSTEM = (
    "你是韩国/华语流行音乐资料助手。把用户给出的艺人名列表翻译成中文常用译名："
    "已经是中文的原样返回，英文名用中文圈通行译名，韩文名用中文译名。"
    "保持顺序与数量不变，只输出 JSON 字符串数组，不要任何解释。"
)


class OverviewEnhancer:
    """简介增强引擎：收集待处理条目、生成简介、写回媒体服务器并记录状态。"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        data_dir: Optional[Path] = None,
        media_server_helper: Any = None,
        notify: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """初始化配置、状态存储与依赖。"""
        self._config = normalize_config(config)
        self._data_dir = Path(data_dir) if data_dir else Path("/config/temp/MediaOverviewEnhancer")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._data_dir / "state.json"
        self._helper = media_server_helper
        self._notify = notify
        self._tmdb = TmdbProvider()
        self._llm = LLMTextWriter()
        self._mb = MusicBrainzProvider()
        self._wd = WikidataProvider()
        self._lock = threading.RLock()
        # 状态文件落盘的独立 IO 锁：锁内只做「写临时文件 + 原子替换」
        self._io_lock = threading.Lock()
        # 一轮任务内复用的媒体服务器客户端（避免每条目都重读配置、重连 Emby）
        self._clients_cache: Optional[Tuple[List[EmbyClient], List[str]]] = None
        self._state = self._load_state()
        self._run: Optional[Dict[str, Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._pending: List[Dict[str, Any]] = []
        self._pending_worker: Optional[threading.Thread] = None
        self._stop_pending = threading.Event()
        self._skipped_no_provider = 0
        self._no_provider_names = []
        self._title_matched = 0
        # 本轮缺 TMDB 标识的条目名称，用于给出可操作的提示
        self._no_provider_names: List[str] = []
        # 状态落盘节流：热点路径（头像/缓存）先标脏，最多每 5 秒落盘一次
        self._last_save_at = 0.0
        self._state_dirty = False
        # 单条重做/失败重试时只处理这些 key（server|item_id）
        self._focus_keys: set = set()

    # ------------------------------------------------------------------ 状态持久化

    def _load_state(self) -> Dict[str, Any]:
        """读取本地状态文件。"""
        default: Dict[str, Any] = {
            "records": {},
            "logs": [],
            "last_run": None,
            "stats": {},
            "daily": {},
            "failures": {},
            "backups": {},
            "recent_episodes": {},
            "person_images": {},
            "skipped_untranslated": {},
            "title_cache": {},
        }
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    default.update(data)
        except Exception as err:  # noqa: BLE001
            # 解析失败时保留损坏文件，避免下一次写入把唯一现场覆盖掉
            self._quarantine_state_file()
            logger.warning(f"影视简介增强：状态文件读取失败，已保留损坏副本：{err}")
        if not isinstance(default.get("records"), dict):
            default["records"] = {}
        if not isinstance(default.get("logs"), list):
            default["logs"] = []
        if not isinstance(default.get("daily"), dict):
            default["daily"] = {}
        for key in (
            "failures",
            "backups",
            "recent_episodes",
            "person_images",
            "skipped_untranslated",
            "title_cache",
        ):
            if not isinstance(default.get(key), dict):
                default[key] = {}
        return default

    def _quarantine_state_file(self) -> None:
        """把无法解析的状态文件改名保留，避免被下一次写入覆盖。"""
        try:
            if not self._state_file.exists():
                return
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self._state_file.with_name(f"state.corrupt-{stamp}.json")
            os.replace(self._state_file, target)
            logger.warning(f"影视简介增强：损坏的状态文件已备份为 {target.name}")
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：损坏状态文件备份失败 {err}")

    def _save_state(self, allow_stopped: bool = False) -> None:
        """保存状态快照：锁内整理数据，锁外原子落盘，避免持锁做磁盘 IO。"""
        with self._lock:
            if self._stop_pending.is_set() and not allow_stopped:
                return
            self._state["records"] = self._prune_records(self._state.get("records"))
            self._state["logs"] = list(self._state.get("logs", []))[-300:]
            failures = self._state.get("failures")
            if isinstance(failures, dict) and len(failures) > 500:
                self._state["failures"] = dict(list(failures.items())[-500:])
            self._cleanup_backups()
            self._cleanup_caches()
            self._state["state_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = dict(self._state)
            self._state_dirty = False
            self._last_save_at = time.time()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # 并发 worker 各用独立临时文件并在 IO 锁内串行替换，避免互相截断写出半截 JSON
        tmp_file = self._state_file.with_name(f"{self._state_file.name}.{uuid4().hex}.tmp")
        try:
            with self._io_lock:
                # 先写临时文件再原子替换：进程中断不会留下半截 JSON
                tmp_file.write_text(text, encoding="utf-8")
                os.replace(tmp_file, self._state_file)
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：状态文件写入失败 {err}")
            try:
                tmp_file.unlink()
            except OSError:
                pass

    def _mark_dirty(self) -> None:
        """标记状态需要落盘，配合 _flush_state 做节流写入。"""
        self._state_dirty = True

    def _flush_state(self, force: bool = False) -> None:
        """按最小间隔节流落盘；force=True 时立即写盘。"""
        if force:
            self._save_state()
            return
        if not self._state_dirty:
            return
        if time.time() - self._last_save_at < _STATE_SAVE_INTERVAL:
            return
        self._save_state()

    @staticmethod
    def _prune_records(records: Any) -> Dict[str, Any]:
        """只保留最近若干条处理记录，避免状态文件无限增长。"""
        if not isinstance(records, dict):
            return {}
        if len(records) <= _RECORDS_MAX:
            return dict(records)
        ordered = sorted(
            records.items(),
            key=lambda item: (
                str((item[1] or {}).get("time") or "")
                if isinstance(item[1], dict)
                else ""
            ),
        )
        return dict(ordered[-_RECORDS_MAX:])

    def _cleanup_caches(self) -> None:
        """清理超期或超量的外部查询缓存（调用方需持有锁）。"""
        now = time.time()
        for key in ("skipped_untranslated", "title_cache"):
            bucket = self._state.get(key)
            if not isinstance(bucket, dict):
                self._state[key] = {}
                continue
            for name, entry in list(bucket.items()):
                stamp = 0.0
                if isinstance(entry, dict):
                    try:
                        stamp = float(entry.get("ts") or 0)
                    except (TypeError, ValueError):
                        stamp = 0.0
                if stamp and stamp < now - _CACHE_DAYS * 86400:
                    bucket.pop(name, None)
            if len(bucket) > _CACHE_MAX:
                ordered = sorted(
                    bucket.items(),
                    key=lambda item: (
                        float((item[1] or {}).get("ts") or 0)
                        if isinstance(item[1], dict)
                        else 0
                    ),
                )
                for name, _ in ordered[: len(bucket) - _CACHE_MAX]:
                    bucket.pop(name, None)
        images = self._state.get("person_images")
        if isinstance(images, dict) and len(images) > _PERSON_IMAGE_MAX:
            for name in list(images)[: len(images) - _PERSON_IMAGE_MAX]:
                images.pop(name, None)

    def _state_size(self) -> int:
        """返回状态文件字节数，供详情页展示体积占用。"""
        try:
            return int(self._state_file.stat().st_size)
        except OSError:
            return 0

    def _last_error(self) -> str:
        """返回最近一条错误日志内容，便于快速定位问题。"""
        for entry in reversed(self._state.get("logs") or []):
            if isinstance(entry, dict) and entry.get("level") == "error":
                return str(entry.get("message") or "")
        return ""

    def _cleanup_backups(self) -> None:
        """清理超过保留天数或条数上限的旧简介备份（调用方需持有锁）。"""
        backups = self._state.get("backups")
        if not isinstance(backups, dict) or not backups:
            return
        days = int(self._config.get("backup_days") or 0)
        if days > 0:
            limit_time = time.time() - days * 86400
            for key, entry in list(backups.items()):
                try:
                    stamp = float((entry or {}).get("ts") or 0)
                except (TypeError, ValueError):
                    stamp = 0
                if stamp and stamp < limit_time:
                    backups.pop(key, None)
        maximum = int(self._config.get("rollback_max") or 200)
        if len(backups) > maximum:
            ordered = sorted(
                backups.items(), key=lambda item: float((item[1] or {}).get("ts") or 0)
            )
            for key, _ in ordered[: len(backups) - maximum]:
                backups.pop(key, None)

    def _note_no_provider(self, kind: str, label: str) -> None:
        """记录本轮缺少 TMDB 标识的条目（只用于汇总提示，不落盘）。"""
        text = str(label or "").strip()
        if not text:
            return
        bucket = self._no_provider_names
        if len(bucket) < 50 and text not in bucket:
            bucket.append(text)

    def _log(self, message: str, level: str = "info") -> None:
        """写入运行日志（同时输出到宿主日志）。"""
        entry = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "level": level, "message": str(message)}
        with self._lock:
            self._state.setdefault("logs", []).append(entry)
        if level == "error":
            logger.error(f"影视简介增强：{message}")
        elif level == "warning":
            logger.warning(f"影视简介增强：{message}")
        else:
            logger.info(f"影视简介增强：{message}")

    def update_config(self, config: Optional[Dict[str, Any]]) -> None:
        """更新运行配置。"""
        self._config = normalize_config(config)

    # ------------------------------------------------------------------ 对外状态

    @property
    def config(self) -> Dict[str, Any]:
        """返回当前生效配置。"""
        return dict(self._config)

    def status(self) -> Dict[str, Any]:
        """返回插件运行状态、统计与最近日志。"""
        # 运行中的 worker 会持续写入这些字典，先加锁取快照再组装，避免前端轮询时
        # 抛 RuntimeError: dictionary changed size during iteration
        with self._lock:
            records = dict(self._state.get("records") or {})
            failures = dict(self._state.get("failures") or {})
            backups = dict(self._state.get("backups") or {})
            skipped_untranslated = dict(self._state.get("skipped_untranslated") or {})
            stats = dict(self._state.get("stats") or {})
            last_run = self._state.get("last_run")
            saved_at = self._state.get("state_saved_at")
            logs = list(self._state.get("logs") or [])[-40:]
        run = self._run or {}
        failure_rows = [
            {
                "key": entry.get("key"),
                "kind": entry.get("kind"),
                "title": entry.get("title"),
                "season": entry.get("season"),
                "episode": entry.get("episode"),
                "message": entry.get("message"),
                "time": entry.get("time"),
                "count": entry.get("count"),
            }
            for entry in sorted(
                [item for item in failures.values() if isinstance(item, dict)],
                key=lambda item: str(item.get("time") or ""),
                reverse=True,
            )[:20]
        ]
        backup_rows = [
            {
                "key": entry.get("key"),
                "kind": entry.get("kind"),
                "title": entry.get("title"),
                "season": entry.get("season"),
                "episode": entry.get("episode"),
                "time": entry.get("time"),
                "locked": bool("Overview" in [str(value) for value in (entry.get("locked") or [])]),
                "chars": visible_length(entry.get("overview")),
                "preview": clean_text(entry.get("overview"))[:120],
                "run_id": entry.get("run_id"),
            }
            for entry in sorted(
                [item for item in backups.values() if isinstance(item, dict)],
                key=lambda item: float(item.get("ts") or 0),
                reverse=True,
            )[:20]
        ]
        return {
            "enabled": bool(self._config.get("enabled")),
            "llm_available": LLMTextWriter.available(),
            "servers": _as_str_list(self._config.get("servers")),
            "libraries": _as_str_list(self._config.get("libraries")),
            "schedule_hours": self._config.get("schedule_hours"),
            "auto_on_transfer": bool(self._config.get("auto_on_transfer")),
            "movie_mode": self._config.get("movie_mode"),
            "episode_mode": self._config.get("episode_mode"),
            "mv_enabled": bool(self._config.get("mv_enabled")),
            "mv_libraries": _as_str_list(self._config.get("mv_libraries")),
            "mv_min_chars": self._config.get("mv_min_chars"),
            "mv_target_chars": self._config.get("mv_target_chars"),
            "mv_split_collab": bool(self._config.get("mv_split_collab")),
            "processed_total": len(records),
            "failure_count": len(failures),
            "backup_count": len(backups),
            "skipped_untranslated": len(skipped_untranslated),
            "state_bytes": self._state_size(),
            "state_saved_at": saved_at,
            "last_error": self._last_error(),
            "failures": failure_rows,
            "backups": backup_rows,
            "stats": stats,
            "last_run": last_run,
            "daily": self.daily_stats(),
            "running": bool(run and run.get("state") == "running"),
            "run": run,
            "logs": logs,
        }

    def server_status(self) -> List[Dict[str, Any]]:
        """列出可用 Emby 服务器与连接状态。"""
        clients, errors = self._resolve_clients()
        result: List[Dict[str, Any]] = []
        for client in clients:
            ok, message = client.test_connection()
            result.append({"name": client.name, "connected": ok, "message": message})
        for message in errors:
            result.append({"name": "-", "connected": False, "message": message})
        return result

    def clear_records(self) -> Dict[str, Any]:
        """清空处理记录与失败清单，使所有条目可以重新补全（保留回滚备份）。"""
        with self._lock:
            count = len(self._state.get("records") or {})
            failed = len(self._state.get("failures") or {})
            self._state["records"] = {}
            self._state["failures"] = {}
        self._save_state()
        self._log(f"已清空 {count} 条处理记录与 {failed} 条失败记录", "warning")
        return {"cleared": count, "failures": failed}

    def daily_stats(self) -> Dict[str, Any]:
        """返回当天处理统计，跨天时自动清零。"""
        with self._lock:
            daily = self._state.get("daily")
            today = datetime.now().strftime("%Y-%m-%d")
            if not isinstance(daily, dict) or daily.get("date") != today:
                daily = {
                    "date": today,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                    "untranslated": 0,
                    "runs": 0,
                }
                self._state["daily"] = daily
            return {
                "date": today,
                "updated": int(daily.get("updated") or 0),
                "skipped": int(daily.get("skipped") or 0),
                "failed": int(daily.get("failed") or 0),
                "untranslated": int(daily.get("untranslated") or 0),
                "runs": int(daily.get("runs") or 0),
            }

    def send_daily_summary(self) -> Dict[str, Any]:
        """按配置发送当天处理结果汇总通知。"""
        if not self._config.get("notify_daily"):
            return {"sent": False, "message": "每日汇总通知未开启"}
        stats = self.daily_stats()
        if not (
            stats["updated"]
            or stats["skipped"]
            or stats["failed"]
            or stats.get("untranslated")
            or stats["runs"]
        ):
            return {"sent": False, "message": "今天还没有处理记录"}
        text = (
            f"今日汇总：成功更新 {stats['updated']} 条，跳过 {stats['skipped']} 条，"
            f"失败 {stats['failed']} 条（共 {stats['runs']} 轮任务）"
        )
        if stats.get("untranslated"):
            text += (
                f"\n其中 {stats['untranslated']} 条因素材缺中文未写回，"
                "已记入放弃清单，不再重复消耗 AI"
            )
        failed_titles = self._failed_titles(5)
        if failed_titles:
            text += "\n失败条目：\n" + "\n".join(f"· {item}" for item in failed_titles)
        if self._notify is not None:
            try:
                self._notify("影视简介增强 · 每日汇总", text)
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：每日汇总通知发送失败 {err}")
                return {"sent": False, "message": str(err), "stats": stats}
        self._log(text)
        return {"sent": True, "message": text, "stats": stats}

    # ------------------------------------------------------------------ 媒体服务器

    def _resolve_clients(self, use_cache: bool = False) -> Tuple[List[EmbyClient], List[str]]:
        """按配置解析可用的 Emby 客户端；use_cache=True 时复用本轮已解析结果。"""
        if use_cache and self._clients_cache is not None:
            return self._clients_cache
        clients, errors = self._resolve_clients_fresh()
        self._clients_cache = (clients, errors)
        return clients, errors

    def _resolve_clients_fresh(self) -> Tuple[List[EmbyClient], List[str]]:
        """重新读取媒体服务器配置并构造客户端。"""
        clients: List[EmbyClient] = []
        errors: List[str] = []
        if self._helper is None:
            return clients, ["媒体服务器服务不可用"]
        try:
            configs = self._helper.get_configs() or {}
        except Exception as err:  # noqa: BLE001
            return clients, [f"读取媒体服务器配置失败：{err}"]
        wanted = _as_str_list(self._config.get("servers"))
        for name, conf in configs.items():
            if wanted and name not in wanted:
                continue
            if str(getattr(conf, "type", "") or "").lower() != "emby":
                continue
            raw = getattr(conf, "config", None)
            if not isinstance(raw, dict):
                raw = dict(raw) if raw else {}
            host = str(raw.get("host") or "").strip()
            api_key = str(raw.get("apikey") or raw.get("api_key") or "").strip()
            client = EmbyClient(name=name, host=host, api_key=api_key)
            client.set_user(str(raw.get("user") or raw.get("username") or ""))
            if not client.ready:
                errors.append(f"{name} 缺少 host 或 api_key")
                continue
            clients.append(client)
        if not clients and not errors:
            errors.append("未找到可用的 Emby 媒体服务器")
        return clients, errors

    def _client_by_name(self, name: str) -> Optional[EmbyClient]:
        """按名称获取指定 Emby 客户端。"""
        clients, _ = self._resolve_clients(use_cache=True)
        for client in clients:
            if client.name == name:
                return client
        return None

    # ------------------------------------------------------------------ 任务收集

    def _overview_of(self, item: Dict[str, Any]) -> str:
        """读取条目当前的简介文本。"""
        return clean_text(item.get("Overview"))

    def _tmdb_id_of(self, item: Dict[str, Any], kind: str, title: str = "", year: str = "") -> Optional[int]:
        """从条目 ProviderIds 或 TMDB 搜索中解析 TMDB ID。"""
        providers = item.get("ProviderIds") or {}
        if isinstance(providers, dict):
            for key, value in providers.items():
                if str(key).lower() == "tmdb" and value:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        break
        if not title:
            return None
        if kind == MOVIE:
            return self._tmdb.search_movie_id(title, year)
        return self._tmdb.search_tv_id(title, year)

    def _tmdb_provider_id(self, item: Dict[str, Any]) -> Optional[int]:
        """只读取条目自带 TMDB ProviderId，不做标题模糊匹配。

        库级扫描使用该口径，避免把 MV 等缺少 TMDB 标识的条目误判成影视作品。
        """
        providers = item.get("ProviderIds") or {}
        if not isinstance(providers, dict):
            return None
        for key, value in providers.items():
            if str(key).lower() == "tmdb" and value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None
    def _series_item(self, client: EmbyClient, series_id: str) -> Dict[str, Any]:
        """读取剧集条目的基础信息。"""
        if not series_id:
            return {}
        return client.get_item(series_id, "ProviderIds,Overview,Name,ProductionYear")

    def _series_index(self, client: EmbyClient) -> Dict[str, Dict[str, Any]]:
        """建立 Server 级剧集索引，供分集任务解析所属剧集的 TMDB ID。"""
        index: Dict[str, Dict[str, Any]] = {}
        for item in client.iter_items("Series", [None], max_items=5000, page_size=200):
            item_id = str(item.get("Id") or "")
            if item_id:
                index[item_id] = item
        return index

    def _untranslated_skipped(self, key: str, current: str) -> bool:
        """该条目此前判定为中文缺失而放弃，且简介未变化时不再重复消耗 AI。"""
        bucket = self._state.get("skipped_untranslated")
        if not isinstance(bucket, dict):
            return False
        entry = bucket.get(key)
        if not isinstance(entry, dict):
            return False
        return str(entry.get("sig") or "") == text_signature(current)

    def _cached_title_match(
        self, cache_key: str, matcher: Callable[[], Tuple[Optional[int], str]]
    ) -> Optional[int]:
        """TMDB 标题匹配缓存：正负结果都保留，避免每轮重复请求。"""
        with self._lock:
            cache = self._state.get("title_cache")
            if not isinstance(cache, dict):
                cache = {}
                self._state["title_cache"] = cache
            entry = cache.get(cache_key)
            if isinstance(entry, dict) and "id" in entry:
                cached = int(entry.get("id") or 0)
                if cached:
                    self._title_matched += 1
                return cached or None
        matched_id, matched_name = matcher()
        with self._lock:
            self._state.setdefault("title_cache", {})[cache_key] = {
                "id": int(matched_id or 0),
                "name": str(matched_name or ""),
                "ts": time.time(),
            }
        self._mark_dirty()
        if matched_id:
            self._title_matched += 1
        return matched_id or None

    def _cached_movie_match(self, name: str, year: str) -> Optional[int]:
        """按标题匹配电影 TMDB ID（带持久缓存）。"""
        cache_key = f"movie|{_normalize_title(name)}|{year}"

        def _matcher() -> Tuple[Optional[int], str]:
            matched_id, matched_name = self._tmdb.match_movie_id(name, year)
            if matched_id:
                self._log(
                    f"电影「{name}」无 TMDB 标识，按标题匹配到「{matched_name}」"
                    f"（tmdb={matched_id}）"
                )
            return matched_id, matched_name

        return self._cached_title_match(cache_key, _matcher)

    def _cached_tv_match(self, title: str, year: str, season: int) -> Optional[int]:
        """按标题匹配剧集 TMDB ID（带持久缓存，季参与缓存键）。"""
        cache_key = f"tv|{_normalize_title(title)}|{year}|{season}"

        def _matcher() -> Tuple[Optional[int], str]:
            matched_id, matched_name = self._tmdb.match_tv_id(title, year, season=season)
            if matched_id:
                self._log(
                    f"「{title}」无 TMDB 标识，按标题匹配到「{matched_name}」"
                    f"（tmdb={matched_id}）"
                )
            return matched_id, matched_name

        return self._cached_title_match(cache_key, _matcher)

    def _build_movie_jobs(
        self,
        client: EmbyClient,
        items: List[Dict[str, Any]],
        force: bool,
        require_provider: bool = False,
    ) -> List[Dict[str, Any]]:
        """根据电影条目清单构建待处理任务。"""
        jobs: List[Dict[str, Any]] = []
        min_chars = int(self._config.get("movie_min_chars") or 0)
        for item in items:
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            focus = f"{client.name}|{item_id}" in self._focus_keys
            current = self._overview_of(item)
            current_len = visible_length(current)
            if (
                not force
                and not focus
                and self._untranslated_skipped(f"{client.name}|{item_id}", current)
            ):
                # 已判定中文缺失且简介未变化：跳过，避免每轮重复生成与翻译
                continue
            if not force and not focus and current_len >= min_chars:
                continue
            name = str(item.get("Name") or "")
            year = str(item.get("ProductionYear") or "")
            if require_provider:
                tmdb_id = self._tmdb_provider_id(item)
                if not tmdb_id and self._config.get("tmdb_title_fallback"):
                    tmdb_id = self._cached_movie_match(name, year)
            else:
                tmdb_id = self._tmdb_id_of(item, MOVIE, name, year)
            if not tmdb_id:
                if require_provider:
                    self._skipped_no_provider += 1
                    self._note_no_provider(MOVIE, f"{name}（{year or '年份未知'}）")
                continue
            jobs.append(
                {
                    "key": f"{client.name}|{item_id}",
                    "kind": MOVIE,
                    "server": client.name,
                    "item_id": item_id,
                    "title": name,
                    "year": year,
                    "tmdb_id": tmdb_id,
                    "current": current,
                    "current_len": current_len,
                    "reason": "force" if force else ("missing" if not current_len else "short"),
                    "genres": item.get("Genres") or [],
                }
            )
        return jobs

    def _need_avatar(self, item: Dict[str, Any], names: List[str]) -> bool:
        """判断已写入 Emby 的艺人是否缺少人物头像（支持拆分后的多个署名）。"""
        if (
            not names
            or not self._config.get("mv_people_avatar")
            or not self._config.get("mv_write_people")
        ):
            return False
        cached = self._state.get("person_images") or {}
        index: Dict[str, Dict[str, Any]] = {}
        for person in item.get("People") or []:
            if not isinstance(person, dict):
                continue
            key = _normalize_title(person.get("Name"))
            if key:
                index.setdefault(key, person)
        for name in names:
            if name in cached and not cached.get(name):
                # 已查过且确实没有图，避免每轮重复判定
                continue
            person = index.get(_normalize_title(name))
            if person is None:
                continue
            if not bool(str(person.get("PrimaryImageTag") or "").strip()):
                return True
        return False

    def _build_mv_jobs(
        self,
        client: EmbyClient,
        items: List[Dict[str, Any]],
        force: bool,
    ) -> List[Dict[str, Any]]:
        """根据 MV 库条目构建待处理任务（简介由 AI 生成，并自检 NFO 与头像）。"""
        jobs: List[Dict[str, Any]] = []
        minimum = int(self._config.get("mv_min_chars") or 0)
        self_heal = bool(self._config.get("mv_self_heal"))
        for item in items:
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            key = f"{client.name}|{item_id}"
            focus = key in self._focus_keys
            current = self._overview_of(item)
            current_len = visible_length(current)
            path = str(item.get("Path") or "")
            parsed = parse_mv_media(path or str(item.get("Name") or ""))
            artist = str(parsed.get("artist") or "").strip()
            need_text = force or focus or current_len < minimum
            existing_people = {name.casefold() for name in _people_names(item.get("People"))}
            job: Dict[str, Any] = {
                "key": key,
                "kind": MV,
                "server": client.name,
                "item_id": item_id,
                "title": str(item.get("Name") or "") or parsed.get("song") or "",
                "year": str(item.get("ProductionYear") or parsed.get("year") or ""),
                "current": current,
                "current_len": current_len,
                "reason": (
                    ("force" if force else ("missing" if not current_len else "short"))
                    if need_text
                    else "people"
                ),
                "people_only": False,
                "path": path,
                "artist": artist,
                "song": parsed.get("song") or "",
                "notes": parsed.get("notes") or "",
                "need_people": False,
                "need_nfo": False,
                "need_avatar": False,
                "nfo_reason": "",
            }
            expected_people = self._mv_expected_people(job)
            artist_present = bool(expected_people) and all(
                name.casefold() in existing_people for name in expected_people
            )
            need_nfo, nfo_reason = self._nfo_health(job) if self_heal else (False, "")
            need_avatar = self._need_avatar(item, expected_people) if self_heal else False
            # 只要派生产物（NFO / 头像）需要修，就不重写简介，也不去展开成员：
            # 成员查询会逐艺人访问 MusicBrainz（约 1 秒限流），维护模式不该为它变慢。
            maintenance_only = (not need_text) and (need_nfo or need_avatar)
            need_member_lookup = bool(
                len(expected_people) == 1
                and self._config.get("mv_member_enabled")
                and not maintenance_only
                and (need_text or not artist_present or len(existing_people) <= 1)
            )
            if need_member_lookup:
                # 扫描阶段只读缓存，避免为每个艺人等待 MusicBrainz 限流
                expected_people.extend(self._cached_member_names(artist))
            need_people = bool(expected_people) and any(
                name.casefold() not in existing_people for name in expected_people
            )
            job["need_people"] = need_people
            if not need_text and not need_people and not need_nfo and not need_avatar:
                continue
            if not need_text and (need_nfo or need_avatar):
                job["reason"] = "nfo" if need_nfo else "avatar"
            job["need_nfo"] = need_nfo
            job["need_avatar"] = need_avatar
            job["nfo_reason"] = nfo_reason
            job["people_only"] = bool(need_people and not need_text)
            jobs.append(job)
        return jobs

    def _build_episode_jobs(
        self,
        client: EmbyClient,
        items: List[Dict[str, Any]],
        force: bool,
        require_provider: bool = False,
        series_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """根据剧集分集条目清单构建待处理任务（含同季重复简介检测）。"""
        groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for item in items:
            series_id = str(item.get("SeriesId") or "")
            if not series_id:
                continue
            try:
                season = int(item.get("ParentIndexNumber") or 0)
                episode = int(item.get("IndexNumber") or 0)
            except (TypeError, ValueError):
                continue
            if self._config.get("skip_specials") and (season <= 0 or episode <= 0):
                continue
            groups.setdefault((series_id, season), []).append(item)

        min_chars = int(self._config.get("episode_min_chars") or 0)
        always_rewrite = bool(self._config.get("episode_always_rewrite"))
        duplicate_detect = bool(self._config.get("duplicate_detect"))
        jobs: List[Dict[str, Any]] = []
        series_cache: Dict[str, Dict[str, Any]] = dict(series_map or {})
        missing_series = [sid for sid in sorted({series_id for series_id, _ in groups}) if sid not in series_cache]
        if missing_series:
            series_cache.update(client.get_items_by_ids(missing_series))
        for (series_id, season), group in groups.items():
            series_item = series_cache.get(series_id) or {}
            series_title = str(series_item.get("Name") or group[0].get("SeriesName") or "")
            series_year = str(series_item.get("ProductionYear") or "")
            if require_provider:
                tmdb_id = self._tmdb_provider_id(series_item)
                if not tmdb_id and self._config.get("tmdb_title_fallback"):
                    tmdb_id = self._cached_tv_match(series_title, series_year, season)
            else:
                tmdb_id = self._tmdb_id_of(series_item, EPISODE, series_title, series_year)
            if not tmdb_id:
                if require_provider:
                    self._skipped_no_provider += 1
                    self._note_no_provider(
                        EPISODE, f"{series_title} S{season}" if season else series_title
                    )
                continue
            duplicate_values = set()
            if duplicate_detect:
                counter: Dict[str, int] = {}
                for item in group:
                    text = self._overview_of(item)
                    if visible_length(text) < 10:
                        continue
                    signature = text_signature(text)
                    counter[signature] = counter.get(signature, 0) + 1
                duplicate_values = {signature for signature, count in counter.items() if count > 1}
            for item in group:
                item_id = str(item.get("Id") or "")
                if not item_id:
                    continue
                focus = f"{client.name}|{item_id}" in self._focus_keys
                current = self._overview_of(item)
                current_len = visible_length(current)
                if (
                    not force
                    and not focus
                    and self._untranslated_skipped(f"{client.name}|{item_id}", current)
                ):
                    # 已判定中文缺失且简介未变化：跳过，避免每轮重复生成与翻译
                    continue
                duplicated = current_len >= 10 and text_signature(current) in duplicate_values
                if (
                    not force
                    and not focus
                    and not always_rewrite
                    and not duplicated
                    and current_len >= min_chars
                ):
                    continue
                reason = "force" if force else ("duplicate" if duplicated else ("missing" if not current_len else "short"))
                jobs.append(
                    {
                        "key": f"{client.name}|{item_id}",
                        "kind": EPISODE,
                        "server": client.name,
                        "item_id": item_id,
                        "title": series_title,
                        "year": series_year,
                        "tmdb_id": tmdb_id,
                        "season": season,
                        "episode": int(item.get("IndexNumber") or 0),
                        "episode_title": str(item.get("Name") or ""),
                        "current": current,
                        "current_len": current_len,
                        "reason": reason,
                    }
                )
        return jobs

    def _collect_jobs(
        self,
        media_type: str = "all",
        title: str = "",
        force: Optional[bool] = None,
        limit: Optional[int] = None,
        focus_keys: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        """按范围收集待处理任务。"""
        clients, errors = self._resolve_clients()
        force_flag = bool(self._config.get("force_rewrite")) if force is None else bool(force)
        self._focus_keys = {
            str(value) for value in (focus_keys or []) if str(value or "").strip()
        }
        self._skipped_no_provider = 0
        self._no_provider_names = []
        self._title_matched = 0
        jobs: List[Dict[str, Any]] = []
        stats = {
            "clients": [client.name for client in clients],
            "movies": 0,
            "episodes": 0,
            "mv": 0,
        }
        libraries = _as_str_list(self._config.get("libraries"))
        scan_days = int(self._config.get("scan_days") or 0)
        min_date = ""
        if scan_days > 0 and not force_flag and not self._focus_keys:
            min_date = (datetime.now() - timedelta(days=scan_days)).strftime("%Y-%m-%d")
        # 候选收集只做分页遍历、成本很低，必须覆盖整库：单季超出十万集的库极少，
        # 这里给一个足够大的安全上限，避免大库尾部条目因窗口太小而永远扫不到。
        scan_limit = max(50000, int(self._config.get("max_items_per_run") or 200) * 10)
        for client in clients:
            if media_type in {"mv", "maintenance"}:
                if not self._config.get("mv_enabled"):
                    errors.append("MV 简介未在配置中启用，本次跳过")
                else:
                    mv_names = _as_str_list(self._config.get("mv_libraries")) or ["mv"]
                    mv_parents = client.resolve_library_ids(mv_names)
                    if not mv_parents:
                        errors.append(f"{client.name} 未匹配到 MV 媒体库：{'、'.join(mv_names)}")
                    for parent in mv_parents:
                        mv_jobs = self._build_mv_jobs(
                            client,
                            list(
                                client.iter_items(
                                    "Movie,MusicVideo,Video",
                                    [parent],
                                    max_items=scan_limit,
                                    extra_fields="Path,People",
                                )
                            ),
                            force_flag,
                        )
                        if title:
                            mv_jobs = [job for job in mv_jobs if title.casefold() in job["title"].casefold()]
                        if media_type == "maintenance":
                            mv_jobs = [
                                job for job in mv_jobs
                                if job.get("need_nfo") or job.get("need_avatar")
                            ]
                        stats["mv"] += len(mv_jobs)
                        jobs.extend(mv_jobs)
                continue
            if libraries:
                parents = client.resolve_library_ids(libraries)
                if not parents:
                    errors.append(f"{client.name} 未匹配到配置的媒体库：{'、'.join(libraries)}，本次跳过")
                    continue
            else:
                parents = client.resolve_library_ids([]) or [None]
            if title:
                if self._config.get("movie_enabled") and media_type in {"all", "movie"}:
                    for parent in parents:
                        movie_jobs = self._build_movie_jobs(
                            client, client.search_items(title, "Movie", parent=parent),
                            force_flag, require_provider=True,
                        )
                        stats["movies"] += len(movie_jobs)
                        jobs.extend(movie_jobs)
                if self._config.get("episode_enabled") and media_type in {"all", "tv"}:
                    episode_items: List[Dict[str, Any]] = []
                    series_items = [
                        series for parent in parents
                        for series in client.search_items(title, "Series", parent=parent)
                    ]
                    for series in series_items:
                        series_id = str(series.get("Id") or "")
                        if not series_id:
                            continue
                        episode_items.extend(
                            list(client.iter_items("Episode", [series_id], max_items=scan_limit))
                        )
                    episode_jobs = self._build_episode_jobs(
                        client, episode_items, force_flag, require_provider=True
                    )
                    stats["episodes"] += len(episode_jobs)
                    jobs.extend(episode_jobs)
                continue
            if self._config.get("movie_enabled") and media_type in {"all", "movie"}:
                for parent in parents:
                    movie_jobs = self._build_movie_jobs(
                        client,
                        list(
                            client.iter_items(
                                "Movie", [parent], max_items=scan_limit, min_date=min_date
                            )
                        ),
                        force_flag,
                        require_provider=True,
                    )
                    stats["movies"] += len(movie_jobs)
                    jobs.extend(movie_jobs)
            if self._config.get("episode_enabled") and media_type in {"all", "tv"}:
                series_map = self._series_index(client)
                for parent in parents:
                    episode_jobs = self._build_episode_jobs(
                        client,
                        list(
                            client.iter_items(
                                "Episode", [parent], max_items=scan_limit, min_date=min_date
                            )
                        ),
                        force_flag,
                        require_provider=True,
                        series_map=series_map,
                    )
                    stats["episodes"] += len(episode_jobs)
                    jobs.extend(episode_jobs)
        stats["skipped_no_provider"] = self._skipped_no_provider
        stats["title_matched"] = self._title_matched
        if self._focus_keys:
            jobs = [job for job in jobs if job.get("key") in self._focus_keys]
        elif not force_flag:
            jobs = self._drop_exhausted_failures(jobs)
        configured_max = int(self._config.get("max_items_per_run") or 200)
        max_items = _bounded_int(limit, configured_max, 1, configured_max)
        return jobs[:max_items], errors, stats

    def _drop_exhausted_failures(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """跳过连续失败达到上限的条目，避免定时扫描反复消耗 AI 额度。"""
        with self._lock:
            failures = dict(self._state.get("failures") or {})
        if not failures:
            return jobs
        kept: List[Dict[str, Any]] = []
        dropped = 0
        for job in jobs:
            entry = failures.get(job.get("key"))
            try:
                count = int(entry.get("count") or 0) if isinstance(entry, dict) else 0
            except (TypeError, ValueError):
                count = 0
            if count >= _FAILURE_RETRY_LIMIT:
                dropped += 1
                continue
            kept.append(job)
        if dropped:
            self._log(
                f"跳过 {dropped} 条已连续失败 {_FAILURE_RETRY_LIMIT} 次的条目"
                "（可在失败列表手动重试，或开启强制重写）",
                "warning",
            )
        return kept

    # ------------------------------------------------------------------ 简介决策

    def _expand_short_translation(
        self,
        job: Dict[str, Any],
        text: str,
        target: int,
        detail: Dict[str, Any],
        en_overview: str = "",
    ) -> str:
        """译文明显短于目标字数时，先给 AI 一次扩写机会。

        ``translate`` 模式的语义是「译文本身」，所以不再额外走素材过短扩写；
        英文简介常常只有一两句，直译后远低于目标字数，这里直接把译文
        当作素材扩写，扩写失败则原样返回译文。
        """
        body = clean_text(text, 4000)
        threshold = int((target or 0) * 0.6)
        if not body or threshold <= 0 or visible_length(body) >= threshold:
            return body
        if not self._llm.available():
            return body
        context = self._movie_context(job, detail, en_overview)
        expanded = clean_text(
            self._llm_generate(
                MOVIE_EXPAND_SYSTEM,
                f"{context}\n\n现有中文简介：{body}\n\n"
                f"请在此基础上扩写为约 {target} 字的中文简介，不得编造具体情节。",
            ),
            4000,
        )
        # 只有确实更长、且能通过质量闸门时才采用扩写结果
        if expanded and visible_length(expanded) > visible_length(body):
            if not self._quality_issue(expanded, str(job.get("kind") or "")):
                return expanded
        return body

    def _movie_context(self, job: Dict[str, Any], detail: Dict[str, Any], en_overview: str) -> str:
        """构造电影提示词上下文。"""
        genres = detail.get("genres") or job.get("genres") or []
        genre_names = [
            str(item.get("name")) if isinstance(item, dict) else str(item) for item in genres if item
        ]
        lines = [
            f"影片标题：{job['title']}",
            f"上映年份：{job.get('year') or '未知'}",
        ]
        if genre_names:
            lines.append(f"类型：{'、'.join(genre_names[:5])}")
        if detail.get("tagline"):
            lines.append(f"宣传语：{detail.get('tagline')}")
        lines.append(f"现有简介：{clean_text(detail.get('overview')) or job.get('current') or '无'}")
        if en_overview:
            lines.append(f"参考英文简介：{en_overview}")
        return "\n".join(lines)

    def _mv_context(self, job: Dict[str, Any]) -> str:
        """构造 MV 提示词上下文（Emby 条目名 + 文件路径 + 文件名线索）。"""
        title = strip_mv_file_noise_words(str(job.get("title") or "")) or "未知"
        lines = [f"条目名线索：{title}"]
        if job.get("path"):
            lines.append(f"文件线索：{strip_mv_file_noise_words(str(job['path']))}")
        if job.get("artist"):
            lines.append(f"艺人线索：{job['artist']}")
        if job.get("song"):
            lines.append(f"曲名线索：{job['song']}")
        if job.get("year"):
            lines.append(f"发行年份线索：{job['year']}")
        if job.get("notes"):
            lines.append(f"版本标注：{job['notes']}")
        if job.get("current"):
            lines.append(f"现有简介：{job['current']}")
        return "\n".join(lines)

    def _member_entries(self, artist: str) -> List[Dict[str, str]]:
        """查询团体成员（多数据源合并），结果写入插件状态做持久缓存。"""
        key = str(artist or "").strip()
        if not key or not self._config.get("mv_member_enabled"):
            return []
        with self._lock:
            cache = self._state.get("mb_members")
            if not isinstance(cache, dict):
                cache = {}
                self._state["mb_members"] = cache
            cached = cache.get(key)
        entries = self._normalize_member_cache(cached)
        if entries:
            return entries
        if isinstance(cached, list):
            return []
        entries = self._fetch_member_entries(key)
        with self._lock:
            self._state.setdefault("mb_members", {})[key] = entries
        self._save_state()
        if entries:
            self._log(
                f"成员数据：{key} 共 {len(entries)} 人（"
                + "、".join(str(item.get("zh") or item.get("original") or "") for item in entries[:12])
                + "）"
            )
        return entries

    @staticmethod
    def _normalize_member_cache(cached: Any) -> List[Dict[str, str]]:
        """把历史缓存的成员数据统一成 [{original, zh}]。"""
        entries: List[Dict[str, str]] = []
        if isinstance(cached, dict):
            originals = [str(name) for name in (cached.get("members") or []) if str(name).strip()]
            zh_values = [str(name) for name in (cached.get("zh") or []) if str(name).strip()]
            for index, name in enumerate(originals):
                zh = zh_values[index] if index < len(zh_values) else ""
                if not zh and re.search(r"[\u4e00-\u9fff]", name):
                    name, zh = "", name
                entries.append({"original": name, "zh": zh})
            return entries
        if isinstance(cached, list):
            for item in cached:
                if isinstance(item, dict):
                    original = str(item.get("original") or "").strip()
                    zh = str(item.get("zh") or "").strip()
                    if original or zh:
                        entries.append({"original": original or zh, "zh": zh or original})
                elif isinstance(item, str) and item.strip():
                    entries.append({"original": item.strip(), "zh": ""})
        return entries

    def _member_display_names(self, entries: List[Dict[str, str]]) -> List[str]:
        """按配置的名字模式生成要写入 Emby 的成员名。"""
        mode = str(self._config.get("mv_member_name_mode") or "zh")
        names: List[str] = []
        for entry in entries:
            original = str(entry.get("original") or "").strip()
            zh = str(entry.get("zh") or "").strip()
            if mode == "original":
                value = original or zh
            elif mode == "both":
                value = (
                    f"{zh} ({original})"
                    if zh and original and zh.casefold() != original.casefold()
                    else (zh or original)
                )
            else:
                value = zh or original
            if value and value not in names:
                names.append(value)
        return names

    def _member_names(self, artist: str) -> List[str]:
        """返回按当前名字模式处理后的成员名列表。"""
        return self._member_display_names(self._member_entries(artist))

    def _cached_member_names(self, artist: str) -> List[str]:
        """只使用已缓存的成员数据，绝不触发网络查询。

        扫描阶段只做判断，不必为每个艺人访问 MusicBrainz；真正写入时
        ``_mv_people`` 会按需查询并缓存。
        """
        key = str(artist or "").strip()
        if not key or not self._config.get("mv_member_enabled"):
            return []
        with self._lock:
            cached = (self._state.get("mb_members") or {}).get(key)
        return self._member_display_names(self._normalize_member_cache(cached))

    def _fetch_member_entries(self, artist: str) -> List[Dict[str, str]]:
        """按配置的数据源查询成员并合并，必要时用 AI 补齐缺失的中文名。"""
        source = str(self._config.get("mv_member_source") or "both")
        entries: List[Dict[str, str]] = []
        if source in {"musicbrainz", "both"}:
            for name in self._mb.members(artist):
                entries.append({"original": name, "zh": ""})
        if source in {"wikidata", "both"}:
            for item in self._wd.members(artist):
                original = str(item.get("original") or "").strip()
                zh = str(item.get("zh") or "").strip()
                target = next(
                    (
                        entry
                        for entry in entries
                        if original
                        and entry["original"]
                        and entry["original"].casefold() == original.casefold()
                    ),
                    None,
                )
                if target is not None:
                    if zh and not target["zh"]:
                        target["zh"] = zh
                    continue
                if zh and any(entry["zh"] == zh for entry in entries):
                    continue
                entries.append({"original": original or zh, "zh": zh or original})
        if str(self._config.get("mv_member_name_mode") or "zh") != "original":
            pending = [
                entry["original"] for entry in entries if not entry["zh"] and entry["original"]
            ]
            translated = self._llm.translate_names(pending)
            if translated and len(translated) == len(pending):
                for name, value in zip(pending, translated):
                    target = next(
                        (entry for entry in entries if entry["original"] == name), None
                    )
                    if target is not None and value:
                        target["zh"] = value
        return entries

    def _mv_expected_people(self, job: Dict[str, Any]) -> List[str]:
        """返回本条目应写入的演员名：合作署名拆分后各自署名。"""
        if not self._config.get("mv_write_people"):
            return []
        artist = str(job.get("artist") or "").strip()
        if not artist:
            return []
        if self._config.get("mv_split_collab"):
            names = split_mv_artists(artist)
            if names:
                return names
        return [artist]

    def _mv_people(self, job: Dict[str, Any]) -> List[Dict[str, Any]]:
        """构造 MV 的演员列表：拆分的合作艺人，或艺人（团体）及其团队成员。"""
        names = self._mv_expected_people(job)
        if not names:
            return []
        role = str(self._config.get("mv_people_role") or "").strip() or "演唱"
        if len(names) > 1:
            # 合作署名按个人写入，各自去人物库取头像；不再写整串组合名
            return [{"Name": name, "Type": "Actor", "Role": role} for name in names]
        people = [{"Name": names[0], "Type": "Actor", "Role": role}]
        member_role = str(self._config.get("mv_member_role") or "").strip() or "成员"
        for member in self._member_names(names[0]):
            people.append({"Name": member, "Type": "Actor", "Role": member_role})
        return people

    def _mv_prune_role(
        self, job: Dict[str, Any], people: Optional[List[Dict[str, Any]]]
    ) -> str:
        """返回需要按期望名单清理的角色名。

        拆分合作署名后，旧的整串组合名会留在「演唱」角色下且永远没有头像，
        写入时一并清掉；未拆分时沿用原行为，清理「成员」角色的历史译名。
        """
        if job.get("kind") != MV or not people:
            return ""
        if len(self._mv_expected_people(job)) > 1:
            return str(self._config.get("mv_people_role") or "").strip() or "演唱"
        return str(self._config.get("mv_member_role") or "").strip() or "成员"

    def _nfo_path_maps(self) -> List[Tuple[str, str]]:
        """解析 NFO 路径映射，支持用分号或换行分隔多组「服务器前缀:本地前缀」。"""
        text = str(self._config.get("nfo_path_map") or "").strip()
        if not text:
            return []
        result: List[Tuple[str, str]] = []
        for part in re.split(r"[;\n]+", text):
            if ":" not in part:
                continue
            source, _, target = part.partition(":")
            source = source.strip()
            target = target.strip()
            if not source or not target:
                continue
            result.append((source.rstrip("/") + "/", target.rstrip("/") + "/"))
        return result

    def _local_media_path(self, media_path: Any) -> Optional[Path]:
        """把媒体服务器里的路径换算成本地可写路径。

        配置了路径映射时，路径必须命中其中一组前缀，否则不写（避免写到错误位置）；
        未配置映射时按原路径处理，适用于媒体服务器路径与本地路径一致的部署。
        """
        raw = str(media_path or "").strip()
        if not raw:
            return None
        maps = self._nfo_path_maps()
        for source, target in maps:
            if raw.startswith(source):
                return Path(target + raw[len(source):])
        if maps:
            return None
        if raw.startswith("/"):
            return Path(raw)
        return None

    def _nfo_text(
        self, job: Dict[str, Any], overview: str, people: List[Dict[str, Any]], local: Path
    ) -> str:
        """生成与 Kodi / Emby / Jellyfin 兼容的 NFO 文本。"""
        root = ET.Element("musicvideo" if self._config.get("mv_nfo_root") == "musicvideo" else "movie")
        # 条目名可能是「1080i」这类文件信息，此时用「艺人 - 曲名」作为 NFO 标题
        title = str(job.get("title") or "").strip()
        if not is_usable_title(title):
            artist = str(job.get("artist") or "").strip()
            song = str(job.get("song") or "").strip()
            title = f"{artist} - {song}".strip(" -") or local.stem
        ET.SubElement(root, "title").text = title
        if overview:
            ET.SubElement(root, "plot").text = overview
        if job.get("year"):
            ET.SubElement(root, "year").text = str(job["year"])
        poster = local.with_suffix(".jpg")
        if poster.exists():
            ET.SubElement(root, "thumb").text = poster.name
        for order, person in enumerate(people):
            name = str(person.get("Name") or "").strip()
            if not name:
                continue
            actor = ET.SubElement(root, "actor")
            ET.SubElement(actor, "name").text = name
            if person.get("Role"):
                ET.SubElement(actor, "role").text = str(person["Role"])
            ET.SubElement(actor, "order").text = str(order)
            if person.get("image"):
                ET.SubElement(actor, "thumb").text = str(person["image"])
            ET.SubElement(actor, "type").text = str(person.get("Type") or "Actor")
        ET.SubElement(root, "lockdata").text = "false"
        try:
            ET.indent(root, space="  ")
        except AttributeError:  # pragma: no cover - 兼容旧运行时
            pass
        return (
            '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
            + ET.tostring(root, encoding="utf-8").decode("utf-8")
            + "\n"
        )

    def _person_image(self, name: str) -> str:
        """查询演员头像地址（TMDB 优先、Wikidata 兜底，结果持久缓存）。"""
        key = str(name or "").strip()
        if not key:
            return ""
        with self._lock:
            cache = self._state.get("person_images")
            if not isinstance(cache, dict):
                cache = {}
                self._state["person_images"] = cache
            if key in cache:
                return str(cache[key] or "")
        url = ""
        try:
            from app.modules.themoviedb.tmdbapi import TmdbApi

            for row in (TmdbApi(language="zh-CN").search_persons(key) or [])[:3]:
                path = (
                    row.get("profile_path")
                    if isinstance(row, dict)
                    else getattr(row, "profile_path", "")
                )
                if path:
                    url = f"https://image.tmdb.org/t/p/w300{path}"
                    break
        except Exception:  # noqa: BLE001
            url = ""
        if not url:
            try:
                url = self._wd.person_image(key)
            except Exception:  # noqa: BLE001
                url = ""
        with self._lock:
            self._state.setdefault("person_images", {})[key] = url
        # 头像查询可能很密集，只标脏并节流落盘，避免每次查询都写整份状态
        self._mark_dirty()
        self._flush_state()
        return url

    def _ensure_avatars(
        self,
        client: EmbyClient,
        job: Dict[str, Any],
        people: List[Dict[str, Any]],
        dto: Optional[Dict[str, Any]] = None,
    ) -> None:
        """给本次写入的演员补 Emby 人物头像（人物还没有头像时才写）。"""
        if not people or not self._config.get("mv_people_avatar"):
            return
        detail = (
            dto
            if isinstance(dto, dict) and dto.get("People")
            else client.get_full_dto(job.get("item_id") or "")
        )
        for person in detail.get("People") or []:
            if not isinstance(person, dict):
                continue
            name = str(person.get("Name") or "").strip()
            person_id = str(person.get("Id") or "")
            if not name or not person_id:
                continue
            with self._lock:
                done = self._state.get("person_avatars")
                if not isinstance(done, dict):
                    done = {}
                    self._state["person_avatars"] = done
                if done.get(person_id):
                    continue
            image = self._person_image(name)
            if not image:
                continue
            ok, message = client.set_remote_image(person_id, image)
            if ok:
                with self._lock:
                    self._state.setdefault("person_avatars", {})[person_id] = True
                # 头像补齐属于热点路径：标脏 + 节流落盘，避免每个头像整份写状态文件
                self._mark_dirty()
                self._flush_state()
                self._log(f"已为演员 {name} 补充头像")
            else:
                logger.debug(f"影视简介增强：演员 {name} 头像写入失败 {message}")
        self._flush_state()

    def _write_nfo(
        self, job: Dict[str, Any], overview: str, people: List[Dict[str, Any]]
    ) -> None:
        """把简介与演员写入与媒体同名的 NFO 文件，供其它客户端读取。"""
        if not self._config.get("mv_write_nfo"):
            return
        media_path = str(job.get("path") or "")
        if not media_path:
            return
        local = self._local_media_path(media_path)
        if local is None or not local.exists():
            return
        nfo = local.with_suffix(".nfo")
        enriched: List[Dict[str, Any]] = []
        for person in people:
            item = dict(person)
            image = self._person_image(str(person.get("Name") or ""))
            if image:
                item["image"] = image
            enriched.append(item)
        try:
            content = self._nfo_text(job, overview, enriched, local)
            if nfo.exists() and nfo.read_text(encoding="utf-8") == content:
                return
            nfo.write_text(content, encoding="utf-8")
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：NFO 写入失败 {nfo} {err}")

    def _nfo_health(self, job: Dict[str, Any]) -> Tuple[bool, str]:
        """检查 MV 的 NFO 是否缺失或过期，返回 (是否需要重写, 原因)。"""
        if not self._config.get("mv_write_nfo"):
            return False, ""
        local = self._local_media_path(job.get("path"))
        if local is None or not local.exists():
            return False, ""
        nfo = local.with_suffix(".nfo")
        if not nfo.exists():
            return True, "NFO 缺失"
        try:
            root = ET.parse(str(nfo)).getroot()
        except Exception:  # noqa: BLE001
            return True, "NFO 无法解析"
        plot = clean_text(root.findtext("plot"))
        if text_signature(plot) != text_signature(job.get("current") or ""):
            return True, "NFO 简介与条目不一致"
        expected = self._mv_expected_people(job)
        if expected:
            actors: Dict[str, Any] = {}
            for node in root.findall("actor"):
                key = _normalize_title(node.findtext("name"))
                if key:
                    actors.setdefault(key, node)
            missing = [name for name in expected if _normalize_title(name) not in actors]
            if missing:
                return True, "NFO 缺少演员"
            if self._config.get("mv_people_avatar"):
                cached = self._state.get("person_images") or {}
                for name in expected:
                    node = actors.get(_normalize_title(name))
                    has_thumb = bool((node.findtext("thumb") if node is not None else "") or "")
                    if not has_thumb and name not in cached:
                        return True, "NFO 演员缺头像"
        return False, ""

    def _mv_plan(self, job: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """判断 MV 简介的生成方式：MV 没有 TMDB 源，只能由 AI 生成。"""
        maintenance = job.get("reason") in {"nfo", "avatar"} and not job.get("people_only")
        if job.get("people_only") or maintenance:
            role = str(self._config.get("mv_people_role") or "").strip() or "演唱"
            message = (
                f"仅补充演员：{job.get('artist')}（{role}）"
                if job.get("people_only")
                else f"仅维护派生产物：{job.get('nfo_reason') or '演员头像'}"
            )
            return {
                "action": "write",
                "text": str(job.get("current") or ""),
                "source": SOURCE_PEOPLE if job.get("people_only") else SOURCE_MAINTENANCE,
                "message": message,
                "skip_write": bool(maintenance and not job.get("need_people")),
            }
        if not self._config.get("mv_enabled"):
            return {"action": "skip", "message": "MV 简介未启用（请在配置里打开「处理 MV」）"}
        if not self._config.get("ai_generate_when_missing"):
            return {"action": "skip", "message": "未开启「缺少简介时由 AI 生成」，MV 跳过"}
        target = int(self._config.get("mv_target_chars") or 110)
        minimum = int(self._config.get("mv_min_chars") or 60)
        if not allow_llm:
            return {
                "action": "write",
                "text": "",
                "source": SOURCE_AI,
                "message": f"将用 AI 生成约 {target} 字的 MV 中文简介",
            }
        if not self._llm.available():
            return {"action": "skip", "message": "LLM 不可用，无法生成 MV 简介", "failed": True}
        text = clean_text(
            strip_mv_file_noise(
                self._llm_generate(
                    MV_AI_SYSTEM,
                    f"{self._mv_context(job)}\n\n请写一段约 {target} 字的该 MV 中文简介。",
                )
            ),
            2000,
        )
        if visible_length(text) < max(20, min(minimum, 40)):
            return {"action": "skip", "message": "AI 生成结果过短", "failed": True}
        return {"action": "write", "text": text, "source": SOURCE_AI}

    def _movie_plan(self, job: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """判断电影简介的生成方式与素材。"""
        mode = str(self._config.get("movie_mode") or "expand")
        target = int(self._config.get("movie_target_chars") or 320)
        zh_detail = self._tmdb.movie_detail(job["tmdb_id"], "zh-CN")
        zh_overview = clean_text(zh_detail.get("overview"))
        en_overview = ""
        if mode != "ai" and visible_length(zh_overview) < 20:
            en_overview = clean_text(self._tmdb.movie_detail(job["tmdb_id"], "en-US").get("overview"))

        if mode == "translate":
            if visible_length(zh_overview) >= 20:
                return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
            if visible_length(en_overview) < 20:
                return {"action": "skip", "message": "TMDB 无可用简介", "detail": zh_detail}
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文简介", "detail": zh_detail}
            text = self._llm_generate(
                TRANSLATE_SYSTEM,
                f"影片：{job['title']}（{job.get('year') or '年份未知'}）\n\n简介原文：\n{en_overview}",
            )
            if not text:
                # 翻译失败但原文可用：至少写回理由，避免条目一直没有中文简介
                return {
                    "action": "skip",
                    "message": "英文简介翻译失败",
                    "failed": True,
                    "detail": zh_detail,
                }
            # translate 模式只做翻译，英文原文偏短时译文同样偏短；
            # 目标字数明显不足时再判断一次，交给 _short_material_ai_plan 决定是否扩写。
            return {
                "action": "write",
                "text": self._expand_short_translation(job, text, target, zh_detail, en_overview),
                "source": SOURCE_TRANSLATE,
                "detail": zh_detail,
            }

        if mode == "ai":
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 依据影片信息生成", "detail": zh_detail}
            if not self._llm.available():
                if visible_length(zh_overview) >= 20:
                    return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
                return {"action": "skip", "message": "LLM 不可用", "failed": True, "detail": zh_detail}
            text = self._llm_generate(
                MOVIE_AI_SYSTEM,
                f"{self._movie_context(job, zh_detail, en_overview)}\n\n请写一段约 {target} 字的剧情简介。",
            )
            if not text:
                if visible_length(zh_overview) >= 20:
                    return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
                return {"action": "skip", "message": "AI 生成失败", "failed": True, "detail": zh_detail}
            return {"action": "write", "text": text, "source": SOURCE_AI, "detail": zh_detail}

        # expand：以 TMDB 中文简介为基础扩写，缺中文时先翻译英文，再考虑 AI 生成
        if visible_length(zh_overview) < 20:
            if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
                if not allow_llm:
                    return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文简介", "detail": zh_detail}
                text = self._llm_generate(
                    TRANSLATE_SYSTEM,
                    f"影片：{job['title']}（{job.get('year') or '年份未知'}）\n\n简介原文：\n{en_overview}",
                )
                if not text:
                    return {
                        "action": "skip",
                        "message": "英文简介翻译失败",
                        "failed": True,
                        "detail": zh_detail,
                    }
                return {
                    "action": "write",
                    "text": text,
                    "source": SOURCE_TRANSLATE,
                    "detail": zh_detail,
                }
            if not self._config.get("ai_generate_when_missing"):
                return {"action": "skip", "message": "缺少 TMDB 简介且未开启 AI 生成", "detail": zh_detail}
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 生成", "detail": zh_detail}
            text = self._llm_generate(
                MOVIE_AI_SYSTEM,
                f"{self._movie_context(job, zh_detail, '')}\n\n请写一段约 {target} 字的剧情简介。",
            )
            if not text:
                return {
                    "action": "skip",
                    "message": "AI 生成失败或 LLM 不可用",
                    "failed": True,
                    "detail": zh_detail,
                }
            return {"action": "write", "text": text, "source": SOURCE_AI, "detail": zh_detail}

        if not allow_llm:
            return {
                "action": "write",
                "text": "",
                "source": f"{SOURCE_TMDB}+{SOURCE_AI}",
                "message": "将在现有简介基础上用 AI 扩写",
                "detail": zh_detail,
            }
        if not self._llm.available():
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
        text = self._llm_generate(
            MOVIE_EXPAND_SYSTEM,
            f"{self._movie_context(job, zh_detail, en_overview)}\n\n请把上面的简介扩写为约 {target} 字的详细简介。",
        )
        if not text:
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
        return {"action": "write", "text": text, "source": f"{SOURCE_TMDB}+{SOURCE_AI}", "detail": zh_detail}

    def _episode_context(
        self,
        job: Dict[str, Any],
        zh_episode: Dict[str, Any],
        zh_overview: str,
        en_overview: str,
    ) -> str:
        """构造分集提示词上下文。"""
        lines = [
            f"剧集名称：{job['title']}",
            f"首播年份：{job.get('year') or '未知'}",
            f"季集：第 {job.get('season')} 季 第 {job.get('episode')} 集",
        ]
        episode_name = str(job.get("episode_title") or zh_episode.get("name") or "").strip()
        if episode_name:
            lines.append(f"该集标题：{episode_name}")
        if zh_episode.get("air_date"):
            lines.append(f"播出日期：{zh_episode.get('air_date')}")
        series_detail = self._tmdb.tv_detail(job["tmdb_id"], "zh-CN")
        series_overview = clean_text(series_detail.get("overview"))
        if series_overview:
            lines.append(f"剧集整体简介：{series_overview[:600]}")
        if zh_overview:
            lines.append(f"该集现有中文简介：{zh_overview}")
        if en_overview:
            lines.append(f"该集参考英文简介：{en_overview}")
        lines.append(f"当前简介问题：{job.get('reason')}")
        return "\n".join(lines)

    def _llm_generate(self, system_prompt: str, user_prompt: str) -> str:
        """按配置的重试次数调用大模型，失败时返回空字符串。"""
        return self._llm.generate(
            system_prompt, user_prompt, retries=int(self._config.get("llm_retries") or 0)
        )

    def _episode_duplicate(self, job: Dict[str, Any], text: str) -> bool:
        """判断新生成的分集简介是否与同季已写入内容雷同。"""
        body = str(text or "").strip()
        if not body:
            return False
        bucket = (
            (self._state.get("recent_episodes") or {})
            .get(f"{job.get('tmdb_id')}|{job.get('season')}") or {}
        )
        signature = text_signature(body)
        head = body[:60]
        for episode, value in bucket.items():
            try:
                if int(episode) == int(job.get("episode") or 0):
                    continue
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                if str(value.get("sig") or "") == signature:
                    return True
                saved_head = str(value.get("head") or "")
                if saved_head and len(head) >= 40 and saved_head[:40] == head[:40]:
                    return True
            elif str(value) == signature:
                return True
        return False

    def _finalize_episode_text(
        self, job: Dict[str, Any], text: str, context: str, target: int
    ) -> str:
        """检查分集简介是否与同季雷同，必要时重生成一次；仍雷同返回空字符串。"""
        if not text:
            return ""
        text = strip_template_opening(text)
        if not self._episode_duplicate(job, text):
            return text
        retry = self._llm_generate(
            EPISODE_SYSTEM,
            (
                f"{context}\n\n请写一段约 {target} 字的该集简介，"
                "必须与其他集明显区分，不要复用相同的开头与句式。"
            ),
        )
        if retry:
            retry = strip_template_opening(retry)
        if retry and not self._episode_duplicate(job, retry):
            return retry
        return ""

    def _expand_short_episode_translation(
        self,
        job: Dict[str, Any],
        text: str,
        context: str,
        target: int,
        minimum: int,
    ) -> str:
        """分集译文短于阈值时补写一次；补写失败或更短则保留译文。"""
        body = clean_text(text, 4000)
        if not body or visible_length(body) >= max(1, minimum):
            return body
        if not self._llm.available():
            return body
        expanded = clean_text(
            self._llm_generate(
                EPISODE_EXPAND_SYSTEM,
                f"{context}\n\n现有中文简介：{body}\n\n"
                f"请在此基础上补写为约 {target} 字的该集简介，不得编造具体情节。",
            ),
            4000,
        )
        if expanded and visible_length(expanded) > visible_length(body):
            if not self._quality_issue(expanded, EPISODE):
                return expanded
        return body

    def _episode_short_and_expandable(
        self, job: Dict[str, Any], zh_overview: str, min_chars: int
    ) -> bool:
        """判断该集是否属于「中文简介偏短、值得按素材扩写」。

        只有大模型可用、且原文确实短于阈值（或本集被判定为过短/雷同/强制重写）时才扩写；
        素材充足且未开启「已有简介也交给 AI 重写」的条目保持原样，避免无谓消耗额度。
        """
        if not self._llm.available():
            return False
        if job.get("reason") in {"short", "duplicate", "force"}:
            return True
        threshold = max(1, min_chars)
        return visible_length(zh_overview) < threshold

    def _episode_plan(self, job: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """判断分集简介的生成方式与素材。"""
        mode = str(self._config.get("episode_mode") or "auto")
        min_chars = int(self._config.get("episode_min_chars") or 0)
        target = int(self._config.get("episode_target_chars") or 160)
        season_map = self._tmdb.season_episodes(job["tmdb_id"], int(job.get("season") or 0), "zh-CN")
        zh_episode = season_map.get(int(job.get("episode") or 0)) or {}
        zh_overview = clean_text(zh_episode.get("overview"))
        en_overview = ""
        if mode != "ai" and visible_length(zh_overview) < max(20, min_chars):
            en_map = self._tmdb.season_episodes(job["tmdb_id"], int(job.get("season") or 0), "en-US")
            en_overview = clean_text((en_map.get(int(job.get("episode") or 0)) or {}).get("overview"))
        context = self._episode_context(job, zh_episode, zh_overview, en_overview)
        has_tmdb = visible_length(zh_overview) >= 20 or visible_length(en_overview) >= 20

        if mode == "tmdb":
            # 中文简介再短也算 TMDB 素材：优先按素材扩写，而不是把几十字原文直接写回
            if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
                if not allow_llm:
                    return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文分集简介"}
                text = self._llm_generate(TRANSLATE_SYSTEM, f"{context}\n\n简介原文：\n{en_overview}")
                if not text:
                    return {"action": "skip", "message": "英文分集简介翻译失败", "failed": True}
                return {
                    "action": "write",
                    "text": text,
                    "source": SOURCE_TRANSLATE,
                }
            if visible_length(zh_overview) >= 20:
                return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}
            if visible_length(en_overview) >= 20:
                return {"action": "write", "text": en_overview, "source": SOURCE_TMDB}
            return {"action": "skip", "message": "TMDB 无该集简介"}

        if mode == "ai":
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 重写该集简介"}
            text = self._finalize_episode_text(
                job,
                self._llm_generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。"),
                context,
                target,
            )
            if text:
                return {"action": "write", "text": text, "source": SOURCE_AI}
            if visible_length(zh_overview) >= 20:
                return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}
            return {"action": "skip", "message": "AI 生成失败或与同季其他集雷同", "failed": True}

        # auto：中文分集简介优先，其次英文翻译，最后按上下文生成。
        # 中文简介偏短（含「已有简介也交给 AI 重写」/短简介扩写）时按素材扩写，而不是原样写回。
        if visible_length(zh_overview) >= 20:
            needs_expand = self._episode_short_and_expandable(job, zh_overview, min_chars)
            if not needs_expand and self._config.get("episode_always_rewrite") and job.get("reason") in {
                "short",
                "duplicate",
                "force",
            }:
                needs_expand = True
            if needs_expand:
                if not allow_llm:
                    return {"action": "write", "text": "", "source": f"{SOURCE_TMDB}+{SOURCE_AI}", "message": "将扩写该集简介"}
                text = self._finalize_episode_text(
                    job,
                    self._llm_generate(
                        EPISODE_EXPAND_SYSTEM,
                        f"{context}\n\n请在以上素材基础上扩写为约 {target} 字的该集简介。",
                    ),
                    context,
                    target,
                )
                if text:
                    return {"action": "write", "text": text, "source": f"{SOURCE_TMDB}+{SOURCE_AI}"}
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}

        if visible_length(zh_overview) >= 20:
            if not allow_llm:
                return {"action": "write", "text": "", "source": f"{SOURCE_TMDB}+{SOURCE_AI}", "message": "将扩写该集简介"}
            text = self._finalize_episode_text(
                job,
                self._llm_generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。"),
                context,
                target,
            )
            if text:
                return {"action": "write", "text": text, "source": f"{SOURCE_TMDB}+{SOURCE_AI}"}
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}

        if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文分集简介"}
            text = self._llm_generate(TRANSLATE_SYSTEM, f"{context}\n\n简介原文：\n{en_overview}")
            if not text:
                return {"action": "skip", "message": "英文分集简介翻译失败", "failed": True}
            # 英文分集简介常常只有一两句，直译后仍短于阈值：补写一次再写回
            text = self._expand_short_episode_translation(job, text, context, target, min_chars)
            return {
                "action": "write",
                "text": text,
                "source": SOURCE_TRANSLATE,
            }

        if not self._config.get("ai_generate_when_missing"):
            return {"action": "skip", "message": "缺少该集简介且未开启 AI 生成"}
        if not allow_llm:
            return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 依据剧集上下文生成"}
        if not has_tmdb:
            self._log(f"{job.get('title')} S{job.get('season')}E{job.get('episode')} 无 TMDB 简介，改用 AI 生成")
        text = self._finalize_episode_text(
            job,
            self._llm_generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。"),
            context,
            target,
        )
        if not text:
            return {"action": "skip", "message": "AI 生成失败或与同季其他集雷同", "failed": True}
        return {"action": "write", "text": text, "source": SOURCE_AI}

    def _plan_job(self, job: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """按条目类型生成处理方案。"""
        try:
            if job.get("kind") == MV:
                return self._mv_plan(job, allow_llm=allow_llm)
            if job.get("kind") == MOVIE:
                plan = self._movie_plan(job, allow_llm=allow_llm)
            else:
                plan = self._episode_plan(job, allow_llm=allow_llm)
            return self._short_material_ai_plan(job, plan, allow_llm=allow_llm)
        except Exception as err:  # noqa: BLE001
            return {"action": "skip", "message": f"生成方案失败：{err}"}

    def _short_material_ai_plan(
        self,
        job: Dict[str, Any],
        plan: Dict[str, Any],
        allow_llm: bool = True,
    ) -> Dict[str, Any]:
        """素材过短或同季多集简介重复时，改用 AI 依上下文生成差异化简介。

        默认关闭（``ai_when_source_short``）。开启后只对「按常规方式处理完仍达不到
        字数阈值」或「同季多集简介雷同」的条目生效，不会影响已有充足素材的条目。
        """
        if not self._config.get("ai_when_source_short"):
            return plan
        is_movie = job.get("kind") == MOVIE
        minimum = int(self._config.get("movie_min_chars" if is_movie else "episode_min_chars") or 0)
        target = int(self._config.get("movie_target_chars" if is_movie else "episode_target_chars") or 0)
        text = clean_text(plan.get("text"))
        too_short = visible_length(text) < max(1, minimum)
        duplicated = (not is_movie) and job.get("reason") == "duplicate"
        if plan.get("action") == "write" and not too_short and not duplicated:
            return plan
        if not allow_llm:
            return {
                "action": "write",
                "text": "",
                "source": SOURCE_AI,
                "message": "素材不足或同季重复，将用 AI 生成差异化简介",
            }
        if not self._llm.available():
            return plan

        if is_movie:
            zh_detail = self._tmdb.movie_detail(job["tmdb_id"], "zh-CN")
            en_overview = clean_text(self._tmdb.movie_detail(job["tmdb_id"], "en-US").get("overview"))
            context = self._movie_context(job, zh_detail, en_overview)
            has_material = bool(clean_text(zh_detail.get("overview"))) or bool(en_overview)
            system_prompt = MOVIE_EXPAND_SYSTEM if has_material else MOVIE_AI_SYSTEM
            user_prompt = (
                f"{context}\n\n"
                f"可用素材较少，请在忠实于以上信息、不编造具体情节的前提下，写成约 {target} 字的完整简介。"
            )
        else:
            season = int(job.get("season") or 0)
            episode = int(job.get("episode") or 0)
            zh_episode = (self._tmdb.season_episodes(job["tmdb_id"], season, "zh-CN").get(episode)) or {}
            en_episode = (self._tmdb.season_episodes(job["tmdb_id"], season, "en-US").get(episode)) or {}
            context = self._episode_context(
                job,
                zh_episode,
                clean_text(zh_episode.get("overview")),
                clean_text(en_episode.get("overview")),
            )
            system_prompt = EPISODE_SYSTEM
            user_prompt = (
                f"{context}\n\n"
                f"现有素材不足以区分本集，请依据以上上下文写一段约 {target} 字的该集简介，"
                "并与其他集明显区分开。"
            )

        answer = clean_text(self._llm_generate(system_prompt, user_prompt), 4000)
        if not answer:
            return plan
        if visible_length(answer) >= max(1, minimum):
            source = SOURCE_AI if not text else f"{plan.get('source') or SOURCE_TMDB}+{SOURCE_AI}"
            return {"action": "write", "text": answer, "source": source}
        if visible_length(answer) > visible_length(text):
            return {
                "action": "write",
                "text": answer,
                "source": SOURCE_AI,
                "message": "AI 生成（素材偏少，已尽量扩写）",
            }
        return plan

    # ------------------------------------------------------------------ 执行

    def preview(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """试跑：扫描与判断不写库；sample>0 时为前几条生成样张（不写入）。"""
        payload = payload or {}
        sample = _bounded_int(payload.get("sample"), 0, 0, 5)
        jobs, errors, stats = self._collect_jobs(
            media_type=str(payload.get("media_type") or "all"),
            title=str(payload.get("title") or ""),
            force=payload.get("force"),
            limit=_bounded_int(payload.get("limit"), 30, 1, 200),
            focus_keys=payload.get("keys") if isinstance(payload.get("keys"), list) else None,
        )
        items: List[Dict[str, Any]] = []
        for index, job in enumerate(jobs):
            plan = self._plan_job(job, allow_llm=False)
            preview_text = ""
            quality = ""
            if sample and index < sample:
                richer = self._plan_job(job, allow_llm=True)
                preview_text = clean_text(richer.get("text"))[:400]
                if richer.get("failed"):
                    quality = str(richer.get("message") or "生成失败")
                    preview_text = ""
                elif preview_text:
                    quality = self._quality_issue(preview_text, str(job.get("kind") or ""))
            items.append(
                {
                    "key": job.get("key"),
                    "server": job.get("server"),
                    "kind": job.get("kind"),
                    "title": job.get("title"),
                    "year": job.get("year"),
                    "season": job.get("season"),
                    "episode": job.get("episode"),
                    "episode_title": job.get("episode_title"),
                    "reason": job.get("reason"),
                    "current_len": job.get("current_len"),
                    "action": plan.get("action"),
                    "source": plan.get("source"),
                    "message": plan.get("message"),
                    "current": clean_text(job.get("current"))[:160],
                    "preview": preview_text,
                    "quality": quality,
                    "need_nfo": bool(job.get("need_nfo")),
                    "need_avatar": bool(job.get("need_avatar")),
                }
            )
        return {
            "items": items,
            "errors": errors,
            "stats": stats,
            "total": len(jobs),
            "sample": sample,
        }

    def start_run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """启动一次后台执行任务（试跑请调用 preview）。"""
        with self._lock:
            if self._stop_pending.is_set() or not self._config.get("enabled"):
                return {"started": False, "message": "插件已停止或未启用"}
            if self._thread is not None and self._thread.is_alive():
                return {"started": False, "message": "已有任务正在执行"}
            payload = payload or {}
            self._cancel.clear()
            self._run = self._new_run(str(payload.get("trigger") or "manual"))
            self._thread = threading.Thread(
                target=self._run_worker,
                args=(payload,),
                name="MediaOverviewEnhancerRun",
                daemon=True,
            )
            self._thread.start()
            return {"started": True, "message": "任务已启动"}

    def _new_run(self, trigger: str) -> Dict[str, Any]:
        """构造一次运行的进度状态。"""
        return {
            "state": "running",
            "run_id": datetime.now().strftime("%Y%m%d%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}",
            "trigger": trigger,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": 0,
            "done": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "current": "",
            "message": "正在扫描媒体库",
            "sources": {},
        }

    def retry_failures(self) -> Dict[str, Any]:
        """重试处理记录里仍然失败的条目（使用失败时的任务快照）。"""
        failures = self._state.get("failures") or {}
        jobs = [
            dict(entry.get("job"))
            for entry in failures.values()
            if isinstance(entry, dict) and isinstance(entry.get("job"), dict)
        ]
        maximum = int(self._config.get("max_items_per_run") or 200)
        jobs = jobs[:maximum]
        if not jobs:
            return {"started": False, "message": "没有可重试的失败条目"}
        return self._start_jobs(jobs, trigger="retry")

    def _start_jobs(self, jobs: List[Dict[str, Any]], trigger: str = "retry") -> Dict[str, Any]:
        """用已构造好的任务列表启动后台执行（失败重试路径）。"""
        with self._lock:
            if self._stop_pending.is_set() or not self._config.get("enabled"):
                return {"started": False, "message": "插件已停止或未启用"}
            if self._thread is not None and self._thread.is_alive():
                return {"started": False, "message": "已有任务正在执行"}
            if not jobs:
                return {"started": False, "message": "没有可处理的条目"}
            self._cancel.clear()
            self._run = self._new_run(trigger)
            self._run["total"] = len(jobs)
            self._run["message"] = f"待处理 {len(jobs)} 条"
            self._thread = threading.Thread(
                target=self._execute_jobs,
                args=(jobs, {}),
                name="MediaOverviewEnhancerRetry",
                daemon=True,
            )
            self._thread.start()
            return {"started": True, "message": f"已启动 {len(jobs)} 条失败重试"}

    def cancel_run(self) -> Dict[str, Any]:
        """请求停止当前任务。"""
        if not self._run or self._run.get("state") != "running":
            return {"cancelled": False, "message": "当前没有正在执行的任务"}
        self._cancel.set()
        return {"cancelled": True, "message": "已请求停止，将在当前条目处理完成后退出"}

    def _run_worker(self, payload: Dict[str, Any]) -> None:
        """后台执行任务：收集条目后交给统一执行器。"""
        try:
            # 每轮重新解析一次媒体服务器配置，本轮内所有条目复用同一批客户端
            self._clients_cache = None
            jobs, errors, stats = self._collect_jobs(
                media_type=str(payload.get("media_type") or "all"),
                title=str(payload.get("title") or ""),
                force=payload.get("force"),
                limit=payload.get("limit"),
                focus_keys=payload.get("keys") if isinstance(payload.get("keys"), list) else None,
            )
            for message in errors:
                self._log(message, "warning")
            if stats.get("skipped_no_provider"):
                names = list(getattr(self, "_no_provider_names", []) or [])
                hint = ""
                if names:
                    shown = "、".join(names[:5])
                    more = f" 等 {len(names)} 个" if len(names) > 5 else ""
                    hint = f"；例如 {shown}{more}，可在 Emby 里补 TMDB 标识后重跑"
                self._log(
                    f"跳过 {stats['skipped_no_provider']} 条缺少 TMDB 标识的条目"
                    "（多为 MV 或未刮削内容，合集类库默认不动）" + hint,
                    "warning",
                )
            if stats.get("title_matched"):
                self._log(
                    f"其中 {stats['title_matched']} 条按标题匹配到 TMDB 标识后继续处理",
                    "warning",
                )
            self._execute_jobs(jobs, stats)
        except Exception as err:  # noqa: BLE001
            self._log(f"任务执行异常：{err}", "error")
            self._finish_run(f"任务执行异常：{err}", {})

    def _execute_jobs(self, jobs: List[Dict[str, Any]], stats: Dict[str, Any]) -> None:
        """执行给定的任务列表（手动、定时与失败重试共用同一路径）。"""
        try:
            with self._lock:
                if self._run is not None:
                    self._run.update(
                        {
                            "total": len(jobs),
                            "message": f"待处理 {len(jobs)} 条",
                            "servers": stats.get("clients") or (self._run.get("servers") or []),
                        }
                    )
            if not jobs:
                self._finish_run("没有需要处理的条目", stats)
                return
            workers = max(1, min(8, int(self._config.get("concurrency") or 2)))
            self._log(f"开始处理 {len(jobs)} 条简介（并发 {workers}）")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._process_job, job): job for job in jobs}
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        result = future.result()
                    except Exception as err:  # noqa: BLE001
                        result = {"status": "failed", "message": str(err)}
                    self._record_result(job, result)
            with self._lock:
                run = self._run or {}
                updated = int(run.get("updated") or 0)
                skipped = int(run.get("skipped") or 0)
                failed = int(run.get("failed") or 0)
            summary = f"处理完成：更新 {updated} 条，跳过 {skipped} 条，失败 {failed} 条"
            self._finish_run(summary, stats)
        except Exception as err:  # noqa: BLE001
            self._log(f"任务执行异常：{err}", "error")
            self._finish_run(f"任务执行异常：{err}", stats)

    def _record_result(self, job: Dict[str, Any], result: Dict[str, Any]) -> None:
        """记录单条处理结果、失败清单与同季简介指纹。"""
        status = str(result.get("status") or "skipped")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            if self._run is not None:
                self._run["done"] = int(self._run.get("done") or 0) + 1
                if status == "updated":
                    self._run["updated"] = int(self._run.get("updated") or 0) + 1
                    sources = self._run.get("sources")
                    if not isinstance(sources, dict):
                        sources = {}
                        self._run["sources"] = sources
                    source = str(result.get("source") or "unknown")
                    sources[source] = int(sources.get(source) or 0) + 1
                elif status == "failed":
                    self._run["failed"] = int(self._run.get("failed") or 0) + 1
                else:
                    self._run["skipped"] = int(self._run.get("skipped") or 0) + 1
                if result.get("untranslated"):
                    self._run["untranslated"] = int(self._run.get("untranslated") or 0) + 1
                label = str(job.get("title") or "")
                if job.get("kind") == EPISODE:
                    label = f"{label} S{job.get('season')}E{job.get('episode')}"
                self._run["current"] = f"{label} · {status}"
            self._bump_daily(status)
            failures = self._state.get("failures")
            if not isinstance(failures, dict):
                failures = {}
                self._state["failures"] = failures
            key = str(job.get("key") or "")
            if status == "updated":
                failures.pop(key, None)
                skipped_cache = self._state.get("skipped_untranslated")
                if isinstance(skipped_cache, dict):
                    skipped_cache.pop(key, None)
                self._state.setdefault("records", {})[key] = {
                    "hash": text_signature(result.get("text")),
                    "time": now,
                    "source": result.get("source") or "",
                    "chars": visible_length(result.get("text")),
                }
                if job.get("kind") == EPISODE:
                    bucket = self._state.setdefault("recent_episodes", {}).setdefault(
                        f"{job.get('tmdb_id')}|{job.get('season')}", {}
                    )
                    bucket[str(job.get("episode"))] = {
                        "sig": text_signature(result.get("text")),
                        "head": str(result.get("text") or "")[:60],
                        "time": now,
                    }
                    if len(bucket) > 200:
                        for old in list(bucket)[:-200]:
                            bucket.pop(old, None)
            elif status == "failed":
                previous = failures.get(key) if isinstance(failures.get(key), dict) else {}
                failures[key] = {
                    "key": key,
                    "kind": job.get("kind"),
                    "title": job.get("title"),
                    "year": job.get("year"),
                    "season": job.get("season"),
                    "episode": job.get("episode"),
                    "server": job.get("server"),
                    "item_id": job.get("item_id"),
                    "message": str(result.get("message") or ""),
                    "time": now,
                    "count": int(previous.get("count") or 0) + 1,
                    "job": dict(job),
                }
            elif result.get("untranslated"):
                # 中文缺失止损：记录当前简介指纹，简介未变化时不再重复生成
                self._state.setdefault("skipped_untranslated", {})[key] = {
                    "sig": text_signature(job.get("current")),
                    "message": str(result.get("message") or ""),
                    "time": now,
                    "ts": time.time(),
                }
                self._bump_daily("untranslated")
        if status == "failed":
            self._log(f"{job.get('title')} {job.get('item_id')} 处理失败：{result.get('message')}", "error")

    def _bump_daily(self, status: str) -> None:
        """按天累计处理结果，供每日汇总通知使用。"""
        daily = self._state.get("daily")
        today = datetime.now().strftime("%Y-%m-%d")
        if not isinstance(daily, dict) or daily.get("date") != today:
            daily = {
                "date": today,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "untranslated": 0,
                "runs": 0,
            }
            self._state["daily"] = daily
        key = status if status in {"updated", "skipped", "failed", "untranslated"} else "skipped"
        daily[key] = int(daily.get(key) or 0) + 1

    def _finish_run(self, message: str, stats: Dict[str, Any]) -> None:
        """结束任务并保存状态、发送通知。"""
        if self._stop_pending.is_set():
            return
        with self._lock:
            if self._run is not None:
                self._run.update(
                    {
                        "state": "finished",
                        "message": message,
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                summary = dict(self._run)
                daily = self._state.get("daily")
                today = datetime.now().strftime("%Y-%m-%d")
                if not isinstance(daily, dict) or daily.get("date") != today:
                    daily = {
                        "date": today,
                        "updated": 0,
                        "skipped": 0,
                        "failed": 0,
                        "untranslated": 0,
                        "runs": 0,
                    }
                    self._state["daily"] = daily
                daily["runs"] = int(daily.get("runs") or 0) + 1
            else:
                summary = {}
            self._state["last_run"] = summary
            self._state["stats"] = {
                "movies": stats.get("movies", 0),
                "episodes": stats.get("episodes", 0),
                "servers": stats.get("clients") or [],
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        self._save_state()
        self._log(message)
        if not summary or self._stop_pending.is_set():
            return
        servers = "、".join(summary.get("servers") or []) or "全部"
        sources = summary.get("sources") if isinstance(summary.get("sources"), dict) else {}
        source_text = "、".join(
            f"{key} {value}"
            for key, value in sorted(
                sources.items(), key=lambda item: -int(item[1] or 0)
            )[:4]
        )
        detail = f"{message}\n服务器：{servers}"
        if source_text:
            detail += f"\n来源：{source_text}"
        skipped_ai = int(summary.get("untranslated") or 0)
        if skipped_ai:
            detail += (
                f"\n其中 {skipped_ai} 条因素材缺中文已记入放弃清单"
                "（简介变化或强制重写时才会再试）"
            )
        if self._config.get("notify") and self._notify is not None:
            try:
                self._notify("影视简介增强", detail)
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：通知发送失败 {err}")
        failed = int(summary.get("failed") or 0)
        if failed and self._config.get("notify_failure") and self._notify is not None:
            failed_titles = self._failed_titles(5)
            text = f"本次有 {failed} 条处理失败，可在插件详情页查看并可一键重试。\n服务器：{servers}"
            if failed_titles:
                text += "\n" + "\n".join(f"· {item}" for item in failed_titles)
            try:
                self._notify("影视简介增强 · 有失败条目", text)
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：失败提醒发送失败 {err}")

    def _failed_titles(self, limit: int = 5) -> List[str]:
        """返回最近失败条目的可读名称（含失败原因）。"""
        failures = self._state.get("failures") or {}
        rows = sorted(
            [entry for entry in failures.values() if isinstance(entry, dict)],
            key=lambda entry: str(entry.get("time") or ""),
            reverse=True,
        )[:limit]
        result: List[str] = []
        for entry in rows:
            title = str(entry.get("title") or "")
            if entry.get("kind") == EPISODE:
                title = f"{title} S{entry.get('season')}E{entry.get('episode')}"
            message = str(entry.get("message") or "")
            if message:
                title = f"{title}（{message[:40]}）"
            if title.strip():
                result.append(title.strip())
        return result

    def _process_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """处理单条条目：生成简介、质量校验、写回媒体服务器并维护 NFO/头像。"""
        if self._cancel.is_set():
            return {"status": "skipped", "message": "任务已取消"}
        client = self._client_by_name(job.get("server") or "")
        if client is None:
            return {"status": "failed", "message": "媒体服务器不可用"}
        plan = self._plan_job(job)
        if plan.get("failed"):
            return {"status": "failed", "message": plan.get("message") or "生成失败"}
        if plan.get("action") != "write":
            return {"status": "skipped", "message": plan.get("message") or "无可用简介"}
        text = clean_text(plan.get("text"), 4000)
        source = str(plan.get("source") or "")
        maintenance = source in {SOURCE_PEOPLE, SOURCE_MAINTENANCE}
        if not maintenance:
            # 电影/剧集同样剔除「2160p、WEB-DL、编码」这类文件信息句
            text = clean_text(strip_technical_sentences(text), 4000)
            # 分集 AI 文案常以「第12集中，」「本集延续…」开场，去掉编号套话再交给质量闸门
            if job.get("kind") == EPISODE:
                text = clean_text(strip_template_opening(text), 4000)
            issue = self._quality_issue(text, str(job.get("kind") or ""))
            if issue:
                if issue.startswith(_UNTRANSLATED_PREFIX):
                    # 素材本身没有中文且翻译失败：记为「中文缺失跳过」并写入止损缓存，
                    # 避免每轮扫描重复调用 AI 翻译
                    return {"status": "skipped", "message": issue, "untranslated": True}
                return {"status": "failed", "message": issue}
        if not maintenance and text_signature(text) == text_signature(job.get("current")):
            return {"status": "skipped", "message": "内容与现有简介一致"}
        if not maintenance and not text:
            # 方案只给出「将翻译 / 将扩写」等提示、没有实际文本时不写库，
            # 避免把空字符串当成一次「更新」计入统计。
            return {"status": "skipped", "message": plan.get("message") or "无可用简介文本"}
        if self._cancel.is_set():
            return {"status": "skipped", "message": "任务已取消"}
        people: Optional[List[Dict[str, Any]]] = None
        if job.get("kind") == MV:
            people = self._mv_people(job) or None
        dto = client.get_full_dto(job["item_id"])
        if not dto:
            return {"status": "failed", "message": "无法读取条目当前信息"}
        if plan.get("skip_write"):
            # 仅维护派生产物：简介与演员都没有变化，只补 NFO / 头像
            self._write_nfo(job, text, people or [])
            self._ensure_avatars(client, job, people or [], dto=dto)
            return {
                "status": "updated",
                "text": text,
                "source": source,
                "people": [person["Name"] for person in (people or [])],
            }
        old_overview = clean_text(dto.get("Overview"))
        old_locked = [str(value) for value in (dto.get("LockedFields") or []) if value]
        verify: Dict[str, Any] = {}
        ok, message = client.update_overview(
            job["item_id"],
            text,
            lock=bool(self._config.get("lock_overview")),
            people=people,
            lock_people=bool(people) and bool(self._config.get("lock_overview")),
            prune_role=self._mv_prune_role(job, people),
            dto=dto,
            verify_sink=verify,
        )
        if not ok:
            return {"status": "failed", "message": message}
        if old_overview and text_signature(old_overview) != text_signature(text):
            self._save_backup(job, old_overview, old_locked)
        self._write_nfo(job, text, people or [])
        self._ensure_avatars(client, job, people or [], dto=verify or dto)
        return {
            "status": "updated",
            "text": text,
            "source": source,
            "people": [person["Name"] for person in (people or [])],
        }

    def _quality_issue(self, text: str, kind: str) -> str:
        """质量闸门：拦截未翻译、技术信息残留、模板化与长度异常的简介。"""
        if not self._config.get("quality_gate"):
            return ""
        body = str(text or "").strip()
        if visible_length(body) < 10:
            return "生成结果过短"
        target_key = (
            "movie_target_chars"
            if kind == MOVIE
            else ("mv_target_chars" if kind == MV else "episode_target_chars")
        )
        target = int(self._config.get(target_key) or 0)
        if target and visible_length(body) > max(600, target * 3):
            return "生成结果明显超出目标字数"
        ratio = text_cjk_ratio(body)
        minimum = float(self._config.get("quality_min_cjk_ratio") or 0.25)
        if ratio < minimum:
            return f"简介中文占比过低（{ratio:.0%}），疑似未翻译"
        if kind != MV and MV_TEXT_NOISE_PATTERN.search(body) and visible_length(body) <= 80:
            return "简介仍在描述画质/编码等技术信息"
        if kind != MV and TEMPLATE_SENTENCE_PATTERN.match(body) and visible_length(body) < 80:
            return "简介过于模板化，可能是空泛生成"
        return ""

    def _save_backup(self, job: Dict[str, Any], overview: str, locked: List[str]) -> None:
        """写入前保存旧简介与锁定状态（保留最原始版本），供详情页回滚。"""
        key = str(job.get("key") or "")
        if not key:
            return
        with self._lock:
            backups = self._state.get("backups")
            if not isinstance(backups, dict):
                backups = {}
                self._state["backups"] = backups
            if key in backups:
                return
            backups[key] = {
                "key": key,
                "server": job.get("server"),
                "kind": job.get("kind"),
                "title": job.get("title"),
                "year": job.get("year"),
                "season": job.get("season"),
                "episode": job.get("episode"),
                "item_id": job.get("item_id"),
                "overview": overview,
                "locked": list(locked),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ts": time.time(),
                "run_id": str((self._run or {}).get("run_id") or ""),
            }
            self._cleanup_backups()
        self._save_state()

    def rollback(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """把条目简介回滚到写入前的版本（支持按键或按最近一轮运行）。"""
        payload = payload or {}
        if self._thread is not None and self._thread.is_alive():
            return {"rolled_back": 0, "failed": 0, "message": "当前有任务在运行，请先停止"}
        keys = payload.get("keys") if isinstance(payload.get("keys"), list) else []
        keys = {str(value) for value in keys if str(value or "").strip()}
        run_id = str(payload.get("run_id") or "").strip()
        backups = self._state.get("backups") or {}
        targets: List[Tuple[str, Dict[str, Any]]] = []
        for key, entry in backups.items():
            if not isinstance(entry, dict):
                continue
            if keys and key not in keys:
                continue
            if run_id and str(entry.get("run_id") or "") != run_id:
                continue
            targets.append((key, entry))
        if not targets:
            return {"rolled_back": 0, "failed": 0, "message": "没有匹配的备份"}
        rolled = failed = 0
        messages: List[str] = []
        for key, entry in targets:
            client = self._client_by_name(str(entry.get("server") or ""))
            if client is None:
                failed += 1
                continue
            locked = [str(value) for value in (entry.get("locked") or []) if value]
            ok, message = client.update_overview(
                str(entry.get("item_id") or ""),
                str(entry.get("overview") or ""),
                lock="Overview" in locked,
                unlock_overview="Overview" not in locked,
            )
            if ok:
                rolled += 1
                with self._lock:
                    (self._state.get("backups") or {}).pop(key, None)
                self._log(f"已回滚「{entry.get('title')}」的简介到写入前版本", "warning")
            else:
                failed += 1
                messages.append(f"{entry.get('title')}: {message}")
        self._save_state()
        return {
            "rolled_back": rolled,
            "failed": failed,
            "message": "；".join(messages[:3]) or f"已回滚 {rolled} 条",
        }

    # ------------------------------------------------------------------ 入库后自动

    def queue_transfer(self, title: str, year: str = "", media_type: str = "") -> Dict[str, Any]:
        """记录入库事件，稍后延迟补全该媒体简介。"""
        if (not self._config.get("enabled") or self._stop_pending.is_set()
                or not self._config.get("auto_on_transfer") or not title):
            return {"queued": False, "message": "未开启入库后自动补全或插件已停止"}
        with self._lock:
            self._pending.append({
                "title": title, "year": str(year or ""), "type": media_type or "",
                "ready_at": time.monotonic() + int(self._config.get("post_transfer_delay") or 0),
            })
            self._pending = self._pending[-20:]
            if self._pending_worker is None or not self._pending_worker.is_alive():
                self._pending_worker = threading.Thread(
                    target=self._pending_loop, name="MediaOverviewEnhancerPending", daemon=True
                )
                self._pending_worker.start()
        return {"queued": True, "message": f"已登记 {title}，稍后自动补全"}

    def _pending_loop(self) -> None:
        """按每次入库的完整延迟等待；忙碌时保留队列，停止时立即唤醒。"""
        while not self._stop_pending.wait(1):
            with self._lock:
                if not self._pending or self._pending[0]["ready_at"] > time.monotonic():
                    continue
                if self._thread is not None and self._thread.is_alive():
                    continue
                entry = self._pending.pop(0)
                result = self.start_run({
                    "trigger": "transfer", "title": entry["title"], "media_type": "all"
                })
                if not result.get("started"):
                    self._pending.insert(0, entry)

    def stop(self) -> None:
        """停止接收任务、唤醒延迟线程并阻止生成中的条目继续写回。"""
        self._stop_pending.set()
        self._cancel.set()
        with self._lock:
            self._pending.clear()
        for thread in (self._pending_worker, self._thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
        self._save_state(allow_stopped=True)

    def handle_transfer_event(self, event_data: Any) -> Dict[str, Any]:
        """解析整理完成事件并登记待补全条目。"""
        if not isinstance(event_data, dict):
            return {"queued": False, "message": "事件数据格式不支持"}
        mediainfo = event_data.get("mediainfo") or {}
        meta = event_data.get("meta") or {}
        title = str(
            event_value(mediainfo, "title", "name") or event_value(meta, "name", "title") or ""
        ).strip()
        year = str(event_value(mediainfo, "year", "release_year", default="") or "").strip()
        media_type = str(event_value(mediainfo, "type", default="") or "").strip()
        season = event_value(meta, "begin_season", "season")
        if not title:
            return {"queued": False, "message": "未能解析标题"}
        if season and not media_type:
            media_type = "电视剧"
        return self.queue_transfer(title=title, year=year, media_type=media_type)
