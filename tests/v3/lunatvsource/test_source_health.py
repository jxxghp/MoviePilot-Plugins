from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Dict

import pytest

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import AppleCmsClient, CmsResult, CmsSource


class PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = PluginData()
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
    plugin.init_plugin(config or {})
    return plugin


def make_source(key: str, *, comment: str = "") -> CmsSource:
    return CmsSource(
        key=key,
        name=f"{key}源",
        api=f"https://{key}.example/api.php/provide/vod/",
        comment=comment,
    )


def save_catalog(plugin: LunaTVSource, *sources: CmsSource) -> None:
    plugin.save_data(
        plugin_module.SOURCE_CACHE_KEY,
        [source.to_dict() for source in sources],
    )


def test_search_protocol_health_accepts_a_valid_empty_result(monkeypatch):
    source = make_source("empty-ok")
    client = AppleCmsClient([source])
    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: {"list": []})

    client.verify_search(source)

    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: {"code": 1})
    with pytest.raises(ValueError, match="list/data"):
        client.verify_search(source)

    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: {"code": 1002, "msg": "Current API search."},
    )
    with pytest.raises(ValueError, match="源站在线，但禁止关键词搜索（API 1002）"):
        client.verify_search(source)


def test_search_forbidden_source_is_auto_disabled_with_clear_reason(monkeypatch):
    source = make_source("search-forbidden")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: [source],
    )
    monkeypatch.setattr(
        AppleCmsClient,
        "_request",
        lambda *_args, **_kwargs: {"code": 1002, "msg": "Current API search."},
    )

    result = plugin.refresh_source_health()
    payload = plugin.api_sources()["data"][0]

    assert result["disabled"] == 1
    assert payload["auto_disabled"] is True
    assert payload["last_error"] == "CMS 源站在线，但禁止关键词搜索（API 1002）"
    assert plugin._client().sources == []


def test_unchecked_source_is_excluded_until_health_check_passes(monkeypatch):
    source = make_source("unchecked")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)

    payload = plugin.api_sources()["data"][0]
    assert payload["enabled"] is False
    assert payload["disabled_reason"] == "unchecked"
    assert plugin._client().sources == []

    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: [source],
    )
    monkeypatch.setattr(AppleCmsClient, "verify_search", lambda *_args, **_kwargs: None)
    plugin.refresh_source_health()

    assert [item.key for item in plugin._client().sources] == [source.key]


def test_health_failure_disables_search_and_later_success_recovers(monkeypatch):
    healthy = make_source("healthy")
    failing = make_source("failing")
    sources = [healthy, failing]
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, *sources)
    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: list(sources),
    )

    def fail_one(_client, source, _query="1"):
        if source.key == "failing":
            raise OSError("search endpoint unavailable")

    monkeypatch.setattr(AppleCmsClient, "verify_search", fail_one)
    result = plugin.refresh_source_health()

    assert result == {
        "success": True,
        "checked": 2,
        "healthy": 1,
        "disabled": 1,
        "skipped_manual": 0,
    }
    by_key = {item["key"]: item for item in plugin.api_sources()["data"]}
    assert by_key["healthy"]["enabled"] is True
    assert by_key["failing"]["enabled"] is False
    assert by_key["failing"]["auto_disabled"] is True
    assert by_key["failing"]["failures"] == 1
    assert [source.key for source in plugin._client().sources] == ["healthy"]

    monkeypatch.setattr(AppleCmsClient, "verify_search", lambda *_args, **_kwargs: None)
    plugin.refresh_source_health()

    by_key = {item["key"]: item for item in plugin.api_sources()["data"]}
    assert by_key["failing"]["enabled"] is True
    assert by_key["failing"]["auto_disabled"] is False
    assert by_key["failing"]["failures"] == 0
    assert {source.key for source in plugin._client().sources} == {"healthy", "failing"}


