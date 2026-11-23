"""0.2.3 删除安全：CodeRabbit 审查属实条目的回归测试（每条先在 0.2.2 上红，修完变绿）。"""

import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

from app.plugins.zspacevideo.core import watched as W
from app.plugins.zspacevideo.core.cli import CliError
from app.plugins.zspacevideo.core.watch_service import WatchHost, WatchService, WatchSettings

from .test_watched import DAY, FakeCli, FakeHost, Fixture, Log, _list_media, movie_row, season_row, tor


def full_plan(fx, entry, transfers, torrents, now=0.0):
    versions = W.build_versions(entry, transfers, [], torrents, fx.roots, fx.index,
                                lambda t: _list_media(t.content_path), exact_links=True)
    return W.make_plan(entry.key, "样片", versions, W.MODE_FULL, None, fx.roots, now=now)


class StuckHost(FakeHost):
    """qB 拒绝删任务（返回失败、任务还在）。"""

    def _del_t(self, hashes):
        return False


class BrokenReadHost(FakeHost):
    """删任务请求发出后，读回 qB 任务列表报错（网络断、qB 重启）。"""

    def __init__(self, torrents):
        super().__init__(torrents)
        self.calls = 0

    def _list(self, hashes):
        self.calls += 1
        if self.calls > 1:  # 第一次是执行前核对
            raise RuntimeError("qB 读不到")
        return super()._list(hashes)


class TorrentFailureTest:
    def setup_method(self):
        self.fx = Fixture()
        self.entry = W.watched_entries(movie_row(), dict, dict)[0]
        self.src_dir, self.src, self.dest = self.fx.add_version("WEB")
        self.transfers = [{"id": 9, "status": True, "src": str(self.src), "dest": str(self.dest), "download_hash": "t1"}]

    def teardown_method(self):
        self.fx.cleanup()

    def test_source_kept_when_qb_refuses_delete(self):
        torrents = [tor("t1", self.src_dir)]
        plan = full_plan(self.fx, self.entry, self.transfers, torrents)
        host = StuckHost(torrents)
        result = W.execute_plan(plan, host, now=1.0, wait_seconds=0, poll=0)
        assert result["status"] == "partial"
        assert "t1" in result["torrents_failed"]
        assert self.src.exists(), "qB 任务还在，做种源文件不能删"
        assert host.records_deleted == []

    def test_source_kept_when_qb_readback_fails(self):
        torrents = [tor("t1", self.src_dir)]
        plan = full_plan(self.fx, self.entry, self.transfers, torrents)

        class Host(BrokenReadHost):
            def _del_t(self, hashes):  # 请求发出了，但 qB 实际没删
                return True
        host = Host(torrents)
        result = W.execute_plan(plan, host, now=1.0, wait_seconds=0, poll=0)
        assert result["status"] == "partial"
        assert str(self.dest) in result["deleted"]  # 已完成的库入口删除要留在结果里
        assert self.src.exists()
        assert any("qB" in x for x in result["failed"])

    def test_refused_but_gone_counts_once(self):
        torrents = [tor("t1", self.src_dir)]
        plan = full_plan(self.fx, self.entry, self.transfers, torrents)

        class Host(FakeHost):
            def _del_t(self, hashes):  # 报失败，但实际删掉了
                FakeHost._del_t(self, hashes)
                return False
        result = W.execute_plan(plan, Host(torrents), now=1.0, wait_seconds=0, poll=0)
        assert result["torrents_removed"] == ["t1"]
        assert result["torrents_failed"] == []


class SidecarWhitelistTest:
    def test_unknown_file_keeps_whole_folder(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("WEB")
            (dest.parent / "movie.nfo").write_text("x")
            (dest.parent / "notes.pdf").write_bytes(b"p")
            versions = W.build_versions(entry, [{"id": 1, "status": True, "src": str(src), "dest": str(dest)}],
                                        [], [], fx.roots, fx.index, lambda t: [])
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_LIBRARY, None, fx.roots, now=0.0)
            assert [os.path.basename(a.path) for a in plan.actions] == [dest.name]
        finally:
            fx.cleanup()

    def test_known_sidecars_still_cleaned(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("WEB")
            for name in ("movie.nfo", "poster.jpg", "fanart.png", "样片.chs.srt", "样片.ass"):
                (dest.parent / name).write_bytes(b"s")
            versions = W.build_versions(entry, [{"id": 1, "status": True, "src": str(src), "dest": str(dest)}],
                                        [], [], fx.roots, fx.index, lambda t: [])
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_LIBRARY, None, fx.roots, now=0.0)
            assert len(plan.actions) == 6
        finally:
            fx.cleanup()


