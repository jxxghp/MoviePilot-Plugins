"""日历插件的生产导入、宿主 API 和有界网络读取回归。"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from app.plugins.simplemoviecalendar import SimpleMovieCalendar, calendar
from app.sdk.plugin import _PluginBase
from tests.v3.simplemoviecalendar.test_calendar import sample


def test_network_fetch_uses_verified_bounded_host_stream(monkeypatch):
    """读取通过宿主传输完成，限制实际字节数并校验证书。"""
    import json

    response = Mock()
    response.iter_content.return_value = [json.dumps(sample()).encode()]

    @contextmanager
    def stream(*args, **kwargs):
        """以受控上下文替代实际 HTTP 连接。"""
        yield response

    request = Mock()
    request.get_stream.side_effect = stream
    factory = Mock(return_value=request)
    monkeypatch.setattr(calendar, "RequestUtils", factory)
    assert calendar.fetch_snapshot()["schema_version"] == 1
    assert factory.call_args.kwargs["verify"] is True
    assert factory.call_args.kwargs["timeout"] == 12
    response.raise_for_status.assert_called_once()
    monkeypatch.setattr(calendar, "MAX_BYTES", 8)
    response.iter_content.return_value = [b"0123456789"]
    with pytest.raises(ValueError, match="过大"):
        calendar.fetch_snapshot()


def test_plugin_exposes_real_host_media_and_enveloped_routes(monkeypatch):
    """启用实例用同一份缓存提供页面、探索和媒体识别。"""
    monkeypatch.setattr(_PluginBase, "__init__", lambda self: None)
    plugin = SimpleMovieCalendar()
    plugin._enabled = True
    snapshot = sample()
    plugin._cache = calendar.CalendarCache(
        loader=lambda: {"snapshot": snapshot, "fetched_at": 1}, save=lambda _: None)
    plugin.get_data = Mock(return_value=None)
    result = plugin.discover(group="all")
    assert result.success and len(result.data) == 3
    info = plugin.recognize_media(media_source=calendar.SOURCE, media_id="a")
    assert info.media_id == "a" and info.title == "多版本"
    assert plugin.get_page() and plugin.get_dashboard("upcoming")
    routes = plugin.get_api()
    assert all(route["auth"] == "bear" and route["response_model"] for route in routes)
    plugin.stop_service()
    assert plugin.discover(group="all").success is False
