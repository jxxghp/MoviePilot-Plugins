from typing import Literal

from .proxybase import ProxyBase


class DirectProxy(ProxyBase):
    type: Literal['direct'] = 'direct'
