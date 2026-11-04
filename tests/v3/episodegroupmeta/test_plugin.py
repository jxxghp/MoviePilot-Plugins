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

    assert module.EpisodeGroupMeta.plugin_version == "3.2.4"
    assert v3["EpisodeGroupMeta"]["version"] == "3.2.4"
    assert v3["EpisodeGroupMeta"]["system_version"] == ">=3.0.0"
    assert v3["EpisodeGroupMeta"]["history"]["v3.2.4"]
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


def _position_plugin(module, group_episodes: list):
    """装配按剧集组分集列表定位所需的插件替身，并收集写入媒体服务器的字段。"""
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._ignorelock = True
    plugin._notify = False
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin.tv = SimpleNamespace(
        group_episodes=lambda _group_id: [{"order": 1, "episodes": group_episodes}]
    )
    plugin.get_iteminfo = lambda **_kwargs: {"Id": "item", "Name": "旧标题", "Overview": "旧简介"}
    plugin.set_item_image = lambda **_kwargs: True
    written: list = []
    plugin.set_iteminfo = lambda **kwargs: (written.append(kwargs["iteminfo"]), True)[1]
    return plugin, written


def test_zero_numbered_season_is_mapped_by_position() -> None:
    """媒体库集号从 0 开始（含特别篇）时按序号配对，第 0 集也要正常刮削。"""
    module = _load_plugin()
    plugin, written = _position_plugin(module, [
        {"name": "特别篇", "overview": "组内第 1 位"},
        {"name": "第一集", "overview": "组内第 2 位"},
        {"name": "第二集", "overview": "组内第 3 位"},
    ])
    exists = module.ExistMediaInfo(
        groupep={1: [0, 1, 2]},
        groupid={1: [["id0"], ["id1"], ["id2"]]},
        server_type="jellyfin",
        server="测试",
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert [(w["IndexNumber"], w["Name"]) for w in written] == [
        ("0", "特别篇"),
        ("1", "第一集"),
        ("2", "第二集"),
    ]


def test_one_numbered_season_keeps_legacy_position_mapping() -> None:
    """集号从 1 开始且连续时，序号配对与原先的 ep_num-1 定位结果完全一致。"""
    module = _load_plugin()
    plugin, written = _position_plugin(module, [
        {"name": "第一集", "overview": "o1"},
        {"name": "第二集", "overview": "o2"},
    ])
    exists = module.ExistMediaInfo(
        groupep={1: [1, 2]},
        groupid={1: [["id1"], ["id2"]]},
        server_type="jellyfin",
        server="测试",
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert [(w["IndexNumber"], w["Name"]) for w in written] == [("1", "第一集"), ("2", "第二集")]


def test_items_beyond_group_length_are_skipped_without_wraparound() -> None:
    """指定剧集组且媒体库条目多于剧集组时，多出的项跳过，不得回绕取用最后一集。"""
    module = _load_plugin()
    plugin, written = _position_plugin(module, [
        {"name": "特别篇", "overview": "o0"},
        {"name": "第一集", "overview": "o1"},
    ])
    exists = module.ExistMediaInfo(
        groupep={1: [0, 1, 2]},
        groupid={1: [["id0"], ["id1"], ["id2"]]},
        server_type="jellyfin",
        server="测试",
    )

    plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
        "group",
    )
    assert [w["IndexNumber"] for w in written] == ["0", "1"]


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


def _lock_plugin(module, group_episodes: list, iteminfo: dict, ignorelock: bool = False):
    """装配锁定分支替身，分别收集元数据写入与分集图推送。"""
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._ignorelock = ignorelock
    plugin._notify = False
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin.tv = SimpleNamespace(
        group_episodes=lambda _group_id: [{"order": 1, "episodes": group_episodes}]
    )
    plugin.get_iteminfo = lambda **_kwargs: dict(iteminfo)
    written: list = []
    images: list = []
    plugin.set_iteminfo = lambda **kwargs: (written.append(kwargs["iteminfo"]), True)[1]
    plugin.set_item_image = lambda **kwargs: (images.append(kwargs["imageurl"]), True)[1]
    return plugin, written, images


def _still_url(module, still_path: str) -> str:
    return f"https://{module.settings.TMDB_IMAGE_DOMAIN}/t/p/original{still_path}"


def test_is_locked_item_detects_lock_states() -> None:
    """锁定判定：整项锁定或标题+简介同时锁定，缺少 LockedFields 视为未锁定。"""
    module = _load_plugin()
    is_locked = module.EpisodeGroupMeta._EpisodeGroupMeta__is_locked_item

    assert is_locked({"LockData": True}) is True
    assert is_locked({"LockedFields": ["Name", "Overview"]}) is True
    assert is_locked({"LockedFields": ["Name"]}) is False
    assert is_locked({"LockedFields": []}) is False
    assert is_locked({"Name": "标题"}) is False
    assert is_locked({}) is False


def test_locked_item_only_backfills_still_image() -> None:
    """已锁定条目：不写元数据、不改锁定状态，但补剧集组已有的分集图，补图成功即算执行成功。"""
    module = _load_plugin()
    plugin, written, images = _lock_plugin(
        module,
        [{"name": "第一集", "overview": "o1", "still_path": "/still1.jpg"}],
        {"Id": "item", "Name": "旧标题", "LockData": True},
    )
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="jellyfin", server="测试"
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert written == []
    assert images == [_still_url(module, "/still1.jpg")]


def test_locked_item_without_new_still_does_nothing() -> None:
    """已锁定且剧集组该位置没有分集图时，既不写元数据也不推图。"""
    module = _load_plugin()
    plugin, written, images = _lock_plugin(
        module,
        [{"name": "第一集", "overview": "o1"}],
        {"Id": "item", "LockedFields": ["Name", "Overview"]},
    )
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="jellyfin", server="测试"
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is False
    assert written == []
    assert images == []


def test_locked_item_beyond_group_length_is_not_backfilled() -> None:
    """锁定条目多于剧集组时只补范围内的图，越界条目不得回绕取用最后一集。"""
    module = _load_plugin()
    plugin, written, images = _lock_plugin(
        module,
        [{"name": "特别篇", "overview": "o0", "still_path": "/still0.jpg"}],
        {"Id": "item", "LockData": True},
    )
    exists = module.ExistMediaInfo(
        groupep={1: [0, 1]},
        groupid={1: [["id0"], ["id1"]]},
        server_type="jellyfin",
        server="测试",
    )

    plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
        "group",
    )
    assert written == []
    assert images == [_still_url(module, "/still0.jpg")]


