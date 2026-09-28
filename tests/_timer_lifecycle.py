"""媒体服务器消息插件跨代共享的 Timer 生命周期断言。"""

from threading import Event
from types import SimpleNamespace


def _plugin_with_lifecycle(plugin_class):
    """绕过运行时依赖，建立只包含聚合生命周期状态的插件实例。"""
    plugin = object.__new__(plugin_class)
    plugin._initialize_lifecycle_state()
    plugin._aggregate_time = 0
    plugin._get_tmdb_info = SimpleNamespace(cache_clear=lambda: None)
    with plugin._lifecycle_condition:
        plugin._accepting_events = True
    return plugin


def assert_running_timer_is_retained(plugin_class) -> None:
    """验证已进入回调的 Timer 超时后仍被持有，释放后可重试收敛。"""
    plugin = _plugin_with_lifecycle(plugin_class)
    plugin.SHUTDOWN_TIMEOUT = 0.02
    entered = Event()
    release = Event()
    calls = []

    def blocking_send(_series_id):
        """模拟已经进入通知发送且暂时无法结束的 Timer 回调。"""
        calls.append("send")
        entered.set()
        release.wait(timeout=2)

    plugin._send_aggregated_message_impl = blocking_send
    plugin._aggregate_tv_episodes("series", object())
    assert entered.wait(timeout=1)

    timer = next(iter(plugin._owned_timers))
    assert timer.is_alive()
    assert plugin.stop_service() is False
    assert timer in plugin._owned_timers
    assert timer.is_alive()

    release.set()
    timer.join(timeout=1)
    assert not timer.is_alive()
    assert plugin.stop_service() is True
    assert plugin._owned_timers == set()

    plugin._aggregate_tv_episodes("late", object())
    plugin._send_aggregated_message("late")
    assert calls == ["send"]
    assert plugin._aggregate_timers == {}
    assert plugin._pending_messages == {}
    assert plugin.close() is True


def assert_waiting_timer_is_cancelled(plugin_class) -> None:
    """验证尚未开始的 Timer 会被 cancel+join，且双宿主钩子保持幂等。"""
    plugin = _plugin_with_lifecycle(plugin_class)
    plugin._aggregate_time = 60
    calls = []
    plugin._send_aggregated_message_impl = lambda _series_id: calls.append("send")

    plugin._aggregate_tv_episodes("series", object())
    timer = next(iter(plugin._owned_timers))
    assert timer.is_alive()

    assert plugin.close() is True
    assert not timer.is_alive()
    assert plugin.stop_service() is True
    assert calls == []
    assert plugin._aggregate_timers == {}
    assert plugin._pending_messages == {}
