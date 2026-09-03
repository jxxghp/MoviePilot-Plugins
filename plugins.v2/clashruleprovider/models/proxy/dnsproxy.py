from typing import Literal

from .proxybase import ProxyBase


class DnsProxy(ProxyBase):
    type: Literal['dns'] = 'dns'
