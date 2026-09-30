#!/usr/bin/env python3
"""
V3 插件导入边界门禁。

旧导入以宿主 ``app.runtime.compat.manifest`` 为准：凡需经 Compat 解析的模块或符号都属于
旧写法，与宿主 DEBUG 模式的旧导入告警口径一致。旧导入与直接访问宿主 Model、Session 工厂
的存量记录在基线中，只允许减少；引用其他插件的模块、修改 ``sys.path``、直接访问宿主数据库
文件和导入 SDK Legacy 没有存量，直接禁止。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = REPO_ROOT / "plugins.v3"
BASELINE_PATH = REPO_ROOT / "tests/ci/v3_import_baseline.json"

# 基线分区：Compat 旧导入与宿主数据层直连
LEGACY_SECTION = "legacy_imports"
HOST_DATA_SECTION = "host_data_access"
# 宿主 Session 工厂：V3 插件应经 Oper、Chain 或 SDK 访问宿主数据
_SESSION_FACTORIES = {"SessionFactory", "AsyncSessionFactory", "ScopedSession"}
# 宿主 SQLite 数据库文件名；插件直接打开会绕过宿主数据层，且 PostgreSQL 部署下不存在
_HOST_DB_FILE = re.compile(r"(^|/)user\.db$")
_OTHER_PLUGIN = re.compile(r"^app\.plugins\.([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class Violation:
    """一处直接禁止的越界访问。"""

    path: str  # 相对仓库根的文件路径
    line: int  # 源码行号
    message: str  # 违规说明

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def load_compat_manifest() -> ModuleType:
    """从宿主后端加载 Compat 清单；定位规则与插件测试引导一致。"""
    candidates = []
    env = os.environ.get("MOVIEPILOT_BACKEND_PATH")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(REPO_ROOT.parent / "MoviePilot")
    for backend in candidates:
        if (backend / "app/runtime/compat/manifest.py").is_file():
            if str(backend) not in sys.path:
                sys.path.insert(0, str(backend))
            return import_module("app.runtime.compat.manifest")
    raise RuntimeError(
        "未找到 MoviePilot 后端的 app/runtime/compat/manifest.py，"
        "请设置 MOVIEPILOT_BACKEND_PATH 或把后端放在插件仓同级目录"
    )


class _LegacyMatcher:
    """按 Compat 清单判断一次导入是否经兼容层解析。"""

    def __init__(self, manifest: ModuleType) -> None:
        self._modules = set(manifest.MODULE_ALIASES) | set(manifest.VIRTUAL_PACKAGES)
        self._packages = tuple(f"{name}." for name in manifest.PACKAGE_ALIASES)
        self._modules |= set(manifest.PACKAGE_ALIASES)
        self._symbols = {
            module: set(names)
            for exports in (manifest.SYMBOL_ALIASES, manifest.PACKAGE_EXPORTS)
            for module, names in exports.items()
        }

    def match(self, module: str, names: list[str]) -> list[str]:
        """返回命中的旧模块或旧符号，形如 ``app.log`` 或 ``app.plugins._PluginBase``。"""
        hits = []
        if module in self._modules or module.startswith(self._packages):
            hits.append(module)
        symbols = self._symbols.get(module, set())
        hits.extend(f"{module}.{name}" for name in names if name in symbols)
        return hits


def _string_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """收集字符串字面量，用于识别按字符串导入其他插件和打开宿主数据库文件。"""
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _mutates_sys_path(node: ast.AST) -> bool:
    """识别 ``sys.path.append/insert/extend`` 调用与对 ``sys.path`` 的赋值。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        target = node.func.value
        return (
            node.func.attr in {"append", "insert", "extend"}
            and isinstance(target, ast.Attribute)
            and target.attr == "path"
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
        )
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(item, ast.Attribute)
            and item.attr == "path"
            and isinstance(item.value, ast.Name)
            and item.value.id == "sys"
            for item in targets
        )
    return False


def _imports(tree: ast.AST) -> list[tuple[int, str, list[str]]]:
    """返回绝对导入的 (行号, 模块, 导入名)。"""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module, [alias.name for alias in node.names]))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, []) for alias in node.names)
    return found


def _python_files(plugin_dir: Path) -> list[Path]:
    """插件目录内随插件下发的 Python 源码。"""
    return sorted(
        path for path in plugin_dir.rglob("*.py")
        if "node_modules" not in path.parts
    )