@pytest.mark.parametrize("entrypoint", ["api_search", "api_discover", "search_medias"])
def test_search_entrypoints_drop_results_disabled_during_request(
    monkeypatch, entrypoint
):
    source = make_source(f"stale-{entrypoint}")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    with plugin._source_health_lock:
        plugin._source_health[source.key] = {
            "api": source.api,
            "health_status": "healthy",
            "last_checked": time.time(),
        }
        plugin._source_health_revision += 1
        initial_revision = plugin._source_health_revision
    result = CmsResult(
        source_key=source.key,
        source_name=source.name,
        vod_id="stale-result",
        title="并发禁用示例",
        year="2026",
        media_type="movie",
        remark="",
        episodes=(),
        detail="",
        season_range=(0, 0),
        season_ambiguous=False,
    )

    class Client:
        _lunatv_health_revision = initial_revision

        def search(self, *_args, **_kwargs):
            response = plugin.api_source_state(
                {"source_key": source.key, "enabled": False}
            )
            assert response["success"] is True
            return [result]

    monkeypatch.setattr(plugin, "_client", lambda: Client())
    if entrypoint == "api_search":
        assert plugin.api_search({"query": result.title})["data"] == []
    elif entrypoint == "api_discover":
        assert plugin.api_discover(keyword=result.title)["data"] == []
    else:
        meta = SimpleNamespace(name=result.title, year="2026", type="电影")
        assert plugin.search_medias(meta=meta) == []


def test_configured_problem_sources_never_enter_normal_search():
    good = make_source("good")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(
        plugin,
        good,
        make_source("unsupported", comment="无法搜索"),
        make_source("polluted", comment="污染搜索结果"),
        make_source("empty", comment="无搜索结果"),
    )
    with plugin._source_health_lock:
        plugin._source_health[good.key] = {
            "api": good.api,
            "health_status": "healthy",
            "last_checked": time.time(),
        }

    assert [source.key for source in plugin._client().sources] == ["good"]
    by_key = {item["key"]: item for item in plugin.api_sources()["data"]}
    assert by_key["unsupported"]["health_label"] == "配置禁用"
    assert by_key["polluted"]["enabled"] is False
    assert by_key["empty"]["enabled"] is False


def test_manual_disable_is_persistent_and_skipped_by_health_checks(monkeypatch):
    store: Dict[str, object] = {}
    first = make_source("first")
    second = make_source("second")
    sources = [first, second]

    def install_store(plugin: LunaTVSource) -> None:
        monkeypatch.setattr(
            plugin,
            "get_data",
            lambda key, default=None: store.get(key, default),
        )
        monkeypatch.setattr(plugin, "save_data", lambda key, value: store.__setitem__(key, value))

    plugin = _plugin()
    install_store(plugin)
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, *sources)
    assert plugin.api_source_state({"source_key": "first", "enabled": False})["success"] is True

    checked = []

    def verify(_client, source, _query="1"):
        checked.append(source.key)

    monkeypatch.setattr(plugin_module, "load_sources_from_url", lambda *_args, **_kwargs: list(sources))
    monkeypatch.setattr(AppleCmsClient, "verify_search", verify)
    plugin.refresh_source_health()

    assert checked == ["second"]
    assert [source.key for source in plugin._client().sources] == ["second"]

    restarted = _plugin()
    install_store(restarted)
    restarted.init_plugin({"enabled": True})
    assert [source.key for source in restarted._client().sources] == ["second"]
    first_payload = next(
        item for item in restarted.api_sources()["data"] if item["key"] == "first"
    )
    assert first_payload["manual_disabled"] is True
    assert first_payload["health_label"] == "手动禁用"


def test_manual_state_change_invalidates_resource_search_cache():
    source = make_source("cache-state")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    with plugin._source_health_lock:
        plugin._source_health[source.key] = {
            "api": source.api,
            "health_status": "healthy",
            "last_checked": time.time(),
        }
        previous_revision = plugin._source_health_revision
    with plugin._resource_search_lock:
        plugin._resource_search_cache["stale"] = (time.monotonic(), [object()])

    response = plugin.api_source_state(
        {"source_key": source.key, "enabled": False}
    )

    assert response["success"] is True
    assert plugin._resource_search_cache == {}
    assert plugin._source_health_revision == previous_revision + 1
    assert plugin._client().sources == []


