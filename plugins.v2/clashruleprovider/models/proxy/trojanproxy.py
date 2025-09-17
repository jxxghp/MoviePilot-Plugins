from typing import Optional, Literal

from pydantic import BaseModel, Field

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin
from .networkmixin import NetworkMixin


class TrojanSSOption(BaseModel):
    enabled: Optional[bool] = None
    method: Optional[Literal['aes-128-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305']] = None
    password: Optional[str] = None


class TrojanProxy(ProxyBase, TLSMixin, NetworkMixin):
    type: Literal['trojan'] = 'trojan'
    password: str
    ss_opts: Optional[TrojanSSOption] = Field(None, alias='ss-opts')
    network: Optional[Literal['tcp', 'grpc', 'ws']] = None
    tls: Optional[bool] = True
