"""ZSpaceVideo 宿主契约测试。

用真实的 ``_PluginBase`` 验证插件生命周期与声明结构：关闭状态下初始化不启动后台、
可重复初始化、停止可重入、API 声明合法、事件入口在关闭时不做任何事。
不触网、不下载 zspace-cli。没有 MoviePilot 后端（插件仓单独跑纯逻辑测试）时跳过。
"""

import inspect
from unittest.mock import MagicMock

import pytest

pytest.importorskip("app.sdk.plugin")

from app.plugins.zspacevideo import ZSpaceVideo, transfer_target_path  # noqa: E402


def _plugin(tmp_path):
    plugin = object.__new__(ZSpaceVideo)
    plugin.get_data_path = MagicMock(return_value=str(tmp_path))
    plugin.get_data = MagicMock(return_value=None)
    plugin.save_data = MagicMock()
    plugin.update_config = MagicMock()
    plugin.post_message = MagicMock()
    plugin._service = None
    plugin._watch = None
    return plugin


class TestPluginContract:
    """插件必须实现的基线契约。"""

    def test_inherits_plugin_base(self):
        from app.sdk.plugin import _PluginBase

        assert issubclass(ZSpaceVideo, _PluginBase)

    @pytest.mark.parametrize(
        "method",
        ["init_plugin", "get_state", "get_api", "get_form", "get_page", "stop_service", "get_service"],
    )
    def test_required_methods_exist(self, method):
        assert callable(getattr(ZSpaceVideo, method, None))

    def test_vue_render_mode_points_to_built_assets(self):
        from pathlib import Path

        mode, assets = ZSpaceVideo.get_render_mode()
        assert mode == "vue"
        plugin_dir = Path(inspect.getfile(ZSpaceVideo)).parent
        assert (plugin_dir / assets / "remoteEntry.js").is_file()


class TestLifecycle:
    """关闭状态下初始化不启动后台；可重复初始化、重复停止。"""

    def test_disabled_init_has_no_background_service(self, tmp_path):
        plugin = _plugin(tmp_path)
        plugin.init_plugin({"enabled": False})
        assert plugin.get_state() is False
        assert plugin.get_service() == []
        assert plugin._service is not None and plugin._watch is not None

    def test_init_is_repeatable_and_stop_idempotent(self, tmp_path):
        plugin = _plugin(tmp_path)
        plugin.init_plugin({"enabled": False})
        plugin.init_plugin({"enabled": False})
        plugin.stop_service()
        plugin.stop_service()
        assert plugin._service is None

    def test_data_dirs_are_private(self, tmp_path):
        plugin = _plugin(tmp_path)
        plugin.init_plugin({"enabled": False})
        for name in ("bin", "cli"):
            mode = (tmp_path / name).stat().st_mode & 0o777
            assert mode == 0o700, (name, oct(mode))

    def test_transfer_event_ignored_when_disabled(self, tmp_path):
        plugin = _plugin(tmp_path)
        plugin.init_plugin({"enabled": False})
        plugin._service = MagicMock()
        plugin.on_transfer_complete(MagicMock(event_data={}))
        plugin._service.on_transfer.assert_not_called()

    def test_transfer_target_path_handles_missing_data(self):
        assert transfer_target_path(None) is None
        assert transfer_target_path({}) is None


class TestApiDeclaration:
    """get_api 声明的结构必须符合宿主契约。"""

    def test_api_entries_are_well_formed(self, tmp_path):
        plugin = _plugin(tmp_path)
        entries = plugin.get_api()
        assert isinstance(entries, list) and entries
        routes = [(entry["path"], method) for entry in entries for method in entry["methods"]]
        assert len(routes) == len(set(routes))
        for entry in entries:
            assert entry["path"].startswith("/")
            assert callable(entry["endpoint"])
            assert isinstance(entry["methods"], list) and entry["methods"]
            assert entry["auth"] == "bear"
            assert entry.get("summary")


class TestPruneDir:
    """删完库入口后清空目录：上级目录里有别的文件（如 pdf）时只删空的那一层。"""

    def test_parent_with_unknown_file_kept(self, tmp_path, monkeypatch):
        from app.plugins.zspacevideo import host as H
        from app.plugins.zspacevideo.core import watched as W

        root = tmp_path / "tv"
        season = root / "样剧" / "Season 1"
        season.mkdir(parents=True)
        (root / "样剧" / "notes.pdf").write_bytes(b"p")
        monkeypatch.setattr(H, "library_roots", lambda: W.Roots(library=[str(root)], download=[]))
        from app.application.directory import DirectoryHelper
        monkeypatch.setattr(DirectoryHelper, "get_media_cleanup_root", lambda self, item: root)
        H.prune_dir(str(season))
        assert not season.exists()
        assert (root / "样剧" / "notes.pdf").exists()
        assert root.is_dir()

    def test_boundary_lookup_failure_prunes_nothing(self, tmp_path, monkeypatch):
        from app.application.directory import DirectoryHelper
        from app.plugins.zspacevideo import host as H
        from app.plugins.zspacevideo.core import watched as W

        root = tmp_path / "media"
        season = root / "TV" / "样剧" / "Season 1"
        season.mkdir(parents=True)
        monkeypatch.setattr(H, "library_roots", lambda: W.Roots(library=[str(root)], download=[]))

        def boom(self, item):
            raise RuntimeError("目录配置读不到")
        monkeypatch.setattr(DirectoryHelper, "get_media_cleanup_root", boom)
        H.prune_dir(str(season))
        assert season.is_dir()


class TestWatchedApi:
    def test_preview_empty_version_list_is_not_all(self, tmp_path):
        plugin = _plugin(tmp_path)
        svc = MagicMock()
        plugin._watch = svc
        plugin.api_watched_preview({"key": "movie:1", "mode": "library", "version_ids": []})
        assert svc.preview.call_args.args[2] == []
        plugin.api_watched_preview({"key": "movie:1", "mode": "library"})
        assert svc.preview.call_args.args[2] is None


class TestHistoryFilters:
    def test_media_type_filter_accepted_by_host(self):
        from app.schemas.query import DownloadHistoryFilter, TransferHistoryFilter
        from app.plugins.zspacevideo import host as H

        for kind in ("movie", "season"):
            TransferHistoryFilter.model_validate({"media_source": "themoviedb", "media_id": "1", "status": True,
                                                  "media_types": H._media_types(kind)})
            DownloadHistoryFilter.model_validate({"media_source": "themoviedb", "media_id": "1",
                                                  "media_types": H._media_types(kind)})
