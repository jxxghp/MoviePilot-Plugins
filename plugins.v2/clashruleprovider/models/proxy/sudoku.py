from typing import Literal

from pydantic import Field, BaseModel

from .proxybase import ProxyBase


class HttpMask(BaseModel):
    disable: bool
    mode: Literal["legacy", "stream", "poll", "auto", "ws"] = Field(default="legacy")
    tls: bool | None = Field(default=None)
    host: str | None = Field(default=None)
    path_root: str | None = Field(default=None, alias="path-root")
    multiplex: Literal["off", "auto", "on"] = Field(default="off")


class Sudoku(ProxyBase):
    type: Literal["sudoku"] = "sudoku"
    key: str
    aead_method: Literal["chacha20-poly1305", "aes-128-gcm", "none"] | None = Field(default=None, alias="aead-method")
    padding_min: int | None = Field(default=None, alias="padding-min")
    padding_max: int | None = Field(default=None, alias="padding-max")
    table_type: Literal["prefer_ascii", "prefer_entropy", "up_ascii_down_entropy", "up_entropy_down_ascii"] = Field(
        default="prefer_ascii", alias="table-type")
    custom_table: str | None = Field(default=None, alias="custom-table")
    custom_tables: list[str] = Field(default_factory=list, alias="custom-tables")
    multiplex: Literal["off", "auto", "on"] = Field(default="off")
    enable_pure_downlink: bool = Field(default=False, alias="enable-pure-downlink")
    httpmask: HttpMask | None = Field(default=None)
