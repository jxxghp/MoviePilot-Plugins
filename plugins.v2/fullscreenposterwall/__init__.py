"""
全屏海报墙插件。

从 MoviePilot 推荐媒体接口（流行趋势 / TMDB 热门电影 / TMDB 热门电视剧）
抓取海报图片，通过 Vue 联邦页面以五种屏幕保护动效全屏展示。
"""
from __future__ import annotations

import asyncio
import socket
from typing import Any, Dict, List, Optional, Tuple

from app.chain.recommend import RecommendChain
from app.plugins import _PluginBase
from app.schemas import MediaInfo
from app.schemas.types import MediaType
from fastapi import Request


def _detect_lan_info() -> Dict[str, Any]:
    """获取 LAN 访问信息（本机出口 IP + MoviePilot 端口 + 分享 URL）。

    通过 UDP socket 探测出口 IP（不发实际数据包）。MoviePilot 前端
    默认监听 NGINX_PORT（3000），我们把端口直接拼到 URL 上。
    """
    from app.core.config import settings as _settings

    port = 3000
    try:
        port = int(getattr(_settings, "NGINX_PORT", 3000) or 3000)
    except Exception:
        port = 3000

    ips: List[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except Exception:
        pass
    try:
        ips.append(socket.gethostbyname(socket.gethostname()))
    except Exception:
        pass

    def score(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            try:
                second = int(ip.split(".")[1])
                if 16 <= second <= 31:
                    return 2
            except Exception:
                pass
        return 3

    seen: set = set()
    lan_ips: List[str] = []
    for ip in ips:
        if ip in seen or ip.startswith("127.") or ip == "0.0.0.0":
            continue
        seen.add(ip)
        lan_ips.append(ip)
    lan_ips.sort(key=score)
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"

    return {
        "lan_ip": primary_ip,
        "lan_ips": lan_ips,
        "port": port,
        "url": f"http://{primary_ip}:{port}/",
        # 默认指向 dashboard — 该页有 FullScreenPosterWall widget 可一键进入全屏
        "dashboard_url": f"http://{primary_ip}:{port}/#/dashboard",
        "hint": (
            "在同一 Wi-Fi / 局域网内用其他设备浏览器打开 URL；"
            "先用 MoviePilot 账号登录，然后进入 Dashboard / 插件列表 → 全屏海报墙 → 全屏播放。"
        ),
    }


class FullScreenPosterWall(_PluginBase):
    """全屏海报墙插件：以 5 种屏幕保护动效全屏展示推荐媒体海报。"""

    # ─── 插件元数据 ─────────────────────────────────────────
    plugin_name = "全屏海报墙"
    plugin_desc = "这是一个全屏海报墙插件，让所有终端可以播放精美的电影海报。抓取 MoviePilot 推荐媒体（流行趋势/TMDB热门电影/TMDB热门电视剧）的海报图片，以照片/拼贴/纵深穿梭/滑动面板/浮动/怀旧冲印/光舞等多种动效全屏展示，支持局域网海报墙页面。"
    plugin_icon = "fullscreenposterwall.png"
    plugin_version = "1.14.2"
    plugin_label = "媒体展示"
    plugin_author = "ltdstudio"
    plugin_config_prefix = "fullscreenposterwall_"
    plugin_order = 50
    auth_level = 1

    # ─── 运行时状态 ─────────────────────────────────────────
    _enabled: bool = False
    _sources: List[str] = []
    _effect: str = "photos"
    _interval: int = 8
    _image_type: str = "backdrop"
    _poster_count: int = 60
    _refresh_minutes: int = 60
    _autoplay: bool = True
    _show_dashboard: bool = True
    _shuffle: bool = False
    _hide_text: bool = False
    _recommend_chain: Optional[RecommendChain] = None
    _cache: List[Dict[str, Any]] = []
    _cache_time: float = 0.0
    # 当前缓存周期内是否已尝试过 Logo 补抓（防止缓存命中时反复外呼 Fanart/TMDB）
    _logo_enrich_done: bool = False

    def init_plugin(self, config: dict | None = None) -> None:
        """根据持久化配置初始化运行状态。"""
        self.stop_service()
        self._recommend_chain = RecommendChain()
        self._cache = []
        self._cache_time = 0.0
        if not config:
            return

        self._enabled = bool(config.get("enabled", False))
        sources = config.get("sources") or ["trending", "tmdb_movies", "tmdb_tvs"]
        if isinstance(sources, str):
            sources = [s for s in sources.split(",") if s]
        self._sources = list(sources)
        self._effect = str(config.get("effect") or "photos")
        try:
            self._interval = max(3, min(30, int(config.get("interval") or 8)))
        except (TypeError, ValueError):
            self._interval = 8
        self._image_type = str(config.get("image_type") or "backdrop")
        try:
            pc = int(config.get("poster_count") or 60)
            self._poster_count = pc if pc in (30, 60, 120, 180, 240) else 60
        except (TypeError, ValueError):
            self._poster_count = 60
        try:
            self._refresh_minutes = max(5, min(1440, int(config.get("refresh_minutes") or 60)))
        except (TypeError, ValueError):
            self._refresh_minutes = 60
        self._autoplay = bool(config.get("autoplay", True))
        self._show_dashboard = bool(config.get("show_dashboard", True))
        self._shuffle = bool(config.get("shuffle", False))
        self._hide_text = bool(config.get("hide_text", False))

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    def get_form(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Vue 联邦模式下设置弹窗由前端 Config.vue 渲染，后端只返回默认配置数据。

        必须返回一个 (空 schema, 默认 model) 元组——schema 为空 list，
        MoviePilot 会用联邦方式加载 './Config' 暴露组件。
        """
        return [], self._default_config()

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "enabled": False,
            "sources": ["trending", "tmdb_movies", "tmdb_tvs"],
            "effect": "photos",
            "image_type": "backdrop",
            "interval": 8,
            "poster_count": 60,
            "refresh_minutes": 60,
            "autoplay": True,
            "show_dashboard": True,
            "shuffle": False,
            "hide_text": False,
        }

    # ─── 渲染模式：Vue 联邦 ─────────────────────────────────
    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明插件使用 Vue 联邦组件渲染。"""
        return "vue", "dist/assets"

    def get_page(self) -> List[dict]:
        """Vue 模式下详情页由远程 Page 组件渲染。"""
        return []

    # 注意：不在此处添加 get_sidebar_nav() —— 用户明确要求"主要导航菜单左边不要出现"。

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """声明一个仪表板窗口：仅在插件启用且用户开启 dashboard 时返回。"""
        if not self.get_state():
            return None
        if not bool(self._show_dashboard):
            return None
        return [{"key": "preview", "name": "全屏海报墙 · 实时预览"}]

    def get_dashboard(
        self, key: str = "", **kwargs
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]]:
        """仪表板组件。

        返回 (cols, header, elements) 三元组。MoviePilot 后端会把 cols/header
        转成 DashboardItem，elements 是要注入的 RenderProps 列表。
        """
        if not self.get_state():
            return None
        if not bool(self._show_dashboard):
            return None
        if key and key != "preview":
            return None

        subtitle_parts = [
            f"{self._effect}",
            f"每 {self._interval} 秒切换",
            self._image_type,
        ]
        return (
            {"cols": 12, "sm": 6, "md": 4},
            {
                "title": "全屏海报墙 · 实时预览",
                "subtitle": " · ".join(subtitle_parts),
                "refresh": max(60, self._refresh_minutes * 60),
                "border": True,
            },
            [],
        )

    # ─── 供前端调用的 API（Vue 联邦用 bear 鉴权） ────────────
    def get_api(self) -> List[Dict[str, Any]]:
        """返回供前端 Vue 调用的 API 列表。

        MoviePilot 通过 ``app.add_api_route(**api)`` 动态注册这些路由。
        FastAPI 的 ``add_api_route`` 接受 ``endpoint``（可调用对象）和
        ``methods``（HTTP 方法列表）。
        """
        return [
            {
                "path": "/config",
                "endpoint": self.api_get_config,
                "methods": ["GET"],
                "summary": "获取当前插件配置",
                "auth": "bear",
            },
            {
                "path": "/config",
                "endpoint": self.api_update_config,
                "methods": ["PUT"],
                "summary": "更新插件配置",
                "auth": "bear",
            },
            {
                "path": "/recommend",
                "endpoint": self.api_get_recommend,
                "methods": ["GET"],
                "summary": "获取推荐媒体列表",
                "auth": "bear",
            },
            {
                "path": "/lan-info",
                "endpoint": self.api_lan_info,
                "methods": ["GET"],
                "summary": "获取局域网访问信息",
                "auth": "bear",
            },
            {
                # 局域网独立全屏页所需数据：一次性打包 config + items，跳过认证
                "path": "/public-data",
                "endpoint": self.api_public_data,
                "methods": ["GET"],
                "summary": "局域网独立页用的公开数据接口（无认证）",
                "auth": "bear",
                "allow_anonymous": True,
            },
            {
                # 局域网独立全屏 SPA 入口 HTML —— 不需登录
                "path": "/lan-wall",
                "endpoint": self.api_lan_wall,
                "methods": ["GET"],
                "summary": "局域网独立全屏播放 HTML 页",
                "auth": "bear",
                "allow_anonymous": True,
            },
        ]

    def api_lan_info(self, request: Request = None) -> Dict[str, Any]:
        """返回局域网访问信息。

        - 优先使用客户端实际访问的 Host 头（随环境变化：localhost / LAN IP / 域名），
          socket 探测仅作为兜底（Docker 容器内探测到的是网桥 IP，不可用于分享）
        - lan_ip / lan_ips：探测到的网卡 IP（参考用）
        - lan_wall_url：独立的局域网全屏播放页 URL（其他设备直接打开即看全屏）
        """
        info = _detect_lan_info()
        try:
            host = ""
            scheme = "http"
            if request is not None:
                host = request.headers.get("host") or ""
                try:
                    scheme = request.url.scheme or "http"
                except Exception:
                    scheme = "http"
            if host:
                base = f"{scheme}://{host}"
                info["url"] = f"{base}/"
                info["dashboard_url"] = f"{base}/#/dashboard"
                hostname, _, port_str = host.partition(":")
                info["lan_ip"] = hostname
                if port_str:
                    try:
                        info["port"] = int(port_str)
                    except ValueError:
                        pass
        except Exception:
            pass
        info["lan_wall_url"] = f"{info['url'].rstrip('/')}/api/v1/plugin/FullScreenPosterWall/lan-wall"
        return info

    def api_public_data(self) -> Dict[str, Any]:
        """公开接口（无认证）—— 返回独立全屏页需要的配置 + 海报列表。

        一次性打包 config + items，前端一次 fetch 即可开始播放。
        数据走 cache（refresh_minutes），启用时立刻返回，禁用时返回空配置。
        """
        cfg = {
            "enabled": self._enabled,
            "effect": self._effect,
            "interval": self._interval,
            "image_type": self._image_type,
            "shuffle": self._shuffle,
            "hide_text": self._hide_text,
            "tmdb_image_domain": "https://image.tmdb.org/t/p/original",
        }
        if not self._enabled:
            return {"config": cfg, "items": []}
        # 复用 recommend 的缓存逻辑
        rec = self.api_get_recommend()
        return {"config": cfg, "items": rec.get("data", [])}

    def api_lan_wall(self) -> Any:
        """返回独立全屏播放 HTML（无认证）。HTML 文件随 plugin 一起发布到 dist/lan-wall.html。

        在浏览器里直接打开这个 URL 即可看到完整动效，不需要登录 MoviePilot。
        """
        from fastapi.responses import HTMLResponse
        from pathlib import Path

        # plugin dist 在 MoviePilot 容器里的真实路径：/config/local-plugins/plugins.v2/<id>/dist/
        # 但 register_plugin_api 时 plugin 代码被复制到 /app/app/plugins/<id>/，所以 dist 在那里
        candidates = [
            Path("/app/app/plugins/fullscreenposterwall/dist/lan-wall.html"),
            Path("/config/local-plugins/plugins.v2/fullscreenposterwall/dist/lan-wall.html"),
            Path(__file__).parent / "dist" / "lan-wall.html",
        ]
        for p in candidates:
            if p.exists():
                html = p.read_text(encoding="utf-8")
                return HTMLResponse(html)
        # 文件丢失兜底：返回一段错误 HTML
        return HTMLResponse(
            "<h1 style='color:#fff;background:#000;font-family:sans-serif;padding:24px;'>"
            "lan-wall.html 不存在。请重新安装插件以部署最新的前端资源。"
            "</h1>",
            status_code=500,
        )

    def api_get_config(self) -> Dict[str, Any]:
        """返回给前端 Vue 的运行时配置。"""
        return {
            "enabled": self._enabled,
            "sources": self._sources,
            "effect": self._effect,
            "interval": self._interval,
            "image_type": self._image_type,
            "poster_count": self._poster_count,
            "refresh_minutes": self._refresh_minutes,
            "autoplay": self._autoplay,
            "show_dashboard": self._show_dashboard,
            "shuffle": self._shuffle,
            "hide_text": self._hide_text,
            "tmdb_image_domain": "https://image.tmdb.org/t/p/original",
        }

    def api_update_config(
        self, config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """接收前端 PUT 更新，持久化并重新初始化插件。"""
        if not config or not isinstance(config, dict):
            return {"success": False, "message": "请求体不是合法对象"}
        merged = {**self.api_get_config(), **config}
        merged["enabled"] = bool(merged.get("enabled", False))
        if isinstance(merged.get("sources"), str):
            merged["sources"] = [s for s in merged["sources"].split(",") if s]
        if not isinstance(merged.get("sources"), list):
            merged["sources"] = ["trending", "tmdb_movies", "tmdb_tvs"]
        try:
            merged["interval"] = max(3, min(30, int(merged.get("interval") or 8)))
        except (TypeError, ValueError):
            merged["interval"] = 8
        try:
            pc = int(merged.get("poster_count") or 60)
            merged["poster_count"] = pc if pc in (30, 60, 120, 180, 240) else 60
        except (TypeError, ValueError):
            merged["poster_count"] = 60
        try:
            merged["refresh_minutes"] = max(
                5, min(1440, int(merged.get("refresh_minutes") or 60))
            )
        except (TypeError, ValueError):
            merged["refresh_minutes"] = 60
        ok = self.update_config(merged)
        if not ok:
            return {"success": False, "message": "持久化失败"}
        self.init_plugin(merged)
        self._cache = []
        self._cache_time = 0.0
        self._logo_enrich_done = False
        return {"success": True, "data": merged}

    def api_get_recommend(
        self, force: bool = False, shuffle: bool = False
    ) -> Dict[str, Any]:
        """拉取推荐媒体，缓存 N 分钟。

        参数:
            force: 强制刷新（绕过缓存）
            shuffle: 是否乱序；前端默认根据 config.shuffle 字段决定，
                     也可以用 ?shuffle=true 临时覆盖。
        """
        import time

        now = time.time()
        if (
            not force
            and self._cache
            and (now - self._cache_time) < self._refresh_minutes * 60
        ):
            # 切到 logo 模式但缓存里没有 logo_path 时，补抓一次（每个缓存周期仅尝试一次，
            # 无结果的条目在下个刷新周期前不再重复外呼，避免绕过 refresh_minutes 频率约束）
            if (
                self._image_type == "logo"
                and not self._logo_enrich_done
                and any(not it.get("logo_path") for it in self._cache)
            ):
                self._logo_enrich_done = True
                self._enrich_logos(self._cache)
            data = list(self._cache)
            should_shuffle = shuffle or bool(self._shuffle)
            if should_shuffle:
                import random

                random.shuffle(data)
            return {"success": True, "data": data, "cached": True}

        chain = self._recommend_chain or RecommendChain()
        items: List[Dict[str, Any]] = []
        # 按目标张数计算每源需要的页数（每页约 20 条）
        n_sources = max(1, len(self._sources))
        pages = max(1, -(-self._poster_count // (20 * n_sources)))  # 向上取整
        loop = asyncio.new_event_loop()
        try:
            for page in range(1, pages + 1):
                for source in self._sources:
                    try:
                        medias = loop.run_until_complete(
                            self._fetch_source(chain, source, page=page)
                        )
                    except Exception:
                        continue
                    for m in medias or []:
                        item = self._normalize(m, source)
                        if item:
                            items.append(item)
        finally:
            loop.close()

        seen = set()
        unique: List[Dict[str, Any]] = []
        for it in items:
            key = (it.get("source"), it.get("tmdb_id") or it.get("title"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(it)

        # 按配置的目标张数截断
        unique = unique[: self._poster_count]

        # image_type=logo 时，为每条数据抓取 TMDB 片名 Logo（带电影名字的艺术字图）
        if self._image_type == "logo":
            self._enrich_logos(unique)

        self._cache = unique
        self._cache_time = now
        # 抓取阶段已按当前 image_type 处理过 Logo，本缓存周期标记为已尝试
        self._logo_enrich_done = self._image_type == "logo"
        data = list(unique)
        should_shuffle = shuffle or bool(self._shuffle)
        if should_shuffle:
            import random

            random.shuffle(data)
        return {"success": True, "data": data, "cached": False, "count": len(data)}

    async def _fetch_source(
        self, chain: RecommendChain, source: str, page: int = 1
    ) -> Optional[List[MediaInfo]]:
        """根据 source 拉取对应类型的推荐（支持分页）。"""
        if source == "trending":
            return await chain.async_tmdb_trending(page=page)
        if source == "tmdb_movies":
            return await chain.async_tmdb_movies(page=page)
        if source == "tmdb_tvs":
            return await chain.async_tmdb_tvs(page=page)
        return None

    @staticmethod
    def _normalize(media: MediaInfo, source: str) -> Optional[Dict[str, Any]]:
        """把 MediaInfo 转成前端友好的 dict。"""
        try:
            data = media.to_dict() if hasattr(media, "to_dict") else dict(media)
        except Exception:
            data = {}
        if not data:
            return None
        return {
            "source": source,
            "title": data.get("title") or data.get("title_year") or "",
            "year": data.get("year") or "",
            "type": data.get("type") or "",
            "overview": data.get("overview") or "",
            "vote_average": data.get("vote_average") or 0,
            "poster_path": data.get("poster_path"),
            "backdrop_path": data.get("backdrop_path"),
            "logo_path": data.get("logo_path"),
            "thumb_path": data.get("thumb_path"),
            "fanart_poster_path": data.get("fanart_poster_path"),
            "tmdb_id": data.get("tmdb_id"),
            "release_date": data.get("release_date"),
        }

    @staticmethod
    def _enrich_logos(items: List[Dict[str, Any]]) -> None:
        """为每条数据抓取「带 Logo 的图」，与 MoviePilot 媒体整理刮削同源：
        走内置 Fanart.tv 模块（默认开启、自带公共 key、中文优先）——
          thumb.jpg  = 原生带 Logo 的横图；poster.jpg = 带片名海报；logo.png = 透明艺术字
        Fanart 没有 logo 时退回 TMDB images 接口。线程池并发，单条失败跳过。"""
        try:
            from concurrent.futures import ThreadPoolExecutor
            from app.modules.fanart import FanartModule
            from app.core.context import MediaInfo
            from app.schemas.types import MediaType
        except Exception:
            return
        try:
            fanart = FanartModule()
        except Exception:
            fanart = None
        try:
            from app.modules.themoviedb.tmdbapi import TmdbApi
            tmdb_api = TmdbApi()
        except Exception:
            tmdb_api = None

        def pick_key(d: Dict[str, Any], stem: str) -> Optional[str]:
            for k, v in d.items():
                if k.startswith(stem):
                    return v
            return None

        def fetch_one(it: Dict[str, Any]) -> None:
            tid = it.get("tmdb_id")
            if not tid:
                return
            is_tv = (it.get("type") or "") == "电视剧"
            # 1) Fanart.tv（MoviePilot 官方刮削链路）
            if fanart:
                try:
                    mi = MediaInfo()
                    mi.type = MediaType.TV if is_tv else MediaType.MOVIE
                    mi.tmdb_id = int(tid)
                    imgs = fanart.metadata_img(mi) or {}
                    thumb = pick_key(imgs, "thumb.")
                    logo = pick_key(imgs, "logo.")
                    poster = pick_key(imgs, "poster.")
                    if thumb:
                        it["thumb_path"] = thumb
                    if logo:
                        it["logo_path"] = logo
                    if poster:
                        it["fanart_poster_path"] = poster
                except Exception:
                    pass
            # 2) TMDB images 兜底透明 logo（Fanart 缺 logo 时）
            if not it.get("logo_path") and tmdb_api:
                try:
                    imgs = (tmdb_api.get_tv_images(int(tid)) if is_tv
                            else tmdb_api.get_movie_images(int(tid)))
                    logos = (imgs or {}).get("logos") or []

                    def score(l: Dict[str, Any]):
                        lang = l.get("iso_639_1")
                        lp = 0 if lang == "zh" else (1 if lang == "en" else 2)
                        return (lp, -(l.get("vote_average") or 0))

                    if logos:
                        fp = sorted(logos, key=score)[0].get("file_path")
                        if fp:
                            it["logo_path"] = fp
                except Exception:
                    pass

        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(fetch_one, items))
        except Exception:
            pass

    # ─── 资源清理 ────────────────────────────────────────────
    def stop_service(self) -> None:
        """停止插件后台服务并释放资源。"""
        self._enabled = False
        self._recommend_chain = None
        self._cache = []
        self._cache_time = 0.0

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表（暂不提供）。"""
        return []
