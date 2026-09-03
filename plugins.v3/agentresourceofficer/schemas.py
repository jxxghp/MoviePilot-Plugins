from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HDHiveSearchSessionToolInput(BaseModel):
    keyword: str = Field(..., description="要搜索的影片或剧集名称")
    media_type: str = Field(default="auto", description="媒体类型，auto / movie / tv；不确定时用 auto")
    year: Optional[str] = Field(default=None, description="可选年份，用于缩小候选范围")
    path: Optional[str] = Field(default=None, description="可选目标目录，不填则使用默认目录")


class HDHiveSessionPickToolInput(BaseModel):
    session_id: str = Field(..., description="上一步搜索返回的会话 ID")
    choice: int = Field(default=0, description="当前阶段要选择的编号，从 1 开始；详情或翻页时可为 0")
    path: Optional[str] = Field(default=None, description="可选目标目录，不填则使用会话中的目录")
    action: Optional[str] = Field(default=None, description="可选动作：detail/details/review/详情/审查 或 next/n/下一页")


class ShareRouteToolInput(BaseModel):
    url: str = Field(..., description="115 或夸克分享链接")
    path: Optional[str] = Field(default=None, description="目标目录")
    access_code: Optional[str] = Field(default=None, description="提取码，可选")


class AssistantRouteToolInput(BaseModel):
    text: Optional[str] = Field(default=None, description="统一智能入口文本，例如 盘搜搜索 片名、影巢搜索 片名、115登录 或直接粘贴 115/夸克分享链接")
    session: Optional[str] = Field(default="default", description="会话标识，用于关联后续选择、115 待任务与扫码续跑")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，适合外部智能体按 sessions 列表中的精确会话继续使用")
    path: Optional[str] = Field(default=None, description="可选目标目录，不填则按当前模式使用默认目录")
    mode: Optional[str] = Field(default=None, description="结构化模式：mp / pansou / hdhive")
    keyword: Optional[str] = Field(default=None, description="结构化搜索关键词")
    url: Optional[str] = Field(default=None, description="结构化分享链接，支持 115 / 夸克")
    access_code: Optional[str] = Field(default=None, description="结构化提取码")
    media_type: Optional[str] = Field(default=None, description="结构化媒体类型：auto / movie / tv")
    year: Optional[str] = Field(default=None, description="结构化年份")
    client_type: Optional[str] = Field(default=None, description="115 扫码客户端类型")
    action: Optional[str] = Field(default=None, description="结构化动作：p115_qrcode_start / p115_qrcode_check / p115_status / p115_help / p115_pending / p115_resume / p115_cancel / assistant_help")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantPickToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识，需与上一步统一智能入口保持一致")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    choice: int = Field(default=0, description="选择的编号，从 1 开始；详情或翻页时可为 0")
    action: Optional[str] = Field(default=None, description="可选动作：detail/details/review/详情/审查 或 next/n/下一页")
    mode: Optional[str] = Field(default=None, description="推荐列表后续搜索方式：mp / hdhive / pansou")
    path: Optional[str] = Field(default=None, description="可选目标目录，不填则沿用会话目录")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantHelpToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="可选会话标识；如该会话存在待继续的 115 任务，帮助里会附带任务摘要")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")


class AssistantSessionStateToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识；不填则查看 default 会话当前状态")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantSessionClearToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识；不填则清理 default 会话")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")


class AssistantCapabilitiesToolInput(BaseModel):
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantReadinessToolInput(BaseModel):
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class FeishuChannelHealthToolInput(BaseModel):
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantPulseToolInput(BaseModel):
    pass


class AssistantStartupToolInput(BaseModel):
    pass


class AssistantMaintainToolInput(BaseModel):
    execute: Optional[bool] = Field(default=False, description="是否立即执行低风险维护；默认只返回建议")
    limit: Optional[int] = Field(default=100, description="单次最多清理多少条")


class AssistantToolboxToolInput(BaseModel):
    pass


class AssistantRequestTemplatesToolInput(BaseModel):
    limit: Optional[int] = Field(default=100, description="模板中批量类请求默认 limit，范围由插件限制")
    names: Optional[str] = Field(default=None, description="可选模板名，多个用逗号或空格分隔，例如 maintain_execute,workflow_dry_run")
    recipe: Optional[str] = Field(default=None, description="可选推荐流程名或别名，例如 plan / maintain / continue / bootstrap")
    include_templates: Optional[bool] = Field(default=True, description="是否返回完整模板内容；关闭时只返回名称、无效项和执行策略")


class AssistantSelfcheckToolInput(BaseModel):
    pass


