from typing import Optional, Dict, Literal, List, Union

from pydantic import Field, BaseModel, field_validator, ValidationInfo

from .proxybase import ProxyBase


ShadowsocksCipherType = Literal[
    # AES 相关
    'aes-128-ctr', 'aes-192-ctr', 'aes-256-ctr',
    'aes-128-cfb', 'aes-192-cfb', 'aes-256-cfb',
    'aes-128-gcm', 'aes-192-gcm', 'aes-256-gcm',
    'aes-128-com', 'aes-192-com', 'aes-256-com',
    'aes-128-gcm-siv', 'aes-256-gcm-siv',
    # CHACHA 相关
    'chacha20-ietf', 'chacha20', 'xchacha20',
    'chacha20-ietf-poly1305', 'xchacha20-ietf-poly1305',
    'chacha8-ietf-poly1305', 'xchacha8-ietf-poly1305',
    # 2022 Blake3 相关
    '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm', '2022-blake3-chacha20-poly1305',
    # LEA 相关
    'lea-128-gcm', 'lea-192-gcm', 'lea-256-gcm',
    # 其他
    'rabbit128-poly1305', 'aegis-128l', 'aegis-256', 'aez-384', 'deoxys-ii-256-128', 'rc4-md5', 'none'
]


class ObfsPluginOpts(BaseModel):
    mode: Literal['tls', 'http']
    host: Optional[str] = Field(default="bing.com")


class V2rayPluginOpts(BaseModel):
    mode: Literal['websocket'] = 'websocket'
    host: Optional[str] = Field(default="bing.com")
    path: Optional[str] = None
    tls: Optional[bool] = False
    fingerprint: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    skip_cert_verify: Optional[bool] = Field(False, alias='skip-cert-verify')
    mux: Optional[bool] = True
    v2ray_http_upgrade: Optional[bool] = Field(False, alias='v2ray-http-upgrade')
    v2ray_http_upgrade_fast_open: Optional[bool] = Field(False, alias='v2ray-http-upgrade-fast-open')


class GostPluginOpts(BaseModel):
    mode: Literal['websocket'] = 'websocket'
    host: Optional[str] = Field(default="bing.com")
    path: Optional[str] = None
    tls: Optional[bool] = False
    fingerprint: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    skip_cert_verify: Optional[bool] = Field(False, alias='skip-cert-verify')
    mux: Optional[bool] = True


class ShadowTlsPluginOpts(BaseModel):
    password: Optional[str] = None
    host: str
    fingerprint: Optional[str] = None
    skip_cert_verify: Optional[bool] = Field(False, alias='skip-cert-verify')
    version: Optional[Literal[1, 2, 3]] = 2
    alpn: Optional[List[str]] = None


class RestlsPluginOpts(BaseModel):
    password: str
    host: str
    version_hint: str = Field(alias='version-hint')
    restls_script: Optional[str] = Field(None, alias='restls-script')


class ShadowsocksProxy(ProxyBase):
    type: Literal['ss'] = 'ss'
    cipher: ShadowsocksCipherType
    password: str
    udp_over_tcp: Optional[bool] = Field(None, alias='udp-over-tcp')
    udp_over_tcp_version: Optional[Literal[1, 2]] = Field(1, alias='udp-over-tcp-version')
    client_fingerprint: Optional[Literal['chrome', 'ios', 'firefox', 'safari']] = Field(None,
                                                                                        alias='client-fingerprint')
    plugin: Optional[Literal['obfs', 'v2ray-plugin', 'shadow-tls', 'restls', 'gost-plugin']] = None
    plugin_opts: Optional[Union[
        ObfsPluginOpts,
        V2rayPluginOpts,
        GostPluginOpts,
        ShadowTlsPluginOpts,
        RestlsPluginOpts,
    ]] = Field(None, alias='plugin-opts')


    @field_validator("plugin_opts")
    @classmethod
    def validate_plugin_opts(cls, v, info: ValidationInfo):
        plugin = info.data.get("plugin")
        if plugin and v:
            if not isinstance(plugin, str):
                raise ValueError("plugin must be a string")
            plugin_model_map = {
                "obfs": "ObfsPluginOpts",
                "v2ray-plugin": "V2rayPluginOpts",
                "gost-plugin": "GostPluginOpts",
                "shadow-tls": "ShadowTlsPluginOpts",
                "restls": "RestlsPluginOpts",
            }

            expected_model = plugin_model_map.get(plugin)
            if expected_model and v.__class__.__name__ != expected_model:
                raise ValueError(f"{plugin} plugin requires {expected_model}")

        return v
