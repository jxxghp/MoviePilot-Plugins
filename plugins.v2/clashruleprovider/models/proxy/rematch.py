from typing import Literal

from pydantic import Field

from .proxybase import ProxyBase


class Rematch(ProxyBase):
    type: Literal["rematch"] = "rematch"
    target_rematch_name: str = Field(alias="target-rematch-name")
    target_sub_rule: str | None = Field(default=None, alias="target-sub-rule")
