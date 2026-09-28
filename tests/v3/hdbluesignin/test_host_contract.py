"""真实 V3 基类、数据库、实例加载器和 APScheduler 的离线集成测试。"""

import inspect
import json
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler

from app.plugins import _PluginBase
from app.plugins.hdbluesignin import HDBlueSignin, core


KEY = "hdbmp_" + "x" * 40


def config(**changes):
    """默认禁止补签和通知，使宿主测试只有显式安排的本地任务。"""
    value = dict(core.DEFAULTS, api_key=KEY, catch_up=False, notification="off")
    value.update(changes)
    return value


def payload(checked=False):
    return {
        "protocolVersion": 1,
        "account": {"id": "host-test", "username": "host-test", "nickname": "隔离测试", "avatarUrl": ""},
        "date": core.now_beijing().date().isoformat(), "timezone": "Asia/Shanghai",
        "pointName": "影币", "points": 105 if checked else 100, "reward": 5 if checked else 0,
        "alreadyCheckedIn": checked, "performedCheckIn": checked,
        "currentStreak": 1 if checked else 0, "maxStreak": 1, "history": [],
    }


def http_reply(data=None, status=200):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"code": 0, "data": data or payload()}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def install_http(monkeypatch, replies):
    """只替换 HTTP 外边界，保留真实 ForumClient 的鉴权、解析和错误处理。"""
    calls = []
    remaining = iter(replies)

    def request(_session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        reply = next(remaining)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(requests.Session, "request", request)
    return calls


def test_production_import_uses_real_host_base_and_sqlite(host_plugin, host_runtime):
    from app.db.engine import peek_sync_engine
    from app.db.oper.plugindata import PluginDataOper
    from app.db.oper.systemconfig import SystemConfigOper
    from app.runtime.config import settings

    assert HDBlueSignin.__module__ == "app.plugins.hdbluesignin"
    assert isinstance(host_plugin, _PluginBase)
    assert Path(inspect.getfile(_PluginBase)).resolve() == host_runtime / "app/plugins/__init__.py"
    assert isinstance(host_plugin.plugindata, PluginDataOper)
    assert isinstance(host_plugin.systemconfig, SystemConfigOper)
    assert peek_sync_engine().url.get_backend_name() == "sqlite"
    assert Path(peek_sync_engine().url.database).is_relative_to(settings.CONFIG_PATH)
    assert settings.CONFIG_PATH != host_runtime / "config"
    host_plugin.update_config(config())
    host_plugin.save_data("host-proof", {"value": 7})
    fresh = HDBlueSignin()
    assert fresh.get_config()["api_key"] == KEY
    assert fresh.get_data("host-proof") == {"value": 7}


def test_one_shot_toggles_reset_in_real_host_configuration(host_plugin, monkeypatch):
    calls = install_http(monkeypatch, [http_reply()])
    host_plugin.update_config(config(test_connection=True, run_once=True))
    host_plugin.init_plugin(host_plugin.get_config())
    host_plugin._scheduler.pause()
    saved = HDBlueSignin().get_config()
    assert saved["test_connection"] is False
    assert saved["run_once"] is False
    assert saved["api_key"] == KEY
    jobs = host_plugin._scheduler.get_jobs()
    assert [job.id for job in jobs] == ["test"]
    jobs[0].func(**jobs[0].kwargs)
    assert [call[:2] for call in calls] == [("GET", core.API_ROOT + "/me")]
    assert HDBlueSignin().get_data("state")["lastResult"]["result"] == "连接成功"
    assert host_plugin._scheduler is None


@pytest.mark.parametrize("test_status", [200, 503])
def test_connection_reload_restores_real_persisted_retry_without_post(host_plugin, monkeypatch, test_status):
    fixed_now = datetime(2026, 9, 12, 10, 0, tzinfo=core.TZ)
    monkeypatch.setattr(core, "now_beijing", lambda: fixed_now)
    original_start = BackgroundScheduler.start

    def start_paused(scheduler, *args, **kwargs):
        kwargs["paused"] = True
        return original_start(scheduler, *args, **kwargs)

    # 使用真调度器但暂停实际派发；固定白天避免跨午夜合法不重试导致测试误报。
    monkeypatch.setattr(BackgroundScheduler, "start", start_paused)
    calls = install_http(monkeypatch, [requests.Timeout(), http_reply(status=test_status)])
    host_plugin.init_plugin(config(enabled=True))
    host_plugin._scheduler.pause()
    today = core.now_beijing().date().isoformat()
    host_plugin._run("auto", today, host_plugin._generation)
    saved = HDBlueSignin().get_data("state")
    assert saved["attempts"]["count"] == 1
    assert "retry" in saved
    host_plugin.update_config(config(enabled=True, test_connection=True))
    host_plugin.init_plugin(host_plugin.get_config())
    host_plugin._scheduler.pause()
    job = host_plugin._scheduler.get_job("test")
    job.func(**job.kwargs)
    restored = HDBlueSignin().get_data("state")
    pending = host_plugin._scheduler.get_job("checkin")
    assert restored["attempts"] == saved["attempts"]
    assert restored["retry"]["date"] == today
    assert pending.next_run_time.isoformat() == restored["retry"]["dueAt"]
    assert pending.kwargs["mode"] == "auto"
    assert [call[:2] for call in calls] == [
        ("GET", core.API_ROOT + "/check-in"), ("GET", core.API_ROOT + "/me"),
    ]


def test_disabled_configuration_allocates_no_scheduler_thread(host_plugin):
    before = set(threading.enumerate())
    host_plugin.init_plugin(config())
    assert host_plugin._scheduler is None
    assert not host_plugin.get_state()
    assert set(threading.enumerate()) == before


def test_disabling_running_plugin_releases_its_real_idle_thread(host_plugin):
    host_plugin.init_plugin(config(enabled=True))
    scheduler = host_plugin._scheduler
    scheduler_thread = scheduler._thread
    assert scheduler_thread.is_alive()
    host_plugin.init_plugin(config(enabled=False))
    scheduler_thread.join(timeout=2)
    assert not scheduler_thread.is_alive()
    assert not scheduler.running
    assert host_plugin._scheduler is None
    assert host_plugin.get_service() == []


def test_real_form_and_page_are_readonly_and_never_issue_http(host_plugin, monkeypatch):
    calls = install_http(monkeypatch, [])
    host_plugin.update_config(config())
    host_plugin.init_plugin(host_plugin.get_config())
    before_config = host_plugin.get_config()
    before_state = host_plugin.get_data("state")
    form, defaults = host_plugin.get_form()
    page = host_plugin.get_page()
    assert form and page and defaults["enabled"] is False
    assert host_plugin.get_config() == before_config
    assert host_plugin.get_data("state") == before_state
    assert calls == []
    assert host_plugin._scheduler is None


@pytest.mark.parametrize("toggle,fail", [
    ("test_connection", False), ("test_connection", True),
    ("run_once", False), ("run_once", True),
])
def test_disabled_one_shot_releases_real_scheduler_and_executor(host_plugin, monkeypatch, toggle, fail):
    completed = threading.Event()
    workers = []
    calls = []
    errors = []

    def request(_session, method, url, **_kwargs):
        workers.append(threading.current_thread())
        calls.append((method, url))
        if fail:
            raise requests.Timeout()
        return http_reply(payload(checked=method == "POST"))

    monkeypatch.setattr(requests.Session, "request", request)
    host_plugin.init_plugin(config(**{toggle: True}))
    scheduler = host_plugin._scheduler
    scheduler_thread = scheduler._thread

    def on_done(event):
        if event.exception:
            errors.append(event.exception)
        completed.set()

    scheduler.add_listener(on_done, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    job_id = "test" if toggle == "test_connection" else "checkin"
    scheduler.reschedule_job(job_id, trigger="date", run_date=datetime.now(core.TZ) + timedelta(milliseconds=30))
    assert completed.wait(5), "真实一次性任务未完成"
    scheduler_thread.join(timeout=2)
    for worker in set(workers):
        worker.join(timeout=2)
    assert not errors
    assert workers and not any(worker.is_alive() for worker in workers)
    assert not scheduler_thread.is_alive()
    assert host_plugin._scheduler is None
    assert not scheduler.running
    expected_methods = ["GET", "POST"] if toggle == "run_once" and not fail else ["GET"]
    assert [call[0] for call in calls] == expected_methods
    state = HDBlueSignin().get_data("state")
    assert state["lastResult"]["failed"] is fail
    assert "retry" not in state


@pytest.fixture
def cloned_plugins(host_runtime):
    """由官方 PluginLoader 执行两份真实源码，清理精确实例模块及数据库键。"""
    from app.runtime.extensions.plugin import manager as manager_module
    from app.runtime.extensions.plugin.loader import PluginLoader
    from app.schemas.plugin import PluginInstance
    from app.sdk.logging import logger

    source_root = Path(core.__file__).resolve().parent.parent
    loader = PluginLoader(
        plugins_root=source_root,
        import_preparer=manager_module._legacy_plugin_import_preparer,
        import_scanner=manager_module._legacy_import_scanner,
        log=logger,
    )
    plugins = []
    identities = ["HDBlueHostContractA", "HDBlueHostContractB"]
    try:
        for identity in identities:
            classes = loader.load_instance(
                PluginInstance(instance_id=identity, source_plugin_id="HDBlueSignin"),
                lambda candidate: issubclass(candidate, _PluginBase) and candidate is not _PluginBase,
            )
            assert len(classes) == 1
            plugin = classes[0]()
            plugins.append(plugin)
            plugin.init_plugin(config(enabled=True))
        yield tuple(plugins)
    finally:
        for plugin in plugins:
            plugin.stop_service()
            plugin.plugindata.del_data(plugin.__class__.__name__)
            plugin.systemconfig.delete("plugin." + plugin.__class__.__name__)
        for identity in identities:
            loader.clear_modules(identity)


def test_official_loader_isolates_instances_modules_locks_storage_and_paths(cloned_plugins):
    first, second = cloned_plugins
    assert first.__class__.__name__ == "HDBlueHostContractA"
    assert second.__class__.__name__ == "HDBlueHostContractB"
    assert first._run_lock is not second._run_lock
    assert first._scheduler is not second._scheduler
    first_core = sys.modules[first.__class__.__module__ + ".core"]
    second_core = sys.modules[second.__class__.__module__ + ".core"]
    assert first_core is not second_core and first_core is not core
    assert first_core.DEFAULTS is not second_core.DEFAULTS
    assert first.get_data_path() != second.get_data_path()
    first.update_config(config(api_key="hdbmp_" + "a" * 40))
    second.update_config(config(api_key="hdbmp_" + "b" * 40))
    first.save_data("instance-proof", {"owner": "A"})
    second.save_data("instance-proof", {"owner": "B"})
    assert first.get_data("instance-proof") == {"owner": "A"}
    assert second.get_data("instance-proof") == {"owner": "B"}
    assert first.get_config()["api_key"] != second.get_config()["api_key"]
    first.stop_service()
    assert second.get_state() and second._scheduler.running


def test_host_scheduler_reconciles_instances_without_duplicates_or_cross_removal(cloned_plugins, monkeypatch):
    from app.runtime.extensions.plugin.manager import PluginManager
    from app.scheduler.facade import Scheduler
    from app.scheduler.registry import ExecutionRegistry

    first, second = cloned_plugins
    manager = PluginManager()
    for plugin in cloned_plugins:
        monkeypatch.setitem(manager._running_plugins, plugin.__class__.__name__, plugin)
    host = Scheduler()
    scheduler = BackgroundScheduler(timezone=core.TZ)
    scheduler.start(paused=True)
    scheduler_thread = scheduler._thread
    monkeypatch.setattr(host, "_scheduler", scheduler)
    monkeypatch.setattr(host, "_jobs", {})
    monkeypatch.setattr(host, "_registry", ExecutionRegistry(host._lock))
    first_id = first.__class__.__name__
    second_id = second.__class__.__name__
    try:
        host.update_plugin_job(first_id)
        host.update_plugin_job(second_id)
        host.update_plugin_job(first_id)
        host.update_plugin_job(second_id)
        expected = {first_id + "_" + first_id + "DailyCheckin", second_id + "_" + second_id + "DailyCheckin"}
        assert {job.id for job in scheduler.get_jobs()} == expected
        assert set(host._jobs) == expected
        assert all(str(job.trigger.timezone) == "Asia/Shanghai" for job in scheduler.get_jobs())
        first.init_plugin(config(enabled=False))
        host.update_plugin_job(first_id)
        remaining = second_id + "_" + second_id + "DailyCheckin"
        assert [job.id for job in scheduler.get_jobs()] == [remaining]
        assert set(host._jobs) == {remaining}
        assert second.get_state()
        assert scheduler.state == 2  # STATE_PAUSED：不执行宿主 provider。
    finally:
        scheduler.shutdown(wait=True)
        scheduler_thread.join(timeout=2)
        assert not scheduler_thread.is_alive()
