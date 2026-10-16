"""AgentTokens 插件单测（pytest 原生）。

覆盖侧栏入口受 show_sidebar_nav 配置控制的逻辑。依赖 MoviePilot 后端（app.*）与
插件包：根 conftest 会先隔离 CONFIG_DIR，再通过生产命名空间暴露对应插件源码。
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.plugins.agenttokens import AgentTokens  # noqa: E402


def _plugin() -> AgentTokens:
    """构造插件实例；宿主 Chain 运行上下文由根 conftest 统一装配替身。"""
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


@pytest.fixture
def cooldown_plugin(monkeypatch):
    """隔离持久记录和时钟，复现跨轮次选号及重载后的冷却。"""
    usage = {}
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr('app.plugins.agenttokens.time.time', lambda: clock.now)
    plugin = _initialized_plugin([
        _provider('primary', 1, failure_cooldown_enabled=True, failure_threshold=2,
                  cooldown_seconds=60, cooldown_max_seconds=180, cooldown_exponential=True),
        _provider('backup', 2),
    ])
    monkeypatch.setattr(plugin, 'get_data', lambda _key: deepcopy(usage))

    def save_usage(_key, value):
        """模拟独立序列化读写，避免测试依赖原地修改共享字典。"""
        usage.clear()
        usage.update(deepcopy(value))

    monkeypatch.setattr(plugin, 'save_data', save_usage)
    return plugin, usage, clock


def _record_result(plugin, success=False, provider_id='primary', error='429 queue.full.title'):
    """通过生产事件入口记录一次执行结果，包括失败轮次的真实用量。"""
    plugin.record_tokens_usage(SimpleNamespace(event_data={
        'selected_provider_id': provider_id,
        'success': success,
        'error': error,
        'input_tokens': 10,
        'output_tokens': 5,
    }))


def _selected_id(plugin, **kwargs):
    """通过链式事件入口验证最终分配 ID，并保留不可用元数据供其他测试检查。"""
    event = SimpleNamespace(event_data={'metadata': {}, **kwargs})
    plugin.select_llm_provider(event)
    return event.event_data.get('selected_provider_id')


def test_failure_threshold_skips_primary_and_preserves_usage(cooldown_plugin):
    """达到阈值前仍用主记录；达到后跳过它，状态与统计同步体现冷却。"""
    plugin, usage, _clock = cooldown_plugin
    _record_result(plugin)
    assert _selected_id(plugin) == 'primary'
    _record_result(plugin)
    assert _selected_id(plugin) == 'backup'
    row = plugin.get_status().data['providers'][0]
    assert row['usage']['cooling_down'] is True
    assert row['usage']['cooldown_remaining_seconds'] == 60
    assert row['usage']['cooldown_reason'] == '429 queue.full.title'
    assert usage['primary']['failure_count'] == 2
    assert usage['primary']['total_tokens'] == 30
    assert plugin._summary()['available_count'] == 1


def test_cooldown_expiry_and_exponential_cap(cooldown_plugin):
    """到期即可重新选号；再次连续失败翻倍，并严格遵守时长上限。"""
    plugin, usage, clock = cooldown_plugin
    for expected_duration in (60, 120, 180, 180):
        _record_result(plugin)
        _record_result(plugin)
        assert usage['primary']['cooldown_duration'] == expected_duration
        assert _selected_id(plugin) == 'backup'
        clock.now += expected_duration
        assert _selected_id(plugin) == 'primary'
        assert plugin._summary()['available_count'] == 2


def test_fixed_cooldown_does_not_back_off(cooldown_plugin):
    """关闭指数退避后，反复触发仍使用固定冷却时长。"""
    plugin, usage, clock = cooldown_plugin
    plugin._providers[0]['cooldown_exponential'] = False
    for _ in range(3):
        _record_result(plugin)
        _record_result(plugin)
        assert usage['primary']['cooldown_duration'] == 60
        clock.now += 60


def test_success_clears_streak_cooldown_and_backoff(cooldown_plugin):
    """成功打断连续失败，在途成功也可解除冷却并重置退避时长。"""
    plugin, usage, clock = cooldown_plugin
    _record_result(plugin)
    _record_result(plugin, success=True)
    _record_result(plugin)
    assert _selected_id(plugin) == 'primary'
    _record_result(plugin)
    clock.now += 60
    _record_result(plugin)
    _record_result(plugin)
    assert usage['primary']['cooldown_duration'] == 120
    _record_result(plugin, success=True)
    assert _selected_id(plugin) == 'primary'
    assert usage['primary']['cooldown_until'] == 0
    assert usage['primary']['cooldown_reason'] is None
    _record_result(plugin)
    _record_result(plugin)
    assert usage['primary']['cooldown_duration'] == 60


def test_inflight_failures_do_not_extend_cooldown(cooldown_plugin):
    """已进入冷却时，其他在途失败仍记账但不重复延长冷却或累计下一轮阈值。"""
    plugin, usage, clock = cooldown_plugin
    _record_result(plugin)
    _record_result(plugin)
    clock.now += 10
    _record_result(plugin)
    assert usage['primary']['cooldown_until'] == 1060
    assert usage['primary']['consecutive_failures'] == 0
    assert usage['primary']['failure_count'] == 3


def test_cooldown_persists_across_reload_and_reset_clears_it(cooldown_plugin):
    """重载保留记录级冷却；原有重置用量操作也清除该记录冷却。"""
    plugin, usage, _clock = cooldown_plugin
    _record_result(plugin)
    _record_result(plugin)
    with patch.object(plugin, 'update_config'):
        plugin.init_plugin(plugin._current_config())
    assert _selected_id(plugin) == 'backup'
    assert plugin.reset_usage_api({'provider_id': 'primary'}).success
    assert _selected_id(plugin) == 'primary'
    assert 'primary' not in usage


def test_disabled_policy_and_cancelled_runs_do_not_cool(cooldown_plugin):
    """旧配置默认关闭；关闭策略和用户取消均不触发冷却。"""
    plugin, usage, _clock = cooldown_plugin
    assert plugin._providers[1]['failure_cooldown_enabled'] is False
    for _ in range(3):
        _record_result(plugin, provider_id='backup')
        _record_result(plugin, error='任务已取消')
    assert usage['primary'].get('consecutive_failures', 0) == 0
    assert not usage['backup'].get('cooldown_until')
    assert _selected_id(plugin) == 'primary'
    _record_result(plugin)
    _record_result(plugin)
    plugin._providers[0]['failure_cooldown_enabled'] = False
    assert _selected_id(plugin) == 'primary'
    assert plugin._summary()['available_count'] == 2


def test_requested_provider_respects_cooldown_and_fallback(cooldown_plugin):
    """定向选号复用冷却判据；所有记录不可用时保持宿主系统配置兜底。"""
    plugin, _usage, _clock = cooldown_plugin
    _record_result(plugin)
    _record_result(plugin)
    assert _selected_id(plugin, requested_provider_id='primary') is None
    assert _selected_id(plugin, requested_provider_id='primary', allow_failover=True) == 'backup'
    plugin._providers[1]['enabled'] = False
    event = SimpleNamespace(event_data={'metadata': {}})
    plugin.select_llm_provider(event)
    assert 'selected_provider_id' not in event.event_data
    assert event.event_data['metadata']['provider_selection_status'] == 'unavailable'


@pytest.mark.parametrize('value,expected', [(None, 3), ('bad', 3), (0, 1), (-2, 1), ('5', 5)])
def test_failure_policy_normalizes_invalid_threshold(value, expected):
    """空值和非数字使用默认值，零和负数收敛到最小有效阈值。"""
    provider = AgentTokens._normalize_provider({'failure_threshold': value}, 0)
    assert provider['failure_threshold'] == expected
    assert provider['failure_cooldown_enabled'] is False


def test_string_false_result_is_a_failure(cooldown_plugin):
    """字典事件中的字符串 false 不能被当作成功并重置连续失败。"""
    plugin, usage, _clock = cooldown_plugin
    _record_result(plugin, success='false')
    _record_result(plugin, success='false')
    assert usage['primary']['failure_count'] == 2
    assert _selected_id(plugin) == 'backup'
