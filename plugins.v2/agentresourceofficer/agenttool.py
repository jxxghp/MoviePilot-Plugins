from typing import Optional, Type

from pydantic import BaseModel

from app.agent.tools.base import MoviePilotTool
from app.core.plugin import PluginManager

from .schemas import (
    AssistantCapabilitiesToolInput,
    AssistantExecuteActionToolInput,
    AssistantExecuteActionsToolInput,
    AssistantExecutePlanToolInput,
    AssistantHistoryToolInput,
    AssistantHelpToolInput,
    AssistantMaintainToolInput,
    AssistantPickToolInput,
    AssistantPreferencesToolInput,
    AssistantPlansClearToolInput,
    AssistantPlansToolInput,
    AssistantPulseToolInput,
    AssistantReadinessToolInput,
    AssistantRecoverToolInput,
    AssistantRequestTemplatesToolInput,
    AssistantRouteToolInput,
    AssistantSessionClearToolInput,
    AssistantSessionsClearToolInput,
    AssistantSessionsToolInput,
    AssistantSessionStateToolInput,
    AssistantSelfcheckToolInput,
    AssistantStartupToolInput,
    AssistantToolboxToolInput,
    AssistantWorkflowToolInput,
    FeishuChannelHealthToolInput,
    HDHiveSearchSessionToolInput,
    HDHiveSessionPickToolInput,
    P115CancelPendingToolInput,
    P115PendingToolInput,
    P115QRCodeCheckToolInput,
    P115QRCodeStartToolInput,
    P115ResumePendingToolInput,
    P115StatusToolInput,
    ShareRouteToolInput,
)


def _get_plugin():
    return PluginManager().running_plugins.get("AgentResourceOfficer")


