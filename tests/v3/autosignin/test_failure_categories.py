"""通知按错误语义归类，但不改写执行结果、历史或重试依据。"""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.plugins.autosignin import AutoSignIn
from app.plugins.autosignin.notification import build_notification_content
from app.plugins.autosignin.result import SiteResult


@pytest.mark.parametrize("message", [
    "Cookie已失效",
    "签到失败，Cookie失效",
    "模拟登录失败： cookie 已失效！",
    "COOKIE 过期",
    "Cookie不正确",
    "Cookie不对",
    "未识别到登录状态",
    "未识别到登录状态；Cookie已失效",
    "Cookie已失效；未识别到登录状态",
    "状态码：404！；未识别到登录状态",
    "未识别到登录状态；状态码：404！",
    "状态码：404！；Cookie已失效",
    "签到失败，Cookie已失效；模拟登录失败，Cookie已失效",
    "Token登录态已失效，请重新登录站点后更新Token",
    "个人 API Key 已失效或权限不足",
    "Authorization 已失效或权限不足",
    "请先登录",
    "需要重新登录",
    "Invalid token",
    "Cookie expired",
    "Token invalid",
    "HTTP 401",
    "状态码：401！",
    "接口信息" * 100 + "；Cookie已失效",
])
def test_login_failures_share_one_semantic_group(message):
    """登录证据缺失与凭据失效共用中性分类，不受附带 404、前缀、大小写和顺序影响。"""
    result = SiteResult("测试站", message, False)
    content = build_notification_content("2026-11-11", "签到", [result], 1, [1], [1])
    assert [(block.title, block.text) for block in content.blocks[3:-1]] == [
        ("Cookie / Token / 登录状态异常", "测试站 ↻"),
    ]
    assert result.message == message
    assert not result.completed


@pytest.mark.parametrize("messages,expected", [
    (["未配置站点地址或Cookie", "未配置站点Token（需填写浏览器登录态Authorization）",
      "缺少个人 API Key 或兼容 Authorization 信息", "缺少站点信息", "Cookie为空"], "站点配置缺失"),
    (["站点被Cloudflare防护，请打开站点浏览器仿真", "无法通过Cloudflare！"], "Cloudflare 防护验证失败"),
    (["验证码错误", "未获取到验证码", "invalid_imagehash"], "验证码获取或校验失败"),
    (["HTTPSConnectionPool: Read timed out. (read timeout=60)", "连接超时", "HTTP 408"], "网络请求超时"),
    (["无法打开网站！", "无法访问网站", "请检查站点连通性", "无法打开签到页",
      "提交签到请求无响应", "ConnectionError: Connection refused", "NameResolutionError: failed to resolve"],
     "网络连接失败"),
    (["状态码：403！", "HTTP 403"], "站点访问被拒绝（HTTP 403）"),
    (["状态码：429！", "HTTP 429"], "站点访问频率受限（HTTP 429）"),
    (["状态码：500！", "HTTP 502", "HTTP 503"], "站点服务异常（HTTP 5xx）"),
    (["状态码：404！", "HTTP 404"], "HTTP 状态异常（404）"),
    (["状态码：466！", "模拟登录失败，状态码：466"], "HTTP 状态异常（466）"),
    (["状态码：404！；状态码：466！", "HTTP 466；HTTP 404"], "HTTP 状态异常（404 / 466）"),
    (["站点返回空页面", "签到接口返回数据异常", "Incorrect CSRF token",
      "未获取到相关签到参数"], "站点页面或接口解析异常"),
    (["未确认签到结果", "接口未确认访问时间更新", "签到页状态未知",
      "提交后未确认到签到成功状态", "未返回可确认的结果"], "站点返回结果未确认"),
    (["", "签到失败", "模拟登录失败"], "未返回具体失败原因"),
])
def test_other_known_failures_keep_separate_categories(messages, expected):
    """配置、防护、验证码、网络、HTTP 与页面问题独立归类，已知同义文案只出现一组。"""
    results = [SiteResult(f"站点{index}", message, False) for index, message in enumerate(messages)]
    ids = list(range(len(results)))
    content = build_notification_content("2026-11-11", "签到", results, len(results), [], ids)
    assert [(block.title, block.text) for block in content.blocks[3:-1]] == [
        (expected, "、".join(result.site_name for result in results)),
    ]


