from typing import Optional, Literal

from pydantic import Field

from .proxybase import ProxyBase
from .tlsmixin import TLSMixin
from .networkmixin import NetworkMixin


class AnyTLSProxy(ProxyBase, TLSMixin, NetworkMixin):
    type: Literal['anytls'] = 'anytls'
    password: str
    idle_session_check_interval: Optional[int] = Field(30, alias='idle-session-check-interval')
    idle_session_timeout: Optional[int] = Field(30, alias='idle-session-timeout')
    min_idle_session: Optional[int] = Field(0, alias='min-idle-session')