def test_manual_enable_persists_and_requests_an_immediate_check(monkeypatch):
    source = make_source("manual")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    plugin.api_source_state({"source_key": source.key, "enabled": False})
    starts = []
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda key="": starts.append(key) or True,
    )

    response = plugin.api_source_state({"source_key": source.key, "enabled": True})

    assert response["success"] is True
    assert response["data"]["check_started"] is True
    assert starts == [source.key]
    persisted = plugin.get_data(plugin_module.SOURCE_HEALTH_KEY)
    assert persisted[source.key]["manual_disabled"] is False


def test_manual_reenable_waits_for_fresh_health_check(monkeypatch):
    source = make_source("manual-stale")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    with plugin._source_health_lock:
        plugin._source_health[source.key] = {
            "api": source.api,
            "health_status": "healthy",
            "last_checked": time.time(),
            "last_error": "",
            "failures": 0,
        }

    assert [item.key for item in plugin._client().sources] == [source.key]
    assert plugin.api_source_state(
        {"source_key": source.key, "enabled": False}
    )["success"] is True

    starts = []
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda key="": starts.append(key) or True,
    )
    response = plugin.api_source_state(
        {"source_key": source.key, "enabled": True}
    )

    assert response["success"] is True
    assert starts == [source.key]
    assert plugin._client().sources == []
    source_payload = response["data"]["source"]
    assert source_payload["health_status"] == "unchecked"
    assert source_payload["last_checked"] == 0


def test_inflight_health_result_cannot_override_manual_reenable(monkeypatch):
    source = make_source("generation-race")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    request_started = threading.Event()
    release_request = threading.Event()

    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: [source],
    )

    def delayed_verify(_client, _source, _query="1"):
        request_started.set()
        assert release_request.wait(2)

    monkeypatch.setattr(AppleCmsClient, "verify_search", delayed_verify)
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda _key="": True,
    )
    result = {}

    def run_check():
        result.update(plugin._run_source_health_refresh())

    worker = threading.Thread(target=run_check)
    worker.start()
    assert request_started.wait(2)
    assert plugin.api_source_state(
        {"source_key": source.key, "enabled": False}
    )["success"] is True
    assert plugin.api_source_state(
        {"source_key": source.key, "enabled": True}
    )["success"] is True
    release_request.set()
    worker.join(2)

    assert not worker.is_alive()
    assert result["checked"] == 0
    assert plugin._client().sources == []
    payload = plugin.api_sources()["data"][0]
    assert payload["health_status"] == "unchecked"


def test_manual_enable_queues_check_while_full_check_is_running():
    source = make_source("queued-manual")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    plugin.api_source_state({"source_key": source.key, "enabled": False})
    with plugin._source_health_lock:
        plugin._source_health_running = True

    response = plugin.api_source_state(
        {"source_key": source.key, "enabled": True}
    )

    assert response["success"] is True
    assert response["data"]["check_started"] is True
    assert source.key in plugin._source_health_pending_keys
    with plugin._source_health_lock:
        plugin._source_health_running = False
        plugin._source_health_pending_keys.clear()


def test_full_refresh_is_queued_and_prioritized_while_single_check_runs(
    monkeypatch,
):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    stop_event = plugin._source_health_stop
    starts = []
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda key="": starts.append(key) or True,
    )
    with plugin._source_health_lock:
        plugin._source_health_running = True
        plugin._source_health_pending_keys.add("single")

    response = plugin.refresh_source_health()
    assert response["queued"] is True
    with plugin._source_health_lock:
        assert plugin._source_health_pending_full is True

    plugin._finish_source_health_run(stop_event)

    assert starts == [""]
    with plugin._source_health_lock:
        assert plugin._source_health_pending_full is False
        assert plugin._source_health_pending_keys == set()


