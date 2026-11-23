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
