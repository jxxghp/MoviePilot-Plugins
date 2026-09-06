"""MediaGovernor 4.4 合同测试：不访问 NAS、模型以外的网络或真实媒体。"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3/mediagovernor/__init__.py"
PAGE = ROOT / "plugins.v3/mediagovernor/src/components/AppPage.vue"
RULES = ROOT / "plugins.v3/mediagovernor/src/lib/governance.js"
GOLDEN = ROOT / "tests/v3/mediagovernor/fixtures/golden/v1/cases.json"
LIVE_GOLDEN = ROOT / "tests/v3/mediagovernor/fixtures/golden/v1/live-baseline.json"


class _FakeLLM:
    async def ainvoke(self, _prompt):
        return types.SimpleNamespace(content='{"probe":{"title":"示例剧","media_type":"tv","confidence":0.9,"abstain":false},"one":{"title":"示例剧","media_type":"tv","confidence":0.9,"abstain":false}}')


class _FakeLLMHelper:
    @staticmethod
    def get_llm(*_args, **_kwargs): return _FakeLLM()
    @staticmethod
    def extract_text_content(content, **_kwargs): return str(content or "")


def _load_plugin():
    app, plugins, agent, llm, helper, fastapi = (types.ModuleType(name) for name in ("app", "app.plugins", "app.agent", "app.agent.llm", "app.agent.llm.helper", "fastapi"))
    class Base:
        def __init__(self): self.store, self.path = {}, Path(tempfile.mkdtemp())
        def get_data(self, key): return self.store.get(key)
        def save_data(self, key, value): self.store[key] = value
        def get_data_path(self): return self.path
    plugins._PluginBase = Base; helper.LLMHelper = _FakeLLMHelper; fastapi.Request = type("Request", (), {})
    saved = {name: sys.modules.get(name) for name in ("app", "app.plugins", "app.agent", "app.agent.llm", "app.agent.llm.helper", "fastapi")}
    sys.modules.update({"app": app, "app.plugins": plugins, "app.agent": agent, "app.agent.llm": llm, "app.agent.llm.helper": helper, "fastapi": fastapi})
    try:
        spec = importlib.util.spec_from_file_location("mediagovernor_plugin", PLUGIN); module = importlib.util.module_from_spec(spec); assert spec and spec.loader; sys.modules[spec.name] = module; spec.loader.exec_module(module); return module
    finally:
        for name, value in saved.items():
            if value is None: sys.modules.pop(name, None)
            else: sys.modules[name] = value


class Request:
    method = "POST"
    def __init__(self, body): self.body = body
    async def json(self): return self.body


def test_versions_assets_and_new_api_contract_are_synced():
    module = _load_plugin(); manifest = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["MediaGovernor"]
    package = json.loads((ROOT / "plugins.v3/mediagovernor/package.json").read_text(encoding="utf-8"))
    assert manifest["version"] == package["version"] == module.MediaGovernor.plugin_version == "4.4.0"
    assert list(manifest["history"])[0] == "v4.4.0"
    assert module.MediaGovernor.get_render_mode() == ("vue", "dist/v4.4.0/assets")
    instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    assert [row["path"] for row in instance.get_api()] == ["/map_status", "/map_snapshot", "/map_watch", "/map_plan", "/map_commit", "/map_unit", "/map_dirty", "/ai_probe", "/bundle_analyze_batch"]
    assert all(row["auth"] == "bear" for row in instance.get_api())


def test_map_persists_paths_only_privately_and_status_never_leaks_them():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    result = asyncio.run(instance.api_map_commit(Request({"baseline": True, "scope_verified": True, "download_units": [{"id": "/private/download/A", "root": {"path": "/private/download/A", "name": "A"}, "label": "示例媒体", "fingerprint": "one"}], "library_nodes": [{"id": "/private/library/A", "root": {"path": "/private/library/A", "name": "A"}}], "coverage": {"failed_history": 47}, "findings": [{"unit_id": "/private/download/A", "kind": "native_failure", "reason": "当前失败"}]})))
    assert result.success and result.data["download_units"] == 1
    assert "/private" not in json.dumps(result.data, ensure_ascii=False)
    saved = instance._map_path().read_text(encoding="utf-8")
    assert "/private/download/A" in saved
    assert asyncio.run(instance.api_map_status()).data["findings"] == 1
    snapshot = asyncio.run(instance.api_map_snapshot()).data
    assert snapshot["summary"]["download_units"] == 1
    assert snapshot["findings"][0]["title"] == "示例媒体"
    assert snapshot["coverage"]["failed_history"] == 47
    assert "/private" not in json.dumps(snapshot, ensure_ascii=False)


def test_saved_card_can_load_one_private_detail_without_rescanning_everything():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    detail = {"id": "unit-a", "root": {"path": "/private/download/A", "name": "A"}, "entries": [{"path": "/private/download/A/A.mkv", "name": "A.mkv"}], "history": []}
    assert asyncio.run(instance.api_map_commit(Request({"baseline": True, "scope_verified": True, "download_units": [{"id": "unit-a", "package_id": "pkg-a", "label": "示例媒体", "detail": detail}], "library_nodes": [], "findings": [{"unit_id": "unit-a", "kind": "native_failure", "reason": "当前失败"}]}))).success
    card = asyncio.run(instance.api_map_snapshot()).data["findings"][0]
    loaded = asyncio.run(instance.api_map_unit(Request({"unit_id": card["unit_id"]})))
    assert loaded.success and loaded.data["unit"]["entries"][0]["name"] == "A.mkv"


def test_incremental_plan_only_echoes_the_callers_changed_or_unchanged_ids():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    asyncio.run(instance.api_map_commit(Request({"baseline": True, "scope_verified": True, "download_units": [{"id": "raw-a", "root": {"path": "/private/A"}, "header_fingerprint": "same"}], "library_nodes": [], "findings": []})))
    plan = asyncio.run(instance.api_map_plan(Request({"units": [{"id": "raw-a", "fingerprint": "same"}, {"id": "raw-b", "fingerprint": "new"}]})))
    assert plan.data["unchanged"] == ["raw-a"]


def test_batch_analysis_is_bounded_path_free_and_cached():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    body = {"items": [{"id": "one", "evidence": {"title_hints": ["示例剧"], "entries": [{"name": "Show.S01E01.mkv", "path": "/must/not/leave"}], "video_count": 1}}]}
    first = asyncio.run(instance.api_bundle_analyze_batch(Request(body))); second = asyncio.run(instance.api_bundle_analyze_batch(Request(body)))
    assert first.success and first.data["analyzed"] == 1
    assert first.data["omitted"] == []
    assert second.success and second.data["cached"] == 1
    assert "path" not in json.dumps(instance._normalise_evidence(body["items"][0]["evidence"]))
    oversized = {"entries": [{"name": f"Episode-{index:04d}.mkv", "type": "file", "depth": 2} for index in range(500)]}
    assert len(instance._normalise_evidence(oversized)["entries"]) == 80


def test_ai_cache_fingerprint_is_versioned_and_cannot_reuse_v42_diagnoses():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    evidence = instance._normalise_evidence({"title_hints": ["示例剧"], "entries": [{"name": "Show.S01E01.mkv"}], "video_count": 1})
    legacy = module.hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    current = instance._diagnosis_fingerprint(evidence)
    assert current != legacy
    assert current == instance._diagnosis_fingerprint(evidence)


def test_ai_abstention_is_returned_but_never_cached():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    async def abstain(items):
        return {key: module.Diagnosis(abstain=True, confidence=0, reasons=["本批无法确认"]) for key, _ in items}
    instance._model = abstain
    body = {"items": [{"id": "one", "evidence": {"title_hints": ["示例"], "entries": [{"name": "Example.mkv"}]}}]}
    first = asyncio.run(instance.api_bundle_analyze_batch(Request(body)))
    second = asyncio.run(instance.api_bundle_analyze_batch(Request(body)))
    assert first.success and second.success
    assert first.data["cached"] == second.data["cached"] == 0
    assert instance._diagnosis_cache == {}


def test_events_only_mark_dirty_and_never_read_media_or_call_model():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    instance._on_transfer_result({"event_data": {"transfer_history_id": 7, "fileitem": {"path": "/private/A"}}})
    assert len(instance._dirty) == 1
    source = PLUGIN.read_text(encoding="utf-8")
    callback = source[source.index("def _on_transfer_result"):source.index("@classmethod\n    def _normalise_evidence")]
    assert "storage/list" not in callback and "_model" not in callback


def test_frontend_builds_evidence_packages_and_uses_only_declared_official_preview_fields():
    page, rules = PAGE.read_text(encoding="utf-8"), RULES.read_text(encoding="utf-8")
    for endpoint in ("storage/directories?directory_type=${kind}", "storage/list", "history/transfer?status=${status}", "plugin/MediaGovernor/map_snapshot", "plugin/MediaGovernor/map_commit", "plugin/MediaGovernor/bundle_analyze_batch", "media/recognize_file", "transfer/manual"):
        assert endpoint in page
    assert "preview: true" in page and "preview: false" in page and "reorganize: false" in page
    assert "storage/delete" not in page and "fetch(" not in page
    for name in ("createDownloadUnits", "unitFingerprint", "diffMap", "classifyFinding"):
        assert f"function {name}" in rules or f"export function {name}" in rules
    assert "evaluateOfficialPreview" in page
    assert "identityTargets(units.value)" in page
    assert "preliminary.some" not in page
    assert "previewComplete(unit.officialPreview" in page
    assert "scanTargetParents(units.value)" in page
    assert "scanLibrary(" not in page
    assert "createEvidencePackages(top.map(unit => unit.root), histories.value)" in page
    assert "scanDownloadUnits(toScan, packages.length)" in page
    assert "Math.min(4, toScan.length)" in page
    assert "MediaGovernor 4.4.0" in page
    assert "selectLibraryTarget" in page
    assert "transfer/manual/target-path" not in page
    assert "configuredDownloadRoots(downloadConfigurations)" in page
    assert "scope_verified: true" in page
    assert "evaluateCurrentState" in page
    assert "createDownloadUnits(root, await list(root))" in page
    assert "createDownloadUnits(downloadConfigurations" not in page
    assert "src_fileitem" not in page
    assert "manualPreviewRequest" in page and "manualRebuildRequests" in page
    assert "media/${encodeURIComponent(identity.media_id)}?media_source=" in page
    assert "const pageSize = 100, entryLimit = 20000" in page
    assert "result.omitted" in page and "chars + cost > 24000" in page
    assert "整理前后对比" in page


def test_map_rejects_unverified_scope_and_discards_previous_schema():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    rejected = asyncio.run(instance.api_map_commit(Request({"baseline": True, "download_units": [], "library_nodes": [], "findings": []})))
    assert not rejected.success
    assert "下载范围未通过验证" in rejected.message
    instance._map_path().write_text(json.dumps({"schema": "3.2", "download_units": [{"id": "old"}]}), encoding="utf-8")
    replacement = module.MediaGovernor(); replacement.init_plugin({"enabled": True})
    assert replacement._runtime_map == {}


def test_incremental_normal_commit_removes_only_that_units_stale_finding():
    module = _load_plugin(); instance = module.MediaGovernor(); instance.init_plugin({"enabled": True})
    baseline = {"baseline": True, "scope_verified": True, "download_units": [{"id": "unit-a", "root": {"path": "/private/A"}}, {"id": "unit-b", "root": {"path": "/private/B"}}], "library_nodes": [], "findings": [{"unit_id": "unit-a", "kind": "native_failure", "reason": "旧问题"}, {"unit_id": "unit-b", "kind": "native_failure", "reason": "保留问题"}]}
    assert asyncio.run(instance.api_map_commit(Request(baseline))).success
    restored = {"partial": True, "scope_verified": True, "download_units": [{"id": "unit-a", "root": {"path": "/private/A"}}], "library_nodes": [], "findings": []}
    assert asyncio.run(instance.api_map_commit(Request(restored))).success
    snapshot = asyncio.run(instance.api_map_snapshot()).data
    assert [item["reason"] for item in snapshot["findings"]] == ["保留问题"]


def test_golden_fixtures_are_deidentified_and_cover_the_known_failure_contract():
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    live_payload = json.loads(LIVE_GOLDEN.read_text(encoding="utf-8"))
    assert payload["schema"] == "mediagovernor-golden-fixture/v2"
    assert live_payload["schema"] == "mediagovernor-golden-fixture/v2"
    assert len(payload["cases"]) >= 10
    assert len(live_payload["cases"]) >= 16
    def contains_real_path(value):
        if isinstance(value, dict):
            return any(
                (key.lower() in {"src_fileitem", "dest_fileitem"})
                or (key.lower() == "path" and (not isinstance(item, str) or not item.startswith("/fixture/")))
                or (key.lower() != "path" and contains_real_path(item))
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_real_path(item) for item in value)
        return isinstance(value, str) and (value.startswith(("/", "\\")) or ":\\" in value) and not value.startswith("/fixture/")
    assert not contains_real_path(payload)
    assert not contains_real_path(live_payload)
    required = {"normal-target-present", "native-failure", "wrong-category", "wrong-season", "wrong-episode", "wrong-identity", "incomplete-preview-abstains", "native-ai-conflict", "ai-unique-grounding", "anime-not-live-action", "multi-season-one-work", "movie-collection-split", "multi-root-download-split", "no-download-hash-auditable-not-executable", "one-work-one-finding"}
    assert required <= {item["id"] for item in payload["cases"]}
    live_required = {
        "baseline-blue-eye-samurai-season-failed",
        "baseline-cyberpunk-one-episode-failed",
        "baseline-cowboy-bebop-mixed-failure-and-wrong-work",
        "baseline-one-piece-live-action-wrong-anime",
        "baseline-chuka-ichiban-wrong-live-action",
        "baseline-rick-and-morty-wrong-category",
        "baseline-love-death-old-seasons-wrong-category",
        "baseline-pantheon-wrong-category",
        "baseline-scavengers-reign-wrong-category",
        "baseline-asia-sound-split-and-wrong-category",
        "baseline-chorus-variety-wrong-category",
        "baseline-comedy-variety-wrong-category",
        "baseline-prehistoric-planet-flat-hierarchy",
        "baseline-demon-slayer-subtitle-wrong-work",
        "baseline-protege-subtitle-wrong-year",
        "baseline-normal-boba-fett",
        "baseline-normal-my-altay",
        "baseline-normal-love-death-season-four",
        "baseline-sample-is-ignored",
    }
    assert live_required <= {item["id"] for item in live_payload["cases"]}
