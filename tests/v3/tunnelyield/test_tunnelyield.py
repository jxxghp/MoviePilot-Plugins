"""TunnelYield V3 unit regressions.

Production module name: app.plugins.tunnelyield.
SDK/HTTP/downloaders are mocked inside a fixture and restored afterwards.
Run with MoviePilot's interpreter: python -m pytest tests/v3/tunnelyield.
These unit tests do not replace a real V3 import/route/UI acceptance test.
"""
import ast
import importlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import types
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins.v3" / "tunnelyield" / "__init__.py"
MODULE = "app.plugins.tunnelyield"


def _module(name, package=False):
    mod = types.ModuleType(name)
    if package:
        mod.__path__ = []
    return mod


@pytest.fixture
def ty(tmp_path):
    """Load under the production name using strictly scoped, V3-only SDK doubles."""
    env = types.SimpleNamespace(downloaders={}, media={}, notifications=[], logs=[],
                                once_jobs={}, once_calls=[], remove_calls=[], scheduler_ok=True)
    app = _module("app", True)
    sdk = _module("app.sdk", True)
    plugins = _module("app.plugins", True)
    plugins.__path__ = [str(REPO / "plugins.v3")]
    schemas = _module("app.schemas", True)
    schema_types = _module("app.schemas.types")
    schema_types.EventType = types.SimpleNamespace(WebhookMessage="webhook.message")
    schema_types.MessageType = types.SimpleNamespace(Plugin="plugin")

    class Response:
        def __init__(self, success=False, message=None, data=None):
            self.success, self.message, self.data = success, message, data
        @classmethod
        def __class_getitem__(cls, value):
            return cls
    schemas.Response = Response
    schemas.types = schema_types
    app.schemas, app.sdk, app.plugins = schemas, sdk, plugins

    sdk_plugin = _module("app.sdk.plugin")
    class PluginBase:
        def update_config(self, config):
            self._test_saved_config = dict(config)
            return True
        def post_message(self, **kwargs):
            env.notifications.append(kwargs)
            return True
        def get_data_path(self):
            path = tmp_path / type(self).__name__
            path.mkdir(exist_ok=True)
            return path
        def get_config(self, *args, **kwargs):
            return {}
    sdk_plugin._PluginBase = PluginBase
    sdk_config = _module("app.sdk.config")
    sdk_config.settings = types.SimpleNamespace(TZ="Asia/Shanghai")
    sdk_log = _module("app.sdk.logging")
    class Logger:
        def __getattr__(self, level):
            return lambda *args, **kwargs: env.logs.append((level, args))
    sdk_log.logger = Logger()
    sdk_events = _module("app.sdk.events")
    class Event:
        def __init__(self, event_data=None):
            self.event_data = event_data
    class EventManager:
        def register(self, event):
            return lambda method: method
    sdk_events.Event, sdk_events.eventmanager = Event, EventManager()
    sdk_services = _module("app.sdk.services")
    class DownloaderHelper:
        def get_services(self, type_filter=None, name_filters=None):
            return {name: info for name, info in env.downloaders.items()
                    if (not type_filter or info.type == type_filter)
                    and (not name_filters or name in name_filters)}
    class MediaServerHelper:
        def get_services(self, *args, **kwargs):
            return dict(env.media)
    sdk_services.DownloaderHelper = DownloaderHelper
    sdk_services.MediaServerHelper = MediaServerHelper
    sdk_scheduler = _module("app.sdk.scheduler")
    def add_once(plugin_id, job_id, func, name, delay_seconds=3):
        env.once_calls.append((plugin_id, job_id, func, delay_seconds))
        if env.scheduler_ok:
            env.once_jobs[(plugin_id, job_id)] = (func, delay_seconds)
        return env.scheduler_ok
    def remove_once(plugin_id, job_id):
        env.remove_calls.append((plugin_id, job_id))
        env.once_jobs.pop((plugin_id, job_id), None)
    sdk_scheduler.add_plugin_once_job = add_once
    sdk_scheduler.remove_plugin_once_job = remove_once
    stubs = {m.__name__: m for m in (app, sdk, plugins, schemas, schema_types,
             sdk_plugin, sdk_config, sdk_log, sdk_events, sdk_services, sdk_scheduler)}
    for name in ("plugin", "config", "logging", "events", "services", "scheduler"):
        setattr(sdk, name, stubs["app.sdk." + name])

    # Prefer the interpreter's real third-party dependencies. Minimal doubles are
    # used only when an optional local test environment lacks a dependency.
    try:
        importlib.import_module("apscheduler.triggers.cron")
    except ImportError:
        aps = _module("apscheduler", True)
        triggers = _module("apscheduler.triggers", True)
        cron = _module("apscheduler.triggers.cron")
        interval = _module("apscheduler.triggers.interval")
        class CronTrigger:
            @staticmethod
            def from_crontab(expression):
                if len(expression.split()) != 5:
                    raise ValueError("invalid cron")
                return types.SimpleNamespace(expression=expression)
        class IntervalTrigger:
            def __init__(self, seconds):
                self.seconds = seconds
        cron.CronTrigger, interval.IntervalTrigger = CronTrigger, IntervalTrigger
        aps.triggers, triggers.cron, triggers.interval = triggers, cron, interval
        stubs.update({m.__name__:m for m in (aps, triggers, cron, interval)})
    try:
        importlib.import_module("fastapi")
    except ImportError:
        fastapi = _module("fastapi")
        fastapi.Header = lambda *a, **kw: None
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None):
                self.status_code, self.detail = status_code, detail
        fastapi.HTTPException = HTTPException
        stubs["fastapi"] = fastapi
    try:
        requests = importlib.import_module("requests")
    except ImportError:
        requests = _module("requests")
        requests.Timeout = type("Timeout", (Exception,), {})
        requests.get = lambda *a, **kw: None
        stubs["requests"] = requests
    def deny_network(*args, **kwargs):
        raise AssertionError("ordinary unit tests must not access external networks")
    absent = object()
    module_names = list(stubs) + [MODULE]
    before = {name: sys.modules.get(name, absent) for name in module_names}
    with patch.dict(sys.modules, stubs), patch.object(requests, "get", deny_network):
        sys.modules.pop(MODULE, None)
        module = importlib.import_module(MODULE)
        module._test_env = env
        yield module
    # Verify that SDK mocks and plugin modules cannot leak into other plugins' tests.
    for name, previous in before.items():
        if previous is absent:
            assert name not in sys.modules
        else:
            assert sys.modules.get(name) is previous


