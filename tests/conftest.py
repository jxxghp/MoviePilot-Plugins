"""pytest 全局引导。

收集任何用例前隔离 ``CONFIG_DIR``（确保后续 ``import app.*`` 不连主程序真实库），并复用主程序
``app/testing`` 的 autouse 网络守卫与 v1/v2 marker 逻辑。后端 / 插件目录注入交由各用例按 v1/v2
显式引导（见 :mod:`tests._bootstrap`），收集阶段不引入任一代插件包，规避 v1/v2 同名包冲突。
"""
import sys
from pathlib import Path

# 将仓库根置于 sys.path，使 ``tests._bootstrap`` 可被导入（兼容 pytest 与直接运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# import 副作用：tests._bootstrap 定位后端并入 sys.path，使后续 app.* / app.testing 可用；
# isolate_config_dir 须早于首个 import app.db（其在 import 期即按 CONFIG_PATH 连库）
from tests._bootstrap import isolate_config_dir  # noqa: E402

isolate_config_dir()

import pytest  # noqa: E402
from app.testing.bootstrap import mark_plugin_generation  # noqa: E402
from app.testing.network_guard import block_real_network  # noqa: E402,F401  复用主程序 autouse 网络守卫


def pytest_collection_modifyitems(config, items):
    """按所在目录自动为用例打 v1/v2 marker（逻辑复用主程序共享实现）。"""
    mark_plugin_generation(items, pytest)
