from pydantic import Field
from typing import Optional, Literal

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin
from .networkmixin import NetworkMixin


class VlessProxy(ProxyBase, TLSMixin, NetworkMixin):
    type: Literal['vless'] = 'vless'
    uuid: str
    flow: Optional[str] = None
    packet_addr: Optional[bool] = Field(None, alias='packet-addr')
    xudp: Optional[bool] = None
    packet_encoding: Optional[Literal['packetaddr', 'xudp']] = Field(None, alias='packet-encoding')
    encryption: Optional[str] = None