@pytest.mark.parametrize("message,expected", [
    ("未配置站点地址或Cookie；Cookie已失效", "站点配置缺失"),
    ("状态码：503！；Cookie已失效", "Cookie / Token / 登录状态异常"),
    ("站点被Cloudflare防护；未识别到登录状态", "Cloudflare 防护验证失败"),
    ("验证码错误；未识别到登录状态", "验证码获取或校验失败"),
    ("Read timed out；未识别到登录状态", "网络请求超时"),
    ("无法打开网站！；未识别到登录状态", "网络连接失败"),
    ("状态码：403！；未识别到登录状态", "站点访问被拒绝（HTTP 403）"),
    ("状态码：429！；未识别到登录状态", "站点访问频率受限（HTTP 429）"),
    ("状态码：503！；未识别到登录状态", "站点服务异常（HTTP 5xx）"),
    ("Incorrect CSRF token；未识别到登录状态", "站点页面或接口解析异常"),
    ("CSRF Token已失效；未识别到登录状态", "站点页面或接口解析异常"),
    ("CSRF_token已失效；未识别到登录状态", "站点页面或接口解析异常"),
    ("CSRF-token已失效；未识别到登录状态", "站点页面或接口解析异常"),
    ("未确认签到结果；状态码：466！", "HTTP 状态异常（466）"),
    ("状态码：466！；未识别到登录状态", "HTTP 状态异常（466）"),
    ("状态码：404！；状态码：466！；未识别到登录状态", "HTTP 状态异常（404 / 466）"),
])
def test_specific_causes_take_priority_over_missing_login_evidence(message, expected):
    """未识别登录只是证据不足，不能覆盖明确的配置、防护、网络或站点错误。"""
    content = build_notification_content("2026-11-11", "签到", [SiteResult("测试站", message, False)], 1, [], [1])
    assert content.blocks[3].title == expected


def test_unknown_errors_and_completed_results_are_not_reclassified():
    """无法识别的业务原因保留原文，完成状态仍只由结构化结果决定。"""
    messages = ["账号已被封禁", "Cookie有效，站点业务错误", "Cookie未失效，9点前不签到", "相同前缀" * 80 + "原因一",
                "相同前缀" * 80 + "原因二"]
    failed = [SiteResult(f"失败站{index}", message, False) for index, message in enumerate(messages)]
    results = failed + [SiteResult("成功站", "Cookie更新后签到成功", True, True),
                        SiteResult("保号站", "登录成功，签到未确认", False, True)]
    content = build_notification_content("2026-11-11", "签到", results, len(results), [], list(range(len(results))))
    assert [block.title for block in content.blocks[3:6]] == messages[:3]
    assert [block.text for block in content.blocks[3:8]] == [result.site_name for result in failed]
    assert any(block.title == "Cookie更新后签到成功" and block.text == "成功站" for block in content.blocks)
    assert any(block.title == "登录成功，签到未确认" and block.text == "保号站" for block in content.blocks)
    assert content.blocks[1].title == "确认签到 1  ·  仅登录 1  ·  失败 5"


