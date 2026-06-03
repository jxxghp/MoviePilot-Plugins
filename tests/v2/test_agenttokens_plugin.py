"""AgentTokens 插件单测（pytest 原生）。

覆盖侧栏入口受 show_sidebar_nav 配置控制的逻辑。依赖 MoviePilot 后端（app.*）与
插件包：通过共享引导隔离 CONFIG_DIR 并把后端、plugins.v2 注入 sys.path，再以
顶层包名导入插件。
"""
import sys
from pathlib import Path
from unittest.mock import patch

# 将仓库根置于 sys.path，使共享引导可被导入（兼容 pytest 与直接 python 运行）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests._bootstrap import prepare_v2_backend  # noqa: E402

# 隔离 CONFIG_DIR 并注入后端 + plugins.v2，必须在 import app.* / 插件包之前完成
prepare_v2_backend()

from agenttokens import AgentTokens  # noqa: E402


def test_sidebar_nav_respects_config():
    """侧栏入口应受 show_sidebar_nav 配置控制：关闭则不注册，开启且插件启用则注册。

    init_plugin 内部会持久化配置，这里 patch 掉 update_config，仅隔离验证侧栏逻辑。
    """
    plugin = AgentTokens()
    with patch.object(plugin, "update_config"):
        plugin.init_plugin({"enabled": True, "show_sidebar_nav": False, "providers": []})
        assert plugin.get_sidebar_nav() == []

        plugin.init_plugin({"enabled": True, "show_sidebar_nav": True, "providers": []})
        nav = plugin.get_sidebar_nav()

    assert nav[0]["title"] == "Agent Tokens 管理"
