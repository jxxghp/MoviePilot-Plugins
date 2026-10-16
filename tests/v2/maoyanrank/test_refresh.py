"""猫眼榜单的异常隔离、上映年份与后续订阅回归。"""


import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins import maoyanrank
from app.plugins.maoyanrank import MaoyanRank
from app.schemas import MediaType


@pytest.fixture
def plugin(monkeypatch):
    """绕过宿主初始化并隔离日志、浏览器和 HTTP 客户端。"""
    instance = object.__new__(MaoyanRank)
    monkeypatch.setattr(maoyanrank, "logger", Mock())
    monkeypatch.setattr(instance, "_MaoyanRank__with_browser", Mock(return_value=None))
    monkeypatch.setattr(maoyanrank, "RequestUtils", Mock())

    def metadata(title):
        """只保留本插件使用的字段，避免初始化宿主的识别词配置服务。"""
        return SimpleNamespace(name=title, year=None, begin_season=None)

    monkeypatch.setattr(maoyanrank, "MetaInfo", metadata)
    return instance


def response(payload):
    """构造可检查 HTTP 状态的 JSON 响应。"""
    result = Mock()
    result.json.return_value = payload
    return result


@pytest.mark.parametrize("release_info", [None, "", "暂无", "点映", "敬请期待"])
def test_unknown_release_year_continues_recognition_without_warning(plugin, release_info):
    """未提供有效上映时间时不报转换警告，仍以未知年份识别媒体。"""
    plugin.chain = SimpleNamespace(recognize_media=Mock(return_value=None))

    plugin.set_sub([{"title": "待识别电影", "releaseInfo": release_info}], [], MediaType.MOVIE)

    assert plugin.chain.recognize_media.called, maoyanrank.logger.mock_calls
    assert plugin.chain.recognize_media.call_args.kwargs["meta"].year is None
    assert maoyanrank.logger.warn.call_count == 1
    assert "未识别到媒体信息" in maoyanrank.logger.warn.call_args.args[0]
    maoyanrank.logger.warning.assert_not_called()
    maoyanrank.logger.error.assert_not_called()


def test_browser_failure_does_not_block_any_rank(plugin):
    """浏览器取 Cookie 失败时仍逐个请求电影、网络电影及剧集榜单。"""
    plugin._MaoyanRank__with_browser.side_effect = RuntimeError("browser unavailable")
    request = maoyanrank.RequestUtils.return_value.get_res
    request.side_effect = [
        response({"movieList": {"list": [{"movieInfo": {"movieName": "院线电影"}}]}}),
        response({"dataList": {"list": [{"movieName": "网络电影"}]}}),
        response({"dataList": {"list": [{"seriesInfo": {"name": "电视剧"}}]}}),
    ]

    movies, shows = plugin._MaoyanRank__get_url_info("movie", [["tv", 10]], "web-movie")

    assert [item["title"] for item in movies] == ["院线电影", "网络电影"]
    assert [item["title"] for item in shows] == ["电视剧"]
    assert [call.args[0] for call in request.call_args_list] == ["movie", "web-movie", "tv"]
    assert "Cookie" in str(maoyanrank.logger.mock_calls)


@pytest.mark.parametrize("kind", ["movie", "web-movie", "tv"])
def test_invalid_item_preserves_other_items_in_same_rank(plugin, kind):
    """榜单内部坏条目不丢弃前后有效记录，也不订阅排名限制之外的记录。"""
    data_key, info_key, title_key = {
        "movie": ("movieList", "movieInfo", "movieName"),
        "web-movie": ("dataList", None, "movieName"),
        "tv": ("dataList", "seriesInfo", "name"),
    }[kind]

    def item(title):
        """按榜单类型生成一条上游数据。"""
        info = {title_key: title}
        return {info_key: info} if info_key else info

    rows = [item("第一条"), None, item(""), item("第四条"), item("范围外")]
    maoyanrank.RequestUtils.return_value.get_res.return_value = response({data_key: {"list": rows}})

    movies, shows = plugin._MaoyanRank__get_url_info(
        "movie" if kind == "movie" else "",
        [["tv", 4]] if kind == "tv" else [],
        "web-movie" if kind == "web-movie" else "",
        4,
    )

    assert [item["title"] for item in movies + shows] == ["第一条", "第四条"]
    assert kind in str(maoyanrank.logger.mock_calls)


