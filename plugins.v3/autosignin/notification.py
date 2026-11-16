"""汇总站点任务的语义结果，渠道能力、转义及消息分段由宿主处理。"""

import re
from typing import List

from app.plugins.autosignin.result import SiteResult, merge_failure_messages
from app.schemas.message import NotificationBlock, NotificationContent

_DETAIL_LIMIT = 160
_NAME_LIMIT = 60
_LOGIN_FAILURE = "Cookie / Token / 登录状态异常"
_UNCONFIRMED_LOGIN = r"未识别到登录状态|未确认(?:到)?登录状态"
# CSRF token 是页面提交参数，不是登录凭据，不能因同含 Token 而归为登录失效。
_CREDENTIAL = r"(?<![a-z_])(?:cookie|(?<!csrf-)token|authorization|api[-_]?key)"
_HTTP_STATUS = r"(?:状态码|http(?:status(?:code)?)?|status(?:code)?)[:：=]?"
_UNCONFIRMED_RESULT = (r"未确认(?:到)?签到(?:结果|成功状态)|接口未确认访问时间更新|"
                       r"签到(?:页)?状态未知|未返回可确认的结果|签到接口未返回明确的成功或重复签到结果")

# 明确原因优先于泛化的登录证据缺失；404 可能只是签到入口不存在，不能拆散同类登录失败。
_FAILURE_RULES = (
    ("站点配置缺失", rf"(?:未配置|未填写|未设置|未提供|缺少)[^；;]*(?:站点(?:地址|信息)|{_CREDENTIAL})|"
                 rf"(?:站点(?:地址|信息)|{_CREDENTIAL})(?:为空|未配置|缺失|未填写)"),
    (_LOGIN_FAILURE, rf"{_CREDENTIAL}(?:登录(?:态|状态|信息)|格式)?(?:已|已经)?"
                     r"(?:失效|过期|无效|不正确|不对|错误|权限不足|(?:is)?(?:invalid|expired))|"
                     r"(?:登录态|登录状态|登录凭据)(?:已|已经)?(?:失效|过期|无效)|"
                     r"未(?:登录|登陆)|(?:请|需要|必须)(?:先|重新)?(?:登录|登陆)|"
                     r"(?:invalid|expired)(?:cookie|token)|unauthorized|fullauthenticationisrequired|"
                     rf"authenticationrequired|{_HTTP_STATUS}401(?!\d)"),
    ("Cloudflare 防护验证失败", r"cloudflare"),
    ("验证码获取或校验失败", r"验证码|captcha|invalid_imagehash"),
    ("网络请求超时", rf"超时|timeout|timedout|{_HTTP_STATUS}408(?!\d)"),
    ("网络连接失败", r"无法(?:打开|访问)(?:网站|签到页)|站点连通性|请求无响应|"
                   r"connection(?:error|refused|reset|aborted)|nameresolutionerror|failedtoresolve|"
                   r"(?:连接|域名解析|dns解析)(?:失败|错误)"),
    ("站点访问被拒绝（HTTP 403）", rf"{_HTTP_STATUS}403(?!\d)"),
    ("站点访问频率受限（HTTP 429）", rf"{_HTTP_STATUS}429(?!\d)"),
    ("站点服务异常（HTTP 5xx）", rf"{_HTTP_STATUS}5\d{{2}}(?!\d)"),
    ("站点页面或接口解析异常", r"空页面|空响应|接口(?:返回)?数据异常|csrf|"
                          r"未获取到(?:相关)?签到(?:参数|问题|图片)|未获取到(?:答案选项|匹配答案)|获取签到参数失败"),
)


def _compact(text: str, limit: int) -> str:
    """压缩站点结果的换行并限制展示长度，完整原文保留在插件详情。"""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _failure_reason(message: str) -> str:
    """
    为通知摘要选择稳定的失败类别，不改写历史中的真实错误和重试依据。

    登录证据缺失不等于 Cookie 已失效，因此共用中性标题；明确防护、网络和页面错误仍独立分类。
    未知业务错误保留完整原因作分组键，不能因为展示截断或包含 Cookie 字样而误合并。

    :param message: 站点执行结果中的原始失败文案
    :return: 通知展示类别，无法识别时返回去重后的原始原因
    """
    reason = re.sub(r"\s+", " ", merge_failure_messages(message)).strip()
    key = re.sub(r"\s+", "", reason)
    for label, pattern in _FAILURE_RULES:
        if re.search(pattern, key, re.IGNORECASE):
            return label
    status_codes = sorted(set(re.findall(rf"{_HTTP_STATUS}([1-5]\d{{2}})(?!\d)", key, re.IGNORECASE)))
    # 没有更具体的 HTTP 错误时才使用登录证据缺失；签到入口 404 可作为伴随错误。
    if re.search(_UNCONFIRMED_LOGIN, key) and all(code == "404" for code in status_codes):
        return _LOGIN_FAILURE
    if status_codes:
        return f"HTTP 状态异常（{' / '.join(status_codes)}）"
    if re.search(_UNCONFIRMED_RESULT, key, re.IGNORECASE):
        return "站点返回结果未确认"
    return reason or "未返回具体失败原因"


def _group_results(rows: list, retry_ids: list) -> List[NotificationBlock]:
    """同一状态内按失败类别或成功原因归并，保留所有站点及各自重试标记。"""
    reasons: dict[str, list[str]] = {}
    for site_id, result in rows:
        message = result.message if result.completed else _failure_reason(result.message)
        reason = re.sub(r"\s+", " ", str(message)).strip()
        name = _compact(result.site_name, _NAME_LIMIT)
        if site_id in retry_ids:
            name += " ↻"
        reasons.setdefault(reason, []).append(name)
    return [NotificationBlock(title=_compact(reason, _DETAIL_LIMIT), text="、".join(names))
            for reason, names in reasons.items()]


def build_notification_content(day: str, action: str, results: List[SiteResult],
                               total: int, retry_ids: list, site_ids: list) -> NotificationContent:
    """先按业务状态、再按失败类别或成功原因归并，失败优先；构造与渠道无关的通知。"""
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
