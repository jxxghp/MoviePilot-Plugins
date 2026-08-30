"""DownloadSiteTag V3 的宿主边界、业务路径和生命周期测试。"""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

from app.plugins.downloadsitetag import DownloadSiteTag, _DownloadHistoryView
from app.schemas.types import MediaSource


ROOT = Path(__file__).parents[3]
PLUGIN_SOURCE = ROOT / "plugins.v3" / "downloadsitetag" / "__init__.py"


def _make_plugin() -> DownloadSiteTag:
    """构造不触发宿主插件管理器的最小实例。"""
    plugin = object.__new__(DownloadSiteTag)
    plugin._enabled = True
    plugin._enabled_tag = True
    plugin._enabled_media_tag = False
    plugin._enabled_category = False
    plugin._enabled_del_tags = False
    plugin._category_movie = "电影"
    plugin._category_tv = "电视"
    plugin._category_anime = "动漫"
    plugin._downloaders = ["qb"]
    plugin._site_prefix = ""
    plugin._media_prefix = ""
    plugin._tracker_mappings = {}
    plugin._event = threading.Event()
    plugin._scheduler = None
    return plugin


def _make_service(downloader: MagicMock) -> SimpleNamespace:
    """构造 DownloadSiteTag 使用的最小下载器服务描述。"""
    return SimpleNamespace(name="qb", type="qbittorrent", instance=downloader)


def test_v3_metadata_and_host_floor_are_declared() -> None:
    """V3 版本、索引和最低宿主版本必须保持一致。"""
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    legacy_package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    metadata = package["DownloadSiteTag"]

    assert DownloadSiteTag.plugin_version == "3.2.0"
    assert metadata["version"] == DownloadSiteTag.plugin_version
    assert metadata["system_version"] == ">=3.0.0"
    assert metadata["history"]["v3.2.0"]
    assert legacy_package["DownloadSiteTag"]["v3"] is False


def test_v3_uses_oper_without_importing_or_constructing_host_orm_model() -> None:
    """插件只依赖公开 Oper 查询，不能把宿主 ORM 模型带入插件逻辑。"""
    tree = ast.parse(PLUGIN_SOURCE.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.db.models")
        for node in ast.walk(tree)
    )
    assert "from app.db.oper.downloadhistory import DownloadHistoryOper" in PLUGIN_SOURCE.read_text(
        encoding="utf-8"
    )


def test_history_view_normalizes_media_identity_and_is_detached_from_record() -> None:
    """媒体来源和 ID 必须成对规范化，推导站点标签不得回写宿主记录。"""
    record = SimpleNamespace(
        torrent_site="站点",
        media_id=" 123 ",
        media_source="tmdb",
        type="电视剧",
        title="示例剧",
    )

    view = _DownloadHistoryView.from_record(record)
    view.torrent_site = "推导站点"

    assert view.media_source == MediaSource.TMDB
    assert view.media_id == "123"
    assert record.torrent_site == "站点"

    invalid = _DownloadHistoryView.from_record(
        SimpleNamespace(
            torrent_site=None,
            media_id="0",
            media_source="themoviedb",
            type="电视剧",
            title="示例剧",
        )
    )
    assert invalid.media_source is None
    assert invalid.media_id is None


def test_complemented_history_projects_oper_record_before_tagging() -> None:
    """补全历史时应通过 Oper 读取并使用插件侧视图生成站点标签。"""
    plugin = _make_plugin()
    downloader = MagicMock()
    torrent = {
        "hash": "abc",
        "size": 100,
        "name": "示例种子",
        "added_on": 1,
        "tags": "",
        "category": "",
        "trackers": [],
    }
    downloader.get_torrents.return_value = ([torrent], None)
    service = _make_service(downloader)
    record = SimpleNamespace(
        torrent_site="站点",
        media_id="123",
        media_source="themoviedb",
        type="电视剧",
        title="示例剧",
    )
    plugin._set_torrent_info = MagicMock()

    with patch.object(
        type(plugin),
        "service_infos",
        new_callable=PropertyMock,
        return_value={"qb": service},
    ), patch("app.plugins.downloadsitetag.SitesHelper") as sites_helper, patch(
        "app.plugins.downloadsitetag.DownloadHistoryOper"
    ) as history_oper:
        sites_helper.return_value.get_indexers.return_value = []
        history_oper.return_value.get_by_hash.return_value = record
        plugin._complemented_history()

    history_oper.return_value.get_by_hash.assert_called_once_with("abc")
    plugin._set_torrent_info.assert_called_once()
    assert plugin._set_torrent_info.call_args.kwargs["_tags"] == ["站点"]
    assert record.torrent_site == "站点"


