"""pytest 全局引导。

在收集任何用例之前隔离 ``CONFIG_DIR``，确保后续 ``import app.*`` 不会连到主程序
真实库。``sys.path`` 的后端 / 插件目录注入交由各用例按 v1/v2 显式引导
（见 :mod:`tests._bootstrap`），不在收集阶段引入任一代插件包，以规避 v1/v2 同名包冲突。
"""
import sys
from pathlib import Path

import pytest

# 将仓库根置于 sys.path，使共享引导 tests._bootstrap 可被导入（兼容 pytest 与直接运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._bootstrap import isolate_config_dir  # noqa: E402

# conftest 早于测试模块收集执行，保证 CONFIG_DIR 在首个 import app.* 之前生效
isolate_config_dir()


def pytest_collection_modifyitems(config, items):
    """按所在目录自动为用例打 v1/v2 marker，支持 ``pytest -m v2`` 选择运行。

    避免每个用例手动标注；与按目录运行（``pytest tests/v2``）二选一皆可。
    """
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/v2/" in path:
            item.add_marker(pytest.mark.v2)
        elif "/tests/v1/" in path:
            item.add_marker(pytest.mark.v1)
