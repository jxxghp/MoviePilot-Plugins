# -*- coding: utf-8 -*-
"""NexusPHP 架构通用适配器（绝大多数 PT 站的默认兜底）。

数据来源：
- BT 客户端列表：用户详情页 userdetails.php?id=<uid> 中的客户端/连接信息表格；
- 下载中种子列表：getusertorrentlistajax.php?userid=<uid>&type=leeching（HTML 片段，
  兼容纯 HTML 与 JSON 包裹 rows 两种返回）。

站点模板差异通过覆写钩子（client_table_locator / torrent_row_parser /
promotion_tags / leeching_url 等）在 adapters/sites/ 下的小适配器中解决。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from lxml import etree

from app.sdk.logging import logger

from .base import (
    AdapterError,
    SiteAdapter,
    _PORT_RE,
    extract_ips,
    looks_like_agent,
    parse_size,
)

# NexusPHP 促销图标/字体 class → 标签
PROMO_CLASS_MAP = {
    "pro_free": ["Free"],
    "pro_free2up": ["Free", "2x"],
    "pro_free2up50pctdown": ["Free", "2x", "50%"],
    "pro_2up": ["2x"],
    "pro_50pctdown": ["50%"],
    "pro_50pctdown2up": ["50%", "2x"],
    "pro_30pctdown": ["30%"],
    "pro_30pctdown2up": ["30%", "2x"],
    "pro_70pctdown": ["70%"],
}

# 促销文字（alt/title/文本）→ 标签
PROMO_TEXT_MAP = {
    "free": ["Free"],
    "2xfree": ["Free", "2x"],
    "2xfree": ["Free", "2x"],
    "2x": ["2x"],
    "双倍": ["2x"],
    "免费": ["Free"],
    "免费双倍": ["Free", "2x"],
    "50%": ["50%"],
    "30%": ["30%"],
    "70%": ["70%"],
    "半价": ["50%"],
}

# 客户端表格表头列名（小写匹配）
_HEADER_AGENT_KEYS = ("client", "agent", "客户端", "peer", "useragent", "user-agent")
_HEADER_IPV4_KEYS = ("ip", "ipv4", "ip地址", "ip地址(ipv4)", "地址")
_HEADER_IPV6_KEYS = ("ipv6", "ipv6地址")
_HEADER_PORT_KEYS = ("port", "端口", "连接端口")


class NexusPhpAdapter(SiteAdapter):
    """NexusPHP 站点通用适配器。"""

    schema_name = "nexusphp"
    # 用户详情页/下载中列表端点，子类可覆写
    user_detail_page = "userdetails.php"
    leeching_page = "getusertorrentlistajax.php"

    # ------------------------------------------------------------------ 对外接口

    def parse_clients(self, uid: str) -> List[Dict[str, Any]]:
        """解析用户详情页的 BT 客户端表格。"""
        html = self._fetch(urljoin(self.base_url, f"{self.user_detail_page}?id={uid}"))
        if not html:
            return []
        tables = self.client_table_locator(html)
        clients: List[Dict[str, Any]] = []
        for table in tables:
            clients.extend(self.client_table_parse(table))
        return clients

    def parse_leeching(self, uid: str) -> List[Dict[str, Any]]:
        """翻页抓取下载中种子列表。"""
        torrents: List[Dict[str, Any]] = []
        seen_ids = set()
        url = self.leeching_url(uid, 0)
        for _ in range(self.max_pages):
            text = self._fetch(url)
            if not text:
                break
            fragment, total = self.extract_rows(text)
            page_rows = self.parse_torrent_rows(fragment)
            fresh = 0
            for row in page_rows:
                tid = str(row.get("id") or "")
                if not tid or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                torrents.append(row)
                fresh += 1
            next_url = self.next_page_url(text)
            if not next_url or fresh == 0 or (total and len(torrents) >= total):
                break
            url = next_url
        return torrents

    # ------------------------------------------------------------------ 钩子（站点小适配器覆写点）

    def client_table_locator(self, html: str) -> List[etree._Element]:
        """
        从用户详情页 HTML 定位客户端信息表格。

        默认策略：优先在最内层表格（无嵌套子表）中挑选「单元格命中 IP 特征」最多的表
        （至少 1 次）；整页只有一张大包装表时退化为在该表内挑选。
        """
        doc = etree.HTML(html)
        if doc is None:
            return []
        tables = doc.xpath("//table")
        innermost = [table for table in tables if not table.xpath(".//table")]
        candidates = innermost or tables
        best, best_hits = None, 0
        for table in candidates:
            hits = 0
            for cell in table.xpath(".//td | .//th"):
                ipv4s, ipv6s, _ = extract_ips(cell.xpath("string(.)"))
                hits += len(ipv4s) + len(ipv6s)
            if hits > best_hits:
                best, best_hits = table, hits
        return [best] if best is not None and best_hits > 0 else []

    def client_table_parse(self, table: etree._Element) -> List[Dict[str, Any]]:
        """把单个客户端表格解析为客户端列表（表头定位 + 逐单元格分类兜底）。"""
        rows = table.xpath(".//tr")
        if not rows:
            return []
        # 尝试表头定位列；定位失败说明首行就是数据行
        colmap = self._locate_columns(rows[0])
        data_rows = rows[1:] if colmap else rows
        clients: List[Dict[str, Any]] = []
        for row in data_rows:
            # 包装行（单元格内含子表格）跳过，避免整页文本混入
            if row.xpath(".//table"):
                continue
            cells = row.xpath("./td")
            if not cells:
                continue
            entry = {"agent": "", "ipv4": "", "ipv6": "", "port": None}
            used = set()
            if colmap:
                for key, idx in colmap.items():
                    if idx < len(cells) and idx not in used:
                        used.add(idx)
                        self._fill_client_cell(entry, key, cells[idx].xpath("string(.)"))
            # 表头定位不到的列逐单元格分类兜底
            for idx, cell in enumerate(cells):
                if idx in used:
                    continue
                self._fill_client_cell(entry, None, cell.xpath("string(.)"))
            if entry["agent"] or entry["ipv4"] or entry["ipv6"] or entry["port"]:
                clients.append(entry)
        return clients

    def leeching_url(self, uid: str, page: int = 0) -> str:
        """下载中列表页地址。"""
        url = urljoin(self.base_url, f"{self.leeching_page}?userid={uid}&type=leeching")
        if page:
            url += f"&page={page}"
        return url

    def parse_torrent_rows(self, fragment: str) -> List[Dict[str, Any]]:
        """解析种子列表 HTML 片段的行。"""
        if not fragment:
            return []
        doc = etree.HTML(f"<html><body><table>{fragment}</table></body></html>")
        if doc is None:
            return []
        # 按表头定位大小列
        size_col = self._locate_size_column(doc)
        torrents: List[Dict[str, Any]] = []
        for row in doc.xpath("//table//tr"):
            anchor = row.xpath('.//a[contains(@href, "details.php?id=")]')
            if not anchor:
                continue
            href = anchor[0].get("href") or ""
            id_match = re.search(r"details\.php\?id=(\d+)", href)
            if not id_match:
                continue
            name = "".join(anchor[0].xpath(".//text()")).strip() or (anchor[0].get("title") or "")
            entry = {
                "id": id_match.group(1),
                "name": name,
                "tags": self.promotion_tags(row),
                "size": 0,
                "hash": "",
            }
            cells = row.xpath("./td")
            if size_col is not None and size_col < len(cells):
                entry["size"] = parse_size(cells[size_col].xpath("string(.)"))
            else:
                # 兜底：找形如 10.5 GB 的单元格
                for cell in cells:
                    size = parse_size(cell.xpath("string(.)"))
                    if size:
                        entry["size"] = size
                        break
            torrents.append(entry)
        return torrents

    def promotion_tags(self, element: etree._Element) -> List[str]:
        """从种子行提取促销标签（pro_* class、alt/title、免费/2x 文字）。"""
        tags: List[str] = []
        # img/font/b/span 的 class
        for cls in element.xpath(".//img/@class | .//font/@class | .//b/@class | .//span/@class"):
            for token in str(cls).split():
                mapped = PROMO_CLASS_MAP.get(token.lower())
                if mapped:
                    tags.extend(mapped)
                elif token.lower().startswith("pro_"):
                    tags.append(token)
        # alt/title 文本
        for text in element.xpath(".//img/@alt | .//img/@title | .//font/text() | .//b/text()"):
            key = str(text).strip().lower()
            if key in PROMO_TEXT_MAP:
                tags.extend(PROMO_TEXT_MAP[key])
        # 行内文字兜底
        row_text = element.xpath("string(.)")
        for key in ("免费", "免费双倍", "双倍", "半价"):
            if key in row_text:
                tags.extend(PROMO_TEXT_MAP[key])
        # 去重保序
        return list(dict.fromkeys(tags))

    def extract_rows(self, text: str) -> Tuple[str, Optional[int]]:
        """
        处理 getusertorrentlistajax 返回：
        兼容纯 HTML 片段与 JSON 包裹（{"total": N, "rows": "<tr>.."}）两种格式。

        :return: (行的 HTML 片段, 总数或 None)
        """
        text = str(text or "").replace(r"\/", "/").strip()
        if text.startswith("{"):
            try:
                payload = json.loads(text)
                rows = payload.get("rows") if isinstance(payload, dict) else None
                if isinstance(rows, str):
                    total = payload.get("total")
                    return rows, int(total) if total else None
                if isinstance(rows, list):  # 个别站直接返回行数组
                    total = payload.get("total")
                    return "".join(str(r) for r in rows), int(total) if total else None
            except (ValueError, TypeError, AttributeError):
                pass
        return text, None

    def next_page_url(self, text: str) -> Optional[str]:
        """从列表片段中提取下一页链接（绝对或相对），没有则 None。"""
        text = str(text or "").replace(r"\/", "/")
        doc = etree.HTML(f"<html><body><div>{text}</div></body></html>")
        if doc is None:
            return None
        for href in doc.xpath('//a[contains(.//text(), "下一页") or contains(.//text(), "下一頁") '
                              'or contains(.//text(), ">")]/@href'):
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return urljoin(self.base_url, href)
            return urljoin(self.base_url, "/" + href)
        return None

    # ------------------------------------------------------------------ 内部工具

    @staticmethod
    def _fill_client_cell(entry: Dict[str, Any], key: Optional[str], text: str) -> None:
        """把一个单元格的内容按已知列语义/内容特征填进客户端条目。"""
        text = str(text or "").strip()
        if not text:
            return
        # agent 特征优先：版本号（如 3.6.0.0）与 IPv4 字面量无法区分，
        # 命中 agent 特征的单元格整格作为 agent，不再提取其中的 IP
        if key == "agent" or (key is None and looks_like_agent(text)):
            if not entry["agent"]:
                entry["agent"] = " ".join(text.split())
            return
        ipv4s, ipv6s, port = extract_ips(text)
        if ipv4s and not entry["ipv4"]:
            entry["ipv4"] = ipv4s[0]
        if ipv6s and not entry["ipv6"]:
            entry["ipv6"] = ipv6s[0]
        if port and entry["port"] is None:
            entry["port"] = port
        elif _PORT_RE.match(text) and text.isdigit() and int(text) <= 65535 \
                and entry["port"] is None:
            # 独立端口单元格（有无表头均适用）
            entry["port"] = int(text)

    @staticmethod
    def _locate_columns(header_row: etree._Element) -> Dict[str, int]:
        """按表头文本定位 agent/ipv4/ipv6/port 列索引。"""
        cells = header_row.xpath("./th | ./td")
        colmap: Dict[str, int] = {}
        for idx, cell in enumerate(cells):
            text = "".join(cell.xpath(".//text()")).strip().lower()
            if not text:
                continue
            if any(k in text for k in _HEADER_IPV6_KEYS):
                colmap.setdefault("ipv6", idx)
            elif any(k in text for k in _HEADER_IPV4_KEYS):
                colmap.setdefault("ipv4", idx)
            elif any(k in text for k in _HEADER_PORT_KEYS):
                colmap.setdefault("port", idx)
            elif any(k in text for k in _HEADER_AGENT_KEYS):
                colmap.setdefault("agent", idx)
        return colmap if len(colmap) >= 2 else {}

    @staticmethod
    def _locate_size_column(doc: etree._Element) -> Optional[int]:
        """按表头定位大小列（'大小' / img.alt=size）。"""
        for row in doc.xpath("//table//tr[position()=1]"):
            for idx, cell in enumerate(row.xpath("./td | ./th")):
                texts = [t.strip().lower() for t in cell.xpath(".//text()")]
                alts = [a.strip().lower() for a in cell.xpath(".//img/@alt | .//img/@class")]
                if any(t in texts for t in ("大小", "大小)", "size")) or "size" in alts:
                    return idx
        return None
