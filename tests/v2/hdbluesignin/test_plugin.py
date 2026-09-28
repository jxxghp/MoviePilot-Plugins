"""Protocol/lifecycle regressions using the real host import namespace.

Run through the repository harness in a separate process per generation.
"""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from app.plugins.hdbluesignin import core


TEST_DIR = Path(__file__).resolve().parent
GENERATION = TEST_DIR.parent.name
SOURCE = TEST_DIR.parents[2] / ("plugins." + GENERATION) / "hdbluesignin"
KEY = "hdbmp_" + "a" * 40
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=core.TZ)


def payload(checked=False, **changes):
    data = {"protocolVersion": 1, "account": {"id": "u1", "username": "alice", "nickname": "Alice", "avatarUrl": ""},
            "date": "2026-09-12", "timezone": "Asia/Shanghai", "pointName": "积分", "points": 100,
            "reward": 5 if checked else 0, "alreadyCheckedIn": checked, "performedCheckIn": checked,
            "currentStreak": 3 if checked else 2, "maxStreak": 8,
            "history": [{"date": "2026-09-11", "reward": 5, "createdAt": "2026-09-11T00:35:00Z"}]}
    data.update(changes)
    return data


class Scheduler:
    def __init__(self, **kwargs):
        self.jobs = {}
        self.running = False
        self.removed = False

    def start(self):
        self.running = True

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = SimpleNamespace(func=func, next_run_time=kwargs["run_date"], **kwargs)

    def remove_all_jobs(self):
        self.jobs.clear()
        self.removed = True

    def shutdown(self, wait):
        assert wait is False
        self.running = False

    def get_jobs(self):
        return list(self.jobs.values())


class Plugin(core.HDBluePlugin):
    notification_type = "site"
    host_logger = Mock()

    def __init__(self):
        self.storage = {}
        self.post_message = Mock()
        self.update_config = Mock()

    def get_data(self, key):
        return copy.deepcopy(self.storage.get(key))

    def save_data(self, key, value):
        self.storage[key] = copy.deepcopy(value)


@pytest.fixture
def plugin(monkeypatch):
    monkeypatch.setattr(core, "BackgroundScheduler", Scheduler)
    monkeypatch.setattr(core, "now_beijing", lambda: NOW)
    monkeypatch.setattr(core.random, "randint", lambda a, b: b)
    item = Plugin()
    item.init_plugin({"api_key": KEY, "enabled": True, "catch_up": False, "notification": "all"})
    yield item
    item.stop_service()


def run(plugin, responses, mode="auto", target="2026-09-12"):
    client = Mock()
    client.request.side_effect = responses
    plugin._client = lambda: client
    plugin._run(mode, target, plugin._generation)
    return client


def test_first_checkin_reads_then_posts_and_records_actual_reward(plugin):
    client = run(plugin, [payload(), payload(True, points=127, reward=27)])
    assert client.request.call_args_list[0].args == ("GET", "/check-in")
    assert client.request.call_args_list[1].args == ("POST", "/check-in")
    assert plugin.storage["state"]["snapshot"]["reward"] == 27
    assert plugin.storage["state"]["lastResult"]["result"] == "签到成功"
    plugin.post_message.assert_called_once()


def test_already_checked_does_not_post_or_claim_new_reward(plugin):
    client = run(plugin, [payload(True)])
    assert client.request.call_count == 1
    assert plugin.storage["state"]["lastResult"]["result"] == "今日已签到"


def test_racing_web_checkin_is_reported_as_already_checked(plugin):
    run(plugin, [payload(), payload(True, performedCheckIn=False)])
    assert plugin.storage["state"]["lastResult"]["result"] == "今日已签到"


def test_post_timeout_checks_server_before_retrying(plugin):
    error = core.CheckinError("超时", retryable=True, uncertain=True)
    client = run(plugin, [payload(), error, payload(True)])
    assert [call.args[0] for call in client.request.call_args_list] == ["GET", "POST", "GET"]
    assert plugin.storage["state"]["lastResult"]["result"] == "已确认签到成功"
    assert "retry" not in plugin.storage["state"]


def test_uncertain_post_does_not_post_again_in_same_execution(plugin):
    error = core.CheckinError("超时", retryable=True, uncertain=True)
    client = run(plugin, [payload(), error, payload()])
    assert sum(call.args[0] == "POST" for call in client.request.call_args_list) == 1
    assert plugin.storage["state"]["lastResult"]["result"] == "结果待确认"
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=10)


def test_retries_are_bounded_and_survive_reload(plugin):
    error = core.CheckinError("网络故障", retryable=True)
    run(plugin, [error])
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=10)
    plugin.init_plugin(plugin._config)
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=10)
    run(plugin, [error])
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=30)
    run(plugin, [error])
    assert "retry" not in plugin._state
    client = run(plugin, [error])
    client.request.assert_not_called()
    assert plugin._state["attempts"]["count"] == 3


def test_rate_limit_honors_retry_after(plugin):
    run(plugin, [core.CheckinError("限流", retryable=True, retry_after=2700)])
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=45)


