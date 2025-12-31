import jsonpatch
from typing import Union, Any

from pydantic import Field, RootModel, model_validator

from .anytlsproxy import AnyTLSProxy
from .directproxy import DirectProxy
from .dnsproxy import DnsProxy
from .httpproxy import HttpProxy
from .hysteriaproxy import HysteriaProxy
from .hysteria2proxy import Hysteria2Proxy
from .mieruproxy import MieruProxy
from .networkmixin import NetworkMixin
from .proxybase import ProxyBase
from .shadowsocksproxy import ShadowsocksProxy
from .shadowsocksrproxy import ShadowsocksRProxy
from .snellproxy import SnellProxy
from .socks5proxy import Socks5Proxy
from .sshproxy import SshProxy
from .tlsmixin import TLSMixin
from .trojanproxy import TrojanProxy
from .tuicproxy import TuicProxy
from .vlessproxy import VlessProxy
from .vmessproxy import VmessProxy
from .wireguardproxy import WireGuardProxy
from ..generics import ResourceItem, ResourceList

ProxyType = Union[
    AnyTLSProxy,
    DirectProxy,
    DnsProxy,
    HttpProxy,
    HysteriaProxy,
    Hysteria2Proxy,
    MieruProxy,
    ShadowsocksProxy,
    ShadowsocksRProxy,
    SnellProxy,
    Socks5Proxy,
    SshProxy,
    TrojanProxy,
    TuicProxy,
    VlessProxy,
    VmessProxy,
    WireGuardProxy,
]


class Proxy(RootModel[ProxyType]):
    root: ProxyType = Field(..., discriminator="type")

    @property
    def name(self) -> str:
        return self.root.name

    def __getattr__(self, item):
        return getattr(self.root, item)

    def patch(self, patch: str) -> 'Proxy':
        src = self.model_dump(mode='json', by_alias=True)
        patched = jsonpatch.apply_patch(src, patch=patch, in_place=True)
        return Proxy.model_validate(patched)


class ProxyData(ResourceItem[Proxy]):
    raw: Union[str, dict[str, Any], None] = None
    v2ray_link: str | None = None

    @model_validator(mode="after")
    def validate_name_consistency(self):
        if self.name != self.data.name:
            raise ValueError(f"name ({self.name}) must equal data.name ({self.data.name})")
        return self


class Proxies(ResourceList[ProxyData]):
    """Proxies Collection"""
    pass