class AssistantHistoryToolInput(BaseModel):
    session: Optional[str] = Field(default=None, description="可选会话名；不填则返回全部最近执行记录")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")
    limit: Optional[int] = Field(default=20, description="最多返回多少条执行记录")


class AssistantExecuteActionToolInput(BaseModel):
    name: str = Field(..., description="要执行的动作模板名，例如 pick_pansou_result / candidate_next_page / resume_pending_115")
    session: Optional[str] = Field(default="default", description="可选会话名")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    choice: Optional[int] = Field(default=None, description="需要选择编号时传入")
    path: Optional[str] = Field(default=None, description="可选目标目录")
    keyword: Optional[str] = Field(default=None, description="搜索类动作使用的关键词")
    media_type: Optional[str] = Field(default=None, description="搜索类动作使用的媒体类型")
    year: Optional[str] = Field(default=None, description="搜索类动作使用的年份")
    url: Optional[str] = Field(default=None, description="直链类动作使用的分享链接")
    access_code: Optional[str] = Field(default=None, description="可选提取码")
    client_type: Optional[str] = Field(default=None, description="115 扫码客户端类型")
    source: Optional[str] = Field(default=None, description="MP 推荐来源，例如 tmdb_trending / douban_movie_hot / bangumi_calendar")
    kind: Optional[str] = Field(default=None, description="批量清理会话时的类型过滤")
    has_pending_p115: Optional[bool] = Field(default=None, description="批量清理会话时是否仅清理带待继续 115 的会话")
    stale_only: Optional[bool] = Field(default=False, description="批量清理会话时是否只清理过期会话")
    all_sessions: Optional[bool] = Field(default=False, description="批量清理会话时是否清理全部会话")
    limit: Optional[int] = Field(default=100, description="批量清理会话时的最多处理条数")
    plan_id: Optional[str] = Field(default=None, description="计划动作使用的 plan_id")
    prefer_unexecuted: Optional[bool] = Field(default=True, description="计划动作未指定 plan_id 时是否优先选择未执行计划")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantExecuteActionsToolInput(BaseModel):
    actions: List[Dict[str, Any]] = Field(..., description="动作模板执行数组，每项可直接复用 action_templates 里的 action_body")
    session: Optional[str] = Field(default="default", description="批量动作默认会话名；子动作未显式传 session/session_id 时自动继承")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    stop_on_error: Optional[bool] = Field(default=True, description="遇到失败动作时是否立即停止后续执行")
    include_raw_results: Optional[bool] = Field(default=False, description="是否附带每一步原始返回；默认关闭以减少 token 与负载")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantWorkflowToolInput(BaseModel):
    name: str = Field(..., description="预设工作流名，例如 pansou_search / pansou_transfer / hdhive_candidates / hdhive_unlock / mp_search / mp_search_download / mp_subscribe / mp_recommend / mp_recommend_search / share_transfer / p115_status")
    session: Optional[str] = Field(default="default", description="工作流会话名")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    keyword: Optional[str] = Field(default=None, description="搜索关键词")
    choice: Optional[int] = Field(default=None, description="通用选择编号，盘搜转存默认使用 1")
    candidate_choice: Optional[int] = Field(default=None, description="影巢候选影片编号")
    resource_choice: Optional[int] = Field(default=None, description="影巢资源编号")
    path: Optional[str] = Field(default=None, description="可选目标目录")
    url: Optional[str] = Field(default=None, description="分享链接")
    access_code: Optional[str] = Field(default=None, description="提取码")
    media_type: Optional[str] = Field(default=None, description="媒体类型，auto / movie / tv")
    mode: Optional[str] = Field(default=None, description="推荐后续搜索方式，mp / hdhive / pansou")
    year: Optional[str] = Field(default=None, description="年份")
    client_type: Optional[str] = Field(default=None, description="115 扫码客户端类型")
    source: Optional[str] = Field(default=None, description="MP 推荐来源，例如 tmdb_trending / douban_movie_hot / bangumi_calendar")
    limit: Optional[int] = Field(default=20, description="推荐数量上限")
    dry_run: Optional[bool] = Field(default=False, description="只生成工作流计划，不实际执行")
    stop_on_error: Optional[bool] = Field(default=True, description="遇到失败动作时是否停止")
    include_raw_results: Optional[bool] = Field(default=False, description="是否附带原始执行结果")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantPreferencesToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="偏好画像会话名；建议外部智能体固定传自己的用户会话")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    user_key: Optional[str] = Field(default=None, description="可选用户键；用于跨 session 共享同一套偏好")
    preferences: Optional[Dict[str, Any]] = Field(default=None, description="要保存的偏好画像；不传则只读取")
    reset: Optional[bool] = Field(default=False, description="是否重置偏好画像")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantExecutePlanToolInput(BaseModel):
    plan_id: Optional[str] = Field(default=None, description="可选 dry_run 返回的 plan_id；不传时可按 session/session_id 自动选择最近计划")
    session: Optional[str] = Field(default=None, description="可选会话名；未传 plan_id 时可按会话自动选择最近计划")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    prefer_unexecuted: Optional[bool] = Field(default=True, description="自动选计划时是否优先只选未执行计划")
    stop_on_error: Optional[bool] = Field(default=True, description="遇到失败动作时是否停止")
    include_raw_results: Optional[bool] = Field(default=False, description="是否附带原始执行结果")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")


