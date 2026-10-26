# -*- coding: utf-8 -*-
"""站点适配器基类。

统一实现：带凭据抓取（Cloudflare 仿真兜底、同站限速、登录态检测）、
用户 ID 三级解析（缓存 → Cookie → 站点首页）、种子详情页 hash 兜底解析。

站点/架构差异通过子类覆写钩子方法解决（client_table_locator、
leeching_url、torrent_row_parser、promotion_tags、parse_detail_hash 等），
新增站点适配只需在 adapters/sites/ 下加一个小文件并注册。
"""

import base64
import ipaddress
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from lxml import etree

from app.adapters.network.browser import PlaywrightHelper
from app.adapters.network.cloudflare import under_challenge
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils


class AdapterError(Exception):
    """站点采集失败，消息会进入采集结果的 errors 列表。"""


# IPv4 / IPv6 / 端口的粗判正则，精确校验用 ipaddress 模块
# 内嵌形式：IP 与地理位置等文本连写（无分隔符，如 "1.2.3.4克罗地亚"），不做词边界约束
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV4_EMBED_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_IPV6_EMBED_RE = re.compile(r"(?<![0-9A-Fa-f:.])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f])")
_PORT_RE = re.compile(r"^\d{1,5}$")
# NexusPHP 种子详情页里的 infohash
_HASH_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
_SIZE_RE = re.compile(r"([\d,.]+)\s*([KMGT]i?B|B)\b", re.IGNORECASE)
_SIZE_UNITS = {
    "B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
    "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4,
}


def parse_size(text: str) -> int:
    """把 '10.55 GB' 之类的文本解析为字节数，失败返回 0。"""
    if not text:
        return 0
    match = _SIZE_RE.search(str(text))
    if not match:
        return 0
    try:
        number = float(match.group(1).replace(",", ""))
        unit = match.group(2).upper()
        return int(number * _SIZE_UNITS.get(unit, 1))
    except (ValueError, KeyError):
        return 0


