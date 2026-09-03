import importlib.util
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


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

    assert module.CourseOrganizer.plugin_version == package_v3["CourseOrganizer"]["version"]
    expected_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/courseorganizer.png"
    assert package_v3["CourseOrganizer"]["icon"] == expected_icon
    assert module.CourseOrganizer.plugin_icon == expected_icon
    assert module.CourseOrganizer.author_url == "https://github.com/OneBigMoon"
    assert (ROOT / "icons/courseorganizer.png").is_file()
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


def test_v3_confirmed_movie_keeps_movie_type_when_targeting_children_library(tmp_path):
    module = load_v3_courseorganizer()
    plugin = module.CourseOrganizer.__new__(module.CourseOrganizer)
    plugin._logger = MagicMock()
    plugin._download_root_for_path = MagicMock(return_value=str(tmp_path / "incoming"))
    expected_binding = {"st_dev": 1, "st_ino": 2, "st_ctime_ns": 3}
    decision = SimpleNamespace(action="confirm", target_library="children", value="示例电影")
    calls = []

    class FakeAdapter:
        def get_file_item(self, *_args, **_kwargs):
            return object()

        def rename_context(self, *_args, **_kwargs):
            return nullcontext()

        def manual_transfer(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("stop after capture")

    plugin._current_source_binding = MagicMock(return_value=expected_binding)
    plugin._source_bindings_equal = MagicMock(return_value=True)
    plugin._manual_decision_for = MagicMock(return_value=decision)
    plugin._manual_binding = MagicMock(return_value=expected_binding)
    plugin._confirmed_media_identity = MagicMock(
        return_value=("themoviedb", "123", "movie")
    )
    plugin._moviepilot_directory_context = MagicMock(
        return_value={
            "selected": {
                "children": {
                    "renaming": True,
                    "path": str(tmp_path / "children"),
                    "storage": "local",
                    "library_storage": "local",
                }
            }
        }
    )
    plugin._get_native_adapter = MagicMock(return_value=FakeAdapter())

    result = plugin._apply_manual_decision_locked(
        "示例电影", str(tmp_path / "source"), expected_binding
    )

    assert result == "failed"
    assert calls[0]["mtype"] == "movie"


@pytest.mark.parametrize("transfer_type", ["copy", "hardlink", "move"])
def test_v3_direct_transfer_rejects_symlink_tree(tmp_path, transfer_type):
    module = load_v3_courseorganizer()
    incoming = tmp_path / "incoming"
    source = incoming / "课程"
    target = tmp_path / "target"
    source.mkdir(parents=True)
    target.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"outside")
    os.symlink(outside, source / "linked.mkv")

    plugin = module.CourseOrganizer.__new__(module.CourseOrganizer)
    plugin._logger = MagicMock()
    decision = SimpleNamespace(value="安全课程", target_library="children")
    rule = {
        "download_path": str(incoming),
        "path": str(target),
        "transfer_type": transfer_type,
    }

    result = plugin._apply_direct_transfer("课程", str(source), {}, decision, rule)

    assert result == "failed"
    assert source.is_dir()
    assert not (target / "安全课程").exists()


def test_v3_nested_system_entries_are_excluded_from_scans(tmp_path):
    module = load_v3_courseorganizer()
    course = tmp_path / "课程"
    recycle = course / "#recycle"
    metadata = course / "@eaDir"
    hidden = course / ".hidden"
    recycle.mkdir(parents=True)
    metadata.mkdir()
    hidden.mkdir()
    (course / "main.mkv").write_bytes(b"main")
    (recycle / "old.part").write_bytes(b"old")
    (metadata / "preview.mkv").write_bytes(b"system")
    (hidden / "still.part").write_bytes(b"partial")
    (hidden / "episode.mkv").write_bytes(b"downloading")
    (course / ".DS_Store").write_bytes(b"system")
    (course / "Thumbs.db").write_bytes(b"system")

    fd = os.open(course, os.O_RDONLY)
    try:
        tree = module.CourseOrganizer._scan_manifest_dir(fd)
    finally:
        os.close(fd)
    assert tree is not None
    assert [item[0] for item in tree[0]] == [
        ".hidden/episode.mkv",
        ".hidden/still.part",
        "main.mkv",
    ]
    assert [item[0] for item in tree[1]] == [".hidden"]

    plugin = module.CourseOrganizer.__new__(module.CourseOrganizer)
    plugin._review_path_config = MagicMock(return_value={"incoming": str(tmp_path)})
    expected_binding = plugin._current_source_binding("课程")
    assert expected_binding is not None

    (hidden / "late.mkv").write_bytes(b"downloading")
    late_fd = os.open(course, os.O_RDONLY)
    try:
        late_tree = module.CourseOrganizer._scan_manifest_dir(late_fd)
    finally:
        os.close(late_fd)
    assert late_tree is not None
    assert late_tree != tree
    assert ".hidden/late.mkv" in [item[0] for item in late_tree[0]]
    current_binding = plugin._current_source_binding("课程")
    assert current_binding is not None
    assert not plugin._source_bindings_equal(current_binding, expected_binding)
    (hidden / "late.mkv").unlink()

    media_by_season, subtitle_map, _ = plugin._collect_course_files(str(course))
    assert [Path(path).name for paths in media_by_season.values() for path in paths] == [
        "main.mkv"
    ]
    assert subtitle_map == {}
    assert [item[0] for item in plugin._snapshot_signature(str(course))] == [
        ".hidden/episode.mkv",
        ".hidden/still.part",
        "main.mkv",
    ]
    assert plugin._has_incomplete_file(str(course)) is True

    (hidden / "still.part").unlink()
    assert plugin._has_incomplete_file(str(course)) is False
    assert [item[0] for item in plugin._snapshot_signature(str(course))] == [
        ".hidden/episode.mkv",
        "main.mkv",
    ]

    (course / ".episode.mkv.part").write_bytes(b"partial")
    assert plugin._has_incomplete_file(str(course)) is True


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


