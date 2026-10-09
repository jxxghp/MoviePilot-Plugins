"""FullScreenPosterWall 插件单测：纯函数与类级合同，不依赖宿主运行态实例。

覆盖：动态数据源配置迁移、类型过滤、图床代理改写、内置源目录完整性、版本元数据。
插件的 Chain/网络行为在真实 V3 宿主另有集成验证，这里只锁定纯逻辑合同。
"""
from app.plugins.fullscreenposterwall import (
    FullScreenPosterWall,
    _proxy_image_url,
)


class TestProxyImageUrl:
    """图床代理改写：白名单内主机改写到插件免登录代理，其余原样。"""

    def test_douban_rewritten_and_upgraded(self):
        url = "https://img1.doubanio.com/view/photo/m_ratio_poster/public/p1.webp"
        out = _proxy_image_url(url)
        assert out.startswith("/api/v1/plugin/FullScreenPosterWall/img?url=")
        assert "l_ratio_poster" in out
        assert "m_ratio_poster" not in out

    def test_anilist_rewritten(self):
        out = _proxy_image_url("https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/x.jpg")
        assert out.startswith("/api/v1/plugin/FullScreenPosterWall/img?url=")

    def test_tmdb_full_url_rewritten(self):
        out = _proxy_image_url("https://image.tmdb.org/t/p/original/abc.jpg")
        assert out.startswith("/api/v1/plugin/FullScreenPosterWall/img?url=")

    def test_tmdb_relative_path_completed_then_rewritten(self):
        out = _proxy_image_url("/abc.jpg")
        assert "https%3A%2F%2Fimage.tmdb.org" in out

    def test_non_whitelisted_passthrough(self):
        url = "https://example.com/x.jpg"
        assert _proxy_image_url(url) == url

    def test_already_proxied_idempotent(self):
        url = "/api/v1/plugin/FullScreenPosterWall/img?url=https%3A%2F%2Fimg1.doubanio.com%2Fx.webp"
        assert _proxy_image_url(url) == url

    def test_empty_and_none(self):
        assert _proxy_image_url(None) is None
        assert _proxy_image_url("") == ""


class TestMatchTypes:
    """按来源勾选的电影/电视剧过滤。"""

    def test_movie_only(self):
        assert FullScreenPosterWall._match_types({"type": "电影"}, ["movie"])
        assert not FullScreenPosterWall._match_types({"type": "电视剧"}, ["movie"])

    def test_tv_only(self):
        assert FullScreenPosterWall._match_types({"type": "电视剧"}, ["tv"])
        assert not FullScreenPosterWall._match_types({"type": "电影"}, ["tv"])

    def test_unknown_type_kept(self):
        # 类型缺失的条目放行，避免第三方源被误杀
        assert FullScreenPosterWall._match_types({"type": ""}, ["movie"])
        assert FullScreenPosterWall._match_types({}, ["tv"])


class TestNormalizeSourceConfig:
    """动态数据源配置规整：新版 dict / 旧版简写列表 / 缺省回退。"""

    def test_dict_passthrough(self):
        cfg = {"source_config": {"recommend/tmdb_movies": ["movie"]}}
        out = FullScreenPosterWall._normalize_source_config(cfg)
        assert out == {"recommend/tmdb_movies": ["movie"]}

    def test_dict_drops_empty_and_invalid(self):
        cfg = {"source_config": {
            "recommend/tmdb_movies": [],
            "recommend/tmdb_tvs": ["tv", "bogus"],
            "": ["movie"],
        }}
        out = FullScreenPosterWall._normalize_source_config(cfg)
        assert out == {"recommend/tmdb_tvs": ["tv"]}

    def test_legacy_list_migrated(self):
        cfg = {"sources": ["trending", "tmdb_movies", "tmdb_tvs"]}
        out = FullScreenPosterWall._normalize_source_config(cfg)
        assert out == {
            "recommend/tmdb_trending": ["movie", "tv"],
            "recommend/tmdb_movies": ["movie", "tv"],
            "recommend/tmdb_tvs": ["movie", "tv"],
        }

    def test_legacy_string_form(self):
        cfg = {"sources": "trending,tmdb_movies"}
        out = FullScreenPosterWall._normalize_source_config(cfg)
        assert set(out) == {"recommend/tmdb_trending", "recommend/tmdb_movies"}

    def test_empty_falls_back_to_default(self):
        out = FullScreenPosterWall._normalize_source_config({})
        assert out == FullScreenPosterWall._default_source_config()
        assert out  # 默认非空


class TestBuiltinSourceCatalog:
    """内置源目录结构合同（与系统探索页对齐的 15 源）。"""

    def test_fifteen_builtin_sources(self):
        assert len(FullScreenPosterWall._BUILTIN_SOURCES) == 15

    def test_unique_api_paths(self):
        paths = [s[0] for s in FullScreenPosterWall._BUILTIN_SOURCES]
        assert len(paths) == len(set(paths))

    def test_tuple_shape_and_nat(self):
        for api_path, name, chain_key, method, nat in FullScreenPosterWall._BUILTIN_SOURCES:
            assert api_path.startswith(("recommend/", "anilist/"))
            assert name and method
            assert chain_key in ("recommend", "anilist")
            assert nat in ("movie", "tv", "mixed")

    def test_anilist_sources_present(self):
        paths = [s[0] for s in FullScreenPosterWall._BUILTIN_SOURCES]
        assert "anilist/trending" in paths
        assert "anilist/popular_this_season" in paths


class TestPluginMetadata:
    """插件元数据与索引一致性。"""

    def test_version_is_v3_track(self):
        major = int(FullScreenPosterWall.plugin_version.split(".")[0])
        assert major >= 2

    def test_identity_fields(self):
        assert FullScreenPosterWall.plugin_name
        assert FullScreenPosterWall.plugin_desc
        assert FullScreenPosterWall.plugin_icon
