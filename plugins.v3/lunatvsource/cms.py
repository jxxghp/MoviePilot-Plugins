"""Apple CMS V10 configuration and response adapter."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


LOGGER = logging.getLogger(__name__)


_EPISODE_RE = re.compile(
    r"(?:S(?P<season>\d{1,3})\s*E(?P<episode>\d{1,4}))|"
    r"(?:第\s*(?P<cn_episode>\d{1,4})\s*[集话])|"
    r"(?:^|[\s._\-])(?P<bare_episode>\d{1,4})(?:$|[\s._\-])",
    re.IGNORECASE,
)
_SEASON_RE = re.compile(
    r"(?:S\s*(?P<s_season>\d{1,3})\s*(?:季|SEASON)?|"
    r"第\s*(?P<season>\d{1,3})\s*季)",
    re.IGNORECASE,
)
_CN_SEASON_RE = re.compile(
    r"(?:第\s*)(?P<season>[一二两三四五六七八九十百千万]+)\s*季",
    re.IGNORECASE,
)
_TV_TYPE_NAMES = frozenset(
    {
        "电视剧",
        "连续剧",
        "剧集",
        "国产剧",
        "大陆剧",
        "内地剧",
        "华语剧",
        "欧美剧",
        "美剧",
        "英剧",
        "韩剧",
        "日剧",
        "泰剧",
        "港剧",
        "香港剧",
        "台剧",
        "台湾剧",
        "日韩剧",
        "海外剧",
        "其他剧",
        "短剧",
        "微短剧",
        "网络剧",
        "情景剧",
        "动画剧",
    }
)
_SEASON_RANGE_RE = re.compile(
    r"(?:第\s*)?(?P<start>\d{1,3})\s*[-~至]\s*(?P<end>\d{1,3})\s*季|"
    r"S(?P<sstart>\d{1,3})\s*[-~至]\s*S?(?P<send>\d{1,3})",
    re.IGNORECASE,
)
_STREAM_RESOLUTION_RE = re.compile(r"(?P<width>\d{2,5})x(?P<height>\d{2,5})", re.IGNORECASE)
_MASTER_RESOLUTION_RE = re.compile(
    r"^#EXT-X-STREAM-INF:[^\r\n]*\bRESOLUTION\s*=\s*"
    r"(?P<width>\d{2,5})x(?P<height>\d{2,5})",
    re.IGNORECASE | re.MULTILINE,
)
_HLS_URI_RE = re.compile(
    r"\bURI\s*=\s*(?:\"(?P<quoted>[^\"]+)\"|(?P<plain>[^,\s]+))",
    re.IGNORECASE,
)
_HLS_BANDWIDTH_RE = re.compile(r"\bBANDWIDTH\s*=\s*(?P<value>\d+)", re.IGNORECASE)
_PROBE_REDIRECT_CODES = {301, 302, 303, 307, 308}
_PROBE_MAX_REDIRECTS = 5
_PROBE_PLAYLIST_BYTES = 256 * 1024
_PROBE_MEDIA_BYTES = 4 * 1024 * 1024
_TV_EPISODE_ROW_TITLE_RE = re.compile(
    r"^(?P<title>.+?)(?:\s*[-_.·:：]*\s*)"
    r"(?:S\s*(?P<season>\d{1,3})\s*E\s*(?P<episode>\d{1,4})|"
    r"第\s*(?P<cn_episode>\d{1,4})\s*[集话])\s*$",
    re.IGNORECASE,
)
# Apple CMS pages normally contain 10 or 20 rows. Keep a finite bound even for
# broken payloads while still covering a 208-episode season at those sizes.
_TV_EPISODE_ROW_MAX_PAGES = 32
_DETAIL_IDS_BATCH_SIZE = 50


def _season_range(label: str) -> Tuple[int, int]:
    """Return an explicit season range from a CMS title, if present."""

    match = _SEASON_RANGE_RE.search(_text(label))
    if not match:
        return 1, 1
    start = int(match.group("start") or match.group("sstart") or 1)
    end = int(match.group("end") or match.group("send") or start)
    return (start, end) if end >= start else (end, start)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _chinese_number(value: str) -> int:
    """Convert the small Chinese numerals commonly used in CMS season names."""

    text = _text(value).replace("两", "二")
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if all(char in digits for char in text):
        result = 0
        for char in text:
            result = result * 10 + digits[char]
        return result
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return 0


def _json_get(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LunaTVSource/0.1 MoviePilot"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def stream_quality_label(height: int) -> str:
    """Return a compact quality label from the actual video height."""

    value = max(0, int(height or 0))
    if value == 4320:
        return "8K"
    if value == 2160:
        return "4K"
    if value > 0:
        return f"{value}P"
    return "未知"


def _resolution_height(value: str) -> int:
    heights = [
        int(match.group("height"))
        for match in _STREAM_RESOLUTION_RE.finditer(value or "")
        if 100 <= int(match.group("height")) <= 10000
    ]
    return max(heights, default=0)


def _master_playlist_height(playlist: str) -> int:
    heights = [
        int(match.group("height"))
        for match in _MASTER_RESOLUTION_RE.finditer(playlist or "")
        if 100 <= int(match.group("height")) <= 10000
    ]
    return max(heights, default=0)


def _resolve_public_probe_target(
    url: str,
    allowed_private_ranges: Iterable[str] = (),
) -> Tuple[urllib.parse.ParseResult, str, int]:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported probe URL")
    if parsed.username or parsed.password:
        raise ValueError("probe URL credentials are not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("invalid probe URL port") from exc

    hostname = parsed.hostname.split("%", 1)[0]
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            address_infos = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("probe host cannot be resolved") from exc
        addresses = []
        for address_info in address_infos:
            candidate = str(address_info[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
    private_networks = []
    for value in allowed_private_ranges or ():
        try:
            private_networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            continue
    allowed_addresses = [address for address in addresses if address.is_global]
    allowed_addresses.extend(
        address
        for address in addresses
        if any(address in network for network in private_networks)
        and address not in allowed_addresses
    )
    if not allowed_addresses:
        raise ValueError("probe URL resolves to a non-public address")
    return parsed, str(allowed_addresses[0]), port


def _is_public_probe_url(url: str, allowed_private_ranges: Iterable[str] = ()) -> bool:
    try:
        _resolve_public_probe_target(url, allowed_private_ranges)
    except ValueError:
        return False
    return True


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to the address already approved by DNS policy."""

    def __init__(self, hostname: str, address: str, port: int, timeout: float):
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._probe_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._probe_address, self.port),
            self.timeout,
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _probe_host_header(parsed: urllib.parse.ParseResult, port: int) -> str:
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme == "https" else 80
    return hostname if port == default_port else f"{hostname}:{port}"


