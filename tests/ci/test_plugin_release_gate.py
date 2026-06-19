"""验证插件版本校验在本地 push、PR 和 Release 三个入口保持一致。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / ".github/scripts/check_plugin_versions.py"
PRE_PUSH = REPO_ROOT / ".githooks/pre-push"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-gate.yml"
TEST_RUNNER = REPO_ROOT / "tests/run.py"


def _write_fixture(repo: Path, package_version: str, source_version: str) -> None:
    """构造最小 v2 插件仓，隔离验证 checker 与 Hook 的退出码。"""
    plugin_dir = repo / "plugins.v2/example"
    plugin_dir.mkdir(parents=True)
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package.v2.json").write_text(
        json.dumps(
            {
                "Example": {
                    "version": package_version,
                    "release": True,
                }
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "class Example:\n"
        f'    plugin_version = "{source_version}"\n',
        encoding="utf-8",
    )
    checker_target = repo / ".github/scripts/check_plugin_versions.py"
    checker_target.parent.mkdir(parents=True)
    shutil.copy2(CHECKER, checker_target)


def _run_checker(repo: Path, *package_files: Path | str) -> subprocess.CompletedProcess[str]:
    """从指定目录运行 checker，便于覆盖 cwd 与 package 路径组合。"""
    args = ["python3", str(CHECKER)]
    args.extend(str(package_file) for package_file in package_files)
    return subprocess.run(
        args,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_checker_rejects_mismatched_versions(tmp_path: Path) -> None:
    """package 与源码版本不一致时必须返回失败，防止错误资产进入发布流程。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="1.0.0")

    result = _run_checker(tmp_path, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "版本不一致" in result.stdout


def test_checker_resolves_plugin_dir_relative_to_package_file(tmp_path: Path) -> None:
    """从其他 cwd 调用时，插件目录应相对 package 文件定位。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="2.0.0", source_version="2.0.0")

    result = _run_checker(tmp_path, repo / "package.json", repo / "package.v2.json")

    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_reports_missing_release_plugin_dir(tmp_path: Path) -> None:
    """release=true 的插件缺少源码目录时应失败，避免发布项被静默跳过。"""
    repo = tmp_path / "repo"
    (repo / ".github/scripts").mkdir(parents=True)
    shutil.copy2(CHECKER, repo / ".github/scripts/check_plugin_versions.py")
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package.v2.json").write_text(
        json.dumps({"MissingPlugin": {"version": "1.0.0", "release": True}}),
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "缺少插件目录" in result.stdout
    assert "plugins.v2/missingplugin" in result.stdout


def test_checker_reads_class_level_plugin_version_only(tmp_path: Path) -> None:
    """只接受类级 plugin_version，避免函数内局部变量被误识别为插件版本。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="1.2.3", source_version="0.0.0")
    init_file = repo / "plugins.v2/example/__init__.py"
    init_file.write_text(
        "def helper():\n"
        "    plugin_version = '1.2.3'\n"
        "    return plugin_version\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "未在" in result.stdout
    assert "类级 plugin_version" in result.stdout


def test_checker_accepts_annotated_class_level_plugin_version(tmp_path: Path) -> None:
    """类级注解赋值的 plugin_version 也是有效插件版本声明。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="1.2.3", source_version="0.0.0")
    init_file = repo / "plugins.v2/example/__init__.py"
    init_file.write_text(
        "class Example:\n"
        "    plugin_version: str = '1.2.3'\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_push_propagates_version_gate_failure(tmp_path: Path) -> None:
    """pre-push 必须传播 checker 非零状态，确保 git push 在上传前被拒绝。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="1.0.0")
    hook_target = tmp_path / ".githooks/pre-push"
    hook_target.parent.mkdir(parents=True)
    shutil.copy2(PRE_PUSH, hook_target)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["sh", ".githooks/pre-push"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "插件版本门禁失败" in result.stdout


def test_pre_push_accepts_matching_versions(tmp_path: Path) -> None:
    """版本一致时 pre-push 应允许上传，避免正常插件发布被误拦截。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    hook_target = tmp_path / ".githooks/pre-push"
    hook_target.parent.mkdir(parents=True)
    shutil.copy2(PRE_PUSH, hook_target)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["sh", ".githooks/pre-push"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "插件版本门禁通过" in result.stdout


def test_pr_workflow_runs_gate_for_every_main_pull_request() -> None:
    """Required Check 不得使用 paths 过滤，否则部分 PR 会一直缺少强制状态。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "paths:" not in workflow
    assert "name: Plugin release gate" in workflow
    assert "python .github/scripts/check_plugin_versions.py package.json package.v2.json" in workflow


def test_current_repository_passes_version_gate() -> None:
    """启用 Ruleset 前真实 main 基线必须通过，否则所有 PR 都无法合并。"""
    result = subprocess.run(
        ["python3", str(CHECKER), "package.json", "package.v2.json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_full_test_runner_includes_ci_gate_tests() -> None:
    """push 前全量入口必须执行 CI 工具测试，防止门禁实现脱离常规回归。"""
    runner = TEST_RUNNER.read_text(encoding="utf-8")

    assert 'for generation in ("ci", "v2", "v1"):' in runner
