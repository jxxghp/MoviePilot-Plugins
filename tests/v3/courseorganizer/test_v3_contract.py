import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "courseorganizer"


def load_v3_courseorganizer():
    """Use MoviePilot's production namespace in CI and a local namespace standalone."""
    try:
        from app.plugins import courseorganizer as module

        return module
    except ImportError:
        package_name = "courseorganizer_v3_test"
        for key in list(sys.modules):
            if key == package_name or key.startswith(f"{package_name}."):
                sys.modules.pop(key, None)
        spec = importlib.util.spec_from_file_location(
            package_name,
            PLUGIN_DIR / "__init__.py",
            submodule_search_locations=[str(PLUGIN_DIR)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
        return module


def test_v3_package_and_plugin_versions_are_consistent():
    module = load_v3_courseorganizer()
    package_v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    package_v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))

    assert module.CourseOrganizer.plugin_version == "2.0.3"
    assert package_v3["CourseOrganizer"]["version"] == "2.0.3"
    assert package_v3["CourseOrganizer"]["system_version"] == ">=3.0.0"
    assert package_v2["CourseOrganizer"]["v3"] is False


def test_v3_source_uses_public_contracts_and_unified_media_identity():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(PLUGIN_DIR.glob("*.py"))
    )

    for forbidden in (
        "app.core.",
        "app.helper.",
        "app.utils.",
        "app.application.",
        "app.sdk._legacy",
        "tmdbid=",
        "doubanid=",
    ):
        assert forbidden not in source

    vite_config = (PLUGIN_DIR / "vite.config.js").read_text(encoding="utf-8")
    assert "'vuetify/styles'" in vite_config
    assert "vuetify:" in vite_config
    assert "singleton: true" in vite_config

    readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    assert "目录内没有正在下载的临时或缓存文件" in readme
    assert "不会并行执行" in readme


def test_v3_directory_rules_come_from_system_config_oper():
    module = load_v3_courseorganizer()
    requested_keys = []

    class FakeSystemConfigOper:
        def get(self, key):
            requested_keys.append(key)
            return [{"download_path": "/media/incoming", "path": "/media/tv"}]

    class FakeDirectoryModel:
        def __init__(self, **values):
            self.values = values

    adapter = module._MoviePilotNativeAdapter(
        system_config_oper=FakeSystemConfigOper,
        storage_chain=object,
        transfer_chain=object,
        chain_event_type=object,
        event_manager=object(),
        media_source=object,
        media_type=object,
        system_config_key=SimpleNamespace(Directories="directories"),
        directory_model=FakeDirectoryModel,
    )

    rules = adapter.get_directory_rules()

    assert requested_keys == ["directories"]
    assert len(rules) == 1
    assert rules[0].values["download_path"] == "/media/incoming"
    assert rules[0].values["path"] == "/media/tv"


def test_v3_manual_transfer_converts_source_and_type_without_legacy_ids():
    module = load_v3_courseorganizer()
    calls = []

    class FakeTransferChain:
        def manual_transfer(self, **kwargs):
            calls.append(kwargs)
            return True, "ok"

    class FakeMediaSource:
        def __new__(cls, value):
            return f"source:{value}"

    media_type = SimpleNamespace(MOVIE="movie-enum", TV="tv-enum")
    adapter = module._MoviePilotNativeAdapter(
        system_config_oper=object,
        storage_chain=object,
        transfer_chain=FakeTransferChain,
        chain_event_type=object,
        event_manager=object(),
        media_source=FakeMediaSource,
        media_type=media_type,
        system_config_key=object,
        directory_model=object,
    )

    result = adapter.manual_transfer(
        media_source="themoviedb",
        media_id="123",
        mtype="tv",
    )

    assert result == (True, "ok")
    assert calls == [
        {
            "media_source": "source:themoviedb",
            "media_id": "123",
            "mtype": "tv-enum",
        }
    ]
    assert "tmdbid" not in calls[0]
    assert "doubanid" not in calls[0]


