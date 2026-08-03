"""OidcAuth 插件与 MoviePilot 认证模块的兼容性回归测试。"""

import oidcauth
from app.core.auth import create_plugin_auth_ticket


def test_imports_auth_ticket_factory_from_current_moviepilot_module() -> None:
    """新版 MoviePilot 中应从 app.core.auth 导入认证票据工厂。"""
    assert oidcauth.create_plugin_auth_ticket is create_plugin_auth_ticket
    assert oidcauth.OidcAuth.plugin_version == "0.3.2"