def scan_plugin(
        plugin_dir: Path,
        matcher: _LegacyMatcher,
        root: Path = REPO_ROOT,
) -> tuple[dict[str, Counter[str]], list[Violation]]:
    """扫描单个 V3 插件，返回按基线分区的存量计数与直接禁止的越界访问。"""
    plugin_id = plugin_dir.name
    legacy: Counter[str] = Counter()
    host_data: Counter[str] = Counter()
    violations: list[Violation] = []
    for path in _python_files(plugin_dir):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as exc:
            violations.append(Violation(relative, exc.lineno or 0, f"无法解析：{exc.msg}"))
            continue
        for line, module, names in _imports(tree):
            legacy.update(matcher.match(module, names))
            if module == "app.db.models" or module.startswith("app.db.models."):
                host_data[module] += 1
            if module.startswith("app.db"):
                host_data.update(f"{module}.{name}" for name in names if name in _SESSION_FACTORIES)
            if module == "app.sdk._legacy" or module.startswith("app.sdk._legacy."):
                violations.append(Violation(relative, line, f"导入 SDK Legacy {module}"))
        for line, text in _string_literals(tree):
            other = _OTHER_PLUGIN.match(text)
            if other and other.group(1).lower() != plugin_id:
                violations.append(Violation(relative, line, f"引用其他插件的模块 {text}"))
            if _HOST_DB_FILE.search(text):
                violations.append(Violation(relative, line, f"直接访问宿主数据库文件 {text}"))
        for line, module, _names in _imports(tree):
            other = _OTHER_PLUGIN.match(module)
            if other and other.group(1).lower() != plugin_id:
                violations.append(Violation(relative, line, f"导入其他插件的模块 {module}"))
        for node in ast.walk(tree):
            if _mutates_sys_path(node):
                violations.append(Violation(relative, node.lineno, "修改 sys.path"))
    return {LEGACY_SECTION: legacy, HOST_DATA_SECTION: host_data}, violations


def scan_repository(
        matcher: _LegacyMatcher,
        v3_root: Path = V3_ROOT,
        root: Path = REPO_ROOT,
) -> tuple[dict[str, dict[str, dict[str, int]]], list[Violation]]:
    """扫描全部 V3 插件，返回 ``{分区: {插件: {模块或符号: 次数}}}`` 与直接禁止的越界访问。"""
    current: dict[str, dict[str, dict[str, int]]] = {LEGACY_SECTION: {}, HOST_DATA_SECTION: {}}
    violations: list[Violation] = []
    for plugin_dir in sorted(v3_root.iterdir()):
        if not (plugin_dir / "__init__.py").is_file():
            continue
        sections, found = scan_plugin(plugin_dir, matcher, root)
        for section, counts in sections.items():
            if counts:
                current[section][plugin_dir.name] = dict(sorted(counts.items()))
        violations.extend(found)
    return current, violations


def compare_baseline(
        current: dict[str, dict[str, dict[str, int]]],
        baseline: dict[str, dict[str, dict[str, int]]],
) -> tuple[list[str], list[str]]:
    """
    比较当前存量与基线。

    :return: (超出基线的条目, 已减少但基线未同步下调的条目)
    """
    increased, stale = [], []
    for section in (LEGACY_SECTION, HOST_DATA_SECTION):
        now_section, allowed_section = current.get(section, {}), baseline.get(section, {})
        for plugin in sorted(set(now_section) | set(allowed_section)):
            now, allowed = now_section.get(plugin, {}), allowed_section.get(plugin, {})
            for name in sorted(set(now) | set(allowed)):
                count, limit = now.get(name, 0), allowed.get(name, 0)
                item = f"plugins.v3/{plugin}: {name} {limit} -> {count}"
                if count > limit:
                    increased.append(f"[{section}] {item}")
                elif count < limit:
                    stale.append(f"[{section}] {item}")
    return increased, stale


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, dict[str, int]]]:
    """读取存量基线。"""
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(current: dict[str, dict[str, dict[str, int]]], path: Path = BASELINE_PATH) -> None:
    """写入当前存量作为新的基线。"""
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """执行门禁；``--write-baseline`` 只在存量减少后用于下调基线。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", action="store_true", help="存量减少后同步下调基线")
    args = parser.parse_args(argv)

    matcher = _LegacyMatcher(load_compat_manifest())
    current, violations = scan_repository(matcher)
    errors = [str(item) for item in violations]
    increased, stale = compare_baseline(current, load_baseline())
    if args.write_baseline:
        if increased:
            errors.extend(f"超出基线，不能写入：{item}" for item in increased)
        else:
            write_baseline(current)
            print(f"已写入 {BASELINE_PATH.relative_to(REPO_ROOT)}")
    else:
        errors.extend(
            f"超出基线，旧导入请改用 Compat 清单给出的新路径，宿主数据请经 Oper、Chain 或 SDK 访问：{item}"
            for item in increased
        )
        errors.extend(
            f"存量已减少，请运行 scripts/check_v3_imports.py --write-baseline 下调基线：{item}"
            for item in stale
        )
    if errors:
        print("V3 插件导入边界门禁失败：", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1
    if not args.write_baseline:
        print("V3 插件导入边界门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
