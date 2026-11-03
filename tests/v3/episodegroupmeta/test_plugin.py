"""EpisodeGroupMeta V3 的 API、媒体身份和媒体服务器结果合同测试。"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Event

from app import schemas


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/episodegroupmeta/__init__.py"


def _load_plugin():
    return importlib.import_module("app.plugins.episodegroupmeta")


def test_v3_metadata_and_legacy_indexes_are_aligned() -> None:
    """V3 版本、宿主下限和旧索引禁用标记必须一致。"""
    module = _load_plugin()
    v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    legacy = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert module.EpisodeGroupMeta.plugin_version == "3.2.1"
    assert v3["EpisodeGroupMeta"]["version"] == "3.2.1"
    assert v3["EpisodeGroupMeta"]["system_version"] == ">=3.0.0"
    assert v3["EpisodeGroupMeta"]["history"]["v3.2.1"]
    assert legacy["EpisodeGroupMeta"]["v3"] is False


def test_dynamic_apis_use_bearer_and_declared_response_models() -> None:
    """插件页面 API 使用宿主登录态，且显式声明统一响应模型。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)

    apis = {api["path"]: api for api in plugin.get_api()}

    assert apis["/delete_media_database"]["auth"] == "bear"
    assert apis["/start_rt"]["auth"] == "bear"
    assert apis["/delete_media_database"]["response_model"] == schemas.Response[None]
    assert apis["/start_rt"]["response_model"] == schemas.Response[None]
    assert "apikey" not in SOURCE.read_text(encoding="utf-8")


def test_plugin_does_not_import_host_orm_models() -> None:
    """插件数据只能通过 PluginBase 合同访问，不能导入宿主 ORM 模型。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.db.models")
        for node in ast.walk(tree)
    )


def _media_server_plugin(module, set_iteminfo_result: bool):
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._ignorelock = True
    plugin._notify = False
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin.tv = SimpleNamespace(
        group_episodes=lambda _group_id: [
            {"order": 1, "episodes": [{"name": "新标题", "overview": "简介"}]}
        ]
    )
    plugin.get_iteminfo = lambda **_kwargs: {
        "Id": "item",
        "Name": "旧标题",
        "Overview": "旧简介",
        "LockedFields": [],
    }
    plugin.set_iteminfo = lambda **_kwargs: set_iteminfo_result
    plugin.set_item_image = lambda **_kwargs: True
    return plugin


def test_media_server_result_is_false_when_no_item_was_updated() -> None:
    """媒体服务器写入失败时不得向上层报告成功。"""
    module = _load_plugin()
    plugin = _media_server_plugin(module, set_iteminfo_result=False)
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="emby", server="测试"
    )
    media = SimpleNamespace(title_year="示例剧 (2026)")

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        media,
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is False


def test_media_server_result_is_true_after_item_update() -> None:
    """至少一个媒体项成功写入后才报告成功。"""
    module = _load_plugin()
    plugin = _media_server_plugin(module, set_iteminfo_result=True)
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="emby", server="测试"
    )
    media = SimpleNamespace(title_year="示例剧 (2026)")

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        media,
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True


def test_delayed_transfer_wait_can_be_cancelled() -> None:
    """卸载时设置停止事件，延迟处理应立即可观察到取消状态。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._event = Event()

    plugin.stop_service()

    assert plugin._event.is_set()
    assert plugin._event.wait(0)


def test_reload_does_not_clear_previous_stop_signal() -> None:
    """重载创建新取消令牌时，旧任务的停止信号保持有效。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    old_event = Event()
    plugin._event = old_event
    plugin.stop_service()

    plugin._event = Event()

    assert old_event.is_set()
    assert not plugin._event.is_set()


class _FakeResponse:
    """只提供详情读取所需的 json()/status_code。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload


class _FakeJellyfinAdapter:
    """模拟 V3 宿主 Jellyfin 适配器：只有实例级 get_data，没有 jellyfin 子客户端。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.requested_urls: list = []

    def get_data(self, url: str) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self._payload)


def test_jellyfin_iteminfo_uses_adapter_get_data() -> None:
    """V3 Jellyfin 详情必须走适配器自身的 get_data，不能依赖已移除的嵌套子客户端。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin.log_error = lambda *_args, **_kwargs: None
    adapter = _FakeJellyfinAdapter({"Id": "item", "Name": "旧标题", "Path": "/media/示例.S01E01.mkv"})

    iteminfo = plugin.get_iteminfo(
        server_type="jellyfin", itemid="item", mediaserver_instance=adapter
    )

    assert adapter.requested_urls == [
        "[HOST]Users/[USER]/Items/item?Fields=ChannelMappingInfo&api_key=[APIKEY]"
    ]
    assert iteminfo["Name"] == "旧标题"
    assert iteminfo["FileName"] == "示例.S01E01.mkv"


def test_out_of_range_episode_number_is_skipped_without_update() -> None:
    """媒体库第 0 集等越界集数必须跳过，不得取用剧集组最后一集的标题与简介。"""
    module = _load_plugin()
    plugin = _media_server_plugin(module, set_iteminfo_result=True)
    written: list = []
    plugin.set_iteminfo = lambda **kwargs: (written.append(kwargs["iteminfo"]), True)[1]
    exists = module.ExistMediaInfo(
        groupep={1: [0]}, groupid={1: [["item0"]]}, server_type="jellyfin", server="测试"
    )
    media = SimpleNamespace(title_year="示例剧 (2026)")

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        media,
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is False
    assert written == []


def test_iteminfo_without_locked_fields_still_updates() -> None:
    """详情缺少 LockedFields 时不得抛 KeyError，应照常写入并锁定字段。"""
    module = _load_plugin()
    plugin = _media_server_plugin(module, set_iteminfo_result=True)
    plugin.get_iteminfo = lambda **_kwargs: {
        "Id": "item",
        "Name": "旧标题",
        "Overview": "旧简介",
    }
    written: list = []
    plugin.set_iteminfo = lambda **kwargs: (written.append(kwargs["iteminfo"]), True)[1]
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="jellyfin", server="测试"
    )
    media = SimpleNamespace(title_year="示例剧 (2026)")

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        media,
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert written[0]["LockedFields"] == ["Name", "Overview"]
