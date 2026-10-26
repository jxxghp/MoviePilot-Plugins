"""自定义 Hosts 插件使用真实解析库和临时文件验证写入及恢复行为。"""

from unittest.mock import Mock

import pytest
from python_hosts import Hosts

from app.plugins.customhosts import CustomHosts


@pytest.fixture
def plugin_hosts(tmp_path, monkeypatch):
    """将所有系统 Hosts 读写和配置保存隔离到临时文件与替身。"""
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n# system entry\n", encoding="utf-8")
    plugin = object.__new__(CustomHosts)
    plugin._enabled = False
    plugin._hosts = []
    plugin.systemmessage = Mock()
    plugin.update_config = Mock()
    monkeypatch.setattr(
        CustomHosts,
        "_CustomHosts__read_system_hosts",
        staticmethod(lambda: Hosts(path=str(hosts_path))),
    )
    return plugin, hosts_path


def _mappings(hosts_path):
    """重新读取磁盘文件，返回地址和域名映射，避免只检查内存对象。"""
    return [
        (entry.address, entry.names)
        for entry in Hosts(path=str(hosts_path)).entries
        if entry.address
    ]


@pytest.mark.parametrize("address", ["162.159.129.235", "2001:db8::1"])
@pytest.mark.parametrize("as_list", [False, True])
def test_multiple_lines_with_same_address_are_written(plugin_hosts, address, as_list):
    """同一 IPv4 或 IPv6 的五行配置均应写入，兼容文本与历史列表配置。"""
    plugin, hosts_path = plugin_hosts
    names = ["ourbits.club", "pterclub.net", "www.pthome.net", "u2.dmhy.org", "bilibili.download"]
    lines = [f"{address} {name}" for name in names]
    config = lines if as_list else "\n".join(lines)

    plugin.init_plugin({"enabled": True, "hosts": config})

    assert _mappings(hosts_path) == [
        ("127.0.0.1", ["localhost"]),
        *((address, [name]) for name in names),
    ]
    assert plugin.get_state() is True
    assert plugin.update_config.call_args.args[0]["err_hosts"] == []
    plugin.systemmessage.put.assert_not_called()


@pytest.mark.parametrize("address", ["203.0.113.1", "2001:db8::1"])
def test_address_already_in_system_hosts_allows_other_names(plugin_hosts, address):
    """系统已有相同地址时，仍应追加其他域名，且保留原系统记录。"""
    plugin, hosts_path = plugin_hosts
    with hosts_path.open("a", encoding="utf-8") as hosts_file:
        hosts_file.write(f"{address} system.example\n")

    plugin.init_plugin({"enabled": True, "hosts": f"{address} first.example\n{address} second.example"})

    assert _mappings(hosts_path) == [
        ("127.0.0.1", ["localhost"]),
        (address, ["system.example"]),
        (address, ["first.example"]),
        (address, ["second.example"]),
    ]


def test_comments_and_multiple_names_per_line_are_preserved(plugin_hosts):
    """写入保留配置注释及同一行的多个域名。"""
    plugin, hosts_path = plugin_hosts
    plugin.init_plugin({
        "enabled": True,
        "hosts": "# custom entry\n203.0.113.1 first.example alias.example\n203.0.113.1 second.example",
    })

    assert "# custom entry" in hosts_path.read_text(encoding="utf-8")
    assert _mappings(hosts_path)[1:] == [
        ("203.0.113.1", ["first.example", "alias.example"]),
        ("203.0.113.1", ["second.example"]),
    ]


def test_repeated_save_replaces_old_block_and_disable_restores_system(plugin_hosts):
    """重复保存应替换旧插件区块，关闭插件后恢复原系统记录。"""
    plugin, hosts_path = plugin_hosts
    config = {"enabled": True, "hosts": "203.0.113.1 first.example\n203.0.113.1 second.example"}
    plugin.init_plugin(config)
    plugin.init_plugin(config)
    assert len(_mappings(hosts_path)) == 3
    assert hosts_path.read_text(encoding="utf-8").count("# CustomHostsPlugin") == 1

    plugin.init_plugin({"enabled": True, "hosts": "203.0.113.1 replacement.example"})
    assert _mappings(hosts_path)[1:] == [("203.0.113.1", ["replacement.example"])]

    plugin.init_plugin({"enabled": False, "hosts": config["hosts"]})
    assert _mappings(hosts_path) == [("127.0.0.1", ["localhost"])]
    assert "# system entry" in hosts_path.read_text(encoding="utf-8")
    assert "# CustomHostsPlugin" not in hosts_path.read_text(encoding="utf-8")


def test_existing_system_hostname_is_not_overwritten(plugin_hosts):
    """允许重复地址后，仍保留已有同名系统域名的保护行为。"""
    plugin, hosts_path = plugin_hosts
    with hosts_path.open("a", encoding="utf-8") as hosts_file:
        hosts_file.write("172.67.213.134 u2.dmhy.org\n")
    plugin.init_plugin({
        "enabled": True,
        "hosts": "162.159.129.235 ourbits.club\n162.159.129.235 u2.dmhy.org\n162.159.129.235 pterclub.net",
    })

    assert _mappings(hosts_path)[1:] == [
        ("172.67.213.134", ["u2.dmhy.org"]),
        ("162.159.129.235", ["ourbits.club"]),
        ("162.159.129.235", ["pterclub.net"]),
    ]


def test_invalid_address_is_reported_without_losing_valid_lines(plugin_hosts):
    """无效地址继续进入错误配置，有效的同 IP 多行仍应写入。"""
    plugin, hosts_path = plugin_hosts
    plugin.init_plugin({
        "enabled": True,
        "hosts": "203.0.113.1 first.example\ninvalid-address bad.example\n203.0.113.1 second.example",
    })

    assert _mappings(hosts_path)[1:] == [
        ("203.0.113.1", ["first.example"]),
        ("203.0.113.1", ["second.example"]),
    ]
    assert plugin.update_config.call_args.args[0]["err_hosts"] == ["invalid-address bad.example\n"]
    plugin.systemmessage.put.assert_called_once()


def test_write_failure_disables_plugin_and_reports_error(plugin_hosts, monkeypatch):
    """写入权限错误应关闭插件并报告失败，不能误报写入成功。"""
    plugin, hosts_path = plugin_hosts
    monkeypatch.setattr(Hosts, "write", Mock(side_effect=PermissionError("read-only hosts")))

    plugin.init_plugin({"enabled": True, "hosts": "203.0.113.1 first.example\n203.0.113.1 second.example"})

    assert plugin.get_state() is False
    assert plugin.update_config.call_args.args[0]["enabled"] is False
    assert "read-only hosts" in plugin.systemmessage.put.call_args.args[0]
    assert _mappings(hosts_path) == [("127.0.0.1", ["localhost"])]