@pytest.mark.parametrize("failure", ["network", "empty", "http", "json", "schema"])
def test_failed_source_preserves_previous_and_later_ranks(plugin, failure):
    """任一来源的传输、JSON 或响应结构错误不影响已获取及后续榜单。"""
    failed = response({"dataList": {"list": None}})
    if failure == "network":
        failed = RuntimeError("network unavailable")
    elif failure == "empty":
        failed = None
    elif failure == "http":
        failed.raise_for_status.side_effect = RuntimeError("HTTP 503")
    elif failure == "json":
        failed.json.side_effect = ValueError("invalid JSON")
    request = maoyanrank.RequestUtils.return_value.get_res
    request.side_effect = [
        response({"movieList": {"list": [{"movieInfo": {"movieName": "电影"}}]}}),
        failed,
        response({"dataList": {"list": [{"seriesInfo": {"name": "后续剧集"}}]}}),
    ]

    movies, shows = plugin._MaoyanRank__get_url_info("movie", [["broken-tv", 10], ["next-tv", 10]], "")

    assert [item["title"] for item in movies] == ["电影"]
    assert [item["title"] for item in shows] == ["后续剧集"]
    assert request.call_count == 3
    assert "broken-tv" in str(maoyanrank.logger.mock_calls)


def test_item_subscription_failure_continues_and_persists_success(plugin):
    """识别和订阅分别失败后继续下一条，仅保存成功添加的历史。"""
    media = SimpleNamespace(
        title="成功电影", year="2026", type=MediaType.MOVIE,
        tmdb_id=123, media_source=SimpleNamespace(value="themoviedb"), media_id="123",
        get_poster_image=Mock(return_value=""), overview="",
    )
    plugin.chain = SimpleNamespace(recognize_media=Mock(side_effect=[RuntimeError("识别失败"), media, media]))
    plugin.downloadchain = SimpleNamespace(get_no_exists_info=Mock(return_value=(False, {})))
    plugin.subscribechain = SimpleNamespace(exists=Mock(return_value=False), add=Mock(side_effect=[RuntimeError("订阅失败"), None]))
    history = []

    plugin.set_sub([{"title": title} for title in ["识别异常", "订阅异常", "成功电影"]], history, MediaType.MOVIE)

    assert plugin.chain.recognize_media.call_count == 3
    assert plugin.subscribechain.add.call_count == 2
    assert [item["title"] for item in history] == ["成功电影"]
    assert "识别异常" in str(maoyanrank.logger.mock_calls)
    assert "订阅异常" in str(maoyanrank.logger.mock_calls)