def test_auth_failure_stops_automatic_requests_until_key_test(plugin):
    run(plugin, [core.CheckinError("无权限", auth=True)])
    assert plugin._auth_blocked
    assert "retry" not in plugin._state
    assert run(plugin, [payload()]).request.call_count == 0
    client = run(plugin, [payload()], mode="test")
    assert client.request.call_args.args == ("GET", "/me")
    assert not plugin._auth_blocked


def test_connection_test_is_readonly_and_resets_toggle(plugin):
    plugin.init_plugin(dict(plugin._config, test_connection=True, run_once=True))
    assert set(plugin._scheduler.jobs) == {"test"}
    assert not plugin.update_config.call_args.args[0]["test_connection"]
    assert not plugin.update_config.call_args.args[0]["run_once"]
    client = run(plugin, [payload()], mode="test")
    assert client.request.call_count == 1
    plugin.post_message.assert_not_called()


def test_changed_credential_discards_old_account_and_retry_state(plugin):
    run(plugin, [payload(True)])
    assert plugin._state["snapshot"]["account"]["username"] == "alice"
    plugin.init_plugin(dict(plugin._config, api_key="hdbmp_" + "b" * 40))
    assert "snapshot" not in plugin.storage["state"]
    assert "events" not in plugin.storage["state"]
    assert "alice" not in json.dumps(plugin.get_page())


def test_cache_survives_reload_with_same_credential(plugin):
    run(plugin, [payload(True)])
    plugin.init_plugin(plugin._config)
    assert plugin._state["snapshot"]["account"]["username"] == "alice"
    assert run(plugin, [payload()]).request.call_count == 0


def test_stop_and_reload_invalidate_old_jobs(plugin):
    old_generation = plugin._generation
    old_scheduler = plugin._scheduler
    plugin.init_plugin(plugin._config)
    assert old_scheduler.removed and not old_scheduler.running
    assert plugin._generation != old_generation
    client = Mock()
    plugin._client = lambda: client
    plugin._run("auto", "2026-09-12", old_generation)
    client.request.assert_not_called()
    current_scheduler = plugin._scheduler
    plugin.stop_service()
    assert current_scheduler.removed and not current_scheduler.running
    plugin.scheduled_checkin()
    client.request.assert_not_called()


def test_configuration_change_during_http_prevents_post_and_cache(plugin):
    def request(method, endpoint):
        plugin.stop_service()
        return payload()
    client = Mock()
    client.request.side_effect = request
    plugin._client = lambda: client
    plugin._run("auto", "2026-09-12", plugin._generation)
    assert client.request.call_count == 1
    assert "snapshot" not in plugin.storage["state"]


def test_concurrent_callback_cannot_issue_second_request(plugin):
    plugin._run_lock.acquire()
    try:
        client = run(plugin, [payload(True)])
        client.request.assert_not_called()
    finally:
        plugin._run_lock.release()


def test_previous_day_callback_and_changed_server_date_never_post(plugin):
    assert run(plugin, [payload()], target="2026-09-11").request.call_count == 0
    client = run(plugin, [payload(date="2026-09-13")])
    assert client.request.call_count == 1
    assert "往日" in plugin._state["lastResult"]["message"]


def test_retry_never_crosses_midnight(plugin, monkeypatch):
    late = NOW.replace(hour=23, minute=58)
    monkeypatch.setattr(core, "now_beijing", lambda: late)
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    assert "retry" not in plugin._state
    assert not plugin._scheduler.jobs


def test_cron_is_in_beijing_and_catchup_only_after_due_time(plugin, monkeypatch):
    service = plugin.get_service()[0]
    assert str(service["trigger"].timezone) == "Asia/Shanghai"
    assert service["id"] == "PluginDailyCheckin"
    plugin.init_plugin(dict(plugin._config, catch_up=True))
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=30, seconds=15)
    monkeypatch.setattr(core, "now_beijing", lambda: NOW.replace(hour=7))
    plugin.init_plugin(dict(plugin._config, catch_up=True))
    assert not plugin._scheduler.jobs


def test_scheduled_jitter_and_no_duplicate_pending_retry(plugin):
    plugin.scheduled_checkin()
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=30)
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.scheduled_checkin()
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=10)


def test_frequent_cron_does_not_postpone_pending_jitter(plugin, monkeypatch):
    plugin.init_plugin(dict(plugin._config, cron="* * * * *"))
    plugin.scheduled_checkin()
    due = plugin._scheduler.jobs["checkin"].next_run_time
    monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=1))
    plugin.scheduled_checkin()
    assert plugin._scheduler.jobs["checkin"].next_run_time == due


def test_invalid_configuration_registers_no_jobs(plugin):
    plugin.init_plugin(dict(plugin._config, cron="bad cron", api_key="password"))
    assert plugin.get_service() == []
    assert plugin._scheduler is None
    assert plugin._config_error


def test_notification_failure_does_not_undo_success(plugin):
    plugin.post_message.side_effect = RuntimeError("channel unavailable")
    run(plugin, [payload(True)])
    assert plugin._state["snapshot"]["alreadyCheckedIn"]
    assert "retry" not in plugin._state


