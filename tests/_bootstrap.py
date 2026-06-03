"""插件仓单测引导薄壳：定位同级 MoviePilot 后端并入 ``sys.path``，引导逻辑委托主程序 ``app.testing.bootstrap``。

chicken-egg：导入主程序共享引导之前，必须先由本仓定位后端、加入 ``sys.path``——这一步不可消除，
故每个插件仓只保留这层极薄 shim；隔离 CONFIG_DIR / 建表 / 插件目录注入 / v1·v2 marker 等
实际逻辑均在主程序 ``app/testing`` 维护一处，所有插件仓行为与修复保持一致。

所有引导函数都必须在首次 ``import app.*`` 或导入任一插件包之前调用，否则隔离与路径注入不生效。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ``tests/`` 的父级即插件仓根；其同级 ``MoviePilot`` 为后端默认位置（工作区多仓同级布局）
_TESTS_DIR = Path(__file__).resolve().parent
_PLUGINS_REPO = _TESTS_DIR.parent
_WORKSPACE_ROOT = _PLUGINS_REPO.parent


def _resolve_backend_path() -> Path:
    """定位 MoviePilot 后端根目录。

    优先取环境变量 ``MOVIEPILOT_BACKEND_PATH``（便于 CI 或非同级布局覆盖），否则按工作区
    同级布局推导 ``<workspace>/MoviePilot``。校验 ``app/`` 存在，避免把错误路径塞进
    ``sys.path`` 后产生误导性的 ``ImportError``。
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


# 导入副作用：定位后端并前置到 ``sys.path``，使后续 ``import app.*`` / ``app.testing.bootstrap`` 可用
_BACKEND_PATH = _resolve_backend_path()
if str(_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PATH))

from app.testing import bootstrap as _bootstrap  # noqa: E402  后端就绪后引导逻辑全部复用主程序实现


def isolate_config_dir() -> str:
    """隔离 ``CONFIG_DIR`` 到进程私有临时目录（委托主程序共享实现）。"""
    return _bootstrap.isolate_config_dir()


def prepare_backend() -> None:
    """隔离 ``CONFIG_DIR`` 并建表，仅需 ``import app.*`` 的用例可直接调用（委托主程序共享实现）。"""
    _bootstrap.prepare_backend()


def prepare_v2_backend() -> None:
    """v2 插件单测引导：后端 + 本仓 ``plugins.v2/``（委托主程序共享实现）。"""
    _bootstrap.prepare_v2_backend(_PLUGINS_REPO)


def prepare_v1_backend() -> None:
    """v1 插件单测引导：后端 + 本仓 ``plugins/``（委托主程序共享实现，与 v2 互斥）。"""
    _bootstrap.prepare_v1_backend(_PLUGINS_REPO)