def test_refresh_keeps_later_ranks_and_saves_history(plugin, monkeypatch):
    """从真实刷新入口验证首榜失败后仍订阅后续来源并持久化历史。"""
    plugin._type = ["movie", "web-movie", "web-heat", "web-tv", "zongyi"]
    plugin._all_enabled = True
    plugin._tx_enabled = plugin._iqy_enabled = plugin._mg_enabled = plugin._yk_enabled = False
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=[]))
    monkeypatch.setattr(plugin, "save_data", Mock())
    monkeypatch.setattr(plugin, "_MaoyanRank__resolve_tv_subscribe_season", Mock(return_value=1))
    request = maoyanrank.RequestUtils.return_value.get_res
    request.side_effect = [
        RuntimeError("首榜失败"),
        response({"dataList": {"list": [{"movieName": "网络电影"}]}}),
        response({"dataList": {"list": [{"seriesInfo": {"name": "电视剧"}}]}}),
        response({"dataList": {"list": [{"seriesInfo": {"name": "网剧"}}]}}),
        response({"dataList": {"list": [{"seriesInfo": {"name": "综艺"}}]}}),
    ]

    def recognize(meta, mtype, cache):
        """保留真实榜单条目到订阅参数的传递。"""
        assert cache is False
        return SimpleNamespace(
            title=meta.name, year="2026", type=mtype, tmdb_id=123,
            media_source=SimpleNamespace(value="themoviedb"), media_id="123",
            get_poster_image=Mock(return_value=""), overview="",
        )

    plugin.chain = SimpleNamespace(recognize_media=recognize)
    plugin.downloadchain = SimpleNamespace(get_no_exists_info=Mock(return_value=(False, {})))
    plugin.subscribechain = SimpleNamespace(exists=Mock(return_value=False), add=Mock())

    plugin._MaoyanRank__refresh_maoyan()

    assert request.call_count == 5
    assert [call.kwargs["title"] for call in plugin.subscribechain.add.call_args_list] == ["网络电影", "电视剧", "网剧", "综艺"]
    plugin.save_data.assert_called_once()
    key, history = plugin.save_data.call_args.args
    assert key == "history"
    assert [item["title"] for item in history] == ["网络电影", "电视剧", "网剧", "综艺"]


def test_cookies_limits_and_tv_deduplication_are_preserved(plugin):
    """正常 Cookie、各平台数量限制及跨榜标题去重不受异常隔离改动影响。"""
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[{"name": "session", "value": "test-cookie"}])),
        evaluate=Mock(return_value="official-browser-ua"),
    )
    plugin._MaoyanRank__with_browser.side_effect = lambda callback: callback(page)
    request = maoyanrank.RequestUtils.return_value.get_res
    request.side_effect = [
        response({"dataList": {"list": [{"seriesInfo": {"name": name}} for name in ["同名剧集", "超出排名"]]}}),
        response({"dataList": {"list": [{"seriesInfo": {"name": "同名剧集", "platformDesc": "腾讯视频"}}]}}),
    ]

    movies, shows = plugin._MaoyanRank__get_url_info("", [["first-tv", 1], ["second-tv", 10]], "")

    assert movies == []
    assert len(shows) == 1
    assert shows[0]["title"] == "同名剧集"
    assert shows[0]["platformDesc"] == "腾讯视频"
    assert all(call.kwargs["cookies"] == {"session": "test-cookie"} for call in request.call_args_list)


@pytest.mark.parametrize("release_info,year", [
    ("上映首日", 2026), ("今日上映", 2026), ("上映10天", 2025),
    ("上线 10 天", 2025), ("开播1天", 2026),
    ("2024-12-31上映", 2024), ("2024年12月31日", 2024),
    ("2024/12/31", 2024), ("2024-02-30", None),
    ("还有10天上映", None), ("上映2年", None),
    ("上映9999999999999999999999天", None),
])
def test_release_year_uses_only_known_date_formats(release_info, year):
    """仅解析明确日期和已上映天数，避免把完整日期误当成天数。"""
    assert MaoyanRank._MaoyanRank__release_year(release_info, datetime.datetime(2026, 1, 5)) == year


def test_current_heat_endpoints_use_one_browser_session(plugin):
    """当前热度接口在官网会话内请求，不把已失效的裸 HTTP 结果当成榜单。"""
    urls = [
        "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatData?showDate=20260930&seriesType=0",
        "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatData?showDate=20260930&seriesType=2&platformType=3",
    ]
    payloads = [
        {"dataList": {"list": [{"seriesInfo": {"name": name}}]}}
        for name in ("电视剧", "综艺")
    ]
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[])),
        evaluate=Mock(side_effect=["official-browser-ua", *payloads]),
    )
    plugin._MaoyanRank__with_browser.side_effect = lambda callback: callback(page)

    movies, shows = plugin._MaoyanRank__get_url_info("", [[url, 10] for url in urls], "")

    assert movies == []
    assert [item["title"] for item in shows] == ["电视剧", "综艺"]
    plugin._MaoyanRank__with_browser.assert_called_once()
    maoyanrank.RequestUtils.assert_not_called()
    assert [call.args[1] for call in page.evaluate.call_args_list[1:]] == urls


