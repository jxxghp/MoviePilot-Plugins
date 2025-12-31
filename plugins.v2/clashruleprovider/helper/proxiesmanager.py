import copy
from typing import Callable, Dict, List, Optional, Any, Iterator, Union

from ..models.metadata import Metadata
from ..models.types import DataSource
from ..models.proxy import Proxy, ProxyData


class ProxyManager:
    """Proxy Manager"""
    def __init__(self):
        self._proxies: Dict[str, ProxyData] = {}

    def add(self, proxy: Proxy, source: DataSource, remark: str = "", raw: str | dict[str, Any] | None = None):
        """Add a proxy to the proxy manager. """
        if proxy.name not in self._proxies:
            meta = Metadata(source=source, remark=remark)
            self._proxies[proxy.name] = ProxyData(data=proxy, name=proxy.name, meta=meta, raw=copy.deepcopy(raw))
        else:
            raise ValueError(f"Proxy with name {proxy.name!r} already exists.")

    def update(self, name: str, proxy: Proxy):
        if name not in self._proxies:
            raise ValueError(f"Key '{name}' not found")
        src = self._proxies[name]
        src.data = proxy

    def add_proxy_data(self, proxy_data: dict[str, Any]):
        pd = ProxyData.model_validate(proxy_data)
        if pd.data.name not in self._proxies:
            self._proxies[pd.data.name] = pd
        else:
            raise ValueError(f"Proxy with name {pd.data.name!r} already exists.")

    def add_proxy_dict(self, proxy_dict: Dict[str, Any], source: DataSource, remark: str = "", raw: str | None = None):
        """
        Add a proxy to the proxies list.
        :param proxy_dict: Proxy dict with proxy name as key
        :param source: Proxy source
        :param remark: Remark
        :param raw: Proxy raw
        :raises: ValueError if proxy name already exists
        """
        proxy = Proxy.model_validate(proxy_dict)
        raw = raw or proxy_dict
        self.add(proxy, source=source, remark=remark, raw=raw)

    def get_all_proxies(self) -> List[Dict[str, Any]]:
        proxies = []
        for proxy_item in self._proxies.values():
            proxy_dict = proxy_item.data.model_dump(by_alias=True, exclude_none=True)
            proxies.append(proxy_dict)
        return proxies

    def remove_proxy(self, name):
        if name in self._proxies:
            del self._proxies[name]

    def remove_proxies_by_condition(self, condition: Callable[[ProxyData], bool]) -> int:
        """
        Removes proxies from the manager based on a given condition.
        :param condition: A callable that takes a ProxyData and returns True if the proxy should be removed.
        :return: The number of proxies removed.
        """
        initial_count = len(self._proxies)
        self._proxies = {
            name: item
            for name, item in self._proxies.items()
            if not condition(item)
        }
        return initial_count - len(self._proxies)

    def filter_proxies_by_condition(self, condition: Callable[[ProxyData], bool]) -> List[ProxyData]:
        return [proxy for proxy in self._proxies.values() if condition(proxy)]

    def clear(self):
        self._proxies.clear()

    def export_raw(self, condition: Optional[Callable[[ProxyData], bool]] = None) -> List[Union[str, Dict[str, Any]]]:
        proxies = []
        for proxy in self._proxies.values():
            if condition and not condition(proxy):
                continue
            if proxy.raw:
                proxies.append(copy.deepcopy(proxy.raw))
            else:
                proxies.append(proxy.data.model_dump(by_alias=True, exclude_none=True))
        return proxies

    def proxy_names(self) -> Iterator[str]:
        return iter(self._proxies)

    def set_proxy_meta(self, name: str, meta: Metadata):
        if name not in self._proxies:
            raise ValueError(f"Key '{name}' not found")
        self._proxies[name].meta = meta

    def __len__(self) -> int:
        return len(self._proxies)

    def __iter__(self) -> Iterator[ProxyData]:
        return iter(self._proxies.values())

    def __contains__(self, name: str) -> bool:
        return name in self._proxies

    def __getitem__(self, name: str) -> ProxyData:
        if name not in self._proxies:
            raise KeyError(f"Key '{name}' not found")
        return self._proxies[name]