class FakeQB:
    def __init__(self):
        self.qbc = types.SimpleNamespace(transfer=types.SimpleNamespace(upload_limit=2048*1024, download_limit=0))
        self.torrents = []
        self.calls = []
    def get_torrents(self):
        self.calls.append("list")
        return [dict(t) for t in self.torrents], None
    def stop_torrents(self, ids):
        self.calls.append(("pause", tuple(ids)))
        for torrent in self.torrents:
            if torrent["hash"] in ids:
                torrent.update(state="pausedUP", upspeed=0)
        return True
    def start_torrents(self, ids):
        self.calls.append(("resume", tuple(ids)))
        for torrent in self.torrents:
            if torrent["hash"] in ids:
                torrent.update(state="stalledUP", upspeed=0)
        return True


@pytest.fixture
def make_plugin(ty):
    def factory(**overrides):
        qb = FakeQB()
        ty._test_env.downloaders["QB"] = types.SimpleNamespace(type="qbittorrent", instance=qb)
        config = dict(enabled=True, notify=False, downloader=["QB"], action="limit",
                      upload_limit=512, download_limit=0, cron="*/1 * * * *", hosts="tablet",
                      detect_mode="webhook", secret="test-secret", heartbeat=0, lost_release=30)
        config.update(overrides)
        plugin = ty.TunnelYield()
        plugin.init_plugin(config)
        plugin._test_qb = qb
        return plugin
    return factory


def peer_index(plugin, online=True):
    return plugin._TunnelYield__build_peer_index(
        [{"ipv4":"10.100.0.3", "hostname":"tablet", "is_online":online}], True)


