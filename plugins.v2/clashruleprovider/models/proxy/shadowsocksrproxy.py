from pydantic import Field
from typing import Optional, Literal

from .proxybase import ProxyBase


class ShadowsocksRProxy(ProxyBase):
    type: Literal['ssr'] = 'ssr'
    cipher: str
    password: str
    obfs: Literal['plain', 'http_simple', 'http_post', 'random_head', 'tls1.2_ticket_auth', 'tls1.2_ticket_fastauth']
    obfs_param: Optional[str] = Field(None, alias='obfs-param')
    protocol: Literal['origin', 'auth_sha1_v4', 'auth_aes128_md5', 'auth_aes128_sha1', 'auth_chain_a', 'auth_chain_b']
    protocol_param: Optional[str] = Field(None, alias='protocol-param')

    class Config:
        extra = 'allow'
        allow_population_by_field_name = True
