import importlib.util
import json
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
PACKAGE_PATH = PLUGIN_PATH.parents[2] / "package.v2.json"


class FakeBase:
    def __init__(self):
        self._config = {}
        self.messages = []

    def update_config(self, config):
        self._config = config

    def post_message(self, **kwargs):
        self.messages.append(kwargs)


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


class FakeEventManager:
    def register(self, _event_type):
        def decorator(func):
            return func

        return decorator


class PluginTestCase(unittest.TestCase):
    def setUp(self):
        app_module = types.ModuleType("app")
        api_module = types.ModuleType("app.api")
        api_endpoints_module = types.ModuleType("app.api.endpoints")
        plugin_api_module = types.ModuleType("app.api.endpoints.plugin")
        self.registered_api_plugins = []

        def register_plugin_api(plugin_id=None):
            self.registered_api_plugins.append(plugin_id)

        plugin_api_module.register_plugin_api = register_plugin_api
        plugins_module = types.ModuleType("app.plugins")
        plugins_module._PluginBase = FakeBase
        core_module = types.ModuleType("app.core")
        event_module = types.ModuleType("app.core.event")
        event_module.Event = types.SimpleNamespace
        event_module.eventmanager = FakeEventManager()
        db_module = types.ModuleType("app.db")
        site_oper_module = types.ModuleType("app.db.site_oper")
        site_oper_module.SiteOper = lambda: None
        log_module = types.ModuleType("app.log")
        log_module.logger = QuietLogger()
        self.logger = log_module.logger

        apscheduler_module = types.ModuleType("apscheduler")
        triggers_module = types.ModuleType("apscheduler.triggers")
        cron_module = types.ModuleType("apscheduler.triggers.cron")
        cron_module.CronTrigger = FakeCronTrigger
        schemas_types_module = types.ModuleType("app.schemas.types")
        schemas_types_module.NotificationType = types.SimpleNamespace(Plugin="plugin")
        schemas_types_module.EventType = types.SimpleNamespace(PluginReload="plugin_reload")

        modules = {
            "app": app_module,
            "app.api": api_module,
            "app.api.endpoints": api_endpoints_module,
            "app.api.endpoints.plugin": plugin_api_module,
            "app.plugins": plugins_module,
            "app.core": core_module,
            "app.core.event": event_module,
            "app.db": db_module,
            "app.db.site_oper": site_oper_module,
            "app.log": log_module,
            "app.schemas.types": schemas_types_module,
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

    def test_cdp_send_includes_target_session_id(self):
        socket = FakeSocket([json.dumps({"id": 1, "result": {}})])
        connection = self.module._CdpConnection(socket)

        connection.send("Network.enable", session_id="session-1")

        message = json.loads(socket.sent[0])
        self.assertEqual(message["sessionId"], "session-1")

    def test_plugin_registers_user_cron_and_has_expected_defaults(self):
        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True})

        form, model = plugin.get_form()
        self.assertTrue(form)
        self.assertEqual(model["schedule"], "0 */6 * * *")
        self.assertEqual(model["ttl_minutes"], 5)
        self.assertFalse(model["notify_enabled"])
        self.assertTrue(plugin.get_state())

        services = plugin.get_service()
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["trigger"].expression, "0 */6 * * *")
        self.assertEqual(services[0]["func"], plugin.run_once)

        components = []
        nodes = []

        def collect(items):
            for item in items:
                nodes.append(item)
                components.append(item.get("component"))
                collect(item.get("content", []))

        collect(form)
        self.assertIn("VRow", components)
        self.assertIn("VCol", components)
        self.assertIn("VSwitch", components)
        schedule_field = next(
            item for item in nodes if item.get("props", {}).get("model") == "schedule"
        )
        self.assertEqual(schedule_field["props"]["label"], "计划任务 Cron（五段）")
        self.assertNotIn("hint", schedule_field["props"])

        api = plugin.get_api()
        self.assertEqual(len(api), 1)
        self.assertEqual(api[0]["path"], "/run")
        self.assertEqual(api[0]["methods"], ["POST"])

    def test_localized_plugin_text_is_utf8_and_not_replacement_questions(self):
        plugin = self.module.PTSiteOpener()
        form, _ = plugin.get_form()

        self.assertEqual(plugin.plugin_version, "1.1.3")
        self.assertNotIn("?", plugin.plugin_name)
        self.assertNotIn("?", plugin.plugin_desc)

        localized_values = []

        def collect_text(items):
            for item in items:
                props = item.get("props", {})
                for key in ("label", "placeholder"):
                    value = props.get(key)
                    if isinstance(value, str):
                        localized_values.append(value)
                value = item.get("text")
                if isinstance(value, str):
                    localized_values.append(value)
                collect_text(item.get("content", []))

        collect_text(form)
        self.assertTrue(localized_values)
        self.assertTrue(all("?" not in value for value in localized_values))

        metadata = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))["PTSiteOpener"]
        self.assertEqual(metadata["version"], plugin.plugin_version)
        for key in ("name", "description", "labels"):
            self.assertNotIn("?", metadata[key])

    def test_parse_site_cookie_preserves_equals_and_skips_invalid_segments(self):
        self.assertEqual(
            self.module.parse_site_cookie(
                "sid=abc==; invalid; theme=dark; =missing-name;"
            ),
            [("sid", "abc=="), ("theme", "dark")],
        )
        self.assertEqual(self.module.parse_site_cookie(None), [])

    def test_cookie_reuse_switch_defaults_to_enabled(self):
        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True})

        form, model = plugin.get_form()

        self.assertTrue(model["reuse_site_cookie"])
        switches = []

        def collect(items):
            for item in items:
                if item.get("component") == "VSwitch":
                    switches.append(item)
                collect(item.get("content", []))

        collect(form)
        self.assertIn(
            "reuse_site_cookie",
            [item.get("props", {}).get("model") for item in switches],
        )

    def test_manual_run_button_is_on_data_page_not_config_form(self):
        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True})

        form, _ = plugin.get_form()
        form_buttons = []
        page_buttons = []

        def collect(items, buttons):
            for item in items:
                if item.get("component") == "VBtn":
                    buttons.append(item)
                collect(item.get("content", []), buttons)

        collect(form, form_buttons)
        collect(plugin.get_page(), page_buttons)

        self.assertFalse(form_buttons)
        self.assertEqual(len(page_buttons), 1)
        self.assertEqual(page_buttons[0]["text"], "立即执行")
        self.assertEqual(page_buttons[0]["events"]["click"]["api"], "plugin/PTSiteOpener/run")
        self.assertEqual(page_buttons[0]["events"]["click"]["method"], "post")

    def test_plugin_reload_re_registers_api_routes(self):
        plugin = self.module.PTSiteOpener()

        plugin.reload(types.SimpleNamespace(event_data={"plugin_id": "PTSiteOpener"}))

        self.assertEqual(self.registered_api_plugins, ["PTSiteOpener"])

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

    def test_run_once_injects_site_cookie_before_navigation(self):
        sites = [
            types.SimpleNamespace(
                id=1,
                name="One",
                url="https://one.example/",
                is_active=True,
                cookie="sid=abc==; theme=dark;",
            )
        ]
        cdp = FakeCdp()
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True, "ttl_minutes": 5})
        plugin._connect_cdp = lambda: cdp

        result = plugin.run_once()

        self.assertEqual(result, ["https://one.example/"])
        self.assertEqual(
            [method for method, _, _ in cdp.calls],
            [
                "Target.createTarget",
                "Target.attachToTarget",
                "Network.setCookie",
                "Network.setCookie",
                "Page.navigate",
                "Target.activateTarget",
            ],
        )
        self.assertEqual(cdp.calls[0][1]["url"], "about:blank")
        self.assertEqual(cdp.calls[2][2], "session-1")
        self.assertEqual(cdp.calls[2][1]["name"], "sid")
        self.assertEqual(cdp.calls[2][1]["value"], "abc==")
        self.assertEqual(cdp.calls[4][2], "session-1")
        self.assertEqual(cdp.calls[4][1]["url"], "https://one.example/")
        self.assertEqual(len(FakeTimer.instances), 1)

    def test_cookie_injection_failure_logs_and_notifies_without_exposing_value(self):
        sites = [
            types.SimpleNamespace(
                id=1,
                name="One",
                url="https://one.example/",
                is_active=True,
                cookie="sid=abc==;",
            )
        ]
        cdp = FakeCdp(cookie_failure=True)
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True, "notify_enabled": True})
        plugin._connect_cdp = lambda: cdp

        result = plugin.run_once()

        self.assertEqual(result, ["https://one.example/"])
        warning_texts = [
            message for level, message in self.logger.messages if level == "warning"
        ]
        self.assertTrue(any("Cookie 注入失败" in message for message in warning_texts))
        self.assertTrue(all("abc==" not in message for message in warning_texts))
        failure_messages = [
            message["text"]
            for message in plugin.messages
            if "Cookie 注入失败" in message["text"]
        ]
        self.assertEqual(len(failure_messages), 1)
        self.assertIn("https://one.example/", failure_messages[0])
        self.assertIn("cookie rejected", failure_messages[0])
        self.assertNotIn("abc==", failure_messages[0])

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

    def test_manual_run_api_opens_sites_and_returns_result(self):
        sites = [types.SimpleNamespace(id=1, url="https://one.example/", is_active=True)]
        cdp = FakeCdp()
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": True, "notify_enabled": True})
        plugin._connect_cdp = lambda: cdp

        response = plugin.get_api()[0]["endpoint"]()

        self.assertEqual(response["success"], True)
        self.assertEqual(response["opened"], ["https://one.example/"])
        self.assertIn("已打开 1 个站点", response["message"])
        self.assertEqual(len(plugin.messages), 1)
        self.assertEqual(plugin.messages[0]["title"], plugin.plugin_name)
        self.assertIn("https://one.example/", plugin.messages[0]["text"])

    def test_manual_run_api_works_when_schedule_is_disabled_and_logs_entry(self):
        sites = [types.SimpleNamespace(id=1, url="https://one.example/", is_active=True)]
        cdp = FakeCdp()
        self.module.SiteOper = lambda: types.SimpleNamespace(list_active=lambda: sites)
        self.module.threading.Timer = FakeTimer
        FakeTimer.instances.clear()

        plugin = self.module.PTSiteOpener()
        plugin.init_plugin({"enabled": False})
        plugin._connect_cdp = lambda: cdp

        response = plugin.get_api()[0]["endpoint"]()

        self.assertEqual(response["success"], True)
        self.assertEqual(response["opened"], ["https://one.example/"])
        self.assertTrue(any("收到立即执行请求" in message for _, message in self.logger.messages))


class FakeCdp:
    def __init__(self, cookie_failure=False):
        self.calls = []
        self.closed = []
        self.connected = True
        self.next_target = 0
        self.cookie_failure = cookie_failure

    def send(self, method, params=None, session_id=None):
        params = params or {}
        self.calls.append((method, params, session_id))
        if method == "Target.createTarget":
            if params["url"] == "https://failed.example/":
                raise RuntimeError("target rejected")
            self.next_target += 1
            return {"targetId": f"opened-{self.next_target}"}
        if method == "Target.attachToTarget":
            return {"sessionId": "session-1"}
        if method == "Network.setCookie":
            if self.cookie_failure:
                raise RuntimeError("cookie rejected")
            return {"success": True}
        if method == "Page.navigate":
            return {"frameId": "frame-1"}
        if method == "Target.activateTarget":
            return {}
        if method == "Target.closeTarget":
            self.closed.append(params["targetId"])
            return {"success": True}
        raise AssertionError(f"unexpected CDP method: {method}")

    def close(self):
        self.connected = False


class FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def recv(self):
        return self.responses.pop(0)

    def close(self):
        pass


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