def test_ignorelock_overrides_lock_and_writes_metadata() -> None:
    """开启“锁定的剧集也刮削”后仍走全量写入，并照常重新锁定标题与简介。"""
    module = _load_plugin()
    plugin, written, images = _lock_plugin(
        module,
        [{"name": "新标题", "overview": "o1", "still_path": "/still1.jpg"}],
        {"Id": "item", "Name": "旧标题", "LockData": True},
        ignorelock=True,
    )
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="jellyfin", server="测试"
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert written[0]["Name"] == "新标题"
    assert written[0]["LockData"] is True
    assert written[0]["LockedFields"] == ["Name", "Overview"]
    assert images == [_still_url(module, "/still1.jpg")]


VIDEO = "/media/动漫/示例/Season 01/示例.S01E01.mkv"
FOLDER = "/media/动漫/示例/Season 01"


class _FakeStorageChain:
    """假存储链：只登记已知路径并记录上传参数，不触碰真实文件系统也不创建目录。"""

    def __init__(self, existing: list, upload_ok: bool = True) -> None:
        self.existing = [str(item) for item in existing]
        self.upload_ok = upload_ok
        self.parent_calls: list = []
        self.upload_calls: list = []

    def get_file_item(self, storage: str, path):
        """只有已登记的路径才返回条目，其余一律视为不可见。"""
        if str(path) in self.existing:
            return SimpleNamespace(path=str(path), storage=storage)
        return None

    def get_parent_item(self, fileitem):
        """由已验证的文件项反推上级目录，并记录被反推过的文件路径。"""
        self.parent_calls.append(str(fileitem.path))
        return SimpleNamespace(path=str(Path(str(fileitem.path)).parent), storage="local")

    def upload_file(self, fileitem, path, new_name=None):
        """模拟上传：记录目标目录与文件名，成功时让目标路径变为可见。"""
        self.upload_calls.append({
            "folder": str(fileitem.path),
            "source": str(path),
            "name": new_name,
        })
        if not self.upload_ok:
            return None
        target = str(Path(str(fileitem.path)) / str(new_name))
        self.existing.append(target)
        return SimpleNamespace(path=target, storage="local")


