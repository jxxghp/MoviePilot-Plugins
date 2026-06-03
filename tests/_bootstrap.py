"""插件仓单测共享引导。

为复用 MoviePilot 后端逻辑的插件单测提供统一的运行前准备。所有函数都必须在
首次 ``import app.*`` 或导入任一插件包之前调用，否则隔离与路径注入不生效。

职责：
1. 把 ``CONFIG_DIR`` 指向进程私有临时目录，隔离主程序真实数据库与配置；
2. 定位 MoviePilot 后端并加入 ``sys.path``，使 ``import app.*`` 可用；
3. 按 v1 / v2 分别加入插件源码目录到 ``sys.path``。

关键约束：v1（``plugins/``）与 v2（``plugins.v2/``）存在同名插件包，
同一解释器进程无法同时加载两代同名包，必须在各自独立的 pytest 会话中运行，
因此 v1 / v2 的引导函数分开提供、互斥使用。
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ``tests/`` 的父级即插件仓根；其同级 ``MoviePilot`` 为后端默认位置（工作区多仓同级布局）
_TESTS_DIR = Path(__file__).resolve().parent
_PLUGINS_REPO = _TESTS_DIR.parent
_WORKSPACE_ROOT = _PLUGINS_REPO.parent

# 记录本进程隔离出的临时 CONFIG_DIR，兼作幂等标记
_isolated_config_dir: Optional[str] = None


def isolate_config_dir() -> str:
    """把 ``CONFIG_DIR`` 指向进程私有临时目录，隔离主程序真实库与配置。

    ``import app.chain.*`` 会按 ``settings.CONFIG_PATH`` 直接连 ``user.db``；在
    本地非容器布局下默认落到 ``MoviePilot/config/user.db``（线上真实库），因此必须
    在首个 ``import app.*`` 之前改写。幂等：重复调用返回同一目录。

    若调用方已显式设置 ``CONFIG_DIR``（如 CI 指定的隔离目录），则尊重之、不覆盖。

    :return: 实际生效的 CONFIG_DIR 绝对路径
    """
    global _isolated_config_dir
    if _isolated_config_dir is not None:
        return _isolated_config_dir
    existing = os.environ.get("CONFIG_DIR")
    if existing:
        _isolated_config_dir = existing
        return existing
    tmp = tempfile.mkdtemp(prefix="mp-plugin-test-config-")
    os.environ["CONFIG_DIR"] = tmp
    _isolated_config_dir = tmp
    # 进程退出时清理临时库与目录，避免 /tmp 堆积
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def _resolve_backend_path() -> Path:
    """定位 MoviePilot 后端根目录。

    优先取环境变量 ``MOVIEPILOT_BACKEND_PATH``（便于 CI 或非同级布局覆盖）；
    否则按工作区同级布局推导 ``<workspace>/MoviePilot``。校验 ``app/`` 存在，
    避免把错误路径塞进 ``sys.path`` 后产生误导性的 ``ImportError``。
    """
    candidates = []
    env = os.environ.get("MOVIEPILOT_BACKEND_PATH")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(_WORKSPACE_ROOT / "MoviePilot")
    for path in candidates:
        if (path / "app").is_dir():
            return path
    raise RuntimeError(
        "未找到 MoviePilot 后端（app/ 不存在）。请将后端置于插件仓同级目录，"
        f"或设置环境变量 MOVIEPILOT_BACKEND_PATH。已尝试: {[str(c) for c in candidates]}"
    )


def _prepend_sys_path(path: Path) -> None:
    """把目录前置到 ``sys.path``（去重），使其内的顶层包可被导入。"""
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def prepare_backend() -> None:
    """隔离配置目录、加入后端到 ``sys.path`` 并建表（不加载任何插件源码）。

    仅需 ``import app.*`` 而不触碰具体插件包的用例可直接调用本函数。
    """
    isolate_config_dir()
    _prepend_sys_path(_resolve_backend_path())
    # 隔离出的临时库为空，插件读取 systemconfig 等表会报 no such table；与主程序 conftest 一致建表。
    # init_db 仅 import models + create_all，无 alembic/网络、幂等、毫秒级。
    from app.db.init import init_db
    init_db()


def prepare_v2_backend() -> None:
    """v2 插件单测引导：后端 + ``plugins.v2/`` 源码目录。

    调用后可 ``import app.*`` 与 ``import <v2 插件包名>``。与 v1 引导互斥，
    勿在同一进程内混用。
    """
    prepare_backend()
    _prepend_sys_path(_PLUGINS_REPO / "plugins.v2")


def prepare_v1_backend() -> None:
    """v1 插件单测引导：后端 + ``plugins/`` 源码目录。

    与 :func:`prepare_v2_backend` 互斥：v1/v2 存在同名插件包，同一进程同时加载会
    相互覆盖，请在独立 pytest 会话中分别运行 ``tests/v1`` 与 ``tests/v2``。
    """
    prepare_backend()
    _prepend_sys_path(_PLUGINS_REPO / "plugins")
