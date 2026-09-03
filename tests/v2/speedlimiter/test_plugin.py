"""V2 播放限速插件的 Jellyfin 多版本兼容测试。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.plugins import speedlimiter as speedlimiter_module
from app.plugins.speedlimiter import SpeedLimiter


def _timestamp(offset_seconds: int = 0) -> str:
    """生成相对当前时间的 Jellyfin UTC 时间字符串。"""
    value = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return value.isoformat().replace("+00:00", "Z")


def _plugin() -> SpeedLimiter:
    """创建隔离了可变类属性的插件实例。"""
    with patch("app.plugins.PluginChian"):
        plugin = SpeedLimiter()
    plugin._unlimited_ips = {"ipv4": "", "ipv6": ""}
    plugin._exclude_path = ""
    return plugin


def _legacy_session() -> dict:
    """构造 Jellyfin 10.8 风格的 PascalCase 播放会话。"""
    return {
        "IsActive": True,
        "RemoteEndPoint": "8.8.8.8",
        "LastPlaybackCheckIn": _timestamp(),
        "PlayState": {"IsPaused": False},
        "NowPlayingItem": {
            "MediaType": "Video",
            "Path": "/media/movie.mkv",
            "MediaStreams": [
                {"Type": "Video", "BitRate": 8_000_000},
                {"Type": "Audio", "BitRate": 192_000},
                {"Type": "Subtitle", "BitRate": 99_000},
            ],
        },
    }


def _camel_case_session(with_bitrate: bool = True) -> dict:
    """构造 camelCase、枚举媒体类型及媒体源比特率的兼容会话。"""
    media_source = {"id": "source-1"}
    if with_bitrate:
        media_source["bitrate"] = 6_000_000
    return {
        "isActive": True,
        "remoteEndpoint": "8.8.4.4:8096",
        "lastPlaybackCheckIn": _timestamp(),
        "playState": {"isPaused": False, "mediaSourceId": "source-1"},
        "nowPlayingItem": {
            "mediaType": 1,
            "path": None,
            "mediaSources": [media_source],
        },
    }


def test_legacy_session_sums_audio_and_video_streams():
    """Jellyfin 10.8 风格会话应汇总音视频流并忽略字幕流。"""
    bit_rate = _plugin()._SpeedLimiter__jellyfin_session_bitrate(_legacy_session())

    assert bit_rate == 8_192_000


def test_camel_case_session_supports_enum_media_type_and_endpoint_port():
    """兼容字段应识别枚举视频类型、camelCase 和带端口的远端地址。"""
    plugin = _plugin()
    plugin._exclude_path = "/cloud"

    bit_rate = plugin._SpeedLimiter__jellyfin_session_bitrate(_camel_case_session())

    assert bit_rate == 6_000_000


def test_stale_inactive_and_paused_sessions_are_ignored():
    """停止后残留、服务端失活和暂停会话均不应继续触发限速。"""
    plugin = _plugin()
    stale = _legacy_session()
    stale["LastPlaybackCheckIn"] = _timestamp(-(plugin._jellyfin_session_timeout + 1))
    inactive = _legacy_session()
    inactive["IsActive"] = False
    paused = deepcopy(_camel_case_session())
    paused["playState"]["isPaused"] = True

    assert plugin._SpeedLimiter__jellyfin_session_bitrate(stale) is None
    assert plugin._SpeedLimiter__jellyfin_session_bitrate(inactive) is None
    assert plugin._SpeedLimiter__jellyfin_session_bitrate(paused) is None


def test_missing_bitrate_still_represents_active_playback():
    """字段缺失时返回零比特率而非空，供固定限速继续按播放状态触发。"""
    bit_rate = _plugin()._SpeedLimiter__jellyfin_session_bitrate(_camel_case_session(with_bitrate=False))

    assert bit_rate == 0


def test_polling_triggers_fixed_limit_without_webhook_or_bitrate(monkeypatch):
    """定时轮询应独立于 Webhook，并在缺少比特率时仍触发固定播放限速。"""
    requested_urls = []

    class JellyfinApi:
        """记录会话请求并返回兼容包装结构。"""

        @staticmethod
        def get_data(url: str):
            """返回不含比特率的活跃外网会话。"""
            requested_urls.append(url)
            return SimpleNamespace(status_code=200, json=lambda: {"items": [_camel_case_session(False)]})

    jellyfin_api = JellyfinApi()
    media_server = SimpleNamespace(type="jellyfin", instance=jellyfin_api)
    media_server_helper = SimpleNamespace(get_services=lambda: {"jellyfin": media_server})
    plugin = _plugin()
    plugin._enabled = True
    plugin._auto_limit = False
    plugin._play_up_speed = 512
    plugin._play_down_speed = 1024
    captured = []

    monkeypatch.setattr(speedlimiter_module, "MediaServerHelper", lambda: media_server_helper)
    monkeypatch.setattr(SpeedLimiter, "service_infos", property(lambda _self: {"qb": object()}))
    monkeypatch.setattr(
        plugin,
        "_SpeedLimiter__set_limiter",
        lambda **kwargs: captured.append(kwargs),
    )

    plugin.check_playing_sessions()

    assert "activeWithinSeconds=120" in requested_urls[0]
    assert captured == [{"limit_type": "播放", "upload_limit": 512, "download_limit": 1024}]
