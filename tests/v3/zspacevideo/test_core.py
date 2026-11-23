"""单测：路径映射、分类命中、去抖合并、授权码不落盘不进日志不进参数/环境变量。

只依赖插件的 core/ 纯逻辑，不需要 MoviePilot：python3 -m pytest tests 即可。
"""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.plugins.zspacevideo.core import pathmap
from app.plugins.zspacevideo.core.batcher import Batcher
from app.plugins.zspacevideo.core.cli import Binary, Cli, CliError, Connection, LoginSession
from app.plugins.zspacevideo.core.router import Library, Target, parse_manual_dirs, read_zvideo_dirs, resolve_targets
from app.plugins.zspacevideo.core.service import Service, Settings

MOUNTINFO = (
    "7904 3421 0:64 /sata1/example-user/data/downloads /downloads rw,nosuid,nodev,relatime - "
    "zfuse.zfsv3 zfsv3 rw,user_id=0,group_id=0,default_permissions,allow_other\n"
    "7906 3421 0:77 /appstore/media/moviepilot/config /config rw,relatime - btrfs /dev/nvme1n1p4 rw\n"
    "7905 3421 9:1 /sqlite/zvideo /zvideo ro,noatime - ext4 /dev/md1 rw\n"
)

LIBS = [
    Library("movie", "电影", ["/sata1/my/data/downloads/movies", "/sata1/my/data/downloads/tv"], True),
    Library("tv", "电视剧", ["/sata1/my/data/downloads/movies", "/sata1/my/data/downloads/tv"], True),
    Library("anime", "动漫", ["/sata1/my/data/downloads/anime"]),
    Library("variety", "综艺", ["/sata1/my/data/downloads/variety"]),
    Library("docu", "纪录片", ["/sata1/my/data/downloads/docu"]),
]


class PathMapTest:
    def test_infer_from_mountinfo_only_zfuse(self):
        maps = pathmap.infer_mappings(MOUNTINFO)
        assert len(maps) == 1
        assert maps[0].container == "/downloads"
        assert maps[0].zspace == "/sata1/my/data/downloads"

    def test_mountinfo_octal_escape(self):
        text = "1 2 0:1 /sata1/u/data/a\\040b /media\\040x rw - zfuse.zfsv3 z rw\n"
        maps = pathmap.infer_mappings(text)
        assert maps[0].container == "/media x"
        assert maps[0].zspace == "/sata1/my/data/a b"

    def test_to_zspace(self):
        maps = pathmap.infer_mappings(MOUNTINFO)
        assert pathmap.to_zspace("/downloads/tv/黑镜 (2011)/Season 7", maps) == \
                         "/sata1/my/data/downloads/tv/黑镜 (2011)/Season 7"
        assert pathmap.to_zspace("/downloads", maps) == "/sata1/my/data/downloads"
        assert pathmap.to_zspace("/config/x", maps) is None
        # 前缀相似但不是同一段：/downloads2 不应命中 /downloads
        assert pathmap.to_zspace("/downloads2/a", maps) is None

    def test_longest_prefix_manual(self):
        maps = pathmap.parse_manual("""
        # 注释
        /media => /sata1/my/data
        /media/tv => /sata2/my/data/tv
        """)
        assert pathmap.to_zspace("/media/tv/a", maps) == "/sata2/my/data/tv/a"
        assert pathmap.to_zspace("/media/movies/a", maps) == "/sata1/my/data/movies/a"

    def test_manual_bad(self):
        with pytest.raises(ValueError):
            pathmap.parse_manual("/a -> /b")
        with pytest.raises(ValueError):
            pathmap.parse_manual("relative => /b")
        with pytest.raises(ValueError):
            pathmap.normalize("/a/../../etc")

    def test_zfuse_to_zspace(self):
        assert pathmap.zfuse_to_zspace("/tmp/zfsv3/sata1/example-user/data/downloads/anime") == \
                         "/sata1/my/data/downloads/anime"
        assert pathmap.zfuse_to_zspace("/sata1/my/data/x") is None

    def test_merge_paths(self):
        assert pathmap.merge_paths(["/a/b/c", "/a/b", "/a/bc", "/a/b/"]) == ["/a/b", "/a/bc"]


