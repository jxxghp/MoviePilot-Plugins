"""OIDC 代理开关、配置保存和登录绑定链路的离线回归。"""

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request

from app.plugins import oidcauth


@pytest.fixture
def plugin():
    """提供启用且配置完整的插件，绕过宿主构造。"""
    instance = object.__new__(oidcauth.OidcAuth)
    instance.init_plugin({
        "enabled": True,
        "issuer": "https://auth.example.lan",
        "client_id": "moviepilot",
        "client_secret": "test-secret",
    })
    instance._states = {}
    instance._state_lock = threading.RLock()
    return instance


@pytest.fixture
def oidc_http(monkeypatch):
    """记录客户端选项并离线响应各 OIDC 端点，禁止真实出网。"""
    options = []
    requests = []
    original_client = httpx.AsyncClient

    def respond(request):
        """响应发现文档、Token 和用户信息请求。"""
        requests.append(request)
        if request.url.path == "/.well-known/openid-configuration":
            payload = {
                "authorization_endpoint": "https://auth.example.lan/authorize",
                "token_endpoint": "https://auth.example.lan/token",
                "userinfo_endpoint": "https://auth.example.lan/userinfo",
            }
        elif request.url.path == "/token":
            payload = {"access_token": "test-token"}
        elif request.url.path == "/userinfo":
            payload = {"sub": "test-subject"}
        else:
            raise AssertionError(f"意外的 OIDC 请求：{request.url}")
        return httpx.Response(200, json=payload)

    def create_client(**kwargs):
        """保留真实客户端的超时和环境策略，仅替换网络传输。"""
        options.append(kwargs.copy())
        kwargs.pop("proxy")
        return original_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(oidcauth.httpx, "AsyncClient", create_client)
    monkeypatch.setenv("HTTP_PROXY", "http://environment-proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://environment-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://environment-proxy.invalid:8080")
    return options, requests


@pytest.mark.parametrize("use_proxy", [None, False, True])
@pytest.mark.parametrize("global_proxy", [None, "", "http://global-proxy.invalid:8080"])
def test_oidc_requests_follow_plugin_proxy_switch(
    plugin, oidc_http, monkeypatch, use_proxy, global_proxy
):
    """三处请求默认直连，仅显式开启时使用全局代理且不继承环境代理。"""
    if use_proxy is not None:
        plugin._config["use_proxy"] = use_proxy
    else:
        plugin._config.pop("use_proxy")
    monkeypatch.setattr(oidcauth.settings, "PROXY_HOST", global_proxy)

    async def run_flow():
        """沿真实发现、授权码交换和用户信息调用完成协议链路。"""
        assert "authorize?" in await plugin._build_authorize_url("https://mp.example/callback", "state")
        token = await plugin._exchange_code("test-code", "https://mp.example/callback")
        assert await plugin._fetch_userinfo(token) == {"sub": "test-subject"}

    asyncio.run(run_flow())
    options, requests = oidc_http
    expected_proxy = (global_proxy or None) if use_proxy else None
    assert options == [{"timeout": 10.0, "proxy": expected_proxy, "trust_env": False}] * 5
    assert [request.url.path for request in requests] == [
        "/.well-known/openid-configuration",
        "/.well-known/openid-configuration", "/token",
        "/.well-known/openid-configuration", "/userinfo",
    ]
    assert requests[-1].headers["Authorization"] == "Bearer test-token"
    assert b"code=test-code" in requests[2].content


@pytest.mark.parametrize("use_proxy", [False, True])
def test_save_and_connection_test_use_submitted_proxy_setting(
    plugin, oidc_http, monkeypatch, use_proxy
):
    """未保存的连接测试使用表单开关，保存后重载保留开关，旧配置默认关闭。"""
    monkeypatch.setattr(oidcauth.settings, "PROXY_HOST", "http://global-proxy.invalid:8080")
    plugin._config["use_proxy"] = not use_proxy
    user = SimpleNamespace(is_superuser=True)
    result = asyncio.run(plugin.test_api({"use_proxy": use_proxy}, user))
    assert result.success is True
    assert plugin._config["use_proxy"] is not use_proxy
    assert oidc_http[0][0]["proxy"] == (oidcauth.settings.PROXY_HOST if use_proxy else None)

    saved = []
    monkeypatch.setattr(plugin, "update_config", saved.append)
    response = plugin.save_config_api({**plugin._config, "use_proxy": use_proxy}, user)
    assert response.success is True
    plugin.init_plugin(saved[0])
    assert plugin._config["use_proxy"] is use_proxy
    assert plugin._normalize_config({})["use_proxy"] is False


@pytest.mark.parametrize("action", ["login", "bind"])
def test_login_and_binding_authorization_default_to_direct_connection(
    plugin, oidc_http, monkeypatch, action
):
    """全局代理已配置时，登录和绑定入口仍可通过直连发现文档生成授权地址。"""
    monkeypatch.setattr(oidcauth.settings, "PROXY_HOST", "http://global-proxy.invalid:8080")
    monkeypatch.setattr(plugin, "_callback_url", lambda _request: "https://mp.example/callback")
    monkeypatch.setattr(plugin, "_get_user_binding", lambda _user_id: None)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    if action == "login":
        response = asyncio.run(plugin.authorize(request))
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://auth.example.lan/authorize?")
    else:
        response = asyncio.run(plugin.bind_start(request, SimpleNamespace(id=7)))
        assert response.success is True
        assert response.data["authorize_url"].startswith("https://auth.example.lan/authorize?")
    assert oidc_http[0] == [{"timeout": 10.0, "proxy": None, "trust_env": False}]
    assert next(iter(plugin._states.values()))["action"] == action
