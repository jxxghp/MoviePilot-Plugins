from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.plugins.sitestatistic import SiteStatistic


def _plugin() -> SiteStatistic:
    """构造站点数据统计插件，并隔离宿主 Chain 初始化。"""
    with patch("app.plugins.PluginChian"):
        plugin = SiteStatistic()
    plugin._notify_type = "inc"
    return plugin


def _site_data(name: str, upload: int, download: int, updated_day: str) -> SimpleNamespace:
    """构造通知计算所需的最小站点数据对象。"""
    return SimpleNamespace(
        name=name,
        upload=upload,
        download=download,
        updated_day=updated_day,
    )


def _event() -> SimpleNamespace:
    """构造表示全量站点刷新完成的事件。"""
    return SimpleNamespace(event_data={"site_id": "*"})


def test_send_msg_skips_only_identical_snapshot_and_keeps_later_updates():
    """凌晨部分刷新后，后续定时刷新有新数据应继续推送，相同快照仍只推送一次。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    previous = [
        _site_data("站点A", 100, 50, yesterday),
        _site_data("站点B", 100, 50, yesterday),
    ]
    snapshots = [
        (
            today,
            [_site_data("站点A", 200, 100, today)],
            previous[:1],
        ),
        (
            today,
            [
                _site_data("站点A", 220, 110, today),
                _site_data("站点B", 180, 90, today),
            ],
            previous,
        ),
        (
            today,
            [
                _site_data("站点A", 220, 110, today),
                _site_data("站点B", 180, 90, today),
            ],
            previous,
        ),
    ]
    plugin = _plugin()
    stored_data = {}

    def get_data(key):
        """返回测试中的持久化通知状态。"""
        return stored_data.get(key)

    def save_data(key, value):
        """保存测试中的持久化通知状态。"""
        stored_data[key] = value

    with (
        patch.object(plugin, "get_data", side_effect=get_data),
        patch.object(plugin, "save_data", side_effect=save_data),
        patch.object(plugin, "post_message") as post_message,
        patch.object(plugin, "_SiteStatistic__get_data", side_effect=snapshots),
    ):
        plugin.send_msg(_event())
        plugin.send_msg(_event())
        plugin.send_msg(_event())

    assert post_message.call_count == 2
    first_text = post_message.call_args_list[0].kwargs["text"]
    second_text = post_message.call_args_list[1].kwargs["text"]
    assert "站点A" in first_text
    assert "站点B" not in first_text
    assert "站点A" in second_text
    assert "站点B" in second_text
    assert stored_data["last_notify"]["fingerprint"]


def test_send_msg_migrates_legacy_daily_marker():
    """升级自 v1.9.2 的旧日期标记不应阻止首个内容指纹通知。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    plugin = _plugin()
    stored_data = {"last_notify": {"date": today, "type": "inc"}}
    snapshot = (
        today,
        [_site_data("站点A", 200, 100, today)],
        [_site_data("站点A", 100, 50, yesterday)],
    )

    def get_data(key):
        """返回测试中的旧版持久化通知状态。"""
        return stored_data.get(key)

    def save_data(key, value):
        """保存升级后的通知指纹状态。"""
        stored_data[key] = value

    with (
        patch.object(plugin, "get_data", side_effect=get_data),
        patch.object(plugin, "save_data", side_effect=save_data),
        patch.object(plugin, "post_message") as post_message,
        patch.object(plugin, "_SiteStatistic__get_data", return_value=snapshot),
    ):
        plugin.send_msg(_event())

    post_message.assert_called_once()
    assert stored_data["last_notify"]["fingerprint"]


def test_format_filesize_supports_large_float_without_scientific_notation():
    """大容量浮点流量应显示 PB 单位，而不是把科学计数法当作文本返回。"""
    large_upload = 1.2621812704607864e19

    formatted = SiteStatistic._SiteStatistic__format_filesize(large_upload)

    assert formatted == "11210.42PB"
    assert "e+" not in formatted
    assert SiteStatistic._SiteStatistic__format_filesize(1024 ** 3) == "1.0G"


def test_get_data_labels_mixed_dates_and_caches_previous_snapshots():
    """各站点日期不一致时应明确标注，并按日期复用前一天整批查询结果。"""
    latest_data = [
        SimpleNamespace(
            domain="a.example",
            name="站点A",
            upload=300,
            updated_day="2026-09-01",
        ),
        SimpleNamespace(
            domain="b.example",
            name="站点B",
            upload=200,
            updated_day="2026-08-31",
        ),
        SimpleNamespace(
            domain="c.example",
            name="站点C",
            upload=100,
            updated_day="2026-08-31",
        ),
    ]
    previous_by_date = {
        "2026-08-31": [SimpleNamespace(name="站点A", err_msg="")],
        "2026-08-30": [
            SimpleNamespace(name="站点B", err_msg=""),
            SimpleNamespace(name="站点C", err_msg=""),
        ],
    }

    with patch("app.plugins.sitestatistic.SiteOper") as site_oper_class:
        site_oper = site_oper_class.return_value
        site_oper.get_userdata_latest.return_value = latest_data
        site_oper.list_active.return_value = [
            SimpleNamespace(domain="a.example"),
            SimpleNamespace(domain="b.example"),
            SimpleNamespace(domain="c.example"),
        ]
        site_oper.get_userdata_by_date.side_effect = previous_by_date.__getitem__

        latest_day, latest, previous = SiteStatistic._SiteStatistic__get_data()

    assert latest_day == "各站点最近更新日"
    assert [site.name for site in latest] == ["站点A", "站点B", "站点C"]
    assert [site.name for site in previous] == ["站点A", "站点B", "站点C"]
    assert site_oper_class.call_count == 1
    assert site_oper.get_userdata_by_date.call_count == 2
    assert [call.args[0] for call in site_oper.get_userdata_by_date.call_args_list] == [
        "2026-08-31",
        "2026-08-30",
    ]
