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


def test_form_uses_plugin_owned_directory_configuration():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    config = plugin._normalize_config({})
    directory_context = {"ready": False, "message": "请至少添加一个下载目录"}

    with (
        patch.object(plugin, "_get_config", return_value=config),
        patch.object(
            plugin, "_moviepilot_directory_context", return_value=directory_context
        ),
    ):
        form, defaults = plugin.get_form()

    models = {
        node.get("props", {}).get("model")
        for node in _walk(form)
        if isinstance(node.get("props"), dict)
    }
    texts = [str(node.get("text", "")) for node in _walk(form)]
    assert "auto_organize" in models
    assert defaults["download_directories"] == []
    assert defaults["archive_directories"] == []
    assert any("插件独立维护" in text for text in texts)


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


def test_incomplete_directories_force_preview_mode():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    config = plugin._normalize_config({"auto_organize": True})
    plugin._get_config = MagicMock(return_value=config)

    runtime = plugin._review_path_config()

    assert runtime["auto_organize"] is False
    assert runtime["naming_mode"] == "preview"
    assert "目录" in runtime["monitoring_conflict"]


def test_custom_config_exposes_dynamic_plugin_directories():
    source = (
        ROOT / "plugins.v2" / "courseorganizer" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "download_directories" in source
    assert "archive_directories" in source
    assert "addDownloadDirectory" in source
    assert "addArchiveDirectory" in source
    assert "从 MoviePilot 导入" not in source
    assert "directory_source_mode" not in source


def test_custom_page_filters_system_entries_from_stale_api_rows():
    source = (
        ROOT / "plugins.v2" / "courseorganizer" / "src" / "components" / "Page.vue"
    ).read_text(encoding="utf-8")

    assert "visibleReviewItems(data)" in source
    assert "rows.filter(item => !isIgnoredSystemItem(item))" in source
    assert "'#recycle'" in source


def test_v2_market_manifest_uses_renderable_png_icon():
    package_v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))

    assert CourseOrganizer.plugin_version == "1.7.20"
    assert package_v2["CourseOrganizer"]["version"] == "1.7.20"
    expected_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/courseorganizer.png"
    assert package_v2["CourseOrganizer"]["icon"] == expected_icon
    assert CourseOrganizer.plugin_icon == expected_icon
    assert CourseOrganizer.author_url == "https://github.com/OneBigMoon"
    assert (ROOT / "icons/courseorganizer.png").is_file()


