"""IyuuMsg 队列线程的生命周期测试。"""

from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from app.plugins import iyuumsg as plugin_module
from app.plugins.iyuumsg import IyuuMsg
from tests.v1._queue_lifecycle import assert_queue_worker_lifecycle


def test_worker_timeout_retains_owner_and_retry_seals_tail_messages(monkeypatch):
    """发送被阻塞时首次停止失败并保留线程，释放后重试成功且不再接收消息。"""
    entered = Event()
    release = Event()
    calls = []

    class BlockingRequest:
        """在测试信号释放前阻塞一次 IYUU HTTP 请求。"""

        @staticmethod
        def get_res(_url):
            """记录发送并等待测试释放信号。"""
            calls.append("send")
            entered.set()
            release.wait(timeout=2)
            return None

    monkeypatch.setattr(plugin_module, "RequestUtils", BlockingRequest)
    with patch("app.plugins.PluginChian"):
        plugin = IyuuMsg()
    plugin.init_plugin({"enabled": True, "token": "token", "msgtypes": []})

    event = SimpleNamespace(event_data={"title": "title", "text": "body"})
    assert_queue_worker_lifecycle(plugin, event, entered, release, calls)
