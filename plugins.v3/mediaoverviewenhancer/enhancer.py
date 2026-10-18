"""影视简介增强核心引擎：扫描媒体库条目、生成更详细的简介并写回媒体服务器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

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
    "episode_min_chars": 40,
    "episode_target_chars": 160,
    "episode_always_rewrite": False,
    "skip_specials": True,
    # MV（音乐视频）
    "mv_enabled": True,
    "mv_libraries": ["mv"],
    "mv_min_chars": 60,
    "mv_target_chars": 110,
    # 数据源与写入
    "translate_foreign": True,
    "ai_generate_when_missing": True,
    "ai_when_source_short": False,
    "tmdb_title_fallback": False,
    "duplicate_detect": True,
    "lock_overview": True,
    "force_rewrite": False,
    # 运行控制
    "concurrency": 2,
    "max_items_per_run": 200,
    "notify": True,
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
    data["episode_min_chars"] = _bounded_int(data.get("episode_min_chars"), 40, 0, 2000)
    data["episode_target_chars"] = _bounded_int(data.get("episode_target_chars"), 160, 40, 1000)
    data["mv_libraries"] = _as_str_list(data.get("mv_libraries")) or ["mv"]
    data["mv_min_chars"] = _bounded_int(data.get("mv_min_chars"), 60, 0, 2000)
    data["mv_target_chars"] = _bounded_int(data.get("mv_target_chars"), 110, 40, 1000)
    data["concurrency"] = _bounded_int(data.get("concurrency"), 2, 1, 8)
    data["max_items_per_run"] = _bounded_int(data.get("max_items_per_run"), 200, 1, 5000)
    for key in (
        "enabled",
        "auto_on_transfer",
        "movie_enabled",
        "episode_enabled",
        "mv_enabled",
        "episode_always_rewrite",
        "skip_specials",
        "translate_foreign",
        "ai_generate_when_missing",
        "ai_when_source_short",
        "tmdb_title_fallback",
        "duplicate_detect",
        "lock_overview",
        "force_rewrite",
        "notify",
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
    ) -> Iterator[Dict[str, Any]]:
        """按媒体库分页遍历指定类型的条目。"""
        fields = (
            "ProviderIds,Overview,ProductionYear,PremiereDate,Genres,"
            "SeriesId,SeriesName,ParentIndexNumber,IndexNumber,Name,Type"
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

    def update_overview(self, item_id: str, overview: str, lock: bool = True) -> Tuple[bool, str]:
        """写入条目的简介。

        Emby 的 UpdateItem 会整份覆盖条目字段，缺失 ``ProviderIds`` 会直接报 400，
        缺失 ``Name``/``IndexNumber`` 则会被清空。因此这里先读回完整条目，
        只替换简介与锁定字段后整体回写。
        """
        payload = self.get_full_dto(item_id)
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
        verify = self.get_item_detail(item_id, "Overview,Name")
        written = clean_text(verify.get("Overview"))
        if text_signature(written) != text_signature(overview):
            return False, "写入后回读不一致"
        if not verify.get("Name"):
            return False, "写入后条目名称为空"
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

    def _client(self, language: str) -> Any:
        """获取指定语言的 TMDB 客户端。"""
        if language not in self._clients:
            from app.modules.themoviedb.tmdbapi import TmdbApi

            self._clients[language] = TmdbApi(language=language)
        return self._clients[language]

    def movie_detail(self, tmdb_id: Any, language: str = "zh-CN") -> Dict[str, Any]:
        """读取电影详情，失败时返回空字典。"""
        try:
            detail = self._client(language).movie.details(int(tmdb_id)) or {}
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：TMDB 电影详情读取失败 {tmdb_id} {err}")
            return {}
        return detail if isinstance(detail, dict) else dict(detail)

    def tv_detail(self, tmdb_id: Any, language: str = "zh-CN") -> Dict[str, Any]:
        """读取剧集详情，失败时返回空字典。"""
        try:
            detail = self._client(language).tv.details(int(tmdb_id)) or {}
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视简介增强：TMDB 剧集详情读取失败 {tmdb_id} {err}")
            return {}
        return detail if isinstance(detail, dict) else dict(detail)

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

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """同步调用 LLM 生成文本，失败时返回空字符串。"""
        if not self.available():
            return ""
        try:
            return str(run_coroutine(self._ainvoke(system_prompt, user_prompt)) or "").strip()
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：LLM 调用失败 {err}")
            return ""


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
    r"(?i)(2160p|1080p|720p|4k|uhd|web-?dl|blu-?ray|蓝光|hevc|avc|vp9|av1|aac|opus|flac|pcm|mp3|prores|"
    r"编码|码率|画质|超清|高清|分辨率|片源|压制|音轨|轨道|文件大小|webrip|hdtv)"
)

# MV 文件名里的画质、编码、来源等噪声词
MV_NOISE_PATTERN = re.compile(
    r"(?i)\b(2160p|1080p|720p|480p|4k|uhd|web-?dl|webrip|bluray|blu-ray|bdrip|avc|hevc|h\.?264|h\.?265|"
    r"vp9|av1|aac|ac3|eac3|dts|opus|prores|pcm|mp3|flac|xvid|divx|10bits?|8bits?|60fps|\d+fps|"
    r"official|music video|demo|lg|umax|sbs|mbc|kbs|youtube|ytb)\b"
)

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
    year_match = re.search(r"(19|20)\d{2}", stem)
    body = re.sub(r"-(PTerMV|CMTV|CMCT|FRDS|HHWEB|CornerMV|Amzv)\b.*$", "", stem, flags=re.I)
    parts = re.split(r"\s+[-–]\s+", body, maxsplit=1)
    artist = parts[0].strip(" ._-") if len(parts) > 1 else ""
    song = parts[1] if len(parts) > 1 else parts[0]
    song = re.sub(r"[._]+", " ", song)
    song = re.sub(r"\[[^\]]*\]", " ", song)
    song = re.sub(r"\([^)]*\)", " ", song)
    song = re.sub(MV_NOISE_PATTERN, " ", song)
    song = re.sub(r"\s{2,}", " ", song).strip(" -_")
    artist = re.sub(r"[._]+", " ", artist).strip(" -_")
    if not artist and origin:
        artist = origin
    return {
        "artist": artist,
        "song": song or origin or stem,
        "year": year_match.group(0) if year_match else "",
        "notes": "、".join(dict.fromkeys(notes)),
    }


TRANSLATE_SYSTEM = (
    "你是影视作品简介翻译。把给定简介翻译成通顺的简体中文，"
    "保持原有信息量，不增删情节，不加小标题或列表，直接输出译文。"
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
        self._lock = threading.RLock()
        self._state = self._load_state()
        self._run: Optional[Dict[str, Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._pending: List[Dict[str, Any]] = []
        self._pending_worker: Optional[threading.Thread] = None
        self._stop_pending = threading.Event()
        self._skipped_no_provider = 0
        self._title_matched = 0

    # ------------------------------------------------------------------ 状态持久化

    def _load_state(self) -> Dict[str, Any]:
        """读取本地状态文件。"""
        default: Dict[str, Any] = {"records": {}, "logs": [], "last_run": None, "stats": {}}
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    default.update(data)
        except Exception as err:  # noqa: BLE001
            logger.warning(f"影视简介增强：状态文件读取失败 {err}")
        if not isinstance(default.get("records"), dict):
            default["records"] = {}
        if not isinstance(default.get("logs"), list):
            default["logs"] = []
        return default

    def _save_state(self, allow_stopped: bool = False) -> None:
        """串行保存快照；旧引擎停止后仅允许 stop 保存最后一次状态。"""
        with self._lock:
            if self._stop_pending.is_set() and not allow_stopped:
                return
            self._state["records"] = dict(list(self._state.get("records", {}).items())[-20000:])
            self._state["logs"] = list(self._state.get("logs", []))[-300:]
            payload = dict(self._state)
            try:
                self._state_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：状态文件写入失败 {err}")

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
        records = self._state.get("records") or {}
        run = self._run or {}
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
            "processed_total": len(records),
            "stats": self._state.get("stats") or {},
            "last_run": self._state.get("last_run"),
            "running": bool(run and run.get("state") == "running"),
            "run": run,
            "logs": list(self._state.get("logs") or [])[-40:],
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
        """清空处理记录，使所有条目可以重新补全。"""
        with self._lock:
            count = len(self._state.get("records") or {})
            self._state["records"] = {}
        self._save_state()
        self._log(f"已清空 {count} 条处理记录", "warning")
        return {"cleared": count}

    # ------------------------------------------------------------------ 媒体服务器

    def _resolve_clients(self) -> Tuple[List[EmbyClient], List[str]]:
        """按配置解析可用的 Emby 客户端。"""
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
        clients, _ = self._resolve_clients()
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
            current = self._overview_of(item)
            current_len = visible_length(current)
            if not force and current_len >= min_chars:
                continue
            name = str(item.get("Name") or "")
            year = str(item.get("ProductionYear") or "")
            if require_provider:
                tmdb_id = self._tmdb_provider_id(item)
            else:
                tmdb_id = self._tmdb_id_of(item, MOVIE, name, year)
            if not tmdb_id:
                if require_provider:
                    self._skipped_no_provider += 1
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

    def _build_mv_jobs(
        self,
        client: EmbyClient,
        items: List[Dict[str, Any]],
        force: bool,
    ) -> List[Dict[str, Any]]:
        """根据 MV 库条目构建待处理任务（简介来源只有 AI）。"""
        jobs: List[Dict[str, Any]] = []
        minimum = int(self._config.get("mv_min_chars") or 0)
        for item in items:
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            current = self._overview_of(item)
            current_len = visible_length(current)
            if not force and current_len >= minimum:
                continue
            path = str(item.get("Path") or "")
            parsed = parse_mv_media(path or str(item.get("Name") or ""))
            jobs.append(
                {
                    "key": f"{client.name}|{item_id}",
                    "kind": MV,
                    "server": client.name,
                    "item_id": item_id,
                    "title": str(item.get("Name") or "") or parsed.get("song") or "",
                    "year": str(item.get("ProductionYear") or parsed.get("year") or ""),
                    "current": current,
                    "current_len": current_len,
                    "reason": "force" if force else ("missing" if not current_len else "short"),
                    "path": path,
                    "artist": parsed.get("artist") or "",
                    "song": parsed.get("song") or "",
                    "notes": parsed.get("notes") or "",
                }
            )
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
                    matched_id, matched_name = self._tmdb.match_tv_id(
                        series_title, series_year, season=season
                    )
                    if matched_id:
                        tmdb_id = matched_id
                        self._title_matched += 1
                        self._log(
                            f"「{series_title}」无 TMDB 标识，按标题匹配到「{matched_name}」"
                            f"（tmdb={matched_id}）"
                        )
            else:
                tmdb_id = self._tmdb_id_of(series_item, EPISODE, series_title, series_year)
            if not tmdb_id:
                if require_provider:
                    self._skipped_no_provider += 1
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
                current = self._overview_of(item)
                current_len = visible_length(current)
                duplicated = current_len >= 10 and text_signature(current) in duplicate_values
                if not force and not always_rewrite and not duplicated and current_len >= min_chars:
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
    ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        """按范围收集待处理任务。"""
        clients, errors = self._resolve_clients()
        force_flag = bool(self._config.get("force_rewrite")) if force is None else bool(force)
        self._skipped_no_provider = 0
        self._title_matched = 0
        jobs: List[Dict[str, Any]] = []
        stats = {
            "clients": [client.name for client in clients],
            "movies": 0,
            "episodes": 0,
            "mv": 0,
        }
        libraries = _as_str_list(self._config.get("libraries"))
        # 候选收集只做分页遍历、成本很低，必须覆盖整库：单季超出十万集的库极少，
        # 这里给一个足够大的安全上限，避免大库尾部条目因窗口太小而永远扫不到。
        scan_limit = max(50000, int(self._config.get("max_items_per_run") or 200) * 10)
        for client in clients:
            if media_type == "mv":
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
                                    "Movie,MusicVideo,Video", [parent], max_items=scan_limit, extra_fields="Path"
                                )
                            ),
                            force_flag,
                        )
                        if title:
                            mv_jobs = [job for job in mv_jobs if title.casefold() in job["title"].casefold()]
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
                        list(client.iter_items("Movie", [parent], max_items=scan_limit)),
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
                        list(client.iter_items("Episode", [parent], max_items=scan_limit)),
                        force_flag,
                        require_provider=True,
                        series_map=series_map,
                    )
                    stats["episodes"] += len(episode_jobs)
                    jobs.extend(episode_jobs)
        stats["skipped_no_provider"] = self._skipped_no_provider
        stats["title_matched"] = self._title_matched
        configured_max = int(self._config.get("max_items_per_run") or 200)
        max_items = _bounded_int(limit, configured_max, 1, configured_max)
        return jobs[:max_items], errors, stats

    # ------------------------------------------------------------------ 简介决策

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

    def _mv_plan(self, job: Dict[str, Any], allow_llm: bool = True) -> Dict[str, Any]:
        """判断 MV 简介的生成方式：MV 没有 TMDB 源，只能由 AI 生成。"""
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
            return {"action": "skip", "message": "LLM 不可用，无法生成 MV 简介"}
        text = clean_text(
            strip_mv_file_noise(
                self._llm.generate(
                    MV_AI_SYSTEM,
                    f"{self._mv_context(job)}\n\n请写一段约 {target} 字的该 MV 中文简介。",
                )
            ),
            2000,
        )
        if visible_length(text) < max(20, min(minimum, 40)):
            return {"action": "skip", "message": "AI 生成结果过短"}
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
            text = self._llm.generate(
                TRANSLATE_SYSTEM,
                f"影片：{job['title']}（{job.get('year') or '年份未知'}）\n\n简介原文：\n{en_overview}",
            )
            return {
                "action": "write",
                "text": text or en_overview,
                "source": SOURCE_TRANSLATE if text else SOURCE_TMDB,
                "detail": zh_detail,
            }

        if mode == "ai":
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 依据影片信息生成", "detail": zh_detail}
            if not self._llm.available():
                if visible_length(zh_overview) >= 20:
                    return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
                return {"action": "skip", "message": "LLM 不可用", "detail": zh_detail}
            text = self._llm.generate(
                MOVIE_AI_SYSTEM,
                f"{self._movie_context(job, zh_detail, en_overview)}\n\n请写一段约 {target} 字的剧情简介。",
            )
            if not text:
                if visible_length(zh_overview) >= 20:
                    return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB, "detail": zh_detail}
                return {"action": "skip", "message": "AI 生成失败", "detail": zh_detail}
            return {"action": "write", "text": text, "source": SOURCE_AI, "detail": zh_detail}

        # expand：以 TMDB 中文简介为基础扩写，缺中文时先翻译英文，再考虑 AI 生成
        if visible_length(zh_overview) < 20:
            if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
                if not allow_llm:
                    return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文简介", "detail": zh_detail}
                text = self._llm.generate(
                    TRANSLATE_SYSTEM,
                    f"影片：{job['title']}（{job.get('year') or '年份未知'}）\n\n简介原文：\n{en_overview}",
                )
                return {
                    "action": "write",
                    "text": text or en_overview,
                    "source": SOURCE_TRANSLATE if text else SOURCE_TMDB,
                    "detail": zh_detail,
                }
            if not self._config.get("ai_generate_when_missing"):
                return {"action": "skip", "message": "缺少 TMDB 简介且未开启 AI 生成", "detail": zh_detail}
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 生成", "detail": zh_detail}
            text = self._llm.generate(
                MOVIE_AI_SYSTEM,
                f"{self._movie_context(job, zh_detail, '')}\n\n请写一段约 {target} 字的剧情简介。",
            )
            if not text:
                return {"action": "skip", "message": "AI 生成失败或 LLM 不可用", "detail": zh_detail}
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
        text = self._llm.generate(
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
            if visible_length(zh_overview) >= 20:
                return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}
            if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
                if not allow_llm:
                    return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文分集简介"}
                text = self._llm.generate(TRANSLATE_SYSTEM, f"{context}\n\n简介原文：\n{en_overview}")
                return {
                    "action": "write",
                    "text": text or en_overview,
                    "source": SOURCE_TRANSLATE if text else SOURCE_TMDB,
                }
            if visible_length(en_overview) >= 20:
                return {"action": "write", "text": en_overview, "source": SOURCE_TMDB}
            return {"action": "skip", "message": "TMDB 无该集简介"}

        if mode == "ai":
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 重写该集简介"}
            text = self._llm.generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。")
            if text:
                return {"action": "write", "text": text, "source": SOURCE_AI}
            if visible_length(zh_overview) >= 20:
                return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}
            return {"action": "skip", "message": "AI 生成失败或 LLM 不可用"}

        # auto：中文分集简介优先，其次英文翻译，最后按上下文生成
        if visible_length(zh_overview) >= max(20, min_chars):
            if self._config.get("episode_always_rewrite") and job.get("reason") in {"short", "duplicate", "force"}:
                if not allow_llm:
                    return {"action": "write", "text": "", "source": f"{SOURCE_TMDB}+{SOURCE_AI}", "message": "将扩写该集简介"}
                text = self._llm.generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。")
                if text:
                    return {"action": "write", "text": text, "source": f"{SOURCE_TMDB}+{SOURCE_AI}"}
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}

        if visible_length(zh_overview) >= 20:
            if not allow_llm:
                return {"action": "write", "text": "", "source": f"{SOURCE_TMDB}+{SOURCE_AI}", "message": "将扩写该集简介"}
            text = self._llm.generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。")
            if text:
                return {"action": "write", "text": text, "source": f"{SOURCE_TMDB}+{SOURCE_AI}"}
            return {"action": "write", "text": zh_overview, "source": SOURCE_TMDB}

        if visible_length(en_overview) >= 20 and self._config.get("translate_foreign"):
            if not allow_llm:
                return {"action": "write", "text": "", "source": SOURCE_TRANSLATE, "message": "将翻译英文分集简介"}
            text = self._llm.generate(TRANSLATE_SYSTEM, f"{context}\n\n简介原文：\n{en_overview}")
            return {
                "action": "write",
                "text": text or en_overview,
                "source": SOURCE_TRANSLATE if text else SOURCE_TMDB,
            }

        if not self._config.get("ai_generate_when_missing"):
            return {"action": "skip", "message": "缺少该集简介且未开启 AI 生成"}
        if not allow_llm:
            return {"action": "write", "text": "", "source": SOURCE_AI, "message": "将由 AI 依据剧集上下文生成"}
        if not has_tmdb:
            self._log(f"{job.get('title')} S{job.get('season')}E{job.get('episode')} 无 TMDB 简介，改用 AI 生成")
        text = self._llm.generate(EPISODE_SYSTEM, f"{context}\n\n请写一段约 {target} 字的该集简介。")
        if not text:
            return {"action": "skip", "message": "AI 生成失败或 LLM 不可用"}
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

        answer = clean_text(self._llm.generate(system_prompt, user_prompt), 4000)
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
        """试跑：只扫描与判断，不写库也不调用大模型。"""
        payload = payload or {}
        jobs, errors, stats = self._collect_jobs(
            media_type=str(payload.get("media_type") or "all"),
            title=str(payload.get("title") or ""),
            force=payload.get("force"),
            limit=_bounded_int(payload.get("limit"), 30, 1, 200),
        )
        items: List[Dict[str, Any]] = []
        for job in jobs:
            plan = self._plan_job(job, allow_llm=False)
            items.append(
                {
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
                }
            )
        return {"items": items, "errors": errors, "stats": stats, "total": len(jobs)}

    def start_run(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """启动一次后台执行任务（试跑请调用 preview）。"""
        with self._lock:
            if self._stop_pending.is_set() or not self._config.get("enabled"):
                return {"started": False, "message": "插件已停止或未启用"}
            if self._thread is not None and self._thread.is_alive():
                return {"started": False, "message": "已有任务正在执行"}
            payload = payload or {}
            self._cancel.clear()
            self._run = {
                "state": "running",
                "trigger": str(payload.get("trigger") or "manual"),
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total": 0,
                "done": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "current": "",
                "message": "正在扫描媒体库",
            }
            self._thread = threading.Thread(
                target=self._run_worker,
                args=(payload,),
                name="MediaOverviewEnhancerRun",
                daemon=True,
            )
            self._thread.start()
            return {"started": True, "message": "任务已启动"}

    def cancel_run(self) -> Dict[str, Any]:
        """请求停止当前任务。"""
        if not self._run or self._run.get("state") != "running":
            return {"cancelled": False, "message": "当前没有正在执行的任务"}
        self._cancel.set()
        return {"cancelled": True, "message": "已请求停止，将在当前条目处理完成后退出"}

    def _run_worker(self, payload: Dict[str, Any]) -> None:
        """后台执行任务：收集条目、生成简介并写回。"""
        try:
            jobs, errors, stats = self._collect_jobs(
                media_type=str(payload.get("media_type") or "all"),
                title=str(payload.get("title") or ""),
                force=payload.get("force"),
                limit=payload.get("limit"),
            )
            for message in errors:
                self._log(message, "warning")
            if stats.get("skipped_no_provider"):
                self._log(
                    f"跳过 {stats['skipped_no_provider']} 条缺少 TMDB 标识的条目"
                    "（多为 MV 或未刮削内容，合集类库默认不动）",
                    "warning",
                )
            if stats.get("title_matched"):
                self._log(
                    f"其中 {stats['title_matched']} 部剧集按标题匹配到 TMDB 标识后继续处理",
                    "warning",
                )
            with self._lock:
                if self._run is not None:
                    self._run.update(
                        {
                            "total": len(jobs),
                            "message": f"待处理 {len(jobs)} 条",
                            "servers": stats.get("clients") or [],
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
            summary = (
                f"处理完成：更新 {self._run.get('updated', 0)} 条，"
                f"跳过 {self._run.get('skipped', 0)} 条，失败 {self._run.get('failed', 0)} 条"
            )
            self._finish_run(summary, stats)
        except Exception as err:  # noqa: BLE001
            self._log(f"任务执行异常：{err}", "error")
            self._finish_run(f"任务执行异常：{err}", {})

    def _record_result(self, job: Dict[str, Any], result: Dict[str, Any]) -> None:
        """记录单条处理结果并更新进度。"""
        status = str(result.get("status") or "skipped")
        with self._lock:
            if self._run is not None:
                self._run["done"] = int(self._run.get("done") or 0) + 1
                if status == "updated":
                    self._run["updated"] = int(self._run.get("updated") or 0) + 1
                elif status == "failed":
                    self._run["failed"] = int(self._run.get("failed") or 0) + 1
                else:
                    self._run["skipped"] = int(self._run.get("skipped") or 0) + 1
                label = str(job.get("title") or "")
                if job.get("kind") == EPISODE:
                    label = f"{label} S{job.get('season')}E{job.get('episode')}"
                self._run["current"] = f"{label} · {status}"
        if status == "updated":
            self._state.setdefault("records", {})[job["key"]] = {
                "hash": text_signature(result.get("text")),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": result.get("source") or "",
                "chars": visible_length(result.get("text")),
            }
        elif status == "failed":
            self._log(f"{job.get('title')} {job.get('item_id')} 处理失败：{result.get('message')}", "error")

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
        if self._notify and summary and not self._stop_pending.is_set():
            try:
                self._notify(
                    "影视简介增强",
                    f"{message}\n服务器：{'、'.join(summary.get('servers') or []) or '全部'}",
                )
            except Exception as err:  # noqa: BLE001
                logger.warning(f"影视简介增强：通知发送失败 {err}")

    def _process_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """处理单条条目：生成简介并写回媒体服务器。"""
        if self._cancel.is_set():
            return {"status": "skipped", "message": "任务已取消"}
        client = self._client_by_name(job.get("server") or "")
        if client is None:
            return {"status": "failed", "message": "媒体服务器不可用"}
        plan = self._plan_job(job)
        if plan.get("action") != "write":
            return {"status": "skipped", "message": plan.get("message") or "无可用简介"}
        text = clean_text(plan.get("text"), 4000)
        if visible_length(text) < 10:
            return {"status": "skipped", "message": "生成结果过短"}
        if text_signature(text) == text_signature(job.get("current")):
            return {"status": "skipped", "message": "内容与现有简介一致"}
        if self._cancel.is_set():
            return {"status": "skipped", "message": "任务已取消"}
        ok, message = client.update_overview(
            job["item_id"], text, lock=bool(self._config.get("lock_overview"))
        )
        if not ok:
            return {"status": "failed", "message": message}
        return {"status": "updated", "text": text, "source": plan.get("source")}

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