class LibraryOnlySurvivorTest:
    def test_abort_when_download_link_vanished_after_preview(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("WEB")
            versions = W.build_versions(entry, [{"id": 1, "status": True, "src": str(src), "dest": str(dest)}],
                                        [], [], fx.roots, fx.index, lambda t: [], exact_links=True)
            plan = W.make_plan(entry.key, "样片", versions, W.MODE_LIBRARY, None, fx.roots, now=0.0)
            assert [a.path for a in plan.actions] == [str(dest)]
            os.unlink(src)  # 预览后做种源被别处删掉，库里成了唯一一份
            result = W.execute_plan(plan, FakeHost([]), now=1.0)
            assert result["status"] == "aborted"
            assert dest.exists()
        finally:
            fx.cleanup()


class AmbiguousSeasonMarkTest:
    def test_one_mark_spanning_seasons_is_not_auto_deleted(self):
        videos = {"video_list": [{"file_path": "/x/样剧/Season 1/样剧 - S01E01.mkv"},
                                 {"file_path": "/x/样剧/Season 2/样剧 - S02E01.mkv"}]}
        entries = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 0}, lambda: videos)
        assert entries, "仍然列出来，可以手动删"
        state, _, _ = W.track({}, entries, now=0.0)
        assert W.due_keys(state, 1, now=100 * DAY) == []

    def test_single_inferred_season_still_auto(self):
        videos = {"video_list": [{"file_path": "/x/样剧/Season 3/样剧 - S03E01.mkv"}]}
        entries = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 0}, lambda: videos)
        state, _, _ = W.track({}, entries, now=0.0)
        assert W.due_keys(state, 1, now=100 * DAY) == ["tv:22:S3"]


class OtherSeasonLinkTest:
    def test_confirmation_never_reaches_other_season_link(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            complete, tv = root / "downloads" / "complete", root / "downloads" / "tv"
            src = complete / "Show.Disc" / "00001.m2ts"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"d" * 50)
            s1 = tv / "样剧" / "Season 1" / "00001.m2ts"
            s2 = tv / "样剧" / "Season 2" / "00001.m2ts"  # 同一份数据被误整理进第 2 季
            for p in (s1, s2):
                p.parent.mkdir(parents=True)
                os.link(src, p)
            roots = W.Roots(library=[str(tv)], download=[str(complete)])
            index = W.InodeIndex([str(root / "downloads")])
            entry = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 1}, dict)[0]
            transfers = [{"id": 1, "status": True, "src": str(src), "dest": str(s1), "seasons": "S01"}]
            versions = W.build_versions(entry, transfers, [], [], roots, index, lambda t: [], exact_links=True)
            for mode in (W.MODE_LIBRARY, W.MODE_FULL):
                plan = W.make_plan(entry.key, "样剧", versions, mode, None, roots, now=0.0, confirm_unknown_season=True)
                assert str(s2) not in [a.path for a in plan.actions], mode
        finally:
            tmp.cleanup()


class StaleSeenAutoTest:
    def test_entry_kept_after_read_failure_is_not_auto_deleted(self):
        fx = Fixture()
        try:
            src_dir, src, dest = fx.add_version("WEB")
            fake = FakeHost([tor("t1", src_dir)])
            transfers = [{"id": 1, "status": True, "src": str(src), "dest": str(dest), "download_hash": "t1"}]
            host = WatchHost(transfers_by_tmdb=lambda tid: transfers, downloads_by_tmdb=lambda tid: [],
                             torrents=lambda: list(fake.torrents.values()),
                             torrent_files=lambda t: _list_media(t.content_path), roots=lambda: fx.roots,
                             exec_host=lambda: fake, rescan=lambda p, w: [])
            now = [0.0]
            cli = FakeCli()
            store = {}
            svc = WatchService(cli, WatchSettings(enabled=True, auto_mode=W.MODE_FULL, buffer_days=7, auto_since=-1),
                               host, mappings=lambda: [], log=Log(), notify=lambda t, x: None,
                               load=store.get, save=store.__setitem__, clock=lambda: now[0], sleep=lambda s: None)
            svc.run_auto()
            now[0] = 30 * DAY
            cli.fail = {"movie"}  # 读不到这个分类（用户其实可能已经取消了已看）
            out = svc.run_auto()
            assert out["results"] == []
            assert src.exists() and dest.exists()
        finally:
            fx.cleanup()