def test_confirmed_movie_keeps_movie_type_when_targeting_children_library(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
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
    plugin._download_root_for_path = MagicMock(return_value=str(tmp_path / "source-root"))
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
        tree = CourseOrganizer._scan_manifest_dir(fd)
    finally:
        os.close(fd)
    assert tree is not None
    assert [item[0] for item in tree[0]] == [
        ".hidden/episode.mkv",
        ".hidden/still.part",
        "main.mkv",
    ]
    assert [item[0] for item in tree[1]] == [".hidden"]

    plugin = CourseOrganizer.__new__(CourseOrganizer)
    plugin._review_path_config = MagicMock(return_value={"incoming": str(tmp_path)})
    expected_binding = plugin._current_source_binding("课程")
    assert expected_binding is not None

    (hidden / "late.mkv").write_bytes(b"downloading")
    late_fd = os.open(course, os.O_RDONLY)
    try:
        late_tree = CourseOrganizer._scan_manifest_dir(late_fd)
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
    assert CourseOrganizer._is_system_scan_entry(" #recycle ")
    assert CourseOrganizer._is_system_scan_entry("@eaDir")
    assert not CourseOrganizer._is_system_scan_entry(".temporary")


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
    plugin._moviepilot_directory_context = MagicMock(return_value={"selected": {}})
    plugin._get_resolver = MagicMock(return_value=resolver)
    plugin.get_data = MagicMock(return_value={})
    plugin._current_source_binding = MagicMock()

    assert plugin._review_rows() == []
    plugin._current_source_binding.assert_not_called()

def _directory_list_config(tmp_path):
    first_download = tmp_path / "download-a"
    second_download = tmp_path / "download-b"
    tv = tmp_path / "tv"
    custom = tmp_path / "custom"
    for path in (first_download, second_download, tv, custom):
        path.mkdir()
    return {
        "download_directories": [
            {"name": "下载 A", "path": str(first_download)},
            {"name": "下载 B", "path": str(second_download)},
        ],
        "archive_directories": [
            {"key": "tv", "name": "电视剧", "path": str(tv), "media_type": "tv"},
            {"key": "course", "name": "课程归档", "path": str(custom)},
        ],
    }, first_download, second_download, tv, custom


def test_directory_lists_migrate_legacy_config():
    plugin = CourseOrganizer.__new__(CourseOrganizer)

    config = plugin._normalize_config(
        {
            "incoming": "/legacy/download",
            "tv_output": "/legacy/tv",
            "movie_output": "/legacy/movie",
            "children_output": "/legacy/children",
        }
    )

    assert config["download_directories"] == [
        {"name": "下载目录", "path": "/legacy/download"}
    ]
    assert [item["key"] for item in config["archive_directories"]] == [
        "tv",
        "movie",
        "children",
    ]
    assert config["incoming"] == "/legacy/download"
    assert config["tv_output"] == "/legacy/tv"


def test_plugin_directory_context_uses_lists_without_system_directory_reads(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    plugin._logger = MagicMock()
    raw_config, first_download, second_download, tv, custom = _directory_list_config(tmp_path)
    config = plugin._normalize_config(raw_config)
    plugin._get_config = MagicMock(return_value=config)
    plugin._load_moviepilot_directory_rules = MagicMock(
        side_effect=AssertionError("system directory rules must not be read")
    )

    context = plugin._moviepilot_directory_context()

    assert [item["path"] for item in context["download_directories"]] == [
        str(first_download),
        str(second_download),
    ]
    assert [item["value"] for item in context["libraries"]] == ["tv", "course"]
    assert context["selected"]["course"]["path"] == str(custom)
    plugin._load_moviepilot_directory_rules.assert_not_called()


def test_run_scans_each_configured_download_directory(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    plugin._logger = MagicMock()
    raw_config, first_download, second_download, tv, custom = _directory_list_config(tmp_path)
    config = plugin._normalize_config({**raw_config, "enabled": True})
    (first_download / "课程 A").mkdir()
    (second_download / "课程 B").mkdir()
    calls = []
    plugin._get_config = MagicMock(return_value=config)
    def process_course(course_name, _course_path, output_root=None, source_root=None):
        assert output_root is None
        calls.append((course_name, source_root))

    plugin._process_course = process_course

    plugin._run_with_config(force=True)

    assert {call[0] for call in calls} == {"课程 A", "课程 B"}
    assert {call[1] for call in calls} == {
        str(first_download),
        str(second_download),
    }


def test_dynamic_archive_keys_are_available_for_manual_targets(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    raw_config, _first, _second, _tv, _custom = _directory_list_config(tmp_path)
    config = plugin._normalize_config(raw_config)
    plugin._get_config = MagicMock(return_value=config)

    assert plugin._manual_target_libraries() == {"tv", "course"}
    assert plugin._archive_directory_by_key("course")["name"] == "课程归档"


def test_custom_archive_key_is_valid_for_legacy_manual_override(tmp_path):
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    raw_config, _first, _second, _tv, _custom = _directory_list_config(tmp_path)
    config = plugin._normalize_config(
        {**raw_config, "naming_manual_overrides": "示例课程 => confirm:course:示例课程"}
    )
    plugin._get_config = MagicMock(return_value=config)

    decision = plugin._legacy_review_override("示例课程")

    assert decision is not None
    assert decision.target_library == "course"


def test_incomplete_directory_lists_force_preview_mode():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    config = plugin._normalize_config({"auto_organize": True})
    plugin._get_config = MagicMock(return_value=config)

    runtime = plugin._review_path_config()

    assert runtime["auto_organize"] is False
    assert runtime["naming_mode"] == "preview"
    assert "目录" in runtime["monitoring_conflict"]


def test_directory_config_ui_supports_dynamic_download_and_archive_lists():
    source = (
        ROOT / "plugins.v2" / "courseorganizer" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "download_directories" in source
    assert "archive_directories" in source
    assert "addDownloadDirectory" in source
    assert "addArchiveDirectory" in source
    assert "removeDownloadDirectory" in source
    assert "removeArchiveDirectory" in source
    assert "下载目录" in source
    assert "归档目录" in source
    assert "MoviePilot" in source
