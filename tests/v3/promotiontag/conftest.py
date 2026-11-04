# -*- coding: utf-8 -*-
"""promotiontag v3 插件单测公共夹具。

插件类 import 必须放在 fixture 体内延迟执行：conftest 顶层 import 早于
pytest_configure 的 plugins.v3 目录注入（app.plugins.__path__），会 ModuleNotFoundError。
"""

from unittest.mock import Mock

import pytest


@pytest.fixture
def plugin(monkeypatch):
    """隔离存储的插件实例（默认无前缀 / 时区偏移 0）。"""
    from app.plugins.promotiontag import PromotionTag

    instance = object.__new__(PromotionTag)
    for name in ("update_config", "save_data", "post_message"):
        monkeypatch.setattr(instance, name, Mock())
    monkeypatch.setattr(instance, "get_data", Mock(return_value=None))
    instance._enabled = False
    instance._onlyonce = False
    instance._notify = False
    instance._downloaders = []
    instance._dl_hours = 3
    instance._cmp_hours = 24
    instance._fallback_enabled = True
    instance._fallback_hours = 12
    instance._tz_offset = 0
    instance._tag_prefix = ""
    return instance
