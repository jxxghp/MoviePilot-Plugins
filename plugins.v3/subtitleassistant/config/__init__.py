"""插件配置解析与公开投影能力的调用侧契约。"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..schemas.attribution import PackageAttributionStrategy
from ..schemas.config import PluginConfig
from ..schemas.source import SubtitleSource
from ..schemas.target import PathMapping

_DEFAULT_FORMAT_ORDER = ("ASS", "SSA", "SRT", "SUP")


def _normalize_format_priority(
    allowed_formats: Sequence[str],
    saved_priority: object,
) -> list[str]:
    """归一化宿主允许的字幕格式与保存顺序。"""

    allowed: list[str] = []
    for item in allowed_formats:
        normalized = str(item).strip().lstrip(".").upper()
        if normalized and normalized not in allowed:
            allowed.append(normalized)
    saved = (
        saved_priority if isinstance(saved_priority, Sequence) and not isinstance(saved_priority, (str, bytes)) else ()
    )
    priority: list[str] = []
    for item in (*saved, *_DEFAULT_FORMAT_ORDER):
        normalized = str(item).strip().lstrip(".").upper()
        if normalized in allowed and normalized not in priority:
            priority.append(normalized)
    priority.extend(item for item in allowed if item not in priority)
    return priority


def load_config(raw: Mapping[str, object] | None, allowed_formats: Sequence[str]) -> PluginConfig:
    """解析宿主原始配置为非敏感配置契约。"""

    values: Mapping[str, object] = raw if raw is not None else {}
    source_order: list[SubtitleSource] = []
    raw_source_priority = values.get("source_priority", ("moviepilot", "assrt", "opensubtitles"))
    source_priority = (
        raw_source_priority
        if isinstance(raw_source_priority, Sequence) and not isinstance(raw_source_priority, (str, bytes))
        else ()
    )
    for item in source_priority:
        try:
            source = SubtitleSource(str(item).strip().lower())
        except ValueError:
            continue
        if source not in source_order:
            source_order.append(source)
    source_order.extend(source for source in SubtitleSource if source not in source_order)
    try:
        raw_attempts = values.get("max_candidate_attempts", 3)
        attempts = int(raw_attempts) if isinstance(raw_attempts, (str, int, float)) else 3
    except (TypeError, ValueError):
        attempts = 3
    mapping_values = values.get("path_mappings")
    mappings: list[PathMapping] = []
    source_keys: set[str] = set()
    if isinstance(mapping_values, Sequence) and not isinstance(mapping_values, (str, bytes)):
        for index, item in enumerate(mapping_values):
            if not isinstance(item, Mapping):
                raise TypeError(f"第{index + 1}条路径映射格式无效")
            try:
                source = Path(str(item["source_prefix"])).expanduser()
                target = Path(str(item["target_prefix"])).expanduser()
            except KeyError as exc:
                raise ValueError(f"第{index + 1}条路径映射缺少{exc.args[0]}") from exc
            if not source.is_absolute() or not target.is_absolute():
                raise ValueError("路径映射前缀必须是绝对路径")
            if "*" in str(source) or "?" in str(source) or "*" in str(target) or "?" in str(target):
                raise ValueError("路径映射前缀不支持通配符")
            mapping = PathMapping(source_prefix=source, target_prefix=target)
            source_key = os.path.normcase(str(mapping.source_prefix))
            if source_key in source_keys:
                raise ValueError(f"历史目录前缀重复：{mapping.source_prefix}")
            source_keys.add(source_key)
            mappings.append(mapping)
    for current in mappings:
        for other in mappings:
            if current is not other and os.path.normcase(str(current.target_prefix)) == os.path.normcase(
                str(other.source_prefix)
            ):
                raise ValueError(f"路径映射不支持链式关系：{current.target_prefix}又是{other.source_prefix}的源目录")
    strategy = PackageAttributionStrategy(
        str(values.get("package_attribution_strategy", PackageAttributionStrategy.TRUST_PACKAGE.value))
    )
    return PluginConfig(
        enabled=bool(values.get("enabled", False)),
        moviepilot_enabled=bool(values.get("moviepilot_enabled", True)),
        opensubtitles_enabled=bool(values.get("opensubtitles_enabled", False)),
        assrt_enabled=bool(values.get("assrt_enabled", False)),
        allow_machine_translation=bool(values.get("allow_machine_translation", False)),
        max_candidate_attempts=min(10, max(1, attempts)),
        source_priority=source_order,
        format_priority=_normalize_format_priority(allowed_formats, values.get("format_priority")),
        path_mappings=tuple(mappings),
        package_attribution_strategy=strategy,
    )


def public_config(config: PluginConfig, **kwargs: object) -> dict[str, object]:
    """投影给宿主设置页的非敏感配置。"""

    return {
        "plugin_id": kwargs.get("plugin_id", "SubtitleAssistant"),
        "enabled": config.enabled,
        "moviepilot_enabled": config.moviepilot_enabled,
        "opensubtitles_enabled": config.opensubtitles_enabled,
        "assrt_enabled": config.assrt_enabled,
        "allow_machine_translation": config.allow_machine_translation,
        "max_candidate_attempts": config.max_candidate_attempts,
        "source_priority": [source.value for source in config.source_priority],
        "format_priority": list(config.format_priority),
        "path_mappings": [mapping.as_dict() for mapping in config.path_mappings],
        "package_attribution_strategy": config.package_attribution_strategy.value,
        **kwargs,
    }


__all__ = ["load_config", "public_config"]
