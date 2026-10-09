"""站点刷流 V3 插件的站点分享率控制回归测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


def _make_ratio_task() -> BrushTaskConfig:
    """构造一个启用站点分享率控制的测试任务。"""
    return BrushTaskConfig(
        {
            "id": "ratio-task",
            "name": "分享率测试",
            "site_id": 1,
            "downloader": "qb",
            "site_ratio_control": True,
            "site_ratio_target": 2,
        }
    )


def _evaluate_ratio(user_data: SimpleNamespace):
    """使用最小插件实例评估一条站点用户统计。"""
    plugin = object.__new__(BrushFlow)
    site = SimpleNamespace(domain="example.com")
    with patch("app.plugins.brushflow.SiteOper") as site_oper:
        site_oper.return_value.get.return_value = site
        site_oper.return_value.get_userdata_latest.return_value = [user_data]
        return plugin._evaluate_site_ratio_control(_make_ratio_task(), site=site)


def test_empty_zero_ratio_waits_for_site_data():
    """分享率和上传下载量同时为零时应等待数据，不得启动刷流。"""
    passed, reason, status = _evaluate_ratio(
        SimpleNamespace(
            domain="example.com",
            ratio=0,
            upload=0,
            download=0,
            updated_day="2026-09-15",
            updated_time="10:00:00",
        )
    )

    assert passed is False
    assert "等待数据更新" in reason
    assert status["available"] is False
    assert status["current"] is None


def test_known_zero_ratio_remains_a_valid_low_ratio():
    """已知存在下载量的零分享率是真实低分享率，应允许继续刷流。"""
    passed, reason, status = _evaluate_ratio(
        SimpleNamespace(
            domain="example.com",
            ratio=0,
            upload=0,
            download=100,
            updated_day="2026-09-15",
            updated_time="10:00:00",
        )
    )

    assert passed is True
    assert reason is None
    assert status["available"] is True
    assert status["current"] == 0


def test_unlimited_ratio_zero_remains_blocked():
    """上传量存在且无下载量的零比率仍应识别为无限分享率并停止新增。"""
    passed, reason, status = _evaluate_ratio(
        SimpleNamespace(
            domain="example.com",
            ratio=0,
            upload=100,
            download=0,
            updated_day="2026-09-15",
            updated_time="10:00:00",
        )
    )

    assert passed is False
    assert "已达到目标" in reason
    assert status["available"] is True
    assert status["unlimited"] is True
