"""促销标签写入失败、标签保留和到期边界回归。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock


def test_failed_write_does_not_create_promotion_record(plugin):
    """下载器返回失败时不缓存为已打标签，后续扫描仍可重试。"""
    downloader = Mock()
    downloader.set_torrents_tag.return_value = False
    service = SimpleNamespace(name="qb", type="qbittorrent", instance=downloader)
    assert plugin._apply_tag(service, "hash", 0, 1, None, "免费", "event") is False
    plugin.save_data.assert_not_called()


def test_transmission_read_failure_cannot_overwrite_other_tags(plugin):
    """读取原标签失败时禁止覆盖式写入，保留其他插件标签。"""
    downloader = Mock()
    downloader.get_torrents.return_value = (None, "offline")
    service = SimpleNamespace(name="tr", type="transmission", instance=downloader)
    assert plugin._set_torrents_tag(service, "hash", ["免费"]) is False
    assert plugin._remove_torrents_tag(service, "hash", ["免费"]) is False
    downloader.set_torrent_tag.assert_not_called()


def test_remove_last_transmission_tag_uses_empty_label_rpc(plugin):
    """宿主包装器不允许空列表，移除最后一个促销标签时直接清空对应任务标签。"""
    downloader = Mock()
    downloader.get_torrents.return_value = ([SimpleNamespace(labels=["免费"])], None)
    service = SimpleNamespace(name="tr", type="transmission", instance=downloader)
    assert plugin._remove_torrents_tag(service, "hash", ["免费"]) is True
    downloader.trc.change_torrent.assert_called_once_with(ids="hash", labels=[])
    downloader.set_torrent_tag.assert_not_called()


def test_promotion_does_not_expire_before_actual_second(plugin):
    """未来不足一分钟的时间仍有效，带时区日期按其实际时刻比较。"""
    assert not plugin._is_expired((datetime.now() + timedelta(seconds=30)).isoformat())
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert not plugin._is_expired(future.isoformat())
    assert plugin._promo_label(0.3, 1) == "30%"
    assert plugin._promo_label(0.25, 2) == "2X 25%"