def test_stop_during_record_persistence_suppresses_notification(plugin):
    original_save = plugin.save_data
    def save(key, value):
        original_save(key, value)
        if "snapshot" in value:
            plugin.stop_service()
    plugin.save_data = save
    run(plugin, [payload(True)])
    plugin.post_message.assert_not_called()


def test_stop_during_logging_suppresses_notification(plugin):
    plugin._log = lambda text: plugin.stop_service()
    run(plugin, [payload(True)])
    plugin.post_message.assert_not_called()


def test_late_day_jitter_is_clamped_instead_of_dropping_run(plugin, monkeypatch):
    late = NOW.replace(hour=23, minute=55)
    monkeypatch.setattr(core, "now_beijing", lambda: late)
    plugin.init_plugin(dict(plugin._config, cron="55 23 * * *", catch_up=True))
    assert plugin._scheduler.jobs["checkin"].next_run_time == late.replace(minute=59, second=30)
    plugin._scheduler.remove_all_jobs()
    plugin.scheduled_checkin()
    assert plugin._scheduler.jobs["checkin"].next_run_time == late.replace(minute=59, second=30)


def test_page_and_form_never_send_requests_or_expose_key(plugin):
    client = Mock()
    plugin._client = lambda: client
    content = json.dumps([plugin.get_page(), plugin.get_form()])
    client.request.assert_not_called()
    assert KEY not in content
    assert '"type": "password"' in content


def test_form_preserves_all_models_defaults_and_input_contracts(plugin):
    form, defaults = plugin.get_form()
    cells = form[0]["content"][0]["content"]
    controls = {cell["content"][0]["props"]["model"]: cell["content"][0]
                for cell in cells if "model" in cell["content"][0].get("props", {})}
    assert defaults == {
        "enabled": False, "api_key": "", "cron": "30 8 * * *", "jitter_minutes": 30,
        "catch_up": True, "notification": "failure", "use_proxy": False, "proxy_url": "",
        "run_once": False, "test_connection": False,
    }
    assert set(controls) == set(defaults)
    assert len(controls) == sum("model" in cell["content"][0].get("props", {}) for cell in cells)
    for model in ("api_key", "proxy_url"):
        assert controls[model]["props"]["type"] == "password"
        assert controls[model]["props"]["autocomplete"] == "off"
    assert controls["jitter_minutes"]["props"]["min"] == 0
    assert controls["jitter_minutes"]["props"]["max"] == 30
    assert [item["value"] for item in controls["notification"]["props"]["items"]] == ["failure", "all", "off"]


def test_form_grid_reserves_label_hint_spacing_and_stacks_on_mobile(plugin):
    form, _ = plugin.get_form()
    assert form[0]["component"] == "VForm"
    row = form[0]["content"][0]
    assert row["component"] == "VRow"
    assert row["props"]["class"] == "ma-0"
    for cell in row["content"]:
        assert cell["component"] == "VCol"
        assert cell["props"]["cols"] == 12
        assert cell["props"]["class"] == "pa-2"
        assert len(cell["content"]) == 1
        control = cell["content"][0]
        props = control.get("props", {})
        assert cell["props"]["md"] == (6 if props.get("model") in ("cron", "jitter_minutes") else 12)
        if control["component"] in ("VTextField", "VSelect"):
            assert props["hide-details"] is False
        if props.get("hint"):
            assert props["persistent-hint"] is True


def test_form_layout_has_no_runtime_or_default_mutation(plugin):
    config = copy.deepcopy(plugin._config)
    state = copy.deepcopy(plugin._state)
    stored = copy.deepcopy(plugin.storage)
    jobs = list(plugin._scheduler.jobs)
    defaults_before = copy.deepcopy(core.DEFAULTS)
    client = Mock()
    plugin._client = lambda: client
    _, returned_defaults = plugin.get_form()
    returned_defaults["cron"] = "0 0 * * *"
    assert core.DEFAULTS == defaults_before
    assert plugin._config == config
    assert plugin._state == state
    assert plugin.storage == stored
    assert list(plugin._scheduler.jobs) == jobs
    client.request.assert_not_called()
    plugin.update_config.assert_not_called()
    plugin.post_message.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"protocolVersion": 2}, {"history": {}}, {"points": "100"}, {"date": "2026-09-99"},
    {"timezone": "UTC"}, {"alreadyCheckedIn": "false"}, {"account": {}}, {"reward": -5},
])
def test_protocol_rejects_malformed_data(changes):
    with pytest.raises(core.CheckinError):
        core.validate_payload(payload(**changes))


def test_protocol_discards_unknown_sensitive_fields():
    data = payload(token=KEY, email="private@example.com")
    data["account"]["email"] = "private@example.com"
    safe = json.dumps(core.validate_payload(data))
    assert KEY not in safe and "private@example.com" not in safe


class Session:
    def __init__(self, response):
        self.response = response
        self.trust_env = True
        self.proxies = {}
        self.request = Mock(return_value=response)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def response(status=200, data=None, headers=None):
    item = Mock(status_code=status, headers=headers or {}, content=b"{}")
    item.json.return_value = data if data is not None else {"code": 0, "data": payload()}
    return item