def _fetch_public_url(
    url: str,
    timeout: float,
    limit: int,
    allowed_private_ranges: Iterable[str] = (),
) -> Tuple[bytes, str]:
    """Fetch a bounded public URL while pinning DNS and validating redirects."""

    current_url = str(url or "").strip()
    request_timeout = min(max(float(timeout or 8.0), 1.0), 15.0)
    for _ in range(_PROBE_MAX_REDIRECTS + 1):
        parsed, address, port = _resolve_public_probe_target(
            current_url,
            allowed_private_ranges,
        )
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            connection = _PinnedHTTPSConnection(
                parsed.hostname or "",
                address,
                port,
                request_timeout,
            )
        else:
            connection = http.client.HTTPConnection(address, port, timeout=request_timeout)
        path = urllib.parse.urlunparse(
            ("", "", parsed.path or "/", parsed.params, parsed.query, "")
        )
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": _probe_host_header(parsed, port),
                    "User-Agent": "LunaTVSource/0.1 MoviePilot",
                    "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, */*",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in _PROBE_REDIRECT_CODES:
                location = response.getheader("Location")
                if not location:
                    raise OSError("probe redirect has no target")
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            if response.status < 200 or response.status >= 400:
                raise OSError(f"probe request returned HTTP {response.status}")
            return response.read(max(1, int(limit)) + 1)[:limit], current_url
        finally:
            connection.close()
    raise OSError("too many probe redirects")


def _playlist_followup_urls(playlist: str, base_url: str) -> Tuple[List[str], bool]:
    lines = [line.strip() for line in (playlist or "").splitlines()]
    variants: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        bandwidth_match = _HLS_BANDWIDTH_RE.search(line)
        bandwidth = int(bandwidth_match.group("value")) if bandwidth_match else 0
        for candidate in lines[index + 1:]:
            if not candidate or candidate.startswith("#"):
                continue
            variants.append((bandwidth, urllib.parse.urljoin(base_url, candidate)))
            break
    if variants:
        return [max(variants, key=lambda item: item[0])[1]], True

    urls: List[str] = []
    for line in lines:
        if line.upper().startswith("#EXT-X-MAP:"):
            match = _HLS_URI_RE.search(line)
            if match:
                urls.append(
                    urllib.parse.urljoin(
                        base_url,
                        match.group("quoted") or match.group("plain") or "",
                    )
                )
            break
    for line in lines:
        if line and not line.startswith("#"):
            urls.append(urllib.parse.urljoin(base_url, line))
            break
    return list(dict.fromkeys(url for url in urls if url)), False


def _probe_media_sample(
    url: str,
    timeout: float,
    depth: int = 0,
    allowed_private_ranges: Iterable[str] = (),
) -> Tuple[int, bytes, str]:
    payload, final_url = _fetch_public_url(
        url,
        timeout,
        _PROBE_PLAYLIST_BYTES,
        allowed_private_ranges,
    )
    playlist = payload.decode("utf-8", errors="replace")
    if "#EXTM3U" not in playlist:
        suffix = urllib.parse.urlparse(final_url).path.rpartition(".")[2]
        return 0, payload, f".{suffix}" if suffix else ".bin"

    height = _master_playlist_height(playlist)
    if height:
        return height, b"", ""
    followups, is_variant = _playlist_followup_urls(playlist, final_url)
    if is_variant:
        if depth >= 1 or not followups:
            return 0, b"", ""
        return _probe_media_sample(
            followups[0],
            timeout,
            depth + 1,
            allowed_private_ranges,
        )
    if not followups:
        return 0, b"", ""

    chunks: List[bytes] = []
    suffix = ".bin"
    for media_url in followups[:2]:
        chunk, final_media_url = _fetch_public_url(
            media_url,
            timeout,
            _PROBE_MEDIA_BYTES,
            allowed_private_ranges,
        )
        chunks.append(chunk)
        extension = urllib.parse.urlparse(final_media_url).path.rpartition(".")[2]
        if extension:
            suffix = f".{extension}"
    return 0, b"".join(chunks), suffix


def _ffprobe_path(ffmpeg_path: str) -> str:
    value = str(ffmpeg_path or "ffmpeg").strip() or "ffmpeg"
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme or "/" not in value:
        return "ffprobe"
    directory, _, name = value.rpartition("/")
    if name.startswith("ffmpeg"):
        return f"{directory}/ffprobe"
    return "ffprobe"


