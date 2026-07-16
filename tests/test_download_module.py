from pathlib import Path

import app.log
import p115offlinedownloader as plugin_module
from app.helper.downloader import DownloaderHelper
from p115offlinedownloader import P115OfflineDownloader
from p115offlinedownloader.schemas import (
    ConnectionResult,
    NormalizedDownload,
    SubmitResult,
)


HASH = "0123456789abcdef0123456789abcdef01234567"


class FakeClient:
    def __init__(self, submit=None, connection=None):
        self.submit = submit or SubmitResult(True, "任务已添加")
        self.connection = connection or ConnectionResult(True, "连接成功", {"enabled": True})
        self.magnet = None
        self.closed = False

    def add_offline_task(self, magnet):
        self.magnet = magnet
        return self.submit

    def test_connection(self):
        return self.connection

    def close(self):
        self.closed = True


def make_plugin(enabled=True):
    plugin = P115OfflineDownloader()
    plugin.init_plugin(
        {
            "enabled": enabled,
            "downloader_type": "p115offline",
            "api_token": "token",
        }
    )
    return plugin


def test_get_module_only_when_enabled():
    assert make_plugin(False).get_module() == {}
    assert make_plugin(True).get_module()["download"].__name__ == "download"


def test_non_target_and_missing_downloader_return_none():
    plugin = make_plugin()
    DownloaderHelper.registry = {"普通下载": "qbittorrent", "同名115": "qbittorrent"}
    args = ("magnet:?xt=urn:btih:" + HASH, Path("/media"), "cookie")
    assert plugin.download(*args, downloader=None) is None
    assert plugin.download(*args, downloader="普通下载") is None
    assert plugin.download(*args, downloader="同名115") is None


def test_target_success(monkeypatch):
    plugin = make_plugin()
    fake_client = FakeClient()
    plugin._client = fake_client
    DownloaderHelper.registry = {"115离线下载": "p115offline"}
    normalized = NormalizedDownload(
        magnet="magnet:?xt=urn:btih:" + HASH,
        info_hash=HASH,
        source_type="magnet",
    )
    monkeypatch.setattr(plugin_module, "normalize_download_content", lambda *args, **kwargs: normalized)

    result = plugin.download(
        "ignored",
        Path("/media115/inbox"),
        "site-cookie",
        downloader="115离线下载",
    )
    assert result == ("115离线下载", HASH, "Original", "任务已添加")
    assert fake_client.magnet == normalized.magnet


def test_target_input_failure_is_nonempty_and_does_not_submit(monkeypatch):
    plugin = make_plugin()
    fake_client = FakeClient()
    plugin._client = fake_client
    DownloaderHelper.registry = {"115离线下载": "p115offline"}
    monkeypatch.setattr(
        plugin_module,
        "normalize_download_content",
        lambda *args, **kwargs: NormalizedDownload(error="私有种子禁止提交"),
    )
    result = plugin.download("ignored", Path("/media"), "", downloader="115离线下载")
    assert result == ("115离线下载", None, None, "私有种子禁止提交")
    assert fake_client.magnet is None


def test_target_api_failure_never_returns_none(monkeypatch):
    plugin = make_plugin()
    plugin._client = FakeClient(submit=SubmitResult(False, "P115StrmHelper不可用"))
    DownloaderHelper.registry = {"115离线下载": "p115offline"}
    monkeypatch.setattr(
        plugin_module,
        "normalize_download_content",
        lambda *args, **kwargs: NormalizedDownload(
            magnet="magnet:?xt=urn:btih:" + HASH,
            info_hash=HASH,
            source_type="magnet",
        ),
    )
    result = plugin.download("ignored", Path("/media"), "", downloader="115离线下载")
    assert result == ("115离线下载", None, None, "P115StrmHelper不可用")


def test_episode_warning_and_no_sensitive_log(monkeypatch):
    plugin = make_plugin()
    plugin._client = FakeClient()
    DownloaderHelper.registry = {"115离线下载": "p115offline"}
    full_magnet = "magnet:?xt=urn:btih:" + HASH + "&tr=https://tracker/?token=secret"
    monkeypatch.setattr(
        plugin_module,
        "normalize_download_content",
        lambda *args, **kwargs: NormalizedDownload(
            magnet=full_magnet,
            info_hash=HASH,
            source_type="magnet",
        ),
    )
    app.log.logger.messages.clear()
    plugin.download(
        "ignored",
        Path("/media"),
        "secret-cookie",
        episodes={3},
        downloader="115离线下载",
    )
    rendered_logs = "\n".join(message for _, message in app.log.logger.messages)
    assert "不支持文件级精确选集" in rendered_logs
    assert full_magnet not in rendered_logs
    assert "secret-cookie" not in rendered_logs
    assert "token=secret" not in rendered_logs


def test_connection_api_and_stop_service():
    plugin = make_plugin()
    fake_client = FakeClient(connection=ConnectionResult(False, "未启用", {"enabled": False}))
    plugin._client = fake_client
    assert plugin.test_connection() == {
        "code": 1,
        "msg": "未启用",
        "data": {"enabled": False},
    }
    plugin.stop_service()
    assert fake_client.closed is True
    assert plugin._client is None


def test_form_and_api_contract():
    plugin = make_plugin()
    form, defaults = plugin.get_form()
    assert form
    assert defaults["downloader_type"] == "p115offline"
    assert defaults["allow_torrent_conversion"] is True
    assert plugin.get_api()[0]["path"] == "/test_connection"
    assert plugin.get_api()[0]["auth"] == "bear"
