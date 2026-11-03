"""自定义 RSS 下载在媒体入库前的季集查重回归。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.domain import metainfo as metainfo_module
from app.plugins import rsssubscribe as rss_module
from app.plugins.rsssubscribe import RssSubscribe
from app.schemas import ExistMediaInfo
from app.schemas.types import MediaSource, MediaType
from app.schemas.transfer import DownloaderTorrent
from app.sdk.media import MediaInfo
from app.sdk.queries import DownloadHistorySnapshot, QueryPage


def _entry(episode: str = "E01", version: str = "CHS.mkv", season: str = "S01") -> dict:
    """构造同一字幕组不同格式的 RSS 条目。"""
    return {
        "title": f"Example Show (2026) {season}{episode} 1080p {version}",
        "enclosure": f"https://rss.invalid/{season}{episode}/{version}.torrent",
        "size": 1024,
    }


def _history(**overrides) -> DownloadHistorySnapshot:
    """构造携带规范媒体身份和实际下载集号的宿主历史快照。"""
    return DownloadHistorySnapshot(**{
        "id": 1, "type": MediaType.TV.value,
        "media_source": MediaSource.TMDB, "media_id": "123",
        "seasons": "S01", "episodes": "E01",
        "download_hash": "existing-hash", "downloader": "qb",
        **overrides,
    })


def _task(**overrides) -> DownloaderTorrent:
    """构造下载器当前仍保留的任务，默认尚未完成下载。"""
    return DownloaderTorrent(**{
        "downloader": "qb", "hash": "existing-hash",
        "state": "downloading", "progress": 50, "tags": "MOVIEPILOT",
        **overrides,
    })


@pytest.fixture
def rss_download(monkeypatch):
    """隔离 RSS、媒体库、下载器与插件存储，只执行生产刷新逻辑。"""
    plugin = object.__new__(RssSubscribe)
    plugin._address = "https://rss.invalid/feed"
    plugin._action = "download"
    plugin._filter = True
    plugin._save_path = "/downloads/anime"
    plugin._clearflag = False
    plugin.chain = Mock()
    plugin.chain.recognize_media.return_value = MediaInfo(
        type=MediaType.TV, title="Example Show", year="2026",
        media_source=MediaSource.TMDB, media_id="123",
        seasons={1: list(range(1, 13)), 2: list(range(1, 13))},
    )
    plugin.chain.media_exists.return_value = None
    plugin.chain.filter_torrents.side_effect = lambda torrent_list, **_kwargs: torrent_list
    monkeypatch.setattr(plugin, "get_data", Mock(return_value=[]))
    monkeypatch.setattr(plugin, "save_data", Mock())
    plugin.systemconfig = Mock()
    plugin.systemconfig.get.return_value = None
    monkeypatch.setattr("app.application.recognition.get_configured_system_config", lambda: plugin.systemconfig)
    metainfo_module.clear_rust_parse_options_cache()
    downloader = Mock()
    downloader.list_torrents.return_value = []
    downloader.download_single.return_value = "accepted-hash"
    subscriber = Mock()
    subscriber.exists.return_value = False
    feed = Mock()
    feed.parse.return_value = [_entry(), _entry(version="CHT.mp4")]
    monkeypatch.setattr(rss_module, "DownloadChain", lambda: downloader)
    monkeypatch.setattr(rss_module, "SubscribeChain", lambda: subscriber)
    monkeypatch.setattr(rss_module, "RssHelper", lambda: feed)
    histories = Mock(return_value=QueryPage(items=[]))
    monkeypatch.setattr(rss_module, "list_download_history", histories, raising=False)
    try:
        yield SimpleNamespace(
            plugin=plugin, downloader=downloader, subscriber=subscriber, feed=feed, histories=histories,
        )
    finally:
        metainfo_module.clear_rust_parse_options_cache()


@pytest.mark.parametrize("use_filter", (False, True))
@pytest.mark.parametrize("season", ("S01", ""))
def test_same_batch_versions_submit_only_once(rss_download, use_filter, season):
    """第一版提交成功但下载器列表尚不可见时，同集另一格式也必须跳过。"""
    rss_download.plugin._filter = use_filter
    rss_download.feed.parse.return_value = [_entry(season=season), _entry(version="CHT.mp4", season=season)]
    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 1
    history = rss_download.plugin.save_data.call_args.args[1]
    assert [item["key"] for item in history] == [_entry(season=season)["title"]]
    assert rss_download.downloader.download_single.call_args.kwargs["save_path"] == "/downloads/anime"


def test_failed_first_version_does_not_block_second(rss_download):
    """下载提交失败不能占用集数，应继续尝试下一版本。"""
    rss_download.downloader.download_single.side_effect = [None, "accepted-hash"]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 2
    history = rss_download.plugin.save_data.call_args.args[1]
    assert [item["key"] for item in history] == [_entry(version="CHT.mp4")["title"]]


def test_exception_on_first_version_does_not_block_second(rss_download):
    """下载链抛错后，后续版本仍能提交且不会记入失败版本历史。"""
    rss_download.downloader.download_single.side_effect = [RuntimeError("download failed"), "accepted-hash"]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 2
    history = rss_download.plugin.save_data.call_args.args[1]
    assert [item["key"] for item in history] == [_entry(version="CHT.mp4")["title"]]


def test_different_episodes_and_seasons_are_not_duplicates(rss_download):
    """同媒体不同集或不同季必须独立下载。"""
    rss_download.feed.parse.return_value = [_entry(), _entry("E02"), _entry(season="S02")]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 3


def test_partial_pack_downloads_only_missing_episodes(rss_download):
    """先提交单集后遇到双集合集，只把未提交的集数交给下载链。"""
    rss_download.feed.parse.return_value = [_entry(), _entry("E01-E02", "CHT.mp4")]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 2
    assert rss_download.downloader.download_single.call_args.kwargs["episodes"] == {2}


def test_library_coverage_is_combined_with_batch_submissions(rss_download):
    """已入库与本轮已提交的集数共同覆盖合集时，不应重复下载。"""
    rss_download.plugin.chain.media_exists.return_value = ExistMediaInfo(seasons={1: [1]})
    rss_download.feed.parse.return_value = [_entry("E02"), _entry("E01-E02", "CHT.mp4")]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 1


def test_implicit_first_season_checks_existing_library_episode(rss_download):
    """省略季号的动漫单集应按第一季查询媒体库，不能漏过已入库内容。"""
    rss_download.plugin.chain.media_exists.return_value = ExistMediaInfo(seasons={1: [1]})
    rss_download.feed.parse.return_value = [_entry(season="")]

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()


def test_multiple_feeds_share_successful_episode_coverage(rss_download):
    """同轮不同 RSS 地址发布同集时，共享成功提交的查重范围。"""
    rss_download.plugin._address += "\nhttps://rss.invalid/another"
    rss_download.feed.parse.side_effect = [[_entry()], [_entry(version="CHT.mp4")]]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 1


def test_subscribe_action_preserves_existing_path(rss_download):
    """订阅动作继续交给订阅链，不查询下载器或走直接下载。"""
    rss_download.plugin._action = "subscribe"
    rss_download.feed.parse.return_value = [_entry()]

    rss_download.plugin.check()

    rss_download.subscriber.add.assert_called_once()
    rss_download.downloader.list_torrents.assert_not_called()
    rss_download.downloader.download_single.assert_not_called()


@pytest.mark.parametrize("state,progress", (("downloading", 50), ("paused", 10), ("completed", 100)))
def test_existing_unorganized_task_blocks_both_versions(rss_download, state, progress):
    """已提交任务无论正在下载、暂停还是完成待整理，均占用对应剧集。"""
    rss_download.downloader.list_torrents.return_value = [_task(state=state, progress=progress)]
    rss_download.histories.return_value = QueryPage(items=[_history()])

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()
    filters = rss_download.histories.call_args.kwargs["filters"]
    assert filters == {"media_source": MediaSource.TMDB, "media_id": "123", "media_types": (MediaType.TV,)}


@pytest.mark.parametrize("task", (None, _task(tags="MOVIEPILOT, 已整理"), _task(downloader="other-qb")))
def test_stale_organized_or_other_downloader_history_does_not_block(rss_download, task):
    """删除任务、已整理任务和另一下载器同 hash 的旧记录不能拦截补集。"""
    rss_download.feed.parse.return_value = [_entry()]
    rss_download.downloader.list_torrents.return_value = [task] if task else []
    rss_download.histories.return_value = QueryPage(items=[_history()])

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_called_once()


@pytest.mark.parametrize("history", (
    _history(seasons="S02"),
    _history(episodes="E02"),
    _history(seasons=None),
    _history(episode_group="other-order"),
))
def test_other_season_episode_or_group_does_not_block(rss_download, history):
    """不相干的季集或剧集组、无法确认季号的历史均不能占用目标集。"""
    rss_download.feed.parse.return_value = [_entry()]
    rss_download.downloader.list_torrents.return_value = [_task()]
    rss_download.histories.return_value = QueryPage(items=[history])

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_called_once()


def test_disjoint_history_does_not_fill_episode_gap(rss_download):
    """E01、E03 的选集记录不能把间隔中的 E02 当作已下载。"""
    rss_download.feed.parse.return_value = [_entry("E02")]
    rss_download.downloader.list_torrents.return_value = [_task()]
    rss_download.histories.return_value = QueryPage(items=[_history(episodes="E01、E03")])

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_called_once()


def test_whole_season_task_covers_single_episode(rss_download):
    """已提交整季且尚未整理时，该季单集不应再次下载。"""
    rss_download.downloader.list_torrents.return_value = [_task()]
    rss_download.histories.return_value = QueryPage(items=[_history(episodes="")])

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()


def test_pending_episode_on_later_history_page_is_checked(rss_download):
    """遍历媒体全部历史分页，不能遗漏较后页的实际待整理任务。"""
    rss_download.feed.parse.return_value = [_entry()]
    rss_download.downloader.list_torrents.return_value = [_task()]
    rss_download.histories.side_effect = [
        QueryPage(items=[_history(id=2, episodes="E02")], total=2, page=1, count=1),
        QueryPage(items=[_history()], total=2, page=2, count=1),
    ]

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()
    assert [call.kwargs["page"]["page"] for call in rss_download.histories.call_args_list] == [1, 2]


@pytest.mark.parametrize("identity", (
    {"media_id": "456"},
    {"media_source": MediaSource.TVDB},
    {"episode_group": "other-order"},
))
def test_batch_coverage_is_scoped_to_media_identity(rss_download, identity):
    """相同季集但不同来源、媒体 ID 或剧集组的条目必须分别下载。"""
    media = rss_download.plugin.chain.recognize_media.return_value
    other_media = deepcopy(media)
    for key, value in identity.items():
        setattr(other_media, key, value)
    rss_download.plugin.chain.recognize_media.side_effect = [media, other_media]

    rss_download.plugin.check()

    assert rss_download.downloader.download_single.call_count == 2


def test_rejected_first_version_does_not_reserve_episode(rss_download):
    """首版未通过用户过滤规则时，后续合规版本仍须正常提交。"""
    rss_download.plugin.chain.filter_torrents.side_effect = [[], [object()]]

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_called_once()
    context = rss_download.downloader.download_single.call_args.kwargs["context"]
    assert context.torrent_info.title == _entry(version="CHT.mp4")["title"]


def test_failed_history_query_does_not_submit_unchecked_episode(rss_download):
    """下载历史查询失败时保留错误处理，不把无法查重的任务继续提交。"""
    rss_download.downloader.list_torrents.return_value = [_task()]
    rss_download.histories.side_effect = RuntimeError("query unavailable")

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()


def test_unavailable_downloader_does_not_submit_unchecked_episode(rss_download):
    """下载器查询返回不可用时，不将未知状态当作空任务列表。"""
    rss_download.downloader.list_torrents.return_value = None

    rss_download.plugin.check()

    rss_download.downloader.download_single.assert_not_called()


def test_refresh_lock_is_released_on_failure(rss_download):
    """RSS 拉取异常后释放串行锁，后续定时刷新仍能继续。"""
    rss_download.feed.parse.side_effect = RuntimeError("feed unavailable")
    with pytest.raises(RuntimeError, match="feed unavailable"):
        rss_download.plugin.check()

    assert rss_module.lock.acquire(blocking=False)
    rss_module.lock.release()
    rss_download.feed.parse.side_effect = None
    rss_download.feed.parse.return_value = [_entry()]
    rss_download.plugin.check()
    rss_download.downloader.download_single.assert_called_once()


def test_concurrent_refresh_waits_for_previous_refresh(rss_download):
    """立即运行与定时刷新并发触发时，后一轮不能在前一轮保存历史前读取 RSS。"""
    first_feed = Event()
    release_first = Event()
    second_started = Event()
    second_feed = Event()

    def parse_feed(*_args, **_kwargs):
        """阻塞第一轮 RSS 读取，并标记后一轮何时实际进入刷新。"""
        if not first_feed.is_set():
            first_feed.set()
            assert release_first.wait(5)
        else:
            second_feed.set()
        return [_entry()]

    def run_second():
        """报告第二个调用已启动，再进入生产刷新入口。"""
        second_started.set()
        rss_download.plugin.check()

    rss_download.feed.parse.side_effect = parse_feed
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(rss_download.plugin.check)
        try:
            assert first_feed.wait(5)
            second = pool.submit(run_second)
            assert second_started.wait(5)
            assert not second_feed.wait(0.1)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert second_feed.is_set()
