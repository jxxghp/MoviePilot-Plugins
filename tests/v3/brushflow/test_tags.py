"""站点刷流 V3 插件：种子下载标签逻辑单测。

覆盖 issue #6322 修复：
- 任务默认按站点名称生成可读标签（如「刷流-聆音」），不再使用随机代码；
- 新增种子仅打该单一标签（qBittorrent / Transmission）；
- 全局下载数量统计兼容新站点标签与旧全局标签。
"""
import threading
from unittest.mock import MagicMock, PropertyMock, patch

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


class FakeSite:
    """模拟 SiteOper().get() 返回的站点对象"""

    def __init__(self, name: str):
        self.name = name


def _make_task(config=None, site_id=1):
    """构造任务配置，固定 ID 以校验回退标签"""
    return BrushTaskConfig(
        {
            "id": "aabbccdd00112233",
            "name": "聆音刷流",
            "site_id": site_id,
            "downloader": "qb",
            **(config or {}),
        }
    )


def _make_plugin(task):
    """构造不经过 __init__ 的 BrushFlow 实例，仅注入标签逻辑所需状态"""
    plugin = object.__new__(BrushFlow)
    plugin._task_configs = {task.id: task}
    plugin._task_locks = {}
    plugin._runtime = {}
    plugin._runtime_lock = threading.Lock()
    plugin._task_context = threading.local()
    plugin._task_context.task_id = task.id
    return plugin


class TestBrushTag:
    """brush_tag 属性：默认按站点名生成、可自定义、站点缺失时回退"""

    def test_default_tag_uses_site_name(self):
        task = _make_task()
        with patch("app.plugins.brushflow.SiteOper") as mock_site_oper:
            mock_site_oper.return_value.get.return_value = FakeSite("聆音")
            assert task.brush_tag == "刷流-聆音"

    def test_default_tag_falls_back_to_task_id_without_site(self):
        task = _make_task(site_id=0)
        with patch("app.plugins.brushflow.SiteOper") as mock_site_oper:
            mock_site_oper.return_value.get.return_value = None
            assert task.brush_tag == "刷流-aabbccdd"

    def test_custom_tag_wins(self):
        task = _make_task({"tag": "刷流-2xfree"})
        assert task.brush_tag == "刷流-2xfree"


class TestDownloadTags:
    """__download 添加种子时仅打单一可读标签"""

    def _mock_qb_environment(self, plugin, downloader):
        mock_service = MagicMock()
        mock_service.instance = downloader
        mock_dh = MagicMock()
        mock_dh.is_downloader.return_value = True
        patch_service = patch.object(
            type(plugin), "service_info", new_callable=PropertyMock, return_value=mock_service
        )
        patch_helper = patch("app.plugins.brushflow.DownloaderHelper", return_value=mock_dh)
        patch_request = patch("app.plugins.brushflow.RequestUtils", return_value=MagicMock(ok=False))
        return patch_service, patch_helper, patch_request

    def test_qb_download_applies_only_readable_tag(self):
        task = _make_task()
        plugin = _make_plugin(task)
        torrent = MagicMock()
        torrent.enclosure = "http://example.com/seed.torrent"
        torrent.site_proxy = False
        torrent.site_cookie = None
        torrent.site_ua = None
        torrent.site = 1
        torrent.title = "测试种子"
        downloader = MagicMock()
        downloader.add_torrent.return_value = True
        downloader.get_torrent_id_by_tag.return_value = "hash123"
        patch_service, patch_helper, patch_request = self._mock_qb_environment(plugin, downloader)
        with patch("app.plugins.brushflow.SiteOper") as mock_site_oper, \
             patch_service, patch_helper, patch_request:
            mock_site_oper.return_value.get.return_value = FakeSite("聆音")
            result = plugin._BrushFlow__download(torrent)

        assert result == "hash123"
        _, kwargs = downloader.add_torrent.call_args
        assert kwargs["tag"][0] == "刷流-聆音"
        assert "已整理" not in kwargs["tag"]
        assert "刷流" not in kwargs["tag"]
        # 仅站点可读标签 + 用于定位种子 Hash 的临时唯一标签
        assert len(kwargs["tag"]) == 2
        lookup_tag = downloader.get_torrent_id_by_tag.call_args.kwargs["tags"]
        assert lookup_tag in kwargs["tag"]

    def test_transmission_download_applies_only_readable_label(self):
        task = _make_task()
        plugin = _make_plugin(task)
        torrent = MagicMock()
        torrent.enclosure = "http://example.com/seed.torrent"
        torrent.site_proxy = False
        torrent.site_cookie = None
        torrent.site_ua = None
        torrent.site = 1
        torrent.title = "测试种子"
        added = MagicMock()
        added.hashString = "hashxyz"
        downloader = MagicMock()
        downloader.add_torrent.return_value = added
        mock_service = MagicMock()
        mock_service.instance = downloader
        mock_dh = MagicMock()
        mock_dh.is_downloader.side_effect = lambda name, service=None: name == "transmission"
        with patch("app.plugins.brushflow.SiteOper") as mock_site_oper, \
             patch.object(type(plugin), "service_info", new_callable=PropertyMock, return_value=mock_service), \
             patch("app.plugins.brushflow.DownloaderHelper", return_value=mock_dh), \
             patch("app.plugins.brushflow.RequestUtils", return_value=MagicMock(ok=False)):
            mock_site_oper.return_value.get.return_value = FakeSite("聆音")
            result = plugin._BrushFlow__download(torrent)

        assert result == "hashxyz"
        _, kwargs = downloader.add_torrent.call_args
        assert kwargs["labels"] == ["刷流-聆音"]


class TestGlobalDownloadingCount:
    """__get_global_downloading_count 兼容新站点标签与旧全局标签"""

    def test_counts_task_and_legacy_brush_tags(self):
        task = _make_task()
        plugin = _make_plugin(task)
        downloader = MagicMock()
        downloader.get_downloading_torrents.return_value = [
            {"tags": "刷流-聆音"},       # 新版本站点标签
            {"tags": "刷流"},            # 旧版全局标签
            {"tags": "MOVIEPILOT"},      # 无关标签
            {"tags": ""},                # 无标签
        ]
        mock_service = MagicMock()
        mock_service.instance = downloader
        mock_dh = MagicMock()
        mock_dh.get_service.return_value = mock_service
        mock_dh.is_downloader.return_value = True
        with patch("app.plugins.brushflow.SiteOper") as mock_site_oper, \
             patch.object(type(plugin), "service_info", new_callable=PropertyMock, return_value=mock_service), \
             patch("app.plugins.brushflow.DownloaderHelper", return_value=mock_dh):
            mock_site_oper.return_value.get.return_value = FakeSite("聆音")
            assert plugin._BrushFlow__get_global_downloading_count() == 2
