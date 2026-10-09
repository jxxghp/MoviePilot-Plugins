"""V1 消息队列插件共享的确定性生命周期断言。"""

from threading import Event


def assert_queue_worker_lifecycle(plugin, event, entered: Event, release: Event, calls: list) -> None:
    """验证发送中超时保留 owner，释放后可重试收敛且封口后无尾任务。"""
    plugin.SHUTDOWN_TIMEOUT = 0.02
    plugin.send(event)
    assert entered.wait(timeout=1)

    worker = plugin.processing_thread
    assert worker is not None and worker.is_alive()
    assert plugin.stop_service() is False
    assert plugin.processing_thread is worker
    assert worker.is_alive()

    release.set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert plugin.stop_service() is True
    assert plugin.processing_thread is None

    plugin.send(event)
    assert calls == ["send"]
    assert plugin.message_queue.empty()
    assert plugin.close() is True
