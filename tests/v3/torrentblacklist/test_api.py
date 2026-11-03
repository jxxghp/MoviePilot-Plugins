"""真实动态路由、JWT 解码与管理员身份查询。"""

from uuid import uuid4

import pytest

from app.db.oper.downloadhistory import DownloadHistoryOper
from app.db.oper.site import SiteOper


def history(title="Film", site="测试站", torrent_name="Film.2026.1080p"):
    download_hash = uuid4().hex
    DownloadHistoryOper().add(type="电影", title=title, torrent_name=torrent_name, torrent_site=site,
                              download_hash=download_hash, path="/private/path",
                              note="private note", date="2026-01-01 00:00:00")
    return DownloadHistoryOper().get_by_hash(download_hash)


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/rules", None), ("POST", "/rules", {"kind": "site", "site_id": 1}),
    ("DELETE", "/rules/" + "0" * 64, None), ("GET", "/history", None),
    ("POST", "/history/1/block", None), ("GET", "/sites", None),
])
def test_all_custom_routes_require_active_admin(api_client, method, path, payload):
    client, base, users, _ = api_client
    kwargs = {"json": payload} if payload is not None else {}
    assert client.request(method, base + path, **kwargs).status_code == 401
    assert client.request(method, base + path, headers=users["normal"], **kwargs).status_code == 403
    for label in ("inactive", "missing"):
        assert client.request(method, base + path, headers=users[label], **kwargs).status_code == 401


def test_rules_response_models_pagination_dedupe_and_delete(api_client):
    client, base, users, app = api_client
    headers = users["admin"]
    assert len([route for route in app.routes if getattr(route, "path", "").startswith(base)]) == 6
    empty = client.get(base + "/rules", headers=headers).json()
    assert set(empty) == {"success", "message", "data"}
    assert empty["success"] and empty["data"]["rules"] == [] and empty["data"]["revision"] == 0
    created = client.post(base + "/rules", headers=headers,
                          json={"kind": "keyword", "keyword": "CAM"}).json()["data"]
    duplicate = client.post(base + "/rules", headers=headers,
                            json={"kind": "keyword", "keyword": "cam"}).json()["data"]
    assert created["created"] and not duplicate["created"]
    assert created["rule"]["id"] == duplicate["rule"]["id"] and duplicate["revision"] == 1
    client.post(base + "/rules", headers=headers, json={"kind": "site", "site_id": 7})
    page = client.get(base + "/rules?page=2&page_size=1", headers=headers).json()["data"]
    assert page["total"] == 2 and len(page["rules"]) == 1 and page["revision"] == 2
    rule_id = created["rule"]["id"]
    assert client.delete(base + "/rules/" + rule_id, headers=headers).json()["data"]["deleted"]
    again = client.delete(base + "/rules/" + rule_id, headers=headers).json()["data"]
    assert not again["deleted"] and again["revision"] == 3


@pytest.mark.parametrize("payload", [
    {"kind": "publisher", "publisher": "x"}, {"kind": "site", "site_id": True},
    {"kind": "keyword", "keyword": ""}, {"kind": "keyword", "keyword": "a" * 257},
    {"kind": "site_title", "site_name": "fake", "title": "fake"},
    {"kind": "site", "site_id": 1, "extra": "no"},
])
def test_invalid_or_client_forged_rules_return_422(api_client, payload):
    client, base, users, _ = api_client
    assert client.post(base + "/rules", headers=users["admin"], json=payload).status_code == 422


@pytest.mark.parametrize("path", ["/rules?page=0", "/rules?page_size=101",
                                 "/history?page=0", "/history?page_size=101",
                                 "/history?search=" + "a" * 257, "/rules/not-a-rule-id"])
def test_bounded_queries_and_ids(api_client, path):
    client, base, users, _ = api_client
    method = "DELETE" if path == "/rules/not-a-rule-id" else "GET"
    assert client.request(method, base + path, headers=users["admin"]).status_code == 422