def _local_plugin(module, existing: list, mode: str = "auto",
                  overwrite: bool = False, upload_ok: bool = True):
    """装配本地落盘替身：替换存储链与图片下载，返回插件、假存储链和告警文本。"""
    warnings: list = []
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._local_image_mode = mode
    plugin._local_image_storage = "local"
    plugin._local_image_overwrite = overwrite
    plugin._local_image_mappings = []
    plugin._storage_chain = _FakeStorageChain(existing, upload_ok=upload_ok)
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda msg, *_args, **_kwargs: warnings.append(str(msg))
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin._download_image_bytes = lambda _url: b"IMAGE"
    return plugin, plugin._storage_chain, warnings


def test_local_image_maps_longest_prefix_first() -> None:
    """路径映射按最长前缀优先命中，未命中的路径原样返回，坏行与空行忽略。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin._local_image_mappings = plugin._parse_local_image_mappings(
        "/media=/base\n/media/links=/media/视频媒体库/links\n/data/media=/media\n\n缺少等号"
    )

    assert plugin._local_image_mappings == [
        ("/media/links", "/media/视频媒体库/links"),
        ("/data/media", "/media"),
        ("/media", "/base"),
    ]
    assert plugin._map_media_server_path("/media/links/剧/S01/E01.mkv") == \
        "/media/视频媒体库/links/剧/S01/E01.mkv"
    assert plugin._map_media_server_path("/data/media/剧/E01.mkv") == "/media/剧/E01.mkv"
    assert plugin._map_media_server_path("/media/剧/E01.mkv") == "/base/剧/E01.mkv"
    # 前缀必须是完整路径段，/mediaother 不能被子串命中
    assert plugin._map_media_server_path("/mediaother/剧/E01.mkv") == "/mediaother/剧/E01.mkv"


def test_local_image_skips_unverified_path_without_creating_directories() -> None:
    """MoviePilot 看不见该路径时不写本地、不反推目录，只提示配置路径映射。"""
    module = _load_plugin()
    plugin, chain, warnings = _local_plugin(module, existing=[])

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.jpg") is False
    assert chain.parent_calls == []
    assert chain.upload_calls == []
    assert any("路径映射" in w for w in warnings)


def test_local_image_writes_mp_named_file_into_video_folder() -> None:
    """本地落盘按 <视频文件名>.jpg 写入视频所在目录，成功后不再调用媒体服务器接口。"""
    module = _load_plugin()
    plugin, chain, _ = _local_plugin(module, existing=[VIDEO])
    server_calls: list = []
    plugin.set_item_image = lambda **kwargs: (server_calls.append(kwargs), True)[1]

    assert plugin.apply_episode_image(
        server_type="jellyfin",
        itemid="item",
        imageurl="https://image/still1.jpg",
        iteminfo={"Path": VIDEO},
    ) is True
    assert chain.parent_calls == [VIDEO]
    assert [call["name"] for call in chain.upload_calls] == ["示例.S01E01.jpg"]
    assert chain.upload_calls[0]["folder"] == FOLDER
    assert server_calls == []
    # 临时文件在上传后必须被清理，不能在容器里留下垃圾
    assert not Path(chain.upload_calls[0]["source"]).exists()


def test_local_image_uploads_to_mapped_storage_path() -> None:
    """配置映射后按 MoviePilot 视角校验路径，写入目标是映射后的目录。"""
    module = _load_plugin()
    mapped_video = "/media-mp/动漫/示例/Season 01/示例.S01E01.mkv"
    plugin, chain, _ = _local_plugin(module, existing=[mapped_video])
    plugin._local_image_mappings = [("/media/动漫", "/media-mp/动漫")]

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.jpg") is True
    assert chain.parent_calls == [mapped_video]
    assert chain.upload_calls[0]["folder"] == "/media-mp/动漫/示例/Season 01"


def test_auto_mode_falls_back_to_media_server_when_local_fails() -> None:
    """auto 模式本地写入失败后回退媒体服务器，保证分集图仍有去处。"""
    module = _load_plugin()
    plugin, chain, _ = _local_plugin(module, existing=[VIDEO], upload_ok=False)
    server_calls: list = []
    plugin.set_item_image = lambda **kwargs: (server_calls.append(kwargs), True)[1]

    assert plugin.apply_episode_image(
        server_type="emby",
        itemid="item",
        imageurl="https://image/still1.jpg",
        iteminfo={"Path": VIDEO},
    ) is True
    assert len(chain.upload_calls) == 1
    assert len(server_calls) == 1


def test_local_only_mode_never_touches_media_server_api() -> None:
    """local_only 模式落盘失败也不得调用媒体服务器图片接口。"""
    module = _load_plugin()
    plugin, _chain, warnings = _local_plugin(module, existing=[], mode="local_only")
    server_calls: list = []
    plugin.set_item_image = lambda **kwargs: (server_calls.append(kwargs), True)[1]

    assert plugin.apply_episode_image(
        server_type="emby",
        itemid="item",
        imageurl="https://image/still1.jpg",
        iteminfo={"Path": VIDEO},
    ) is False
    assert server_calls == []
    assert any("跳过媒体服务器" in w for w in warnings)


def test_off_mode_keeps_media_server_write_without_storage_access() -> None:
    """默认 off 模式完全不接触存储链，与历史版本行为一致。"""
    module = _load_plugin()
    plugin, chain, _ = _local_plugin(module, existing=[VIDEO], mode="off")
    server_calls: list = []
    plugin.set_item_image = lambda **kwargs: (server_calls.append(kwargs), True)[1]

    assert plugin.apply_episode_image(
        server_type="jellyfin",
        itemid="item",
        imageurl="https://image/still1.jpg",
        iteminfo={"Path": VIDEO},
    ) is True
    assert chain.parent_calls == []
    assert chain.upload_calls == []
    assert len(server_calls) == 1


def test_existing_image_is_kept_and_duplicate_thumb_is_warned() -> None:
    """同名 Primary 图已存在时跳过写入仍算成功，Thumb 图位的重复副本给出清理提示。"""
    module = _load_plugin()
    plugin, chain, warnings = _local_plugin(
        module,
        existing=[VIDEO, f"{FOLDER}/示例.S01E01.jpg", f"{FOLDER}/示例.S01E01-thumb.jpg"],
    )

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.jpg") is True
    assert chain.upload_calls == []
    assert any("Thumb 图位" in w for w in warnings)


def test_overwrite_mode_replaces_existing_image() -> None:
    """开启覆盖后同名分集图也会被重新写入，并沿用图片自身的后缀。"""
    module = _load_plugin()
    plugin, chain, _ = _local_plugin(
        module, existing=[VIDEO, f"{FOLDER}/示例.S01E01.jpg"], overwrite=True
    )

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.png") is True
    assert [call["name"] for call in chain.upload_calls] == ["示例.S01E01.png"]


def test_locked_backfill_prefers_local_image_when_enabled() -> None:
    """已锁定条目补图同样走本地落盘，成功后不再推送媒体服务器图片接口，并算作执行成功。"""
    module = _load_plugin()
    plugin, written, images = _lock_plugin(
        module,
        [{"name": "第一集", "overview": "o1", "still_path": "/still1.jpg"}],
        {"Id": "item", "Name": "旧标题", "LockData": True, "Path": VIDEO},
    )
    plugin._local_image_mode = "auto"
    plugin._local_image_storage = "local"
    plugin._local_image_overwrite = False
    plugin._local_image_mappings = []
    plugin._storage_chain = _FakeStorageChain([VIDEO])
    plugin._download_image_bytes = lambda _url: b"IMAGE"
    exists = module.ExistMediaInfo(
        groupep={1: [1]}, groupid={1: [["item"]]}, server_type="jellyfin", server="测试"
    )

    assert plugin._EpisodeGroupMeta__start_rt_mediaserver(
        SimpleNamespace(title_year="示例剧 (2026)"),
        exists,
        [{"id": "group", "name": "剧集组"}],
    ) is True
    assert written == []
    assert images == []
    assert [call["name"] for call in plugin._storage_chain.upload_calls] == ["示例.S01E01.jpg"]


def _bucket_plugin(module):
    """装配只用于分组构造的替身，收集 info/warn 日志。"""
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin.logs = []
    plugin.log_info = lambda msg, *_args, **_kwargs: plugin.logs.append(("info", msg))
    plugin.log_warn = lambda msg, *_args, **_kwargs: plugin.logs.append(("warn", msg))
    return plugin


def test_season_episode_is_parsed_from_file_path() -> None:
    """文件名中的 SxxExx 直接决定季集号，包含第 0 集。"""
    module = _load_plugin()
    plugin = _bucket_plugin(module)

    assert plugin._parse_season_episode("/media/x/Season 02/示例 S02E12 1080p.mkv") == (2, 12)
    assert plugin._parse_season_episode("/media/x/Season 01/示例 S01E00 1080p.mkv") == (1, 0)


def test_season_folder_is_used_when_filename_lacks_season() -> None:
    """文件名没有季集号时退回季目录，集号仍由条目记录决定。"""
    module = _load_plugin()
    plugin = _bucket_plugin(module)

    assert plugin._parse_season_episode("/media/x/Season 03/示例 - 05.mkv") == (3, None)
    assert plugin._parse_season_episode("/media/x/不规范的标题.mkv") == (None, None)


def test_buckets_follow_file_path_over_recorded_numbers() -> None:
    """条目记录成第 1 季第 12 集、文件却是 Season 02 的 S02E12 时，按文件归入第 2 季。"""
    module = _load_plugin()
    plugin = _bucket_plugin(module)
    items = [
        {"Id": "a", "ParentIndexNumber": 1, "IndexNumber": 12,
         "Path": "/media/x/Season 01/示例 S01E12.mkv"},
        {"Id": "b", "ParentIndexNumber": 1, "IndexNumber": 12,
         "Path": "/media/x/Season 02/示例 S02E12.mkv"},
    ]

    group_ep, group_id = plugin._build_group_buckets(items)

    assert group_ep == {1: [12], 2: [12]}
    assert group_id == {1: [["a"]], 2: [["b"]]}
    assert any(kind == "info" and "按文件名纠正季集" in msg for kind, msg in plugin.logs)


def test_duplicate_episode_number_keeps_first_and_warns() -> None:
    """同季同集号只保留第一个条目，其余跳过并告警，避免同一份数据写进多个 NFO。"""
    module = _load_plugin()
    plugin = _bucket_plugin(module)
    items = [
        {"Id": "first", "ParentIndexNumber": 1, "IndexNumber": 12,
         "Path": "/media/x/Season 01/示例 S01E12.mkv"},
        {"Id": "dup", "ParentIndexNumber": 1, "IndexNumber": 12,
         "Path": "/media/x/Season 01/示例 S01E12 副本.mkv"},
    ]

    group_ep, group_id = plugin._build_group_buckets(items)

    assert group_ep == {1: [12]}
    assert group_id == {1: [["first"]]}
    assert any(kind == "warn" and "存在多个条目" in msg for kind, msg in plugin.logs)


def test_buckets_fall_back_to_recorded_numbers_without_path() -> None:
    """缺少路径时沿用条目自带的季集号，行为与历史一致。"""
    module = _load_plugin()
    plugin = _bucket_plugin(module)

    group_ep, group_id = plugin._build_group_buckets(
        [{"Id": "a", "ParentIndexNumber": 2, "IndexNumber": 3}]
    )

    assert group_ep == {2: [3]}
    assert group_id == {2: [["a"]]}


def test_legacy_config_keys_are_not_rewritten() -> None:
    """旧配置缺少 notify/autorun 时按当前默认值生效，不再为补默认值回写用户配置。"""
    source = SOURCE.read_text(encoding="utf-8")
    assert "更新插件配置默认配置" not in source

    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    # 隔离数据层：本用例只关注配置读取，不触发身份迁移
    plugin.get_data = lambda *_args, **_kwargs: []
    rewritten: list = []
    plugin.update_config = lambda config: rewritten.append(dict(config))

    plugin.init_plugin({"enabled": True, "ignorelock": False, "allowlist": "A, B", "delay": 60})

    assert plugin._notify is True
    assert plugin._autorun is True
    assert plugin._ignorelock is False
    assert plugin._allowlist == ["A", "B"]
    assert plugin._local_image_mode == "off"
    assert rewritten == []


def test_legacy_bare_tmdb_key_is_still_migrated() -> None:
    """V2 遗留的裸 TMDB key 在加载时仍迁移为带来源前缀的统一身份，旧记录随之清除。"""
    module = _load_plugin()
    legacy = {
        "episode_groups": [{"id": "g1", "name": "组一"}],
        "mediainfo_dict": {"title": "旧记录", "year": "2015", "tmdb_id": 69367},
    }
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin.get_data = lambda *_args, **_kwargs: [
        SimpleNamespace(key="69367", value=json.dumps(legacy))
    ]
    saved: dict = {}
    deleted: list = []
    plugin.save_data = lambda key, data: saved.setdefault(key, data)
    plugin.del_data = lambda key: deleted.append(key)

    plugin.init_plugin({"enabled": False, "notify": False, "autorun": False, "delay": 60})

    assert list(saved) == ["tmdb:69367"]
    assert deleted == ["69367"]
    migrated_dict = saved["tmdb:69367"]["mediainfo_dict"]
    # 存储 key 用来源别名 tmdb，mediainfo_dict 里保存的是枚举值 themoviedb
    assert migrated_dict["media_source"] == "themoviedb"
    assert migrated_dict["media_id"] == "69367"
    assert "tmdb_id" not in migrated_dict


def test_debounce_merges_events_inside_window() -> None:
    """同一媒体在窗口内的连续事件只保留最后一次，并且只登记一次任务。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=600)

    assert debounce.submit("tmdb:69367", "第一次", now=0) is True
    assert debounce.submit("tmdb:69367", "第二次", now=50) is False
    assert debounce.submit("tmdb:69367", "第三次", now=100) is False

    assert debounce.due("tmdb:69367", now=150) is None
    # 最后一次事件在 100，截止时间为 220
    assert debounce.due("tmdb:69367", now=219) is None
    assert debounce.due("tmdb:69367", now=220) == "第三次"