def test_v3_system_scan_entry_helper_ignores_only_system_and_hidden_items():
    module = load_v3_courseorganizer()
    ignored = (
        "#recycle",
        "@eaDir",
        ".DS_Store",
        "Thumbs.db",
        "THUMBS.DB",
        "desktop.ini",
        "DESKTOP.INI",
        ".temporary",
        " #recycle ",
    )
    retained = ("#课程资料", "@课程资料", "课程资料", "recycle")

    assert all(module.CourseOrganizer._is_ignored_scan_entry(name) for name in ignored)
    assert not any(module.CourseOrganizer._is_ignored_scan_entry(name) for name in retained)
    assert module.CourseOrganizer._is_system_scan_entry(" #recycle ")
    assert module.CourseOrganizer._is_system_scan_entry("@eaDir")
    assert not module.CourseOrganizer._is_system_scan_entry(".temporary")


def test_v3_scan_entrypoint_skips_system_entries_without_skipping_normal_hash_directory():
    module = load_v3_courseorganizer()
    plugin = module.CourseOrganizer.__new__(module.CourseOrganizer)
    plugin._logger = MagicMock()
    stored_config = {
        "enabled": True,
        "incoming": "/legacy/incoming",
        "tv_output": "/legacy/tv",
        "movie_output": "/legacy/movie",
        "children_output": "/legacy/children",
        "naming_mode": "preview",
    }
    runtime_config = {
        **stored_config,
        "incoming": "/moviepilot/incoming",
        "tv_output": "/moviepilot/tv",
        "movie_output": "/moviepilot/movie",
        "children_output": "/moviepilot/children",
    }
    observed_configs = []
    plugin.get_config = MagicMock(return_value=stored_config)
    plugin._review_path_config = MagicMock(return_value=runtime_config)
    plugin._process_course = MagicMock(
        side_effect=lambda *_args, **_kwargs: observed_configs.append(plugin._get_config())
    )
    entries = [
        "#recycle",
        "@eaDir",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".hidden",
        "#课程资料",
        "普通课程",
    ]

    with (
        patch.object(module.os, "listdir", return_value=entries),
        patch.object(module.os.path, "isdir", return_value=True),
        patch.object(module.naming, "validate_manual_raw_title", return_value=(True, "")),
    ):
        plugin._run(force=True)

    assert {call.args[0] for call in plugin._process_course.call_args_list} == {"#课程资料", "普通课程"}
    assert all(item["incoming"] == "/moviepilot/incoming" for item in observed_configs)
    assert all(
        call.kwargs["source_root"] == "/moviepilot/incoming"
        for call in plugin._process_course.call_args_list
    )
    assert plugin._get_config()["incoming"] == "/legacy/incoming"


def test_v3_review_rows_hide_persisted_system_entries():
    module = load_v3_courseorganizer()
    plugin = module.CourseOrganizer.__new__(module.CourseOrganizer)
    resolver = MagicMock()
    resolver.preview_rows.return_value = [{"raw_title": "#recycle"}]
    plugin._review_path_config = MagicMock(return_value={})
    plugin._get_resolver = MagicMock(return_value=resolver)
    plugin.get_data = MagicMock(return_value={})
    plugin._current_source_binding = MagicMock()

    assert plugin._review_rows() == []
    plugin._current_source_binding.assert_not_called()
