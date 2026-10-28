"""TrackerEditor 的下载器参数、逐种子结果、配置和版本边界回归。"""

import builtins
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from packaging.specifiers import SpecifierSet
from packaging.version import Version
import pytest

from app.plugins import trackereditor as module


ROOT = Path(__file__).resolve().parents[3]
OLD = "https://t.hddolby.com/announce.php?passkey=private-test-key"
NEW = "https://www.uhddolby.com/announce.php?passkey=private-test-key"
OTHER = "https://other.example/announce?passkey=unchanged-test-key"


@pytest.fixture
def plugin(monkeypatch):
    """隔离下载器与宿主配置，收集本轮日志和通知。"""
    value = object.__new__(module.TrackerEditor)
    value._downloader_type = "transmission"
    value._host = "localhost"
    value._port = 9091
    value._username = "test-user"
    value._password = "test-password"
    value._tracker_config = "t.hddolby.com|www.uhddolby.com"
    value._onlyonce = True
    value._run_con_enable = False
    value._run_con = ""
    value._notify = True
    value.send_site_message = Mock()
    value.update_config = Mock()
    monkeypatch.setattr(module, "logger", Mock())
    return value


def _transmission_torrent(name, *trackers):
    """模拟客户端已解析的 Tracker 地址列表。"""
    return SimpleNamespace(name=name, hashString=name, tracker_list=list(trackers))


def _connect(monkeypatch, torrents, *, error=False, update_result=True, kind="transmission"):
    """替换下载器创建过程，阻止真实连接或修改任务。"""
    client = Mock()
    client.get_torrents.return_value = torrents, error
    client.update_tracker.return_value = update_result
    constructor = Mock(return_value=client)
    monkeypatch.setattr(module, "Transmission" if kind == "transmission" else "Qbittorrent", constructor)
    return client


def _summary(plugin):
    """读取与日志共用的通知摘要。"""
    return plugin.send_site_message.call_args.args[1]


@pytest.mark.parametrize("host,expected_old,expected_new", [
    ("2.15.6", True, False),
    ("3.0.0", False, True),
    ("3.1.9", False, True),
    ("3.2.0", False, True),
    ("3.2.1", False, True),
])
def test_indexes_keep_installation_available_across_v2_and_v3(host, expected_old, expected_new):
    """V2 选择旧实现，所有正式 V3 均有可安装的新实现，不依赖降级回退。"""
    from app.domain.plugin import is_plugin_generation_compatible

    legacy = json.loads((ROOT / "package.json").read_text())["TrackerEditor"]
    current = json.loads((ROOT / "package.v3.json").read_text())["TrackerEditor"]
    generation = f"v{Version(host).major}"
    old_allowed = is_plugin_generation_compatible(legacy, None, current_generation=generation)
    new_allowed = is_plugin_generation_compatible(current, "v3", current_generation=generation)
    assert legacy["v2"] is True and legacy["v3"] is False
    assert (old_allowed and SpecifierSet(legacy.get("system_version", "")).contains(host)) is expected_old
    assert (new_allowed and SpecifierSet(current["system_version"]).contains(host)) is expected_new
    assert current["version"] == module.TrackerEditor.plugin_version == "2.0"
    assert next(iter(current["history"])) == "v2.0"


def test_plugin_without_detail_page_opens_settings(plugin):
    """无详情页时不得声明 get_page 钩子，避免卡片打开空白详情。"""
    from app.runtime.extensions.plugin.contracts import supports_plugin_hook

    assert not supports_plugin_hook(plugin, "get_page")


def test_transmission_only_writes_changed_torrents(plugin, monkeypatch):
    """前一个任务命中规则，不得导致后续未命中任务被提交。"""
    client = _connect(monkeypatch, [
        _transmission_torrent("changed", OLD, OTHER),
        _transmission_torrent("unchanged", OTHER),
    ])
    plugin.task()
    client.update_tracker.assert_called_once_with(hash_string="changed", tracker_list=[NEW, OTHER])
    client.get_session.assert_not_called()
    assert "扫描 2 个种子，成功 1 个，未变更 1 个，失败 0 个" in _summary(plugin)