class SampleNameTest:
    def test_unrelated_video_with_sample_in_title_blocks(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("PACK")
            (src_dir / "The.Sampler.2019.1080p.mkv").write_bytes(b"z" * 5)
            # 种子不在 MP 记录里（只靠同 inode 找到），种子里别的视频都算「不属于这部片」
            transfers = [{"id": 1, "status": True, "src": str(src), "dest": str(dest), "download_hash": "zz"}]
            plan = full_plan(fx, entry, transfers, [tor("p", src_dir)])
            assert plan.torrents == [], "种子里有别的片，整个版本不删"
        finally:
            fx.cleanup()

    def test_real_sample_still_ignored(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, dest = fx.add_version("PACK")
            (src_dir / "Sample").mkdir()
            (src_dir / "Sample" / "pack-sample.mkv").write_bytes(b"z" * 5)
            transfers = [{"id": 1, "status": True, "src": str(src), "dest": str(dest), "download_hash": "zz"}]
            plan = full_plan(fx, entry, transfers, [tor("p", src_dir)])
            assert [t.hash for t in plan.torrents] == ["p"]
        finally:
            fx.cleanup()


class RecordScopeTest:
    def test_directory_record_spanning_seasons_kept(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            complete, tv = root / "downloads" / "complete", root / "downloads" / "tv"
            pack = complete / "Show.S01-S02"
            files = {}
            for s in (1, 2):
                src = pack / f"Show.S0{s}E01.mkv"
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(b"e" * 10)
                dest = tv / "样剧" / f"Season {s}" / f"样剧 - S0{s}E01.mkv"
                dest.parent.mkdir(parents=True)
                os.link(src, dest)
                files[s] = (src, dest)
            roots = W.Roots(library=[str(tv)], download=[str(complete)])
            index = W.InodeIndex([str(root / "downloads")])
            entry = W.watched_entries(season_row(), lambda: {"is_seen": 1, "season": 1}, dict)[0]
            transfers = [{"id": 7, "status": True, "src": str(pack) + "/", "dest": str(tv / "样剧") + "/",
                          "seasons": "S01-S02"}]
            versions = W.build_versions(entry, transfers, [], [], roots, index, lambda t: [], exact_links=True)
            plan = W.make_plan(entry.key, "样剧", versions, W.MODE_FULL, None, roots, now=0.0)
            assert str(files[1][1]) in [a.path for a in plan.actions]
            assert plan.record_ids == [], "第 2 季的文件还靠这条整理记录追溯"
        finally:
            tmp.cleanup()


class NonLocalStorageTest:
    def test_remote_destination_not_planned_locally(self):
        fx = Fixture()
        try:
            entry = W.watched_entries(movie_row(), dict, dict)[0]
            src_dir, src, _ = fx.add_version("WEB", link=False)
            # 整理到网盘；本地恰好有一个同路径的无关文件（不是这次整理的产物）
            dest = fx.library / "样片 (2026)" / "样片 (2026) - WEB.mkv"
            dest.parent.mkdir()
            dest.write_bytes(b"o" * 7)
            (fx.library / "other.mkv").write_bytes(b"k")
            os.link(dest, fx.complete / "keep-other-link.mkv")  # 本地文件自己有做种源，只移库本来可以删
            transfers = [{"id": 1, "status": True, "src": str(src), "dest": str(dest),
                          "src_storage": "local", "dest_storage": "alipan"}]
            versions = W.build_versions(entry, transfers, [], [], fx.roots, fx.index, lambda t: [], exact_links=True)
            for mode in (W.MODE_LIBRARY, W.MODE_FULL):
                plan = W.make_plan(entry.key, "样片", versions, mode, None, fx.roots, now=0.0)
                assert str(dest) not in [a.path for a in plan.actions], mode
        finally:
            fx.cleanup()


class TransferEventAuthTest:
    def test_cli_error_at_event_alerts(self):
        from .test_core import CaptureLog, FakeVideoCli, LIBS, MOUNTINFO
        from app.plugins.zspacevideo.core.service import Service, Settings

        class ExpiredCli(FakeVideoCli):
            def libraries(self):
                raise CliError("E_OAUTH", "授权已失效")

        notes = []
        settings = Settings(enabled=True, quiet_seconds=0, max_wait_seconds=0,
                            library_dirs="\n".join(f"{x.id} = {d}" for x in LIBS for d in x.dirs))
        svc = Service(ExpiredCli(), settings, log=CaptureLog(), notify=lambda t, m: notes.append((t, m)),
                      mountinfo_reader=lambda: MOUNTINFO, sleep=lambda s: None, poll_interval=0)
        assert svc.on_transfer("/downloads/anime/x") == []
        assert notes and "授权" in notes[0][1]


class QbDuplicateHashTest:
    def test_hash_on_two_clients_is_refused(self, monkeypatch):
        if "app.sdk.logging" not in sys.modules:
            for name in ("app.sdk", "app.sdk.logging"):
                monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
            sys.modules["app.sdk.logging"].logger = Log()
        from app.plugins.zspacevideo import host as H

        class Client:
            def __init__(self):
                self.deleted = []

            def get_torrents(self, ids=None):
                return [{"hash": h} for h in ids], False

            def delete_torrents(self, delete_file, ids):
                self.deleted.extend(ids)
                return True

        a, b = Client(), Client()
        qb = object.__new__(H.QbAdapter)
        qb._clients = lambda: [a, b]
        assert qb.delete(["h1"]) is False
        assert a.deleted == [] and b.deleted == []
