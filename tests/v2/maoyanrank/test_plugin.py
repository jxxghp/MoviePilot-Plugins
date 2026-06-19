from types import SimpleNamespace

import maoyanrank
from app.core.metainfo import MetaInfo

from maoyanrank import MaoyanRank


def test_resolve_tv_subscribe_season_prefers_title_marker(monkeypatch):
    """标题含有明确季号时，应优先使用标题识别出的季号。"""

    class FakeTmdbChain:
        """防止显式季号场景误查 TMDB。"""

        def tmdb_seasons(self, tmdbid):
            """显式季号命中后不应调用 TMDB 季查询。"""
            raise AssertionError("tmdb_seasons should not be called")

    monkeypatch.setattr(maoyanrank, "TmdbChain", FakeTmdbChain)
    plugin = MaoyanRank()
    meta = MetaInfo("问心 第二季")
    mediainfo = SimpleNamespace(tmdb_id=225780, title="问心")

    season = plugin._MaoyanRank__resolve_tv_subscribe_season("问心 第二季", meta, mediainfo)

    assert season == 2


def test_resolve_tv_subscribe_season_uses_latest_tmdb_season(monkeypatch):
    """标题没有季号时，应从 TMDB 季信息中取最新有效季。"""

    class FakeTmdbChain:
        """返回混合形态的 TMDB 季信息，覆盖字典和对象两类入口。"""

        def tmdb_seasons(self, tmdbid):
            """模拟 TMDB 返回第 0 季、第一季和第二季。"""
            assert tmdbid == 225780
            return [
                {"season_number": 0},
                SimpleNamespace(season_number=1),
                {"season_number": 2},
            ]

    monkeypatch.setattr(maoyanrank, "TmdbChain", FakeTmdbChain)
    plugin = MaoyanRank()
    meta = MetaInfo("问心")
    mediainfo = SimpleNamespace(tmdb_id=225780, title="问心")

    season = plugin._MaoyanRank__resolve_tv_subscribe_season("问心", meta, mediainfo)

    assert season == 2
    assert meta.begin_season == 2


def test_latest_tmdb_season_falls_back_to_mediainfo(monkeypatch):
    """TMDB 查询失败时，应使用识别结果中已有的季信息兜底。"""

    class FakeTmdbChain:
        """模拟 TMDB 季查询失败。"""

        def tmdb_seasons(self, tmdbid):
            """抛出异常触发 MediaInfo 兜底路径。"""
            raise RuntimeError("tmdb unavailable")

    monkeypatch.setattr(maoyanrank, "TmdbChain", FakeTmdbChain)
    plugin = MaoyanRank()
    mediainfo = SimpleNamespace(
        tmdb_id=225780,
        title="问心",
        season_info=[
            {"season_number": 0},
            {"season_number": 1},
            {"season_number": 3},
        ],
    )

    season = plugin._MaoyanRank__latest_tmdb_season(mediainfo)

    assert season == 3
