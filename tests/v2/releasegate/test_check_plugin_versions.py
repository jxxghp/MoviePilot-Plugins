"""插件发布版本门禁脚本单测。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "check_plugin_versions.py"


def _load_module():
    """按文件路径加载脚本，避免要求 .github/scripts 成为 Python 包。"""
    spec = importlib.util.spec_from_file_location("check_plugin_versions", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_package(path: Path, plugin_id: str, version: str = "1.2.3") -> None:
    """写入最小 release=true package 条目。"""
    path.write_text(
        json.dumps({plugin_id: {"version": version, "release": True}}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_check_package_resolves_plugin_dir_relative_to_package_file(tmp_path):
    """从其他工作目录调用时，插件目录应相对 package 文件定位。"""
    module = _load_module()
    repo = tmp_path / "repo"
    plugin_dir = repo / "plugins.v2" / "demo"
    plugin_dir.mkdir(parents=True)
    package_file = repo / "package.v2.json"
    _write_package(package_file, "Demo")
    (plugin_dir / "__init__.py").write_text(
        "class Demo:\n"
        "    plugin_version = '1.2.3'\n",
        encoding="utf-8",
    )

    assert module.check_package(package_file) == []


def test_cli_resolves_package_paths_from_repo_root_when_run_elsewhere(tmp_path):
    """命令入口从其他工作目录运行时仍应读取仓库根的 package 文件。"""
    repo = tmp_path / "repo"
    plugin_dir = repo / "plugins.v2" / "demo"
    plugin_dir.mkdir(parents=True)
    _write_package(repo / "package.v2.json", "Demo")
    (repo / "package.json").write_text("{}", encoding="utf-8")
    (plugin_dir / "__init__.py").write_text(
        "class Demo:\n"
        "    plugin_version = '1.2.3'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(repo / "package.json"),
            str(repo / "package.v2.json"),
        ],
        cwd=tmp_path,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_check_package_reports_missing_release_plugin_dir(tmp_path):
    """release=true 的插件缺少源码目录时应失败，避免发布项被静默跳过。"""
    module = _load_module()
    package_file = tmp_path / "package.v2.json"
    _write_package(package_file, "MissingPlugin")

    errors = module.check_package(package_file)

    assert errors == [
        f"{package_file}: MissingPlugin 缺少插件目录 {tmp_path / 'plugins.v2' / 'missingplugin'}"
    ]


def test_check_package_reads_class_level_plugin_version_only(tmp_path):
    """只接受类级 plugin_version，避免函数内局部变量被误识别为插件版本。"""
    module = _load_module()
    plugin_dir = tmp_path / "plugins.v2" / "nestedonly"
    plugin_dir.mkdir(parents=True)
    package_file = tmp_path / "package.v2.json"
    _write_package(package_file, "NestedOnly")
    (plugin_dir / "__init__.py").write_text(
        "def helper():\n"
        "    plugin_version = '1.2.3'\n"
        "    return plugin_version\n",
        encoding="utf-8",
    )

    errors = module.check_package(package_file)

    assert errors == [
        f"{package_file}: NestedOnly 未在 {plugin_dir / '__init__.py'} 中声明类级 plugin_version"
    ]
