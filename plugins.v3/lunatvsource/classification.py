"""LunaTVSource classification extension declarations and fact extraction."""

from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .cms import CmsResult


CLASSIFICATION_PROTOCOL_VERSION = 1
LUNATV_SOURCE_ID = "lunatv"
CMS_SOURCE_KEY_FIELD = "extensions.lunatv.cms_source_key"
CMS_TYPE_NAME_FIELD = "extensions.lunatv.cms_type_name"
CMS_CLASS_NAMES_FIELD = "extensions.lunatv.cms_class_names"

_CMS_CLASS_SEPARATOR_RE = re.compile(r"[,，、/|;；]+")


def normalize_cms_class_names(value: Any) -> tuple[str, ...]:
    """Normalize a CMS class field into stable, ordered, unique labels."""

    if isinstance(value, (set, frozenset)):
        raw_values = sorted(str(item or "") for item in value)
    elif isinstance(value, (list, tuple)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = [str(value or "")]

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for candidate in _CMS_CLASS_SEPARATOR_RE.split(raw_value):
            name = candidate.strip()
            if name and name not in seen:
                seen.add(name)
                normalized.append(name)
    return tuple(normalized)


def _classification_sdk() -> Any | None:
    """Load the public host classification SDK when protocol V1 is available."""

    try:
        sdk = importlib.import_module("app.sdk.classification")
        version = int(
            getattr(sdk, "MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION", 0) or 0
        )
    except (ImportError, AttributeError, TypeError, ValueError):
        return None

    if version < CLASSIFICATION_PROTOCOL_VERSION:
        return None
    if not all(
        hasattr(sdk, name)
        for name in ("ClassificationFieldDefinition", "MediaSourceInfo")
    ):
        return None
    return sdk


def classification_protocol_available() -> bool:
    return _classification_sdk() is not None


def build_media_source_declaration() -> Any | None:
    """Build the optional host declaration for LunaTV classification fields."""

    sdk = _classification_sdk()
    if sdk is None:
        return None

    shared = {
        "operators": [
            "equals",
            "not_equals",
            "in",
            "not_in",
            "exists",
            "not_exists",
        ]
    }
    fields = [
        sdk.ClassificationFieldDefinition(
            id=CMS_SOURCE_KEY_FIELD,
            label="CMS 源标识",
            description="LunaTV CMS 源的稳定标识",
            value_type="string",
            **shared,
        ),
        sdk.ClassificationFieldDefinition(
            id=CMS_TYPE_NAME_FIELD,
            label="CMS 类型名称",
            description="Apple CMS 返回的原始类型名称",
            value_type="string",
            **shared,
        ),
        sdk.ClassificationFieldDefinition(
            id=CMS_CLASS_NAMES_FIELD,
            label="CMS 分类标签",
            description="Apple CMS 返回并规范化去重的分类标签",
            value_type="string_list",
            operators=[
                "contains_any",
                "contains_all",
                "contains_none",
                "exists",
                "not_exists",
            ],
        ),
    ]
    return sdk.MediaSourceInfo(
        name="LunaTV",
        media_source=LUNATV_SOURCE_ID,
        media_types=["电影", "电视剧"],
        classification_fields=fields,
    )


def extract_classification_facts(result: "CmsResult") -> dict[str, Any]:
    """Extract declared LunaTV facts already fetched from a CMS result."""

    facts: dict[str, Any] = {}
    source_key = str(getattr(result, "source_key", "") or "").strip()
    type_name = str(getattr(result, "cms_type_name", "") or "").strip()
    class_names = normalize_cms_class_names(
        getattr(result, "cms_class_names", ())
    )
    if source_key:
        facts[CMS_SOURCE_KEY_FIELD] = source_key
    if type_name:
        facts[CMS_TYPE_NAME_FIELD] = type_name
    if class_names:
        facts[CMS_CLASS_NAMES_FIELD] = list(class_names)
    return facts
