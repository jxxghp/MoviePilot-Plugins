"""Vuetify JSON 页面：配置表单、报告详情页与通知摘要。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from .models import ISSUE_TYPE_LABELS, VERSION_DIMENSIONS, Issue, IssueType, Report, Severity

# 每类问题在详情页展示的上限，完整数据可通过 /report 接口获取
MAX_ROWS_PER_TYPE = 300
# 每条问题展示的明细行数上限
MAX_DETAIL_LINES = 8

_TYPE_COLORS = {
    IssueType.MISSING: "error",
    IssueType.VERSION: "warning",
    IssueType.DUPLICATE: "info",
    IssueType.CONFLICT: "purple",
    IssueType.UNCHECKED: "grey",
    IssueType.SUGGESTION: "teal",
}

_TYPE_ORDER = [
    IssueType.SUGGESTION, IssueType.MISSING, IssueType.VERSION, IssueType.DUPLICATE, IssueType.CONFLICT, IssueType.UNCHECKED,
]


def _col(content: list[dict], **props: Any) -> dict:
    """生成栅格列。"""
    return {"component": "VCol", "props": props or {"cols": 12}, "content": content}


def _row(*cols: dict) -> dict:
    """生成栅格行。"""
    return {"component": "VRow", "content": list(cols)}


def _switch(model: str, label: str, hint: str = "", md: int = 4) -> dict:
    """生成开关字段列。"""
    props: dict[str, Any] = {"model": model, "label": label}
    if hint:
        props.update({"hint": hint, "persistent-hint": True})
    return _col([{"component": "VSwitch", "props": props}], cols=12, md=md)


def _text(model: str, label: str, hint: str = "", md: int = 4, **extra: Any) -> dict:
    """生成文本输入列。"""
    props: dict[str, Any] = {"model": model, "label": label, **extra}
    if hint:
        props.update({"hint": hint, "persistent-hint": True})
    return _col([{"component": "VTextField", "props": props}], cols=12, md=md)


def _textarea(model: str, label: str, placeholder: str, hint: str, rows: int = 3, md: int = 12) -> dict:
    """生成多行文本列。"""
    return _col([{
        "component": "VTextarea",
        "props": {
            "model": model,
            "label": label,
            "rows": rows,
            "placeholder": placeholder,
            "hint": hint,
            "persistent-hint": True,
        },
    }], cols=12, md=md)


def _section(title: str) -> dict:
    """生成分组标题行。"""
    return _row(_col([{"component": "div", "props": {"class": "text-subtitle-1 font-weight-bold mt-2"}, "text": title}]))


def build_form(server_items: list[str]) -> list[dict]:
    """生成配置页面。"""
    dimension_items = [{"title": label, "value": key} for key, label in VERSION_DIMENSIONS.items()]
    return [
        {
            "component": "VForm",
            "content": [
                _row(
                    _switch("enabled", "启用插件"),
                    _switch("notify", "扫描完成后通知"),
                    _switch("onlyonce", "保存后立即扫描一次"),
                ),
                _row(_col([{
                    "component": "VCronField",
                    "props": {"model": "cron", "label": "定时扫描周期", "placeholder": "5 位 cron 表达式，留空不定时"},
                }], cols=12, md=4)),

                _section("数据来源"),
                _row(
                    _switch("use_emby", "扫描 Emby"),
                    _col([{
                        "component": "VSelect",
                        "props": {
                            "model": "servers",
                            "label": "Emby 服务器",
                            "items": server_items,
                            "multiple": True,
                            "chips": True,
                            "clearable": True,
                            "hint": "留空表示全部已启用的 Emby 服务器",
                            "persistent-hint": True,
                        },
                    }], cols=12, md=4),
                    _col([{
                        "component": "VCombobox",
                        "props": {
                            "model": "libraries",
                            "label": "Emby 媒体库名称",
                            "multiple": True,
                            "chips": True,
                            "clearable": True,
                            "hint": "输入后回车；留空表示全部影视库（不含家庭视频库）",
                            "persistent-hint": True,
                        },
                    }], cols=12, md=4),
                ),
                _row(
                    _switch("read_nfo", "读取 NFO 补充信息", "缺单集 ID 或 strm 未探测时读取同名 NFO"),
                    _textarea(
                        "path_mappings", "Emby 路径映射", "/media => /mnt/media",
                        "每行一条：Emby 中的路径 => MoviePilot 中的路径；两边一致时留空", md=8,
                    ),
                ),
                _row(_textarea(
                    "local_dirs", "本地扫描目录", "/media/电视剧\n/media/strm/动漫",
                    "每行一个 MoviePilot 中的目录，不经过 Emby 直接扫描；建议只填未加入 Emby 的目录，避免重复报告",
                )),
                _row(
                    _switch("local_probe", "读取本地视频媒体信息", "用 ffprobe/mediainfo 读取分辨率、编码、HDR；strm 不读取"),
                    _text("probe_max_files", "每轮最多新读取文件数", "已读取过且未变化的文件走缓存", type="number"),
                    _text("probe_path", "ffprobe/mediainfo 路径", "留空自动查找"),
                ),

                _section("检查项"),
                _row(
                    _switch("check_missing", "检查缺集", "按单集 TMDB ID 对比已播出的集"),
                    _switch("check_versions", "检查同季版本一致性", "以多数版本为基准报告偏离"),
                    _switch("check_duplicates", "检查多文件", "同一集或同一电影存在多个文件"),
                ),
                _row(
                    _text("air_buffer_days", "播出缓冲天数", "播出超过该天数才计入缺集", type="number"),
                    _switch("include_specials", "检查第 0 季（特别篇）"),
                    _switch("only_existing_seasons", "只检查库中已有的季", "关闭时整季缺失也会报告"),
                ),
                _row(
                    _col([{
                        "component": "VSelect",
                        "props": {
                            "model": "dimensions",
                            "label": "版本比较维度",
                            "items": dimension_items,
                            "multiple": True,
                            "chips": True,
                            "hint": "发布组/字幕组差异只作提示；未知取值不参与比较",
                            "persistent-hint": True,
                        },
                    }], cols=12, md=8),
                    _switch("ignore_mixed", "忽略 strm 与本地文件并存", "同一集同时有两种文件时不报多文件"),
                ),

                _section("AI 建议"),
                _row(
                    _switch("ai_enabled", "启用 AI 建议", "需在系统设置中启用智能助手；AI 只提建议，经规则验证后由你采纳"),
                    _switch("ai_summary", "AI 生成报告摘要", "摘要附在通知与报告页"),
                ),

                _section("规则"),
                _row(_textarea(
                    "ignore_rules", "忽略规则",
                    "tmdb:1399\nmissing@tmdb:1399:S0\nversion@tmdb:1399:S2\nduplicate@tmdb:1399:S1E5",
                    "每行一条，# 后为注释；可在报告页点击「忽略」自动添加", rows=4,
                )),
                _row(
                    _textarea(
                        "number_mappings", "编号映射", "tmdb:1399 S1E13-E24 => S2E1",
                        "库内编号与 TMDB 不同时按此对应；可在报告页采纳 AI 建议自动添加", md=6,
                    ),
                    _textarea(
                        "identity_overrides", "身份指定", "emby:Emby/12345 => tmdb:1399\nlocal:/media/剧名 => tmdb:1399",
                        "为无法识别或识别错误的剧集指定 TMDB ID；可在报告页采纳 AI 建议自动添加", md=6,
                    ),
                ),
                _row(_col([{
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": (
                            "插件只读取 Emby、本地目录、NFO 与 TMDB 数据并生成报告，不修改、不删除任何文件，也不会自动订阅。"
                            "缺集只与 TMDB 已播出的集比较；无法确定 TMDB ID 或 TMDB 查询失败的剧集归入「无法核对」，不视为完整。"
                            "忽略规则格式为 [类型@]tmdb:ID[:S季[E集]]，类型可选 missing、version、duplicate、conflict、unchecked、suggestion。"
                        ),
                    },
                }])),
            ],
        }
    ]


def _row_actions(issue: Issue, plugin_id: str) -> list[dict]:
    """生成行内操作按钮：AI 建议可采纳，所有问题都可忽略。"""
    buttons: list[dict] = []
    if issue.adopt_kind and issue.adopt_rule:
        buttons.append({
            "component": "VBtn",
            "props": {"size": "small", "variant": "tonal", "color": "primary", "class": "me-1"},
            "text": "采纳",
            "events": {
                "click": {
                    "api": f"plugin/{plugin_id}/adopt",
                    "method": "post",
                    "params": {"kind": issue.adopt_kind, "rule": issue.adopt_rule},
                }
            },
        })
    buttons.append({
        "component": "VBtn",
        "props": {"size": "small", "variant": "tonal", "color": "secondary"},
        "text": "忽略",
        "events": {
            "click": {
                "api": f"plugin/{plugin_id}/ignore",
                "method": "post",
                "params": {"key": issue.scope, "type": issue.type.value},
            }
        },
    })
    return buttons


def _issue_row(issue: Issue, plugin_id: str) -> dict:
    """生成报告表格中的一行。"""
    details = issue.details[:MAX_DETAIL_LINES]
    if len(issue.details) > MAX_DETAIL_LINES:
        details.append(f"……另有 {len(issue.details) - MAX_DETAIL_LINES} 条")
    location = issue.library if not issue.server else f"{issue.server} / {issue.library}"
    return {
        "component": "tr",
        "content": [
            {
                "component": "td",
                "content": [
                    {"component": "div", "props": {"class": "font-weight-medium"}, "text": issue.title},
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": location},
                ],
            },
            {
                "component": "td",
                "content": [
                    {
                        "component": "div",
                        "content": [
                            {
                                "component": "VChip",
                                "props": {
                                    "size": "x-small",
                                    "class": "me-2",
                                    "color": "warning" if issue.severity == Severity.WARNING else "default",
                                },
                                "text": "警告" if issue.severity == Severity.WARNING else "提示",
                            },
                            {"component": "span", "text": issue.summary},
                        ],
                    },
                    *[
                        {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": line}
                        for line in details
                    ],
                ],
            },
            {
                "component": "td",
                "props": {"class": "text-no-wrap"},
                "content": _row_actions(issue, plugin_id),
            },
        ],
    }


def _issue_panel(issue_type: IssueType, issues: list[Issue], plugin_id: str) -> dict:
    """生成一类问题的折叠面板。"""
    shown = issues[:MAX_ROWS_PER_TYPE]
    rows = [_issue_row(issue, plugin_id) for issue in shown]
    content: list[dict] = [{
        "component": "VTable",
        "props": {"density": "compact", "hover": True},
        "content": [
            {
                "component": "thead",
                "content": [{
                    "component": "tr",
                    "content": [
                        {"component": "th", "text": "媒体"},
                        {"component": "th", "text": "问题"},
                        {"component": "th", "text": "操作"},
                    ],
                }],
            },
            {"component": "tbody", "content": rows},
        ],
    }]
    if len(issues) > len(shown):
        content.append({
            "component": "div",
            "props": {"class": "text-caption pa-2"},
            "text": f"仅显示前 {len(shown)} 条，共 {len(issues)} 条；完整数据可调用插件 /report 接口获取。",
        })
    return {
        "component": "VExpansionPanel",
        "content": [
            {
                "component": "VExpansionPanelTitle",
                "content": [{
                    "component": "VChip",
                    "props": {"color": _TYPE_COLORS[issue_type], "size": "small", "class": "me-2"},
                    "text": str(len(issues)),
                }, {"component": "span", "text": ISSUE_TYPE_LABELS[issue_type]}],
            },
            {"component": "VExpansionPanelText", "content": content},
        ],
    }


def build_page(
    plugin_id: str,
    report: Optional[Report],
    visible: list[Issue],
    ignored: int,
    progress: str,
) -> list[dict]:
    """生成报告详情页。"""
    header: list[dict] = []
    if progress:
        header.append({
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "class": "mb-3", "text": f"正在扫描：{progress}"},
        })
    actions = {
        "component": "div",
        "props": {"class": "d-flex align-center flex-wrap ga-2 mb-3"},
        "content": [
            {
                "component": "VBtn",
                "props": {"color": "primary", "prepend-icon": "mdi-magnify-scan", "disabled": bool(progress)},
                "text": "立即扫描",
                "events": {"click": {"api": f"plugin/{plugin_id}/scan", "method": "post", "params": {}}},
            },
        ],
    }
    if report is None:
        return header + [actions, {
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "text": "还没有扫描报告，点击「立即扫描」或等待定时扫描。"},
        }]

    stats = report.stats
    actions["content"].append({
        "component": "span",
        "props": {"class": "text-caption text-medium-emphasis"},
        "text": (
            f"上次扫描 {report.finished_at}，耗时 {report.duration_seconds} 秒；"
            f"{'、'.join(stats.servers) or '无服务器'}，{stats.libraries} 个媒体库，"
            f"{stats.series} 部剧 / {stats.episodes} 个单集条目 / {stats.movies} 部电影；"
            f"读取 NFO {stats.nfo_reads} 个，TMDB 查询 {stats.tmdb_requests} 次，"
            f"新读取媒体信息 {stats.probes} 个，AI 调用 {stats.ai_calls} 次"
        ),
    })
    notices: list[dict] = []
    if report.ai_summary:
        notices.append({
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "class": "mb-2", "title": "AI 摘要"},
            "content": rich_text_lines(report.ai_summary),
        })
    for error in report.errors[:10]:
        notices.append({"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "density": "compact", "class": "mb-2", "text": error}})
    if report.truncated:
        notices.append({"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "density": "compact", "class": "mb-2", "text": "问题数量超过上限，报告已截断。可添加忽略规则或缩小扫描的媒体库范围。"}})
    if ignored:
        notices.append({"component": "div", "props": {"class": "text-caption mb-2"}, "text": f"已按忽略规则隐藏 {ignored} 条问题，可在配置页的「忽略规则」中恢复。"})

    grouped: dict[IssueType, list[Issue]] = {issue_type: [] for issue_type in _TYPE_ORDER}
    for issue in visible:
        grouped.setdefault(issue.type, []).append(issue)
    panels = [_issue_panel(t, grouped[t], plugin_id) for t in _TYPE_ORDER if grouped.get(t)]
    if not panels:
        body: dict = {"component": "VAlert", "props": {"type": "success", "variant": "tonal", "text": "没有发现问题。"}}
    else:
        body = {"component": "VExpansionPanels", "props": {"multiple": True}, "content": panels}
    return header + [actions] + notices + [body]


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_PREFIX = re.compile(r"^(#{1,6}\s+|>\s*)")


def rich_text_lines(text: str) -> list[dict]:
    """把 AI 输出的简单 Markdown 转为逐行展示的组件：保留换行，**加粗** 转为粗体，去掉标题等符号。

    AI 输出可能夹带剧名等不受信任的内容，因此只生成文本组件，不使用 HTML 渲染。
    """
    rows: list[dict] = []
    for raw in str(text or "").splitlines():
        line = _MARKDOWN_PREFIX.sub("", raw.strip())
        if not line:
            continue
        parts: list[dict] = []
        position = 0
        for match in _BOLD.finditer(line):
            if match.start() > position:
                parts.append({"component": "span", "text": line[position:match.start()]})
            parts.append({"component": "span", "props": {"class": "font-weight-bold"}, "text": match.group(1)})
            position = match.end()
        if position < len(line):
            parts.append({"component": "span", "text": line[position:]})
        rows.append({"component": "div", "props": {"class": "mt-1"}, "content": parts})
    return rows


def plain_text(text: str) -> str:
    """去掉 AI 输出中的 Markdown 标记，供纯文本通知使用，保留换行。"""
    lines = (_MARKDOWN_PREFIX.sub("", _BOLD.sub(r"\1", raw.strip())) for raw in str(text or "").splitlines())
    return "\n".join(line for line in lines if line)


def build_summary_text(report: Report, visible: list[Issue], ignored: int) -> str:
    """生成扫描完成通知的正文。"""
    counts = Counter(issue.type for issue in visible)
    missing_eps = sum(len(issue.episodes) for issue in visible if issue.type == IssueType.MISSING)
    missing_series = len({(i.server, i.media_id or i.title) for i in visible if i.type == IssueType.MISSING})
    lines = [
        f"扫描 {report.stats.series} 部剧、{report.stats.movies} 部电影，耗时 {report.duration_seconds} 秒",
        f"缺集：{missing_series} 部剧共 {missing_eps} 集",
        f"版本偏离：{counts.get(IssueType.VERSION, 0)} 项",
        f"多文件：{counts.get(IssueType.DUPLICATE, 0)} 项",
        f"编号冲突：{counts.get(IssueType.CONFLICT, 0)} 项",
        f"无法核对：{counts.get(IssueType.UNCHECKED, 0)} 部",
    ]
    if counts.get(IssueType.SUGGESTION):
        lines.append(f"AI 建议待采纳：{counts[IssueType.SUGGESTION]} 项")
    if ignored:
        lines.append(f"已忽略：{ignored} 项")
    if report.errors:
        lines.append(f"扫描错误：{len(report.errors)} 个，详见插件详情页")
    if report.ai_summary:
        lines.append(f"\nAI 摘要：\n{plain_text(report.ai_summary)}")
    return "\n".join(lines)
