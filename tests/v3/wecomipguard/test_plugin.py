"""WeComIPGuard 插件测试。

这些用例覆盖不依赖网络与浏览器内核的纯逻辑：公网 IPv4 解析与过滤、
Cookie HeaderString 解析、配置读取边界。运行方式与官方插件仓一致：

    python tests/run.py

或单独运行：

    python -m pytest tests/v3/wecomipguard -q
"""

from unittest.mock import MagicMock

import pytest

from app.plugins.wecomipguard import WeComIPGuard


def _make_plugin() -> WeComIPGuard:
    """构造不触发宿主 Chain 依赖的插件实例。"""
    plugin = object.__new__(WeComIPGuard)
    plugin._enabled = False
    plugin._onlyonce = False
    plugin._notify = True
    plugin._debug = False
    plugin._check_cron = "*/11 * * * *"
    plugin._keepalive_cron = "*/5 * * * *"
    plugin._status_cron = "0 * * * *"
    plugin._wechat_url = ""
    plugin._cookie_header = ""
    plugin._qr_send_users = ""
    plugin._overwrite = True
    plugin._use_cookiecloud = True
    plugin._schedule_login = False
    plugin._ip_urls_text = ""
    plugin._http_timeout = 15
    plugin._browser_timeout = 180
    plugin._cookie_valid = False
    plugin._pending_sync = False
    plugin._urls = []
    plugin._cookie_from_cloud = ""
    plugin._scheduler = None
    plugin._current_ip = ""
    plugin._ip_source = ""
    plugin._ip_checked_at = ""
    plugin._ip_error = ""
    plugin._sync_at = ""
    plugin._sync_result = ""
    plugin._sync_detail = []
    plugin._last_probe_mode = ""
    plugin._code = 0
    plugin._cookiecloud = MagicMock()
    return plugin


class TestPluginMetadata:
    """插件元数据应稳定，便于市场与勋章统计识别。"""

    def test_metadata(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "企业微信可信IP助手"
        assert plugin.plugin_version == "1.1.0"
        assert plugin.plugin_config_prefix == "wecomipguard_"
        assert plugin.plugin_author == "workroom2008"
        assert plugin.auth_level == 1

    def test_icon_is_local_file(self):
        """图标必须是仓库 icons/ 下的文件名，不能是完整 URL。"""
        assert not WeComIPGuard.plugin_icon.startswith(("http://", "https://"))
        assert WeComIPGuard.plugin_icon.endswith(".png")


class TestParseIpv4:
    """公网 IPv4 解析与校验。"""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Current IP Address: 106.112.158.166", "106.112.158.166"),
            ("106.112.158.166\n", "106.112.158.166"),
            ('{"ip":"8.8.8.8"}', "8.8.8.8"),
            ("https://ddns.oray.com/checkip: 1.2.3.4", "1.2.3.4"),
        ],
    )
    def test_extracts_valid_ipv4(self, text, expected):
        assert WeComIPGuard._parse_ipv4(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            # IPv6 文本不能当成 IPv4
            "当前 IP：240e:341:7146:4a00:c42c:9d6c:c666:11e1 来自于：中国 河北",
            # 私网 / 回环地址要过滤
            "192.168.1.5",
            "127.0.0.1",
            "10.0.0.1",
            # 非法数值
            "999.1.1.1",
            # 版本号不能被误判
            "v1.2.3.4.5.6",
            "",
            None,
        ],
    )
    def test_rejects_invalid_or_non_public(self, text):
        assert WeComIPGuard._parse_ipv4(text) is None


class TestParseCookieHeader:
    """Cookie HeaderString 解析。"""

    def test_parses_pairs_and_skips_malformed(self):
        result = WeComIPGuard._parse_cookie_header("a=1; b=2;c=3; bad; =x; d=")
        assert result == {"a": "1", "b": "2", "c": "3", "d": ""}

    def test_value_can_contain_equals(self):
        assert WeComIPGuard._parse_cookie_header("k=a=b==c") == {"k": "a=b==c"}

    def test_empty_input(self):
        assert WeComIPGuard._parse_cookie_header("") == {}


class TestConfigDefaults:
    """配置读取的边界行为。"""

    def test_as_int_falls_back_on_bad_value(self):
        assert WeComIPGuard._as_int("abc", 15) == 15
        assert WeComIPGuard._as_int(None, 180) == 180
        assert WeComIPGuard._as_int(0, 15) == 15
        assert WeComIPGuard._as_int("30", 15) == 30

    def test_default_ip_sources_are_https(self):
        sources = WeComIPGuard._default_ip_urls
        assert sources, "必须至少有一个内置 IP 源"
        assert all(url.startswith("https://") for url in sources)

    def test_load_config_keeps_defaults_for_missing_keys(self):
        """空配置不应把默认值覆盖成 None。"""
        plugin = _make_plugin()
        plugin._reset_config()
        plugin._load_config({})
        assert plugin._check_cron == "*/11 * * * *"
        assert plugin._keepalive_cron == "*/5 * * * *"
        assert plugin._http_timeout == 15
        assert plugin._browser_timeout == 180
        assert plugin._overwrite is True

    def test_load_config_applies_values(self):
        plugin = _make_plugin()
        plugin._reset_config()
        plugin._load_config(
            {
                "enabled": True,
                "check_cron": "*/30 * * * *",
                "http_timeout": "20",
                "overwrite": False,
            }
        )
        assert plugin._enabled is True
        assert plugin._check_cron == "*/30 * * * *"
        assert plugin._http_timeout == 20
        assert plugin._overwrite is False


class TestIpSources:
    """IP 源选择逻辑。"""

    def test_uses_default_sources_when_text_empty(self):
        plugin = _make_plugin()
        plugin._ip_urls_text = ""
        assert plugin._ip_sources == WeComIPGuard._default_ip_urls

    def test_uses_custom_sources_when_provided(self):
        plugin = _make_plugin()
        plugin._ip_urls_text = "https://a.example/ip, https://b.example/ip"
        assert plugin._ip_sources == ["https://a.example/ip", "https://b.example/ip"]
