"""验证 V3 插件存量历史的统一媒体身份迁移。"""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest
from app.schemas.types import MediaSource
from app.plugins.doubanrank import DoubanRank
from app.plugins.doubansync import DoubanSync
from app.plugins.episodegroupmeta import EpisodeGroupMeta
from app.plugins.historytov2 import HistoryToV2
from app.plugins.maoyanrank import MaoyanRank
from app.plugins.neodbsync import NeoDBSync
from app.plugins.rsssubscribe import RssSubscribe


PLUGIN_CASES = (
    (DoubanSync, {"doubanid": "129"}, MediaSource.Douban, {"doubanid", "tmdbid"}),
    (DoubanRank, {"doubanid": "129"}, MediaSource.Douban, {"doubanid", "tmdbid"}),
    (MaoyanRank, {"tmdbid": "129"}, MediaSource.TMDB, {"tmdbid"}),
    (RssSubscribe, {"tmdbid": "129"}, MediaSource.TMDB, {"tmdbid"}),
    (NeoDBSync, {"tmdbid": "129", "neodb_id": "legacy"}, MediaSource.TMDB, {"tmdbid", "neodb_id"}),
)

INVALID_PAIRS = (
    {"media_source": MediaSource.TMDB.value, "media_id": "0"},
    {"media_source": MediaSource.TMDB.value, "media_id": "   "},
    {"media_source": "Plugin Source:Invalid", "media_id": "999"},
)


def _run_migration(plugin_class, history: list[dict], monkeypatch) -> list[tuple[str, list[dict]]]:
    """以隔离的插件数据读写替身执行指定插件的私有迁移入口。"""
    plugin = object.__new__(plugin_class)
    saved = []
    monkeypatch.setattr(plugin, "get_data", lambda key: history)
    monkeypatch.setattr(plugin, "save_data", lambda key, value: saved.append((key, deepcopy(value))))
    migrate = getattr(plugin, f"_{plugin_class.__name__}__migrate_history_identity")
    migrate()
    return saved


@pytest.mark.parametrize("plugin_class,legacy,expected_source,legacy_keys", PLUGIN_CASES)
@pytest.mark.parametrize("invalid_pair", INVALID_PAIRS)
def test_invalid_pair_falls_back_before_removing_legacy_fields(
        plugin_class,
        legacy: dict,
        expected_source: MediaSource,
        legacy_keys: set[str],
        invalid_pair: dict,
        monkeypatch,
) -> None:
    """零值、空白或未知来源 pair 必须先由合法旧字段回填，再删除旧字段。"""
    history = [{"title": "Movie", **legacy, **invalid_pair}]

    saved = _run_migration(plugin_class, history, monkeypatch)

    assert history[0]["media_source"] == expected_source.value
    assert history[0]["media_id"] == "129"
    assert not legacy_keys.intersection(history[0])
    assert saved == [("history", history)]


@pytest.mark.parametrize("plugin_class,legacy,expected_source,legacy_keys", PLUGIN_CASES)
def test_invalid_identity_preserves_legacy_fields_when_no_fallback_exists(
        plugin_class,
        legacy: dict,
        expected_source: MediaSource,
        legacy_keys: set[str],
        monkeypatch,
) -> None:
    """现有 pair 与旧字段均无效时不得删列或保存半迁移记录。"""
    del expected_source, legacy_keys
    invalid_legacy = {key: "0" for key in legacy}
    history = [{
        "title": "Movie",
        "media_source": "unknown",
        "media_id": "0",
        **invalid_legacy,
    }]
    original = deepcopy(history)

    saved = _run_migration(plugin_class, history, monkeypatch)

    assert history == original
    assert saved == []


@pytest.mark.parametrize("plugin_class", (DoubanSync, DoubanRank))
def test_invalid_douban_fallback_continues_to_valid_tmdb(
        plugin_class,
        monkeypatch,
) -> None:
    """首个旧字段为零值时应继续寻找后续合法来源，而不是保留无效身份。"""
    history = [{
        "title": "Movie",
        "media_source": MediaSource.Douban.value,
        "media_id": "0",
        "doubanid": "0",
        "tmdbid": "456",
    }]

    saved = _run_migration(plugin_class, history, monkeypatch)

    assert history == [{
        "title": "Movie",
        "media_source": MediaSource.TMDB.value,
        "media_id": "456",
    }]
    assert saved == [("history", history)]


