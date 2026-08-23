"""CourseOrganizer 识别设置单测。"""

import json
from pathlib import Path

from unittest.mock import MagicMock, patch

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

    assert "naming_sources" not in models
    assert "naming_append_tmdb_id" not in models
    assert "naming_auto_threshold" in models
    assert "naming_min_margin" in models
    assert "naming_ai_review" in models
    assert "naming_sources" not in defaults
    assert "naming_append_tmdb_id" not in defaults
    assert any("无需重复配置" in text for text in texts)


def test_v2_market_manifest_uses_renderable_png_icon():
    package_v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))

    assert package_v2["CourseOrganizer"]["icon"] == "courseorganizer.png"
    assert (ROOT / "icons/courseorganizer.png").is_file()


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
    )
    retained = ("#课程资料", "@课程资料", "课程资料", "recycle")

    assert all(CourseOrganizer._is_ignored_scan_entry(name) for name in ignored)
    assert not any(CourseOrganizer._is_ignored_scan_entry(name) for name in retained)


def test_scan_entrypoint_skips_system_entries_without_skipping_normal_hash_directory():
    plugin = CourseOrganizer.__new__(CourseOrganizer)
    plugin._logger = MagicMock()
    plugin._get_config = MagicMock(
        return_value={
            "enabled": True,
            "incoming": "/media/incoming",
            "tv_output": "/media/tv",
            "movie_output": "/media/movie",
            "children_output": "/media/children",
            "naming_mode": "off",
        }
    )
    plugin._process_course = MagicMock()
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