def video(ip="8.8.8.8", paused=False, path="/media/local/movie.mkv"):
    return {"NowPlayingItem":{"MediaType":"Video", "Name":"Movie", "Path":path},
            "PlayState":{"IsPaused":paused}, "RemoteEndPoint":ip,
            "UserName":"User", "DeviceName":"TV"}


def contents(nodes):
    result=[]
    def visit(node):
        if isinstance(node, dict):
            if "text" in node:
                result.append(str(node["text"]))
            for value in node.values():visit(value)
        elif isinstance(node, list):
            for item in node:visit(item)
    visit(nodes)
    return "\n".join(result)


class TestV3Structure:
    def test_production_import_name(self, ty):
        assert ty.__name__ == MODULE
    def test_repository_layout(self):
        assert PLUGIN.is_file()
        assert "plugins.v3" in PLUGIN.parts
    def test_no_legacy_imports(self):
        tree=ast.parse(PLUGIN.read_text(encoding="utf-8"))
        assert not [n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)
                    and n.module and n.module.startswith(("app.core.","app.helper.","app.utils.","app.sdk._legacy"))]
    def test_no_private_scheduler_or_sleep(self):
        source=PLUGIN.read_text(encoding="utf-8")
        assert "BackgroundScheduler" not in source
        assert "time.sleep(" not in source
    def test_module_import_has_no_jobs(self, ty):
        assert not ty._test_env.once_jobs
    def test_metadata(self, ty):
        assert ty.TunnelYield.plugin_name == "隧道在线带宽释放"
        version = ty.TunnelYield.plugin_version
        assert isinstance(version, str)
        assert version.strip(), "plugin_version 不能为空"
    
        assert ty.TunnelYield.plugin_config_prefix == "tunnelyield_"
        assert ty.SNAPSHOT_SCHEMA == 1
        assert ty.SECRET_HEADER == "X-Tunnel-Secret"


class TestPureLogic:
    @pytest.mark.parametrize("value,expected",[(True,True),(False,False),(1,True),(0,False),(2,None),
        ("True",True),("yes",True),("online",True),("False",False),("no",False),("offline",False),
        ("x",None),(1.5,None),(None,None),([],None)])
    def test_parse_online(self, ty, value, expected):
        assert ty.TunnelYield._TunnelYield__parse_online(value) is expected
    @pytest.mark.parametrize("value,valid",[(1,True),(0,False),(-1,False),(True,False),("1",False)])
    def test_seq(self, ty, value, valid):
        result=ty.TunnelYield._TunnelYield__parse_seq(value)
        assert (result is not None) is valid
    @pytest.mark.parametrize("value,expected",[(None,True),(1,True),(2,False),("1",False),(True,False)])
    def test_schema(self, ty, value, expected):
        assert ty.TunnelYield._TunnelYield__schema_supported(value) is expected
    @pytest.mark.parametrize("value,expected",[(1720000000,1720000000),(0,None),(-5,None),(float("nan"),None),(float("inf"),None),(True,None)])
    def test_timestamp(self, ty, value, expected):
        assert ty.TunnelYield._TunnelYield__parse_snapshot_ts(value) == expected
    def test_parse_ip_ranges(self, ty):
        rules, invalid=ty.parse_unlimited_ips("192.168.1.0/24,10.0.0.1-10.0.0.9,bad")
        assert len(rules)==2 and invalid==["bad"]
    @pytest.mark.parametrize("ip,expected",[("192.168.1.5",True),("127.0.0.1",True),("8.8.8.8",False),("not-an-ip",False),("192.168.1.5:8096",True)])
    def test_default_unlimited(self, ty, ip, expected):
        assert ty.ip_unlimited(ip,[]) is expected
    def test_explicit_ip_and_ipv6(self, ty):
        rules,_=ty.parse_unlimited_ips("8.8.8.0/24,fd00::/8")
        assert ty.ip_unlimited("8.8.8.8",rules)
        assert ty.ip_unlimited("[fd00::123]:8096",rules)
        assert not ty.ip_unlimited("9.9.9.9",rules)
    @pytest.mark.parametrize("state,expected",[("uploading","active"),("stalledUP","active"),("pausedUP","paused"),
        ("stoppedUP","paused"),("missingFiles","errored"),("error","errored"),("queuedForChecking","other"),(None,"unknown")])
    def test_torrent_status(self, ty, state, expected):
        assert ty.QbittorrentAdapter.torrent_status({"state":state})==expected
    def test_parse_hosts(self, make_plugin):
        plugin=make_plugin(hosts="10.0.0.1\nMatePad Pro # 平板\n10.0.0.1\n")
        assert plugin._TunnelYield__parse_hosts()==["10.0.0.1","MatePad Pro"]
    def test_future_decision_not_fresh(self, make_plugin):
        assert not make_plugin()._TunnelYield__decision_fresh(time.time()+100)


