from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict

from .generics import ResourceItem, ResourceList
from .types import VehicleType


class OverrideProxyName(BaseModel):
    """代理名称覆盖配置"""
    pattern: str | None = Field(None, description="正则表达式模式")
    target: str = Field(..., description="替换目标")


class Override(BaseModel):
    """代理配置覆盖"""
    tfo: bool | None = Field(None, description="TCP Fast Open")
    mptcp: bool | None = Field(None, description="Multipath TCP")
    udp: bool | None = Field(None, description="UDP支持")
    udp_over_tcp: bool | None = Field(None, alias="udp-over-tcp", description="UDP over TCP")
    up: str | None = Field(None, description="上传速度限制")
    dialer_proxy: str | None = Field(None, alias="dialer-proxy", description="拨号代理")
    skip_cert_verify: bool | None = Field(None, alias="skip-cert-verify", description="跳过证书验证")
    interface_name: Optional[str] = Field(None, alias="interface-name", description="网络接口名称")
    routing_mark: int | None = Field(None, alias="routing-mark", description="路由标记")
    ip_version: str | None = Field(None, alias="ip-version", description="IP版本偏好")
    additional_prefix: str | None = Field(None, alias="additional-prefix", description="名称前缀")
    additional_suffix: str | None = Field(None, alias="additional-suffix", description="名称后缀")
    proxy_name: list[OverrideProxyName] | None = Field(None, alias="proxy-name", description="代理名称替换规则")


class HealthCheck(BaseModel):
    """健康检查配置"""
    enable: bool = Field(..., description="启用健康检查")
    url: str = Field(..., description="健康检查URL")
    interval: int = Field(300, description="检查间隔(秒)")
    timeout: int | None = Field(None, description="超时时间(毫秒)")
    lazy: bool = Field(True, description="懒加载模式")
    expected_status: str | None = Field(None, alias="expected-status", description="期望的HTTP状态码")

    @field_validator('interval')
    @classmethod
    def validate_interval(cls, v):
        if v <= 0:
            raise ValueError("间隔时间必须大于0")
        return v

    @field_validator('timeout')
    @classmethod
    def validate_timeout(cls, v):
        if v is not None and v <= 0:
            raise ValueError("超时时间必须大于0")
        return v


class ProxyProvider(BaseModel):
    """Proxy Provider"""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    type: VehicleType = Field(..., description="Provider类型")
    path: str | None = Field(default=None, description="本地文件路径")
    url: str | None = Field(default=None, description="远程URL")
    proxy: str | None = Field(default=None, description="使用的代理")
    interval: int | None = Field(default=None, description="更新间隔(秒)")
    filter: str | None = Field(default=None, description="过滤正则表达式")
    exclude_filter: str | None = Field(default=None, alias="exclude-filter", description="排除过滤正则表达式")
    exclude_type: str | None = Field(default=None, alias="exclude-type", description="排除的代理类型")
    dialer_proxy: str | None = Field(default=None, alias="dialer-proxy", description="拨号代理")
    size_limit: int | None = Field(default=None, alias="size-limit", description="文件大小限制(字节)")
    payload: list[dict[str, Any]] | None = Field(default=None, description="内联代理配置")
    health_check: HealthCheck | None = Field(default=None, alias="health-check", description="健康检查配置")
    override: Override | None = Field(default=None, description="配置覆盖")
    header: dict[str, list[str]] | None = Field(default=None, description="HTTP请求头")

    @field_validator('interval')
    @classmethod
    def validate_interval(cls, v):
        if v is not None and v <= 0:
            raise ValueError("间隔时间必须大于0")
        return v

    @field_validator('size_limit')
    @classmethod
    def validate_size_limit(cls, v):
        if v is not None and v < 0:
            raise ValueError("文件大小限制不能为负数")
        return v

    @field_validator('exclude_type')
    @classmethod
    def validate_exclude_type(cls, v):
        if v is not None:
            types = [t.strip() for t in v.split('|')]
            if not all(types):
                raise ValueError("排除类型不能为空")
        return v

    @field_validator('url')
    @classmethod
    def validate_url_dependency(cls, v, info):
        if info.data.get('type') == VehicleType.HTTP and not v:
            raise ValueError("HTTP类型的provider必须提供URL")
        return v

    @field_validator('path')
    @classmethod
    def validate_path_dependency(cls, v, info):
        if info.data.get('type') == VehicleType.FILE and not v:
            raise ValueError("FILE类型的provider必须提供路径")
        return v

    @field_validator('payload')
    @classmethod
    def validate_payload_dependency(cls, v, info):
        if info.data.get('type') == VehicleType.INLINE and not v:
            raise ValueError("INLINE类型的provider必须提供payload")
        return v


class ProxyProviderData(ResourceItem[ProxyProvider]):
    """Proxy Provider Data"""
    pass


class ProxyProviders(ResourceList[ProxyProviderData]):
    """Proxy Provider Collection"""
    pass
