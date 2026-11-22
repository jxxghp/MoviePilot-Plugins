"""基类完成凭据与整页负向文案的优先级回归。"""

from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.plugins.autosignin.sites.u2 import U2

_CREDENTIAL = "感谢，今天已签到。"
# 当天完成提示与发言区引用的站点公告原文（含“签到失败”字样）同时可见。
_PAGE = (
    '<html><body><a href="logout.php">退出</a>'
    f'<p>{_CREDENTIAL}</p>'
    '<div class="text">如問題已經過期或出現其他錯誤，則視為簽到失敗而非回答錯誤。</div>'
    '</body></html>'
)


def test_default_handlers_still_reject_notice_failure_wording():
    """未开启正向优先的处理器保持整页负向预判。"""
    assert not _ISiteSigninHandler.sign_in_result(_PAGE, [_CREDENTIAL])


def test_u2_today_credential_wins_over_notice():
    """U2 开启正向优先后，公告引用不再否掉当天完成提示。"""
    assert U2.sign_in_result(_PAGE, U2._sign_regex)