def probe_stream_height(
    url: str,
    ffmpeg_path: str = "ffmpeg",
    timeout: float = 8.0,
    allowed_private_ranges: Iterable[str] = (),
) -> int:
    """Read an HLS master playlist or the first video stream to get its height.

    Apple CMS metadata rarely carries a trustworthy quality field.  Reading the
    playlist first is cheap; for a media playlist, ffprobe reads just enough of
    the first segment to expose the video dimensions without saving a frame.
    """

    value = str(url or "").strip()
    if not _is_public_probe_url(value, allowed_private_ranges):
        return 0
    try:
        height, media_sample, suffix = _probe_media_sample(
            value,
            timeout,
            allowed_private_ranges=allowed_private_ranges,
        )
        if height:
            return height
    except Exception:
        return 0
    if not media_sample:
        return 0

    probe_timeout = min(max(float(timeout or 8.0), 3.0), 15.0)
    with tempfile.NamedTemporaryFile(prefix="lunatv-probe-", suffix=suffix) as sample:
        sample.write(media_sample)
        sample.flush()
        try:
            result = subprocess.run(
                [
                    _ffprobe_path(ffmpeg_path),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-analyzeduration",
                    "1000000",
                    "-probesize",
                    "1000000",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=s=x:p=0",
                    sample.name,
                ],
                capture_output=True,
                text=True,
                timeout=probe_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 0
        except (OSError, subprocess.SubprocessError, ValueError):
            result = None
        height = _resolution_height(result.stdout if result else "")
        if height:
            return height

        # Some streams expose dimensions only after the first frame is decoded.
        try:
            frame = subprocess.run(
            [
                str(ffmpeg_path or "ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "info",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                sample.name,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=probe_timeout,
            check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0
        return _resolution_height(frame.stderr)


def _split_player_values(value: str) -> List[str]:
    return [part.strip() for part in _text(value).split("$$$") if part.strip()]


def _extract_season_episode(label: str, default_season: int = 1) -> Tuple[int, int]:
    match = _EPISODE_RE.search(_text(label))
    if not match:
        return default_season, 1
    season = int(match.group("season") or default_season)
    episode = int(match.group("episode") or match.group("cn_episode") or match.group("bare_episode") or 1)
    return season, episode


def _extract_season(label: str, default_season: int = 1) -> int:
    match = _SEASON_RE.search(_text(label))
    if match:
        return int(match.group("season") or match.group("s_season"))
    match = _CN_SEASON_RE.search(_text(label))
    return _chinese_number(match.group("season")) if match else default_season


def _season_hint(label: str, default_season: int = 1) -> int:
    """从线路标题中读取季号；没有季号时保留默认值。"""
    return _extract_season(label, default_season)


def _has_explicit_season(label: str) -> bool:
    value = _text(label)
    return bool(
        re.search(r"S\s*\d{1,3}\s*E\s*\d{1,4}", value, re.IGNORECASE)
        or re.search(r"(?:第\s*)?\d{1,3}\s*季", value, re.IGNORECASE)
        or _CN_SEASON_RE.search(value)
        or re.search(r"\bS\s*\d{1,3}\b", value, re.IGNORECASE)
    )


def _parse_play_urls(
    play_from: Any,
    play_url: Any,
    default_season: int = 1,
    default_season_known: bool = True,
    number_unlabelled_multi_episode: bool = False,
) -> List["CmsEpisode"]:
    from_values = _split_player_values(_text(play_from))
    url_values = _split_player_values(_text(play_url))
    if not url_values:
        return []

    # A CMS response may list one player name and one URL group, or several
    # groups in matching order.  The first group is the stable fallback.
    selected_groups: List[Tuple[str, str]] = []

    def playable_entry_count(group: str) -> int:
        """Count entries this parser can expose as playable episodes."""

        count = 0
        for raw in group.split("#"):
            raw = raw.strip()
            if not raw:
                continue
            _, separator, url = raw.partition("$")
            url = (url if separator else raw).strip()
            parsed_url = urllib.parse.urlparse(url)
            if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
                count += 1
        return count

    if from_values:
        pairs = list(zip(from_values, url_values))
        has_season_groups = any(_extract_season(name, 0) > 0 for name, _ in pairs)
        preferred = [
            pair
            for pair in pairs
            if any(token in pair[0].lower() for token in ("m3u8", "高清", "在线播放", "在线"))
        ]
        # Keep all season-labelled groups; otherwise select one stable
        # playable group to avoid downloading the same episode repeatedly from
        # backup players.
        selected_groups = pairs if has_season_groups else (preferred[:1] or pairs[:1])
    elif number_unlabelled_multi_episode:
        # Some TV CMS payloads omit player names entirely. Prefer the group
        # with the most parseable episode URLs; ``max`` keeps the first group
        # when counts tie, preserving the historical stable preference.
        selected_groups = [("", max(url_values, key=playable_entry_count))]
    else:
        selected_groups = [("", url_values[0])]

    episodes: List[CmsEpisode] = []
    for group_name, group in selected_groups:
        parsed_entries: List[Tuple[int, str, str]] = []
        for ordinal, raw in enumerate(group.split("#"), start=1):
            raw = raw.strip()
            if not raw:
                continue
            if "$" in raw:
                label, url = raw.split("$", 1)
            else:
                label, url = "", raw
            url = url.strip()
            parsed_url = urllib.parse.urlparse(url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                continue
            parsed_entries.append((ordinal, label.strip(), url))

        # A TV detail row occasionally carries a whole season as plain
        # ``url#url`` entries despite a title such as “第52集”. Number the
        # unlabelled entries only when all entries on that one player line are
        # unlabelled; movie parsing retains its historical E01 treatment.
        number_unlabelled = (
            number_unlabelled_multi_episode
            and len(parsed_entries) > 1
            and all(not label for _, label, _ in parsed_entries)
        )
        for ordinal, label, url in parsed_entries:
            if number_unlabelled:
                season = _season_hint(group_name, default_season)
                episode = ordinal
            else:
                season, episode = _extract_season_episode(
                    label,
                    _season_hint(group_name, default_season),
                )
            season_known = default_season_known or _has_explicit_season(group_name) or _has_explicit_season(label)
            episodes.append(
                CmsEpisode(
                    season=season,
                    episode=episode,
                    label=label.strip(),
                    url=url,
                    season_known=season_known,
                )
            )
    deduped: Dict[Tuple[int, int, str], CmsEpisode] = {}
    for item in episodes:
        deduped[(item.season, item.episode, item.url)] = item
    return sorted(deduped.values(), key=lambda item: (item.season, item.episode, item.url))


def _source_status(comment: str) -> Tuple[str, str]:
    """Map a LunaTV source remark to a non-live display state."""

    remark = _text(comment).casefold()
    if any(token in remark for token in ("403", "失效", "不可用")):
        return "error", "异常"
    if "不稳定" in remark:
        return "warning", "不稳定"
    if "备用" in remark:
        return "warning", "备用"
    return "ready", "已加载"


def _source_search_status(comment: str, status: str) -> Tuple[str, str]:
    """Map a LunaTV source remark to its documented search capability."""

    if status == "error":
        return "unavailable", "不可用"

    remark = _text(comment).casefold()
    # ``无搜索结果`` is a distinct configured capability note.  Check it
    # before the unsupported wording so it is never presented as a disabled
    # search source by a future broader matching rule.
    if "无搜索结果" in remark:
        return "empty", "无结果"
    if any(token in remark for token in ("暂不支持搜索", "无法搜索", "禁止搜索")):
        return "unsupported", "不支持"
    if "污染搜索结果" in remark:
        return "degraded", "结果异常"
    return "supported", "支持"


@dataclass(frozen=True)
class CmsSource:
    key: str
    name: str
    api: str
    detail: str = ""
    comment: str = ""

    def to_dict(self) -> Dict[str, str]:
        """Return stable source metadata for the plugin workbench.

        The upstream LunaTV configuration carries human-maintained remarks, not
        health-check telemetry.  Keep the presentation state derived solely
        from that remark so the UI cannot imply a live availability probe.
        """

        status, status_label = _source_status(self.comment)
        search_status, search_label = _source_search_status(self.comment, status)
        return {
            "key": self.key,
            "name": self.name,
            "api": self.api,
            "detail": self.detail,
            "comment": self.comment,
            "url": self.detail or self.api,
            "status": status,
            "status_label": status_label,
            "search_status": search_status,
            "search_label": search_label,
        }


@dataclass(frozen=True)
class CmsEpisode:
    season: int
    episode: int
    label: str
    url: str
    season_known: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "season": self.season,
            "episode": self.episode,
            "label": self.label,
            "url": self.url,
            "season_known": self.season_known,
        }


@dataclass(frozen=True)
class CmsResult:
    source_key: str
    source_name: str
    vod_id: str
    title: str
    year: str
    media_type: str
    remark: str
    episodes: Tuple[CmsEpisode, ...] = field(default_factory=tuple)
    detail: str = ""
    season_range: Tuple[int, int] = (1, 1)
    season_ambiguous: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_key": self.source_key,
            "source_name": self.source_name,
            "vod_id": self.vod_id,
            "title": self.title,
            "year": self.year,
            "media_type": self.media_type,
            "remark": self.remark,
            "episodes": [episode.to_dict() for episode in self.episodes],
            "detail": self.detail,
            "season_range": list(self.season_range),
            "season_ambiguous": self.season_ambiguous,
        }


def _media_type_hint(item: Mapping[str, Any]) -> Optional[str]:
    """Return only an explicit, reliable type signal from a CMS list row."""

    type_name = _text(item.get("type_name")).strip().lower()
    value = f"{type_name} {_text(item.get('vod_class'))}".lower()
    if "电影" in value and "电视剧" not in value:
        return "movie"
    # Regional drama categories such as 欧美剧/韩剧 are used by some CMS
    # providers without the literal 电视剧 label. Use an explicit type-name
    # allowlist so movie categories such as 喜剧/悲剧 remain movies.
    if type_name in _TV_TYPE_NAMES:
        return "tv"
    if any(token in value for token in ("电视剧", "连续剧", "tv", "剧集", "综艺", "儿童", "少儿")):
        return "tv"
    return None


def _media_type(item: Mapping[str, Any]) -> str:
    media_type_hint = _media_type_hint(item)
    if media_type_hint is not None:
        return media_type_hint

    type_name = _text(item.get("type_name")).strip().lower()
    value = f"{type_name} {_text(item.get('vod_class'))}".lower()
    # 动漫/动画/纪录片在 CMS 中同时承载电影和剧集。 只有出现季集
    # 标记或明确的多集播放列表时才按电视剧处理，避免把动画电影误放到 TV 库。
    if any(token in value for token in ("动漫", "动画", "纪录")):
        title = _text(item.get("vod_name"))
        play_url = _text(item.get("vod_play_url"))
        if (
            _SEASON_RE.search(title)
            or _CN_SEASON_RE.search(title)
            or re.search(r"第\s*\d{1,4}\s*[集话]", title)
            or "#" in play_url
        ):
            return "tv"
    return "movie"


def _canonical_media_type_filter(value: str) -> str:
    """Return a supported result-type filter, or no filter for unknown input."""

    normalized = _text(value).strip().lower()
    return normalized if normalized in {"movie", "tv"} else ""


def _source_key(api_key: str, item: Mapping[str, Any]) -> str:
    return _text(item.get("vod_id") or item.get("vod_name") or api_key)


def _result_from_item(source: CmsSource, item: Mapping[str, Any]) -> CmsResult:
    title = _text(item.get("vod_name") or item.get("vod_en"))
    year = _text(item.get("vod_year"))
    media_type = _media_type(item)
    # 有些 CMS 只把“1-8季”写在片名里，线路名和集名都没有季号。
    # 这时至少保留起始季，避免所有集被误标成 S01；真正分季的线路仍优先使用线路标题。
    title_season = _extract_season(title, 1)
    season_range = _season_range(title)
    episodes = tuple(
        _parse_play_urls(
            item.get("vod_play_from"),
            item.get("vod_play_url"),
            title_season,
            default_season_known=season_range[0] == season_range[1],
            number_unlabelled_multi_episode=media_type == "tv",
        )
    )
    if media_type == "movie" and not episodes:
        direct_url = _text(item.get("vod_play_url"))
        if direct_url.startswith("http"):
            episodes = (CmsEpisode(season=1, episode=1, label="正片", url=direct_url),)
    season_ambiguous = season_range[1] > season_range[0] and not all(
        episode.season_known for episode in episodes
    )
    return CmsResult(
        source_key=source.key,
        source_name=source.name,
        vod_id=_source_key(source.key, item),
        title=title,
        year=year,
        media_type=media_type,
        remark=_text(item.get("vod_remarks")),
        episodes=episodes,
        detail=source.detail,
        season_range=season_range,
        season_ambiguous=season_ambiguous,
    )


def _episode_row_title_identity(
    result: CmsResult,
) -> Optional[Tuple[str, str, int, int, str]]:
    """Return a title-only candidate identity for an episode-indexed CMS row.

    Apple CMS instances sometimes expose a long season as individual search
    rows (``剧名 S01E001`` or ``剧名 第1集``).  Treat only explicit trailing
    episode markers as rows: a broad title search must never start paging just
    because a result happens to contain an episode-like word elsewhere.
    """

    if result.media_type != "tv":
        return None
    match = _TV_EPISODE_ROW_TITLE_RE.match(_text(result.title))
    if not match:
        return None
    title = _text(match.group("title")).strip(" -_.·:：")
    if not title:
        return None
    episode = int(match.group("episode") or match.group("cn_episode") or 0)
    season = int(match.group("season") or _extract_season(title, 1) or 1)
    if season <= 0 or episode <= 0:
        return None
    normalized_title = re.sub(r"[\s._\-·:：]+", "", title).casefold()
    if not normalized_title:
        return None
    return normalized_title, _text(result.year), season, episode, title


def _episode_row_identity(result: CmsResult) -> Optional[Tuple[str, str, int, int, str]]:
    """Return a row identity only when detail parsing confirms one episode.

    A CMS can label a complete series item as a latest episode while its detail
    payload holds the entire season.  Such an item is a normal result, not a
    single-row episode record, and must retain all of its parsed episodes.
    """

    identity = _episode_row_title_identity(result)
    if not identity:
        return None
    episode_keys = {(episode.season, episode.episode) for episode in result.episodes}
    return identity if len(episode_keys) == 1 else None


def _merge_episode_row_results(rows: Iterable[CmsResult]) -> Optional[CmsResult]:
    """Collapse the rows of one explicit TV season without discarding mirrors."""

    materialized = list(rows)
    if not materialized:
        return None
    identity = _episode_row_identity(materialized[0])
    if not identity:
        return materialized[0]
    _, _, season, _, title = identity
    episodes: Dict[Tuple[int, int, str], CmsEpisode] = {}
    for row in materialized:
        row_identity = _episode_row_identity(row)
        if not row_identity:
            continue
        _, _, row_season, row_episode, _ = row_identity
        if row_season != season:
            continue
        for episode in row.episodes:
            normalized = replace(
                episode,
                season=season,
                episode=row_episode,
                season_known=True,
            )
            episodes[(normalized.season, normalized.episode, normalized.url)] = normalized
    return replace(
        materialized[0],
        title=title,
        episodes=tuple(
            sorted(
                episodes.values(),
                key=lambda episode: (episode.season, episode.episode, episode.url),
            )
        ),
        season_range=(season, season),
        season_ambiguous=False,
    )


def _merge_episode_row_bundles(result: CmsResult, bundles: Iterable[CmsResult]) -> CmsResult:
    """Add later full-detail rows to one selected season without a second card."""

    season = result.season_range[0]
    episodes: Dict[Tuple[int, int, str], CmsEpisode] = {
        (episode.season, episode.episode, episode.url): episode
        for episode in result.episodes
    }
    for bundle in bundles:
        for episode in bundle.episodes:
            if episode.season != season:
                continue
            episodes[(episode.season, episode.episode, episode.url)] = episode
    return replace(
        result,
        episodes=tuple(
            sorted(
                episodes.values(),
                key=lambda episode: (episode.season, episode.episode, episode.url),
            )
        ),
    )


def apply_season_counts(result: CmsResult, season_counts: Mapping[int, int]) -> CmsResult:
    """Map a flat multi-season CMS list when TMDB supplies exact counts.

    A title range alone is not enough to infer season boundaries.  We only
    rewrite episodes when the CMS list length exactly equals the sum of the
    known season counts, avoiding silently putting episodes in the wrong
    season.
    """

    if not result.season_ambiguous or not season_counts:
        return result
    seasons = sorted(
        (int(season), int(count))
        for season, count in season_counts.items()
        if int(season) >= result.season_range[0]
        and int(season) <= result.season_range[1]
        and int(count) > 0
    )
    if not seasons or sum(count for _, count in seasons) != len(result.episodes):
        return result
    mapped: List[CmsEpisode] = []
    offset = 0
    for season, count in seasons:
        for episode_number in range(1, count + 1):
            episode = result.episodes[offset]
            mapped.append(replace(episode, season=season, episode=episode_number, season_known=True))
            offset += 1
    return replace(result, episodes=tuple(mapped), season_ambiguous=False)


def _merge_detail_item(item: Mapping[str, Any], detail: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge a detail response without discarding list metadata.

    Apple CMS installations commonly omit ``vod_play_url`` from ``ac=list``
    results and only expose the playable URLs from ``ac=detail``.  Keep the
    list item as the base so a sparse detail response cannot erase its title or
    type fields.
    """

    merged = dict(item)
    for key, value in detail.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def parse_config(payload: Mapping[str, Any], allowlist: Sequence[str] = ()) -> List[CmsSource]:
    raw_sites = payload.get("api_site") if isinstance(payload, Mapping) else None
    if not isinstance(raw_sites, Mapping):
        return []
    allowed = {str(item).strip().lower() for item in allowlist if str(item).strip()}
    sources: List[CmsSource] = []
    for key, value in raw_sites.items():
        if not isinstance(value, Mapping):
            continue
        api = _text(value.get("api"))
        if not api:
            continue
        key_text = _text(key).lower()
        host = urllib.parse.urlparse(api).hostname or key_text
        if allowed and not ({key_text, host.lower()} & allowed):
            continue
        sources.append(
            CmsSource(
                key=key_text,
                name=_text(value.get("name") or key),
                api=api,
                detail=_text(value.get("detail")),
                comment=_text(value.get("_comment")),
            )
        )
    return sources


def load_sources_from_url(url: str, timeout: float = 15, allowlist: Sequence[str] = ()) -> List[CmsSource]:
    return parse_config(_json_get(url, timeout), allowlist=allowlist)


class AppleCmsClient:
    def __init__(
        self,
        sources: Sequence[CmsSource],
        timeout: float = 15,
        parallel_wait_timeout: Optional[float] = None,
    ) -> None:
        self.sources = list(sources)
        self.timeout = timeout
        self.parallel_wait_timeout = parallel_wait_timeout

    def _parallel_wait_seconds(self) -> float:
        """Return the total budget for a parallel source search.

        The optional override keeps the timeout behavior deterministic in
        tests; production callers use a bounded budget derived from the
        per-source request timeout.
        """

        if self.parallel_wait_timeout is not None:
            return max(0.0, float(self.parallel_wait_timeout))
        return max(20.0, min(30.0, float(self.timeout) * 2))

    @staticmethod
    def _deadline_expired(deadline: Optional[float]) -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def _request(self, source: CmsSource, **params: Any) -> Mapping[str, Any]:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in (None, "")})
        separator = "&" if "?" in source.api else "?"
        url = f"{source.api}{separator}{query}" if query else source.api
        payload = _json_get(url, self.timeout)
        if not isinstance(payload, Mapping):
            raise ValueError("CMS 响应不是 JSON 对象")
        return payload

    @staticmethod
    def _items(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        items = payload.get("list") or payload.get("data") or []
        if isinstance(items, Mapping):
            items = items.get("list") or []
        return [item for item in items if isinstance(item, Mapping)]

    def _enrich_item(self, source: CmsSource, item: Mapping[str, Any]) -> Mapping[str, Any]:
        """Fetch the playable detail payload when the list response is sparse."""

        if _text(item.get("vod_play_url")):
            return item
        vod_id = _text(item.get("vod_id"))
        if not vod_id:
            return item
        try:
            payload = self._request(source, ac="detail", ids=vod_id)
            detail_items = self._items(payload)
            if detail_items:
                return _merge_detail_item(item, detail_items[0])
        except Exception:
            # A broken detail endpoint should not hide a valid list result.
            pass
        return item

    def _enrich_items(
        self,
        source: CmsSource,
        items: Iterable[Mapping[str, Any]],
        enrich: bool,
        deadline: Optional[float] = None,
    ) -> List[Mapping[str, Any]]:
        """Fill sparse Apple CMS rows with a bulk detail request when possible.

        A few CMS deployments do not implement comma-separated ``ids``
        correctly. Missing rows and failed bulk requests deliberately fall back
        to the established one-id request, so sparse search results remain
        compatible with those deployments.
        """

        materialized = list(items)
        if not enrich:
            return materialized
        sparse_ids = list(
            dict.fromkeys(
                _text(item.get("vod_id"))
                for item in materialized
                if not _text(item.get("vod_play_url")) and _text(item.get("vod_id"))
            )
        )
        details: Dict[str, Mapping[str, Any]] = {}
        if sparse_ids:
            sparse_id_set = set(sparse_ids)
            for start in range(0, len(sparse_ids), _DETAIL_IDS_BATCH_SIZE):
                if self._deadline_expired(deadline):
                    break
                batch = sparse_ids[start : start + _DETAIL_IDS_BATCH_SIZE]
                try:
                    payload = self._request(source, ac="detail", ids=",".join(batch))
                    for detail_item in self._items(payload):
                        vod_id = _text(detail_item.get("vod_id"))
                        if vod_id in sparse_id_set:
                            details[vod_id] = detail_item
                except Exception:
                    # Individual detail fallback below is intentionally retained.
                    pass

        enriched: List[Mapping[str, Any]] = []
        individual_fallbacks: Dict[str, Mapping[str, Any]] = {}
        for item in materialized:
            vod_id = _text(item.get("vod_id"))
            if _text(item.get("vod_play_url")):
                enriched.append(item)
            elif vod_id in details:
                merged = _merge_detail_item(item, details[vod_id])
                if _text(merged.get("vod_play_url")):
                    enriched.append(merged)
                    continue
                if self._deadline_expired(deadline):
                    enriched.append(merged)
                    continue
                if vod_id not in individual_fallbacks:
                    individual_fallbacks[vod_id] = self._enrich_item(source, merged)
                enriched.append(individual_fallbacks[vod_id])
            elif not vod_id:
                enriched.append(item)
            else:
                if self._deadline_expired(deadline):
                    enriched.append(item)
                    continue
                if vod_id not in individual_fallbacks:
                    individual_fallbacks[vod_id] = self._enrich_item(source, item)
                enriched.append(individual_fallbacks[vod_id])
        return enriched

    @staticmethod
    def _page_count(payload: Mapping[str, Any]) -> Optional[int]:
        """Read an Apple CMS page count, including its common numeric string."""

        raw = payload.get("pagecount")
        if raw in (None, ""):
            raw = payload.get("page_count")
        try:
            page_count = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return page_count if page_count > 0 else None

    def _results_from_items(
        self,
        source: CmsSource,
        items: Iterable[Mapping[str, Any]],
        enrich: bool,
        deadline: Optional[float] = None,
    ) -> List[CmsResult]:
        return [
            _result_from_item(source, item)
            for item in self._enrich_items(source, items, enrich, deadline=deadline)
        ]

    def _search_source(
        self,
        source: CmsSource,
        query: str,
        limit: int,
        enrich: bool = True,
        require_playable: bool = False,
        expand_tv_episode_rows: bool = False,
        media_type_filter: str = "",
    ) -> List[CmsResult]:
        media_type_filter = _canonical_media_type_filter(media_type_filter)
        list_params: Dict[str, Any] = {"ac": "list", "wd": query, "pg": 1}
        deadline = (
            time.monotonic() + self._parallel_wait_seconds()
            if expand_tv_episode_rows
            else None
        )
        try:
            if self._deadline_expired(deadline):
                return []
            payload = self._request(source, **list_params)
            items = self._items(payload)
            if not items:
                if self._deadline_expired(deadline):
                    return []
                list_params["pages"] = 1
                payload = self._request(source, **list_params)
                items = self._items(payload)
        except Exception:
            # A single third-party source must not block the rest.
            return []

        raw_items = items
        if media_type_filter:
            items = [
                item
                for item in items
                if _media_type_hint(item) in (None, media_type_filter)
            ]

        if not expand_tv_episode_rows:
            candidate_items = items if media_type_filter else items[:limit]
            return [
                result
                for result in self._results_from_items(source, candidate_items, enrich)
                if (not media_type_filter or result.media_type == media_type_filter)
                and (not require_playable or result.episodes)
            ][:limit]

        # Select up to ``limit`` cards rather than raw rows. A selected
        # long-season group can therefore grow past the source result cap,
        # while unrelated results retain the existing cap.
        selected_entries: List[Tuple[str, Any]] = []
        selected_groups: Dict[Tuple[str, str, int], List[CmsResult]] = {}
        selected_bundles: Dict[Tuple[str, str, int], List[CmsResult]] = {}
        selected_count = 0
        ambiguous_year_groups: set[Tuple[str, int]] = set()
        seen_explicit_years: Dict[Tuple[str, int], set[str]] = {}
        upgraded_unknown_groups: Dict[Tuple[str, int], str] = {}

        def remember_year_groups(
            page_results: Iterable[CmsResult],
        ) -> Tuple[Dict[Tuple[str, int], set[str]], set[Tuple[str, int]]]:
            explicit_years: Dict[Tuple[str, int], set[str]] = {}
            unknown_year_groups: set[Tuple[str, int]] = set()
            for result in page_results:
                group_identity = (
                    _episode_row_identity(result)
                    or _episode_row_title_identity(result)
                )
                if not group_identity:
                    continue
                base_key = (group_identity[0], group_identity[2])
                if group_identity[1]:
                    explicit_years.setdefault(base_key, set()).add(group_identity[1])
                else:
                    unknown_year_groups.add(base_key)
            for base_key, years in explicit_years.items():
                seen_explicit_years.setdefault(base_key, set()).update(years)
            ambiguous_year_groups.update(
                base_key
                for base_key, years in seen_explicit_years.items()
                if len(years) > 1
            )
            return explicit_years, unknown_year_groups

        def matching_group_key(
            identity: Tuple[str, str, int, int, str],
        ) -> Optional[Tuple[str, str, int]]:
            if identity[:3] in selected_groups:
                return identity[:3]
            if (identity[0], identity[2]) in ambiguous_year_groups:
                return None
            matches = [
                group_key
                for group_key in selected_groups
                if (
                    identity[0] == group_key[0]
                    and identity[2] == group_key[2]
                    and (
                        not identity[1]
                        or not group_key[1]
                        or identity[1] == group_key[1]
                    )
                )
            ]
            return matches[0] if len(matches) == 1 else None

        def upgrade_group_key(
            group_key: Tuple[str, str, int], year: str
        ) -> Tuple[str, str, int]:
            if group_key[1] or not year:
                return group_key
            upgraded_group_key = (group_key[0], year, group_key[2])
            if (
                upgraded_group_key in selected_groups
                or upgraded_group_key in selected_bundles
                or any(
                    kind == "group" and entry == upgraded_group_key
                    for kind, entry in selected_entries
                )
            ):
                return group_key
            selected_groups[upgraded_group_key] = selected_groups.pop(group_key)
            bundles = selected_bundles.pop(group_key, None)
            if bundles is not None:
                selected_bundles[upgraded_group_key] = bundles
            for index, (kind, entry) in enumerate(selected_entries):
                if kind == "group" and entry == group_key:
                    selected_entries[index] = (kind, upgraded_group_key)
                    break
            upgraded_unknown_groups[(group_key[0], group_key[2])] = year
            return upgraded_group_key

        def restore_upgraded_group(base_key: Tuple[str, int]) -> None:
            year = upgraded_unknown_groups.pop(base_key, "")
            if not year:
                return
            current_key = (base_key[0], year, base_key[1])
            unknown_key = (base_key[0], "", base_key[1])
            rows = selected_groups.pop(current_key, [])
            unknown_rows = [result for result in rows if not result.year]
            if unknown_rows:
                selected_groups[unknown_key] = unknown_rows
            bundles = selected_bundles.pop(current_key, [])
            unknown_bundles = [bundle for bundle in bundles if not bundle.year]
            if unknown_bundles:
                selected_bundles[unknown_key] = unknown_bundles
            for index, (kind, entry) in enumerate(selected_entries):
                if kind == "group" and entry == current_key:
                    selected_entries[index] = (kind, unknown_key)
                    break
            ambiguous_year_groups.add(base_key)

        def selected_group_year_conflict(page_results: Iterable[CmsResult]) -> bool:
            _, unknown_year_groups = remember_year_groups(page_results)
            selected_explicit_years: Dict[Tuple[str, int], set[str]] = {}
            selected_unknown_year_groups: set[Tuple[str, int]] = set()
            for title, year, season in selected_groups:
                base_key = (title, season)
                if year:
                    selected_explicit_years.setdefault(base_key, set()).add(year)
                else:
                    selected_unknown_year_groups.add(base_key)
            possible_unknown_groups = (
                unknown_year_groups
                | selected_unknown_year_groups
                | set(upgraded_unknown_groups)
            )
            has_conflict = False
            for base_key in possible_unknown_groups:
                known_years = {
                    *seen_explicit_years.get(base_key, set()),
                    *selected_explicit_years.get(base_key, set()),
                }
                if len(known_years) > 1:
                    restore_upgraded_group(base_key)
                    has_conflict = True
            return has_conflict

        def collect_results(
            page_results: Iterable[CmsResult], selected_group_only: bool = False
        ) -> bool:
            """Select cards and attach same-season bundles independently of row order."""

            nonlocal selected_count
            conflict = False
            media_type_results = [
                result
                for result in page_results
                if (not media_type_filter or result.media_type == media_type_filter)
            ]
            playable_results = [
                result
                for result in media_type_results
                if not require_playable or result.episodes
            ]
            _, unknown_year_groups = remember_year_groups(media_type_results)
            if (
                selected_group_only
                and selected_groups
                and selected_group_year_conflict(media_type_results)
            ):
                return True
            row_group_keys = set()
            for result in playable_results:
                identity = _episode_row_identity(result)
                if identity:
                    row_group_keys.add(identity[:3])

            for result in playable_results:
                identity = _episode_row_identity(result)
                title_identity = _episode_row_title_identity(result)
                group_identity = identity or title_identity
                matching_key = (
                    matching_group_key(group_identity) if group_identity else None
                )
                if selected_group_only and selected_groups:
                    if not group_identity:
                        continue
                    if matching_key is None:
                        if any(
                            group_identity[0] == group_key[0]
                            and group_identity[2] == group_key[2]
                            and group_identity[1]
                            and group_key[1]
                            and group_identity[1] != group_key[1]
                            for group_key in selected_groups
                        ):
                            conflict = True
                        continue
                group_key = (
                    upgrade_group_key(matching_key, group_identity[1])
                    if matching_key and group_identity
                    else (identity[:3] if identity else None)
                )
                if (
                    group_key is None
                    and title_identity
                    and (
                        not result.episodes
                        or title_identity[:3] in selected_groups
                        or title_identity[:3] in row_group_keys
                    )
                ):
                    group_key = title_identity[:3]
                if group_key is None:
                    if selected_count < limit:
                        selected_entries.append(("result", result))
                        selected_count += 1
                    continue
                if group_key not in selected_groups:
                    if selected_count >= limit:
                        continue
                    selected_groups[group_key] = []
                    selected_entries.append(("group", group_key))
                    selected_count += 1
                if identity:
                    selected_groups[group_key].append(result)
                else:
                    selected_bundles.setdefault(group_key, []).append(result)
            return conflict

        collect_results(self._results_from_items(source, items, enrich, deadline=deadline))

        if not selected_groups and not (require_playable and not selected_entries):
            return [entry for kind, entry in selected_entries if kind == "result"]

        def page_vod_ids(page_items: Iterable[Mapping[str, Any]]) -> Tuple[str, ...]:
            return tuple(_text(item.get("vod_id")) for item in page_items)

        def page_signature(
            page_items: Iterable[Mapping[str, Any]],
        ) -> Tuple[Tuple[str, ...], ...]:
            signatures = []
            for item in page_items:
                vod_id = _text(item.get("vod_id"))
                if vod_id:
                    signatures.append(("id", vod_id))
                else:
                    signatures.append(
                        (
                            "content",
                            _text(item.get("vod_name") or item.get("vod_en")),
                            _text(item.get("vod_year")),
                            _text(item.get("vod_play_from")),
                            _text(item.get("vod_play_url")),
                        )
                    )
            return tuple(sorted(signatures))

        seen_vod_ids = {vod_id for vod_id in page_vod_ids(raw_items) if vod_id}
        seen_page_signatures = {page_signature(raw_items)}
        page_count = self._page_count(payload)
        if page_count and page_count > _TV_EPISODE_ROW_MAX_PAGES:
            LOGGER.warning(
                "CMS episode-row pagination capped source=%s query=%s pagecount=%s cap=%s",
                source.key or source.name,
                query,
                page_count,
                _TV_EPISODE_ROW_MAX_PAGES,
            )
        last_page = min(page_count or _TV_EPISODE_ROW_MAX_PAGES, _TV_EPISODE_ROW_MAX_PAGES)
        for page in range(2, last_page + 1):
            if self._deadline_expired(deadline):
                break
            try:
                page_params = dict(list_params)
                page_params["pg"] = page
                page_payload = self._request(source, **page_params)
            except Exception:
                break
            raw_page_items = self._items(page_payload)
            if not raw_page_items:
                break
            page_ids = page_vod_ids(raw_page_items)
            signature = page_signature(raw_page_items)
            if signature in seen_page_signatures:
                break
            seen_page_signatures.add(signature)
            new_vod_ids = {vod_id for vod_id in page_ids if vod_id} - seen_vod_ids
            if page_ids and all(page_ids) and not new_vod_ids:
                break
            seen_vod_ids.update(new_vod_ids)

            page_items = raw_page_items
            if media_type_filter:
                page_items = [
                    item
                    for item in raw_page_items
                    if _media_type_hint(item) in (None, media_type_filter)
                ]
            if not page_items:
                if selected_groups or not require_playable:
                    break
                continue

            if selected_groups:
                # Once an episode-row season has been selected, retain only
                # matching rows on broad-search pages. A gap ends expansion
                # rather than walking an arbitrary result set.
                matched_items: List[Mapping[str, Any]] = []
                matched_results: List[CmsResult] = []
                for item in page_items:
                    result = _result_from_item(source, item)
                    identity = _episode_row_title_identity(result)
                    if (
                        identity is None
                        and _media_type_hint(item) is None
                    ):
                        identity = _episode_row_title_identity(
                            replace(result, media_type="tv")
                        )
                    if identity and any(
                        identity[0] == group_key[0]
                        and identity[2] == group_key[2]
                        for group_key in selected_groups
                    ):
                        matched_items.append(item)
                        matched_results.append(result)
                if not matched_items:
                    break
                if selected_group_year_conflict(matched_results):
                    break
                if collect_results(
                    self._results_from_items(
                        source,
                        matched_items,
                        enrich,
                        deadline=deadline,
                    ),
                    selected_group_only=True,
                ):
                    break
                continue

            # With require_playable enabled, an all-unplayable first page must
            # not hide later results. Keep the same bounded page safeguards
            # while discovering the first playable card.
            collect_results(
                self._results_from_items(
                    source,
                    page_items,
                    enrich,
                    deadline=deadline,
                )
            )
            if selected_entries and not selected_groups:
                # A regular card has no episode row to expand further.
                break

        source_results: List[CmsResult] = []
        for kind, entry in selected_entries:
            if kind == "result":
                source_results.append(entry)
                continue
            group_results = [
                replace(result, year=entry[1])
                if entry[1] and not result.year
                else result
                for result in selected_groups[entry]
            ]
            merged = _merge_episode_row_results(group_results)
            if merged and (not require_playable or merged.episodes):
                source_results.append(
                    _merge_episode_row_bundles(merged, selected_bundles.get(entry, ()))
                )
            elif not require_playable and selected_bundles.get(entry):
                bundles = selected_bundles[entry]
                base_bundle = next(
                    (bundle for bundle in bundles if bundle.episodes),
                    bundles[0],
                )
                source_results.append(_merge_episode_row_bundles(base_bundle, bundles))
        return source_results

    def detail(self, source_key: str, vod_id: str) -> Optional[CmsResult]:
        """按插件媒体身份读取单条详情，供 MoviePilot 原生订阅复用。"""
        source = next((item for item in self.sources if item.key == str(source_key).lower()), None)
        if source is None:
            return None
        payload = self._request(source, ac="detail", ids=vod_id)
        items = self._items(payload)
        if not items:
            return None
        return _result_from_item(source, self._enrich_item(source, items[0]))

    def search(
        self,
        query: str,
        limit: int = 20,
        stop_after_first_source: bool = False,
        enrich: bool = True,
        require_playable: bool = False,
        source_limit: Optional[int] = None,
        max_workers: int = 1,
        progress_callback: Optional[Callable[..., None]] = None,
        expand_tv_episode_rows: bool = False,
        media_type_filter: str = "",
    ) -> List[CmsResult]:
        media_type_filter = _canonical_media_type_filter(media_type_filter)
        ordered_sources = list(self.sources)
        total_sources = len(ordered_sources)
        results: List[CmsResult] = []
        seen: set[Tuple[str, str]] = set()
        completed_sources: set[int] = set()
        finished = 0

        def notify_progress() -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(
                    finished=finished,
                    total=total_sources,
                    text=f"正在搜索源 {finished}/{total_sources}",
                )
            except Exception:
                # UI/event handlers must not affect third-party CMS search.
                pass

        def settle_source(index: int) -> None:
            nonlocal finished
            if index in completed_sources:
                return
            completed_sources.add(index)
            finished += 1
            notify_progress()

        def settle_unfinished_sources() -> None:
            for index in range(total_sources):
                settle_source(index)
            if total_sources == 0:
                notify_progress()

        def merge_source_results(source_results: Iterable[CmsResult]) -> None:
            for result in source_results:
                key = (result.source_key, result.vod_id)
                if result.title and key not in seen:
                    seen.add(key)
                    results.append(result)

        if limit <= 0:
            settle_unfinished_sources()
            return []
        per_source_limit = max(1, min(int(source_limit or limit), int(limit)))
        max_workers = max(1, int(max_workers))
        if stop_after_first_source or max_workers == 1 or len(ordered_sources) <= 1:
            for index, source in enumerate(ordered_sources):
                source_result_count = len(results)
                try:
                    source_results = self._search_source(
                        source,
                        query=query,
                        limit=per_source_limit,
                        enrich=enrich,
                        require_playable=require_playable,
                        expand_tv_episode_rows=expand_tv_episode_rows,
                        media_type_filter=media_type_filter,
                    )
                except Exception:
                    source_results = []
                finally:
                    settle_source(index)
                merge_source_results(source_results)
                if stop_after_first_source and len(results) > source_result_count:
                    # The remaining sources are intentionally skipped; settle
                    # each one so progress always reaches total/total.
                    settle_unfinished_sources()
                    break
            settle_unfinished_sources()
            return results[:limit]

        futures: Dict[Any, int] = {}
        pending_futures = set()
        source_results: Dict[int, List[CmsResult]] = {}
        executor = ThreadPoolExecutor(max_workers=min(max_workers, len(ordered_sources)))
        try:
            for idx, source in enumerate(ordered_sources):
                future = executor.submit(
                    self._search_source,
                    source=source,
                    query=query,
                    limit=per_source_limit,
                    enrich=enrich,
                    require_playable=require_playable,
                    expand_tv_episode_rows=expand_tv_episode_rows,
                    media_type_filter=media_type_filter,
                )
                futures[future] = idx
                pending_futures.add(future)

            deadline = time.monotonic() + self._parallel_wait_seconds()
            while pending_futures:
                done_futures, pending_futures = wait(
                    pending_futures,
                    timeout=max(0.0, deadline - time.monotonic()),
                    return_when=FIRST_COMPLETED,
                )
                if not done_futures:
                    break
                for future in done_futures:
                    idx = futures[future]
                    try:
                        source_results[idx] = future.result()
                    except Exception:
                        source_results[idx] = []
                    finally:
                        settle_source(idx)

            # Do not leave queued sources running after the total search
            # budget expires. Running requests cannot be forcefully stopped,
            # but queued futures can be cancelled before executor shutdown.
            for future in pending_futures:
                future.cancel()
            settle_unfinished_sources()
            for idx in sorted(source_results):
                merge_source_results(source_results[idx])
                if len(results) >= limit:
                    return results[:limit]
            return results[:limit]
        finally:
            settle_unfinished_sources()
            # ``wait=False`` is intentional: slow third-party source calls do
            # not hold up the native search response after the budget.
            executor.shutdown(wait=False, cancel_futures=True)
