from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin


class TuicProxy(ProxyBase, TLSMixin):
    type: Literal['tuic'] = 'tuic'
    # TUIC v4/v5 认证
    token: Optional[str] = None
    uuid: Optional[str] = None
    password: Optional[str] = None

    # 连接配置
    ip: Optional[str] = None
    heartbeat_interval: Optional[int] = Field(None, alias='heartbeat-interval')
    reduce_rtt: Optional[bool] = Field(None, alias='reduce-rtt')
    request_timeout: Optional[int] = Field(None, alias='request-timeout')
    udp_relay_mode: Optional[Literal['native', 'quic']] = Field(None, alias='udp-relay-mode')
    congestion_controller: Optional[Literal['cubic', 'new_reno', 'bbr']] = Field(None, alias='congestion-controller')
    disable_sni: Optional[bool] = Field(None, alias='disable-sni')
    max_udp_relay_packet_size: Optional[int] = Field(None, alias='max-udp-relay-packet-size')

    # 性能配置
    fast_open: Optional[bool] = Field(None, alias='fast-open')
    max_open_streams: Optional[int] = Field(None, alias='max-open-streams')
    cwnd: Optional[int] = None
    recv_window_conn: Optional[int] = Field(None, alias='recv-window-conn')
    recv_window: Optional[int] = Field(None, alias='recv-window')
    disable_mtu_discovery: Optional[bool] = Field(None, alias='disable-mtu-discovery')
    max_datagram_frame_size: Optional[int] = Field(None, alias='max-datagram-frame-size')

    # TLS 证书配置
    ca: Optional[str] = None
    ca_str: Optional[str] = Field(None, alias='ca-str')

    # UDP over Stream 扩展
    udp_over_stream: Optional[bool] = Field(None, alias='udp-over-stream')
    udp_over_stream_version: Optional[int] = Field(None, alias='udp-over-stream-version')
