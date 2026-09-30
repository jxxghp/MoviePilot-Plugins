"""Agent影视助手飞书入口测试：改用宿主飞书长连接后的事件解析与连接生命周期。"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

from app.plugins.agentresourceofficer import feishu_channel
from app.plugins.agentresourceofficer.feishu_channel import FeishuChannel, _FeishuLongConnectionRuntime


def _event(event_type: str = "im.message.receive_v1", text: str = "帮助") -> bytes:
    """构造长连接收到的 2.0 版事件报文。"""
    return json.dumps(
        {
            "schema": "2.0",
            "header": {"event_id": "evt-1", "event_type": event_type},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_user"}},
                "message": {
                    "chat_id": "oc_chat",
                    "message_type": "text",
                    "content": json.dumps({"text": text}),
                },
            },
        }
    ).encode("utf-8")


def _channel() -> FeishuChannel:
    """构造已启用且放行全部会话的渠道，回复改为记录。"""
    channel = FeishuChannel(MagicMock())
    channel.enabled = True
    channel.allow_all = True
    channel.app_id = "cli_app"
    channel.app_secret = "secret"
    channel.reply_text = MagicMock()
    return channel


class _FakeConnection:
    """替代宿主长连接：run() 阻塞到 stop()，记录构造参数。"""

    instances = []

    def __init__(self, app_id, app_secret, on_event, name):
        self.app_id = app_id
        self.on_event = on_event
        self.stopped = threading.Event()
        _FakeConnection.instances.append(self)

    def run(self):
        self.stopped.wait(5)

    def stop(self):
        self.stopped.set()


def test_message_event_is_parsed_from_json():
    """接收消息事件按 JSON 字段解析出会话、发送者和文本。"""
    runtime = _FeishuLongConnectionRuntime()
    channel = _channel()
    runtime._channel = channel

    runtime._on_event(_event(text="帮助"))

    channel.reply_text.assert_called_once()
    chat_id, open_id, _ = channel.reply_text.call_args.args
    assert (chat_id, open_id) == ("oc_chat", "ou_user")


def test_non_message_events_are_ignored():
    """其他事件类型不进入命令处理。"""
    runtime = _FeishuLongConnectionRuntime()
    channel = _channel()
    channel.handle_long_connection_event = MagicMock()
    runtime._channel = channel

    runtime._on_event(_event(event_type="im.chat.member.bot.added_v1"))

    channel.handle_long_connection_event.assert_not_called()


def test_stop_closes_connection_and_credential_change_reconnects(monkeypatch):
    """停止会关闭连接并结束线程；凭证变更时关闭旧连接再建立新连接。"""
    _FakeConnection.instances.clear()
    monkeypatch.setattr(feishu_channel, "FeishuLongConnection", _FakeConnection)
    runtime = _FeishuLongConnectionRuntime()
    channel = _channel()

    runtime.start(channel)
    first = _FakeConnection.instances[0]
    assert runtime.is_running()

    runtime.start(channel)
    assert len(_FakeConnection.instances) == 1

    channel.app_id = "cli_other"
    runtime.start(channel)
    assert first.stopped.is_set()
    assert len(_FakeConnection.instances) == 2
    assert _FakeConnection.instances[1].app_id == "cli_other"

    runtime.stop()
    assert _FakeConnection.instances[1].stopped.is_set()
    assert not runtime.is_running()


def test_missing_host_transport_reports_upgrade(monkeypatch):
    """宿主未提供飞书长连接时不启动，并在健康检查中提示升级主程序。"""
    monkeypatch.setattr(feishu_channel, "FeishuLongConnection", None)
    channel = _channel()

    channel.runtime.start(channel)
    health = channel.health()

    assert not channel.is_running()
    assert health["sdk_available"] is False
    assert "MoviePilot>=v3.0.11" in health["missing_requirements"]


def test_plugin_import_does_not_load_lark_oapi():
    """加载插件不再导入 lark-oapi。"""
    script = """
import json, sys
from tests._bootstrap import prepare_v3_backend
prepare_v3_backend()
import app.plugins.agentresourceofficer
print(json.dumps(sorted(m for m in sys.modules if m.split(".")[0] == "lark_oapi")))
"""
    repo_root = Path(__file__).parents[3]
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo_root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
