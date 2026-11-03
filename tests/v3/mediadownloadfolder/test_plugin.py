"""通过生产插件模块与真实事件合同验证下载前作品目录。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.plugins.mediadownloadfolder import MediaDownloadFolder
from app.plugins.mediadownloadfolder.paths import directory_reference, parse_reference
from app.schemas.event import ResourceDownloadEventData
from app.schemas.system import TransferDirectoryConf
from app.schemas.types import MediaType, SystemConfigKey
from app.sdk.media import Context, MediaInfo, MetaInfo, TorrentInfo


@pytest.fixture(autouse=True)
def host_configuration(monkeypatch):
    """为真实解析器提供只读空系统配置，结束时恢复原提供方。"""
    from app.application import configuration

    service = SimpleNamespace(get=lambda _key: None)
    monkeypatch.setattr(configuration, "_configured_system_config", service)
    return service


@pytest.fixture
def directory():
    """两种媒体共用一个真实形状的下载配置。"""
    return TransferDirectoryConf(name="影视下载", storage="local", download_path="/downloads")


@pytest.fixture
def plugin(directory):
    """保留真实基类初始化，替换只读配置边界。"""
    instance = MediaDownloadFolder()
    instance.systemconfig = MagicMock()
    instance.systemconfig.get.return_value = [directory.model_dump()]
    instance.chain = SimpleNamespace(runtime_config=SimpleNamespace(
        rename_format=lambda media_type: "{{title}} ({{year}})/Season {{season}}/file.mkv",
    ))
    instance.init_plugin({
        "enabled": True,
        "movie_root": directory_reference(directory),
        "tv_root": directory_reference(directory),
    })
    return instance


def event(media_type=MediaType.MOVIE, save_path=None, title="示例", version="1080p", **kwargs):
    """构造下载链实际传递的数据，而非插件自定义事件替身。"""
    media = MediaInfo(type=media_type, title=title, year="2026", tmdb_id=123)
    context = Context(
        meta_info=MetaInfo(f"Example.2026.{version}"),
        media_info=media,
        torrent_info=TorrentInfo(title=f"Example.2026.{version}"),
    )
    return SimpleNamespace(event_data=ResourceDownloadEventData(
        context=context, options={"save_path": save_path, "userid": "admin"},
        downloader="qb", origin="Subscribe", **kwargs,
    ))


@pytest.mark.parametrize("media_type", [MediaType.MOVIE, MediaType.TV])
def test_same_work_download_versions_share_folder(plugin, media_type):
    """不同版本下载前就归入相同作品目录。"""
    for version in ("1080p", "2160p"):
        item = event(media_type=media_type, version=version)
        context = item.event_data.context
        plugin.on_resource_download(item)
        assert item.event_data.options == {"save_path": "/downloads/示例 (2026)", "userid": "admin"}
        assert item.event_data.context is context
        assert item.event_data.downloader == "qb"
        assert item.event_data.origin == "Subscribe"
        assert item.event_data.cancel is False


@pytest.mark.parametrize("condition,should_cancel", [
    ("title is sameas(en_title)", True),
    ("title is equalto(en_title)", False),
])
def test_equal_host_work_facts_do_not_depend_on_string_identity(plugin, condition, should_cancel):
    """真实宿主命名事实值相同，即使字符串对象身份不同也不能产生不同归组。"""
    from app.modules.filemanager.transhandler import TransHandler

    title = "Example Naming Identity"
    items = [event(title=title), event(title=title)]
    items[0].event_data.context.media_info.en_title = title
    items[1].event_data.context.media_info.en_title = title.encode().decode()
    facts = [
        TransHandler.get_naming_dict(MetaInfo(""), item.event_data.context.media_info)
        for item in items
    ]
    fields = ("title", "en_title", "year", "tmdbid")
    assert {key: facts[0][key] for key in fields} == {key: facts[1][key] for key in fields}
    assert facts[0]["title"] is facts[0]["en_title"]
    assert facts[1]["title"] is not facts[1]["en_title"]
    plugin.chain.runtime_config.rename_format = lambda _: (
        "{{title}} {% if " + condition + " %}A{% else %}B{% endif %}/file.mkv"
    )
    for item in items:
        plugin.on_resource_download(item)
    results = [(item.event_data.cancel, item.event_data.options["save_path"]) for item in items]
    if should_cancel:
        assert results == [(True, None), (True, None)]
        for item in items:
            assert "作品目录" in item.event_data.reason
    else:
        assert results == [(False, f"/downloads/{title} A")] * 2


def test_disabled_and_unconfigured_types_keep_original_path(plugin):
    """默认关闭，独立类型未配置时不接管路径。"""
    for config in ({}, {"enabled": False}, {"enabled": True}):
        plugin.init_plugin(config)
        item = event()
        plugin.on_resource_download(item)
        assert item.event_data.options["save_path"] is None
        assert item.event_data.cancel is False


@pytest.mark.parametrize("save_path", ["/other", "/downloads/custom", "影视下载"])
def test_explicit_other_directory_subdirectory_or_alias_is_preserved(plugin, save_path):
    """仅未指定路径或精确选中根目录属于插件作用范围。"""
    item = event(save_path=save_path)
    plugin.on_resource_download(item)
    assert item.event_data.options["save_path"] == save_path
    assert item.event_data.cancel is False


def test_exact_root_and_repeated_event_are_idempotent(plugin):
    """同一事件再分发时不会反复追加作品目录。"""
    item = event(save_path="/downloads")
    plugin.on_resource_download(item)
    plugin.on_resource_download(item)
    assert item.event_data.options["save_path"] == "/downloads/示例 (2026)"


def test_existing_cancellation_is_not_overwritten(plugin):
    """不覆盖其它插件的取消原因，也不改路径。"""
    item = event(cancel=True, source="前置插件", reason="已屏蔽")
    before = item.event_data.model_dump()
    plugin.on_resource_download(item)
    assert item.event_data.model_dump() == before


@pytest.mark.parametrize("change", [
    {}, {"name": "改名"}, {"download_path": "/moved"}, {"storage": "rclone"},
])
@pytest.mark.parametrize("save_path", [None, "/downloads"])
def test_deleted_or_changed_root_does_not_silently_substitute(plugin, directory, change, save_path):
    """失效引用在默认请求和原根请求中都必须明确失败。"""
    plugin.systemconfig.get.return_value = [directory.model_copy(update=change).model_dump()] if change else []
    item = event(save_path=save_path)
    plugin.on_resource_download(item)
    assert item.event_data.cancel is True
    assert "目录" in item.event_data.reason
    assert item.event_data.options["save_path"] == save_path


def test_unsafe_template_cancels_before_submission(plugin):
    """非法模板不会静默退回根目录下载。"""
    plugin.chain.runtime_config.rename_format = lambda _: "{{title}}-{{videoFormat}}/file.mkv"
    item = event()
    plugin.on_resource_download(item)
    assert item.event_data.cancel is True
    assert "作品目录" in item.event_data.reason
    assert item.event_data.options["save_path"] is None


@pytest.mark.parametrize("media_type,title", [(MediaType.UNKNOWN, "示例"), (MediaType.MOVIE, "")])
def test_unrecognized_media_keeps_host_behavior(plugin, media_type, title):
    """缺少识别作品事实时不伪造目录。"""
    item = event(media_type=media_type, title=title)
    plugin.on_resource_download(item)
    assert item.event_data.cancel is False
    assert item.event_data.options["save_path"] is None


@pytest.mark.parametrize("options,expected", [
    ({"download_type_folder": True, "download_category_folder": True}, "/downloads/电影/亚洲/华语/示例 (2026)"),
    ({"media_type": "电影", "download_type_folder": True, "download_category_folder": True}, "/downloads/亚洲/华语/示例 (2026)"),
    ({"media_category": "亚洲/华语", "download_category_folder": True}, "/downloads/示例 (2026)"),
    ({"media_category_id": "movie:test", "download_category_folder": True}, "/downloads/示例 (2026)"),
])
def test_host_type_and_nested_category_rules_are_applied_once(plugin, directory, options, expected):
    """所选根的类型/分类开关复用宿主，固定分类不会重复追加。"""
    directory = directory.model_copy(update=options)
    plugin.systemconfig.get.return_value = [directory.model_dump()]
    item = event()
    item.event_data.context.media_info.category = "亚洲/华语"
    plugin.on_resource_download(item)
    assert item.event_data.cancel is False
    assert item.event_data.options["save_path"] == expected


@pytest.mark.parametrize("storage,path,expected", [
    ("rclone", "/remote", "rclone:/remote/示例 (2026)"),
    ("local", "D:/Downloads", "D:/Downloads/示例 (2026)"),
])
def test_storage_and_configured_windows_drive_are_preserved(plugin, storage, path, expected):
    """远端 URI 和 Windows 盘符不被误写为本地 POSIX 路径。"""
    root = TransferDirectoryConf(name="独立根", storage=storage, download_path=path)
    plugin.systemconfig.get.return_value = [root.model_dump()]
    plugin.init_plugin({"enabled": True, "movie_root": directory_reference(root)})
    item = event()
    plugin.on_resource_download(item)
    assert item.event_data.cancel is False
    assert item.event_data.options["save_path"] == expected


@pytest.mark.parametrize("storage,path", [
    ("local", "relative"), ("local", "/a/../b"), ("local", "//server/a"),
    ("local", "C:\\Downloads"), ("rclone", "C:/Downloads"), ("missing", "/a"),
    ("local", "/a\nb"), ("local", "/a\x00b"), ("local", "/C:/Downloads"),
])
def test_invalid_root_cannot_be_selected_or_injected(storage, path):
    """选择器和手工编辑配置使用相同的路径验证。"""
    root = TransferDirectoryConf(name="非法", storage=storage, download_path=path)
    with pytest.raises(ValueError):
        directory_reference(root)
    with pytest.raises(ValueError):
        parse_reference(json.dumps(["非法", storage, path]))


def test_same_named_root_is_not_used_as_replacement(plugin, directory):
    """同名但不同路径的新配置不能接管旧引用。"""
    plugin.systemconfig.get.return_value = [
        directory.model_copy(update={"download_path": "/replacement"}).model_dump(),
    ]
    item = event()
    plugin.on_resource_download(item)
    assert item.event_data.cancel is True
    assert item.event_data.options["save_path"] is None


def test_repeated_initialization_and_instances_are_isolated(plugin, directory):
    """启停只影响当前实例，重新初始化清除旧类型选择。"""
    other = MediaDownloadFolder()
    other.init_plugin({})
    assert plugin.get_state() is True
    assert other.get_state() is False
    plugin.stop_service()
    item = event()
    plugin.on_resource_download(item)
    assert item.event_data.options["save_path"] is None
    plugin.init_plugin({"enabled": True, "tv_root": directory_reference(directory)})
    plugin.on_resource_download(item)
    assert item.event_data.options["save_path"] is None
    series = event(media_type=MediaType.TV)
    plugin.on_resource_download(series)
    assert series.event_data.options["save_path"] == "/downloads/示例 (2026)"
    assert other.get_state() is False


def test_storage_read_failure_cancels_only_applicable_download(plugin):
    """读取配置失败不会静默绕过；显式其它目录仍不受插件影响。"""
    plugin.systemconfig.get.side_effect = RuntimeError("database unavailable")
    default = event()
    plugin.on_resource_download(default)
    assert default.event_data.cancel is True
    custom = event(save_path="/downloads/custom")
    plugin.on_resource_download(custom)
    assert custom.event_data.cancel is False
    assert custom.event_data.options["save_path"] == "/downloads/custom"


def test_host_title_cleanup_is_used_instead_of_raw_title(plugin):
    """作品名中的非法文件字符使用整理上下文的全角替换。"""
    item = event(title="示例: 第一/第二部")
    plugin.on_resource_download(item)
    assert item.event_data.options["save_path"] == "/downloads/示例： 第一／第二部 (2026)"


def test_form_defaults_metadata_and_readable_status(plugin, directory):
    """真实实例可生成无自定义 API 的配置/详情页及失效反馈。"""
    form, defaults = plugin.get_form()
    assert defaults == {"enabled": False, "movie_root": None, "tv_root": None}
    selectors = [row for row in form[0]["content"] if row["component"] == "VSelect"]
    assert [row["props"]["model"] for row in selectors] == ["movie_root", "tv_root"]
    assert selectors[0]["props"]["items"][0]["value"] == directory_reference(directory)
    assert plugin.get_api() == []
    assert plugin.get_render_mode() == ("vuetify", None)
    plugin.systemconfig.get.return_value = []
    assert any("已变化" in row["props"]["text"] for row in plugin.get_page())
    root = Path(__file__).resolve().parents[3]
    index = json.loads((root / "package.v3.json").read_text())
    assert index["MediaDownloadFolder"]["version"] == plugin.plugin_version == "1.0.0"
    assert index["MediaDownloadFolder"]["system_version"] == ">=3.2.3"
    assert next(iter(index["MediaDownloadFolder"]["history"])) == "v1.0.0"


def test_stale_selection_has_readable_label_instead_of_raw_reference(plugin, directory):
    """已保存目录失效后仍展示可读名称，让用户清空或重新选择。"""
    plugin.systemconfig.get.return_value = []
    form, _ = plugin.get_form()
    selector = next(row for row in form[0]["content"] if row["component"] == "VSelect")
    item = next(row for row in selector["props"]["items"] if row["value"] == directory_reference(directory))
    assert "影视下载" in item["title"]
    assert "已失效" in item["title"]


def test_status_checks_supported_structure_without_inventing_media_ids(plugin):
    """需要真实来源 ID 的正常模板不能因为预检查没有 ID 而误报。"""
    plugin.chain.runtime_config.rename_format = lambda _: "{{title}} {{tmdbid | int}}/file.mkv"
    assert plugin._status() == []
    item = event()
    plugin.on_resource_download(item)
    assert item.event_data.cancel is False
    assert item.event_data.options["save_path"] == "/downloads/示例 123"


@pytest.mark.parametrize("template", [
    "{{title | random}}/file.mkv",
    "{{title | attr('__class__')}}/file.mkv",
    "{{title}} {% if title is sameas(en_title) %}A{% else %}B{% endif %}/file.mkv",
    "{{title}}-{{videoFormat}}/file.mkv",
    "fixed/file.mkv",
])
def test_status_still_reports_unsupported_structure(plugin, template):
    """不渲染伪数据后，结构上不支持的格式仍有配置错误提示。"""
    plugin.chain.runtime_config.rename_format = lambda _: template
    assert plugin._status()


@pytest.mark.parametrize("template", [
    "{{title | random}}/file.mkv", "{{title | attr('__class__')}}/file.mkv",
    "{{title}} {% if title is sameas(en_title) %}A{% else %}B{% endif %}/file.mkv",
])
def test_unsupported_templates_do_not_take_over_explicit_custom_path(plugin, template):
    """模板检查仅发生在插件作用范围内，显式子目录不会因此取消。"""
    plugin.chain.runtime_config.rename_format = lambda _: template
    item = event(save_path="/downloads/custom")
    plugin.on_resource_download(item)
    assert item.event_data.cancel is False
    assert item.event_data.options["save_path"] == "/downloads/custom"


@pytest.mark.parametrize("template,missing_identity", [
    ("{{title}} {{tmdbid | int}}/file.mkv", True),
    ("{{title | replace('示例', '..')}}/file.mkv", False),
])
def test_runtime_still_rejects_missing_required_facts_and_invalid_rendered_name(
    plugin, template, missing_identity,
):
    """结构检查不代替真实事实与最终目录名的运行时验证。"""
    plugin.chain.runtime_config.rename_format = lambda _: template
    assert plugin._status() == []
    item = event()
    if missing_identity:
        item.event_data.context.media_info = MediaInfo(type=MediaType.MOVIE, title="示例", year="2026")
    plugin.on_resource_download(item)
    assert item.event_data.cancel is True
    assert "作品目录" in item.event_data.reason
    assert item.event_data.options["save_path"] is None


@pytest.mark.parametrize("actual_override", [False, True])
def test_real_download_chain_accepts_folder_and_persists_actual_path(
    plugin, directory, host_configuration, monkeypatch, tmp_path, actual_override,
):
    """真实宿主提交链验证子目录，并将下载器实际目录写入隔离数据库。"""
    from app.chain.download import DownloadChain, submission
    from app.db.adapters.history.download import TransactionalDownloadHistoryRepository
    from app.db.models.downloadhistory import DownloadFiles, DownloadHistory
    from app.schemas.transfer import DownloaderTorrent
    from app.sdk.events import eventmanager
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    root = directory.model_copy(update={"download_path": str(tmp_path / "downloads")})
    plugin.systemconfig.get.return_value = [root.model_dump()]
    plugin.init_plugin({"enabled": True, "movie_root": directory_reference(root)})
    host_configuration.get = lambda key: [root.model_dump()] if key == SystemConfigKey.Directories else None
    monkeypatch.setattr(submission, "MediaChain", lambda: SimpleNamespace(
        supplement_tmdb_info=lambda media, _meta: media,
    ))
    monkeypatch.setattr(submission, "TorrentHelper", lambda: SimpleNamespace(
        get_fileinfo_from_torrent_content=lambda _content: ("", ["Example.2026.1080p.mkv"]),
    ))

    def dispatch(event_type, data):
        """通过宿主事件入口执行真实插件处理器。"""
        from app.schemas.types import ChainEventType

        assert event_type == ChainEventType.ResourceDownload
        message = SimpleNamespace(event_data=data)
        plugin.on_resource_download(message)
        return message

    monkeypatch.setattr(eventmanager, "send_event", dispatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    DownloadHistory.__table__.create(engine)
    DownloadFiles.__table__.create(engine)
    repository = TransactionalDownloadHistoryRepository(
        sync_session=sessionmaker(bind=engine), async_session=MagicMock(),
    )
    chain = object.__new__(DownloadChain)
    chain.runtime_config = SimpleNamespace(media_extensions=(".mkv",))
    chain.download_history_repository = repository
    chain.durable_event_writer = None
    chain.eventmanager = MagicMock()
    chain._build_download_notification = MagicMock(return_value=None)
    chain._submit_download_added_task = MagicMock()
    chain.download = MagicMock(return_value=("qb", "example-hash", "NoSubfolder", "添加下载成功"))
    expected = tmp_path / "downloads" / "示例 (2026)"
    actual = tmp_path / "existing-task" if actual_override else expected
    chain.list_torrents = MagicMock(return_value=[DownloaderTorrent(
        hash="example-hash", downloader="qb", save_path=str(actual),
    )])
    try:
        result = chain.download_single(
            context=event().event_data.context, torrent_content=b"local-test-fixture",
            source="Subscribe", return_detail=True,
        )
        assert result[0] == "example-hash"
        assert chain.download.call_args.kwargs["download_dir"] == expected
        assert repository.get_by_hash("example-hash").path == str(actual / "Example.2026.1080p.mkv")
        assert repository.get_files_by_hash("example-hash")[0].savepath == str(actual)
        assert not (tmp_path / "downloads").exists()
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid", ["template", "removed", "attribute_filter", "random_filter", "identity_test"])
def test_real_chain_rejects_invalid_plugin_settings_before_downloader(
    plugin, monkeypatch, invalid,
):
    """配置失败发生在真实提交链下载器和取种副作用之前。"""
    from app.chain.download import DownloadChain, submission
    from app.sdk.events import eventmanager

    if invalid == "template":
        plugin.chain.runtime_config.rename_format = lambda _: "{{title}}-{{videoFormat}}/file.mkv"
    elif invalid == "attribute_filter":
        plugin.chain.runtime_config.rename_format = lambda _: "{{title | attr('__class__')}}/file.mkv"
    elif invalid == "random_filter":
        plugin.chain.runtime_config.rename_format = lambda _: "{{title | random}}/file.mkv"
    elif invalid == "identity_test":
        plugin.chain.runtime_config.rename_format = lambda _: (
            "{{title}} {% if title is sameas(en_title) %}A{% else %}B{% endif %}/file.mkv"
        )
    else:
        plugin.systemconfig.get.return_value = []
    monkeypatch.setattr(submission, "MediaChain", lambda: SimpleNamespace(
        supplement_tmdb_info=lambda media, _meta: media,
    ))

    def dispatch(_event_type, data):
        """保留真实事件对象及取消输出。"""
        message = SimpleNamespace(event_data=data)
        plugin.on_resource_download(message)
        return message

    monkeypatch.setattr(eventmanager, "send_event", dispatch)
    chain = object.__new__(DownloadChain)
    chain.download = MagicMock()
    chain.download_torrent = MagicMock()
    result = chain.download_single(context=event().event_data.context, return_detail=True)
    assert result == (None, "下载被事件取消")
    chain.download.assert_not_called()
    chain.download_torrent.assert_not_called()
