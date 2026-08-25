import json
import logging
import socket
import time

import pytest
import app.plugins.lunatvsource.cms as cms_module

from app.plugins.lunatvsource.cms import (
    AppleCmsClient,
    CmsSource,
    _fetch_public_url,
    _is_public_probe_url,
    _master_playlist_height,
    _parse_play_urls,
    _result_from_item,
    apply_season_counts,
    parse_config,
    probe_stream_height,
    stream_quality_label,
)


def test_stream_quality_label_uses_actual_video_height():
    assert stream_quality_label(4320) == "8K"
    assert stream_quality_label(2304) == "2304P"
    assert stream_quality_label(2160) == "4K"
    assert stream_quality_label(1080) == "1080P"
    assert stream_quality_label(720) == "720P"
    assert stream_quality_label(480) == "480P"
    assert stream_quality_label(608) == "608P"
    assert stream_quality_label(360) == "360P"
    assert stream_quality_label(0) == "未知"


def test_master_playlist_height_only_reads_stream_inf_resolution():
    playlist = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080\n"
        "https://cdn.example/video-3840x2160.m3u8\n"
    )

    assert _master_playlist_height(playlist) == 1080
    assert _master_playlist_height(
        "#EXTM3U\n#EXTINF:6,\nsegment-3840x2160.ts\n"
    ) == 0


def test_public_probe_url_rejects_private_and_mixed_dns(monkeypatch):
    assert _is_public_probe_url("http://127.0.0.1/metadata") is False
    assert _is_public_probe_url("http://169.254.169.254/latest/meta-data") is False
    assert _is_public_probe_url("http://192.168.1.10/video.m3u8") is False
    assert _is_public_probe_url("http://[::1]/video.m3u8") is False
    assert _is_public_probe_url(
        "http://10.0.0.8/video.m3u8",
        ("10.0.0.0/8",),
    ) is True

    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )
    assert _is_public_probe_url("https://video.example/media.m3u8") is True

    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        ],
    )
    assert _is_public_probe_url("https://video.example/media.m3u8") is True

    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.2.148", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fdfe:dcba:9876::241", 443, 0, 0)),
        ],
    )
    assert _is_public_probe_url("https://video.example/media.m3u8") is False
    assert _is_public_probe_url(
        "https://video.example/media.m3u8",
        ("198.18.0.0/15", "fdfe:dcba:9876::/48"),
    ) is True
    assert _is_public_probe_url("http://video.example/media.m3u8") is False

    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        ],
    )
    assert _is_public_probe_url("https://video.example/media.m3u8") is False


def test_public_fetch_pins_dns_and_rejects_private_redirect(monkeypatch):
    requests = []
    responses = iter(
        [
            type(
                "RedirectResponse",
                (),
                {
                    "status": 302,
                    "getheader": lambda self, name: (
                        "http://127.0.0.1/metadata" if name == "Location" else None
                    ),
                },
            )(),
        ]
    )

    class Connection:
        def __init__(self, address, port, timeout):
            requests.append({"address": address, "port": port, "timeout": timeout})

        def request(self, method, path, headers):
            requests[-1].update({"method": method, "path": path, "headers": headers})

        def getresponse(self):
            return next(responses)

        def close(self):
            return None

    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ],
    )
    monkeypatch.setattr("app.plugins.lunatvsource.cms.http.client.HTTPConnection", Connection)

    with pytest.raises(ValueError, match="non-public"):
        _fetch_public_url("http://video.example/start.m3u8", 3.0, 1024)

    assert requests == [
        {
            "address": "93.184.216.34",
            "port": 80,
            "timeout": 3.0,
            "method": "GET",
            "path": "/start.m3u8",
            "headers": {
                "Host": "video.example",
                "User-Agent": "LunaTVSource/0.1 MoviePilot",
                "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, */*",
                "Connection": "close",
            },
        }
    ]


def test_probe_stream_height_reads_master_playlist_resolution(monkeypatch):
    monkeypatch.setattr("app.plugins.lunatvsource.cms._is_public_probe_url", lambda *_args: True)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms._probe_media_sample",
        lambda *_args, **_kwargs: (1080, b"", ""),
    )
    assert probe_stream_height("https://example.test/master.m3u8") == 1080


def test_probe_stream_height_falls_back_to_first_video_stream(monkeypatch):
    class ProcessResult:
        stdout = "854x480\n"

    def run(args, **_kwargs):
        assert "-protocol_whitelist" in args
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert not args[-1].startswith(("http://", "https://"))
        return ProcessResult()

    monkeypatch.setattr("app.plugins.lunatvsource.cms._is_public_probe_url", lambda *_args: True)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms._probe_media_sample",
        lambda *_args, **_kwargs: (0, b"segment", ".ts"),
    )
    monkeypatch.setattr("app.plugins.lunatvsource.cms.subprocess.run", run)
    assert probe_stream_height("https://example.test/media.m3u8") == 480


def test_probe_stream_height_decodes_one_frame_when_ffprobe_has_no_dimensions(monkeypatch):
    results = iter([
        type("ProbeResult", (), {"stdout": "", "stderr": ""})(),
        type("FrameResult", (), {"stdout": "", "stderr": "Video: h264, 1280x720"})(),
    ])
    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        return next(results)

    monkeypatch.setattr("app.plugins.lunatvsource.cms._is_public_probe_url", lambda *_args: True)
    monkeypatch.setattr(
        "app.plugins.lunatvsource.cms._probe_media_sample",
        lambda *_args, **_kwargs: (0, b"segment", ".ts"),
    )
    monkeypatch.setattr("app.plugins.lunatvsource.cms.subprocess.run", run)

    assert probe_stream_height("https://example.test/media.m3u8") == 720
    assert len(calls) == 2
    for args in calls:
        assert "-protocol_whitelist" in args
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert not any(str(value).startswith(("http://", "https://")) for value in args)


def test_parse_config_filters_by_api_host():
    sources = parse_config(
        {
            "api_site": {
                "suonizy.net": {
                    "name": "索尼",
                    "api": "https://suoniapi.com/api.php/provide/vod",
                    "detail": "https://suonizy.net",
                },
                "other": {"name": "其它", "api": "https://other.example/vod"},
            }
        },
        allowlist=("suonizy.net",),
    )
    assert len(sources) == 1
    assert sources[0].api.endswith("/api.php/provide/vod")


def test_source_to_dict_derives_non_live_configuration_states():
    cases = [
        ("", "ready", "已加载", "supported", "支持"),
        ("备用源", "warning", "备用", "supported", "支持"),
        ("线路不稳定", "warning", "不稳定", "supported", "支持"),
        ("HTTP 403", "error", "异常", "unavailable", "不可用"),
        ("暂不支持搜索", "ready", "已加载", "unsupported", "不支持"),
        ("无法搜索", "ready", "已加载", "unsupported", "不支持"),
        ("禁止搜索", "ready", "已加载", "unsupported", "不支持"),
        ("无搜索结果", "ready", "已加载", "empty", "无结果"),
        ("污染搜索结果", "ready", "已加载", "degraded", "结果异常"),
    ]

    for comment, status, status_label, search_status, search_label in cases:
        data = CmsSource(
            key="demo",
            name="演示源",
            api="https://api.example/vod",
            detail="https://detail.example",
            comment=comment,
        ).to_dict()
        assert data["url"] == "https://detail.example"
        assert data["status"] == status
        assert data["status_label"] == status_label
        assert data["search_status"] == search_status
        assert data["search_label"] == search_label

    fallback = CmsSource("fallback", "回退源", "https://api.example/vod").to_dict()
    assert fallback["url"] == "https://api.example/vod"


