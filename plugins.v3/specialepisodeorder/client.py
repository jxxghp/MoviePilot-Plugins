"""使用宿主网络与配置查询特典的跨来源身份和播放位置。"""

from threading import Event, RLock
from time import monotonic
from typing import Any

from app.sdk.cache import MemoryBackend
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils


METADATA_CACHE_KEY = "metadata_cache_v1"
TEMPORARY_CACHE_REGION = "specialepisodeorder.metadata.temporary"

# 短期复用空结果或不完整响应，避免同一轮扫描重复查询。
_temporary_cache = MemoryBackend(maxsize=32768, ttl=300)


class LookupFailure(Exception):
    """表示外部查询失败；消息仅含服务和状态，不携带凭据。"""


class TvdbEpisodeNotFound(LookupFailure):
    """TVDB 明确返回单集 404，应重新查询对应的自动映射。"""


class MetadataClient:
    """查询共享的元数据缓存，并在实例内管理 TVDB 登录。"""

    def __init__(self, load_data=None, save_data=None, *, stopped: Event | None = None, cache_lock=None) -> None:
        """注入 MP 插件存储和停止信号，首次查询时才读取缓存。"""
        self._lock = RLock()
        self._token = ""
        self._token_until = 0.0
        self._load_data = load_data
        self._save_data = save_data
        self._stopped = stopped if stopped is not None else Event()
        self._cache_lock = cache_lock if cache_lock is not None else RLock()
        self._records: dict[str, dict] | None = None
        self._dirty = False

    @property
    def configured(self) -> bool:
        """确认两个数据源均有访问密钥。"""
        return bool(settings.TMDB_API_KEY and settings.TVDB_V4_API_KEY)

    def _cached(self, key: str, fetch, complete) -> dict:
        """优先读取持久缓存，不完整响应和异常不写入插件存储。"""
        with self._cache_lock:
            if self._records is None:
                try:
                    stored = self._load_data(METADATA_CACHE_KEY) if self._load_data else None
                except Exception as error:
                    # 读取失败时仍可查询元数据，保护已有缓存免遭空快照覆盖。
                    logger.warning(f"特典播放顺序：读取元数据缓存失败（{type(error).__name__}）")
                    stored = None
                    self._save_data = None
                self._records = dict(stored) if isinstance(stored, dict) else {}
            cached = self._records.get(key)
            if isinstance(cached, dict) and complete(cached):
                return dict(cached)
            cached = _temporary_cache.get(key, region=TEMPORARY_CACHE_REGION)
            if cached is not None:
                return dict(cached)
        result = fetch()
        with self._cache_lock:
            if not self._stopped.is_set():
                if complete(result):
                    self._records[key] = dict(result)
                    self._dirty = True
                else:
                    _temporary_cache.set(key, dict(result), region=TEMPORARY_CACHE_REGION)
        return result

    def flush_cache(self) -> None:
        """查询结束后批量保存，已停用的客户端不再写入。"""
        with self._cache_lock:
            if not self._dirty or self._stopped.is_set() or self._save_data is None:
                return
            try:
                self._save_data(METADATA_CACHE_KEY, self._records)
            except Exception as error:
                logger.warning(f"特典播放顺序：保存元数据缓存失败（{type(error).__name__}）")
            else:
                self._dirty = False

    @staticmethod
    def clear_temporary_cache() -> None:
        """清除进程内的短期查询缓存。"""
        _temporary_cache.clear(region=TEMPORARY_CACHE_REGION)

    @staticmethod
    def _http(headers: dict | None = None) -> RequestUtils:
        """复用宿主代理和 UA，启用 TLS 校验并限制单次等待时间。"""
        return RequestUtils(
            headers=headers, ua=settings.NORMAL_USER_AGENT,
            proxies=settings.PROXY, timeout=10, verify=True, content_type="application/json",
        )

    @staticmethod
    def _json(response: Any, service: str) -> dict:
        """校验响应而不记录带密钥的 URL、响应正文或令牌。"""
        if response is None:
            raise LookupFailure(f"{service} 网络请求失败或超时")
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            raise LookupFailure(f"{service} HTTP {response.status_code}")
        try:
            result = response.json()
        except (ValueError, TypeError) as error:
            raise LookupFailure(f"{service} 返回无效 JSON") from error
        if not isinstance(result, dict):
            raise LookupFailure(f"{service} 返回格式不正确")
        return result

    @staticmethod
    def _tmdb_target(series_id: int, episode: int | None = None) -> tuple[str, str]:
        """构造查询和失效处理共用的 TMDb 缓存键与地址。"""
        domain = str(settings.TMDB_API_DOMAIN).removeprefix("https://").removeprefix("http://").rstrip("/")
        path = f"tv/{series_id}"
        if episode is not None:
            path += f"/season/0/episode/{episode}"
        path += "/external_ids"
        return f"tmdb:{domain}:{path}", f"https://{domain}/3/{path}"

    def _tmdb(self, series_id: int, episode: int | None = None) -> dict:
        """按 TMDb 域名和请求路径缓存外部 ID 查询。"""
        key, url = self._tmdb_target(series_id, episode)

        def fetch() -> dict:
            """只保存匹配单集和剧集所需的 ID。"""
            response = self._http().get_res(url, params={"api_key": settings.TMDB_API_KEY})
            data = self._json(response, "TMDb")
            return {key: data[key] for key in ("id", "tvdb_id") if data.get(key) is not None}

        def complete(data: dict) -> bool:
            """缺少 TVDB 映射或单集 ID 时仅短期缓存。"""
            keys = ("id", "tvdb_id") if episode is not None else ("tvdb_id",)
            return all(type(data.get(key)) is int and data[key] > 0 for key in keys)

        return self._cached(key, fetch, complete)

    def episode_ids(self, series_id: int, episode: int) -> dict:
        """查询 TMDb 默认 Season 0 单集身份及外部映射。"""
        return self._tmdb(series_id, episode)

    def invalidate_episode_mapping(self, series_id: int, episode: int, ids: dict) -> None:
        """仅淘汰这次请求使用的失效映射，保护并发更新的新值。"""
        key, _ = self._tmdb_target(series_id, episode)
        with self._cache_lock:
            if self._stopped.is_set():
                return
            if self._records is not None and self._records.get(key) == ids:
                del self._records[key]
                self._dirty = True
            if _temporary_cache.get(key, region=TEMPORARY_CACHE_REGION) == ids:
                _temporary_cache.delete(key, region=TEMPORARY_CACHE_REGION)

    def series_ids(self, series_id: int) -> dict:
        """查询 TVDB 剧集 ID，用于阻止跨剧误配。"""
        return self._tmdb(series_id)

    def _login(self) -> str:
        """创建 TVDB 会话；锁内再次检查，避免并发重复登录。"""
        with self._lock:
            if self._token and self._token_until > monotonic():
                return self._token
            payload = {"apikey": settings.TVDB_V4_API_KEY}
            if settings.TVDB_V4_API_PIN:
                payload["pin"] = settings.TVDB_V4_API_PIN
            response = self._http().post_res("https://api4.thetvdb.com/v4/login", json=payload)
            data = self._json(response, "TVDB 登录").get("data")
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise LookupFailure("TVDB 登录未返回有效令牌")
            self._token, self._token_until = token, monotonic() + 6 * 3600
            return token

    def episode(self, episode_id: int) -> dict:
        """获取 TVDB 单集扩展信息；401 时最多重新登录一次。"""
        position_fields = ("airsAfterSeason", "airsBeforeSeason", "airsBeforeEpisode")

        def fetch() -> dict:
            """按明确单集 ID 查询，404 直接抛出以跳过缓存。"""
            for attempt in range(2):
                token = self._login()
                response = self._http({"Authorization": f"Bearer {token}"}).get_res(
                    f"https://api4.thetvdb.com/v4/episodes/{episode_id}/extended",
                )
                if response is not None and response.status_code == 401 and attempt == 0:
                    with self._lock:
                        if self._token == token:
                            self._token, self._token_until = "", 0
                    continue
                if response is not None and response.status_code == 404:
                    raise TvdbEpisodeNotFound("TVDB 单集不存在（404）")
                data = self._json(response, "TVDB 单集").get("data", {})
                if not isinstance(data, dict):
                    raise LookupFailure("TVDB 单集返回格式不正确")
                fields = ("id", "seriesId", *position_fields)
                return {key: data[key] for key in fields if key in data}
            return {}

        def complete(data: dict) -> bool:
            """只持久化身份完整且有有效播放位置的结果。"""
            return (
                type(data.get("id")) is int and data["id"] == episode_id
                and type(data.get("seriesId")) is int and data["seriesId"] > 0
                and any(type(data.get(key)) is int and data[key] >= 0 for key in position_fields)
            )

        return self._cached(f"tvdb:{episode_id}", fetch, complete)
