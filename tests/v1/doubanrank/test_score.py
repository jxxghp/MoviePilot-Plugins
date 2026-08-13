from doubanrank import _parse_douban_score, _select_score


def test_parse_douban_score_from_rss_description():
    """RSS 描述中的豆瓣评分应被解析为浮点数。"""
    assert _parse_douban_score("<p>评分：8.3分</p>") == 8.3


def test_select_score_uses_configured_source():
    """评分来源开关应严格选择豆瓣或 TMDB。"""
    assert _select_score("douban", 5.0, 8.5) == (5.0, "豆瓣")
    assert _select_score("tmdb", 5.0, 8.5) == (8.5, "TMDB")