@pytest.mark.parametrize("host", ["v3.0.0", "v3.1.9", "v3.2.0", "v3.2.1"])
def test_host_contracts_serialize_complete_tracker_urls(plugin, monkeypatch, host):
    """旧接口代理与真实新 MP 封装均经过真实客户端编码，地址不可被拆成字符。"""
    from app.modules.transmission import Transmission
    from transmission_rpc import Client

    client = object.__new__(Client)
    capture = Mock(return_value={})
    monkeypatch.setattr(client, "_request", capture)
    monkeypatch.setattr(client, "_rpc_version_warning", Mock())
    downloader = object.__new__(Transmission)
    downloader.trc = client
    monkeypatch.setattr(module, "APP_VERSION", host)
    if Version(host) < Version("3.2.0"):
        def legacy_update(hash_string, tracker_list):
            """旧 MP 接口只将调用方准备的分组原样交给客户端。"""
            client.change_torrent(ids=hash_string, tracker_list=tracker_list)
            return True

        monkeypatch.setattr(downloader, "update_tracker", legacy_update)
    monkeypatch.setattr(downloader, "get_torrents", Mock(return_value=(
        [_transmission_torrent("changed", OLD, OTHER)], False,
    )))
    monkeypatch.setattr(module, "Transmission", Mock(return_value=downloader))

    plugin.task()

    capture.assert_called_once()
    payload = capture.call_args.args[1]
    assert payload["trackerList"].split() == [NEW, OTHER]
    assert "成功 1 个" in _summary(plugin)


@pytest.mark.parametrize("host,expected", [
    ("v3.0.0", [[NEW, OTHER]]),
    ("v3.1.9", [[NEW, OTHER]]),
    ("v3.2.0", [NEW, OTHER]),
    ("v3.2.1", [NEW, OTHER]),
])
def test_transmission_payload_matches_host_version(plugin, monkeypatch, host, expected):
    """版本差异集中在参数适配处，其余替换流程保持一致。"""
    monkeypatch.setattr(module, "APP_VERSION", host)
    client = _connect(monkeypatch, [_transmission_torrent("changed", OLD, OTHER)])
    plugin.task()
    client.update_tracker.assert_called_once_with(hash_string="changed", tracker_list=expected)


def test_unrecognized_host_version_does_not_write_trackers(plugin, monkeypatch):
    """无法确定接口格式时明确记失败，不尝试提交可能错误的参数。"""
    monkeypatch.setattr(module, "APP_VERSION", "unknown-build")
    client = _connect(monkeypatch, [_transmission_torrent("changed", OLD)])
    plugin.task()
    client.update_tracker.assert_not_called()
    assert "成功 0 个，未变更 0 个，失败 1 个" in _summary(plugin)


def test_early_v3_can_import_legacy_plugin_base(monkeypatch):
    """MP 3.0.0 尚无新基类 SDK，仍能通过当时的公开入口加载插件。"""
    base = module._PluginBase
    original_import = builtins.__import__

    def without_new_sdk(name, *args, **kwargs):
        """模拟早期 V3 不存在新版 SDK 包，保留其他宿主导入。"""
        if name == "app.sdk.plugin":
            raise ModuleNotFoundError("No module named app.sdk.plugin", name=name)
        return original_import(name, *args, **kwargs)

    try:
        with monkeypatch.context() as context:
            context.setattr(builtins, "__import__", without_new_sdk)
            importlib.reload(module)
            assert issubclass(module.TrackerEditor, base)
    finally:
        importlib.reload(module)


def test_sdk_dependency_failure_is_not_mistaken_for_old_host(monkeypatch):
    """新版 SDK 自身缺少依赖时保留真实错误，不静默退回旧入口。"""
    original_import = builtins.__import__

    def broken_new_sdk(name, *args, **kwargs):
        """只模拟 SDK 内部依赖失败，不模拟整个 SDK 包缺失。"""
        if name == "app.sdk.plugin":
            raise ModuleNotFoundError("missing SDK dependency", name="missing-sdk-dependency")
        return original_import(name, *args, **kwargs)

    try:
        with monkeypatch.context() as context:
            context.setattr(builtins, "__import__", broken_new_sdk)
            with pytest.raises(ModuleNotFoundError, match="missing SDK dependency"):
                importlib.reload(module)
    finally:
        importlib.reload(module)


def test_multiple_trackers_count_as_one_torrent(plugin, monkeypatch):
    """一个种子内修改多个地址，成功种子数只增加一次。"""
    second = OLD.replace("announce.php", "announce2.php")
    client = _connect(monkeypatch, [_transmission_torrent("multi", OLD, second)])
    plugin.task()
    client.update_tracker.assert_called_once_with(
        hash_string="multi", tracker_list=[NEW, second.replace("t.hddolby.com", "www.uhddolby.com")],
    )
    assert "扫描 1 个种子，成功 1 个" in _summary(plugin)


def test_failed_update_keeps_previous_success_and_continues(plugin, monkeypatch):
    """中间一项失败时保留已完成计数，并处理其余独立任务。"""
    client = _connect(monkeypatch, [
        _transmission_torrent("first", OLD),
        _transmission_torrent("failed", OLD),
        _transmission_torrent("last", OLD),
    ])
    client.update_tracker.side_effect = [True, False, True]
    plugin.task()
    assert client.update_tracker.call_count == 3
    assert "扫描 3 个种子，成功 2 个，未变更 0 个，失败 1 个" in _summary(plugin)


