import time

from pydantic import BaseModel, Field

from .api import ConfigRequest
from .types import DataSource


class Metadata(BaseModel):
    """Metadata model for Clash items"""
    # source of the item
    source: DataSource = Field(default=DataSource.MANUAL)
    # whether the item is disabled
    disabled: bool = Field(default=False)
    # roles that cannot see the item
    invisible_to: list[str] = Field(default_factory=list)
    # additional remarks
    remark: str = Field(default="")
    # last modified time
    time_modified: float = Field(default_factory=lambda: time.time())
    # whether the item has been patched
    patched: bool = Field(default=False)

    def available(self, param: ConfigRequest | None = None) -> bool:
        return not self.disabled and (param is None or not any(param.resolve(expr) for expr in self.invisible_to))
