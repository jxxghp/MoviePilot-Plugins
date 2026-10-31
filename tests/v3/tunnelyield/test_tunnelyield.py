# tests/v3/tunnelyield/test_tunnelyield.py
"""
TunnelYield 插件最小测试。

不依赖 MoviePilot 运行时：导入插件模块前桩掉 app.* / fastapi / apscheduler，
只覆盖模块内的纯函数逻辑（无下载器、无网络、无调度器）。
"""
import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# 最小运行时桩
# ---------------------------------------------------------------------------

def _install_app_stubs():
    """提供导入插件所需的最小 app.* 桩；测试环境已有真实桩时跳过。"""
    if "app" in sys.modules:
        return

    app = types.ModuleType("app")
    schemas = types.ModuleType("app.schemas")

    class _Response:
        def __init__(self, success=False, message=None, data=None):
            self.success = success
            self.message = message
            self.data = data

    schemas.Response = _Response
    app.schemas = schemas

    core = types.ModuleType("app.core")
    config = types.ModuleType("app.core.config")
    config.settings = types.SimpleNamespace(TZ="Asia/Shanghai")
    core.config = config

    log = types.ModuleType("app.log")

    class _Logger:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    log.logger = _Logger()

    plugins = types.ModuleType("app.plugins")

    class _PluginBase:
        def update_config(self, config):
            self._saved_config = config

        def post_message(self, **kwargs):
            pass

        def get_data_path(self):
            import tempfile
            return Path(tempfile.mkdtemp())

    plugins._PluginBase = _PluginBase

    schemas_types = types.ModuleType("app.schemas.types")
    schemas_types.EventType = types.SimpleNamespace(WebhookMessage="webhook.message")
    schemas_types.MessageType = types.SimpleNamespace(Plugin="plugin")

    # 优先走 V3 SDK 事件路径，避免回退 import app.core.event
    sdk = types.ModuleType("app.sdk")
    sdk_events = types.ModuleType("app.sdk.events")

    class _Event:
        event_data = None

    class _EventManager:
        def register(self, event_type):
            def deco(func):
                return func
            return deco

    sdk_events.Event = _Event
    sdk_events.eventmanager = _EventManager()
    sdk.events = sdk_events

    for m in (app, schemas, core, config, log, plugins, schemas_types, sdk, sdk_events):
        sys.modules[m.__name__] = m


def _ensure_third_party(name, factory):
    """CI 环境缺少 fastapi/apscheduler 时补最小桩，保证插件模块可导入。"""
    try:
        __import__(name)
    except ImportError:
        for mod in factory():
            sys.modules[mod.__name__] = mod


def _fastapi_stub():
    fastapi = types.ModuleType("fastapi")
    fastapi.Header = lambda *a, **k: None
    fastapi.HTTPException = type("HTTPException", (Exception,), {})
    return (fastapi,)


def _apscheduler_stub():
    def _pkg(name):
        return types.ModuleType(name)

    apscheduler = _pkg("apscheduler")
    schedulers = _pkg("apscheduler.schedulers")
    background = _pkg("apscheduler.schedulers.background")
    background.BackgroundScheduler = type("BackgroundScheduler", (), {})
    triggers = _pkg("apscheduler.triggers")
    cron = _pkg("apscheduler.triggers.cron")
    cron.CronTrigger = type("CronTrigger", (), {"from_crontab": staticmethod(lambda *a, **k: None)})
    interval = _pkg("apscheduler.triggers.interval")
    interval.IntervalTrigger = type("IntervalTrigger", (), {})
    apscheduler.schedulers = schedulers
    schedulers.background = background
    apscheduler.triggers = triggers
    triggers.cron = cron
    triggers.interval = interval
    return (apscheduler, schedulers, background, triggers, cron, interval)


_install_app_stubs()
_ensure_third_party("fastapi", _fastapi_stub)
_ensure_third_party("apscheduler", _apscheduler_stub)

# ---------------------------------------------------------------------------
# 从文件路径加载被测插件（不依赖 plugins.v3 包结构）
# ---------------------------------------------------------------------------

_PLUGIN_PATH = (
    Path(__file__).resolve().parents[3] / "plugins" / "v3" / "tunnelyield" / "__init__.py"
)
_spec = importlib.util.spec_from_file_location("tunnelyield_plugin", _PLUGIN_PATH)
ty = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ty
_spec.loader.exec_module(ty)


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

