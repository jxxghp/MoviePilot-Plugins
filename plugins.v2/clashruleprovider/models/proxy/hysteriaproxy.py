from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase


class HysteriaProxy(ProxyBase):
    type: Literal['hysteria'] = 'hysteria'
    auth_str: Optional[str] = Field(None, alias='auth-str')
    auth: Optional[str] = None
    protocol: Optional[Literal['udp','wechat-video', 'faketcp']] = None
    up: Optional[str] = None
    down: Optional[str] = None
    up_speed: Optional[int] = Field(None, alias='up-speed')
    down_speed: Optional[int] = Field(None, alias='down-speed')
    obfs: Optional[str] = None
    obfs_protocol: Optional[str] = Field(None, alias='obfs-protocol')
    recv_window_conn: Optional[int] = Field(None, alias='recv-window-conn')
    recv_window: Optional[int] = Field(None, alias='recv-window')
    disable_mtu_discovery: Optional[bool] = Field(None, alias='disable-mtu-discovery')
    fast_open: Optional[bool] = Field(None, alias='fast-open')
    hop_interval: Optional[int] = Field(None, alias='hop-interval')
    ca: Optional[str] = None
    ca_str: Optional[str] = Field(None, alias='ca-str')
    ports: Optional[str] = None
