import hashlib
import hmac
import random
import socket
import string
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType

_MAX_HISTORY = 100


class AliDnsDDNS(_PluginBase):
    # ──────────────────────────────────────────────
    # 插件元数据
    # ──────────────────────────────────────────────
    plugin_name = "阿里云 DDNS"
    plugin_desc = "定时检测公网 IP，自动更新阿里云 DNS 解析记录，支持泛域名（* 记录）及 IPv6（AAAA）。"
    plugin_icon = "AliDnsDDNS.png"
    plugin_version = "1.0"
    plugin_author = "dtzsghnr"
    author_url = "https://github.com/dtzsghnr"
    plugin_config_prefix = "alidnsddns_"
    plugin_order = 30
    auth_level = 1

    # ──────────────────────────────────────────────
    # 私有状态
    # ──────────────────────────────────────────────
    _enabled: bool = False
    _access_key_id: str = ""
    _access_key_secret: str = ""
    _records: str = ""
    _interval: int = 5
    _notify: bool = True
    _run_once: bool = False

    _scheduler: Optional[BackgroundScheduler] = None
    _last_ipv4: str = ""
    _last_ipv6: str = ""

    # ──────────────────────────────────────────────
    # 生命周期
    # ──────────────────────────────────────────────

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled           = config.get("enabled", False)
            self._access_key_id     = config.get("access_key_id", "").strip()
            self._access_key_secret = config.get("access_key_secret", "").strip()
            self._records           = config.get("records", "").strip()
            self._interval          = max(1, int(config.get("interval", 5) or 5))
            self._notify            = config.get("notify", True)
            self._run_once          = config.get("run_once", False)

        self.stop_service()

        if not self._enabled:
            return

        record_count = len(_parse_records(self._records))
        logger.info(
            f"[AliDnsDDNS] 插件已启动 | 检测间隔: {self._interval}min | 记录数: {record_count}"
        )

        # 立即执行一次：用独立调度器触发，不与宿主调度器冲突
        if self._run_once:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.__update_dns,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="阿里云DDNS 立即执行",
            )
            self._scheduler.start()
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "access_key_id": self._access_key_id,
                "access_key_secret": self._access_key_secret,
                "records": self._records,
                "interval": self._interval,
                "notify": self._notify,
                "run_once": False,
            })

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"[AliDnsDDNS] 停止调度器失败: {e}")

    # ──────────────────────────────────────────────
    # 服务注册（宿主调度器）
    # ──────────────────────────────────────────────

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and self._interval:
            return [{
                "id": "AliDnsDDNS",
                "name": "阿里云 DDNS 更新",
                "trigger": IntervalTrigger(minutes=self._interval),
                "func": self.__update_dns,
                "kwargs": {},
            }]
        return []

    def get_command(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/alidnsddns/history",
                "endpoint": self.__api_history,
                "methods": ["GET"],
                "summary": "获取 DDNS 更新历史",
            },
            {
                "path": "/alidnsddns/history/clear",
                "endpoint": self.__api_clear_history,
                "methods": ["POST"],
                "summary": "清空 DDNS 更新历史",
            },
        ]

    # ──────────────────────────────────────────────
    # API
    # ──────────────────────────────────────────────

    def __api_history(self) -> List[dict]:
        return self.get_data("history") or []

    def __api_clear_history(self) -> dict:
        self.del_data("history")
        logger.info("[AliDnsDDNS] 更新历史已清空")
        return {"success": True}

    # ──────────────────────────────────────────────
    # 配置表单
    # ──────────────────────────────────────────────

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # ── 开关行 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify", "label": "IP 变化时发送通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "run_once", "label": "立即运行一次"},
                                }],
                            },
                        ],
                    },
                    # ── 密钥行 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "access_key_id",
                                        "label": "AccessKey ID",
                                        "placeholder": "LTAI5t...",
                                        "hint": "阿里云 RAM 访问密钥 ID",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "access_key_secret",
                                        "label": "AccessKey Secret",
                                        "placeholder": "xxxx...",
                                        "type": "password",
                                        "hint": "阿里云 RAM 访问密钥 Secret",
                                    },
                                }],
                            },
                        ],
                    },
                    # ── 间隔 ──
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12, "md": 4},
                            "content": [{
                                "component": "VTextField",
                                "props": {
                                    "model": "interval",
                                    "label": "检测间隔（分钟）",
                                    "type": "number",
                                    "placeholder": "5",
                                    "hint": "最小 1 分钟",
                                },
                            }],
                        }],
                    },
                    # ── 记录列表 ──
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [{
                                "component": "VTextarea",
                                "props": {
                                    "model": "records",
                                    "label": "DNS 记录列表",
                                    "rows": 6,
                                    "placeholder": (
                                        "格式：顶级域名 主机记录 类型（类型可省略默认A）\n"
                                        "example.com @ A        # example.com 根域 IPv4\n"
                                        "example.com * A        # *.example.com 泛域名 IPv4\n"
                                        "example.com home A     # home.example.com IPv4\n"
                                        "example.com home AAAA  # home.example.com IPv6"
                                    ),
                                    "hint": "第一列：阿里云注册的顶级域（如 example.com）；第二列：主机记录前缀（@ 根域 / * 泛域名 / 子域名前缀）",
                                    "persistent-hint": True,
                                },
                            }],
                        }],
                    },
                    # ── 说明 ──
                    {
                        "component": "VRow",
                        "content": [{
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [{
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": (
                                        "需要在阿里云 RAM 控制台为 AccessKey 授予 AliyunDNSFullAccess 权限。"
                                        "第一列必须是阿里云中托管的顶级域（如 example.com），第二列是主机记录前缀。"
                                        "更新 home.example.com 填：example.com home A。"
                                        "泛域名填 *，根域填 @，IPv6 类型填 AAAA。"
                                    ),
                                },
                            }],
                        }],
                    },
                ],
            }
        ], {
            "enabled": False,
            "access_key_id": "",
            "access_key_secret": "",
            "records": "",
            "interval": 5,
            "notify": True,
            "run_once": False,
        }

    # ──────────────────────────────────────────────
    # 详情页
    # ──────────────────────────────────────────────

    def get_page(self) -> List[dict]:
        history: List[dict] = self.get_data("history") or []

        if not history:
            return [{
                "component": "div",
                "props": {"class": "text-center pa-6 text-medium-emphasis"},
                "text": "暂无更新记录",
            }]

        history = sorted(history, key=lambda x: x.get("update_time", ""), reverse=True)

        return [{
            "component": "VDataTable",
            "props": {
                "headers": [
                    {"title": "域名",     "key": "fqdn",        "sortable": True},
                    {"title": "类型",     "key": "type",        "sortable": True,  "width": "80px"},
                    {"title": "IP 地址",  "key": "ip",          "sortable": False},
                    {"title": "更新时间", "key": "update_time", "sortable": True},
                ],
                "items": history,
                "density": "comfortable",
                "hover": True,
                "items-per-page": 20,
            },
        }]

    # ──────────────────────────────────────────────
    # 核心逻辑
    # ──────────────────────────────────────────────

    def __update_dns(self):
        if not self._access_key_id or not self._access_key_secret:
            logger.warning("[AliDnsDDNS] AccessKey 未配置，跳过本次检测")
            return

        parsed = _parse_records(self._records)
        if not parsed:
            logger.warning("[AliDnsDDNS] 记录列表为空，跳过本次检测")
            return

        need_v4 = any(r["type"] == "A"    for r in parsed)
        need_v6 = any(r["type"] == "AAAA" for r in parsed)

        ipv4 = _get_public_ip(v6=False) if need_v4 else None
        ipv6 = _get_public_ip(v6=True)  if need_v6 else None

        if need_v4 and not ipv4:
            logger.error("[AliDnsDDNS] 公网 IPv4 获取失败，跳过本次更新")
            return
        if need_v6 and not ipv6:
            logger.error("[AliDnsDDNS] 公网 IPv6 获取失败，跳过本次更新")
            return

        client   = _AliDnsClient(self._access_key_id, self._access_key_secret)
        updated: List[dict] = []
        now_str  = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")

        for rec in parsed:
            ip   = ipv4 if rec["type"] == "A" else ipv6
            fqdn = _fqdn(rec["rr"], rec["domain"])
            try:
                changed = client.upsert(rec["domain"], rec["rr"], rec["type"], ip)
                if changed:
                    updated.append({"fqdn": fqdn, "type": rec["type"],
                                    "ip": ip, "update_time": now_str})
                    logger.info(
                        f"[AliDnsDDNS] 记录已更新 | {fqdn} | {rec['type']} | {ip}"
                    )
                else:
                    logger.debug(
                        f"[AliDnsDDNS] 记录无变化 | {fqdn} | {rec['type']} | {ip}"
                    )
            except Exception as e:
                logger.error(
                    f"[AliDnsDDNS] 记录更新失败 | {fqdn} | {rec['type']} | 原因: {e}"
                )

        if ipv4:
            self._last_ipv4 = ipv4
        if ipv6:
            self._last_ipv6 = ipv6

        if not updated:
            return

        self.__save_history(updated)

        if self._notify:
            self.__send_notify(updated)

    def __save_history(self, new_items: List[dict]):
        history: List[dict] = self.get_data("history") or []
        history = (new_items + history)[:_MAX_HISTORY]
        self.save_data("history", history)

    def __send_notify(self, updated: List[dict]):
        blocks = []
        for item in updated:
            type_label = "IPv4" if item["type"] == "A" else "IPv6"
            blocks.append(f"{item['fqdn']}（{type_label}）\n{item['ip']}")

        text = "以下记录已同步新 IP：\n\n" + "\n\n".join(blocks) + "\n\n查看详情"

        self.post_message(
            mtype=NotificationType.Plugin,
            title="🌐 阿里云 DDNS 已更新",
            text=text,
        )


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _fqdn(rr: str, domain: str) -> str:
    return domain if rr == "@" else f"{rr}.{domain}"


