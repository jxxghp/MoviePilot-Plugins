from typing import Optional, Literal, List, Union

from pydantic import Field

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin


class ShadowQUICProxy(ProxyBase, TLSMixin):
    """
    ShadowQUIC 代理配置模型。
    """
    type: Literal["shadowquic"] = "shadowquic"
    username: str = Field(..., description="ShadowQUIC 认证用户名")
    password: str = Field(..., description="ShadowQUIC 认证密码")

    # TLS & QUIC 设置
    alpn: Optional[List[str]] = Field(default_factory=lambda: ["h3"], description="ALPN 协议协商列表")
    quic_versions: Optional[List[Literal["v1", "v2"]]] = Field(
        default_factory=lambda: ["v1"], alias="quic-versions", description="支持的 QUIC 版本列表"
    )
    udp_over_stream: Optional[bool] = Field(
        default=False, alias="udp-over-stream", description="是否通过流传输 UDP"
    )
    zero_rtt: Optional[bool] = Field(default=None, alias="zero-rtt", description="是否启用 0-RTT")
    keep_alive_interval: Optional[int] = Field(
        default=None, alias="keep-alive-interval", description="保活心跳包发送间隔(毫秒)"
    )
    congestion_controller: Optional[Literal["cubic", "new_reno", "bbr"]] = Field(
        default="cubic", alias="congestion-controller", description="拥塞控制算法"
    )

    # Brutal 传输选项
    up: Optional[Union[int, str]] = Field(default=None, description="客户端 upload 速度")
    down: Optional[Union[int, str]] = Field(default=None, description="客户端 download 速度")
    cwnd: Optional[int] = Field(default=32, description="初始拥塞窗口大小")
    bbr_profile: Optional[Literal["standard", "conservative", "aggressive"]] = Field(
        default=None, alias="bbr-profile", description="BBR 算法激进程度配置"
    )

    # 连接与帧大小限制
    max_datagram_frame_size: Optional[int] = Field(
        default=1400, alias="max-datagram-frame-size", description="最大允许的数据报帧大小(字节)"
    )
    max_open_streams: Optional[int] = Field(
        default=1024, alias="max-open-streams", description="最大允许的同时并发流数量"
    )
    recv_window_conn: Optional[int] = Field(
        default=None, alias="recv-window-conn", description="单个流的接收窗口大小"
    )
    recv_window: Optional[int] = Field(
        default=None, alias="recv-window", description="连接级别的接收窗口大小"
    )
    disable_mtu_discovery: Optional[bool] = Field(
        default=None, alias="disable-mtu-discovery", description="是否禁用 Path MTU Discovery"
    )
