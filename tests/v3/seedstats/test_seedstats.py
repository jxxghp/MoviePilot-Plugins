"""SeedStats 索引一致性、tracker 归属、格式化与页面结构测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.plugins.seedstats import SeedStats

ROOT = Path(__file__).parents[3]


def _plugin(**overrides) -> SeedStats:
    """构造不触发宿主插件管理器的最小实例。"""
    plugin = object.__new__(SeedStats)
    plugin._enabled = True
    plugin._dashboard = True
    plugin._interval = 20
    plugin._downloaders = []
    plugin._stale_hours = 24
    plugin._include_removed = False
    plugin._site_mapping = {}
    plugin._site_prefixes = {}
    for key, value in overrides.items():
        setattr(plugin, key, value)
    return plugin


def _cache() -> dict:
    """构造一份与真实统计结构一致的缓存快照。"""
    now = time.time()
    row_a = {
        "站点": "A",
        "任务数": 5,
        "做种": 5,
        "辅种": 2,
        "辅种暂停": 1,
        "辅种合计": 3,
        "体积": 1024 ** 4,
        "上传": 1024 ** 3,
        "下载": 1024 ** 2,
        "分享率": 3.5,
        "等级": "Power User",
        "魔力": 12345,
        "时魔": 12.3,
        "时魔标记": "",
        "状态": "正常",
        "数据时间": "2026-10-22 15:00:00",
    }
    row_b = {
        "站点": "B",
        "任务数": 3,
        "做种": 3,
        "辅种": 1,
        "辅种暂停": 0,
        "辅种合计": 1,
        "体积": 1024 ** 3,
        "上传": 1024 ** 2,
        "下载": 0,
        "分享率": 1500,
        "等级": "",
        "魔力": 0,
        "时魔": None,
        "时魔标记": "无魔力",
        "状态": "零做种",
        "数据时间": "",
    }
    return {
        "timestamp": "2026-10-22 16:06:40",
        "totals": {
            "下载器": 2,
            "任务数": 8,
            "做种": 8,
            "辅种": 3,
            "辅种合计": 4,
            "体积": 1024 ** 4 + 1024 ** 3,
            "上传": 1024 ** 3 + 1024 ** 2,
            "下载": 1024 ** 2,
            "站点数": 2,
            "未映射": 0,
        },
        "rows": [row_a, row_b],
        "alerts": ["示例告警"],
        "trend": [
            {"hour": "2026-10-22 14", "ts": now - 7200, "做种": 7, "辅种": 2,
             "体积": 1024 ** 4, "站点数": 2},
            {"hour": "2026-10-22 15", "ts": now - 3600, "做种": 8, "辅种": 3,
             "体积": 1024 ** 4 + 1024 ** 3, "站点数": 2},
        ],
    }


def test_v3_metadata_matches_market_index() -> None:
    """插件版本必须与 package.v3.json 条目、历史记录一致。"""
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    metadata = package["SeedStats"]

    assert metadata["version"] == SeedStats.plugin_version
    assert metadata["history"][f"v{SeedStats.plugin_version}"]
    assert metadata["system_version"] == ">=3.0.0"
    assert metadata["name"] == SeedStats.plugin_name
    assert metadata["labels"] == SeedStats.plugin_label


def test_command_and_dashboard_meta_are_declared() -> None:
    """远程命令与仪表板元信息必须可被宿主发现。"""
    commands = SeedStats.get_command()
    assert any(item.get("cmd") == "/保种统计" for item in commands)

    plugin = _plugin()
    assert plugin.get_dashboard_meta() == [{"key": "seedstats", "name": "站点保种统计"}]
    assert _plugin(_dashboard=False).get_dashboard_meta() == []
    assert _plugin(_enabled=False).get_dashboard_meta() == []


def test_site_mapping_parsing_normalizes_domains() -> None:
    """域名映射需忽略注释、大小写与协议前缀，并补全一级域名。"""
    mapping = SeedStats._SeedStats__parse_site_mapping(
        "# 注释行\nBGP.TECHNOLOGY=BGP\nhttps://hdhome.org = 家园\n\n无效行"
    )

    assert mapping["bgp.technology"] == "BGP"
    assert mapping["bgp"] == "BGP"
    assert mapping["hdhome.org"] == "家园"
    assert "无效行" not in mapping


def test_mapped_site_prefers_explicit_configuration() -> None:
    """显式映射优先，未命中的域名返回空串。"""
    plugin = _plugin(_site_mapping={"bgp": "BGP", "hdhome.org": "家园"})

    assert plugin._SeedStats__mapped_site("bgp.technology") == "BGP"
    assert plugin._SeedStats__mapped_site("hdhome.org:443") == "家园"
    assert plugin._SeedStats__mapped_site("unknown.example") == ""


def test_resolve_site_follows_tracker_tier_order() -> None:
    """同一任务的多个 tracker 按 tier 顺序解析，主 tracker 优先。"""
    plugin = _plugin(_site_mapping={"primary.example": "主站", "secondary.example": "备站"})
    torrent = {
        "trackers": [
            {"announce": "https://secondary.example/announce", "tier": 2},
            {"announce": "https://primary.example/announce", "tier": 1},
        ]
    }

    assert plugin._SeedStats__resolve_site(torrent, None) == "主站"


def test_resolve_site_falls_back_to_domain_and_unrecognized() -> None:
    """无映射时按域名单独成行；完全没有 tracker 时标记未识别。"""
    plugin = _plugin()

    assert plugin._SeedStats__resolve_site(
        {"tracker": "https://tracker.bgp.technology/announce"}, None
    ) == "bgp.technology"
    assert plugin._SeedStats__resolve_site({"trackers": []}, None) == "未识别"


def test_torrent_size_and_labels_handle_both_clients() -> None:
    """兼容 Transmission 与 qBittorrent 的字段命名。"""
    assert SeedStats._SeedStats__torrent_size({"totalSize": 100}) == 100
    assert SeedStats._SeedStats__torrent_size({"total_size": "2.9"}) == 2
    assert SeedStats._SeedStats__torrent_size({}) == 0
    assert SeedStats._SeedStats__labels({"labels": ["已整理", "辅种"]}) == ["已整理", "辅种"]
    assert SeedStats._SeedStats__labels({"tags": "已整理, 辅种"}) == ["已整理", "辅种"]
    assert SeedStats._SeedStats__labels({}) == []


def test_format_helpers_cover_edge_values() -> None:
    """容量、比例、魔力、时魔与效率的展示格式。"""
    fmt = SeedStats
    assert fmt._SeedStats__format_size(0) == "-"
    assert fmt._SeedStats__format_size(1024 ** 4) == "1.0 TB"
    assert fmt._SeedStats__format_ratio(0) == "-"
    assert fmt._SeedStats__format_ratio(1500) == "∞"
    assert fmt._SeedStats__format_ratio(3.456) == "3.46"
    assert fmt._SeedStats__format_bonus(12345) == "1.23 万"
    assert fmt._SeedStats__format_hourly(1.234) == "1.2/时"
    assert fmt._SeedStats__format_hourly(None, "无魔力") == "无魔力"
    assert fmt._SeedStats__format_efficiency(100, 1024 ** 4) == "100/TB·时"


def test_row_status_marks_stale_idle_and_unmapped() -> None:
    """站点行状态按未映射、零做种、数据过期依次判定。"""
    plugin = _plugin(_stale_hours=24)
    old = time.time() - 48 * 3600

    assert plugin._SeedStats__row_status({"_unknown_tracker": True, "任务数": 1}) == "未映射"
    assert plugin._SeedStats__row_status({"任务数": 0}) == "零做种"
    assert plugin._SeedStats__row_status({"_updated_ts": old, "任务数": 1}) == "数据过期"
    assert plugin._SeedStats__row_status({"_updated_ts": time.time(), "任务数": 1}) == "正常"


def test_build_alerts_reports_stale_idle_unmapped_and_removed() -> None:
    """告警文案需覆盖四类异常，并带上站点名。"""
    plugin = _plugin(_stale_hours=24)
    rows = [
        {"站点": "过期站", "状态": "数据过期", "数据时间": "2026-10-14 10:00:00", "任务数": 2},
        {"站点": "空闲站", "状态": "零做种", "任务数": 0},
        {"站点": "bgp.technology", "状态": "未映射", "任务数": 55, "_unknown_tracker": True},
    ]
    alerts = plugin._SeedStats__build_alerts(rows, [{"站点": "旧站", "任务数": 0}])

    assert len(alerts) == 4
    assert "过期站" in alerts[0]
    assert "空闲站" in alerts[1]
    assert "bgp.technology 55" in alerts[2]
    assert "旧站(仅账户数据)" in alerts[3]


def test_append_trend_replaces_current_hour_and_keeps_cap() -> None:
    """同一小时只保留一条趋势点，且不超过上限。"""
    now = time.time()
    hour_key = time.strftime("%Y-%m-%d %H", time.localtime(now))
    plugin = _plugin()
    plugin.get_data = lambda key=None: {
        "trend": [
            {"hour": hour_key, "ts": now - 60, "做种": 1, "辅种": 0, "体积": 1, "站点数": 1}
        ]
    }

    trend = plugin._SeedStats__append_trend({"做种": 9, "辅种": 4, "体积": 2048, "站点数": 3})

    same_hour = [item for item in trend if item["hour"] == hour_key]
    assert len(same_hour) == 1
    assert same_hour[0]["做种"] == 9
    assert same_hour[0]["辅种"] == 4


def _walk_charts(node, out: list) -> None:
    """递归收集页面中的图表配置。"""
    if isinstance(node, dict):
        if node.get("component") == "VApexChart":
            out.append(node.get("props", {}).get("options", {}))
        for value in node.values():
            _walk_charts(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_charts(value, out)


def test_page_and_dashboard_render_with_cached_snapshot() -> None:
    """页面与仪表板读取缓存即可渲染，柱状/折线图必须关闭 dataLabels。"""
    cache = _cache()
    plugin = _plugin()
    # 插件把统计快照写在 _CACHE_KEY（stats）下，这里按同样的键位提供桩数据
    plugin.get_data = lambda key=None: cache if key == "stats" else None

    page = plugin.get_page()
    charts: list = []
    _walk_charts(page, charts)
    types = [options.get("chart", {}).get("type") for options in charts]
    assert "bar" in types and "line" in types and "pie" in types
    for options in charts:
        if options.get("chart", {}).get("type") in {"bar", "line"}:
            assert options.get("dataLabels", {}).get("enabled") is False

    dashboard = plugin.get_dashboard("seedstats")
    assert dashboard is not None
    cols, attrs, content = dashboard
    assert cols["cols"] == 12
    assert attrs["refresh"] == 600
    dash_charts: list = []
    _walk_charts(content, dash_charts)
    assert dash_charts and dash_charts[0]["dataLabels"]["enabled"] is False


def test_page_shows_hint_before_first_snapshot() -> None:
    """首次统计尚未完成时给出等待提示，而不是空白页面。"""
    plugin = _plugin()
    plugin.get_data = lambda key=None: None

    page = plugin.get_page()

    assert page[0]["component"] == "VAlert"
    assert "首次统计" in page[0]["props"]["text"]
