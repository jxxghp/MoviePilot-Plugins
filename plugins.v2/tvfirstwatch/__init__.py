import datetime
import json
import re
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import feedparser
import requests

from app.chain.download import DownloadChain
from app.core.config import settings
from app.core.context import Context, MediaInfo, TorrentInfo
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.core.event import eventmanager
from app.schemas.types import MediaType, EventType

lock = Lock()

EPISODE_PATTERNS = [
    re.compile(r"[Ss]\d{1,2}[Ee](\d{1,3})", re.IGNORECASE),
    re.compile(r"\bEP?\.?(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"第\s*(\d{1,3})\s*集"),
    re.compile(r"[【\[(（](\d{1,3})[】\])）]"),
    re.compile(r"\b(\d{1,3})\s*of\s*\d+\b", re.IGNORECASE),
]

TV_HINTS = re.compile(
    r"\b(S\d{1,2}E\d{1,3}|EP?\d{1,3}|第\d+集|Season|Complete|HDTV|WEB-?DL)\b",
    re.IGNORECASE,
)

COMPLETE_HINTS = re.compile(
    r"\b(Complete|全集|全季|Season\s*\d+\s*Complete|S\d+\s*Complete)\b",
    re.IGNORECASE,
)


class TvFirstWatch(_PluginBase):
    plugin_name = "首播试看"
    plugin_desc = "定时抓取 RSS, 只下载剧集前 N 集（首播试看），防重复推送。"
    plugin_icon = "rss.png"
    plugin_version = "1.0.0"
    plugin_author = "Raymond38324"
    author_url = "https://github.com/Raymond38324"
    plugin_config_prefix = "tvfirstwatch_"
    plugin_order = 25
    auth_level = 2

    _scheduler: Optional[BackgroundScheduler] = None
    _downloadchain: Optional[DownloadChain] = None
    _history_path: Optional[Path] = None

    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = "*/30 * * * *"
    _rss_urls: str = ""
    _max_episode: int = 2
    _whitelist: str = "1080p,2160p,4K,HEVC,H.265"
    _blacklist: str = "720p,CAM,HDTS"
    _save_path: str = ""
    _max_storage_gb: int = 0
    _default_size_gb: float = 2.0
    _max_single_size_gb: float = 10.0

    def init_plugin(self, config: dict = None) -> None:
        self._downloadchain = DownloadChain()
        self.stop_service()

        if config:
            self._enabled = _to_bool(config.get("enabled", False), False)
            self._onlyonce = _to_bool(config.get("onlyonce", False), False)
            self._cron = config.get("cron", "*/30 * * * *") or "*/30 * * * *"
            self._rss_urls = config.get("rss_urls", "")
            self._max_episode = _to_int(config.get("max_episode", 2), 2)
            self._whitelist = config.get("whitelist", "")
            self._blacklist = config.get("blacklist", "")
            self._save_path = config.get("save_path", "")
            self._max_storage_gb = _to_int(config.get("max_storage_gb", 0), 0)
            self._default_size_gb = _to_float(config.get("default_size_gb", 2.0), 2.0)
            self._max_single_size_gb = _to_float(
                config.get("max_single_size_gb", 10.0), 10.0
            )

        self._history_path = self.get_data_path() / "history.json"

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("[首播试看] 立即运行一次")
            self._scheduler.add_job(
                func=self._check_all_feeds,
                trigger="date",
                run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ))
                + datetime.timedelta(seconds=3),
            )
            if self._scheduler.get_jobs():
                self._scheduler.start()

            self._onlyonce = False
            self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    def get_command(self) -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/tvfirst_check",
                "event": EventType.PluginAction,
                "desc": "首播试看立即检查",
                "category": "订阅",
                "data": {"action": "check_feeds"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/clear_history",
                "endpoint": self._clear_history,
                "methods": ["GET"],
                "summary": "清空首播试看下载历史",
            },
            {
                "path": "/storage_status",
                "endpoint": self._storage_status,
                "methods": ["GET"],
                "summary": "获取存储空间使用情况",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and self._cron:
            return [
                {
                    "id": "TvFirstWatch",
                    "name": "首播试看轮询",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self._check_all_feeds,
                    "kwargs": {},
                }
            ]
        return []

    @eventmanager.register(EventType.PluginAction)
    def _plugin_action(self, event):
        if not self._enabled:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "check_feeds":
            return
        logger.info("[首播试看] 收到远程命令，立即执行检查")
        self._check_all_feeds()

    def stop_service(self) -> None:
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            if self._scheduler.running:
                self._scheduler.shutdown()
            self._scheduler = None

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _switch("enabled", "启用插件")),
                            _col(4, _switch("onlyonce", "立即运行一次")),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                4,
                                _textfield(
                                    "cron",
                                    "执行周期（Cron）",
                                    placeholder="*/30 * * * *",
                                ),
                            ),
                            _col(
                                2,
                                _textfield(
                                    "max_episode",
                                    "最大集号",
                                    placeholder="默认 2",
                                ),
                            ),
                            _col(
                                3,
                                _textfield(
                                    "max_storage_gb",
                                    "空间上限(GB)",
                                    placeholder="0=不限制",
                                ),
                            ),
                            _col(
                                3,
                                _textfield(
                                    "max_single_size_gb",
                                    "单集上限(GB)",
                                    placeholder="超过跳过",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                6,
                                _textfield(
                                    "default_size_gb",
                                    "预估大小(GB)",
                                    placeholder="RSS无大小默认值",
                                ),
                            ),
                            _col(
                                6,
                                _textfield(
                                    "save_path",
                                    "下载保存路径",
                                    placeholder="留空使用MP默认",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                {
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "rss_urls",
                                        "label": "RSS 地址",
                                        "rows": 4,
                                        "placeholder": (
                                            "每行一个地址，格式：\n"
                                            "https://site/rss?passkey=xxx\n"
                                            "# 需要Cookie：https://site/rss|Cookie: uid=1; pass=abc"
                                        ),
                                    },
                                },
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                6,
                                _textfield(
                                    "whitelist",
                                    "白名单关键字（逗号分隔）",
                                    placeholder="1080p,4K,HEVC",
                                ),
                            ),
                            _col(
                                6,
                                _textfield(
                                    "blacklist",
                                    "黑名单关键字（逗号分隔）",
                                    placeholder="720p,CAM",
                                ),
                            ),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                {
                                    "component": "VAlert",
                                    "props": {
                                        "type": "info",
                                        "variant": "tonal",
                                        "text": (
                                            "仅下载集号≤最大集号的电视剧，自动跳过Complete/全集。"
                                            "单集上限：超过此大小的种子将跳过(防合集)。"
                                            "空间上限：超出将停止下载，0表示不限制。"
                                        ),
                                    },
                                },
                            ),
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "*/30 * * * *",
            "rss_urls": "",
            "max_episode": 2,
            "whitelist": "1080p,2160p,4K,HEVC,H.265",
            "blacklist": "720p,CAM,HDTS",
            "save_path": "",
            "max_storage_gb": 0,
            "default_size_gb": 2.0,
            "max_single_size_gb": 10.0,
        }

    def get_page(self) -> List[dict]:
        history = self._load_history()
        total_bytes = self._calculate_total_size(history)
        total_gb = total_bytes / (1024**3)
        max_gb = self._max_storage_gb
        usage_percent = (total_gb / max_gb * 100) if max_gb > 0 else 0
        count = len(history)

        header_content = [
            {
                "component": "div",
                "props": {"class": "d-flex justify-space-between align-center"},
                "content": [
                    {
                        "component": "p",
                        "props": {"class": "text-h6 mb-0"},
                        "text": f"已用空间: {total_gb:.2f} GB"
                        + (
                            f" / {max_gb} GB ({usage_percent:.1f}%)"
                            if max_gb > 0
                            else f" | 共 {count} 条记录"
                        ),
                    },
                    {
                        "component": "VBtn",
                        "props": {
                            "color": "error",
                            "variant": "outlined",
                            "size": "small",
                        },
                        "text": "清空历史",
                        "events": {
                            "click": {
                                "api": "plugin/TvFirstWatch/clear_history",
                                "method": "get",
                                "params": {"token": settings.API_TOKEN},
                            }
                        },
                    },
                ],
            }
        ]

        if not history:
            return [
                {
                    "component": "div",
                    "props": {"class": "pa-4"},
                    "content": header_content
                    + [
                        {
                            "component": "p",
                            "text": "暂无下载记录",
                            "props": {"class": "text-center mt-4"},
                        },
                    ],
                }
            ]

        rows = []
        for key, meta in sorted(
            history.items(), key=lambda x: x[1].get("added_at", ""), reverse=True
        ):
            size_str = meta.get("size_str", "-")
            rows.append(
                {
                    "component": "tr",
                    "content": [
                        {"component": "td", "text": meta.get("series_name", key)},
                        {"component": "td", "text": str(meta.get("episode", ""))},
                        {"component": "td", "text": size_str},
                        {"component": "td", "text": meta.get("source", "")},
                        {"component": "td", "text": meta.get("added_at", "")},
                    ],
                }
            )

        return [
            {
                "component": "div",
                "props": {"class": "pa-2"},
                "content": header_content,
            },
            {
                "component": "VTable",
                "props": {"hover": True},
                "content": [
                    {
                        "component": "thead",
                        "content": [
                            {
                                "component": "tr",
                                "content": [
                                    {"component": "th", "text": "剧名"},
                                    {"component": "th", "text": "集号"},
                                    {"component": "th", "text": "大小"},
                                    {"component": "th", "text": "来源"},
                                    {"component": "th", "text": "下载时间"},
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": rows},
                ],
            },
        ]

    def _check_all_feeds(self) -> None:
        if not self._rss_urls:
            logger.warning("[首播试看] 未配置任何 RSS 地址，跳过。")
            return

        lines = [l.strip() for l in self._rss_urls.splitlines() if l.strip()]
        for line in lines:
            try:
                self._process_feed(line)
            except Exception as exc:
                logger.error("[首播试看] 处理 RSS 源出错: %s — %s", line, exc)

    def _parse_feed_line(self, line: str) -> Tuple[str, dict]:
        parts = line.split("|", 1)
        url = parts[0].strip()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        }
        if len(parts) == 2:
            cookie_part = parts[1].strip()
            if cookie_part.lower().startswith("cookie:"):
                headers["Cookie"] = cookie_part[7:].strip()
            else:
                headers["Cookie"] = cookie_part
        return url, headers

    def _process_feed(self, line: str) -> None:
        url, headers = self._parse_feed_line(line)
        source = urlparse(url).netloc
        logger.info("[首播试看] 抓取 RSS: %s", url)

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("[首播试看] RSS 请求失败 [%s]: %s", source, exc)
            return

        parsed = feedparser.parse(resp.text)
        if not parsed.entries:
            logger.warning("[首播试看] RSS 无条目 [%s]", source)
            return

        logger.info("[首播试看] [%s] 解析到 %d 个条目", source, len(parsed.entries))
        for entry in parsed.entries:
            try:
                self._process_entry(entry, source)
            except Exception as exc:
                logger.error(
                    "[首播试看] 处理条目异常 [%s]: %s", entry.get("title") or "", exc
                )

    def _process_entry(self, entry, source: str) -> None:
        title = entry.get("title") or ""
        if not title:
            return

        if not self._is_tv(entry):
            logger.debug("[首播试看][跳过-非TV] %s", title)
            return

        if COMPLETE_HINTS.search(title):
            logger.info("[首播试看][跳过-合集] %s | 检测到Complete/全集关键词", title)
            return

        episodes = _extract_episodes(title)
        if not episodes:
            logger.debug("[首播试看][跳过-无集数] %s", title)
            return

        eps_in_range = [ep for ep in episodes if ep <= self._max_episode]
        if not eps_in_range:
            logger.info(
                "[首播试看][跳过-超限] %s | 识别集号=%s 限制≤%d",
                title,
                episodes,
                self._max_episode,
            )
            return

        ok, reason = self._keyword_filter(title)
        if not ok:
            logger.info("[首播试看][跳过-关键字] %s | %s", title, reason)
            return

        series_name = _guess_series_name(title)

        torrent_size, is_estimated = self._get_torrent_size(entry)
        size_label = "预估" if is_estimated else "实际"
        size_gb = torrent_size / (1024**3)

        if self._max_single_size_gb > 0 and size_gb > self._max_single_size_gb:
            logger.info(
                "[首播试看][跳过-过大] %s | 大小 %.2f GB > 上限 %.1f GB (可能是合集)",
                title,
                size_gb,
                self._max_single_size_gb,
            )
            return

        with lock:
            history = self._load_history()
            new_eps = [
                ep
                for ep in eps_in_range
                if not self._is_downloaded(history, series_name, ep)
            ]
            if not new_eps:
                logger.info(
                    "[首播试看][跳过-已下载] %s | 剧名=%s | 集号=%s",
                    title,
                    series_name,
                    eps_in_range,
                )
                return

            if self._max_storage_gb > 0:
                current_total = self._calculate_total_size(history)
                max_bytes = self._max_storage_gb * (1024**3)
                if current_total + torrent_size > max_bytes:
                    logger.warning(
                        "[首播试看][跳过-空间不足] 已用 %.2f GB + 新增 %.2f GB(%s) > 上限 %d GB",
                        current_total / (1024**3),
                        size_gb,
                        size_label,
                        self._max_storage_gb,
                    )
                    return

            logger.info(
                "[首播试看][下载] %s | 剧名=%s | 集号=%s | 大小=%.2f GB(%s) | 来源=%s",
                title,
                series_name,
                new_eps,
                size_gb,
                size_label,
                source,
            )
            success = self._do_download(entry, title, series_name)

            if success:
                now = datetime.datetime.now().isoformat(timespec="seconds")
                size_str = self._format_size(torrent_size, is_estimated)
                for ep in new_eps:
                    key = _make_key(series_name, ep)
                    history[key] = {
                        "series_name": series_name,
                        "episode": ep,
                        "title": title,
                        "source": source,
                        "added_at": now,
                        "size": torrent_size,
                        "size_str": size_str,
                        "is_estimated": is_estimated,
                    }
                self._save_history(history)

    def _get_torrent_size(self, entry) -> Tuple[int, bool]:
        """
        获取种子大小。
        返回: (大小字节数, 是否为预估大小)
        """
        try:
            if hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    length = enc.get("length")
                    if length:
                        return int(length), False
            if hasattr(entry, "content_length"):
                return int(entry.content_length), False
        except Exception:
            pass
        default_bytes = int(self._default_size_gb * (1024**3))
        return default_bytes, True

    @staticmethod
    def _format_size(size_bytes: int, is_estimated: bool = False) -> str:
        label = "(预估)" if is_estimated else ""
        if size_bytes == 0:
            return "未知" + label
        elif size_bytes < 1024:
            return f"{size_bytes} B{label}"
        elif size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB{label}"
        elif size_bytes < 1024**3:
            return f"{size_bytes / (1024**2):.1f} MB{label}"
        else:
            return f"{size_bytes / (1024**3):.2f} GB{label}"

    @staticmethod
    def _calculate_total_size(history: dict) -> int:
        total = 0
        for meta in history.values():
            total += meta.get("size", 0)
        return total

    def _do_download(self, entry, title: str, series_name: str) -> bool:
        torrent_url = ""
        for enc in getattr(entry, "enclosures", []):
            enc_type = enc.get("type") or ""
            if enc_type.startswith("application/"):
                torrent_url = enc.get("href") or ""
                break
        if not torrent_url:
            torrent_url = entry.get("link") or ""

        if not torrent_url:
            logger.error("[首播试看] 条目缺少种子 URL: %s", title)
            return False

        meta = MetaInfo(title=title)
        if not meta.name:
            meta.name = series_name

        mediainfo = self.chain.recognize_media(meta=meta)
        if not mediainfo:
            logger.warning("[首播试看] 未识别到媒体信息，使用基本信息: %s", title)
            mediainfo = MediaInfo()
            mediainfo.type = MediaType.TV
            mediainfo.title = series_name

        torrent = TorrentInfo(
            title=title,
            enclosure=torrent_url,
            page_url=entry.get("link", ""),
        )

        context = Context(
            meta_info=meta,
            media_info=mediainfo,
            torrent_info=torrent,
        )

        try:
            did = self._downloadchain.download_single(
                context=context,
                torrent_file=None,
                save_path=self._save_path or None,
            )
            if did:
                logger.info("[首播试看] ✅ DownloadChain 推送成功: %s", title)
                return True
            else:
                logger.error("[首播试看] ❌ DownloadChain 推送失败 [%s]", title)
                return False
        except Exception as exc:
            logger.error("[首播试看] ❌ 下载异常 [%s]: %s", title, exc)
            return False

    def _keyword_filter(self, title: str) -> Tuple[bool, str]:
        title_lower = title.lower()
        for kw in [k.strip() for k in self._blacklist.split(",") if k.strip()]:
            if kw.lower() in title_lower:
                return False, f"命中黑名单「{kw}」"
        wl = [k.strip() for k in self._whitelist.split(",") if k.strip()]
        if wl and not any(k.lower() in title_lower for k in wl):
            return False, f"未命中白名单 {wl}"
        return True, ""

    @staticmethod
    def _is_tv(entry) -> bool:
        cat = ""
        try:
            if hasattr(entry, "tags") and entry.tags:
                term = entry.tags[0].get("term") or ""
                cat = term.lower()
            elif hasattr(entry, "category"):
                cat = (entry.category or "").lower()
        except Exception:
            pass

        tv_cats = ("tv", "series", "drama", "television", "综艺", "剧集", "连续剧")
        movie_kw = ("movie", "film", "电影", "纪录片")
        if any(k in cat for k in tv_cats):
            return True
        if any(k in cat for k in movie_kw):
            return False
        return bool(TV_HINTS.search(entry.get("title") or ""))

    def _load_history(self) -> dict:
        if self._history_path and self._history_path.exists():
            try:
                return json.loads(self._history_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_history(self, history: dict) -> None:
        if self._history_path:
            self._history_path.write_text(
                json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    @staticmethod
    def _is_downloaded(history: dict, series_name: str, episode: int) -> bool:
        return _make_key(series_name, episode) in history

    def _clear_history(self, token: str = "") -> dict:
        if token != settings.API_TOKEN:
            return {"success": False, "message": "认证失败"}
        self._save_history({})
        logger.info("[首播试看] 下载历史已清空。")
        return {"success": True, "message": "历史已清空"}

    def _storage_status(self, token: str = "") -> dict:
        if token != settings.API_TOKEN:
            return {"success": False, "message": "认证失败"}
        history = self._load_history()
        total_bytes = self._calculate_total_size(history)
        total_gb = total_bytes / (1024**3)
        count = len(history)
        return {
            "success": True,
            "total_bytes": total_bytes,
            "total_gb": round(total_gb, 2),
            "max_gb": self._max_storage_gb,
            "count": count,
        }

    def __update_config(self) -> None:
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "rss_urls": self._rss_urls,
                "max_episode": self._max_episode,
                "whitelist": self._whitelist,
                "blacklist": self._blacklist,
                "save_path": self._save_path,
                "max_storage_gb": self._max_storage_gb,
                "default_size_gb": self._default_size_gb,
                "max_single_size_gb": self._max_single_size_gb,
            }
        )


def _extract_episodes(title: str) -> List[int]:
    found: set[int] = set()
    for pat in EPISODE_PATTERNS:
        for m in pat.finditer(title):
            try:
                ep = int(m.group(1))
                if 0 < ep < 1000:
                    found.add(ep)
            except (IndexError, ValueError):
                pass
    return sorted(found)


def _guess_series_name(title: str) -> str:
    name = re.split(
        r"[\s._\-]*(?:[Ss]\d{1,2}[Ee]\d{1,3}|[Ee][Pp]?\d{1,3}|第\d+集|\d+of\d+|[\[(【]\d+[】\])])",
        title,
        maxsplit=1,
    )[0]
    name = re.sub(r"^\s*\[.*?\]\s*", "", name)
    name = re.sub(r"\b(19|20)\d{2}\b", "", name)
    name = re.sub(r"[\s._\-]+", " ", name).strip(" .-_")
    return name or title


def _make_key(series_name: str, episode: int) -> str:
    norm = re.sub(r"\W+", "", series_name.lower())
    return f"{norm}__ep{episode:03d}"


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off", ""):
            return False
    return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _col(md: int, *children) -> dict:
    return {
        "component": "VCol",
        "props": {"cols": 12, "md": md},
        "content": list(children),
    }


def _switch(model: str, label: str) -> dict:
    return {
        "component": "VSwitch",
        "props": {"model": model, "label": label},
    }


def _textfield(model: str, label: str, placeholder: str = "") -> dict:
    props: dict = {"model": model, "label": label}
    if placeholder:
        props["placeholder"] = placeholder
    return {"component": "VTextField", "props": props}
