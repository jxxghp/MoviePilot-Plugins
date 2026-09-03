"""OidcAuth 插件与 MoviePilot 认证模块的兼容性回归测试。"""

from types import SimpleNamespace

from app.core.auth import create_plugin_auth_ticket
from app.plugins import oidcauth


def test_imports_auth_ticket_factory_from_current_moviepilot_module() -> None:
    """新版 MoviePilot 中应从 app.core.auth 导入认证票据工厂。"""
    assert oidcauth.create_plugin_auth_ticket is create_plugin_auth_ticket
    assert oidcauth.OidcAuth.plugin_version == "0.3.4"


def test_auth_ticket_factory_falls_back_to_legacy_module(monkeypatch) -> None:
    """当前认证模块不存在时应兼容旧版 app.core.auth_bridge。"""
    def legacy_factory(*_args, **_kwargs) -> str:
        """返回旧版认证模块生成的模拟票据。"""
        return "legacy-ticket"

    def fake_import_module(module_name: str):
        """模拟新版模块缺失、旧版模块可用的 MoviePilot 环境。"""
        if module_name == "app.core.auth":
            raise ModuleNotFoundError(name=module_name)
        return type("LegacyAuthModule", (), {
            "create_plugin_auth_ticket": legacy_factory
        })

    monkeypatch.setattr(oidcauth, "import_module", fake_import_module)

    assert oidcauth._load_auth_ticket_factory() is legacy_factory


def test_oidc_callbacks_query_users_through_compatible_oper(monkeypatch) -> None:
    """登录、绑定与自动绑定都应通过 V3 可用的 UserOper 查询用户。"""
    user = SimpleNamespace(id=7, name="alice", is_active=True)
    queried_ids = []
    queried_names = []

    class FakeUserOper:
        """记录 OIDC 回调发起的用户查询。"""

        def get_by_id(self, user_id: int):
            """按 ID 返回测试用户。"""
            queried_ids.append(user_id)
            return user

        def get_by_name(self, username: str):
            """按用户名返回测试用户。"""
            queried_names.append(username)
            return user

    # 回调单测只需要插件自身状态，绕开宿主启动组合根尚未装配的 Chain 依赖。
    plugin = object.__new__(oidcauth.OidcAuth)
    plugin._config = {
        "issuer": "https://issuer.example",
        "allow_auto_bind_by_username": False,
        "username_claim": "preferred_username",
    }
    monkeypatch.setattr(oidcauth, "UserOper", FakeUserOper)
    monkeypatch.setattr(
        oidcauth,
        "create_plugin_auth_ticket",
        lambda **_kwargs: "test-ticket",
    )
    monkeypatch.setattr(plugin, "get_data", lambda _key: {"user_id": user.id})
    monkeypatch.setattr(plugin, "save_data", lambda _key, _value: None)
    monkeypatch.setattr(plugin, "_get_user_binding", lambda _user_id: None)

    login_response = plugin._handle_login_callback(
        userinfo={"preferred_username": user.name},
        sub="subject-1",
    )
    bind_response = plugin._handle_bind_callback(
        state_data={"user_id": user.id},
        userinfo={"preferred_username": user.name},
        sub="subject-1",
    )
    auto_bound_user = plugin._auto_bind_by_username(
        userinfo={"preferred_username": user.name},
        sub="subject-2",
    )

    assert login_response.status_code == 200
    assert bind_response.status_code == 200
    assert auto_bound_user is user
    assert queried_ids == [user.id, user.id]
    assert queried_names == [user.name]


def test_user_lookup_falls_back_for_legacy_v2_oper(monkeypatch) -> None:
    """旧版 V2 UserOper 缺少 get_by_id 时仍应能按 ID 找到用户。"""
    expected_user = SimpleNamespace(id=7)

    class LegacyUserOper:
        """模拟仅提供 list 的旧版 V2 用户访问对象。"""

        def list(self):
            """返回少量测试用户供兼容分支筛选。"""
            return [SimpleNamespace(id=3), expected_user]

    monkeypatch.setattr(oidcauth, "UserOper", LegacyUserOper)

    assert oidcauth.OidcAuth._get_user_by_id(7) is expected_user
