"""WeComIPGuard 宿主契约测试。

用真实的 ``_PluginBase``、数据库与 APScheduler 验证插件的生命周期契约：
配置可重复初始化、调度器可停止、页面与 API 声明结构合法。
不触网、不启动浏览器内核。
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from app.plugins.wecomipguard import WeComIPGuard


def _base_config(**changes):
    """构造默认关闭定时任务的配置，避免测试期间产生真实调度。"""
    value = {
        "enabled": False,
        "onlyonce": False,
        "notify": False,
        "debug": False,
        "check_cron": "*/11 * * * *",
        "keepalive_cron": "*/5 * * * *",
        "status_cron": "0 * * * *",
        "wechat_url": "https://work.weixin.qq.com/wework_admin/frame#/apps/modApiApp/0000000000000000",
        "cookie_header": "",
        "qr_send_users": "",
        "overwrite": True,
        "use_cookiecloud": False,
        "schedule_login": False,
        "ip_urls": "",
        "http_timeout": 15,
        "browser_timeout": 180,
    }
    value.update(changes)
    return value


class TestPluginContract:
    """插件必须实现的基线契约。"""

    def test_inherits_plugin_base(self):
        from app.plugins import _PluginBase

        assert issubclass(WeComIPGuard, _PluginBase)

    @pytest.mark.parametrize(
        "method",
        ["init_plugin", "get_state", "get_api", "get_form", "get_page", "stop_service"],
    )
    def test_required_methods_exist(self, method):
        assert callable(getattr(WeComIPGuard, method, None))

    def test_get_command_registers_plugin_action(self):
        commands = WeComIPGuard.get_command()
        assert isinstance(commands, list) and commands
        command = commands[0]
        assert command["cmd"] == "/wecomipguard"
        assert command["data"] == {"action": "wecomipguard"}

    def test_get_service_empty_when_disabled(self):
        plugin = object.__new__(WeComIPGuard)
        plugin._enabled = False
        plugin._check_cron = "*/11 * * * *"
        assert plugin.get_service() == []

    def test_get_service_invalid_cron_returns_empty(self):
        """非法 cron 不应抛异常，而是返回空服务列表。"""
        plugin = object.__new__(WeComIPGuard)
        plugin._enabled = True
        plugin._check_cron = "not a cron"
        assert plugin.get_service() == []


class TestConfigLifecycle:
    """配置初始化必须可重复执行且不残留资源。"""

    def test_init_plugin_disabled_keeps_scheduler_none(self):
        plugin = object.__new__(WeComIPGuard)
        plugin._reset_config()
        plugin.stop_service = MagicMock()
        plugin.update_config = MagicMock()
        plugin.init_plugin(_base_config(enabled=False))
        assert plugin._scheduler is None
        assert plugin._enabled is False
        plugin.update_config.assert_called()

    def test_init_plugin_is_repeatable(self):
        """连续两次初始化不应抛错，且第二次会先停止旧调度器。"""
        plugin = object.__new__(WeComIPGuard)
        plugin._reset_config()
        plugin.stop_service = MagicMock()
        plugin.update_config = MagicMock()
        config = _base_config(enabled=True)

        with patch("app.plugins.wecomipguard.BackgroundScheduler") as scheduler_cls:
            scheduler = MagicMock()
            scheduler.get_jobs.return_value = []
            scheduler_cls.return_value = scheduler
            plugin.init_plugin(config)
            plugin.init_plugin(config)

        assert plugin.stop_service.call_count >= 2

    def test_stop_service_is_idempotent(self):
        plugin = object.__new__(WeComIPGuard)
        plugin._scheduler = None
        plugin.stop_service()
        plugin.stop_service()
        assert plugin._scheduler is None


class TestApiDeclaration:
    """get_api 声明的结构必须符合宿主契约。"""

    def test_api_entries_are_well_formed(self):
        plugin = object.__new__(WeComIPGuard)
        entries = plugin.get_api()
        assert isinstance(entries, list) and entries
        for entry in entries:
            assert entry["path"].startswith("/")
            assert callable(entry["endpoint"])
            assert isinstance(entry["methods"], list) and entry["methods"]
            assert entry["auth"] in {"bear", "apikey"}
            assert entry.get("summary")

    def test_api_endpoints_accept_no_required_args(self):
        plugin = object.__new__(WeComIPGuard)
        for entry in plugin.get_api():
            sig = inspect.signature(entry["endpoint"])
            required = [
                name
                for name, param in sig.parameters.items()
                if param.default is inspect.Parameter.empty
                and param.kind
                not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            assert not required, f"{entry['path']} 存在必填参数：{required}"


class TestFormDeclaration:
    """get_form 必须返回（组件树, 默认配置）二元组。"""

    def test_form_returns_tree_and_defaults(self):
        plugin = object.__new__(WeComIPGuard)
        tree, defaults = plugin.get_form()
        assert isinstance(tree, list) and tree
        assert isinstance(defaults, dict) and defaults
        assert tree[0]["component"] == "VForm"

    def test_form_defaults_cover_config_keys(self):
        """默认配置应覆盖 init_plugin 会读取的全部键。"""
        plugin = object.__new__(WeComIPGuard)
        _, defaults = plugin.get_form()
        expected = {
            "enabled",
            "onlyonce",
            "notify",
            "debug",
            "check_cron",
            "keepalive_cron",
            "status_cron",
            "wechat_url",
            "cookie_header",
            "qr_send_users",
            "overwrite",
            "use_cookiecloud",
            "schedule_login",
            "ip_urls",
            "http_timeout",
            "browser_timeout",
        }
        assert expected.issubset(set(defaults))

    def test_form_components_are_known(self):
        """组件名必须是 Vuetify 组件或原生标签，避免渲染报错。"""
        known = {
            "VForm", "VRow", "VCol", "VCard", "VCardText", "VSwitch", "VTextField",
            "VTextarea", "VAlert", "VExpansionPanels", "VExpansionPanel",
            "VExpansionPanelText", "VIcon", "VChip", "VBtn", "VDivider", "VSheet",
            "VAvatar", "VTable", "VProgressLinear", "VTimeline", "VTimelineItem",
            "VImg", "VMenu", "VList", "VListItem", "VSelect", "VSlider",
            "VCheckbox", "VAutocomplete", "VCombobox", "VWindow", "VWindowItem",
            "div", "span", "a", "img", "svg", "path", "p", "h1", "h2", "h3",
            "h4", "h5", "h6", "table", "thead", "tbody", "tr", "td", "th",
            "ul", "ol", "li", "br", "hr", "strong", "b", "i", "em", "small",
            "code", "pre", "style", "section",
        }
        plugin = object.__new__(WeComIPGuard)
        tree, _ = plugin.get_form()

        seen = set()

        def walk(node):
            if isinstance(node, dict):
                component = node.get("component")
                if isinstance(component, str):
                    seen.add(component)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(tree)
        unknown = seen - known
        assert not unknown, f"未知组件：{sorted(unknown)}"


class TestPageRender:
    """get_page 在各种状态下都必须返回可渲染结构。"""

    @pytest.mark.parametrize(
        "enabled,cookie_valid,pending,sync_result",
        [
            (False, False, False, ""),
            (True, False, False, ""),
            (True, True, True, "Cookie失效，等待恢复后自动补写"),
            (True, True, False, "成功"),
            (True, True, False, ""),
        ],
    )
    def test_page_renders_in_any_state(self, enabled, cookie_valid, pending, sync_result):
        plugin = object.__new__(WeComIPGuard)
        plugin._reset_config()
        plugin._enabled = enabled
        plugin._cookie_valid = cookie_valid
        plugin._pending_sync = pending
        plugin._sync_result = sync_result
        plugin._sync_detail = ["应用1: 1.2.3.4 -> 1.2.3.4 (成功)"] if pending else []
        plugin._urls = ["https://example.com/a", "https://example.com/b"]
        plugin._current_ip = "1.2.3.4"

        page = plugin.get_page()
        assert isinstance(page, list) and page
        for block in page:
            assert isinstance(block, dict)
            assert block.get("component")


class TestStatusApi:
    """状态查询 API 的返回结构。"""

    def test_status_returns_expected_keys(self):
        plugin = object.__new__(WeComIPGuard)
        plugin._reset_config()
        result = plugin.api_status()
        assert result["code"] == 0
        data = result["data"]
        for key in (
            "enabled",
            "cookie_valid",
            "current_ip",
            "pending_sync",
            "sync_result",
            "ip_source",
        ):
            assert key in data

    def test_check_api_rejects_when_disabled(self):
        plugin = object.__new__(WeComIPGuard)
        plugin._reset_config()
        result = plugin.api_check()
        assert result["code"] == 1
        assert "未启用" in result["message"]
