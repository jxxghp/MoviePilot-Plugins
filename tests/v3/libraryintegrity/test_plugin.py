"""影视库完整性检查：插件主类配置、页面、接口与扫描生命周期测试。"""

import atexit
import json
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

import app.plugins.libraryintegrity as plugin_module
from app.plugins.libraryintegrity import AdoptRequest, IgnoreRequest, LibraryIntegrity
from app.plugins.libraryintegrity.config import DEFAULT_CONFIG, local_dirs, normalize_config, to_scan_options
from app.plugins.libraryintegrity.models import Issue, IssueType, Report


def _plugin(**config):
    """绕过 __init__ 构造插件并装配运行状态，配置保存只记录在内存。"""
    plugin = object.__new__(LibraryIntegrity)
    plugin._config = normalize_config(config)
    plugin._enabled = plugin._config["enabled"]
    plugin._stop_event = threading.Event()
    plugin._scan_lock = threading.Lock()
    plugin._progress = ""
    plugin.saved_configs = []
    plugin.update_config = lambda conf, plugin_id=None: plugin.saved_configs.append(dict(conf)) or True
    plugin.stored = {}
    plugin.get_data = lambda key=None, plugin_id=None: plugin.stored.get(key)
    plugin.save_data = lambda key, value, plugin_id=None: plugin.stored.__setitem__(key, value)
    plugin.del_data = lambda key, plugin_id=None: plugin.stored.pop(key, None)
    data_dir = Path(tempfile.mkdtemp(prefix="libraryintegrity-"))
    atexit.register(shutil.rmtree, data_dir, True)
    plugin.get_data_path = lambda plugin_id=None: data_dir
    plugin.messages = []
    plugin.post_message = lambda **kwargs: plugin.messages.append(kwargs)
    return plugin


