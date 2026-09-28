#!/usr/bin/env python3
"""校验插件市场版本与插件源码版本一致。

Release workflow 依赖 package.json/package.v2.json/package.v3.json 生成 tag 和资产名；
若插件目录内的 plugin_version 不同步，运行时会继续展示旧版本。这里在打包前失败退出，
避免发布资产与插件自报版本不一致。
"""

from __future__ import annotations

import ast
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)


PACKAGE_PLUGIN_DIRS = {
    "package.v2.json": Path("plugins.v2"),
    "package.v3.json": Path("plugins.v3"),
}


def _load_package(path: Path) -> dict:
    """读取 package 文件；文件不存在时返回空字典，便于同一脚本兼容各代索引。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _plugin_dir(package_file: Path, plugin_id: str) -> Path | None:
    """按 package 文件定位对应插件目录，避免不同代同名插件互相串线。"""
    plugin_id_lc = plugin_id.lower()
    base_dir = PACKAGE_PLUGIN_DIRS.get(package_file.name, Path("plugins"))
    candidate = package_file.parent / base_dir / plugin_id_lc
    return candidate if candidate.is_dir() else None


def _expected_plugin_dir(package_file: Path, plugin_id: str) -> Path:
    """返回 package 条目对应的插件目录，用于缺失目录时输出可定位错误。"""
    plugin_id_lc = plugin_id.lower()
    base_dir = PACKAGE_PLUGIN_DIRS.get(package_file.name, Path("plugins"))
    return package_file.parent / base_dir / plugin_id_lc


def _plugin_version(init_file: Path) -> str | None:
    """从 __init__.py 类级属性中提取 plugin_version 字面量。"""
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for node in class_node.body:
            value_node = None
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets):
                    value_node = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "plugin_version"
            ):
                value_node = node.value
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                return value_node.value
    return None


def _semantic_version(value: object) -> tuple[int, ...] | None:
    """将索引版本解析为数字元组，兼容历史记录中的可选 ``v`` 前缀。"""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """按语义版本数字段比较两个版本，缺失的小版本段按零处理。"""
    width = max(len(left), len(right), 3)
    normalized_left = left + (0,) * (width - len(left))
    normalized_right = right + (0,) * (width - len(right))
    return (normalized_left > normalized_right) - (normalized_left < normalized_right)


def _check_v3_release_contract(path: Path, plugin_id: str, meta: dict) -> list[str]:
    """校验 V3 副本的大版本跃迁和版本历史顺序。"""
    errors: list[str] = []
    package_version = str(meta.get("version") or "").strip()
    parsed_version = _semantic_version(package_version)
    if parsed_version is None:
        errors.append(f"{path}: {plugin_id} 当前版本 {package_version or '<空>'} 不是合法语义版本")
    history = meta.get("history")
    if not isinstance(history, dict) or not history:
        return [f"{path}: {plugin_id} 缺少非空 history"]

    history_versions = list(history)
    parsed_history = [_semantic_version(item) for item in history_versions]
    for item, parsed in zip(history_versions, parsed_history):
        if parsed is None:
            errors.append(f"{path}: {plugin_id} history 包含非法版本 {item}")
    if parsed_version and parsed_history[0] and _compare_versions(parsed_history[0], parsed_version) != 0:
        errors.append(
            f"{path}: {plugin_id} history 首项 {history_versions[0]} 与当前版本 {package_version} 不一致"
        )
    for previous_key, previous, current_key, current in zip(
        history_versions, parsed_history, history_versions[1:], parsed_history[1:]
    ):
        if previous and current and _compare_versions(previous, current) < 0:
            errors.append(
                f"{path}: {plugin_id} history 未按语义版本降序排列：{previous_key} 在 {current_key} 之前"
            )

    legacy_meta = None
    for legacy_name in ("package.v2.json", "package.json"):
        legacy_meta = _load_package(path.parent / legacy_name).get(plugin_id)
        if isinstance(legacy_meta, dict):
            break
    legacy_version = _semantic_version(legacy_meta.get("version")) if isinstance(legacy_meta, dict) else None
    if parsed_version and legacy_version:
        expected_major = legacy_version[0] + 1
        if parsed_version[0] != expected_major:
            errors.append(
                f"{path}: {plugin_id} V3 版本应与旧代 {legacy_meta.get('version')} 保持大版本跃迁"
                f"（主版本 {expected_major}.x），当前为 {package_version}"
            )
    return errors


def check_package(path: Path) -> list[str]:
    """校验单个 package 文件，返回所有错误文本。"""
    errors: list[str] = []
    package = _load_package(path)
    for plugin_id, meta in package.items():
        if not isinstance(meta, dict):
            continue
        # V3 是独立实现，所有索引项都必须校验；旧代沿用仅门禁发布项的既有规则。
        if path.name != "package.v3.json" and meta.get("release") is not True:
            continue
        package_version = str(meta.get("version") or "").strip()
        plugin_dir = _plugin_dir(path, plugin_id)
        if not plugin_dir:
            errors.append(f"{path}: {plugin_id} 缺少插件目录 {_expected_plugin_dir(path, plugin_id)}")
            continue
        init_file = plugin_dir / "__init__.py"
        if not init_file.exists():
            errors.append(f"{path}: {plugin_id} 缺少 {init_file}")
            continue
        source_version = _plugin_version(init_file)
        if not source_version:
            errors.append(f"{path}: {plugin_id} 未在 {init_file} 中声明类级 plugin_version")
            continue
        if package_version != source_version:
            errors.append(
                f"{path}: {plugin_id} 版本不一致，package={package_version}, "
                f"plugin_version={source_version} ({init_file})"
            )
        if path.name == "package.v3.json":
            errors.extend(_check_v3_release_contract(path, plugin_id, meta))
    return errors


def main() -> int:
    """命令入口：所有 package 均通过时返回 0，否则打印错误并返回 1。"""
    package_files = [Path(arg) for arg in sys.argv[1:]] or [
        Path("package.json"),
        Path("package.v2.json"),
        Path("package.v3.json"),
    ]
    errors: list[str] = []
    for package_file in package_files:
        errors.extend(check_package(package_file))
    if errors:
        print("插件版本门禁失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("插件版本门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
