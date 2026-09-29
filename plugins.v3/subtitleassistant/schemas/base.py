"""公共业务 schema 的私有 Pydantic 基础设施。"""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

__all__: list[str] = []


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，供 schema 默认值使用。"""

    return datetime.now(UTC)


def new_id() -> str:
    """生成 UUIDv4 字符串标识，供 schema 默认值使用。"""

    return str(uuid4())


class StrictModel(BaseModel):
    """拒绝未知字段、隐式类型转换并校验赋值的公共 schema 基类。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


def elapsed_ms(start: datetime | None, end: datetime | None = None) -> int | None:
    """计算两个时间点之间的毫秒数。"""

    if start is None:
        return None
    finish = end or utc_now()
    return max(0, int((finish - start).total_seconds() * 1000))