def test_parse_play_urls_reads_multiple_episodes_and_seasons():
    episodes = _parse_play_urls(
        "高清$$$备用",
        "01$https://example.test/s01e01.m3u8#02$https://example.test/s01e02.m3u8$$$01$https://backup.test/01.m3u8",
    )
    assert [(item.season, item.episode) for item in episodes] == [(1, 1), (1, 2)]
    assert episodes[0].url.endswith("s01e01.m3u8")


def test_parse_play_urls_supports_chinese_episode_label():
    episodes = _parse_play_urls("在线播放", "第8集$https://example.test/08.m3u8")
    assert episodes[0].episode == 8


def test_parse_play_urls_rejects_non_http_urls():
    episodes = _parse_play_urls("在线播放", "01$file:///tmp/episode.m3u8#02$https://example.test/02.m3u8")
    assert [(item.episode, item.url) for item in episodes] == [(2, "https://example.test/02.m3u8")]


def test_parse_play_urls_preserves_season_groups():
    episodes = _parse_play_urls(
        "第1季$$$第2季",
        "01$https://example.test/s1e01.m3u8$$$01$https://example.test/s2e01.m3u8",
    )
    assert [(item.season, item.episode) for item in episodes] == [(1, 1), (2, 1)]


def test_result_from_item_recognizes_chinese_season_title():
    result = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": "42",
            "vod_name": "小猪佩奇 第八季",
            "type_name": "欧美动漫",
            "vod_play_url": "第45集$https://example.test/s08e45.m3u8",
        },
    )
    assert result.media_type == "tv"
    assert [(episode.season, episode.episode, episode.season_known) for episode in result.episodes] == [(8, 45, True)]


def test_search_enriches_sparse_list_item_with_detail_play_urls():
    source = CmsSource(
        key="demo",
        name="演示",
        api="https://cms.example/api.php/provide/vod",
    )
    client = AppleCmsClient([source])
    calls = []

    def fake_request(current, **params):
        calls.append(params)
        if params.get("ac") == "list":
            return {"list": [{"vod_id": "42", "vod_name": "示例剧", "type_name": "电视剧"}]}
        return {
            "list": [
                {
                    "vod_id": "42",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "01$https://example.test/01.m3u8#02$https://example.test/02.m3u8",
                }
            ]
        }

    client._request = fake_request
    results = client.search("示例剧")
    assert len(results) == 1
    assert [episode.episode for episode in results[0].episodes] == [1, 2]
    assert {call.get("ac") for call in calls} == {"list", "detail"}


def _episode_row(index: int, *, title: str = "长剧", year: str = "2026"):
    return {
        "vod_id": f"episode-{index}",
        "vod_name": f"{title} S01E{index:03d}",
        "vod_year": year,
        "type_name": "电视剧",
        "vod_play_url": f"第{index}集$https://video.example/{title}-{index}.m3u8",
    }


def _search_item(index: int, media_type: str, *, playable: bool = True):
    type_name = {"movie": "电影", "tv": "电视剧"}[media_type]
    item = {
        "vod_id": f"{media_type}-{index}",
        "vod_name": f"示例{type_name}{index}",
        "type_name": type_name,
    }
    if playable:
        item["vod_play_url"] = f"正片$https://video.example/{media_type}-{index}.m3u8"
    return item


def test_search_applies_media_type_filter_before_per_source_limit():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    items = [_search_item(index, "tv", playable=False) for index in range(1, 4)] + [
        _search_item(4, "movie")
    ]
    detail_calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            detail_calls.append(params["ids"])
            return {"list": []}
        return {"list": items}

    client._request = fake_request

    unfiltered = client.search(
        "示例",
        limit=3,
        source_limit=3,
        enrich=False,
        media_type_filter="",
    )
    movies = client.search(
        "示例",
        limit=3,
        source_limit=3,
        media_type_filter="movie",
    )

    assert [result.vod_id for result in unfiltered] == ["tv-1", "tv-2", "tv-3"]
    assert [result.vod_id for result in movies] == ["movie-4"]
    assert detail_calls == []


def test_search_tv_filter_enriches_row_without_reliable_type_hint():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    detail_calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            return {"list": [{"vod_id": "unknown-tv", "vod_name": "缺类型剧"}]}
        detail_calls.append(params["ids"])
        return {
            "list": [
                {
                    "vod_id": "unknown-tv",
                    "type_name": "电视剧",
                    "vod_play_url": "第1集$https://video.example/unknown-tv.m3u8",
                }
            ]
        }

    client._request = fake_request

    results = client.search("缺类型剧", media_type_filter="tv")

    assert detail_calls == ["unknown-tv"]
    assert [result.vod_id for result in results] == ["unknown-tv"]
    assert [result.media_type for result in results] == ["tv"]


def test_search_applies_tv_filter_before_per_source_limit_in_episode_row_mode():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    detail_calls = []
    unplayable = _episode_row(1)
    unplayable["vod_play_url"] = "not-a-url"

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            detail_calls.append(params["ids"])
            return {"list": []}
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {
                "pagecount": "2",
                "list": [_search_item(index, "movie", playable=False) for index in range(1, 4)]
                + [unplayable],
            }
        return {
            "pagecount": "2",
            "list": [_search_item(4, "movie", playable=False), _episode_row(2)],
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        source_limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
        media_type_filter="tv",
    )

    assert calls == [1, 2]
    assert detail_calls == []
    assert [result.title for result in results] == ["长剧"]
    assert [episode.episode for episode in results[0].episodes] == [2]