def test_query_error_returns_before_reading_session(plugin, monkeypatch):
    """认证失败时不再对空会话调用 get，也不提交修改。"""
    client = _connect(monkeypatch, None, error=True)
    plugin.task()
    client.get_session.assert_not_called()
    client.update_tracker.assert_not_called()
    plugin.send_site_message.assert_not_called()
    assert "用户名和密码" in module.logger.error.call_args.args[0]


def test_connection_exception_is_reported_without_url_secrets(plugin, monkeypatch):
    """异常中的地址和 passkey 不应进入插件日志。"""
    monkeypatch.setattr(module, "Transmission", Mock(side_effect=RuntimeError("connection rejected: " + OLD)))
    plugin.task()
    message = module.logger.error.call_args.args[0]
    assert "连接下载器或读取种子失败" in message
    assert "connection rejected" in message
    assert "private-test-key" not in message


@pytest.mark.parametrize("rules", [None, "", "\n", "|new", "old|", "invalid", "a|b|c"])
def test_empty_or_invalid_rules_do_not_connect(plugin, monkeypatch, rules):
    """没有有效规则时不应连接下载器或清空 Tracker。"""
    constructor = Mock()
    monkeypatch.setattr(module, "Transmission", constructor)
    plugin._tracker_config = rules
    plugin.task()
    constructor.assert_not_called()


def test_noop_replacement_is_skipped(plugin, monkeypatch):
    """替换前后相同的地址不算修改，也不提交请求。"""
    plugin._tracker_config = "t.hddolby.com|t.hddolby.com"
    client = _connect(monkeypatch, [_transmission_torrent("same", OLD)])
    plugin.task()
    client.update_tracker.assert_not_called()
    assert "成功 0 个，未变更 1 个，失败 0 个" in _summary(plugin)


def test_rules_ignore_blank_lines_and_use_first_match(plugin, monkeypatch):
    """配置顺序确定单次替换，不连续套用后续规则。"""
    plugin._tracker_config = "\n t.hddolby.com | www.uhddolby.com \nwww.uhddolby.com|wrong.example\n"
    client = _connect(monkeypatch, [_transmission_torrent("first-rule", OLD)])
    plugin.task()
    assert client.update_tracker.call_args.kwargs["tracker_list"] == [NEW]


def _qb_torrent(name, *trackers):
    """模拟 qBittorrent 的按地址修改入口。"""
    return SimpleNamespace(name=name, trackers=[SimpleNamespace(url=url) for url in trackers], edit_tracker=Mock())


def test_qbittorrent_updates_changed_urls_and_counts_torrents(plugin, monkeypatch):
    """qB 多 Tracker 的修改方式保留，统计统一按种子计数。"""
    plugin._downloader_type = "qbittorrent"
    torrent = _qb_torrent("qb-changed", OLD, OLD.replace("announce.php", "announce2.php"), OTHER)
    untouched = _qb_torrent("qb-unchanged", OTHER)
    _connect(monkeypatch, [torrent, untouched], kind="qbittorrent")
    plugin.task()
    assert torrent.edit_tracker.call_count == 2
    untouched.edit_tracker.assert_not_called()
    assert "成功 1 个，未变更 1 个，失败 0 个" in _summary(plugin)


def test_qbittorrent_failed_edit_is_not_counted_as_success(plugin, monkeypatch):
    """qB 的失败任务与后续成功任务独立统计。"""
    plugin._downloader_type = "qbittorrent"
    failed = _qb_torrent("qb-failed", OLD)
    failed.edit_tracker.side_effect = RuntimeError("request rejected: " + OLD)
    success = _qb_torrent("qb-success", OLD)
    _connect(monkeypatch, [failed, success], kind="qbittorrent")
    plugin.task()
    success.edit_tracker.assert_called_once()
    assert "成功 1 个，未变更 0 个，失败 1 个" in _summary(plugin)
    assert "private-test-key" not in module.logger.error.call_args.args[0]


@pytest.mark.parametrize("legacy_keys", [False, True])
def test_run_once_preserves_schedule_configuration(plugin, monkeypatch, legacy_keys):
    """立即运行后保存规范字段，也能读取旧版错写的定时字段。"""
    monkeypatch.setattr(plugin, "task", Mock())
    config = {
        "onlyonce": True, "downloader_type": "transmission", "host": "localhost", "port": 9091,
        "username": "test-user", "password": "test-password", "tracker_config": "old|new", "notify": True,
        "run_cron_enable" if legacy_keys else "run_con_enable": True,
        "run_cron" if legacy_keys else "run_con": "0 * * * *",
    }
    plugin.init_plugin(config)
    plugin.task.assert_called_once()
    saved = plugin.update_config.call_args.args[0]
    assert saved["onlyonce"] is False
    assert saved["run_con_enable"] is True
    assert saved["run_con"] == "0 * * * *"
    assert "run_cron_enable" not in saved and "run_cron" not in saved
    assert plugin.get_service()[0]["id"] == "TrackerChangeRun"
