"""特典映射、NFO 补全、存量写入和插件生命周期回归。"""

import os
import stat
from datetime import datetime, timezone
from os.path import split
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import MagicMock
from xml.dom import minidom

import pytest

from app.plugins import specialepisodeorder as plugin_module
from app.plugins.specialepisodeorder import SpecialEpisodeOrder
from app.plugins.specialepisodeorder import client as client_module
from app.plugins.specialepisodeorder.client import LookupFailure, MetadataClient, TvdbEpisodeNotFound
from app.plugins.specialepisodeorder.nfo import NfoEnricher, integer, parse_overrides
from app.plugins.specialepisodeorder import repair as repair_module
from app.plugins.specialepisodeorder.repair import RepairRunner
from app.schemas.types import MediaType


def nfo(extra="", episode=2, identity=938553, as_bytes=True):
    """构造已有缩进且带双重 TMDb 身份的特典 NFO。"""
    content = (
        '<episodedetails>\n  <title>测试 &amp; 特典</title>\n'
        f'  <season>0</season>\n  <episode>{episode}</episode>\n'
        f'  <tmdbid>{identity}</tmdbid>\n  <uniqueid type="tmdb">{identity}</uniqueid>\n'
        f'  <plot><![CDATA[保留原有 <简介>]]></plot>\n{extra}</episodedetails>\n'
    )
    return content.encode() if as_bytes else content


@pytest.fixture
def client():
    """隔离所有外部查询，默认表示已人工核实的首季第二个特典。"""
    value = MagicMock()
    value.configured = True
    value.episode_ids.return_value = {"id": 938553, "tvdb_id": 3250591}
    value.series_ids.return_value = {"tvdb_id": 194961}
    value.episode.return_value = {"id": 3250591, "seriesId": 194961, "airsAfterSeason": 1}
    return value


def tags(content):
    """读取 XML 直接子节点的文本以断言业务结果。"""
    root = minidom.parseString(content).documentElement
    return {node.tagName: "".join(child.nodeValue or "" for child in node.childNodes) for node in root.childNodes if isinstance(node, minidom.Element)}


@pytest.mark.parametrize("as_bytes", [True, False])
def test_enrichment_preserves_content_type_and_format(client, as_bytes):
    """补全保留输入类型、已有字段、CDATA 和缩进格式。"""
    original = nfo(as_bytes=as_bytes)
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.status == "updated"
    assert type(result.content) is type(original)
    assert tags(result.content)["airsafter_season"] == "1"
    text = result.content.decode() if as_bytes else result.content
    assert "\n\n" not in text
    assert '<![CDATA[保留原有 <简介>]]>' in text
    assert "测试 &amp; 特典" in text


def test_manual_override_and_cross_season_numbering(client):
    """人工修正优先于失效映射，TVDB 集号不同也可按身份精确匹配。"""
    client.episode.return_value.update(id=8636540, number=50, seasonNumber=0)
    result = NfoEnricher(client, parse_overrides("938553,tvdb=8636540")).enrich(nfo(), 56353, 2)
    assert result.status == "updated"
    assert result.mapping_source == "手动修正"
    client.episode.assert_called_once_with(8636540)


def test_manual_positions_merge_with_tvdb_and_suppress_explicit_empty_field(client):
    """手动值覆盖 API，省略项也用本次映射替换旧值。"""
    client.episode.return_value.update(id=8636540, airsBeforeSeason=2, airsBeforeEpisode=7)
    overrides = parse_overrides("938553,tvdb=8636540,airsafter_season=0,airsbefore_episode=")
    original = nfo("<airsafter_season>9</airsafter_season><displayseason>9</displayseason><airsbefore_episode>6</airsbefore_episode><displayepisode>6</displayepisode>")
    result = NfoEnricher(client, overrides).enrich(original, 56353, 2)

    assert result.status == "updated"
    assert result.positions_after == {"airsafter_season": "0", "airsbefore_season": "2", "airsbefore_episode": None}
    assert {"airsbefore_episode", "displayepisode"}.isdisjoint(tags(result.content))
    assert "airsbefore_episode：6 → 未设置" in result.describe_changes()
    client.episode.assert_called_once_with(8636540)


@pytest.mark.parametrize("value", [None, True, False, -1, 1.2, "abc", "-1"])
def test_invalid_positions_leave_original_unchanged(client, value):
    """无效或缺失的位置不触发文件重写。"""
    client.episode.return_value["airsAfterSeason"] = value
    original = nfo()
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.status == "skipped"
    assert result.content is original


@pytest.mark.parametrize("field,value", [("airsAfterSeason", 0), ("airsBeforeSeason", "0"), ("airsBeforeEpisode", 7)])
def test_zero_and_before_positions(client, field, value):
    """接受零值及剧集之前播放的位置。"""
    client.episode.return_value = {"id": 3250591, "seriesId": 194961, field: value}
    result = NfoEnricher(client).enrich(nfo(), 56353, 2)
    assert result.status == "updated"
    assert str(value) in tags(result.content).values()


