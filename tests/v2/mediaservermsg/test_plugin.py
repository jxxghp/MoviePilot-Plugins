"""V2 媒体库服务器通知插件的Plex音乐消息测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.plugins.mediaservermsg import MediaServerMsg
from tests._timer_lifecycle import (
    assert_running_timer_is_retained,
    assert_waiting_timer_is_cancelled,
)


def _event(*, channel="plex", metadata=None, item_type="SHOW", item_name="我爱洗澡 (None)"):
    """构造最小Webhook事件信息。"""
    return SimpleNamespace(
        channel=channel,
        item_type=item_type,
        item_name=item_name,
        json_object={"Metadata": metadata or {}},
    )


def test_plex_track_uses_music_title_and_artist():
    """Plex曲目即使被核心解析成SHOW，也应显示为音乐并带歌手。"""
    event_info = _event(
        metadata={
            "type": "track",
            "title": "我爱洗澡",
            "grandparentTitle": "范晓萱",
            "parentTitle": "小魔女的魔法书",
        }
    )

    title = MediaServerMsg._build_message_title(event_info, "开始播放")

    assert title == "开始播放音乐 我爱洗澡 - 范晓萱"


def test_plex_track_omits_missing_artist_without_none_text():
    """Plex曲目缺少歌手时仍显示歌曲名，标题中不应出现None。"""
    event_info = _event(
        metadata={
            "type": "track",
            "title": "纯音乐",
            "grandparentTitle": None,
        }
    )

    title = MediaServerMsg._build_message_title(event_info, "停止播放")

    assert title == "停止播放音乐 纯音乐"
    assert "None" not in title


def test_plex_episode_keeps_existing_series_title():
    """Plex非音乐SHOW事件必须继续使用原有剧集文案。"""
    event_info = _event(
        metadata={"type": "episode", "title": "第一集"},
        item_name="测试剧 S1E1 第一集",
    )

    title = MediaServerMsg._build_message_title(event_info, "开始播放")

    assert title == "开始播放剧集 测试剧 S1E1 第一集"


def test_non_plex_track_does_not_change_existing_classification():
    """只针对Plex原始Webhook识别曲目，其他渠道保持现有分类逻辑。"""
    event_info = _event(
        channel="emby",
        metadata={"type": "track", "title": "歌曲"},
        item_name="现有媒体项",
    )

    title = MediaServerMsg._build_message_title(event_info, "开始播放")

    assert title == "开始播放剧集 现有媒体项"


def test_send_reads_item_type_for_image_processing():
    """普通Webhook消息在图片处理阶段也应能访问媒体类型。"""
    plugin = object.__new__(MediaServerMsg)
    plugin._initialize_lifecycle_state()
    plugin._accepting_events = True
    plugin._enabled = True
    plugin._types = ["playback.start"]
    plugin._mediaservers = ["测试媒体库"]
    plugin._aggregate_enabled = False
    plugin._add_play_link = False
    plugin._webhook_msg_keys = {}
    plugin.service_infos = lambda type_filter=None: {"测试媒体库": object()}
    plugin.service_info = lambda name: object()
    plugin.post_message = MagicMock()
    plugin._MediaServerMsg__get_elements = MagicMock(return_value=[])
    plugin._MediaServerMsg__add_element = MagicMock()
    plugin._MediaServerMsg__remove_element = MagicMock()

    event = SimpleNamespace(
        event_data=SimpleNamespace(
            event="playback.start",
            item_id="movie-1",
            item_type="MOV",
            item_name="测试电影",
            channel="plex",
        )
    )

    plugin.send(event)

    plugin.post_message.assert_called_once()


def test_running_timer_timeout_retains_owner_until_retry():
    """聚合回调已开始时必须报告超时并保留 Timer owner。"""
    assert_running_timer_is_retained(MediaServerMsg)


def test_waiting_timer_is_cancelled_and_host_hooks_are_idempotent():
    """尚未触发的聚合 Timer 应被取消等待，close/stop_service 可顺序调用。"""
    assert_waiting_timer_is_cancelled(MediaServerMsg)
