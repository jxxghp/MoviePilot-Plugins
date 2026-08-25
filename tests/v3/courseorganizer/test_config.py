"""CourseOrganizer V3 识别设置单测。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_plugin_directory_context_does_not_read_system_directory_rules():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    config = plugin._normalize_config({})
    plugin._get_config = MagicMock(return_value=config)
    plugin._load_moviepilot_directory_rules = MagicMock(
        side_effect=AssertionError("system directory rules must not be read")
    )

    context = plugin._moviepilot_directory_context()

    assert context["monitoring_enabled"] is False
    assert context["monitoring_rules"] == []
    assert context["monitoring_conflicts"] == []
    plugin._load_moviepilot_directory_rules.assert_not_called()


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
        ROOT / "plugins.v3" / "courseorganizer" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "download_directories" in source
    assert "archive_directories" in source
    assert "addDownloadDirectory" in source
    assert "addArchiveDirectory" in source
    assert "从 MoviePilot 导入" not in source
    assert "directory_source_mode" not in source


def test_custom_page_filters_system_entries_from_stale_api_rows():
    source = (
        ROOT / "plugins.v3" / "courseorganizer" / "src" / "components" / "Page.vue"
    ).read_text(encoding="utf-8")

    assert "visibleReviewItems(data)" in source
    assert "rows.filter(item => !isIgnoredSystemItem(item))" in source
    assert "'#recycle'" in source


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
        ROOT / "plugins.v3" / "courseorganizer" / "src" / "components" / "Config.vue"
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
