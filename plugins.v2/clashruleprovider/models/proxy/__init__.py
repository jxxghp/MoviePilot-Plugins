from typing import Union

from pydantic import Field, BaseModel

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

class Proxy(BaseModel):
    __root__: ProxyType = Field(..., discriminator="type")
