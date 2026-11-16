"""为自动签到的网页回归隔离宿主站点模块分发。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def site_module_dispatch(monkeypatch):
    """默认将网页测试交还通用处理，API 用例按实例注入生产模块或指定回执。"""
    from app.application.site.protocol import SiteConnectionResult
    from app.plugins.autosignin import AutoSignIn

    chain = SimpleNamespace(run_module=Mock(return_value=SiteConnectionResult(supported=False)))
    monkeypatch.setattr(AutoSignIn, "chain", chain, raising=False)
    return chain.run_module
