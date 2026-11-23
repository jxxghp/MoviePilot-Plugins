"""
验证 IP 更新接口的返回契约、二维码图片的缓存策略与通知渠道过滤的降级。
"""

from types import SimpleNamespace
import threading

from fastapi import HTTPException

from app.plugins.updatewechatip import UpdateLogDto, UpdateWeChatIp
from app.schemas.types import NotificationChannel


def _build_plugin() -> UpdateWeChatIp:
    """
    构造不初始化网络会话的插件实例。
    """
    plugin = UpdateWeChatIp.__new__(UpdateWeChatIp)
    plugin._qrcode_key = "qrcode-key"
    return plugin


def test_update_ip_returns_per_app_result() -> None:
    """
    接口返回整体成功标记、更新数量与失败应用列表。
    """
    plugin = _build_plugin()
    plugin._save_ip_config = lambda app_ids=None: [
        SimpleNamespace(status=True, app_id="1000002"),
        SimpleNamespace(status=False, app_id="1000003"),
    ]

    result = plugin.UpdateIp(" 1.2.3.4 ")

    assert result.model_dump(mode="json") == {
        "success": False,
        "ip": "1.2.3.4",
        "updated": 2,
        "failed_app_ids": ["1000003"],
    }


def test_update_ip_rejects_invalid_ipv4() -> None:
    """
    非法地址在写入前以 400 拒绝，不触发任何应用写入。
    """
    plugin = _build_plugin()
    plugin._save_ip_config = lambda app_ids=None: [SimpleNamespace(status=True, app_id="1")]
    try:
        plugin.UpdateIp("1.2.3")
    except HTTPException as err:
        assert err.status_code == 400
    else:
        raise AssertionError("非法 IPv4 未被拒绝")


def test_get_img_disables_cache() -> None:
    """
    二维码含登录凭据，响应必须带 no-store。
    """
    plugin = _build_plugin()
    UpdateWeChatIp._qr_image = (b"\x89PNG\r\n\x1a\n" + b"0" * 8, "image/png")
    token = UpdateWeChatIp._new_img_token()

    response = plugin.get_img("uuid", t=token)

    assert response.headers["cache-control"] == "no-store"
    assert response.media_type == "image/png"


def test_enabled_channels_fall_back_when_manager_missing() -> None:
    """
    取不到模块管理器时退回全部渠道，保证提醒不会静默丢失。
    """
    channels = _build_plugin()._enabled_notify_channels()

    assert NotificationChannel.Wechat in channels
    assert NotificationChannel.Web not in channels
    assert NotificationChannel.WebAgent not in channels


def test_update_log_ignores_unknown_fields_and_bad_time() -> None:
    """
    旧数据结构里的多余字段和非法时间不应让记录还原失败。
    """
    record = UpdateLogDto.from_dict({
        "status": True,
        "ip": "1.1.1.1",
        "app_id": "1000002",
        "result": "ok",
        "UpdateTime": "not-a-time",
        "legacy_extra": {"nested": 1},
    })

    assert record.status is True
    assert record.ip == "1.1.1.1"
    assert record.app_id == "1000002"
    assert record.UpdateTime is not None


def test_update_log_tolerates_missing_fields() -> None:
    """
    缺失字段按默认值还原，而不是让整页渲染抛异常。
    """
    record = UpdateLogDto.from_dict({})

    assert record.status is False
    assert record.ip == ""
    assert record.result == ""


def test_login_defers_wait_to_background_thread() -> None:
    """
    扫码确认的等待放到后台线程，调用方立刻拿到回执。
    """
    plugin = _build_plugin()
    plugin._qrcode_key = "qrcode-key"
    posted = []
    plugin.post_message = lambda **kwargs: posted.append(kwargs)
    handled = threading.Event()

    def worker(*_args) -> None:
        handled.set()

    plugin._login_worker = worker
    plugin._login(NotificationChannel.Wechat, "member")

    assert handled.wait(2), "后台线程没有接手登录流程"
    assert any("正在校验登录状态" in (item.get("text") or "") for item in posted)


def test_qrcode_message_marks_replaced() -> None:
    """
    新二维码覆盖旧二维码时，提示上一次已失效。
    """
    payload = _build_plugin()._qrcode_message(
        NotificationChannel.Wechat, "member", "https://mp.example/qr.png", replaced=True
    )

    assert "上一次待扫码的二维码已失效" in payload["text"]


def test_login_worker_requires_auth_code() -> None:
    """
    扫码结果缺少 auth_code 时立即报错，不去请求登录页，避免拿旧 sid 谎报登录成功。
    """
    plugin = _build_plugin()
    plugin._se = object()
    plugin._check = lambda _key: {"status": "QRCODE_SCAN_SUCC"}
    calls = []
    plugin._loginpage_wx = lambda *args: calls.append(args)
    posted = []
    plugin.post_message = lambda **kwargs: posted.append(kwargs)

    plugin._login_worker(NotificationChannel.Wechat, "member", "qrcode-key")

    assert not calls
    assert any("auth_code" in (item.get("text") or "") for item in posted)


def test_login_worker_stops_when_session_closed() -> None:
    """
    插件停用后残留的登录线程不再发请求，也不推送错误消息。
    """
    plugin = _build_plugin()
    plugin._se = None
    plugin._check = lambda _key: (_ for _ in ()).throw(AssertionError("不应再检查扫码结果"))
    posted = []
    plugin.post_message = lambda **kwargs: posted.append(kwargs)

    plugin._login_worker(NotificationChannel.Wechat, "member", "qrcode-key")

    assert posted == []


def test_login_success_clears_stale_tl_key() -> None:
    """
    无需短信验证的登录成功后，上一轮的 tl_key 不能留到下一次验证码提交。
    """
    plugin = _build_plugin()
    plugin._tl_key = "stale-tl-key"
    plugin._wwrtx_sid = "sid"
    plugin._app_id = "1000002"
    plugin._party_cache_data = {}
    plugin._cron = "*/10 * * * *"
    plugin._enabled = True
    plugin._clear_fail = lambda: None
    plugin.get_config = lambda: {}
    plugin.update_config = lambda _config: None

    plugin._login_success()

    assert plugin._tl_key is None


def test_ip_update_failure_message_reports_total() -> None:
    """
    全部失败且超过 3 个应用时，正文说明失败总数而不是只列前 3 个。
    """
    plugin = _build_plugin()
    plugin._ip = "1.2.3.4"
    posted = []
    plugin.post_message = lambda **kwargs: posted.append(kwargs)
    results = [
        SimpleNamespace(status=False, app_id=f"100000{index}", result="err")
        for index in range(1, 6)
    ]

    plugin._notify_ip_update(results)

    assert "共 5 个应用失败" in posted[0]["text"]


def test_captcha_text_input_without_sms_state() -> None:
    """
    短信验证状态已清空时，聊天框发来 6 位数字应提示重新扫码，而不是拿旧状态提交。
    """
    plugin = _build_plugin()
    plugin._captcha = {}
    plugin._tl_key = None
    submitted = []
    plugin._confirm_captcha = lambda *args: submitted.append(args)
    posted = []
    plugin.post_message = lambda **kwargs: posted.append(kwargs)

    plugin._handle_text_input_event(
        {
            "channel": NotificationChannel.Wechat,
            "userid": "member",
            "payload": {"qrcode_key": "qrcode-key"},
            "input_text": "123456",
        },
        "plugin_input",
    )

    assert not submitted
    assert "未获取到短信验证状态" in posted[0]["text"]
