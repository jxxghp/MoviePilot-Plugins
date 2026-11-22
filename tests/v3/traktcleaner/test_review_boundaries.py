"""清理操作的媒体匹配、下载器隔离与 HTTP 参数回归。"""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.plugins.traktcleaner import TraktCleaner, verify_token
from app.schemas import TokenPayload
from app.schemas.types import MediaType


def test_different_year_and_partial_title_do_not_match(plugin, monkeypatch):
    """同名翻拍作品或名称只含另一作品的子串都不得触发删除。"""
    import app.plugins.traktcleaner as module

    monkeypatch.setattr(module, "MetaInfo", lambda _: SimpleNamespace(
        cn_name="", en_name="Example", name="Example", year="2026", type=MediaType.MOVIE))
    match = plugin._TraktCleaner__match_torrent
    assert match("Example.2026.1080p", {"example|1999|movie": {"type": "movie", "year": "1999"}}) is None
    assert match("Example.2026.1080p", {"example extended|2026|movie": {"type": "movie", "year": "2026"}}) is None
    assert match("Example.2026.1080p", {"example|2026|show": {"type": "show", "year": "2026"}}) is None


def test_ambiguous_title_without_year_is_skipped(plugin, monkeypatch):
    """没有年份且有多条同名观看记录时不选取第一条。"""
    import app.plugins.traktcleaner as module

    monkeypatch.setattr(module, "MetaInfo", lambda _: SimpleNamespace(
        cn_name="", en_name="Example", name="Example", year=None, type=MediaType.MOVIE))
    watched = {f"example|{year}|movie": {"type": "movie", "year": str(year)} for year in (1999, 2026)}
    assert plugin._TraktCleaner__match_torrent("Example", watched) is None


def test_episode_files_and_delete_target_the_same_downloader(plugin):
    """文件校验和删除必须指定任务所在下载器，失败不能记为成功。"""
    plugin.chain = Mock()
    plugin._enabled = True
    plugin.chain.torrent_files.return_value = []
    plugin._TraktCleaner__get_torrent_episodes("hash", 1, "secondary")
    plugin.chain.torrent_files.assert_called_once_with(tid="hash", downloader="secondary")
    plugin.chain.remove_torrents.return_value = False
    info = {}
    torrent = SimpleNamespace(hash="hash", title="Example", downloader="secondary")
    assert plugin._TraktCleaner__remove_torrent(torrent, info, {}, "", "watched") is False
    plugin.chain.remove_torrents.assert_called_once_with(hashs="hash", delete_file=True, downloader="secondary")
    assert info["error"]


def test_json_buttons_accept_body_and_return_host_envelope(plugin):
    """详情页 POST 的 JSON 参数可被 FastAPI 接收，响应满足宿主三段式协议。"""
    plugin._enabled = True
    plugin.chain = Mock()
    plugin.chain.remove_torrents.return_value = False
    state = {"pending": {"secondary:hash": {"torrent_hash": "hash", "downloader": "secondary"}}}
    plugin.get_data = lambda key: copy.deepcopy(state.get(key))

    def save(key, value):
        """保存隔离的插件数据快照。"""
        state[key] = copy.deepcopy(value)

    plugin.save_data = save
    app = FastAPI()
    app.dependency_overrides[verify_token] = lambda: TokenPayload(super_user=True)
    for declaration in plugin.get_api():
        route = dict(declaration)
        assert route.pop("auth") == "bear"
        app.add_api_route(**route)
    with TestClient(app) as client:
        response = client.post("/clean_now", json={"torrent_hash": "secondary:hash"})
        assert response.status_code == 200
        assert response.json() == {"success": False, "message": "删除种子失败（下载器返回失败）", "data": None}
        assert "secondary:hash" in state["pending"]
        plugin.chain.remove_torrents.return_value = True
        assert client.post("/clean_now", json={"torrent_hash": "secondary:hash"}).json()["success"] is True
        assert state["pending"] == {}
        assert client.get("/clean_now").status_code == 405
    assert all(call.kwargs["downloader"] == "secondary" for call in plugin.chain.remove_torrents.call_args_list)


def test_nonadministrator_cannot_invoke_cleanup_or_clear_seen(plugin):
    """普通登录用户不能删除下载任务、修改队列或读取管理员授权入口。"""
    plugin._enabled = True
    plugin.chain = Mock()
    app = FastAPI()
    app.dependency_overrides[verify_token] = lambda: TokenPayload(super_user=False)
    for declaration in plugin.get_api():
        route = dict(declaration)
        route.pop("auth")
        app.add_api_route(**route)
    with TestClient(app) as client:
        assert client.post("/clean_now", json={"torrent_hash": "secondary:hash"}).status_code == 403
        assert client.post("/clear_seen", json={"torrent_hash": "secondary:hash"}).status_code == 403
        assert client.get("/authorize_url").status_code == 403
    plugin.chain.remove_torrents.assert_not_called()
    plugin.save_data.assert_not_called()


def test_legacy_pending_cannot_delete_without_downloader(plugin):
    """旧队列缺少下载器时保留条目，等待重新扫描建立来源。"""
    from app.plugins.traktcleaner import TraktTorrentAction

    plugin._enabled = True
    plugin.chain = Mock()
    plugin.get_data.return_value = {"hash": {"torrent_hash": "hash"}}
    result = plugin._TraktCleaner__clean_now_api(TraktTorrentAction(torrent_hash="hash"))
    assert result.success is False
    plugin.chain.remove_torrents.assert_not_called()


def test_repeated_unauthorized_response_only_refreshes_once(plugin, monkeypatch):
    """令牌刷新后仍返回 401 时结束分页，避免无限刷新。"""
    import app.plugins.traktcleaner as module

    request = Mock(return_value=SimpleNamespace(status_code=401))
    refresh = Mock(return_value=True)
    monkeypatch.setattr(module.requests, "get", request)
    monkeypatch.setattr(plugin, "_TraktCleaner__refresh_token", refresh)
    assert plugin._TraktCleaner__fetch_watched_movies() == []
    assert request.call_count == 2 and refresh.call_count == 1


def test_page_does_not_expose_host_api_key(plugin):
    """详情页动作使用用户登录态，页面数据不包含宿主 API 密钥。"""
    page = plugin._TraktCleaner__build_pending_section({"secondary:hash": {"first_seen": 123}})
    assert "apikey=" not in str(page)
