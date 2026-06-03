"""pytest 全局引导：按本次运行目标选择 v1/v2 插件环境并装载网络守卫。

``tests/run.py`` 会把 v1/v2 放到独立 pytest 进程中运行；这里据本次目标路径只注入对应
插件目录，避免同一进程同时加载 ``plugins`` 与 ``plugins.v2`` 的同名包。
"""

from __future__ import annotations

from pathlib import Path

# 相对导入本仓薄壳，先定位同级 MoviePilot 后端并加入 ``sys.path``，再复用主程序共享引导。
from ._bootstrap import (
    block_real_network,  # noqa: F401  导入即注册主程序共享 autouse 网络守卫
    prepare_v1_backend,
    prepare_v2_backend,
)


def _selected_generation(config) -> str:
    """根据 pytest 本次目标路径判断插件代际，禁止同一进程混跑 v1/v2。"""
    generations = set()
    for arg in config.args:
        file_part = arg.split("::", 1)[0]
        path = Path(file_part).resolve().as_posix().replace("\\", "/")
        if "tests/v2" in path:
            generations.add("v2")
        elif "tests/v1" in path:
            generations.add("v1")
    if len(generations) == 1:
        return next(iter(generations))
    raise RuntimeError("插件仓单测必须按 tests/run.py 分 v1/v2 独立会话运行，避免同名插件包冲突")


def pytest_configure(config) -> None:
    """收集用例前隔离 CONFIG_DIR、建表并注入对应代际插件目录。"""
    if _selected_generation(config) == "v2":
        prepare_v2_backend()
    else:
        prepare_v1_backend()
