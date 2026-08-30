"""pytest 全局引导：按目标选择插件代际，CI 工具测试不加载后端。

``tests/run.py`` 默认把 CI、V3 专用实现和兼容 V3 的 V2 实现放到独立 pytest 进程中运行；
手工执行历史代测试时仍按目标路径注入对应插件目录，避免同一进程同时加载不同代的同名包。
``tests/ci`` 只校验仓库工具和 workflow，不初始化 MoviePilot 运行时。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 相对导入本仓薄壳，先定位同级 MoviePilot 后端并加入 ``sys.path``，再复用主程序共享引导。
from ._bootstrap import (
    block_real_network,  # noqa: F401  导入即注册主程序共享 autouse 网络守卫
    prepare_v1_backend,
    prepare_v2_backend,
    prepare_v3_backend,
)


def _configure_test_plugin_runtime() -> None:
    """为绕过完整启动流程的插件测试装配最小插件 Runtime。"""
    from app.runtime.config import settings
    from app.runtime.extensions.plugin import manager as plugin_manager_module
    from app.runtime.extensions.plugin.manager import PluginManager
    from app.runtime.extensions.plugin.runtime import (
        PluginRuntimeEnvironment,
        build_plugin_runtime,
    )
    from app.runtime.extensions.plugin.storage import get_plugin_storage
    from app.runtime.extensions.plugin.system import get_plugin_system

    def build_test_plugin_runtime(host):
        """构造使用隔离配置的插件运行时，避免隐式依赖生产组合根。"""
        return build_plugin_runtime(
            host,
            PluginRuntimeEnvironment(
                plugins_root=settings.ROOT_PATH / "app" / "plugins",
                storage=get_plugin_storage,
                system=get_plugin_system,
                catalog_factory=lambda _mapper: None,
                import_preparer=lambda **_kwargs: None,
                import_scanner=lambda **_kwargs: None,
                auth_level=lambda: 0,
                remote_entry=host.get_plugin_remote_entry,
                development=lambda: False,
                logger=plugin_manager_module.logger,
            ),
            tool_build_max_attempts=PluginManager.AGENT_TOOLS_BUILD_MAX_ATTEMPTS,
        )

    plugin_manager_module.configure_plugin_runtime_factory(build_test_plugin_runtime)


def _selected_generation(config) -> str:
    """根据 pytest 本次目标路径判断插件代际，禁止同一进程混跑不同代。"""
    generations = set()
    for arg in config.args:
        file_part = arg.split("::", 1)[0]
        path = Path(file_part).resolve().as_posix().replace("\\", "/")
        if "tests/v3" in path:
            generations.add("v3")
        elif "tests/v2" in path:
            generations.add("v2")
        elif "tests/v1" in path:
            generations.add("v1")
        elif "tests/ci" in path:
            generations.add("ci")
    if len(generations) == 1:
        return next(iter(generations))
    raise RuntimeError("插件仓单测必须按 tests/run.py 分代独立会话运行，避免同名插件包冲突")


def pytest_configure(config) -> None:
    """收集用例前隔离 CONFIG_DIR、建表并注入对应代际插件目录。"""
    generation = _selected_generation(config)
    if generation == "ci":
        return
    if generation == "v3":
        prepare_v3_backend()
    elif generation == "v2":
        prepare_v2_backend()
    else:
        prepare_v1_backend()
    _configure_test_plugin_runtime()


def _report_session_cleanup_error(session, name: str, err: Exception) -> None:
    """记录收尾错误；原测试绿色时将会话标记为失败。"""
    sys.stderr.write(f"\npytest session cleanup failed: {name}: {err!r}\n")
    if session.exitstatus == 0:
        session.exitstatus = 1


def pytest_sessionfinish(session, exitstatus) -> None:
    """释放测试过程中创建的消息队列与日志后台线程"""
    if _selected_generation(session.config) == "ci":
        return

    try:
        from app.helper.message import stop_message

        stop_message()
    except Exception as err:
        _report_session_cleanup_error(session, "message service", err)

    try:
        from app.log import LoggerManager

        LoggerManager.shutdown()
    except Exception as err:
        _report_session_cleanup_error(session, "logger manager", err)

    try:
        from app.runtime.extensions.plugin.manager import reset_plugin_runtime_factory

        reset_plugin_runtime_factory()
    except Exception as err:
        _report_session_cleanup_error(session, "plugin runtime factory", err)
