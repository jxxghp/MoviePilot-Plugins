"""每项集成测试使用独立插件实例和隔离宿主数据库。"""

from importlib import import_module
from uuid import uuid4

import pytest


@pytest.fixture
def plugin():
    module = import_module("app.plugins.torrentblacklist")
    plugin_type = type(f"TorrentBlacklistTest{uuid4().hex}", (module.TorrentBlacklist,), {})
    instance = plugin_type()
    instance.init_plugin({})
    try:
        yield instance
    finally:
        instance.del_data("rules")


@pytest.fixture
def api_client(plugin, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.adapters.web.plugin.routes import FastAPIDynamicRouteRegistry
    from app.adapters.web.security import access
    from app.application import configuration
    from app.db.oper.user import UserOper
    from app.log import logger
    from app.runtime.config import settings
    from app.sdk.security import create_access_token, decode_access_token, verify_token
    from app.startup.composition.configuration import build_token_runtime_config

    monkeypatch.setattr(configuration, "_token_runtime_config_provider",
                        lambda: build_token_runtime_config(settings))
    monkeypatch.setattr(access, "_token_encoder", create_access_token)
    monkeypatch.setattr(access, "_token_decoder", decode_access_token)
    # 令牌仍经过真实 JWT 解码；不借宿主身份预检掩盖插件自己的管理员查询。
    monkeypatch.setattr(access, "_token_identity_validator", lambda _payload: None)
    users = {}
    for label, active, superuser in (
        ("admin", True, True), ("normal", True, False), ("inactive", False, True),
    ):
        name = f"blacklist-{label}-{uuid4().hex}"
        UserOper().add(name=name, is_active=active, is_superuser=superuser, hashed_password="unused")
        user = UserOper().get_by_name(name)
        # 普通用户 token 故意带有 super_user=True，仍必须被服务器真实身份拒绝。
        users[label] = {"Authorization": f"Bearer {create_access_token(user.id, name, True)}"}
    users["missing"] = {"Authorization": f"Bearer {create_access_token(2147483647, 'missing', True)}"}
    app = FastAPI()
    plugin_id = type(plugin).__name__
    registry = FastAPIDynamicRouteRegistry(
        app=app, plugin_ids=lambda: [plugin_id],
        plugin_apis=lambda identity: [
            {**route, "path": f"/{identity}{route['path']}"} for route in plugin.get_api()
        ],
        verify_token=verify_token, verify_apikey=lambda: pytest.fail("API key route selected"),
        prefix="/api/v1/plugin", log=logger,
    )
    registry.update(plugin_id, "add")
    with TestClient(app) as client:
        yield client, f"/api/v1/plugin/{plugin_id}", users, app