class TestLifecycle:
    def test_empty_config_resets_enabled(self, make_plugin):
        plugin=make_plugin()
        plugin.init_plugin({})
        assert not plugin.get_state()
        assert plugin._hosts==""
        assert not plugin._media_enabled
    def test_none_config_resets_enabled(self, make_plugin):
        plugin=make_plugin()
        plugin.init_plugin(None)
        assert not plugin.get_state()
    def test_reinitialize_no_duplicate_once_jobs(self, ty, make_plugin):
        plugin=make_plugin()
        config=dict(enabled=True,downloader=["QB"],secret="test-secret",hosts="tablet")
        plugin.init_plugin(config)
        plugin.init_plugin(config)
        assert len(ty._test_env.once_jobs)==1
    def test_stop_disables_and_cancels(self, ty, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin.on_media_webhook(ty.Event({"event":"PlaybackStart"}))
        old_gen=plugin._gen
        plugin.stop_service()
        assert not plugin.get_state()
        assert plugin._gen>old_gen
        assert not ty._test_env.once_jobs
    def test_stop_does_not_restore_on_reload(self, make_plugin):
        plugin=make_plugin()
        called=[]
        plugin._TunnelYield__restore=lambda:called.append(True)
        plugin.stop_service()
        assert not called
    @pytest.mark.parametrize("value",[-1,float("nan"),float("inf"),True])
    def test_invalid_limits_disable(self, make_plugin, value):
        assert not make_plugin(upload_limit=value).get_state()
    def test_invalid_timeout_defaults_positive(self, make_plugin):
        assert make_plugin(timeout=-5)._timeout==10
    def test_late_media_query_dropped_after_stop(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        entered,resume=threading.Event(),threading.Event()
        applied=[]
        def query():
            entered.set()
            assert resume.wait(2)
            return {"sessions":[],"servers":[],"failed":[]}
        plugin._TunnelYield__query_media=query
        plugin._TunnelYield__apply_media=lambda result:applied.append(result)
        worker=threading.Thread(target=plugin.media_check,daemon=True)
        worker.start()
        try:
            assert entered.wait(2)
            plugin.stop_service()
        finally:
            resume.set();worker.join(2)
        assert not worker.is_alive() and not applied
    def test_late_media_query_dropped_after_reinit(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        entered,resume=threading.Event(),threading.Event()
        applied=[]
        def query():
            entered.set();assert resume.wait(2)
            return {"sessions":[],"servers":[],"failed":[]}
        plugin._TunnelYield__query_media=query
        plugin._TunnelYield__apply_media=lambda result:applied.append(result)
        worker=threading.Thread(target=plugin.media_check,daemon=True);worker.start()
        try:
            assert entered.wait(2)
            plugin.init_plugin(dict(enabled=True,media_monitor=True,downloader=["QB"],secret="test-secret",hosts="tablet"))
        finally:resume.set();worker.join(2)
        assert not applied
    def test_newer_media_result_wins(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        entered,resume=threading.Event(),threading.Event()
        def query():
            if threading.current_thread().name=="older-query":
                entered.set();assert resume.wait(2)
                return {"sessions":[],"servers":["JF"],"failed":[]}
            return {"sessions":[{"user":"User","device":"TV","ip":"8.8.8.8","item":"Movie"}],"servers":["JF"],"failed":[]}
        plugin._TunnelYield__query_media=query
        worker=threading.Thread(target=plugin.media_check,name="older-query",daemon=True);worker.start()
        try:
            assert entered.wait(2);plugin.media_check()
        finally:resume.set();worker.join(2)
        assert plugin._media_state=="playing"


class TestSchedulingAndAPI:
    def test_event_schedules_instead_of_querying(self, ty, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin._TunnelYield__query_media=lambda:pytest.fail("event callback must not query synchronously")
        plugin.on_media_webhook(ty.Event({"event":"PlaybackStop"}))
        func,delay=ty._test_env.once_jobs[("TunnelYield","TunnelYieldMediaRefresh")]
        assert func.__self__ is plugin and delay==3
    def test_event_coalesces_and_not_replace_startup_sync(self, ty, make_plugin):
        plugin=make_plugin(media_monitor=True)
        for name in ("PlaybackStart","PlaybackStop","PlaybackStart"):
            plugin.on_media_webhook(ty.Event({"event":name}))
        assert set(ty._test_env.once_jobs)=={("TunnelYield","TunnelYieldOnce"),("TunnelYield","TunnelYieldMediaRefresh")}
        assert ty._test_env.once_jobs[("TunnelYield","TunnelYieldMediaRefresh")][1]==1
    def test_unknown_event_ignored(self, ty, make_plugin):
        plugin=make_plugin(media_monitor=True)
        before=len(ty._test_env.once_calls)
        plugin.on_media_webhook(ty.Event({"event":"ItemAdded"}))
        assert len(ty._test_env.once_calls)==before
    def test_scheduler_failure_no_private_fallback(self, ty, make_plugin):
        ty._test_env.scheduler_ok=False
        plugin=make_plugin()
        assert plugin.get_state()
        assert not ty._test_env.once_jobs
    def test_periodic_services_and_disable(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        ids={job["id"] for job in plugin.get_service()}
        assert {"TunnelYieldCompensate","TunnelYieldMediaCheck","TunnelYieldLostCheck"}<=ids
        plugin.stop_service();assert plugin.get_service()==[]
    def test_poll_services(self, make_plugin):
        plugin=make_plugin(detect_mode="poll")
        ids={job["id"] for job in plugin.get_service()}
        assert "TunnelYieldCheck" in ids and "TunnelYieldCompensate" not in ids
    def test_api_has_auth(self, make_plugin):
        declaration=make_plugin().get_api()[0]
        assert declaration["auth"]=="apikey" and declaration["methods"]==["POST"]
    def test_bad_secret(self, ty, make_plugin):
        plugin=make_plugin()
        with pytest.raises(ty.HTTPException) as error:
            plugin.api_webhook({},x_webhook_secret="bad")
        assert error.value.status_code==401
    @pytest.mark.parametrize("payload",[{}, {"schema":2,"peer_list":[{}]}, {"peer_list":[]},
        {"seq":1,"peer_list":[{"hostname":"tablet","is_online":"false"}]},
        {"seq":True,"peer_list":[{"hostname":"tablet","is_online":True}]}])
    def test_invalid_payload_rejected(self, make_plugin, payload):
        response=make_plugin().api_webhook(payload,x_webhook_secret="test-secret")
        assert response.success is False
    def test_old_seq_does_not_change_state(self, make_plugin):
        plugin=make_plugin()
        assert plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=2) is None
        assert plugin._TunnelYield__apply_peers(peer_index(plugin,False),None,seq=1)=="stale"
        assert plugin._state["decision"]=="online"
    def test_equal_seq_different_content_conflict(self, make_plugin):
        plugin=make_plugin()
        plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=2)
        assert plugin._TunnelYield__apply_peers(peer_index(plugin,False),None,seq=2)=="conflict"
    def test_instance_id_in_detail_url(self, ty, make_plugin):
        plugin=make_plugin()
        clone=type("TunnelYieldInstance",(ty.TunnelYield,),{})
        plugin.__class__=clone
        assert "/api/v1/plugin/TunnelYieldInstance/webhook" in contents(plugin.get_page())
    def test_form_defaults(self, make_plugin):
        form,defaults=make_plugin().get_form()
        assert form and defaults["downloader"]==[]
        assert "media_monitor" in defaults
        json.dumps(form,ensure_ascii=False)


class TestDownloaderSafety:
    def test_limit_then_restore_original(self, make_plugin):
        plugin=make_plugin();qb=plugin._test_qb
        plugin._TunnelYield__release()
        assert qb.qbc.transfer.upload_limit==512*1024
        assert plugin._state["downloaders"]["QB"]["orig_limits"]["upload"]==2048
        plugin._TunnelYield__restore()
        assert qb.qbc.transfer.upload_limit==2048*1024
        assert plugin._state["downloaders"]["QB"]["orig_limits"] is None
    def test_state_write_failure_prevents_limit(self, make_plugin):
        plugin=make_plugin();qb=plugin._test_qb
        plugin._TunnelYield__save_state=lambda:False
        plugin._TunnelYield__release()
        assert qb.qbc.transfer.upload_limit==2048*1024
    def test_read_failure_prevents_limit(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin();qb=plugin._test_qb
        monkeypatch.setattr(ty.QbittorrentAdapter,"read_limits",lambda self:None)
        plugin._TunnelYield__release()
        assert qb.qbc.transfer.upload_limit==2048*1024
    def test_pause_only_uploading_and_restore_owned(self, make_plugin):
        plugin=make_plugin(action="pause");qb=plugin._test_qb
        qb.torrents=[{"hash":"upload","state":"uploading","upspeed":100},
                     {"hash":"idle","state":"stalledUP","upspeed":0},
                     {"hash":"manual","state":"pausedUP","upspeed":0}]
        plugin._TunnelYield__release()
        assert ("pause",("upload",)) in qb.calls
        plugin._TunnelYield__restore()
        assert ("resume",("upload",)) in qb.calls
        assert next(t for t in qb.torrents if t["hash"]=="manual")["state"]=="pausedUP"
    def test_pause_exception_pending_not_resumed(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(action="pause");qb=plugin._test_qb
        qb.torrents=[{"hash":"x","state":"uploading","upspeed":100}]
        def fail(self,hashes):raise TimeoutError()
        monkeypatch.setattr(ty.QbittorrentAdapter,"pause",fail)
        plugin._TunnelYield__release()
        assert plugin._state["downloaders"]["QB"]["pending_hashes"]==["x"]
        plugin._TunnelYield__restore()
        assert not any(isinstance(call,tuple) and call[0]=="resume" for call in qb.calls)
    def test_unavailable_one_downloader_does_not_block_other(self, ty, make_plugin):
        plugin=make_plugin(downloader=["missing","QB"])
        plugin._TunnelYield__release()
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_disable_restores(self, make_plugin):
        plugin=make_plugin();qb=plugin._test_qb
        plugin._TunnelYield__release()
        plugin.init_plugin(dict(enabled=False,downloader=["QB"]))
        assert qb.qbc.transfer.upload_limit==2048*1024
    def test_no_recovery_record_no_downloader_call(self, make_plugin):
        plugin=make_plugin()
        plugin._test_qb.calls.clear()
        plugin._TunnelYield__restore()
        assert plugin._test_qb.calls==[]


class TestMedia:
    @pytest.mark.parametrize("paused,expected",[(False,True),(True,False),("false",True),("true",False),(0,True),(1,False)])
    def test_pause_boolean(self, ty, paused, expected):
        entry=ty.TunnelYield._TunnelYield__playing_entry(video(paused=paused),"JF","jellyfin",[],[])
        assert (entry is not None) is expected
    def test_private_playback_ignored(self, ty):
        assert ty.TunnelYield._TunnelYield__playing_entry(video(ip="192.168.1.2"),"JF","jellyfin",[],[]) is None
    def test_path_exclusion(self, ty):
        assert ty.TunnelYield._TunnelYield__playing_entry(video(path="/media/cloud/movie.mkv"),"JF","jellyfin",[],["/cloud/"]) is None
    def test_blank_path_rule_does_not_exclude_everything(self, ty):
        assert ty.TunnelYield._TunnelYield__playing_entry(video(),"JF","jellyfin",[],[""]) is not None
    def test_none_path_safe(self, ty):
        assert ty.TunnelYield._TunnelYield__playing_entry(video(path=None),"JF","jellyfin",[],["/cloud/"]) is not None
    def test_empty_config_exclude_lines_cleaned(self, make_plugin):
        plugin=make_plugin(exclude_path="/cloud/\n\n  \n")
        assert plugin._exclude_paths==["/cloud/"]
    def test_malformed_session_server_unknown(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(media_monitor=True)
        monkeypatch.setattr(ty,"list_media_services",lambda:{"JF":("jellyfin",object())})
        monkeypatch.setattr(ty,"fetch_media_sessions",lambda *a:[123])
        result=plugin._TunnelYield__query_media()
        assert result["sessions"] is None and result["failed"]==["JF"]
    def test_valid_playback_other_server_failed_still_plays(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(media_monitor=True)
        monkeypatch.setattr(ty,"list_media_services",lambda:{"bad":("jellyfin",0),"good":("jellyfin",1)})
        monkeypatch.setattr(ty,"fetch_media_sessions",lambda kind,instance:None if instance==0 else [video()])
        result=plugin._TunnelYield__query_media()
        assert len(result["sessions"])==1 and result["failed"]==["bad"]
    def test_media_idle_does_not_override_tunnel_online(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=1)
        plugin._TunnelYield__apply_media({"sessions":[],"servers":["JF"],"failed":[]})
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_tunnel_offline_does_not_override_media_playing(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin._TunnelYield__apply_media({"sessions":[{"user":"u","device":"d","ip":"8.8.8.8","item":"m"}],"servers":["JF"],"failed":[]})
        plugin._TunnelYield__apply_peers(peer_index(plugin,False),None,seq=1)
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_both_idle_restores(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin._TunnelYield__apply_media({"sessions":[{"user":"u","device":"d","ip":"8.8.8.8","item":"m"}],"servers":["JF"],"failed":[]})
        plugin._TunnelYield__apply_peers(peer_index(plugin,False),None,seq=1)
        plugin._TunnelYield__apply_media({"sessions":[],"servers":["JF"],"failed":[]})
        assert plugin._test_qb.qbc.transfer.upload_limit==2048*1024
    def test_media_unknown_holds_then_expires(self, make_plugin):
        plugin=make_plugin(media_monitor=True,hosts="")
        plugin._TunnelYield__apply_media({"sessions":[{"user":"u","device":"d","ip":"8.8.8.8","item":"m"}],"servers":["JF"],"failed":[]})
        plugin._TunnelYield__apply_media({"sessions":None,"servers":["JF"],"failed":["JF"]})
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
        plugin._media_unknown_since=time.time()-plugin.MEDIA_UNKNOWN_HOLD-1
        plugin._TunnelYield__apply_media({"sessions":None,"servers":["JF"],"failed":["JF"]})
        assert plugin._test_qb.qbc.transfer.upload_limit==2048*1024
    def test_fetch_standard_jellyfin_key_and_close(self, ty):
        class Result:
            status_code=200
            closed=False
            def json(self):return []
            def close(self):self.closed=True
        result=Result();calls=[]
        instance=types.SimpleNamespace(get_data=lambda url:calls.append(url) or result)
        assert ty.fetch_media_sessions("jellyfin",instance)==[]
        assert "?ApiKey=[APIKEY]" in calls[0] and result.closed
    def test_failed_fetch_not_idle(self, ty):
        instance=types.SimpleNamespace(get_data=lambda url:None)
        assert ty.fetch_media_sessions("jellyfin",instance) is None
    def test_media_types_unsupported_not_fnos(self, ty):
        assert "trimemedia" not in ty.MEDIA_SERVER_TYPES


class TestAdditionalSafety:
    def test_secret_empty_does_not_pass(self, make_plugin):
        plugin=make_plugin(secret="")
        assert not plugin._TunnelYield__secret_ok("")
    def test_media_unknown_does_not_release_during_hold(self, make_plugin):
        plugin=make_plugin(media_monitor=True,hosts="")
        plugin._TunnelYield__release()
        plugin._TunnelYield__apply_media({"sessions":None,"servers":["JF"],"failed":["JF"]})
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_lost_tunnel_does_not_override_media(self, make_plugin):
        plugin=make_plugin(media_monitor=True)
        plugin._TunnelYield__apply_media({"sessions":[{"user":"u","device":"d","ip":"8.8.8.8","item":"m"}],"servers":["JF"],"failed":[]})
        plugin._run_started=time.time()-4000
        plugin._state["contact_ts"]=time.time()-4000
        plugin.lost_check()
        assert plugin._state["decision"]=="lost"
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_lost_tunnel_without_media_restores(self, make_plugin):
        plugin=make_plugin()
        plugin._TunnelYield__release()
        plugin._run_started=time.time()-4000
        plugin._state["contact_ts"]=time.time()-4000
        plugin.lost_check()
        assert plugin._state["decision"]=="lost"
        assert plugin._test_qb.qbc.transfer.upload_limit==2048*1024
    def test_recovered_tunnel_reapplies(self, make_plugin):
        plugin=make_plugin()
        plugin._TunnelYield__release()
        plugin._run_started=time.time()-4000
        plugin.lost_check()
        assert plugin._test_qb.qbc.transfer.upload_limit==2048*1024
        plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=10)
        assert plugin._state["decision"]=="online"
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_query_response_closed(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(api_url="http://collector.local/")
        class Result:
            closed=False
            def raise_for_status(self):pass
            def json(self):return {"schema":1,"seq":1,"peer_list":[{"hostname":"tablet","is_online":True}]}
            def close(self):self.closed=True
        response=Result();monkeypatch.setattr(ty.requests,"get",lambda *a,**kw:response)
        plugin.check()
        assert response.closed
        assert plugin._state["decision"]=="online"
    def test_query_failure_preserves_limit(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(api_url="http://collector.local/")
        plugin._TunnelYield__release()
        def fail(*a,**kw):raise ty.requests.Timeout()
        monkeypatch.setattr(ty.requests,"get",fail)
        plugin.check()
        assert not plugin._synced
        assert plugin._test_qb.qbc.transfer.upload_limit==512*1024
    def test_same_seq_same_content_resync(self, make_plugin):
        plugin=make_plugin()
        plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=10)
        plugin._synced=False
        assert plugin._TunnelYield__apply_peers(peer_index(plugin,True),None,seq=10) is None
        assert plugin._synced
    def test_limit_records_survive_new_instance(self, ty, make_plugin):
        plugin=make_plugin()
        plugin._TunnelYield__release()
        newer=ty.TunnelYield()
        newer.init_plugin(dict(enabled=True,notify=False,downloader=["QB"],action="limit",upload_limit=512,hosts="tablet",secret="test-secret",heartbeat=0))
        assert newer._state["downloaders"]["QB"]["orig_limits"]["upload"]==2048
    def test_string_false_active_is_ignored(self, ty):
        value=video();value["IsActive"]="false"
        assert ty.TunnelYield._TunnelYield__playing_entry(value,"JF","jellyfin",[],[]) is None
    def test_bad_paused_value_server_is_unknown(self, ty, make_plugin, monkeypatch):
        plugin=make_plugin(media_monitor=True)
        monkeypatch.setattr(ty,"list_media_services",lambda:{"JF":("jellyfin",object())})
        monkeypatch.setattr(ty,"fetch_media_sessions",lambda *a:[video(paused="garbage")])
        assert plugin._TunnelYield__query_media()["sessions"] is None
    def test_camelcase_media_response(self, ty):
        entry={"nowPlayingItem":{"mediaType":"Video","name":"Movie"},"playState":{"isPaused":"false"},"remoteEndPoint":"8.8.8.8"}
        assert ty.TunnelYield._TunnelYield__playing_entry(entry,"JF","jellyfin",[],[]) is not None
