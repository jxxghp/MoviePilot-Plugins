"""CrossSeed 插件的 FluxTorrent 站点适配测试。

FluxTorrent 走的是站点**原生开放 API**，与上游「pieces-hash」方言的
请求形状、凭据位置、响应结构都不一样：

| | 上游方言 | FluxTorrent |
|---|---|---|
| 查询 | ``POST {url}api/pieces-hash`` | ``POST {url}api/v1/crossseed/lookup`` |
| 凭据 | body 里的 ``passkey`` | 头 ``Authorization: Token <fxo_>`` |
| 请求体 | ``{passkey, pieces_hash:[...]}`` | ``{pieces_sha1:[...]}`` |
| 响应 | ``{"data":{sha1:torrent_id}}`` | ``{"data":{"results":[...]}}`` |
| 下载 | ``GET {url}download.php?id=&passkey=`` | ``GET {url}api/v1/crossseed/dl/{id}`` |

本文件锁住三件事：

1. **分派正确**：站点名精确为 ``FluxTorrent`` 时才走原生 API，其余站点
   （含上游对「憨憨」的特殊方言）逐字保持原行为。
2. **请求形状正确**：令牌只进请求头，不进 body；指纹字段名是
   ``pieces_sha1``。
3. **响应解析正确**：FluxTorrent 的 ``data`` 是 ``results`` 数组，不能套用
   上游的 ``data.items()``——那会把 ``"results"`` 当成指纹名，产出一条
   ``torrent_id="results"`` 的假命中。

站点侧不需要新增任何端点，用的就是它本来就有的
``/api/v1/crossseed/*`` 开放 API（需 ``crossseed`` scope）。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

from app.plugins.crossseed import (
    CSSiteConfig,
    CrossSeed,
    CrossSeedHelper,
    FLUX_SITE_NAMES,
    FLUX_TOKEN_PREFIX,
    TorInfo,
)

# 测试里代表 FluxTorrent 架构站点的站点名（白名单首项）
FLUX_SITE_NAME = FLUX_SITE_NAMES[0]


# 站点真实响应形状：data.results 数组，query 是回标的原指纹，
# match 是「命中的是哪一类」（info_hash_v1 / pieces_sha1），不是指纹值。
FLUX_OK_PAYLOAD = {
    "code": 0,
    "message": "ok",
    "data": {
        "results": [
            {
                "match": "pieces_sha1",
                "query": "db6aab38b13a6ae52542471a4a9fef2507973831",
                "torrent_id": 12345,
                "name": "Some.Release.2024.1080p",
                "size": 1024,
                "download_url": "/api/v1/crossseed/dl/12345",
            }
        ]
    },
}

# 上游方言响应：data 是「指纹 → 种子 id」的映射。
UPSTREAM_OK_PAYLOAD = {
    "data": {
        "db6aab38b13a6ae52542471a4a9fef2507973831": 12345,
    }
}


class _Response:
    """构造 requests.post 所需的最小响应对象。"""

    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode() if payload is not None else b""

    def json(self):
        """返回模拟 JSON 结果。"""
        return self._payload

    def raise_for_status(self):
        """非 2xx 时抛异常（与 requests 行为一致）。"""
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _flux_site(url="https://pt.example.com"):
    """构造 FluxTorrent 站点配置。

    ``query_gap=0`` 让查询路径不引入等待，测试跑得快且不依赖时钟。
    """
    return CSSiteConfig(
        name=FLUX_SITE_NAME,
        url=url,
        passkey="fxo_test_token",
        query_gap=0,
    )


def _upstream_site(url="https://pt.example.org/"):
    """构造一个上游方言站点配置。"""
    return CSSiteConfig(
        name="青蛙",
        url=url,
        passkey="upstream_passkey",
        query_gap=0,
    )


def _capture_post(monkeypatch, payload):
    """把 requests.post 换成记录调用参数的替身，返回记录容器。"""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, proxies=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        captured["timeout"] = timeout
        return _Response(payload)

    monkeypatch.setattr(
        "app.plugins.crossseed.requests.post",
        fake_post,
    )
    return captured


# ─── 分派：只有站点名精确匹配才走原生 API ───────────────────────────


def test_flux_site_uses_native_openapi_endpoints():
    """FluxTorrent 的查询口与下载口应是站点原生开放 API。"""
    site = _flux_site()

    assert site.get_api_url() == \
        "https://pt.example.com/api/v1/crossseed/lookup"
    assert site.get_torrent_url("12345") == \
        "https://pt.example.com/api/v1/crossseed/dl/12345"


def test_flux_url_tolerates_trailing_slash():
    """站点地址带尾斜杠时不能拼出双斜杠。"""
    site = _flux_site("https://pt.example.com/")

    assert site.get_api_url() == \
        "https://pt.example.com/api/v1/crossseed/lookup"
    assert site.get_torrent_url("1") == \
        "https://pt.example.com/api/v1/crossseed/dl/1"


def test_hxpt_site_name_is_recognised():
    """好学已由 NexusPHP 迁移到 FluxTorrent 架构，站点名命中白名单。

    两者对外契约完全一致（同一套 ``/api/v1/crossseed/*`` 开放 API），
    故走同一条适配路径。
    """
    site = CSSiteConfig(name="好学", url="https://www.hxpt.org", passkey="fxo_token")

    assert site.is_flux is True
    assert site.get_api_url() == "https://www.hxpt.org/api/v1/crossseed/lookup"
    assert site.get_torrent_url("9") == "https://www.hxpt.org/api/v1/crossseed/dl/9"


def test_fxo_credential_detects_flux_architecture():
    """自定义站点名任意填时，凭据形态仍能正确分派。

    MoviePilot 的自定义站点名可以随便填，只靠站点名会漏判；``fxo_`` 开放
    API 令牌只有 FluxTorrent 架构会签发，故凭据形态是可靠的第二判据。
    """
    site = CSSiteConfig(name="我的站", url="https://pt.example.com", passkey="fxo_abc")

    assert site.is_flux is True
    assert site.get_api_url() == "https://pt.example.com/api/v1/crossseed/lookup"
    assert site.get_torrent_url("1") == "https://pt.example.com/api/v1/crossseed/dl/1"


def test_flux_token_prefix_constant_matches_site_contract():
    """令牌前缀常量必须是站点实际签发的形态。"""
    assert FLUX_TOKEN_PREFIX == "fxo_"


def test_non_flux_site_with_non_flux_credential_stays_upstream():
    """非白名单站点名 + 非 fxo_ 凭据 ⇒ 不走 Flux 分派。"""
    site = CSSiteConfig(name="青蛙", url="https://pt.example.org/", passkey="np_passkey")

    assert site.is_flux is False
    assert site.get_api_url() == "https://pt.example.org/api/pieces-hash"


def test_flux_detection_requires_exact_site_name():
    """分派依据是站点名精确匹配，大小写敏感。"""
    assert _flux_site().is_flux is True
    assert CSSiteConfig(name="fluxtorrent").is_flux is False
    assert CSSiteConfig(name="FluxTorrent 2").is_flux is False
    assert CSSiteConfig(name="").is_flux is False


def test_other_sites_keep_upstream_dialect():
    """非 FluxTorrent 站点仍走上游方言，适配不得改坏它。"""
    site = _upstream_site()

    assert site.get_api_url() == "https://pt.example.org/api/pieces-hash"
    assert site.get_torrent_url("7") == \
        "https://pt.example.org/download.php?id=7&passkey=upstream_passkey"


def test_hanhhan_dialect_is_kept():
    """上游对「憨憨」的特殊方言也不能被改坏。"""
    site = CSSiteConfig(name="憨憨", url="https://han.example.org/")

    assert site.get_api_url() == \
        "https://han.example.org/nexusapi/pieces-hash"


# ─── 请求形状：凭据走头，指纹字段名不同 ────────────────────────────


def test_flux_lookup_sends_token_header_and_pieces_sha1(monkeypatch):
    """FluxTorrent 查询：令牌走 Authorization 头，body 只有 pieces_sha1。"""
    captured = _capture_post(monkeypatch, FLUX_OK_PAYLOAD)

    infos, err = CrossSeedHelper.get_target_torrent(_flux_site(), ["abc"])

    assert err is None
    assert captured["url"] == \
        "https://pt.example.com/api/v1/crossseed/lookup"
    assert captured["headers"]["Authorization"] == "Token fxo_test_token"
    assert captured["body"] == {"pieces_sha1": ["abc"]}
    assert "passkey" not in captured["body"]
    assert len(infos) == 1


def test_upstream_lookup_still_sends_passkey_in_body(monkeypatch):
    """上游方言的 body 仍带 passkey，且不出现 Authorization 头。"""
    captured = _capture_post(monkeypatch, UPSTREAM_OK_PAYLOAD)

    CrossSeedHelper.get_target_torrent(_upstream_site(), ["abc"])

    assert captured["body"] == {
        "passkey": "upstream_passkey",
        "pieces_hash": ["abc"],
    }
    assert "Authorization" not in captured["headers"]


# ─── 响应解析：results 数组，不是指纹映射 ──────────────────────────


def test_flux_lookup_response_is_parsed_from_results_array(monkeypatch):
    """FluxTorrent 响应应解析出种子 id、命中的指纹与站点名。"""
    captured = _capture_post(monkeypatch, FLUX_OK_PAYLOAD)

    infos, err = CrossSeedHelper.get_target_torrent(_flux_site(), ["abc"])

    assert err is None
    assert len(infos) == 1
    assert infos[0].torrent_id == "12345"
    assert infos[0].pieces_hash == \
        "db6aab38b13a6ae52542471a4a9fef2507973831"
    assert infos[0].site_name == FLUX_SITE_NAME


def test_flux_response_is_not_parsed_as_upstream_mapping():
    """**核心回归**：FluxTorrent 的 data 不能被当成上游的指纹映射。

    上游的 ``data.items()`` 套到 FluxTorrent 的 data 上，会把 ``"results"``
    当成**指纹名**，产出一条 ``pieces_hash="results"`` 的假命中——插件随后
    拿着这个假指纹去反查本地保存路径，必然落空。
    """
    infos = CrossSeedHelper._parse_flux_results(FLUX_OK_PAYLOAD, FLUX_SITE_NAME)

    upstream_style = [
        TorInfo.remote(FLUX_SITE_NAME, key, value)
        for key, value in FLUX_OK_PAYLOAD["data"].items()
    ]
    assert [item.pieces_hash for item in upstream_style] == ["results"]
    assert [item.torrent_id for item in infos] == ["12345"]
    assert all(item.pieces_hash != "results" for item in infos)


def test_upstream_lookup_response_is_still_parsed_as_mapping(monkeypatch):
    """上游方言的响应仍按「指纹 → 种子 id」映射解析。"""
    _capture_post(monkeypatch, UPSTREAM_OK_PAYLOAD)

    infos, err = CrossSeedHelper.get_target_torrent(_upstream_site(), ["abc"])

    assert err is None
    assert [(item.pieces_hash, item.torrent_id) for item in infos] == [
        ("db6aab38b13a6ae52542471a4a9fef2507973831", 12345),
    ]


def test_match_field_is_never_used_as_fingerprint():
    """``match`` 是命中类别（info_hash_v1 / pieces_sha1），不是指纹值。

    站点每条 result 里 ``match`` 说的是「命中的是哪一类」，``query`` 才是
    原指纹本身。拿 ``match`` 当 pieces_hash 会得到一个本地永远查不到的
    假指纹，上游反查保存路径时就会落空。
    """
    payload = {
        "code": 0,
        "data": {
            "results": [
                {"match": "pieces_sha1", "torrent_id": 7},
                {"match": "info_hash_v1", "query": "aa", "torrent_id": 8},
            ]
        },
    }

    infos = CrossSeedHelper._parse_flux_results(payload, FLUX_SITE_NAME)

    assert [item.torrent_id for item in infos] == ["7", "8"]
    assert [item.pieces_hash for item in infos] == ["", "aa"]


def test_flux_parser_tolerates_broken_payload():
    """响应结构异常时返回空列表，不抛异常。"""
    parse = CrossSeedHelper._parse_flux_results

    assert parse({}, "x") == []
    assert parse({"data": None}, "x") == []
    assert parse({"data": {}}, "x") == []
    assert parse({"data": {"results": "nope"}}, "x") == []
    assert parse(None, "x") == []


def test_flux_parser_skips_rows_without_torrent_id():
    """缺种子 id 的行直接跳过，不炸。"""
    payload = {
        "code": 0,
        "data": {
            "results": [
                {"query": "aa"},
                "not-a-dict",
                {"query": "bb", "torrent_id": 5},
            ]
        },
    }

    infos = CrossSeedHelper._parse_flux_results(payload, "x")

    assert len(infos) == 1
    assert infos[0].torrent_id == "5"


# ─── 下载：必须跟随 302 到临时凭证地址 ────────────────────────────


def test_flux_download_follows_redirect_to_temporary_credential():
    """下载口 302 到带 30 分钟临时凭证的地址，必须跟随重定向。

    站点口 ``/api/v1/crossseed/dl/{id}`` 只回一个 302，真实下载地址在
    Location 的 query 里（``fxk_`` 临时凭证）。不跟随重定向就拿不到种子。
    """
    received = []

    class _Handler(BaseHTTPRequestHandler):
        """扮演 FluxTorrent：下载口回 302，其余路径回种子字节。"""

        def do_GET(self):
            """记录路径并按站点语义应答。"""
            received.append(self.path)
            if self.path.startswith("/api/v1/crossseed/dl/"):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "/api/v1/downloads/12345?token=fxk_test_key",
                )
                self.end_headers()
                return
            body = b"d8:announce20:http://tracker/announcee"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-bittorrent")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """静默访问日志，避免污染用例输出。"""

    try:
        server = HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as err:
        pytest.skip(f"当前环境不允许绑定本地回环端口：{err}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        site = _flux_site(f"http://127.0.0.1:{server.server_port}")
        download = getattr(CrossSeed, "_CrossSeed__download_flux_torrent")
        content, err = download(site.get_torrent_url("12345"), site)
    finally:
        server.shutdown()
        server.server_close()

    assert err == ""
    assert content
    assert received[0].startswith("/api/v1/crossseed/dl/12345")
    assert received[1] == "/api/v1/downloads/12345?token=fxk_test_key"
