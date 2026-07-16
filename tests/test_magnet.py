import base64

from p115offlinedownloader.magnet import extract_info_hash, normalize_info_hash
from p115offlinedownloader.torrent import normalize_download_content


HEX_HASH = "0123456789abcdef0123456789abcdef01234567"


def test_extract_lower_and_upper_hex():
    assert extract_info_hash(f"magnet:?xt=urn:btih:{HEX_HASH}") == HEX_HASH
    assert extract_info_hash(f"MAGNET:?xt=URN:BTIH:{HEX_HASH.upper()}") == HEX_HASH


def test_extract_base32():
    encoded = base64.b32encode(bytes.fromhex(HEX_HASH)).decode("ascii")
    assert len(encoded) == 32
    assert extract_info_hash(f"magnet:?xt=urn:btih:{encoded}") == HEX_HASH


def test_extract_uses_first_valid_btih():
    magnet = f"magnet:?xt=urn:sha1:bad&xt=urn:btih:nope&xt=urn:btih:{HEX_HASH}"
    assert extract_info_hash(magnet) == HEX_HASH


def test_invalid_magnets():
    assert extract_info_hash("https://example.com/file") is None
    assert extract_info_hash("magnet:?dn=missing") is None
    assert extract_info_hash("magnet:?xt=urn:btih:invalid") is None
    assert normalize_info_hash("A" * 31) is None


def test_bytes_magnet_is_supported():
    result = normalize_download_content(
        f"  magnet:?xt=urn:btih:{HEX_HASH}  ".encode("utf-8")
    )
    assert result.error is None
    assert result.info_hash == HEX_HASH
    assert result.source_type == "magnet"
