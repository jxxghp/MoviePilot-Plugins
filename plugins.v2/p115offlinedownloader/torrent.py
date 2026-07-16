from pathlib import Path
from typing import Any, Iterable, List, Optional, Union
from urllib.parse import parse_qsl, urlencode, urlparse

from torrentool.torrent import Torrent

from .magnet import extract_info_hash, normalize_info_hash
from .schemas import NormalizedDownload


SENSITIVE_TRACKER_PARAMS = {
    "passkey",
    "authkey",
    "torrent_pass",
    "torrent_passkey",
    "token",
    "uid",
    "user_id",
}


def _dict_get(mapping: object, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    if key in mapping:
        return mapping[key]
    return mapping.get(key.encode("utf-8"), default)


def _flatten_trackers(value: object) -> List[str]:
    trackers: List[str] = []
    if isinstance(value, (str, bytes)):
        value = [value]
    if not isinstance(value, Iterable):
        return trackers
    for item in value:
        if isinstance(item, (list, tuple, set)):
            trackers.extend(_flatten_trackers(item))
        elif isinstance(item, bytes):
            try:
                trackers.append(item.decode("utf-8"))
            except UnicodeDecodeError:
                continue
        elif isinstance(item, str):
            trackers.append(item)
    return list(dict.fromkeys(tracker for tracker in trackers if tracker))


def get_trackers(torrent: Torrent) -> List[str]:
    trackers = _flatten_trackers(getattr(torrent, "announce_urls", None))
    struct = getattr(torrent, "_struct", {}) or {}
    announce = _dict_get(struct, "announce")
    trackers.extend(_flatten_trackers(announce))
    return list(dict.fromkeys(trackers))


def contains_sensitive_tracker(torrent: Torrent) -> bool:
    for tracker in get_trackers(torrent):
        parsed = urlparse(tracker)
        if parsed.username or parsed.password:
            return True
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in SENSITIVE_TRACKER_PARAMS:
                return True
    return False


def is_pure_v2_torrent(torrent: Torrent) -> bool:
    struct = getattr(torrent, "_struct", {}) or {}
    info = _dict_get(struct, "info", {}) or {}
    meta_version = _dict_get(info, "meta version")
    try:
        meta_version = int(meta_version)
    except (TypeError, ValueError):
        pass
    return meta_version == 2 and not bool(_dict_get(info, "pieces"))


def _get_web_seeds(torrent: Torrent) -> List[str]:
    struct = getattr(torrent, "_struct", {}) or {}
    return _flatten_trackers(_dict_get(struct, "url-list"))


def _build_magnet(torrent: Torrent, info_hash: str, include_trackers: bool) -> str:
    params = [("xt", f"urn:btih:{info_hash}")]
    name = getattr(torrent, "name", None)
    if name:
        params.append(("dn", str(name)))
    if include_trackers:
        params.extend(("tr", tracker) for tracker in get_trackers(torrent))
        params.extend(("ws", seed) for seed in _get_web_seeds(torrent))
    return f"magnet:?{urlencode(params, doseq=True)}"


def _normalize_magnet(value: str) -> NormalizedDownload:
    magnet = value.strip()
    info_hash = extract_info_hash(magnet)
    if not info_hash:
        return NormalizedDownload(error="磁力链接中不存在有效BTIH")
    return NormalizedDownload(
        magnet=magnet,
        info_hash=info_hash,
        source_type="magnet",
    )


def normalize_download_content(
    content: Union[Path, str, bytes, bytearray],
    *,
    allow_torrent_conversion: bool = True,
    include_trackers: bool = True,
) -> NormalizedDownload:
    """Normalize supported MoviePilot content without leaking it in errors."""

    if isinstance(content, str):
        if content.strip().lower().startswith("magnet:"):
            return _normalize_magnet(content)
        return NormalizedDownload(error="不支持的字符串下载内容")

    if isinstance(content, Path):
        try:
            torrent_content = content.read_bytes()
        except OSError:
            return NormalizedDownload(error="读取种子文件失败")
    elif isinstance(content, (bytes, bytearray)):
        torrent_content = bytes(content)
    else:
        return NormalizedDownload(error="不支持的下载内容类型")

    stripped_content = torrent_content.strip()
    if stripped_content.lower().startswith(b"magnet:"):
        try:
            return _normalize_magnet(stripped_content.decode("utf-8"))
        except UnicodeDecodeError:
            return NormalizedDownload(error="磁力内容不是有效UTF-8")

    if not allow_torrent_conversion:
        return NormalizedDownload(error="当前配置不允许Torrent转换为磁力")

    try:
        torrent = Torrent.from_string(torrent_content)
    except Exception:
        return NormalizedDownload(error="种子文件解析失败")

    torrent_name = str(getattr(torrent, "name", "") or "") or None
    if bool(getattr(torrent, "private", False)):
        return NormalizedDownload(
            torrent_name=torrent_name,
            error="检测到私有种子，禁止提交到115",
        )
    if contains_sensitive_tracker(torrent):
        return NormalizedDownload(
            torrent_name=torrent_name,
            error="检测到含敏感认证参数的Tracker，禁止提交到115",
        )
    if is_pure_v2_torrent(torrent):
        return NormalizedDownload(
            torrent_name=torrent_name,
            error="检测到纯BitTorrent v2种子，当前不支持btmh",
        )

    info_hash = normalize_info_hash(getattr(torrent, "info_hash", None))
    if not info_hash:
        return NormalizedDownload(
            torrent_name=torrent_name,
            error="无法生成BitTorrent v1 BTIH",
        )

    magnet = _build_magnet(torrent, info_hash, include_trackers)
    return NormalizedDownload(
        magnet=magnet,
        info_hash=info_hash,
        source_type="torrent",
        torrent_name=torrent_name,
    )
