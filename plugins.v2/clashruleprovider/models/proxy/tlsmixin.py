from enum import StrEnum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class ClientFingerprint(StrEnum):
    chrome = 'chrome'
    firefox = 'firefox'
    safari = 'safari'
    ios = 'ios'
    android = 'android'
    edge = 'edge'
    n360 = '360'
    qq = 'qq'
    random = 'random'


class RealityOpts(BaseModel):
    public_key: str = Field(..., alias='public-key')
    short_id: Optional[str] = Field(None, alias='short-id')
    support_x25519mlkem768: Optional[bool] = Field(None, alias='support-x25519mlkem768')


class EchOpts(BaseModel):
    enable: bool = False
    config: str


class RestlsOpts(BaseModel):
    password: str
    version_hint: Literal["tls12", "tls13"] | None = Field(None, alias="version-hint")
    restls_script: str | None = Field(default=None, alias="restls-script")


class JlsOpts(BaseModel):
    username: str
    password: str


class ShadowTlsOpts(BaseModel):
    password: str
    version: Literal["v1", "v2", "v3"] = Field(default="v2")


class DeferInstanceDerivedWriteTime(BaseModel):
    base_nanoseconds: int = Field(alias="base-nanoseconds")
    uniform_random_multiplier_nanoseconds: int = Field(alias="uniform-random-multiplier-nanoseconds")


class TlsmirrorOpts(BaseModel):
    primary_key: str = Field(alias="primary-key")
    explicit_nonce_ciphersuites: list[int] = Field(alias="explicit-nonce-ciphersuites")
    defer_instance_derived_write_time: DeferInstanceDerivedWriteTime | None = None


class RealmOpts(BaseModel):
    """Realm 配置选项"""
    enable: bool = False
    server_url: Optional[str] = Field(None, alias="server-url")
    token: Optional[str] = None
    realm_id: Optional[str] = Field(None, alias="realm-id")
    stun_servers: Optional[List[str]] = Field(None, alias="stun-servers")
    sni: Optional[str] = None
    skip_cert_verify: Optional[bool] = Field(None, alias="skip-cert-verify")
    name_cert_verify: Optional[str] = Field(None, alias="name-cert-verify")
    fingerprint: Optional[str] = None
    certificate: Optional[str] = None
    private_key: Optional[str] = Field(None, alias="private-key")
    alpn: Optional[List[str]] = None


class TLSMixin(BaseModel):
    """TLS 配置混入类"""
    tls: Optional[bool] = None
    sni: Optional[str] = None
    servername: Optional[str] = None
    fingerprint: Optional[str] = None
    alpn: Optional[List[str]] = None
    skip_cert_verify: Optional[bool] = Field(None, alias="skip-cert-verify")
    client_fingerprint: Optional[ClientFingerprint] = Field(None, alias="client-fingerprint")
    reality_opts: Optional[RealityOpts] = Field(None, alias="reality-opts")
    ech_opts: Optional[EchOpts] = Field(None, alias="ech-opts")
    restls_opts: Optional[RestlsOpts] = Field(None, alias="restls-opts")
    jls_opts: Optional[JlsOpts] = Field(None, alias="jls-opts")
    shadow_tls_opts: Optional[ShadowTlsOpts] = Field(None, alias="shadow-tls-opts")
    tlsmirror_opts: Optional[TlsmirrorOpts] = Field(None, alias="tlsmirror-opts")
