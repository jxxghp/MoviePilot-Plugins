from app.plugins.lunatvsource import LunaTVSource
import app.plugins.lunatvsource as plugin_module


def test_probe_allowlist_does_not_inherit_image_proxy_settings(monkeypatch):
    monkeypatch.setattr(
        plugin_module,
        "_get_runtime_settings",
        lambda: {"IMAGE_PROXY_ALLOWED_PRIVATE_RANGES": ["10.0.0.0/8"]},
        raising=False,
    )

    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})

    assert plugin._probe_allowed_private_ranges() == ()


def test_explicit_private_ranges_are_forwarded_to_cms_requests(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin(
        {
            "enabled": True,
            "probe_allowed_private_ranges": "198.18.0.0/15, 10.0.0.0/8",
        }
    )
    expected = ("198.18.0.0/15", "10.0.0.0/8")
    assert plugin._queue._allowed_private_ranges == expected
    client_kwargs = {}

    class Client:
        def __init__(self, **kwargs):
            client_kwargs.update(kwargs)

    monkeypatch.setattr(plugin_module, "AppleCmsClient", Client)
    monkeypatch.setattr(plugin, "_cached_source_catalog", lambda: [])

    plugin._client()

    assert client_kwargs["allowed_private_ranges"] == expected

    source = plugin_module.CmsSource(
        "demo",
        "演示源",
        "https://cms.example/vod",
    )
    load_kwargs = {}

    def load_sources_from_url(*_args, **kwargs):
        load_kwargs.update(kwargs)
        return [source]

    monkeypatch.setattr(plugin_module, "load_sources_from_url", load_sources_from_url)

    assert plugin._load_sources(
        "https://config.example/sources.json",
        timeout=3,
        allowlist=(),
    ) == [source]
    assert load_kwargs["allowed_private_ranges"] == expected