def test_search_tv_filter_enriches_unknown_episode_row_on_later_page():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            page = int(params["pg"])
            calls.append(("list", page))
            if page == 1:
                return {"pagecount": "2", "list": [_episode_row(1)]}
            return {
                "pagecount": "2",
                "list": [
                    {
                        "vod_id": "unknown-tv-2",
                        "vod_name": "长剧 S01E002",
                        "vod_year": "2026",
                    }
                ],
            }
        calls.append(("detail", params["ids"]))
        return {
            "list": [
                {
                    "vod_id": "unknown-tv-2",
                    "type_name": "电视剧",
                    "vod_play_url": "第2集$https://video.example/long-show-2.m3u8",
                }
            ]
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        expand_tv_episode_rows=True,
        media_type_filter="tv",
    )

    assert calls == [("list", 1), ("list", 2), ("detail", "unknown-tv-2")]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_episode_row_expansion_enriches_unknown_later_row_without_filter():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            page = int(params["pg"])
            calls.append(("list", page))
            if page == 1:
                return {"pagecount": "2", "list": [_episode_row(1)]}
            return {
                "pagecount": "2",
                "list": [
                    {
                        "vod_id": "unknown-tv-2",
                        "vod_name": "长剧 S01E002",
                        "vod_year": "2026",
                    }
                ],
            }
        calls.append(("detail", params["ids"]))
        return {
            "list": [
                {
                    "vod_id": "unknown-tv-2",
                    "type_name": "电视剧",
                    "vod_play_url": "第2集$https://video.example/long-show-2.m3u8",
                }
            ]
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [("list", 1), ("list", 2), ("detail", "unknown-tv-2")]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_tv_filter_pages_past_non_target_rows_before_first_playable_card():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    pages = {
        1: [_search_item(1, "movie", playable=False)],
        2: [_search_item(2, "movie", playable=False)],
        3: [_episode_row(3)],
    }
    calls = []
    detail_calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            detail_calls.append(params["ids"])
            return {"list": []}
        page = int(params["pg"])
        calls.append(page)
        return {"pagecount": "3", "list": pages[page]}

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
        media_type_filter="tv",
    )

    assert calls == [1, 2, 3]
    assert detail_calls == []
    assert [result.title for result in results] == ["长剧"]
    assert [episode.episode for episode in results[0].episodes] == [3]


def test_search_expands_episode_rows_across_pagecount_before_source_limit():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        calls.append(params)
        page = int(params["pg"])
        rows = {
            1: [_episode_row(1), _episode_row(2)],
            2: [_episode_row(3), _episode_row(4)],
        }[page]
        return {"pagecount": "2", "list": rows}

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        source_limit=1,
        expand_tv_episode_rows=True,
    )

    assert [(call["pg"], call.get("ac")) for call in calls] == [(1, "list"), (2, "list")]
    assert len(results) == 1
    assert results[0].title == "长剧"
    assert results[0].season_range == (1, 1)
    assert [(episode.season, episode.episode) for episode in results[0].episodes] == [
        (1, 1),
        (1, 2),
        (1, 3),
        (1, 4),
    ]


def test_search_episode_row_expansion_stops_on_empty_page_without_pagecount():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    pages = {
        1: [_episode_row(1)],
        2: [_episode_row(2)],
        3: [],
    }
    calls = []

    def fake_request(_source, **params):
        calls.append(int(params["pg"]))
        return {"list": pages[int(params["pg"])]}

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2, 3]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_episode_row_expansion_stops_when_cms_ignores_pg():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        calls.append(int(params["pg"]))
        return {"list": [_episode_row(1)]}

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [episode.episode for episode in results[0].episodes] == [1]


def test_search_episode_row_expansion_does_not_page_non_episode_results():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        calls.append(int(params["pg"]))
        return {
            "pagecount": "9",
            "list": [
                {
                    "vod_id": "series",
                    "vod_name": "长剧",
                    "vod_year": "2026",
                    "type_name": "电视剧",
                    "vod_play_url": "第1集$https://video.example/long-show.m3u8",
                }
            ],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1]
    assert [episode.episode for episode in results[0].episodes] == [1]