def test_enabled_runtime_starts_overdue_health_check_automatically(monkeypatch):
    plugin = _plugin()
    starts = []
    monkeypatch.setattr(plugin_module, "_HostMediaSource", object())
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda key="": starts.append(key) or True,
    )

    plugin.init_plugin({"enabled": True, "source_check_minutes": 60})

    assert starts == [""]


def test_source_health_interval_is_clamped_and_exposed():
    plugin = _plugin()
    plugin.init_plugin({"enabled": True, "source_check_minutes": 1})

    assert plugin._config["source_check_minutes"] == 15
    assert plugin.api_status()["data"]["source_health"]["interval_minutes"] == 15
    assert {
        item["id"] for item in plugin.get_service()
    } >= {"LunaTVSource.SourceHealth"}
    form, defaults = plugin.get_form()
    fields = {
        item.get("props", {}).get("model"): item.get("props", {})
        for item in form[0]["content"]
    }
    assert defaults["source_check_minutes"] == 60
    assert defaults["generate_nfo"] is False
    assert fields["source_check_minutes"]["min"] == 15
    assert fields["source_check_minutes"]["max"] == 1440
    assert fields["generate_nfo"]["label"] == "生成 NFO 元数据"


def test_due_check_considers_every_current_source(monkeypatch):
    now = time.time()
    first = make_source("first")
    added = make_source("added")
    plugin = _plugin()
    plugin.save_data(
        plugin_module.SOURCE_HEALTH_KEY,
        {
            first.key: {
                "api": first.api,
                "health_status": "healthy",
                "last_checked": now,
            }
        },
    )
    plugin.init_plugin({"enabled": True, "source_check_minutes": 60})
    save_catalog(plugin, first, added)
    monkeypatch.setattr(plugin_module.time, "time", lambda: now)

    assert plugin._source_health_due() is True

    with plugin._source_health_lock:
        plugin._source_health[added.key] = {
            "api": added.api,
            "health_status": "healthy",
            "last_checked": now,
        }
    assert plugin._source_health_due() is False


def test_endpoint_change_preserves_generation_and_can_recover(monkeypatch):
    old_source = CmsSource(
        "endpoint-change",
        "换址源",
        "https://old.example/api.php/provide/vod/",
    )
    new_source = CmsSource(
        old_source.key,
        old_source.name,
        "https://new.example/api.php/provide/vod/",
    )
    plugin = _plugin()
    plugin.save_data(
        plugin_module.SOURCE_HEALTH_KEY,
        {
            old_source.key: {
                "api": old_source.api,
                "generation": 2,
                "manual_disabled": False,
                "health_status": "healthy",
                "last_checked": time.time(),
            }
        },
    )
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, new_source)
    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: [new_source],
    )
    monkeypatch.setattr(AppleCmsClient, "verify_search", lambda *_args: None)

    response = plugin.refresh_source_health()

    assert response["healthy"] == 1
    payload = plugin.api_sources()["data"][0]
    assert payload["health_status"] == "healthy"
    assert payload["enabled"] is True
    persisted = plugin.get_data(plugin_module.SOURCE_HEALTH_KEY)
    assert persisted[new_source.key]["api"] == new_source.api
    assert persisted[new_source.key]["generation"] == 2


def test_inflight_health_result_is_dropped_after_endpoint_change(monkeypatch):
    old_source = make_source("inflight-endpoint")
    new_source = CmsSource(old_source.key, old_source.name, "https://new.example/vod")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, old_source)
    with plugin._source_health_lock:
        plugin._source_health[old_source.key] = {
            "api": old_source.api,
            "generation": 1,
            "manual_disabled": False,
        }
    started = threading.Event()
    release = threading.Event()

    def delayed_verify(_client, _source, _query="1"):
        started.set()
        assert release.wait(2)

    monkeypatch.setattr(plugin_module, "load_sources_from_url", lambda *_a, **_k: [old_source])
    monkeypatch.setattr(AppleCmsClient, "verify_search", delayed_verify)
    result = {}
    worker = threading.Thread(
        target=lambda: result.update(plugin._run_source_health_refresh())
    )
    worker.start()
    assert started.wait(2)

    save_catalog(plugin, new_source)
    with plugin._source_health_lock:
        plugin._source_health[old_source.key] = {
            "api": new_source.api,
            "generation": 1,
            "manual_disabled": False,
        }
    release.set()
    worker.join(5)

    assert not worker.is_alive()
    assert result["checked"] == 0
    assert plugin._source_health[old_source.key]["api"] == new_source.api