class HDHiveSearchSessionTool(MoviePilotTool):
    name: str = "agent_resource_officer_hdhive_search"
    description: str = "Search HDHive by title, return candidate titles and a reusable session_id for the next selection step."
    args_schema: Type[BaseModel] = HDHiveSearchSessionToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        keyword = kwargs.get("keyword", "")
        return f"正在通过 Agent影视助手搜索影巢候选：{keyword}"

    async def run(self, keyword: str, media_type: str = "auto", year: str = None, path: str = None, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_hdhive_search_session(
            keyword=keyword,
            media_type=media_type,
            year=year,
            target_path=path,
        )


class HDHiveSessionPickTool(MoviePilotTool):
    name: str = "agent_resource_officer_hdhive_pick"
    description: str = "Continue a previous HDHive session by selecting either a candidate title or a resource item."
    args_schema: Type[BaseModel] = HDHiveSessionPickToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        session_id = kwargs.get("session_id", "")
        choice = kwargs.get("choice", "")
        return f"正在继续 Agent影视助手 会话：{session_id}，选择 {choice}"

    async def run(self, session_id: str, choice: int = 0, path: str = None, action: str = None, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_hdhive_pick_session(
            session_id=session_id,
            index=choice,
            target_path=path,
            action=action,
        )


class ShareRouteTool(MoviePilotTool):
    name: str = "agent_resource_officer_route_share"
    description: str = "Route a 115 or Quark share link into the configured transfer pipeline and save it into the target path."
    args_schema: Type[BaseModel] = ShareRouteToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 路由分享链接"

    async def run(self, url: str, path: str = None, access_code: str = None, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_route_share(
            share_url=url,
            access_code=access_code,
            target_path=path,
        )


class AssistantRouteTool(MoviePilotTool):
    name: str = "agent_resource_officer_smart_entry"
    description: str = "Use the unified Agent影视助手 smart entry for HDHive search, PanSou search, 115 login, or direct 115/Quark share links."
    args_schema: Type[BaseModel] = AssistantRouteToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        text = kwargs.get("text") or kwargs.get("keyword") or kwargs.get("url") or kwargs.get("action") or ""
        return f"正在通过 Agent影视助手 统一入口处理：{text}"

    async def run(
        self,
        text: str = None,
        session: str = "default",
        session_id: str = None,
        path: str = None,
        mode: str = None,
        keyword: str = None,
        url: str = None,
        access_code: str = None,
        media_type: str = None,
        year: str = None,
        client_type: str = None,
        action: str = None,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_route(
            text=text,
            session=session,
            session_id=session_id,
            target_path=path,
            mode=mode,
            keyword=keyword,
            share_url=url,
            access_code=access_code,
            media_type=media_type,
            year=year,
            client_type=client_type,
            action=action,
            compact=compact,
        )


class AssistantPickTool(MoviePilotTool):
    name: str = "agent_resource_officer_smart_pick"
    description: str = "Continue the unified Agent影视助手 smart-entry session by choosing an item, requesting details, or moving to the next page."
    args_schema: Type[BaseModel] = AssistantPickToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        session = kwargs.get("session", "default")
        choice = kwargs.get("choice", 0)
        action = kwargs.get("action", "")
        tail = f"动作 {action}" if action else f"选择 {choice}"
        return f"正在继续 Agent影视助手 统一会话：{session}，{tail}"

    async def run(
        self,
        session: str = "default",
        session_id: str = None,
        choice: int = 0,
        action: str = None,
        mode: str = None,
        path: str = None,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_pick(
            session=session,
            session_id=session_id,
            index=choice,
            action=action,
            mode=mode,
            target_path=path,
            compact=compact,
        )


class AssistantHelpTool(MoviePilotTool):
    name: str = "agent_resource_officer_help"
    description: str = "Show the recommended Agent影视助手 workflow for MoviePilot Agent, including smart-entry examples, pick examples, and 115 login guidance."
    args_schema: Type[BaseModel] = AssistantHelpToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在查看 Agent影视助手 使用帮助"

    async def run(self, session: str = "default", session_id: str = None, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_help(session=session, session_id=session_id)


class AssistantCapabilitiesTool(MoviePilotTool):
    name: str = "agent_resource_officer_capabilities"
    description: str = "Show the current Agent影视助手 execution capabilities, supported structured smart-entry fields, defaults, and recommended call patterns for external agents."
    args_schema: Type[BaseModel] = AssistantCapabilitiesToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在查看 Agent影视助手 能力说明"

    async def run(self, compact: bool = True, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_capabilities(compact=compact)


class AssistantReadinessTool(MoviePilotTool):
    name: str = "agent_resource_officer_readiness"
    description: str = "Check whether Agent影视助手 is ready for external agents, including version, services, suggested entrypoints, and startup warnings."
    args_schema: Type[BaseModel] = AssistantReadinessToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在检查 Agent影视助手 启动就绪状态"

    async def run(self, compact: bool = True, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_readiness(compact=compact)


class FeishuChannelHealthTool(MoviePilotTool):
    name: str = "agent_resource_officer_feishu_health"
    description: str = "Check Agent影视助手 built-in Feishu Channel status, including whether it is enabled, running, and configured."
    args_schema: Type[BaseModel] = FeishuChannelHealthToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在检查 Agent影视助手 内置飞书入口状态"

    async def run(self, compact: bool = True, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_feishu_health(compact=compact)


class AssistantPulseTool(MoviePilotTool):
    name: str = "agent_resource_officer_pulse"
    description: str = "Return a compact Agent影视助手 startup pulse: version, service readiness, warnings, and best recovery hint for external agents."
    args_schema: Type[BaseModel] = AssistantPulseToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在检查 Agent影视助手 轻量启动状态"

    async def run(self, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_pulse()


class AssistantStartupTool(MoviePilotTool):
    name: str = "agent_resource_officer_startup"
    description: str = "Return one compact startup bundle for external agents: pulse, self-check result, key tools, endpoints, defaults, and recovery hint."
    args_schema: Type[BaseModel] = AssistantStartupToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在读取 Agent影视助手 启动聚合信息"

    async def run(self, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_startup()


class AssistantMaintainTool(MoviePilotTool):
    name: str = "agent_resource_officer_maintain"
    description: str = "Inspect or execute low-risk Agent影视助手 maintenance: clear stale assistant sessions and executed saved plans."
    args_schema: Type[BaseModel] = AssistantMaintainToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在检查 Agent影视助手 维护建议"

    async def run(self, execute: bool = False, limit: int = 100, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_maintain(execute=execute, limit=limit)


class AssistantToolboxTool(MoviePilotTool):
    name: str = "agent_resource_officer_toolbox"
    description: str = "Return a compact Agent影视助手 toolbox manifest: recommended tools, endpoints, workflows, actions, defaults, and command examples."
    args_schema: Type[BaseModel] = AssistantToolboxToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在读取 Agent影视助手 轻量工具清单"

    async def run(self, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_toolbox()


class AssistantRequestTemplatesTool(MoviePilotTool):
    name: str = "agent_resource_officer_request_templates"
    description: str = "Return compact HTTP request templates for external agents to call Agent影视助手 assistant endpoints without guessing request bodies."
    args_schema: Type[BaseModel] = AssistantRequestTemplatesToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在读取 Agent影视助手 请求模板"

    async def run(self, limit: int = 100, names: str = None, recipe: str = None, include_templates: bool = True, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_request_templates(
            limit=limit,
            names=names,
            recipe=recipe,
            include_templates=include_templates,
        )


class AssistantSelfcheckTool(MoviePilotTool):
    name: str = "agent_resource_officer_selfcheck"
    description: str = "Run a compact Agent影视助手 protocol self-check for compact templates, boolean parsing, and basic assistant protocol health."
    args_schema: Type[BaseModel] = AssistantSelfcheckToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在执行 Agent影视助手 协议自检"

    async def run(self, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_selfcheck()


class AssistantHistoryTool(MoviePilotTool):
    name: str = "agent_resource_officer_history"
    description: str = "Show recent Agent影视助手 assistant executions so external agents can debug progress, retries, and the last completed action."
    args_schema: Type[BaseModel] = AssistantHistoryToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在查看 Agent影视助手 最近执行历史"

    async def run(
        self,
        session: str = None,
        session_id: str = None,
        compact: bool = True,
        limit: int = 20,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_history(
            session=session,
            session_id=session_id,
            compact=compact,
            limit=limit,
        )


class AssistantExecuteActionTool(MoviePilotTool):
    name: str = "agent_resource_officer_execute_action"
    description: str = "Execute a named Agent影视助手 action template directly, so external agents can reuse action_templates without manually mapping each next step."
    args_schema: Type[BaseModel] = AssistantExecuteActionToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return f"正在执行 Agent影视助手 动作模板：{kwargs.get('name', '')}"

    async def run(
        self,
        name: str,
        session: str = "default",
        session_id: str = None,
        choice: int = None,
        path: str = None,
        keyword: str = None,
        media_type: str = None,
        year: str = None,
        url: str = None,
        access_code: str = None,
        client_type: str = None,
        source: str = None,
        kind: str = None,
        has_pending_p115: bool = None,
        stale_only: bool = False,
        all_sessions: bool = False,
        limit: int = 100,
        plan_id: str = None,
        prefer_unexecuted: bool = True,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_execute_action(
            name=name,
            session=session,
            session_id=session_id,
            choice=choice,
            target_path=path,
            keyword=keyword,
            media_type=media_type,
            year=year,
            share_url=url,
            access_code=access_code,
            client_type=client_type,
            source=source,
            kind=kind,
            has_pending_p115=has_pending_p115,
            stale_only=stale_only,
            all_sessions=all_sessions,
            limit=limit,
            plan_id=plan_id,
            prefer_unexecuted=prefer_unexecuted,
            compact=compact,
        )


class AssistantExecuteActionsTool(MoviePilotTool):
    name: str = "agent_resource_officer_execute_actions"
    description: str = "Execute a sequence of Agent影视助手 action templates in one request, so external agents can reduce round trips and reuse action_templates directly."
    args_schema: Type[BaseModel] = AssistantExecuteActionsToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        actions = kwargs.get("actions") or []
        return f"正在批量执行 Agent影视助手 动作模板：{len(actions)} 步"

    async def run(
        self,
        actions: list,
        session: str = "default",
        session_id: str = None,
        stop_on_error: bool = True,
        include_raw_results: bool = False,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_execute_actions(
            actions=actions,
            session=session,
            session_id=session_id,
            stop_on_error=stop_on_error,
            include_raw_results=include_raw_results,
            compact=compact,
        )


class AssistantWorkflowTool(MoviePilotTool):
    name: str = "agent_resource_officer_run_workflow"
    description: str = "Run a preset Agent影视助手 workflow such as pansou_transfer, hdhive_unlock, mp_search_best, mp_search_detail, mp_search_download, mp_subscribe, mp_recommend, share_transfer, or p115_status with compact inputs."
    args_schema: Type[BaseModel] = AssistantWorkflowToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return f"正在运行 Agent影视助手 预设工作流：{kwargs.get('name', '')}"

    async def run(
        self,
        name: str,
        session: str = "default",
        session_id: str = None,
        keyword: str = None,
        choice: int = None,
        candidate_choice: int = None,
        resource_choice: int = None,
        path: str = None,
        url: str = None,
        access_code: str = None,
        media_type: str = None,
        year: str = None,
        client_type: str = None,
        source: str = None,
        limit: int = 20,
        dry_run: bool = False,
        stop_on_error: bool = True,
        include_raw_results: bool = False,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_workflow(
            name=name,
            session=session,
            session_id=session_id,
            keyword=keyword,
            choice=choice,
            candidate_choice=candidate_choice,
            resource_choice=resource_choice,
            target_path=path,
            share_url=url,
            access_code=access_code,
            media_type=media_type,
            year=year,
            client_type=client_type,
            source=source,
            limit=limit,
            dry_run=dry_run,
            stop_on_error=stop_on_error,
            include_raw_results=include_raw_results,
            compact=compact,
        )


class AssistantPreferencesTool(MoviePilotTool):
    name: str = "agent_resource_officer_preferences"
    description: str = "Read, save, or reset Agent影视助手 source preferences for scoring cloud-drive and PT results before automated actions."
    args_schema: Type[BaseModel] = AssistantPreferencesToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        if kwargs.get("reset"):
            return "正在重置 Agent影视助手 智能体偏好画像"
        if kwargs.get("preferences"):
            return "正在保存 Agent影视助手 智能体偏好画像"
        return "正在读取 Agent影视助手 智能体偏好画像"

    async def run(
        self,
        session: str = "default",
        session_id: str = None,
        user_key: str = None,
        preferences: dict = None,
        reset: bool = False,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_preferences(
            session=session,
            session_id=session_id,
            user_key=user_key,
            preferences=preferences,
            reset=reset,
            compact=compact,
        )


class AssistantExecutePlanTool(MoviePilotTool):
    name: str = "agent_resource_officer_execute_plan"
    description: str = "Execute a saved Agent影视助手 dry-run workflow plan by plan_id, or recover the latest plan by session/session_id."
    args_schema: Type[BaseModel] = AssistantExecutePlanToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return f"正在执行 Agent影视助手 已保存计划：{kwargs.get('plan_id', '') or kwargs.get('session_id', '') or kwargs.get('session', '')}"

    async def run(
        self,
        plan_id: str = None,
        session: str = None,
        session_id: str = None,
        prefer_unexecuted: bool = True,
        stop_on_error: bool = True,
        include_raw_results: bool = False,
        compact: bool = True,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_execute_plan(
            plan_id=plan_id,
            session=session,
            session_id=session_id,
            prefer_unexecuted=prefer_unexecuted,
            stop_on_error=stop_on_error,
            include_raw_results=include_raw_results,
            compact=compact,
        )


class AssistantPlansTool(MoviePilotTool):
    name: str = "agent_resource_officer_plans"
    description: str = "List saved Agent影视助手 dry-run workflow plans so agents can recover and execute the right plan_id."
    args_schema: Type[BaseModel] = AssistantPlansToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在查看 Agent影视助手 已保存计划"

    async def run(
        self,
        session: str = None,
        session_id: str = None,
        executed: bool = None,
        include_actions: bool = False,
        compact: bool = True,
        limit: int = 20,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_plans(
            session=session,
            session_id=session_id,
            executed=executed,
            include_actions=include_actions,
            compact=compact,
            limit=limit,
        )


class AssistantPlansClearTool(MoviePilotTool):
    name: str = "agent_resource_officer_plans_clear"
    description: str = "Clear saved Agent影视助手 workflow plans by plan_id, session, executed state, or all_plans."
    args_schema: Type[BaseModel] = AssistantPlansClearToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在清理 Agent影视助手 已保存计划"

    async def run(
        self,
        plan_id: str = None,
        session: str = None,
        session_id: str = None,
        executed: bool = None,
        all_plans: bool = False,
        limit: int = 100,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_plans_clear(
            plan_id=plan_id,
            session=session,
            session_id=session_id,
            executed=executed,
            all_plans=all_plans,
            limit=limit,
        )


class AssistantRecoverTool(MoviePilotTool):
    name: str = "agent_resource_officer_recover"
    description: str = "Inspect the best Agent影视助手 recovery action, or execute it directly, so external agents can resume work through one stable entrypoint."
    args_schema: Type[BaseModel] = AssistantRecoverToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        target = kwargs.get("session_id") or kwargs.get("session") or "全局"
        action = "并直接恢复" if kwargs.get("execute") else "恢复建议"
        return f"正在查看 Agent影视助手 {target} 的{action}"

    async def run(
        self,
        session: str = None,
        session_id: str = None,
        execute: bool = False,
        prefer_unexecuted: bool = True,
        stop_on_error: bool = True,
        include_raw_results: bool = False,
        compact: bool = True,
        limit: int = 20,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_recover(
            session=session,
            session_id=session_id,
            execute=execute,
            prefer_unexecuted=prefer_unexecuted,
            stop_on_error=stop_on_error,
            include_raw_results=include_raw_results,
            compact=compact,
            limit=limit,
        )


class AssistantSessionStateTool(MoviePilotTool):
    name: str = "agent_resource_officer_session_state"
    description: str = "Inspect the current Agent影视助手 assistant session, including stage, current page, selected candidate, and pending 115 task."
    args_schema: Type[BaseModel] = AssistantSessionStateToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        session = kwargs.get("session", "default")
        return f"正在查看 Agent影视助手 会话状态：{session}"

    async def run(self, session: str = "default", session_id: str = None, compact: bool = True, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_session_state(session=session, session_id=session_id, compact=compact)


class AssistantSessionClearTool(MoviePilotTool):
    name: str = "agent_resource_officer_session_clear"
    description: str = "Clear the current Agent影视助手 assistant session cache."
    args_schema: Type[BaseModel] = AssistantSessionClearToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        session = kwargs.get("session", "default")
        return f"正在清理 Agent影视助手 会话：{session}"

    async def run(self, session: str = "default", session_id: str = None, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_session_clear(session=session, session_id=session_id)


class AssistantSessionsTool(MoviePilotTool):
    name: str = "agent_resource_officer_sessions"
    description: str = "List active Agent影视助手 assistant sessions so external agents can recover, inspect, and resume the right workflow."
    args_schema: Type[BaseModel] = AssistantSessionsToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在查看 Agent影视助手 活跃会话列表"

    async def run(self, kind: str = None, has_pending_p115: bool = None, compact: bool = True, limit: int = 20, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_sessions(
            kind=kind,
            has_pending_p115=has_pending_p115,
            compact=compact,
            limit=limit,
        )


class AssistantSessionsClearTool(MoviePilotTool):
    name: str = "agent_resource_officer_sessions_clear"
    description: str = "Clear one or more Agent影视助手 assistant sessions by session_id, session name, filters, or full reset."
    args_schema: Type[BaseModel] = AssistantSessionsClearToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在清理 Agent影视助手 活跃会话"

    async def run(
        self,
        session: str = None,
        session_id: str = None,
        kind: str = None,
        has_pending_p115: bool = None,
        stale_only: bool = False,
        all_sessions: bool = False,
        limit: int = 100,
        **kwargs,
    ) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_assistant_sessions_clear(
            session=session,
            session_id=session_id,
            kind=kind,
            has_pending_p115=has_pending_p115,
            stale_only=stale_only,
            all_sessions=all_sessions,
            limit=limit,
        )


class P115QRCodeStartTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_qrcode_start"
    description: str = "Generate a 115 login QR code using the p115client-compatible client session flow."
    args_schema: Type[BaseModel] = P115QRCodeStartToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        client_type = kwargs.get("client_type", "alipaymini")
        return f"正在通过 Agent影视助手 生成 115 扫码二维码：{client_type}"

    async def run(self, client_type: str = "alipaymini", **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_qrcode_start(client_type=client_type)


class P115QRCodeCheckTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_qrcode_check"
    description: str = "Check the status of a previous 115 QR-code login and save the client session when login succeeds."
    args_schema: Type[BaseModel] = P115QRCodeCheckToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 检查 115 扫码状态"

    async def run(self, uid: str, time: str, sign: str, client_type: str = "alipaymini", **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_qrcode_check(
            uid=uid,
            time_value=time,
            sign=sign,
            client_type=client_type,
        )


class P115StatusTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_status"
    description: str = "Show the current 115 transfer readiness, default target path, and current session source."
    args_schema: Type[BaseModel] = P115StatusToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 查看 115 当前状态"

    async def run(self, **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_status()


class P115PendingTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_pending"
    description: str = "Show the pending 115 transfer task for an assistant session, including target path, retry count, and last error."
    args_schema: Type[BaseModel] = P115PendingToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 查看待继续的 115 任务"

    async def run(self, session: str = "default", **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_pending(session=session)


class P115ResumePendingTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_resume_pending"
    description: str = "Retry the pending 115 transfer task for an assistant session."
    args_schema: Type[BaseModel] = P115ResumePendingToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 继续待处理的 115 任务"

    async def run(self, session: str = "default", **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_resume(session=session)


class P115CancelPendingTool(MoviePilotTool):
    name: str = "agent_resource_officer_p115_cancel_pending"
    description: str = "Cancel and clear the pending 115 transfer task for an assistant session."
    args_schema: Type[BaseModel] = P115CancelPendingToolInput

    def get_tool_message(self, **kwargs) -> Optional[str]:
        return "正在通过 Agent影视助手 取消待处理的 115 任务"

    async def run(self, session: str = "default", **kwargs) -> str:
        plugin = _get_plugin()
        if not plugin:
            return "Agent影视助手 插件未运行"
        return await plugin.tool_p115_cancel(session=session)