def test_browser_request_failure_does_not_block_later_heat_rank(plugin):
    """官网会话内的某个请求失败时仍请求下一平台，并保留成功条目。"""
    urls = [
        "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatData?seriesType=2",
        "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatData?seriesType=2&platformType=3",
    ]
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[])),
        evaluate=Mock(side_effect=[
            "official-browser-ua", RuntimeError("HTTP 403 Forbidden"),
            {"dataList": {"list": [{"seriesInfo": {"name": "后续综艺"}}]}},
        ]),
    )
    plugin._MaoyanRank__with_browser.side_effect = lambda callback: callback(page)

    _, shows = plugin._MaoyanRank__get_url_info("", [[url, 10] for url in urls], "")

    assert [item["title"] for item in shows] == ["后续综艺"]
    assert urls[0] in str(maoyanrank.logger.error.call_args)
    assert page.evaluate.call_count == 3


def test_browser_cleanup_failure_does_not_repeat_processed_ranks(plugin):
    """关闭浏览器失败不应触发已处理榜单的重复请求或丢掉已有结果。"""
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[])),
        evaluate=Mock(return_value="official-browser-ua"),
    )

    def use_browser(callback):
        """在完成榜单读取后模拟关闭异常。"""
        callback(page)
        raise RuntimeError("context close failed")

    plugin._MaoyanRank__with_browser.side_effect = use_browser
    request = maoyanrank.RequestUtils.return_value.get_res
    request.return_value = response({"movieList": {"list": [{"movieInfo": {"movieName": "已读取电影"}}]}})

    movies, _ = plugin._MaoyanRank__get_url_info("movie", [], "")

    assert [item["title"] for item in movies] == ["已读取电影"]
    request.assert_called_once()
    assert request.call_args.kwargs["headers"]["User-Agent"] == "official-browser-ua"


def test_refresh_builds_current_heat_urls_and_preserves_filters(plugin, monkeypatch):
    """三类榜单和五个平台均使用实际日期，全网不发送空的平台参数。"""
    from urllib.parse import parse_qs, urlparse

    plugin._type = ["web-heat", "web-tv", "zongyi"]
    plugin._all_enabled = plugin._tx_enabled = plugin._iqy_enabled = plugin._mg_enabled = plugin._yk_enabled = True
    plugin._all_num, plugin._tx_num, plugin._iqy_num, plugin._mg_num, plugin._yk_num = 1, 2, 3, 5, 7
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=[]))
    monkeypatch.setattr(plugin, "save_data", Mock())
    fetch = Mock(return_value=([], []))
    monkeypatch.setattr(plugin, "_MaoyanRank__get_url_info", fetch)

    plugin._MaoyanRank__refresh_maoyan()

    movie_url, tv_urls, web_movie_url, _ = fetch.call_args.args
    assert movie_url == web_movie_url == ""
    assert len(tv_urls) == 15
    expected_date = datetime.datetime.now(maoyanrank.pytz.timezone("Asia/Shanghai")).strftime("%Y%m%d")
    queries = []
    for url, limit in tv_urls:
        parsed = urlparse(url)
        assert parsed.path == "/i/api/encrypt/dashboard/webHeatData"
        query = parse_qs(parsed.query, keep_blank_values=True)
        assert query["showDate"] == [expected_date]
        assert query.get("platformType") != [""]
        queries.append((query["seriesType"][0], query.get("platformType", [None])[0], limit))
    assert queries == [(series, platform, limit) for series in ("0", "1", "2")
                       for platform, limit in ((None, 1), ("3", 2), ("2", 3), ("7", 5), ("1", 7))]


