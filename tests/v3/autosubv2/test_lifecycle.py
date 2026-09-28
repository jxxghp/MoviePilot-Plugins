"""AutoSubv2 初始化、事件、持久化与停止生命周期测试。"""

from __future__ import annotations

from datetime import datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.chain.context import (
    ChainRuntimeContext,
    configure_chain_runtime_context_provider,
)
from app.application.configuration import ChainRuntimeConfig
from app.testing import stub_modules


class _Cache:
    """为未进入被测路径的翻译缓存提供最小第三方依赖替身。"""

    def __init__(self, *args, **kwargs):
        self._values = {}

    def get(self, key):
        return self._values.get(key)

    def set(self, key, value):
        self._values[key] = value

    def delete(self, key):
        self._values.pop(key, None)


iso639 = ModuleType("iso639")
srt = ModuleType("srt")
cacheout = ModuleType("cacheout")
cacheout.Cache = _Cache

with stub_modules({"iso639": iso639, "srt": srt, "cacheout": cacheout}):
    from app.plugins.autosubv2 import (
        AutoSubv2,
        TaskItem,
        TaskSource,
        TaskStatus,
    )


def _chain_context() -> ChainRuntimeContext:
    """构造不启动宿主服务的最小 Chain 组合根。"""
    message_queue = Mock()
    message_queue.bind.return_value = Mock()
    return ChainRuntimeContext(
        module_manager=Mock(),
        plugin_manager=Mock(),
        event_manager=Mock(),
        message_oper=Mock(),
        message_helper=Mock(),
        file_cache=Mock(),
        async_file_cache=Mock(),
        message_queue=message_queue,
        module_dispatcher_factory=Mock(return_value=Mock()),
        site_repository=Mock(),
        subscription_repository=Mock(),
        subscription_mutation_scope=Mock(),
        sync_subscription_mutation_scope=Mock(),
        subscription_delete_scope=Mock(),
        sync_subscription_delete_scope=Mock(),
        subscription_completion_scope=Mock(),
        rule_group_mutation_scope=Mock(),
        site_reference_mutation_scope=Mock(),
        download_history_repository=Mock(),
        transfer_history_repository=Mock(),
        transfer_admission_repository=Mock(),
        transfer_execution_repository=Mock(),
        media_server_repository=Mock(),
        download_failure_repository=Mock(),
        user_repository=Mock(),
        configuration=ChainRuntimeConfig(media_extensions=(".mkv",)),
    )


@pytest.fixture
def plugin(monkeypatch):
    """装配真实构造路径；依赖 monkeypatch 以便先停线程再还原用例补丁。"""
    configure_chain_runtime_context_provider(_chain_context)
    instance = AutoSubv2()
    try:
        yield instance
    finally:
        if instance.get_state():
            instance.stop_service()
        configure_chain_runtime_context_provider(None)


def test_load_tasks_restores_persisted_task_contract(plugin, monkeypatch) -> None:
    """插件数据中的枚举与时间字段必须恢复为运行时任务对象。"""
    monkeypatch.setattr(plugin, "get_data", lambda key: {
        "task-1": {
            "task_id": "task-1",
            "video_file": "/media/example.mkv",
            "source": "event",
            "add_time": "2026-08-31T10:00:00",
            "status": "completed",
            "complete_time": "2026-08-31T10:01:00",
        }
    })

    tasks = plugin.load_tasks()

    assert tasks["task-1"] == TaskItem(
        task_id="task-1",
        video_file="/media/example.mkv",
        source=TaskSource.EVENT,
        add_time=datetime(2026, 8, 31, 10, 0),
        status=TaskStatus.COMPLETED,
        complete_time=datetime(2026, 8, 31, 10, 1),
    )


def test_transfer_event_enqueues_only_media_files(plugin, monkeypatch) -> None:
    """入库事件只把宿主声明的媒体扩展名加入字幕任务队列。"""
    plugin._listen_transfer_event = True
    added = []
    monkeypatch.setattr(plugin, "add_task", lambda path, source: added.append((path, source)))
    event = SimpleNamespace(event_data={
        "mediainfo": SimpleNamespace(title="Example", original_language="en"),
        "transferinfo": SimpleNamespace(
            file_list_new=["/media/example.mkv", "/media/example.nfo"],
        ),
    })

    plugin.on_transfer_complete(event)

    assert added == [("/media/example.mkv", TaskSource.EVENT)]


def test_init_and_stop_own_consumer_and_persist_pending_tasks(
        plugin,
        monkeypatch,
        tmp_path,
) -> None:
    """启停必须完整持有消费者线程，并把未完成任务标记失败后持久化。"""
    persisted = []
    monkeypatch.setattr(plugin, "load_tasks", lambda: {})
    monkeypatch.setattr(plugin, "save_data", lambda key, value: persisted.append((key, value)))
    monkeypatch.setattr(plugin, "_AutoSubv2__check_asr", lambda: True)

    plugin.init_plugin({
        "enabled": True,
        "enable_asr": True,
        "faster_whisper_model": "base",
        "faster_whisper_model_path": tmp_path,
    })

    assert plugin.get_state() is True
    assert plugin._consumer_thread.is_alive()
    plugin._tasks["pending"] = TaskItem(
        task_id="pending",
        video_file="/media/pending.mkv",
        source=TaskSource.MANUAL,
        add_time=datetime.now(),
    )

    plugin.stop_service()

    assert plugin.get_state() is False
    assert not plugin._consumer_thread.is_alive()
    assert plugin._task_queue.empty()
    assert plugin._tasks["pending"].status is TaskStatus.FAILED
    assert plugin._tasks["pending"].complete_time is not None
    assert persisted[-1][0] == "tasks"
    assert persisted[-1][1]["pending"]["status"] == "failed"
