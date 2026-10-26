"""siteuserdetail 插件单测公共夹具。

解析层（adapters）直接实例化适配器测纯函数，不发真实请求；
主类测试按 autosignin 模式用 object.__new__ 绕过插件构造，monkeypatch 存储与外部依赖。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def site_info():
    """标准 NexusPHP 站点条目。"""
    return {
        "id": 14,
        "name": "示例站",
        "domain": "example.org",
        "url": "https://example.org/",
        "cookie": "c_secure_uid=MTIzNDU%3D; c_secure_pass=abc",
        "ua": "Mozilla/5.0 (test)",
        "proxy": False,
        "render": False,
        "public": False,
    }


@pytest.fixture
def plugin(monkeypatch):
    """隔离存储与站点访问的主类实例。"""
    from app.plugins.siteuserdetail import SiteUserDetail

    instance = object.__new__(SiteUserDetail)
    for name in ("update_config", "save_data", "post_message"):
        monkeypatch.setattr(instance, name, Mock())
    monkeypatch.setattr(instance, "get_data", Mock(return_value=None))
    monkeypatch.setattr(instance, "get_config", Mock(return_value=None))
    instance._enabled = False
    instance._onlyonce = False
    instance._notify = False
    instance._cron = ""
    instance._sites = []
    instance._use_downloader_hash = True
    instance._hash_from_detail = True
    instance._detail_limit = 20
    instance._request_interval = 0
    instance._concurrency = 2
    return instance


@pytest.fixture
def fake_site_oper(monkeypatch):
    """SiteOper 返回一个已配置站点。"""
    from app.plugins import siteuserdetail as plugin_module

    monkeypatch.setattr(plugin_module, "SiteOper", lambda: SimpleNamespace(
        list_order_by_pri=lambda: [SimpleNamespace(id=14, name="示例站")]))
