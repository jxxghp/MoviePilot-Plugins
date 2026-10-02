"""签到结果及页面证据校验，禁止用登录状态或缺失按钮推断签到完成。"""

import re
from typing import NamedTuple

from app.utils.site import SiteUtils
from lxml import etree


class SiteResult(NamedTuple):
    """分别保留请求动作的完成状态与登录证据，登录保号不能冒充签到。"""

    site_name: str
    message: str
    success: bool
    logged_in: bool = False

    @property
    def completed(self) -> bool:
        """已签到或确认登录均完成本轮访问任务，签到 API 仍单独使用 success。"""
        return self.success or self.logged_in


def visible_html(source: str) -> str:
    """移除脚本、注释和显式隐藏内容，避免把模板中的成功提示当作实际结果。"""
    document = etree.HTML(source or "")
    if document is None:
        return ""
    for node in document.xpath(
        "//head | //script | //style | //template | //noscript | //textarea | //comment() | "
        "//*[@hidden or @aria-hidden='true'] | //input[@type='hidden']"
    ):
        parent = node.getparent()
        if parent is not None:
            if node.tail:
                previous = node.getprevious()
                if previous is None:
                    parent.text = (parent.text or "") + node.tail
                else:
                    previous.tail = (previous.tail or "") + node.tail
            parent.remove(node)
    for node in document.xpath("//*[@style]"):
        if re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", node.get("style", ""), re.IGNORECASE):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
    return etree.tostring(document, encoding="unicode", method="html")


def has_login_form(source: str) -> bool:
    """仅在可见页面确实要求输入密码时判定 Cookie 登录已失效。"""
    document = etree.HTML(visible_html(source))
    return document is not None and bool(document.xpath(
        "//input[translate(@type, 'PASSWORD', 'password')='password']"
    ))


def has_login_evidence(source: str) -> bool:
    """识别可见的用户导航或退出控件，兼容新模板且排除隐藏模板和登录表单。"""
    source = visible_html(source)
    document = etree.HTML(source)
    if document is None or document.xpath("//input[translate(@type, 'PASSWORD', 'password')='password']"):
        return False
    if SiteUtils.is_logged_in(source):
        return True
    for node in document.xpath("//a | //button | //form | //*[@role='button'] | //shark-icon-button"):
        for attr in ("href", "action", "formaction", "data-url", "onclick", "lay-on"):
            if re.search(r"\b(?:logout|logoff|signout)\b", node.get(attr, ""), re.IGNORECASE):
                return True
        label = re.sub(r"\s+", "", "".join(node.itertext())).lower()
        if node.tag != "form" and label in {"退出登录", "退出登錄", "登出", "logout", "signout"}:
            return True
    return False


def has_signin_evidence(source: str) -> bool:
    """只接受可见的完成状态或本次奖励，未完成表单和否定提示优先拒绝。"""
    document = etree.HTML(visible_html(source))
    if document is None or document.xpath("//input[@type='password']"):
        return False
    text = re.sub(r"\s+", " ", " ".join(document.itertext())).strip()
    compact = re.sub(r"\s+", "", text)
    if re.search(r"(?:签到|簽到)(?:失败|失敗|未成功)|(?:未|没有|沒有)(?:签到|簽到)成功", compact):
        return False
    # 带验证码或提交按钮的签到表单仍等待用户操作，页面上的说明不构成成功证据。
    for node in document.xpath("//input[@type='submit'] | //button"):
        label = re.sub(r"\s+", "", node.get("value") or "".join(node.itertext())).lower()
        if label in {"签到", "簽到", "立即签到", "立即簽到", "每日签到", "打卡", "checkin", "checkinnow"}:
            return False
    for node in document.iter():
        label = re.sub(r"\s+", "", "".join(node.itertext()))
        if re.fullmatch(r"(?:您|你)?(?:今天|今日)?(?:尚未|还未|還未|未|没有|沒有)(?:签到|簽到)[！!。.]?", label):
            return False
    for node in document.iter():
        if node.tag == "input" and node.get("type", "").lower() not in {"button", "submit"}:
            continue
        label = re.sub(r"\s+", "", node.get("value") or "".join(node.itertext()))
        if re.fullmatch(r"(?:签到成功|簽到成功|(?:今日|今天)?(?:已签到|已簽到|已经签到|已經簽到)|已经打卡)[！!。.]?", label):
            return True
    # NexusPHP 的当前用户签到结果；普通奖励说明或累计天数不是当天签到凭据。
    return bool(re.search(
        r"(?:您|你)(?:今天|今日)(?:已(?:经)?签(?:到|过到)|已經簽到)(?:过|過|了)|"
        r"(?:本次|此次)(?:签到|簽到)(?:您)?(?:获得|獲得)(?:了)?\d|(?:签到|簽到)已得\d",
        compact,
    ) or re.search(
        r"You have already attend, no refresh please\.|"
        r"You have already attended \d+ days, Continuous \d+ days, this time you will get \d+ bonus\.",
        text,
        re.IGNORECASE,
    ))