@pytest.mark.parametrize("tag", ["airsafter_season", "displayafterseason"])
def test_successful_mapping_replaces_existing_positions_and_aliases(client, tag):
    """三项均有旧值时，同步本次结果并清除无值的位置。"""
    original = nfo(f"<{tag}>9</{tag}><airsbefore_season>2</airsbefore_season><displayepisode>6</displayepisode>")
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.status == "updated"
    fields = tags(result.content)
    assert fields[tag] == "1"
    assert {"airsbefore_season", "displayepisode"}.isdisjoint(fields)
    assert result.positions_after == {"airsafter_season": "1", "airsbefore_season": None, "airsbefore_episode": None}


def test_successful_mapping_without_positions_clears_old_values(client):
    """确认单集归属后，空位置结果也用于同步 NFO。"""
    client.episode.return_value.pop("airsAfterSeason")
    result = NfoEnricher(client).enrich(nfo("<displayafterseason>1</displayafterseason>"), 56353, 2)

    assert result.status == "updated"
    assert result.positions_after == dict.fromkeys(("airsafter_season", "airsbefore_season", "airsbefore_episode"))
    assert "displayafterseason" not in tags(result.content)


def test_repeated_enrichment_is_idempotent(client):
    """重复补全不会添加重复字段或重新排版文件。"""
    engine = NfoEnricher(client)
    first = engine.enrich(nfo(), 56353, 2)
    second = engine.enrich(first.content, 56353, 2)
    assert second.status == "skipped"
    assert second.content is first.content


@pytest.mark.parametrize("mutate,status", [
    (lambda c: c.episode_ids.return_value.update(id=999), "skipped"),
    (lambda c: c.episode_ids.return_value.update(tvdb_id=None), "needs_correction"),
    (lambda c: setattr(c, "configured", False), "skipped"),
    (lambda c: c.episode.return_value.clear(), "needs_correction"),
    (lambda c: c.episode.return_value.update(id=999), "needs_correction"),
    (lambda c: c.episode.return_value.update(seriesId=999), "needs_correction"),
    (lambda c: c.series_ids.return_value.clear(), "needs_correction"),
])
def test_unverified_identity_does_not_modify_nfo(client, mutate, status):
    """保留原文件，并区分需要修正的映射和普通跳过。"""
    mutate(client)
    original = nfo("<airsafter_season>1</airsafter_season><airsbefore_season>2</airsbefore_season><airsbefore_episode>3</airsbefore_episode>")
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.status == status
    assert result.content is original


@pytest.mark.parametrize("method", ["episode_ids", "episode", "series_ids"])
def test_lookup_failure_preserves_original(client, method):
    """可选的外部补全失败不会损坏基础 NFO。"""
    getattr(client, method).side_effect = LookupFailure("测试服务 HTTP 503")
    original = nfo("<airsafter_season>9</airsafter_season>")
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.status == "failed"
    assert result.content is original
    assert "503" in result.reason


@pytest.mark.parametrize("original", [
    b"<episodedetails>",
    b'<!DOCTYPE x [<!ENTITY a "x">]><episodedetails/>',
    nfo().replace(b"<season>0</season>", b"<season>1</season>"),
    nfo().replace(b"<tmdbid>938553</tmdbid>", b"<tmdbid>999</tmdbid>"),
    nfo().replace(b"<episode>2</episode>", b"<episode>2</episode><episode>2</episode>"),
    nfo().replace(b"episodedetails", b"movie"),
])
def test_unsuitable_nfo_does_not_query_network(client, original):
    """不适合的 XML、错误季集及冲突身份在查询前被拒绝。"""
    result = NfoEnricher(client).enrich(original, 56353, 2)
    assert result.content is original
    client.episode_ids.assert_not_called()


@pytest.mark.parametrize("text", [
    "bad", "1=2=3", "0=1", "1=-1", "1=2\n1=3", "True=4",
    "1,tvdb=", "1,tvdb=0", "1,airsbefore_episode=-1", "1,other=2", "1,airsafter_season",
    "1,tvdb=2,tvdb=3", "1,airsafter_season=2\n1,airsafter_season=3",
    "1,ignore,tvdb=2", "1,tvdb=2,ignore", "1,ignore=1", "1,ignore\n1,airsafter_season=2",
])
def test_invalid_override_configuration(text):
    """错误配置整体失败，避免悄悄丢弃用户输入。"""
    with pytest.raises(ValueError):
        parse_overrides(text)


def test_valid_override_comments_and_duplicates():
    """允许空行、注释和相同映射的重复声明。"""
    assert parse_overrides("# 已核实\n938553=8636540\n\n938553 , tvdb = 8636540 # 同一集") == parse_overrides(
        "938553,tvdb=8636540"
    )
    rule = parse_overrides("938555,airsafter_season=0,airsbefore_season=2,airsbefore_episode=")[938555]
    assert rule.tvdb_id is None
    assert rule.positions == {"airsafter_season": 0, "airsbefore_season": 2, "airsbefore_episode": None}
    assert parse_overrides("1174618, ignore # 保留本集原值")[1174618].ignore
    assert integer(True) is None


