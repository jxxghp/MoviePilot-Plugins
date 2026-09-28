from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


@pytest.mark.parametrize('previous,current,expected', [
    (1.001 * 1024 ** 5, 1.002 * 1024 ** 5, True),
    (round(1.001 * 1024 ** 5), round(1.001 * 1024 ** 5), True),
    (0.977 * 1024 ** 5, 0.978 * 1024 ** 5, True),
    (1.001 * 1024 ** 5 + 100, 1.002 * 1024 ** 5 + 100, False),
    (1.001 * 1024 ** 5 + 100, 1.002 * 1024 ** 5, False),
    (10.001 * 1024 ** 4, 10.002 * 1024 ** 4, False),
    (0, 1.001 * 1024 ** 5, False),
    (1.002 * 1024 ** 5, 1.001 * 1024 ** 5, False),
    (float('inf'), float('inf'), False),
])
def test_precision_hint_checks_both_pb_readings_with_byte_tolerance(previous, current, expected):
    """只对两期疑似 PB 格点给出提示，不将精确 API、TB 流量或回退读数当作量化。"""
    fields = SiteStatistic._SiteStatistic__get_approximate_fields(
        [_site_data('站点A', current, 200, '2026-09-09')],
        [_site_data('站点A', previous, 100, '2026-09-08')],
    )
    assert fields == ({'站点A': {'upload'}} if expected else {})


@pytest.mark.parametrize('invalid', ['missing', 'same_day', 'current_error', 'previous_error'])
def test_precision_hint_requires_two_valid_snapshots(invalid):
    """缺少历史或刷新失败时不宣称已识别显示精度。"""
    current = _site_data('站点A', 1024 ** 5, 100, '2026-09-09')
    previous = _site_data('站点A', 1024 ** 5, 100, '2026-09-08')
    if invalid == 'same_day':
        previous.updated_day = current.updated_day
    elif invalid == 'current_error':
        current.err_msg = '刷新失败'
    elif invalid == 'previous_error':
        previous.err_msg = '刷新失败'
    assert SiteStatistic._SiteStatistic__get_approximate_fields(
        [current], [] if invalid == 'missing' else [previous],
    ) == {}


@pytest.mark.parametrize('field', ['upload', 'download'])
@pytest.mark.parametrize('jump', [0, 1, 3])
def test_notification_keeps_quantized_zero_and_marks_jumps_and_total(field, jump):
    """低精度零差值仍通知，跨一个或多个步长都标近似，另一方向流量保持精确。"""
    plugin = _plugin()
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    current = _site_data('站点A', 100, 100, today)
    previous = _site_data('站点A', 100, 100, yesterday)
    setattr(previous, field, round(1.001 * 1024 ** 5))
    setattr(current, field, round((1.001 + jump / 1000) * 1024 ** 5))
    with (
        patch.object(plugin, '_SiteStatistic__get_data', return_value=(today, [current], [previous])),
        patch.object(plugin, 'get_data', return_value={}),
        patch.object(plugin, 'save_data'),
        patch.object(plugin, 'post_message') as post_message,
    ):
        plugin.send_msg(_event())
    post_message.assert_called_once()
    text = post_message.call_args.kwargs['text']
    label = '上传' if field == 'upload' else '下载'
    other_label = '下载' if field == 'upload' else '上传'
    assert f'{label}量：≈ ' in text
    assert f'总{label}：≈ ' in text
    assert f'{other_label}量：≈ ' not in text
    assert '两期读数疑似经过 PB 舍入' in text
    assert ('实际增量未知' in text) == (jump == 0)
    assert '日均' not in text


def _display_data(upload, day):
    """构造仪表盘与明细页面共用的完整站点快照。"""
    data = _site_data('站点A', upload, 100, day)
    data.username = 'user'
    data.user_level = 'VIP'
    data.ratio = 1
    data.bonus = 1
    data.seeding = 1
    data.seeding_size = 100
    data.to_dict = lambda: {key: value for key, value in vars(data).items() if key != 'to_dict'}
    return data


