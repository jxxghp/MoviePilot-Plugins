"""MediaGovernor v5 合同与同路回放测试；不访问 NAS、网络或真实媒体。"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = ROOT / "plugins.v3/mediagovernor"
GOVERNOR = PLUGIN_DIR / "governor.py"
PLUGIN = PLUGIN_DIR / "__init__.py"
PAGE = PLUGIN_DIR / "src/components/AppPage.vue"
MANIFEST = ROOT / "package.v3.json"
GOLDENS = [
    ROOT / "tests/v3/mediagovernor/fixtures/golden/v1/cases.json",
    ROOT / "tests/v3/mediagovernor/fixtures/golden/v1/live-baseline.json",
]


def load_governor():
    name = "mediagovernor_v5_governor"
    spec = importlib.util.spec_from_file_location(name, GOVERNOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


G = load_governor()


def load_plugin_with_host_boundary():
    app = types.ModuleType("app")
    plugins = types.ModuleType("app.plugins")
    class Base:
        def __init__(self): self.path = Path(tempfile.mkdtemp())
        def get_data_path(self): return self.path
    plugins._PluginBase = Base
    saved = {name: sys.modules.get(name) for name in ("app", "app.plugins")}
    sys.modules.update({"app": app, "app.plugins": plugins})
    name = "mediagovernor_v5_plugin"
    try:
        spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN_DIR)])
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None: sys.modules.pop(key, None)
            else: sys.modules[key] = value


class FakeAdapter:
    def __init__(self):
        self.present: dict[str, dict] = {}
        self.preview_value: dict = {"summary": {"total": 0, "success": 0, "failed": 0}, "items": []}
        self.preview_calls = 0
        self.rebuild_calls: list[dict] = []

    def get_item(self, storage, path):
        return self.present.get(G.normal_path(path))

    def preview(self, source, identity):
        self.preview_calls += 1
        return json.loads(json.dumps(self.preview_value))

    def rebuild(self, entry, identity):
        self.rebuild_calls.append(entry)
        self.present[G.normal_path(entry["expected"])] = {"path": entry["expected"], "type": "file"}
        if entry.get("cleanup_attributable"):
            self.present.pop(G.normal_path(entry.get("current")), None)


def inventory(roots=None):
    return G.Inventory([], roots or [{"path": "/fixture/library/movie", "name": "电影"}, {"path": "/fixture/library/tv", "name": "电视剧"}, {"path": "/fixture/library/anime", "name": "动漫"}], [], [])


def object_for(case):
    unit = case["input"]["unit"]
    entries = [{"storage": "local", "type": "file", **row} for row in unit.get("entries") or []]
    return {"id": unit.get("id", "case"), "label": unit.get("id", "case"), "root": {"path": entries[0]["path"] if len(entries) == 1 else str(Path(entries[0]["path"]).parent), "storage": "local", "type": "dir"}, "entries": entries, "complete": unit.get("complete", True), "fingerprint": G.fingerprint(entries)}


def test_versions_api_and_frontend_contract_are_v5():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["MediaGovernor"]
    package = json.loads((PLUGIN_DIR / "package.json").read_text(encoding="utf-8"))
    source = PLUGIN.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    assert manifest["version"] == package["version"] == "5.0.0"
    assert next(iter(manifest["history"])) == "v5.0.0"
    assert 'plugin_version = "5.0.0"' in source
    assert 'return "vue", "dist/v5.0.0/assets"' in source
    for endpoint in ("/audit/start", "/audit/status", "/findings", "/objects/{object_id}", "/identity/confirm", "/repair/{object_id}"):
        assert endpoint in source
    for forbidden in ("storage/list", "transfer/manual", "bundle_analyze_batch", "experiment_run", "map_commit"):
        assert forbidden not in page
    assert "检查现在" in page and "重建全部基线" in page and "确认修复" in page
    module = load_plugin_with_host_boundary()
    plugin = module.MediaGovernor(); plugin.init_plugin({"enabled": False})
    assert plugin.get_render_mode() == ("vue", "dist/v5.0.0/assets")
    assert [row["path"] for row in plugin.get_api()] == ["/audit/start", "/audit/status", "/findings", "/objects/{object_id}", "/identity/confirm", "/repair/{object_id}"]
    assert all(row["auth"] == "bear" for row in plugin.get_api())


def test_real_moviepilot_v3_runtime_constructs_initializes_and_stops_plugin():
    from app.application.chain.context import configure_chain_runtime_context_provider
    from app.application.configuration import ChainRuntimeConfig
    from app.chain.storage import StorageChain
    from app.chain.transfer import TransferChain
    from app.plugins import mediagovernor
    from app.runtime.stop import runtime_stop_state
    from app.sdk.queries import list_transfer_history

    queue = types.SimpleNamespace(bind=lambda _callback: types.SimpleNamespace())
    context = types.SimpleNamespace(
        module_manager=types.SimpleNamespace(), plugin_manager=types.SimpleNamespace(), event_manager=types.SimpleNamespace(),
        message_oper=types.SimpleNamespace(), message_helper=types.SimpleNamespace(), file_cache=types.SimpleNamespace(), async_file_cache=types.SimpleNamespace(),
        message_queue=queue, module_dispatcher_factory=lambda **_kwargs: types.SimpleNamespace(), site_repository=None,
        subscription_repository=None, subscription_search_repository=None, subscription_mutation_scope=None, sync_subscription_mutation_scope=None,
        subscription_delete_scope=None, sync_subscription_delete_scope=None, subscription_completion_scope=None, rule_group_mutation_scope=None,
        site_reference_mutation_scope=None, download_history_repository=None, transfer_history_repository=None, transfer_admission_repository=None,
        transfer_execution_repository=None, media_server_repository=None, download_failure_repository=None, subscription_download_repository=None,
        user_repository=None, legacy_transfer_command=None, durable_event_writer=None, configuration=ChainRuntimeConfig(media_extensions=()), stop_state=runtime_stop_state,
    )
    configure_chain_runtime_context_provider(lambda: context)
    try:
        required = {"fileitem", "target_storage", "target_path", "media_source", "media_id", "mtype", "season", "transfer_type", "preview", "reorganize", "cleanup_dest_fileitem"}
        assert required <= set(inspect.signature(TransferChain.manual_transfer).parameters)
        assert "storage" in inspect.signature(StorageChain.get_file_item_strict).parameters
        assert callable(list_transfer_history)
        plugin = mediagovernor.MediaGovernor()
        plugin.init_plugin({"enabled": False})
        assert plugin.get_state() is False and plugin.get_render_mode() == ("vue", "dist/v5.0.0/assets")
        plugin.stop_service()
    finally:
        configure_chain_runtime_context_provider(None)


def test_sqlite_ledger_has_five_tables_and_does_not_touch_legacy_map(tmp_path):
    legacy = tmp_path / "media_map.json"
    legacy.write_text('{"keep":true}', encoding="utf-8")
    ledger = G.Ledger(tmp_path / "governor-v5.sqlite3")
    tables = {row["name"] for row in ledger.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"objects", "identities", "observations", "findings", "jobs"} <= tables
    assert legacy.read_text(encoding="utf-8") == '{"keep":true}'


def test_reinitialization_never_duplicates_event_listeners():
    module = load_plugin_with_host_boundary()
    active = set()
    module.EventType = types.SimpleNamespace(TransferComplete="complete", TransferFailed="failed")
    module.eventmanager = types.SimpleNamespace(
        add_event_listener=lambda event, handler: active.add((event, handler)),
        remove_event_listener=lambda event, handler: active.discard((event, handler)),
    )
    plugin = module.MediaGovernor()
    plugin.init_plugin({"enabled": True}); plugin.init_plugin({"enabled": True})
    assert len(active) == 2
    plugin.stop_service()
    assert active == set()


def test_download_hash_is_the_primary_work_boundary_and_unmatched_is_not_guessed():
    top = {"path": "/fixture/download/mixed", "name": "mixed", "type": "dir", "storage": "local"}
    entries = [
        {"path": "/fixture/download/mixed/A.mkv", "name": "A.mkv", "type": "file"},
        {"path": "/fixture/download/mixed/B.mkv", "name": "B.mkv", "type": "file"},
        {"path": "/fixture/download/mixed/loose.mkv", "name": "loose.mkv", "type": "file"},
    ]
    histories = [
        {"src": entries[0]["path"], "download_hash": "one", "media_source": "themoviedb", "media_id": "1", "type": "电影"},
        {"src": entries[1]["path"], "download_hash": "two", "media_source": "themoviedb", "media_id": "2", "type": "电影"},
    ]
    groups = G.partition_entries(top, entries, histories)
    assert {row["group_key"] for row in groups} == {"hash:one", "hash:two", "unmatched"}
    assert sum(len(row["entries"]) for row in groups) == 3


def test_configured_roots_reject_container_root_and_deduplicate():
    rows = [types.SimpleNamespace(download_path="/", storage="local"), types.SimpleNamespace(download_path="/downloads", storage="local"), types.SimpleNamespace(download_path="/downloads", storage="local")]
    adapter = G.MoviePilotAdapter()
    adapter._loaded = {"dirs": types.SimpleNamespace(get_download_dirs=lambda: rows)}
    assert [row["path"] for row in adapter.directories("download")] == ["/downloads"]


def test_bdmv_is_walked_as_one_atomic_object_and_samples_are_ignored():
    assert G.is_sample({"path": "/fixture/download/Film/Sample/sample.mkv"})
    assert "bdmv" in G.DISC_DIRECTORIES
    top = {"path": "/fixture/download/Disc", "name": "Disc", "type": "dir"}
    entries = [{"path": "/fixture/download/Disc/movie.iso", "name": "movie.iso", "type": "file"}]
    groups = G.partition_entries(top, entries, [])
    assert len(groups) == 1 and groups[0]["group_key"] == "unmatched"


def test_structural_fallback_splits_movie_collections_but_not_tv_seasons():
    top = {"path": "/fixture/download/Collection", "name": "Collection", "type": "dir"}
    movies = [
        {"path": "/fixture/download/Collection/Film A/A.mkv", "name": "A.mkv", "type": "file"},
        {"path": "/fixture/download/Collection/Film B/B.mkv", "name": "B.mkv", "type": "file"},
    ]
    seasons = [
        {"path": "/fixture/download/Collection/Season 1/Show.S01E01.mkv", "name": "Show.S01E01.mkv", "type": "file"},
        {"path": "/fixture/download/Collection/Season 2/Show.S02E01.mkv", "name": "Show.S02E01.mkv", "type": "file"},
    ]
    assert {row["group_key"] for row in G.partition_entries(top, movies, [])} == {"folder:film a", "folder:film b"}
    assert [row["group_key"] for row in G.partition_entries(top, seasons, [])] == ["unmatched"]


def test_identity_only_auto_confirms_when_native_and_history_agree(tmp_path):
    class Adapter(FakeAdapter):
        def recognize(self, path): return {"title": "Film", "media_type": "movie", "media_source": "themoviedb", "media_id": "7"}
        def ai_queries(self, evidence): return []
        def search(self, query): return []
    service = G.GovernorService(tmp_path, Adapter())
    obj = {"id": "one", "fingerprint": "fp", "root": {"path": "/fixture/download/Film"}, "entries": [{"path": "/fixture/download/Film.mkv"}]}
    agree = [{"src": "/fixture/download/Film.mkv", "media_source": "themoviedb", "media_id": "7", "type": "电影"}]
    conflict = [{**agree[0], "media_id": "8"}]
    assert service._resolve_identity(obj, agree)[0] == "confirmed"
    state, identity, candidates, _ = service._resolve_identity({**obj, "id": "two"}, conflict)
    assert state == "candidate" and identity == {} and {row["media_id"] for row in candidates} == {"7", "8"}


def test_async_only_llm_is_supported_and_limited_to_three_queries(monkeypatch):
    class Model:
        async def ainvoke(self, prompt):
            return types.SimpleNamespace(content='{"queries":[{"title":"A","year":"2024"},{"title":"B"},{"title":"C"},{"title":"D"}]}')
    class Helper:
        get_llm = staticmethod(lambda streaming=False: Model())
        extract_text_content = staticmethod(lambda value: value)
    app = types.ModuleType("app"); agent = types.ModuleType("app.agent"); llm = types.ModuleType("app.agent.llm"); helper = types.ModuleType("app.agent.llm.helper")
    helper.LLMHelper = Helper
    monkeypatch.setitem(sys.modules, "app", app); monkeypatch.setitem(sys.modules, "app.agent", agent); monkeypatch.setitem(sys.modules, "app.agent.llm", llm); monkeypatch.setitem(sys.modules, "app.agent.llm.helper", helper)
    assert G.MoviePilotAdapter().ai_queries({"names": ["A.mkv"]}) == ["A 2024", "B", "C"]


def test_current_async_get_llm_contract_is_supported(monkeypatch):
    class Model:
        async def ainvoke(self, prompt): return types.SimpleNamespace(content='{"one":{"queries":[{"title":"Film"}]}}')
    class Helper:
        @staticmethod
        async def get_llm(streaming=False): return Model()
        extract_text_content = staticmethod(lambda value: value)
    helper = types.ModuleType("app.agent.llm.helper"); helper.LLMHelper = Helper
    monkeypatch.setitem(sys.modules, "app.agent.llm.helper", helper)
    assert G.MoviePilotAdapter().ai_queries({"names": ["Film.mkv"]}) == ["Film"]


def test_golden_audit_cases_replay_through_v5_classifier(tmp_path):
    service = G.GovernorService(tmp_path, FakeAdapter())
    checked = 0
    for fixture in GOLDENS:
        for case in json.loads(fixture.read_text(encoding="utf-8"))["cases"]:
            if case.get("operation") not in {"audit", "state_audit"} or "preview" not in case["input"]:
                continue
            obj = object_for(case)
            data = case["input"]
            preview = json.loads(json.dumps(data["preview"]))
            for index, row in enumerate(preview.get("items") or []):
                row.setdefault("source", obj["entries"][min(index, len(obj["entries"]) - 1)]["path"])
                row.setdefault("target_storage", "local")
            adapter = service.adapter
            adapter.present = {G.normal_path(path): {"path": path, "type": "file"} for path in data.get("present") or []}
            inv = G.Inventory([], data.get("library_roots") or inventory().library_roots, [], [])
            findings = service._findings(obj, data["unit"].get("history") or [], "confirmed", data["identity"], preview, inv)
            expected = case["expected"]
            if expected.get("disposition") == "normal":
                assert findings == [], case["id"]
            elif expected.get("kind") in {"native_failure", "category_error", "identity_error", "episode_error", "hierarchy_error"}:
                kinds = {row["kind"] for row in findings}
                issue_kinds = {kind for row in findings for kind in (row.get("evidence") or {}).get("issue_kinds", [])}
                assert expected["kind"] in kinds | issue_kinds, case["id"]
            checked += 1
    assert checked >= 10


def test_one_object_failure_does_not_abort_later_objects(tmp_path):
    class Adapter(FakeAdapter):
        def directories(self, kind): return []
        def histories(self): return []
    service = G.GovernorService(tmp_path, Adapter())
    objects = [{"id": value, "label": value, "fingerprint": value, "root": {"path": f"/fixture/{value}"}, "entries": [], "complete": True} for value in ("bad", "good")]
    service._discover = lambda job_id: G.Inventory(objects, [], [], [])
    seen = []
    def process(job_id, obj, inv, resolved=None, force_preview=False):
        seen.append(obj["id"])
        if obj["id"] == "bad": raise RuntimeError("boom")
        service.ledger.replace_findings(obj["id"], [])
    service._process = process
    job = service.ledger.begin_job("full")
    service._run(job, "full", None)
    assert seen == ["bad", "good"]
    assert service.ledger.current_job()["status"] == "completed"


def test_ambiguous_identity_queries_are_batched_by_four(tmp_path):
    class Adapter(FakeAdapter):
        def recognize(self, path): return {}
        def ai_queries_batch(self, items):
            batches.append(len(items)); return {key: [] for key, _ in items}
        def search(self, query): return []
    batches = []
    service = G.GovernorService(tmp_path, Adapter())
    objects = [{"id": str(index), "label": str(index), "fingerprint": str(index), "root": {"path": f"/fixture/{index}"}, "entries": [{"path": f"/fixture/{index}.mkv"}], "complete": True} for index in range(9)]
    service._discover = lambda job_id: G.Inventory(objects, [], [], [])
    job = service.ledger.begin_job("full")
    service._run(job, "full", None)
    assert batches == [4, 4, 1]
    assert len(service.findings()["confirmations"]) == 9


def test_incomplete_inventory_never_resolves_previous_findings(tmp_path):
    service = G.GovernorService(tmp_path, FakeAdapter())
    old = {"id": "old", "label": "Old", "fingerprint": "fp", "root": {}, "entries": [], "complete": True}
    service.ledger.upsert_object(old)
    service.ledger.replace_findings("old", [{"kind": "native_failure", "reason": "旧问题", "evidence": {}}])
    service._discover = lambda job_id: G.Inventory([], [], [], [{"path": "/fixture/download", "error": "unreadable"}])
    job = service.ledger.begin_job("incremental")
    service._run(job, "incremental", None)
    assert service.findings()["problems"][0]["title"] == "Old"


def test_clean_empty_inventory_resolves_removed_objects(tmp_path):
    service = G.GovernorService(tmp_path, FakeAdapter())
    old = {"id": "old", "label": "Old", "fingerprint": "fp", "root": {}, "entries": [], "complete": True}
    service.ledger.upsert_object(old)
    service.ledger.replace_findings("old", [{"kind": "native_failure", "reason": "旧问题", "evidence": {}}])
    service._discover = lambda job_id: G.Inventory([], [], [], [])
    job = service.ledger.begin_job("incremental")
    service._run(job, "incremental", None)
    assert service.findings()["problems"] == []


def test_preview_is_cached_but_target_existence_is_rechecked(tmp_path):
    adapter = FakeAdapter()
    service = G.GovernorService(tmp_path, adapter)
    obj = {"id": "one", "label": "Film", "fingerprint": "fp", "root": {"path": "/fixture/download/Film", "type": "dir"}, "entries": [{"path": "/fixture/download/Film.mkv", "type": "file"}], "complete": True}
    identity = {"title": "Film", "media_type": "movie", "media_source": "themoviedb", "media_id": "1"}
    service.ledger.upsert_object(obj); service.ledger.save_identity("one", "confirmed", "fp", identity, [identity], "user_confirmed")
    adapter.preview_value = {"summary": {"total": 1, "success": 1, "failed": 0}, "items": [{"source": obj["entries"][0]["path"], "target": "/fixture/library/movie/Film/Film.mkv", "target_storage": "local", "success": True}]}
    inv = G.Inventory([obj], [{"path": "/fixture/library/movie", "name": "电影"}], [], [])
    service._process("job", obj, inv); service._process("job", obj, inv)
    assert adapter.preview_calls == 1
    assert service.findings()["problems"][0]["kind"] == "native_failure"
    service._process("job", obj, inv, force_preview=True)
    assert adapter.preview_calls == 2


def test_repair_token_expires_if_source_target_or_official_preview_changes(tmp_path):
    adapter = FakeAdapter(); service = G.GovernorService(tmp_path, adapter)
    source = {"path": "/fixture/download/Film.mkv", "storage": "local", "type": "file", "name": "Film.mkv", "size": 10}
    obj = {"id": "one", "label": "Film", "fingerprint": G.fingerprint([source]), "root": source, "entries": [source], "complete": True}
    identity = {"title": "Film", "media_type": "movie", "media_source": "themoviedb", "media_id": "1"}
    history = {"id": 9, "status": True, "src": source["path"], "dest": "/fixture/library/tv/Wrong/Wrong.mkv", "dest_storage": "local", "dest_fileitem": {"path": "/fixture/library/tv/Wrong/Wrong.mkv", "storage": "local", "type": "file"}}
    adapter.preview_value = {"summary": {"total": 1, "success": 1, "failed": 0}, "items": [{"source": source["path"], "target": "/fixture/library/movie/Film/Film.mkv", "target_storage": "local", "success": True}]}
    adapter.present = {G.normal_path(source["path"]): source, G.normal_path(history["dest"]): history["dest_fileitem"]}
    service.ledger.upsert_object(obj); service.ledger.save_identity("one", "confirmed", obj["fingerprint"], identity, [identity], "user_confirmed")
    service.ledger.save_observation("one", "source", True, obj["fingerprint"], {"object": obj, "histories": [history]})
    service.ledger.save_observation("__library__", "configuration", True, "cfg", {"roots": [{"path": "/fixture/library/tv"}, {"path": "/fixture/library/movie"}]})
    plan = service.repair_preview("one")
    assert plan["entries"][0]["cleanup_attributable"] is True
    adapter.present[G.normal_path(source["path"])] = {**source, "size": 11}
    try:
        service.repair_execute("one", plan["token"])
    except ValueError as error:
        assert "已经变化" in str(error)
    else:
        raise AssertionError("变化后的源文件不应执行修复")
    assert adapter.rebuild_calls == []


def test_repair_executes_frozen_plan_once_and_then_rechecks(tmp_path):
    adapter = FakeAdapter(); service = G.GovernorService(tmp_path, adapter)
    source = {"path": "/fixture/download/Film.mkv", "storage": "local", "type": "file", "name": "Film.mkv", "size": 10}
    obj = {"id": "one", "label": "Film", "fingerprint": G.fingerprint([source]), "root": source, "entries": [source], "complete": True}
    identity = {"title": "Film", "media_type": "movie", "media_source": "themoviedb", "media_id": "1"}
    adapter.preview_value = {"summary": {"total": 1, "success": 1, "failed": 0}, "items": [{"source": source["path"], "target": "/fixture/library/movie/Film/Film.mkv", "target_storage": "local", "success": True}]}
    adapter.present = {G.normal_path(source["path"]): source}
    service.ledger.upsert_object(obj); service.ledger.save_identity("one", "confirmed", obj["fingerprint"], identity, [identity], "user_confirmed")
    service.ledger.save_observation("one", "source", True, obj["fingerprint"], {"object": obj, "histories": []})
    service.ledger.save_observation("__library__", "configuration", True, "cfg", {"roots": [{"path": "/fixture/library/movie"}]})
    plan = service.repair_preview("one")
    service.start = lambda mode, ids: {"job": {"status": "running"}}
    result = service.repair_execute("one", plan["token"])
    assert result["accepted"] and len(adapter.rebuild_calls) == 1
    try:
        service.repair_execute("one", plan["token"])
    except ValueError:
        pass
    else:
        raise AssertionError("修复确认必须是一次性的")


def test_stop_is_cooperative_and_event_marking_only_sets_dirty(tmp_path):
    service = G.GovernorService(tmp_path, FakeAdapter())
    obj = {"id": "one", "label": "one", "fingerprint": "fp", "root": {}, "entries": [], "complete": True}
    service.ledger.upsert_object(obj); service.ledger.execute("UPDATE objects SET dirty=0")
    service.mark_dirty({"path": "/ignored"})
    assert service.ledger.one("SELECT dirty FROM objects WHERE id='one'")["dirty"] == 1
    assert service.stop() is True


def test_fixtures_are_deidentified_and_cover_real_baseline_categories():
    ids = set()
    for fixture in GOLDENS:
        raw = fixture.read_text(encoding="utf-8")
        assert "C:\\" not in raw and "/volume" not in raw
        ids |= {row["id"] for row in json.loads(raw)["cases"]}
    required = {"native-failure", "wrong-category", "wrong-season", "wrong-episode", "wrong-identity", "movie-collection-split", "baseline-one-piece-live-action-wrong-anime", "baseline-normal-boba-fett", "baseline-sample-is-ignored"}
    assert required <= ids
