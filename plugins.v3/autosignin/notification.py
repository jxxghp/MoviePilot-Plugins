"""汇总站点任务的语义结果，渠道能力、转义及消息分段由宿主处理。"""

import re
from typing import List

from app.plugins.autosignin.result import SiteResult
from app.schemas.message import NotificationBlock, NotificationContent

_DETAIL_LIMIT = 160
_NAME_LIMIT = 60


def _compact(text: str, limit: int) -> str:
    """压缩站点结果的换行并限制展示长度，完整原文保留在插件详情。"""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def build_notification_content(day: str, action: str, results: List[SiteResult],
                               total: int, retry_ids: list, site_ids: list) -> NotificationContent:
    """按明确业务结果分组，失败优先；仅构造一份与渠道无关的通知数据。"""
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
        for site_id, result in rows:
            retry = " · ↻ 下次执行" if site_id in retry_ids else ""
            blocks.append(NotificationBlock(title=_compact(result.site_name, _NAME_LIMIT) + retry,
                                            text=_compact(result.message, _DETAIL_LIMIT)))
    blocks.append(NotificationBlock(text="💡 仅登录不计入签到成功。" if action == "签到" else "💡 本次执行为登录保号。"))
    return NotificationContent(title=f"站点自动{action}", blocks=blocks)
