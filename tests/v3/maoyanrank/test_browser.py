"""猫眼浏览器会话在导航及请求失败时的资源释放回归。"""

from unittest.mock import Mock

import pytest

from app.plugins import maoyanrank


@pytest.mark.parametrize("failure", ["navigation", "callback", "page_close"])
def test_browser_context_is_released_on_failure(monkeypatch, failure):
    """无论哪个阶段失败，均关闭整个浏览器上下文。"""
    context = Mock()
    page = context.new_page.return_value
    callback = Mock()
    monkeypatch.setattr(maoyanrank, "launch_browser_context", Mock(return_value=context))
    if failure == "navigation":
        page.goto.side_effect = RuntimeError("navigation failed")
    elif failure == "callback":
        callback.side_effect = RuntimeError("callback failed")
    else:
        page.close.side_effect = RuntimeError("page close failed")

    with pytest.raises(RuntimeError):
        maoyanrank.MaoyanRank._MaoyanRank__with_browser(callback)

    page.close.assert_called_once()
    context.close.assert_called_once()
    if failure == "navigation":
        callback.assert_not_called()
    else:
        callback.assert_called_once_with(page)
