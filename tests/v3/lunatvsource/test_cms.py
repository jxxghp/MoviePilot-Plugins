import json
import socket
import time

import pytest

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
