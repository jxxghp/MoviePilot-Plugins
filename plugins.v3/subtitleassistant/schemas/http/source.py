"""字幕源 HTTP 请求响应模型。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BeforeValidator, Field, JsonValue, model_validator

from ...schemas.source import SourceHealth, SubtitleSource
from .base import ApiModel

__all__ = ["CredentialUpdate", "SourceStatusItem"]


def _enum_parser[EnumType: Enum](enum_type: type[EnumType]) -> Callable[[object], object]:
    """把 HTTP JSON 中的枚举值显式解析为对应枚举。"""

    def parse(value: object) -> object:
        if value is None or isinstance(value, enum_type):
            return value
        if isinstance(value, str):
            try:
                return enum_type(value)
            except ValueError:
                return value
        return value

    return parse


def _datetime_parser(value: object) -> object:
    """把 ISO-8601 字符串显式解析为时间值。"""

    if isinstance(value, datetime) or not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


_SubtitleSource = Annotated[SubtitleSource, BeforeValidator(_enum_parser(SubtitleSource))]
_SourceHealth = Annotated[SourceHealth, BeforeValidator(_enum_parser(SourceHealth))]
_DateTimeOptional = Annotated[datetime | None, BeforeValidator(_datetime_parser)]


class SourceStatusItem(ApiModel):
    """字幕源状态安全响应项。"""

    source: _SubtitleSource
    enabled: bool
    configured: bool
    health: _SourceHealth
    last_checked_at: _DateTimeOptional
    last_success_at: _DateTimeOptional
    last_error_at: _DateTimeOptional
    last_error_summary: str | None
    last_duration_ms: int | None
    details: dict[str, JsonValue]


class CredentialUpdate(ApiModel):
    """外部字幕源凭据增量更新请求。"""

    api_key: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=512)
    password: str | None = Field(default=None, max_length=2048)
    token: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def require_nonempty_value(self) -> CredentialUpdate:
        """要求请求至少携带一个非空更新值。"""

        if not any(
            isinstance(value, str) and bool(value.strip())
            for value in (self.api_key, self.username, self.password, self.token)
        ):
            raise ValueError("至少提供一个非空凭据字段")
        return self

    def cleaned(self) -> dict[str, str]:
        """返回去除首尾空白后的非空字段。"""

        return {
            key: value.strip() for key, value in self.model_dump().items() if isinstance(value, str) and value.strip()
        }
