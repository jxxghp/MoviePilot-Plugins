import threading
from pathlib import Path
from types import SimpleNamespace

import app.plugins.lunatvsource as plugin_module
from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.cms import CmsSource, _result_from_item
from app.plugins.lunatvsource.downloader import DownloadQueue, DownloadTask


def test_api_search_collapses_tv_episode_rows_into_season_result(monkeypatch):
    source = CmsSource("demo", "演示源", "https://cms.example/vod")
    rows = [
        _result_from_item(
            source,
            {
                "vod_id": f"episode-{episode}",
                "vod_name": f"示例剧 第{episode}集",
                "vod_year": "2026",
                "type_name": "电视剧",
                "vod_play_url": (
                    f"第{episode}集$https://video.example/s01e{episode:02d}.m3u8"
                ),
            },
        )
        for episode in (1, 2)
    ]

    class Client:
        def search(self, *_args, **_kwargs):
            return rows

    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "ai_enabled": False})
    monkeypatch.setattr(plugin, "_client", lambda: Client())
    monkeypatch.setattr(plugin, "_associate_tmdb", lambda *_args, **_kwargs: {})

    response = plugin.api_search({"query": "示例剧", "media_type": "tv"})

    assert response["success"] is True
    assert len(response["data"]) == 1
    assert response["data"][0]["title"].endswith("第1季")
    assert "集" not in response["data"][0]["title"]
    assert [item["episode"] for item in response["data"][0]["episodes"]] == [1, 2]


def test_record_completion_respects_disabled_moviepilot_organize(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "moviepilot_organize": False})
    calls = []

    monkeypatch.setattr(
        plugin,
        "_native_transfer",
        lambda *_args: calls.append("transfer") or "moviepilot",
    )
    monkeypatch.setattr(
        plugin,
        "_record_native_history",
        lambda _task, output: calls.append(("history", output)),
    )
    monkeypatch.setattr(plugin, "_sync_media_server", lambda: calls.append("sync"))

    plugin._record_completion(SimpleNamespace(), "/downloads/movie.mp4")

    assert calls == [("history", "/downloads/movie.mp4"), "sync"]


def test_native_subscription_ids_require_exact_identity_and_season(monkeypatch):
    subscriptions = [
        SimpleNamespace(
            id=1,
            state="R",
            type="电视剧",
            media_source="themoviedb",
            media_id="42",
            season=1,
        ),
        SimpleNamespace(
            id=2,
            state="P",
            type="tv",
            media_source="themoviedb",
            media_id="42",
            season=1,
        ),
        SimpleNamespace(
            id=3,
            state="R",
            type="tv",
            media_source="themoviedb",
            media_id="43",
            season=1,
        ),
        SimpleNamespace(
            id=4,
            state="R",
            type="tv",
            media_source="themoviedb",
            media_id="42",
            season=2,
        ),
        SimpleNamespace(
            id=5,
            state="S",
            type="tv",
            media_source="themoviedb",
            media_id="42",
            season=1,
        ),
        SimpleNamespace(
            id=6,
            state="R",
            type="tv",
            media_source="themoviedb",
            media_id="42",
            season=0,
        ),
    ]

    class Repository:
        @staticmethod
        def list(_state=None):
            return subscriptions

    class SubscribeChain:
        subscription_repository = Repository()

    monkeypatch.setattr(plugin_module, "_HostSubscribeChain", SubscribeChain)
    task = DownloadTask(
        task_id="subscription-progress-identity",
        source_key="lunatv",
        media_id="cms:series",
        title="示例剧",
        year="2026",
        media_type="tv",
        season=1,
        episode=7,
        url="https://video.example/s01e07.m3u8",
        root="/downloads",
        host_media_source="themoviedb",
        host_media_id="42",
    )

    assert LunaTVSource()._native_subscription_ids(task) == {1, 2}

    task.season = 0
    assert LunaTVSource()._native_subscription_ids(task) == {6}


