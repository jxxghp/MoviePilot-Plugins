from typing import Optional, Literal

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin


class Socks5Proxy(ProxyBase, TLSMixin):
    type: Literal['socks5'] = 'socks5'
    username: Optional[str] = None
    password: Optional[str] = None
