from typing import Optional, Literal

from pydantic import BaseModel, Field


class SmuxBrutalOpts(BaseModel):
    enabled: bool = False
    up: Optional[str] = None
    down: Optional[str] = None


class Smux(BaseModel):
    enabled: bool = False
    protocol: Literal['smux', 'yamux', 'h2mux'] = 'h2mux'
    max_connections: Optional[int] = Field(None, alias='max-connections')
    min_streams: Optional[int] = Field(None, alias='min-streams')
    max_streams: Optional[int] = Field(None, alias='max-streams')
    statistic: Optional[bool] = None
    only_tcp: Optional[bool] = Field(None, alias='only-tcp')
    padding: Optional[bool] = None
    brutal_opts: Optional[SmuxBrutalOpts] = Field(None, alias='brutal-opts')


class ProxyBase(BaseModel):
    name: str
    type: Literal['direct', 'dns', 'http', 'ss', 'ssr', 'mieru', 'snell', 'vmess', 'vless', 'trojan', 'anytls',
                  'hysteria','hysteria2', 'tuic', 'wireguard', 'ssh', 'socks5']
    server: str
    port: int
    ip_version: Optional[Literal['dual', 'ipv4', 'ipv6', 'ipv4-prefer', 'ipv6-prefer']] = Field(None,
                                                                                                alias='ip-version')
    udp: bool = False
    interface_name: Optional[str] = Field(None, alias='interface-name')
    routing_mark: Optional[int] = Field(None, alias='routing-mark')
    tfo: Optional[bool] = None
    mptcp: Optional[bool] = None
    dialer_proxy: Optional[str] = Field(None, alias='dialer-proxy')
    smux: Optional[Smux] = None
