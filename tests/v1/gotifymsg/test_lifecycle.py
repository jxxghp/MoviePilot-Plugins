"""GotifyMsg 队列线程的生命周期测试。"""

import sys
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

gotify_stub = ModuleType("gotify")
gotify_stub.Gotify = object
sys.modules.setdefault("gotify", gotify_stub)

from app.plugins import gotifymsg as plugin_module  # noqa: E402
from app.plugins.gotifymsg import GotifyMsg  # noqa: E402
from tests.v1._queue_lifecycle import assert_queue_worker_lifecycle  # noqa: E402


def test_worker_timeout_retains_owner_and_retry_seals_tail_messages(monkeypatch):
    """发送被阻塞时首次停止失败并保留线程，释放后重试成功且不再接收消息。"""
    entered = Event()
    release = Event()
    calls = []

    class BlockingGotify:
        """在测试信号释放前阻塞一次 Gotify 通知。"""

        def __init__(self, **_kwargs):
            """接受现有 Gotify 客户端构造参数。"""

        @staticmethod
        def create_message(*_args, **_kwargs):
            """记录发送并等待测试释放信号。"""
            calls.append("send")
            entered.set()
            release.wait(timeout=2)

    monkeypatch.setattr(plugin_module, "Gotify", BlockingGotify)
    with patch("app.plugins.PluginChian"):
        plugin = GotifyMsg()
    plugin.init_plugin({
        "enabled": True,
        "server": "https://gotify.example.com",
        "token": "token",
        "msgtypes": [],
    })

    event = SimpleNamespace(event_data={"title": "title", "text": "body"})
    assert_queue_worker_lifecycle(plugin, event, entered, release, calls)
