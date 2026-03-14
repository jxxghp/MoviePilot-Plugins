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
from app.helper.event import eventmanager
from app.schemas.types import MediaType, EventType

lock = Lock()

# ─── 集数正则（与独立脚本保持一致） ─────────────────────────────────────

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


class TvFirstWatch(_PluginBase):
    """
    电视剧首播试看自动下载

    定时抓取多个 RSS 源，仅下载电视剧前 N 集（默认 1-2 集），
    通过 MoviePilot DownloadChain 触发下载（支持洗版、刮削）。
    """

    # ── 插件元信息 ──────────────────────────────────────────────────────
    plugin_name = "首播试看"
    plugin_desc = "定时抓取 RSS，只下载剧集前 N 集（首播试看），防重复推送。"
    plugin_icon = "rss.png"
    plugin_version = "1.0"
    plugin_author = "Raymond38324"
    author_url = "https://github.com/Raymond38324"
    plugin_config_prefix = "tvfirstwatch_"
    plugin_order = 25
    auth_level = 2

    # ── 私有变量 ─────────────────────────────────────────────────────────
    _scheduler: Optional[BackgroundScheduler] = None
    _downloadchain: Optional[DownloadChain] = None
    _history_path: Optional[Path] = None

    # ── 配置属性 ─────────────────────────────────────────────────────────
    _enabled: bool = False
    _onlyonce: bool = False
    _notify: bool = False
    _cron: str = "*/30 * * * *"  # cron 轮询周期
    _rss_urls: str = ""  # 每行一个 RSS URL（含 Cookie 则用 "|" 分隔）
    _max_episode: int = 2  # 最大集号
    _whitelist: str = "1080p,2160p,4K,HEVC,H.265"
    _blacklist: str = "720p,CAM,HDTS"
    _save_path: str = ""  # 下载保存路径（留空 MP 默认）

    # ─────────────────────────────────────────────────────────────────────

    def init_plugin(self, config: dict = None) -> None:
        self._downloadchain = DownloadChain()
        self.stop_service()

        if config:
            self._enabled = config.get("enabled", False)
            self._onlyonce = config.get("onlyonce", False)
            self._notify = config.get("notify", False)
            self._cron = config.get("cron", "*/30 * * * *") or "*/30 * * * *"
            self._rss_urls = config.get("rss_urls", "")
            self._max_episode = int(config.get("max_episode", 2))
            self._whitelist = config.get("whitelist", "")
            self._blacklist = config.get("blacklist", "")
            self._save_path = config.get("save_path", "")

        # 数据目录
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

            # 关闭一次性开关并保存
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
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时任务。"""
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
        """处理远程命令。"""
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

    # ─── 配置页面 ─────────────────────────────────────────────────────────

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # 第一行：开关
                    {
                        "component": "VRow",
                        "content": [
                            _col(4, _switch("enabled", "启用插件")),
                            _col(4, _switch("notify", "下载时通知")),
                            _col(4, _switch("onlyonce", "立即运行一次")),
                        ],
                    },
                    # 第二行：执行周期 + 最大集号
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                8,
                                _textfield(
                                    "cron",
                                    "执行周期（Cron）",
                                    placeholder="5位cron，如 */30 * * * *",
                                ),
                            ),
                            _col(
                                4,
                                _textfield(
                                    "max_episode",
                                    "最大集号",
                                    placeholder="默认 2（即下载 EP01-02）",
                                ),
                            ),
                        ],
                    },
                    # 第三行：RSS 地址
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
                    # 第四行：白名单 / 黑名单
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
                    # 第五行：保存路径
                    {
                        "component": "VRow",
                        "content": [
                            _col(
                                12,
                                _textfield(
                                    "save_path",
                                    "下载保存路径（留空使用 MP 默认）",
                                    placeholder="/downloads/TV",
                                ),
                            ),
                        ],
                    },
                    # 说明
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
                                            "仅下载识别到集号 ≤ 最大集号 的电视剧资源，"
                                            "下载记录保存在插件数据目录 history.json，"
                                            "点击「清空历史」API 可重置。"
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
            "notify": False,
            "onlyonce": False,
            "cron": "*/30 * * * *",
            "rss_urls": "",
            "max_episode": 2,
            "whitelist": "1080p,2160p,4K,HEVC,H.265",
            "blacklist": "720p,CAM,HDTS",
            "save_path": "",
        }

    def get_page(self) -> List[dict]:
        """详情页：展示最近下载记录。"""
        history = self._load_history()
        if not history:
            return [
                {
                    "component": "div",
                    "props": {"class": "text-center pa-4"},
                    "content": [{"component": "p", "text": "暂无下载记录"}],
                }
            ]

        rows = []
        for key, meta in sorted(
            history.items(), key=lambda x: x[1].get("added_at", ""), reverse=True
        ):
            rows.append(
                {
                    "component": "tr",
                    "content": [
                        {"component": "td", "text": meta.get("series_name", key)},
                        {"component": "td", "text": str(meta.get("episode", ""))},
                        {"component": "td", "text": meta.get("source", "")},
                        {"component": "td", "text": meta.get("added_at", "")},
                    ],
                }
            )

        return [
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
                                    {"component": "th", "text": "来源"},
                                    {"component": "th", "text": "下载时间"},
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": rows},
                ],
            }
        ]

    # ─── 核心逻辑 ─────────────────────────────────────────────────────────

    def _check_all_feeds(self) -> None:
        """轮询所有 RSS 源（定时任务入口）。"""
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
        """
        解析 RSS 行格式：
          URL
          URL|Cookie: xxx
        """
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
            # 支持 "Cookie: xxx" 或直接是 cookie 字符串
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
                logger.exception(
                    "[首播试看] 处理条目异常 [%s]: %s", entry.get("title", ""), exc
                )

    def _process_entry(self, entry, source: str) -> None:
        title = entry.get("title", "")
        if not title:
            return

        # 1. 是否为电视剧
        if not self._is_tv(entry):
            logger.debug("[首播试看][跳过-非TV] %s", title)
            return

        # 2. 提取集数
        episodes = _extract_episodes(title)
        if not episodes:
            logger.debug("[首播试看][跳过-无集数] %s", title)
            return

        # 3. 集数范围
        eps_in_range = [ep for ep in episodes if ep <= self._max_episode]
        if not eps_in_range:
            logger.info(
                "[首播试看][跳过-超限] %s | 识别集号=%s 限制≤%d",
                title,
                episodes,
                self._max_episode,
            )
            return

        # 4. 关键字过滤
        ok, reason = self._keyword_filter(title)
        if not ok:
            logger.info("[首播试看][跳过-关键字] %s | %s", title, reason)
            return

        # 5. 去重检查
        series_name = _guess_series_name(title)
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

            # 6. 触发下载
            logger.info(
                "[首播试看][下载] %s | 剧名=%s | 集号=%s | 来源=%s",
                title,
                series_name,
                new_eps,
                source,
            )
            success = self._do_download(entry, title, series_name)

            if success:
                now = datetime.datetime.now().isoformat(timespec="seconds")
                for ep in new_eps:
                    key = _make_key(series_name, ep)
                    history[key] = {
                        "series_name": series_name,
                        "episode": ep,
                        "title": title,
                        "source": source,
                        "added_at": now,
                    }
                self._save_history(history)

                if self._notify:
                    self.systemmessage.put(
                        f"📺 首播试看已推送下载\n"
                        f"剧名：{series_name}\n"
                        f"集号：{new_eps}\n"
                        f"标题：{title}"
                    )

    def _do_download(self, entry, title: str, series_name: str) -> bool:
        """通过 MoviePilot DownloadChain 触发下载。"""
        # 构造 TorrentInfo
        torrent_url = ""
        for enc in getattr(entry, "enclosures", []):
            if enc.get("type", "").startswith("application/"):
                torrent_url = enc.get("href", "")
                break
        if not torrent_url:
            torrent_url = entry.get("link", "")

        if not torrent_url:
            logger.error("[首播试看] 条目缺少种子 URL: %s", title)
            return False

        meta = MetaInfo(title=title)
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
            did, msg = self._downloadchain.download_single(
                context=context,
                torrent_file=None,
                save_path=self._save_path or None,
            )
            if did:
                logger.info("[首播试看] ✅ DownloadChain 推送成功: %s", title)
                return True
            else:
                logger.error(
                    "[首播试看] ❌ DownloadChain 推送失败 [%s]: %s", title, msg
                )
                return False
        except Exception as exc:
            logger.error("[首播试看] ❌ 下载异常 [%s]: %s", title, exc)
            return False

    # ─── 辅助：关键字过滤 ─────────────────────────────────────────────────

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
        if hasattr(entry, "tags") and entry.tags:
            cat = entry.tags[0].get("term", "").lower()
        elif hasattr(entry, "category"):
            cat = (entry.category or "").lower()

        tv_cats = ("tv", "series", "drama", "television", "综艺", "剧集", "连续剧")
        movie_kw = ("movie", "film", "电影", "纪录片")
        if any(k in cat for k in tv_cats):
            return True
        if any(k in cat for k in movie_kw):
            return False
        return bool(TV_HINTS.search(entry.get("title", "")))

    # ─── 历史记录操作 ─────────────────────────────────────────────────────

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
        """API：清空下载历史。"""
        if token != settings.API_TOKEN:
            return {"success": False, "message": "认证失败"}
        self._save_history({})
        logger.info("[首播试看] 下载历史已清空。")
        return {"success": True, "message": "历史已清空"}

    def __update_config(self) -> None:
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "notify": self._notify,
                "cron": self._cron,
                "rss_urls": self._rss_urls,
                "max_episode": self._max_episode,
                "whitelist": self._whitelist,
                "blacklist": self._blacklist,
                "save_path": self._save_path,
            }
        )


# ─── 模块级工具函数 ───────────────────────────────────────────────────────


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


# ─── Vuetify 组件快捷函数 ─────────────────────────────────────────────────


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
