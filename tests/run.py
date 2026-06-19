"""插件仓全量单测入口：CI 工具与 v1/v2 分别运行，命令行参数透传给 pytest。

plugins/（v1）与 plugins.v2/（v2）存在同名插件包，同一进程无法同时加载，故各代在
独立子进程运行；CI 工具测试不加载插件运行时。任一组非零退出码即整体失败，无用例的
分组直接跳过。路径以 __file__ 推导，从任意目录调用均可。
"""
import subprocess
import sys
from pathlib import Path

# 本文件位于 tests/ 下：其父为 tests 目录，再上一级为插件仓根
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent


def _run_generation(generation: str, extra_args: list) -> int:
    """在独立子进程运行某一代（v1/v2）的全部用例；该代无用例则跳过、返回 0。"""
    target = _TESTS_DIR / generation
    if not list(target.rglob("test_*.py")):
        return 0
    return subprocess.call(
        [sys.executable, "-m", "pytest", str(target), *extra_args],
        cwd=str(_REPO_ROOT),
    )


if __name__ == "__main__":
    extra = sys.argv[1:]
    exit_code = 0
    # CI 工具与 v1/v2 分会话运行；保留首个非零退出码作为整体结果。
    for generation in ("ci", "v2", "v1"):
        rc = _run_generation(generation, extra)
        exit_code = exit_code or rc
    sys.exit(exit_code)
