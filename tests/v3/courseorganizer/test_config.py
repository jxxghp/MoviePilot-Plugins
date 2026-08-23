"""CourseOrganizer V3 识别设置单测。"""

from unittest.mock import patch

from app.plugins.courseorganizer import CourseOrganizer
from app.plugins.courseorganizer.resolver import NamingConfig


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
