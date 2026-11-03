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

    assert module.EpisodeGroupMeta.plugin_version == "3.2.3"
    assert v3["EpisodeGroupMeta"]["version"] == "3.2.3"
    assert v3["EpisodeGroupMeta"]["system_version"] == ">=3.0.0"
    assert v3["EpisodeGroupMeta"]["history"]["v3.2.3"]
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
    """已锁定条目：不写元数据、不改锁定状态，但补剧集组已有的分集图。"""
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
    ) is False
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


def test_existing_image_is_kept_and_legacy_thumb_is_warned() -> None:
    """同名分集图已存在时跳过写入仍算成功，旧命名 -thumb 图给出清理提示。"""
    module = _load_plugin()
    plugin, chain, warnings = _local_plugin(
        module,
        existing=[VIDEO, f"{FOLDER}/示例.S01E01.jpg", f"{FOLDER}/示例.S01E01-thumb.jpg"],
    )

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.jpg") is True
    assert chain.upload_calls == []
    assert any("旧命名分集图" in w for w in warnings)


def test_overwrite_mode_replaces_existing_image() -> None:
    """开启覆盖后同名分集图也会被重新写入，并沿用图片自身的后缀。"""
    module = _load_plugin()
    plugin, chain, _ = _local_plugin(
        module, existing=[VIDEO, f"{FOLDER}/示例.S01E01.jpg"], overwrite=True
    )

    assert plugin.save_item_image_local({"Path": VIDEO}, "https://image/still1.png") is True
    assert [call["name"] for call in chain.upload_calls] == ["示例.S01E01.png"]


def test_locked_backfill_prefers_local_image_when_enabled() -> None:
    """已锁定条目补图同样走本地落盘，成功后不再推送媒体服务器图片接口。"""
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
    ) is False
    assert written == []
    assert images == []
    assert [call["name"] for call in plugin._storage_chain.upload_calls] == ["示例.S01E01.jpg"]