class RouterTest:
    def test_shared_smart_libraries_both_hit(self):
        targets = resolve_targets("/sata1/my/data/downloads/tv/黑镜 (2011)", LIBS)
        assert {t.library_id for t in targets} == {"movie", "tv"}
        assert all(t.library_dir.endswith("/tv") for t in targets)

    def test_anime_only(self):
        targets = resolve_targets("/sata1/my/data/downloads/anime/紫川 (2021)", LIBS)
        assert [t.library_id for t in targets] == ["anime"]

    def test_outside_any_library(self):
        assert resolve_targets("/sata1/my/data/downloads/complete/x", LIBS) == []
        assert resolve_targets("/sata1/my/data/downloads/animex/x", LIBS) == []

    def test_manual_dirs(self):
        dirs = parse_manual_dirs("动漫 = /sata1/my/data/downloads/anime\ndocu = /x", LIBS)
        assert dirs == {"anime": ["/sata1/my/data/downloads/anime"], "docu": ["/x"]}
        with pytest.raises(ValueError):
            parse_manual_dirs("不存在 = /x", LIBS)

    def test_read_zvideo_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "zvideo.db")
            conn = sqlite3.connect(db)
            conn.execute("create table zvideo_classification_file (id integer, user_name text, "
                         "classification_id text, path text, created_at int, updated_at int)")
            conn.executemany("insert into zvideo_classification_file values (?,?,?,?,0,0)", [
                (1, "u", "movie", "/tmp/zfsv3/sata1/u/data/downloads/movies"),
                (2, "u", "tv", "/tmp/zfsv3/sata1/u/data/downloads/movies"),
                (3, "u", "anime", "/tmp/zfsv3/sata1/u/data/downloads/anime"),
                (4, "other", "anime", "/tmp/zfsv3/sata1/other/data/x"),
            ])
            conn.commit()
            conn.close()
            os.chmod(db, 0o444)
            dirs = read_zvideo_dirs(db, owner="u")
            assert dirs["anime"] == ["/sata1/my/data/downloads/anime"]
            assert dirs["tv"] == ["/sata1/my/data/downloads/movies"]


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def tgt(lib, path):
    return Target(lib, lib, f"/r/{lib}", path)


class BatcherTest:
    def test_debounce_merges_same_library(self):
        clock = FakeClock()
        b = Batcher(quiet=60, max_wait=300, clock=clock)
        for ep in range(10):
            b.add(tgt("tv", "/r/tv/剧A/Season 1"), source="剧A")
            clock.t += 5
        assert b.pop_due() == []  # 还在安静期
        clock.t += 61
        batches = b.pop_due()
        assert len(batches) == 1
        assert batches[0].paths == ["/r/tv/剧A/Season 1"]
        assert batches[0].sources == ["剧A"]
        assert b.pending_count() == 0

    def test_max_wait_caps_continuous_stream(self):
        clock = FakeClock()
        b = Batcher(quiet=60, max_wait=300, clock=clock)
        for _ in range(40):
            b.add(tgt("tv", "/r/tv/x"))
            clock.t += 10  # 一直不安静
            if b.pop_due():
                break
        assert clock.t - 1000.0 <= 310

    def test_libraries_separate_and_subpath_merge(self):
        clock = FakeClock()
        b = Batcher(quiet=0, max_wait=0, clock=clock)
        b.add(tgt("tv", "/r/tv/A"))
        b.add(tgt("tv", "/r/tv/A/Season 1"))
        b.add(tgt("anime", "/r/anime/B"))
        batches = {x.library_id: x for x in b.pop_due()}
        assert batches["tv"].paths == ["/r/tv/A"]
        assert batches["anime"].paths == ["/r/anime/B"]

    def test_too_many_paths_falls_back_to_library_dir(self):
        clock = FakeClock()
        b = Batcher(quiet=0, max_wait=0, max_paths=3, clock=clock)
        for i in range(5):
            b.add(tgt("tv", f"/r/tv/{i}"))
        assert b.pop_due()[0].paths == ["/r/tv"]

    def test_next_due(self):
        clock = FakeClock()
        b = Batcher(quiet=60, max_wait=300, clock=clock)
        assert b.next_due_in() is None
        b.add(tgt("tv", "/r/tv/A"))
        assert b.next_due_in() == 60


