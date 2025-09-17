from typing import List, Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase


class SshProxy(ProxyBase):
    type: Literal['ssh'] = 'ssh'
    username: str
    password: Optional[str] = None
    private_key: Optional[str] = Field(None, alias='privateKey')
    private_key_passphrase: Optional[str] = Field(None, alias='private-key-passphrase')
    host_key: Optional[List[str]] = Field(None, alias='host-key')
    host_key_algorithms: Optional[List[str]] = Field(None, alias='host-key-algorithms')
