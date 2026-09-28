"""在隔离环境中按声明平台真实安装 V3 插件依赖清单。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = REPO_ROOT / "plugins.v3"
V3_PACKAGE = REPO_ROOT / "package.v3.json"
# package.v3.json 中的 free-threaded 运行时（v3t）声明字段；与主程序
# app.domain.plugin.PLUGIN_FREE_THREADED_FIELD 语义一致：缺省视为兼容，只有显式 false 表示不支持
FREE_THREADED_FIELD = "v3t"
# 目标运行时 ABI 与 uv 解释器请求的对应关系；cp314t 对应 v3t 镜像的 free-threaded 解释器
ABI_PYTHON_SPECS = {
    "cp314": "3.14",
    "cp314t": "3.14t",
}
FREE_THREADED_ABIS = frozenset({"cp314t"})
# v3t 运行镜像不含编译工具链；cp314t 门禁环境出现这些命令时，源码构建会被放过而使结论失真
BUILD_TOOLCHAIN_COMMANDS = ("cc", "gcc", "c++", "g++", "clang", "cargo", "rustc")
# 在目标 venv 内确认解释器确实关闭了 GIL，防止 uv 请求回落到标准构建后误判门禁通过
FREE_THREADED_PROBE = (
    "import sys, sysconfig; "
    "sys.exit(0 if sysconfig.get_config_var('Py_GIL_DISABLED') else 1)"
)
SUPPORTED_PLATFORMS = frozenset(
    {
        "linux-x64",
        "linux-arm64",
        "windows-x64",
        "macos-x64",
        "macos-arm64",
    }
)


def discover_manifests(root: Path = V3_ROOT) -> list[Path]:
    """返回仓库中全部 V3 modern manifest。"""
    return sorted(root.glob("*/pyproject.toml"))


def manifest_platforms(manifest: Path) -> frozenset[str]:
    """返回清单声明的安装门禁平台，未声明时覆盖标准五平台。"""
    with manifest.open("rb") as file_obj:
        document = tomllib.load(file_obj)
    configured = (
        document.get("tool", {})
        .get("moviepilot", {})
        .get("dependency-gate", {})
        .get("platforms")
    )
    if configured is None:
        return SUPPORTED_PLATFORMS
    if (
        not isinstance(configured, list)
        or not configured
        or not all(isinstance(item, str) for item in configured)
    ):
        raise ValueError(f"{manifest} 的 dependency-gate.platforms 必须是非空字符串列表")
    platforms = frozenset(configured)
    unknown = platforms - SUPPORTED_PLATFORMS
    if unknown:
        raise ValueError(f"{manifest} 声明了未知安装平台：{sorted(unknown)}")
    return platforms


def load_free_threaded_opt_outs(
    manifests: list[Path],
    package_path: Path | None = None,
) -> frozenset[Path]:
    """返回在 package.v3.json 中显式声明 "v3t": false 的插件清单。

    插件目录名是 package.v3.json 插件 ID 的小写形式；每份清单必须能唯一对应到一个插件 ID，
    否则 v3t 声明无法可靠生效，直接报错而不是按缺省兼容静默放行。
    """
    package_path = package_path or V3_PACKAGE
    with package_path.open(encoding="utf-8") as file_obj:
        package = json.load(file_obj)
    entries: dict[str, dict] = {}
    for plugin_id, plugin_info in package.items():
        directory = plugin_id.lower()
        if directory in entries:
            raise ValueError(f"{package_path.name} 存在大小写冲突的插件 ID：{plugin_id}")
        entries[directory] = plugin_info

    opt_outs: set[Path] = set()
    for manifest in manifests:
        plugin_info = entries.get(manifest.parent.name)
        if plugin_info is None:
            raise ValueError(f"{manifest} 未在 {package_path.name} 中找到对应插件 ID")
        # 与主程序一致只识别布尔 false，其他值（含缺省）均视为兼容 free-threaded 运行时
        if plugin_info.get(FREE_THREADED_FIELD) is False:
            opt_outs.add(manifest)
    return frozenset(opt_outs)


def venv_python(environment: Path, *, windows: bool | None = None) -> Path:
    """返回目标虚拟环境的解释器路径。"""
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def installation_commands(
    *,
    uv_bin: str,
    python_spec: str,
    environment: Path,
    manifest: Path,
    abi: str = "cp314",
    windows: bool | None = None,
) -> tuple[list[str], ...]:
    """构造与宿主插件安装语义一致的隔离安装和健康检查命令。

    cp314t 在创建 venv 后额外校验解释器为 free-threaded 构建，再执行安装。
    """
    python_bin = venv_python(environment, windows=windows)
    create = [uv_bin, "venv", "--python", python_spec, str(environment)]
    abi_checks = (
        [[str(python_bin), "-c", FREE_THREADED_PROBE]]
        if abi in FREE_THREADED_ABIS
        else []
    )
    return (
        create,
        *abi_checks,
        [
            uv_bin,
            "pip",
            "install",
            "--python",
            str(python_bin),
            "-r",
            str(manifest),
        ],
        [uv_bin, "pip", "check", "--python", str(python_bin)],
    )


def verify_manifest(
    *,
    uv_bin: str,
    python_spec: str,
    manifest: Path,
    abi: str = "cp314",
) -> None:
    """在一次性虚拟环境中安装并检查指定清单。"""
    prefix = f"moviepilot-{manifest.parent.name}-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        environment = Path(temp_dir) / ".venv"
        for command in installation_commands(
            uv_bin=uv_bin,
            python_spec=python_spec,
            environment=environment,
            manifest=manifest,
            abi=abi,
        ):
            subprocess.run(command, cwd=REPO_ROOT, check=True)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Install V3 plugin manifests supported by a CI platform.",
    )
    parser.add_argument(
        "--abi",
        default="cp314",
        choices=sorted(ABI_PYTHON_SPECS),
        help="目标运行时 ABI；cp314t 使用 free-threaded 解释器并遵循 v3t 声明",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="目标 Python 解释器请求，缺省按 --abi 选择",
    )
    parser.add_argument(
        "--require-no-toolchain",
        action="store_true",
        help="cp314t 门禁环境存在编译工具链时直接失败，保证与 v3t 镜像一致",
    )
    parser.add_argument("--uv", default="uv", help="uv 可执行文件")
    parser.add_argument(
        "--platform",
        required=True,
        choices=sorted(SUPPORTED_PLATFORMS),
        help="当前依赖安装门禁平台",
    )
    return parser.parse_args()


def resolve_python_spec(abi: str, override: str | None = None) -> str:
    """返回目标 ABI 使用的 uv 解释器请求，显式 --python 优先。"""
    return override or ABI_PYTHON_SPECS[abi]


def detect_build_toolchain(which=shutil.which) -> list[str]:
    """返回 PATH 中可用的编译工具链命令。"""
    return [command for command in BUILD_TOOLCHAIN_COMMANDS if which(command)]


def is_environment_failure(err: subprocess.CalledProcessError) -> bool:
    """判断失败是否发生在创建或校验目标解释器阶段，而不是插件依赖安装阶段。"""
    command = [str(item) for item in err.cmd]
    return command[1:2] == ["venv"] or FREE_THREADED_PROBE in command


def free_threaded_failure_message(relative_manifest: Path) -> str:
    """返回 cp314t 下插件依赖安装失败时的修复指引。"""
    return (
        f"{relative_manifest}：该插件依赖无法在 free-threaded 运行时（v3t）安装"
        "（v3t 镜像不含编译工具链，每个依赖都需要 cp314t wheel 或纯 Python sdist）；"
        f'修复依赖或在 package.v3.json 为该插件标记 "{FREE_THREADED_FIELD}": false'
    )


def main() -> int:
    """执行当前平台全部适用 V3 插件依赖的真实安装门禁。

    cp314 遇到首个失败即退出；cp314t 收集全部失败后统一报告，便于一次确定需要修复或
    声明 v3t=false 的插件。
    """
    args = parse_args()
    python_spec = resolve_python_spec(args.abi, args.python)
    free_threaded = args.abi in FREE_THREADED_ABIS
    uv_bin = shutil.which(args.uv)
    if not uv_bin:
        print(f"未找到 uv 可执行文件：{args.uv}")
        return 1

    manifests = discover_manifests()
    if not manifests:
        print("未发现 V3 插件 pyproject.toml，拒绝空门禁")
        return 1

    try:
        selected = [
            manifest
            for manifest in manifests
            if args.platform in manifest_platforms(manifest)
        ]
    except ValueError as err:
        print(err)
        return 1
    if not selected:
        print(f"{args.platform} 没有适用的 V3 依赖清单，拒绝空平台门禁")
        return 1

    opt_outs: frozenset[Path] = frozenset()
    if free_threaded:
        toolchain = detect_build_toolchain()
        if toolchain:
            notice = (
                f"当前环境存在编译工具链 {toolchain}，依赖可能从源码构建成功，"
                "与不含工具链的 v3t 镜像不一致"
            )
            if args.require_no_toolchain:
                print(f"{notice}，拒绝执行 cp314t 门禁")
                return 1
            print(f"警告：{notice}，结果仅供参考")
        try:
            opt_outs = load_free_threaded_opt_outs(manifests)
        except (OSError, ValueError) as err:
            print(err)
            return 1

    label = f"{args.platform} {args.abi}"
    installed = 0
    failures: list[str] = []
    for manifest in manifests:
        relative_manifest = manifest.relative_to(REPO_ROOT)
        if manifest not in selected:
            print(f"跳过不支持 {args.platform} 的 {relative_manifest}")
            continue
        if manifest in opt_outs:
            print(
                f"跳过 package.v3.json 声明 \"{FREE_THREADED_FIELD}\": false 的 "
                f"{relative_manifest}：插件不支持 free-threaded 运行时"
            )
            continue
        print(f"真实安装 {relative_manifest}（{args.abi}）", flush=True)
        try:
            verify_manifest(
                uv_bin=uv_bin,
                python_spec=python_spec,
                manifest=manifest,
                abi=args.abi,
            )
        except subprocess.CalledProcessError as err:
            if is_environment_failure(err):
                # 解释器不可用或不是 free-threaded 构建属于门禁环境问题，与插件依赖无关
                print(f"无法准备 {python_spec} 目标解释器，退出码：{err.returncode}")
                return err.returncode or 1
            if not free_threaded:
                print(f"{relative_manifest} 安装门禁失败，退出码：{err.returncode}")
                return err.returncode or 1
            failures.append(free_threaded_failure_message(relative_manifest))
            print(f"{relative_manifest} 安装门禁失败，退出码：{err.returncode}")
            continue
        installed += 1

    if failures:
        print(f"{label} V3 插件依赖真实安装门禁失败：{len(failures)} 份清单")
        for message in failures:
            print(f"- {message}")
        return 1
    print(f"{label} V3 插件依赖真实安装门禁通过：{installed} 份清单")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