@pytest.fixture
def library(tmp_path):
    """创建仅位于临时目录的电视剧及特典，不接触生产媒体。"""
    root = tmp_path / "library"
    season = root / "Series" / "Season 0"
    season.mkdir(parents=True)
    (season.parent / "tvshow.nfo").write_text('<tvshow><uniqueid type="tmdb">56353</uniqueid></tvshow>')
    path = season / "S00E02.nfo"
    path.write_bytes(nfo())
    path.chmod(0o640)
    return root, path


def runner_for(client, stopped=None):
    """构造存量修复器。"""
    return RepairRunner(NfoEnricher(client), stopped or Event(), RLock())


def test_preview_shows_before_and_proposed_after_without_writing(client, tmp_path, library, monkeypatch):
    """预览同时展示已有值、零值、缺失值与拟新增值。"""
    root, path = library
    path.write_bytes(nfo("<displayseason>0</displayseason><airsbefore_episode></airsbefore_episode>"))
    original = path.read_bytes()
    files = set(tmp_path.rglob("*"))
    debug = MagicMock()
    monkeypatch.setattr(repair_module.logger, "debug", debug)
    report = runner_for(client).run([str(root)])
    assert report["counts"] == {"preview": 1}
    record = report["records"][0]
    assert record["before"] == {"airsafter_season": None, "airsbefore_season": "0", "airsbefore_episode": ""}
    assert record["after"] == {"airsafter_season": "1", "airsbefore_season": None, "airsbefore_episode": None}
    assert record["tvdb_episode_id"] == 3250591
    assert path.read_bytes() == original
    assert set(tmp_path.rglob("*")) == files
    debug.assert_not_called()


def test_manual_positions_preview_and_repair_use_only_local_values(client, library):
    """存量预览和修复会清除省略项，包括已有的 Jellyfin 别名。"""
    root, path = library
    original = nfo("<airsbefore_season>2</airsbefore_season><displayseason>2</displayseason><displayepisode>6</displayepisode>", identity=1174618)
    path.write_bytes(original)
    client.configured = False
    overrides = parse_overrides("1174618,airsafter_season=1")
    runner = RepairRunner(NfoEnricher(client, overrides), Event(), RLock())

    preview = runner.run([str(root)])["records"][0]
    assert preview["status"] == "preview"
    assert preview["before"] == {"airsafter_season": None, "airsbefore_season": "2", "airsbefore_episode": "6"}
    assert preview["after"] == {"airsafter_season": "1", "airsbefore_season": None, "airsbefore_episode": None}
    assert preview["mapping_source"] == "手动修正"
    assert preview["tmdb_episode_id"] == 1174618
    assert preview["tvdb_episode_id"] is None
    assert path.read_bytes() == original
    updated = runner.run([str(root)], dry_run=False)["records"][0]
    assert updated["status"] == "updated" and updated["after"] == preview["after"]
    fields = tags(path.read_bytes())
    assert {"airsbefore_season", "displayseason", "displayepisode"}.isdisjoint(fields)
    assert fields["airsafter_season"] == "1"
    assert runner.run([str(root)], dry_run=False)["counts"] == {"skipped": 1}
    assert client.mock_calls == []


@pytest.mark.parametrize("has_tvshow", [True, False])
def test_scan_reports_configured_tvdb_id_without_lookup(client, library, has_tvshow):
    """缺密钥或缺少剧集文件时，仍显示手动指定的单集 ID。"""
    root, path = library
    client.configured = False
    if not has_tvshow:
        (path.parent.parent / "tvshow.nfo").unlink()
    path.write_bytes(nfo("<airsafter_season>1</airsafter_season><airsbefore_season>2</airsbefore_season><airsbefore_episode>3</airsbefore_episode>"))
    overrides = parse_overrides("938553,tvdb=8636540")
    record = RepairRunner(NfoEnricher(client, overrides), Event(), RLock()).run([str(root)])["records"][0]

    assert record["status"] == "skipped"
    assert record["tmdb_episode_id"] == 938553
    assert record["tvdb_episode_id"] == 8636540
    assert client.mock_calls == []


def test_ignore_preserves_episode_and_skips_external_queries(client, library):
    """忽略规则让存量扫描保留原始 NFO。"""
    root, path = library
    original = nfo("<airsbefore_season>2</airsbefore_season><displayepisode>6</displayepisode>", identity=1174618)
    path.write_bytes(original)
    overrides = parse_overrides("1174618,ignore")
    runner = RepairRunner(NfoEnricher(client, overrides), Event(), RLock())

    report = runner.run([str(root)], dry_run=False)
    assert report["counts"] == {"skipped": 1}
    record = report["records"][0]
    assert record["reason"] == "已按手动规则忽略"
    assert record["before"] == record["after"]
    assert record["tmdb_episode_id"] == 1174618
    assert path.read_bytes() == original
    assert client.mock_calls == []


