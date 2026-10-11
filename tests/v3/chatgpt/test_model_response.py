"""模型响应边界回归：真实 LangChain 空候选、明确拒答、输入清洗和通知节流。"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from openai.types.chat import ChatCompletion

from app.plugins.chatgpt import DEFAULT_RECOGNIZE_PROMPT
from app.plugins.chatgpt.openai import OpenAi
from app.core.event import eventmanager
from app.schemas.types import ChainEventType
from tests.v3.chatgpt.test_plugin import _mocked_openai, _plugin


@pytest.mark.parametrize("filename,expected", [
    (
        "Chi Qing Nv Zi 1992 1080p WEB-DL H264 AAC2.0-CSWEB"
        "[痴情女子 | Chi Qing Nv Zi | 类型:  | 导演: 刘国权 | 编剧: 李宝林 | 演员: 周里京/瞿颖/辛颖 | ARDTU]",
        "Chi Qing Nv Zi 1992 1080p WEB-DL H264 AAC2.0-CSWEB[痴情女子 | Chi Qing Nv Zi]",
    ),
    (
        "[LoliHouse] 转生后的大圣女 / Daiseijo - 03 [WebRip 1080p HEVC-10bit AAC][简繁内封字幕]",
        "转生后的大圣女 / Daiseijo - 03 [WebRip 1080p HEVC-10bit AAC][简繁内封字幕]",
    ),
    ("[lOLi_house] Title S02E03 2026 [1080p][导演剪辑版]", "Title S02E03 2026 [1080p][导演剪辑版]"),
    ("[痴情女子] 1992 [导演：刘国权]", "[痴情女子] 1992"),
    ("[ARDTU] Title", "Title"),
    ("周杰伦 - 晴天 [叶惠美] 2003 FLAC", "周杰伦 - 晴天 [叶惠美] 2003 FLAC"),
    ("LoliHouse Love 2026 [OtherGroup]", "LoliHouse Love 2026 [OtherGroup]"),
])
def test_filename_cleanup_preserves_recognition_fields(filename, expected):
    """仅删除可确认的噪音标签，片名、别名、集数、年份、技术信息与音乐要素仍可识别。"""
    client = OpenAi(api_key="key", model="model")
    llm = MagicMock()
    llm.generate.return_value = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content='{"name":"Title"}'))]],
    )
    with patch.object(client, "_get_llm", return_value=llm):
        assert client.get_media_name(filename) == {"name": "Title"}
    assert llm.generate.call_args.args[0][0][1].content == expected


@pytest.mark.parametrize("choices,error_code", [
    ([], "empty_response"),
    ([{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop", "index": 0}], "empty_response"),
    ([{"message": {"role": "assistant", "content": "", "refusal": "blocked"}, "finish_reason": "stop", "index": 0}], "model_refusal"),
    ([{"message": {"role": "assistant", "content": '{"name":"Unsafe"}'}, "finish_reason": "content_filter", "index": 0}], "model_refusal"),
])
def test_real_langchain_empty_and_refused_responses(choices, error_code):
    """真实 OpenAI 适配器和 LangChain 生成链路遇到空 choices 时仍保留用量并返回友好失败。"""
    llm = ChatOpenAI(api_key="test-key", model="test-model")
    completion = ChatCompletion.model_validate({
        "id": "test", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": choices,
        "usage": {"prompt_tokens": 36, "completion_tokens": 0, "total_tokens": 36},
    })
    chat_result = llm._create_chat_result(completion)
    client = OpenAi(api_key="key", model="model")
    with patch.object(client, "_get_llm", return_value=llm), \
            patch.object(ChatOpenAI, "_generate", return_value=chat_result) as generate:
        result = client.get_media_name("Title")
    assert result["errorCode"] == error_code
    assert "list index out of range" not in result["errorMsg"]
    assert result["content"] == ""
    assert client.get_last_usage() == {"input_tokens": 36, "output_tokens": 0, "total_tokens": 36}
    generate.assert_called_once()


@pytest.mark.parametrize("message,error_code", [
    (AIMessage(content="", response_metadata={"finish_reason": "SAFETY"}), "model_refusal"),
    (AIMessage(content="", response_metadata={"prompt_feedback": {"block_reason": 1}}), "model_refusal"),
    (AIMessage(content=[{"type": "refusal", "refusal": "blocked"}]), "model_refusal"),
    (AIMessage(content=[{"type": "thinking", "thinking": "reasoning only"}]), "empty_response"),
])
def test_provider_refusal_metadata_and_non_text_output(message, error_code):
    """原生供应商安全元数据和 Responses 拒答块可识别，仅推理输出视为空文本。"""
    llm = MagicMock()
    llm.generate.return_value = LLMResult(generations=[[ChatGeneration(message=message)]])
    client = OpenAi(api_key="key", model="model")
    with patch.object(client, "_get_llm", return_value=llm):
        assert client.get_media_name("Title")["errorCode"] == error_code


@pytest.mark.parametrize("error", [IndexError("list index out of range"), RuntimeError("connection failed")])
def test_unrelated_errors_are_not_labeled_as_safety_blocks(error):
    """模型内部或初始化异常没有空候选证据时保留原错误，避免误判为安全审查。"""
    client = OpenAi(api_key="key", model="model")
    llm = MagicMock()
    llm.generate.side_effect = error
    with patch.object(client, "_get_llm", return_value=llm):
        result = client.get_media_name("Title")
    assert result["errorMsg"] == str(error)
    assert "errorCode" not in result


def test_failed_recognition_retries_without_cache():
    """空候选失败仍统计每次调用，重试可成功，同类通知节流且不缓存失败。"""
    plugin = _plugin({"notify": True})
    error = {"errorCode": "empty_response", "errorMsg": "模型未返回候选结果（空 choices）"}
    with _mocked_openai(plugin, error) as client, patch.object(plugin, "post_message") as notify, \
            patch.object(plugin, "save_data"), patch("app.plugins.chatgpt.time.monotonic", side_effect=[0, 299, 300]):
        for _ in range(3):
            assert plugin._invoke_recognition("Title", "", DEFAULT_RECOGNIZE_PROMPT) is None
        assert client.get_media_name.call_count == 3
        assert notify.call_count == 2
        assert plugin._get_cached_result("Title") is None
        assert plugin._usage_stats["failed_count"] == 3
        client.get_media_name.return_value = {"name": "Title", "year": "2026"}
        assert plugin._invoke_recognition("Title", "", DEFAULT_RECOGNIZE_PROMPT)["name"] == "Title"
        assert plugin._get_cached_result("Title")["name"] == "Title"


def test_failed_recognition_leaves_event_unresolved():
    """明确拒答不写回名称或占用事件来源，保留宿主和其他插件后续识别机会。"""
    plugin = _plugin()
    with _mocked_openai(plugin, {"errorCode": "model_refusal", "errorMsg": "模型拒答"}), \
            patch.object(plugin, "save_data"):
        result = eventmanager.send_event(ChainEventType.NameRecognize, {"title": "Title"})
    assert not result.event_data.get("name")
    assert not result.event_data.get("source_plugin")


def test_normal_response_then_empty_candidates_resets_usage():
    """正常 fenced JSON 仍可解析，下一次空候选不沿用前次 token 统计。"""
    client = OpenAi(api_key="key", model="model")
    llm = MagicMock()
    message = AIMessage(
        content='```json\n{"name":"Title","year":"2026","episode":3}\n```',
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        response_metadata={"prompt_feedback": {"block_reason": "BLOCK_REASON_UNSPECIFIED"}},
    )
    llm.generate.side_effect = [
        LLMResult(generations=[[ChatGeneration(message=message)]]),
        LLMResult(generations=[]),
    ]
    with patch.object(client, "_get_llm", return_value=llm):
        assert client.get_media_name("Title") == {"name": "Title", "year": "2026", "episode": 3}
        assert client.get_last_usage()["total_tokens"] == 20
        assert client.get_media_name("Other")["errorCode"] == "empty_response"
        assert client.get_last_usage()["total_tokens"] == 0


def test_concurrent_model_errors_send_one_notification():
    """并发识别失败共享节流锁，避免同一时间发送重复模型错误通知。"""
    plugin = _plugin({"notify": True})
    with patch.object(plugin, "post_message") as notify:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: plugin._notify_error("空候选", error_code="empty_response"), range(16)))
    notify.assert_called_once()


def test_other_errors_keep_existing_notification_behavior():
    """网络与配置等普通错误继续按通知开关发送，关闭通知时不消耗模型错误节流窗口。"""
    plugin = _plugin({"notify": False})
    with patch.object(plugin, "post_message") as notify:
        plugin._notify_error("空候选", error_code="empty_response")
        notify.assert_not_called()
        plugin._notify = True
        plugin._notify_error("空候选", error_code="empty_response")
        plugin._notify_error("connection failed")
        plugin._notify_error("connection failed")
        assert notify.call_count == 3
