"""V3 插件依赖清单和宿主安装边界合同。"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


REPO_ROOT = Path(__file__).resolve().parents[2]
V3_ROOT = REPO_ROOT / "plugins.v3"
PROCESS_CALLS = {
    "call",
    "check_call",
    "check_output",
    "Popen",
    "run",
    "system",
}


def _pyproject_files() -> list[Path]:
    """返回 V3 插件提交的现代依赖清单。"""
    return sorted(V3_ROOT.glob("*/pyproject.toml"))


def _load_pyproject(path: Path) -> dict:
    """读取一份 TOML 清单。"""
    with path.open("rb") as file_obj:
        return tomllib.load(file_obj)


def _call_name(node: ast.Call) -> str:
    """返回调用表达式的末级名称。"""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _literal_tokens(node: ast.AST) -> set[str]:
    """收集调用参数中的字符串字面量，用于识别直接包管理命令。"""
    return {
        child.value.casefold()
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def test_v3_dependency_manifests_use_pyproject_only() -> None:
    """V3 运行时只提交现代清单，不携带旧 requirements 或插件锁文件。"""
    assert _pyproject_files()
    assert list(V3_ROOT.glob("*/requirements.txt")) == []
    assert list(V3_ROOT.glob("*/uv.lock")) == []


@pytest.mark.parametrize("pyproject_path", _pyproject_files())
def test_v3_pyproject_declares_static_dependencies_only(
        pyproject_path: Path,
) -> None:
    """插件版本不在依赖清单重复维护，依赖必须保持可静态解析。"""
    document = _load_pyproject(pyproject_path)
    project = document["project"]

    assert project["name"] == f"moviepilot-plugin-{pyproject_path.parent.name}"
    assert project.get("dynamic") == ["version"]
    assert "version" not in project
    assert project.get("requires-python") == ">=3.12"

    dependencies = project.get("dependencies")
    assert isinstance(dependencies, list)
    assert all(isinstance(item, str) for item in dependencies)
    for item in dependencies:
        Requirement(item)


@pytest.mark.parametrize("pyproject_path", _pyproject_files())
def test_v3_uv_sources_reference_declared_dependencies_and_indexes(
        pyproject_path: Path,
) -> None:
    """具名索引只能绑定已声明依赖，且引用必须指向同清单中的有效索引。"""
    document = _load_pyproject(pyproject_path)
    dependencies = {
        canonicalize_name(Requirement(item).name)
        for item in document["project"].get("dependencies", [])
    }
    uv_config = document.get("tool", {}).get("uv", {})
    indexes = uv_config.get("index", [])
    sources = uv_config.get("sources", {})

    index_names = [item.get("name") for item in indexes]
    assert all(isinstance(name, str) and name for name in index_names)
    assert len(index_names) == len(set(index_names))
    for item in indexes:
        assert item.get("url", "").startswith("https://")

    referenced_indexes = set()
    for package_name, source in sources.items():
        assert canonicalize_name(package_name) in dependencies
        assert isinstance(source, dict)
        index_name = source.get("index")
        assert index_name in index_names
        referenced_indexes.add(index_name)
    assert set(index_names) == referenced_indexes


def test_v3_plugins_do_not_execute_package_managers() -> None:
    """插件不得通过子进程绕过宿主修改共享 Python 环境。"""
    violations = []
    for source_file in sorted(V3_ROOT.rglob("*.py")):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in PROCESS_CALLS:
                continue
            tokens = _literal_tokens(node)
            invokes_pip = "pip" in tokens and "install" in tokens
            invokes_uv = "uv" in tokens and bool({"pip", "sync"} & tokens)
            if invokes_pip or invokes_uv:
                violations.append(f"{source_file.relative_to(REPO_ROOT)}:{node.lineno}")

    assert violations == []
