"""pytest 全局引导。

收集任何用例前隔离 ``CONFIG_DIR``（确保后续 ``import app.*`` 不连主程序真实库），并复用主程序
``app/testing`` 的 autouse 网络守卫与 v1/v2 marker 逻辑。后端 / 插件目录注入交由各用例按 v1/v2
显式引导（见 :mod:`tests._bootstrap`），收集阶段不引入任一代插件包，规避 v1/v2 同名包冲突。
"""
# tests 为包（含 __init__.py），用相对导入引入同包的引导模块——绝对 ``from tests._bootstrap`` 在
# 多仓工作区里会被解析到其它仓的 tests（报“找不到 _bootstrap”），相对导入无歧义。导入 _bootstrap
# 时其模块级代码会定位同级 MoviePilot 后端并加入 sys.path，使后续 app.* / app.testing 可用；
# isolate_config_dir 须早于首个 import app.db（app.db 在 import 期即按 CONFIG_PATH 连库），故最先调用。
from ._bootstrap import isolate_config_dir

isolate_config_dir()

import pytest  # noqa: E402
from app.testing.bootstrap import mark_plugin_generation  # noqa: E402
from app.testing.network_guard import block_real_network  # noqa: E402,F401  复用主程序 autouse 网络守卫


def pytest_collection_modifyitems(config, items):
    """按所在目录自动为用例打 v1/v2 marker（逻辑复用主程序共享实现）。"""
    mark_plugin_generation(items, pytest)