def test_search_episode_row_expansion_uses_batch_detail_then_individual_fallback():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def sparse_row(index: int):
        row = _episode_row(index)
        row.pop("vod_play_url")
        return row

    def fake_request(_source, **params):
        calls.append((params.get("ac"), params.get("ids"), params.get("pg")))
        if params.get("ac") == "list":
            return {"pagecount": 1, "list": [sparse_row(1), sparse_row(2)]}
        if params.get("ids") == "episode-1,episode-2":
            return {"list": [_episode_row(1)]}
        if params.get("ids") == "episode-2":
            return {"list": [_episode_row(2)]}
        raise AssertionError(params)

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert ("detail", "episode-1,episode-2", None) in calls
    assert ("detail", "episode-2", None) in calls
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_episode_row_expansion_collects_a_208_episode_season():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        first = (page - 1) * 20 + 1
        last = min(first + 20, 209)
        return {
            "pagecount": "11",
            "list": [_episode_row(index) for index in range(first, last)],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == list(range(1, 12))
    assert len(results) == 1
    assert [episode.episode for episode in results[0].episodes] == list(range(1, 209))


def test_search_episode_row_expansion_keeps_multi_episode_detail_as_regular_result():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        calls.append(dict(params))
        if params.get("ac") == "list":
            return {
                "pagecount": "99",
                "list": [
                    {
                        "vod_id": "bundle",
                        "vod_name": "长剧 第52集",
                        "vod_year": "2026",
                        "type_name": "电视剧",
                    }
                ],
            }
        if params.get("ids") == "bundle":
            return {
                "list": [
                    {
                        "vod_id": "bundle",
                        "vod_name": "长剧 第52集",
                        "vod_year": "2026",
                        "type_name": "电视剧",
                        "vod_play_url": "#".join(
                            f"第{episode}集$https://video.example/long-{episode}.m3u8"
                            for episode in range(1, 4)
                        ),
                    }
                ]
            }
        raise AssertionError(params)

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert [(call["pg"], call.get("pages")) for call in calls if call["ac"] == "list"] == [
        (1, None)
    ]
    assert results[0].title == "长剧 第52集"
    assert [episode.episode for episode in results[0].episodes] == [1, 2, 3]


def test_search_episode_row_expansion_batches_sparse_detail_ids_in_groups_of_50():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    detail_batches = []

    def sparse_row(index: int):
        row = _episode_row(index)
        row.pop("vod_play_url")
        return row

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            return {"pagecount": 1, "list": [sparse_row(index) for index in range(1, 209)]}
        ids = params.get("ids", "").split(",")
        detail_batches.append(ids)
        return {
            "list": [_episode_row(int(vod_id.removeprefix("episode-"))) for vod_id in ids]
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert [len(batch) for batch in detail_batches] == [50, 50, 50, 50, 8]
    assert [vod_id for batch in detail_batches for vod_id in batch] == [
        f"episode-{index}" for index in range(1, 209)
    ]
    assert [episode.episode for episode in results[0].episodes] == list(range(1, 209))


def test_search_episode_row_expansion_keeps_pages_compatibility_on_later_pages():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        calls.append(dict(params))
        page = int(params["pg"])
        if page == 1 and params.get("pages") is None:
            return {"list": []}
        assert params.get("pages") == 1
        return {
            "pagecount": "2",
            "list": [_episode_row(page)],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert [(call["pg"], call.get("pages")) for call in calls] == [
        (1, None),
        (1, 1),
        (2, 1),
    ]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_episode_row_expansion_stops_at_32_page_safety_limit(caplog):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {"pagecount": "999", "list": [_episode_row(page)]}

    client._request = fake_request

    caplog.set_level(logging.WARNING, logger=cms_module.LOGGER.name)
    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == list(range(1, 33))
    assert [episode.episode for episode in results[0].episodes] == list(range(1, 33))
    assert "source=demo" in caplog.text
    assert "query=长剧" in caplog.text
    assert "pagecount=999" in caplog.text


def test_tv_unlabelled_multi_url_bundle_keeps_all_episodes_and_does_not_paginate():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    urls = "#".join(f"https://video.example/long-{episode}.m3u8" for episode in range(1, 53))

    def fake_request(_source, **params):
        calls.append(int(params["pg"]))
        return {
            "pagecount": "999",
            "list": [
                {
                    "vod_id": "bundle",
                    "vod_name": "长剧 第52集",
                    "vod_year": "2026",
                    "type_name": "电视剧",
                    "vod_play_url": urls,
                }
            ],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1]
    assert results[0].title == "长剧 第52集"
    assert [episode.episode for episode in results[0].episodes] == list(range(1, 53))

    movie = _result_from_item(
        source,
        {
            "vod_id": "movie",
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_url": "https://video.example/a.m3u8#https://video.example/b.m3u8",
        },
    )
    assert [episode.episode for episode in movie.episodes] == [1, 1]


def test_search_episode_row_expansion_stops_after_slow_page_reaches_deadline(monkeypatch):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    client._parallel_wait_seconds = lambda: 1
    now = [0.0]
    calls = []
    monkeypatch.setattr(cms_module.time, "monotonic", lambda: now[0])

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 2:
            now[0] = 2.0
        return {"pagecount": "3", "list": [_episode_row(page)]}

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


def test_search_episode_row_expansion_skips_compat_retry_after_deadline(monkeypatch):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    client._parallel_wait_seconds = lambda: 1
    now = [0.0]
    calls = []
    monkeypatch.setattr(cms_module.time, "monotonic", lambda: now[0])

    def fake_request(_source, **params):
        calls.append((int(params["pg"]), params.get("pages")))
        now[0] = 2.0
        return {"list": []}

    client._request = fake_request

    assert client.search("长剧", limit=1, expand_tv_episode_rows=True) == []
    assert calls == [(1, None)]


def test_search_episode_row_expansion_skips_fallback_after_slow_bulk_detail(monkeypatch):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    client._parallel_wait_seconds = lambda: 1
    now = [0.0]
    calls = []
    monkeypatch.setattr(cms_module.time, "monotonic", lambda: now[0])

    def fake_request(_source, **params):
        calls.append((params.get("ac"), params.get("ids")))
        if params.get("ac") == "list":
            row = _episode_row(1)
            row.pop("vod_play_url")
            return {"pagecount": "2", "list": [row]}
        now[0] = 2.0
        return {"list": []}

    client._request = fake_request

    assert client.search(
        "长剧",
        limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
    ) == []
    assert calls == [("list", None), ("detail", "episode-1")]


def test_search_episode_row_expansion_merges_later_multi_episode_bundle_into_one_card():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            page = int(params["pg"])
            if page == 1:
                return {"pagecount": "2", "list": [_episode_row(1)]}
            return {
                "pagecount": "2",
                "list": [
                    {
                        "vod_id": "bundle",
                        "vod_name": "长剧 第52集",
                        "vod_year": "2026",
                        "type_name": "电视剧",
                    }
                ],
            }
        assert params.get("ids") == "bundle"
        return {
            "list": [
                {
                    "vod_id": "bundle",
                    "vod_name": "长剧 第52集",
                    "vod_year": "2026",
                    "type_name": "电视剧",
                    "vod_play_url": (
                        "第1集$https://video.example/bundle-e1.m3u8#"
                        "第2集$https://video.example/bundle-e2.m3u8#"
                        "第3集$https://video.example/bundle-e3.m3u8"
                    ),
                }
            ]
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert len(results) == 1
    assert [episode.episode for episode in results[0].episodes] == [1, 1, 2, 3]
    assert {episode.url for episode in results[0].episodes if episode.episode == 1} == {
        "https://video.example/长剧-1.m3u8",
        "https://video.example/bundle-e1.m3u8",
    }


def test_search_batch_detail_same_id_without_play_url_uses_individual_fallback():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    detail_calls = []

    def fake_request(_source, **params):
        if params.get("ac") == "list":
            return {
                "list": [
                    {
                        "vod_id": "same",
                        "vod_name": "回退剧",
                        "type_name": "电视剧",
                    }
                ]
            }
        detail_calls.append(params["ids"])
        assert params == {"ac": "detail", "ids": "same"}
        if len(detail_calls) == 1:
            return {"list": [{"vod_id": "same", "vod_name": "回退剧"}]}
        return {
            "list": [
                {
                    "vod_id": "same",
                    "vod_play_url": "第1集$https://video.example/fallback.m3u8",
                }
            ]
        }

    client._request = fake_request

    results = client.search("回退剧", require_playable=True)

    assert detail_calls == ["same", "same"]
    assert [episode.url for episode in results[0].episodes] == [
        "https://video.example/fallback.m3u8"
    ]


def test_search_episode_row_expansion_pages_past_unplayable_first_page_and_continues_season():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unplayable = _episode_row(1)
    unplayable["vod_play_url"] = "第1集$not-a-url"

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {
            "pagecount": "3",
            "list": {
                1: [unplayable],
                2: [_episode_row(2)],
                3: [_episode_row(3)],
            }[page],
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
    )

    assert calls == [1, 2, 3]
    assert results[0].title == "长剧"
    assert [episode.episode for episode in results[0].episodes] == [2, 3]


def test_search_episode_row_expansion_returns_later_regular_playable_result():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unplayable = _episode_row(1)
    unplayable["vod_play_url"] = "第1集$not-a-url"

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {"pagecount": "3", "list": [unplayable]}
        if page == 2:
            return {
                "pagecount": "3",
                "list": [
                    {
                        "vod_id": "regular",
                        "vod_name": "普通剧",
                        "vod_year": "2026",
                        "type_name": "电视剧",
                        "vod_play_url": "第1集$https://video.example/regular.m3u8",
                    }
                ],
            }
        raise AssertionError(params)

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
    )

    assert calls == [1, 2]
    assert [(result.title, [episode.episode for episode in result.episodes]) for result in results] == [
        ("普通剧", [1])
    ]


def test_tv_without_player_names_keeps_original_ordinal_after_bad_url():
    episodes = _parse_play_urls(
        "",
        "https://e1.m3u8#bad#https://e3.m3u8",
        number_unlabelled_multi_episode=True,
    )

    assert [(episode.episode, episode.url) for episode in episodes] == [
        (1, "https://e1.m3u8"),
        (3, "https://e3.m3u8"),
    ]


def test_search_episode_row_expansion_without_required_playable_skips_unplayable_title_row():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unplayable = {
        "vod_id": "episode-1",
        "vod_name": "长剧 S01E001",
        "vod_year": "2026",
        "type_name": "电视剧",
    }

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            calls.append(("detail", params["ids"]))
            assert params == {"ac": "detail", "ids": "episode-1"}
            return {"list": [{"vod_id": "episode-1", "vod_play_url": "not-a-url"}]}
        page = int(params["pg"])
        calls.append(("list", page))
        return {
            "pagecount": "2",
            "list": {1: [unplayable], 2: [_episode_row(2)]}[page],
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=False,
        expand_tv_episode_rows=True,
    )

    assert calls == [("list", 1), ("detail", "episode-1"), ("list", 2)]
    assert [(result.title, [episode.episode for episode in result.episodes]) for result in results] == [
        ("长剧", [2])
    ]


def test_search_episode_row_expansion_enriches_unknown_year_but_rejects_conflict():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unknown_year = {
        "vod_id": "episode-2",
        "vod_name": "长剧 S01E002",
        "type_name": "电视剧",
    }

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            calls.append(("detail", params["ids"]))
            assert params == {"ac": "detail", "ids": "episode-2"}
            return {
                "list": [
                    {
                        "vod_id": "episode-2",
                        "vod_year": "2026",
                        "vod_play_url": "第2集$https://video.example/long-show-2.m3u8",
                    }
                ]
            }
        page = int(params["pg"])
        calls.append(("list", page))
        return {
            "pagecount": "3",
            "list": {
                1: [_episode_row(1)],
                2: [unknown_year],
                3: [_episode_row(3, year="2025")],
            }[page],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [
        ("list", 1),
        ("list", 2),
        ("detail", "episode-2"),
        ("list", 3),
    ]
    assert [(episode.episode, episode.url) for episode in results[0].episodes] == [
        (1, "https://video.example/长剧-1.m3u8"),
        (2, "https://video.example/long-show-2.m3u8"),
    ]


def test_search_episode_row_expansion_stops_after_detail_year_conflict():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unknown_year = {
        "vod_id": "episode-2",
        "vod_name": "长剧 S01E002",
        "type_name": "电视剧",
    }

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            calls.append(("detail", params["ids"]))
            assert params == {"ac": "detail", "ids": "episode-2"}
            return {
                "list": [
                    {
                        "vod_id": "episode-2",
                        "vod_year": "2025",
                        "vod_play_url": "第2集$https://video.example/conflict-e2.m3u8",
                    }
                ]
            }
        page = int(params["pg"])
        calls.append(("list", page))
        return {
            "pagecount": "3",
            "list": {
                1: [_episode_row(1)],
                2: [unknown_year],
                3: [_episode_row(3)],
            }[page],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [("list", 1), ("list", 2), ("detail", "episode-2")]
    assert [(result.year, [episode.episode for episode in result.episodes]) for result in results] == [
        ("2026", [1])
    ]


def test_search_episode_row_expansion_upgrades_unknown_group_year():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {
            "pagecount": "2",
            "list": {
                1: [_episode_row(1, year="")],
                2: [_episode_row(2)],
            }[page],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [(result.year, [episode.episode for episode in result.episodes]) for result in results] == [
        ("2026", [1, 2])
    ]


def test_search_episode_row_expansion_stops_on_ambiguous_unknown_year():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    year_2025 = _episode_row(1, year="2025")
    year_2025["vod_id"] = "episode-2025"
    year_2026 = _episode_row(1, year="2026")
    year_2026["vod_id"] = "episode-2026"

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {"pagecount": "3", "list": [year_2025, year_2026]}
        if page == 2:
            return {"pagecount": "3", "list": [_episode_row(2, year="")]}
        raise AssertionError("ambiguous rows must stop expansion")

    client._request = fake_request

    results = client.search("长剧", limit=2, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [(result.year, [episode.episode for episode in result.episodes]) for result in results] == [
        ("2025", [1]),
        ("2026", [1]),
    ]


def test_search_episode_row_expansion_keeps_ambiguous_first_page_years_separate():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    unknown_year = _episode_row(1, year="")
    year_2025 = _episode_row(2, year="2025")
    year_2026 = _episode_row(3, year="2026")

    def fake_request(_source, **params):
        assert int(params["pg"]) == 1
        return {
            "pagecount": "1",
            "list": [unknown_year, year_2025, year_2026],
        }

    client._request = fake_request

    results = client.search("长剧", limit=3, expand_tv_episode_rows=True)

    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [
        ("", [1]),
        ("2025", [2]),
        ("2026", [3]),
    ]


def test_search_episode_row_expansion_stops_before_later_page_year_conflict():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    unknown_year = _episode_row(2, year="")
    unknown_year["vod_id"] = "episode-unknown"
    year_2026 = _episode_row(2, year="2026")
    year_2026["vod_id"] = "episode-2026"

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {"pagecount": "3", "list": [_episode_row(1, year="2025")]}
        if page == 2:
            return {"pagecount": "3", "list": [unknown_year, year_2026]}
        raise AssertionError("conflicting year page must stop expansion")

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [("2025", [1])]


def test_search_episode_row_expansion_remembers_years_excluded_by_limit():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    year_2025 = _episode_row(1, year="2025")
    year_2025["vod_id"] = "episode-2025"
    year_2026 = _episode_row(1, year="2026")
    year_2026["vod_id"] = "episode-2026"

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {"pagecount": "2", "list": [year_2025, year_2026]}
        return {"pagecount": "2", "list": [_episode_row(2, year="")]}

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [("2025", [1])]


def test_search_episode_row_expansion_restores_unknown_year_after_later_conflict():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {
            "pagecount": "3",
            "list": {
                1: [_episode_row(1, year="")],
                2: [_episode_row(2, year="2025")],
                3: [_episode_row(3, year="2026")],
            }[page],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2, 3]
    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [("", [1])]


def test_search_episode_row_expansion_prefers_playable_bundle_over_title_only_fallback():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    title_only = {
        "vod_id": "bad-row",
        "vod_name": "长剧 S01E001",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": "not-a-url",
    }
    bundle = {
        "vod_id": "bundle",
        "vod_name": "长剧 S01E002",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": (
            "第1集$https://video.example/bundle-e1.m3u8#"
            "第2集$https://video.example/bundle-e2.m3u8"
        ),
    }

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {"pagecount": "2", "list": {1: [title_only], 2: [bundle]}[page]}

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=False,
        expand_tv_episode_rows=True,
    )

    assert calls == [1, 2]
    assert [(result.vod_id, [episode.episode for episode in result.episodes]) for result in results] == [
        ("bundle", [1, 2])
    ]


def test_search_episode_row_expansion_merges_all_playable_fallback_bundles():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    title_only = {
        "vod_id": "bad-row",
        "vod_name": "长剧 S01E001",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": "not-a-url",
    }
    first_bundle = {
        "vod_id": "bundle-1",
        "vod_name": "长剧 S01E002",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": (
            "第1集$https://video.example/bundle-e1.m3u8#"
            "第2集$https://video.example/bundle-e2.m3u8"
        ),
    }
    second_bundle = {
        "vod_id": "bundle-2",
        "vod_name": "长剧 S01E004",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": (
            "第3集$https://video.example/bundle-e3.m3u8#"
            "第4集$https://video.example/bundle-e4.m3u8"
        ),
    }

    def fake_request(_source, **params):
        page = int(params["pg"])
        return {
            "pagecount": "3",
            "list": {
                1: [title_only],
                2: [first_bundle],
                3: [second_bundle],
            }[page],
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=False,
        expand_tv_episode_rows=True,
    )

    assert len(results) == 1
    assert [episode.episode for episode in results[0].episodes] == [1, 2, 3, 4]


def test_search_episode_row_expansion_does_not_upgrade_ambiguous_unknown_year():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    year_2025 = _episode_row(1, year="2025")
    year_2025["vod_id"] = "episode-2025"
    year_2026 = _episode_row(1, year="2026")
    year_2026["vod_id"] = "episode-2026"
    unknown_year = {
        "vod_id": "episode-2",
        "vod_name": "长剧 S01E002",
        "type_name": "电视剧",
    }

    def fake_request(_source, **params):
        if params.get("ac") == "detail":
            calls.append(("detail", params["ids"]))
            return {
                "list": [
                    {
                        "vod_id": "episode-2",
                        "vod_year": "2026",
                        "vod_play_url": "第2集$https://video.example/resolved-e2.m3u8",
                    }
                ]
            }
        page = int(params["pg"])
        calls.append(("list", page))
        return {"pagecount": "2", "list": {1: [year_2025, year_2026], 2: [unknown_year]}[page]}

    client._request = fake_request

    results = client.search("长剧", limit=2, expand_tv_episode_rows=True)

    assert calls == [("list", 1), ("list", 2)]
    assert [(result.year, [episode.episode for episode in result.episodes]) for result in results] == [
        ("2025", [1]),
        ("2026", [1]),
    ]


def test_search_episode_row_expansion_remembers_unplayable_year_candidates():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    unknown_year = _episode_row(1, year="")
    unknown_year["vod_id"] = "episode-unknown"
    year_2025 = _episode_row(1, year="2025")
    year_2025["vod_id"] = "episode-2025"
    year_2026 = _episode_row(1, year="2026")
    year_2026["vod_id"] = "episode-2026"
    year_2026["vod_play_url"] = "第1集$not-a-url"

    def fake_request(_source, **params):
        assert params.get("ac") == "list"
        return {
            "pagecount": "1",
            "list": [unknown_year, year_2025, year_2026],
        }

    client._request = fake_request

    results = client.search(
        "长剧",
        limit=1,
        require_playable=True,
        expand_tv_episode_rows=True,
    )

    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [("", [1])]


def test_search_episode_row_expansion_restores_all_conflicting_unknown_groups():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])

    def row(index, *, title, year):
        item = _episode_row(index, title=title, year=year)
        item["vod_id"] = f"{title}-{year or 'unknown'}-{index}"
        return item

    pages = {
        1: [
            row(1, title="长剧甲", year=""),
            row(1, title="长剧乙", year=""),
        ],
        2: [
            row(2, title="长剧甲", year="2025"),
            row(2, title="长剧乙", year="2025"),
        ],
        3: [
            row(3, title="长剧甲", year="2026"),
            row(3, title="长剧乙", year="2026"),
        ],
    }

    def fake_request(_source, **params):
        page = int(params["pg"])
        return {"pagecount": "3", "list": pages[page]}

    client._request = fake_request

    results = client.search("长剧", limit=2, expand_tv_episode_rows=True)

    assert [
        (result.year, [episode.episode for episode in result.episodes])
        for result in results
    ] == [("", [1]), ("", [1])]


@pytest.mark.parametrize(
    "years",
    (("2025", "2026"), ("2026", "2025")),
    ids=("2025-first", "2026-first"),
)
def test_search_episode_row_expansion_stops_before_ambiguous_year_page_mutates(years):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []

    def row(year):
        item = _episode_row(2, year=year)
        item["vod_id"] = f"episode-{year}"
        return item

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        if page == 1:
            return {"pagecount": "3", "list": [_episode_row(1, year="")]}
        if page == 2:
            return {"pagecount": "3", "list": [row(year) for year in years]}
        raise AssertionError("ambiguous page must stop expansion")

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2]
    assert [(result.year, [episode.episode for episode in result.episodes]) for result in results] == [
        ("", [1])
    ]