def test_http_fixed_origin_tls_no_redirects_no_ambient_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid:8888")
    session = Session(response())
    client = core.ForumClient(KEY, session_factory=lambda: session)
    client.request("POST", "/check-in")
    call = session.request.call_args
    assert call.args == ("POST", "https://hdblue.cc/api/integrations/moviepilot/v1/check-in")
    assert call.kwargs["json"] == {}
    assert call.kwargs["verify"] is True
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["headers"]["Authorization"] == "Bearer " + KEY
    assert session.trust_env is False and session.proxies == {}


def test_http_explicit_proxy():
    session = Session(response())
    core.ForumClient(KEY, "http://proxy:8080", lambda: session).request("GET", "/me")
    assert session.proxies == {"http": "http://proxy:8080", "https": "http://proxy:8080"}


@pytest.mark.parametrize("status,retryable,auth", [(401, False, True), (403, False, False),
    (429, True, False), (503, True, False), (302, False, False), (400, False, False)])
def test_http_errors_are_classified_without_body_or_key_leak(status, retryable, auth):
    session = Session(response(status, {"message": KEY}, {"Retry-After": "900"}))
    with pytest.raises(core.CheckinError) as caught:
        core.ForumClient(KEY, session_factory=lambda: session).request("GET", "/check-in")
    assert caught.value.retryable is retryable
    assert caught.value.auth is auth
    assert KEY not in str(caught.value)
    if status == 429:
        assert caught.value.retry_after == 900


def test_transport_exception_never_leaks_request_secret():
    session = Session(response())
    session.request.side_effect = requests.Timeout("header " + KEY)
    with pytest.raises(core.CheckinError) as caught:
        core.ForumClient(KEY, session_factory=lambda: session).request("POST", "/check-in")
    assert caught.value.uncertain and caught.value.retryable
    assert KEY not in str(caught.value)


def test_successful_post_with_invalid_response_is_uncertain():
    session = Session(response(data={"code": 0, "data": {}}))
    with pytest.raises(core.CheckinError) as caught:
        core.ForumClient(KEY, session_factory=lambda: session).request("POST", "/check-in")
    assert caught.value.uncertain


def test_retry_after_accepts_http_date_and_invalid_value():
    assert core.retry_after_seconds("Sat, 12 Sep 2026 02:15:00 GMT", NOW) == 901
    assert core.retry_after_seconds("invalid", NOW) == 0


def test_metadata_and_core_match_generations():
    import ast
    tree = ast.parse((SOURCE / "__init__.py").read_text())
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    fields = {node.targets[0].id: ast.literal_eval(node.value) for node in klass.body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}
    package = json.loads((TEST_DIR.parents[2] / ("package." + GENERATION + ".json")).read_text())["HDBlueSignin"]
    assert fields["plugin_version"] == package["version"]
    assert fields["plugin_icon"] == package["icon"]
    assert fields["plugin_name"] == package["name"]
    assert package["release"] is False
    opposite = "v3" if GENERATION == "v2" else "v2"
    assert (SOURCE / "core.py").read_bytes() == (TEST_DIR.parents[2] / ("plugins." + opposite) / "hdbluesignin/core.py").read_bytes()


def fire_date_job(plugin, job_id, responses):
    """Mirror APScheduler removing a date job before calling its callback."""
    job = plugin._scheduler.jobs.pop(job_id)
    client = Mock()
    client.request.side_effect = responses
    plugin._client = lambda: client
    job.func(**job.kwargs)
    return client


@pytest.mark.parametrize("outcome,restored,blocked", [
    ("unchecked", True, False), ("checked", False, False),
    ("network", True, False), ("auth", False, True),
])
def test_connection_restores_retry_without_post_or_budget_reset(plugin, outcome, restored, blocked):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    original_retry = copy.deepcopy(plugin._state["retry"])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    assert set(plugin._scheduler.jobs) == {"test"}
    result = (payload(outcome == "checked") if outcome in ("unchecked", "checked") else
              core.CheckinError("网络故障", retryable=True) if outcome == "network" else
              core.CheckinError("密钥失效", auth=True))
    client = fire_date_job(plugin, "test", [result])
    assert [call.args for call in client.request.call_args_list] == [("GET", "/me")]
    assert plugin._state["attempts"] == {"date": "2026-09-12", "count": 1}
    assert plugin._auth_blocked is blocked
    assert plugin._test_pending is False
    if restored:
        assert plugin._state["retry"] == original_retry
        assert set(plugin._scheduler.jobs) == {"checkin"}
        assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=10)
    else:
        assert "retry" not in plugin._state
        assert not plugin._scheduler.jobs


def test_connection_without_retry_does_not_create_automatic_post(plugin):
    plugin.init_plugin(dict(plugin._config, catch_up=True, test_connection=True))
    client = fire_date_job(plugin, "test", [payload()])
    assert client.request.call_count == 1
    assert not plugin._scheduler.jobs
    assert "attempts" not in plugin._state
    assert "retry" not in plugin._state


