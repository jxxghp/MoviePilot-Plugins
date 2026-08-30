"""V3 插件依赖真实安装门禁测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "scripts/check_v3_dependency_install.py"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-gate.yml"


def _load_install_module():
    """按文件路径导入安装门禁脚本。"""
    spec = importlib.util.spec_from_file_location(
        "check_v3_dependency_install",
        INSTALL_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_discovery_covers_every_v3_pyproject() -> None:
    """门禁必须自动覆盖全部 V3 modern manifest。"""
    module = _load_install_module()
    expected = sorted((REPO_ROOT / "plugins.v3").glob("*/pyproject.toml"))

    assert expected
    assert module.discover_manifests() == expected


def test_manifest_platforms_default_to_product_matrix() -> None:
    """未声明窄平台的普通插件必须覆盖 V3 标准五平台。"""
    module = _load_install_module()
    manifest = REPO_ROOT / "plugins.v3/agentresourceofficer/pyproject.toml"

    assert module.manifest_platforms(manifest) == module.SUPPORTED_PLATFORMS


def test_animeupscale_dependency_gate_matches_linux_cuda_contract() -> None:
    """AnimeUpscale 的大体积 CUDA 依赖只在真实支持的 Linux x64 安装。"""
    module = _load_install_module()
    manifest = REPO_ROOT / "plugins.v3/animeupscale/pyproject.toml"

    assert module.manifest_platforms(manifest) == frozenset({"linux-x64"})


def test_autosubv2_dependency_gate_excludes_unsupported_macos_intel() -> None:
    """AutoSubv2 只在 Python 3.14 依赖可安装的平台进入真实安装门禁。"""
    module = _load_install_module()
    manifest = REPO_ROOT / "plugins.v3/autosubv2/pyproject.toml"

    assert module.manifest_platforms(manifest) == frozenset(
        {"linux-x64", "linux-arm64", "windows-x64", "macos-arm64"}
    )


def test_installation_uses_fresh_environment_and_host_manifest_semantics(
    tmp_path: Path,
) -> None:
    """安装命令必须面向隔离解释器并通过 -r 消费原始 pyproject。"""
    module = _load_install_module()
    environment = tmp_path / ".venv"
    manifest = REPO_ROOT / "plugins.v3/agentresourceofficer/pyproject.toml"

    create, install, healthcheck = module.installation_commands(
        uv_bin="uv",
        python_spec="3.14",
        environment=environment,
        manifest=manifest,
        windows=False,
    )

    python_bin = environment / "bin/python"
    assert create == ["uv", "venv", "--python", "3.14", str(environment)]
    assert install == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_bin),
        "-r",
        str(manifest),
    ]
    assert healthcheck == ["uv", "pip", "check", "--python", str(python_bin)]


def test_windows_environment_uses_scripts_python(tmp_path: Path) -> None:
    """Windows runner 必须把依赖安装到目标 venv，而不是 runner 全局环境。"""
    module = _load_install_module()

    assert module.venv_python(tmp_path / ".venv", windows=True) == (
        tmp_path / ".venv/Scripts/python.exe"
    )


def test_workflow_runs_scoped_five_platform_install_matrix() -> None:
    """PR 门禁应在相关变更时按平台执行真实安装脚本。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    job_start = workflow.index("  plugin-dependency-install-gate:")
    job_end = len(workflow)
    install_job = workflow[job_start:job_end]

    expected_targets = {
        "ubuntu-latest": "linux-x64",
        "ubuntu-24.04-arm": "linux-arm64",
        "windows-latest": "windows-x64",
        "macos-15-intel": "macos-x64",
        "macos-15": "macos-arm64",
    }
    for runner, platform in expected_targets.items():
        assert f"os: {runner}" in install_job
        assert f"platform: {platform}" in install_job
    assert "runs-on: ${{ matrix.os }}" in install_job
    assert "fetch-depth: 0" in install_job
    assert (
        'git diff --quiet "${{ github.event.pull_request.base.sha }}" HEAD'
        in install_job
    )
    for pathspec in (
        "plugins.v3/*/pyproject.toml",
        "scripts/check_v3_dependency_install.py",
        "tests/ci/test_v3_dependency_install_gate.py",
        ".github/workflows/plugin-gate.yml",
    ):
        assert pathspec in install_job
    assert "steps.dependency-scope.outputs.run == 'true'" in install_job
    assert "--platform \"${{ matrix.platform }}\"" in install_job