def test_reported_48_sites_have_three_failure_categories_and_keep_all_names():
    """回放 11 月 11 日的 48 站报告，失败从七组归为三组，全部站点及重试标记保留。"""
    from app.modules.telegram.module import TelegramModule
    from app.modules.telegram.telegram import Telegram
    from app.schemas.message import Message

    rows = json.loads((Path(__file__).parent / "fixtures/notification_48.json").read_text())
    results = [SiteResult(row["name"], row["message"], row["success"], row["logged_in"]) for row in rows]
    content = build_notification_content("2026-11-11", "签到", results, 48, list(range(11)), list(range(48)))
    assert content.blocks[1].title == "确认签到 30  ·  仅登录 7  ·  失败 11"
    assert content.blocks[1].text == "已选 48  /  本次 48  /  下次执行 11"
    assert [(block.title, block.text) for block in content.blocks[3:6]] == [
        ("Cookie / Token / 登录状态异常", "我堡 ↻、藏宝阁 ↻、冬樱 ↻、1PTBA ↻、天雪 ↻、铂金学院 ↻、烧包乐园 ↻、AGSVPT ↻、星空 ↻"),
        ("站点配置缺失", "高清杜比 ↻"),
        ("网络连接失败", "雨 ↻"),
    ]
    assert len(content.blocks) == 11
    names = [name.removesuffix(" ↻") for block in content.blocks[3:-1] if block.text
             for name in block.text.split("、")]
    assert sorted(names) == sorted(row["name"] for row in rows)
    assert sum((block.text or "").count("↻") for block in content.blocks[:-1]) == 11
    assert [result.message for result in results] == [row["message"] for row in rows]

    message = Message(title="站点自动签到", text="完整原始结果", rich_content=content,
                      link="https://example.com/#/plugins?tab=installed&id=AutoSignIn")
    chunks = Telegram._build_rich_message_chunks(TelegramModule._notification_rich_message(message))
    body = "".join(chunk["html"] for chunk in chunks)
    assert body.count("<h3>") == 3
    assert body.count("<li>") == 5
    assert all(row["name"] in body for row in rows)
    assert '<a href="https://example.com/#/plugins?tab=installed&amp;id=AutoSignIn">查看详情</a>' in body


@pytest.mark.parametrize("rich_enabled", [True, False])
def test_notification_classification_preserves_history_retry_and_plain_text(monkeypatch, rich_enabled):
    """语义分组只影响富文本摘要，历史、自动更新 Cookie、重试与纯文本保留真实原文。"""
    results = [SiteResult("失效站", "签到失败，未识别到登录状态；Cookie已失效", False),
               SiteResult("未确认站", "签到失败，状态码：404！；未识别到登录状态", False)]
    plugin = object.__new__(AutoSignIn)
    plugin._notify = True
    plugin._rich_notify = rich_enabled
    plugin._clean = False
    plugin._auto_cf = 0
    plugin._retry_keyword = "Cookie已失效"
    for method in ("post_message", "save_data", "update_config", "_clean_history"):
        monkeypatch.setattr(plugin, method, Mock())
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=None))
    monkeypatch.setattr(plugin, "_AutoSignIn__custom_sites", Mock(return_value=[]))
    monkeypatch.setattr(plugin, "eventmanager", SimpleNamespace(send_event=Mock()), raising=False)
    monkeypatch.setattr("app.plugins.autosignin.SitesHelper", lambda: SimpleNamespace(
        get_indexers=lambda: [{"id": index, "name": result.site_name} for index, result in enumerate(results, 1)]))
    monkeypatch.setattr(plugin, "signin_site", Mock(side_effect=lambda site: results[site["id"] - 1]))

    history = plugin._AutoSignIn__do(datetime(2026, 11, 11), "签到", [1, 2])

    assert [history[str(index)]["message"] for index in (1, 2)] == [result.message for result in results]
    saved_history = next(call.kwargs["value"] for call in plugin.save_data.call_args_list
                         if call.kwargs.get("key") == "签到-2026-11-11")
    assert saved_history["retry"] == [1, 2]
    assert saved_history["results"] == history
    plugin.eventmanager.send_event.assert_called_once()
    assert plugin.eventmanager.send_event.call_args.args[1] == {"site_id": 1, "action": "site_refresh"}
    plugin.post_message.assert_called_once()
    notification = plugin.post_message.call_args.kwargs
    assert all(result.message in notification["text"] for result in results)
    assert ("rich_content" in notification) is rich_enabled
    if rich_enabled:
        assert [(block.title, block.text) for block in notification["rich_content"].blocks[3:-1]] == [
            ("Cookie / Token / 登录状态异常", "失效站 ↻、未确认站 ↻"),
        ]