class AssistantPlansToolInput(BaseModel):
    session: Optional[str] = Field(default=None, description="可选会话名；不填则返回全部最近计划")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    executed: Optional[bool] = Field(default=None, description="可选过滤：true 只看已执行，false 只看未执行")
    include_actions: Optional[bool] = Field(default=False, description="是否附带计划动作明细；默认关闭以减少 token")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")
    limit: Optional[int] = Field(default=20, description="最多返回多少条计划")


class AssistantPlansClearToolInput(BaseModel):
    plan_id: Optional[str] = Field(default=None, description="可选计划 ID；传入时只清理这一条")
    session: Optional[str] = Field(default=None, description="可选会话名；按会话清理")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    executed: Optional[bool] = Field(default=None, description="可选过滤：true 只清理已执行，false 只清理未执行")
    all_plans: Optional[bool] = Field(default=False, description="清理全部计划；未指定 plan_id/session/session_id/executed 时需要显式打开")
    limit: Optional[int] = Field(default=100, description="批量清理时最多清理多少条")


class AssistantRecoverToolInput(BaseModel):
    session: Optional[str] = Field(default=None, description="可选会话名；不传则自动从全局活跃会话和待执行计划里挑选最佳恢复项")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID，优先于 session")
    execute: Optional[bool] = Field(default=False, description="是否直接执行推荐恢复动作；默认只返回恢复建议")
    prefer_unexecuted: Optional[bool] = Field(default=True, description="执行保存计划时是否优先选择未执行计划")
    stop_on_error: Optional[bool] = Field(default=True, description="执行恢复动作时遇到失败是否停止")
    include_raw_results: Optional[bool] = Field(default=False, description="是否附带原始执行结果；默认关闭以减少 token")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启，只返回恢复所需关键字段")
    limit: Optional[int] = Field(default=20, description="全局恢复扫描时最多查看多少个会话")


class AssistantSessionsToolInput(BaseModel):
    kind: Optional[str] = Field(default=None, description="按会话类型过滤，例如 assistant_pansou / assistant_hdhive / assistant_p115_login")
    has_pending_p115: Optional[bool] = Field(default=None, description="是否只看带待继续 115 任务的会话")
    compact: Optional[bool] = Field(default=True, description="是否使用低 token 回执；默认开启")
    limit: Optional[int] = Field(default=20, description="最多返回多少条活跃会话摘要")


class AssistantSessionsClearToolInput(BaseModel):
    session: Optional[str] = Field(default=None, description="可选会话名；只清理这一个会话")
    session_id: Optional[str] = Field(default=None, description="可选 assistant:: 会话 ID；只清理这一个会话")
    kind: Optional[str] = Field(default=None, description="按会话类型批量清理")
    has_pending_p115: Optional[bool] = Field(default=None, description="是否只清理带待继续 115 任务的会话")
    stale_only: Optional[bool] = Field(default=False, description="只清理已过期但仍残留的 assistant 会话")
    all_sessions: Optional[bool] = Field(default=False, description="清理全部 assistant 会话；用于重置外部智能体状态")
    limit: Optional[int] = Field(default=100, description="批量清理时最多清理多少条")


class P115QRCodeStartToolInput(BaseModel):
    client_type: Optional[str] = Field(default="alipaymini", description="115 扫码客户端类型，默认 alipaymini")


class P115QRCodeCheckToolInput(BaseModel):
    uid: str = Field(..., description="上一步二维码返回的 uid")
    time: str = Field(..., description="上一步二维码返回的 time")
    sign: str = Field(..., description="上一步二维码返回的 sign")
    client_type: Optional[str] = Field(default="alipaymini", description="客户端类型，需与生成二维码时保持一致")


class P115StatusToolInput(BaseModel):
    pass


class P115PendingToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识；不填则查看 default 会话")


class P115ResumePendingToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识；不填则继续 default 会话的待处理 115 任务")


class P115CancelPendingToolInput(BaseModel):
    session: Optional[str] = Field(default="default", description="会话标识；不填则取消 default 会话的待处理 115 任务")
