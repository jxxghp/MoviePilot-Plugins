"""BrushFlow 间接种子下载地址解析测试。"""

import base64
import json
from unittest.mock import MagicMock, patch

from brushflow import BrushFlow


def _build_indirect_url(config: dict, request_url: str) -> str:
    """将请求配置编码为 MoviePilot 间接下载链接。"""
    encoded = base64.b64encode(json.dumps(config).encode("utf-8")).decode("ascii")
    return f"[{encoded}]{request_url}"


def test_redirect_url_builds_yemapt_download_url_from_token():
    """YemaPT 返回 token 时应组装出可下载种子的完整 URL。"""
    config = {
        "method": "post",
        "cookie": False,
        "params": {"id": 123},
        "success": "success",
        "result": "data",
        "result_base_url": "https://www.yemapt.org/",
        "result_path": "/api/torrent/download1",
        "result_query_param": "token",
    }
    indirect_url = _build_indirect_url(
        config,
        "https://www.yemapt.org/openApi/torrent/generateDownloadKey.json",
    )
    response = MagicMock()
    response.json.return_value = {"success": True, "data": "token/with=symbols"}

    with patch("brushflow.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = response
        result = getattr(BrushFlow, "_BrushFlow__get_redict_url")(indirect_url)

    assert result == (
        "https://www.yemapt.org/api/torrent/download1?"
        "token=token%2Fwith%3Dsymbols"
    )
    request_utils.return_value.post_res.assert_called_once_with(
        "https://www.yemapt.org/openApi/torrent/generateDownloadKey.json",
        params={"id": 123},
    )


def test_redirect_url_rejects_unsuccessful_token_response():
    """站点显式返回失败状态时不应继续构造种子下载 URL。"""
    config = {
        "method": "post",
        "cookie": False,
        "success": "success",
        "result": "data",
        "result_base_url": "https://www.yemapt.org",
        "result_path": "api/torrent/download1",
        "result_query_param": "token",
    }
    indirect_url = _build_indirect_url(config, "https://www.yemapt.org/token")
    response = MagicMock()
    response.json.return_value = {"success": False, "data": "invalid-token"}

    with patch("brushflow.RequestUtils") as request_utils:
        request_utils.return_value.post_res.return_value = response
        result = getattr(BrushFlow, "_BrushFlow__get_redict_url")(indirect_url)

    assert result is None