def test_record_completion_schedules_backfill_only_after_native_transfer(
    monkeypatch, tmp_path: Path
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "moviepilot_organize": True})
    task = DownloadTask(
        task_id="subscription-progress-completion",
        source_key="lunatv",
        media_id="cms:series",
        title="示例剧",
        year="2026",
        media_type="tv",
        season=1,
        episode=7,
        url="https://video.example/s01e07.m3u8",
        root=str(tmp_path),
    )
    calls = []
    transfer_results = iter(("moviepilot", "fallback:no-library-target"))

    monkeypatch.setattr(plugin, "_native_transfer", lambda *_args: next(transfer_results))
    monkeypatch.setattr(plugin, "_remove_empty_download_parents", lambda *_args: None)
    monkeypatch.setattr(plugin, "_record_native_history", lambda *_args: calls.append("history"))
    monkeypatch.setattr(plugin, "_native_subscription_ids", lambda _task: {10, 11})

    probes = []

    def sync(subscription_ids=None, episode=None, media_probe=None):
        calls.append(("sync", subscription_ids, episode))
        probes.append(media_probe)
        return True

    monkeypatch.setattr(plugin, "_sync_media_server", sync)

    plugin._record_completion(task, str(tmp_path / "episode-7.mp4"))
    plugin._record_completion(task, str(tmp_path / "episode-7.mp4"))

    assert calls == [
        "history",
        ("sync", {10, 11}, 7),
        "history",
        ("sync", {10, 11}, None),
    ]
    assert probes[0]["media_type"] == "tv"
    assert probes[0]["episode"] == 7
    assert probes[1] is None


def test_record_completion_replay_skips_duplicate_native_transfer(
    monkeypatch, tmp_path: Path
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "moviepilot_organize": True})
    task = DownloadTask(
        task_id="completion-replay",
        source_key="lunatv",
        media_id="cms:series",
        title="示例剧",
        year="2026",
        media_type="tv",
        season=1,
        episode=7,
        url="https://video.example/s01e07.m3u8",
        root=str(tmp_path),
    )
    history_checks = iter((False, True))
    transfers = []
    syncs = []

    monkeypatch.setattr(
        plugin,
        "_native_history_has_episode",
        lambda _task: next(history_checks),
    )
    monkeypatch.setattr(
        plugin,
        "_native_transfer",
        lambda *_args: transfers.append("transfer") or "moviepilot",
    )
    monkeypatch.setattr(plugin, "_remove_empty_download_parents", lambda *_args: None)
    monkeypatch.setattr(plugin, "_record_native_history", lambda *_args: None)
    monkeypatch.setattr(plugin, "_native_subscription_ids", lambda _task: {10})
    monkeypatch.setattr(
        plugin,
        "_sync_media_server",
        lambda ids, episode=None, media_probe=None: syncs.append((ids, episode))
        or True,
    )

    output = str(tmp_path / "episode-7.mp4")
    plugin._record_completion(task, output)
    plugin._record_completion(task, output)

    assert transfers == ["transfer"]
    assert syncs == [({10}, 7), ({10}, None)]


def test_backfill_native_subscription_progress_reads_fresh_snapshot(monkeypatch):
    snapshot = SimpleNamespace(id=10)
    gets = []
    backfills = []

    class Repository:
        @staticmethod
        def get(subscribe_id):
            gets.append(subscribe_id)
            return snapshot

    class SubscribeChain:
        subscription_repository = Repository()

        @staticmethod
        def backfill_existing_episodes(subscribe, episodes):
            backfills.append((subscribe, episodes))
            return {
                "accepted": episodes,
                "updated": True,
                "progress": {"updated": True},
            }

    monkeypatch.setattr(plugin_module, "_HostSubscribeChain", SubscribeChain)

    handled = LunaTVSource()._backfill_native_subscription_progress({10: {7, 6}})

    assert handled == {10}
    assert gets == [10]
    assert backfills == [(snapshot, [6, 7])]


def test_backfill_native_subscription_progress_accepts_duplicate_episodes(monkeypatch):
    snapshot = SimpleNamespace(id=10)

    class Repository:
        @staticmethod
        def get(_subscribe_id):
            return snapshot

    class SubscribeChain:
        subscription_repository = Repository()

        @staticmethod
        def backfill_existing_episodes(_subscribe, _episodes):
            return {
                "accepted": [],
                "ignored": [{"episode": 7, "reason": "duplicate"}],
            }

    monkeypatch.setattr(plugin_module, "_HostSubscribeChain", SubscribeChain)

    assert LunaTVSource()._backfill_native_subscription_progress({10: {7}}) == {10}


