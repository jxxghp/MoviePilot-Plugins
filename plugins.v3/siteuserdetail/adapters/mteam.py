# -*- coding: utf-8 -*-
"""M-Team（馒头）API 型站点适配器（x-api-key 认证）。

数据来源（M-Team openapi，api.<注册域> 域名 + x-api-key 请求头）：
- 用户 ID：POST api/member/profile（不带 uid 返回本人）；
- BT 客户端列表：POST api/tracker/myPeerStatus；
- 下载中种子列表：POST api/member/getUserTorrentList（type=INCOMPLETE，翻页）。

注意：字段结构以实际响应为准，M-Team myPeerStatus 的 peers 明细字段
在 MoviePilot 生态内无先例可参考，本适配器采用防御式映射，
实测后如字段名不同只需调整本文件的映射常量。
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils

from .base import AdapterError, SiteAdapter

# M-Team 优惠字段（discount）→ 促销标签片段
_DISCOUNT_TOKENS = (
    ("FREE", "Free"),
    ("2XFREE", "Free+2x"),
    ("PERCENT_50", "50%"),
    ("PERCENT_30", "30%"),
    ("PERCENT_70", "70%"),
    ("2X", "2x"),
)

# peers 明细中可能的列表字段名（按顺序探测）
_PEER_LIST_KEYS = ("peers", "list", "rows", "data", "items")
# 单个 peer 中可能的字段名
_PEER_AGENT_KEYS = ("agent", "client", "userAgent", "peerAgent")
_PEER_IPV4_KEYS = ("ip", "ipv4", "ipV4", "address")
_PEER_IPV6_KEYS = ("ipv6", "ipV6", "address6")
_PEER_PORT_KEYS = ("port", "connectPort", "listenPort")


class MTeamAdapter(SiteAdapter):
    """M-Team 站点适配器。"""

    schema_name = "mteam"
    # 下载中列表的 type 参数（M-Team：SEEDING=做种，INCOMPLETE=下载中）
    leeching_type = "INCOMPLETE"
    page_size = 100

    def __init__(self, site_info: Dict[str, Any], interval: int = 3, uid: Optional[str] = None):
        super().__init__(site_info, interval=interval, uid=uid)
        # API 域名固定为 api.<注册域>
        self.api_base = f"https://api.{StringUtils.get_url_domain(self.base_url)}"

    def has_credential(self) -> bool:
        return bool(self.apikey)

    # ------------------------------------------------------------------ 对外接口

    def get_uid(self) -> Optional[str]:
        """POST api/member/profile 取本人用户 ID。"""
        if self._uid:
            return self._uid
        if not self.has_credential():
            raise AdapterError("站点未配置 APIKEY")
        data = self._api_post("api/member/profile", {})
        member = data or {}
        uid = member.get("id") or member.get("uid") or member.get("memberId")
        if uid:
            self._uid = str(uid)
        return self._uid

    def parse_clients(self, uid: str) -> List[Dict[str, Any]]:
        """POST api/tracker/myPeerStatus 取当前活动客户端。"""
        try:
            data = self._api_post("api/tracker/myPeerStatus", {"uid": int(uid)})
        except AdapterError as err:
            logger.warning(f"【{self.site_name}】获取客户端信息失败: {err}")
            return []
        peers = None
        if isinstance(data, list):
            peers = data
        elif isinstance(data, dict):
            for key in _PEER_LIST_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    peers = value
                    break
        clients: List[Dict[str, Any]] = []
        for peer in peers or []:
            if not isinstance(peer, dict):
                continue
            agent = next((str(peer[k]) for k in _PEER_AGENT_KEYS if peer.get(k)), "")
            ipv4 = next((str(peer[k]) for k in _PEER_IPV4_KEYS if peer.get(k)), "")
            ipv6 = next((str(peer[k]) for k in _PEER_IPV6_KEYS if peer.get(k)), "")
            port = next((peer[k] for k in _PEER_PORT_KEYS if peer.get(k) is not None), None)
            if agent or ipv4 or ipv6 or port:
                clients.append({
                    "agent": agent,
                    "ipv4": "" if ":" in ipv4 and "." not in ipv4 else ipv4,
                    "ipv6": ipv6,
                    "port": int(port) if port else None,
                })
        if peers is None and data:
            # 响应无 peers 明细：记录结构便于后续适配
            logger.debug(f"【{self.site_name}】myPeerStatus 响应无 peers 明细: {list(data)[:20]}")
        return clients

    def parse_leeching(self, uid: str) -> List[Dict[str, Any]]:
        """POST api/member/getUserTorrentList 取正在下载的种子（type=INCOMPLETE）。

        响应结构（oes v3.1.5 实测）：
        data = {"pageNumber", "pageSize", "total", "totalPages", "data": [
            {"torrent": {"id", "name", "smallDescr", "size", "infoHash",
                         "status": {"discount": "FREE"/"PERCENT_50"/"_2X"...}}, "peer": ...}]}

        注意：M-Team 的 INCOMPLETE 是**历史未完成**列表（含客户端已删除的种子），
        行内 peer 非空才代表当前正在下载。先取 myPeerStatus.leecher（活动下载数）：
        为 0 直接返回空，>0 时翻页收集到该数量即止。若响应行均无 peer 字段
        （API 结构变化），回退为返回全部行。
        """
        # 活动下载数（权威计数，兼作翻页上限）
        leecher_count = None
        try:
            peer_status = self._api_post("api/tracker/myPeerStatus", {"uid": int(uid)}) or {}
            leecher_count = int(peer_status.get("leecher") or 0)
        except (AdapterError, TypeError, ValueError):
            leecher_count = None
        if leecher_count == 0:
            return []
        torrents: List[Dict[str, Any]] = []
        page = 0
        for _ in range(self.max_pages):
            page += 1
            try:
                payload = self._api_post("api/member/getUserTorrentList", {
                    "pageNumber": page,
                    "pageSize": self.page_size,
                    "type": self.leeching_type,
                    "userid": int(uid),
                })
            except AdapterError as err:
                logger.warning(f"【{self.site_name}】获取下载中种子失败: {err}")
                break
            payload = payload or {}
            rows = payload.get("data") or payload.get("rows") or []
            if not rows:
                break
            has_peer_field = any("peer" in row for row in rows if isinstance(row, dict))
            for row in rows:
                if not isinstance(row, dict):
                    continue
                # 历史未完成（peer 为空）不算正在下载
                if has_peer_field and not row.get("peer"):
                    continue
                torrent = row.get("torrent") or row
                tid = torrent.get("id")
                if not tid:
                    continue
                status = torrent.get("status") or {}
                discount = status.get("discount") if isinstance(status, dict) \
                    else torrent.get("discount")
                torrents.append({
                    "id": str(tid),
                    "name": str(torrent.get("name") or torrent.get("smallDescr") or "").strip(),
                    "tags": self._discount_tags(discount),
                    "size": int(torrent.get("size") or 0),
                    "hash": str(torrent.get("infoHash") or torrent.get("hash") or "").lower(),
                })
            total = int(payload.get("total") or 0)
            if (total and len(torrents) >= total) or \
                    (leecher_count is not None and len(torrents) >= leecher_count):
                break
        return torrents

    def parse_detail_hash(self, torrent_id: str) -> str:
        """M-Team 无公开的种子 infohash 查询接口，返回空串（由下载器匹配兜底）。"""
        return ""

    # ------------------------------------------------------------------ 内部工具

    def _api_post(self, path: str, payload: Dict[str, Any]) -> Any:
        """
        POST M-Team openapi，返回 data 字段；认证/接口失败抛 AdapterError。
        """
        if not self.apikey:
            raise AdapterError("站点未配置 APIKEY")
        self._throttle()
        # M-Team WAF 拦截非浏览器 UA，站点未配置 UA 时用标准浏览器 UA 兜底
        ua = self.ua or ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        res = RequestUtils(
            headers={
                "x-api-key": self.apikey,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            ua=ua,
            proxies=settings.PROXY if self.proxy else None,
            timeout=self.timeout,
        ).post_res(url=urljoin(self.api_base, path), json=payload)
        if res is None:
            raise AdapterError("API 无法访问")
        if res.status_code != 200:
            raise AdapterError(f"API 返回状态码 {res.status_code}")
        try:
            payload_json = json.loads(res.text)
        except ValueError as err:
            raise AdapterError(f"API 返回非 JSON: {err}") from err
        message = payload_json.get("message") or payload_json.get("msg")
        if str(payload_json.get("code")) != "0":
            raise AdapterError(f"API 返回错误: {message or payload_json.get('code')}")
        return payload_json.get("data")

    @staticmethod
    def _discount_tags(discount: Any) -> List[str]:
        """M-Team discount 字段（如 FREE / _2X / PERCENT_50）→ 促销标签。"""
        tokens = str(discount or "").upper().replace(" ", "").split("_")
        tags: List[str] = []
        joined = "_".join(tokens)
        for token, label in _DISCOUNT_TOKENS:
            if token in joined:
                if label == "Free+2x":
                    tags.extend(["Free", "2x"])
                else:
                    tags.append(label)
        return list(dict.fromkeys(tags))
