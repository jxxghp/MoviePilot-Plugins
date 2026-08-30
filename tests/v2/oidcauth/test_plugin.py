"""OidcAuth 插件与 MoviePilot 认证模块的兼容性回归测试。"""

from app.core.auth import create_plugin_auth_ticket
from app.plugins import oidcauth


def test_imports_auth_ticket_factory_from_current_moviepilot_module() -> None:
    """新版 MoviePilot 中应从 app.core.auth 导入认证票据工厂。"""
    assert oidcauth.create_plugin_auth_ticket is create_plugin_auth_ticket
    assert oidcauth.OidcAuth.plugin_version == "0.3.3"


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