def test_apply_logs_changes_preserves_permissions_and_creates_no_extra_files(client, tmp_path, library, monkeypatch):
    """只更新目标文件；实际修改才生成变更日志。"""
    root, path = library
    files = set(tmp_path.rglob("*"))
    debug = MagicMock()
    monkeypatch.setattr(repair_module.logger, "debug", debug)
    runner = runner_for(client)
    report = runner.run([str(root), str(root)], dry_run=False)
    assert report["counts"] == {"updated": 1}
    assert report["records"][0]["after"]["airsafter_season"] == "1"
    debug.assert_called_once()
    assert str(path) in debug.call_args.args[0]
    assert "airsafter_season：未设置 → 1" in debug.call_args.args[0]
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert tags(path.read_bytes())["airsafter_season"] == "1"
    report = runner.run([str(root)], dry_run=False)
    assert report["counts"] == {"skipped": 1}
    assert report["records"][0]["before"] == report["records"][0]["after"]
    assert set(tmp_path.rglob("*")) == files
    debug.assert_called_once()


@pytest.mark.skipif(not hasattr(os, "fchown"), reason="当前平台不支持设置文件属主")
def test_atomic_write_preserves_mode_when_fchown_is_denied(library, monkeypatch):
    """属主设置被拒绝时，仍通过同一个文件描述符保留权限并完成写入。"""
    _, path = library
    original = path.stat()
    expected = SimpleNamespace(st_uid=original.st_uid + 1, st_gid=original.st_gid, st_mode=original.st_mode)
    fchown = MagicMock(side_effect=PermissionError)
    fchmod = MagicMock(wraps=os.fchmod)
    monkeypatch.setattr(os, "fchown", fchown)
    monkeypatch.setattr(os, "fchmod", fchmod)

    repair_module.atomic_write(path, b"updated NFO", expected)

    descriptor = fchown.call_args.args[0]
    fchown.assert_called_once_with(descriptor, expected.st_uid, expected.st_gid)
    fchmod.assert_called_once_with(descriptor, 0o640)
    assert path.read_bytes() == b"updated NFO"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_concurrent_file_change_is_not_overwritten(client, library):
    """查询期间其他进程更新的 NFO 不被覆盖。"""
    root, path = library
    def mutate(*args):
        """模拟网络查询期间媒体服务器更新文件。"""
        path.write_bytes(b"changed externally")
        return {"id": 3250591, "seriesId": 194961, "airsAfterSeason": 1}
    client.episode.side_effect = mutate
    report = runner_for(client).run([str(root)], dry_run=False)
    assert report["counts"] == {"skipped": 1}
    assert report["records"][0]["before"] == report["records"][0]["after"]
    assert path.read_bytes() == b"changed externally"


def test_stop_during_query_prevents_next_write(client, library):
    """停用信号在查询返回之后仍阻止媒体写入。"""
    root, path = library
    original = path.read_bytes()
    stopped = Event()
    def stop(*args):
        """模拟网络请求期间停用插件。"""
        stopped.set()
        return {"id": 3250591, "seriesId": 194961, "airsAfterSeason": 1}
    client.episode.side_effect = stop
    report = runner_for(client, stopped).run([str(root)], dry_run=False)
    assert path.read_bytes() == original
    assert report["counts"] == {"skipped": 1}
    assert report["status"] == "cancelled"


def test_symlinks_and_missing_show_are_not_written(client, tmp_path, library):
    """不沿符号链接扫描或使用扫描范围之外的剧集身份。"""
    root, path = library
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.nfo").write_bytes(nfo())
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (path.parent / "linked.nfo").symlink_to(outside / "outside.nfo")
    report = runner_for(client).run([str(path.parent)], dry_run=False)
    assert report["counts"] == {"skipped": 1}
    assert "tvshow.nfo" in report["records"][0]["reason"]
    assert report["records"][0]["tmdb_episode_id"] == 938553
    client.episode.assert_not_called()


@pytest.fixture
def plugin(monkeypatch):
    """构造插件实例并隔离宿主调度与配置。"""
    monkeypatch.setattr(plugin_module.scheduler, "remove_plugin_once_job", MagicMock())
    monkeypatch.setattr(plugin_module.scheduler, "add_plugin_once_job", MagicMock(return_value=True))
    value = SpecialEpisodeOrder()
    monkeypatch.setattr(value, "update_config", MagicMock())
    monkeypatch.setattr(value, "save_data", MagicMock())
    monkeypatch.setattr(value, "get_data", MagicMock(return_value=None))
    monkeypatch.setattr(value, "del_data", MagicMock())
    return value


def test_one_shot_reset_reinit_and_stop(plugin):
    """请求只调度一次，保存后复位；重载取消旧代际，停用取消待执行任务。"""
    plugin.init_plugin({"enabled": True, "paths": "/library", "onlyonce": True})
    plugin_module.scheduler.add_plugin_once_job.assert_called_once()
    saved = plugin.update_config.call_args.args[0]
    assert saved["onlyonce"] is False
    old = plugin._stopped
    plugin.init_plugin(saved)
    assert old.is_set()
    plugin_module.scheduler.add_plugin_once_job.assert_called_once()
    plugin.stop_service()
    assert plugin._stopped.is_set()
    assert not plugin.get_state()


