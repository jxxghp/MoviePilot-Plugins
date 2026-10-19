"""MediaOverviewEnhancer 通知与每日汇总单测。

覆盖：通知开关与时间配置规整、按天统计、每日汇总通知文案与开关、
每日汇总定时服务的注册规则。不依赖宿主运行态，也不发起真实通知。
"""

from __future__ import annotations

import tempfile

from apscheduler.triggers.cron import CronTrigger

from app.plugins.mediaoverviewenhancer import MediaOverviewEnhancer
from app.plugins.mediaoverviewenhancer.enhancer import (
    OverviewEnhancer,
    normalize_config,
)


def make_engine(config=None, sent=None) -> OverviewEnhancer:
    """构造只依赖本地状态文件的引擎实例。"""
    calls = sent if sent is not None else []
    return OverviewEnhancer(
        config=config or {},
        data_dir=tempfile.mkdtemp(prefix="moe_notify_"),
        notify=lambda title, text: calls.append((title, text)),
    )


class TestNotifyConfig:
    """通知相关配置的规整与默认值。"""

    def test_daily_time_normalized(self):
        """每日通知时间规范为 HH:MM。"""
        assert normalize_config({"notify_daily_time": "9:5"})["notify_daily_time"] == "09:05"
        assert normalize_config({"notify_daily_time": "21:00"})["notify_daily_time"] == "21:00"

    def test_invalid_daily_time_falls_back(self):
        """非法时间回退默认 21:00。"""
        assert normalize_config({"notify_daily_time": "25:99"})["notify_daily_time"] == "21:00"
        assert normalize_config({"notify_daily_time": ""})["notify_daily_time"] == "21:00"

    def test_notify_switches_coerced(self):
        """通知开关规整为布尔值。"""
        config = normalize_config({"notify_failure": 0, "notify_daily": 1})
        assert config["notify_failure"] is False
        assert config["notify_daily"] is True


class TestDailySummary:
    """每日统计与汇总通知。"""

    def test_daily_stats_count_by_status(self):
        """按处理结果累计当天统计。"""
        engine = make_engine()
        engine._bump_daily("updated")
        engine._bump_daily("updated")
        engine._bump_daily("failed")
        engine._bump_daily("skipped")
        stats = engine.daily_stats()
        assert stats["updated"] == 2
        assert stats["failed"] == 1
        assert stats["skipped"] == 1

    def test_daily_summary_sends_when_enabled(self):
        """开启每日汇总时发送当天成功条数。"""
        sent = []
        engine = make_engine({"notify_daily": True, "notify_daily_time": "21:00"}, sent)
        engine._bump_daily("updated")
        result = engine.send_daily_summary()
        assert result["sent"] is True
        assert "成功更新 1 条" in result["message"]
        assert sent and sent[0][0].endswith("每日汇总")

    def test_daily_summary_skips_when_disabled(self):
        """关闭每日汇总时不发送通知。"""
        sent = []
        engine = make_engine({"notify_daily": False}, sent)
        assert engine.send_daily_summary()["sent"] is False
        assert sent == []


class TestDailyNotifyService:
    """每日汇总服务的注册规则。"""

    def test_service_registered_when_enabled(self):
        """开启每日汇总时注册 cron 服务并使用配置时间。"""
        plugin = object.__new__(MediaOverviewEnhancer)
        plugin._enabled = True
        plugin._config = normalize_config(
            {"enabled": True, "notify_daily": True, "notify_daily_time": "07:30"}
        )
        daily = [s for s in plugin.get_service() if s["id"].endswith("DailyNotify")]
        assert daily, plugin.get_service()
        trigger = daily[0]["trigger"]
        assert isinstance(trigger, CronTrigger)
        fields = {field.name: str(field) for field in trigger.fields}
        assert fields["hour"] == "7"
        assert fields["minute"] == "30"

    def test_service_absent_when_disabled(self):
        """关闭每日汇总且未开启定时补漏时不注册服务。"""
        plugin = object.__new__(MediaOverviewEnhancer)
        plugin._enabled = True
        plugin._config = normalize_config(
            {"enabled": True, "notify_daily": False, "schedule_hours": 0}
        )
        assert plugin.get_service() == []
