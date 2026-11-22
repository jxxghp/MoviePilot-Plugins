"""豆瓣想看同步入口的续集回退接线用例。

用本地桩替换 RSS、媒体链与订阅链，验证：
1. 续集命中时按 TMDB 原剧 ID 识别并把季号写回元数据；
2. 未命中时保留原有的豆瓣数据识别回退（不复用旧版直接跳过的语义）；
3. 身份转换成功时不触发续集回退，避免多余的远端查询。
"""

import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest
from app.schemas.types import MediaSource

import app.plugins.doubansync as doubansync_module
from app.plugins.doubansync import DoubanSync


class _PluginChain:
    """记录识别调用的插件链桩。"""

    def __init__(self, candidates: Optional[List[Dict[str, Any]]] = None,
                 season_info: Optional[Dict[str, Any]] = None,
                 year: str = "2025") -> None:
        """初始化隔离的测试字段与预设响应。"""
        self.candidates = candidates or []
        self.season_info = season_info or {}
        self.year = year
        self.search_calls: List[Dict[str, Any]] = []
        self.season_calls: List[Dict[str, Any]] = []
        self.recognize_calls: List[Dict[str, Any]] = []

    def douban_info(self, doubanid: str) -> Dict[str, Any]:
        """返回通用豆瓣条目信息。"""
        return {"type": "tv", "year": self.year, "title": "示例剧集2"}

    def search_medias(self, meta: Any, media_source: Any = None) -> List[Any]:
        """返回预置 TMDB 候选。"""
        self.search_calls.append({"meta": meta, "media_source": media_source})
        return list(self.candidates)

    def tmdb_info(self, tmdbid: int, mtype: Any = None,
                  season: Optional[int] = None) -> Any:
        """返回预置季度详情。"""
        self.season_calls.append({"tmdbid": tmdbid, "mtype": mtype, "season": season})
        return self.season_info

    def recognize_media(self, meta: Any = None, media_source: Any = None,
                        media_id: Any = None) -> None:
        """记录识别参数并返回空，使同步在此分支结束。"""
        self.recognize_calls.append({"meta": meta, "media_source": media_source,
                                     "media_id": media_id})
        return None


class _MediaChain:
    """媒体链桩，只提供身份转换结果。"""

    def __init__(self, converted: Optional[Dict[str, Any]]) -> None:
        """初始化隔离的测试字段与预设响应。"""
        self.converted = converted
        self.convert_calls: List[Dict[str, Any]] = []

    def convert_media_identity(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """记录转换参数并返回预置结果。"""
        self.convert_calls.append(kwargs)
        return self.converted


def _candidate(**overrides: Any) -> Dict[str, Any]:
    """构造一条 TMDB 电视剧候选。"""
    item: Dict[str, Any] = {
        "type": "电视剧",
        "media_source": "themoviedb",
        "media_id": "100",
        "title": "示例剧集",
        "original_name": "示例剧集",
    }
    item.update(overrides)
    return item


def _season(**overrides: Any) -> Dict[str, Any]:
    """构造一份季度详情。"""
    item: Dict[str, Any] = {
        "season_number": 2,
        "air_date": "2025-06-07",
        "episode_count": 10,
    }
    item.update(overrides)
    return item


def _build_plugin(chain: _PluginChain) -> DoubanSync:
    """构造不触发插件初始化与真实存储的插件实例。"""
    plugin = object.__new__(DoubanSync)
    plugin.chain = chain
    plugin.systemconfig = SimpleNamespace()
    plugin._users = "generic-user"
    plugin._days = 7
    plugin._clearflag = False
    plugin._search_download = False
    plugin.get_data = Mock(return_value=[])  # type: ignore[method-assign]
    plugin.save_data = Mock()  # type: ignore[method-assign]
    return plugin


def _install_runtime(monkeypatch: pytest.MonkeyPatch, mediachain: _MediaChain) -> None:
    """替换同步流程用到的 RSS、元数据解析与各类链工厂。"""
    rss_items = [{
        "title": "想看示例剧集2",
        "link": "https://example.org/subject/1234567/",
        "pubdate": datetime.datetime.now(datetime.timezone.utc),
        "nickname": "",
    }]

    class _StubMetaInfo:
        """只保留标题与季号字段的元数据替身，隔离启动阶段的系统配置服务。"""

        def __init__(self, title: Any = None, **_: Any) -> None:
            """初始化隔离的测试字段与预设响应。"""
            self.title = str(title or "")
            self.name = self.title
            self.type = None
            self.begin_season = None

    monkeypatch.setattr(doubansync_module, "MetaInfo", _StubMetaInfo)
    monkeypatch.setattr(doubansync_module, "RssHelper",
                        lambda: SimpleNamespace(parse=lambda *args, **kwargs: rss_items))
    monkeypatch.setattr(doubansync_module, "MediaChain", lambda: mediachain)
    monkeypatch.setattr(doubansync_module, "DownloadChain", lambda: SimpleNamespace())
    monkeypatch.setattr(doubansync_module, "SubscribeChain", lambda: SimpleNamespace())
    monkeypatch.setattr(doubansync_module, "SearchChain", lambda: SimpleNamespace())
    monkeypatch.setattr(doubansync_module, "SubscribeOper", lambda: SimpleNamespace())
    monkeypatch.setattr(doubansync_module, "settings", SimpleNamespace(
        RECOGNIZE_SOURCE="themoviedb", USER_AGENT="test-agent"))


def test_sync_uses_tmdb_identity_with_season_on_sequel_hit(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """续集命中后按 TMDB 原剧 ID 识别，并把季号写回元数据。"""
    chain = _PluginChain(candidates=[_candidate()], season_info=_season())
    mediachain = _MediaChain(converted=None)
    _install_runtime(monkeypatch, mediachain)
    plugin = _build_plugin(chain)

    plugin.sync()

    assert len(mediachain.convert_calls) == 1
    assert len(chain.recognize_calls) == 1
    recognized = chain.recognize_calls[0]
    assert recognized["media_source"] == MediaSource.TMDB
    assert recognized["media_id"] == "100"
    assert recognized["meta"].begin_season == 2
    assert chain.season_calls == [
        {"tmdbid": 100, "mtype": recognized["meta"].type, "season": 2}
    ]


def test_sync_keeps_douban_fallback_when_sequel_misses(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """续集未命中时保留原有的豆瓣身份识别回退。"""
    chain = _PluginChain(candidates=[_candidate(media_id="100"),
                                     _candidate(media_id="200")],
                         season_info=_season())
    mediachain = _MediaChain(converted=None)
    _install_runtime(monkeypatch, mediachain)
    plugin = _build_plugin(chain)

    plugin.sync()

    assert len(chain.recognize_calls) == 1
    recognized = chain.recognize_calls[0]
    assert recognized["media_source"] == MediaSource.Douban
    assert recognized["media_id"] == "1234567"


def test_sync_skips_sequel_lookup_when_identity_converts(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """身份转换成功时不再触发续集回退查询。"""
    chain = _PluginChain(candidates=[_candidate()], season_info=_season())
    mediachain = _MediaChain(converted={"id": 999})
    _install_runtime(monkeypatch, mediachain)
    plugin = _build_plugin(chain)

    plugin.sync()

    assert chain.search_calls == []
    assert chain.season_calls == []
    assert len(chain.recognize_calls) == 1
    assert chain.recognize_calls[0]["media_source"] == MediaSource.TMDB
    assert chain.recognize_calls[0]["media_id"] == "999"
