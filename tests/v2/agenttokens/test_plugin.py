"""AgentTokens 插件单测（pytest 原生）。

覆盖侧栏入口受 show_sidebar_nav 配置控制的逻辑。依赖 MoviePilot 后端（app.*）与
插件包：根 conftest 会先隔离 CONFIG_DIR，再通过生产命名空间暴露对应插件源码。
"""
from unittest.mock import patch
from types import SimpleNamespace

from app.plugins.agenttokens import AgentTokens  # noqa: E402


def _plugin() -> AgentTokens:
    """构造插件实例，隔离与被测逻辑无关的宿主 Chain 组合根。"""
    with patch("app.plugins.PluginChian"):
        return AgentTokens()


def _provider(provider_id: str, priority: int, **overrides) -> dict:
    """构造具备完整连接配置的供应商测试数据。"""
    provider = {
        "id": provider_id,
        "enabled": True,
        "name": provider_id.title(),
        "provider": "openai",
        "base_url": f"https://{provider_id}.example.com",
        "api_key": f"{provider_id}-key",
        "model": f"{provider_id}-model",
        "priority": priority,
    }
    provider.update(overrides)
    return provider


def _initialized_plugin(providers: list[dict]) -> AgentTokens:
    """创建启用状态的插件实例，并隔离配置持久化副作用。"""
    plugin = _plugin()
    with patch.object(plugin, "update_config"):
        plugin.init_plugin({"enabled": True, "providers": providers})
    return plugin


def test_sidebar_nav_respects_config():
    """侧栏入口应受 show_sidebar_nav 配置控制：关闭则不注册，开启且插件启用则注册。

    init_plugin 内部会持久化配置，这里 patch 掉 update_config，仅隔离验证侧栏逻辑。
    """
    plugin = _plugin()
    with patch.object(plugin, "update_config"):
        plugin.init_plugin({"enabled": True, "show_sidebar_nav": False, "providers": []})
        assert plugin.get_sidebar_nav() == []

        plugin.init_plugin({"enabled": True, "show_sidebar_nav": True, "providers": []})
        nav = plugin.get_sidebar_nav()

    assert nav[0]["title"] == "Agent Tokens 管理"


def test_summary_separates_limited_progress_from_unlimited_usage():
    """混合限量和不限量供应商时，限量进度不应包含不限量调用量。"""
    plugin = _plugin()
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


def test_select_llm_provider_uses_requested_provider_from_metadata():
    """metadata 指定的供应商应优先于自动优先级选择并完整回填配置。"""
    plugin = _initialized_plugin([
        _provider("primary", 1),
        _provider("requested", 2),
    ])
    event = SimpleNamespace(event_data={
        "metadata": {"requested_provider_id": "requested"},
    })

    with patch.object(plugin, "get_data", return_value={}):
        plugin.select_llm_provider(event)

    assert event.event_data["selected_provider_id"] == "requested"
    assert event.event_data["selected_provider_name"] == "Requested"
    assert event.event_data["base_url"] == "https://requested.example.com"
    assert event.event_data["api_key"] == "requested-key"
    assert event.event_data["model"] == "requested-model"
    assert event.event_data["metadata"]["provider_selection_status"] == "selected"


def test_select_llm_provider_accepts_direct_requested_provider_field():
    """字典事件中的兼容字段 requested_provider_id 应支持定向选择。"""
    plugin = _initialized_plugin([
        _provider("primary", 1),
        _provider("requested", 2),
    ])
    event = SimpleNamespace(event_data={"requested_provider_id": "requested"})

    with patch.object(plugin, "get_data", return_value={}):
        plugin.select_llm_provider(event)

    assert event.event_data["selected_provider_id"] == "requested"
    assert event.event_data["metadata"]["requested_provider_id"] == "requested"


def test_requested_provider_unavailable_does_not_fallback_by_default():
    """指定供应商不可用且未授权回退时，应保持未选择状态并写回失败原因。"""
    plugin = _initialized_plugin([
        _provider("primary", 1),
        _provider("requested", 2, enabled=False),
    ])
    event = SimpleNamespace(event_data={
        "metadata": {"requested_provider_id": "requested"},
    })

    with patch.object(plugin, "get_data", return_value={}):
        plugin.select_llm_provider(event)

    assert "selected_provider_id" not in event.event_data
    assert event.event_data["metadata"]["provider_selection_status"] == "unavailable"
    assert event.event_data["metadata"]["provider_selection_error"] == "供应商已停用"


def test_requested_provider_can_explicitly_fallback():
    """调用方显式允许回退时，应在指定项不可用后选择优先级最高的可用供应商。"""
    plugin = _initialized_plugin([
        _provider("primary", 1),
        _provider("requested", 2, token_limit=100),
    ])
    event = SimpleNamespace(event_data={
        "metadata": {
            "requested_provider_id": "requested",
            "allow_failover": True,
        },
    })

    with patch.object(
        plugin,
        "get_data",
        return_value={"requested": {"total_tokens": 100}},
    ):
        plugin.select_llm_provider(event)

    assert event.event_data["selected_provider_id"] == "primary"
    assert event.event_data["metadata"]["provider_selection_status"] == "fallback"
    assert event.event_data["metadata"]["requested_provider_error"] == "供应商 Token 额度已耗尽"
