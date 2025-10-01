from typing import Optional, Literal

from pydantic import Field, validator

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

    @validator('port', 'port_range', allow_reuse=True)
    def validate_port_config(cls, v, values):
        port = values.get('port')
        port_range = values.get('port_range')
        if not port and not port_range:
            raise ValueError("either port or port-range must be set")
        if port and port_range:
            raise ValueError("port and port-range cannot be set at the same time")
        return v
