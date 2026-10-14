"""签到结果的统一结构、通知样式开关和 V3 版本依赖契约。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.notification import build_notification_content
from app.plugins.autosignin.result import SiteResult


@pytest.mark.parametrize("action", ["签到", "登录"])
def test_notification_counts_groups_and_retry(action):
    """业务结果分组和重试标记独立，不需要知道任何投递渠道。"""
    results = [SiteResult("成功站", "奖励 10", True, True),
               SiteResult("保号站", "登录成功，签到未确认", False, True),
               SiteResult("失败站", "Cookie已失效", False)]
    content = build_notification_content("2026-10-14", action, results, 5, [1, 3], [1, 2, 3])
    titles = [block.title or "" for block in content.blocks]
    texts = [block.text or "" for block in content.blocks]
    assert "仅登录 1  ·  失败 1" in titles[1]
    assert texts[1] == "已选 5  /  本次 3  /  下次执行 2"
    assert titles.index("失败站 · ↻ 下次执行") < titles.index("保号站") < titles.index("成功站 · ↻ 下次执行")
    assert sum("↻ 下次执行" in title for title in titles) == 2


def test_external_results_are_raw_data_in_universal_payload():
    """插件保留站点文本原意，转义和渠道语法由宿主完成。"""
    result = SiteResult("<script>*站_点*", "<!channel> [链接](https://bad.example) **成功**", False)
    content = build_notification_content("2026-10-14", "签到", [result], 1, [], [1])
    row = next(block for block in content.blocks if block.title == result.site_name)
    assert row.text == result.message
    assert set(content.to_dict()) == {"title", "blocks"}


def test_large_report_prioritizes_failures_and_keeps_every_site():
    """全部站点进入同一份内容，渠道分段由宿主完成。"""
    success = [SiteResult(f"成功站{index}", "奖励 " * 5000, True) for index in range(40)]
    failure = SiteResult("失败站", "失败 " * 5000, False)
    content = build_notification_content("2026-10-14", "签到", success + [failure], 41, [40], list(range(41)))
    titles = [block.title or "" for block in content.blocks]
    assert titles.index("失败站 · ↻ 下次执行") < titles.index("成功站0")
    assert all(f"成功站{index}" in titles for index in range(40))
    assert "确认签到 40" in titles[1]
    assert len([block for block in content.blocks if block.text and block.text.endswith("…")]) == 41


@pytest.mark.parametrize("rich_enabled", [True, False])
def test_execution_keeps_plain_fallback_and_one_broadcast(monkeypatch, rich_enabled):
    """只广播一次，保留完整旧正文，关闭开关时不提供结构化内容。"""
    plugin = object.__new__(AutoSignIn)
    plugin._notify = True
    plugin._rich_notify = rich_enabled
    plugin._clean = False
    plugin._auto_cf = 0
    plugin._retry_keyword = "失败"
    for method in ("post_message", "save_data", "update_config", "_clean_history"):
        monkeypatch.setattr(plugin, method, Mock())
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=None))
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", Mock(return_value=[]))
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(
        get_indexers=lambda: [{"id": 1, "name": "站点一"}]))
    monkeypatch.setattr(plugin, "signin_site", Mock(return_value=SiteResult("站点一", "签到成功", True)))
    plugin._AutoSignIn__do(datetime(2026, 10, 14), "签到", [1])
    plugin.post_message.assert_called_once()
    kwargs = plugin.post_message.call_args.kwargs
    assert kwargs["text"] == (
        "全部签到数量: 1 \n本次签到数量: 1 \n下次签到数量: 0 \n"
        "确认签到成功: 1 \n仅确认登录: 0 \n登录或访问失败: 0 \n【站点一】签到成功"
    )
    assert ("rich_content" in kwargs) == rich_enabled


@pytest.mark.parametrize("config,expected", [({"notify": True}, True), ({"rich_notify": False}, False), ({}, True)])
def test_style_switch_default_configuration_and_persistence(monkeypatch, config, expected):
    """升级缺少开关的旧配置默认启用，用户关闭后持久化，重新初始化不泄漏旧状态。"""
    plugin = object.__new__(AutoSignIn)
    plugin._rich_notify = False
    for method in ("stop_service", "update_config"):
        monkeypatch.setattr(plugin, method, Mock())
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", Mock(return_value=[]))
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", lambda: SimpleNamespace(list_order_by_pri=lambda: []))
    plugin.init_plugin(config)
    assert plugin._rich_notify is expected
    if config:
        assert plugin.update_config.call_args.args[0]["rich_notify"] is expected


def test_form_exposes_enabled_style_switch(monkeypatch):
    """配置表单提供默认开启的优化通知样式开关。"""
    plugin = object.__new__(AutoSignIn)
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", Mock(return_value=[]))
    monkeypatch.setattr("app.plugins.autosignin.SiteOper", lambda: SimpleNamespace(list_order_by_pri=lambda: []))
    form, defaults = plugin.get_form()

    def models(nodes):
        """提取声明式表单字段供契约断言。"""
        return [node.get("props", {}).get("model") for node in nodes] + [
            value for node in nodes for value in models(node.get("content", []))]

    assert "rich_notify" in models(form)
    assert defaults["rich_notify"] is True


def test_v3_metadata_requires_next_backend_version_and_preserves_v2():
    """V3 独立发版和最低版本限制同步，V2 保留对旧版 V3 的兼容。"""
    import json
    from pathlib import Path
    from packaging.specifiers import SpecifierSet

    root = Path(__file__).resolve().parents[3]
    v3 = json.loads((root / "package.v3.json").read_text())["AutoSignIn"]
    v2 = json.loads((root / "package.v2.json").read_text())["AutoSignIn"]
    assert AutoSignIn.plugin_version == v3["version"] == "3.0.0"
    assert v3["system_version"] == ">=3.1.6"
    requirement = SpecifierSet(v3["system_version"])
    assert "3.1.5" not in requirement
    assert "3.1.6" in requirement
    assert "3.2.0" in requirement
    assert v2["version"] == "2.9.13" and v2["v3"] is True
    assert v2["system_version"] == "<=3.1.5"
    legacy_requirement = SpecifierSet(v2["system_version"])
    assert "2.2.1" in legacy_requirement
    assert "3.1.5" in legacy_requirement
    assert "3.1.6" not in legacy_requirement
    assert "v2.9.14" not in v2["history"]


def test_old_v3_can_install_v2_compatible_entry(monkeypatch):
    """旧版 V3 可选择并通过 V2 安装准入，新样式版本仍受最低版本限制。"""
    import json
    from pathlib import Path

    from packaging.version import Version

    from app.adapters.external.plugin import client as client_module
    from app.adapters.external.plugin.client import PluginMarketTransport

    root = Path(__file__).resolve().parents[3]
    indexes = {generation: json.loads((root / f"package.{generation}.json").read_text())
               for generation in ("v2", "v3")}
    monkeypatch.setattr(client_module, "get_runtime_setting",
                        lambda key, default=None: "v3" if key == "VERSION_FLAG" else default)
    monkeypatch.setattr(PluginMarketTransport, "get_current_system_version",
                        staticmethod(lambda: Version("3.1.5")))
    transport = PluginMarketTransport()
    monkeypatch.setattr(transport, "get_plugins",
                        lambda _repo, package_version=None: indexes.get(package_version, {}))
    assert transport.get_plugin_package_version("AutoSignIn", "https://github.com/jxxghp/MoviePilot-Plugins",
                                                package_version="v2") == "v2"
    assert transport.check_plugin_install_compatibility(indexes["v2"]["AutoSignIn"])[0]
    assert not transport.check_plugin_install_compatibility(indexes["v3"]["AutoSignIn"])[0]
    monkeypatch.setattr(PluginMarketTransport, "get_current_system_version",
                        staticmethod(lambda: Version("3.1.6")))
    assert not transport.check_plugin_install_compatibility(indexes["v2"]["AutoSignIn"])[0]
    assert transport.check_plugin_install_compatibility(indexes["v3"]["AutoSignIn"])[0]
