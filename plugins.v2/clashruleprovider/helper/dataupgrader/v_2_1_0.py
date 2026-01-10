import copy
import time
from typing import Any

import jsonpatch
from pydantic import ValidationError

from app.db.plugindata_oper import PluginDataOper

from ..configconverter import Converter
from ..utilsprovider import UtilsProvider
from ...models.proxygroups import ProxyGroupData
from ...models.proxy import Proxy, ProxyData
from ...models.ruleproviders import RuleProviderData
from ...models.types import DataSource, DataKey
from ...models.datapatch import PatchItem
from ...models.metadata import Metadata


def _overwrite_proxy(proxy: dict[str, Any], overwritten_proxies: dict[str, Any]) -> dict[str, Any]:
    if proxy["name"] in overwritten_proxies:
        for key in ['base', 'tls', 'network']:
            if overlay := overwritten_proxies[proxy["name"]].get(key):
                proxy.update(copy.deepcopy(overlay))
    return proxy


def upgrade(plugin_id: str):
    data_oper = PluginDataOper()

    # Upgrade proxy groups
    proxy_groups = data_oper.get_data(plugin_id, "proxy_groups") or []
    new_pg, invalid_pg, names = [], [], set()

    for pg in proxy_groups:
        try:
            obj = ProxyGroupData(meta=Metadata(source=DataSource.MANUAL), data=pg, name=pg["name"])
            if obj.name not in names:
                new_pg.append(obj.model_dump(by_alias=True, exclude_none=True))
                names.add(obj.name)
        except ValidationError:
            invalid_pg.append(pg)

    data_oper.save(plugin_id, DataKey.PROXY_GROUPS, new_pg)
    data_oper.save(plugin_id, "proxy_groups", invalid_pg)

    # Upgrade rule providers
    rule_providers = data_oper.get_data(plugin_id, "extra_rule_providers") or {}
    new_rp, invalid_rp = [], []

    for name, rp in rule_providers.items():
        try:
            obj = RuleProviderData(meta=Metadata(source=DataSource.MANUAL), name=name, data=rp)
            new_rp.append(obj.model_dump(by_alias=True, exclude_none=True))
        except ValidationError:
            invalid_rp.append(rp)

    data_oper.save(plugin_id, DataKey.RULE_PROVIDERS, new_rp)
    data_oper.save(plugin_id, "extra_rule_providers", invalid_rp)

    # Upgrade proxies
    proxies = data_oper.get_data(plugin_id, DataKey.PROXIES) or []
    new_proxies, invalid_proxies = [], []
    all_proxies = []
    names = set()
    converter = Converter()

    for proxy in proxies:
        try:
            raw = None
            if isinstance(proxy, str):
                proxy_dict, raw = converter.convert_line(proxy), proxy
            elif isinstance(proxy, dict):
                proxy_dict = UtilsProvider.filter_empty(proxy, empty=['', None])
            else:
                continue

            obj = Proxy.model_validate(proxy_dict)
            if obj.name in names: continue

            p_data = ProxyData(data=obj, name=obj.name, meta=Metadata(source=DataSource.MANUAL), raw=raw)
            new_proxies.append(p_data.model_dump(by_alias=True, exclude_none=True))
            all_proxies.append(p_data.data)
            names.add(p_data.name)
        except Exception:
            invalid_proxies.append(proxy)

    data_oper.save(plugin_id, DataKey.PROXIES, new_proxies)
    data_oper.save(plugin_id, "extra_proxies", invalid_proxies)

    # Create proxy patches
    data_patch = {}
    overwritten = data_oper.get_data(plugin_id, "overwritten_proxies") or {}
    for name in overwritten:
        if proxy := next((p for p in all_proxies if p.name == name), None):
            src = proxy.model_dump(by_alias=True)
            # Create a deep copy for dst to avoid modifying src in place if _overwrite_proxy mutates
            dst = _overwrite_proxy(copy.deepcopy(src), overwritten)
            if patch := jsonpatch.make_patch(src, dst).to_string():
                data_patch[name] = PatchItem(patch=patch).model_dump(by_alias=True, exclude_none=True)

    data_oper.save(plugin_id, DataKey.PROXY_PATCH, data_patch)
    data_oper.save(plugin_id, DataKey.ACL4SSR, [])

    # Upgrade rules
    for key in [DataKey.TOP_RULES, DataKey.RULESET_RULES]:
        if rules := data_oper.get_data(plugin_id, key):
            for rule in rules:
                rule["meta"] = Metadata(
                    source=rule.get("remark") or DataSource.MANUAL,
                    time_modified=rule.get("time_modified") or time.time()
                ).model_dump()
            data_oper.save(plugin_id, key, rules)
    data_oper.save(plugin_id, DataKey.DATA_VERSION, "2.1.0")