def test_backfill_native_subscription_progress_rejects_invalid_ignored_episode(monkeypatch):
    snapshot = SimpleNamespace(id=10)

    class Repository:
        @staticmethod
        def get(_subscribe_id):
            return snapshot

    class SubscribeChain:
        subscription_repository = Repository()

        @staticmethod
        def backfill_existing_episodes(_subscribe, _episodes):
            return {
                "accepted": [],
                "ignored": [{"episode": 7, "reason": "invalid"}],
            }

    monkeypatch.setattr(plugin_module, "_HostSubscribeChain", SubscribeChain)

    assert LunaTVSource()._backfill_native_subscription_progress({10: {7}}) == set()


def test_sync_media_server_replays_request_arriving_during_sync(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)
    sync_calls = []
    backfills = []
    refreshes = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)
            if len(sync_calls) == 1:
                assert plugin._sync_media_server({9}, 2) is False

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    def backfill(pending):
        backfills.append(pending)
        return set(pending)

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(plugin, "_backfill_native_subscription_progress", backfill)
    monkeypatch.setattr(
        plugin,
        "_refresh_native_subscription_progress",
        lambda ids: refreshes.append(ids),
    )

    assert plugin._sync_media_server({9}, 1) is True
    assert sync_calls == ["Emby", "Emby"]
    assert backfills == [{9: {1}}, {9: {2}}]
    assert refreshes == []
    assert plugin._media_sync_running is False


def test_sync_media_server_retries_once_after_transient_failure(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)
    sync_calls = []
    refreshes = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)
            if len(sync_calls) == 1:
                raise RuntimeError("temporary")

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(plugin, "_backfill_native_subscription_progress", lambda _pending: set())
    monkeypatch.setattr(
        plugin,
        "_refresh_native_subscription_progress",
        lambda ids: refreshes.append(ids) or set(ids),
    )

    assert plugin._sync_media_server({9}) is True
    assert sync_calls == ["Emby", "Emby"]
    assert refreshes == [{9}]
    assert plugin._media_sync_running is False
    status = plugin.get_data(plugin_module.FOLLOWUP_STATUS_KEY)["media_server_sync"]
    assert status["success"] is True
    assert status["media_server_synced"] is True
    assert status["refreshed_subscriptions"] == 1


def test_sync_media_server_does_not_report_success_when_library_refresh_fails(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    events = []
    refresh_calls = []
    sync_calls = []
    subscription_refreshes = []

    class MediaServer:
        def refresh_root_library(self):
            events.append("refresh")
            refresh_calls.append("Emby")
            return False

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            assert name_filters == ["Emby"]
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            events.append("sync")
            sync_calls.append(server)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        plugin,
        "_refresh_native_subscription_progress",
        lambda ids: subscription_refreshes.append(set(ids)) or set(ids),
    )

    assert plugin._sync_media_server({9}) is True
    assert events == ["refresh", "sync", "refresh", "sync"]
    assert refresh_calls == ["Emby", "Emby"]
    assert sync_calls == ["Emby", "Emby"]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["media_server_synced"] is False
    assert status["media_server_refreshed"] is False
    assert status["moviepilot_index_synced"] is True
    assert subscription_refreshes == []


