"""Jellyfin current-session provider for tunnel_api."""
import json
import ipaddress
from functools import lru_cache
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_CONFIG = {
    "JELLYFIN_URL": "http://192.168.1.20:8096",
    "JELLYFIN_API_KEY": "请填写Jellyfin API密钥",
    "JELLYFIN_TIMEOUT": 5,
    "JELLYFIN_USER_IDS": [],
    "JELLYFIN_EXCLUDE_IPS": [],
    "JELLYFIN_INCLUDE_PAUSED": False,
    "JELLYFIN_SESSION_TIMEOUT": 0,
    "JELLYFIN_NODE_NAME": "jellyfin-playback",
}


# 声明式安装参数；兼容现有通用安装器。
CONFIG_FIELDS = {'JELLYFIN_URL': {'label': 'Jellyfin 基础地址', 'required': True, 'help': '纯HTTP/HTTPS地址，可包含反向代理基础路径。'}, 'JELLYFIN_API_KEY': {'label': 'Jellyfin API Key（隐藏输入）', 'secret': True, 'required': True}, 'JELLYFIN_TIMEOUT': {'label': 'Jellyfin 请求超时（秒）', 'type': 'int', 'min': 1, 'max': 60}, 'JELLYFIN_USER_IDS': {'label': '监控用户 ID（逗号分隔）', 'type': 'csv', 'help': '空列表=全部用户；回车保留，输入 !clear 清空。'}, 'JELLYFIN_EXCLUDE_IPS': {'label': '不触发让位的 IP/网段（逗号分隔）', 'type': 'csv', 'help': '例如 172.16.8.0/24,192.168.1.50；输入 !clear 清空。以Jellyfin会话中的客户端地址为准。'}, 'JELLYFIN_INCLUDE_PAUSED': {'label': '暂停中的视频仍让位？y/n', 'type': 'bool'}, 'JELLYFIN_SESSION_TIMEOUT': {'label': '播放会话新鲜度（秒，0关闭）', 'type': 'int', 'min': 0, 'max': 86400}, 'JELLYFIN_NODE_NAME': {'label': 'MP 虚拟监控主机名', 'required': True}}

def validate_config(config):
    base_url = config.get("JELLYFIN_URL")
    api_key = config.get("JELLYFIN_API_KEY")
    node_name = config.get("JELLYFIN_NODE_NAME")

    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("JELLYFIN_URL 必须为非空字符串")
    base_url = base_url.strip()
    parsed = urlparse(base_url)
    try:
        parsed.port
    except ValueError:
        raise ValueError("JELLYFIN_URL 端口无效") from None
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 32 for char in base_url)
    ):
        raise ValueError(
            "JELLYFIN_URL 必须是无内嵌账户、查询参数和片段的 http/https 基础地址"
        )
    if (
        not isinstance(api_key, str)
        or not api_key.strip()
        or api_key.strip().startswith("请")
        or any(char in api_key for char in "\r\n\0")
    ):
        raise ValueError("JELLYFIN_API_KEY 无效")

    timeout = config.get("JELLYFIN_TIMEOUT")
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("JELLYFIN_TIMEOUT 必须为 1～60 的整数")
    users = config.get("JELLYFIN_USER_IDS")
    if (
        not isinstance(users, list)
        or any(
            not isinstance(user, str)
            or not user.strip()
            or any(char in user for char in "\r\n\0")
            for user in users
        )
    ):
        raise ValueError("JELLYFIN_USER_IDS 必须为非空用户 ID 字符串数组")
    if type(config.get("JELLYFIN_INCLUDE_PAUSED")) is not bool:
        raise ValueError("JELLYFIN_INCLUDE_PAUSED 必须为布尔值")
    session_timeout = config.get("JELLYFIN_SESSION_TIMEOUT")
    if type(session_timeout) is not int or not 0 <= session_timeout <= 86400:
        raise ValueError("JELLYFIN_SESSION_TIMEOUT 必须为 0～86400 的整数")
    if (
        not isinstance(node_name, str)
        or not node_name.strip()
        or any(ord(char) < 32 for char in node_name)
    ):
        raise ValueError("JELLYFIN_NODE_NAME 无效")

    config["JELLYFIN_URL"] = base_url.rstrip("/")
    config["JELLYFIN_API_KEY"] = api_key.strip()
    config["JELLYFIN_USER_IDS"] = [user.strip() for user in users]
    config["JELLYFIN_NODE_NAME"] = node_name.strip()
    excluded = config.get("JELLYFIN_EXCLUDE_IPS", [])
    _exclude_networks(excluded)
    config["JELLYFIN_EXCLUDE_IPS"] = [value.strip() for value in excluded]
    if any(char in config["JELLYFIN_API_KEY"] for char in ('"', '\\')):
        raise ValueError("JELLYFIN_API_KEY 不应包含引号或反斜杠")