def test_search_episode_row_expansion_processes_idless_page_once_by_content_signature():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    calls = []
    idless_row = {
        "vod_name": "长剧 S01E002",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": "第2集$https://video.example/idless-e2.m3u8",
    }

    def fake_request(_source, **params):
        page = int(params["pg"])
        calls.append(page)
        return {
            "pagecount": "4",
            "list": {1: [_episode_row(1)], 2: [idless_row], 3: [idless_row]}[page],
        }

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert calls == [1, 2, 3]
    assert [episode.episode for episode in results[0].episodes] == [1, 2]


@pytest.mark.parametrize("bundle_first", (True, False), ids=("bundle-first", "row-first"))
def test_search_episode_row_expansion_merges_same_page_bundle_regardless_of_order(bundle_first):
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    client = AppleCmsClient([source])
    row = _episode_row(1)
    bundle = {
        "vod_id": "bundle",
        "vod_name": "长剧 S01E001",
        "vod_year": "2026",
        "type_name": "电视剧",
        "vod_play_url": (
            "第1集$https://video.example/bundle-e1.m3u8#"
            "第2集$https://video.example/bundle-e2.m3u8#"
            "第3集$https://video.example/bundle-e3.m3u8"
        ),
    }

    def fake_request(_source, **params):
        assert params == {"ac": "list", "wd": "长剧", "pg": 1}
        return {"pagecount": "1", "list": [bundle, row] if bundle_first else [row, bundle]}

    client._request = fake_request

    results = client.search("长剧", limit=1, expand_tv_episode_rows=True)

    assert len(results) == 1
    assert results[0].title == "长剧"
    assert [episode.episode for episode in results[0].episodes] == [1, 1, 2, 3]
    assert {episode.url for episode in results[0].episodes if episode.episode == 1} == {
        "https://video.example/长剧-1.m3u8",
        "https://video.example/bundle-e1.m3u8",
    }