def test_sync_media_server_waits_only_for_services_accepting_refresh(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    events = []
    sync_calls = []

    class AcceptedMediaServer:
        def refresh_root_library(self):
            events.append("accepted-refresh")
            return True

        def get_movies(self, *, title, year=None):
            events.append(("accepted-probe", title, year))
            return [SimpleNamespace(item_id="new-movie")]

    class RejectedMediaServer:
        def refresh_root_library(self):
            events.append("rejected-refresh")
            return False

        def get_movies(self, **_kwargs):
            raise AssertionError("未接受刷新请求的服务不应参与可见性等待")

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            assert name_filters is None
            return {
                "Accepted": SimpleNamespace(instance=AcceptedMediaServer()),
                "Rejected": SimpleNamespace(instance=RejectedMediaServer()),
            }

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "部分成功", "year": "2026"}
    ) is True
    assert events == [
        "accepted-refresh",
        "rejected-refresh",
        ("accepted-probe", "部分成功", "2026"),
        "accepted-refresh",
        "rejected-refresh",
        ("accepted-probe", "部分成功", "2026"),
    ]
    assert sync_calls == [None, None]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["media_server_refresh_requested"] is True
    assert status["media_server_refreshed"] is False
    assert status["moviepilot_index_synced"] is True
    assert status["media_server_synced"] is False


def test_sync_media_server_waits_until_new_movie_is_visible_before_index_sync(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    events = []
    movie_queries = iter(([], [SimpleNamespace(item_id="new-movie")]))

    class MediaServer:
        def refresh_root_library(self):
            events.append("refresh")
            return True

        def get_movies(self, *, title, year=None):
            events.append(("probe", title, year))
            return next(movie_queries)

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            assert name_filters == ["Emby"]
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            events.append(("sync", server))

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_VISIBILITY_POLL_SECONDS", 0, raising=False)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "新电影", "year": "2026"}
    ) is True
    assert events == [
        "refresh",
        ("probe", "新电影", "2026"),
        ("probe", "新电影", "2026"),
        ("sync", "Emby"),
    ]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is True
    assert status["media_server_refresh_requested"] is True
    assert status["media_server_refreshed"] is True
    assert status["moviepilot_index_synced"] is True


def test_sync_media_server_replays_probe_arriving_during_visibility_wait(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    probes = []
    sync_calls = []
    second_queued = False

    class MediaServer:
        def refresh_root_library(self):
            return True

        def get_movies(self, *, title, year=None):
            nonlocal second_queued
            probes.append((title, year))
            if title == "第一部" and not second_queued:
                second_queued = True
                assert plugin._sync_media_server(
                    media_probe={
                        "media_type": "movie",
                        "title": "第二部",
                        "year": "2026",
                    }
                ) is False
            return [SimpleNamespace(item_id=title)]

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "第一部", "year": "2026"}
    ) is True
    assert probes == [("第一部", "2026"), ("第二部", "2026")]
    assert sync_calls == ["Emby", "Emby"]


def test_sync_media_server_checks_all_probes_with_one_visibility_deadline(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    queries = []
    sync_calls = []

    class MediaServer:
        def refresh_root_library(self):
            return True

        def get_movies(self, *, title, year=None):
            queries.append((title, year))
            if title == "已就绪":
                return [SimpleNamespace(item_id="ready")]
            return []

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            return None

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", DeferredThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "未就绪", "year": "2026"}
    ) is True
    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "已就绪", "year": "2026"}
    ) is False
    worker = plugin._media_sync_thread
    assert worker is not None
    worker.target()

    assert queries == [
        ("未就绪", "2026"),
        ("已就绪", "2026"),
        ("未就绪", "2026"),
    ]
    assert sync_calls == ["Emby", "Emby"]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["failed_media_probes"] == 1


def test_sync_media_server_keeps_failed_batch_visible_after_later_success(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    queries = []
    sync_calls = []

    class MediaServer:
        def refresh_root_library(self):
            return True

        def get_movies(self, *, title, year=None):
            queries.append((title, year))
            return [SimpleNamespace(item_id="ready")] if title == "后来成功" else []

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)
            if len(sync_calls) == 2:
                assert plugin._sync_media_server(
                    media_probe={
                        "media_type": "movie",
                        "title": "后来成功",
                        "year": "2026",
                    }
                ) is False

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "持续失败", "year": "2026"}
    ) is True

    assert queries == [
        ("持续失败", "2026"),
        ("持续失败", "2026"),
        ("后来成功", "2026"),
    ]
    assert sync_calls == ["Emby", "Emby", "Emby"]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["media_server_synced"] is True
    assert status["failed_media_probes"] == 1
    assert status["successful_media_batches"] == 1
    assert status["failed_media_batches"] == 1
    assert status["all_media_batches_synced"] is False
    assert "重试仍失败" in status["error"]