def test_debounce_slides_window_with_new_event() -> None:
    """窗口内继续到达的事件会推迟执行时间。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=600)

    debounce.submit("tmdb:69367", "第一次", now=0)
    debounce.submit("tmdb:69367", "第二次", now=119)

    # 原截止时间 120 已被顺延到 239
    assert debounce.due("tmdb:69367", now=200) is None
    assert debounce.due("tmdb:69367", now=239) == "第二次"


def test_debounce_max_wait_forces_execution() -> None:
    """持续不断的入库不能无限推迟，超过窗口上限就执行。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=300)

    debounce.submit("tmdb:69367", "一", now=0)
    debounce.submit("tmdb:69367", "二", now=100)
    debounce.submit("tmdb:69367", "三", now=200)
    debounce.submit("tmdb:69367", "四", now=250)

    assert debounce.due("tmdb:69367", now=299) is None
    assert debounce.due("tmdb:69367", now=300) == "四"


def test_debounce_reruns_when_event_arrives_while_running() -> None:
    """执行期间到达的新事件在本轮结束后补跑，不会丢失。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=600)

    debounce.submit("tmdb:69367", "本轮", now=0)
    assert debounce.due("tmdb:69367", now=120) == "本轮"
    # 执行中再来事件：只置待补跑，不额外登记
    assert debounce.submit("tmdb:69367", "补跑", now=130) is False
    assert debounce.finish("tmdb:69367", now=140) is True
    assert debounce.due("tmdb:69367", now=200) is None
    assert debounce.due("tmdb:69367", now=260) == "补跑"
    assert debounce.finish("tmdb:69367", now=270) is False
    assert debounce.has("tmdb:69367") is False


def test_debounce_new_batch_starts_after_finish() -> None:
    """一批事件执行完毕后状态被清理，后续入库会重新开始一轮。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=600)

    assert debounce.submit("tmdb:69367", "第一批", now=0) is True
    assert debounce.due("tmdb:69367", now=120) == "第一批"
    assert debounce.finish("tmdb:69367", now=121) is False
    assert debounce.has("tmdb:69367") is False

    # 之后又入库了新集，需要重新调度
    assert debounce.submit("tmdb:69367", "新入库", now=3600) is True
    assert debounce.due("tmdb:69367", now=3720) == "新入库"