@pytest.mark.parametrize(
    "item,expected",
    (
        (
            {"media_source": MediaSource.TMDB.value, "media_id": "0", "doubanid": "129"},
            (MediaSource.Douban, "129"),
        ),
        (
            {"media_source": MediaSource.TMDB.value, "media_id": "   ", "imdbid": "tt123"},
            (MediaSource.IMDb, "tt123"),
        ),
        (
            {"media_source": "Plugin Source:Invalid", "media_id": "999", "tvdbid": "456"},
            (MediaSource.TVDB, "456"),
        ),
        (
            {"media_source": MediaSource.TMDB.value, "tmdbid": "0"},
            (None, None),
        ),
    ),
)
def test_history_to_v3_rejects_invalid_identity_before_legacy_fallback(
        item: dict,
        expected: tuple,
) -> None:
    """V1 历史迁移不得把零值、空白、未知来源或半对身份写入 V3。"""
    resolver = HistoryToV2._HistoryToV2__resolve_history_identity

    assert resolver(item) == expected


@pytest.mark.parametrize(
    "key,mediainfo_dict",
    (
        ("0", {"media_source": MediaSource.TMDB.value, "media_id": "0"}),
        (" ", {"media_source": MediaSource.TMDB.value, "media_id": "   "}),
        ("unknown:123", {"media_source": "unknown", "media_id": "123"}),
        ("tmdb:0", {"media_source": MediaSource.TMDB.value}),
    ),
)
def test_episode_group_invalid_identity_never_saves_or_deletes_key(
        key: str,
        mediainfo_dict: dict,
        monkeypatch,
) -> None:
    """剧集组迁移无法构造合法新 key 时必须保留原记录且不得保存空 key。"""
    plugin = object.__new__(EpisodeGroupMeta)
    plugin_data = type("PluginDataStub", (), {
        "key": key,
        "value": {"mediainfo_dict": mediainfo_dict},
    })()
    saved = []
    deleted = []
    monkeypatch.setattr(plugin, "get_data", lambda: [plugin_data])
    monkeypatch.setattr(plugin, "save_data", lambda data_key, value: saved.append((data_key, value)))
    monkeypatch.setattr(plugin, "del_data", lambda data_key: deleted.append(data_key))
    monkeypatch.setattr(plugin, "log_warn", lambda message: None)

    plugin._EpisodeGroupMeta__migrate_media_identity_data()

    assert saved == []
    assert deleted == []


def test_episode_group_valid_legacy_key_migrates_to_prefixed_key(monkeypatch) -> None:
    """合法裸 TMDB key 仍应迁移，并且仅在新记录保存后删除旧 key。"""
    plugin = object.__new__(EpisodeGroupMeta)
    plugin_data = type("PluginDataStub", (), {
        "key": "123",
        "value": {"mediainfo_dict": {"media_source": MediaSource.TMDB.value, "media_id": "0"}},
    })()
    operations = []
    monkeypatch.setattr(plugin, "get_data", lambda: [plugin_data])
    monkeypatch.setattr(plugin, "save_data", lambda data_key, value: operations.append(("save", data_key, value)))
    monkeypatch.setattr(plugin, "del_data", lambda data_key: operations.append(("delete", data_key)))
    monkeypatch.setattr(plugin, "log_warn", lambda message: None)

    plugin._EpisodeGroupMeta__migrate_media_identity_data()

    assert operations[0][0:2] == ("save", "tmdb:123")
    assert operations[0][2]["mediainfo_dict"]["media_id"] == "123"
    assert operations[1] == ("delete", "123")


@pytest.mark.parametrize(
    "plugin_path",
    (
        Path(__file__).parents[2] / "plugins.v3/doubanrank/__init__.py",
        Path(__file__).parents[2] / "plugins.v3/doubansync/__init__.py",
    ),
)
def test_douban_plugins_use_unified_identity_conversion(plugin_path: Path) -> None:
    """豆瓣 V3 插件必须经统一 pair 转换到 TMDB，不得恢复来源专有公共入口。"""
    source = plugin_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(plugin_path))
    legacy_calls = []
    conversion_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "get_tmdbinfo_by_doubanid":
            legacy_calls.append(node.lineno)
        elif node.func.attr == "convert_media_identity":
            conversion_calls.append(node)

    assert not legacy_calls
    assert conversion_calls
    for call in conversion_calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert ast.unparse(keywords["target_source"]) == "MediaSource.TMDB"
        assert ast.unparse(keywords["media_source"]) == "MediaSource.Douban"
        assert ast.unparse(keywords["media_id"]) == "douban_id"
        assert ast.unparse(keywords["mtype"]) == "meta.type"