def test_tv_without_player_names_prefers_largest_valid_group_stably_and_movies_keep_first():
    source = CmsSource(key="demo", name="演示", api="https://cms.example/vod")
    largest = _result_from_item(
        source,
        {
            "vod_id": "largest",
            "vod_name": "多线路剧",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/first-1.m3u8$$$"
                "第1集$https://video.example/second-1.m3u8#"
                "第2集$https://video.example/second-2.m3u8#"
                "损坏$not-a-url"
            ),
        },
    )
    tied = _result_from_item(
        source,
        {
            "vod_id": "tied",
            "vod_name": "并列剧",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/tie-first-1.m3u8#"
                "第2集$https://video.example/tie-first-2.m3u8$$$"
                "第1集$https://video.example/tie-second-1.m3u8#"
                "第2集$https://video.example/tie-second-2.m3u8"
            ),
        },
    )
    movie = _result_from_item(
        source,
        {
            "vod_id": "movie",
            "vod_name": "多线路电影",
            "type_name": "电影",
            "vod_play_url": (
                "正片$https://video.example/movie-first.m3u8$$$"
                "正片$https://video.example/movie-second-1.m3u8#"
                "备份$https://video.example/movie-second-2.m3u8"
            ),
        },
    )

    assert [episode.url for episode in largest.episodes] == [
        "https://video.example/second-1.m3u8",
        "https://video.example/second-2.m3u8",
    ]
    assert [episode.url for episode in tied.episodes] == [
        "https://video.example/tie-first-1.m3u8",
        "https://video.example/tie-first-2.m3u8",
    ]
    assert [episode.url for episode in movie.episodes] == [
        "https://video.example/movie-first.m3u8"
    ]


