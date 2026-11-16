# -*- coding: utf-8 -*-
"""episodetag v3 插件单测公共夹具。

插件类 import 必须放在 fixture 体内延迟执行：conftest 顶层 import 早于
pytest_configure 的 plugins.v3 目录注入（app.plugins.__path__），会 ModuleNotFoundError。
"""

from unittest.mock import Mock

import pytest


@pytest.fixture
def plugin(monkeypatch):
    """隔离存储的插件实例（默认标签格式 E/2/-）。"""
    from app.plugins.episodetag import EpisodeTag

    instance = object.__new__(EpisodeTag)
    for name in ("update_config", "save_data"):
        monkeypatch.setattr(instance, name, Mock())
    monkeypatch.setattr(instance, "get_data", Mock(return_value=None))
    instance._enabled = False
    instance._onlyonce = False
    instance._cron = ""
    instance._only_tv = True
    instance._tag_prefix = "E"
    instance._merge_threshold = 2
    instance._tag_separator = "-"
    instance._known_prefixes = ["E"]
    instance._include_tags = set()
    instance._exclude_tags = set()
    instance._downloaders = None
    return instance