def test_history_rule_uses_server_facts_and_survives_history_deletion(api_client, plugin):
    client, base, users, _ = api_client
    headers = users["admin"]
    record = history()
    response = client.post(f"{base}/history/{record.id}/block", headers=headers)
    assert response.status_code == 200
    rule = response.json()["data"]["rule"]
    assert (rule["kind"], rule["site_name"], rule["title"]) == ("site_title", "测试站", "Film.2026.1080p")
    assert "private" not in response.text
    repeated = client.post(f"{base}/history/{record.id}/block", headers=headers).json()["data"]
    assert not repeated["created"] and repeated["rule"]["id"] == rule["id"]
    listing = client.get(base + "/history?search=Film", headers=headers).json()["data"]
    row = next(row for row in listing["items"] if row["id"] == record.id)
    assert row["blocked"] is True and row["can_block"] is True
    assert set(row) == {"id", "title", "torrent_name", "torrent_site", "date",
                        "can_block", "blocked", "unavailable_reason"}
    DownloadHistoryOper().delete_history(record.id)
    plugin.init_plugin({"enabled": True})
    assert plugin._store.read().entries[0].id == rule["id"]


def test_history_missing_facts_and_forbidden_body(api_client):
    client, base, users, _ = api_client
    headers = users["admin"]
    assert client.post(base + "/history/2147483647/block", headers=headers).status_code == 404
    record = history(site="")
    assert client.post(f"{base}/history/{record.id}/block", headers=headers).status_code == 409
    record = history()
    assert client.post(f"{base}/history/{record.id}/block", headers=headers,
                       json={"site_name": "fake", "title": "fake"}).status_code == 422
    DownloadHistoryOper().delete_history(record.id)


def test_sites_exposes_only_id_and_name(api_client):
    client, base, users, _ = api_client
    domain = f"https://{uuid4().hex}.invalid"
    assert SiteOper().add(name="测试站", domain=domain, url=domain, cookie="private-cookie")[0]
    response = client.get(base + "/sites", headers=users["admin"])
    assert response.status_code == 200 and "private-cookie" not in response.text
    sites = response.json()["data"]["sites"]
    assert sites and all(set(site) == {"id", "name"} for site in sites)
    for site in SiteOper().list():
        if site.domain == domain:
            SiteOper().delete(site.id)


def test_storage_failure_is_explicit_and_keeps_previous_rules(api_client, plugin, monkeypatch):
    client, base, users, _ = api_client
    headers = users["admin"]
    client.post(base + "/rules", headers=headers, json={"kind": "site", "site_id": 1})
    previous = plugin.get_data("rules")

    def fail(*_args):
        raise OSError("private-storage-path")

    monkeypatch.setattr(plugin, "save_data", fail)
    response = client.post(base + "/rules", headers=headers, json={"kind": "site", "site_id": 2})
    assert response.status_code == 503
    assert "private-storage-path" not in response.text
    assert plugin.get_data("rules") == previous
    assert len(plugin._store.snapshot()[0].entries) == 1


def test_history_search_is_literal_title_or_path_and_pagination_is_stable(api_client):
    client, base, users, _ = api_client
    headers = users["admin"]
    marker = f"search-{uuid4().hex}%_"
    records = [history(title=marker) for _ in range(3)]
    outside = history(title="outside", torrent_name=marker)
    try:
        first = client.get(base + "/history", headers=headers,
                           params={"search": marker, "page_size": 2}).json()["data"]
        second = client.get(base + "/history", headers=headers,
                            params={"search": marker, "page_size": 2, "page": 2}).json()["data"]
        assert first["total"] == second["total"] == 3
        assert [row["id"] for row in first["items"] + second["items"]] == [r.id for r in reversed(records)]
        by_path = client.get(base + "/history", headers=headers,
                             params={"search": "/private/path"}).json()["data"]
        assert outside.id in {row["id"] for row in by_path["items"]}
        assert all("path" not in row for row in by_path["items"])
    finally:
        for record in [*records, outside]:
            DownloadHistoryOper().delete_history(record.id)


def test_corrupt_stored_rules_are_reported_without_overwriting(api_client, plugin):
    client, base, users, _ = api_client
    plugin.save_data("rules", None)
    for method, path, body in [("GET", "/rules", None), ("GET", "/history", None),
                                ("POST", "/rules", {"kind": "site", "site_id": 1}),
                                ("DELETE", "/rules/" + "0" * 64, None)]:
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method, base + path, headers=users["admin"], **kwargs)
        assert response.status_code == 503 and "规则数据无法读取" in response.text
        assert plugin.get_data()[0].value is None
