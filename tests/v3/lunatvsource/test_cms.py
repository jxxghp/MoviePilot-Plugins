import json
import time

from app.plugins.lunatvsource.cms import (
    AppleCmsClient,
    CmsSource,
    _parse_play_urls,
    _result_from_item,
    apply_season_counts,
    parse_config,
    probe_stream_height,
    stream_quality_label,
)


def test_stream_quality_label_uses_actual_video_height():
    assert stream_quality_label(2160) == "4K"
    assert stream_quality_label(1080) == "1080P"
    assert stream_quality_label(720) == "720P"
    assert stream_quality_label(480) == "480P"
    assert stream_quality_label(608) == "608P"
    assert stream_quality_label(360) == "360P"
    assert stream_quality_label(0) == "未知"


def test_probe_stream_height_reads_master_playlist_resolution(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return (
                b"#EXTM3U\n"
                b"#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720\n720.m3u8\n"
                b"#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080\n1080.m3u8\n"
            )

    monkeypatch.setattr("app.plugins.lunatvsource.cms.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    assert probe_stream_height("https://example.test/master.m3u8") == 1080


def test_probe_stream_height_falls_back_to_first_video_stream(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"#EXTM3U\n#EXTINF:6,\nsegment-001.ts\n"

    class ProcessResult:
        stdout = "854x480\n"

    monkeypatch.setattr("app.plugins.lunatvsource.cms.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("app.plugins.lunatvsource.cms.subprocess.run", lambda *_args, **_kwargs: ProcessResult())
    assert probe_stream_height("https://example.test/media.m3u8") == 480


def test_probe_stream_height_decodes_one_frame_when_ffprobe_has_no_dimensions(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"#EXTM3U\n#EXTINF:6,\nsegment-001.ts\n"

    results = iter([
        type("ProbeResult", (), {"stdout": "", "stderr": ""})(),
        type("FrameResult", (), {"stdout": "", "stderr": "Video: h264, 1280x720"})(),
    ])
    monkeypatch.setattr("app.plugins.lunatvsource.cms.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("app.plugins.lunatvsource.cms.subprocess.run", lambda *_args, **_kwargs: next(results))

    assert probe_stream_height("https://example.test/media.m3u8") == 720


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

    def fake_search_source(source, **params):
        if source.key == "slow":
            slow_started.set()
            release_slow.wait(1)
        elif source.key == "second":
            time.sleep(0.02)
        item = {
            "vod_id": source.key,
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_from": "在线播放",
            "vod_play_url": f"正片$https://{source.key}.example/movie.m3u8",
        }
        return [_result_from_item(source, item)]

    client._search_source = fake_search_source
    started = time.monotonic()
    results = client.search("示例电影", limit=10, max_workers=3)
    elapsed = time.monotonic() - started
    try:
        assert slow_started.is_set()
        assert elapsed < 0.3
        assert [item.source_key for item in results] == ["second", "third"]
    finally:
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