# ---------------------------------------------------------------------- 授权码安全
SECRET = "AuthCode-Very-Secret-1234567890"

FAKE_CLI = r'''#!{python}
import hashlib, json, os, sys
argv = sys.argv[1:]
home = os.environ["ZSPACE_CLI_HOME"]
log = os.path.join(home, "fake-argv.log")
with open(log, "a") as f:
    f.write(json.dumps({"argv": argv, "env": {k: v for k, v in os.environ.items() if k != "FAKE_EXPECT_SHA"}}) + "\n")
if "login" in argv:
    print(json.dumps({"event": "oauth_authorization", "url": "https://oauth.zconnect.cn/wbui/authorize?state=abc",
                      "expires_in": 180, "state_prefix": "abc", "code_input": "stdin"}), flush=True)
    print("请在 180 秒内完成网页授权", file=sys.stderr, flush=True)
    code = sys.stdin.readline().strip()
    # 模拟真实 CLI：只把令牌写进凭据文件，不写授权码
    if hashlib.sha256(code.encode()).hexdigest() == os.environ.get("FAKE_EXPECT_SHA", ""):
        with open(os.path.join(home, "credentials.json"), "w") as f:
            json.dump({"access_token": "tok", "refresh_token": "rt"}, f)
        print(json.dumps({"ok": True, "profile": "mp", "data": {"nas_id": "Z043…7QJA", "expires_at": 1, "backend": "file"}}))
        sys.exit(0)
    print(json.dumps({"ok": False, "error": {"code": "E_OAUTH", "message": "授权码不属于本次登录"}}), file=sys.stderr)
    sys.exit(1)
if "status" in argv:
    print(json.dumps({"ok": True, "data": {"logged_in": True, "expires_at": 1795441038, "nas_id": "Z043…7QJA"}}))
    sys.exit(0)
print(json.dumps({"ok": True, "data": []}))
'''


class FakeBinary(Binary):
    def __init__(self, path):
        self._p = Path(path)
        self.artifact = {"version": "test", "sha256": "x"}
        self.platform = "test"

    @property
    def path(self):
        return self._p

    def ensure(self):
        return self._p

    def status(self):
        return {"version": "test", "installed": True}


class CaptureLog:
    def __init__(self):
        self.lines = []

    def _add(self, msg):
        self.lines.append(str(msg))

    info = warning = error = debug = _add


def tree_contains(root, needle):
    hits = []
    for base, _, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            try:
                if needle.encode() in Path(p).read_bytes():
                    hits.append(p)
            except OSError:
                pass
    return hits


