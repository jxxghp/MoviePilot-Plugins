from typing import Optional, Dict, Literal, List

from pydantic import Field, field_validator, model_validator

from .proxybase import ProxyBase


class OpenVPN(ProxyBase):
    """
    OpenVPN 代理配置模型。
    """
    type: Literal["openvpn"] = "openvpn"
    port: int = Field(default=1194, description="服务器端口")
    proto: Literal["udp", "tcp"] = Field(default="udp", description="协议类型")
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码")
    ca: str = Field(..., description="CA证书内容")
    cert: Optional[str] = Field(default=None, description="客户端证书内容")
    key: Optional[str] = Field(default=None, description="客户端私钥内容")
    tls_auth: Optional[str] = Field(default=None, alias="tls-auth", description="TLS认证密钥")
    key_direction: Optional[Literal["1", "0", ""]] = Field(
        default=None, alias="key-direction", description="密钥方向"
    )
    tls_crypt: Optional[str] = Field(default=None, alias="tls-crypt", description="TLS加密密钥")
    tls_crypt_v2: Optional[str] = Field(
        default=None, alias="tls-crypt-v2", description="TLS加密v2客户端密钥"
    )
    ping: int = Field(default=0, description="ping间隔")
    ping_restart: int = Field(default=0, alias="ping-restart", description="ping-restart间隔")
    peer_info: Optional[Dict[str, str]] = Field(
        default=None, alias="peer-info", description="传递给服务器的对等端信息"
    )
    handshake_timeout: int = Field(default=0, alias="handshake-timeout", description="握手超时时间")
    dev: Literal["tun"] = Field(default="tun", description="虚拟网卡类型")
    cipher: Optional[
        Literal[
            "AES-128-GCM",
            "AES-256-GCM",
            "AES-128-CBC",
            "AES-256-CBC",
            "CHACHA20-POLY1305",
            "AES-CBC",
        ]
    ] = Field(default="AES-128-GCM", description="加密算法")
    data_ciphers: Optional[List[str]] = Field(
        default=None, alias="data-ciphers", description="数据通道加密算法协商列表"
    )
    data_ciphers_fallback: Optional[str] = Field(
        default=None, alias="data-ciphers-fallback", description="协商失败时的后备加密算法"
    )
    auth: Literal["MD5", "SHA1", "SHA256", "SHA384", "SHA512"] = Field(
        default="SHA256", description="认证算法"
    )
    comp_lzo: Optional[Literal["yes", "no", "adaptive"]] = Field(
        default=None, alias="comp-lzo", description="数据压缩方式"
    )
    udp: bool = Field(default=True, description="是否使用UDP协议")
    mtu: int = Field(default=1500, description="最大传输单元")
    remote_dns_resolve: bool = Field(
        default=False, alias="remote-dns-resolve", description="是否强制远程DNS解析"
    )
    dns: Optional[List[str]] = Field(default=None, description="DNS服务器地址列表")

    @field_validator("cipher", mode="before")
    @classmethod
    def _validate_cipher(cls, v: Optional[str]) -> Optional[str]:
        """
        验证并格式化加密算法。

        将 AES-CBC 自动转换为 AES-128-CBC。
        """
        if v == "AES-CBC":
            return "AES-128-CBC"
        return v

    @model_validator(mode="after")
    def _validate_auth_and_tls(self) -> "OpenVPN":
        """
        验证 OpenVPN 身份验证和 TLS 相关字段的合法性。
        """
        # 1. 校验用户名密码与证书私钥必须选其一
        has_user_pass = bool(self.username and self.password)
        has_cert_key = bool(self.cert and self.key)
        if not has_user_pass and not has_cert_key:
            raise ValueError(
                "Must choose between username/password or cert/key. "
                "Both pairs cannot be empty at the same time."
            )

        # 2. 校验 tls-auth, tls-crypt, tls-crypt-v2 互斥
        tls_fields = [self.tls_auth, self.tls_crypt, self.tls_crypt_v2]
        non_empty_tls = [f for f in tls_fields if f is not None]
        if len(non_empty_tls) > 1:
            raise ValueError("tls-auth, tls-crypt, and tls-crypt-v2 are mutually exclusive.")

        return self
