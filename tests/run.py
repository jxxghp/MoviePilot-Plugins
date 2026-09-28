"""插件仓当前 V3 运行环境回归入口。

``package.v2.json`` 是旧实现能否在 V3 加载的事实源。存在测试且未声明 ``v3: false``
的 V2 插件继续使用 V3 后端回归；明确不兼容的历史实现不进入 V3 门禁。各分组使用独立
子进程，避免同名插件包互相覆盖。
"""
import json
import subprocess
import sys
from pathlib import Path

# 本文件位于 tests/ 下：其父为 tests 目录，再上一级为插件仓根
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
_V2_PACKAGE = _REPO_ROOT / "package.v2.json"


def _contains_tests(path: Path) -> bool:
    """判断目录中是否存在 pytest 用例文件。"""
    return path.is_dir() and any(path.rglob("test_*.py"))


def compatible_v2_test_targets(
        tests_dir: Path = _TESTS_DIR,
        package_path: Path = _V2_PACKAGE,
) -> list[Path]:
    """按市场兼容标记收集仍由 V3 主程序承载的 V2 插件测试目录。"""
    package = json.loads(package_path.read_text(encoding="utf-8"))
    metadata_by_id = {
        plugin_id.casefold(): metadata
        for plugin_id, metadata in package.items()
    }
    targets = []
    for test_dir in sorted((tests_dir / "v2").iterdir()):
        if not _contains_tests(test_dir):
            continue
        metadata = metadata_by_id.get(test_dir.name.casefold())
        if metadata is None:
            raise RuntimeError(
                f"tests/v2/{test_dir.name} 在 package.v2.json 中没有对应插件条目"
            )
        if metadata.get("v3") is False:
            continue
        targets.append(test_dir)
    return targets


def _generation_targets(generation: str) -> list[Path]:
    """返回一个独立 pytest 会话需要执行的测试目标。"""
    if generation == "v2":
        return compatible_v2_test_targets()
    target = _TESTS_DIR / generation
    return [target] if _contains_tests(target) else []


def _run_generation(generation: str, extra_args: list) -> int:
    """在独立子进程运行一个测试分组；该组无用例则跳过。"""
    targets = _generation_targets(generation)
    if not targets:
        return 0
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            *(str(target) for target in targets),
            *extra_args,
        ],
        cwd=str(_REPO_ROOT),
    )


if __name__ == "__main__":
    extra = sys.argv[1:]
    exit_code = 0
    # CI 工具、V3 专用实现与兼容 V3 的旧实现分会话运行。
    for generation in ("ci", "v3", "v2"):
        rc = _run_generation(generation, extra)
        exit_code = exit_code or rc
    sys.exit(exit_code)
