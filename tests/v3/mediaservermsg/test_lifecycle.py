"""V3 媒体库服务器通知插件的 Timer 生命周期测试。"""

from app.plugins.mediaservermsg import MediaServerMsg
from tests._timer_lifecycle import (
    assert_running_timer_is_retained,
    assert_waiting_timer_is_cancelled,
)


def test_running_timer_timeout_retains_owner_until_retry():
    """聚合回调已开始时必须报告超时并保留 Timer owner。"""
    assert_running_timer_is_retained(MediaServerMsg)


def test_waiting_timer_is_cancelled_and_host_hooks_are_idempotent():
    """尚未触发的聚合 Timer 应被取消等待，close/stop_service 可顺序调用。"""
    assert_waiting_timer_is_cancelled(MediaServerMsg)
