from pathlib import Path
from urllib.parse import parse_qs, urlparse

from p115offlinedownloader.torrent import normalize_download_content


def bencode(value):
    if isinstance(value, int):
        return f"i{value}e".encode()
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, str):
        return bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=lambda item: item if isinstance(item, bytes) else str(item).encode()):
            parts.append(bencode(key))
            parts.append(bencode(value[key]))
        return b"d" + b"".join(parts) + b"e"
    raise TypeError(type(value))


def torrent_bytes(*, private=0, tracker="https://tracker.example/announce", hybrid=False, pure_v2=False):
    info = {
        b"name": b"Example.mkv",
        b"piece length": 16384,
    }
    if pure_v2:
        info.update({b"meta version": 2, b"file tree": {b"Example.mkv": {b"": {b"length": 1}}}})
    else:
        info.update({b"length": 1, b"pieces": b"x" * 20})
        if hybrid:
            info.update({b"meta version": 2, b"file tree": {b"Example.mkv": {b"": {b"length": 1}}}})
    if private:
        info[b"private"] = 1
    return bencode(
        {
            b"announce": tracker,
            b"announce-list": [[tracker]],
            b"url-list": ["https://seed.example/file"],
            b"info": info,
        }
    )


def test_public_v1_torrent_to_detailed_magnet():
    result = normalize_download_content(torrent_bytes())
    assert result.error is None
    assert len(result.info_hash) == 40
    query = parse_qs(urlparse(result.magnet).query)
    assert query["xt"] == [f"urn:btih:{result.info_hash}"]
    assert query["tr"] == ["https://tracker.example/announce"]
    assert query["ws"] == ["https://seed.example/file"]


def test_tracker_and_webseed_can_be_omitted():
    result = normalize_download_content(torrent_bytes(), include_trackers=False)
    query = parse_qs(urlparse(result.magnet).query)
    assert "tr" not in query
    assert "ws" not in query


def test_torrent_path(tmp_path: Path):
    path = tmp_path / "sample.torrent"
    path.write_bytes(torrent_bytes())
    result = normalize_download_content(path)
    assert result.error is None
    assert result.source_type == "torrent"


def test_private_torrent_is_rejected():
    result = normalize_download_content(torrent_bytes(private=1))
    assert result.error == "检测到私有种子，禁止提交到115"


def test_sensitive_tracker_is_rejected():
    result = normalize_download_content(
        torrent_bytes(tracker="https://tracker.example/announce?passkey=secret")
    )
    assert "敏感认证参数" in result.error


def test_pure_v2_is_rejected_and_hybrid_is_allowed():
    pure = normalize_download_content(torrent_bytes(pure_v2=True))
    assert "纯BitTorrent v2" in pure.error
    hybrid = normalize_download_content(torrent_bytes(hybrid=True))
    assert hybrid.error is None
    assert len(hybrid.info_hash) == 40


def test_invalid_and_disabled_conversion():
    assert "解析失败" in normalize_download_content(b"not-a-torrent").error
    result = normalize_download_content(
        torrent_bytes(), allow_torrent_conversion=False
    )
    assert "不允许Torrent转换" in result.error


def test_unsupported_string_and_missing_path(tmp_path: Path):
    assert "不支持" in normalize_download_content("https://example.com/a").error
    assert "读取种子文件失败" == normalize_download_content(tmp_path / "missing").error
