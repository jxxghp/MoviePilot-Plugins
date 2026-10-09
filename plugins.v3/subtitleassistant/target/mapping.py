"""整理历史目标的纯路径映射规则。

路径映射只负责把历史目标路径转换为当前本地路径。模块不访问文件系统，
也不负责创建目录或判断挂载状态；这些检查必须留在真正执行文件操作的
worker/改配服务中。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..schemas.target import PathMapping, PathMappingResolution


class PathMappingValidationError(ValueError):
    """路径映射配置不符合插件契约时抛出的校验错误。"""


def _normalize_prefix(value: str | Path, field_name: str) -> str:
    """校验并规范化一个绝对目录前缀，不触碰文件系统。"""

    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise PathMappingValidationError(f"{field_name}必须是绝对路径") from exc
    if not isinstance(raw, str):
        raise PathMappingValidationError(f"{field_name}必须是绝对路径")
    raw = raw.strip()
    if not raw or not os.path.isabs(raw):
        raise PathMappingValidationError(f"{field_name}必须是绝对路径")
    if "*" in raw or "?" in raw:
        raise PathMappingValidationError(f"{field_name}不支持通配符或正则表达式")
    normalized = os.path.normpath(raw)
    if not os.path.isabs(normalized):
        # 这只是防御性分支；normpath 对绝对路径通常不会改变根属性。
        raise PathMappingValidationError(f"{field_name}必须是绝对路径")
    return normalized


def validate_path_mappings(
    values: Iterable[PathMapping | Mapping[str, Any]] | None,
) -> tuple[PathMapping, ...]:
    """校验并规范化路径映射配置。

    校验只覆盖绝对路径、通配符、同路径和重复历史前缀，不探测目录、权限
    或挂载状态。返回值保持输入顺序，解析时再按匹配长度选择规则。
    """

    mappings: list[PathMapping] = []
    source_keys: set[str] = set()
    for index, value in enumerate(values or ()):
        if isinstance(value, PathMapping):
            mapping = value
        elif isinstance(value, Mapping):
            try:
                source = value["source_prefix"]
                target = value["target_prefix"]
            except KeyError as exc:
                raise PathMappingValidationError(f"第{index + 1}条路径映射缺少{exc.args[0]}") from exc
            try:
                mapping = PathMapping(
                    source_prefix=Path(_normalize_prefix(source, "历史目录前缀")),
                    target_prefix=Path(_normalize_prefix(target, "当前目录前缀")),
                )
            except ValueError as exc:
                raise PathMappingValidationError(str(exc)) from exc
        else:
            raise PathMappingValidationError(f"第{index + 1}条路径映射格式无效")
        source_key = os.path.normcase(str(mapping.source_prefix))
        if source_key in source_keys:
            raise PathMappingValidationError(f"历史目录前缀重复：{mapping.source_prefix}")
        source_keys.add(source_key)
        mappings.append(mapping)
    # 路径替换只允许单次执行。若某条规则的目标目录又正好作为另一条规则
    # 的源目录，后续维护者很容易误以为可以继续套用，因此在配置阶段直接
    # 拒绝这种链式关系。
    for current in mappings:
        for other in mappings:
            if current is other:
                continue
            if os.path.normcase(str(current.target_prefix)) != os.path.normcase(str(other.source_prefix)):
                continue
            raise PathMappingValidationError(
                f"路径映射不支持链式关系：{current.target_prefix}又是{other.source_prefix}的源目录"
            )
    return tuple(mappings)


def resolve_path(
    path: str | Path,
    mappings: Sequence[PathMapping],
) -> PathMappingResolution:
    """按最长目录分段前缀对路径执行一次映射。

    规则只匹配完整目录段，例如 `/media/tv` 不会匹配
    `/media/tv-archive`。多个规则同时命中时选择源前缀更长的规则；替换
    后不会再次参与匹配，因此不会形成链式映射。
    """

    original = _normalize_prefix(path, "历史目标路径")
    normalized_mappings = validate_path_mappings(mappings)
    best: PathMapping | None = None
    best_relative: Path | None = None
    for mapping in normalized_mappings:
        try:
            relative = Path(original).relative_to(mapping.source_prefix)
        except ValueError:
            continue
        if best is None or len(mapping.source_prefix.parts) > len(best.source_prefix.parts):
            best = mapping
            best_relative = relative
    if best is None or best_relative is None:
        return PathMappingResolution(original_path=Path(original), resolved_path=Path(original))
    resolved = os.path.normpath(os.path.join(best.target_prefix, os.fspath(best_relative)))
    return PathMappingResolution(
        original_path=Path(original),
        resolved_path=Path(resolved),
        mapping=best,
    )


__all__ = [
    "PathMappingResolution",
    "PathMappingValidationError",
    "resolve_path",
    "validate_path_mappings",
]
