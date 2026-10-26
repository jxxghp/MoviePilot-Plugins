# -*- coding: utf-8 -*-
"""M-Team（馒头）API 型站点适配器。

认证与数据来源（oes v3.1.5 实测）：
- x-api-key（站点 APIKEY 字段）：api/member/profile（uid）、api/member/getUserTorrentList
  （INCOMPLETE 历史未完成列表，需按 peer 活动会话过滤）；
- 浏览器 JWT（站点 Token 字段，localStorage.auth）+ HMAC 签名：
  api/torrent/peers（种子 peers 明细，含 agent/ip/ipv6/memberId）——
  用 memberId == 自己 uid 精确识别自己的会话，聚合得到 BT 客户端列表（API 无 port）。

客户端采集流程：取做种列表前几个种子 → 逐个调 torrent/peers → 匹配 memberId → 去重。
未配置 Token 或 Token 过期（401）时客户端为空（主类兜底全空值条目）。
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.utilities import StringUtils

from .base import AdapterError, SiteAdapter

# 网页端 HMAC 签名密钥（由主站前端 main.*.js 生成，站点轮换后需同步更新）
_WEB_SIGN_SECRET = "HLkPcWmycL57mfJt"
# 查询 peers 的种子数量上限（做种列表前 N 个，控制请求量、降低风控风险）
_PEERS_TORRENT_LIMIT = 2

# M-Team 优惠字段（discount）→ 促销标签片段
_DISCOUNT_TOKENS = (
    ("FREE", "Free"),
    ("2XFREE", "Free+2x"),
    ("PERCENT_50", "50%"),
    ("PERCENT_30", "30%"),
    ("PERCENT_70", "70%"),
    ("2X", "2x"),
)


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
        """
        采集 BT 客户端列表（需站点配置 Token=浏览器登录态 JWT）。

        流程：getUserTorrentList(SEEDING) 取前几个做种种子 → 逐个调
        /api/torrent/peers（JWT+签名）→ memberId 等于自己 uid 的即本人会话 →
        按 (agent, ipv4, ipv6) 去重。API 不返回端口。
        """
        if not self.token:
            logger.info(f"【{self.site_name}】未配置站点 Token（浏览器登录态），无法采集客户端明细")
            return []
        try:
            seeding = self._api_post("api/member/getUserTorrentList", {
                "pageNumber": 1, "pageSize": _PEERS_TORRENT_LIMIT,
                "type": "SEEDING", "userid": int(uid),
            })
            rows = (seeding or {}).get("data") or []
            if not rows:
                return []
            clients: List[Dict[str, Any]] = []
            seen = set()
            for row in rows[:_PEERS_TORRENT_LIMIT]:
                torrent = row.get("torrent") or {}
                tid = torrent.get("id")
                if not tid:
                    continue
                peers = self._call_signed("/api/torrent/peers", {"id": str(tid)})
                for peer in peers or []:
                    if not isinstance(peer, dict) or str(peer.get("memberId")) != str(uid):
                        continue
                    ipv4 = str(peer.get("ip") or "")
                    ipv6 = str(peer.get("ipv6") or "")
                    agent = str(peer.get("agent") or "")
                    key = (agent, ipv4, ipv6)
                    if not agent and not ipv4 and not ipv6:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    clients.append({"agent": agent, "ipv4": ipv4, "ipv6": ipv6, "port": None})
                # 命中一个客户端后继续查剩余种子（不同客户端可能做不同的种），
                # 但已有结果时提前结束可减少对 peers 接口的请求量
                if clients and len(clients) >= _PEERS_TORRENT_LIMIT:
                    break
            return clients
        except AdapterError as err:
            parts = str(self.token or "").split(".")
            fingerprint = parts[1][60:110] if len(parts) == 3 and len(parts[1]) > 110 else str(self.token or "")[:30]
            logger.warning(f"【{self.site_name}】客户端信息获取失败（Token 可能过期，请重新登录站点更新）: {err} "
                           f"[token指纹: {fingerprint}]")
            return []

    def _call_signed(self, api_path: str, params: Dict[str, Any]) -> Any:
        """
        浏览器 JWT + HMAC 签名调用网页端接口（form 编码）。

        签名：HMAC-SHA1(密钥, "POST&<path>&<毫秒时间戳>") 的 Base64，
        与站点前端一致（参考 autosignin 馒头签到实现）。返回 data 字段。
        """
        if not self.token:
            raise AdapterError("未配置站点 Token")
        self._throttle()
        ts_ms = int(time.time() * 1000)
        sign = base64.b64encode(hmac.new(
            _WEB_SIGN_SECRET.encode(), f"POST&{api_path}&{ts_ms}".encode(),
            hashlib.sha1).digest()).decode()
        fingerprint = hashlib.sha256(self.token.encode()).hexdigest()
        form = dict(params)
        form["_timestamp"] = str(ts_ms)
        form["_sgin"] = sign
        # 注意：RequestUtils 传入 headers 时 ua 参数不生效，UA 必须写进 headers
        res = RequestUtils(
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/plain, */*",
                "Authorization": self.token,
                "Origin": self.base_url,
                "Referer": urljoin(self.base_url, "/index"),
                "Ts": str(ts_ms // 1000),
                "webversion": "2000",
                "Did": fingerprint[:32],
                "visitorid": fingerprint[32:],
                "User-Agent": self.ua or ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                                          "Chrome/124.0.0.0 Safari/537.36"),
            },
            proxies=settings.PROXY if self.proxy else None,
            timeout=self.timeout,
        ).post_res(url=urljoin(self.api_base, api_path.lstrip("/")), data=form)
        if res is None:
            raise AdapterError("网页接口无法访问")
        if res.status_code != 200:
            raise AdapterError(f"网页接口返回状态码 {res.status_code}")
        try:
            payload = res.json()
        except ValueError as err:
            raise AdapterError(f"网页接口返回非 JSON: {err}") from err
        code = str(payload.get("code"))
        if code == "401" or "full authentication" in str(payload.get("message") or "").lower():
            raise AdapterError("Token 登录态已失效，请重新登录站点更新 Token")
        if code != "0":
            raise AdapterError(f"网页接口返回错误: {payload.get('message') or code}")
        return payload.get("data")

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
