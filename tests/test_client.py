import requests

from p115offlinedownloader.client import P115HelperClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("bad json")
        return self.payload


class FakeSession:
    def __init__(self, post=None, get=None):
        self.post_result = post
        self.get_result = get
        self.post_call = None
        self.get_call = None
        self.closed = False

    def post(self, url, **kwargs):
        self.post_call = (url, kwargs)
        if isinstance(self.post_result, Exception):
            raise self.post_result
        return self.post_result

    def get(self, url, **kwargs):
        self.get_call = (url, kwargs)
        if isinstance(self.get_result, Exception):
            raise self.get_result
        return self.get_result

    def close(self):
        self.closed = True


def client(session, token="token", url="http://moviepilot/api/v1/plugin/P115StrmHelper"):
    return P115HelperClient(url, token, timeout=7, verify_ssl=False, session=session)


def test_submit_success_and_payload_shape():
    session = FakeSession(post=FakeResponse(payload={"code": 0, "msg": "已添加"}))
    result = client(session).add_offline_task("magnet:?xt=urn:btih:test")
    assert result.success is True
    assert result.message == "已添加"
    _, kwargs = session.post_call
    assert kwargs["json"] == {
        "links": ["magnet:?xt=urn:btih:test"],
        "path": "",
    }
    assert kwargs["timeout"] == 7
    assert kwargs["verify"] is False


def test_submit_business_and_http_failures():
    business = FakeSession(post=FakeResponse(payload={"code": -1, "msg": "额度不足"}))
    assert client(business).add_offline_task("magnet:test").message == "额度不足"
    for status, expected in [(401, "Token"), (403, "Token"), (404, "接口不存在"), (500, "服务异常")]:
        session = FakeSession(post=FakeResponse(status_code=status))
        result = client(session).add_offline_task("magnet:test")
        assert result.success is False
        assert expected in result.message


def test_upstream_message_cannot_echo_full_magnet():
    full_magnet = "magnet:?xt=urn:btih:abc&tr=https://tracker/?token=secret"
    session = FakeSession(
        post=FakeResponse(payload={"code": -1, "msg": f"添加失败 {full_magnet}"})
    )
    message = client(session).add_offline_task(full_magnet).message
    assert full_magnet not in message
    assert "token=secret" not in message
    assert "magnet已脱敏" in message


def test_submit_transport_and_response_failures():
    cases = [
        (requests.Timeout(), "超时"),
        (requests.ConnectionError(), "无法连接"),
        (requests.RequestException(), "请求"),
    ]
    for exception, expected in cases:
        result = client(FakeSession(post=exception)).add_offline_task("magnet:test")
        assert expected in result.message
    result = client(FakeSession(post=FakeResponse(json_error=True))).add_offline_task("magnet:test")
    assert "非JSON" in result.message


def test_configuration_validation():
    session = FakeSession()
    assert "地址为空" in client(session, url="").add_offline_task("x").message
    assert "格式无效" in client(session, url="localhost:3001").add_offline_task("x").message
    assert "Token为空" in client(session, token="").add_offline_task("x").message


def test_connection_statuses():
    ok = FakeSession(get=FakeResponse(payload={"code": 0, "data": {"enabled": True, "has_client": True}}))
    assert client(ok).test_connection().success is True

    disabled = FakeSession(get=FakeResponse(payload={"code": 0, "data": {"enabled": False, "has_client": True}}))
    assert "未启用" in client(disabled).test_connection().message

    no_client = FakeSession(get=FakeResponse(payload={"code": 0, "data": {"enabled": True, "has_client": False}}))
    assert "未初始化" in client(no_client).test_connection().message

    missing_data = FakeSession(get=FakeResponse(payload={"code": 0}))
    assert "缺少data" in client(missing_data).test_connection().message

    failed = FakeSession(get=FakeResponse(payload={"code": 1, "msg": "状态失败"}))
    assert client(failed).test_connection().message == "状态失败"