def test_connection_429_preserves_server_retry_after_and_survives_reload(plugin):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    fire_date_job(plugin, "test", [core.CheckinError("限流", retryable=True, retry_after=2700)])
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=45)
    assert plugin._state["attempts"]["count"] == 1
    assert plugin.storage["state"]["retry"]["dueAt"] == (NOW + timedelta(minutes=45)).isoformat()
    plugin.init_plugin(plugin._config)
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=45)


def test_cron_cannot_race_dequeued_test_or_consume_its_pending_retry(plugin, monkeypatch):
    import threading
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    test_job = plugin._scheduler.jobs.pop("test")
    # The date job is already dequeued but has not acquired its run lock yet.
    plugin.scheduled_checkin()
    assert not plugin._scheduler.jobs
    attempted, acquired = observe_background_lock(plugin)
    cron = threading.Thread(target=plugin.scheduled_checkin)
    client = Mock()
    def request(method, endpoint):
        assert (method, endpoint) == ("GET", "/me")
        monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=11))
        cron.start()
        assert attempted.wait(2)
        assert not acquired.is_set()
        assert not plugin._scheduler.jobs
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    test_job.func(**test_job.kwargs)
    cron.join(3)
    assert not cron.is_alive() and acquired.is_set()
    assert client.request.call_count == 1
    assert set(plugin._scheduler.jobs) == {"checkin"}
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=11, seconds=15)
    assert plugin._state["attempts"]["count"] == 1


def test_restored_retry_makes_only_one_normal_checkin_attempt(plugin, monkeypatch):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    fire_date_job(plugin, "test", [payload()])
    monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=10))
    client = fire_date_job(plugin, "checkin", [payload(), payload(True)])
    assert [call.args for call in client.request.call_args_list] == [
        ("GET", "/check-in"), ("POST", "/check-in")]
    assert plugin._state["attempts"]["count"] == 2
    assert "retry" not in plugin._state
    assert not plugin._scheduler.jobs
    plugin.scheduled_checkin()
    assert not plugin._scheduler.jobs


def test_test_completion_does_not_revive_exhausted_retry_budget(plugin):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin._state["attempts"]["count"] = 3
    plugin.save_data("state", plugin._state)
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    fire_date_job(plugin, "test", [payload()])
    assert not plugin._scheduler.jobs
    assert "retry" not in plugin._state
    assert plugin._state["attempts"]["count"] == 3
    assert run(plugin, [payload()]).request.call_count == 0


@pytest.mark.parametrize("late", [
    NOW.replace(hour=23, minute=59, second=50),
    NOW + timedelta(days=1),
])
def test_test_completion_never_moves_previous_retry_into_next_day(plugin, monkeypatch, late):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    client = Mock()
    def request(method, endpoint):
        monkeypatch.setattr(core, "now_beijing", lambda: late)
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    job = plugin._scheduler.jobs.pop("test")
    job.func(**job.kwargs)
    assert client.request.call_count == 1
    assert not plugin._scheduler.jobs
    assert "retry" not in plugin._state


def test_disabled_without_one_shot_does_not_construct_scheduler(plugin, monkeypatch):
    previous_scheduler = plugin._scheduler
    factory = Mock()
    monkeypatch.setattr(core, "BackgroundScheduler", factory)
    plugin.init_plugin(dict(plugin._config, enabled=False))
    factory.assert_not_called()
    assert previous_scheduler.removed and not previous_scheduler.running
    assert plugin._scheduler is None
    assert not plugin.get_state()
    assert plugin.get_service() == []
    plugin.stop_service()
    plugin.stop_service()


@pytest.mark.parametrize("mode", ["test", "manual"])
@pytest.mark.parametrize("outcome", ["success", "network", "auth", "unexpected"])
def test_disabled_one_shot_always_releases_scheduler(plugin, mode, outcome):
    plugin.init_plugin(dict(plugin._config, enabled=False,
                            test_connection=mode == "test", run_once=mode == "manual"))
    scheduler = plugin._scheduler
    job = scheduler.jobs.pop("test" if mode == "test" else "checkin")
    client = Mock()
    responses = ([payload()] if mode == "test" else [payload(), payload(True)])
    if outcome == "network":
        responses = [core.CheckinError("网络故障", retryable=True)]
    elif outcome == "auth":
        responses = [core.CheckinError("密钥失效", auth=True)]
    elif outcome == "unexpected":
        responses = [RuntimeError("simulated internal failure")]
    client.request.side_effect = responses
    plugin._client = lambda: client
    if outcome == "unexpected":
        with pytest.raises(RuntimeError, match="simulated internal failure"):
            job.func(**job.kwargs)
    else:
        job.func(**job.kwargs)
    assert plugin._scheduler is None
    assert scheduler.removed and not scheduler.running and not scheduler.jobs
    assert plugin._test_pending is False
    assert not plugin.get_state()
    assert plugin.get_service() == []
    assert "retry" not in plugin._state
    assert client.request.call_args_list[0].args == ("GET", "/me" if mode == "test" else "/check-in")
    assert sum(call.args[0] == "POST" for call in client.request.call_args_list) == (
        1 if mode == "manual" and outcome == "success" else 0)


