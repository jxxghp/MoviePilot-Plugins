import copy
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Union, Any, Iterator

from ..models.proxy import Proxy, ProxyType


@dataclass
class ProxyItem:
    proxy: ProxyType
    remark: str = ""
    raw: Optional[Union[str, Dict[str, Any]]] = None

class ProxyManager:
    """Proxy Manager"""
    def __init__(self):
        self.proxies: Dict[str,ProxyItem] = {}

    def add(self, proxy: ProxyType, remark: str = "", raw: Optional[str|Dict[str, Any]] = None):
        """Add a proxy to the proxy manager. """
        if proxy.name not in self.proxies:
            self.proxies[proxy.name] = ProxyItem(proxy, remark, raw=copy.deepcopy(raw))
        else:
            raise ValueError(f"Proxy with name {proxy.name!r} already exists.")

    def add_proxy_dict(self, proxy_dict: Dict[str, Any], remark: str = "", raw: Optional[str] = None):
        """
        Add a proxy to the proxies list.
        :param proxy_dict: Proxy dict with proxy name as key
        :param remark: Proxy remark
        :param raw: Proxy raw
        :raises: ValueError if proxy name already exists
        """
        proxy = Proxy.parse_obj(proxy_dict)
        raw = raw or proxy_dict
        self.add(proxy.__root__, remark=remark, raw=raw)

    def add_from_list(self, proxies: List[Dict[str, Any]], remark: str = "", skip_existing: bool = False):
        """Add proxies from the proxies list. """
        proxies_list = []
        for proxy in proxies:
            p = Proxy.parse_obj(proxy)
            proxies_list.append(ProxyItem(p.__root__, remark, raw=proxy))

        for proxy_item in proxies_list:
            try:
                self.add(proxy_item.proxy, remark=remark, raw=proxy_item.raw)
            except ValueError:
                if skip_existing:
                    continue
                raise

    def get_all_proxies(self) -> List[Dict[str, Any]]:
        proxies = []
        for proxy_item in self.proxies.values():
            proxy_dict = proxy_item.proxy.dict(by_alias=True, exclude_none=True)
            proxies.append(proxy_dict)
        return proxies

    def remove_proxy(self, name):
        if name in self.proxies:
            del self.proxies[name]

    def remove_proxies_by_condition(self, condition: Callable[[ProxyItem], bool]) -> int:
        """
        Removes proxies from the manager based on a given condition.
        :param condition: A callable that takes a ProxyItem and returns True if the proxy should be removed.
        :return: The number of proxies removed.
        """
        initial_count = len(self.proxies)
        self.proxies = {
            name: item
            for name, item in self.proxies.items()
            if not condition(item)
        }
        return initial_count - len(self.proxies)

    def filter_proxies_by_condition(self, condition: Callable[[ProxyItem], bool]) -> List[ProxyItem]:
        return [proxy for proxy in self.proxies.values() if condition(proxy)]

    def clear(self):
        self.proxies.clear()

    def export_raw(self, condition: Optional[Callable[[ProxyItem], bool]] = None) -> List[str|Dict[str, Any]]:
        proxies = []
        for proxy in self.proxies.values():
            if condition and not condition(proxy):
                continue
            if proxy.raw:
                proxies.append(copy.deepcopy(proxy.raw))
            else:
                proxies.append(proxy.proxy.dict(by_alias=True, exclude_none=True))
        return proxies

    def proxy_names(self) -> Iterator[str]:
        return iter(self.proxies)

    def __len__(self) -> int:
        return len(self.proxies)

    def __iter__(self) -> Iterator[ProxyItem]:
        return iter(self.proxies.values())

    def __contains__(self, name: str) -> bool:
        return name in self.proxies
