"""WPUSH 消息通知插件测试。"""

from unittest.mock import MagicMock, patch

from app.plugins.wpushmsg import WPUSH_SEND_URL, WPushMsg


def _make_plugin() -> WPushMsg:
    """构造不触发宿主 Chain 依赖的插件实例。"""
    return object.__new__(WPushMsg)


def test_plugin_metadata() -> None:
    """插件元数据应与市场索引保持一致。"""
    plugin = _make_plugin()
    assert plugin.plugin_name == "WPUSH消息推送"
    assert plugin.plugin_version == "1.0.0"
    assert plugin.plugin_config_prefix == "wpushmsg_"
    assert plugin.plugin_author == "Alone88"
    assert plugin.plugin_icon == "WPush_A.png"


def test_get_state_requires_enabled_and_apikey() -> None:
    """启用状态需要同时开启插件并配置 API Key。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._apikey = "WPUSHtestkey"
    assert plugin.get_state() is True

    plugin._apikey = None
    assert plugin.get_state() is False

    plugin._apikey = "WPUSHtestkey"
    plugin._enabled = False
    assert plugin.get_state() is False


def test_init_plugin_defaults() -> None:
    """init_plugin 应规范化空配置与默认渠道。"""
    plugin = _make_plugin()
    plugin.init_plugin({})
    assert plugin._enabled is False
    assert plugin._apikey is None
    assert plugin._channel == "wechat"
    assert plugin._topic_code is None
    assert plugin._msgtypes == []

    plugin.init_plugin(
        {
            "enabled": True,
            "apikey": "  WPUSHabc  ",
            "channel": "feishu",
            "topic_code": " topic1 ",
            "msgtypes": ["Download"],
        }
    )
    assert plugin._enabled is True
    assert plugin._apikey == "WPUSHabc"
    assert plugin._channel == "feishu"
    assert plugin._topic_code == "topic1"
    assert plugin._msgtypes == ["Download"]


def test_get_form_returns_config_schema() -> None:
    """配置表单应包含启用开关、API Key、渠道、主题与消息类型。"""
    plugin = _make_plugin()
    form, defaults = plugin.get_form()
    assert isinstance(form, list) and form
    assert defaults["enabled"] is False
    assert defaults["channel"] == "wechat"
    assert defaults["apikey"] == ""
    assert defaults["topic_code"] == ""
    assert defaults["msgtypes"] == []

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "apikey" in form_str
    assert "channel" in form_str
    assert "topic_code" in form_str
    assert "code===0" in form_str


@patch("app.plugins.wpushmsg.RequestUtils")
def test_send_wpush_success_code_zero(mock_request_utils) -> None:
    """仅当响应 JSON code===0 时判定成功。"""
    plugin = _make_plugin()
    plugin._apikey = "WPUSHsecret"
    plugin._channel = "wechat"
    plugin._topic_code = None

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"code": 0, "message": "ok"}
    mock_request_utils.return_value.post_res.return_value = response

    assert plugin._send_wpush("标题", "正文") is True
    mock_request_utils.assert_called_once_with(content_type="application/json")
    kwargs = mock_request_utils.return_value.post_res.call_args
    assert kwargs[0][0] == WPUSH_SEND_URL
    assert kwargs[1]["allow_redirects"] is False
    payload = kwargs[1]["json"]
    assert payload["apikey"] == "WPUSHsecret"
    assert payload["title"] == "标题"
    assert payload["content"] == "正文"
    assert payload["channel"] == "wechat"
    assert "topic_code" not in payload


@patch("app.plugins.wpushmsg.RequestUtils")
def test_send_wpush_rejects_nonzero_code(mock_request_utils) -> None:
    """HTTP 200 但 code!=0 应判定失败（不同于 PushPlus 的 200）。"""
    plugin = _make_plugin()
    plugin._apikey = "WPUSHsecret"
    plugin._channel = "wechat"
    plugin._topic_code = "t1"

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"code": 200, "message": "not success for wpush"}
    mock_request_utils.return_value.post_res.return_value = response

    assert plugin._send_wpush("标题", "正文") is False
    payload = mock_request_utils.return_value.post_res.call_args[1]["json"]
    assert payload["topic_code"] == "t1"


@patch("app.plugins.wpushmsg.RequestUtils")
def test_send_wpush_http_error(mock_request_utils) -> None:
    """非 HTTP 200 应判定失败。"""
    plugin = _make_plugin()
    plugin._apikey = "WPUSHsecret"
    plugin._channel = "wechat"
    plugin._topic_code = None

    response = MagicMock()
    response.status_code = 500
    response.reason = "Internal Server Error"
    mock_request_utils.return_value.post_res.return_value = response

    assert plugin._send_wpush("标题", "正文") is False


@patch("app.plugins.wpushmsg.RequestUtils")
def test_send_wpush_no_response(mock_request_utils) -> None:
    """无响应时应判定失败。"""
    plugin = _make_plugin()
    plugin._apikey = "WPUSHsecret"
    plugin._channel = "wechat"
    plugin._topic_code = None
    mock_request_utils.return_value.post_res.return_value = None

    assert plugin._send_wpush("标题", "正文") is False


def test_send_skips_when_channel_set() -> None:
    """事件已指定专用通知渠道时不发送。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._apikey = "WPUSHsecret"
    plugin._msgtypes = []

    event = MagicMock()
    event.event_data = {
        "channel": "Telegram",
        "title": "t",
        "text": "b",
        "type": None,
    }

    with patch.object(plugin, "_send_wpush") as mock_send:
        plugin.send(event)
        mock_send.assert_not_called()


def test_send_skips_filtered_msgtype() -> None:
    """未勾选的消息类型应跳过发送。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._apikey = "WPUSHsecret"
    plugin._msgtypes = ["Download"]

    msg_type = MagicMock()
    msg_type.name = "Organize"
    msg_type.value = "整理"

    event = MagicMock()
    event.event_data = {
        "channel": None,
        "title": "t",
        "text": "b",
        "type": msg_type,
    }

    with patch.object(plugin, "_send_wpush") as mock_send:
        plugin.send(event)
        mock_send.assert_not_called()


def test_send_invokes_wpush_when_ready() -> None:
    """启用且未指定专用渠道时应调用 WPUSH 发送。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._apikey = "WPUSHsecret"
    plugin._msgtypes = []

    event = MagicMock()
    event.event_data = {
        "channel": None,
        "title": "标题",
        "text": "正文",
        "type": None,
    }

    with patch.object(plugin, "_send_wpush", return_value=True) as mock_send:
        plugin.send(event)
        mock_send.assert_called_once_with("标题", "正文")


@patch("app.plugins.wpushmsg.logger")
@patch("app.plugins.wpushmsg.RequestUtils")
def test_send_wpush_does_not_log_apikey(mock_request_utils, mock_logger) -> None:
    """成功/失败日志不得包含 apikey。"""
    plugin = _make_plugin()
    plugin._apikey = "WPUSHsupersecretkey"
    plugin._channel = "wechat"
    plugin._topic_code = None

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"code": 1, "message": "bad"}
    mock_request_utils.return_value.post_res.return_value = response

    plugin._send_wpush("标题", "正文")

    logged = " ".join(
        str(call.args[0]) if call.args else ""
        for call in mock_logger.warn.call_args_list
        + mock_logger.info.call_args_list
        + mock_logger.error.call_args_list
    )
    assert "WPUSHsupersecretkey" not in logged
