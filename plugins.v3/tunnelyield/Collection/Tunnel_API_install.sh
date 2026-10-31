#!/bin/sh
# 交互安装：sh Tunnel_API_install.sh [tunnel_api.py所在路径]
# 源码旁必须同时存在 providers/ 目录；安装/更新时合并驱动目录，保留自定义驱动。
# 仅安装本地配套源码，不从不明地址下载或执行代码。
# 安装完成后在终端输出一次 MoviePilot 插件需要填写的参数。
set -eu
umask 077
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

die() { printf '%s\n' "$*" >&2; exit 1; }
ask_yes() {
    printf '%s [y/N]: ' "$1" >/dev/tty
    IFS= read -r answer </dev/tty || return 1
    case "$answer" in y|Y|yes|YES) return 0;; *) return 1;; esac
}

[ "$(id -u)" -eq 0 ] || die "请使用 root 运行：sudo sh Tunnel_API_install.sh"
[ -r /dev/tty ] || die "需要交互终端，请直接运行脚本，不要通过管道执行。"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE=${1:-"$SCRIPT_DIR/tunnel_api.py"}
[ -f "$SOURCE" ] || die "未找到 $SOURCE，请将 tunnel_api.py 与安装脚本放在同一目录。"
LOCK=/tmp/tunnel-api-installer.lock
mkdir "$LOCK" 2>/dev/null || die "另一安装进程可能正在运行。确认没有后才删除 $LOCK"
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT HUP INT TERM

if [ -f /etc/openwrt_release ]; then
    PLATFORM=openwrt
    [ -f /etc/rc.common ] || die "未找到 OpenWrt rc.common/procd，停止安装。"
elif [ -f /etc/os-release ]; then
    # 仅解析发行版标识，不执行 os-release 内容。
    PLATFORM=$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"')
    case "$PLATFORM" in ubuntu|debian) PLATFORM=systemd;; *) die "仅支持 Ubuntu、Debian、OpenWrt。";; esac
    command -v systemctl >/dev/null 2>&1 || die "该环境没有 systemd（容器/WSL需单独配置），停止安装。"
    [ -d /run/systemd/system ] || die "systemd 未作为系统服务管理器运行，停止安装。"
else
    die "无法识别系统。"
fi
export PLATFORM

if ! command -v python3 >/dev/null 2>&1 ||
   ! python3 -c 'import sys; assert sys.version_info >= (3, 8); import json, ssl, urllib.request, http.server, subprocess, threading, termios, unicodedata' 2>/dev/null; then
    ask_yes "需要安装 Python3 标准库和 CA 证书，是否继续？（会访问系统软件源）" || die "已取消。"
    if [ "$PLATFORM" = systemd ]; then
        apt-get update
        apt-get install -y python3 ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        apk update
        apk add python3 python3-urllib python3-openssl ca-bundle
    elif command -v opkg >/dev/null 2>&1; then
        opkg update
        opkg install python3 python3-urllib python3-openssl ca-bundle
    else
        die "未找到 apk/opkg，无法安装依赖。"
    fi
fi
python3 -c 'import sys; assert sys.version_info >= (3, 8); import json, ssl, urllib.request, http.server, subprocess, threading, termios, unicodedata' ||
    die "Python3 版本或标准库不完整，请修复后重新执行。"
export PYTHONUNBUFFERED=1
python3 - "$SOURCE" <<'PY'
import ast
import atexit
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
from urllib.parse import urlparse, quote

platform = os.environ["PLATFORM"]
source = Path(sys.argv[1]).resolve()
provider_source = source.parent / "providers"
if not provider_source.is_dir() or not (provider_source / "__init__.py").is_file():
    raise SystemExit("未找到 providers/ 驱动目录；请将 providers 文件夹与 tunnel_api.py 放在同一目录。")
target = Path("/etc/tunnel-api" if platform == "openwrt" else "/opt/tunnel-api")
config_file = target / "config.json"
state_file = target / "tunnel_api_state.json"
unit = Path("/etc/init.d/tunnel-api" if platform == "openwrt"
            else "/etc/systemd/system/tunnel-api.service")
# 此辅助模块只供安装器使用；不改变采集主程序。
sys.path.insert(0, str(source.parent))
try:
    from installer_ui import TerminalUI, configure_provider, summary_text
except ImportError:
    raise SystemExit("缺少 installer_ui.py，请与安装脚本、tunnel_api.py 放在同一目录。")