def test_invalid_mapping_disables_plugin(plugin):
    """配置错误不能沿用旧引擎继续写入。"""
    plugin.init_plugin({"enabled": True, "overrides": "invalid", "onlyonce": True})
    assert not plugin.get_state()
    plugin_module.scheduler.add_plugin_once_job.assert_not_called()
    assert plugin._config_error
    assert plugin.get_page()


def media(**overrides):
    """提供插件需要的最小媒体上下文。"""
    return SimpleNamespace(**{"type": MediaType.TV, "tmdb_id": 56353, "episode_group": None, "scrape_source": "themoviedb", **overrides})


@pytest.mark.parametrize("info,season,episode", [
    (media(), 1, 2), (media(), 0, None), (media(), False, 2),
    (media(episode_group="custom"), 0, 2), (media(scrape_source="douban"), 0, 2),
    (media(type=MediaType.MOVIE), 0, 2), (media(tmdb_id=None), 0, 2),
])
def test_non_target_scrapes_do_not_intercept(plugin, client, monkeypatch, info, season, episode):
    """普通剧集、电影、剧集组与其他来源不额外生成 NFO 或查询网络。"""
    plugin.init_plugin({"enabled": True})
    plugin._engine = NfoEnricher(client)
    manager = MagicMock()
    monkeypatch.setattr(plugin_module, "ModuleManager", manager)
    assert plugin.metadata_nfo(None, info, season, episode) is None
    manager.assert_not_called()
    client.episode_ids.assert_not_called()


def test_auto_nfo_uses_system_module_without_recursive_dispatch(plugin, client, monkeypatch):
    """通过模块目录调用基础生成器，对外提供当前宿主合同要求的文本。"""
    plugin.init_plugin({"enabled": True})
    plugin._engine = NfoEnricher(client)
    module = MagicMock()
    module.metadata_nfo.return_value = nfo()
    manager = MagicMock()
    manager.get_running_modules.return_value = [module]
    monkeypatch.setattr(plugin_module, "ModuleManager", lambda: manager)
    debug = MagicMock()
    monkeypatch.setattr(plugin_module.logger, "debug", debug)
    result = plugin.metadata_nfo(None, media(), 0, 2)
    assert isinstance(result, str)
    assert tags(result)["airsafter_season"] == "1"
    module.metadata_nfo.assert_called_once()
    assert "S00E02" in debug.call_args.args[0]
    assert "airsafter_season：未设置 → 1" in debug.call_args.args[0]


def test_auto_nfo_applies_direct_position_without_api_keys(plugin, monkeypatch):
    """基础刮削 NFO 可直接应用手动位置，插件无需访问 API。"""
    monkeypatch.setattr(MetadataClient, "configured", False)
    plugin.init_plugin({"enabled": True, "overrides": "938553,airsafter_season=1"})
    module = MagicMock()
    module.metadata_nfo.return_value = nfo()
    manager = MagicMock()
    manager.get_running_modules.return_value = [module]
    monkeypatch.setattr(plugin_module, "ModuleManager", lambda: manager)
    network = MagicMock(side_effect=AssertionError("直接指定位置无需访问 API"))
    monkeypatch.setattr(plugin._engine.client, "_http", network)

    result = plugin.metadata_nfo(None, media(), 0, 2)
    assert tags(result)["airsafter_season"] == "1"
    network.assert_not_called()


def test_client_cache_and_token_refresh(monkeypatch):
    """缓存命中不重复请求；TVDB 401 仅重新登录一次。"""
    def response(code=200, data=None):
        """创建不会接触网络的 HTTP 响应替身。"""
        return SimpleNamespace(status_code=code, json=lambda: data)
    http = MagicMock()
    http.post_res.side_effect = [response(data={"data": {"token": "first"}}), response(data={"data": {"token": "second"}})]
    http.get_res.side_effect = [response(401), response(data={"data": {"id": 123}})]
    client = MetadataClient()
    monkeypatch.setattr(client, "_http", lambda *args: http)
    assert client.episode(123) == {"id": 123}
    assert client.episode(123) == {"id": 123}
    assert http.post_res.call_count == 2
    assert http.get_res.call_count == 2


def test_tmdb_404_and_failure_cache_policy(monkeypatch):
    """短期缓存 TMDb 的 404，临时故障会在后续查询重试。"""
    client = MetadataClient()
    http = MagicMock()
    http.get_res.side_effect = [
        SimpleNamespace(status_code=404),
        SimpleNamespace(status_code=503),
        SimpleNamespace(status_code=200, json=lambda: {"id": 938554, "tvdb_id": 8636541}),
    ]
    monkeypatch.setattr(client, "_http", lambda *args: http)
    assert client.episode_ids(56353, 2) == {}
    assert client.episode_ids(56353, 2) == {}
    with pytest.raises(LookupFailure, match="503"):
        client.episode_ids(56353, 3)
    assert client.episode_ids(56353, 3) == {"id": 938554, "tvdb_id": 8636541}
    assert http.get_res.call_count == 3


