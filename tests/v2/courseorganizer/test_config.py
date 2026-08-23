"""CourseOrganizer 识别设置单测。"""

import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.plugins import courseorganizer as courseorganizer_module
from app.plugins.courseorganizer import CourseOrganizer
from app.plugins.courseorganizer.resolver import NamingConfig


ROOT = Path(__file__).parents[3]


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def test_missing_plugin_source_override_uses_supported_system_sources():
    config = NamingConfig.sanitize({"naming_mode": "auto"})

    assert config.sources == ("themoviedb", "douban")
    assert config.append_tmdb_id is False


def test_form_hides_settings_owned_by_moviepilot():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    config = plugin._normalize_config({})

    with patch.object(plugin, "_get_config", return_value=config):
        form, defaults = plugin.get_form()

    models = {
        node.get("props", {}).get("model")
        for node in _walk(form)
        if isinstance(node.get("props"), dict)
    }
    texts = [str(node.get("text", "")) for node in _walk(form)]
    assert "auto_organize" in models
    assert "naming_sources" not in models
    assert "naming_append_tmdb_id" not in models
    assert "naming_auto_threshold" not in models
    assert "naming_min_margin" not in models
    assert "naming_uncertain_policy" not in models
    assert "naming_ai_review" not in models
    assert "naming_clear_cache_once" not in models
    assert "naming_sources" not in defaults
    assert "naming_append_tmdb_id" not in defaults
    assert defaults["auto_organize"] is False
    assert defaults["naming_mode"] == "preview"
    assert defaults["naming_uncertain_policy"] == "hold"
    assert defaults["naming_ai_review"] is True
    assert any("不在插件内重复配置" in text for text in texts)
    assert any("自动监控" in text for text in texts)


def test_auto_organize_controls_apply_mode_and_migrates_legacy_apply():
    plugin = CourseOrganizer.__new__(CourseOrganizer)

    disabled = plugin._normalize_config({})
    enabled = plugin._normalize_config({"auto_organize": True})
    migrated = plugin._normalize_config({"naming_mode": "apply"})
    resolver_config = NamingConfig.sanitize(enabled)

    assert disabled["auto_organize"] is False
    assert disabled["naming_mode"] == "preview"
    assert enabled["auto_organize"] is True
    assert enabled["naming_mode"] == "apply"
    assert migrated["auto_organize"] is True
    assert migrated["naming_mode"] == "apply"
    assert resolver_config.mode == "apply"
    assert resolver_config.uncertain_policy == "hold"
    assert resolver_config.ai_review is True


def test_custom_config_exposes_only_auto_organize_control():
    source = (
        ROOT / "plugins.v2" / "courseorganizer" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "localConfig.auto_organize" in source
    assert "config.naming_mode" in source
    assert "=== 'apply'" in source
    for model in (
        "naming_auto_threshold",
        "naming_min_margin",
        "naming_uncertain_policy",
        "naming_ai_review",
        "naming_clear_cache_once",
    ):
        assert model not in source


def test_custom_page_filters_system_entries_from_stale_api_rows():
    source = (
        ROOT / "plugins.v2" / "courseorganizer" / "src" / "components" / "Page.vue"
    ).read_text(encoding="utf-8")

    assert "visibleReviewItems(data)" in source
    assert "rows.filter(item => !isIgnoredSystemItem(item))" in source
    assert "'#recycle'" in source


def test_v2_market_manifest_uses_renderable_png_icon():
    package_v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))

    assert CourseOrganizer.plugin_version == "1.7.16"
    assert package_v2["CourseOrganizer"]["version"] == "1.7.16"
    assert package_v2["CourseOrganizer"]["icon"] == "courseorganizer.png"
    assert CourseOrganizer.plugin_icon == "icons/courseorganizer.png"
    assert (ROOT / "icons/courseorganizer.png").is_file()


def test_confirmed_movie_keeps_movie_type_when_targeting_children_library(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    plugin._logger = MagicMock()
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
def test_direct_transfer_rejects_symlink_tree(tmp_path, transfer_type):
    incoming = tmp_path / "incoming"
    source = incoming / "课程"
    target = tmp_path / "target"
    source.mkdir(parents=True)
    target.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"outside")
    os.symlink(outside, source / "linked.mkv")

    plugin = CourseOrganizer.__new__(CourseOrganizer)
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


def test_nested_system_entries_are_excluded_from_scans(tmp_path):
    course = tmp_path / "课程"
    recycle = course / "#recycle"
    hidden = course / ".hidden"
    recycle.mkdir(parents=True)
    hidden.mkdir()
    (course / "main.mkv").write_bytes(b"main")
    (recycle / "old.mkv").write_bytes(b"old")
    (hidden / "still.part").write_bytes(b"partial")
    (course / "Thumbs.db").write_bytes(b"system")

    fd = os.open(course, os.O_RDONLY)
    try:
        tree = CourseOrganizer._scan_manifest_dir(fd)
    finally:
        os.close(fd)
    assert tree is not None
    assert [item[0] for item in tree[0]] == ["main.mkv"]

    plugin = CourseOrganizer.__new__(CourseOrganizer)
    media_by_season, subtitle_map, _ = plugin._collect_course_files(str(course))
    assert [Path(path).name for paths in media_by_season.values() for path in paths] == [
        "main.mkv"
    ]
    assert subtitle_map == {}
    assert [item[0] for item in plugin._snapshot_signature(str(course))] == ["main.mkv"]
    assert plugin._has_incomplete_file(str(course)) is False


def test_system_scan_entry_helper_ignores_only_system_and_hidden_items():
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

    assert all(CourseOrganizer._is_ignored_scan_entry(name) for name in ignored)
    assert not any(CourseOrganizer._is_ignored_scan_entry(name) for name in retained)


def test_scan_entrypoint_skips_system_entries_without_skipping_normal_hash_directory():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
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
        patch.object(courseorganizer_module.os, "listdir", return_value=entries),
        patch.object(courseorganizer_module.os.path, "isdir", return_value=True),
        patch.object(courseorganizer_module.naming, "validate_manual_raw_title", return_value=(True, "")),
    ):
        plugin._run(force=True)

    assert {call.args[0] for call in plugin._process_course.call_args_list} == {"#课程资料", "普通课程"}
    assert all(item["incoming"] == "/moviepilot/incoming" for item in observed_configs)
    assert all(
        call.kwargs["source_root"] == "/moviepilot/incoming"
        for call in plugin._process_course.call_args_list
    )
    assert plugin._get_config()["incoming"] == "/legacy/incoming"


def test_review_rows_hide_persisted_system_entries():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    resolver = MagicMock()
    resolver.preview_rows.return_value = [{"raw_title": "#recycle"}]
    plugin._review_path_config = MagicMock(return_value={})
    plugin._get_resolver = MagicMock(return_value=resolver)
    plugin.get_data = MagicMock(return_value={})
    plugin._current_source_binding = MagicMock()

    assert plugin._review_rows() == []
    plugin._current_source_binding.assert_not_called()
