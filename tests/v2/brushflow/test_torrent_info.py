"""BrushFlow 插件兼容性测试：确保 __get_torrent_info 兼容 transmission-rpc v7.x。

v7.x 将以下属性重命名：
  date_done   → done_date
  date_added  → added_date
  date_active → activity_date
  tags (dict)  → labels (property, list[str])
  tracker (dict) → tracker_list (property, list[str])
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from brushflow import BrushFlow


class FakeTorrentV7:
    """模拟 transmission-rpc v7.x 的 Torrent 对象。

    v7.x 中 date_done/date_added/date_active 已被移除，
    只保留 done_date/added_date/activity_date。
    """

    def __init__(self):
        self.hashString = "aabbccdd"
        self.name = "Test.Torrent-SomeGroup"
        self.done_date = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.added_date = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        self.activity_date = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        self.total_size = 1024 * 1024 * 100  # 100 MB
        self.progress = 100.0
        self.ratio = 1.5
        self.labels = ["brush_tag", "movie"]
        self.tracker_list = ["https://tracker.example.com/announce"]
        self.magnet_link = "magnet:?xt=urn:btih:aabbccdd&tr=https://tracker.example.com/announce"

    # v7.x Torrent 没有 .get() 方法，不定义该属性


@pytest.fixture
def brushflow_instance():
    """创建 BrushFlow 实例。"""
    return BrushFlow()


def _make_downloader_helper_mock():
    """创建 mock DownloaderHelper，模拟 Transmission 下载器（非 QB）。"""
    mock_dh = MagicMock()
    mock_dh.is_downloader.return_value = False
    return mock_dh


# ─── __get_torrent_info ────────────────────────────────────────────

class TestGetTorrentInfoV7:
    """测试 __get_torrent_info 能正确处理 v7.x Torrent 对象。"""

    def test_extracts_basic_fields_from_v7_torrent(self, brushflow_instance):
        """应从 v7.x Torrent 对象正确提取基本字段（hash, title, total_size, ratio）。"""
        torrent = FakeTorrentV7()
        mock_dh = _make_downloader_helper_mock()
        with patch("brushflow.DownloaderHelper", return_value=mock_dh), \
             patch.object(type(brushflow_instance), "service_info",
                          new_callable=PropertyMock,
                          return_value=MagicMock()):
            result = getattr(brushflow_instance, "_BrushFlow__get_torrent_info")(torrent)

        assert result["hash"] == "aabbccdd"
        assert result["title"] == "Test.Torrent-SomeGroup"
        assert result["total_size"] == 1024 * 1024 * 100
        assert result["ratio"] == 1.5

    def test_computes_seeding_time_from_done_date(self, brushflow_instance):
        """应使用 done_date（v7.x）计算做种时间，结果为正数。"""
        torrent = FakeTorrentV7()
        mock_dh = _make_downloader_helper_mock()
        with patch("brushflow.DownloaderHelper", return_value=mock_dh), \
             patch.object(type(brushflow_instance), "service_info",
                          new_callable=PropertyMock,
                          return_value=MagicMock()):
            result = getattr(brushflow_instance, "_BrushFlow__get_torrent_info")(torrent)

        assert result["seeding_time"] > 0

    def test_extracts_tags_from_labels(self, brushflow_instance):
        """应从 labels 属性（v7.x）提取标签列表。"""
        torrent = FakeTorrentV7()
        mock_dh = _make_downloader_helper_mock()
        with patch("brushflow.DownloaderHelper", return_value=mock_dh), \
             patch.object(type(brushflow_instance), "service_info",
                          new_callable=PropertyMock,
                          return_value=MagicMock()):
            result = getattr(brushflow_instance, "_BrushFlow__get_torrent_info")(torrent)

        assert result["tags"] == ["brush_tag", "movie"]

    def test_extracts_tracker_from_tracker_list(self, brushflow_instance):
        """应从 tracker_list 属性（v7.x）提取第一个 tracker URL。"""
        torrent = FakeTorrentV7()
        mock_dh = _make_downloader_helper_mock()
        with patch("brushflow.DownloaderHelper", return_value=mock_dh), \
             patch.object(type(brushflow_instance), "service_info",
                          new_callable=PropertyMock,
                          return_value=MagicMock()):
            result = getattr(brushflow_instance, "_BrushFlow__get_torrent_info")(torrent)

        assert result["tracker"] == "https://tracker.example.com/announce"


# ─── __get_site_by_torrent ─────────────────────────────────────────

class TestGetSiteByTorrentV7:
    """测试 __get_site_by_torrent 能从 v7.x Torrent 对象获取站点信息。"""

    def test_extracts_tracker_from_v7_torrent(self):
        """应从 v7.x Torrent 的 tracker_list 获取 tracker URL。"""
        torrent = FakeTorrentV7()
        site_id, domain = getattr(BrushFlow, "_BrushFlow__get_site_by_torrent")(torrent)

        # 至少应解析出 tracker.example.com 的域名
        assert "example.com" in domain or domain != "未知"