def test_sync_media_server_new_probe_during_retry_gets_full_budget(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    query_attempts = {"旧批失败": 0, "新批重试成功": 0}
    sync_calls = []
    queued_new_probe = False

    class MediaServer:
        def refresh_root_library(self):
            return True

        def get_movies(self, *, title, year=None):
            query_attempts[title] += 1
            if title == "新批重试成功" and query_attempts[title] == 2:
                return [SimpleNamespace(item_id="ready")]
            return []

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    def queue_on_first_retry(_timeout):
        nonlocal queued_new_probe
        if not queued_new_probe:
            queued_new_probe = True
            assert plugin._sync_media_server(
                media_probe={
                    "media_type": "movie",
                    "title": "新批重试成功",
                    "year": "2026",
                }
            ) is False
        return False

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_VISIBILITY_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(plugin._media_sync_stop, "wait", queue_on_first_retry)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "旧批失败", "year": "2026"}
    ) is True

    assert query_attempts == {"旧批失败": 2, "新批重试成功": 2}
    assert sync_calls == ["Emby", "Emby", "Emby", "Emby"]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["media_server_synced"] is True
    assert status["failed_media_probes"] == 1
    assert status["successful_media_batches"] == 1
    assert status["failed_media_batches"] == 1
    assert status["all_media_batches_synced"] is False


def test_sync_media_server_does_not_sync_index_after_stop_during_probe(
    monkeypatch,
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    sync_calls = []

    class MediaServer:
        def refresh_root_library(self):
            return True

        def get_movies(self, *, title, year=None):
            plugin._media_sync_stop.set()
            return []

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "停止测试", "year": "2026"}
    ) is True
    assert sync_calls == []


def test_sync_media_server_detects_visible_tv_episode(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    events = []

    class MediaServer:
        def refresh_root_library(self):
            events.append("refresh")
            return True

        def get_tv_episodes(self, *, title, year=None, season=None):
            events.append(("probe", title, year, season))
            return [], {"2": ["3"]}

    class MediaServerHelper:
        def get_services(self, *, name_filters=None):
            return {"Emby": SimpleNamespace(instance=MediaServer())}

    class MediaServerChain:
        def sync(self, *, server=None):
            events.append(("sync", server))

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        plugin_module,
        "_HostMediaServerHelper",
        MediaServerHelper,
        raising=False,
    )
    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)

    assert plugin._sync_media_server(
        media_probe={
            "media_type": "tv",
            "title": "新剧",
            "year": "2026",
            "season": 2,
            "episode": 3,
        }
    ) is True
    assert events == [
        "refresh",
        ("probe", "新剧", "2026", 2),
        ("sync", "Emby"),
    ]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is True
    assert status["media_server_synced"] is True


def test_sync_media_server_persists_failure_after_retry(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)
    sync_calls = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)
            raise RuntimeError("media server unavailable")

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        plugin,
        "_backfill_native_subscription_progress",
        lambda pending: set(pending),
    )

    assert plugin._sync_media_server({9}, 1) is True
    assert sync_calls == ["Emby", "Emby"]
    status = plugin.api_status()["data"]["followup_status"]["media_server_sync"]
    assert status["success"] is False
    assert status["media_server_synced"] is False
    assert status["backfilled_subscriptions"] == 1
    assert "重试仍失败" in status["error"]


