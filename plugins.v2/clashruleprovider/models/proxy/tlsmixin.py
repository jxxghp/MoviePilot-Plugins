from enum import StrEnum
from typing import List, Optional

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


class TLSMixin(BaseModel):
    """TLS 配置混入类"""
    # TLS settings
    tls: Optional[bool] = None
    sni: Optional[str] = None
    servername: Optional[str] = None
    fingerprint: Optional[str] = None
    alpn: Optional[List[str]] = None
    skip_cert_verify: Optional[bool] = Field(None, alias='skip-cert-verify')
    client_fingerprint: Optional[ClientFingerprint] = Field(None, alias='client-fingerprint')
    reality_opts: Optional[RealityOpts] = Field(None, alias='reality-opts')
    ech_opts: Optional[EchOpts] = Field(None, alias='ech-opts')