def _parse_records(raw: str) -> List[Dict[str, str]]:
    """
    格式：顶级域名 主机记录 [类型]
    示例：
        example.com @ A
        example.com * A
        example.com home AAAA
    空行和 # 注释行会被跳过。
    """
    result = []
    for line in raw.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            logger.warning(f"[AliDnsDDNS] 忽略无效配置行: {line!r}")
            continue
        domain   = parts[0]
        rr       = parts[1]
        rec_type = parts[2].upper() if len(parts) >= 3 else "A"
        if rec_type not in ("A", "AAAA"):
            logger.warning(
                f"[AliDnsDDNS] 不支持的记录类型 {rec_type!r}，已跳过: {line!r}"
            )
            continue
        result.append({"domain": domain, "rr": rr, "type": rec_type})
    return result


def _get_public_ip(v6: bool = False) -> Optional[str]:
    """从多个公共端点轮询获取公网 IPv4 或 IPv6 地址，首个成功即返回。"""
    sources_v4 = [
        "https://api4.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://myexternalip.com/raw",
        "https://ipecho.net/plain",
    ]
    sources_v6 = [
        "https://api6.ipify.org",
        "https://ipv6.icanhazip.com",
        "https://6.ident.me",
    ]
    sources = sources_v6 if v6 else sources_v4
    validate = _is_valid_ipv6 if v6 else _is_valid_ipv4
    label = "IPv6" if v6 else "IPv4"

    for url in sources:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "MoviePilot-AliDnsDDNS/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                ip = resp.read(64).decode().strip()
            if validate(ip):
                logger.debug(f"[AliDnsDDNS] 检测到公网 {label}: {ip}（来源: {url}）")
                return ip
            logger.debug(f"[AliDnsDDNS] {url} 返回无效 {label}: {ip!r}")
        except Exception as e:
            logger.debug(f"[AliDnsDDNS] {label} 检测源不可用: {url} — {e}")

    logger.warning(f"[AliDnsDDNS] 所有 {label} 检测源均不可用")
    return None


