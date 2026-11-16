# -*- coding: utf-8 -*-
r"""xloli（萝莉，mua.xloli.cc）站点适配器。

NexusPHP 架构，但用户标识与通用模板不同（2026-11-04 实测）：
- 用户 ID 是 UUID（36 位）而非数字：首页用户链接 ``userdetails.php?uuid=<uuid>``，
  基类 ``userdetails.php?id=\d+`` 正则匹配不到 → 覆写 uid 解析；
- 用户详情页参数为 ``uuid=``（页面同时展示数字 UID，但访问只认 uuid）；
- 下载中列表 ajax 参数为 ``useruuid=``（非 ``userid=``），无 Referer 要求。

客户端表格（Agent/IPV4/IPV6/Port 内层表格）与种子列表行均为标准 NexusPHP 结构，
通用解析逻辑直接适用，无需覆写。
"""

import re
from typing import Optional
from urllib.parse import urljoin

from lxml import etree

from ..nexusphp import NexusPhpAdapter

# UUID 形式的用户标识（8-4-4-4-12 hex）
_UUID_RE = re.compile(r"uuid=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


class XloliAdapter(NexusPhpAdapter):
    """xloli：UUID 用户标识 + useruuid ajax 参数。"""

    schema_name = "nexusphp-xloli"

    def _uid_from_homepage(self) -> Optional[str]:
        """
        首页「欢迎回来」区块解析自己的 UUID。

        首页存在多个 userdetails.php?uuid= 链接（管理员、最近动向的其他用户等），
        必须锚定 class='User_Name'（当前登录用户）的链接，避免误取他人 ID。
        """
        html = self.fetch_index()
        if not html:
            return None
        doc = etree.HTML(html)
        if doc is None:
            return None
        for anchor in doc.xpath("//a[contains(@href, 'userdetails.php?uuid=')]"):
            if "user_name" not in str(anchor.get("class") or "").lower():
                continue
            match = _UUID_RE.search(anchor.get("href") or "")
            if match:
                return match.group(1).lower()
        return None

    def user_detail_url(self, uid: str) -> str:
        return urljoin(self.base_url, f"{self.user_detail_page}?uuid={uid}")

    def leeching_url(self, uid: str, page: int = 0) -> str:
        url = urljoin(self.base_url, f"{self.leeching_page}?useruuid={uid}&type=leeching")
        if page:
            url += f"&page={page}"
        return url
