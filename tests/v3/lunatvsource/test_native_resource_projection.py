import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import CmsEpisode, CmsResult


def test_tv_native_projection_keeps_quality_out_of_card_title_and_description(monkeypatch):
    class TorrentInfo:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    rows = [
        CmsResult(
            source_key="high",
            source_name="高清源",
            vod_id="s02-high",
            title="示例剧",
            year="2024",
            media_type="tv",
            remark="",
            episodes=(CmsEpisode(2, 1, "第1集", "https://video.example/1080-s02.m3u8"),),
        ),
        CmsResult(
            source_key="low",
            source_name="标清源",
            vod_id="s02-low",
            title="示例剧",
            year="2024",
            media_type="tv",
            remark="",
            episodes=(CmsEpisode(2, 1, "第1集", "https://video.example/720-s02.m3u8"),),
        ),
    ]

    class Client:
        sources = ()

        def search(self, *_args, **_kwargs):
            return rows

    monkeypatch.setattr("app.plugins.PluginChian", lambda: object())
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(plugin_module, "_HostTorrentInfo", TorrentInfo)
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        plugin,
        "_probe_resource_urls",
        lambda urls: {url: 1080 if "1080" in url else 720 for url in urls},
    )
    plugin._quality_probe_ms["https://video.example/1080-s02.m3u8"] = 86

    items = plugin._resource_torrents("示例剧", mtype="tv")

    assert [item.pri_order for item in items] == [108, 72]
    assert {item.title for item in items} == {"示例剧 (2024) · 第2季"}
    assert all("1080P" not in item.title and "720P" not in item.title for item in items)
    assert all("1080P" not in item.description and "720P" not in item.description for item in items)
    assert items[0].site_name == "高清源 · 1080P · 86ms"
    assert "1080P" in items[0].labels
    assert "86ms" in items[0].labels

    targeted_items = plugin._resource_torrents(
        "示例剧",
        mtype="tv",
        target_media_source="themoviedb",
        target_media_id="selected-tv-123",
        target_media_title="目标剧名",
        target_media_year="2024",
    )
    targeted_payloads = [
        plugin._decode_resource_token(item.enclosure) for item in targeted_items
    ]
    assert {
        (item.media_source, item.media_id) for item in targeted_items
    } == {("themoviedb", "selected-tv-123")}
    assert all(payload["title"] == "目标剧名" for payload in targeted_payloads)
    assert all(payload["year"] == "2024" for payload in targeted_payloads)
    assert all(
        (payload["host_media_source"], payload["host_media_id"])
        == ("themoviedb", "selected-tv-123")
        for payload in targeted_payloads
    )
    assert all(
        (episode["host_media_source"], episode["host_media_id"])
        == ("themoviedb", "selected-tv-123")
        for payload in targeted_payloads
        for episode in payload["episodes"]
    )
