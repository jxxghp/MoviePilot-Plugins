"""BrushFlow 间接下载响应校验与候选退避回归测试。"""

import base64
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


class FakeResponse:
    """模拟间接换票和最终种子下载的 HTTP 响应。"""

    def __init__(self, content: bytes, payload: dict | None = None, ok: bool = True):
        self.content = content
        self.ok = ok
        self.status_code = 200 if ok else 502
        self._payload = payload

    def json(self) -> dict:
        """返回预先设置的 JSON 响应。"""
        if self._payload is None:
            raise ValueError("响应不是 JSON")
        return self._payload


def _make_plugin() -> tuple[BrushFlow, dict[str, object]]:
    """构造带任务数据替身的最小 BrushFlow 实例。"""
    task = BrushTaskConfig(
        {
            "id": "indirect-download-task",
            "name": "间接下载测试",
            "site_id": 1,
            "downloader": "qb",
        }
    )
    plugin = object.__new__(BrushFlow)
    plugin._task_configs = {task.id: task}
    plugin._task_context = threading.local()
    plugin._task_context.task_id = task.id
    data: dict[str, object] = {}
    plugin._get_task_data = lambda _task_id, name: data.get(name)
    plugin._save_task_data = lambda _task_id, name, value: data.__setitem__(name, value)
    return plugin, data


def _indirect_torrent() -> MagicMock:
    """构造包含稳定页面地址的间接下载候选。"""
    request = {
        "method": "get",
        "cookie": False,
        "result": "data",
    }
    encoded = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
    torrent = MagicMock()
    torrent.enclosure = f"[{encoded}]https://m-team.example/api/ticket"
    torrent.page_url = "https://m-team.example/detail/123"
    torrent.site = 1
    torrent.site_proxy = False
    torrent.site_cookie = None
    torrent.site_ua = "MoviePilot-Test"
    torrent.title = "测试间接种子"
    torrent.size = 1
    torrent.pubdate = "2026-11-08 00:00:00"
    return torrent


def _download_environment(plugin: BrushFlow, request: MagicMock, downloader: MagicMock):
    """装配 qBittorrent 下载器和间接请求替身。"""
    service = SimpleNamespace(instance=downloader)
    helper = MagicMock()
    helper.is_downloader.return_value = True
    return (
        patch.object(type(plugin), "service_info", new_callable=PropertyMock, return_value=service),
        patch("app.plugins.brushflow.DownloaderHelper", return_value=helper),
        patch("app.plugins.brushflow.RequestUtils", return_value=request),
    )


def test_invalid_indirect_response_is_rejected_and_backed_off() -> None:
    """HTTP 200 的站点错误 JSON 不得进入下载器，并且同一候选当天只请求一次。"""
    plugin, data = _make_plugin()
    torrent = _indirect_torrent()
    downloader = MagicMock()
    downloader.add_torrent.return_value = True
    resolver = FakeResponse(b"", {"data": "https://m-team.example/api/rss/dlv2?sign=token"})
    invalid = FakeResponse(
        '{"code":"1","data":null,"message":"相同種子當天最多下載10次"}'.encode(),
        {"code": "1", "data": None, "message": "相同種子當天最多下載10次"},
    )
    request = MagicMock()
    request.get_res.side_effect = [resolver, invalid]

    patches = _download_environment(plugin, request, downloader)
    with patch("app.plugins.brushflow.logger") as logger, patches[0], patches[1], patches[2]:
        assert plugin._BrushFlow__download(torrent) is None
        assert plugin._BrushFlow__download(torrent) is None

    assert request.get_res.call_count == 2
    downloader.add_torrent.assert_not_called()
    failure_rows = data["download_failures"]
    assert isinstance(failure_rows, dict) and len(failure_rows) == 1
    assert "相同種子當天最多下載10次" in str(logger.error.call_args)


def test_valid_indirect_torrent_is_forwarded_as_bytes() -> None:
    """合法 bencode 种子仍应正常传给 qBittorrent。"""
    plugin, data = _make_plugin()
    torrent = _indirect_torrent()
    downloader = MagicMock()
    downloader.add_torrent.return_value = True
    downloader.get_torrent_id_by_tag.return_value = "hash123"
    resolver = FakeResponse(b"", {"data": "https://m-team.example/api/rss/dlv2?sign=token"})
    valid_torrent = b"d4:infod4:name4:test6:lengthi1eee"
    request = MagicMock()
    request.get_res.side_effect = [resolver, FakeResponse(valid_torrent)]

    patches = _download_environment(plugin, request, downloader)
    with patches[0], patches[1], patches[2]:
        assert plugin._BrushFlow__download(torrent) == "hash123"

    assert request.get_res.call_count == 2
    assert data.get("download_failures") is None
    assert downloader.add_torrent.call_args.kwargs["content"] == valid_torrent
