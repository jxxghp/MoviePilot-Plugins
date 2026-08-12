"""HDHiveBrowserService 纯函数测试（无需 pytest，直接 python3 运行）。

绕开 AgentResourceOfficer 包（其 __init__.py 依赖 MoviePilot app.*），
桩掉 app.helper.browser / app.log 后直接加载 services/hdhive_browser.py。
"""
import os
import sys
import types

for _name in ("app", "app.helper", "app.helper.browser", "app.log"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["app.helper.browser"].PlaywrightHelper = object  # type: ignore[attr-defined]
sys.modules["app.log"].logger = types.SimpleNamespace(  # type: ignore[attr-defined]
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services"))
import hdhive_browser  # noqa: E402

HDHiveBrowserService = hdhive_browser.HDHiveBrowserService


def test_detail_url_movie_and_tv():
    svc = HDHiveBrowserService(base_url="https://hdhive.com/", cookie="token=abc")
    assert svc._detail_url("movie", 123) == "https://hdhive.com/tmdb/movie/123"
    assert svc._detail_url("电影", 123) == "https://hdhive.com/tmdb/movie/123"
    assert svc._detail_url("tv", 9) == "https://hdhive.com/tmdb/tv/9"
    assert svc._detail_url("电视剧", 9) == "https://hdhive.com/tmdb/tv/9"


def test_is_ready_requires_cookie():
    assert HDHiveBrowserService(cookie="token=abc").is_ready() is True
    assert HDHiveBrowserService(cookie="").is_ready() is False


def test_normalize_extracts_slug_from_href():
    svc = HDHiveBrowserService(cookie="token=abc")
    raw = {
        "href": "/resource/115/abc-uuid-123/",
        "title": "电影标题",
        "resolution": "1080P",
        "size": "10 GB",
        "is_free": False,
        "unlock_points": 20,
        "user": "u",
        "posted_at": "2026/01/01",
        "tags": ["官组"],
    }
    out = svc._normalize(raw)
    assert out["slug"] == "abc-uuid-123"
    assert out["unlock_points"] == 20
    assert out["title"] == "电影标题"


if __name__ == "__main__":
    test_detail_url_movie_and_tv()
    test_is_ready_requires_cookie()
    test_normalize_extracts_slug_from_href()
    print("ALL PASS")
