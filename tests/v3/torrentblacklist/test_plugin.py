"""通过公开插件 SDK 的真实 SQLite 与事件集成。"""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from types import SimpleNamespace

import pytest

from app.schemas.event import ResourceDownloadEventData, ResourceSelectionEventData


def context(title, site=1, site_name="测试站"):
    return SimpleNamespace(torrent_info=SimpleNamespace(
        title=title, description="", site=site, site_name=site_name,
    ))


def add_keyword(plugin, text="CAM"):
    rules = import_module("app.plugins.torrentblacklist.rules")
    return plugin._store.add(rules.create_rule(rules.KeywordInput(keyword=text)))[0]


def test_plugin_defaults_disabled_and_reuses_store_on_reinitialization(plugin):
    assert not plugin.get_state()
    store = plugin._store
    add_keyword(plugin)
    plugin.init_plugin({"enabled": True})
    assert plugin.get_state() and plugin._store is store
    assert len(plugin._store.snapshot()[0].entries) == 1
    assert plugin.get_form() == ([], {"enabled": True})
    assert plugin.get_render_mode() == ("vue", "dist/assets")
    assert plugin.get_page() == []


def test_real_sdk_distinguishes_missing_key_from_json_null(plugin):
    assert plugin.get_data("rules") is None
    assert plugin.get_data() == []
    plugin.save_data("rules", None)
    assert plugin.get_data("rules") is None
    assert len(plugin.get_data()) == 1
    plugin.init_plugin({"enabled": True})
    assert plugin._store.snapshot()[1]
    assert plugin.get_data()[0].value is None


def test_real_sdk_concurrent_writes_and_new_instance_reload(plugin):
    rules = import_module("app.plugins.torrentblacklist.rules")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: plugin._store.add(rules.create_rule(rules.SiteInput(site_id=n + 1))),
                      range(16)))
    assert plugin.get_data("rules")["revision"] == 16
    restored = type(plugin)()
    restored.init_plugin({"enabled": True})
    assert len(restored._store.snapshot()[0].entries) == 16


def test_clone_instances_keep_separate_sdk_documents(plugin):
    module = import_module("app.plugins.torrentblacklist")
    other_type = type(type(plugin).__name__ + "Other", (module.TorrentBlacklist,), {})
    other = other_type()
    try:
        other.init_plugin({"enabled": True})
        add_keyword(plugin, "CAM")
        add_keyword(other, "TS")
        assert plugin.get_data("rules")["entries"][0]["keyword"] == "cam"
        assert other.get_data("rules")["entries"][0]["keyword"] == "ts"
    finally:
        other.del_data("rules")


def test_selection_keeps_prior_filter_order_and_object_identity(plugin):
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    previous_removed, kept, blocked, last = context("REMOVED"), context("A"), context("CAM"), context("B")
    data = ResourceSelectionEventData(
        contexts=[previous_removed, kept, blocked, last], updated=True,
        updated_contexts=[kept, blocked, last], source="previous", origin="Subscribe",
    )
    plugin.on_resource_selection(SimpleNamespace(event_data=data))
    assert data.updated_contexts == [kept, last]
    assert data.updated_contexts[0] is kept and data.updated_contexts[1] is last
    assert data.source == plugin.plugin_name


def test_empty_prior_selection_is_not_revived_or_relabelled(plugin):
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    data = ResourceSelectionEventData(contexts=[context("A")], updated=True,
                                     updated_contexts=[], source="previous")
    plugin.on_resource_selection(SimpleNamespace(event_data=data))
    assert data.updated_contexts == [] and data.source == "previous"


def test_no_matches_leave_selection_outputs_unchanged(plugin):
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    data = ResourceSelectionEventData(contexts=[context("Film")])
    plugin.on_resource_selection(SimpleNamespace(event_data=data))
    assert not data.updated and data.updated_contexts is None


@pytest.mark.parametrize("origin", ["Manual", "Subscribe", "Search", None])
def test_download_cancels_matching_current_context_without_replacement(plugin, origin):
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    candidate = context("Film.CAM")
    data = ResourceDownloadEventData(context=candidate, options={"save_path": "/custom"},
                                     origin=origin, downloader="test")
    options = data.options
    plugin.on_resource_download(SimpleNamespace(event_data=data))
    assert data.cancel and data.reason
    assert data.source == plugin.plugin_name
    assert data.context is candidate and data.options is options
    assert data.options == {"save_path": "/custom"} and data.origin == origin
    assert data.downloader == "test"


