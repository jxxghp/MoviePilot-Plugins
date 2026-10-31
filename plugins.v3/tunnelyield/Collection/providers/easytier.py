"""EasyTier provider for tunnel_api."""
import math
import re
import subprocess

DEFAULT_CONFIG = {
    "EASYTIER_CLI": "easytier-cli",
}


# 安装器声明；新增参数只需更新 DEFAULT_CONFIG / CONFIG_FIELDS。
CONFIG_FIELDS = {'EASYTIER_CLI': {'label': 'EasyTier CLI 路径', 'type': 'path', 'executable': True, 'required': True}}

def validate_config(config):
    value = config.get("EASYTIER_CLI")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("EASYTIER_CLI 必须为非空字符串")


def configure(old, ask, integer, executable, tty):
    """Installer hook: collect EasyTier-specific settings."""
    import shutil

    cli = old.get("EASYTIER_CLI") or shutil.which("easytier-cli") or "/usr/bin/easytier-cli"
    cli = executable(
        "easytier-cli 的绝对路径",
        cli,
        "路径不存在或不可执行，请先安装 EasyTier，或填写实际路径。",
    )
    return {"EASYTIER_CLI": cli}


def run_cmd(config, args):
    """Execute an EasyTier CLI command, returning (ok, stdout_or_error)."""
    try:
        command = [config["EASYTIER_CLI"], *args]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=4
        )
        if result.returncode != 0:
            return False, result.stderr
        return True, result.stdout
    except Exception as exc:
        return False, str(exc)


def parse_peer_table(text):
    """Parse easytier-cli peer output; malformed or empty output is a failure."""
    lines = text.strip().splitlines() if isinstance(text, str) else []
    sep_idx = None
    for index, line in enumerate(lines):
        if re.match(r"^\|[- ]+\|", line):
            sep_idx = index
            break
    if sep_idx is None or sep_idx < 1:
        return None

    header_cols = [c.strip().lower() for c in lines[sep_idx - 1].split("|") if c.strip()]
    if (
        len(header_cols) < 4
        or header_cols[0] != "ipv4"
        or header_cols[1] != "hostname"
        or header_cols[2] != "cost"
        or not header_cols[3].startswith("lat")
    ):
        return None

    peers = []
    for line in lines[sep_idx + 1:]:
        line = line.strip()
        if not line.startswith("|"):
            return None
        cols = [column.strip() for column in line.split("|")[1:-1]]
        if len(cols) < 9:
            return None

        ipv4, hostname, cost, latency = cols[0], cols[1], cols[2], cols[3]
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}(/\d+)?$", ipv4) or not hostname:
            return None

        if latency == "-":
            latency_online = False
        else:
            try:
                latency_value = float(latency)
            except ValueError:
                return None
            if not math.isfinite(latency_value) or latency_value < 0:
                return None
            latency_online = True

        # EasyTier Local is the local node and is always online.
        is_online = True if cost == "Local" else latency_online
        peers.append({
            "ipv4": ipv4,
            "hostname": hostname,
            "cost": cost,
            "lat_ms": latency,
            "loss": cols[4],
            "rx": cols[5],
            "tx": cols[6],
            "tunnel": cols[7],
            "nat": cols[8],
            "is_online": is_online,
        })

    return peers or None


def parse_node_table(text):
    node_info = {}
    public_ips = []
    lan_cidr = None
    lan_ip = None
    et_ports = set()

    lines = text.strip().splitlines() if isinstance(text, str) else []
    for line in lines:
        match = re.match(r"\|([^|]+)\|([^|]+)\|", line)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        node_info[key] = value

        if key == "Public IPv4" and re.match(r"\d+\.\d+\.\d+\.\d+", value):
            public_ips.append(value)
        elif key == "Proxy CIDRs":
            lan_cidr = value
        elif key == "Interface IPv4":
            lan_ip = value
        elif key.startswith("Listener"):
            port_match = re.search(r":(\d+)", value)
            if port_match:
                et_ports.add(port_match.group(1))

    return node_info, public_ips, lan_cidr, lan_ip, list(et_ports)


def parse_route_table(text):
    routes = []
    lines = text.strip().splitlines() if isinstance(text, str) else []
    start_idx = None
    for index, line in enumerate(lines):
        if re.match(r"^\|[- ]+\|", line):
            start_idx = index + 1
            break
    if start_idx is None:
        return routes

    for line in lines[start_idx:]:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        cols = [column.strip() for column in line.split("|")[1:-1]]
        if len(cols) >= 11:
            routes.append({
                "ipv4": cols[0],
                "hostname": cols[1],
                "next_hop_ipv4": cols[2],
                "next_hop_hostname": cols[3],
                "next_hop_lat": cols[4],
                "path_len": cols[5],
                "path_latency": cols[6],
                "next_hop_ipv4_lat_first": cols[7],
                "next_hop_hostname_lat_first": cols[8],
                "path_len_lat_first": cols[9],
                "path_latency_lat_first": cols[10],
            })
    return routes


def mask_content(text, public_ips, lan_cidr, lan_ip, et_ports):
    output = text
    for ip in public_ips:
        output = output.replace(ip, "[PUBLIC_IP]")
    if lan_cidr:
        output = output.replace(lan_cidr, "[LAN_CIDR]")
    if lan_ip:
        output = output.replace(lan_ip, "[LAN_IP]")
    for port in et_ports:
        output = output.replace(f":{port}", ":[ET_PORT]")
    return output


def collect(config):
    ok, output = run_cmd(config, ["peer"])
    if not ok:
        return None
    peers = parse_peer_table(output)
    if not peers:
        return None
    return peers, output


def detail(peer_raw, config):
    """Collect node/route detail only when the query API is requested."""
    ok_node, node_raw = run_cmd(config, ["node"])
    ok_route, route_raw = run_cmd(config, ["route"])
    if not (ok_node and ok_route and peer_raw):
        return False, None

    node_info, public_ips, lan_cidr, lan_ip, et_ports = parse_node_table(node_raw)
    route_list = parse_route_table(route_raw)

    if "Public IPv4" in node_info:
        node_info["Public IPv4"] = "[PUBLIC_IP]"
    if "Proxy CIDRs" in node_info:
        node_info["Proxy CIDRs"] = "[LAN_CIDR]"
    if "Interface IPv4" in node_info:
        node_info["Interface IPv4"] = "[LAN_IP]"
    for key in node_info:
        if key.startswith("Listener"):
            for port in et_ports:
                node_info[key] = node_info[key].replace(f":{port}", ":[ET_PORT]")

    return True, {
        "node_info": node_info,
        "route_list": route_list,
        "raw": {
            "peer": mask_content(peer_raw, public_ips, lan_cidr, lan_ip, et_ports),
            "node": mask_content(node_raw, public_ips, lan_cidr, lan_ip, et_ports),
            "route": mask_content(route_raw, public_ips, lan_cidr, lan_ip, et_ports),
        },
    }