def test_v3_metadata_provider_preserves_selected_source_and_media_id():
    module = load_v3_courseorganizer()
    providers = sys.modules[f"{module.__name__}.providers"]
    original_media_source = providers.MediaSource
    searches = []

    class FakeSourceValue:
        def __init__(self, value):
            self.value = value

    class FakeMediaSource:
        def __new__(cls, value):
            return FakeSourceValue(value)

    item = SimpleNamespace(
        title="数学荒岛历险记",
        type="tv",
        media_source=FakeSourceValue("themoviedb"),
        media_id="888",
        year=2011,
        names=[],
    )

    class FakeMediaChain:
        def search(self, title, media_source):
            searches.append((title, media_source.value))
            return None, [item]

    try:
        providers.MediaSource = FakeMediaSource
        provider = providers.MoviePilotMetadataProvider(
            chain=FakeMediaChain(), search_source="themoviedb"
        )
        query = providers.naming.QueryCandidate(text="数学荒岛历险记", origin="local")

        result = provider.search([query], ["themoviedb"])
    finally:
        providers.MediaSource = original_media_source

    assert searches == [("数学荒岛历险记", "themoviedb")]
    assert len(result.candidates) == 1
    assert result.candidates[0].key == "themoviedb:888:tv"
    assert result.candidates[0].media_id == "888"


def test_v3_metadata_provider_rejects_legacy_id_only_items():
    module = load_v3_courseorganizer()
    providers = sys.modules[f"{module.__name__}.providers"]
    provider = providers.MoviePilotMetadataProvider(chain=object())
    query = providers.naming.QueryCandidate(text="示例", origin="local")
    legacy_item = SimpleNamespace(
        title="示例",
        type="tv",
        media_source=SimpleNamespace(value="themoviedb"),
        media_id="",
        tmdb_id=123,
    )

    assert provider._from_media_info(legacy_item, "themoviedb", query) is None


def test_v3_manual_candidate_history_respects_current_source_allowlist():
    module = load_v3_courseorganizer()
    naming = sys.modules[f"{module.__name__}.naming"]
    providers = sys.modules[f"{module.__name__}.providers"]
    resolver_module = sys.modules[f"{module.__name__}.resolver"]
    raw_title = "历史 TMDB 关联"
    candidate = naming.MetadataCandidate(
        key="themoviedb:123:tv",
        source="themoviedb",
        media_id="123",
        media_type="tv",
        title=raw_title,
        year=2020,
    )

    class EmptyDoubanProvider:
        def resolve_sources(self, requested):
            return tuple(requested)

        def search(self, queries, sources):
            return providers.ProviderSearchResult(
                candidates=(),
                errors=(),
                attempted_sources=tuple(sources),
                all_failed=False,
            )

    for history_source in ("identity", "query", "manual"):
        identity = {}
        store = {}
        if history_source == "identity":
            identity["cached_candidates"] = [candidate.to_dict()]
        elif history_source == "query":
            identity["last_query_candidates"] = [candidate.to_dict()]
        else:
            store["naming_manual_decisions_v1"] = {
                "schema": 1,
                "items": {raw_title: {"candidate": candidate.to_dict()}},
            }
        if identity:
            store["naming_identity_v1"] = {raw_title: identity}

        resolver = resolver_module.SmartNamingResolver(
            load_data=lambda key, default=None: store.get(key, default),
            save_data=lambda key, value: store.__setitem__(key, value),
            provider=EmptyDoubanProvider(),
        )
        decision = resolver.resolve(
            raw_title,
            naming.DirectoryHints(media_count=1, seasons=(1,), episodic=True),
            resolver_module.NamingConfig(
                mode="apply",
                sources=("douban",),
                manual_overrides=f"{raw_title} => candidate:{candidate.key}",
            ),
        )

        assert decision.status == "invalid_override"
        assert decision.blocked_reason == "candidate_not_found"
        assert decision.source == ""
