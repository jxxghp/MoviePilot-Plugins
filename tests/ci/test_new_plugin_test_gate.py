"""新增 V3 插件最低测试目录门禁。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts/check_new_plugin_tests.py"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-gate.yml"


def _init_repo(repo: Path) -> None:
    """初始化带功能分支的临时 Git 仓库。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)


def _copy_checker(repo: Path) -> None:
    """把当前检查脚本拷入临时仓库。"""
    target = repo / "scripts/check_new_plugin_tests.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CHECKER, target)


def _run_checker(repo: Path) -> subprocess.CompletedProcess[str]:
    """针对临时仓库运行检查脚本。"""
    return subprocess.run(
        ["python3", "scripts/check_new_plugin_tests.py", "--base-ref", "main"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_new_v3_plugin_without_tests_is_rejected(tmp_path: Path) -> None:
    """新增 V3 插件缺少对应测试时必须失败。"""
    _init_repo(tmp_path)
    _copy_checker(tmp_path)
    plugin_dir = tmp_path / "plugins.v3/newplugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("class NewPlugin:\n    pass\n", encoding="utf-8")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "plugins.v3/newplugin" in result.stdout
    assert "tests/v3/newplugin/test_*.py" in result.stdout


def test_new_v3_plugin_with_tests_is_accepted(tmp_path: Path) -> None:
    """新增 V3 插件存在对应 pytest 用例时通过。"""
    _init_repo(tmp_path)
    _copy_checker(tmp_path)
    (tmp_path / "plugins.v3/newplugin").mkdir(parents=True)
    (tmp_path / "plugins.v3/newplugin/__init__.py").write_text(
        "class NewPlugin:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/v3/newplugin").mkdir(parents=True)
    (tmp_path / "tests/v3/newplugin/test_plugin.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_new_legacy_plugin_remains_outside_v3_test_gate(tmp_path: Path) -> None:
    """历史代插件仍可维护和发版，不受新 V3 插件测试门禁约束。"""
    _init_repo(tmp_path)
    _copy_checker(tmp_path)
    plugin_dir = tmp_path / "plugins.v2/legacy"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("class Legacy:\n    pass\n", encoding="utf-8")

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_pr_workflow_runs_new_plugin_test_gate() -> None:
    """PR 工作流执行新增 V3 插件最低测试检查。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "name: Check new plugin tests" in workflow
    assert "fetch-depth: 0" in workflow
    assert "scripts/check_new_plugin_tests.py --base-ref origin/main" in workflow
