from typing import Optional, Literal

from pydantic import Field, model_validator

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin


class TrustTunnelProxy(ProxyBase, TLSMixin):
    """
    TrustTunnel 代理配置模型。
    """
    type: Literal["trusttunnel"] = "trusttunnel"
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码")
    health_check: Optional[bool] = Field(default=None, alias="health-check", description="是否启用健康检查")
    udp: bool = Field(default=True, description="是否使用UDP协议")
    name_cert_verify: Optional[str] = Field(default=None, alias="name-cert-verify", description="验证证书域名")

    # QUIC 选项
    quic: bool = Field(default=False, description="是否启用QUIC")
    congestion_controller: Optional[str] = Field(
        default=None, alias="congestion-controller", description="QUIC拥塞控制算法"
    )
    bbr_profile: Optional[Literal["standard", "conservative", "aggressive"]] = Field(
        default=None, alias="bbr-profile", description="BBR配置文件选项"
    )

    # 复用选项
    max_connections: Optional[int] = Field(default=None, alias="max-connections", description="最大连接数")
    min_streams: Optional[int] = Field(default=None, alias="min-streams", description="最小复用流数")
    max_streams: Optional[int] = Field(default=None, alias="max-streams", description="最大复用流数")

    @model_validator(mode="after")
    def _validate_streams_and_connections(self) -> "TrustTunnelProxy":
        """
        验证多路复用流与连接限制参数是否冲突。
        """
        has_max_streams = self.max_streams is not None
        has_max_connections = self.max_connections is not None
        has_min_streams = self.min_streams is not None

        if has_max_streams and (has_max_connections or has_min_streams):
            raise ValueError(
                "max-streams conflicts with max-connections and min-streams. "
                "You cannot set max-streams at the same time as max-connections or min-streams."
            )
        return self
