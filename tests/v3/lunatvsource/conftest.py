import pytest

@pytest.fixture(autouse=True)
def disable_live_stream_probe(monkeypatch):
    """单元测试不访问公网 CMS 视频端点。"""

    import app.plugins.lunatvsource as plugin_module

    monkeypatch.setattr(plugin_module, "probe_stream_height", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(plugin_module, "_HostMediaSource", None)
