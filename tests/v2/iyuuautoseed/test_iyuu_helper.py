"""IYUUAutoSeed V2 的上游响应异常回归测试。"""

import json
from unittest.mock import patch

from app.plugins.iyuuautoseed.iyuu_helper import IyuuHelper


class _Response:
    """构造 IYUU helper 所需的最小 HTTP 响应对象。"""

    def __init__(self, payload=None, text=""):
        self.status_code = 200
        self.text = text
        self._payload = payload

    def json(self):
        """返回模拟 JSON 结果，或抛出指定的 JSON 解析异常。"""
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_get_seed_info_downgrades_malformed_json_response():
    """IYUU 返回损坏 JSON 时应返回可读错误，而不是向定时任务抛异常。"""
    response_text = "{\"code\":0,\"data\":\"truncated"
    response = _Response(
        json.JSONDecodeError("Unterminated string", response_text, len(response_text)),
        response_text,
    )
    helper = IyuuHelper("test-token")
    helper._sid_sha1 = "sid-sha1"

    with patch("app.plugins.iyuuautoseed.iyuu_helper.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = response

        result, message = helper.get_seed_info(["hash-b"])

    assert result is None
    assert "响应解析失败：JSONDecodeError" in message
    assert "状态码：200" in message
    assert "响应前缀：{\"code\":0,\"data\":\"truncated" in message


def test_get_seed_info_preserves_valid_json_response():
    """IYUU 返回合法 JSON 时应继续透传种子数据和空错误信息。"""
    response = _Response({"code": 0, "data": {"hash-b": {"torrent": []}}})
    helper = IyuuHelper("test-token")
    helper._sid_sha1 = "sid-sha1"

    with patch("app.plugins.iyuuautoseed.iyuu_helper.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = response

        result, message = helper.get_seed_info(["hash-b"])

    assert result == {"hash-b": {"torrent": []}}
    assert message == ""
