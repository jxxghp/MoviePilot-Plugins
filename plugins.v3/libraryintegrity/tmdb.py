"""TMDB 季集来源：读取包含单集 ID 与播出日期的季详情，并按剧集状态持久缓存。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.sdk.logging import logger

from .checks import parse_int
from .models import TmdbEpisodeRef, TmdbSeries

# 已完结剧集的季集结构基本不变，缓存更久；连载中的剧集每天刷新以发现新播出的集
ENDED_TTL_SECONDS = 30 * 86400
ONGOING_TTL_SECONDS = 86400
# 超过该时长未被访问的缓存条目在保存时清理
PRUNE_SECONDS = 60 * 86400
ENDED_STATUSES = {"ended", "canceled", "cancelled"}


class TmdbLookupError(Exception):
    """TMDB 查询失败；对应剧集应归入"无法核对"，而不是判定为缺集或完整。"""


def _as_dict(value: Any) -> dict:
    """把 TMDB 客户端返回的对象统一转换为字典。"""
    if isinstance(value, dict):
        return value
    try:
        return dict(value) if value else {}
    except (TypeError, ValueError):
        return {}


class TmdbSource:
    """按剧集 TMDB ID 读取季集结构。

    宿主 TmdbChain 的单集模型不含单集 ID，因此直接使用宿主 TMDB 客户端读取季详情，
    沿用 MoviePilot 已配置的 TMDB 密钥、代理与请求缓存。
    """

    def __init__(
        self,
        cache_file: Path,
        language: str = "zh-CN",
        api_factory: Optional[Callable[[], Any]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """加载持久缓存，TMDB 客户端在首次需要请求时才创建。"""
        self._cache_file = cache_file
        self._language = language
        self._api_factory = api_factory
        self._clock = clock
        self._api: Any = None
        self._dirty = False
        self.requests = 0
        self._cache: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        """读取缓存文件，文件损坏时丢弃并重新建立。"""
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as err:
            logger.warning(f"影视库完整性检查：TMDB 缓存无法读取，已重建：{err}")
            return {}

    def _client(self) -> Any:
        """返回 TMDB 客户端，首次调用时创建。"""
        if self._api is None:
            if self._api_factory is not None:
                self._api = self._api_factory()
            else:
                from app.modules.themoviedb.tmdbapi import TmdbApi

                self._api = TmdbApi(language=self._language)
        return self._api

    def _fresh(self, entry: dict) -> bool:
        """判断缓存条目是否仍在有效期内。"""
        fetched = float(entry.get("fetched_at") or 0)
        ttl = ENDED_TTL_SECONDS if str(entry.get("status") or "").lower() in ENDED_STATUSES else ONGOING_TTL_SECONDS
        return self._clock() - fetched < ttl

    @staticmethod
    def _build(tmdb_id: int, entry: dict) -> TmdbSeries:
        """把缓存条目转换为季集结构。"""
        series = TmdbSeries(tmdb_id=tmdb_id, name=str(entry.get("name") or ""), status=str(entry.get("status") or ""))
        for season_text, episodes in (entry.get("seasons") or {}).items():
            season = parse_int(season_text)
            if season is None:
                continue
            series.seasons[season] = [
                TmdbEpisodeRef(
                    tmdb_id=int(episode["id"]),
                    season=season,
                    episode=int(episode["episode"]),
                    air_date=str(episode.get("air_date") or ""),
                    name=str(episode.get("name") or ""),
                )
                for episode in episodes
            ]
        return series

    def _fetch(self, tmdb_id: int) -> dict:
        """请求剧集详情与各季详情，生成缓存条目。"""
        client = self._client()
        try:
            self.requests += 1
            details = _as_dict(client.tv.details(tmdb_id, append_to_response=""))
        except Exception as err:  # noqa: BLE001 - TMDB 客户端可能抛出多种网络与业务异常
            raise TmdbLookupError(str(err) or err.__class__.__name__) from err
        if not details.get("id"):
            raise TmdbLookupError("TMDB 未返回剧集信息")
        seasons: dict[str, list[dict]] = {}
        for season_info in details.get("seasons") or []:
            season = parse_int(_as_dict(season_info).get("season_number"))
            if season is None:
                continue
            try:
                self.requests += 1
                season_detail = _as_dict(client.season_obj.details(tmdb_id, season, append_to_response=""))
            except Exception as err:  # noqa: BLE001
                raise TmdbLookupError(f"第 {season} 季读取失败：{err}") from err
            if not season_detail:
                raise TmdbLookupError(f"第 {season} 季读取失败")
            episodes: list[dict] = []
            for raw in season_detail.get("episodes") or []:
                episode = _as_dict(raw)
                episode_id = parse_int(episode.get("id"))
                number = parse_int(episode.get("episode_number"))
                if episode_id is None or number is None:
                    continue
                episodes.append({
                    "id": episode_id,
                    "episode": number,
                    "air_date": str(episode.get("air_date") or ""),
                    "name": str(episode.get("name") or ""),
                })
            seasons[str(season)] = episodes
        return {
            "fetched_at": self._clock(),
            "status": str(details.get("status") or ""),
            "name": str(details.get("name") or ""),
            "seasons": seasons,
        }

    def get_series(self, tmdb_id: int) -> TmdbSeries:
        """返回剧集季集结构，优先使用有效缓存。"""
        key = str(tmdb_id)
        entry = self._cache.get(key)
        if not entry or not self._fresh(entry):
            entry = self._fetch(tmdb_id)
            self._cache[key] = entry
        entry["used_at"] = self._clock()
        self._dirty = True
        return self._build(tmdb_id, entry)

    def search_tv(self, title: str, year: str = "") -> list[dict]:
        """按标题（与年份）搜索剧集候选；带年份无结果时去掉年份再搜一次。"""
        if not title:
            return []
        client = self._client()
        try:
            self.requests += 1
            results = client.search_tvs(title, year) or []
            if not results and year:
                self.requests += 1
                results = client.search_tvs(title, "") or []
        except Exception as err:  # noqa: BLE001
            raise TmdbLookupError(str(err) or err.__class__.__name__) from err
        candidates: list[dict] = []
        for raw in results:
            record = _as_dict(raw)
            tmdb_id = parse_int(record.get("id"))
            if not tmdb_id:
                continue
            candidates.append({
                "id": tmdb_id,
                "name": str(record.get("name") or record.get("title") or ""),
                "original_name": str(record.get("original_name") or ""),
                "first_air_date": str(record.get("first_air_date") or ""),
                "overview": str(record.get("overview") or ""),
            })
        return candidates

    def save(self) -> None:
        """清理长期未使用的条目并写回缓存文件。"""
        if not self._dirty:
            return
        now = self._clock()
        self._cache = {
            key: entry for key, entry in self._cache.items()
            if now - float(entry.get("used_at") or entry.get("fetched_at") or 0) < PRUNE_SECONDS
        }
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._cache_file)
            self._dirty = False
        except OSError as err:
            logger.warning(f"影视库完整性检查：TMDB 缓存保存失败：{err}")

    def close(self) -> None:
        """释放 TMDB 客户端。"""
        if self._api is not None and hasattr(self._api, "close"):
            try:
                self._api.close()
            except Exception as err:  # noqa: BLE001
                logger.debug(f"影视库完整性检查：TMDB 客户端关闭失败：{err}")
        self._api = None
