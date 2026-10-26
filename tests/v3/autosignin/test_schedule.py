"""空执行周期的随机签到计划和宿主服务 ID 回归。"""

from datetime import datetime
from unittest.mock import Mock

import pytz

from app.plugins.autosignin import AutoSignIn


def _plugin(monkeypatch):
    """构造使用内存持久化存储的启用插件。"""
    plugin = object.__new__(AutoSignIn)
    plugin._enabled = True
    plugin._cron = ""
    storage = {}
    monkeypatch.setattr(plugin, "get_data", lambda key: storage.get(key))
    monkeypatch.setattr(plugin, "save_data", lambda key, value: storage.__setitem__(key, value))
    return plugin, storage


def _freeze_now(monkeypatch, value):
    """冻结插件使用的时钟，同时保留 datetime 构造能力。"""
    clock = Mock(wraps=datetime)
    clock.now.return_value = pytz.timezone("Asia/Shanghai").localize(value)
    monkeypatch.setattr("app.plugins.autosignin.datetime", clock)


def test_random_schedule_uses_unique_ids_and_persists_within_the_day(monkeypatch):
    """两次随机服务均保留，重复重载同一天不重新掷出时间。"""
    plugin, storage = _plugin(monkeypatch)
    _freeze_now(monkeypatch, datetime(2026, 10, 17, 8, 0))
    scheduler = Mock(return_value=[datetime(2026, 10, 17, 13, 5), datetime(2026, 10, 17, 20, 10)])
    monkeypatch.setattr("app.plugins.autosignin.TimerUtils.random_scheduler", scheduler)

    first = plugin.get_service()
    second = plugin.get_service()

    assert len(first) == 2
    assert all("|" not in service["id"] for service in first)
    assert [service["id"] for service in first] == [service["id"] for service in second]
    assert scheduler.call_count == 1
    assert storage["random_schedule"] == {
        "date": "2026-10-17",
        "times": [{"hour": 13, "minute": 5}, {"hour": 20, "minute": 10}],
    }


def test_random_schedule_regenerates_when_initial_times_are_all_past(monkeypatch):
    """较晚首次初始化时，重新生成计划以保留当天尚未到时的执行点。"""
    plugin, storage = _plugin(monkeypatch)
    _freeze_now(monkeypatch, datetime(2026, 10, 17, 17, 43))
    scheduler = Mock(side_effect=[
        [datetime(2026, 10, 17, 13, 0), datetime(2026, 10, 17, 17, 0)],
        [datetime(2026, 10, 17, 20, 0), datetime(2026, 10, 17, 22, 0)],
    ])
    monkeypatch.setattr("app.plugins.autosignin.TimerUtils.random_scheduler", scheduler)

    services = plugin.get_service()

    assert [service["kwargs"] for service in services] == [
        {"hour": 20, "minute": 0},
        {"hour": 22, "minute": 0},
    ]
    assert scheduler.call_count == 2
    assert scheduler.call_args_list[1].kwargs["begin_hour"] == 17
    assert storage["random_schedule"]["times"] == [{"hour": 20, "minute": 0}, {"hour": 22, "minute": 0}]