terminal = TerminalUI()
# 旧驱动 configure() 的 tty.write 接口仍保留。
tty = open("/dev/tty", "w", encoding="utf-8", buffering=1)
atexit.register(tty.close)

def ask(label, default="", secret=False):
    return terminal.ask(label, default, secret=secret)


def integer(label, default, low, high):
    while True:
        value = ask(label, str(default))
        try:
            number = int(value)
            if low <= number <= high:
                return number
        except ValueError:
            pass
        tty.write(f"请输入 {low}..{high} 之间的整数。\n")


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".install-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def service(action, check=True, name="tunnel-api"):
    args = ([f"/etc/init.d/{name}", action] if platform == "openwrt"
            else ["systemctl", action, f"{name}.service"])
    return subprocess.run(args, check=check)


def read_seq_state(path):
    """读取 seq 状态文件；不存在返回 None，存在但无效则停止安装（避免丢失版本历史）"""
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or type(state.get("seq")) is not int or state["seq"] < 0:
        raise ValueError(f"{path} 的 seq 状态无效，停止安装，避免丢失版本历史")
    return state["seq"]


# 校验配套源码，且不执行来源文件来提取旧配置。
text = source.read_text(encoding="utf-8")
tree = ast.parse(text)
names = {node.name for node in tree.body
         if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
if not {"load_config", "get_provider_module", "list_providers", "collect_snapshot"} <= names:
    raise SystemExit("请使用模块化版本 tunnel_api.py（需支持 providers/ 驱动目录）。")
# 从源码目录加载公共框架，以便读取驱动清单、驱动默认配置及安装时配置入口。
sys.path.insert(0, str(source.parent))
spec = importlib.util.spec_from_file_location("tunnel_api_installer_check", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
provider_options = module.list_providers()
if not provider_options:
    raise SystemExit("providers/ 中没有可用驱动（需至少包含一个 .py 驱动文件）。")
old = {}
if config_file.exists():
    old = json.loads(config_file.read_text(encoding="utf-8"))
    if not isinstance(old, dict):
        raise SystemExit(f"{config_file} 不是 JSON 对象，停止安装，未改动服务。")

tty.write("\n隧道状态采集服务（tunnel-api）交互安装\n")
tty.write(f"系统：{platform}；安装目录：{target}；不会安装或修改隧道软件本身。\n")


mode = ask("工作方式（webhook = 推送，默认；poll = 仅供插件轮询，完全不推送）",
           old.get("WORK_MODE", "webhook"))
if mode not in ("webhook", "poll"):
    raise SystemExit("工作方式只能为 webhook 或 poll，已取消。")
poll = mode == "poll"
if poll:
    tty.write("轮询方式：不会询问推送相关配置，查询接口将强制开启；插件检测方式请选“轮询”。\n")


def executable(label, default, hint):
    while True:
        path = ask(label, default)
        if Path(path).is_absolute() and Path(path).is_file() and os.access(path, os.X_OK):
            return path
        tty.write(hint + "\n")


# 新安装展示所有可选来源；更新默认保留原启用列表。
old_enabled = old.get("ENABLED_PROVIDERS")
if not isinstance(old_enabled, list) or not old_enabled:
    legacy = old.get("PROVIDER")
    old_enabled = [legacy] if legacy in provider_options else provider_options
missing_existing = [name for name in old_enabled if name not in provider_options]
if config_file.exists() and missing_existing:
    raise SystemExit("更新包缺少原驱动：" + ", ".join(missing_existing) + "；请先复制其模块到本次providers目录。")
old_enabled = [name for name in old_enabled if name in provider_options]
if not old_enabled:
    old_enabled = provider_options
default_enabled = ",".join(old_enabled)
provider_text = ask(
    "启用采集驱动（多个用逗号分隔，可同时运行；可用：" + ", ".join(provider_options) + ")",
    default_enabled,
)
enabled_providers = list(dict.fromkeys(
    name.strip() for name in provider_text.split(",") if name.strip()
))
if not enabled_providers:
    raise SystemExit("至少选择一个采集驱动，已取消。")
unknown = [name for name in enabled_providers if name not in provider_options]
if unknown:
    raise SystemExit("以下驱动不存在于 providers/ 目录：" + ", ".join(unknown))

# 汇集全部驱动配置默认值，只交互配置当前启用的驱动。
provider_config = {}
for provider_name in provider_options:
    driver_module = module.get_provider_module(provider_name)
    for key, default_value in driver_module.DEFAULT_CONFIG.items():
        provider_config[key] = old.get(key, default_value)

previous_enabled = old.get("ENABLED_PROVIDERS") or ([old["PROVIDER"]] if old.get("PROVIDER") else [])
is_update = config_file.exists()
reconfigure = True
if is_update:
    choice = ask("重新填写驱动参数？y/n（n 保留原配置）", "n").lower()
    if choice not in ("y", "n"):
        raise SystemExit("只能输入 y 或 n，未修改原服务。")
    reconfigure = choice == "y"
configured = []
for provider_name in enabled_providers:
    driver = module.get_provider_module(provider_name)
    try:
        missing_fields = [key for key in driver.DEFAULT_CONFIG if key not in old]
        if reconfigure or provider_name not in previous_enabled or missing_fields:
            terminal.write("\n[" + provider_name + " 参数]\n")
            legacy_configure = getattr(driver, "configure", None)
            if hasattr(driver, "CONFIG_FIELDS") or not callable(legacy_configure):
                base = dict(module._all_config_defaults())
                base.update(old)
                base.update(provider_config)
                values = configure_provider(driver, old, base, terminal)
            else:
                # 未声明字段的旧自定义驱动继续沿用原交互钩子。
                values = legacy_configure(old, ask, integer, executable, tty)
                if not isinstance(values, dict):
                    raise ValueError("旧驱动configure必须返回字典")
                # 旧交互钩子遗漏新参数时，按DEFAULT_CONFIG自动补问。
                missing = {key: value for key, value in driver.DEFAULT_CONFIG.items() if key not in values}
                if missing:
                    base = dict(module._all_config_defaults())
                    base.update(old)
                    base.update(provider_config)
                    base.update(values)
                    proxy = types.SimpleNamespace(DEFAULT_CONFIG=missing)
                    values.update(configure_provider(proxy, old, base, terminal))
            if not isinstance(values, dict) or set(values) - set(driver.DEFAULT_CONFIG):
                raise ValueError("驱动配置返回未知字段")
            provider_config.update(values)
        configured.append(provider_name)
    except Exception as exc:
        if is_update and provider_name in previous_enabled:
            for key, value in driver.DEFAULT_CONFIG.items():
                provider_config[key] = old.get(key, value)
            configured.append(provider_name)
            terminal.write(f"{provider_name} 参数未更新，保留原值并继续校验。\n")
        else:
            terminal.write(f"{provider_name} 参数未完成，本次不启用。\n")
enabled_providers = configured
if not enabled_providers:
    raise SystemExit("没有完成配置的来源，未修改原服务。")

webhook_default = old.get("WEBHOOK_URL", "http://192.168.1.10:3001/api/v1/plugin/TunnelYield/webhook")
if poll:
    # 轮询方式不推送：保留旧推送配置（便于以后切回 webhook），不做询问
    # （旧值不合法时置空，避免校验失败）
    webhook = webhook_default if isinstance(old.get("WEBHOOK_URL"), str) else ""
    parsed = urlparse(webhook)
    if not (parsed.scheme in ("http", "https") and parsed.hostname
            and not parsed.username and not parsed.password):
        webhook = ""
    api_key = old.get("MP_API_KEY", "")
    if not isinstance(api_key, str) or any(c in api_key for c in "\r\n\0"):
        api_key = ""
else:
    while True:
        webhook = ask("MoviePilot Webhook 完整地址", webhook_default)
        parsed = urlparse(webhook)
        if (parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.fragment):
            try:
                parsed.port
                break
            except ValueError:
                pass
        tty.write("请输入合法的 http/https URL（不含账号密码或片段）。\n")
    if parsed.scheme == "http":
        tty.write("提示：http 会明文传输密钥，请仅在可信局域网使用；跨公网建议 HTTPS/VPN。\n")
    while True:
        api_key = ask("MoviePilot API_TOKEN（隐藏输入）", old.get("MP_API_KEY", ""), True)
        if api_key and not api_key.startswith("请"):
            break
        tty.write("API_TOKEN 不能为空或占位符。\n")
secret_default = old.get("SECRET", "")
if not isinstance(secret_default, str) or not secret_default or secret_default.startswith("请"):
    secret_default = secrets.token_urlsafe(32)
while True:
    shared_secret = ask("通信密钥（推送与查询共用；隐藏输入；首次回车自动生成）", secret_default, True)
    if shared_secret and not any(c in shared_secret for c in "\r\n\0"):
        break
    tty.write("通信密钥不能为空，且不能包含换行。\n")
if poll:
    enabled = True
else:
    query = ask("启用本地查询接口？y/n", "y" if old.get("ENABLE_QUERY_API", True) else "n")
    if query.lower() not in ("y", "n"):
        raise SystemExit("只能输入 y 或 n，已取消。")
    enabled = query.lower() == "y"
addr = old.get("LISTEN_ADDR", "0.0.0.0")
port = old.get("LISTEN_PORT", 8080)
if enabled:
    while True:
        addr = ask("监听地址（需让 MoviePilot 可访问；不自动修改防火墙）", addr)
        try:
            address = ipaddress.ip_address(addr)
            if address.version == 4:
                break
        except ValueError:
            pass
        tty.write("当前查询服务仅接受 IPv4 监听地址。\n")
    port = integer("查询接口端口", port, 1, 65535)
if poll:
    scan = integer("查询缓存秒数（距上次采集不足该秒数时直接返回缓存）",
                   old.get("SCAN_INTERVAL", 2), 1, 3600)
    keepalive = old.get("KEEPALIVE_INTERVAL", 300)
    # poll 方式不使用保活；旧值非法时回退 300，避免切回 webhook 前因校验失败中止
    if isinstance(keepalive, bool) or not isinstance(keepalive, int) or not 60 <= keepalive <= 1500:
        keepalive = 300
else:
    scan = integer("采集间隔秒数", old.get("SCAN_INTERVAL", 2), 1, 3600)
    keepalive_default = old.get("KEEPALIVE_INTERVAL", 300)
    if isinstance(keepalive_default, bool) or not isinstance(keepalive_default, int) \
            or not 60 <= keepalive_default <= 1500:
        keepalive_default = 300
    keepalive = integer("保活间隔秒数（60~1500，建议300；插件靠保活判断采集端是否在线）",
                        keepalive_default, 60, 1500)
cfg = {
    **provider_config,
    "ENABLED_PROVIDERS": enabled_providers,
    "WEBHOOK_URL": webhook, "MP_API_KEY": api_key, "SECRET": shared_secret,
    "ENABLE_QUERY_API": enabled, "LISTEN_ADDR": addr, "LISTEN_PORT": port,
    "SCAN_INTERVAL": scan, "KEEPALIVE_INTERVAL": keepalive, "WORK_MODE": mode,
}
# 每源独立校验/试采；已有来源暂时不可用时不静默删除。
valid_providers = []
for provider_name in enabled_providers:
    candidate = dict(cfg, ENABLED_PROVIDERS=[provider_name])
    try:
        module.validate_config(candidate)
        cfg.update({k: v for k, v in candidate.items() if k != "ENABLED_PROVIDERS"})
        valid_providers.append(provider_name)
    except Exception:
        if is_update and provider_name in previous_enabled:
            raise SystemExit(f"原来源 {provider_name} 配置无效，请修正或明确取消选择；未修改服务。")
        tty.write(f"{provider_name} 配置校验失败，本次不启用。\n")
if not valid_providers:
    raise SystemExit("没有有效来源，未修改服务。")
cfg["ENABLED_PROVIDERS"] = valid_providers
with tempfile.TemporaryDirectory() as directory:
    staged_cfg = Path(directory) / "config.json"
    staged_cfg.write_text(json.dumps(cfg), encoding="utf-8")
    module.load_config(str(staged_cfg))
    # 本补丁要求配套的可用性优先版核心；试采不会推送或分配seq。
    trial = module.collect_snapshot(persist=False)
    passed = list(module._last_cycle_successes)
    failed = list(module._last_cycle_failures)
if not passed or trial is None:
    raise SystemExit("所有来源试采失败，未修改原服务。")
if is_update:
    retained = [name for name in failed if name in previous_enabled]
    enabled_providers = [name for name in valid_providers if name in passed or name in retained]
else:
    enabled_providers = list(passed)
cfg["ENABLED_PROVIDERS"] = enabled_providers
module.ENABLED_PROVIDERS = list(enabled_providers)
if failed:
    tty.write("试采未通过：" + ", ".join(failed) + "；原来源保留重试，新来源不启用。\n")
healthy = True
if enabled:
    tty.write("不会自动开放端口；请只允许 MoviePilot 所在的可信网络访问。\n")
tty.write(f"\n即将写入 {target} 和 {unit}，启用开机自启并启动/重启服务。\n")
tty.write("现有程序/配置/服务文件会备份；不会删除或重置 seq 状态文件。\n")
if ask("确认安装/更新？输入 yes", "no") != "yes":
    raise SystemExit("已取消，未改动原程序和服务。")

target.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(target, 0o700)
backup = target / ("backup-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
backup.mkdir(mode=0o700)
for path in (target / "tunnel_api.py", target / "installer_ui.py", config_file, unit):
    if path.exists():
        shutil.copy2(path, backup / path.name)
        os.chmod(backup / path.name, 0o600)
if (target / "providers").is_dir():
    shutil.copytree(target / "providers", backup / "providers")
    for saved_file in (backup / "providers").rglob("*"):
        if saved_file.is_file():
            os.chmod(saved_file, 0o600)
was_installed = unit.exists()
if was_installed:
    service("stop")
python = shutil.which("python3")
try:
    atomic_write(target / "tunnel_api.py", text, 0o600)
    atomic_write(target / "installer_ui.py", (source.parent / "installer_ui.py").read_text(encoding="utf-8"), 0o600)
    installed_providers = target / "providers"
    # 合并驱动目录：更新内置驱动，但保留用户自行增加的 provider_x.py。
    shutil.copytree(
        provider_source,
        installed_providers,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for provider_file in installed_providers.rglob("*"):
        if provider_file.is_file():
            os.chmod(provider_file, 0o600)
    atomic_write(config_file, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", 0o600)
    # 继承版本上限：若曾在源码目录手动运行过采集端，取其与现有状态中的最大值，只增不减
    current = read_seq_state(state_file)
    candidates = [read_seq_state(path) for path in (
        source.with_name("tunnel_api_state.json"),
    )]
    candidates = [value for value in candidates if value is not None]
    if candidates and (current is None or max(candidates) > current):
        atomic_write(state_file, json.dumps({"seq": max(candidates)}), 0o600)
    if platform == "openwrt":
        unit_text = f"""#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1
start_service() {{
    procd_open_instance
    procd_set_param command "{python}" -u "{target}/tunnel_api.py"
    procd_set_param env TUNNEL_API_CONFIG="{config_file}"
    procd_set_param respawn 3600 5 5
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param file "{config_file}"
    procd_close_instance
}}
"""
        atomic_write(unit, unit_text, 0o755)
        service("enable")
        service("start")
        result = service("status", check=False)
        if result.returncode:
            raise RuntimeError("procd 服务未运行，请检查 logread -e tunnel")
    else:
        unit_text = f"""[Unit]
Description=Tunnel peer watcher (tunnel-api) and MoviePilot webhook
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Environment=TUNNEL_API_CONFIG={config_file}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WorkingDirectory={target}
ExecStart={python} -u {target}/tunnel_api.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
"""
        atomic_write(unit, unit_text, 0o644)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        service("enable")
        service("start")
        service("is-active")
    # 启动检查不等于推送送达检查，不发送测试 Webhook 以免误操作下载器。
except Exception as error:
    tty.write(f"安装/启动失败：{error}\n备份位于 {backup}，请检查日志后恢复。\n")
    raise SystemExit(1)


def local_ipv4s():
    """本机非回环 IPv4（用于提示插件 API 地址）；优先通往 MoviePilot 的出口地址"""
    found = []
    host = urlparse(webhook).hostname if webhook else None
    if host:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect((host, 9))  # UDP connect 不发送数据，只选路由
                found.append(probe.getsockname()[0])
            finally:
                probe.close()
        except OSError:
            pass
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                found.append(parts[parts.index("inet") + 1].split("/")[0])
    except Exception:
        pass
    result = []
    for value in found:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.version == 4 and not ip.is_loopback and value not in result:
            result.append(value)
    return result


# ---------------- 单次精简完成摘要 ----------------
api_url = ""
if enabled:
    hosts = [addr] if addr not in ("0.0.0.0", "::", "") else (local_ipv4s() or ["<采集端IP>"])
    host = hosts[0]
    if ":" in host:
        host = "[" + host + "]"
    api_url = f"http://{host}:{port}/"
terminal.write(summary_text(
    poll=poll, shared_secret=shared_secret, api_url=api_url,
    selected=enabled_providers, query_enabled=enabled,
    peers=(trial or {}).get("peer_list", []), config_file=config_file,
    platform=platform, unavailable=[name for name in failed if name in enabled_providers],
))
PY
