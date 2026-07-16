import sys
import types
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins.v2"
sys.path.insert(0, str(PLUGIN_ROOT))


class FakeLogger:
    def __init__(self):
        self.messages = []

    def _record(self, level, message):
        self.messages.append((level, str(message)))

    def debug(self, message):
        self._record("debug", message)

    def info(self, message):
        self._record("info", message)

    def warning(self, message):
        self._record("warning", message)

    warn = warning

    def error(self, message):
        self._record("error", message)


class FakeDownloaderHelper:
    registry = {}

    def is_downloader(self, service_type=None, service=None, name=None):
        del service
        return self.registry.get(name) == service_type


class FakePluginBase:
    pass


app_module = types.ModuleType("app")
app_module.__path__ = []
helper_module = types.ModuleType("app.helper")
helper_module.__path__ = []
downloader_module = types.ModuleType("app.helper.downloader")
downloader_module.DownloaderHelper = FakeDownloaderHelper
log_module = types.ModuleType("app.log")
log_module.logger = FakeLogger()
plugins_module = types.ModuleType("app.plugins")
plugins_module._PluginBase = FakePluginBase
app_module.helper = helper_module
app_module.log = log_module
app_module.plugins = plugins_module
helper_module.downloader = downloader_module

sys.modules.setdefault("app", app_module)
sys.modules.setdefault("app.helper", helper_module)
sys.modules.setdefault("app.helper.downloader", downloader_module)
sys.modules.setdefault("app.log", log_module)
sys.modules.setdefault("app.plugins", plugins_module)
