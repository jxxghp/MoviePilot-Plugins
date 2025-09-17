from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase


class Hysteria2Proxy(ProxyBase):
    type: Literal['hysteria2'] = 'hysteria2'
    password: Optional[str] = None
    obfs: Optional[Literal['salamander']] = None
    obfs_password: Optional[str] = Field(None, alias='obfs-password')
    up: Optional[str] = None
    down: Optional[str] = None
    hop_interval: Optional[int] = Field(None, alias='hop-interval')
    ca: Optional[str] = None
    ca_str: Optional[str] = Field(None, alias='ca-str')
    cwnd: Optional[int] = None
    udp_mtu: Optional[int] = Field(None, alias='udp-mtu')
    ports: Optional[str] = None

    # QUIC-GO 特殊配置
    initial_stream_receive_window: Optional[int] = Field(None, alias='initial-stream-receive-window')
    max_stream_receive_window: Optional[int] = Field(None, alias='max-stream-receive-window')
    initial_connection_receive_window: Optional[int] = Field(None, alias='initial-connection-receive-window')
    max_connection_receive_window: Optional[int] = Field(None, alias='max-connection-receive-window')
