# -*- coding: utf-8 -*-
"""促销标签（PromotionTag）v3 单测：促销判定/到期判定/标签读写分支/站点匹配/记录管理。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from app.plugins.promotiontag import PromotionTag


def make_service(qb=True, tags_op=None):
    """构造下载器服务替身：qb=True 走 qB 分支，否则 Tr 分支。"""
    dl_type = "qbittorrent" if qb else "transmission"
    instance = tags_op or Mock()
    return SimpleNamespace(name="dl1", type=dl_type, instance=instance)


class TestPromoLabel:
    """下载/上传因子 → 标签文案。"""

    def test_free(self, plugin):
        assert plugin._promo_label(0, 1) == "免费"

    def test_free_2x(self, plugin):
        assert plugin._promo_label(0, 2) == "2X免费"

    def test_discount(self, plugin):
        assert plugin._promo_label(0.5, 1) == "50%"

    def test_discount_2x(self, plugin):
        assert plugin._promo_label(0.5, 2) == "2X 50%"

    def test_only_2x(self, plugin):
        assert plugin._promo_label(1, 2) == "2X"

    def test_no_promo(self, plugin):
        assert plugin._promo_label(1, 1) is None

    def test_none_factors(self, plugin):
        # 因子缺失按原价处理 → 无促销
        assert plugin._promo_label(None, None) is None

    def test_broken_factors(self, plugin):
        assert plugin._promo_label("abc", "x") is None


class TestFormatLabel:

    def test_no_prefix(self, plugin):
        assert plugin._format_label("免费") == "免费"

    def test_with_prefix(self, plugin):
        plugin._tag_prefix = "PT"
        assert plugin._format_label("免费") == "PT免费"


class TestIsExpired:
    """限时促销到期判定（tz_offset 分钟校正）。"""

    def test_empty_freedate_never_expires(self, plugin):
        # 永久促销 / 站点未返回时间：不判过期
        assert plugin._is_expired(None) is False
        assert plugin._is_expired("") is False

    def test_past_date_expired(self, plugin):
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        assert plugin._is_expired(past) is True

    def test_future_date_not_expired(self, plugin):
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        assert plugin._is_expired(future) is False

    def test_iso_format(self, plugin):
        past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert plugin._is_expired(past) is True

    def test_tz_offset_moves_boundary(self, plugin):
        # 站点比本地快 60 分钟：本地 now+30min 的 freedate 实际已过期
        boundary = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        plugin._tz_offset = 60
        assert plugin._is_expired(boundary) is True

    def test_broken_date_not_expired(self, plugin):
        assert plugin._is_expired("not-a-date") is False


class TestTagReadWrite:
    """qB / Tr 分支的标签读写。"""

    def test_qb_set_tag(self, plugin):
        instance = Mock()
        service = make_service(qb=True, tags_op=instance)
        assert plugin._set_torrents_tag(service, "h1", ["免费"]) is True
        instance.set_torrents_tag.assert_called_once_with(ids="h1", tags=["免费"])

    def test_tr_set_tag_merges_existing(self, plugin):
        # Tr 为覆盖式：先读旧标签再合并
        instance = Mock()
        instance.get_torrents.return_value = ([SimpleNamespace(labels=["a"])], None)
        service = make_service(qb=False, tags_op=instance)
        assert plugin._set_torrents_tag(service, "h1", ["免费"]) is True
        merged = instance.set_torrent_tag.call_args.kwargs["tags"]
        assert set(merged) == {"a", "免费"}

    def test_qb_remove_tag(self, plugin):
        instance = Mock()
        service = make_service(qb=True, tags_op=instance)
        assert plugin._remove_torrents_tag(service, "h1", ["免费"]) is True
        instance.remove_torrents_tag.assert_called_once_with(ids="h1", tag=["免费"])

    def test_tr_remove_tag_diffs_existing(self, plugin):
        instance = Mock()
        instance.get_torrents.return_value = ([SimpleNamespace(labels=["a", "免费"])], None)
        service = make_service(qb=False, tags_op=instance)
        assert plugin._remove_torrents_tag(service, "h1", ["免费"]) is True
        assert instance.set_torrent_tag.call_args.kwargs["tags"] == ["a"]

    def test_failure_returns_false(self, plugin):
        instance = Mock()
        instance.set_torrents_tag.side_effect = RuntimeError("boom")
        service = make_service(qb=True, tags_op=instance)
        assert plugin._set_torrents_tag(service, "h1", ["免费"]) is False


class TestApplyTag:
    """打标签 + 记录写入（单点自行落盘 / 工作集模式）。"""

    def test_records_persisted_when_own(self, plugin, monkeypatch):
        monkeypatch.setattr(plugin, "_set_torrents_tag", lambda s, h, t: True)
        monkeypatch.setattr(plugin, "_load_records", lambda: {})
        service = make_service()
        assert plugin._apply_tag(service, "h1", 0, 1, None, "免费", "event") is True
        saved = plugin.save_data.call_args[0][1]
        assert saved["dl1:h1"]["label"] == "免费"
        assert saved["dl1:h1"]["state"] == "promo"

    def test_working_set_not_persisted(self, plugin, monkeypatch):
        # records 传入时只写工作集，不落盘（由调用方统一保存）
        monkeypatch.setattr(plugin, "_set_torrents_tag", lambda s, h, t: True)
        service = make_service()
        records = {}
        assert plugin._apply_tag(service, "h1", 0, 1, None, "免费", "fallback",
                                 records=records) is True
        assert records["dl1:h1"]["source"] == "fallback"
        plugin.save_data.assert_not_called()

    def test_prefix_applied(self, plugin, monkeypatch):
        plugin._tag_prefix = "PT"
        monkeypatch.setattr(plugin, "_set_torrents_tag", lambda s, h, t: True)
        monkeypatch.setattr(plugin, "_load_records", lambda: {})
        plugin._apply_tag(make_service(), "h1", 0, 2, None, "2X免费", "event")
        assert plugin.save_data.call_args[0][1]["dl1:h1"]["label"] == "PT2X免费"


class TestSiteMatch:
    """tracker 反查站点 / 大小精确匹配。"""

    def test_identify_site_by_tracker(self, plugin):
        site_domains = [("m-team.cc", "kp.m-team.cc")]
        torrent = {"tracker": "https://tracker.m-team.cc/announce.php"}
        assert plugin._identify_site(torrent, "qbittorrent", site_domains) == "kp.m-team.cc"

    def test_identify_site_subdomain(self, plugin):
        site_domains = [("pt.site.org", "pt.site.org")]
        torrent = {"tracker": "https://tracker2.pt.site.org/xx"}
        assert plugin._identify_site(torrent, "qbittorrent", site_domains) == "pt.site.org"

    def test_identify_site_no_match(self, plugin):
        assert plugin._identify_site({"tracker": "https://unknown.xx/a"},
                                     "qbittorrent", [("a.org", "a.org")]) is None
        assert plugin._identify_site({}, "qbittorrent", [("a.org", "a.org")]) is None

    def test_match_torrent_by_size_qb(self, plugin):
        target = SimpleNamespace(title="T")
        torrent = {"size": 12345}
        assert plugin._match_torrent(torrent, "qbittorrent", {12345: target}) is target
        assert plugin._match_torrent({"size": 999}, "qbittorrent", {12345: target}) is None

    def test_match_torrent_by_size_tr(self, plugin):
        target = SimpleNamespace(title="T")
        torrent = SimpleNamespace(total_size=777)
        assert plugin._match_torrent(torrent, "transmission", {777: target}) is target


class TestTorrentCompat:

    def test_qb_hash_trackers(self):
        torrent = {"hash": "h1", "tracker": "https://t.xx/a"}
        assert PromotionTag._get_hash(torrent, "qbittorrent") == "h1"
        assert PromotionTag._get_trackers(torrent, "qbittorrent") == ["https://t.xx/a"]

    def test_tr_hash_trackers(self):
        torrent = SimpleNamespace(
            hashString="h2",
            trackers=[SimpleNamespace(tier=0, announce="https://t.yy/a"),
                      SimpleNamespace(tier=-1, announce="https://dead/yy")])
        assert PromotionTag._get_hash(torrent, "transmission") == "h2"
        assert PromotionTag._get_trackers(torrent, "transmission") == ["https://t.yy/a"]

    def test_broken_returns_safe(self):
        assert PromotionTag._get_hash(None, "qbittorrent") is None
        assert PromotionTag._get_trackers(None, "qbittorrent") == []


class TestInitPlugin:

    def test_defaults(self, plugin):
        plugin.init_plugin({"enabled": True, "dl_hours": "abc", "cmp_hours": ""})
        assert plugin._enabled is True
        assert plugin._dl_hours == 3   # 非法回退
        assert plugin._cmp_hours == 24
        assert plugin._tag_prefix == ""

    def test_values(self, plugin):
        plugin.init_plugin({"enabled": True, "dl_hours": "5", "tz_offset": "120",
                            "tag_prefix": "PT"})
        assert plugin._dl_hours == 5
        assert plugin._tz_offset == 120
        assert plugin._tag_prefix == "PT"

    def test_onlyonce_resets_and_config_saved(self, plugin):
        plugin.init_plugin({"enabled": True, "onlyonce": True, "downloaders": ["dl1"]})
        assert plugin._onlyonce is False
        saved = plugin.update_config.call_args[0][0]
        assert saved["onlyonce"] is False
        assert saved["downloaders"] == ["dl1"]

    def test_get_service_intervals(self, plugin):
        plugin.init_plugin({"enabled": True, "dl_hours": 2, "cmp_hours": 10,
                            "fallback_enabled": True, "fallback_hours": 6})
        tasks = plugin.get_service()
        ids = {t["id"]: t["kwargs"]["hours"] for t in tasks}
        assert ids == {"PromotionTagDownloading": 2,
                       "PromotionTagCompleted": 10,
                       "PromotionTagFallback": 6}

    def test_get_service_min_one_hour(self, plugin):
        plugin.init_plugin({"enabled": True, "dl_hours": 0})
        tasks = plugin.get_service()
        downloading = next(t for t in tasks if t["id"] == "PromotionTagDownloading")
        assert downloading["kwargs"]["hours"] == 1

    def test_get_service_disabled(self, plugin):
        assert plugin.get_service() == []


class TestNotify:

    def test_notify_sent_with_actions(self, plugin):
        plugin._notify = True
        plugin._notify_actions("标题", ["a", "b"])
        assert plugin.post_message.called
        kwargs = plugin.post_message.call_args.kwargs
        assert "a\nb" in kwargs["text"]

    def test_notify_skipped_when_empty_or_disabled(self, plugin):
        plugin._notify = True
        plugin._notify_actions("标题", [])
        assert not plugin.post_message.called
        plugin._notify = False
        plugin._notify_actions("标题", ["a"])
        assert not plugin.post_message.called

    def test_notify_truncates_at_50(self, plugin):
        plugin._notify = True
        plugin._notify_actions("标题", [f"x{i}" for i in range(60)])
        text = plugin.post_message.call_args.kwargs["text"]
        assert "共 60 条" in text


class TestMeta:

    def test_plugin_meta(self):
        assert PromotionTag.plugin_version == "3.0.0"
        assert PromotionTag.plugin_author == "Guoyin-Wen"
        instance = object.__new__(PromotionTag)
        form, defaults = instance.get_form()
        # V3 契约：form 顶层 list 且首元素是组件 dict（非嵌套 list）
        assert isinstance(form, list) and form and isinstance(form[0], dict)
        assert isinstance(defaults, dict)


class TestDownloadHistoryMap:
    """hash → 站点映射：分页拉全量、跳过空 hash、异常安全。"""

    def test_paged_and_skips_empty_hash(self, plugin, monkeypatch):
        from types import SimpleNamespace as NS
        calls = {"page": 0, "count": 0}

        def fake_list_by_page(self, page=1, count=30):
            calls["page"] += 1
            calls["count"] = count
            if page == 1:
                # 满页（count 条）触发翻页，其中含空 hash 行
                rows = [NS(download_hash=f"p1h{i}", torrent_site="站A", torrent_name="N")
                        for i in range(count - 1)]
                rows.append(NS(download_hash=None, torrent_site="X", torrent_name="N2"))
                return rows
            if page == 2:
                return [NS(download_hash="h2", torrent_site="站B", torrent_name="N3")]
            return []

        import app.db.oper.downloadhistory as mod
        monkeypatch.setattr(mod.DownloadHistoryOper, "list_by_page", fake_list_by_page)
        result = plugin._load_downloadhistory_map()
        assert result["h2"] == {"site": "站B", "name": "N3"}
        assert "p1h0" in result and len(result) == calls["count"]  # 空 hash 行被跳过
        assert calls["page"] == 2  # 第 2 页不足一页即止，不再多拉

    def test_broken_history_returns_empty(self, plugin, monkeypatch):
        import app.db.oper.downloadhistory as mod
        def boom(self, page=1, count=30):
            raise RuntimeError("同步事务执行器尚未配置")
        monkeypatch.setattr(mod.DownloadHistoryOper, "list_by_page", boom)
        assert plugin._load_downloadhistory_map() == {}
