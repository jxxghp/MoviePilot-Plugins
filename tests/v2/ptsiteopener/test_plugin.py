import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins.v2"
    / "ptsiteopener"
    / "__init__.py"
)


class FakeBase:
    def __init__(self):
        self._config = {}

    def update_config(self, config):
        self._config = config


class FakeCronTrigger:
    def __init__(self, expression):
        self.expression = expression

    @classmethod
    def from_crontab(cls, expression):
        if expression == "invalid":
            raise ValueError("invalid cron expression")
        if len(expression.split()) != 5:
            raise ValueError("cron must contain five fields")
        return cls(expression)


class QuietLogger:
    def __init__(self):
        self.messages = []

    def debug(self, message):
        self.messages.append(("debug", message))

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class PluginTestCase(unittest.TestCase):
    def setUp(self):
        app_module = types.ModuleType("app")
        plugins_module = types.ModuleType("app.plugins")
        plugins_module._PluginBase = FakeBase
        db_module = types.ModuleType("app.db")
        site_oper_module = types.ModuleType("app.db.site_oper")
        site_oper_module.SiteOper = lambda: None
        log_module = types.ModuleType("app.log")
        log_module.logger = QuietLogger()

        apscheduler_module = types.ModuleType("apscheduler")
        triggers_module = types.ModuleType("apscheduler.triggers")
        cron_module = types.ModuleType("apscheduler.triggers.cron")
        cron_module.CronTrigger = FakeCronTrigger

        modules = {
            "app": app_module,
            "app.plugins": plugins_module,
            "app.db": db_module,
            "app.db.site_oper": site_oper_module,
            "app.log": log_module,
            "apscheduler": apscheduler_module,
            "apscheduler.triggers": triggers_module,
            "apscheduler.triggers.cron": cron_module,
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()

        spec = importlib.util.spec_from_file_location("ptsiteopener_under_test", PLUGIN_PATH)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        if spec.loader is None:
            raise AssertionError("plugin module loader is unavailable")
        spec.loader.exec_module(self.module)
        self.original_timer = self.module.threading.Timer

    def tearDown(self):
        self.module.threading.Timer = self.original_timer
        self.module_patch.stop()

    def test_select_site_urls_filters_active_web_sites_and_deduplicates(self):
        sites = [
            types.SimpleNamespace(id=1, url="https://one.example/", is_active=True),
            types.SimpleNamespace(id=2, url="https://one.example/", is_active=True),
            types.SimpleNamespace(id=3, url="ftp://ignored.example/", is_active=True),
            types.SimpleNamespace(id=4, url="https://inactive.example/", is_active=False),
            types.SimpleNamespace(id=5, url="http://two.example/", is_active=True),
        ]

        self.assertEqual(
            self.module.select_site_urls(sites),
            ["https://one.example/", "http://two.example/"],
        )
        self.assertEqual(
            self.module.select_site_urls(
                sites, site_mode="selected", selected_site_ids=["5"]
            ),
            ["http://two.example/"],
        )

    def test_resolve_websocket_url_uses_remote_cdp_host(self):
        self.assertEqual(
            self.module.resolve_websocket_url(
                {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/id"},
                "http://music.lulin.fun:5656/json/version",
            ),
            "ws://music.lulin.fun:5656/devtools/browser/id",
        )

    def test_plugin_registers_user_cron_and_has_expected_defaults(self):
        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True})

        form, model = plugin.get_form()
        self.assertTrue(form)
        self.assertEqual(model["schedule"], "0 */6 * * *")
        self.assertEqual(model["ttl_minutes"], 5)
        self.assertTrue(plugin.get_state())

        services = plugin.get_service()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["trigger"].expression, "0 */6 * * *")
        self.assertEqual(services[0]["func"], plugin.run_once)

    def test_invalid_cron_disables_service(self):
        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True, "schedule": "invalid"})

        self.assertFalse(plugin.get_state())
        self.assertEqual(plugin.get_service(), [])

    def test_run_once_opens_active_sites_and_closes_only_its_targets(self):
        sites = [
            types.SimpleNamespace(id=1, url="https://one.example/", is_active=True),
            types.SimpleNamespace(id=2, url="https://failed.example/", is_active=True),
            types.SimpleNamespace(id=3, url="https://two.example/", is_active=True),
        ]
        cdp = FakeCdp()
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True, "ttl_minutes": 5})
        plugin._connect_cdp = lambda: cdp

        result = plugin.run_once()

        self.assertEqual(result, ["https://one.example/", "https://two.example/"])
        self.assertEqual(cdp.closed, [])
        self.assertEqual(len(FakeTimer.instances), 1)
        timer = FakeTimer.instances[0]
        self.assertEqual(timer.delay, 300)

        timer.function(*timer.args, **timer.kwargs)
        self.assertEqual(cdp.closed, ["opened-1", "opened-2"])
        self.assertFalse(cdp.connected)

    def test_stop_service_cleans_outstanding_run(self):
        sites = [types.SimpleNamespace(id=1, url="https://one.example/", is_active=True)]
        cdp = FakeCdp()
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True})
        plugin._connect_cdp = lambda: cdp
        plugin.run_once()

        plugin.stop_service()

        self.assertEqual(cdp.closed, ["opened-1"])
        self.assertFalse(cdp.connected)
        self.assertTrue(FakeTimer.instances[0].cancelled)


class FakeCdp:
    def __init__(self):
        self.calls = []
        self.closed = []
        self.connected = True
        self.next_target = 0

    def send(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "Target.createTarget":
            if params["url"] == "https://failed.example/":
                raise RuntimeError("target rejected")
            self.next_target += 1
            return {"targetId": f"opened-{self.next_target}"}
        if method == "Target.activateTarget":
            return {}
        if method == "Target.closeTarget":
            self.closed.append(params["targetId"])
            return {"success": True}
        raise AssertionError(f"unexpected CDP method: {method}")

    def close(self):
        self.connected = False


class FakeTimer:
    instances = []

    def __init__(self, delay, function, args=None, kwargs=None):
        self.delay = delay
        self.function = function
        self.args = args or []
        self.kwargs = kwargs or {}
        self.cancelled = False
        self.started = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


if __name__ == "__main__":
    unittest.main()