def test_tvdb_404_evicts_old_tmdb_mapping_and_retries_on_next_run(monkeypatch):
    """从 3.0.0 的持久缓存读取失效 ID 后，下一轮可直接取得修正映射。"""
    MetadataClient.clear_temporary_cache()
    monkeypatch.setattr(MetadataClient, "configured", True)
    monkeypatch.setattr(client_module.settings, "TMDB_API_DOMAIN", "api.themoviedb.org")
    episode_key = "tmdb:api.themoviedb.org:tv/56353/season/0/episode/2/external_ids"
    series_key = "tmdb:api.themoviedb.org:tv/56353/external_ids"
    cache_key = client_module.METADATA_CACHE_KEY
    old_ids = {"id": 938553, "tvdb_id": 3250591}
    new_ids = {"id": 938553, "tvdb_id": 8636540}
    stored = {cache_key: {episode_key: old_ids, series_key: {"tvdb_id": 194961}}}
    http = MagicMock()
    http.post_res.return_value = SimpleNamespace(status_code=200, json=lambda: {"data": {"token": "example"}})
    http.get_res.side_effect = [
        SimpleNamespace(status_code=404),
        SimpleNamespace(status_code=200, json=lambda: old_ids),
        SimpleNamespace(status_code=404),
        SimpleNamespace(status_code=200, json=lambda: new_ids),
        SimpleNamespace(status_code=200, json=lambda: {
            "data": {"id": 8636540, "seriesId": 194961, "airsAfterSeason": 1}
        }),
    ]
    monkeypatch.setattr(MetadataClient, "_http", staticmethod(lambda *args: http))
    client = MetadataClient(stored.get, stored.__setitem__)
    engine = NfoEnricher(client)
    for _ in range(2):
        result = engine.enrich(nfo(), 56353, 2)
        assert result.status == "needs_correction" and "404" in result.reason
        client.flush_cache()
        assert stored[cache_key] == {series_key: {"tvdb_id": 194961}}

    client = MetadataClient(stored.get, stored.__setitem__)
    result = NfoEnricher(client).enrich(nfo(), 56353, 2)
    assert result.status == "updated" and result.tvdb_episode_id == 8636540
    assert tags(result.content)["airsafter_season"] == "1"
    client.flush_cache()
    assert stored[cache_key][episode_key] == new_ids
    assert http.get_res.call_count == 5


def test_tvdb_404_for_manual_override_preserves_tmdb_mapping(client):
    """手动指定的 TVDB ID 失效时保留独立的 TMDb 自动映射。"""
    client.episode.side_effect = TvdbEpisodeNotFound("TVDB 单集不存在（404）")
    result = NfoEnricher(client, parse_overrides("938553,tvdb=8636540")).enrich(nfo(), 56353, 2)
    assert result.status == "needs_correction" and "404" in result.reason
    client.episode.assert_called_once_with(8636540)
    client.invalidate_episode_mapping.assert_not_called()


def test_metadata_cache_survives_recreation_without_memory_cache(monkeypatch):
    """模拟插件存储读写，新客户端可在进程缓存清除后复用有效元数据。"""
    stored = {}
    http = MagicMock()
    http.post_res.return_value = SimpleNamespace(status_code=200, json=lambda: {"data": {"token": "example"}})
    http.get_res.side_effect = [
        SimpleNamespace(status_code=200, json=lambda: {"id": 10, "tvdb_id": 20}),
        SimpleNamespace(status_code=200, json=lambda: {"tvdb_id": 30}),
        SimpleNamespace(status_code=200, json=lambda: {
            "data": {"id": 20, "seriesId": 30, "airsAfterSeason": 1, "overview": "不需要缓存的简介"}
        }),
    ]
    first = MetadataClient(stored.get, stored.__setitem__)
    monkeypatch.setattr(first, "_http", lambda *args: http)
    first.episode_ids(1, 2)
    first.series_ids(1)
    first.episode(20)
    assert http.get_res.call_count == 3
    first.flush_cache()
    assert len(stored[client_module.METADATA_CACHE_KEY]) == 3

    MetadataClient.clear_temporary_cache()
    second = MetadataClient(stored.get, stored.__setitem__)
    no_network = MagicMock(side_effect=AssertionError("缓存命中时不得发送请求"))
    monkeypatch.setattr(second, "_http", no_network)
    assert second.episode_ids(1, 2) == {"id": 10, "tvdb_id": 20}
    assert second.series_ids(1) == {"tvdb_id": 30}
    assert second.episode(20) == {"id": 20, "seriesId": 30, "airsAfterSeason": 1}
    no_network.assert_not_called()


