import pytest

from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.downloader import DownloadTask


@pytest.mark.parametrize("media_type", ["movie", "tv"])
def test_native_start_retries_failed_tasks_without_restarting_finished_members(
    tmp_path, monkeypatch, media_type
):
    plugin = LunaTVSource()
    plugin.init_plugin({"enabled": True})
    calls = []
    monkeypatch.setattr(plugin._queue, "wake", lambda: calls.append("wake"))
    monkeypatch.setattr(plugin, "_start_queue", lambda: calls.append("start"))
    tasks = [
        DownloadTask(
            task_id=state,
            source_key="cms-demo",
            media_id="cms-demo:46",
            title="原生失败重试",
            year="2026",
            media_type=media_type,
            season=1,
            episode=episode,
            url=f"https://example.test/{episode}.m3u8",
            root=str(tmp_path),
            state=state,
            progress=0.95 if state == "failed" else 0.5,
            error="source failed" if state == "failed" else "",
            downloaded_bytes=1234,
        )
        for episode, state in enumerate(
            ("failed", "paused", "completed", "running"), start=1
        )
    ]
    plugin.save_data(plugin._queue.DATA_KEY, [task.to_dict() for task in tasks])
    before = {task["task_id"]: task for task in plugin._queue.list_tasks()}

    assert plugin.start_torrents(["failed"], downloader="LunaTVSource") is True

    after = {task["task_id"]: task for task in plugin._queue.list_tasks()}
    assert after["failed"]["state"] == "pending"
    assert after["failed"]["progress"] == 0.0
    assert after["failed"]["error"] == ""
    assert after["failed"]["downloaded_bytes"] == 0
    assert after["failed"]["url"] == before["failed"]["url"]
    assert after["failed"]["root"] == before["failed"]["root"]
    assert after["completed"] == before["completed"]
    assert after["running"] == before["running"]
    if media_type == "tv":
        assert after["paused"]["state"] == "pending"
        assert after["paused"]["downloaded_bytes"] == 1234
    else:
        assert after["paused"] == before["paused"]
    assert calls == ["wake", "start"]
