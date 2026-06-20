"""AgentTokens 插件单测（pytest 原生）。

覆盖侧栏入口受 show_sidebar_nav 配置控制的逻辑。依赖 MoviePilot 后端（app.*）与
插件包：根 conftest 会先隔离 CONFIG_DIR 并把后端、plugins.v2 注入 sys.path，
再以顶层包名导入插件。
"""
from unittest.mock import patch

from agenttokens import AgentTokens  # noqa: E402


def test_sidebar_nav_respects_config():
    """侧栏入口应受 show_sidebar_nav 配置控制：关闭则不注册，开启且插件启用则注册。

    init_plugin 内部会持久化配置，这里 patch 掉 update_config，仅隔离验证侧栏逻辑。
    """
    plugin = AgentTokens()
    with patch.object(plugin, "update_config"):
        plugin.init_plugin({"enabled": True, "show_sidebar_nav": False, "providers": []})
        assert plugin.get_sidebar_nav() == []

        plugin.init_plugin({"enabled": True, "show_sidebar_nav": True, "providers": []})
        nav = plugin.get_sidebar_nav()

    assert nav[0]["title"] == "Agent Tokens 管理"


def test_summary_separates_limited_progress_from_unlimited_usage():
    """混合限量和不限量供应商时，限量进度不应包含不限量调用量。"""
    plugin = AgentTokens()
    usage_data = {
        "limited": {"total_tokens": 300, "input_tokens": 100, "output_tokens": 200},
        "unlimited": {"total_tokens": 900, "input_tokens": 400, "output_tokens": 500},
    }
    config = {
        "enabled": True,
        "providers": [
            {
                "id": "limited",
                "enabled": True,
                "name": "Limited",
                "base_url": "https://limited.example.com",
                "api_key": "limited-key",
                "model": "limited-model",
                "token_limit": 1000,
                "used_tokens": 100,
                "priority": 1,
            },
            {
                "id": "unlimited",
                "enabled": True,
                "name": "Unlimited",
                "base_url": "https://unlimited.example.com",
                "api_key": "unlimited-key",
                "model": "unlimited-model",
                "token_limit": 0,
                "used_tokens": 50,
                "priority": 2,
            },
        ],
    }

    with patch.object(plugin, "update_config"), patch.object(plugin, "get_data", return_value=usage_data):
        plugin.init_plugin(config)
        summary = plugin._summary()

    assert summary["total_limit"] == 1000
    assert summary["limited_used"] == 400
    assert summary["unlimited_used"] == 950
    assert summary["total_used"] == 1350
    assert summary["limited_remaining"] == 600
    assert summary["limited_usage_percent"] == 40