def test_auto_disabled_state_survives_restart_until_success(monkeypatch):
    store: Dict[str, object] = {}
    source = make_source("restart-failure")

    def install_store(plugin: LunaTVSource) -> None:
        monkeypatch.setattr(
            plugin,
            "get_data",
            lambda key, default=None: store.get(key, default),
        )
        monkeypatch.setattr(
            plugin,
            "save_data",
            lambda key, value: store.__setitem__(key, value),
        )

    plugin = _plugin()
    install_store(plugin)
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    monkeypatch.setattr(
        plugin_module,
        "load_sources_from_url",
        lambda *_args, **_kwargs: [source],
    )
    monkeypatch.setattr(
        AppleCmsClient,
        "verify_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    plugin.refresh_source_health()

    restarted = _plugin()
    install_store(restarted)
    restarted.init_plugin({"enabled": True})
    assert restarted._client().sources == []

    monkeypatch.setattr(AppleCmsClient, "verify_search", lambda *_args, **_kwargs: None)
    restarted.refresh_source_health()
    assert [item.key for item in restarted._client().sources] == [source.key]


def test_disabled_plugin_has_no_health_service_or_startup_check(monkeypatch):
    plugin = _plugin()
    starts = []
    monkeypatch.setattr(plugin_module, "_HostMediaSource", object())
    monkeypatch.setattr(
        plugin,
        "_start_source_health_refresh",
        lambda key="": starts.append(key) or True,
    )

    plugin.init_plugin({"enabled": False})

    assert starts == []
    assert plugin.get_service() == []
    assert plugin.api_source_refresh()["success"] is False


def test_refresh_api_reports_thread_start_failure(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _self: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )

    response = plugin.api_source_refresh()

    assert response["success"] is False
    assert response["data"] == {"started": False, "running": False}


def test_failed_pending_check_start_is_kept_for_next_service_run(monkeypatch):
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    stop_event = plugin._source_health_stop
    with plugin._source_health_lock:
        plugin._source_health_running = True
        plugin._source_health_pending_keys.add("pending")
    monkeypatch.setattr(plugin, "_start_source_health_refresh", lambda _key="": False)

    plugin._finish_source_health_run(stop_event)

    assert "pending" in plugin._source_health_pending_keys
    assert "下次任务中重试" in plugin._source_health_last_error


def test_source_health_interval_clamps_upper_bound_and_invalid_value():
    plugin = _plugin()
    plugin.init_plugin({"enabled": False, "source_check_minutes": 9999})
    assert plugin._config["source_check_minutes"] == 1440

    plugin.init_plugin({"enabled": False, "source_check_minutes": "invalid"})
    assert plugin._config["source_check_minutes"] == 60


def test_stop_service_discards_an_inflight_health_result(monkeypatch):
    source = make_source("stopping")
    plugin = _plugin()
    plugin.init_plugin({"enabled": True})
    save_catalog(plugin, source)
    request_started = threading.Event()
    release_request = threading.Event()

    def delayed_catalog(*_args, **_kwargs):
        request_started.set()
        assert release_request.wait(2)
        return [source]

    monkeypatch.setattr(plugin_module, "load_sources_from_url", delayed_catalog)
    assert plugin._start_source_health_refresh() is True
    assert request_started.wait(2)
    with plugin._source_health_lock:
        thread = plugin._source_health_thread

    plugin.stop_service()
    release_request.set()
    assert thread is not None
    thread.join(2)

    assert not thread.is_alive()
    assert plugin.get_data(plugin_module.SOURCE_HEALTH_KEY) is None
    assert plugin._source_health_running is False