class AuthCodeSecrecyTest:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bin = root / "fake-cli"
        # 生产里子进程只拿到最小 PATH，假 CLI 用当前解释器的绝对路径，CI 沙箱里也能跑
        self.bin.write_text(FAKE_CLI.replace("{python}", sys.executable, 1))
        self.bin.chmod(0o700)
        self.home = root / "cli"
        self.cli = Cli(FakeBinary(self.bin), home=self.home)
        self.cli_env = self.cli.env
        # 测试专用：只给假 CLI 授权码的哈希，便于判断对错；其余与生产一致
        import hashlib
        digest = hashlib.sha256(SECRET.encode()).hexdigest()
        self.cli.env = lambda: {**self.cli_env(), "FAKE_EXPECT_SHA": digest}

    def teardown_method(self):
        self.tmp.cleanup()

    def test_code_only_via_stdin(self):
        log = CaptureLog()
        session = LoginSession(self.cli)
        info = session.start()
        assert info["url"].startswith("https://")
        assert session.active()
        result = session.submit(SECRET)
        assert result["nas_id"] == "Z043…7QJA"
        assert not session.active()
        # 1) 授权码没进任何文件（含 CLI 记录的 argv/env 日志、凭据文件）
        assert tree_contains(self.tmp.name, SECRET) == []
        # 2) 子进程 argv 与 env 里都没有授权码
        rows = [json.loads(x) for x in (self.home / "fake-argv.log").read_text().splitlines()]
        for row in rows:
            assert SECRET not in json.dumps(row["argv"])
            assert SECRET not in json.dumps(row["env"])
        # 3) 目录权限 0700
        assert oct(self.home.stat().st_mode & 0o777) == "0o700"
        # 4) 生产 env 不继承宿主环境变量
        assert set(self.cli_env()) == {"PATH", "HOME", "ZSPACE_CLI_HOME", "LANG"}
        assert log.lines == []

    def test_wrong_code_error_does_not_echo(self):
        session = LoginSession(self.cli)
        session.start()
        with pytest.raises(CliError) as ctx:
            session.submit("Wrong-Code-ABCDEFG")
        assert ctx.value.code == "E_OAUTH"
        assert "Wrong-Code-ABCDEFG" not in str(ctx.value)

    def test_submit_without_session_rejected(self):
        session = LoginSession(self.cli)
        with pytest.raises(CliError):
            session.submit(SECRET)

    def test_expired_session_rejected(self):
        clock = [0.0]
        session = LoginSession(self.cli, clock=lambda: clock[0])
        session.start()
        clock[0] = 181
        with pytest.raises(CliError):
            session.submit(SECRET)
        assert tree_contains(self.tmp.name, SECRET) == []

    def test_code_format_rejected_before_stdin(self):
        session = LoginSession(self.cli)
        session.start()
        with pytest.raises(CliError):
            session.submit("bad code with spaces\nand newline")
        session.cancel()

    def test_plugin_api_does_not_log_code(self):
        """模拟插件 API：成功和失败两条路径的日志里都没有授权码。"""
        log = CaptureLog()
        svc = Service(self.cli, Settings(enabled=False), log=log, notify=lambda *a: None)
        svc.login.start()
        svc.login.submit(SECRET)
        svc.login.start()
        try:
            svc.login.submit("Another-Secret-Code-999")
        except CliError as error:
            log.warning(f"授权失败：{error.code}")
        assert not any(SECRET in line or "Another-Secret-Code-999" in line for line in log.lines)


class ConnectionTest:
    def test_cloud_default(self):
        assert Connection().args() == ["--clear-host"]

    def test_lan_requires_http_host(self):
        assert Connection("lan", "http://nas.example.com:5055").args() == \
                         ["--host", "http://nas.example.com:5055", "--allow-insecure-http"]
        with pytest.raises(CliError):
            Connection("lan", "nas.example.com").args()
        with pytest.raises(CliError):
            Connection("lan", "http://x/;rm -rf").args()

    def test_only_whitelisted_actions(self):
        cli = Cli(FakeBinary("/bin/false"), home=Path(tempfile.mkdtemp()))
        for action in ("remove_dir", "delete", "create", "add_dirs", "scrape"):
            with pytest.raises(CliError):
                cli.video(action)


