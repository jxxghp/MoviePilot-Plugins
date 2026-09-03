from typing import Optional, Literal, Union

from pydantic import Field, model_validator

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin, RealmOpts


class Hysteria2Proxy(ProxyBase, TLSMixin):
    """
    Hysteria2 代理配置模型。
    """
    type: Literal['hysteria2'] = 'hysteria2'
    password: Optional[str] = Field(default=None, description="认证密码")
    obfs: Optional[Literal['salamander', 'gecko']] = Field(default=None, description="混淆类型")
    obfs_password: Optional[str] = Field(default=None, alias='obfs-password', description="混淆密码")
    obfs_min_packet_size: Optional[int] = Field(
        default=None, alias='obfs-min-packet-size', description="最小数据包大小(仅适用于 gecko)"
    )
    obfs_max_packet_size: Optional[int] = Field(
        default=None, alias='obfs-max-packet-size', description="最大数据包大小(仅适用于 gecko)"
    )
    up: Optional[Union[int, str]] = Field(default=None, description="Brutal 限制上传速度")
    down: Optional[Union[int, str]] = Field(default=None, description="Brutal 限制下载速度")
    hop_interval: Optional[Union[int, str]] = Field(default=None, alias='hop-interval', description="端口跳跃间隔")
    ca: Optional[str] = Field(default=None, description="CA 证书")
    ca_str: Optional[str] = Field(default=None, alias='ca-str', description="CA 证书字符串")
    cwnd: Optional[int] = Field(default=None, description="拥塞窗口大小")
    udp_mtu: Optional[int] = Field(default=None, alias='udp-mtu', description="UDP MTU")
    ports: Optional[str] = Field(default=None, description="端口跳跃范围配置")
    bbr_profile: Optional[Literal["standard", "conservative", "aggressive"]] = Field(
        default=None, alias='bbr-profile', description="BBR激进程度配置"
    )
    name_cert_verify: Optional[str] = Field(default=None, alias='name-cert-verify', description="验证证书域名")

    # QUIC-GO 特殊配置
    initial_stream_receive_window: Optional[int] = Field(
        default=None, alias='initial-stream-receive-window', description="初始流接收窗口大小"
    )
    max_stream_receive_window: Optional[int] = Field(
        default=None, alias='max-stream-receive-window', description="最大流接收窗口大小"
    )
    initial_connection_receive_window: Optional[int] = Field(
        default=None, alias='initial-connection-receive-window', description="初始连接接收窗口大小"
    )
    max_connection_receive_window: Optional[int] = Field(
        default=None, alias='max-connection-receive-window', description="最大连接接收窗口大小"
    )
    realm_opts: Optional[RealmOpts] = Field(default=None, alias="realm-opts", description="Realm 配置选项")

    @model_validator(mode="after")
    def _validate_obfs_packets(self) -> "Hysteria2Proxy":
        """
        验证混淆数据包大小限制参数是否合法。
        """
        if self.obfs != "gecko" and (self.obfs_min_packet_size is not None or self.obfs_max_packet_size is not None):
            raise ValueError("obfs-min-packet-size and obfs-max-packet-size are restricted to gecko obfuscator only.")
        return self
