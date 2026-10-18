"""汇总站点任务的语义结果，渠道能力、转义及消息分段由宿主处理。"""

import re
from typing import List

from app.plugins.autosignin.result import SiteResult, merge_failure_messages
from app.schemas.message import NotificationBlock, NotificationContent

_DETAIL_LIMIT = 160
_NAME_LIMIT = 60


def _compact(text: str, limit: int) -> str:
    """压缩站点结果的换行并限制展示长度，完整原文保留在插件详情。"""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _group_results(rows: list, retry_ids: list) -> List[NotificationBlock]:
    """同一状态内按完整结果原因归并，原因只展示一次，保留所有站点及各自重试标记。"""
    reasons: dict[str, list[str]] = {}
    for site_id, result in rows:
        message = result.message if result.completed else merge_failure_messages(result.message)
        reason = re.sub(r"\s+", " ", str(message)).strip()
        name = _compact(result.site_name, _NAME_LIMIT)
        if site_id in retry_ids:
            name += " ↻"
        reasons.setdefault(reason, []).append(name)
    return [NotificationBlock(title=_compact(reason, _DETAIL_LIMIT), text="、".join(names))
            for reason, names in reasons.items()]


def build_notification_content(day: str, action: str, results: List[SiteResult],
                               total: int, retry_ids: list, site_ids: list) -> NotificationContent:
    """先按业务状态、再按相同原因归并，失败优先；构造一份与渠道无关的通知。"""
    failed = [(site_id, result) for site_id, result in zip(site_ids, results) if not result.completed]
    login_only = [(site_id, result) for site_id, result in zip(site_ids, results)
                  if result.logged_in and not result.success]
    succeeded = [(site_id, result) for site_id, result in zip(site_ids, results) if result.success]
    success_label = "确认签到" if action == "签到" else "确认登录"
    login_label = "🟡 仅确认登录 · 签到未确认" if action == "签到" else "🟡 仅确认登录访问"
    groups = [("❌ 登录或访问失败", failed), (login_label, login_only),
              (f"✅ {success_label}成功", succeeded)]
    blocks = [NotificationBlock(text=f"📅 {day} · 本次{action}结果"),
              NotificationBlock(title=f"{success_label} {len(succeeded)}  ·  仅登录 {len(login_only)}  ·  失败 {len(failed)}",
                                text=f"已选 {total}  /  本次 {len(results)}  /  下次执行 {len(retry_ids)}")]
    for label, rows in groups:
        if not rows:
            continue
        blocks.append(NotificationBlock(title=f"{label} · {len(rows)}"))
        blocks.extend(_group_results(rows, retry_ids))
    footer = "💡 仅登录不计入签到成功。" if action == "签到" else "💡 本次执行为登录保号。"
    if retry_ids:
        footer += "↻ 表示下次执行。"
    blocks.append(NotificationBlock(text=footer))
    return NotificationContent(title=f"站点自动{action}", blocks=blocks)
