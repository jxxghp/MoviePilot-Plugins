import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import app.plugins.lunatvsource as plugin_module
import app.plugins.lunatvsource.classification as classification_module
import pytest
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.classification import (
    CMS_CLASS_NAMES_FIELD,
    CMS_SOURCE_KEY_FIELD,
    CMS_TYPE_NAME_FIELD,
)
from app.plugins.lunatvsource.cms import CmsResult

from app.application.classification.execution import ClassificationExecutionService
from app.domain.context import MediaInfo
from app.runtime.extensions.plugin.classification import PluginClassificationRegistry
from app.schemas.category import CategoryConfig, ClassificationPolicy
from app.schemas.types import MediaSource, MediaType


class _SdkModel:
    """Capture public SDK constructor values without requiring a new host."""

    def __init__(self, **values):
        self.__dict__.update(values)


class _HostMediaInfo:
    """Represent the compatible MediaInfo surface returned by the host."""

    def __init__(self, **values):
        self.__dict__.update(values)


class _ClassificationRuntime:
    """Provide one immutable policy to the host classification executor."""

    def __init__(self, policy: ClassificationPolicy):
        """Store an isolated plugin-fixture policy."""
        self._policy = policy.model_copy(deep=True)

    def active_policy(self):
        """Return an isolated active policy snapshot."""
        return self._policy.model_copy(deep=True)

    @staticmethod
    def legacy_config():
        """Return an empty legacy projection for this V3-only fixture."""
        return CategoryConfig()


def _sdk(version=1, field_model=_SdkModel, source_model=_SdkModel):
    """Build a minimal public classification SDK module for plugin tests."""

    return SimpleNamespace(
        MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION=version,
        ClassificationFieldDefinition=field_model,
        MediaSourceInfo=source_model,
    )


def _plugin():
    """Build the plugin surface needed by media-source and recognition tests."""

    plugin = object.__new__(LunaTVSource)
    plugin._logger = plugin_module.LOGGER
    plugin._enabled = True
    return plugin


def _result() -> CmsResult:
    """Return one LunaTV result carrying all declared extension facts."""

    return CmsResult(
        source_key="cms-demo",
        source_name="演示源",
        vod_id="42",
        title="分类示例",
        year="2026",
        media_type="movie",
        remark="",
        cms_type_name="剧情片",
        cms_class_names=("剧情", "科幻"),
    )


def _enable_protocol(monkeypatch):
    """Expose the minimal protocol V1 models to the guarded adapter."""

    monkeypatch.setattr(classification_module, "_classification_sdk", lambda: _sdk())


def test_get_media_source_declares_lunatv_fields_for_protocol_v1(monkeypatch):
    _enable_protocol(monkeypatch)

    declarations = _plugin().get_media_source()

    assert len(declarations) == 1
    source = declarations[0]
    assert source.name == "LunaTV"
    assert source.media_source == "lunatv"
    assert source.media_types == ["电影", "电视剧"]
    assert [field.id for field in source.classification_fields] == [
        CMS_SOURCE_KEY_FIELD,
        CMS_TYPE_NAME_FIELD,
        CMS_CLASS_NAMES_FIELD,
    ]
    assert [field.value_type for field in source.classification_fields] == [
        "string",
        "string",
        "string_list",
    ]
    assert all(
        field.media_types == ["电影", "电视剧"]
        and field.source_support == {"lunatv": "extension"}
        for field in source.classification_fields
    )


def test_public_host_sdk_accepts_declaration_when_available():
    source = classification_module.build_media_source_declaration()
    if source is None:
        pytest.skip("host does not expose classification protocol V1")

    source_id = str(getattr(source.media_source, "value", source.media_source))
    assert source_id == "lunatv"
    assert [field.id for field in source.classification_fields] == [
        CMS_SOURCE_KEY_FIELD,
        CMS_TYPE_NAME_FIELD,
        CMS_CLASS_NAMES_FIELD,
    ]


def test_media_source_declaration_failure_is_isolated(monkeypatch):
    def failed_declaration():
        raise ValueError("invalid declaration")

    monkeypatch.setattr(
        plugin_module, "build_media_source_declaration", failed_declaration
    )

    assert _plugin().get_media_source() == []


def test_guarded_protocol_import_rejects_missing_and_old_hosts(monkeypatch):
    def missing(_name):
        raise ImportError("classification SDK unavailable")

    monkeypatch.setattr(classification_module.importlib, "import_module", missing)
    assert classification_module.classification_protocol_available() is False

    monkeypatch.setattr(
        classification_module.importlib,
        "import_module",
        lambda _name: _sdk(version=0),
    )
    assert classification_module.classification_protocol_available() is False


def test_old_host_omits_source_declaration_and_classification_facts(monkeypatch):
    monkeypatch.setattr(classification_module, "_classification_sdk", lambda: None)
    monkeypatch.setattr(
        plugin_module, "_schemas", SimpleNamespace(MediaInfo=_HostMediaInfo)
    )

    plugin = _plugin()
    media = plugin._media_info(_result())

    assert plugin.get_media_source() == []
    assert not hasattr(media, "classification_facts")
    assert (media.media_source, media.media_id) == ("lunatv", "cms-demo:42")


