"""WireGuard provider for tunnel_api."""
import re
import shutil
import subprocess
import time

DEFAULT_CONFIG = {
    "WG_CLI": "wg",
    "WG_INTERFACE": "wg0",
    "WG_HANDSHAKE_TIMEOUT": 180,
    "WG_PEER_NAMES": {},
}

_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d+)?$")


# 安装器声明；新增参数只需更新 DEFAULT_CONFIG / CONFIG_FIELDS。
CONFIG_FIELDS = {'WG_CLI': {'label': 'WireGuard wg 路径', 'type': 'path', 'executable': True, 'required': True}, 'WG_INTERFACE': {'label': 'WireGuard 网卡名', 'required': True}, 'WG_HANDSHAKE_TIMEOUT': {'label': '握手超时（秒）', 'type': 'int', 'min': 30, 'max': 86400}, 'WG_PEER_NAMES': {'label': '节点主机名映射（JSON对象）', 'type': 'json', 'help': '例如 {"公钥":"手机"}；输入 {} 清空映射。'}}

def validate_config(config):
    for key in ("WG_CLI", "WG_INTERFACE"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} 必须为非空字符串")
    if not re.match(r"^[A-Za-z0-9_.-]{1,15}$", config["WG_INTERFACE"]):
        raise ValueError("WG_INTERFACE 必须为合法网卡名")

    timeout = config.get("WG_HANDSHAKE_TIMEOUT")
    if type(timeout) is not int or not 30 <= timeout <= 86400:
        raise ValueError("WG_HANDSHAKE_TIMEOUT 必须为 30～86400 的整数")

    names = config.get("WG_PEER_NAMES")
    if not isinstance(names, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not value.strip()
        or any(char in value for char in ",#\r\n")
        for key, value in names.items()
    ):
        raise ValueError("WG_PEER_NAMES 必须为 {公钥: 主机名}，主机名非空且不含逗号/#/换行")


def configure(old, ask, integer, executable, tty):
    cli = old.get("WG_CLI") or shutil.which("wg") or "/usr/bin/wg"
    cli = executable(
        "wg 命令的绝对路径",
        cli,
        "路径不存在或不可执行，请先安装 wireguard-tools，或填写实际路径。",
    )
    interface = ask("WireGuard 网卡名", old.get("WG_INTERFACE", "wg0"))
    timeout_default = old.get("WG_HANDSHAKE_TIMEOUT", 180)
    if type(timeout_default) is not int:
        timeout_default = 180
    timeout = integer(
        "握手超时秒数（超过视为离线，客户端需配置 PersistentKeepalive）",
        timeout_default,
        30,
        86400,
    )
    names = old.get("WG_PEER_NAMES", {})
    return {
        "WG_CLI": cli,
        "WG_INTERFACE": interface,
        "WG_HANDSHAKE_TIMEOUT": timeout,
        "WG_PEER_NAMES": names if isinstance(names, dict) else {},
    }


def parse_dump(text, now, timeout, names=None):
    """Parse `wg show <interface> dump`; never expose private keys or endpoints."""
    names = names or {}
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2 or len(lines[0].split("\t")) != 4:
        return None

    peers = []
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) != 8:
            return None
        public_key, _psk, _endpoint, allowed_ips, handshake = columns[:5]
        if not public_key or not re.match(r"^\d+$", handshake):
            return None
        handshake_at = int(handshake)
        ipv4 = ""
        for item in allowed_ips.split(","):
            item = item.strip()
            if _IPV4_RE.match(item):
                ipv4 = item
                break
        peers.append({
            "ipv4": ipv4,
            "hostname": names.get(public_key) or f"wg-{public_key[:8]}",
            "latest_handshake": handshake_at,
            "is_online": handshake_at > 0 and now - handshake_at <= timeout,
        })
    return peers or None


def collect(config):
    try:
        result = subprocess.run(
            [config["WG_CLI"], "show", config["WG_INTERFACE"], "dump"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return None
        peers = parse_dump(
            result.stdout,
            time.time(),
            config["WG_HANDSHAKE_TIMEOUT"],
            config["WG_PEER_NAMES"],
        )
        return (peers, None) if peers else None
    except Exception:
        return None
