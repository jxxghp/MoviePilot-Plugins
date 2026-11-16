# -*- coding: utf-8 -*-
"""traktcleaner v3 插件单测公共夹具。

插件类 import 必须放在 fixture 体内延迟执行：conftest 顶层 import 早于
pytest_configure 的 plugins.v3 目录注入（app.plugins.__path__），会 ModuleNotFoundError。
"""

from unittest.mock import Mock

import pytest


@pytest.fixture
def plugin(monkeypatch):
    """隔离存储与外部依赖的插件实例。"""
    from app.plugins.traktcleaner import TraktCleaner

    instance = object.__new__(TraktCleaner)
    for name in ("update_config", "save_data", "post_message"):
        monkeypatch.setattr(instance, name, Mock())
    monkeypatch.setattr(instance, "get_data", Mock(return_value=None))
    instance._enabled = False
    instance._onlyonce = False
    instance._cron = None
    instance._notify = True
    instance._delete_file = True
    instance._dry_run = False
    instance._client_id = None
    instance._client_secret = None
    instance._access_token = "tk"
    instance._refresh_token = None
    instance._clean_movie = True
    instance._clean_episode = True
    instance._exclude_tags = ""
    instance._delay_days = 0
    instance._token_error = False
    return instance
