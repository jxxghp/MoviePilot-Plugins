"""单测：已看判定（剧集只认整季）、缓冲期、取消已看不删、清单冻结、辅种共用识别、三种删除选项。

只依赖 core/ 纯逻辑；文件用临时目录里的真实硬链接。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

from app.plugins.zspacevideo.core import pathmap
from app.plugins.zspacevideo.core import watched as W
from app.plugins.zspacevideo.core.cli import CliError
from app.plugins.zspacevideo.core.watch_service import WatchHost, WatchService, WatchSettings

DAY = 86400.0


def movie_row(**kw):
    row = {"classification_id": "movie", "classification_name": "电影", "collection_id": "c1", "title": "样片",
           "type": 100, "is_seen": 1, "extend_type": 1, "tmdb_id": 11, "release_year": 2026}
    row.update(kw)
    return row


def season_row(**kw):
    row = {"classification_id": "tv", "classification_name": "电视剧", "collection_id": "s1", "title": "样剧 第 2 季",
           "type": 200, "is_seen": 1, "extend_type": 1, "tmdb_id": 22}
    row.update(kw)
    return row


class SeenTest:
    def test_movie_seen(self):
        entries = W.watched_entries(movie_row(), dict, dict)
        assert [(e.kind, e.key) for e in entries] == [("movie", "movie:11")]

    def test_unseen_and_series_rows_ignored(self):
        assert W.watched_entries(movie_row(is_seen=0), dict, dict) == []
        assert W.watched_entries(movie_row(extend_type=7), dict, dict) == []  # 合集行

    def test_tv_only_whole_season_mark(self):
        # 季专辑本身被标已看 -> 这一季
        entries = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 2, "tmdbid": 22}, dict)
        assert [e.key for e in entries] == ["tv:22:S2"]
        # 列表说已看但详情说没看（例如刚取消）-> 不算
        assert W.watched_entries(season_row(), lambda: {"is_seen": 0, "season": 2}, dict) == []

    def test_tv_never_uses_episode_progress(self):
        # 季没被标记，但有单集看完的播放记录：不算已看（函数根本不读播放记录）
        info = {"is_seen": 0, "season": 1, "history": {"play_duration": 3000, "last_video_duration": 3000}}
        assert W.watched_entries(season_row(is_seen=0), lambda: info, dict) == []
        assert W.watched_entries(season_row(is_seen=1), lambda: info, dict) == []

    def test_tv_season_from_paths_when_info_has_none(self):
        videos = {"video_list": [{"file_path": "/x/样剧 (2020)/Season 3/样剧 - S03E01.mkv"},
                                 {"file_path": "/x/样剧 (2020)/Season 3/样剧 - S03E02.mkv"}]}
        entries = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 0}, lambda: videos)
        assert [e.season for e in entries] == [3]


class TrackTest:
    def setup_method(self):
        self.movie = W.watched_entries(movie_row(), dict, dict)[0]

    def test_buffer_period(self):
        state, added, removed = W.track({}, [self.movie], now=1000.0)
        assert added == ["movie:11"]
        assert W.due_keys(state, 7, now=1000.0 + 6 * DAY) == []
        state, _, _ = W.track(state, [self.movie], now=1000.0 + 6.5 * DAY)
        assert state["movie:11"]["first_seen_at"] == 1000.0  # 首次发现时间不变
        assert W.due_keys(state, 7, now=1000.0 + 7 * DAY) == ["movie:11"]
        assert W.due_keys(state, 0, now=1000.0) == ["movie:11"]  # 纯函数允许 0；配置层最少 1 天

    def test_unseen_within_buffer_not_deleted(self):
        state, _, _ = W.track({}, [self.movie], now=0.0)
        # 第 3 天客户端取消了已看：本次清单里没有它
        state, _, removed = W.track(state, [], now=3 * DAY)
        assert removed == ["movie:11"]
        assert W.due_keys(state, 7, now=30 * DAY) == []
        # 第 20 天又标已看：缓冲期从头算
        state, added, _ = W.track(state, [self.movie], now=20 * DAY)
        assert added == ["movie:11"]
        assert W.due_keys(state, 7, now=26 * DAY) == []
        assert W.due_keys(state, 7, now=27 * DAY) == ["movie:11"]

    def test_done_not_repeated(self):
        state, _, _ = W.track({}, [self.movie], now=0.0)
        state["movie:11"]["done_at"] = 1.0
        state, _, _ = W.track(state, [self.movie], now=10 * DAY)
        assert W.due_keys(state, 7, now=10 * DAY) == []


class Fixture:
    """临时目录：complete（做种源）+ movies（库入口，硬链接）。"""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.complete = root / "downloads" / "complete"
        self.library = root / "downloads" / "movies"
        self.complete.mkdir(parents=True)
        self.library.mkdir(parents=True)
        self.roots = W.Roots(library=[str(self.library)], download=[str(self.complete)])
        self.index = W.InodeIndex([str(root / "downloads")])

    def add_version(self, name, size=1000, link=True):
        src_dir = self.complete / name
        src_dir.mkdir()
        src = src_dir / f"{name}.mkv"
        src.write_bytes(b"x" * size)
        dest = None
        if link:
            dest_dir = self.library / "样片 (2026)"
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / f"样片 (2026) - {name}.mkv"
            os.link(src, dest)
        return src_dir, src, dest

    def cleanup(self):
        self.tmp.cleanup()


def tor(h, content, site="站点A", state="stalledUP"):
    return W.TorrentInfo(hash=h, name=os.path.basename(content), content_path=str(content),
                         save_path=str(Path(content).parent), state=state, site=site)


class VersionsAndPlanTest:
    def setup_method(self):
        self.fx = Fixture()
        self.entry = W.watched_entries(movie_row(), dict, dict)[0]

    def teardown_method(self):
        self.fx.cleanup()

    def build(self, transfers, downloads, torrents, files=None):
        files = files or {}
        return W.build_versions(self.entry, transfers, downloads, torrents, self.fx.roots, self.fx.index,
                                lambda t: files.get(t.hash, _list_media(t.content_path)))

    def test_wash_old_version_grouped(self):
        # 新版在库里；洗版换下来的旧版只剩下载目录（库入口已被覆盖删掉）
        new_dir, new_src, new_dest = self.fx.add_version("NEW-2160p")
        old_dir, old_src, _ = self.fx.add_version("OLD-1080p", link=False)
        transfers = [
            {"id": 2, "status": True, "src": str(new_src), "dest": str(new_dest), "download_hash": "bbb"},
            {"id": 1, "status": True, "src": str(old_src), "dest": str(self.fx.library / "gone.mkv"), "download_hash": "aaa"},
        ]
        downloads = [{"path": str(old_dir), "download_hash": "aaa", "torrent_site": "朱雀"},
                     {"path": str(new_dir), "download_hash": "bbb", "torrent_site": "站点A"}]
        versions = self.build(transfers, downloads, [tor("aaa", old_dir, "朱雀"), tor("bbb", new_dir)])
        assert len(versions) == 2
        new, old = versions
        assert new.in_library
        assert not old.in_library
        assert old.site == "朱雀"
        lib = next(f for f in new.files if f.role == "library")
        assert sorted(lib.links) == sorted([str(new_src), str(new_dest)])

    def test_cross_seed_identified(self):
        src_dir, src, dest = self.fx.add_version("REMUX")
        transfers = [{"id": 5, "status": True, "src": str(src), "dest": str(dest), "download_hash": "m1"}]
        torrents = [tor("m1", src_dir, "站点A"), tor("h2", src_dir, "站点B")]  # 辅种：同内容路径、不同 hash
        versions = self.build(transfers, [], torrents)
        assert len(versions) == 1
        v = versions[0]
        assert sorted(t.hash for t in v.torrents) == ["h2", "m1"]
        assert all(t.cross_seed for t in v.torrents)
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_FULL, None, self.fx.roots, now=100.0)
        assert sorted(t.hash for t in plan.torrents) == ["h2", "m1"]
        assert any("辅种" in w for w in plan.warnings)
        assert plan.freed_bytes == 1000

    def test_library_only_keeps_seed_and_frees_nothing(self):
        src_dir, src, dest = self.fx.add_version("WEB")
        versions = self.build([{"id": 1, "status": True, "src": str(src), "dest": str(dest)}], [], [tor("t", src_dir)])
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_LIBRARY, None, self.fx.roots, now=0.0)
        assert [a.path for a in plan.actions] == [str(dest)]
        assert plan.freed_bytes == 0
        assert plan.torrents == []

    def test_library_only_skips_sole_copy(self):
        dest_dir = self.fx.library / "样片 (2026)"
        dest_dir.mkdir()
        dest = dest_dir / "only.mkv"
        dest.write_bytes(b"y" * 10)
        versions = self.build([{"id": 1, "status": True, "src": "", "dest": str(dest)}], [], [])
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_LIBRARY, None, self.fx.roots, now=0.0)
        assert plan.actions == []
        assert plan.skipped

    def test_full_blocks_torrent_with_foreign_media(self):
        src_dir, src, dest = self.fx.add_version("PACK")
        other = src_dir / "Another.Movie.2020.mkv"
        other.write_bytes(b"z" * 5)
        versions = self.build([{"id": 1, "status": True, "src": str(src), "dest": str(dest), "download_hash": "zz"}],
                              [], [tor("p", src_dir)])
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_FULL, None, self.fx.roots, now=0.0)
        assert plan.actions == []
        assert plan.torrents == []
        assert plan.skipped

    def test_untraced_zvideo_file_never_deleted(self):
        dest_dir = self.fx.library / "样片 (2026)"
        dest_dir.mkdir()
        stray = dest_dir / "stray.mkv"
        stray.write_bytes(b"s")
        versions = self.build([], [], [], None) if False else W.build_versions(
            self.entry, [], [], [], self.fx.roots, self.fx.index, lambda t: [], zvideo_files=[str(stray)])
        assert len(versions) == 1
        assert not versions[0].traced
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_FULL, None, self.fx.roots, now=0.0)
        assert plan.actions == []

    def test_frozen_plan_detects_swapped_file(self):
        src_dir, src, dest = self.fx.add_version("WEB")
        versions = self.build([{"id": 1, "status": True, "src": str(src), "dest": str(dest)}], [], [tor("t", src_dir)])
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_LIBRARY, None, self.fx.roots, now=0.0)
        host = FakeHost([tor("t", src_dir)])
        assert W.verify_frozen(plan, host, now=10.0) == []
        # 预览后库入口被换成了另一份文件（例如洗版覆盖）
        os.unlink(dest)
        dest.write_bytes(b"x" * 1000)
        problems = W.verify_frozen(plan, host, now=10.0)
        assert problems
        result = W.execute_plan(plan, host, now=10.0)
        assert result["status"] == "aborted"
        assert dest.exists()

    def test_plan_expires(self):
        src_dir, src, dest = self.fx.add_version("WEB")
        versions = self.build([{"id": 1, "status": True, "src": str(src), "dest": str(dest)}], [], [])
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_LIBRARY, None, self.fx.roots, now=0.0)
        assert W.verify_frozen(plan, FakeHost([]), now=W.PLAN_TTL + 1)

    def test_execute_library_then_full(self):
        src_dir, src, dest = self.fx.add_version("WEB")
        torrents = [tor("t1", src_dir), tor("t2", src_dir, "站点B")]
        transfers = [{"id": 9, "status": True, "src": str(src), "dest": str(dest), "download_hash": "t1"}]
        host = FakeHost(torrents)
        versions = self.build(transfers, [], torrents)
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_LIBRARY, None, self.fx.roots, now=0.0)
        result = W.execute_plan(plan, host, now=1.0)
        assert result["status"] == "done"
        assert not dest.exists()
        assert src.exists()
        assert len(host.torrents) == 2  # 继续做种
        # 再真删除剩下的
        versions = self.build(transfers, [], torrents)
        plan = W.make_plan(self.entry.key, "样片", versions, W.MODE_FULL, None, self.fx.roots, now=2.0)
        assert plan.freed_bytes == 1000
        result = W.execute_plan(plan, host, now=3.0, wait_seconds=1, poll=0)
        assert result["status"] == "done", result
        assert not src.exists()
        assert host.torrents == {}
        assert sorted(result["torrents_removed"]) == ["t1", "t2"]
        assert host.records_deleted == [9]
        assert result["freed_bytes"] == 1000
        assert "1 部/季" in W.summarize([result])


class FakeHost(W.Host):
    def __init__(self, torrents):
        self.torrents = {t.hash: t for t in torrents}
        self.records_deleted = []
        super().__init__(delete_path=self._delete_path, list_torrents=self._list, delete_torrents=self._del_t,
                         delete_records=self._del_r, sleep=lambda s: None)

    def _delete_path(self, path, role):
        os.unlink(path)
        return True

    def _list(self, hashes):
        return [self.torrents[h] for h in hashes if h in self.torrents]

    def _del_t(self, hashes):
        for h in hashes:
            t = self.torrents.pop(h, None)
            if t and os.path.exists(t.content_path):
                for root, _d, files in os.walk(t.content_path):
                    for f in files:
                        os.unlink(os.path.join(root, f))
        return True

    def _del_r(self, ids):
        self.records_deleted.extend(ids)
        return len(ids)


def _list_media(path):
    if os.path.isfile(path):
        return [path]
    out = []
    for root, _d, files in os.walk(path):
        out.extend(os.path.join(root, f) for f in files)
    return out


class PathTest:
    def test_season_of_path(self):
        assert W.season_of_path("/tv/黑镜 (2011)/Season 3/黑镜 - S03E01.mkv") == 3
        assert W.season_of_path("/c/Black.Mirror.S04.2160p/Black.Mirror.S04E02.mkv") == 4
        assert W.season_of_path("/c/Some.Movie.2026.2160p.mkv") is None

    def test_parse_seasons(self):
        assert W.parse_seasons("S01-S03") == {1, 2, 3}
        assert W.parse_seasons("S02") == {2}
        assert W.parse_seasons("") == set()

    def test_from_zspace(self):
        maps = [pathmap.Mapping("/downloads", "/sata1/my/data/downloads")]
        assert pathmap.from_zspace("/sata1/my/data/downloads/movies/a.mkv", maps) == "/downloads/movies/a.mkv"
        assert pathmap.from_zspace("/sata2/x", maps) is None


class FakeCli:
    def __init__(self):
        self.seen = {"movie": [movie_row()]}
        self.fail = set()

    def libraries(self):
        return [{"id": "movie", "name": "电影"}, {"id": "tv", "name": "电视剧"}]

    def seen_collections(self, library_id):
        if library_id in self.fail:
            raise CliError("E_NET", "boom")
        return list(self.seen.get(library_id, []))

    def collection_info(self, library_id, cid):
        return {"is_seen": 1, "season": 0}

    def collection_videos(self, library_id, cid):
        return {"video_list": []}


class Log:
    def info(self, *a): pass
    def warning(self, *a): pass
    def error(self, *a): pass


class ServiceTest:
    def setup_method(self):
        self.fx = Fixture()
        self.src_dir, self.src, self.dest = self.fx.add_version("WEB")
        self.torrents = [tor("t1", self.src_dir)]
        self.fake = FakeHost(self.torrents)
        self.now = [0.0]
        self.store = {}
        self.notes = []
        transfers = [{"id": 1, "status": True, "src": str(self.src), "dest": str(self.dest), "download_hash": "t1"}]
        host = WatchHost(
            transfers_by_tmdb=lambda tid: transfers if tid == 11 else [],
            downloads_by_tmdb=lambda tid: [],
            torrents=lambda: list(self.fake.torrents.values()),
            torrent_files=lambda t: _list_media(t.content_path),
            roots=lambda: self.fx.roots,
            exec_host=lambda: self.fake,
            rescan=lambda paths, why: [],
        )
        self.cli = FakeCli()
        self.svc = WatchService(self.cli, WatchSettings(enabled=True, auto_mode=W.MODE_FULL, buffer_days=7, auto_since=-1), host,
                                mappings=lambda: [], log=Log(), notify=lambda t, x: self.notes.append(x),
                                load=lambda k: self.store.get(k), save=self.store.__setitem__,
                                clock=lambda: self.now[0], sleep=lambda s: None)

    def teardown_method(self):
        self.fx.cleanup()

    def test_auto_respects_buffer_and_unseen(self):
        self.svc.run_auto()
        assert self.src.exists()  # 缓冲期内
        self.now[0] = 3 * DAY
        self.cli.seen = {}  # 取消已看
        self.svc.run_auto()
        self.now[0] = 30 * DAY
        self.svc.run_auto()
        assert self.src.exists() and self.dest.exists()
        self.cli.seen = {"movie": [movie_row()]}  # 再标已看，缓冲期重新计
        self.svc.run_auto()
        self.now[0] = 36 * DAY
        self.svc.run_auto()
        assert self.src.exists()
        self.now[0] = 37 * DAY
        out = self.svc.run_auto()
        assert out["results"][0]["status"] == "done", out
        assert not (self.src.exists() or self.dest.exists())
        assert self.fake.torrents == {}
        assert self.svc.state["movie:11"]["done_at"]
        assert self.notes

    def test_auto_off_by_default(self):
        assert WatchSettings.from_config({}).auto_mode == W.MODE_NONE
        self.svc.settings = WatchSettings(enabled=True)
        self.now[0] = 100 * DAY
        self.svc.run_auto()
        self.now[0] = 200 * DAY
        self.svc.run_auto()
        assert self.src.exists() and self.dest.exists()

    def test_read_failure_is_not_unseen(self):
        self.svc.sync()
        self.cli.fail = {"movie"}
        self.now[0] = 10 * DAY
        self.svc.sync()
        assert "movie:11" in self.svc.state
        assert self.svc.state["movie:11"]["first_seen_at"] == 0.0

    def test_manual_preview_then_execute_library(self):
        self.svc.sync()
        plan = self.svc.preview("movie:11", W.MODE_LIBRARY)
        assert plan["freed_bytes"] == 0
        result = self.svc.execute(plan["id"])
        assert result["status"] == "done"
        assert not self.dest.exists()
        assert self.src.exists()
        with pytest.raises(KeyError):  # 清单只能用一次
            self.svc.execute(plan["id"])

    def test_run_keys_only_touches_given_items(self):
        other_dir, other_src, other_dest = self.fx.add_version("OTHER")
        self.cli.seen = {"movie": [movie_row()]}
        self.svc.sync()
        results = self.svc.run_keys(["movie:11"], W.MODE_LIBRARY)
        assert len(results) == 1
        with pytest.raises(KeyError):
            self.svc.run_keys(["movie:999"], W.MODE_LIBRARY)


class SidecarTest:
    def test_sidecars_removed_only_when_no_media_left(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("WEB")
            (dest.parent / "movie.nfo").write_text("x")
            (dest.parent / "poster.jpg").write_bytes(b"p")
            versions = W.build_versions(entry, [{"id": 1, "status": True, "src": str(src), "dest": str(dest)}],
                                        [], [], fx.roots, fx.index, lambda t: [])
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_LIBRARY, None, fx.roots, now=0.0)
            assert sorted(os.path.basename(a.path) for a in plan.actions) == \
                             sorted([dest.name, "movie.nfo", "poster.jpg"])
            # 同目录还有别的视频（例如另一个没被选中的版本）时不清附属文件
            other = dest.parent / "other.mkv"
            other.write_bytes(b"o")
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_LIBRARY, None, fx.roots, now=0.0)
            assert [os.path.basename(a.path) for a in plan.actions] == [dest.name]
        finally:
            fx.cleanup()


class AutoSinceTest:
    def test_items_seen_before_auto_enabled_never_auto_deleted(self):
        movie = W.watched_entries(movie_row(), dict, dict)[0]
        other = W.watched_entries(movie_row(tmdb_id=12, collection_id="c2"), dict, dict)[0]
        state, _, _ = W.track({}, [movie], now=0.0)            # 插件早就读到的已看
        state, _, _ = W.track(state, [movie, other], now=10 * DAY)  # 开自动删除之后新看的
        since = 5 * DAY
        assert W.due_keys(state, 1, now=100 * DAY, since=since) == ["movie:12"]
        assert W.due_keys(state, 1, now=100 * DAY, since=0) == ["movie:11", "movie:12"]

    def test_settings_stamp(self):
        old = WatchSettings()
        new = WatchSettings.from_config({"watched_auto_mode": "full", "watched_buffer_days": 0}).stamped(old, 123.0)
        assert new.auto_since == 123.0
        assert new.buffer_days == 1.0  # 至少 1 天
        same = WatchSettings.from_config(new.to_config()).stamped(new, 999.0)
        assert same.auto_since == 123.0
        off = WatchSettings.from_config({"watched_auto_mode": "none"}).stamped(same, 1000.0)
        assert off.auto_since == 0.0

    def test_auto_without_since_does_nothing(self):
        # 旧配置里有删除选项但没有开启时间（例如从 0.2.0 早期版本升级）：不自动删
        s = WatchSettings.from_config({"watched_auto_mode": "library"})
        assert s.auto_since == 0.0


class UnknownSeasonTest:
    """0.2.1：剧集里路径认不出季号的文件（蓝光原盘 BDMV/STREAM/*.m2ts）真删除默认跳过，需手动确认。"""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.complete = root / "downloads" / "complete"
        self.anime = root / "downloads" / "anime"
        self.complete.mkdir(parents=True)
        self.anime.mkdir(parents=True)
        self.roots = W.Roots(library=[str(self.anime)], download=[str(self.complete)])
        self.index = W.InodeIndex([str(root / "downloads")])
        self.entry = W.watched_entries(season_row(tmdb_id=76075), lambda: {"is_seen": 1, "season": 1}, dict)[0]

    def teardown_method(self):
        self.tmp.cleanup()

    def bdmv(self, discs=2, per=3):
        """原盘：complete 侧没有季号；库里在 Season 1/Disc N 下，同 inode。MP 记录是目录级、季文本 S01。"""
        content = self.complete / "[BDMV] Yuru Camp"
        transfers = []
        for d in range(1, discs + 1):
            src_dir = content / f"Vol.{d}" / "BDROM"
            dest_dir = self.anime / "摇曳露营△ (2018)" / "Season 1" / f"Disc {d}"
            for n in range(per):
                src = src_dir / "BDMV" / "STREAM" / f"0000{n}.m2ts"
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(b"b" * 100)
                dest = dest_dir / "BDMV" / "STREAM" / f"0000{n}.m2ts"
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.link(src, dest)
            transfers.append({"id": 100 + d, "status": True, "src": str(src_dir) + "/", "dest": str(dest_dir) + "/",
                              "seasons": "S01", "download_hash": "bd1"})
        return content, transfers

    def build(self, transfers, torrents, downloads=()):
        return W.build_versions(self.entry, transfers, list(downloads), torrents, self.roots, self.index,
                                lambda t: _list_media(t.content_path), exact_links=True)

    def test_bdmv_full_delete_skipped_and_listed_by_default(self):
        content, transfers = self.bdmv()
        versions = self.build(transfers, [tor("bd1", content)])
        assert len(versions) == 1
        unknown = [f for f in versions[0].files if f.season_unknown]
        assert len(unknown) == 6
        assert all(f.role == "download" for f in unknown)  # 库入口在 Season 1 下，认得出
        plan = W.make_plan(self.entry.key, "摇曳露营△ 第 1 季", versions, W.MODE_FULL, None, self.roots, now=0.0)
        assert plan.actions == []
        assert plan.torrents == []  # 种子也不删
        assert plan.record_ids == []
        assert plan.freed_bytes == 0
        assert any("认不出季号" in s for s in plan.skipped)
        assert plan.unknown_season["count"] == 6
        assert plan.unknown_season["season"] == 1
        assert plan.unknown_season["size"] == 600
        assert not plan.unknown_season["confirmed"]
        assert len(plan.unknown_season["dirs"]) == 2

    def test_bdmv_full_delete_with_confirmation(self):
        content, transfers = self.bdmv()
        versions = self.build(transfers, [tor("bd1", content)])
        plan = W.make_plan(self.entry.key, "摇曳露营△ 第 1 季", versions, W.MODE_FULL, None, self.roots, now=0.0,
                           confirm_unknown_season=True)
        assert len(plan.actions) == 12
        assert [t.hash for t in plan.torrents] == ["bd1"]
        assert plan.record_ids == [101, 102]
        assert plan.freed_bytes == 600
        assert plan.unknown_season["confirmed"]
        # 确认与否是清单的一部分，不同确认状态出的清单 id 不同
        plain = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0)
        assert plain.id != plan.id

    def test_bdmv_library_only_unaffected(self):
        content, transfers = self.bdmv()
        versions = self.build(transfers, [tor("bd1", content)])
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_LIBRARY, None, self.roots, now=0.0)
        assert len(plan.actions) == 6
        assert all("/Season 1/" in a.path for a in plan.actions)
        assert plan.unknown_season == {}

    def test_library_entry_without_season_skipped_in_library_mode(self):
        # 库入口本身也认不出季号（例如库里放成了「剧名/Disc 1/…」）：只移出库同样跳过并列出
        src = self.complete / "Pack" / "BDMV" / "STREAM" / "00001.m2ts"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"c" * 10)
        dest = self.anime / "摇曳露营△ (2018)" / "Disc 1" / "BDMV" / "STREAM" / "00001.m2ts"
        dest.parent.mkdir(parents=True)
        os.link(src, dest)
        transfers = [{"id": 7, "status": True, "src": str(src.parents[2]) + "/", "dest": str(dest.parents[2]) + "/",
                      "seasons": "S01", "download_hash": "p1"}]
        versions = self.build(transfers, [tor("p1", self.complete / "Pack")])
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_LIBRARY, None, self.roots, now=0.0)
        assert plan.actions == []
        assert any("认不出季号" in s for s in plan.skipped)
        assert plan.unknown_season["count"] == 1
        confirmed = W.make_plan(self.entry.key, "x", versions, W.MODE_LIBRARY, None, self.roots, now=0.0,
                                confirm_unknown_season=True)
        assert [a.path for a in confirmed.actions] == [str(dest)]

    def test_mixed_torrent_whole_version_skipped(self):
        # 同一个种子：一部分文件有季号（单文件记录 S01E01），一部分是原盘目录（目录级记录，认不出季号）
        pack = self.complete / "Show.S01.Complete"
        ep = pack / "Show.S01E01.1080p.mkv"
        ep.parent.mkdir(parents=True)
        ep.write_bytes(b"e" * 50)
        ep_dest = self.anime / "Show (2018)" / "Season 1" / "Show - S01E01.mkv"
        ep_dest.parent.mkdir(parents=True)
        os.link(ep, ep_dest)
        disc = pack / "Disc1" / "BDMV" / "STREAM" / "00001.m2ts"
        disc.parent.mkdir(parents=True)
        disc.write_bytes(b"d" * 70)
        disc_dest = self.anime / "Show (2018)" / "Season 1" / "Disc 1" / "BDMV" / "STREAM" / "00001.m2ts"
        disc_dest.parent.mkdir(parents=True)
        os.link(disc, disc_dest)
        transfers = [{"id": 3, "status": True, "src": str(ep), "dest": str(ep_dest), "seasons": "S01", "download_hash": "m1"},
                     {"id": 4, "status": True, "src": str(pack / "Disc1") + "/", "dest": str(disc_dest.parents[2]) + "/",
                      "seasons": "S01", "download_hash": "m1"}]
        versions = self.build(transfers, [tor("m1", pack)])
        assert len(versions) == 1
        assert [f.path for f in versions[0].files if f.season_unknown] == [str(disc)]
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0)
        assert (plan.actions, plan.torrents) == ([], [])  # 有季号的那部分也不删
        assert any("认不出季号" in s for s in plan.skipped)
        assert plan.unknown_season["count"] == 1
        confirmed = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0,
                                confirm_unknown_season=True)
        assert len(confirmed.actions) == 4
        assert [t.hash for t in confirmed.torrents] == ["m1"]

    def test_untraced_extra_in_torrent_still_foreign_even_if_confirmed(self):
        # 种子里没被 MP 记录覆盖、也认不出季号的视频（花絮等）：照旧按「种子里有别的视频」拦，确认也不纳入
        content, transfers = self.bdmv(discs=1, per=2)
        (content / "Extras").mkdir()
        (content / "Extras" / "NCOP.mkv").write_bytes(b"n" * 5)
        versions = self.build(transfers, [tor("bd1", content)])
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0,
                           confirm_unknown_season=True)
        assert (plan.actions, plan.torrents) == ([], [])
        assert any("不属于这部片/这季" in s for s in plan.skipped)

    def test_regular_seasoned_show_unchanged(self):
        # 黑镜式：complete 里文件名带 S03Exx，库在 Season 3；种子里还有别的季 -> 照旧按 foreign_media 拦
        self.entry = W.SeenEntry(library_id="tv", library_name="电视剧", collection_id="s3", title="黑镜",
                                 kind="season", tmdb_id=42009, season=3)
        pack = self.complete / "Black.Mirror.S03.2160p"
        pack.mkdir()
        transfers = []
        for n in (1, 2):
            src = pack / f"Black.Mirror.S03E0{n}.2160p.mkv"
            src.write_bytes(b"m" * 100)
            dest = self.anime / "黑镜 (2011)" / "Season 3" / f"黑镜 - S03E0{n}.mkv"
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.link(src, dest)
            transfers.append({"id": n, "status": True, "src": str(src), "dest": str(dest), "seasons": "S03",
                              "download_hash": "bm3"})
        versions = self.build(transfers, [tor("bm3", pack)])
        assert not any(f.season_unknown for v in versions for f in v.files)
        plan = W.make_plan(self.entry.key, "黑镜 第 3 季", versions, W.MODE_FULL, None, self.roots, now=0.0)
        assert len(plan.actions) == 4
        assert [t.hash for t in plan.torrents] == ["bm3"]
        assert plan.unknown_season == {}
        assert plan.skipped == []
        # 种子里混了别的季：照旧整版本不删（foreign_media），不当成认不出季号
        (pack / "Black.Mirror.S04E01.2160p.mkv").write_bytes(b"o")
        versions = self.build(transfers, [tor("bm3", pack)])
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0,
                           confirm_unknown_season=True)
        assert (plan.actions, plan.torrents) == ([], [])
        assert any("不属于这部片/这季" in s for s in plan.skipped)

    def test_per_file_record_season_text_counts_as_certain(self):
        # 单文件记录、路径没季号但 MP 记录的季文本正好是这一季（字幕组「第二季」命名）：算确定
        self.entry = W.SeenEntry(library_id="tv", library_name="动漫", collection_id="s2", title="摇曳露营△",
                                 kind="season", tmdb_id=76075, season=2)
        pack = self.complete / "[云光字幕组]摇曳露营△ 第二季"
        pack.mkdir()
        src = pack / "[云光字幕组]摇曳露营△ 第二季 Yuru Camp Season 2-[ 9 ][1080p].mp4"
        src.write_bytes(b"y" * 30)
        dest = self.anime / "摇曳露营△ (2018)" / "Season 2" / "摇曳露营△ - S02E09.mp4"
        dest.parent.mkdir(parents=True)
        os.link(src, dest)
        transfers = [{"id": 1313, "status": True, "src": str(src), "dest": str(dest), "seasons": "S02",
                      "download_hash": "yc2"}]
        versions = self.build(transfers, [tor("yc2", pack)])
        assert not any(f.season_unknown for v in versions for f in v.files)
        plan = W.make_plan(self.entry.key, "x", versions, W.MODE_FULL, None, self.roots, now=0.0)
        assert len(plan.actions) == 2

    def test_movie_unaffected(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("WEB")
            versions = W.build_versions(entry, [{"id": 1, "status": True, "src": str(src), "dest": str(dest),
                                                 "download_hash": "t"}], [], [tor("t", src_dir)], fx.roots, fx.index,
                                        lambda t: _list_media(t.content_path), exact_links=True)
            assert not any(f.season_unknown for v in versions for f in v.files)
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_FULL, None, fx.roots, now=0.0)
            assert len(plan.actions) == 2
            assert plan.unknown_season == {}
        finally:
            fx.cleanup()


class UnknownSeasonServiceTest:
    """自动删除永远跳过认不出季号的版本；手动只有显式确认才纳入。"""

    def setup_method(self):
        self.case = UnknownSeasonTest()
        self.case.setup_method()
        self.content, transfers = self.case.bdmv(discs=1, per=2)
        self.fake = FakeHost([tor("bd1", self.content)])
        self.now = [0.0]
        host = WatchHost(
            transfers_by_tmdb=lambda tid: transfers if tid == 76075 else [],
            downloads_by_tmdb=lambda tid: [],
            torrents=lambda: list(self.fake.torrents.values()),
            torrent_files=lambda t: _list_media(t.content_path),
            roots=lambda: self.case.roots,
            exec_host=lambda: self.fake,
            rescan=lambda paths, why: [],
        )
        cli = FakeCli()
        cli.seen = {"tv": [season_row(tmdb_id=76075)]}
        cli.collection_info = lambda lib, cid: {"is_seen": 1, "season": 1}
        self.svc = WatchService(cli, WatchSettings(enabled=True, auto_mode=W.MODE_FULL, buffer_days=1, auto_since=-1),
                                host, mappings=lambda: [], log=Log(), notify=lambda t, x: None,
                                load=lambda k: None, save=lambda k, v: None,
                                clock=lambda: self.now[0], sleep=lambda s: None)

    def teardown_method(self):
        self.case.teardown_method()

    def files(self):
        return sorted(str(p) for p in Path(self.case.tmp.name).rglob("*.m2ts"))

    def test_auto_delete_never_includes_unknown_season(self):
        before = self.files()
        self.svc.run_auto()
        self.now[0] = 30 * DAY
        out = self.svc.run_auto()
        assert out["results"] == []
        assert self.files() == before
        assert "bd1" in self.fake.torrents
        assert "认不出季号" in self.svc.state["tv:76075:S1"].get("last_error", "")

    def test_manual_preview_requires_explicit_confirmation(self):
        self.svc.sync()
        plain = self.svc.preview("tv:76075:S1", W.MODE_FULL)
        assert (plain["actions"], plain["torrents"]) == ([], [])
        assert plain["unknown_season"]["count"] == 2
        confirmed = self.svc.preview("tv:76075:S1", W.MODE_FULL, confirm_unknown_season=True)
        assert len(confirmed["actions"]) == 4
        result = self.svc.execute(confirmed["id"])
        assert result["status"] == "done", result
        assert self.files() == []
        assert self.fake.torrents == {}

    def test_run_keys_default_skips(self):
        self.svc.sync()
        before = self.files()
        results = self.svc.run_keys(["tv:76075:S1"], W.MODE_FULL)
        assert results[0]["deleted"] == []
        assert self.files() == before
