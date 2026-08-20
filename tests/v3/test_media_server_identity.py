"""验证媒体服务器通知插件的统一媒体身份边界。"""

from __future__ import annotations

from types import SimpleNamespace

from app.plugins import mediaservermsg
from app.schemas.types import MediaSource
from app.plugins.mediaservermsg import MediaServerMsg


def _plugin() -> MediaServerMsg:
    """构造不启动服务的插件实例，用于隔离测试身份解析。"""
    return object.__new__(MediaServerMsg)


def test_event_identity_rejects_zero_blank_unknown_and_half_pairs() -> None:
    """Webhook 直接身份中的零值、空白、未知来源和半对均应视为无身份。"""
    plugin = _plugin()
    invalid_events = (
        SimpleNamespace(media_source=MediaSource.TMDB, media_id="0", item_path=None),
        SimpleNamespace(media_source=MediaSource.TMDB, media_id="   ", item_path=None),
        SimpleNamespace(media_source="Plugin Source:Invalid", media_id="123", item_path=None),
        SimpleNamespace(media_source=MediaSource.TMDB, media_id=None, item_path=None),
    )

    for event_info in invalid_events:
        assert plugin._resolve_event_media_identity(event_info) == (None, None)


def test_path_fallback_skips_zero_identity(monkeypatch) -> None:
    """路径元信息返回零值时不得把它当作有效回退身份。"""
    plugin = _plugin()
    monkeypatch.setattr(
        mediaservermsg,
        "MetaInfoPath",
        lambda path: SimpleNamespace(media_source=MediaSource.TMDB, media_id="0"),
    )
    event_info = SimpleNamespace(
        media_source=None,
        media_id=None,
        item_path="/media/Movie",
    )

    assert plugin._resolve_event_media_identity(event_info) == (None, None)


def test_media_server_lookup_skips_zero_identity(monkeypatch) -> None:
    """媒体服务器条目只返回零值身份时不得产生伪造聚合键。"""
    plugin = _plugin()
    service = SimpleNamespace(
        get_iteminfo=lambda item_id: SimpleNamespace(
            media_source=MediaSource.TMDB,
            media_id="0",
        )
    )
    monkeypatch.setattr(
        plugin,
        "service_info",
        lambda name: SimpleNamespace(instance=service),
    )
    event_info = SimpleNamespace(
        media_source=None,
        media_id=None,
        item_path=None,
        item_id="server-item",
        server_name="emby",
    )

    assert plugin._resolve_event_media_identity(event_info, lookup_item=True) == (None, None)


def test_event_identity_preserves_valid_pair() -> None:
    """合法 webhook pair 应保持固定来源枚举和原生 ID。"""
    plugin = _plugin()
    event_info = SimpleNamespace(
        media_source=MediaSource.IMDb,
        media_id="tt123",
        item_path=None,
    )

    assert plugin._resolve_event_media_identity(event_info) == (MediaSource.IMDb, "tt123")
