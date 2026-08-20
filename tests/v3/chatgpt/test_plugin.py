"""ChatGPT 插件单测：音乐标题辅助识别、提示词分离与缓存命名空间隔离。

依赖 MoviePilot 后端（app.*）与插件包：根 conftest 会先隔离 CONFIG_DIR，再通过生产
命名空间暴露对应插件源码。
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.core.event import eventmanager
from app.core.plugin import PluginManager
from app.schemas.types import ChainEventType
from app.plugins.chatgpt import (  # noqa: E402
    DEFAULT_MUSIC_RECOGNIZE_PROMPT,
    DEFAULT_RECOGNIZE_PROMPT,
    MUSIC_NAME_RECOGNIZE_EVENT,
    ChatGPT,
)
from app.plugins.chatgpt.openai import OpenAi  # noqa: E402


def _plugin(config: dict = None) -> ChatGPT:
    """创建启用状态的插件实例，隔离缓存与统计的持久化副作用。

    链式事件分发依赖 PluginManager 路由到运行态插件实例，这里同步注册测试实例，
    保证 send_event 能真实调度到本插件处理器；与当前用例无关的宿主 Chain 组合根不在
    插件仓测试中初始化。
    """
    with patch("app.plugins.PluginChian"):
        plugin = ChatGPT()
    with patch.object(plugin, "get_data", return_value=None), patch.object(plugin, "save_data"):
        plugin.init_plugin({"enabled": True, **(config or {})})
    plugin_manager = PluginManager()
    plugin_manager.plugins[plugin.__class__.__name__] = plugin.__class__
    plugin_manager.running_plugins[plugin.__class__.__name__] = plugin
    return plugin


@contextmanager
def _mocked_openai(plugin: ChatGPT, response: dict):
    """给插件注入模拟 LLM 客户端，补丁在事件分发期间保持生效。"""
    openai = MagicMock()
    openai.get_media_name.return_value = response
    openai.get_last_usage.return_value = {}
    plugin.openai = openai
    with patch.object(plugin, "_resolve_model_config", return_value=({"source": "system"}, "")), \
            patch.object(plugin, "init_openai", return_value=True):
        yield openai


def test_music_event_type_available():
    """主仓应提供音乐名称识别链式事件，插件初始化后注册处理器。"""
    assert MUSIC_NAME_RECOGNIZE_EVENT is ChainEventType.MusicNameRecognize
    _plugin()
    assert eventmanager.check(ChainEventType.MusicNameRecognize)


def test_recognize_music_uses_music_prompt_and_writes_fields():
    """音乐识别事件应使用音乐提示词调用模型，并回写曲名、艺术家、专辑、年份。"""
    plugin = _plugin()
    with _mocked_openai(plugin, {"name": "晴天", "artist": "周杰伦", "album": "叶惠美", "year": "2003"}) as openai:
        result = eventmanager.send_event(
            ChainEventType.MusicNameRecognize,
            {"title": "周杰伦 - 晴天 - 叶惠美 2003 FLAC"},
        )
        openai.get_media_name.assert_called_once()
        _, kwargs = openai.get_media_name.call_args
        assert kwargs.get("prompt") == DEFAULT_MUSIC_RECOGNIZE_PROMPT

    assert result is not None
    event_data = result.event_data
    assert event_data["name"] == "晴天"
    assert event_data["artist"] == "周杰伦"
    assert event_data["album"] == "叶惠美"
    assert event_data["year"] == "2003"
    assert event_data["source_plugin"] == plugin.__class__.__name__


def test_recognize_music_skips_resolved_event():
    """已有插件或名称结果的音乐识别事件不应重复处理。"""
    plugin = _plugin()
    with _mocked_openai(plugin, {"name": "晴天"}) as openai:
        eventmanager.send_event(
            ChainEventType.MusicNameRecognize,
            {"title": "晴天 FLAC", "name": "晴天", "source_plugin": "Other"},
        )
        openai.get_media_name.assert_not_called()


def test_recognize_video_uses_video_prompt():
    """影视识别事件仍使用影视提示词，与音乐提示词相互独立。"""
    plugin = _plugin()
    with _mocked_openai(plugin, {"name": "星际穿越", "year": "2014"}) as openai:
        result = eventmanager.send_event(ChainEventType.NameRecognize, {"title": "Interstellar.2014.1080p"})
        _, kwargs = openai.get_media_name.call_args
        assert kwargs.get("prompt") == DEFAULT_RECOGNIZE_PROMPT

    assert result is not None
    assert result.event_data["name"] == "星际穿越"


def test_music_recognize_switch_disables_handler():
    """关闭音乐识别开关后，音乐事件处理器应被禁用。"""
    _plugin({"music_recognize": False})
    assert not eventmanager.check(ChainEventType.MusicNameRecognize)
    # 影视识别不受影响
    assert eventmanager.check(ChainEventType.NameRecognize)
    # 恢复开关后重新启用
    _plugin()
    assert eventmanager.check(ChainEventType.MusicNameRecognize)


def test_cache_namespace_isolation():
    """影视与音乐缓存使用不同命名空间，相同标题互不覆盖。"""
    plugin = _plugin()
    with patch.object(plugin, "save_data"):
        plugin._cache_result("晴天", {"name": "晴天", "artist": "周杰伦"}, namespace="music:")
        plugin._cache_result("晴天", {"name": "晴天", "year": "2003"})

    music_cached = plugin._get_cached_result("晴天", namespace="music:")
    video_cached = plugin._get_cached_result("晴天")
    assert music_cached["artist"] == "周杰伦"
    assert video_cached.get("artist") is None
    assert video_cached["year"] == "2003"


def test_openai_prompt_parameter_overrides_default():
    """get_media_name 的 prompt 参数应覆盖初始化提示词，缺省时回退默认提示词。"""
    client = OpenAi(api_key="key", model="model", customize_prompt="DEFAULT-PROMPT")

    created_llms = []

    def _fake_llm():
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='{"name": "晴天"}', usage_metadata={})
        created_llms.append(llm)
        return llm

    with patch.object(client, "_get_llm", side_effect=_fake_llm):
        client.get_media_name("title", prompt="MUSIC-PROMPT")
        first_messages = created_llms[-1].invoke.call_args[0][0]
        assert first_messages[0].content == "MUSIC-PROMPT"

        client.get_media_name("title")
        second_messages = created_llms[-1].invoke.call_args[0][0]
        assert second_messages[0].content == "DEFAULT-PROMPT"