@pytest.mark.parametrize("mode", ["test", "manual"])
def test_disabled_cross_midnight_one_shot_leaves_no_empty_scheduler(plugin, monkeypatch, mode):
    monkeypatch.setattr(core, "now_beijing", lambda: NOW.replace(hour=23, minute=59, second=59))
    plugin.init_plugin(dict(plugin._config, enabled=False,
                            test_connection=mode == "test", run_once=mode == "manual"))
    assert plugin._scheduler is None
    assert not plugin._test_pending
    assert not plugin.get_state()


def test_old_disabled_callback_does_not_stop_reloaded_enabled_scheduler(plugin):
    plugin.init_plugin(dict(plugin._config, enabled=False, test_connection=True))
    old_job = plugin._scheduler.jobs["test"]
    plugin.init_plugin(dict(plugin._config, enabled=True, test_connection=False))
    current_scheduler = plugin._scheduler
    client = Mock()
    plugin._client = lambda: client
    old_job.func(**old_job.kwargs)
    client.request.assert_not_called()
    assert plugin._scheduler is current_scheduler
    assert current_scheduler.running
    assert plugin.get_state()


def test_reload_during_disabled_one_shot_cannot_post_or_close_new_scheduler(plugin):
    import threading
    plugin.init_plugin(dict(plugin._config, enabled=False, run_once=True))
    old_scheduler = plugin._scheduler
    job = old_scheduler.jobs.pop("checkin")
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    original_shutdown = old_scheduler.shutdown
    def shutdown(wait):
        original_shutdown(wait)
        stopped.set()
    old_scheduler.shutdown = shutdown
    client = Mock()
    def request(method, endpoint):
        entered.set()
        assert release.wait(2)
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    failures = []
    def guarded(call):
        try:
            call()
        except BaseException as error:
            failures.append(error)
    runner = threading.Thread(target=guarded, args=(lambda: job.func(**job.kwargs),))
    reloader = threading.Thread(target=guarded, args=(
        lambda: plugin.init_plugin(dict(plugin._config, enabled=True, run_once=False)),))
    runner.start()
    try:
        assert entered.wait(2)
        reloader.start()
        assert stopped.wait(2)
    finally:
        release.set()
        runner.join(3)
        if reloader.ident is not None:
            reloader.join(3)
    assert not failures
    assert not runner.is_alive() and not reloader.is_alive()
    assert client.request.call_count == 1
    assert "snapshot" not in plugin._state
    assert plugin._scheduler is not old_scheduler
    assert plugin._scheduler.running
    assert plugin.get_state()


@pytest.mark.parametrize("mode", ["test", "manual"])
def test_real_scheduler_worker_is_released_after_disabled_one_shot(plugin, monkeypatch, mode):
    from apscheduler.schedulers.background import BackgroundScheduler as RealScheduler
    monkeypatch.setattr(core, "BackgroundScheduler", RealScheduler)
    monkeypatch.setattr(core, "now_beijing", lambda: datetime.now(core.TZ))
    client = Mock()
    client.request.side_effect = lambda method, endpoint: payload(
        True, date=datetime.now(core.TZ).date().isoformat())
    plugin._client = lambda: client
    plugin.init_plugin(dict(plugin._config, enabled=False,
                            test_connection=mode == "test", run_once=mode == "manual"))
    scheduler = plugin._scheduler
    scheduler_thread = scheduler._thread
    pool = scheduler._executors["default"]._pool
    plugin._queue(mode, datetime.now(core.TZ) + timedelta(milliseconds=50))
    scheduler_thread.join(3)
    assert not scheduler_thread.is_alive()
    for worker in tuple(pool._threads):
        worker.join(3)
        assert not worker.is_alive()
    assert plugin._scheduler is None
    assert not plugin.get_state()
    assert client.request.call_count == 1
    assert client.request.call_args.args == ("GET", "/me" if mode == "test" else "/check-in")



@pytest.mark.parametrize("mode", ["test", "manual", "auto"])
@pytest.mark.parametrize("stopped_while_waiting", [False, True])
def test_date_callback_waits_for_lock_without_losing_job_or_reviving_stopped_work(plugin, mode, stopped_while_waiting):
    import threading
    plugin.init_plugin(dict(plugin._config, enabled=mode == "auto",
                            test_connection=mode == "test", run_once=mode == "manual"))
    if mode == "auto":
        plugin._queue("auto", NOW)
    job = plugin._scheduler.jobs.pop("test" if mode == "test" else "checkin")
    waiting = threading.Event()
    blocking_modes = []
    class TrackingLock:
        def __init__(self):
            self.inner = threading.Lock()
        def acquire(self, blocking=True):
            blocking_modes.append(blocking)
            if blocking:
                waiting.set()
                return self.inner.acquire()
            acquired = self.inner.acquire(blocking=False)
            waiting.set()
            return acquired
        def release(self):
            self.inner.release()
        def __enter__(self):
            self.acquire()
            return self
        def __exit__(self, *args):
            self.release()
    lock = TrackingLock()
    plugin._run_lock = lock
    client = Mock()
    client.request.return_value = payload(True)
    plugin._client = lambda: client
    failures = []
    def callback():
        try:
            job.func(**job.kwargs)
        except BaseException as error:
            failures.append(error)
    lock.inner.acquire()
    runner = threading.Thread(target=callback)
    runner.start()
    try:
        assert waiting.wait(2)
        assert blocking_modes == [True]
        client.request.assert_not_called()
        if stopped_while_waiting:
            plugin.stop_service()
    finally:
        lock.inner.release()
        runner.join(3)
    assert not runner.is_alive()
    assert not failures
    assert client.request.call_count == (0 if stopped_while_waiting else 1)
    if not stopped_while_waiting:
        assert plugin._state["snapshot"]["alreadyCheckedIn"]
    elif mode in ("test", "manual"):
        assert plugin._scheduler is None