def _is_valid_ipv4(ip: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except (OSError, socket.error):
        return False


def _is_valid_ipv6(ip: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return True
    except (OSError, socket.error):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 阿里云 DNS API 客户端（纯标准库）
# ──────────────────────────────────────────────────────────────────────────────

_ALIDNS_ENDPOINT = "https://alidns.aliyuncs.com/"


class _AliDnsClient:

    def __init__(self, key_id: str, key_secret: str):
        self._key_id     = key_id
        self._key_secret = key_secret

    # ── 签名 ─────────────────────────────────────

    @staticmethod
    def _percent_encode(s: str) -> str:
        e = urllib.parse.quote(s, safe="")
        return e.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")

    def _sign(self, params: Dict[str, str]) -> str:
        canonical = "&".join(
            f"{self._percent_encode(k)}={self._percent_encode(params[k])}"
            for k in sorted(params)
        )
        string_to_sign = "GET&%2F&" + self._percent_encode(canonical)
        mac = hmac.new(
            (self._key_secret + "&").encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        )
        return b64encode(mac.digest()).decode()

    def _base_params(self, action: str) -> Dict[str, str]:
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        return {
            "Action":           action,
            "Version":          "2015-01-09",
            "Format":           "JSON",
            "AccessKeyId":      self._key_id,
            "SignatureMethod":   "HMAC-SHA1",
            "SignatureVersion":  "1.0",
            "SignatureNonce":    nonce,
            "Timestamp":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _request(self, params: Dict[str, str]) -> dict:
        import json as _json
        params["Signature"] = self._sign(params)
        url = _ALIDNS_ENDPOINT + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": "MoviePilot-AliDnsDDNS/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            # 读取响应体以获取阿里云返回的详细错误信息
            try:
                err_body = _json.loads(e.read().decode())
                code = err_body.get("Code", str(e.code))
                msg  = err_body.get("Message", e.reason)
            except Exception:
                code, msg = str(e.code), e.reason
            raise RuntimeError(f"HTTP {e.code} — {code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络请求失败: {e.reason}") from e
        if body.get("Code"):
            raise RuntimeError(f"{body['Code']}: {body.get('Message', '')}")
        return body

    # ── CRUD ─────────────────────────────────────

    def _list_records(self, domain: str, rr: str, rec_type: str) -> List[dict]:
        p = self._base_params("DescribeDomainRecords")
        p.update({"DomainName": domain, "RRKeyWord": rr,
                  "TypeKeyWord": rec_type, "PageSize": "20"})
        return self._request(p).get("DomainRecords", {}).get("Record", [])

    def _add_record(self, domain: str, rr: str, rec_type: str, value: str):
        p = self._base_params("AddDomainRecord")
        p.update({"DomainName": domain, "RR": rr,
                  "Type": rec_type, "Value": value, "TTL": "600"})
        self._request(p)
        logger.info(f"[AliDnsDDNS] 新建 DNS 记录 | {_fqdn(rr, domain)} | {rec_type} | {value}")

    def _update_record(self, record_id: str, rr: str, rec_type: str,
                       value: str, domain: str = ""):
        p = self._base_params("UpdateDomainRecord")
        p.update({"RecordId": record_id, "RR": rr,
                  "Type": rec_type, "Value": value, "TTL": "600"})
        self._request(p)

    def upsert(self, domain: str, rr: str, rec_type: str, new_ip: str) -> bool:
        """
        创建或更新 DNS 记录，更新所有匹配的记录。
        返回 True 表示发生了变更，False 表示所有记录均已是最新值。
        """
        records = self._list_records(domain, rr, rec_type)
        # API RRKeyWord 是模糊匹配，需精确过滤
        matched = [r for r in records if r.get("RR") == rr and r.get("Type") == rec_type]

        if not matched:
            self._add_record(domain, rr, rec_type, new_ip)
            return True

        changed = False
        for rec in matched:
            if rec.get("Value") == new_ip:
                continue  # 该条已是最新，跳过
            self._update_record(rec["RecordId"], rr, rec_type, new_ip, domain)
            changed = True
        return changed