def test_search_can_stop_after_first_source_with_results():
    sources = [
        CmsSource(key="first", name="首选", api="https://first.example/vod"),
        CmsSource(key="second", name="备用", api="https://second.example/vod"),
    ]
    client = AppleCmsClient(sources)
    called = []

    def fake_request(source, **params):
        called.append(source.key)
        return {
            "list": [{
                "vod_id": source.key,
                "vod_name": "示例电影",
                "type_name": "电影",
                "vod_play_from": "在线播放",
                "vod_play_url": "正片$https://example.test/movie.m3u8",
            }]
        }

    client._request = fake_request
    results = client.search("示例电影", stop_after_first_source=True)
    assert [item.source_key for item in results] == ["first"]
    assert set(called) == {"first"}


def test_search_aggregates_multiple_sources_with_stable_source_order():
    sources = [
        CmsSource(key="first", name="首选", api="https://first.example/vod"),
        CmsSource(key="second", name="第二", api="https://second.example/vod"),
    ]
    client = AppleCmsClient(sources)

    def fake_request(source, **params):
        if source.key == "first":
            return {
                "list": [
                    {
                        "vod_id": "10",
                        "vod_name": "示例电影",
                        "type_name": "电影",
                        "vod_play_from": "在线播放",
                        "vod_play_url": "01$https://first.example/10.m3u8",
                    },
                    {
                        "vod_id": "11",
                        "vod_name": "示例电影",
                        "type_name": "电影",
                        "vod_play_from": "在线播放",
                        "vod_play_url": "01$https://first.example/11.m3u8",
                    },
                ]
            }
        return {
            "list": [
                {
                    "vod_id": "20",
                    "vod_name": "示例电影",
                    "type_name": "电影",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "01$https://second.example/20.m3u8",
                },
                {
                    "vod_id": "21",
                    "vod_name": "示例电影",
                    "type_name": "电影",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "01$https://second.example/21.m3u8",
                },
            ]
        }

    client._request = fake_request
    results = client.search(
        "示例电影",
        limit=3,
        source_limit=2,
        stop_after_first_source=False,
        max_workers=2,
    )
    assert [(item.source_key, item.vod_id) for item in results] == [
        ("first", "10"),
        ("first", "11"),
        ("second", "20"),
    ]


def test_search_multi_source_requests_run_concurrently():
    from threading import Barrier

    sources = [
        CmsSource(key="first", name="首选", api="https://first.example/vod"),
        CmsSource(key="second", name="第二", api="https://second.example/vod"),
    ]
    client = AppleCmsClient(sources)
    rendezvous = Barrier(2, timeout=1)

    def fake_request(source, **params):
        rendezvous.wait()
        return {"list": [{
            "vod_id": source.key,
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_from": "在线播放",
            "vod_play_url": f"正片$https://{source.key}.example/movie.m3u8",
        }]}

    client._request = fake_request
    results = client.search("示例电影", limit=10, max_workers=2)
    assert [item.source_key for item in results] == ["first", "second"]


def test_search_parallel_does_not_abandon_other_sources_on_error():
    sources = [
        CmsSource(key="bad", name="异常", api="https://bad.example/vod"),
        CmsSource(key="good", name="可用", api="https://good.example/vod"),
    ]
    client = AppleCmsClient(sources)

    def fake_request(source, **params):
        if source.key == "bad":
            raise RuntimeError("source bad")
        return {
            "list": [
                {
                    "vod_id": "20",
                    "vod_name": "示例电影",
                    "type_name": "电影",
                    "vod_play_from": "在线播放",
                    "vod_play_url": "正片$https://example.test/movie.m3u8",
                },
            ]
        }

    client._request = fake_request
    results = client.search(
        "示例电影",
        limit=10,
        stop_after_first_source=False,
        require_playable=True,
        max_workers=2,
    )
    assert len(results) == 1
    assert results[0].source_key == "good"


def test_search_parallel_returns_completed_sources_within_total_budget():
    from threading import Event

    sources = [
        CmsSource(key="slow", name="慢源", api="https://slow.example/vod"),
        CmsSource(key="second", name="第二", api="https://second.example/vod"),
        CmsSource(key="third", name="第三", api="https://third.example/vod"),
    ]
    client = AppleCmsClient(sources, parallel_wait_timeout=0.05)
    slow_started = Event()
    release_slow = Event()

    def result_for(source):
        return [{
            "vod_id": source.key,
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_from": "在线播放",
            "vod_play_url": f"正片$https://{source.key}.example/movie.m3u8",
        }]

    def fake_search_source(source, **params):
        if source.key == "slow":
            slow_started.set()
            release_slow.wait(1)
        elif source.key == "second":
            # Complete after the third source to prove completed results are
            # merged in source order, not completion order.
            time.sleep(0.02)
        return [_result_from_item(source, item) for item in result_for(source)]

    client._search_source = fake_search_source
    started = time.monotonic()
    results = client.search("示例电影", limit=10, max_workers=3)
    elapsed = time.monotonic() - started
    try:
        assert slow_started.is_set()
        assert elapsed < 0.3
        assert [item.source_key for item in results] == ["second", "third"]
    finally:
        # Let the still-running worker finish so the test process does not
        # retain a deliberately slow task.
        release_slow.set()


def test_search_skips_non_playable_source_when_playable_result_is_required():
    sources = [
        CmsSource(key="empty", name="空播放源", api="https://empty.example/vod"),
        CmsSource(key="playable", name="可播放源", api="https://playable.example/vod"),
    ]
    client = AppleCmsClient(sources)

    def fake_request(source, **params):
        if params.get("ac") == "detail" and source.key == "empty":
            return {"list": [{"vod_id": "empty", "vod_name": "示例电影"}]}
        return {
            "list": [{
                "vod_id": source.key,
                "vod_name": "示例电影",
                "type_name": "电影",
                "vod_play_from": "在线播放" if source.key == "playable" else "",
                "vod_play_url": (
                    "正片$https://example.test/movie.m3u8"
                    if source.key == "playable"
                    else ""
                ),
            }]
        }

    client._request = fake_request
    results = client.search(
        "示例电影",
        stop_after_first_source=True,
        require_playable=True,
    )
    assert [item.source_key for item in results] == ["playable"]
    assert results[0].episodes[0].url == "https://example.test/movie.m3u8"


def test_result_uses_title_season_hint_for_multi_season_bundle():
    result = _result_from_item(
        CmsSource(key="demo", name="演示", api="https://cms.example/api.php/provide/vod"),
        {
            "vod_id": "8",
            "vod_name": "海底小纵队中文版 (1-8季)",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": "01$https://example.test/01.m3u8#02$https://example.test/02.m3u8",
        },
    )
    assert [(item.season, item.episode) for item in result.episodes] == [(1, 1), (1, 2)]
    assert result.season_range == (1, 8)
    assert result.season_ambiguous is True

    season_eight = _result_from_item(
        CmsSource(key="demo", name="演示", api="https://cms.example/api.php/provide/vod"),
        {
            "vod_id": "8b",
            "vod_name": "海底小纵队中文版 第8季",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": "01$https://example.test/08-01.m3u8",
        },
    )
    assert season_eight.episodes[0].season == 8