def test_complemented_history_only_queries_tmdb_for_tmdb_identity() -> None:
    """非 TMDB 媒体身份不能被误传给 TMDB 分类查询。"""
    plugin = _make_plugin()
    plugin._enabled_category = True
    downloader = MagicMock()
    torrent = {
        "hash": "abc",
        "size": 100,
        "name": "示例种子",
        "added_on": 1,
        "tags": "",
        "category": "",
        "trackers": [],
    }
    downloader.get_torrents.return_value = ([torrent], None)
    service = _make_service(downloader)
    record = SimpleNamespace(
        torrent_site="站点",
        media_id="123",
        media_source="douban",
        type="电视剧",
        title="示例剧",
    )
    plugin.chain = MagicMock()
    plugin._set_torrent_info = MagicMock()

    with patch.object(
        type(plugin),
        "service_infos",
        new_callable=PropertyMock,
        return_value={"qb": service},
    ), patch("app.plugins.downloadsitetag.SitesHelper") as sites_helper, patch(
        "app.plugins.downloadsitetag.DownloadHistoryOper"
    ) as history_oper:
        sites_helper.return_value.get_indexers.return_value = []
        history_oper.return_value.get_by_hash.return_value = record
        plugin._complemented_history()

    plugin.chain.tmdb_info.assert_not_called()
    assert plugin._set_torrent_info.call_args.kwargs["_cat"] == "电视"


def test_download_added_routes_event_to_declared_downloader() -> None:
    """下载事件必须使用事件声明的下载器，而不是宿主默认下载器。"""
    plugin = _make_plugin()
    downloader = MagicMock()
    service = _make_service(downloader)
    plugin._set_torrent_info = MagicMock()
    context = SimpleNamespace(
        torrent_info=SimpleNamespace(site_name="站点"),
        media_info=SimpleNamespace(type=None, title=None, genre_ids=None),
    )
    event = SimpleNamespace(event_data={"downloader": "qb", "context": context, "hash": "abc"})

    with patch.object(
        type(plugin),
        "service_infos",
        new_callable=PropertyMock,
        return_value={"qb": service},
    ):
        plugin.download_added(event)

    plugin._set_torrent_info.assert_called_once()
    assert plugin._set_torrent_info.call_args.kwargs["service"] is service
    assert plugin._set_torrent_info.call_args.kwargs["_hash"] == "abc"


def test_qb_category_fallback_keeps_host_call_order() -> None:
    """qBittorrent 分类失败时应先创建分类，再重试当前种子。"""
    plugin = _make_plugin()
    downloader = MagicMock()
    downloader.qbc = MagicMock()
    torrent = MagicMock()
    torrent.setCategory.side_effect = [RuntimeError("category missing"), None]
    service = _make_service(downloader)

    plugin._set_torrent_info(
        service=service,
        _hash="abc",
        _torrent=torrent,
        _tags=["站点"],
        _cat="电视",
        _tags_to_remove=["旧标签"],
    )

    downloader.remove_torrents_tag.assert_called_once_with(ids="abc", tag=["旧标签"])
    downloader.set_torrents_tag.assert_called_once_with(ids="abc", tags=["站点"])
    downloader.qbc.torrents_createCategory.assert_called_once_with(name="电视")
    assert torrent.setCategory.call_args_list == [call(category="电视"), call(category="电视")]


def test_fixed_hour_service_keeps_unused_tag_cleanup_task() -> None:
    """固定小时补全任务不能丢弃已启用的标签清理公共服务。"""
    plugin = _make_plugin()
    plugin._interval = "固定间隔"
    plugin._interval_unit = "小时"
    plugin._interval_time = 2
    plugin._enabled_del_tags = True

    tasks = plugin.get_service()

    assert [task["id"] for task in tasks] == ["DeleteUnusedTags", "DownloadSiteTag"]
    assert tasks[1]["kwargs"] == {"hours": 2}


def test_config_number_parser_handles_missing_values() -> None:
    """缺失或非法的间隔配置应回退到默认值。"""
    assert DownloadSiteTag.str_to_number(None, 6) == 6
    assert DownloadSiteTag.str_to_number("invalid", 6) == 6
    assert DownloadSiteTag.str_to_number("8", 6) == 8


def test_stop_service_is_idempotent_and_shuts_down_scheduler() -> None:
    """插件停止时应移除任务并释放调度器，重复停止不应失败。"""
    plugin = _make_plugin()
    scheduler = MagicMock()
    scheduler.running = True
    plugin._scheduler = scheduler

    plugin.stop_service()
    plugin.stop_service()

    scheduler.remove_all_jobs.assert_called_once_with()
    scheduler.shutdown.assert_called_once_with()
    assert plugin._scheduler is None