def test_debounce_keys_are_independent() -> None:
    """不同媒体的任务互不影响，也都可以被丢弃。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=60, max_wait=600)

    assert debounce.submit("tmdb:1", "A", now=0) is True
    assert debounce.submit("tmdb:2", "B", now=0) is True
    assert debounce.due("tmdb:1", now=60) == "A"
    assert debounce.has("tmdb:2") is True
    debounce.discard("tmdb:2")
    assert debounce.has("tmdb:2") is False


def test_transfer_events_are_debounced_per_media() -> None:
    """事件入口按媒体合并，并保留无延迟时直接执行的分支。"""
    import inspect

    module = _load_plugin()
    source = inspect.getsource(module.EpisodeGroupMeta.scrap_rt)

    assert "_debounce.submit(" in source
    assert "build_media_key(MediaSource.TMDB, tmdb_media_id)" in source
    assert "__debounce_worker" in inspect.getsource(module.EpisodeGroupMeta)


def test_debounce_window_cap_can_be_widened() -> None:
    """大包入库时窗口上限可调大，避免每 10 分钟整剧重扫一次。"""
    module = _load_plugin()
    debounce = module._MediaDebounce(delay=120, max_wait=1800)

    debounce.submit("tmdb:69367", "一", now=0)
    # 事件一直续到 1700，截止时间被顺延到 1820，但上限 1800 会强制执行
    debounce.submit("tmdb:69367", "二", now=1700)

    assert debounce.due("tmdb:69367", now=1799) is None
    assert debounce.due("tmdb:69367", now=1800) == "二"


def test_debounce_max_minutes_is_configurable() -> None:
    """合并窗口上限按配置的分钟数生效，并提供默认值。"""
    module = _load_plugin()
    plugin = object.__new__(module.EpisodeGroupMeta)
    plugin.log_info = lambda *_args, **_kwargs: None
    plugin.log_warn = lambda *_args, **_kwargs: None
    plugin.log_error = lambda *_args, **_kwargs: None
    plugin.get_data = lambda *_args, **_kwargs: []
    plugin.save_data = lambda *_args, **_kwargs: None
    plugin.del_data = lambda *_args, **_kwargs: None

    plugin.init_plugin({"enabled": True, "notify": False, "autorun": True,
                        "delay": 60, "debounce_max": 30})
    assert plugin._debounce_max_minutes == 30
    assert plugin._debounce._max_wait == 1800

    # 非法值回落到默认 10 分钟
    plugin.init_plugin({"enabled": True, "delay": 60, "debounce_max": "abc"})
    assert plugin._debounce_max_minutes == 10
    assert plugin._debounce._max_wait == 600