@pytest.mark.parametrize("source_mode", ["test", "auto"])
def test_cross_day_retry_after_survives_reload_and_blocks_cron_and_all_request_entries(plugin, monkeypatch, source_mode):
    deadline = NOW + timedelta(hours=36)
    if source_mode == "test":
        run(plugin, [core.CheckinError("网络故障", retryable=True)])
        plugin.init_plugin(dict(plugin._config, test_connection=True))
        fire_date_job(plugin, "test", [core.CheckinError("限流", retryable=True, retry_after=36 * 3600)])
    else:
        run(plugin, [core.CheckinError("限流", retryable=True, retry_after=36 * 3600)])
    assert plugin.storage["state"]["notBefore"] == deadline.isoformat()
    assert "retry" not in plugin._state
    plugin.init_plugin(dict(plugin._config, cron="* * * * *", catch_up=True))
    assert not plugin._scheduler.jobs
    attempts = copy.deepcopy(plugin._state["attempts"])
    for moment in (NOW + timedelta(minutes=1), NOW + timedelta(hours=4),
                   NOW + timedelta(days=1), deadline - timedelta(seconds=1)):
        monkeypatch.setattr(core, "now_beijing", lambda moment=moment: moment)
        plugin.scheduled_checkin()
        assert not plugin._scheduler.jobs
        for mode in ("auto", "test", "manual"):
            client = run(plugin, [payload()], mode=mode, target=moment.date().isoformat())
            client.request.assert_not_called()
        assert plugin._state["attempts"] == attempts
        assert plugin._state["notBefore"] == deadline.isoformat()
        plugin.init_plugin(plugin._config)
        assert not plugin._scheduler.jobs
    monkeypatch.setattr(core, "now_beijing", lambda: deadline)
    plugin.scheduled_checkin()
    resumed = plugin._scheduler.jobs["checkin"]
    assert resumed.kwargs["target_date"] == deadline.date().isoformat()
    monkeypatch.setattr(core, "now_beijing", lambda: resumed.next_run_time)
    client = fire_date_job(plugin, "checkin", [
        payload(date=deadline.date().isoformat()), payload(True, date=deadline.date().isoformat())])
    assert [call.args for call in client.request.call_args_list] == [("GET", "/check-in"), ("POST", "/check-in")]
    assert plugin._state["attempts"] == {"date": deadline.date().isoformat(), "count": 1}


def test_test_429_without_existing_retry_persists_cooldown_without_creating_signin(plugin):
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    fire_date_job(plugin, "test", [core.CheckinError("限流", retryable=True, retry_after=2700)])
    assert plugin._state["notBefore"] == (NOW + timedelta(minutes=45)).isoformat()
    assert "retry" not in plugin._state
    assert "attempts" not in plugin._state
    assert not plugin._scheduler.jobs


def test_same_day_retry_after_reload_runs_once_at_allowed_time(plugin, monkeypatch):
    run(plugin, [core.CheckinError("网络故障", retryable=True)])
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    fire_date_job(plugin, "test", [core.CheckinError("限流", retryable=True, retry_after=2700)])
    plugin.init_plugin(dict(plugin._config, cron="* * * * *", catch_up=True))
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=45)
    monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=30))
    plugin.scheduled_checkin()
    assert plugin._scheduler.jobs["checkin"].next_run_time == NOW + timedelta(minutes=45)
    monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=45))
    client = fire_date_job(plugin, "checkin", [payload(), payload(True)])
    assert sum(call.args[0] == "POST" for call in client.request.call_args_list) == 1
    assert plugin._state["attempts"]["count"] == 2
    plugin.scheduled_checkin()
    assert not plugin._scheduler.jobs


def test_disabled_one_shot_during_persisted_cooldown_is_readonly_and_releases_worker(plugin):
    plugin.init_plugin(dict(plugin._config, enabled=False, test_connection=True))
    fire_date_job(plugin, "test", [core.CheckinError("限流", retryable=True, retry_after=2700)])
    assert plugin._scheduler is None
    deadline = plugin._state["notBefore"]
    plugin.init_plugin(dict(plugin._config, enabled=False, run_once=True))
    scheduler = plugin._scheduler
    client = fire_date_job(plugin, "checkin", [payload(), payload(True)])
    client.request.assert_not_called()
    assert plugin._scheduler is None
    assert scheduler.removed and not scheduler.running
    assert plugin._state["notBefore"] == deadline
    assert plugin._state["lastResult"]["result"] == "等待冷却"