def test_incomplete_results_are_not_saved_to_plugin_storage(monkeypatch):
    """缺少外部 ID 或有效位置的响应只进入短期缓存。"""
    monkeypatch.setattr(client_module, "TEMPORARY_CACHE_REGION", "specialepisodeorder.test.incomplete")
    save = MagicMock()
    http = MagicMock()
    http.post_res.return_value = SimpleNamespace(status_code=200, json=lambda: {"data": {"token": "example"}})
    http.get_res.side_effect = [
        SimpleNamespace(status_code=200, json=lambda: {"id": 10, "tvdb_id": None}),
        SimpleNamespace(status_code=200, json=lambda: {
            "data": {"id": 20, "seriesId": 30, "airsAfterSeason": None}
        }),
    ]
    client = MetadataClient(save_data=save)
    monkeypatch.setattr(client, "_http", lambda *args: http)
    assert client.episode_ids(1, 2) == {"id": 10}
    assert client.episode(20)["airsAfterSeason"] is None
    client.flush_cache()
    save.assert_not_called()


def test_clear_cache_resets_flag_and_prevents_old_client_writes(plugin, monkeypatch):
    """清空按单独存储键执行，旧客户端无法在重载后覆盖结果。"""
    plugin.init_plugin({"enabled": True})
    old_client = plugin._engine.client
    http = MagicMock()
    http.get_res.return_value = SimpleNamespace(status_code=200, json=lambda: {"tvdb_id": 30})
    monkeypatch.setattr(old_client, "_http", lambda *args: http)
    old_client.series_ids(1)
    temporary = MagicMock()
    local_files = MagicMock()
    monkeypatch.setattr(MetadataClient, "clear_temporary_cache", temporary)
    monkeypatch.setattr(RepairRunner, "clear_file_cache", local_files)
    plugin.init_plugin({
        "enabled": True, "paths": "/library", "onlyonce": True, "clear_cache": True,
        "overrides": "10=20",
    })
    plugin.del_data.assert_called_once_with(client_module.METADATA_CACHE_KEY)
    temporary.assert_called_once()
    local_files.assert_called_once()
    saved = plugin.update_config.call_args.args[0]
    assert saved["clear_cache"] is False and saved["onlyonce"] is False
    assert saved["overrides"] == "10=20"
    plugin_module.scheduler.add_plugin_once_job.assert_called_once()
    old_client.flush_cache()
    plugin.save_data.assert_not_called()
    assert plugin._cache_cleared


def test_failed_cache_clear_does_not_run_scan(plugin):
    """清理失败显示原因，不执行要求在清缓存后启动的任务。"""
    plugin.del_data.side_effect = RuntimeError("storage unavailable")
    plugin.init_plugin({"enabled": True, "paths": "/library", "onlyonce": True, "clear_cache": True})
    assert "清空缓存失败" in plugin._config_error
    assert not plugin._cache_cleared
    plugin_module.scheduler.add_plugin_once_job.assert_not_called()


def test_http_uses_host_proxy_timeout_and_tls(monkeypatch):
    """所有外部请求继承宿主网络配置并启用 TLS 验证。"""
    factory = MagicMock()
    monkeypatch.setattr(client_module, "RequestUtils", factory)
    MetadataClient._http()
    assert factory.call_args.kwargs["timeout"] == 10
    assert factory.call_args.kwargs["verify"] is True
    assert factory.call_args.kwargs["content_type"] == "application/json"
    assert "proxies" in factory.call_args.kwargs


def page_nodes(nodes):
    """遍历宿主递归渲染器消费的节点，不解释文本为 HTML。"""
    for node in nodes:
        yield node
        yield from page_nodes(node.get("content", []))