class TestPluginMetadata:
    def test_basic_info(self):
        assert ty.TunnelYield.plugin_name == "隧道在线带宽释放"
        assert ty.TunnelYield.plugin_version
        assert ty.TunnelYield.plugin_config_prefix == "tunnelyield_"

    def test_snapshot_schema(self):
        assert ty.SNAPSHOT_SCHEMA == 1
        assert ty.SECRET_HEADER


class TestParseOnline:
    """__parse_online 的严格解析：字符串 "false"、非法数值不得误判。"""

    _parse = ty.TunnelYield._TunnelYield__parse_online

    def test_bool_passthrough(self):
        assert self._parse(True) is True
        assert self._parse(False) is False

    def test_int_only_0_and_1(self):
        assert self._parse(1) is True
        assert self._parse(0) is False
        assert self._parse(2) is None

    def test_string_aliases(self):
        assert self._parse("True") is True
        assert self._parse("yes") is True
        assert self._parse("online") is True
        assert self._parse("False") is False
        assert self._parse("no") is False
        assert self._parse("offline") is False

    def test_garbage_is_unknown(self):
        assert self._parse("x") is None
        assert self._parse(1.5) is None
        assert self._parse(None) is None
        assert self._parse([]) is None


class TestSnapshotGuards:
    """seq / schema / 时间戳的入口校验。"""

    def test_seq_must_be_positive_int(self):
        parse = ty.TunnelYield._TunnelYield__parse_seq
        assert parse(1) == 1
        assert parse(0) is None
        assert parse(-1) is None
        assert parse(True) is None  # bool 是 int 子类，必须排除
        assert parse("1") is None

    def test_schema_only_v1(self):
        ok = ty.TunnelYield._TunnelYield__schema_supported
        assert ok(None) is True   # 缺省视为 1
        assert ok(1) is True
        assert ok(2) is False
        assert ok("1") is False

    def test_timestamp_must_be_finite_positive(self):
        parse = ty.TunnelYield._TunnelYield__parse_snapshot_ts
        assert parse(1720000000) == 1720000000
        assert parse(0) is None
        assert parse(-5) is None
        assert parse(float("nan")) is None
        assert parse(float("inf")) is None


class TestIpRules:
    def test_parse_cidr_and_range(self):
        rules, invalid = ty.parse_unlimited_ips("192.168.1.0/24,10.0.0.1-10.0.0.9,bad")
        assert len(rules) == 2
        assert invalid == ["bad"]

    def test_default_private_unlimited(self):
        # 未填写规则：默认内网/本机不限速，公网参与让位
        assert ty.ip_unlimited("192.168.1.5", []) is True
        assert ty.ip_unlimited("127.0.0.1", []) is True
        assert ty.ip_unlimited("8.8.8.8", []) is False

    def test_with_explicit_rules(self):
        rules, _ = ty.parse_unlimited_ips("8.8.8.0/24")
        assert ty.ip_unlimited("8.8.8.8", rules) is True
        assert ty.ip_unlimited("9.9.9.9", rules) is False

    def test_ipv6_and_port_forms(self):
        rules, _ = ty.parse_unlimited_ips("fd00::/8")
        assert ty.ip_unlimited("[fd00::123]:8096", rules) is True
        assert ty.ip_unlimited("192.168.1.5:8096", []) is True

    def test_unparseable_counts_as_external(self):
        assert ty.ip_unlimited("not-an-ip", []) is False


class TestTorrentStatus:
    """state_enum 不可用时的字符串状态兜底映射。"""

    _status = staticmethod(ty.QbittorrentAdapter.torrent_status)

    def test_active_states(self):
        assert self._status({"state": "uploading"}) == "active"
        assert self._status({"state": "stalledUP"}) == "active"

    def test_paused_states(self):
        assert self._status({"state": "pausedUP"}) == "paused"
        assert self._status({"state": "stoppedUP"}) == "paused"

    def test_errored_states(self):
        assert self._status({"state": "missingFiles"}) == "errored"
        assert self._status({"state": "error"}) == "errored"

    def test_unknown_and_other(self):
        assert self._status({}) == "unknown"
        assert self._status({"state": "queuedForChecking"}) == "other"


class TestParseHosts:
    def test_multiline_and_comment(self):
        obj = ty.TunnelYield()
        obj._hosts = "10.0.0.1\nMatePad Pro  # 平板\n10.0.0.1\n"
        assert obj._TunnelYield__parse_hosts() == ["10.0.0.1", "MatePad Pro"]
