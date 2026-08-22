"""验证 V3 插件索引、目录与统一媒体身份合同。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = REPO_ROOT / "package.v3.json"
V3_ROOT = REPO_ROOT / "plugins.v3"
LEGACY_ID_KEYWORDS = {
    "tmdbid",
    "tmdb_id",
    "doubanid",
    "douban_id",
    "bangumiid",
    "bangumi_id",
    "anilistid",
    "anilist_id",
    "imdbid",
    "imdb_id",
    "tvdbid",
    "tvdb_id",
}
GENERIC_MEDIA_CALLS = {
    "recognize_media",
    "search_by_id",
    "add",
    "get_by_type_tmdbid",
    "get_by_media_identity",
}


def _load_json(path: Path) -> dict:
    """读取测试所需的插件索引。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    """返回函数调用的末级名称，兼容普通函数与属性调用。"""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _semantic_version(value: object) -> tuple[int, ...]:
    """把可带 ``v`` 前缀的版本转为可比较数字元组。"""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(value))
    assert match, f"非法版本：{value}"
    return tuple(int(part) for part in match.group(1).split("."))


def _normalized_version(value: object, width: int = 4) -> tuple[int, ...]:
    """补齐版本段，避免 ``2.0`` 与 ``2.0.0`` 被误判为不同版本。"""
    parsed = _semantic_version(value)
    return parsed + (0,) * (width - len(parsed))


def _legacy_metadata(
    plugin_id: str,
    package_v2: dict,
    package_v1: dict,
) -> dict | None:
    """返回插件的旧代索引元数据；V3 原生插件没有旧代条目。"""
    metadata = package_v2.get(plugin_id)
    if metadata is not None:
        return metadata
    return package_v1.get(plugin_id)


def test_v3_index_has_matching_dedicated_plugins() -> None:
    """V3 条目必须具有独立目录；迁移插件还需在旧索引阻断 V3。"""
    package = _load_json(PACKAGE_PATH)
    package_v2 = _load_json(REPO_ROOT / "package.v2.json")
    package_v1 = _load_json(REPO_ROOT / "package.json")
    assert package
    for plugin_id, metadata in package.items():
        assert (V3_ROOT / plugin_id.lower() / "__init__.py").is_file()
        assert metadata.get("system_version") == ">=3.0.0"
        old_metadata = _legacy_metadata(plugin_id, package_v2, package_v1)
        if old_metadata is not None:
            assert old_metadata.get("v3") is False


def test_v3_versions_use_next_major_and_descending_history() -> None:
    """迁移插件进入 V3 时必须跃迁主版本，所有历史均按语义版本降序。"""
    package = _load_json(PACKAGE_PATH)
    package_v2 = _load_json(REPO_ROOT / "package.v2.json")
    package_v1 = _load_json(REPO_ROOT / "package.json")
    for plugin_id, metadata in package.items():
        old_metadata = _legacy_metadata(plugin_id, package_v2, package_v1)
        if old_metadata is not None:
            old_major = _semantic_version(old_metadata["version"])[0]
            assert _semantic_version(metadata["version"])[0] == old_major + 1

        history_versions = list(metadata["history"])
        assert _normalized_version(history_versions[0]) == _normalized_version(metadata["version"])
        normalized_history = [_normalized_version(item) for item in history_versions]
        assert normalized_history == sorted(normalized_history, reverse=True)


def test_history_migrator_targets_v3() -> None:
    """V3 历史迁移插件的展示、配置与落库语义不得继续指向 V2。"""
    metadata = _load_json(PACKAGE_PATH)["HistoryToV2"]
    source = (V3_ROOT / "historytov2/__init__.py").read_text(encoding="utf-8")
    assert "迁移至V3" in metadata["name"]
    assert "当前 MoviePilot V3" in metadata["description"]
    assert 'plugin_config_prefix = "historytov3_"' in source
    assert "__insert_v3_history" in source
    assert "迁移至 V2" not in source


def test_v3_sources_use_unified_media_contract() -> None:
    """V3 通用媒体链不得继续传旧来源专有 ID，也不得依赖已删除的 MusicChain。"""
    violations = []
    for source_file in sorted(V3_ROOT.rglob("*.py")):
        source = source_file.read_text(encoding="utf-8")
        if "MusicChain" in source or "app.chain.music" in source:
            violations.append(f"{source_file}: 引用了 MusicChain")
        tree = ast.parse(source, filename=str(source_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in GENERIC_MEDIA_CALLS:
                continue
            legacy_args = sorted({item.arg for item in node.keywords if item.arg in LEGACY_ID_KEYWORDS})
            if legacy_args:
                violations.append(f"{source_file}:{node.lineno}: {legacy_args}")
    assert not violations, "\n".join(violations)
