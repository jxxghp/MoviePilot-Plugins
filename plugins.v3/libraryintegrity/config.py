"""插件配置：默认值、归一化与扫描选项转换。"""

from __future__ import annotations

from typing import Any, Optional

from .checks import parse_identity_overrides, parse_ignore_rules, parse_number_mappings
from .models import VERSION_DIMENSIONS
from .scanner import ScanOptions

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "notify": True,
    "onlyonce": False,
    "cron": "0 3 * * 0",
    # 数据源
    "use_emby": True,
    "servers": [],
    "libraries": [],
    "read_nfo": True,
    "path_mappings": "",
    "local_dirs": "",
    "local_probe": False,
    "probe_max_files": 300,
    "probe_path": "",
    # 检查项
    "check_missing": True,
    "check_versions": True,
    "check_duplicates": True,
    "dimensions": ["resolution", "video_codec", "hdr"],
    "air_buffer_days": 2,
    "include_specials": False,
    "only_existing_seasons": False,
    "ignore_mixed": False,
    # AI
    "ai_enabled": False,
    "ai_summary": False,
    # 规则
    "ignore_rules": "",
    "number_mappings": "",
    "identity_overrides": "",
}

_BOOL_KEYS = [key for key, value in DEFAULT_CONFIG.items() if isinstance(value, bool)]
_TEXT_KEYS = ["path_mappings", "local_dirs", "probe_path", "ignore_rules", "number_mappings", "identity_overrides"]


def _str_list(value: Any) -> list[str]:
    """把列表或逗号分隔文本转换为去空去重的字符串列表。"""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).replace("，", ",").split(",")
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """把取值转换为限定范围内的整数。"""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """合并默认值并修正类型，保证后续逻辑拿到的配置结构稳定。"""
    raw = dict(config or {})
    result = dict(DEFAULT_CONFIG)
    result.update({key: raw[key] for key in DEFAULT_CONFIG if key in raw and raw[key] is not None})
    for key in _BOOL_KEYS:
        result[key] = bool(result[key])
    for key in _TEXT_KEYS:
        result[key] = str(result.get(key) or "")
    result["cron"] = str(result.get("cron") or "").strip()
    result["probe_path"] = result["probe_path"].strip()
    result["servers"] = _str_list(result.get("servers"))
    result["libraries"] = _str_list(result.get("libraries"))
    result["dimensions"] = [d for d in _str_list(result.get("dimensions")) if d in VERSION_DIMENSIONS]
    result["air_buffer_days"] = _bounded_int(result.get("air_buffer_days"), 2, 0, 60)
    result["probe_max_files"] = _bounded_int(result.get("probe_max_files"), 300, 0, 100000)
    return result


def local_dirs(config: dict[str, Any]) -> list[str]:
    """返回配置的本地扫描目录，每行一个，# 开头为注释。"""
    return [
        line.strip() for line in config["local_dirs"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def to_scan_options(config: dict[str, Any]) -> ScanOptions:
    """把归一化后的配置转换为扫描选项。"""
    return ScanOptions(
        check_missing=config["check_missing"],
        check_versions=config["check_versions"],
        check_duplicates=config["check_duplicates"],
        dimensions=list(config["dimensions"]),
        air_buffer_days=config["air_buffer_days"],
        include_specials=config["include_specials"],
        only_existing_seasons=config["only_existing_seasons"],
        ignore_mixed=config["ignore_mixed"],
        number_mappings=parse_number_mappings(config["number_mappings"]),
        identity_overrides=parse_identity_overrides(config["identity_overrides"]),
        ignore_rules=parse_ignore_rules(config["ignore_rules"]),
        ai_summary=config["ai_enabled"] and config["ai_summary"],
    )