def test_flat_multi_season_bundle_can_be_mapped_by_exact_tmdb_counts():
    result = _result_from_item(
        CmsSource(key="demo", name="演示", api="https://cms.example/api.php/provide/vod"),
        {
            "vod_id": "bundle",
            "vod_name": "示例合集 1-2季",
            "type_name": "电视剧",
            "vod_play_from": "在线播放",
            "vod_play_url": "01$https://example.test/01.m3u8#02$https://example.test/02.m3u8#03$https://example.test/03.m3u8",
        },
    )
    mapped = apply_season_counts(result, {1: 2, 2: 1})
    assert mapped.season_ambiguous is False
    assert [(item.season, item.episode) for item in mapped.episodes] == [(1, 1), (1, 2), (2, 1)]


def test_animation_is_treated_as_series_for_season_naming():
    result = _result_from_item(
        CmsSource(key="demo", name="演示", api="https://cms.example/api.php/provide/vod"),
        {
            "vod_id": "cartoon",
            "vod_name": "示例动画",
            "type_name": "动漫",
           "vod_play_from": "在线播放",
           "vod_play_url": "01$https://example.test/01.m3u8#02$https://example.test/02.m3u8",
       },
   )
    assert result.media_type == "tv"


def test_result_from_item_recognizes_regional_drama_category_without_movie_class_leak():
    result = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": "green-lantern-corps",
            "vod_name": "绿灯军团",
            "type_name": "欧美剧",
            "vod_class": "剧情",
            "vod_remarks": "更新至02集",
            "vod_play_url": "第01集$https://example.test/01.m3u8#第02集$https://example.test/02.m3u8",
        },
    )
    assert result.media_type == "tv"

    movie = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": "drama-movie",
            "vod_name": "剧情片",
            "type_name": "剧情片",
            "vod_class": "剧情",
            "vod_play_url": "正片$https://example.test/movie.m3u8",
        },
    )
    assert movie.media_type == "movie"

@pytest.mark.parametrize("type_name", ("喜剧", "悲剧", "戏剧", "舞台剧"))
def test_result_from_item_does_not_treat_generic_drama_labels_as_tv(type_name: str):
    result = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": f"movie-{type_name}",
            "vod_name": type_name,
            "type_name": type_name,
            "vod_class": type_name,
            "vod_play_url": "正片$https://example.test/movie.m3u8",
        },
    )

    assert result.media_type == "movie"

@pytest.mark.parametrize("type_name", ("欧美剧", "韩剧", "日剧", "泰剧", "港剧", "台剧"))
def test_result_from_item_recognizes_explicit_regional_tv_categories(type_name: str):
    result = _result_from_item(
        CmsSource("demo", "演示", "https://cms.example/vod"),
        {
            "vod_id": f"series-{type_name}",
            "vod_name": type_name,
            "type_name": type_name,
            "vod_class": "剧情",
            "vod_play_url": "第01集$https://example.test/01.m3u8",
        },
    )

    assert result.media_type == "tv"

def test_search_progress_reports_parallel_completion_before_total_budget():
    from threading import Barrier, Event

    sources = [
        CmsSource(key="slow", name="slow", api="https://slow.example/vod"),
        CmsSource(key="fast", name="fast", api="https://fast.example/vod"),
    ]
    client = AppleCmsClient(sources, parallel_wait_timeout=1)
    rendezvous = Barrier(2, timeout=1)
    progress_reached = Event()
    slow_observed_progress = Event()
    release_slow = Event()
    progress = []

    def fake_search_source(source, **_params):
        rendezvous.wait()
        if source.key == "slow":
            if progress_reached.wait(0.75):
                slow_observed_progress.set()
            release_slow.wait(1)
        return []

    def on_progress(**event):
        progress.append(event)
        if event["finished"] == 1:
            progress_reached.set()
            release_slow.set()

    client._search_source = fake_search_source
    assert client.search("demo", max_workers=2, progress_callback=on_progress) == []

    assert slow_observed_progress.is_set()
    assert [(event["finished"], event["total"]) for event in progress] == [(1, 2), (2, 2)]
    assert [event["text"] for event in progress] == ["正在搜索源 1/2", "正在搜索源 2/2"]

def test_search_progress_advances_after_parallel_source_error_and_callback_error():
    sources = [
        CmsSource(key="bad", name="bad", api="https://bad.example/vod"),
        CmsSource(key="good", name="good", api="https://good.example/vod"),
    ]
    client = AppleCmsClient(sources)
    progress = []

    def fake_search_source(source, **_params):
        if source.key == "bad":
            raise RuntimeError("bad source")
        return []

    def on_progress(**event):
        progress.append(event)
        if event["finished"] == 1:
            raise RuntimeError("broken UI callback")

    client._search_source = fake_search_source
    assert client.search("demo", max_workers=2, progress_callback=on_progress) == []
    assert [(event["finished"], event["total"]) for event in progress] == [(1, 2), (2, 2)]

def test_search_progress_settles_timeout_once_without_late_worker_callback():
    from threading import Event

    sources = [
        CmsSource(key="slow", name="slow", api="https://slow.example/vod"),
        CmsSource(key="fast", name="fast", api="https://fast.example/vod"),
    ]
    client = AppleCmsClient(sources, parallel_wait_timeout=0.05)
    slow_started = Event()
    release_slow = Event()
    slow_finished = Event()
    progress = []

    def fake_search_source(source, **_params):
        if source.key == "slow":
            slow_started.set()
            release_slow.wait(1)
            slow_finished.set()
        return []

    client._search_source = fake_search_source
    try:
        assert client.search(
            "demo",
            max_workers=2,
            progress_callback=lambda **event: progress.append(event),
        ) == []
        assert slow_started.is_set()
        assert [(event["finished"], event["total"]) for event in progress] == [(1, 2), (2, 2)]
    finally:
        release_slow.set()

    assert slow_finished.wait(1)
    assert len(progress) == 2

def test_search_progress_settles_skipped_sources_after_stop_after_first_source():
    sources = [
        CmsSource(key="first", name="first", api="https://first.example/vod"),
        CmsSource(key="second", name="second", api="https://second.example/vod"),
    ]
    client = AppleCmsClient(sources)
    called = []
    progress = []

    def fake_search_source(source, **_params):
        called.append(source.key)
        return [] if source.key == "second" else [
            _result_from_item(
                source,
                {
                    "vod_id": "first",
                    "vod_name": "demo",
                    "type_name": "movie",
                    "vod_play_url": "main$https://first.example/demo.m3u8",
                },
            )
        ]

    client._search_source = fake_search_source
    results = client.search(
        "demo",
        stop_after_first_source=True,
        progress_callback=lambda **event: progress.append(event),
    )

    assert [result.source_key for result in results] == ["first"]
    assert called == ["first"]
    assert [(event["finished"], event["total"]) for event in progress] == [(1, 2), (2, 2)]
