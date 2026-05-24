import re
import socket
import ssl
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Dict, Any, Optional
from urllib.parse import urlparse

from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class MPServerStatus(_PluginBase):
    # 插件名称
    plugin_name = "MoviePilot服务监控"
    # 插件描述
    plugin_desc = "在仪表板中实时显示MoviePilot公共服务器状态。"
    # 插件图标
    plugin_icon = "Duplicati_A.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "MPServer_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enable: bool = False
    _server_base = "https://movie-pilot.org/status"
    _status_timeout = 20
    _network_timeout = 5
    _dns_cache_seconds = 60
    _tls_cache_seconds = 3600
    _last_sample: Optional[Dict[str, Any]] = None
    _dns_cache: Optional[Tuple[float, Dict[str, Any]]] = None
    _tls_cache: Optional[Tuple[float, Dict[str, Any]]] = None

    def init_plugin(self, config: dict = None):
        """
        初始化插件配置和运行时缓存。
        """
        config = config or {}
        self._enable = bool(config.get("enable"))
        self._last_sample: Optional[Dict[str, Any]] = None
        self._dns_cache: Optional[Tuple[float, Dict[str, Any]]] = None
        self._tls_cache: Optional[Tuple[float, Dict[str, Any]]] = None

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件远程命令定义。
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件开放 API 定义。
        """
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置表单。
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": self._enable,
        }

    def get_page(self) -> List[dict]:
        """
        获取插件详情页面。
        """
        if not self._enable:
            return [
                {
                    'component': 'div',
                    'text': '插件未启用',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        _, _, elements = self.get_dashboard()
        return elements

    def get_dashboard(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面。
        """
        cols = {
            "cols": 12,
            "md": 10
        }
        attrs = {
            "refresh": 10
        }

        response, seconds, request_error = self._request_server_status()
        probe = self._build_http_probe(response=response, seconds=seconds, request_error=request_error)
        dns_info = self._get_dns_info()
        tls_info = self._get_tls_info()

        if request_error or not response:
            elements = self._build_unavailable_elements(
                probe=probe,
                dns_info=dns_info,
                tls_info=tls_info,
                message=request_error or "无法连接服务器"
            )
            return cols, attrs, elements

        try:
            status = self._parse_status_text(response.text)
            metrics = self._build_metrics(status=status, seconds=seconds)
            elements = self._build_status_elements(
                metrics=metrics,
                probe=probe,
                dns_info=dns_info,
                tls_info=tls_info
            )
        except Exception as err:
            logger.warn(f"解析服务器状态失败：{err}")
            elements = self._build_unavailable_elements(
                probe=probe,
                dns_info=dns_info,
                tls_info=tls_info,
                message=f"服务器状态格式异常：{err}"
            )
        return cols, attrs, elements

    def get_state(self) -> bool:
        """
        返回插件启用状态。
        """
        return self._enable

    def stop_service(self):
        """
        停止插件服务。
        """
        pass

    def _request_server_status(self) -> Tuple[Optional[Any], float, Optional[str]]:
        """
        请求 MoviePilot 公开状态接口并返回响应、耗时和错误信息。
        """
        start_time = time.time()
        logger.info(f"请求服务器状态 {self._server_base}...")
        try:
            try:
                response = RequestUtils(timeout=self._status_timeout).get_res(self._server_base)
            except TypeError:
                response = RequestUtils().get_res(self._server_base)
        except Exception as err:
            seconds = time.time() - start_time
            logger.warn(f"请求服务器状态异常：{err}")
            return None, seconds, str(err)

        seconds = time.time() - start_time
        logger.info(f"请求耗时：{seconds:.3f}秒")
        if response is None:
            logger.warn("请求服务器状态失败：网络错误")
            return None, seconds, "网络错误"
        return response, seconds, None

    @staticmethod
    def _parse_status_text(text: str) -> Dict[str, int]:
        """
        解析 Nginx stub_status 文本。
        """
        lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
        active_match = re.search(r"Active connections:\s*(\d+)", "\n".join(lines), re.IGNORECASE)
        rw_match = re.search(
            r"Reading:\s*(\d+)\s+Writing:\s*(\d+)\s+Waiting:\s*(\d+)",
            "\n".join(lines),
            re.IGNORECASE
        )
        counter_values = None
        for index, line in enumerate(lines):
            if "server accepts" in line.lower() and index + 1 < len(lines):
                numbers = re.findall(r"\d+", lines[index + 1])
                if len(numbers) >= 3:
                    counter_values = [int(numbers[0]), int(numbers[1]), int(numbers[2])]
                    break
        if counter_values is None:
            for line in lines:
                numbers = re.findall(r"\d+", line)
                if len(numbers) == 3 and "Reading" not in line and "Writing" not in line:
                    counter_values = [int(numbers[0]), int(numbers[1]), int(numbers[2])]
                    break

        if not active_match:
            raise ValueError("缺少活跃连接数据")
        if not counter_values:
            raise ValueError("缺少连接计数数据")
        if not rw_match:
            raise ValueError("缺少读写等待数据")

        return {
            "active_connections": int(active_match.group(1)),
            "accepts": counter_values[0],
            "handled": counter_values[1],
            "requests": counter_values[2],
            "reading": int(rw_match.group(1)),
            "writing": int(rw_match.group(2)),
            "waiting": int(rw_match.group(3)),
        }

    def _build_metrics(self, status: Dict[str, int], seconds: float) -> Dict[str, Any]:
        """
        基于当前状态和上次采样值计算派生监控指标。
        """
        now = time.time()
        active_connections = status.get("active_connections", 0)
        accepts = status.get("accepts", 0)
        handled = status.get("handled", 0)
        total_requests = status.get("requests", 0)
        reading = status.get("reading", 0)
        writing = status.get("writing", 0)
        waiting = status.get("waiting", 0)
        busy = reading + writing
        dropped = max(accepts - handled, 0)

        metrics = {
            **status,
            "seconds": seconds,
            "busy": busy,
            "dropped": dropped,
            "busy_percent": self._safe_percent(busy, active_connections),
            "reading_percent": self._safe_percent(reading, active_connections),
            "writing_percent": self._safe_percent(writing, active_connections),
            "waiting_percent": self._safe_percent(waiting, active_connections),
            "dropped_percent": self._safe_percent(dropped, accepts),
            "requests_per_connection": self._safe_ratio(total_requests, handled),
            "requests_rate": None,
            "accepts_rate": None,
            "handled_rate": None,
            "sample_seconds": None,
        }

        if self._last_sample:
            sample_seconds = now - self._last_sample.get("timestamp", now)
            if sample_seconds > 0:
                metrics["sample_seconds"] = sample_seconds
                metrics["requests_rate"] = self._safe_delta_rate(
                    total_requests,
                    self._last_sample.get("requests", total_requests),
                    sample_seconds
                )
                metrics["accepts_rate"] = self._safe_delta_rate(
                    accepts,
                    self._last_sample.get("accepts", accepts),
                    sample_seconds
                )
                metrics["handled_rate"] = self._safe_delta_rate(
                    handled,
                    self._last_sample.get("handled", handled),
                    sample_seconds
                )

        self._last_sample = {
            "timestamp": now,
            "accepts": accepts,
            "handled": handled,
            "requests": total_requests,
        }
        return metrics

    def _build_http_probe(self, response: Optional[Any], seconds: float, request_error: Optional[str]) -> Dict[str, Any]:
        """
        从 HTTP 响应中提取可展示的服务探测信息。
        """
        headers = getattr(response, "headers", {}) or {}
        content = getattr(response, "content", b"") or b""
        text = getattr(response, "text", "") or ""
        status_code = getattr(response, "status_code", None)
        protocol = self._format_http_version(getattr(getattr(response, "raw", None), "version", None))
        content_bytes = len(content) if content else len(text.encode("utf-8"))

        return {
            "url": self._server_base,
            "host": urlparse(self._server_base).hostname or "-",
            "status_code": status_code,
            "ok": bool(status_code and 200 <= int(status_code) < 400 and not request_error),
            "seconds": seconds,
            "protocol": protocol,
            "server": headers.get("Server") or "-",
            "date": self._format_response_date(headers.get("Date")),
            "content_type": headers.get("Content-Type") or "-",
            "content_bytes": content_bytes,
            "error": request_error or "",
        }

    def _get_dns_info(self) -> Dict[str, Any]:
        """
        解析服务器域名并缓存短时间内的 DNS 探测结果。
        """
        now = time.time()
        if self._dns_cache and now - self._dns_cache[0] < self._dns_cache_seconds:
            return self._dns_cache[1]

        parsed = urlparse(self._server_base)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        start_time = time.time()
        try:
            address_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ips = []
            for address in address_info:
                ip = address[4][0]
                if ip not in ips:
                    ips.append(ip)
            info = {
                "host": host,
                "port": port,
                "ips": ips,
                "seconds": time.time() - start_time,
                "error": "",
            }
        except Exception as err:
            info = {
                "host": host,
                "port": port,
                "ips": [],
                "seconds": time.time() - start_time,
                "error": str(err),
            }

        self._dns_cache = (now, info)
        return info

    def _get_tls_info(self) -> Dict[str, Any]:
        """
        探测 HTTPS 证书信息并缓存较长时间的 TLS 结果。
        """
        parsed = urlparse(self._server_base)
        if parsed.scheme != "https":
            return {
                "enabled": False,
                "error": "",
            }

        now = time.time()
        if self._tls_cache and now - self._tls_cache[0] < self._tls_cache_seconds:
            return self._tls_cache[1]

        host = parsed.hostname or ""
        port = parsed.port or 443
        start_time = time.time()
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=self._network_timeout) as sock:
                with context.wrap_socket(sock, server_hostname=host) as tls_sock:
                    cert = tls_sock.getpeercert()
                    not_after = cert.get("notAfter")
                    expires_at = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    days_left = int((expires_at - datetime.now(timezone.utc)).total_seconds() // 86400)
                    info = {
                        "enabled": True,
                        "version": tls_sock.version() or "-",
                        "issuer": self._extract_certificate_name(cert.get("issuer")),
                        "subject": self._extract_certificate_name(cert.get("subject")),
                        "expires_at": expires_at.strftime("%Y-%m-%d %H:%M UTC"),
                        "days_left": days_left,
                        "seconds": time.time() - start_time,
                        "error": "",
                    }
        except Exception as err:
            info = {
                "enabled": True,
                "version": "-",
                "issuer": "-",
                "subject": "-",
                "expires_at": "-",
                "days_left": None,
                "seconds": time.time() - start_time,
                "error": str(err),
            }

        self._tls_cache = (now, info)
        return info

    @staticmethod
    def _extract_certificate_name(items: Any) -> str:
        """
        从证书 subject 或 issuer 元组中提取可读名称。
        """
        if not items:
            return "-"
        for group in items:
            for key, value in group:
                if key == "commonName":
                    return value
        for group in items:
            for _, value in group:
                if value:
                    return value
        return "-"

    def _build_status_elements(
            self,
            metrics: Dict[str, Any],
            probe: Dict[str, Any],
            dns_info: Dict[str, Any],
            tls_info: Dict[str, Any]
    ) -> List[dict]:
        """
        拼装状态正常时的仪表盘元素。
        """
        cards = [
            self._build_stat_card("HTTP状态", str(probe.get("status_code") or "-"), "mdi-web-check", "success",
                                  probe.get("protocol") or "-"),
            self._build_stat_card("响应延迟", self._format_seconds(probe.get("seconds")), "mdi-speedometer", "info",
                                  f"{self._format_size(probe.get('content_bytes', 0))} 响应"),
            self._build_stat_card("活跃连接", self._format_integer(metrics.get("active_connections")), "mdi-lan-connect",
                                  "primary", f"忙碌 {self._format_percent(metrics.get('busy_percent'))}"),
            self._build_stat_card("请求速率", self._format_rate(metrics.get("requests_rate"), "次/秒"),
                                  "mdi-chart-timeline-variant", "primary",
                                  self._format_sample_caption(metrics.get("sample_seconds"))),
            self._build_stat_card("连接速率", self._format_rate(metrics.get("accepts_rate"), "个/秒"),
                                  "mdi-connection", "info",
                                  self._format_sample_caption(metrics.get("sample_seconds"))),
            self._build_stat_card("等待连接", self._format_integer(metrics.get("waiting")), "mdi-timer-sand", "warning",
                                  f"{self._format_percent(metrics.get('waiting_percent'))} 空闲"),
            self._build_stat_card("处理中连接", self._format_integer(metrics.get("busy")), "mdi-swap-horizontal",
                                  "warning",
                                  f"读 {metrics.get('reading', 0)} / 写 {metrics.get('writing', 0)}"),
            self._build_stat_card("请求/连接", self._format_float(metrics.get("requests_per_connection")),
                                  "mdi-counter", "secondary", "累计均值"),
            self._build_stat_card("总请求数", self._format_integer(metrics.get("requests")),
                                  "mdi-format-list-numbered", "primary", "Nginx 累计"),
            self._build_stat_card("总连接数", self._format_integer(metrics.get("accepts")), "mdi-server-network",
                                  "primary", "Nginx 累计"),
            self._build_stat_card("丢弃连接", self._format_integer(metrics.get("dropped")), "mdi-alert-circle-outline",
                                  self._severity_color(metrics.get("dropped", 0), warning=1, error=10),
                                  self._format_percent(metrics.get("dropped_percent"))),
            self._build_stat_card("TLS证书", self._format_tls_days(tls_info), "mdi-shield-lock-outline",
                                  self._tls_color(tls_info), tls_info.get("expires_at") or "-"),
        ]

        return [
            self._build_summary_alert(probe=probe, message="服务状态正常", alert_type="success"),
            {
                'component': 'VRow',
                'content': cards + [
                    self._build_info_table(
                        title="连接明细",
                        rows=[
                            ("Reading", self._format_connection_detail(metrics.get("reading"),
                                                                      metrics.get("reading_percent"))),
                            ("Writing", self._format_connection_detail(metrics.get("writing"),
                                                                      metrics.get("writing_percent"))),
                            ("Waiting", self._format_connection_detail(metrics.get("waiting"),
                                                                      metrics.get("waiting_percent"))),
                            ("Handled", self._format_integer(metrics.get("handled"))),
                            ("Dropped", f"{self._format_integer(metrics.get('dropped'))} / "
                                        f"{self._format_percent(metrics.get('dropped_percent'))}"),
                        ]
                    ),
                    self._build_info_table(
                        title="服务探测",
                        rows=[
                            ("域名", f"{dns_info.get('host')}:{dns_info.get('port')}"),
                            ("解析IP", self._format_ips(dns_info.get("ips", []), dns_info.get("error"))),
                            ("DNS耗时", self._format_seconds(dns_info.get("seconds"))),
                            ("TLS版本", tls_info.get("version") or "-"),
                            ("证书签发", tls_info.get("issuer") or "-"),
                            ("服务时间", probe.get("date") or "-"),
                            ("Server", probe.get("server") or "-"),
                            ("Content-Type", probe.get("content_type") or "-"),
                        ]
                    )
                ]
            }
        ]

    def _build_unavailable_elements(
            self,
            probe: Dict[str, Any],
            dns_info: Dict[str, Any],
            tls_info: Dict[str, Any],
            message: str
    ) -> List[dict]:
        """
        拼装状态不可用或解析失败时的仪表盘元素。
        """
        return [
            self._build_summary_alert(probe=probe, message=message, alert_type="error"),
            {
                'component': 'VRow',
                'content': [
                    self._build_stat_card("HTTP状态", str(probe.get("status_code") or "-"), "mdi-web-cancel", "error",
                                          probe.get("error") or probe.get("protocol") or "-"),
                    self._build_stat_card("响应延迟", self._format_seconds(probe.get("seconds")),
                                          "mdi-speedometer-slow", "warning", "本次探测"),
                    self._build_stat_card("DNS解析", str(len(dns_info.get("ips", []))), "mdi-dns-outline",
                                          self._severity_color(len(dns_info.get("ips", [])), warning=1, error=0),
                                          self._format_ips(dns_info.get("ips", []), dns_info.get("error"))),
                    self._build_stat_card("TLS证书", self._format_tls_days(tls_info), "mdi-shield-lock-outline",
                                          self._tls_color(tls_info), tls_info.get("expires_at") or "-"),
                    self._build_info_table(
                        title="服务探测",
                        rows=[
                            ("地址", probe.get("url") or "-"),
                            ("域名", f"{dns_info.get('host')}:{dns_info.get('port')}"),
                            ("解析IP", self._format_ips(dns_info.get("ips", []), dns_info.get("error"))),
                            ("DNS耗时", self._format_seconds(dns_info.get("seconds"))),
                            ("TLS版本", tls_info.get("version") or "-"),
                            ("TLS错误", tls_info.get("error") or "-"),
                            ("Server", probe.get("server") or "-"),
                            ("Content-Type", probe.get("content_type") or "-"),
                        ],
                        md=12
                    )
                ]
            }
        ]

    @staticmethod
    def _build_summary_alert(probe: Dict[str, Any], message: str, alert_type: str) -> dict:
        """
        构建仪表盘顶部状态提示。
        """
        status_code = probe.get("status_code") or "-"
        return {
            'component': 'VAlert',
            'props': {
                'type': alert_type,
                'variant': 'tonal',
                'density': 'compact',
                'class': 'mb-3'
            },
            'text': f"{message} · HTTP {status_code} · {probe.get('host') or '-'}"
        }

    @staticmethod
    def _build_stat_card(label: str, value: str, icon: str, color: str, subtitle: str = "") -> dict:
        """
        构建单个统计指标卡片。
        """
        return {
            'component': 'VCol',
            'props': {
                'cols': 6,
                'md': 3
            },
            'content': [
                {
                    'component': 'VCard',
                    'props': {
                        'variant': 'tonal',
                    },
                    'content': [
                        {
                            'component': 'VCardText',
                            'props': {
                                'class': 'd-flex align-center justify-space-between ga-3'
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'span',
                                            'props': {
                                                'class': 'text-caption text-medium-emphasis'
                                            },
                                            'text': label
                                        },
                                        {
                                            'component': 'div',
                                            'props': {
                                                'class': 'text-h6'
                                            },
                                            'text': value
                                        },
                                        {
                                            'component': 'div',
                                            'props': {
                                                'class': 'text-caption text-medium-emphasis text-truncate'
                                            },
                                            'text': subtitle or "-"
                                        }
                                    ]
                                },
                                {
                                    'component': 'VIcon',
                                    'props': {
                                        'color': color,
                                        'size': '28'
                                    },
                                    'text': icon
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    @staticmethod
    def _build_info_table(title: str, rows: List[Tuple[str, str]], md: int = 6) -> dict:
        """
        构建键值详情表格。
        """
        return {
            'component': 'VCol',
            'props': {
                'cols': 12,
                'md': md
            },
            'content': [
                {
                    'component': 'VCard',
                    'props': {
                        'variant': 'tonal',
                    },
                    'content': [
                        {
                            'component': 'VCardTitle',
                            'props': {
                                'class': 'text-subtitle-1'
                            },
                            'text': title
                        },
                        {
                            'component': 'VTable',
                            'props': {
                                'hover': True,
                                'density': 'compact'
                            },
                            'content': [
                                {
                                    'component': 'tbody',
                                    'content': [
                                        {
                                            'component': 'tr',
                                            'content': [
                                                {
                                                    'component': 'td',
                                                    'props': {
                                                        'class': 'text-medium-emphasis text-no-wrap'
                                                    },
                                                    'text': label
                                                },
                                                {
                                                    'component': 'td',
                                                    'props': {
                                                        'class': 'text-end'
                                                    },
                                                    'text': value
                                                }
                                            ]
                                        } for label, value in rows
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    @staticmethod
    def _safe_percent(value: float, total: float) -> Optional[float]:
        """
        安全计算百分比。
        """
        if not total:
            return None
        return value / total * 100

    @staticmethod
    def _safe_ratio(value: float, total: float) -> Optional[float]:
        """
        安全计算比值。
        """
        if not total:
            return None
        return value / total

    @staticmethod
    def _safe_delta_rate(current: float, previous: float, seconds: float) -> Optional[float]:
        """
        安全计算两次采样之间的增长速率。
        """
        if seconds <= 0 or current < previous:
            return None
        return (current - previous) / seconds

    @staticmethod
    def _format_http_version(version: Optional[int]) -> str:
        """
        格式化 requests 原始 HTTP 协议版本。
        """
        if version == 10:
            return "HTTP/1.0"
        if version == 11:
            return "HTTP/1.1"
        if version == 20:
            return "HTTP/2"
        return "-"

    @staticmethod
    def _format_response_date(value: Optional[str]) -> str:
        """
        格式化 HTTP Date 响应头。
        """
        if not value:
            return "-"
        try:
            return parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            return value

    @staticmethod
    def _format_integer(value: Optional[float]) -> str:
        """
        格式化整数显示。
        """
        if value is None:
            return "-"
        return f"{int(value):,}"

    @staticmethod
    def _format_float(value: Optional[float], precision: int = 2) -> str:
        """
        格式化小数显示。
        """
        if value is None:
            return "-"
        return f"{value:.{precision}f}"

    @staticmethod
    def _format_percent(value: Optional[float]) -> str:
        """
        格式化百分比显示。
        """
        if value is None:
            return "-"
        return f"{value:.1f}%"

    @staticmethod
    def _format_seconds(value: Optional[float]) -> str:
        """
        格式化秒级耗时显示。
        """
        if value is None:
            return "-"
        if value < 1:
            return f"{value * 1000:.0f} ms"
        return f"{value:.2f} 秒"

    @staticmethod
    def _format_rate(value: Optional[float], unit: str) -> str:
        """
        格式化速率显示。
        """
        if value is None:
            return "待刷新"
        return f"{value:.2f} {unit}"

    @staticmethod
    def _format_sample_caption(value: Optional[float]) -> str:
        """
        格式化采样窗口说明。
        """
        if value is None:
            return "等待下一次采样"
        return f"{value:.1f} 秒窗口"

    @staticmethod
    def _format_size(value: int) -> str:
        """
        格式化字节大小显示。
        """
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value / 1024 / 1024:.1f} MB"

    @staticmethod
    def _format_ips(ips: List[str], error: Optional[str] = None) -> str:
        """
        格式化 DNS 解析 IP 列表。
        """
        if error:
            return error
        if not ips:
            return "-"
        suffix = " ..." if len(ips) > 3 else ""
        return f"{', '.join(ips[:3])}{suffix}"

    def _format_connection_detail(self, value: Optional[int], percent: Optional[float]) -> str:
        """
        格式化连接数量和占比详情。
        """
        return f"{self._format_integer(value)} / {self._format_percent(percent)}"

    @staticmethod
    def _format_tls_days(tls_info: Dict[str, Any]) -> str:
        """
        格式化 TLS 证书剩余天数。
        """
        if not tls_info.get("enabled"):
            return "未启用"
        if tls_info.get("error"):
            return "异常"
        days_left = tls_info.get("days_left")
        if days_left is None:
            return "-"
        return f"{days_left} 天"

    @staticmethod
    def _severity_color(value: float, warning: float, error: float) -> str:
        """
        根据阈值返回 Vuetify 颜色名称。
        """
        if error >= warning:
            if value >= error:
                return "error"
            if value >= warning:
                return "warning"
            return "success"
        if value <= error:
            return "error"
        if value <= warning:
            return "warning"
        return "success"

    @staticmethod
    def _tls_color(tls_info: Dict[str, Any]) -> str:
        """
        根据 TLS 证书状态返回 Vuetify 颜色名称。
        """
        if not tls_info.get("enabled"):
            return "secondary"
        if tls_info.get("error"):
            return "error"
        days_left = tls_info.get("days_left")
        if days_left is None or days_left < 7:
            return "error"
        if days_left < 30:
            return "warning"
        return "success"
