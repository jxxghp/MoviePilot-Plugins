"""
全屏海报墙插件。

从 MoviePilot 推荐媒体接口（流行趋势 / TMDB 热门电影 / TMDB 热门电视剧）
抓取海报图片，通过 Vue 联邦页面以五种屏幕保护动效全屏展示。
"""
from __future__ import annotations

import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.chain.recommend import RecommendChain
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from fastapi import Request, Response


# 走插件代理的图床白名单：
#  - doubanio/douban：Referer 防盗链（直链 403/418）
#  - anilist.co：无 UA 直链 403
#  - TMDB/Fanart：直链虽可用，但走服务器代理可多设备共享磁盘缓存 7 天、
#    并借 MoviePilot 的代理配置绕过浏览器侧 CDN 不可达（Fanart 尤其明显）
_PROXY_IMAGE_HOSTS: Tuple[str, ...] = (
    "doubanio.com", "douban.com", "anilist.co",
    "image.tmdb.org", "assets.fanart.tv", "images.fanart.tv",
)


def _proxy_image_url(
    url: Optional[str],
    tmdb_domain: str = "",
) -> Optional[str]:
    """图床 URL → 本插件免登录代理（白名单内主机）。

    相对路径（/abc.jpg）先按 TMDB 域名补全再判断。豆瓣顺带
    m_ratio→l_ratio 升清晰度。已是 /api/ 代理路径的原样返回。
    代理路径用相对地址，lan-wall 在任何主机/端口都能用。
    """
    if not url or not isinstance(url, str):
        return url
    if url.startswith("/api/"):
        return url
    full = url
    if url.startswith("/"):
        full = (tmdb_domain or "https://image.tmdb.org/t/p/original") + url
    if not full.startswith("http"):
        return url
    if not any(h in full for h in _PROXY_IMAGE_HOSTS):
        return url
    upgraded = full.replace("s_ratio_poster", "l_ratio_poster").replace(
        "m_ratio_poster", "l_ratio_poster"
    )
    return (
        "/api/v1/plugin/FullScreenPosterWall/img?url="
        + quote(upgraded, safe="")
    )


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
    plugin_icon = "https://ltdstudio.github.io/posterwall/icons/fullscreenposterwall.png"
    plugin_version = "1.15.11"
    plugin_label = "媒体展示"
    plugin_author = "ltdstudio"
    author_url = "https://github.com/ltdstudio/posterwall"
    plugin_config_prefix = "fullscreenposterwall_"
    plugin_order = 50
    auth_level = 1

    # 内置推荐数据源目录：(api_path, 名称, Chain, 方法名, 天然类型 movie/tv/mixed)
    # 与 MoviePilot 探索页的媒体源对齐（RecommendChain 13 源 + AniListChain 2 源）；
    # 运行时按 hasattr 逐个校验，系统升级增减方法时自动跟随。
    _BUILTIN_SOURCES: Tuple[Tuple[str, str, str, str, str], ...] = (
        ("recommend/tmdb_trending", "流行趋势", "recommend", "tmdb_trending", "mixed"),
        ("recommend/douban_showing", "正在热映", "recommend", "douban_movie_showing", "movie"),
        ("recommend/bangumi_calendar", "Bangumi每日放送", "recommend", "bangumi_calendar", "tv"),
        ("recommend/tmdb_movies", "TMDB热门电影", "recommend", "tmdb_movies", "movie"),
        ("recommend/tmdb_tvs", "TMDB热门电视剧", "recommend", "tmdb_tvs", "tv"),
        ("recommend/douban_movie_hot", "豆瓣热门电影", "recommend", "douban_movie_hot", "movie"),
        ("recommend/douban_tv_hot", "豆瓣热门电视剧", "recommend", "douban_tv_hot", "tv"),
        ("recommend/douban_tv_animation", "豆瓣热门动漫", "recommend", "douban_tv_animation", "tv"),
        ("recommend/douban_movies", "豆瓣最新电影", "recommend", "douban_movies", "movie"),
        ("recommend/douban_tvs", "豆瓣最新电视剧", "recommend", "douban_tvs", "tv"),
        ("recommend/douban_movie_top250", "豆瓣电影TOP250", "recommend", "douban_movie_top250", "movie"),
        ("recommend/douban_tv_weekly_chinese", "豆瓣国产剧集榜", "recommend", "douban_tv_weekly_chinese", "tv"),
        ("recommend/douban_tv_weekly_global", "豆瓣全球剧集榜", "recommend", "douban_tv_weekly_global", "tv"),
        ("anilist/trending", "AniList趋势", "anilist", "trending", "tv"),
        ("anilist/popular_this_season", "AniList本季人气", "anilist", "popular_this_season", "tv"),
    )

    # ─── 运行时状态 ─────────────────────────────────────────
    _enabled: bool = False
    # 动态推荐数据源：{api_path: ["movie"/"tv", ...]}，值为空列表 = 停用该源
    _source_config: Dict[str, List[str]] = {}
    _anilist_chain: Any = None
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
        self._source_config = self._normalize_source_config(config)
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

    @classmethod
    def _default_source_config(cls) -> Dict[str, List[str]]:
        """默认启用的数据源（对应旧版 trending/tmdb_movies/tmdb_tvs）。"""
        return {
            "recommend/tmdb_trending": ["movie", "tv"],
            "recommend/tmdb_movies": ["movie", "tv"],
            "recommend/tmdb_tvs": ["movie", "tv"],
        }

    # 旧版 sources 简写 → api_path 映射（配置迁移用）
    _LEGACY_SOURCE_MAP: Dict[str, str] = {
        "trending": "recommend/tmdb_trending",
        "tmdb_movies": "recommend/tmdb_movies",
        "tmdb_tvs": "recommend/tmdb_tvs",
    }

    @classmethod
    def _normalize_source_config(cls, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """把配置里的数据源选择规整为 {api_path: [movie/tv]}。

        兼容三种历史形态：
          1. 新版 source_config dict —— 直接使用（非法值剔除）；
          2. 旧版 sources list/str（trending 等简写）—— 映射迁移；
          3. 啥都没有 —— 默认三源。
        """
        raw = config.get("source_config")
        if isinstance(raw, dict) and raw:
            result: Dict[str, List[str]] = {}
            for api_path, types in raw.items():
                if not isinstance(api_path, str) or not api_path:
                    continue
                if isinstance(types, str):
                    types = [t for t in types.split(",") if t]
                if not isinstance(types, list):
                    types = []
                clean = [t for t in types if t in ("movie", "tv")]
                if clean:
                    result[api_path] = clean
            if result:
                return result
        legacy = config.get("sources")
        if isinstance(legacy, str):
            legacy = [s for s in legacy.split(",") if s]
        if isinstance(legacy, list) and legacy:
            result = {}
            for s in legacy:
                api_path = cls._LEGACY_SOURCE_MAP.get(str(s)) or (
                    str(s) if str(s).startswith(("recommend/", "plugin/", "anilist/")) else None
                )
                if api_path:
                    result[api_path] = ["movie", "tv"]
            if result:
                return result
        return cls._default_source_config()

    # ─── 动态推荐数据源 ─────────────────────────────────────
    def _available_sources(self) -> List[Dict[str, Any]]:
        """枚举当前系统可用的推荐数据源（动态）。

        内置源：按 _BUILTIN_SOURCES 目录逐个 hasattr 校验 RecommendChain
        （MoviePilot 升级增减方法时自动跟随）；
        第三方源：广播 ChainEventType.RecommendSource 事件，
        其他插件（如 IMDb源）注册的源自动出现，卸载后自动消失。
        """
        sources: List[Dict[str, Any]] = []
        for api_path, name, chain_key, method, nat in self._BUILTIN_SOURCES:
            chain = self._chain_for(chain_key)
            if chain is not None and hasattr(chain, method):
                sources.append({
                    "api_path": api_path,
                    "name": name,
                    "builtin": True,
                    "nat": nat,
                })
        try:
            from app.core.event import eventmanager
            from app.schemas import RecommendSourceEventData
            from app.schemas.types import ChainEventType

            event_data = RecommendSourceEventData()
            event = eventmanager.send_event(
                ChainEventType.RecommendSource, event_data
            )
            if event and event.event_data:
                extras = getattr(event.event_data, "extra_sources", None) or []
                for s in extras:
                    api_path = getattr(s, "api_path", None) or (
                        s.get("api_path") if isinstance(s, dict) else None
                    )
                    name = getattr(s, "name", None) or (
                        s.get("name") if isinstance(s, dict) else None
                    )
                    category = getattr(s, "type", None) or (
                        s.get("type") if isinstance(s, dict) else ""
                    ) or ""
                    if not api_path or not name:
                        continue
                    if any(x["api_path"] == api_path for x in sources):
                        continue
                    cat = str(category).lower()
                    nat = ("movie" if "movie" in cat
                           else "tv" if ("tv" in cat or "anime" in cat)
                           else "mixed")
                    sources.append({
                        "api_path": api_path,
                        "name": str(name),
                        "builtin": False,
                        "nat": nat,
                    })
        except Exception:
            pass
        return sources

    def api_get_sources(self) -> Dict[str, Any]:
        """供配置页动态渲染：可用数据源 + 当前选择。"""
        try:
            return {
                "success": True,
                "data": {
                    "sources": self._available_sources(),
                    "selected": self._source_config
                    or self._default_source_config(),
                },
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _chain_for(self, chain_key: str) -> Any:
        """按目录 key 取对应 Chain 实例（anilist 懒加载，导入失败返回 None）。"""
        if chain_key == "anilist":
            if self._anilist_chain is None:
                try:
                    from app.chain.anilist import AniListChain

                    self._anilist_chain = AniListChain()
                except Exception:
                    return None
            return self._anilist_chain
        return self._recommend_chain or RecommendChain()

    def _fetch_source_dicts(
        self, api_path: str, page: int = 1
    ) -> List[Dict[str, Any]]:
        """按 api_path 拉取一页推荐数据（dict 列表）。

        内置源直接调对应 Chain 同步方法；第三方插件源走内部 API
        （与 MoviePilot 工作流「获取媒体数据」动作同一套做法）。
        """
        for bp, _name, chain_key, method, _nat in self._BUILTIN_SOURCES:
            if bp == api_path:
                chain = self._chain_for(chain_key)
                func = getattr(chain, method, None) if chain else None
                if not func:
                    return []
                result = func(page=page) or []
                out: List[Dict[str, Any]] = []
                for x in result:
                    if isinstance(x, dict):
                        out.append(dict(x))
                    elif hasattr(x, "to_dict"):
                        # AniListChain 返回 MediaInfo 对象
                        try:
                            out.append(dict(x.to_dict()))
                        except Exception:
                            pass
                return out
        # 第三方插件源：内部 API 调用
        try:
            from app.core.config import settings
            from app.utils.http import RequestUtils

            sep = "&" if "?" in api_path else "?"
            url = (
                f"http://127.0.0.1:{settings.PORT}/api/v1/{api_path}"
                f"{sep}token={settings.API_TOKEN}"
            )
            # 第三方插件源路由多为 GET-only（如 IMDb源），POST 会 405
            res = RequestUtils(timeout=15).get_res(url)
            if res:
                data = res.json()
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
        return []

    def _build_meta(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """本轮拉取状态：图片/Logo 就绪数。补抓是同步的——响应返回时本轮已结束。"""
        logo_mode = self._image_type == "logo"
        return {
            "total": len(items),
            "with_image": sum(
                1 for i in items
                if i.get("backdrop_path") or i.get("poster_path") or i.get("thumb_path")
            ),
            "with_logo": (
                sum(1 for i in items if i.get("logo_path")) if logo_mode else 0
            ),
            "logo_mode": logo_mode,
            "images_done": True,
            "logos_done": (not logo_mode) or self._logo_enrich_done,
        }

    # 参与代理改写的图字段
    _IMAGE_FIELDS: Tuple[str, ...] = (
        "poster_path", "backdrop_path", "logo_path",
        "thumb_path", "fanart_poster_path",
    )

    def _proxy_items(self, items: List[Dict[str, Any]]) -> None:
        """把条目的全部图字段改写到插件代理（幂等）。"""
        for it in items:
            for field in self._IMAGE_FIELDS:
                v = it.get(field)
                if v:
                    it[field] = _proxy_image_url(v)

    @staticmethod
    def _match_types(item: Dict[str, Any], types: List[str]) -> bool:
        """条目类型是否命中所选（type 缺失时放行，避免误杀）。"""
        t = str(item.get("type") or "")
        if not t:
            return True
        if "电影" in t:
            return "movie" in types
        if "电视剧" in t or "剧集" in t:
            return "tv" in types
        return True

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "enabled": False,
            "source_config": FullScreenPosterWall._default_source_config(),
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
                "path": "/sources",
                "endpoint": self.api_get_sources,
                "methods": ["GET"],
                "summary": "枚举可用推荐数据源（内置+第三方动态）",
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
            {
                "path": "/img",
                "endpoint": self.api_proxy_image,
                "methods": ["GET"],
                "summary": "豆瓣等防盗链图源的免登录代理（白名单域名）",
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
            return {"config": cfg, "items": [], "meta": self._build_meta([])}
        # 复用 recommend 的缓存逻辑
        rec = self.api_get_recommend()
        return {"config": cfg, "items": rec.get("data", []), "meta": rec.get("meta")}

    def api_proxy_image(self, url: str = "") -> Any:
        """免登录图片代理：只放行白名单域名（豆瓣图床防盗链）。

        豆瓣 img*.doubanio.com 会按 Referer 拦截浏览器直链（红叉）。
        拉图直接复用 MoviePilot 自己的 ImageHelper（doubanio 自动带
        Referer + 直连不走代理 + 磁盘缓存），与系统刮削/探索页同一条链路。
        """
        url = (url or "").strip()
        if not url.startswith("https://"):
            return Response(status_code=400, content="invalid url")
        try:
            host = url.split("/", 3)[2].lower()
        except Exception:
            return Response(status_code=400, content="invalid url")
        if not any(host == d or host.endswith("." + d) for d in _PROXY_IMAGE_HOSTS):
            return Response(status_code=403, content="host not allowed")
        try:
            from app.helper.image import ImageHelper

            result = ImageHelper().fetch_image_with_mime_type(
                url=url, use_cache=True
            )
            if not result:
                return Response(status_code=502, content="upstream error")
            content, ctype = result
            return Response(
                content=content,
                media_type=ctype,
                headers={
                    "Cache-Control": "public, max-age=86400, immutable",
                    "Content-Length": str(len(content)),
                },
            )
        except Exception:
            return Response(status_code=502, content="fetch failed")

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
            "source_config": self._source_config
            or self._default_source_config(),
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
        merged["source_config"] = self._normalize_source_config(merged)
        merged.pop("sources", None)
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
                self._proxy_items(self._cache)
            data = list(self._cache)
            should_shuffle = shuffle or bool(self._shuffle)
            if should_shuffle:
                import random

                random.shuffle(data)
            return {"success": True, "data": data, "cached": True, "meta": self._build_meta(data)}

        source_config = self._source_config or self._default_source_config()
        active_sources = [p for p, t in source_config.items() if t]
        items: List[Dict[str, Any]] = []
        # 按目标张数计算每源需要的页数（每页约 20 条）
        n_sources = max(1, len(active_sources))
        pages = max(1, -(-self._poster_count // (20 * n_sources)))  # 向上取整
        for page in range(1, pages + 1):
            for api_path in active_sources:
                types = source_config.get(api_path) or []
                try:
                    dicts = self._fetch_source_dicts(api_path, page=page)
                except Exception:
                    continue
                for d in dicts:
                    if not self._match_types(d, types):
                        continue
                    item = self._normalize(d, api_path)
                    if item:
                        items.append(item)

        seen = set()
        unique: List[Dict[str, Any]] = []
        for it in items:
            # 多源重叠时按 tmdb_id 去重（无 tmdb_id 退回 源+标题）
            key = it.get("tmdb_id") or (it.get("source"), it.get("title"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(it)

        # 按配置的目标张数截断
        unique = unique[: self._poster_count]

        # image_type=logo 时，为每条数据抓取 TMDB 片名 Logo（带电影名字的艺术字图）
        if self._image_type == "logo":
            self._enrich_logos(unique)

        # 全部图字段统一走服务器代理（多设备共享 7 天磁盘缓存，
        # 且绕过浏览器侧 CDN 不可达/防盗链）；幂等，已是 /api/ 的跳过
        self._proxy_items(unique)

        self._cache = unique
        self._cache_time = now
        # 抓取阶段已按当前 image_type 处理过 Logo，本缓存周期标记为已尝试
        self._logo_enrich_done = self._image_type == "logo"
        data = list(unique)
        should_shuffle = shuffle or bool(self._shuffle)
        if should_shuffle:
            import random

            random.shuffle(data)
        return {"success": True, "data": data, "cached": False, "count": len(data), "meta": self._build_meta(data)}

    @staticmethod
    def _normalize(data: Any, source: str) -> Optional[Dict[str, Any]]:
        """把推荐条目（dict 或 MediaInfo）转成前端友好的 dict。"""
        try:
            if hasattr(data, "to_dict"):
                data = data.to_dict()
            data = dict(data)
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