def test_report_page_formats_summary_and_field_diff_as_renderable_text(plugin, monkeypatch):
    """24 条记录有可渲染的行，状态与原因同列，缺失、零值和改动可区分。"""
    paths = [f'/library/作品/Season 0/特典 {index:02d}.nfo' for index in range(24)]
    paths[0] = '/library/<img src=x onerror=alert(1)>.nfo'
    records = [
        {
            "path": path,
            "status": "preview",
            "reason": "可补全缺失的播放位置",
            "mapping_source": "TMDb",
            "tmdb_episode_id": 938553,
            "tvdb_episode_id": 8636540,
            "before": {"airsafter_season": None, "airsbefore_season": "0", "airsbefore_episode": ""},
            "after": {"airsafter_season": "2", "airsbefore_season": "0", "airsbefore_episode": ""},
        }
        for path in paths
    ]
    records[-1].update(status="needs_correction", reason="TMDb 未提供 TVDB 单集映射", mapping_source="", tvdb_episode_id=None)
    monkeypatch.setattr(plugin_module.settings, "TZ", "Asia/Shanghai")
    plugin._last_report = {
        "dry_run": True,
        "status": "completed",
        "counts": {"preview": 23, "needs_correction": 1},
        "records": records,
        "finished_at": datetime(2026, 11, 19, 8, 30, 45, tzinfo=timezone.utc),
    }
    nodes = list(page_nodes(plugin.get_page()))
    texts = [node.get("text") for node in nodes]
    assert all(f"{directory}/" in texts and filename in texts for directory, filename in map(split, paths))
    assert [node["text"] for node in nodes if node["component"] == "th"] == ["文件", "结果", "映射", "播放位置"]
    assert {"airsafter_season", "airsbefore_season", "airsbefore_episode", "0", "空值"}.issubset(texts)
    assert "预览完成 · 待更新 23 项 · 待修正 1 项" in texts
    assert any(node.get("text") == "待修正" and node["props"]["class"] == "text-warning" for node in nodes)
    assert "扫描结束于 2026-11-19 16:30:45+08:00" in texts
    first_row = next(node for node in nodes if node["component"] == "tr" and node["content"][0]["component"] == "td")
    dir_line, file_line = first_row["content"][0]["content"]
    assert dir_line["text"] == "/library/"
    assert file_line["text"] == "<img src=x onerror=alert(1)>.nfo"
    assert [node["text"] for node in first_row["content"][1]["content"]] == ["待更新", "可补全缺失的播放位置"]
    assert first_row["content"][1]["content"][1]["props"]["class"] == "text-caption"
    source_line, tmdb_line, tvdb_line = first_row["content"][2]["content"]
    assert source_line == {"component": "strong", "text": "TMDb"}
    for line, label, episode_id in ((tmdb_line, "TMDb ", "938553"), (tvdb_line, "TVDB ", "8636540")):
        assert line["props"]["class"] == "text-caption"
        assert [node["text"] for node in line["content"]] == [label, episode_id]
        assert "user-select: all" in line["content"][1]["props"]["style"]
    result_rows = [node for node in nodes if node["component"] == "tr" and node["content"][0]["component"] == "td"]
    assert len(result_rows[-1]["content"][2]["content"]) == 2
    changed, unchanged_zero, unchanged_empty = [line["content"][1] for line in first_row["content"][3]["content"]]
    assert [(mark["component"], mark["text"]) for mark in changed["content"]] == [("del", "未设置"), ("ins", "2")]
    assert "--v-theme-error" in changed["content"][0]["props"]["style"]
    assert "--v-theme-success" in changed["content"][1]["props"]["style"]
    assert unchanged_zero == {"component": "span", "text": "0"}
    assert unchanged_empty == {"component": "span", "text": "空值"}
    assert sum(node.get("component") == "tr" for node in nodes) == 25
    assert not any(node.get("html") for node in nodes)


def test_report_page_explains_empty_scan(plugin):
    """已完成但无条目的扫描应显示明确提示。"""
    plugin._last_report = {
        "dry_run": True,
        "status": "completed",
        "counts": {},
        "records": [],
        "finished_at": datetime.now(timezone.utc),
    }
    texts = [node.get("text", "") for node in page_nodes(plugin.get_page())]
    assert "本次扫描未找到符合条件的特典 NFO。" in texts


def test_scan_results_are_only_kept_in_current_instance(plugin, client, library):
    """调度任务结束后可查看本次结果，且不读取或写入持久化报告。"""
    root, _ = library
    plugin.init_plugin({"enabled": True})
    runner = RepairRunner(NfoEnricher(client), plugin._stopped, plugin._write_lock)
    plugin._run_repair(runner, [str(root)], True)
    assert plugin._last_report["counts"] == {"preview": 1}
    assert plugin._last_report["finished_at"].tzinfo is timezone.utc
    assert plugin.get_page()
    plugin.save_data.assert_not_called()
    plugin.get_data.assert_not_called()
    assert SpecialEpisodeOrder()._last_report is None


def test_over_one_thousand_scan_records_reach_the_result_table(plugin, client, library, monkeypatch):
    """超过原上限的真实扫描明细仍可从最终表格访问。"""
    root, first_file = library
    for index in range(1000):
        (first_file.parent / f"特典 {index:04d}.nfo").write_bytes(nfo())
    plugin.init_plugin({"enabled": True})
    runner = RepairRunner(NfoEnricher(client), plugin._stopped, plugin._write_lock)
    lookup = MagicMock(wraps=runner._show_id)
    monkeypatch.setattr(runner, "_show_id", lookup)
    plugin._run_repair(runner, [str(root)], True)
    assert plugin._last_report["counts"] == {"preview": 1001}
    lookup.assert_called_once()
    body = next(node for node in page_nodes(plugin.get_page()) if node["component"] == "tbody")
    assert len(body["content"]) == 1001
    assert body["content"][-1]["content"][0]["content"][-1]["text"] == "特典 0999.nfo"


def test_repeated_scan_skips_unchanged_non_special_nfo_and_reads_changed_file(client, library, monkeypatch):
    """普通集的识别结果跨扫描复用，文件改为特典时重新读取。"""
    root, first_file = library
    candidate = first_file.parent / "later-special.nfo"
    candidate.write_bytes(nfo().replace(b"<season>0</season>", b"<season>1</season>"))
    real_read = Path.read_bytes
    candidate_reads = []

    def track_reads(path):
        if path == candidate:
            candidate_reads.append(path)
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", track_reads)
    assert runner_for(client).run([str(root)])["counts"] == {"preview": 1}
    assert runner_for(client).run([str(root)])["counts"] == {"preview": 1}
    assert candidate_reads == [candidate]
    original_stat = candidate.stat()
    candidate.write_bytes(nfo())
    os.utime(candidate, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 2_000_000_000))
    assert runner_for(client).run([str(root)])["counts"] == {"preview": 2}
    assert candidate_reads == [candidate, candidate]
