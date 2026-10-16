# -*- coding: utf-8 -*-
"""站点适配器工厂。

解析顺序：
1. SITE_ADAPTERS 站点专属适配器（精确域名匹配）；
2. 架构级适配器（M-Team 域名 → MTeamAdapter；其余默认 NexusPhpAdapter）；
3. 均无匹配时由调用方兜底为全空值条目。

新增适配方式参见 adapters/sites/__init__.py 的说明。
"""

from typing import Any, Dict, Optional

from .base import AdapterError, SiteAdapter
from .mteam import MTeamAdapter
from .nexusphp import NexusPhpAdapter
from .sites import SITE_ADAPTERS

# M-Team 家族域名（API 型站点）
MTEAM_DOMAIN_KEYWORDS = ("m-team", "mteam")


def get_adapter(site_info: Dict[str, Any], interval: int = 3,
                uid_map: Optional[Dict[str, str]] = None) -> SiteAdapter:
    """
    根据站点信息构造适配器。

    :param site_info: SitesHelper 的站点条目（或 CustomSites 条目）
    :param interval: 同站相邻请求间隔秒数
    :param uid_map: domain → uid 缓存（主类的 uid_map 数据）
    """
    domain = str(site_info.get("domain") or "").lower()
    uid = (uid_map or {}).get(domain)
    adapter_class = SITE_ADAPTERS.get(domain)
    if adapter_class is None:
        if any(keyword in domain for keyword in MTEAM_DOMAIN_KEYWORDS) or (
                site_info.get("apikey") and "m-team" in str(site_info.get("url") or "").lower()):
            adapter_class = MTeamAdapter
        else:
            adapter_class = NexusPhpAdapter
    return adapter_class(site_info, interval=interval, uid=uid)


__all__ = ["AdapterError", "SiteAdapter", "NexusPhpAdapter", "MTeamAdapter",
           "SITE_ADAPTERS", "get_adapter"]