def classify_token(token: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    判断单个文本片段是否为 IP 地址。

    顺序：完整 IP 优先（v6 尾组 ≤4 位 hex 时是地址的一部分）；
    整体非法时再按 [v6]:port / ip:port 拆分（尾段 >4 位 hex 不可能是地址组，必为端口）。

    :return: (ip 类型: "ipv4"/"ipv6"/None, 规范化 IP 或 None, 端口或 None)
    """
    token = token.strip().strip("()，,;【】｜|")
    if not token or token.isdigit():
        return None, None, None
    # 整体是合法 IP
    try:
        ip = ipaddress.ip_address(token)
        return ("ipv6" if ip.version == 6 else "ipv4"), str(ip), None
    except ValueError:
        pass
    # [v6]:port / v4:port / v6:port
    bracket = re.match(r"^\[(.+)\](?::(\d{1,5}))?$", token)
    if bracket:
        candidate, port = bracket.group(1), bracket.group(2)
    else:
        pair = re.match(r"^(.+):(\d{1,5})$", token)
        if not pair:
            return None, None, None
        candidate, port = pair.group(1), pair.group(2)
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return None, None, None
    return ("ipv6" if ip.version == 6 else "ipv4"), str(ip), (int(port) if port else None)


def extract_ips(text: str) -> Tuple[List[str], List[str], Optional[int]]:
    """
    从任意文本中提取 IPv4 / IPv6 列表与端口。

    先按空白分词做精确匹配（可带端口），命不中时再用内嵌正则兜底
    （兼容 "IP+地理位置文本" 连写的站点，如 UBits）。

    :return: (ipv4 列表, ipv6 列表, 端口或 None)
    """
    ipv4s: List[str] = []
    ipv6s: List[str] = []
    port: Optional[int] = None
    for token in re.split(r"[\s,;|<>&]+", str(text or "")):
        kind, ip, token_port = classify_token(token)
        if kind == "ipv4":
            ipv4s.append(ip)
        elif kind == "ipv6":
            ipv6s.append(ip)
        if token_port and port is None:
            port = token_port
    if not ipv4s:
        for candidate in _IPV4_EMBED_RE.findall(str(text or "")):
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                continue
            ipv4s.append(candidate)
    if not ipv6s:
        for candidate in _IPV6_EMBED_RE.findall(str(text or "")):
            try:
                ip = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if ip.version == 6:
                ipv6s.append(str(ip))
    return ipv4s, ipv6s, port


def looks_like_agent(text: str) -> bool:
    """BT 客户端 UA 特征：ASCII、字母开头（排除纯 IP 单元格）、带 x.y 版本号、长度受限。"""
    text = str(text or "").strip()
    if not text or not text[0].isalpha():
        return False
    if len(text) > 100 or "\n" in text or not text.isascii():
        return False
    return bool(re.search(r"\d+(\.\d+)+", text))


class SiteAdapter:
    """站点适配器基类：抓取、限速、uid 解析统一实现，解析钩子可覆写。"""

    # 子类声明站点架构名称，用于日志
    schema_name = "base"
    # 抓取上限页数，防止翻页死循环
    max_pages = 10

    def __init__(self, site_info: Dict[str, Any], interval: int = 3, uid: Optional[str] = None):
        self.site = site_info or {}
        self.site_name = self.site.get("name")
        self.domain = str(self.site.get("domain") or "").lower()
        self.base_url = self.site.get("url")
        self.cookie = self.site.get("cookie")
        self.ua = self.site.get("ua")
        self.apikey = self.site.get("apikey")
        self.token = self.site.get("token")
        self.proxy = self.site.get("proxy")
        self.render = self.site.get("render")
        self.timeout = self.site.get("timeout") or 60
        self._interval = max(0, int(interval or 0))
        self._uid = str(uid) if uid else None
        self._last_request = 0.0

    # ------------------------------------------------------------------ 对外接口

    def has_credential(self) -> bool:
        """是否有可用凭据（Cookie 或 APIKEY）。"""
        return bool(self.cookie or self.apikey or self.token)

    def get_uid(self) -> Optional[str]:
        """解析当前用户 ID：缓存 → Cookie → 站点首页。"""
        if self._uid:
            return self._uid
        self._uid = self._uid_from_cookie() or self._uid_from_homepage()
        return self._uid

    def parse_clients(self, uid: str) -> List[Dict[str, Any]]:
        """解析站点 BT 客户端列表，子类实现。"""
        return []

    def parse_leeching(self, uid: str) -> List[Dict[str, Any]]:
        """解析下载中种子列表，子类实现。"""
        return []

    def parse_detail_hash(self, torrent_id: str) -> str:
        """
        从种子详情页解析 infohash（NexusPHP 默认实现），失败返回空串。
        """
        html = self._fetch(urljoin(self.base_url, f"details.php?id={torrent_id}"))
        if not html:
            return ""
        # 优先取 hash 关键词附近的 40 位 hex
        keyword = re.search(
            r"(?:info[_\s\-]?hash|hash)\D{0,40}?([0-9a-fA-F]{40})", html, re.IGNORECASE)
        if keyword and _valid_hash(keyword.group(1)):
            return keyword.group(1).lower()
        # 全文兜底
        for candidate in _HASH_RE.findall(html):
            if _valid_hash(candidate):
                return candidate.lower()
        return ""

    # ------------------------------------------------------------------ 抓取层

    def _throttle(self):
        """同站相邻请求限速。"""
        if self._interval <= 0:
            return
        wait = self._interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _request_utils(self, headers: Optional[Dict[str, str]] = None) -> RequestUtils:
        """构造带站点凭据的请求工具。"""
        return RequestUtils(
            ua=self.ua,
            cookies=self.cookie,
            headers=headers,
            proxies=settings.PROXY if self.proxy else None,
            timeout=self.timeout,
        )

    def _fetch(self, url: str, headers: Optional[Dict[str, str]] = None,
               method: str = "get", data=None, json_data=None) -> Optional[str]:
        """
        统一抓取入口：限速 → 请求 → Cloudflare 检测（render 站点浏览器仿真兜底）→ 文本。
        连接失败抛 AdapterError，返回 None 表示无有效内容。
        """
        self._throttle()
        proxies = settings.PROXY if self.proxy else None
        req = self._request_utils(headers)
        try:
            if method == "post":
                res = req.post_res(url=url, json=json_data, data=data)
            else:
                res = req.get_res(url=url)
        except Exception as err:
            raise AdapterError(f"请求失败: {err}") from err
        if res is None:
            raise AdapterError("无法访问站点")
        if res.status_code != 200:
            raise AdapterError(f"站点返回状态码 {res.status_code}")
        # 编码处理
        text = res.text
        if not re.search(r"charset=\"?utf-8\"?", text[:2000], re.IGNORECASE):
            try:
                res.encoding = res.apparent_encoding
                text = res.text
            except Exception:
                pass
        if not text:
            return None
        if under_challenge(text):
            if not self.render:
                raise AdapterError("站点被 Cloudflare 防护，请在站点设置开启浏览器仿真")
            page = PlaywrightHelper().get_page_source(
                url=url, cookies=self.cookie, ua=self.ua,
                proxies=settings.PROXY_SERVER if self.proxy else None, timeout=self.timeout)
            if not page or under_challenge(page):
                raise AdapterError("无法通过 Cloudflare 防护")
            return page
        # 登录页特征检测
        if self._is_login_page(text):
            raise AdapterError("Cookie 已失效或未登录")
        return text

    def fetch_index(self) -> Optional[str]:
        """
        抓取站点首页，处理 NexusPHP 常见反爬：
        1. 首次访问 window.location 二次跳转；
        2. 假首页（无 <link rel="search">/csrf-token）时重试 /index.php。
        """
        text = self._fetch(self.base_url)
        if not text:
            return None
        # 首次访问反爬：window.location 跳转
        if text.find("title") == -1:
            pos = text.find("window.location")
            if pos == -1:
                raise AdapterError("站点返回异常页面")
            redirect = text[pos:text.find(";", pos)] \
                .replace("\"", "").replace("+", "").replace(" ", "") \
                .replace("window.location=", "")
            text = self._fetch(self.base_url + redirect) or text
        # 假首页兜底
        if '"search"' not in text and '"csrf-token"' not in text \
                and not re.search(r"id=\"?root\"?", text, re.IGNORECASE):
            try:
                text = self._fetch(urljoin(self.base_url, "/index.php")) or text
            except AdapterError:
                pass
        return text

    # ------------------------------------------------------------------ uid 解析

    def _uid_from_cookie(self) -> Optional[str]:
        """从 NexusPHP 标准 Cookie c_secure_uid（base64）解析 uid。"""
        for part in str(self.cookie or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name.strip() != "c_secure_uid" or not value:
                continue
            raw = urllib.parse.unquote(value.strip())
            try:
                padded = raw + "=" * (-len(raw) % 4)
                decoded = base64.b64decode(padded).decode("utf-8", "ignore").strip()
            except Exception:
                continue
            if decoded.isdigit():
                return decoded
            match = re.search(r"(\d+)", decoded)
            if match:
                return match.group(1)
        return None

    def _uid_from_homepage(self) -> Optional[str]:
        """从站点首页的 userdetails 链接解析 uid。"""
        if not self.has_credential():
            raise AdapterError("站点未配置 Cookie/APIKEY")
        html = self.fetch_index()
        if not html:
            return None
        match = re.search(r"userdetails\.php\?id=(\d+)", html)
        if match:
            return match.group(1)
        # 兼容部分站点使用 /user/123 形式的链接
        match = re.search(r"(?:user|member)/(\d+)", html)
        return match.group(1) if match else None

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _is_login_page(html: str) -> bool:
        """登录页特征检测（跳转到 login.php 的响应）。"""
        if not html:
            return False
        head = html[:4000]
        if re.search(r"takelogin\.php", head):
            return True
        if re.search(r"<input[^>]+type=[\"']?password", head, re.IGNORECASE):
            return True
        return False


def _valid_hash(candidate: str) -> bool:
    """40 位 hex 且非全 0 / 全 f。"""
    lower = candidate.lower()
    return len(set(lower)) > 1 and set(lower) != {"f"}