def test_sync_media_server_older_runner_cannot_overwrite_latest_status(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)

    class MediaServerChain:
        def sync(self, *, server=None):
            assert server == "Emby"

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(
        plugin,
        "_backfill_native_subscription_progress",
        lambda pending: set(pending),
    )
    original_record = plugin._record_followup_status
    first_waiting = threading.Event()
    release_first = threading.Event()
    second_recorded = threading.Event()
    first_finished = threading.Event()
    record_calls = []

    def delayed_record(name, **kwargs):
        record_calls.append(name)
        call_number = len(record_calls)
        if name == "media_server_sync" and call_number == 1:
            first_waiting.set()
            assert release_first.wait(timeout=2)
        original_record(name, **kwargs)
        if name == "media_server_sync" and call_number == 1:
            first_finished.set()
        elif name == "media_server_sync" and call_number == 2:
            second_recorded.set()

    monkeypatch.setattr(plugin, "_record_followup_status", delayed_record)

    assert plugin._sync_media_server({1}, 1) is True
    assert first_waiting.wait(timeout=2)
    assert plugin._sync_media_server({2, 3}, 2) is True
    assert second_recorded.wait(timeout=2)
    assert plugin.get_data(plugin_module.FOLLOWUP_STATUS_KEY)[
        "media_server_sync"
    ]["backfilled_subscriptions"] == 2

    release_first.set()
    assert first_finished.wait(timeout=2)
    assert plugin.get_data(plugin_module.FOLLOWUP_STATUS_KEY)[
        "media_server_sync"
    ]["backfilled_subscriptions"] == 2


def test_sync_media_server_retries_backfill_without_media_server(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    attempts = []

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    def backfill(pending):
        attempts.append(pending)
        return set(pending) if len(attempts) > 1 else set()

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", None)
    monkeypatch.setattr(plugin_module, "_MEDIA_SYNC_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(plugin_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(plugin, "_backfill_native_subscription_progress", backfill)

    assert plugin._sync_media_server({9}, 1) is True
    assert attempts == [{9: {1}}, {9: {1}}]
    assert plugin._media_sync_running is False


def test_stop_service_prevents_inflight_sync_from_backfilling(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)
    sync_started = threading.Event()
    release_sync = threading.Event()
    backfills = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_started.set()
            assert release_sync.wait(timeout=2)

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(
        plugin,
        "_backfill_native_subscription_progress",
        lambda pending: backfills.append(pending) or set(pending),
    )

    assert plugin._sync_media_server({9}, 1) is True
    assert sync_started.wait(timeout=2)
    worker = plugin._media_sync_thread
    plugin.stop_service()
    release_sync.set()
    assert worker is not None
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert backfills == []


def test_stop_service_rejects_media_sync_from_late_completion(monkeypatch):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True, "mediaserver_name": "Emby"})
    sync_calls = []

    class MediaServerChain:
        def sync(self, *, server=None):
            sync_calls.append(server)

    monkeypatch.setattr(plugin_module, "_HostMediaServerChain", MediaServerChain)
    monkeypatch.setattr(plugin, "_refresh_media_server_library", lambda _server: True)

    plugin.stop_service()

    assert plugin._sync_media_server(
        media_probe={"media_type": "movie", "title": "停止后完成", "year": "2026"}
    ) is False
    assert sync_calls == []
    assert plugin._media_sync_running is False


def test_queue_holds_slot_during_completion_callback(tmp_path: Path):
    data = {}
    callback_entered = threading.Event()
    release_callback = threading.Event()
    completed = []

    def load(key, default=None):
        return data.get(key, default)

    def save(key, value):
        data[key] = value

    def on_complete(task, _output):
        completed.append(task.episode)
        if task.episode == 1:
            callback_entered.set()
            assert release_callback.wait(timeout=2)

    queue = DownloadQueue(load, save, lambda *_args: None, on_complete=on_complete)
    for episode in (1, 2):
        assert queue.enqueue(
            DownloadTask(
                task_id=f"task-{episode}",
                source_key="demo",
                media_id="demo:series",
                title="示例剧",
                year="2026",
                media_type="tv",
                season=1,
                episode=episode,
                url=f"https://video.example/s01e{episode:02d}.m3u8",
                root=str(tmp_path),
            )
        )

    queue._execute = lambda task: str(tmp_path / f"episode-{task.episode}.mp4")
    first_result = []
    first_thread = threading.Thread(target=lambda: first_result.append(queue.run_one()))
    first_thread.start()

    assert callback_entered.wait(timeout=2)
    overlapping_result = queue.run_one()
    assert overlapping_result == {"processed": 0}

    release_callback.set()
    first_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert first_result[0]["state"] == "completed"

    assert queue.run_one()["state"] == "completed"
    assert completed == [1, 2]
