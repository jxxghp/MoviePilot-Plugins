"""AppriseMsg 队列线程的生命周期测试。"""

import sys
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

apprise_stub = ModuleType("apprise")
apprise_stub.Apprise = object
sys.modules.setdefault("apprise", apprise_stub)

from app.plugins import apprisemsg as plugin_module  # noqa: E402
from app.plugins.apprisemsg import AppriseMsg  # noqa: E402
from tests.v1._queue_lifecycle import assert_queue_worker_lifecycle  # noqa: E402


def test_worker_timeout_retains_owner_and_retry_seals_tail_messages(monkeypatch):
    """发送被阻塞时首次停止失败并保留线程，释放后重试成功且不再接收消息。"""
    entered = Event()
    release = Event()
    calls = []

    class BlockingApprise:
        """在测试信号释放前阻塞一次 Apprise 通知。"""

        @staticmethod
        def add(_url):
            """接受测试通知地址。"""

        @staticmethod
        def notify(**_kwargs):
            """记录发送并等待测试释放信号。"""
            calls.append("send")
            entered.set()
            release.wait(timeout=2)

    monkeypatch.setattr(plugin_module.apprise, "Apprise", BlockingApprise)
    with patch("app.plugins.PluginChian"):
        plugin = AppriseMsg()
    plugin.init_plugin({"enabled": True, "url": "json://", "msgtypes": []})

    event = SimpleNamespace(event_data={"title": "title", "text": "body"})
    assert_queue_worker_lifecycle(plugin, event, entered, release, calls)