@pytest.mark.parametrize("latest,retries", [
    ("2026-09-29", 1), ("20260929", 1), ("2026-09-30", 0), (None, 0),
])
def test_network_movie_retries_latest_available_date(plugin, latest, retries):
    """网络电影在同一浏览器会话中回退到可用日期，最多重试一次。"""
    from urllib.parse import parse_qs, urlsplit

    url = "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatNetData?showDate=20260930&platformType=3&dateType=0&rankType=0"
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[])),
        evaluate=Mock(side_effect=[
            "official-browser-ua",
            {"status": False, "calendarNet": {"selectMaxDate": latest}},
            {"dataList": {"list": [
                {"movieName": "网络电影", "releaseInfo": "上映3天"},
                {"movieName": "超出排名"},
            ]}},
        ]),
    )
    plugin._MaoyanRank__with_browser.side_effect = lambda callback: callback(page)

    movies, shows = plugin._MaoyanRank__get_url_info("", [], url, 1)

    assert shows == []
    assert [item["title"] for item in movies] == (["网络电影"] if retries else [])
    assert page.evaluate.call_count == 2 + retries
    maoyanrank.RequestUtils.assert_not_called()
    if retries:
        query = parse_qs(urlsplit(page.evaluate.call_args.args[1]).query)
        assert query == {"showDate": ["20260929"], "platformType": ["3"], "dateType": ["0"], "rankType": ["0"]}


def test_network_movie_retry_failure_preserves_other_ranks(plugin):
    """网络电影回退请求失败后，保留票房榜并继续获取剧集。"""
    net_url = "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatNetData?showDate=20260930&platformType=3&dateType=0&rankType=0"
    tv_url = "https://piaofang.maoyan.com/i/api/encrypt/dashboard/webHeatData?showDate=20260930"
    page = SimpleNamespace(
        context=SimpleNamespace(cookies=Mock(return_value=[])),
        evaluate=Mock(side_effect=[
            "official-browser-ua",
            {"status": False, "calendarNet": {"selectMaxDate": "2026-09-29"}},
            RuntimeError("HTTP 403"),
            {"dataList": {"list": [{"seriesInfo": {"name": "后续剧集"}}]}},
        ]),
    )
    plugin._MaoyanRank__with_browser.side_effect = lambda callback: callback(page)
    maoyanrank.RequestUtils.return_value.get_res.return_value = response(
        {"movieList": {"list": [{"movieInfo": {"movieName": "院线电影"}}]}}
    )

    movies, shows = plugin._MaoyanRank__get_url_info("movie", [[tv_url, 1]], net_url, 1)

    assert [item["title"] for item in movies] == ["院线电影"]
    assert [item["title"] for item in shows] == ["后续剧集"]
    assert page.evaluate.call_count == 4


def test_refresh_builds_current_network_movie_url(plugin, monkeypatch):
    """网络电影从刷新入口生成北京时间日期及官网当前参数。"""
    from urllib.parse import parse_qs, urlsplit

    plugin._type = ["web-movie"]
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=[]))
    monkeypatch.setattr(plugin, "save_data", Mock())
    fetch = Mock(return_value=([], []))
    monkeypatch.setattr(plugin, "_MaoyanRank__get_url_info", fetch)

    plugin._MaoyanRank__refresh_maoyan()

    movie_url, tv_urls, net_url, _ = fetch.call_args.args
    assert movie_url == ""
    assert tv_urls == []
    parts = urlsplit(net_url)
    assert parts.path == "/i/api/encrypt/dashboard/webHeatNetData"
    expected = datetime.datetime.now(maoyanrank.pytz.timezone("Asia/Shanghai")).strftime("%Y%m%d")
    assert parse_qs(parts.query) == {
        "showDate": [expected], "platformType": ["3"], "dateType": ["0"], "rankType": ["0"],
    }