def configure(old, ask, integer, executable, tty):
    url = ask("Jellyfin 基础地址（可包含反向代理路径）", old.get("JELLYFIN_URL", DEFAULT_CONFIG["JELLYFIN_URL"]))
    api_key_default = old.get("JELLYFIN_API_KEY", "")
    if not isinstance(api_key_default, str) or api_key_default.startswith("请"):
        api_key_default = ""
    while True:
        api_key = ask("Jellyfin API Key（隐藏输入）", api_key_default, True)
        if api_key and not api_key.startswith("请"):
            break
        tty.write("Jellyfin API Key 不能为空或占位符。\n")

    timeout_default = old.get("JELLYFIN_TIMEOUT", 5)
    if type(timeout_default) is not int:
        timeout_default = 5
    timeout = integer("Jellyfin 单次请求超时秒数", timeout_default, 1, 60)

    user_ids = old.get("JELLYFIN_USER_IDS", [])
    if not isinstance(user_ids, list) or any(not isinstance(value, str) for value in user_ids):
        user_ids = []
    user_text = ask("只监控指定用户 ID（逗号分隔；留空=全部用户）", ",".join(user_ids))
    user_ids = [value.strip() for value in user_text.split(",") if value.strip()]

    excluded_default = old.get("JELLYFIN_EXCLUDE_IPS", [])
    if not isinstance(excluded_default, list) or any(not isinstance(x, str) for x in excluded_default):
        excluded_default = []
    while True:
        excluded_text = ask(
            "不触发让位的IP/网段（逗号分隔；!clear清空）",
            ",".join(excluded_default),
        )
        excluded_ips = [] if excluded_text == "!clear" else [x.strip() for x in excluded_text.split(",") if x.strip()]
        try:
            _exclude_networks(excluded_ips)
            break
        except ValueError:
            tty.write("请输入合法的单个IPv4/IPv6地址或CIDR网段，不带端口。\n")

    paused_default = "y" if old.get("JELLYFIN_INCLUDE_PAUSED") is True else "n"
    paused_answer = ask("暂停中的视频是否仍然让位？y/n", paused_default).lower()
    if paused_answer not in ("y", "n"):
        raise SystemExit("暂停策略只能输入 y 或 n，已取消。")

    session_timeout_default = old.get("JELLYFIN_SESSION_TIMEOUT", 0)
    if type(session_timeout_default) is not int:
        session_timeout_default = 0
    session_timeout = integer(
        "播放会话新鲜度阈值秒数（0=关闭时间过滤）",
        session_timeout_default,
        0,
        86400,
    )
    node_name = ask(
        "MoviePilot 中使用的虚拟监控主机名",
        old.get("JELLYFIN_NODE_NAME", DEFAULT_CONFIG["JELLYFIN_NODE_NAME"]),
    )
    return {
        "JELLYFIN_URL": url,
        "JELLYFIN_API_KEY": api_key,
        "JELLYFIN_TIMEOUT": timeout,
        "JELLYFIN_USER_IDS": user_ids,
        "JELLYFIN_EXCLUDE_IPS": excluded_ips,
        "JELLYFIN_INCLUDE_PAUSED": paused_answer == "y",
        "JELLYFIN_SESSION_TIMEOUT": session_timeout,
        "JELLYFIN_NODE_NAME": node_name,
    }


def _value(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            return data[key]
    return None


def _boolean(value, field_name):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    raise ValueError(f"Jellyfin {field_name} 无效")


def _datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Jellyfin 会话时间缺失")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("Jellyfin 会话时间格式无效") from None
    if parsed.tzinfo is None:
        raise ValueError("Jellyfin 会话时间缺少时区")
    return parsed.astimezone(timezone.utc)


def _is_video(item):
    media_type = _value(item, "MediaType", "mediaType")
    if isinstance(media_type, str):
        normalized = media_type.strip().lower()
        if normalized == "video":
            return True
        if normalized in ("audio", "photo", "book"):
            return False

    item_type = _value(item, "Type", "type")
    normalized = item_type.strip().lower() if isinstance(item_type, str) else ""
    if normalized in ("movie", "episode", "video", "trailer", "musicvideo"):
        return True
    if normalized in ("audio", "audiobook", "book", "photo"):
        return False
    raise ValueError("Jellyfin 当前播放媒体类型无法识别")


@lru_cache(maxsize=32)
def _compile_exclude_networks(values):
    # Only configuration is cached, never playback state.
    try:
        return tuple(ipaddress.ip_network(value, strict=False) for value in values)
    except ValueError:
        raise ValueError("JELLYFIN_EXCLUDE_IPS 包含无效IP或CIDR网段") from None


def _exclude_networks(values):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip()
        or any(ord(char) < 32 for char in value)
        or "%" in value
        for value in values
    ):
        raise ValueError("JELLYFIN_EXCLUDE_IPS 必须为IP/CIDR字符串数组")
    return _compile_exclude_networks(tuple(value.strip() for value in values))


