"""智能助手工具：只读查询最近一次影视库完整性报告，不触发扫描、不修改规则。"""

from __future__ import annotations

import re
from typing import Any, Optional, Type

from pydantic import BaseModel, Field

TOOL_NAME = "query_library_integrity"


class QueryReportInput(BaseModel):
    """查询报告工具的输入参数。"""

    explanation: str = Field(..., description="Clear explanation of why this tool is being used")
    issue_type: Optional[str] = Field(
        default=None,
        description="Filter by issue type: missing, version, duplicate, conflict, unchecked or suggestion. Omit for all.",
    )
    keyword: Optional[str] = Field(default=None, description="Filter by title keyword, e.g. a TV series name")
    limit: int = Field(default=20, description="Maximum number of issues to return (1-100)")


def tool_name(plugin_id: str) -> str:
    """返回工具名称；插件分身追加实例 ID，避免与源插件的工具重名。"""
    if plugin_id == "LibraryIntegrity":
        return TOOL_NAME
    return f"{TOOL_NAME}_{re.sub(r'[^a-z0-9_]', '_', plugin_id.lower())}"


def build_agent_tools(plugin_id: str) -> list[Type[Any]]:
    """为指定插件实例构造查询工具类；工具执行时按实例 ID 找到运行中的插件。"""
    from app.agent.tools.base import MoviePilotTool

    class LibraryIntegrityQueryTool(MoviePilotTool):
        """查询影视库完整性报告。"""

        name: str = tool_name(plugin_id)
        description: str = (
            "Query the latest media library integrity report produced by the LibraryIntegrity plugin "
            "(Emby / local directories). It lists missing aired episodes, inconsistent versions within a season "
            "(resolution, codec, HDR, release group), duplicate files, episode numbering conflicts, series that "
            "could not be checked, and AI suggestions awaiting user adoption. Read-only: it never starts a scan "
            "or changes any rule. Use it when the user asks which shows are missing episodes, which seasons have "
            "mixed versions, or about the integrity of a specific show."
        )
        args_schema: Type[BaseModel] = QueryReportInput

        def get_tool_message(self, **kwargs: Any) -> Optional[str]:
            """生成工具执行提示。"""
            keyword = kwargs.get("keyword")
            return f"正在查询影视库完整性报告：{keyword}" if keyword else "正在查询影视库完整性报告"

        async def run(
            self,
            issue_type: Optional[str] = None,
            keyword: Optional[str] = None,
            limit: int = 20,
            **kwargs: Any,
        ) -> str:
            """按条件返回报告中的问题。"""
            from app.sdk.plugin import PluginManager

            plugin = PluginManager().running_plugins.get(plugin_id)
            if plugin is None or not hasattr(plugin, "async_query_text"):
                return "影视库完整性检查插件未运行"
            return await plugin.async_query_text(issue_type=issue_type, keyword=keyword, limit=limit)

    return [LibraryIntegrityQueryTool]