def test_media_info_retries_without_facts_when_constructor_is_legacy(monkeypatch):
    _enable_protocol(monkeypatch)
    calls = []

    class LegacyMediaInfo:
        """Reject only the new fact field to emulate a partial old host."""

        def __init__(self, **values):
            calls.append(dict(values))
            if "classification_facts" in values:
                raise TypeError("unexpected classification_facts")
            self.__dict__.update(values)

    monkeypatch.setattr(
        plugin_module, "_schemas", SimpleNamespace(MediaInfo=LegacyMediaInfo)
    )

    media = _plugin()._media_info(_result())

    assert len(calls) == 2
    assert CMS_SOURCE_KEY_FIELD in calls[0]["classification_facts"]
    assert "classification_facts" not in calls[1]
    assert (media.media_source, media.media_id) == ("lunatv", "cms-demo:42")


def test_fact_extraction_failure_keeps_original_media_result(monkeypatch):
    _enable_protocol(monkeypatch)
    monkeypatch.setattr(
        plugin_module, "_schemas", SimpleNamespace(MediaInfo=_HostMediaInfo)
    )

    def failed_facts(_result):
        raise ValueError("invalid source fact")

    monkeypatch.setattr(plugin_module, "extract_classification_facts", failed_facts)
    result = _result()

    class Client:
        """Return the recognized row without any fallback title lookup."""

        @staticmethod
        def detail(source_key, vod_id):
            assert (source_key, vod_id) == ("cms-demo", "42")
            return result

    plugin = _plugin()
    plugin._client = lambda: Client()
    plugin._filter_currently_searchable_results = lambda rows, _client: rows
    plugin._prepare_result = lambda item: (item, {})

    media = plugin.recognize_media(
        media_source="lunatv", media_id="cms-demo:42"
    )

    assert not hasattr(media, "classification_facts")
    assert (media.media_source, media.media_id) == ("lunatv", "cms-demo:42")


def test_sync_and_async_recognition_return_same_facts_and_identity(monkeypatch):
    _enable_protocol(monkeypatch)
    monkeypatch.setattr(
        plugin_module, "_schemas", SimpleNamespace(MediaInfo=_HostMediaInfo)
    )
    detail_calls = []
    result = _result()

    class Client:
        """Return one fetched result and expose any unexpected extra lookup."""

        def detail(self, source_key, vod_id):
            detail_calls.append((source_key, vod_id))
            return result

        def search(self, *_args, **_kwargs):
            raise AssertionError("explicit identity must not trigger title search")

    plugin = _plugin()
    plugin._client = lambda: Client()
    plugin._filter_currently_searchable_results = lambda rows, _client: rows
    plugin._prepare_result = lambda item: (item, {})

    sync_media = plugin.recognize_media(
        media_source="lunatv", media_id="cms-demo:42"
    )
    async_media = asyncio.run(
        plugin.async_recognize_media(
            media_source="lunatv", media_id="cms-demo:42"
        )
    )

    expected_facts = {
        CMS_SOURCE_KEY_FIELD: "cms-demo",
        CMS_TYPE_NAME_FIELD: "剧情片",
        CMS_CLASS_NAMES_FIELD: ["剧情", "科幻"],
    }
    assert detail_calls == [("cms-demo", "42"), ("cms-demo", "42")]
    assert sync_media.classification_facts == expected_facts
    assert async_media.classification_facts == expected_facts
    assert (sync_media.media_source, sync_media.media_id) == (
        "lunatv",
        "cms-demo:42",
    )
    assert (async_media.media_source, async_media.media_id) == (
        "lunatv",
        "cms-demo:42",
    )


def test_real_cms_fixture_classifies_through_host_plugin_registry():
    """A real LunaTV CMS result should select a host category through declared facts."""
    declaration = classification_module.build_media_source_declaration()
    if declaration is None:
        pytest.skip("host does not expose classification protocol V1")
    registry = PluginClassificationRegistry(Mock())
    registry.replace("lunatvsource", [declaration])
    policy = ClassificationPolicy.model_validate(
        {
            "revision": 3,
            "categories": [
                {
                    "id": "movie.cms.drama",
                    "media_type": "电影",
                    "name": "CMS 剧情片",
                    "path": ["电影", "CMS", "剧情片"],
                },
                {
                    "id": "movie.fallback",
                    "media_type": "电影",
                    "name": "未分类",
                    "path": ["电影", "未分类"],
                },
            ],
            "rules": [
                {
                    "id": "rule.lunatv.cms.drama",
                    "name": "LunaTV 剧情片",
                    "kind": "category",
                    "media_types": ["电影"],
                    "sources": ["lunatv"],
                    "when": {
                        "all": [
                            {
                                "field": CMS_TYPE_NAME_FIELD,
                                "operator": "equals",
                                "value": "剧情片",
                            }
                        ]
                    },
                    "target": {"category_id": "movie.cms.drama"},
                }
            ],
            "fallbacks": {"电影": "movie.fallback"},
        }
    )
    service = ClassificationExecutionService(
        _ClassificationRuntime(policy),
        extension_facts_provider=registry.facts,
    )
    result = _result()
    media = MediaInfo(
        media_source=MediaSource("lunatv"),
        media_id=f"{result.source_key}:{result.vod_id}",
        type=MediaType.MOVIE,
        title=result.title,
        classification_facts=classification_module.extract_classification_facts(
            result
        ),
    )

    classified = service.finalize(media)

    assert classified.library_category == "电影/CMS/剧情片"
    assert classified.classification is not None
    assert classified.classification.effective.category_id == "movie.cms.drama"
    assert (classified.media_source, classified.media_id) == (
        MediaSource("lunatv"),
        "cms-demo:42",
    )
