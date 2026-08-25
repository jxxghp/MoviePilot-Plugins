import threading
from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module


class _PluginData:
    def __init__(self):
        self.values = {}

    def get_data(self, _plugin_id, key):
        return self.values.get(key)

    def save(self, _plugin_id, key, value):
        self.values[key] = value


def _plugin(config=None):
    plugin = object.__new__(LunaTVSource)
    plugin.plugindata = _PluginData()
    plugin._logger = plugin_module.LOGGER
    plugin._download_metrics_lock = threading.Lock()
    plugin._download_metrics = {}
    plugin._quality_cache_lock = threading.Lock()
    plugin._quality_cache = {}
    plugin.init_plugin(config)
    return plugin

def test_probe_allowlist_does_not_inherit_image_proxy_settings(monkeypatch):
    monkeypatch.setattr(
        plugin_module,
        "_get_runtime_settings",
        lambda: {"IMAGE_PROXY_ALLOWED_PRIVATE_RANGES": ["10.0.0.0/8"]},
        raising=False,
    )

    plugin = _plugin({"enabled": True})

    assert plugin._probe_allowed_private_ranges() == ()
