from typing import Optional, Literal

from pydantic import Field, model_validator

from .proxybase import ProxyBase


class MieruProxy(ProxyBase):
    type: Literal['mieru'] = 'mieru'
    username: str
    password: str
    port_range: Optional[str] = Field(None, alias='port-range')
    transport: Literal['TCP'] = 'TCP'
    multiplexing: Optional[Literal[
        'MULTIPLEXING_OFF', 'MULTIPLEXING_LOW', 'MULTIPLEXING_MIDDLE', 'MULTIPLEXING_HIGH']] = 'MULTIPLEXING_LOW'
    handshake_mode: Optional[Literal['HANDSHAKE_STANDARD', 'HANDSHAKE_NO_WAIT']] = 'HANDSHAKE_STANDARD'

    @model_validator(mode='after')
    def validate_port_config(self):
        """Pydantic v2 style model-level validation."""
        if not getattr(self, 'port', None) and not getattr(self, 'port_range', None):
            raise ValueError("either 'port' or 'port-range' must be set")
        if getattr(self, 'port', None) and getattr(self, 'port_range', None):
            raise ValueError("'port' and 'port-range' cannot be set at the same time")
        return self
