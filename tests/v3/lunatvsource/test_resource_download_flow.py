import threading
from pathlib import Path

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import CmsSource, _result_from_item


class FakeTorrentInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _configured_plugin(monkeypatch, results):
    class Client:
        def search(self, *_args, **_kwargs):
            return list(results)

    plugin = _plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", FakeTorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        plugin_module,
        "probe_stream_height",
        lambda url, *_args, **_kwargs: 1080 if "1080" in url else 480,
    )
    return plugin


class _PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = _PluginData()
    plugin._logger = plugin_module.LOGGER
    plugin._download_metrics_lock = threading.Lock()
    plugin._download_metrics = {}
    plugin._quality_cache_lock = threading.Lock()
    plugin._quality_cache = {}
    plugin._quality_probe_ms = {}
    plugin._completed_download_sizes = {}
    plugin._source_health_lock = threading.RLock()
    plugin._source_health_running = False
    plugin._source_health = {}
    plugin._source_health_stop = threading.Event()
    plugin._source_health_thread = None
    plugin._source_health_pending_keys = set()
    plugin._source_health_pending_full = False
    plugin._source_health_last_error = ""
    plugin._source_health_last_finished = 0.0
    plugin._source_health_revision = 0
    plugin.init_plugin(config)
    return plugin

def test_search_movie_resources_are_sorted_and_download_queues_highest_resolution(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    low = _result_from_item(
        source,
        {
            "vod_id": "movie-low",
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/480.m3u8",
        },
    )
    high = _result_from_item(
        source,
        {
            "vod_id": "movie-high",
            "vod_name": "示例电影",
            "type_name": "电影",
            "vod_play_url": "正片$https://video.example/1080.m3u8",
        },
    )
    plugin = _configured_plugin(monkeypatch, [low, high])

    resources = plugin.search_torrents(
        {"id": "demo"}, "示例电影", mtype="电影"
    )

    assert [item.title for item in resources] == [
        "示例电影 · 1080P",
        "示例电影 · 480P",
    ]
    assert [item.pri_order for item in resources] == [108, 48]
    assert [
        plugin._decode_resource_token(item.enclosure)["resolution"]
        for item in resources
    ] == ["1080P", "480P"]

    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    result = plugin.download(resources[0].enclosure, tmp_path)

    assert result[0] == "LunaTVSource"
    tasks = plugin._queue._read()
    assert len(tasks) == 1
    assert tasks[0].url == "https://video.example/1080.m3u8"


def test_search_tv_resources_are_season_cards_and_download_runs_episodes_serially(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    low = _result_from_item(
        source,
        {
            "vod_id": "season-low",
            "vod_name": "示例剧 第一季",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/480-e1.m3u8#"
                "第2集$https://video.example/480-e2.m3u8"
            ),
        },
    )
    high = _result_from_item(
        source,
        {
            "vod_id": "season-high",
            "vod_name": "示例剧 第一季",
            "type_name": "电视剧",
            "vod_play_url": (
                "第1集$https://video.example/1080-e1.m3u8#"
                "第2集$https://video.example/1080-e2.m3u8"
            ),
        },
    )
    plugin = _configured_plugin(monkeypatch, [low, high])
    monkeypatch.setattr(plugin, "_start_queue", lambda: True)

    resources = plugin.search_torrents(
        {"id": "demo"}, "示例剧", mtype="电视剧"
    )

    assert [item.title for item in resources] == [
        "示例剧 · 第1季",
        "示例剧 · 第1季",
    ]
    assert all("集" not in item.title for item in resources)
    assert [item.pri_order for item in resources] == [108, 48]
    high_payload = plugin._decode_resource_token(resources[0].enclosure)
    assert [episode["episode"] for episode in high_payload["episodes"]] == [1, 2]

    result = plugin.download(resources[0].enclosure, tmp_path)

    assert result[0] == "LunaTVSource"
    queued = plugin._queue._read()
    assert [(task.season, task.episode, task.url) for task in queued] == [
        (1, 1, "https://video.example/1080-e1.m3u8"),
        (1, 2, "https://video.example/1080-e2.m3u8"),
    ]

    executed = []

    def fake_execute(task):
        executed.append((task.episode, task.url))
        return str(tmp_path / f"episode-{task.episode}.mp4")

    plugin._queue._execute = fake_execute
    assert plugin._queue.run_one()["state"] == "completed"
    assert plugin._queue.run_one()["state"] == "completed"
    assert executed == [
        (1, "https://video.example/1080-e1.m3u8"),
        (2, "https://video.example/1080-e2.m3u8"),
    ]


def test_long_season_cards_probe_one_episode_and_keep_full_hd_download(
    monkeypatch, tmp_path: Path
):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    mixed_urls = [
        f"https://video.example/mixed-{'480' if episode == 2 else '1080'}-e{episode}.m3u8"
        for episode in range(1, 7)
    ]
    full_hd_urls = [
        f"https://video.example/full-1080-e{episode}.m3u8"
        for episode in range(1, 7)
    ]
    mixed = _result_from_item(
        source,
        {
            "vod_id": "season-mixed",
            "vod_name": "长季剧",
            "type_name": "电视剧",
            "vod_play_url": "#".join(
                f"第{episode}集${url}" for episode, url in enumerate(mixed_urls, start=1)
            ),
        },
    )
    full_hd = _result_from_item(
        source,
        {
            "vod_id": "season-full-hd",
            "vod_name": "长季剧",
            "type_name": "电视剧",
            "vod_play_url": "#".join(
                f"第{episode}集${url}"
                for episode, url in enumerate(full_hd_urls, start=1)
            ),
        },
    )
    plugin = _configured_plugin(monkeypatch, [mixed, full_hd])
    probed_urls = []

    def probe(url, *_args, **_kwargs):
        probed_urls.append(url)
        return 480 if "mixed-480-e2" in url else 1080

    monkeypatch.setattr(plugin_module, "probe_stream_height", probe)

    resources = plugin.search_torrents(
        {"id": "demo"}, "长季剧", mtype="电视剧"
    )

    assert [item.pri_order for item in resources] == [108, 108]
    assert [item.title for item in resources] == [
        "长季剧 · 第1季",
        "长季剧 · 第1季",
    ]
    assert all("抽样" not in item.description for item in resources)
    assert all("全6集实测" not in item.description for item in resources)
    assert all("已测" not in item.description for item in resources)
    assert sorted(probed_urls) == sorted([mixed_urls[0], full_hd_urls[0]])

    payloads = [plugin._decode_resource_token(item.enclosure) for item in resources]
    assert all(payload["resolution_scope"] == "sample" for payload in payloads)
    assert all(payload["resolution_probed_episode_count"] == 1 for payload in payloads)
    assert all(payload["resolution_probed_episodes"] == [1] for payload in payloads)
    assert all(
        [episode["resolution_height"] for episode in payload["episodes"]]
        == [1080, 0, 0, 0, 0, 0]
        for payload in payloads
    )
    full_hd_payload = next(
        payload
        for payload in payloads
        if any("full-1080" in episode["url"] for episode in payload["episodes"])
    )
    full_hd_resource = next(
        item
        for item, payload in zip(resources, payloads)
        if payload is full_hd_payload
    )
    assert all("480" not in episode["url"] for episode in full_hd_payload["episodes"])

    monkeypatch.setattr(plugin, "_start_queue", lambda: None)
    result = plugin.download(full_hd_resource.enclosure, tmp_path)

    assert result[0] == "LunaTVSource"
    assert all("480" not in task.url for task in plugin._queue._read())
