from doubanrank import _parse_douban_score, _select_score


def test_parse_douban_score_from_rss_description():
    """RSS 描述中的豆瓣评分应被解析为浮点数。"""
    description = "<p>标题：这一秒过火</p><p>评分：5.0分</p>"

    assert _parse_douban_score(description) == 5.0


def test_parse_douban_score_treats_zero_as_missing():
    """豆瓣用零表示尚未开分，应视为缺失评分。"""
    assert _parse_douban_score("<p>评分：0.0分</p>") is None


def test_select_score_uses_configured_source():
    """评分来源开关应严格选择豆瓣或 TMDB，不应隐式混用。"""
    assert _select_score("douban", 6.7, 7.8) == (6.7, "豆瓣")
    assert _select_score("tmdb", 6.7, 7.8) == (7.8, "TMDB")


def test_select_douban_score_keeps_missing_value():
    """仅豆瓣模式缺分时应返回缺失，由阈值过滤跳过。"""
    assert _select_score("douban", None, 8.5) == (None, "豆瓣")


def test_select_tmdb_score_normalizes_string_and_invalid_values():
    """TMDB 评分应兼容字符串，并将零分或异常值视为缺失。"""
    assert _select_score("tmdb", 6.7, "7.8") == (7.8, "TMDB")
    assert _select_score("tmdb", 6.7, 0) == (None, "TMDB")
    assert _select_score("tmdb", 6.7, "unknown") == (None, "TMDB")
