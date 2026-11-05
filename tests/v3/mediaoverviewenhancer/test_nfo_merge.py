"""NFO 就地合并与分集标题兜底的单元测试。"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.plugins.mediaoverviewenhancer.enhancer import OverviewEnhancer


def test_nfo_apply_keeps_existing_fields() -> None:
    """就地更新只改简介/标题/季集号，其它节点与文本必须原样保留。"""
    root = ET.fromstring(
        "<episodedetails>"
        "<plot>旧简介</plot>"
        "<title>第 3 集</title>"
        "<uniqueid type=\"tmdb\">6513837</uniqueid>"
        "<outline>保留我</outline>"
        "</episodedetails>"
    )
    OverviewEnhancer._nfo_apply(
        root,
        {"kind": "episode", "season": 2, "episode": 5},
        "新简介正文",
        "雨夜的证词",
    )
    assert root.findtext("plot") == "新简介正文"
    assert root.findtext("title") == "雨夜的证词"
    assert root.findtext("season") == "2"
    assert root.findtext("episode") == "5"
    assert root.findtext("outline") == "保留我"
    assert root.find("uniqueid").get("type") == "tmdb"


def test_nfo_apply_movie_does_not_add_season() -> None:
    """电影 NFO 不应被写入季集号。"""
    root = ET.fromstring("<movie><plot>旧</plot></movie>")
    OverviewEnhancer._nfo_apply(root, {"kind": "movie"}, "新的电影简介")
    assert root.findtext("plot") == "新的电影简介"
    assert root.find("season") is None
    assert root.find("episode") is None
