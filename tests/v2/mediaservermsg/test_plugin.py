"""V2 媒体库服务器通知插件的Plex音乐消息测试。"""

from types import SimpleNamespace

from mediaservermsg import MediaServerMsg


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
