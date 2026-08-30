"""邮箱通知插件测试。"""

from unittest.mock import MagicMock, patch

from app.plugins.emailmsg import EmailMsg


def _make_plugin() -> EmailMsg:
    """构造不触发宿主 Chain 依赖的插件实例。"""
    return object.__new__(EmailMsg)


def test_plugin_metadata() -> None:
    """插件元数据应与市场索引保持一致。"""
    plugin = _make_plugin()
    assert plugin.plugin_name == "邮箱通知"
    assert plugin.plugin_version == "1.0.0"
    assert plugin.plugin_config_prefix == "emailmsg_"


def test_get_state_requires_enabled_and_smtp() -> None:
    """启用状态需要同时开启插件并配置 SMTP 服务器、发件人与密码。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._smtp_server = "smtp.qq.com"
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"
    assert plugin.get_state() is True

    plugin._sender = None
    assert plugin.get_state() is False

    plugin._sender = "sender@qq.com"
    plugin._password = None
    assert plugin.get_state() is False

    plugin._password = "auth-code"
    plugin._enabled = False
    assert plugin.get_state() is False


def test_get_form_returns_config_schema() -> None:
    """配置表单应包含启用开关、SMTP 配置、消息类型选择和手动发送功能。"""
    plugin = _make_plugin()
    form, defaults = plugin.get_form()
    assert isinstance(form, list) and form
    assert defaults["enabled"] is False
    assert defaults["smtp_port"] == "465"
    assert defaults["ssl"] is True
    assert defaults["msgtypes"] == []

    # 手动发送功能应包含标题、内容输入框和发送按钮
    import json
    form_str = json.dumps(form, ensure_ascii=False)
    assert "custom_title" in form_str
    assert "custom_text" in form_str
    assert "发送通知" in form_str
    assert "MoviePilotAPI" in form_str


@patch("app.plugins.emailmsg.ServiceConfigHelper")
def test_get_recipients_admin(mock_switch) -> None:
    """admin 范围应返回管理员邮箱。"""
    mock_switch.get_notification_switch.return_value = "admin"
    plugin = _make_plugin()
    plugin._enabled = True

    mock_user = MagicMock()
    mock_user.email = "admin@example.com"
    with patch("app.db.oper.user.UserOper") as mock_user_oper:
        mock_user_oper.return_value.get_by_name.return_value = mock_user
        recipients = plugin._get_recipients(None, None)

    assert recipients == ["admin@example.com"]


@patch("app.plugins.emailmsg.ServiceConfigHelper")
def test_get_recipients_skips_empty_email(mock_switch) -> None:
    """邮箱为空时应跳过该用户。"""
    mock_switch.get_notification_switch.return_value = "admin"
    plugin = _make_plugin()

    mock_user = MagicMock()
    mock_user.email = None
    with patch("app.db.oper.user.UserOper") as mock_user_oper:
        mock_user_oper.return_value.get_by_name.return_value = mock_user
        recipients = plugin._get_recipients(None, None)

    assert recipients == []


@patch("app.plugins.emailmsg.ServiceConfigHelper")
def test_get_recipients_all_dedup(mock_switch) -> None:
    """all 范围应收集所有用户邮箱并去重。"""
    mock_switch.get_notification_switch.return_value = "all"
    plugin = _make_plugin()

    user_a = MagicMock()
    user_a.email = "a@example.com"
    user_b = MagicMock()
    user_b.email = "b@example.com"
    user_c = MagicMock()
    user_c.email = "a@example.com"
    with patch("app.db.oper.user.UserOper") as mock_user_oper:
        mock_user_oper.return_value.list.return_value = [user_a, user_b, user_c]
        recipients = plugin._get_recipients(None, None)

    assert recipients == ["a@example.com", "b@example.com"]


@patch("app.plugins.emailmsg.smtplib")
def test_send_mail_success(mock_smtplib) -> None:
    """SMTP 发送成功时返回 True 并关闭连接，收件人通过 envelope 密送。"""
    plugin = _make_plugin()
    plugin._smtp_server = "smtp.qq.com"
    plugin._smtp_port = "465"
    plugin._ssl = True
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"

    server = MagicMock()
    server.sendmail.return_value = {}
    mock_smtplib.SMTP_SSL.return_value = server

    result = plugin._send_mail(["a@example.com", "b@example.com"], "标题", "正文")

    assert result is True
    mock_smtplib.SMTP_SSL.assert_called_once()
    server.login.assert_called_once_with("sender@qq.com", "auth-code")
    server.sendmail.assert_called_once()
    server.quit.assert_called_once()

    # SMTP envelope 应包含所有收件人
    envelope_recipients = server.sendmail.call_args[0][1]
    assert envelope_recipients == ["a@example.com", "b@example.com"]

    # 邮件内容不应包含 Bcc 头或收件人地址，避免收件人之间互相看到邮箱地址
    msg = server.sendmail.call_args[0][2]
    assert "Bcc:" not in msg
    assert "a@example.com" not in msg
    assert "b@example.com" not in msg


@patch("app.plugins.emailmsg.smtplib")
def test_send_mail_partial_reject(mock_smtplib) -> None:
    """部分收件人被 SMTP 拒收时返回 False。"""
    plugin = _make_plugin()
    plugin._smtp_server = "smtp.qq.com"
    plugin._smtp_port = "465"
    plugin._ssl = True
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"

    server = MagicMock()
    server.sendmail.return_value = {"b@example.com": (550, b"rejected")}
    mock_smtplib.SMTP_SSL.return_value = server

    result = plugin._send_mail(["a@example.com", "b@example.com"], "标题", "正文")

    assert result is False


@patch("app.plugins.emailmsg.smtplib")
def test_send_mail_no_recipients(mock_smtplib) -> None:
    """无收件人时跳过发送并返回 False。"""
    plugin = _make_plugin()
    result = plugin._send_mail([], "标题", "正文")
    assert result is False
    mock_smtplib.SMTP_SSL.assert_not_called()


@patch("app.plugins.emailmsg.smtplib")
def test_send_mail_no_starttls_when_ssl_disabled(mock_smtplib) -> None:
    """未启用 SSL 时使用普通 SMTP 连接，不强制 STARTTLS。"""
    plugin = _make_plugin()
    plugin._smtp_server = "smtp.qq.com"
    plugin._smtp_port = "25"
    plugin._ssl = False
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"

    server = MagicMock()
    server.sendmail.return_value = {}
    mock_smtplib.SMTP.return_value = server

    result = plugin._send_mail(["a@example.com"], "标题", "正文")

    assert result is True
    # 未启用 SSL 时不应调用 starttls，也不应使用 SMTP_SSL
    server.starttls.assert_not_called()
    mock_smtplib.SMTP.assert_called_once()
    mock_smtplib.SMTP_SSL.assert_not_called()
    # 连接应被关闭
    server.quit.assert_called_once()


def test_get_api_declares_send_endpoint() -> None:
    """插件 API 应声明手动发送通知端点。"""
    plugin = _make_plugin()
    apis = plugin.get_api()
    assert len(apis) == 1
    assert apis[0]["path"] == "/send"
    assert apis[0]["methods"] == ["POST"]
    assert apis[0]["auth"] == "bear"
    assert apis[0]["endpoint"] == plugin.send_custom_notification


def test_get_page_returns_intro() -> None:
    """详情页应包含插件介绍卡片。"""
    plugin = _make_plugin()
    page = plugin.get_page()
    assert len(page) == 1
    assert page[0]["component"] == "VCard"


def test_send_custom_notification_requires_enabled() -> None:
    """插件未启用时手动发送应返回失败。"""
    plugin = _make_plugin()
    plugin._enabled = False
    response = plugin.send_custom_notification({"title": "t", "text": "c"})
    assert response.success is False
    assert "未启用" in response.message


def test_send_custom_notification_rejects_empty() -> None:
    """标题和内容都为空时手动发送应返回失败。"""
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._smtp_server = "smtp.qq.com"
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"
    response = plugin.send_custom_notification({"title": "", "text": ""})
    assert response.success is False
    assert "不能同时为空" in response.message


@patch("app.plugins.emailmsg.ServiceConfigHelper")
def test_send_custom_notification_success(mock_switch) -> None:
    """手动发送成功时返回成功响应，并发送给所有用户。"""
    mock_switch.get_notification_switch.return_value = "admin"
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._smtp_server = "smtp.qq.com"
    plugin._smtp_port = "465"
    plugin._ssl = True
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"

    user_a = MagicMock()
    user_a.email = "admin@example.com"
    user_b = MagicMock()
    user_b.email = "user@example.com"
    with patch("app.db.oper.user.UserOper") as mock_user_oper:
        mock_user_oper.return_value.list.return_value = [user_a, user_b]
        with patch("app.plugins.emailmsg.smtplib") as mock_smtplib:
            server = MagicMock()
            server.sendmail.return_value = {}
            mock_smtplib.SMTP_SSL.return_value = server
            response = plugin.send_custom_notification({"title": "标题", "text": "内容"})

    assert response.success is True
    assert "发送成功" in response.message
    assert "admin@example.com" in response.message
    assert "user@example.com" in response.message


@patch("app.plugins.emailmsg.ServiceConfigHelper")
def test_send_custom_notification_no_recipient(mock_switch) -> None:
    """无收件人时手动发送应返回失败。"""
    mock_switch.get_notification_switch.return_value = "admin"
    plugin = _make_plugin()
    plugin._enabled = True
    plugin._smtp_server = "smtp.qq.com"
    plugin._sender = "sender@qq.com"
    plugin._password = "auth-code"

    with patch("app.db.oper.user.UserOper") as mock_user_oper:
        mock_user_oper.return_value.list.return_value = []
        response = plugin.send_custom_notification({"title": "标题", "text": "内容"})

    assert response.success is False
    assert "未获取到收件人" in response.message
