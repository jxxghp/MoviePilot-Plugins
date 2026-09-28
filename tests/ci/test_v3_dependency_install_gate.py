"""V3 插件依赖真实安装门禁测试。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def _job_block(workflow: str, job_id: str) -> str:
    """截取 workflow 中指定 job 的文本块。"""
    start = workflow.index(f"  {job_id}:\n")
    next_job = workflow.find("\n  plugin-", start + 1)
    return workflow[start : next_job if next_job != -1 else len(workflow)]


def _write_package(tmp_path: Path, package: dict) -> Path:
    """写入测试用 package.v3.json。"""
    package_path = tmp_path / "package.v3.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    return package_path


def _write_manifest(tmp_path: Path, directory: str) -> Path:
    """写入测试用插件清单并返回路径。"""
    manifest = tmp_path / "plugins.v3" / directory / "pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    return manifest


def test_abi_selects_standard_or_free_threaded_interpreter() -> None:
    """--abi 缺省选择标准 3.14，cp314t 选择 free-threaded 3.14t，显式 --python 优先。"""
    module = _load_install_module()

    assert module.resolve_python_spec("cp314") == "3.14"
    assert module.resolve_python_spec("cp314t") == "3.14t"
    assert module.resolve_python_spec("cp314t", "/opt/python3.14t") == (
        "/opt/python3.14t"
    )


def test_free_threaded_installation_probes_gil_disabled_interpreter(
    tmp_path: Path,
) -> None:
    """cp314t 必须在安装前确认 venv 解释器确实是 free-threaded 构建。"""
    module = _load_install_module()
    environment = tmp_path / ".venv"
    manifest = REPO_ROOT / "plugins.v3/tvfirstwatch/pyproject.toml"

    commands = module.installation_commands(
        uv_bin="uv",
        python_spec="3.14t",
        environment=environment,
        manifest=manifest,
        abi="cp314t",
        windows=False,
    )

    python_bin = str(environment / "bin/python")
    assert [command[:2] for command in commands] == [
        ["uv", "venv"],
        [python_bin, "-c"],
        ["uv", "pip"],
        ["uv", "pip"],
    ]
    assert commands[0][3] == "3.14t"
    assert "Py_GIL_DISABLED" in commands[1][2]


def test_v3t_opt_outs_follow_host_explicit_false_semantics(tmp_path: Path) -> None:
    """只有显式 "v3t": false 跳过 cp314t 安装，缺省或其他值都视为兼容。"""
    module = _load_install_module()
    opted_out = _write_manifest(tmp_path, "optedout")
    default = _write_manifest(tmp_path, "defaultplugin")
    truthy = _write_manifest(tmp_path, "explicittrue")
    package_path = _write_package(
        tmp_path,
        {
            "OptedOut": {"v3t": False},
            "DefaultPlugin": {},
            "ExplicitTrue": {"v3t": True},
        },
    )

    assert module.load_free_threaded_opt_outs(
        [opted_out, default, truthy],
        package_path,
    ) == frozenset({opted_out})


def test_v3t_opt_outs_reject_manifest_without_package_entry(tmp_path: Path) -> None:
    """清单无法对应到 package.v3.json 插件 ID 时不能按缺省兼容静默放行。"""
    module = _load_install_module()
    manifest = _write_manifest(tmp_path, "orphan")
    package_path = _write_package(tmp_path, {"Other": {}})

    with pytest.raises(ValueError, match="未在 package.v3.json 中找到对应插件 ID"):
        module.load_free_threaded_opt_outs([manifest], package_path)


def test_repository_manifests_map_to_package_entries() -> None:
    """仓库内每份 V3 清单都必须能按目录名映射到 package.v3.json 插件 ID。"""
    module = _load_install_module()

    opt_outs = module.load_free_threaded_opt_outs(module.discover_manifests())

    assert REPO_ROOT / "plugins.v3/autosubv2/pyproject.toml" in opt_outs


def test_build_toolchain_detection_lists_available_commands() -> None:
    """cp314t 门禁需识别会让源码构建被放过的编译工具链。"""
    module = _load_install_module()
    available = {"gcc", "cargo"}

    def fake_which(command: str) -> str | None:
        return f"/usr/bin/{command}" if command in available else None

    assert module.detect_build_toolchain(fake_which) == ["gcc", "cargo"]
    assert module.detect_build_toolchain(lambda _command: None) == []


def _run_main(
    module,
    monkeypatch,
    tmp_path: Path,
    argv: list[str],
    *,
    failing: set[str],
):
    """以替身安装流程执行 main，返回退出码与实际尝试安装的插件目录。"""
    manifests = [
        _write_manifest(tmp_path, name)
        for name in ("alpha", "beta", "gamma", "delta")
    ]
    package_path = _write_package(
        tmp_path,
        {
            "Alpha": {},
            "Beta": {},
            "Gamma": {"v3t": False},
            "Delta": {},
        },
    )
    attempted: list[str] = []

    def fake_verify(*, uv_bin, python_spec, manifest, abi):
        attempted.append(manifest.parent.name)
        assert python_spec == module.ABI_PYTHON_SPECS[abi]
        if manifest.parent.name in failing:
            raise subprocess.CalledProcessError(
                1,
                [uv_bin, "pip", "install", "-r", str(manifest)],
            )

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_manifests", lambda: manifests)
    monkeypatch.setattr(module, "V3_PACKAGE", package_path)
    monkeypatch.setattr(module, "verify_manifest", fake_verify)
    monkeypatch.setattr(module, "detect_build_toolchain", lambda: [])
    monkeypatch.setattr(module.shutil, "which", lambda command: f"/bin/{command}")
    monkeypatch.setattr(sys, "argv", ["check_v3_dependency_install.py", *argv])
    return module.main(), attempted


@pytest.fixture
def install_module():
    """加载安装门禁脚本。"""
    return _load_install_module()


def test_free_threaded_gate_skips_opt_outs_and_reports_all_failures(
    install_module,
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """cp314t 跳过 v3t=false 插件，并在收集全部失败后给出标记指引。"""
    exit_code, attempted = _run_main(
        install_module,
        monkeypatch,
        tmp_path,
        ["--abi", "cp314t", "--platform", "linux-x64"],
        failing={"alpha", "delta"},
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert attempted == ["alpha", "beta", "delta"]
    assert "跳过 package.v3.json 声明 \"v3t\": false 的 plugins.v3/gamma" in output
    assert "linux-x64 cp314t V3 插件依赖真实安装门禁失败：2 份清单" in output
    for name in ("alpha", "delta"):
        assert (
            f"- plugins.v3/{name}/pyproject.toml：该插件依赖无法在 free-threaded "
            "运行时（v3t）安装"
        ) in output
    assert "v3t 镜像不含编译工具链" in output
    assert 'package.v3.json 为该插件标记 "v3t": false' in output


def test_standard_gate_ignores_v3t_and_stops_at_first_failure(
    install_module,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """cp314 不受 v3t 声明影响，并保持首个失败即退出。"""
    exit_code, attempted = _run_main(
        install_module,
        monkeypatch,
        tmp_path,
        ["--platform", "linux-x64"],
        failing={"alpha"},
    )

    assert exit_code == 1
    assert attempted == ["alpha"]


def test_free_threaded_gate_passes_when_remaining_plugins_install(
    install_module,
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """cp314t 全部非声明插件安装成功时门禁通过，计数不含跳过项。"""
    exit_code, attempted = _run_main(
        install_module,
        monkeypatch,
        tmp_path,
        ["--abi", "cp314t", "--platform", "linux-arm64"],
        failing=set(),
    )

    assert exit_code == 0
    assert attempted == ["alpha", "beta", "delta"]
    assert "linux-arm64 cp314t V3 插件依赖真实安装门禁通过：3 份清单" in (
        capsys.readouterr().out
    )


def test_require_no_toolchain_rejects_contaminated_environment(
    install_module,
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """CI 开启 --require-no-toolchain 时，存在编译工具链必须在安装前失败。"""
    monkeypatch.setattr(install_module, "detect_build_toolchain", lambda: ["gcc"])
    manifests = [_write_manifest(tmp_path, "alpha")]
    monkeypatch.setattr(install_module, "discover_manifests", lambda: manifests)
    monkeypatch.setattr(
        install_module,
        "verify_manifest",
        lambda **_kwargs: pytest.fail("工具链污染时不应执行安装"),
    )
    monkeypatch.setattr(install_module.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_v3_dependency_install.py",
            "--abi",
            "cp314t",
            "--platform",
            "linux-x64",
            "--require-no-toolchain",
        ],
    )

    assert install_module.main() == 1
    assert "拒绝执行 cp314t 门禁" in capsys.readouterr().out


def test_workflow_runs_free_threaded_linux_gate_without_toolchain() -> None:
    """cp314t 门禁只覆盖 v3t 镜像平台，并在无工具链的同基底容器内执行。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    standard_job = _job_block(workflow, "plugin-dependency-install-gate")
    v3t_job = _job_block(workflow, "plugin-dependency-install-gate-v3t")

    assert "name: V3 dependency install (${{ matrix.name }}, cp314)" in standard_job
    assert '--abi cp314 --platform "${{ matrix.platform }}"' in standard_job
    assert "name: V3 dependency install (${{ matrix.name }}, cp314t)" in v3t_job
    for runner, platform in {
        "ubuntu-latest": "linux-x64",
        "ubuntu-24.04-arm": "linux-arm64",
    }.items():
        assert f"os: {runner}\n            platform: {platform}\n            abi: cp314t" in (
            v3t_job
        )
    assert v3t_job.count("abi: cp314t") == 2
    assert "container: python:3.14-slim-trixie" in v3t_job
    apt_lines = [line for line in v3t_job.splitlines() if "apt-get install" in line]
    assert apt_lines == [
        "          apt-get install -y --no-install-recommends git ca-certificates"
    ]
    assert '--abi "${{ matrix.abi }}"' in v3t_job
    assert "--require-no-toolchain" in v3t_job
    for job in (standard_job, v3t_job):
        assert "'package.v3.json'" in job
        assert "steps.dependency-scope.outputs.run == 'true'" in job