def test_preexisting_cancel_reason_is_preserved(plugin):
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    data = ResourceDownloadEventData(context=context("CAM"), cancel=True,
                                     reason="上游原因", source="上游")
    plugin.on_resource_download(SimpleNamespace(event_data=data))
    assert (data.cancel, data.source, data.reason) == (True, "上游", "上游原因")


def test_corrupt_rules_cancel_when_enabled_and_pass_when_disabled(plugin):
    plugin.save_data("rules", None)
    plugin.init_plugin({"enabled": True})
    data = ResourceDownloadEventData(context=context("normal"))
    plugin.on_resource_download(SimpleNamespace(event_data=data))
    assert data.cancel and "规则数据无法读取" in data.reason
    plugin.init_plugin({"enabled": False})
    data = ResourceDownloadEventData(context=context("CAM"))
    selection = ResourceSelectionEventData(contexts=[context("CAM")])
    plugin.on_resource_download(SimpleNamespace(event_data=data))
    plugin.on_resource_selection(SimpleNamespace(event_data=selection))
    assert not data.cancel and not selection.updated
    assert plugin.get_data()[0].value is None


def test_rule_removed_after_selection_allows_direct_download(plugin):
    plugin.init_plugin({"enabled": True})
    rule = add_keyword(plugin)
    data = ResourceSelectionEventData(contexts=[context("CAM")])
    plugin.on_resource_selection(SimpleNamespace(event_data=data))
    assert data.updated_contexts == []
    plugin._store.delete(rule.id)
    data = ResourceDownloadEventData(context=context("CAM"))
    plugin.on_resource_download(SimpleNamespace(event_data=data))
    assert not data.cancel


def test_real_download_chain_cancels_before_torrent_fetch_and_submission(plugin, monkeypatch):
    from unittest.mock import MagicMock

    from app.chain.download import DownloadChain, submission
    from app.schemas.types import ChainEventType, MediaType
    from app.sdk.events import eventmanager
    from app.sdk.media import Context, MediaInfo, MetaInfo, TorrentInfo

    from app.application import configuration

    monkeypatch.setattr(configuration, "_configured_system_config", SimpleNamespace(get=lambda _key: None))
    plugin.init_plugin({"enabled": True})
    add_keyword(plugin)
    candidate = Context(meta_info=MetaInfo("Film.2026.CAM"),
                        media_info=MediaInfo(type=MediaType.MOVIE, title="Film", year="2026", tmdb_id=123),
                        torrent_info=TorrentInfo(title="Film.2026.CAM"))
    monkeypatch.setattr(submission, "MediaChain", lambda: SimpleNamespace(
        supplement_tmdb_info=lambda media, _meta: media,
    ))

    def dispatch(event_type, data):
        assert event_type == ChainEventType.ResourceDownload
        message = SimpleNamespace(event_data=data)
        plugin.on_resource_download(message)
        return message

    monkeypatch.setattr(eventmanager, "send_event", dispatch)
    chain = object.__new__(DownloadChain)
    chain.download = MagicMock()
    chain.download_torrent = MagicMock(return_value=(None, "", ""))
    chain._record_download_failure = MagicMock()
    result = chain.download_single(context=candidate, return_detail=True)
    assert result == (None, "下载被事件取消")
    chain.download.assert_not_called()
    chain.download_torrent.assert_not_called()


def test_real_sdk_parallel_duplicate_adds_and_deletes_are_idempotent(plugin):
    rules = import_module("app.plugins.torrentblacklist.rules")
    rule = rules.create_rule(rules.SiteInput(site_id=7))
    with ThreadPoolExecutor(max_workers=8) as pool:
        added = list(pool.map(lambda _: plugin._store.add(rule), range(16)))
    assert sum(created for _, created, _ in added) == 1
    assert plugin.get_data("rules")["revision"] == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        deleted = list(pool.map(lambda _: plugin._store.delete(rule.id), range(16)))
    assert sum(removed for removed, _ in deleted) == 1
    assert plugin.get_data("rules") == {"version": 1, "revision": 2, "entries": []}


def test_real_sdk_parallel_different_deletions_and_additions_do_not_lose_updates(plugin):
    rules = import_module("app.plugins.torrentblacklist.rules")
    old = [rules.create_rule(rules.SiteInput(site_id=n + 1)) for n in range(8)]
    new = [rules.create_rule(rules.SiteInput(site_id=n + 100)) for n in range(8)]
    for rule in old:
        plugin._store.add(rule)

    def change(index):
        plugin._store.delete(old[index].id)
        plugin._store.add(new[index])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(change, range(8)))
    current = plugin._store.read()
    assert current.revision == 24
    assert {rule.id for rule in current.entries} == {rule.id for rule in new}
