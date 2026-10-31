#!/usr/bin/env python3
"""隧道状态采集与 Webhook 推送公共服务（tunnel_api）

本文件只处理与具体数据源无关的公共逻辑：
- 配置加载与校验
- 动态发现 providers/ 下的采集驱动
- 统一快照契约、seq 版本号、状态签名
- Webhook 推送、重试、退避、保活
- HTTP 查询接口与服务生命周期

具体采集逻辑分别放在 providers/<provider>.py。
新增驱动时只需新增一个模块文件，并实现模块接口；本文件无需修改。

驱动模块接口：
- DEFAULT_CONFIG: dict，驱动专属默认配置
- collect(config): 成功返回 (peer_list, raw)，失败返回 None
- validate_config(config): 可选，校验驱动配置
- configure(old, ask, integer, executable, tty): 可选，安装器交互配置入口
- detail(raw, config): 可选，返回 (ok, detail_dict)
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
import hmac
import hashlib
from collections import Counter
import importlib
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# ===================== 公共配置默认值 =====================
CORE_CONFIG_DEFAULTS = {
    "SECRET": "请修改为随机长字符串",
    "LISTEN_ADDR": "0.0.0.0",
    "LISTEN_PORT": 8080,
    "WEBHOOK_URL": "http://192.168.1.10:3001/api/v1/plugin/TunnelYield/webhook",
    "MP_API_KEY": "请填入MoviePilot的API_TOKEN",
    "SCAN_INTERVAL": 2,
    "KEEPALIVE_INTERVAL": 300,
    "ENABLE_QUERY_API": True,
    "WORK_MODE": "webhook",
    "ENABLED_PROVIDERS": [],
}
globals().update(CORE_CONFIG_DEFAULTS)
SEND_BACKOFF_MAX = 60
ERROR_LOG_INTERVAL = 60
SNAPSHOT_SCHEMA = 1
SECRET_HEADER = "X-Tunnel-Secret"


# ===================== 驱动模块自动发现 =====================
_PROVIDER_CACHE = {}


def list_providers():
    """扫描 providers/ 目录；每个合法的 .py 文件就是一个驱动。"""
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers")
    if not os.path.isdir(folder):
        return []
    names = []
    for filename in os.listdir(folder):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        name = filename[:-3]
        if re.fullmatch(r"[a-z][a-z0-9_]*", name):
            names.append(name)
    return sorted(names)


# 由配置/安装器明确选择来源；不默认启用全部驱动。
_available_provider_names = list_providers()
CORE_CONFIG_DEFAULTS["ENABLED_PROVIDERS"] = []
globals()["ENABLED_PROVIDERS"] = []


def get_provider_module(name=None):
    """按文件名加载驱动模块，不在公共框架中硬编码驱动列表。"""
    if name is None:
        enabled = globals().get("ENABLED_PROVIDERS", [])
        name = enabled[0] if enabled else None
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("驱动名称必须是合法模块名")
    if name not in list_providers():
        raise ValueError(f"未找到驱动 providers/{name}.py；可用驱动：{', '.join(list_providers())}")
    if name not in _PROVIDER_CACHE:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        module = importlib.import_module(f"providers.{name}")
        if not isinstance(getattr(module, "DEFAULT_CONFIG", None), dict):
            raise TypeError(f"驱动 {name} 缺少 DEFAULT_CONFIG 字典")
        if not callable(getattr(module, "collect", None)):
            raise TypeError(f"驱动 {name} 缺少 collect(config) 函数")
        _PROVIDER_CACHE[name] = module
    return _PROVIDER_CACHE[name]


def _all_config_defaults():
    """合并公共配置与所有已安装驱动的配置默认值。"""
    defaults = dict(CORE_CONFIG_DEFAULTS)
    for name in list_providers():
        driver_defaults = get_provider_module(name).DEFAULT_CONFIG
        overlap = set(defaults).intersection(driver_defaults)
        if overlap:
            raise ValueError(f"驱动 {name} 的配置名与公共配置重复：{', '.join(sorted(overlap))}")
        defaults.update(driver_defaults)
    return defaults


def runtime_config():
    """导出驱动运行配置；公共配置与驱动配置统一通过 dict 向驱动传递。"""
    defaults = _all_config_defaults()
    return {key: globals().get(key, value) for key, value in defaults.items()}


def validate_config(config):
    """校验公共配置，并委托所有启用驱动校验自己的配置。"""
    if not isinstance(config, dict):
        raise ValueError("配置必须为 JSON 对象")
    if config.get("WORK_MODE") not in ("webhook", "poll"):
        raise ValueError("WORK_MODE 仅支持 webhook / poll")
    poll = config["WORK_MODE"] == "poll"

    enabled = config.get("ENABLED_PROVIDERS")
    if (
        not isinstance(enabled, list)
        or not enabled
        or any(not isinstance(name, str) for name in enabled)
        or len(enabled) != len(set(enabled))
    ):
        raise ValueError("ENABLED_PROVIDERS 必须是非空且不重复的驱动名称数组")
    available = list_providers()
    unknown = [name for name in enabled if name not in available]
    if unknown:
        raise ValueError(
            "未找到驱动：" + ", ".join(unknown)
            + "；当前可用驱动：" + "/".join(available)
        )

    push_fields = ("WEBHOOK_URL", "MP_API_KEY")
    for name in ("SECRET", "LISTEN_ADDR", "WEBHOOK_URL", "MP_API_KEY"):
        value = config.get(name)
        if not isinstance(value, str):
            raise ValueError(f"{name} 必须为字符串")
        if not value.strip() and not (poll and name in push_fields):
            raise ValueError(f"{name} 必须为非空字符串")
    for name in ("SECRET", "MP_API_KEY"):
        if any(char in config[name] for char in "\r\n\0"):
            raise ValueError(f"{name} 不允许换行或 NUL")

    for name, low, high in (
        ("LISTEN_PORT", 1, 65535),
        ("SCAN_INTERVAL", 1, 3600),
        ("KEEPALIVE_INTERVAL", 60, 1500),
    ):
        value = config.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} 必须为 {low}..{high} 之间的整数")
    if type(config.get("ENABLE_QUERY_API")) is not bool:
        raise ValueError("ENABLE_QUERY_API 必须为布尔值")
    if poll and not config["ENABLE_QUERY_API"]:
        raise ValueError("WORK_MODE=poll 时必须开启查询接口 ENABLE_QUERY_API")

    if not poll or config["WEBHOOK_URL"].strip():
        url = urlparse(config["WEBHOOK_URL"])
        try:
            url.port
        except ValueError:
            raise ValueError("WEBHOOK_URL 端口无效") from None
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
        ):
            raise ValueError("WEBHOOK_URL 必须为无内嵌账户密码的 http/https 地址")

    # 仅校验启用的驱动；未启用驱动的配置保留在 JSON 中，供以后启用。
    for provider_name in enabled:
        driver = get_provider_module(provider_name)
        validator = getattr(driver, "validate_config", None)
        if callable(validator):
            validator(config)


def load_config(path):
    """读取安装器 JSON 配置；兼容旧版单 PROVIDER 配置。"""
    with open(path, "r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("配置必须为 JSON 对象")

    # 旧版只有 PROVIDER；升级时将其迁移为单元素列表，不改变旧部署行为。
    # Compatibility: the previous conservative build used a cache TTL.
    # These settings no longer affect publication or persistence.
    for obsolete in ("PROVIDER_CACHE_TTL", "PROVIDER_SAVE_INTERVAL"):
        config.pop(obsolete, None)
    legacy_provider = config.pop("PROVIDER", None)
    if "ENABLED_PROVIDERS" not in config and legacy_provider is not None:
        config["ENABLED_PROVIDERS"] = [legacy_provider]

    defaults = _all_config_defaults()
    if set(config) - set(defaults):
        raise ValueError("配置包含未知字段：" + ", ".join(sorted(set(config) - set(defaults))))
    merged = dict(defaults)
    merged.update(config)
    validate_config(merged)
    globals().update(merged)


def validate_runtime_config():
    """校验并规范化直接修改源码常量的运行配置。"""
    config = runtime_config()
    validate_config(config)
    globals().update(config)



_lock = threading.Lock()
_latest = None          # 最近一次成功采集的快照（含 seq/timestamp/peer_list/_peer_raw）
_collect_ok = False     # 最近一次采集是否成功（False 时查询接口按503处理）
_delivered = None       # 最近一次成功送达的签名（None = 尚未推送过）
_needs_confirm = False  # 是否存在未确认送达的推送（重启后置True，强制重推一次）
_seq = 0                # 当前已用到的快照版本号（仅使用 ≤ _seq_ceiling 的值）
_seq_ceiling = 0        # 已持久化预留的版本号上限（重启后从该值之上继续，绝不复用）
_last_push_ok = 0.0     # 最近一次确认送达的时间（保活重推计时）
_latest_at = 0.0        # 最近一次成功采集的时间（轮询方式下判断缓存是否过期）
_collect_fail_streak = 0
_send_fail_streak = 0
_next_send_at = 0.0
_last_error_log = 0.0

# 号段大小：一次预留约一天的采集量（2秒一轮），写盘频率≈每天一次，避免闪存磨损
SEQ_RESERVE = 50000

# 本轮数据只在内存保存；失败源不参与本轮快照，不借用历史节点状态。
_provider_states = {}
_provider_raw = {}
_provider_fail_log = {}
_last_cycle_successes = []
_last_cycle_failures = []
_provider_last_success = {}


def _seq_file() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tunnel_api_state.json")


def _load_seq():
    """
    启动时恢复版本号：读取单一权威状态文件中持久化的预留上限，从该值之上
    继续分配——任何对外可见过的版本号都 ≤ 持久化上限，因此重启绝不会复用
    版本号。状态文件不可读/被删除时：以当前时间（毫秒）为基准继续。此时无法
    绝对排除与历史版本重叠（会输出警告；接收端会忽略重叠版本直至超过历史值，
    配合重启强制重推机制可自愈），请勿删除该文件。
    恢复后立即预留下一号段（原子写）；预留失败时首轮采集会按失败处理
    （分配在写入成功前停止，不产生无保障的版本号）。
    """
    global _seq, _seq_ceiling
    try:
        with open(_seq_file(), "r", encoding="utf-8") as f:
            v = json.load(f).get("seq")
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            _seq = v
            _seq_ceiling = v
            _reserve_seq()
            return
    except (OSError, ValueError):
        pass
    base = int(time.time() * 1000)
    _seq = base
    _seq_ceiling = base
    print("[警告] seq状态文件不可用，以当前时间（毫秒）为基准继续；如非首次运行，"
          "请勿删除该文件（接收端会忽略重叠版本直至超过历史值）")
    _reserve_seq()


def _reserve_seq() -> bool:
    """
    预留下一号段：把新的版本号上限原子写入状态文件（临时文件+替换）。
    只有写入成功才允许使用超出旧上限的版本号（版本对外可见前必须已获持久化
    保障）；写入失败返回 False，调用方按采集失败处理，绝不带着无保障的版本号
    对外发送或答复查询。
    """
    global _seq_ceiling
    new_ceiling = _seq_ceiling + SEQ_RESERVE
    path = _seq_file()
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seq": new_ceiling}, f)
        os.replace(tmp, path)
    except OSError:
        # 单一权威路径写入失败：停止分配（调用方按采集失败处理），
        # 绝不带着无持久化保障的版本号继续
        return False
    _seq_ceiling = new_ceiling
    return True


def _next_seq():
    """
    分配下一个版本号（须在 _lock 内调用）。号段用尽时先原子预留新号段；
    预留失败返回 None——版本号无法获得持久化保障，本轮按采集失败处理。
    """
    global _seq
    if _seq + 1 > _seq_ceiling:
        if not _reserve_seq():
            return None
    _seq += 1
    return _seq



# ===================== 统一快照契约与驱动调度 =====================
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d+)?$")


def validate_peer_list(peers):
    """所有驱动共用的快照校验，失败时整份采集作废。"""
    if not isinstance(peers, list) or not peers:
        return False
    for peer in peers:
        if not isinstance(peer, dict):
            return False
        ipv4, hostname = peer.get("ipv4"), peer.get("hostname")
        if not isinstance(ipv4, str) or not isinstance(hostname, str):
            return False
        if ipv4 and not _IPV4_RE.match(ipv4):
            return False
        if not (ipv4.strip() or hostname.strip()):
            return False
        if type(peer.get("is_online")) is not bool:
            return False
    return True


def get_enabled_provider_names():
    """返回当前启用的驱动列表（保持配置顺序）。"""
    return list(ENABLED_PROVIDERS)


def validate_provider_peer_list(peers):
    """驱动级校验：必须返回非空列表，避免空快照被误解释为节点全部消失。"""
    return isinstance(peers, list) and bool(peers) and all(
        isinstance(peer, dict)
        and isinstance(peer.get("ipv4"), str)
        and isinstance(peer.get("hostname"), str)
        and (not peer["ipv4"] or _IPV4_RE.match(peer["ipv4"]))
        and bool(peer["ipv4"].strip() or peer["hostname"].strip())
        and type(peer.get("is_online")) is bool
        for peer in peers
    )


def get_provider():
    """兼容辅助入口：单驱动时返回该模块；多驱动时返回模块列表。"""
    modules = [get_provider_module(name) for name in get_enabled_provider_names()]
    return modules[0] if len(modules) == 1 else modules


def _node_key(provider, peer):
    return (provider, peer["ipv4"].split("/", 1)[0].strip(), peer["hostname"].strip())


def normalize_identities(peers):
    """本轮消歧，无磁盘注册表；冲突主机名加来源后缀，冲突IP不作为匹配键。"""
    rows = []
    seen = set()
    for peer in peers:
        item = dict(peer)
        provider = item.get("provider") or "unknown"
        key = _node_key(provider, item)
        _, ip, host = key
        if not (ip or host) or any(ord(c) < 32 for c in host):
            raise ValueError("节点身份为空或含控制字符")
        if key in seen:
            raise ValueError("同一来源存在完全重复节点身份")
        seen.add(key)
        base = host or ("node-" + ip.replace(".", "-"))
        base = base.replace(",", "_").replace("#", "_")
        rows.append((key, item, base))

    ip_counts = Counter(key[1] for key, _, _ in rows if key[1])
    host_counts = Counter(base for _, _, base in rows)
    reserved_ips = set(ip_counts)
    reserved_bases = {base for _, _, base in rows}
    used = set()
    output = []
    for key, item, base in sorted(rows, key=lambda row: row[0]):
        provider, ip, host = key
        candidate = base
        if host_counts[base] > 1 or candidate in reserved_ips:
            candidate = base + "--" + provider
        if candidate in used or candidate in reserved_ips or (candidate != base and candidate in reserved_bases):
            digest = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
            candidate = base + "--" + provider + "-" + digest
        suffix = 2
        original = candidate
        while candidate in used or candidate in reserved_ips or (candidate != base and candidate in reserved_bases):
            candidate = original + "-" + str(suffix)
            suffix += 1
        used.add(candidate)
        item["original_ipv4"] = item["ipv4"]
        item["original_hostname"] = item["hostname"]
        item["hostname"] = candidate
        item["ipv4"] = ip if ip and ip_counts[ip] == 1 else ""
        if candidate != host or (ip and not item["ipv4"]):
            item["identity_remapped"] = True
        output.append(item)
    # Mirror MP's shared IP / hostname index and assert no cross-node overwrite.
    index = {}
    for position, item in enumerate(output):
        for token in (item["ipv4"], item["hostname"]):
            if token and token in index and index[token] != position:
                raise ValueError("节点身份消歧后仍存在冲突")
            if token:
                index[token] = position
    return output


def collect_snapshot(persist=True):
    """只汇总本轮成功源；persist保留为旧安装器兼容参数，不写节点缓存。"""
    global _last_cycle_successes, _last_cycle_failures, _provider_states, _provider_raw
    config = runtime_config()
    enabled = get_enabled_provider_names()
    successes, failures = [], []
    states, raw_by_provider, drivers = {}, {}, {}

    def failed(name):
        failures.append(name)
        now = time.monotonic()
        last = _provider_fail_log.get(name)
        if last is None or now - last >= ERROR_LOG_INTERVAL:
            _provider_fail_log[name] = now
            print(f"[Provider失败] {name}：本轮剔除，下轮继续尝试")

    for name in enabled:
        try:
            drivers[name] = get_provider_module(name)
        except Exception:
            failed(name)

    with ThreadPoolExecutor(max_workers=max(1, len(drivers)), thread_name_prefix="tunnel-provider") as executor:
        futures = {name: executor.submit(driver.collect, config) for name, driver in drivers.items()}
        for name in enabled:
            if name not in futures:
                continue
            try:
                result = futures[name].result()
                if not isinstance(result, tuple) or len(result) != 2:
                    raise ValueError("invalid provider result")
                peers, raw = result
                if not validate_provider_peer_list(peers):
                    raise ValueError("invalid peer list")
                normalized = []
                keys = set()
                for peer in peers:
                    item = {
                        "ipv4": peer["ipv4"].split("/", 1)[0].strip(),
                        "hostname": peer["hostname"].strip(),
                        "is_online": peer["is_online"],
                        "provider": name,
                    }
                    key = _node_key(name, item)
                    if not (key[1] or key[2]) or any(ord(c) < 32 for c in key[2]) or key in keys:
                        raise ValueError("invalid or duplicate identity")
                    keys.add(key)
                    normalized.append(item)
                normalized.sort(key=lambda item: (item["ipv4"], item["hostname"]))
                stamp = int(time.time())
                states[name] = {"timestamp": stamp, "peer_list": normalized}
                raw_by_provider[name] = raw
                _provider_last_success[name] = stamp
                successes.append(name)
                if name in _provider_fail_log:
                    print(f"[Provider恢复] {name}：重新加入本轮快照")
                    _provider_fail_log.pop(name, None)
            except Exception:
                failed(name)

    _last_cycle_successes, _last_cycle_failures = successes, failures
    _provider_states, _provider_raw = states, raw_by_provider
    if not successes:
        return None
    peers = []
    for name in enabled:
        if name in states:
            peers.extend(states[name]["peer_list"])
    peers = normalize_identities(peers)
    return {
        "timestamp": int(time.time()),
        "peer_list": peers,
        "_peer_raw": dict(raw_by_provider),
        "_provider_timestamps": {name: state["timestamp"] for name, state in states.items()},
        "_successes": list(successes),
        "_failures": list(failures),
        "_last_success": dict(_provider_last_success),
    }


def public_snapshot(snapshot):
    """推送/查询共用的对外报文（剔除内部字段）。"""
    enabled = get_enabled_provider_names()
    return {
        "schema": SNAPSHOT_SCHEMA,
        "source": enabled[0] if len(enabled) == 1 else "multi",
        "seq": snapshot.get("seq"),
        "timestamp": snapshot.get("timestamp"),
        "peer_list": [dict(peer) for peer in snapshot["peer_list"]],
    }


def snapshot_signature(snapshot):
    """状态签名包含 Provider 来源，避免不同驱动的同名节点互相覆盖。"""
    return tuple(sorted(
        (
            p.get("provider", ""),
            p["ipv4"],
            p["hostname"],
            bool(p["is_online"]),
        )
        for p in snapshot["peer_list"]
    ))


def send_webhook(snapshot) -> bool:
    """
    推送快照到插件端点（只发送 seq/timestamp/peer_list，剔除内部字段）。
    送达标准：HTTP 200 且响应体业务 success 严格为 true（HTTP 200 不代表业务成功）。
    """
    try:
        payload = public_snapshot(snapshot)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            WEBHOOK_URL,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": MP_API_KEY,
                SECRET_HEADER: SECRET,
            },
        )
        with urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8") or "{}")
        return body.get("success") is True
    except Exception:
        return False


def _log_error(msg: str):
    """错误日志节流：连续失败时首条立即输出，其后按间隔输出"""
    global _last_error_log
    now = time.time()
    if _collect_fail_streak <= 1 or now - _last_error_log >= ERROR_LOG_INTERVAL:
        _last_error_log = now
        print(msg)


def _collect_and_publish():
    """采集全部 Providers、合并快照并分配一个全局 seq（须在 _lock 内调用）。"""
    global _latest, _collect_ok, _collect_fail_streak, _latest_at, _needs_confirm
    snapshot = collect_snapshot()
    if snapshot is None:
        _collect_ok = False
        _needs_confirm = True
        _collect_fail_streak += 1
        if _last_cycle_failures:
            reason = "失败驱动：" + ", ".join(_last_cycle_failures)
        else:
            reason = "没有可发布的完整汇总快照"
        _log_error(
            f"[采集失败] {reason}（连续 {_collect_fail_streak} 次），不推送新快照"
        )
        return None

    seq = _next_seq()
    if seq is None:
        _collect_ok = False
        _collect_fail_streak += 1
        _log_error("[seq预留失败] 无法持久化版本号上限，保留上一快照，不推送")
        return None

    _collect_ok = True
    _collect_fail_streak = 0
    snapshot["seq"] = seq
    _latest = snapshot
    _latest_at = time.time()
    return snapshot


def process_once():
    """本轮成功源合并推送；失败源剔除，全失败不推送，恢复后强制重新同步。"""
    global _latest, _collect_ok, _delivered, _needs_confirm, _seq
    global _collect_fail_streak, _send_fail_streak, _next_send_at, _last_push_ok
    to_send = None
    sig = None
    with _lock:
        # 采集在锁内（_collect_and_publish 与查询接口共用）：并发采集被串行化，
        # 采集顺序与版本分配顺序一致，旧采集结果不可能获得比新结果更高的
        # 版本并覆盖它；部分失败仍发布成功源，全失败撤销健康标记
        snapshot = _collect_and_publish()
        if snapshot is not None:
            sig = snapshot_signature(snapshot)
            now = time.time()
            need_keepalive = (
                KEEPALIVE_INTERVAL > 0
                and now - _last_push_ok >= KEEPALIVE_INTERVAL
            )
            # 签名变化 / 有未确认送达的推送 / 保活到期 才推送；
            # 退避期内不重试
            if WORK_MODE == "webhook" \
                    and (sig != _delivered or _needs_confirm or need_keepalive) \
                    and now >= _next_send_at:
                to_send = snapshot

    if to_send is not None and sig is not None:
        if send_webhook(to_send):
            with _lock:
                _delivered = sig
                _needs_confirm = False
                _last_push_ok = time.time()
            _send_fail_streak = 0
            print(f"[Webhook] 节点状态已送达 @{time.ctime()}")
        else:
            with _lock:
                _needs_confirm = True
            _send_fail_streak += 1
            backoff = min(2 ** min(_send_fail_streak, 6), SEND_BACKOFF_MAX)
            _next_send_at = time.time() + backoff
            _log_error(
                f"[推送失败] 将在 {backoff:.0f} 秒后以最新快照重试"
                f"（连续失败 {_send_fail_streak} 次）"
            )


def watch_loop():
    while True:
        try:
            process_once()
        except Exception as e:
            print(f"[异常] 采集/推送流程异常: {e}")
        time.sleep(SCAN_INTERVAL)


# ---------------- HTTP 查询接口 ----------------

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, code=200, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _write(self, code, obj):
        self._set_headers(code)
        self.wfile.write(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))

    def do_GET(self):
        global _latest, _collect_ok
        if not ENABLE_QUERY_API:
            self._write(404, {"error": "query api disabled"})
            return
        req_secret = self.headers.get(SECRET_HEADER) if self.headers is not None else None
        if not isinstance(req_secret, str) or not req_secret or not hmac.compare_digest(
            req_secret.encode("utf-8"), SECRET.encode("utf-8")
        ):
            self._write(403, {"error": "forbidden"})
            return

        with _lock:
            snapshot = _latest if _collect_ok else None
            if (
                WORK_MODE == "poll"
                and snapshot is not None
                and time.time() - _latest_at >= SCAN_INTERVAL
            ):
                # 轮询方式没有后台采集：缓存超过 SCAN_INTERVAL 秒即重新采集
                snapshot = None
        if snapshot is None:
            # 缓存不可用（尚未就绪或最近一次采集失败）：现场采集一次并如实报告；
            # 绝不把保留的旧缓存当作当前成功查询返回。采集在锁内，与采集循环
            # 共用 _collect_and_publish（采集顺序=版本顺序；任何失败都撤销
            # 健康标记，旧缓存保留但不服务）
            with _lock:
                snapshot = _collect_and_publish()
        if snapshot is None:
            self._write(503, {"error": "not ready: 最近一次采集失败，稍后重试"})
            return

        resp = public_snapshot(snapshot)
        provider_details = {}
        raw_by_provider = snapshot.get("_peer_raw") or {}
        config = runtime_config()
        for provider_name in get_enabled_provider_names():
            try:
                driver = get_provider_module(provider_name)
                detail_func = getattr(driver, "detail", None)
                raw = raw_by_provider.get(provider_name)
                if callable(detail_func) and raw is not None:
                    detail_ok, detail = detail_func(raw, config)
                    if detail_ok and isinstance(detail, dict):
                        provider_details[provider_name] = detail
                    elif not detail_ok:
                        provider_details[provider_name] = {"detail_error": "详情采集失败"}
            except Exception:
                provider_details[provider_name] = {"detail_error": "详情采集失败"}
        if provider_details:
            resp["provider_details"] = provider_details
        resp["provider_status"] = {
            name: {
                "last_success": snapshot.get("_last_success", {}).get(name),
                "collected_this_cycle": name in snapshot.get("_successes", []),
                "excluded_this_cycle": name in snapshot.get("_failures", []),
            }
            for name in get_enabled_provider_names()
        }
        self._write(200, resp)

    def log_message(self, format, *args):
        return


def _mask(value: str) -> str:
    return (value[:3] + "***") if value else "(未配置)"


if __name__ == "__main__":
    config_path = os.environ.get("TUNNEL_API_CONFIG")
    if config_path:
        load_config(config_path)
    # 同时覆盖直接修改源码常量、未使用外部 JSON 配置的运行方式。
    validate_runtime_config()
    if WORK_MODE == "poll" and not ENABLE_QUERY_API:
        raise SystemExit("WORK_MODE=poll 时必须开启查询接口 ENABLE_QUERY_API")
    _load_seq()
    t = None
    if WORK_MODE == "webhook":
        _needs_confirm = True  # 重启后强制重推一次当前状态，完成两端对齐
        t = threading.Thread(target=watch_loop, daemon=True)
        t.start()
        print(
            f"Tunnel API 已启动（工作方式: webhook），并发采集驱动: {', '.join(ENABLED_PROVIDERS)}，"
            f"采集间隔: {SCAN_INTERVAL}s"
        )
        print(f"推送目标: {WEBHOOK_URL}")
        print(f"通信密钥: {_mask(SECRET)} | MoviePilot API_KEY: {_mask(MP_API_KEY)}")
        print(f"保活重推间隔: {KEEPALIVE_INTERVAL}s")
    else:
        # 轮询方式：不启动采集推送线程，不发送任何 Webhook；查询时按需采集
        print(
            f"Tunnel API 已启动（工作方式: poll，仅查询、不推送），并发采集驱动: {', '.join(ENABLED_PROVIDERS)}，"
            f"查询缓存: {SCAN_INTERVAL}s"
        )
    if ENABLE_QUERY_API:
        print(f"查询接口: http://{LISTEN_ADDR}:{LISTEN_PORT}/（请求头 {SECRET_HEADER}）")
    try:
        if ENABLE_QUERY_API:
            server_address = (LISTEN_ADDR, LISTEN_PORT)
            httpd = HTTPServer(server_address, Handler)
            httpd.serve_forever()
        else:
            # 不开启查询接口时不绑定任何监听端口。
            while t.is_alive():
                t.join(timeout=60)
    except KeyboardInterrupt:
        pass