class BinaryTest:
    def test_rejects_wrong_hash(self):
        payload = b"not the real binary"

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            binary = Binary(Path(tmp), platform="linux-x64", opener=lambda *a, **k: Resp(payload))
            with pytest.raises(CliError):
                binary.ensure()
            assert os.listdir(tmp) == []

    def test_accepts_matching_hash(self):
        import hashlib
        payload = b"#!/bin/sh\necho ok\n"

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            binary = Binary(Path(tmp), platform="linux-x64", opener=lambda *a, **k: Resp(payload))
            binary.artifact = dict(binary.artifact, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
            path = binary.ensure()
            assert path.read_bytes() == payload
            assert oct(path.stat().st_mode & 0o777) == "0o700"


class FakeVideoCli:
    """记录 rescan 调用的假 CLI。"""

    def __init__(self, statuses=(1, 2)):
        self.calls = []
        self.statuses = list(statuses)
        self.binary = FakeBinary("/bin/true")

    def libraries(self):
        return [{"id": x.id, "name": x.name, "is_system": x.is_system} for x in LIBS]

    def all_dirs(self):
        return sorted({d for x in LIBS for d in x.dirs})

    def scan_status(self, library_id):
        return 0

    def rescan(self, library_id, paths):
        self.calls.append((library_id, list(paths)))
        return f"task-{len(self.calls)}"

    def rescan_result(self, task_id):
        return self.statuses.pop(0) if self.statuses else 2


class ServiceFlowTest:
    def make(self, statuses=(1, 2), notify=None):
        cli = FakeVideoCli(statuses)
        settings = Settings(enabled=True, quiet_seconds=0, max_wait_seconds=0,
                            library_dirs="\n".join(f"{x.id} = {d}" for x in LIBS for d in x.dirs))
        notes = notify if notify is not None else []
        svc = Service(cli, settings, log=CaptureLog(), notify=lambda t, m: notes.append((t, m)),
                      mountinfo_reader=lambda: MOUNTINFO, sleep=lambda s: None, poll_interval=0)
        return svc, cli, notes

    def test_transfer_to_rescan_end_to_end(self):
        svc, cli, _ = self.make()
        svc.on_transfer("/downloads/anime/紫川 (2021)", source="紫川")
        svc.on_transfer("/downloads/anime/紫川 (2021)/Season 1", source="紫川")
        svc.on_transfer("/downloads/complete/x")  # 不在任何分类
        for batch in svc.batcher.pop_due(force=True):
            svc._execute(batch, svc._new_record(batch, "transfer"))
        assert cli.calls == [("anime", ["/sata1/my/data/downloads/anime/紫川 (2021)"])]
        record = svc.history()[0]
        assert record["status"] == "done"
        assert record["task_status"] == 2

    def test_failure_notifies_once(self):
        notes = []
        svc, cli, _ = self.make(statuses=(5, 5, 5), notify=notes)
        for _ in range(3):
            svc.on_transfer("/downloads/variety/A")
            for batch in svc.batcher.pop_due(force=True):
                svc._execute(batch, svc._new_record(batch, "transfer"))
        assert len(notes) == 1
        assert svc.history()[0]["status"] == "failed"

    def test_status_while_login_pending_does_not_call_cli(self):
        svc, cli, _ = self.make()

        class Pending:
            url = "https://x"
            def active(self): return True
            def remaining(self): return 100
            def cancel(self): pass
        svc.login = Pending()
        info = svc.auth_status()
        assert info["login_pending"]
        assert info["logged_in"] is None

    def test_disabled_does_nothing(self):
        svc, cli, _ = self.make()
        svc.settings.enabled = False
        assert svc.on_transfer("/downloads/anime/x") == []


class StopBeforeSubmitTest:
    def test_stopped_service_does_not_submit(self):
        cli = FakeVideoCli()
        settings = Settings(enabled=True, quiet_seconds=0, max_wait_seconds=0,
                            library_dirs="\n".join(f"{x.id} = {d}" for x in LIBS for d in x.dirs))
        svc = Service(cli, settings, log=CaptureLog(), notify=lambda t, m: None,
                      mountinfo_reader=lambda: MOUNTINFO, sleep=lambda s: None, poll_interval=0)
        svc.on_transfer("/downloads/anime/紫川 (2021)")
        batches = svc.batcher.pop_due(force=True)
        record = svc._new_record(batches[0], "transfer")
        svc.stop()
        svc._execute(batches[0], record)
        assert cli.calls == []
        assert svc.history()[0]["status"] == "cancelled"
