#!/usr/bin/env python3
"""阻止联邦插件把 Vuetify 基础样式注入主程序文档。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FEDERATION_CONFIG_PATTERN = re.compile(r"\bfederation\s*\(")
DYNAMIC_CSS_PATTERN = re.compile(r"dynamicLoadingCss\s*\(\s*\[([^]]*)]", re.DOTALL)
CSS_PATH_PATTERN = re.compile(r"['\"]([^'\"]+\.css)['\"]")
SELECTOR_PATTERN = re.compile(r"(?:^|})\s*([^@{}][^{}]*)\{", re.MULTILINE)
GLOBAL_SELECTOR_PATTERN = re.compile(
    r"^(?:html\b|body\b|:root\b|\*\s*(?:$|[,>+~.#[:])|"
    r"\.v-|\.mdi-|\.rounded(?:\b|-)|\.elevation-\d+\b)"
)
PACKAGE_BY_GENERATION = {
    "plugins": "package.json",
    "plugins.v2": "package.v2.json",
    "plugins.v3": "package.v3.json",
}


def _federation_plugin_dirs(root: Path) -> list[Path]:
    """返回具有 Federation 配置或已构建 remoteEntry 的插件目录。"""
    plugin_dirs: set[Path] = set()
    for config in root.glob("plugins*/**/vite.config.*"):
        if "node_modules" in config.parts or not config.is_file():
            continue
        if FEDERATION_CONFIG_PATTERN.search(config.read_text(encoding="utf-8")):
            plugin_dirs.add(config.parent)
    for remote_entry in root.glob("plugins*/**/remoteEntry.js"):
        if "node_modules" in remote_entry.parts:
            continue
        relative = remote_entry.relative_to(root)
        if len(relative.parts) >= 2:
            plugin_dirs.add(root / relative.parts[0] / relative.parts[1])
    return sorted(plugin_dirs)


def _release_error(root: Path, plugin_dir: Path) -> str | None:
    """确保联邦插件会被 Release workflow 纳入正式资产打包。"""
    relative = plugin_dir.relative_to(root)
    package_name = PACKAGE_BY_GENERATION.get(relative.parts[0])
    if not package_name:
        return f"{relative}: 无法确定插件市场索引"
    package_path = root / package_name
    if not package_path.is_file():
        return f"{relative}: 缺少市场索引 {package_name}"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    matches = [
        (plugin_id, metadata)
        for plugin_id, metadata in package.items()
        if plugin_id.casefold() == plugin_dir.name.casefold()
    ]
    if not matches:
        return f"{relative}: 未在 {package_name} 中登记"
    plugin_id, metadata = matches[0]
    if not isinstance(metadata, dict) or metadata.get("release") is not True:
        return f"{package_name}: 联邦插件 {plugin_id} 必须设置 release=true"
    return None


def _referenced_css(remote_entry: Path) -> list[Path]:
    """解析 remoteEntry 的动态样式列表，并相对入口目录解析文件。"""
    source = remote_entry.read_text(encoding="utf-8")
    paths: set[Path] = set()
    for array_source in DYNAMIC_CSS_PATTERN.findall(source):
        for css_path in CSS_PATH_PATTERN.findall(array_source):
            paths.add((remote_entry.parent / css_path).resolve())
    return sorted(paths)


def _global_selectors(css_file: Path) -> list[str]:
    """提取会直接命中宿主页面的全局 Vuetify/reset 选择器。"""
    css = re.sub(r"/\*.*?\*/", "", css_file.read_text(encoding="utf-8"), flags=re.DOTALL)
    violations: set[str] = set()
    for selector_group in SELECTOR_PATTERN.findall(css):
        for selector in selector_group.split(","):
            normalized = re.sub(r"\s+", " ", selector).strip()
            if GLOBAL_SELECTOR_PATTERN.match(normalized):
                violations.add(normalized)
    return sorted(violations)


def check_repository(root: Path) -> list[str]:
    """检查所有联邦插件，返回可一次性修复的完整错误列表。"""
    errors: list[str] = []
    for plugin_dir in _federation_plugin_dirs(root):
        relative_plugin = plugin_dir.relative_to(root)
        release_error = _release_error(root, plugin_dir)
        if release_error:
            errors.append(release_error)
        shared_styles = sorted(
            plugin_dir.glob("**/__federation_shared_vuetify/styles-*.css")
        )
        for css_file in shared_styles:
            errors.append(
                f"{css_file.relative_to(root)}: 不得发布 Vuetify 共享基础样式"
            )

        remote_entries = sorted(plugin_dir.glob("**/remoteEntry.js"))
        for remote_entry in remote_entries:
            if "node_modules" in remote_entry.parts:
                continue
            for css_file in _referenced_css(remote_entry):
                try:
                    relative_css = css_file.relative_to(root)
                except ValueError:
                    errors.append(
                        f"{remote_entry.relative_to(root)}: CSS 引用越出仓库：{css_file}"
                    )
                    continue
                if not css_file.is_file():
                    errors.append(
                        f"{remote_entry.relative_to(root)}: CSS 文件不存在：{relative_css}"
                    )
                    continue
                selectors = _global_selectors(css_file)
                if selectors:
                    preview = ", ".join(selectors[:3])
                    errors.append(
                        f"{relative_css}: 包含未限定作用域的宿主样式选择器：{preview}"
                    )

        if not remote_entries:
            # 源码阶段允许尚未构建；发布前的版本门禁会再次执行本检查。
            print(f"跳过未构建联邦插件：{relative_plugin}")
    return errors


def parse_args() -> argparse.Namespace:
    """解析仓库根目录，便于测试夹具复用检查器。"""
    parser = argparse.ArgumentParser(description="检查联邦插件 CSS 是否污染宿主页面")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="插件仓库根目录",
    )
    return parser.parse_args()


def main() -> int:
    """命令入口。"""
    root = parse_args().root.resolve()
    errors = check_repository(root)
    if errors:
        print("联邦插件 CSS 门禁失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("联邦插件 CSS 门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