def _components(elements):
    """递归遍历插件声明式组件树，检查用户可见文本和图表配置。"""
    for element in elements:
        yield element
        yield from _components(element.get('content', []))


@pytest.mark.parametrize('jump', [0, 1])
def test_dashboard_and_page_explain_quantized_values_even_without_pie_slice(jump):
    """仪表盘保留未变化站点说明，并标记图表、累计卡片及明细中的近似数据。"""
    plugin = _plugin()
    current = _display_data(round((1.001 + jump / 1000) * 1024 ** 5), '2026-09-09')
    previous = _display_data(round(1.001 * 1024 ** 5), '2026-09-08')
    with patch.object(plugin, '_SiteStatistic__get_data', return_value=('2026-09-09', [current], [previous])):
        page = list(_components(plugin.get_page()))
    texts = [element.get('text', '') for element in page]
    assert any('站点A 上传（2026-09-08 → 2026-09-09）：≈ ' in str(text) for text in texts)
    assert any(element['component'] == 'td' and str(element.get('text', '')).startswith('≈ ')
               for element in page)
    chart = next(element for element in page if element['component'] == 'VApexChart')
    assert '共 ≈ ' in chart['props']['options']['title']['text']
    assert chart['props']['options']['labels'] == (['≈ 站点A'] if jump else [])
    assert any('实际增量未知' in str(text) for text in texts) == (jump == 0)


def test_quantized_zero_notification_remains_deduplicated_within_day():
    """低精度零差值可通知，但相同内容的后续刷新仍只推送一次。"""
    plugin = _plugin()
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    stored = {}
    snapshot = (today, [_site_data('站点A', 1024 ** 5, 100, today)],
                [_site_data('站点A', 1024 ** 5, 100, yesterday)])
    with (
        patch.object(plugin, '_SiteStatistic__get_data', return_value=snapshot),
        patch.object(plugin, 'get_data', side_effect=stored.get),
        patch.object(plugin, 'save_data', side_effect=stored.__setitem__),
        patch.object(plugin, 'post_message') as post_message,
    ):
        plugin.send_msg(_event())
        plugin.send_msg(_event())
    post_message.assert_called_once()


@pytest.mark.parametrize('previous', [None, 1024 ** 5 + 100])
def test_unchanged_exact_api_or_missing_baseline_does_not_send_increment(previous):
    """精确 API 的零差值与无历史站点继续跳过增量通知。"""
    plugin = _plugin()
    snapshot = ('2026-09-09', [_site_data('站点A', 1024 ** 5 + 100, 100, '2026-09-09')],
                [] if previous is None else [_site_data('站点A', previous, 100, '2026-09-08')])
    with (
        patch.object(plugin, '_SiteStatistic__get_data', return_value=snapshot),
        patch.object(plugin, 'post_message') as post_message,
    ):
        plugin.send_msg(_event())
    post_message.assert_not_called()


def test_cumulative_notification_marks_pb_reading_without_changing_total():
    """累计模式只增加近似标记，仍显示原累计量，不将其替换成两期差值。"""
    plugin = _plugin()
    plugin._notify_type = 'all'
    snapshot = ('2026-09-09', [_site_data('站点A', 1024 ** 5, 100, '2026-09-09')],
                [_site_data('站点A', 1024 ** 5, 100, '2026-09-08')])
    with (
        patch.object(plugin, '_SiteStatistic__get_data', return_value=snapshot),
        patch.object(plugin, 'get_data', return_value={}),
        patch.object(plugin, 'save_data'),
        patch.object(plugin, 'post_message') as post_message,
    ):
        plugin.send_msg(_event())
    text = post_message.call_args.kwargs['text']
    assert '上传量：≈ 1.00PB' in text
    assert '总上传：≈ 1.00PB' in text
    assert '实际增量未知' not in text
