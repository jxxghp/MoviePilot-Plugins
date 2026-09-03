from typing import Optional, Dict, Literal

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin


class HttpProxy(ProxyBase, TLSMixin):
    type: Literal['http'] = 'http'
    username: Optional[str] = None
    password: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
