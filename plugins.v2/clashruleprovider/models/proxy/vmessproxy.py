from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin
from .networkmixin import NetworkMixin

class VmessProxy(ProxyBase, TLSMixin, NetworkMixin):
    type: Literal['vmess'] = 'vmess'
    uuid: str
    alter_id: int = Field(0, alias='alterId')
    cipher: Literal['auto', 'zero', 'aes-128-gcm', 'chacha20-poly1305', 'none'] = 'auto'
    packet_addr: Optional[bool] = Field(None, alias='packet-addr')
    xudp: Optional[bool] = None
    packet_encoding: Optional[Literal['packetaddr', 'xudp']] = Field(None, alias='packet-encoding')
    global_padding: Optional[bool] = Field(None, alias='global-padding')
    authenticated_length: Optional[bool] = Field(None, alias='authenticated-length')
