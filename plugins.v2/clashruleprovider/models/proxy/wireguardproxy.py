from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from .proxybase import ProxyBase


class WireGuardPeerOption(BaseModel):
    server: str
    port: int
    public_key: str = Field(..., alias='public-key')
    pre_shared_key: Optional[str] = Field(None, alias='pre-shared-key')
    reserved: Optional[List[int]] = None
    allowed_ips: Optional[List[str]] = Field(None, alias='allowed-ips')


class AmneziaWGOption(BaseModel):
    jc: Optional[int] = None
    jmin: Optional[int] = None
    jmax: Optional[int] = None
    s1: Optional[int] = None
    s2: Optional[int] = None
    h1: Optional[int] = None
    h2: Optional[int] = None
    h3: Optional[int] = None
    h4: Optional[int] = None
    # AmneziaWG v1.5
    i1: Optional[str] = None
    i2: Optional[str] = None
    i3: Optional[str] = None
    i4: Optional[str] = None
    i5: Optional[str] = None
    j1: Optional[str] = None
    j2: Optional[str] = None
    j3: Optional[str] = None
    itime: Optional[int] = None


class WireGuardProxy(ProxyBase):
    type: Literal['wireguard'] = 'wireguard'
    ip: Optional[str] = None
    ipv6: Optional[str] = None
    private_key: str = Field(..., alias='private-key')
    public_key: str = Field(..., alias='public-key')
    pre_shared_key: Optional[str] = Field(None, alias='pre-shared-key')
    reserved: Optional[List[int]] = None
    workers: Optional[int] = None
    mtu: Optional[int] = None
    persistent_keepalive: Optional[int] = Field(None, alias='persistent-keepalive')

    # 多 peer 配置
    peers: Optional[List[WireGuardPeerOption]] = None

    # DNS 配置
    remote_dns_resolve: Optional[bool] = Field(None, alias='remote-dns-resolve')
    dns: Optional[List[str]] = None
    refresh_server_ip_interval: Optional[int] = Field(None, alias='refresh-server-ip-interval')

    # AmneziaWG 扩展
    amnezia_wg_option: Optional[AmneziaWGOption] = Field(None, alias='amnezia-wg-option')
