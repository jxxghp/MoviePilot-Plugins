from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase


class TailscaleProxy(ProxyBase):
    """
    Tailscale 代理配置模型。
    """
    type: Literal["tailscale"] = "tailscale"
    hostname: Optional[str] = Field(default=None, description="Tailscale 设备名称")
    auth_key: Optional[str] = Field(default=None, alias="auth-key", description="登录密钥")
    control_url: Optional[str] = Field(default=None, alias="control-url", description="控制服务器地址")
    state_dir: Optional[str] = Field(default="tailscale", alias="state-dir", description="tsnet 状态目录")
    ephemeral: Optional[bool] = Field(default=False, description="是否作为临时节点登录")
    udp: bool = Field(default=False, description="是否启用 UDP")
    accept_routes: Optional[bool] = Field(default=None, alias="accept-routes", description="是否接受子网路由")
    exit_node: Optional[str] = Field(default=None, alias="exit-node", description="出口节点")
    exit_node_allow_lan_access: Optional[bool] = Field(
        default=None, alias="exit-node-allow-lan-access", description="是否允许访问本地局域网"
    )
