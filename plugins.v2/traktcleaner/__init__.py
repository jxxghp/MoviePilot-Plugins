import re
import time
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.metainfo import MetaInfo
from app.helper.torrent import TorrentHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType, TorrentStatus


class TraktCleaner(_PluginBase):
    # 插件名称
    plugin_name = "Trakt 观看清理"
    # 插件描述
    plugin_desc = "根据 Trakt 播放记录，自动清理下载器中已观看的种子。"
    # 插件图标
    plugin_icon = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/trakt.png"
    # 插件版本
    plugin_version = "1.4"
    # 插件作者
    plugin_author = "Guoyin-Wen"
    author_url = "https://github.com/Guoyin-Wen"
    # 插件配置项ID前缀
    plugin_config_prefix = "traktcleaner_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _cron = None
    _onlyonce = False
    _notify = True
    _delete_file = True
    _dry_run = False
    _client_id = None
    _client_secret = None
    _pin = None
    _access_token = None
    _refresh_token = None
    _clean_movie = True
    _clean_episode = True
    _exclude_tags = ""
    # 首次发现观看后延迟清理的天数，0 表示即时清理（保持原行为）
    _delay_days = 0

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # Token 状态标记
    _token_error = False

    # Trakt API 基础 URL
    _TRAKT_API_BASE = "https://api.trakt.tv"
    _TRAKT_TOKEN_URL = "https://api.trakt.tv/oauth/token"
    _TRAKT_AUTHORIZE_URL = "https://trakt.tv/oauth/authorize"
    _TRAKT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

    def __get_all_config(self) -> dict:
        """获取完整配置字典"""
        return {
            "enabled": self._enabled,
            "cron": self._cron,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "delete_file": self._delete_file,
            "dry_run": self._dry_run,
            "client_id": self._client_id or "",
            "client_secret": self._client_secret or "",
            "pin": "",
            "access_token": self._access_token or "",
            "refresh_token": self._refresh_token or "",
            "clean_movie": self._clean_movie,
            "clean_episode": self._clean_episode,
            "exclude_tags": self._exclude_tags or "",
            "delay_days": self._delay_days,
        }

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify", True)
            self._delete_file = config.get("delete_file", True)
            self._dry_run = config.get("dry_run", False)
            self._client_id = config.get("client_id")
            self._client_secret = config.get("client_secret")
            self._access_token = config.get("access_token")
            self._refresh_token = config.get("refresh_token")
            self._clean_movie = config.get("clean_movie", True)
            self._clean_episode = config.get("clean_episode", True)
            self._exclude_tags = config.get("exclude_tags", "")
            self._delay_days = int(config.get("delay_days", 0) or 0)

            # 如果用户填写了 PIN，自动换取 Token
            pin = config.get("pin", "").strip()
            if pin and self._client_id and self._client_secret:
                logger.info("Trakt 观看清理：检测到 PIN 码，正在换取 Token...")
                if self.__exchange_pin(pin):
                    logger.info("Trakt 观看清理：PIN 换取 Token 成功")
                else:
                    logger.error("Trakt 观看清理：PIN 换取 Token 失败，请检查 PIN 是否正确或已过期")

        # 加载任务
        if self._enabled:
            # 刷新 Token（仅在有 refresh_token 时，且距上次刷新超过 12 小时）
            if self._refresh_token and self._client_id and self._client_secret:
                last_refresh = self.get_data("last_token_refresh") or 0
                if time.time() - last_refresh > 43200:  # 12 小时
                    ok = self.__refresh_token()
                    if not ok:
                        # refresh 失败但 access_token 可能仍有效，不标记为 token_error
                        logger.warning("Trakt 观看清理：Token 刷新失败，将在执行时验证 access_token 是否有效")
                    else:
                        self._token_error = False
            elif not self._access_token:
                self._token_error = True

            # 处理 onlyonce：启动后台线程执行清理
            logger.info(f"Trakt 观看清理：检查 onlyonce={self._onlyonce}, enabled={self._enabled}")
            if self._onlyonce:
                import threading
                logger.info("Trakt 观看清理：立即运行一次（后台线程）")
                thread = threading.Thread(target=self.__run_once, name="TraktCleaner_Once", daemon=True)
                thread.start()
                logger.info(f"Trakt 观看清理：后台线程已启动, alive={thread.is_alive()}")
                self._onlyonce = False

    def __run_once(self):
        """后台线程执行一次清理，完成后关闭 onlyonce 开关"""
        try:
            self.__clean()
        except Exception as e:
            logger.error(f"Trakt 观看清理：立即执行异常: {e}")
        finally:
            # 清理完成后保存配置
            try:
                config = self.get_config() or {}
                config["onlyonce"] = False
                self.update_config(config)
            except Exception:
                pass

    def __exchange_pin(self, pin: str) -> bool:
        """用 PIN 码换取 Access Token 和 Refresh Token"""
        try:
            resp = requests.post(
                self._TRAKT_TOKEN_URL,
                json={
                    "code": pin,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": self._TRAKT_REDIRECT_URI,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._token_error = False
                # 持久化
                self.update_config(self.__get_all_config())
                self.save_data("last_token_refresh", time.time())
                return True
            else:
                logger.error(f"Trakt 观看清理：PIN 换取 Token 失败，状态码 {resp.status_code}，响应: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Trakt 观看清理：PIN 换取 Token 异常: {e}")
            return False

    def __get_trakt_headers(self) -> dict:
        """构造 Trakt API 请求头"""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "trakt-api-version": "2",
            "trakt-api-key": self._client_id,
            "Content-Type": "application/json",
        }

    def __refresh_token(self) -> bool:
        """刷新 Trakt access_token"""
        if not self._refresh_token or not self._client_id or not self._client_secret:
            logger.warning("Trakt 观看清理：缺少凭据，跳过 Token 刷新")
            return False

        try:
            resp = requests.post(
                self._TRAKT_TOKEN_URL,
                json={
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._access_token = data.get("access_token", self._access_token)
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                # 持久化新 token
                self.update_config(self.__get_all_config())
                self.save_data("last_token_refresh", time.time())
                logger.info("Trakt 观看清理：Token 刷新成功")
                return True
            else:
                logger.error(f"Trakt 观看清理：Token 刷新失败，状态码 {resp.status_code}，响应: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Trakt 观看清理：Token 刷新异常: {e}")
            return False

    def __fetch_watched_movies(self) -> List[dict]:
        """获取 Trakt 已观看电影列表（分页）"""
        result = []
        page = 1
        limit = 250
        while True:
            try:
                resp = requests.get(
                    f"{self._TRAKT_API_BASE}/sync/watched/movies",
                    headers=self.__get_trakt_headers(),
                    params={"page": page, "limit": limit},
                    timeout=30,
                )
                if resp.status_code == 401:
                    if self.__refresh_token():
                        continue
                    self._token_error = True
                    break
                if resp.status_code != 200:
                    logger.error(f"Trakt 观看清理：获取电影观看记录失败 {resp.status_code}")
                    break
                data = resp.json()
                if not data:
                    break
                result.extend(data)
                # 检查是否还有下一页
                page_count = int(resp.headers.get("X-Pagination-Page-Count", 1))
                if page >= page_count:
                    break
                page += 1
            except Exception as e:
                logger.error(f"Trakt 观看清理：获取电影观看记录异常: {e}")
                break
        logger.info(f"Trakt 观看清理：获取到 {len(result)} 部已观看电影")
        return result

    def __fetch_watched_shows(self) -> List[dict]:
        """获取 Trakt 已观看剧集列表（分页）"""
        result = []
        page = 1
        limit = 250
        while True:
            try:
                resp = requests.get(
                    f"{self._TRAKT_API_BASE}/sync/watched/shows",
                    headers=self.__get_trakt_headers(),
                    params={"page": page, "limit": limit},
                    timeout=30,
                )
                if resp.status_code == 401:
                    if self.__refresh_token():
                        continue
                    self._token_error = True
                    break
                if resp.status_code != 200:
                    logger.error(f"Trakt 观看清理：获取剧集观看记录失败 {resp.status_code}")
                    break
                data = resp.json()
                if not data:
                    break
                result.extend(data)
                page_count = int(resp.headers.get("X-Pagination-Page-Count", 1))
                if page >= page_count:
                    break
                page += 1
            except Exception as e:
                logger.error(f"Trakt 观看清理：获取剧集观看记录异常: {e}")
                break
        logger.info(f"Trakt 观看清理：获取到 {len(result)} 部已观看剧集")
        return result

    def __fetch_show_progress(self, trakt_id) -> Dict[str, List[int]]:
        """
        获取某部剧的已观看进度：{季号(str): [集号列表]}
        用于 /sync/watched/shows 未返回 seasons 明细时的回退（权威数据源）。
        """
        if not trakt_id:
            return {}
        for attempt in range(2):
            try:
                resp = requests.get(
                    f"{self._TRAKT_API_BASE}/shows/{trakt_id}/progress/watched",
                    headers=self.__get_trakt_headers(),
                    params={"hidden": "false", "specials": "false"},
                    timeout=30,
                )
                if resp.status_code == 401 and attempt == 0:
                    if self.__refresh_token():
                        continue
                    self._token_error = True
                    return {}
                if resp.status_code != 200:
                    logger.error(f"Trakt 观看清理：获取剧集进度失败 {trakt_id} {resp.status_code}")
                    return {}
                data = resp.json()
                watched_seasons = {}
                for season in data.get("seasons", []):
                    sn = season.get("number", 0)
                    # progress/watched 的 episodes 数组包含全部已播出集，
                    # 只有 last_watched_at 非空的才是真正看过的（对应顶层 completed 计数）
                    eps = [
                        e.get("number", 0)
                        for e in season.get("episodes", [])
                        if e.get("last_watched_at")
                    ]
                    if eps:
                        watched_seasons[str(sn)] = eps
                return watched_seasons
            except Exception as e:
                logger.error(f"Trakt 观看清理：获取剧集进度异常 {trakt_id}: {e}")
                return {}
        return {}

    def __normalize_title(self, title: str) -> str:
        """标准化标题用于匹配（保留兼容，用于 Trakt 侧标题）"""
        if not title:
            return ""
        title = title.lower()
        title = re.sub(r"[\.\-_]", " ", title)
        title = re.sub(r"\(?\d{4}\)?", "", title)
        title = re.sub(r"(2160p|1080p|720p|480p|4k|uhd|bluray|web-?dl|webrip|hdtv|dvdrip|brrip|remux|hdr|hevc|x264|x265|h264|h265|aac|dts|atmos|10bit|6ch|multi|dual|dubbed|subbed)", "", title, flags=re.IGNORECASE)
        title = re.sub(r"[\[\(].*?[\]\)]", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def __build_watched_set(self) -> Dict[str, dict]:
        """
        构建已观看媒体集合
        返回: {标准化标题: {type, title, year, reset_at, ...}}
        """
        watched = {}

        # 电影
        if self._clean_movie:
            movies = self.__fetch_watched_movies()
            for item in movies:
                movie = item.get("movie", {})
                title = movie.get("title", "")
                year = movie.get("year")
                ids = movie.get("ids", {})
                # 用年份作为后缀，避免同名不同年份的媒体互相覆盖
                norm = self.__normalize_title(title)
                key = f"{norm}|{year}" if year else norm
                if key:
                    watched[key] = {
                        "type": "movie",
                        "title": title,
                        "year": str(year) if year else None,
                        "trakt_id": ids.get("trakt"),
                        "tmdb_id": ids.get("tmdb"),
                        "last_watched_at": item.get("last_watched_at"),
                        "plays": item.get("plays", 0),
                    }

        # 剧集
        if self._clean_episode:
            shows = self.__fetch_watched_shows()
            for item in shows:
                show = item.get("show", {})
                title = show.get("title", "")
                year = show.get("year")
                ids = show.get("ids", {})
                # 用年份作为后缀，避免同名不同年份的剧集互相覆盖
                norm = self.__normalize_title(title)
                key = f"{norm}|{year}" if year else norm
                # 解析已观看的季集信息
                watched_seasons = {}
                for season in item.get("seasons", []):
                    sn = season.get("number", 0)
                    eps = [e.get("number", 0) for e in season.get("episodes", [])]
                    watched_seasons[str(sn)] = eps
                # 部分账户的 /sync/watched/shows 不返回 seasons 明细，
                # 回退到 /shows/{id}/progress/watched 获取权威的已看季集
                if not watched_seasons and ids.get("trakt"):
                    watched_seasons = self.__fetch_show_progress(ids.get("trakt"))
                if key:
                    watched[key] = {
                        "type": "show",
                        "title": title,
                        "year": str(year) if year else None,
                        "trakt_id": ids.get("trakt"),
                        "tmdb_id": ids.get("tmdb"),
                        "last_watched_at": item.get("last_watched_at"),
                        "plays": item.get("plays", 0),
                        "reset_at": item.get("reset_at"),
                        "watched_seasons": watched_seasons,
                    }

        logger.info(f"Trakt 观看清理：构建已观看集合共 {len(watched)} 条记录")
        return watched

    @staticmethod
    def __format_season_episode_int(season: Optional[int], episodes: Optional[List[int]]) -> str:
        """格式化季集显示文本（int 版本）"""
        if season is None:
            return ""
        season_text = f"S{season:02d}"
        if not episodes:
            return f"{season_text}整季"
        sorted_eps = sorted(episodes)
        if len(sorted_eps) <= 3:
            ep_text = "E".join(f"E{e:02d}" for e in sorted_eps)
            return f"{season_text}{ep_text}"
        return f"{season_text}E{sorted_eps[0]:02d}-E{sorted_eps[-1]:02d}"

    @staticmethod
    def __merge_episode_ranges(episodes: List[int]) -> str:
        """将集数列表合并为区间格式，例如 [1,2,3,5,6,10] -> E01-03E05-06E10"""
        if not episodes:
            return ""
        sorted_eps = sorted(set(episodes))
        ranges = []
        start = sorted_eps[0]
        prev = sorted_eps[0]
        for ep in sorted_eps[1:]:
            if ep == prev + 1:
                prev = ep
            else:
                if start == prev:
                    ranges.append(f"E{start:02d}")
                else:
                    ranges.append(f"E{start:02d}-{prev:02d}")
                start = ep
                prev = ep
        # 处理最后一个区间
        if start == prev:
            ranges.append(f"E{start:02d}")
        else:
            ranges.append(f"E{start:02d}-{prev:02d}")
        return "".join(ranges)

    def __match_torrent(self, torrent_title: str, watched: Dict[str, dict]) -> Optional[dict]:
        """
        用 MetaInfo 识别种子标题中的剧名，匹配已观看记录
        """
        if not torrent_title:
            return None
        meta = MetaInfo(torrent_title)
        # 收集所有可能的名称
        names = set()
        for name in [meta.cn_name, meta.en_name, meta.name]:
            if name:
                names.add(self.__normalize_title(name))
        # 去掉年份等干扰后的原标题
        raw_normalized = self.__normalize_title(torrent_title)
        if raw_normalized:
            names.add(raw_normalized)

        torrent_year = ""
        meta_year = getattr(meta, "year", None)
        if meta_year:
            torrent_year = str(meta_year)

        # 1) 优先精确匹配（带年份，避免同名不同年份的剧互相错配）
        if torrent_year:
            for name in names:
                k = f"{name}|{torrent_year}"
                if k in watched:
                    return watched[k]
        # 2) 不带年份的精确匹配
        for name in names:
            if name in watched:
                return watched[name]

        # 3) 子串匹配（兜底，比较时剥去年份后缀）
        for name in names:
            for key, info in watched.items():
                bare = key.split("|", 1)[0]
                if not bare:
                    continue
                if bare in name or name in bare:
                    return info

        return None

    def __get_torrent_episodes(
        self, torrent_hash: str, default_season: Optional[int] = None
    ) -> Tuple[Dict[int, List[int]], int, int]:
        """
        获取种子内的实际文件列表，用 MetaInfo 提取季集信息
        返回: (季号->集号列表, 视频文件总数, 成功解析出集数的文件数)
        default_season: 当文件名识别不出季号时（如整季包文件名不带 Sxx）回退使用的季号，
                        通常取自种子标题（torrent_meta.begin_season）。
        """
        result: Dict[int, List[int]] = {}
        total_video_files = 0
        parsed_files = 0
        try:
            files = self.chain.torrent_files(tid=torrent_hash)
            if not files:
                return result, 0, 0
            for f in files:
                name = ""
                if hasattr(f, "name"):
                    name = f.name
                elif isinstance(f, dict):
                    name = f.get("name", "")
                if not name:
                    continue
                # 只看视频文件（用 MP 内置的媒体扩展名列表）
                file_path = Path(name)
                if not file_path.suffix or file_path.suffix.lower() not in settings.RMT_MEDIAEXT:
                    continue
                total_video_files += 1
                # 用 MetaInfo 识别文件名中的季集
                meta = MetaInfo(file_path.name)
                if meta.begin_episode is None:
                    # 没有集号信息，无法判断，跳过该文件
                    continue
                # 季号识别失败时，回退到默认季号（通常取自种子标题）
                season = meta.begin_season
                if season is None:
                    season = default_season
                if season is None:
                    continue
                parsed_files += 1
                if season not in result:
                    result[season] = []
                result[season].extend(meta.episode_list or [])
        except Exception as e:
            logger.debug(f"Trakt 观看清理：获取种子文件列表失败 {torrent_hash}: {e}")
        # 去重
        for s in result:
            result[s] = list(set(result[s]))
        return result, total_video_files, parsed_files

    def __should_clean_torrent(
        self, matched: dict, torrent_hash: str, default_season: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        判断是否应该清理该种子
        返回: (是否应清理, 原因描述)
        采用 fail-safe 原则：信息不足时返回 False（跳过），避免误删未看剧集。
        """
        matched_type = matched.get("type", "")

        # 电影：只要匹配到已观看就清理（Trakt watched 即唯一事实来源）
        if matched_type == "movie":
            return True, "已观看电影"

        # 剧集：需要判断集数
        watched_seasons = matched.get("watched_seasons", {})
        if not watched_seasons:
            # 没有 seasons 数据，无法确认集数，跳过避免误删
            return False, "已观看剧集（Trakt 无集数详情，跳过）"

        # 获取种子内实际文件对应的集数
        torrent_eps, total_video_files, parsed_files = self.__get_torrent_episodes(
            torrent_hash, default_season
        )
        if not torrent_eps:
            # 无法解析出任何集数，跳过避免误删
            return False, "已观看剧集（无法解析种子集数，跳过）"

        # 完整性校验：若成功解析的文件数少于实际视频文件数，说明有文件未识别出季集
        # （这些文件很可能还没看），删除整颗种子会误删它们，故跳过。
        if total_video_files > 0 and parsed_files < total_video_files:
            return False, (
                f"已观看剧集（集数解析不完整 {parsed_files}/{total_video_files}，跳过避免误删）"
            )

        # 对比每一季
        all_watched = True
        detail_parts = []
        for season, episodes in torrent_eps.items():
            watched_eps = watched_seasons.get(str(season), [])
            if not watched_eps:
                all_watched = False
                detail_parts.append(f"S{season:02d}未观看")
                continue
            # 检查种子中每一集是否都已观看（都是 int 对比）
            watched_eps_int = [int(we) for we in watched_eps]
            unwatched = [ep for ep in episodes if ep not in watched_eps_int]
            if unwatched:
                all_watched = False
                unwatched_sorted = sorted(unwatched)
                detail_parts.append(f"S{season:02d}E{unwatched_sorted[0]:02d}等{len(unwatched)}集未看")
            else:
                detail_parts.append(f"S{season:02d}全部{len(episodes)}集已看")

        if all_watched:
            return True, "、".join(detail_parts)
        else:
            return False, "、".join(detail_parts)

    def __format_watched_summary(self, watched: Dict[str, dict]) -> str:
        """格式化 Trakt 观看数据摘要，用于日志和通知"""
        parts = []
        for key, info in watched.items():
            title = info.get("title", key)
            mtype = info.get("type", "")
            if mtype == "movie":
                parts.append(f"🎞️ {title}")
            else:
                watched_seasons = info.get("watched_seasons", {})
                if watched_seasons:
                    season_parts = []
                    for sn, eps in sorted(watched_seasons.items(), key=lambda x: int(x[0])):
                        merged = self.__merge_episode_ranges(eps)
                        season_parts.append(f"S{int(sn):02d}{merged}")
                    parts.append(f"📺 {title}: {' '.join(season_parts)}")
                else:
                    parts.append(f"📺 {title}")
        return "；".join(parts)

    def __clean(self):
        """定时任务：获取 Trakt 观看记录 → 匹配种子 → 清理"""
        if not self._access_token or not self._client_id:
            logger.warning("Trakt 观看清理：缺少 Trakt 凭据，跳过执行")
            return

        logger.info("Trakt 观看清理：开始执行清理任务")

        # 1. 刷新 Token
        self.__refresh_token()

        # 2. 获取 Trakt 观看记录
        watched = self.__build_watched_set()
        if not watched:
            logger.info("Trakt 观看清理：无观看记录，跳过清理")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="Trakt 观看清理",
                    text="Trakt 账户无观看记录，跳过清理。",
                )
            return

        # 日志记录从 Trakt 获取到的观看详情
        watched_summary = self.__format_watched_summary(watched)
        logger.info(f"Trakt 观看清理：Trakt 观看数据 → {watched_summary}")

        # 3. 获取下载器中的种子
        try:
            completed_torrents = self.chain.list_torrents(status=TorrentStatus.TRANSFER)
            downloading_torrents = self.chain.list_torrents(status=TorrentStatus.DOWNLOADING)
        except Exception as e:
            logger.error(f"Trakt 观看清理：获取种子列表失败: {e}")
            return

        all_torrents = []
        if completed_torrents:
            all_torrents.extend(completed_torrents)
        if downloading_torrents:
            all_torrents.extend(downloading_torrents)

        if not all_torrents:
            logger.info("Trakt 观看清理：下载器中无种子")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="Trakt 观看清理",
                    text=f"Trakt 观看 {len(watched)} 条记录，下载器中无种子。\n\n观看: {watched_summary}",
                )
            return

        logger.info(f"Trakt 观看清理：下载器中共 {len(all_torrents)} 个种子")

        # 4. 匹配并清理
        cleaned = []
        skipped = []
        excluded = []
        discovered = []   # 延期模式：本次首次发现入队的种子
        waiting = []      # 延期模式：本次仍处于等待中的种子
        # 解析排除标签
        exclude_tags = set()
        if self._exclude_tags:
            exclude_tags = {t.strip() for t in self._exclude_tags.replace("，", ",").split(",") if t.strip()}
            if exclude_tags:
                logger.info(f"Trakt 观看清理：排除标签: {exclude_tags}")

        # 延期模式：加载待清理队列（pending: {hash: item}）
        delayed = self._delay_days > 0
        delay_seconds = self._delay_days * 86400
        now = time.time()
        pending: Dict[str, dict] = {}
        if delayed:
            pending = self.get_data("pending") or {}
            if not isinstance(pending, dict):
                pending = {}
            logger.info(
                f"Trakt 观看清理：延期模式，延迟 {self._delay_days} 天，"
                f"待清理队列 {len(pending)} 个"
            )
        # 本次扫描中"仍满足清理条件"的种子 hash，用于复核 pending 队列
        cleanable_hashes = set()

        for torrent in all_torrents:
            # 检查排除标签
            if exclude_tags and torrent.tags:
                torrent_tags = {t.strip() for t in torrent.tags.split(",") if t.strip()}
                matched_exclude = torrent_tags & exclude_tags
                if matched_exclude:
                    logger.debug(
                        f"Trakt 观看清理：跳过种子 {torrent.title}（包含排除标签: {matched_exclude}）"
                    )
                    # 用 MetaInfo 提取识别名
                    ex_meta = MetaInfo(torrent.title or "")
                    ex_display = ex_meta.cn_name or ex_meta.en_name or ex_meta.name or torrent.title
                    excluded.append({
                        "title": torrent.title,
                        "matched_title": ex_display,
                        "tags": ",".join(matched_exclude),
                        "excluded": True,
                        "clean_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "dry_run": self._dry_run,
                    })
                    continue

            matched = self.__match_torrent(torrent.title, watched)
            if not matched:
                continue

            # 提取种子的季集信息（用 MetaInfo 识别，用于展示）
            torrent_meta = MetaInfo(torrent.title or "")
            torrent_season = torrent_meta.begin_season
            torrent_episodes = torrent_meta.episode_list if torrent_meta.episode_list else None
            season_ep_text = self.__format_season_episode_int(torrent_season, torrent_episodes)

            # 判断是否应清理（基于文件级集数判断，传入默认季号用于回退）
            should_clean, reason = self.__should_clean_torrent(
                matched, torrent.hash, torrent_meta.begin_season
            )

            # 获取种子内实际文件的集数信息（用于展示）
            torrent_file_eps, _, _ = self.__get_torrent_episodes(
                torrent.hash, torrent_meta.begin_season
            )
            file_eps_text = ""
            if torrent_file_eps:
                parts = []
                for s, eps in torrent_file_eps.items():
                    if len(eps) <= 3:
                        parts.append(f"S{s:02d}E{'E'.join(f'{e:02d}' for e in sorted(eps))}")
                    else:
                        parts.append(f"S{s:02d}E{sorted(eps)[0]:02d}-E{sorted(eps)[-1]:02d}({len(eps)}集)")
                file_eps_text = "、".join(parts)

            # 构建 Trakt 侧已观看的集数文本（全部，用于日志）
            watched_seasons = matched.get("watched_seasons", {})
            watched_eps_text = ""
            if watched_seasons:
                wp = []
                for sn, eps in sorted(watched_seasons.items(), key=lambda x: int(x[0])):
                    merged = self.__merge_episode_ranges(eps)
                    wp.append(f"S{int(sn):02d}{merged}")
                watched_eps_text = " ".join(wp)

            # 计算跟种子文件匹配的已看集数（交集）
            matched_watched_text = ""
            if torrent_file_eps and watched_seasons:
                mp = []
                for s, eps in torrent_file_eps.items():
                    w_eps = [int(e) for e in watched_seasons.get(str(s), [])]
                    intersection = sorted(set(eps) & set(w_eps))
                    if intersection:
                        ep_text = ",".join(f"E{e:02d}" for e in intersection)
                        mp.append(f"S{s:02d}{ep_text}")
                matched_watched_text = " ".join(mp)
            elif matched.get("type") == "movie":
                matched_watched_text = "已看"

            # 为通知构建单括号格式：逐集标记已看粗体
            notify_eps_text = ""
            if torrent_file_eps and watched_seasons:
                np_parts = []
                for s, eps in torrent_file_eps.items():
                    w_eps = [int(e) for e in watched_seasons.get(str(s), [])]
                    ep_tags = []
                    for e in sorted(eps):
                        tag = f"**E{e:02d}**" if e in w_eps else f"E{e:02d}"
                        ep_tags.append(tag)
                    np_parts.append(f"S{s:02d}{''.join(ep_tags)}")
                notify_eps_text = " ".join(np_parts)
            elif matched.get("type") == "movie":
                notify_eps_text = "**已看**"

            # 构建逐集标记列表（用于数据页：已看绿色、未看灰色）
            ep_details = []
            if torrent_file_eps and watched_seasons:
                for s, eps in torrent_file_eps.items():
                    w_eps = set(int(e) for e in watched_seasons.get(str(s), []))
                    for e in sorted(eps):
                        ep_details.append({"season": s, "episode": e, "watched": e in w_eps})
            elif matched.get("type") == "movie":
                ep_details.append({"watched": True})

            torrent_info = {
                "title": torrent.title,
                "hash": torrent.hash,
                "matched_type": matched.get("type"),
                "matched_title": matched.get("title"),
                "matched_year": matched.get("year"),
                "season": torrent_season,
                "episodes": torrent_episodes,
                "season_ep_text": season_ep_text,
                "file_eps_text": file_eps_text,
                "watched_eps_text": watched_eps_text,
                "matched_watched_text": matched_watched_text,
                "notify_eps_text": notify_eps_text,
                "ep_details": ep_details,
                "reason": reason,
                "clean_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "dry_run": self._dry_run,
            }

            if not should_clean:
                logger.info(
                    f"Trakt 观看清理：跳过 {matched.get('title')} "
                    f"({season_ep_text}) 种子集数: {file_eps_text or '未知'}, "
                    f"Trakt已看: {watched_eps_text or '未知'}, 原因: {reason}"
                )
                torrent_info["skipped"] = True
                skipped.append(torrent_info)
                continue

            # 满足清理条件
            cleanable_hashes.add(torrent.hash)

            if delayed:
                # 延期模式：进入待清理队列，到期后自动清理
                item = pending.get(torrent.hash)
                if item is None:
                    # 首次发现 → 入队
                    pending[torrent.hash] = self.__build_pending_item(torrent_info, now)
                    logger.info(
                        f"Trakt 观看清理：发现待清理 {matched.get('title')} "
                        f"({season_ep_text})，进入待清理队列，将于 {self._delay_days} 天后清理"
                    )
                    discovered.append(torrent_info)
                elif self._dry_run:
                    logger.info(
                        f"Trakt 观看清理（试运行）：待清理 {matched.get('title')} "
                        f"({season_ep_text}) [{reason}] → 种子 {torrent.title}"
                    )
                    waiting.append(torrent_info)
                elif (now - item.get("first_seen", now)) >= delay_seconds:
                    # 到期，执行清理
                    self.__remove_torrent(torrent, torrent_info, matched, season_ep_text, reason)
                    if torrent.hash in pending:
                        del pending[torrent.hash]
                    cleaned.append(torrent_info)
                else:
                    # 未到期，继续等待
                    waiting.append(torrent_info)
            else:
                # 即时模式（原行为）
                if self._dry_run:
                    logger.info(
                        f"Trakt 观看清理（试运行）：匹配到 {matched.get('title')} "
                        f"({season_ep_text}) [{reason}] → 种子 {torrent.title}"
                    )
                else:
                    self.__remove_torrent(torrent, torrent_info, matched, season_ep_text, reason)
                cleaned.append(torrent_info)

        # 延期模式：复核待清理队列，移除失效条目
        # （种子已消失 / Trakt 观看已取消 / 不再满足清理条件 / 被排除标签命中）
        # 失效后下次扫描若再次满足条件，会重新入列重新计时。
        if delayed:
            stale = [h for h in pending if h not in cleanable_hashes]
            for h in stale:
                del pending[h]
            if stale:
                logger.info(f"Trakt 观看清理：待清理队列移除 {len(stale)} 个失效条目")
            self.save_data("pending", pending)

        # 5. 保存清理历史（含跳过的、排除的；延期模式的 discovered/waiting 保留在待清理队列，不入历史）
        all_records = cleaned + skipped + excluded
        if all_records:
            history = self.get_data("history") or []
            history.extend(all_records)
            history = history[-1000:]
            self.save_data("history", history)

        # 6. 发送通知
        if self._notify:
            dry_tag = "（试运行）" if self._dry_run else ""
            mode_tag = "（延期）" if delayed else ""
            msg_lines = [f"### Trakt 观看清理{dry_tag}{mode_tag}"]

            # 统计信息
            stats = f"📊 观看记录 {len(watched)} 条 · 下载器 {len(all_torrents)} 个种子"
            if delayed:
                stats += (
                    f" · 到期清理 {len(cleaned)} · 新发现 {len(discovered)}"
                    f" · 等待中 {len(waiting)} · 跳过 {len(skipped)}"
                )
            else:
                stats += f" · 清理 {len(cleaned)} · 跳过 {len(skipped)}"
            if excluded:
                stats += f" · 排除 {len(excluded)}"
            msg_lines.append(stats)
            msg_lines.append("")

            # Trakt 观看记录明细（独立展示）
            msg_lines.append("**Trakt 观看记录：**")
            for key, info in watched.items():
                title = info.get("title", key)
                mtype = info.get("type", "")
                watched_seasons = info.get("watched_seasons", {})
                if mtype == "movie":
                    msg_lines.append(f"- 🎞️ **{title}**")
                else:
                    if watched_seasons:
                        season_parts = []
                        for sn, eps in sorted(watched_seasons.items(), key=lambda x: int(x[0])):
                            ep_list = " ".join(f"E{e:02d}" for e in sorted(eps))
                            season_parts.append(f"**S{int(sn):02d} {ep_list}**")
                        msg_lines.append(f"- 📺 {title} {' '.join(season_parts)}")
                    else:
                        msg_lines.append(f"- 📺 **{title}**")
            msg_lines.append("")

            # 种子明细
            cleaned_title = "✅ 待清理（试运行）" if self._dry_run else "✅ 已清理"
            if cleaned:
                msg_lines.append(f"**{cleaned_title} ({len(cleaned)} 个)：**")
                for item in cleaned:
                    title_display = item.get("matched_title", "")
                    notify_eps = item.get("notify_eps_text", "")
                    line = f"- {title_display} [{notify_eps}]" if notify_eps else f"- {title_display}"
                    if item.get("error"):
                        line += f" ❌ {item.get('error')}"
                    msg_lines.append(line)

            if discovered:
                msg_lines.append(f"\n**🆕 新发现入队 ({len(discovered)} 个)：**")
                for item in discovered:
                    title_display = item.get("matched_title", "")
                    notify_eps = item.get("notify_eps_text", "")
                    line = f"- {title_display} [{notify_eps}]" if notify_eps else f"- {title_display}"
                    msg_lines.append(line)

            if waiting:
                msg_lines.append(f"\n**⏳ 等待中 ({len(waiting)} 个)：**")
                for item in waiting:
                    title_display = item.get("matched_title", "")
                    notify_eps = item.get("notify_eps_text", "")
                    line = f"- {title_display} [{notify_eps}]" if notify_eps else f"- {title_display}"
                    msg_lines.append(line)

            if skipped:
                msg_lines.append(f"\n**⏭ 跳过 ({len(skipped)} 个，未看完)：**")
                for item in skipped:
                    title_display = item.get("matched_title", "")
                    notify_eps = item.get("notify_eps_text", "")
                    line = f"- {title_display} [{notify_eps}]" if notify_eps else f"- {title_display}"
                    msg_lines.append(line)

            if excluded:
                msg_lines.append(f"\n**🚫 排除 ({len(excluded)} 个，标签匹配)：**")
                for item in excluded:
                    msg_lines.append(f"- {item['title']} [{item['tags']}]")

            if not cleaned and not skipped and not excluded and not discovered and not waiting:
                msg_lines.append("无匹配的种子需要处理")

            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"Trakt 观看清理{dry_tag}{mode_tag}报告",
                text="\n".join(msg_lines),
            )

        logger.info(
            f"Trakt 观看清理：本次共清理 {len(cleaned)} 个种子"
            f"，跳过 {len(skipped)} 个，排除 {len(excluded)} 个"
            + (
                f"，新发现 {len(discovered)}，等待 {len(waiting)}"
                if delayed else ""
            )
        )

    def __remove_torrent(self, torrent, torrent_info: dict, matched: dict,
                         season_ep_text: str, reason: str):
        """删除种子并把结果（成功/失败/异常）写入 torrent_info"""
        try:
            result = self.chain.remove_torrents(
                hashs=torrent.hash,
                delete_file=self._delete_file,
            )
            if result is not None:
                logger.info(
                    f"Trakt 观看清理：已删除种子 {torrent.title} "
                    f"(匹配: {matched.get('title')} {season_ep_text}, {reason})"
                )
            else:
                logger.warning(f"Trakt 观看清理：删除种子失败 {torrent.title}")
                torrent_info["error"] = "删除失败"
        except Exception as e:
            logger.error(f"Trakt 观看清理：删除种子异常 {torrent.title}: {e}")
            torrent_info["error"] = str(e)

    def __build_pending_item(self, torrent_info: dict, first_seen: float) -> dict:
        """由扫描到的 torrent_info 构建待清理队列条目"""
        return {
            "torrent_hash": torrent_info.get("hash"),
            "title": torrent_info.get("title"),
            "matched_type": torrent_info.get("matched_type"),
            "matched_title": torrent_info.get("matched_title"),
            "matched_year": torrent_info.get("matched_year"),
            "season": torrent_info.get("season"),
            "episodes": torrent_info.get("episodes"),
            "season_ep_text": torrent_info.get("season_ep_text"),
            "file_eps_text": torrent_info.get("file_eps_text"),
            "watched_eps_text": torrent_info.get("watched_eps_text"),
            "matched_watched_text": torrent_info.get("matched_watched_text"),
            "notify_eps_text": torrent_info.get("notify_eps_text"),
            "ep_details": torrent_info.get("ep_details"),
            "reason": torrent_info.get("reason"),
            "first_seen": first_seen,
            "status": "pending",
        }

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/authorize_url",
                "endpoint": self.__authorize_url_api,
                "methods": ["GET"],
                "summary": "获取 Trakt 授权链接",
            },
            {
                "path": "/clean_now",
                "endpoint": self.__clean_now_api,
                "methods": ["GET"],
                "summary": "手动清理待清理队列中的指定种子",
            },
            {
                "path": "/clear_seen",
                "endpoint": self.__clear_seen_api,
                "methods": ["GET"],
                "summary": "清除指定种子的发现状态（重置等待计时）",
            },
        ]

    def __authorize_url_api(self):
        """API：根据当前 Client ID 生成授权链接"""
        from starlette.responses import JSONResponse
        client_id = self._client_id or ""
        if not client_id:
            return JSONResponse({"success": False, "url": "", "message": "请先填写并保存 Client ID"})
        url = (
            f"{self._TRAKT_AUTHORIZE_URL}"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={self._TRAKT_REDIRECT_URI}"
        )
        return JSONResponse({"success": True, "url": url, "message": "请点击链接授权"})

    def __clean_now_api(self, torrent_hash: str = "") -> dict:
        """API：手动立即清理待清理队列中的指定种子（不受试运行开关影响）"""
        if not torrent_hash:
            return {"success": False, "message": "缺少种子 hash"}
        pending = self.get_data("pending") or {}
        if not isinstance(pending, dict):
            pending = {}
        item = pending.get(torrent_hash)
        if not item:
            return {"success": False, "message": "该种子不在待清理队列中"}
        # 手动清理即真实删除，不受 dry_run 影响
        try:
            result = self.chain.remove_torrents(
                hashs=torrent_hash, delete_file=self._delete_file
            )
        except Exception as e:
            logger.error(f"Trakt 观看清理：手动清理异常 {item.get('title')}: {e}")
            return {"success": False, "message": f"删除异常: {e}"}
        if result is None:
            return {"success": False, "message": "删除种子失败（下载器返回失败）"}
        # 成功：移出队列，写入历史
        item["status"] = "cleaned"
        item["manual"] = True
        item["hash"] = torrent_hash
        item["dry_run"] = False
        item["clean_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        del pending[torrent_hash]
        self.save_data("pending", pending)
        history = self.get_data("history") or []
        history.append(item)
        history = history[-1000:]
        self.save_data("history", history)
        logger.info(
            f"Trakt 观看清理：手动清理 {item.get('title')} "
            f"({item.get('season_ep_text')})"
        )
        return {
            "success": True,
            "message": f"已清理：{item.get('matched_title') or item.get('title')}",
        }

    def __clear_seen_api(self, torrent_hash: str = "") -> dict:
        """API：清除指定种子的发现状态（重置等待计时，下次扫描重新入列）"""
        if not torrent_hash:
            return {"success": False, "message": "缺少种子 hash"}
        pending = self.get_data("pending") or {}
        if not isinstance(pending, dict):
            pending = {}
        if torrent_hash in pending:
            item = pending.pop(torrent_hash)
            self.save_data("pending", pending)
            logger.info(
                f"Trakt 观看清理：清除发现状态 {item.get('title')}（重置，下次扫描重新计时）"
            )
            return {"success": True, "message": "已清除发现状态，下次扫描将重新计时"}
        return {"success": False, "message": "该种子不在待清理队列中"}

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时任务"""
        if self._enabled and self._cron:
            return [
                {
                    "id": "TraktCleaner",
                    "name": "Trakt 观看清理",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.__clean,
                    "kwargs": {},
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """插件配置页面"""
        # 动态生成授权链接
        authorize_url = ""
        if self._client_id:
            authorize_url = (
                f"{self._TRAKT_AUTHORIZE_URL}"
                f"?response_type=code"
                f"&client_id={self._client_id}"
                f"&redirect_uri={self._TRAKT_REDIRECT_URI}"
            )
        # Token 状态提示
        token_status = "❌ 未授权"
        token_alert_type = "info"
        if self._access_token and getattr(self, '_token_error', False):
            token_status = "⚠️ Token 已失效，请重新获取 PIN 授权"
            token_alert_type = "error"
        elif self._access_token:
            token_status = "✅ 已授权（Token 已获取，自动刷新中）"
            token_alert_type = "success"

        return [
            {
                "component": "VForm",
                "content": [
                    # 基础开关
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "onlyonce", "label": "立即运行一次"},
                                    }
                                ],
                            },
                        ],
                    },
                    # 清理选项
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "delete_file", "label": "同时删除文件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "dry_run", "label": "试运行模式"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "clean_movie", "label": "清理已看电影"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "clean_episode", "label": "清理已看剧集"},
                                    }
                                ],
                            },
                        ],
                    },
                    # 延迟清理天数
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "delay_days",
                                            "label": "延迟清理天数",
                                            "placeholder": "0 表示即时清理；填 N 则首次发现观看后等 N 天再清理",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {"type": "info", "variant": "tonal"},
                                        "text": "延期模式下，满足清理条件的种子先进入待清理队列，到期后自动清理；可在详情页手动「立即清理」或「清除发现」。",
                                    }
                                ],
                            },
                        ],
                    },
                    # 排除标签
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "exclude_tags",
                                            "label": "排除标签",
                                            "placeholder": "多个标签用逗号分隔，如：H&R,保种",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # 定时任务
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "定时执行周期",
                                            "placeholder": "0 */6 * * *（每6小时）",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # === Trakt 授权配置 ===
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "div",
                                        "props": {"class": "text-subtitle-2 font-weight-bold mb-2"},
                                        "text": "🔑 Trakt 授权配置",
                                    },
                                ],
                            },
                        ],
                    },
                    # ① 创建 Trakt 应用
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {"type": "info", "variant": "tonal", "class": "mb-2"},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {"class": "font-weight-bold mb-1"},
                                                "text": "① 创建 Trakt 应用",
                                            },
                                            {
                                                "component": "a",
                                                "props": {
                                                    "href": "https://trakt.tv/oauth/applications",
                                                    "target": "_blank",
                                                    "class": "text-decoration-underline",
                                                },
                                                "text": "点击前往 trakt.tv/oauth/applications 创建新应用",
                                            },
                                            {
                                                "component": "div",
                                                "props": {"class": "text-caption mt-1"},
                                                "text": "Redirect URI 填写: urn:ietf:wg:oauth:2.0:oob",
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    # ② Client ID 和 Client Secret
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
                                            "model": "client_id",
                                            "label": "② Client ID",
                                            "placeholder": "在 Trakt 应用设置页获取",
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
                                            "model": "client_secret",
                                            "label": "② Client Secret",
                                            "type": "password",
                                            "placeholder": "在 Trakt 应用设置页获取",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ③ 授权链接（动态生成）
                    *(
                        [
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12},
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {"type": "warning", "variant": "tonal", "class": "mb-2"},
                                                "content": [
                                                    {
                                                        "component": "a",
                                                        "props": {
                                                            "href": authorize_url,
                                                            "target": "_blank",
                                                            "class": "text-decoration-underline font-weight-bold",
                                                        },
                                                        "text": "🔐 ③ 点击此处打开 Trakt 授权页面，授权后获取 PIN 码",
                                                    },
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ]
                        if authorize_url
                        else [
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12},
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {"type": "info", "variant": "tonal", "class": "mb-2"},
                                                "text": "⚠️ 请先填写 Client ID 并保存，授权链接将自动生成",
                                            },
                                        ],
                                    },
                                ],
                            },
                        ]
                    ),
                    # ③ PIN 输入
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "pin",
                                            "label": "③ PIN 码（填写后点保存，自动换取 Token）",
                                            "placeholder": "从授权页面获取的 PIN 码",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # Token 状态
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": token_alert_type,
                                            "variant": "tonal",
                                            "class": "mb-2",
                                        },
                                        "text": f"当前状态：{token_status}",
                                    },
                                ],
                            },
                        ],
                    },
                    # 高级：Token 显示
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
                                            "model": "access_token",
                                            "label": "Access Token（自动管理，无需手动填写）",
                                            "type": "password",
                                            "placeholder": "自动获取",
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
                                            "model": "refresh_token",
                                            "label": "Refresh Token（自动管理，无需手动填写）",
                                            "type": "password",
                                            "placeholder": "自动获取",
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
            "onlyonce": False,
            "notify": True,
            "delete_file": True,
            "dry_run": False,
            "cron": "0 */6 * * *",
            "client_id": "",
            "client_secret": "",
            "pin": "",
            "access_token": "",
            "refresh_token": "",
            "clean_movie": True,
            "clean_episode": True,
            "exclude_tags": "",
            "delay_days": 0,
        }

    def __build_batch_page_content(self, items: list) -> List[dict]:
        """构建单个执行批次的内容（统计卡片 + Trakt 观看状态 + 种子状态）"""
        from collections import OrderedDict

        total = len(items)
        error_count = sum(1 for i in items if i.get("error"))
        skip_count = sum(1 for i in items if i.get("skipped"))
        exclude_count = sum(1 for i in items if i.get("excluded"))
        clean_count = total - skip_count - exclude_count

        content = []

        # === 统计卡片 ===
        content.append(
            {
                "component": "VRow",
                "props": {"dense": True},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 3},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "success", "variant": "tonal"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "text-center pa-2"},
                                        "content": [
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": str(clean_count)},
                                            {"component": "div", "props": {"class": "text-caption"}, "text": "清理"},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 3},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "warning", "variant": "tonal"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "text-center pa-2"},
                                        "content": [
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": str(skip_count)},
                                            {"component": "div", "props": {"class": "text-caption"}, "text": "跳过"},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 3},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "error" if error_count else "grey", "variant": "tonal"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "text-center pa-2"},
                                        "content": [
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": str(error_count)},
                                            {"component": "div", "props": {"class": "text-caption"}, "text": "失败"},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 3},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"color": "grey", "variant": "tonal"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "props": {"class": "text-center pa-2"},
                                        "content": [
                                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": str(exclude_count)},
                                            {"component": "div", "props": {"class": "text-caption"}, "text": "排除"},
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        )

        # === Trakt 观看状态 ===
        seen_titles = OrderedDict()
        for item in items:
            key = item.get("matched_title", "")
            if key and key not in seen_titles:
                seen_titles[key] = item

        trakt_rows = []
        for title, item in seen_titles.items():
            mtype = item.get("matched_type", "") or item.get("matched", {}).get("type", "")
            eps_text = item.get("watched_eps_text", "")
            # 解析旧格式 watched_eps_text 并做区间合并
            if eps_text and "E" in eps_text:
                import re as _re2
                merged_parts = []
                for part in eps_text.split(" "):
                    m = _re2.match(r'S(\d+)(.+)', part)
                    if m:
                        s = int(m.group(1))
                        ep_nums = [int(x) for x in _re2.findall(r'E?(\d+)', m.group(2))]
                        if ep_nums:
                            merged_parts.append(f"S{s:02d}{self.__merge_episode_ranges(ep_nums)}")
                if merged_parts:
                    eps_text = "  ".join(merged_parts)
            if not eps_text:
                ws = item.get("watched_seasons", {})
                if ws:
                    parts = []
                    for sn, eps in sorted(ws.items(), key=lambda x: int(x[0])):
                        merged = self.__merge_episode_ranges(eps)
                        parts.append(f"S{int(sn):02d}{merged}")
                    eps_text = "  ".join(parts)
            # 没有观看数据的条目不显示在 Trakt 观看状态中
            if not eps_text and mtype != "movie":
                continue
            icon = "🎞️" if mtype == "movie" else "📺"
            trakt_rows.append(
                {
                    "component": "div",
                    "props": {"class": "d-flex align-center pa-2"},
                    "content": [
                        {
                            "component": "span",
                            "props": {"class": "mr-2"},
                            "text": icon,
                        },
                        {
                            "component": "span",
                            "props": {"class": "font-weight-medium mr-2"},
                            "text": title,
                        },
                        {
                            "component": "span",
                            "props": {"class": "text-body-2 text-primary font-weight-bold"},
                            "text": eps_text,
                        },
                    ],
                }
            )

        if trakt_rows:
            content.append(
                {
                    "component": "div",
                    "props": {"class": "pb-2"},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "text-subtitle-2 font-weight-bold mb-1"},
                            "text": "📺 Trakt 观看状态",
                        },
                        {
                            "component": "VCard",
                            "props": {"variant": "outlined", "class": "rounded-lg"},
                            "content": trakt_rows,
                        },
                    ],
                }
            )

        # === 种子状态 ===
        excluded_items = [i for i in items if i.get("excluded")]
        sorted_items = (
            [i for i in items if not i.get("skipped") and not i.get("excluded")]
            + [i for i in items if i.get("skipped")]
            + excluded_items
        )

        seed_rows = []
        for item in sorted_items:
            matched_title = item.get("matched_title", "")
            matched_year = item.get("matched_year", "")
            matched_type = item.get("matched_type", "")
            dry_run = item.get("dry_run", False)
            error = item.get("error", "")
            skipped = item.get("skipped", False)
            is_excluded = item.get("excluded", False)
            tags = item.get("tags", "")
            file_eps = item.get("file_eps_text", "")
            matched_watched = item.get("matched_watched_text", "")
            torrent_title = item.get("title", "")

            # 状态
            if is_excluded:
                status_color = "grey"
                status_text = "排除"
            elif skipped:
                status_color = "warning"
                status_text = "跳过"
            elif error:
                status_color = "error"
                status_text = "失败"
            elif dry_run:
                status_color = "info"
                status_text = "试运行"
            else:
                status_color = "success"
                status_text = "已清理"

            type_icon = "🚫" if is_excluded else ("🎞️" if matched_type == "movie" else "📺")
            title_display = matched_title if matched_title else torrent_title
            if matched_year:
                title_display += f" ({matched_year})"

            row_content = [
                {
                    "component": "div",
                    "props": {"class": "d-flex align-center"},
                    "content": [
                        {"component": "span", "props": {"class": "mr-1"}, "text": type_icon},
                        {"component": "span", "props": {"class": "font-weight-medium text-body-2"}, "text": title_display},
                        {
                            "component": "VChip",
                            "props": {"size": "x-small", "variant": "tonal", "color": status_color, "class": "ml-2"},
                            "text": status_text,
                        },
                    ],
                },
            ]

            if is_excluded and tags:
                row_content.append(
                    {
                        "component": "div",
                        "props": {"class": "text-body-2 mt-1"},
                        "content": [
                            {
                                "component": "span",
                                "props": {"class": "text-grey-darken-1"},
                                "text": f"🏷 {tags}",
                            },
                        ],
                    }
                )
            else:
                ep_details = item.get("ep_details", [])
                if not ep_details and file_eps:
                    import re as _re
                    file_ep_set = set()
                    watched_ep_set = set()
                    for part in file_eps.split("、"):
                        m = _re.match(r'S(\d+)(.+)', part)
                        if m:
                            s = int(m.group(1))
                            rest = m.group(2)
                            rm = _re.match(r'E(\d+)-E(\d+)', rest)
                            if rm:
                                for e in range(int(rm.group(1)), int(rm.group(2)) + 1):
                                    file_ep_set.add((s, e))
                            else:
                                for em in _re.finditer(r'E?(\d+)', rest):
                                    file_ep_set.add((s, int(em.group(1))))
                    if matched_watched:
                        for part in matched_watched.split(" "):
                            m = _re.match(r'S(\d+)(.+)', part)
                            if m:
                                s = int(m.group(1))
                                for em in _re.finditer(r'E?(\d+)', m.group(2)):
                                    watched_ep_set.add((s, int(em.group(1))))
                    if file_ep_set:
                        ep_details = sorted(
                            [{"season": s, "episode": e, "watched": (s, e) in watched_ep_set}
                             for s, e in file_ep_set],
                            key=lambda x: (x["season"], x["episode"]),
                        )
                if ep_details:
                    ep_spans = []
                    last_season = None
                    for ep in ep_details:
                        s = ep.get("season")
                        e = ep.get("episode")
                        w = ep.get("watched", False)
                        if s is not None and e is not None:
                            if s != last_season:
                                if last_season is not None:
                                    ep_spans.append({"component": "span", "text": " "})
                                ep_spans.append({
                                    "component": "span",
                                    "props": {"class": "text-grey-darken-1"},
                                    "text": f"S{s:02d}",
                                })
                                last_season = s
                            cls = "text-success font-weight-bold" if w else "text-grey-darken-1"
                            ep_spans.append({
                                "component": "span",
                                "props": {"class": cls},
                                "text": f"E{e:02d}",
                            })
                        elif ep.get("watched"):
                            ep_spans.append({
                                "component": "span",
                                "props": {"class": "text-success font-weight-bold"},
                                "text": "已看",
                            })
                    if ep_spans:
                        row_content.append(
                            {
                                "component": "div",
                                "props": {"class": "text-body-2 mt-1"},
                                "content": [
                                    {"component": "span", "props": {"class": "text-grey-darken-1 mr-1"}, "text": "📂"},
                                ] + ep_spans,
                            }
                        )

            if error:
                row_content.append(
                    {
                        "component": "div",
                        "props": {"class": "text-caption text-error mt-1"},
                        "text": f"❌ {error}",
                    }
                )

            if torrent_title:
                row_content.append(
                    {
                        "component": "div",
                        "props": {"class": "text-caption text-grey mt-1", "style": "word-break: break-all;"},
                        "text": torrent_title,
                    }
                )

            seed_rows.append(
                {
                    "component": "div",
                    "props": {"class": "d-flex flex-wrap align-center pa-2", "style": "border-bottom: 1px solid rgba(0,0,0,0.06);"},
                    "content": row_content,
                }
            )

        if seed_rows:
            content.append(
                {
                    "component": "div",
                    "props": {"class": "pb-2"},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "text-subtitle-2 font-weight-bold mb-1"},
                            "text": "📁 种子状态",
                        },
                        {
                            "component": "VCard",
                            "props": {"variant": "outlined", "class": "rounded-lg"},
                            "content": seed_rows,
                        },
                    ],
                }
            )

        return content

    def get_page(self) -> List[dict]:
        """插件详情页：顶部为待清理队列（可手动操作），下方为历史执行批次"""
        page: List[dict] = []

        # 待清理队列（延期模式产物，可手动「立即清理」/「清除发现」）
        pending = self.get_data("pending") or {}
        if isinstance(pending, dict) and pending:
            page.append(self.__build_pending_section(pending))

        history = self.get_data("history")
        if not history:
            if page:
                return page
            return [
                {
                    "component": "div",
                    "props": {"class": "text-center pa-4"},
                    "text": "暂无清理记录",
                }
            ]

        # 按时间倒序
        history = sorted(history, key=lambda x: x.get("clean_time", ""), reverse=True)

        # 按执行批次分组
        from collections import OrderedDict
        groups = OrderedDict()
        for item in history:
            clean_time = item.get("clean_time", "未知时间")
            group_key = clean_time[:16] if len(clean_time) > 16 else clean_time
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(item)

        # 每个批次一个折叠面板
        panels = []
        for batch_time, items in groups.items():
            is_dry_run = any(i.get("dry_run") for i in items)
            total = len(items)
            error_count = sum(1 for i in items if i.get("error"))
            skip_count = sum(1 for i in items if i.get("skipped"))
            exclude_count = sum(1 for i in items if i.get("excluded"))
            clean_count = total - skip_count - exclude_count

            # 面板标题：时间 + 状态标签 + 精简统计
            title_content = [
                {
                    "component": "span",
                    "props": {"class": "font-weight-bold mr-2"},
                    "text": batch_time,
                },
                {
                    "component": "VChip",
                    "props": {
                        "size": "x-small",
                        "variant": "tonal",
                        "color": "warning" if is_dry_run else "success",
                    },
                    "text": "🔍 试运行" if is_dry_run else "✅ 已执行",
                },
                {
                    "component": "span",
                    "props": {"class": "ml-2 text-caption text-grey-darken-1"},
                    "text": f"清理 {clean_count} · 跳过 {skip_count} · 失败 {error_count} · 排除 {exclude_count}",
                },
            ]

            panels.append(
                {
                    "component": "VExpansionPanel",
                    "content": [
                        {
                            "component": "VExpansionPanelTitle",
                            "content": title_content,
                        },
                        {
                            "component": "VExpansionPanelText",
                            "content": self.__build_batch_page_content(items),
                        },
                    ],
                }
            )

        page.append(
            {
                "component": "VExpansionPanels",
                "props": {"modelValue": 0},
                "content": panels,
            }
        )
        return page

    def __build_pending_section(self, pending: Dict[str, dict]) -> dict:
        """构建详情页顶部的待清理队列区段（含手动操作按钮）"""
        now = time.time()
        delay_seconds = self._delay_days * 86400
        plugin_name = self.__class__.__name__

        rows = []
        # 按首次发现时间倒序
        for h, item in sorted(
            pending.items(),
            key=lambda kv: kv[1].get("first_seen", 0),
            reverse=True,
        ):
            first_seen = item.get("first_seen", now) or now
            first_seen_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(first_seen))
            if delay_seconds > 0:
                remain = (first_seen + delay_seconds) - now
                if remain > 0:
                    remain_text = f"剩余 {remain / 86400:.1f} 天"
                    chip_color = "info"
                else:
                    remain_text = "已到期"
                    chip_color = "warning"
            else:
                remain_text = "即时"
                chip_color = "success"

            title_display = item.get("matched_title") or item.get("title") or ""
            season_ep = item.get("season_ep_text") or ""
            notify_eps = item.get("notify_eps_text") or ""
            sub_text = f"发现于 {first_seen_text}"
            if notify_eps:
                sub_text += f" · {notify_eps}"
            elif item.get("reason"):
                sub_text += f" · {item.get('reason')}"

            rows.append(
                {
                    "component": "VRow",
                    "props": {"align": "center", "class": "py-1"},
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 6},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "font-weight-medium"},
                                    "text": f"{title_display} {season_ep}".strip(),
                                },
                                {
                                    "component": "div",
                                    "props": {"class": "text-caption text-grey-darken-1"},
                                    "text": sub_text,
                                },
                            ],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 6, "md": 2},
                            "content": [
                                {
                                    "component": "VChip",
                                    "props": {
                                        "size": "small",
                                        "variant": "tonal",
                                        "color": chip_color,
                                    },
                                    "text": remain_text,
                                },
                            ],
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 6, "md": 4},
                            "content": [
                                {
                                    "component": "VBtn",
                                    "props": {
                                        "color": "error",
                                        "size": "small",
                                        "variant": "tonal",
                                        "class": "mr-2",
                                        "prepend-icon": "mdi-delete",
                                    },
                                    "text": "立即清理",
                                    "events": {
                                        "click": {
                                            "api": f"plugin/{plugin_name}/clean_now?apikey={settings.API_TOKEN}",
                                            "method": "get",
                                            "params": {
                                                "torrent_hash": h,
                                            },
                                        }
                                    },
                                },
                                {
                                    "component": "VBtn",
                                    "props": {
                                        "color": "grey",
                                        "size": "small",
                                        "variant": "text",
                                        "prepend-icon": "mdi-undo",
                                    },
                                    "text": "清除发现",
                                    "events": {
                                        "click": {
                                            "api": f"plugin/{plugin_name}/clear_seen?apikey={settings.API_TOKEN}",
                                            "method": "get",
                                            "params": {
                                                "torrent_hash": h,
                                            },
                                        }
                                    },
                                },
                            ],
                        },
                    ],
                }
            )

        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-4"},
            "content": [
                {
                    "component": "VCardItem",
                    "content": [
                        {
                            "component": "VCardTitle",
                            "text": f"⏳ 待清理队列（{len(pending)} 个）",
                        },
                        {
                            "component": "VCardSubtitle",
                            "text": (
                                f"延期 {self._delay_days} 天自动清理；可手动「立即清理」"
                                f"或「清除发现」重置计时"
                            ),
                        },
                    ],
                },
                {
                    "component": "VCardText",
                    "content": rows,
                },
            ],
        }

    def stop_service(self):
        """停止插件"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"Trakt 观看清理：退出插件失败: {e}")
