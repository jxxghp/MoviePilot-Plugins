"""CourseOrganizer V3 识别设置单测。"""

from pathlib import Path
from unittest.mock import patch

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
        ROOT / "plugins.v3" / "courseorganizer" / "src" / "components" / "Config.vue"
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
        ROOT / "plugins.v3" / "courseorganizer" / "src" / "components" / "Page.vue"
    ).read_text(encoding="utf-8")

    assert "visibleReviewItems(data)" in source
    assert "rows.filter(item => !isIgnoredSystemItem(item))" in source
    assert "'#recycle'" in source
