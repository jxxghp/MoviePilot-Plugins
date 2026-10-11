from pathlib import Path

PLUGIN_ROOT = Path(__file__).parents[3] / "plugins.v3" / "musiclibrarymanager"


def test_vue_federation_contract_files_exist():
    assert (PLUGIN_ROOT / "__init__.py").exists()
    assert (PLUGIN_ROOT / "vite.config.js").exists()
    assert (PLUGIN_ROOT / "src/components/AppPage.vue").exists()
    assert (PLUGIN_ROOT / "src/components/Config.vue").exists()


def test_frontend_uses_host_api_and_no_global_credentials():
    source = (PLUGIN_ROOT / "src/components/AppPage.vue").read_text(encoding="utf-8")
    assert "props.api" in source
    assert "window.MoviePilotAPI" not in source
    assert "site_cookie" not in source


def test_plugin_declares_v3_sidebar_and_bearer_apis():
    from app.plugins.musiclibrarymanager import MusicLibraryManager

    # 插件基类构造需要完整宿主运行时；合同测试只验证本插件声明。
    plugin = MusicLibraryManager.__new__(MusicLibraryManager)
    plugin.init_plugin({"enabled": True, "show_sidebar_nav": True})
    assert plugin.get_render_mode() == ("vue", "dist/assets")
    assert plugin.get_sidebar_nav()[0]["section"] == "organize"
    assert all(route["auth"] == "bear" for route in plugin.get_api())
    assert all(route["response_model"] for route in plugin.get_api())
    assert all(route["dependencies"] for route in plugin.get_api())


def test_fastapi_routes_load_models_and_reject_disabled_requests():
    from app.plugins.musiclibrarymanager import MusicLibraryManager, require_manage_user
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    plugin = MusicLibraryManager.__new__(MusicLibraryManager)
    plugin.init_plugin({"enabled": False})
    app = FastAPI()
    for declaration in plugin.get_api():
        route = dict(declaration)
        route.pop("auth")
        app.add_api_route(**route)
    app.dependency_overrides[require_manage_user] = lambda: object()
    # 真实 FastAPI 解析绑定端点与 response_model，而非只检查文本。
    with TestClient(app) as client:
        assert client.get("/artists/search?query=Taylor").status_code == 409
        assert client.get("/openapi.json").status_code == 200
    assert len(app.openapi()["paths"]) == 10
