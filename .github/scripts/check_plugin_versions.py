#!/usr/bin/env python3
"""校验插件市场版本与插件源码版本一致。

Release workflow 依赖 package.json/package.v2.json 生成 tag 和资产名；
若插件目录内的 plugin_version 不同步，运行时会继续展示旧版本。这里在打包前失败退出，
避免发布资产与插件自报版本不一致。
"""

from __future__ import annotations

import ast
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)


def _load_package(path: Path) -> dict:
    """读取 package 文件；文件不存在时返回空字典，便于同一脚本兼容 v1/v2。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _plugin_dir(package_file: Path, plugin_id: str) -> Path | None:
    """按 package 文件定位对应插件目录，避免 v1/v2 同名插件互相串线。"""
    plugin_id_lc = plugin_id.lower()
    base_dir = Path("plugins.v2") if package_file.name == "package.v2.json" else Path("plugins")
    candidate = package_file.parent / base_dir / plugin_id_lc
    return candidate if candidate.is_dir() else None


def _expected_plugin_dir(package_file: Path, plugin_id: str) -> Path:
    """返回 package 条目对应的插件目录，用于缺失目录时输出可定位错误。"""
    plugin_id_lc = plugin_id.lower()
    base_dir = Path("plugins.v2") if package_file.name == "package.v2.json" else Path("plugins")
    return package_file.parent / base_dir / plugin_id_lc


def _plugin_version(init_file: Path) -> str | None:
    """从 __init__.py 类级属性中提取 plugin_version 字面量。"""
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for node in class_node.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


def check_package(path: Path) -> list[str]:
    """校验单个 package 文件，返回所有错误文本。"""
    errors: list[str] = []
    package = _load_package(path)
    for plugin_id, meta in package.items():
        if not isinstance(meta, dict) or meta.get("release") is not True:
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
    return errors


def main() -> int:
    """命令入口：所有 package 均通过时返回 0，否则打印错误并返回 1。"""
    package_files = [Path(arg) for arg in sys.argv[1:]] or [Path("package.json"), Path("package.v2.json")]
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
