from typing import Optional, Literal

from pydantic import BaseModel, Field

from .proxybase import ProxyBase


class SnellObfsOpts(BaseModel):
    mode: Optional[Literal['http', 'tls']] = None
    host: Optional[str] = None


class SnellProxy(ProxyBase):
    type: Literal['snell'] = 'snell'
    psk: str
    version: Optional[Literal[1,2,3]] = 1
    obfs_opts: Optional[SnellObfsOpts] = Field(None, alias='obfs-opts')