@pytest.mark.parametrize("during_http", [False, True])
def test_actual_daily_cron_during_connection_test_is_resumed_without_pending_retry(plugin, monkeypatch, during_http):
    import threading
    before = NOW.replace(hour=8, minute=29, second=59)
    tick = before + timedelta(seconds=1)
    completed = tick + timedelta(seconds=1)
    monkeypatch.setattr(core, "now_beijing", lambda: before)
    plugin.init_plugin(dict(plugin._config, test_connection=True, jitter_minutes=0))
    job = plugin._scheduler.jobs.pop("test")
    if not during_http:
        monkeypatch.setattr(core, "now_beijing", lambda: tick)
        plugin.scheduled_checkin()
    attempted, acquired = observe_background_lock(plugin)
    cron = threading.Thread(target=plugin.scheduled_checkin)
    client = Mock()
    def request(method, endpoint):
        if during_http:
            monkeypatch.setattr(core, "now_beijing", lambda: tick)
            cron.start()
            assert attempted.wait(2)
            assert not acquired.is_set()
        monkeypatch.setattr(core, "now_beijing", lambda: completed)
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    job.func(**job.kwargs)
    if during_http:
        cron.join(3)
        assert not cron.is_alive() and acquired.is_set()
    assert [call.args for call in client.request.call_args_list] == [("GET", "/me")]
    assert plugin._deferred_cron is None
    assert set(plugin._scheduler.jobs) == {"checkin"}
    assert plugin._scheduler.jobs["checkin"].next_run_time == completed
    assert "attempts" not in plugin._state
    assert "retry" not in plugin._state
    checkin = fire_date_job(plugin, "checkin", [payload(), payload(True)])
    assert [call.args for call in checkin.request.call_args_list] == [("GET", "/check-in"), ("POST", "/check-in")]
    assert plugin._state["attempts"]["count"] == 1


@pytest.mark.parametrize("outcome", ["checked", "auth", "cooldown"])
def test_deferred_daily_cron_does_not_bypass_test_result_or_cooldown(plugin, outcome):
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    plugin.scheduled_checkin()
    result = (payload(True) if outcome == "checked" else core.CheckinError("失效", auth=True)
              if outcome == "auth" else core.CheckinError("限流", retryable=True, retry_after=2700))
    client = fire_date_job(plugin, "test", [result])
    assert client.request.call_count == 1
    assert not plugin._scheduler.jobs
    assert plugin._deferred_cron is None



def observe_background_lock(plugin):
    """Expose a real background thread's lock attempt/acquisition without sleeps."""
    import threading
    owner = threading.current_thread()
    attempted = threading.Event()
    acquired = threading.Event()
    inner = plugin._run_lock
    class ObservedLock:
        def acquire(self, blocking=True):
            background = threading.current_thread() is not owner
            if background:
                attempted.set()
            result = inner.acquire(blocking=blocking)
            if result and background:
                acquired.set()
            return result
        def release(self):
            inner.release()
        def __enter__(self):
            self.acquire()
            return self
        def __exit__(self, *args):
            self.release()
    plugin._run_lock = ObservedLock()
    return attempted, acquired


def test_expired_persisted_cooldown_is_cleared_on_reload(plugin, monkeypatch):
    run(plugin, [core.CheckinError("限流", retryable=True, retry_after=600)])
    monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(minutes=11))
    plugin.init_plugin(plugin._config)
    assert "notBefore" not in plugin._state
    assert "notBefore" not in plugin.storage["state"]


@pytest.mark.parametrize("invalidated", ["stop", "date"])
def test_cron_waiting_for_test_lock_rechecks_generation_and_calendar_day(plugin, monkeypatch, invalidated):
    import threading
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    job = plugin._scheduler.jobs.pop("test")
    attempted, acquired = observe_background_lock(plugin)
    cron = threading.Thread(target=plugin.scheduled_checkin)
    client = Mock()
    def request(method, endpoint):
        cron.start()
        assert attempted.wait(2)
        assert not acquired.is_set()
        if invalidated == "stop":
            plugin.stop_service()
        else:
            monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(days=1))
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    job.func(**job.kwargs)
    cron.join(3)
    assert not cron.is_alive() and acquired.is_set()
    assert client.request.call_count == 1
    assert plugin._scheduler is None or not plugin._scheduler.jobs
    assert plugin._deferred_cron is None



@pytest.mark.parametrize("invalidated", ["generation", "date"])
def test_connection_completion_ignores_stale_deferred_cron_intent(plugin, monkeypatch, invalidated):
    plugin.init_plugin(dict(plugin._config, test_connection=True))
    plugin._deferred_cron = (plugin._generation - (invalidated == "generation"), NOW.date().isoformat())
    client = Mock()
    def request(method, endpoint):
        if invalidated == "date":
            monkeypatch.setattr(core, "now_beijing", lambda: NOW + timedelta(days=1))
        return payload()
    client.request.side_effect = request
    plugin._client = lambda: client
    job = plugin._scheduler.jobs.pop("test")
    job.func(**job.kwargs)
    assert client.request.call_count == 1
    assert not plugin._scheduler.jobs
    assert plugin._deferred_cron is None
