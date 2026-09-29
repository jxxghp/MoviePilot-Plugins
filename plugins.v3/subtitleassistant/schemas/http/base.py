"""HTTP schema 的私有 Pydantic 基础设施。"""

from pydantic import BaseModel, ConfigDict

__all__: list[str] = []


class ApiModel(BaseModel):
    """拒绝未知字段并支持从 adapter 对象显式投影的 HTTP schema 基类。"""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        strict=True,
        validate_assignment=True,
    )