def _remote_ip(value):
    """Parse a literal IP or IP:port. No DNS, URLs, or ambiguous IPv6 port guessing."""
    if not isinstance(value, str) or not value.strip():
        return None
    def literal(candidate):
        base, separator, zone = candidate.partition("%")
        address = ipaddress.ip_address(base)
        if separator and (
            address.version != 6 or not zone
            or any(char in zone for char in "%:/[]")
        ):
            raise ValueError("invalid scope")
        return address

    text = value.strip()
    if any(ord(char) < 32 for char in text):
        return None
    if text.startswith("["):
        closing = text.find("]")
        if closing < 0:
            return None
        candidate, rest = text[1:closing], text[closing + 1:]
        if rest:
            if not rest.startswith(":") or not rest[1:].isdigit() or len(rest[1:]) > 5:
                return None
            if not 0 <= int(rest[1:]) <= 65535:
                return None
    else:
        candidate = text
        try:
            return literal(candidate)
        except ValueError:
            pass
        if text.count(":") == 1 and "." in text:
            candidate, port = text.rsplit(":", 1)
            if not port.isdigit() or len(port) > 5 or not 0 <= int(port) <= 65535:
                return None
        else:
            return None
    try:
        return literal(candidate)
    except ValueError:
        return None


def _ip_excluded(session, networks):
    if not networks:
        return False
    endpoint = _value(
        session, "RemoteEndPoint", "remoteEndPoint",
        "RemoteEndpoint", "remoteEndpoint",
    )
    address = _remote_ip(endpoint)
    # Availability policy: unknown IP does not exclude a valid video session.
    if address is None:
        return False
    candidates = [address]
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        candidates.append(address.ipv4_mapped)
    return any(
        candidate.version == network.version and candidate in network
        for candidate in candidates
        for network in networks
    )


def _session_playing(session, user_ids, now, config, exclude_networks=None):
    if not isinstance(session, dict):
        raise ValueError("Jellyfin 会话条目不是对象")

    item = _value(session, "NowPlayingItem", "nowPlayingItem")
    if item is None:
        return False
    if not isinstance(item, dict) or not item:
        raise ValueError("Jellyfin 当前播放项无效")
    if user_ids:
        user_id = _value(session, "UserId", "userId")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Jellyfin 播放会话缺少用户 ID")
        if user_id.strip().lower() not in user_ids:
            return False
    if not _is_video(item):
        return False
    if exclude_networks is None:
        exclude_networks = _exclude_networks(config.get("JELLYFIN_EXCLUDE_IPS", []))
    if _ip_excluded(session, exclude_networks):
        return False

    active = _value(session, "IsActive", "isActive")
    if active is not None and not _boolean(active, "IsActive"):
        return False

    if not config["JELLYFIN_INCLUDE_PAUSED"]:
        play_state = _value(session, "PlayState", "playState")
        if not isinstance(play_state, dict):
            raise ValueError("Jellyfin 视频会话缺少 PlayState")
        paused = _value(play_state, "IsPaused", "isPaused")
        if _boolean(paused, "IsPaused"):
            return False

    if config["JELLYFIN_SESSION_TIMEOUT"] > 0:
        last_seen = (
            _value(session, "LastPlaybackCheckIn", "lastPlaybackCheckIn")
            or _value(session, "LastActivityDate", "lastActivityDate")
        )
        checked_at = _datetime(last_seen)
        elapsed = (now - checked_at).total_seconds()
        if elapsed < -60:
            raise ValueError("Jellyfin 会话时间明显晚于本机时间")
        if elapsed > config["JELLYFIN_SESSION_TIMEOUT"]:
            return False
    return True


def parse_sessions(payload, config):
    """Return True/False only for a valid Sessions payload; raise on malformed data."""
    if not isinstance(payload, list):
        raise ValueError("Jellyfin Sessions 响应不是数组")
    user_ids = {value.strip().lower() for value in config["JELLYFIN_USER_IDS"]}
    now = datetime.now(timezone.utc)
    exclude_networks = _exclude_networks(config.get("JELLYFIN_EXCLUDE_IPS", []))
    playing = False
    for session in payload:
        # Intentionally don't short-circuit after finding a playing session:
        # malformed entries must not be hidden by an earlier positive match.
        if _session_playing(session, user_ids, now, config, exclude_networks):
            playing = True
    return playing


def collect(config):
    try:
        request = Request(
            config["JELLYFIN_URL"].rstrip("/") + "/Sessions",
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f'MediaBrowser Token="{config["JELLYFIN_API_KEY"]}"',
            },
        )
        with urlopen(request, timeout=config["JELLYFIN_TIMEOUT"]) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8-sig"))
        playing = parse_sessions(payload, config)
        return ([{
            "ipv4": "",
            "hostname": config["JELLYFIN_NODE_NAME"],
            "is_online": playing,
        }], None)
    except Exception:
        # Never log request headers or exception strings that could contain credentials.
        return None