def _put_report(plugin, data):
    """把报告写入插件数据目录中的报告文件。"""
    (plugin.get_data_path() / "report.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_report(plugin):
    """读取插件数据目录中的报告文件，不存在时返回 None。"""
    path = plugin.get_data_path() / "report.json"
    return Report.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def _report(*issues):
    """构造包含指定问题的报告数据。"""
    return Report(finished_at="2026-10-30 03:00:00", issues=list(issues)).model_dump(mode="json")


def _missing_issue():
    """构造一条缺集问题。"""
    return Issue(
        type=IssueType.MISSING, title="剧A", server="Emby", library="电视剧",
        season=1, episodes=[3, 4], summary="第 1 季缺 2 集：E03-E04", scope="tmdb:1:S1",
    )


def _walk(node):
    """遍历页面 JSON 的全部节点。"""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for child in node.get("content") or []:
            yield from _walk(child)


# ---------------- 配置 ----------------

def test_normalize_config_fills_defaults_and_fixes_types():
    """缺省值补齐、未知维度剔除、天数限制在范围内、逗号文本转列表。"""
    config = normalize_config({
        "enabled": 1, "dimensions": ["resolution", "bogus"], "air_buffer_days": "999",
        "libraries": "电视剧，动漫", "cron": "  0 3 * * *  ", "ai_max_calls": "-3",
        "local_dirs": "/a\n# 注释\n\n /b ", "number_mappings": "tmdb:1 S1E13-E24 => S2E1",
        "ai_enabled": True, "ai_summary": True,
    })
    assert config["enabled"] is True
    assert config["dimensions"] == ["resolution"]
    assert config["air_buffer_days"] == 60
    assert config["libraries"] == ["电视剧", "动漫"]
    assert config["cron"] == "0 3 * * *"
    assert config["check_missing"] is True
    assert "ai_max_calls" not in config  # 旧版的调用次数上限已取消，保存的旧值被丢弃
    assert local_dirs(config) == ["/a", "/b"]
    options = to_scan_options(config)
    assert options.air_buffer_days == 60 and options.ai_summary
    assert options.number_mappings["tmdb:1"][0].dst_season == 2


def test_get_form_returns_defaults_and_server_choices(monkeypatch):
    """配置页包含 Emby 服务器选项，默认模型与默认配置一致。"""
    plugin = _plugin()
    monkeypatch.setattr(LibraryIntegrity, "_emby_server_names", lambda self: ["家里的Emby"])
    form, model = plugin.get_form()
    assert model == DEFAULT_CONFIG
    selects = [node for node in _walk(form) if node.get("component") == "VSelect"]
    assert any(node["props"].get("items") == ["家里的Emby"] for node in selects)
    models = {node["props"]["model"] for node in _walk(form) if "model" in (node.get("props") or {})}
    assert set(DEFAULT_CONFIG) <= models


def test_get_service_requires_enabled_and_valid_cron():
    """启用且 cron 有效时注册服务，否则不注册。"""
    assert _plugin(enabled=False, cron="0 3 * * *").get_service() == []
    assert _plugin(enabled=True, cron="").get_service() == []
    assert _plugin(enabled=True, cron="bad cron").get_service() == []
    services = _plugin(enabled=True, cron="0 3 * * 0").get_service()
    assert services[0]["id"] == "LibraryIntegrity.Scan"


# ---------------- 接口 ----------------

def test_api_ignore_appends_typed_rule_once():
    """忽略接口追加类型限定的规则，重复添加不产生重复行，非法输入被拒绝。"""
    plugin = _plugin(ignore_rules="tmdb:9")
    result = plugin.api_ignore(IgnoreRequest(key="tmdb:1:S1", type="missing"))
    assert result.success and result.data.rule == "missing@tmdb:1:S1" and result.data.total == 2
    plugin.api_ignore(IgnoreRequest(key="tmdb:1:S1", type="missing"))
    assert plugin._config["ignore_rules"] == "tmdb:9\nmissing@tmdb:1:S1"
    assert len(plugin.saved_configs) == 1
    assert not plugin.api_ignore(IgnoreRequest(key="", type=None)).success
    assert not plugin.api_ignore(IgnoreRequest(key="tmdb:1", type="bogus")).success
    assert not plugin.api_ignore(IgnoreRequest(key="missing@tmdb:1", type=None)).success


def test_api_scan_states(monkeypatch):
    """未启用、正在扫描与正常排队三种情况。"""
    queued = []
    monkeypatch.setattr(
        plugin_module.scheduler_sdk, "add_plugin_once_job",
        lambda plugin_id, job_id, func, name, delay_seconds=0, func_kwargs=None: queued.append((plugin_id, job_id)) or True,
    )
    assert not _plugin(enabled=False).api_scan().success
    plugin = _plugin(enabled=True)
    plugin._scan_lock.acquire()
    assert plugin.api_scan().message == "已有扫描正在进行"
    plugin._scan_lock.release()
    result = plugin.api_scan()
    assert result.success and result.data.queued
    assert queued == [("LibraryIntegrity", "scan")]


def test_api_report_applies_ignore_rules():
    """报告接口返回完整报告与过滤后的问题。"""
    plugin = _plugin(ignore_rules="missing@tmdb:1:S1E3")
    _put_report(plugin, _report(_missing_issue()))
    result = plugin.api_report()
    assert result.success
    assert result.data.issues[0].episodes == [4]
    assert result.data.ignored == 0
    assert result.data.report.issues[0].episodes == [3, 4]
    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def test_get_api_declares_envelope_models():
    """所有接口都声明 Response 包装模型并要求登录。"""
    routes = _plugin().get_api()
    assert {route["path"] for route in routes} == {"/scan", "/ignore", "/adopt", "/report"}
    assert all(route["auth"] == "bear" and route.get("response_model") for route in routes)


def test_api_routes_work_under_fastapi():
    """按宿主方式注册路由：请求体解析为 IgnoreRequest，响应符合 Response 三段式。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    plugin = _plugin()
    _put_report(plugin, _report(_missing_issue()))
    app = FastAPI()
    for route in plugin.get_api():
        api = dict(route)
        api.pop("auth")
        api["path"] = f"/api/v1/plugin/LibraryIntegrity{api['path']}"
        app.router.add_api_route(**api)
    client = TestClient(app)
    body = client.post("/api/v1/plugin/LibraryIntegrity/ignore", json={"key": "tmdb:1:S1", "type": "missing"}).json()
    assert body == {"success": True, "message": "已忽略：missing@tmdb:1:S1", "data": {"rule": "missing@tmdb:1:S1", "total": 1}}
    report = client.get("/api/v1/plugin/LibraryIntegrity/report").json()
    assert set(report) == {"success", "message", "data"}
    assert report["data"]["issues"] == [] and report["data"]["ignored"] == 1
    scan = client.post("/api/v1/plugin/LibraryIntegrity/scan", json={}).json()
    assert scan["success"] is False and scan["data"] == {"queued": False}
    adopt = client.post(
        "/api/v1/plugin/LibraryIntegrity/adopt", json={"kind": "identity", "rule": "emby:Emby/1 => tmdb:7"}
    ).json()
    assert adopt == {"success": True, "message": "已采纳，下次扫描生效", "data": {"rule": "emby:Emby/1 => tmdb:7", "total": 1}}


# ---------------- 页面 ----------------

def test_get_page_without_report_shows_scan_button():
    """没有报告时显示扫描按钮与提示，按钮走插件 API 而不暴露令牌。"""
    page = _plugin().get_page()
    buttons = [node for node in _walk(page) if node.get("component") == "VBtn"]
    assert buttons[0]["events"]["click"]["api"] == "plugin/LibraryIntegrity/scan"
    assert "apikey" not in json.dumps(page)


def test_get_page_renders_issues_and_ignore_buttons():
    """报告页按类型分组，每条问题带忽略按钮，忽略的数量会提示。"""
    plugin = _plugin(ignore_rules="tmdb:2")
    unchecked = Issue(type=IssueType.UNCHECKED, title="剧B", summary="缺少 TMDB ID，无法核对缺集", scope="tmdb:2")
    _put_report(plugin, _report(_missing_issue(), unchecked))
    page = plugin.get_page()
    titles = [node for node in _walk(page) if node.get("component") == "VExpansionPanelTitle"]
    assert len(titles) == 1
    ignore_buttons = [n for n in _walk(page) if n.get("component") == "VBtn" and n.get("text") == "忽略"]
    assert ignore_buttons[0]["events"]["click"]["params"] == {"key": "tmdb:1:S1", "type": "missing"}
    assert any("已按忽略规则隐藏 1 条" in str(node.get("text")) for node in _walk(page))


# ---------------- 扫描生命周期 ----------------

class _EmptyReader:
    """没有任何媒体库的读取器替身。"""

    name = "Emby"

    def libraries(self):
        """返回空媒体库列表。"""
        return []


@pytest.fixture
def scan_plugin(tmp_path, monkeypatch):
    """准备可执行扫描的插件：替换 Emby 服务与数据目录。"""
    plugin = _plugin(enabled=True, check_missing=False, read_nfo=False)
    plugin.get_data_path = lambda plugin_id=None: tmp_path
    monkeypatch.setattr(LibraryIntegrity, "_build_readers", lambda self: ([_EmptyReader()], ["Emby 服务器 备用 未连接"]))
    return plugin


def test_run_scan_saves_report_and_notifies(scan_plugin):
    """扫描完成后保存报告、发送通知并释放锁。"""
    scan_plugin.run_scan()
    report = _read_report(scan_plugin)
    assert "report" not in scan_plugin.stored  # 报告写入数据目录文件，不再写插件数据表
    assert report.errors == ["Emby 服务器 备用 未连接", "Emby 没有匹配的影视媒体库"]
    assert scan_plugin.messages and "扫描错误：2 个" in scan_plugin.messages[0]["text"]
    assert not scan_plugin._scan_lock.locked()
    assert scan_plugin._progress == ""


def test_run_scan_cancelled_keeps_previous_report(scan_plugin):
    """被停止的扫描不覆盖已有报告，也不发送通知。"""
    _put_report(scan_plugin, _report(_missing_issue()))
    scan_plugin._stop_event.set()
    scan_plugin.run_scan()
    assert _read_report(scan_plugin).issues[0].type == IssueType.MISSING
    assert scan_plugin.messages == []


def test_run_scan_skips_when_already_running(scan_plugin):
    """同一实例已有扫描时跳过新的触发。"""
    scan_plugin._scan_lock.acquire()
    scan_plugin.run_scan()
    assert _read_report(scan_plugin) is None
    scan_plugin._scan_lock.release()


def test_real_instance_lifecycle_and_storage(monkeypatch):
    """经正常构造走完整生命周期：初始化时把旧版存在插件数据表中的报告迁移到数据目录文件。"""
    monkeypatch.setattr(LibraryIntegrity, "_emby_server_names", lambda self: [])
    plugin = LibraryIntegrity()
    assert plugin._config == DEFAULT_CONFIG and plugin._config is not DEFAULT_CONFIG
    plugin._report_path().unlink(missing_ok=True)
    plugin.save_data("report", _report(_missing_issue()))
    plugin.init_plugin({"enabled": True, "cron": "0 3 * * 0"})
    assert plugin.get_data("report") is None
    assert plugin._report_path().exists()
    assert plugin.get_state()
    assert plugin.get_service()[0]["name"] == "影视库完整性检查"
    plugin.get_form()
    page = plugin.get_page()
    assert any(node.get("text") == "缺集" for node in _walk(page))
    plugin.stop_service()
    plugin.init_plugin({"enabled": False})
    assert not plugin.get_state() and plugin.get_service() == []
    plugin._report_path().unlink()


def test_legacy_report_migration_keeps_existing_file_and_tolerates_bad_data():
    """已有报告文件时不覆盖，只删除旧数据；旧数据损坏时不影响启动。"""
    plugin = _plugin()
    _put_report(plugin, _report())
    plugin.stored["report"] = _report(_missing_issue())
    plugin._migrate_legacy_report()
    assert _read_report(plugin).issues == [] and "report" not in plugin.stored
    other = _plugin()
    other.stored["report"] = {"issues": "坏数据"}
    other._migrate_legacy_report()
    assert _read_report(other) is None
    (other.get_data_path() / "report.json").write_text("{坏", encoding="utf-8")
    assert other._load_report() is None


def test_stop_service_sets_stop_event(monkeypatch):
    """停止服务时通知扫描结束并取消一次性任务。"""
    removed = []
    monkeypatch.setattr(plugin_module.scheduler_sdk, "remove_plugin_once_job", lambda pid, jid: removed.append((pid, jid)))
    plugin = _plugin()
    plugin.stop_service()
    assert plugin._stop_event.is_set()
    assert removed == [("LibraryIntegrity", "scan")]


# ---------------- 二期：采纳、智能助手 ----------------

def test_api_adopt_writes_valid_rules_once():
    """采纳映射与身份建议写入对应规则，重复采纳不重复写入，格式错误被拒绝。"""
    plugin = _plugin()
    result = plugin.api_adopt(AdoptRequest(kind="mapping", rule="tmdb:5 S1E3-E4 => S2E1\ntmdb:5 S1E5 => S3E1"))
    assert result.success and result.data.total == 2
    plugin.api_adopt(AdoptRequest(kind="mapping", rule="tmdb:5 S1E3-E4 => S2E1"))
    assert plugin._config["number_mappings"].count("S1E3-E4") == 1
    result = plugin.api_adopt(AdoptRequest(kind="identity", rule="local:/media/剧 名 => tmdb:7"))
    assert result.success and plugin._config["identity_overrides"] == "local:/media/剧 名 => tmdb:7"
    assert not plugin.api_adopt(AdoptRequest(kind="mapping", rule="乱写")).success
    assert not plugin.api_adopt(AdoptRequest(kind="other", rule="x")).success
    assert len(plugin.saved_configs) == 2


def test_page_shows_adopt_button_and_ai_summary():
    """AI 建议显示采纳按钮，报告页显示 AI 摘要。"""
    plugin = _plugin()
    suggestion = Issue(
        type=IssueType.SUGGESTION, title="剧E", summary="AI 建议", scope="tmdb:5",
        adopt_kind="mapping", adopt_rule="tmdb:5 S1E3-E4 => S2E1",
    )
    data = Report(finished_at="t", issues=[suggestion], ai_summary="建议：\n1. **先处理剧E**：对齐编号").model_dump(mode="json")
    _put_report(plugin, data)
    page = plugin.get_page()
    adopt = [n for n in _walk(page) if n.get("component") == "VBtn" and n.get("text") == "采纳"]
    assert adopt[0]["events"]["click"] == {
        "api": "plugin/LibraryIntegrity/adopt", "method": "post",
        "params": {"kind": "mapping", "rule": "tmdb:5 S1E3-E4 => S2E1"},
    }
    alert = next(n for n in _walk(page) if (n.get("props") or {}).get("title") == "AI 摘要")
    rows = alert["content"]
    assert [row["component"] for row in rows] == ["div", "div"]
    assert rows[1]["content"] == [
        {"component": "span", "text": "1. "},
        {"component": "span", "props": {"class": "font-weight-bold"}, "text": "先处理剧E"},
        {"component": "span", "text": "：对齐编号"},
    ]
    assert "**" not in json.dumps(page, ensure_ascii=False)


@pytest.mark.asyncio
async def test_async_query_text_filters_report():
    """智能助手查询按类型与关键词筛选，并应用忽略规则。"""
    plugin = _plugin(ignore_rules="tmdb:2")
    unchecked = Issue(type=IssueType.UNCHECKED, title="剧B", summary="缺少 TMDB ID", scope="tmdb:2")
    assert "还没有可用的影视库完整性报告" in await plugin.async_query_text()
    _put_report(plugin, _report(_missing_issue(), unchecked))
    text = await plugin.async_query_text()
    assert "共 1 条匹配问题（已忽略 1 条）" in text and "[缺集] 剧A" in text
    assert "共 0 条" in await plugin.async_query_text(keyword="不存在")
    assert "不支持的问题类型" in await plugin.async_query_text(issue_type="bogus")


def test_agent_tool_queries_running_plugin(monkeypatch):
    """启用时注册只读工具；工具通过插件管理器找到运行中的实例。"""
    import asyncio

    from app.sdk.plugin import PluginManager

    plugin = _plugin(enabled=True)

    async def fake_query(issue_type=None, keyword=None, limit=20):
        """记录查询参数。"""
        return f"{issue_type}|{keyword}|{limit}"

    plugin.async_query_text = fake_query
    assert _plugin(enabled=False).get_agent_tools() == []
    tools = plugin.get_agent_tools()
    assert len(tools) == 1
    tool_cls = tools[0]
    assert tool_cls.model_fields["name"].default == "query_library_integrity"
    monkeypatch.setattr(PluginManager, "running_plugins", property(lambda self: {"LibraryIntegrity": plugin}))
    tool = object.__new__(tool_cls)
    assert asyncio.run(tool.run(issue_type="missing", keyword="剧", limit=5)) == "missing|剧|5"
    monkeypatch.setattr(PluginManager, "running_plugins", property(lambda self: {}))
    assert asyncio.run(tool.run()) == "影视库完整性检查插件未运行"


def test_build_sources_and_advisor(tmp_path, monkeypatch):
    """关闭 Emby 只填本地目录时只有本地数据源；系统未启用智能助手时不创建 AI 顾问并提示。"""
    plugin = _plugin(use_emby=False, local_dirs=str(tmp_path), ai_enabled=True)
    sources, errors = plugin._build_sources(threading.Event(), None)
    assert [source.name for source in sources] == ["本地目录"] and errors == []
    plugin = _plugin(use_emby=False)
    assert plugin._build_sources(threading.Event(), None)[1] == ["没有可扫描的数据源：请启用 Emby 或填写本地扫描目录"]

    monkeypatch.setattr(plugin_module, "ai_available", lambda: False)
    errors = []
    assert _plugin(ai_enabled=True)._build_advisor(errors) is None
    assert "系统未启用智能助手" in errors[0]
    monkeypatch.setattr(plugin_module, "ai_available", lambda: True)
    assert _plugin(ai_enabled=True)._build_advisor([]).max_calls is None
    assert _plugin(ai_enabled=False)._build_advisor([]) is None


def test_build_probe_requires_local_dirs_and_binary(tmp_path, monkeypatch):
    """只有启用本地媒体信息、填写了目录且找到工具时才创建读取器。"""
    plugin = _plugin(local_probe=True, local_dirs=str(tmp_path))
    plugin.get_data_path = lambda plugin_id=None: tmp_path
    monkeypatch.setattr(plugin_module, "find_probe_binary", lambda configured="": ("", ""))
    assert plugin._build_probe() is None
    monkeypatch.setattr(plugin_module, "find_probe_binary", lambda configured="": ("ffprobe", "/usr/bin/ffprobe"))
    assert plugin._build_probe() is not None
    assert _plugin(local_probe=True)._build_probe() is None


def test_rich_text_and_plain_text_for_ai_summary():
    """AI 摘要：页面逐行展示并把 **加粗** 转为粗体、去掉标题符号；通知去掉标记但保留换行。"""
    from app.plugins.libraryintegrity.page import build_summary_text, plain_text, rich_text_lines

    text = "## 建议处理顺序\n\n1. **修正编号**：先处理《法证先锋》\n2. 清理**重复**文件"
    rows = rich_text_lines(text)
    assert len(rows) == 3
    assert rows[0]["content"] == [{"component": "span", "text": "建议处理顺序"}]
    assert [part.get("props") for part in rows[2]["content"]] == [None, {"class": "font-weight-bold"}, None]
    assert plain_text(text) == "建议处理顺序\n1. 修正编号：先处理《法证先锋》\n2. 清理重复文件"
    summary = build_summary_text(Report(ai_summary=text), [], 0)
    assert "**" not in summary and "AI 摘要：\n建议处理顺序\n1. 修正编号" in summary

