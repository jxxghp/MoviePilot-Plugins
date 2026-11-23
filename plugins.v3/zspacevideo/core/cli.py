"""zspace-cli 的封装：固定版本二进制、调用、OAuth 登录会话。

安全约束（来自官方工具包 SKILL.md / authentication.md）：
- 一次性授权码只写进仍在等待的 ``login --auth-code-stdin`` 进程的 stdin，
  不进命令参数、环境变量、文件、日志，也不在内存里多留（写完即丢弃引用）。
- 凭据用文件后端（容器里没有系统钥匙串），目录 ``ZSPACE_CLI_HOME`` 权限 0700，
  位于插件数据目录，容器重建后仍在。
- 二进制按版本号 + 字节数 + SHA-256 固定，不跟 latest；校验不过不执行。
- 只调用 video-libraries 的 list / dirs / rescan / rescan_result / scan_status 和只读的
  collection_list / collection_info / collection_videos，以及 status / logout；其它 NAS 能力
  （含标记已看、删除影视记录、移除目录）一概不暴露。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

# 官方 runtime-artifacts.json（zspace-nas-agent-toolkit 0.3.11）里 linux-x64 / linux-arm64 两条。
ARTIFACTS: Dict[str, Dict[str, Any]] = {
    "linux-x64": {
        "version": "0.3.11",
        "url": "https://update.zenithspace.net/AgentToolkit/20261023/zspace-cli-v0.3.11-linux-x64",
        "sha256": "97ed9ea7fdeb88129498838eac3493a546008d2ef4e20778fd4d5538016616a7",
        "bytes": 6956744,
        "filename": "zspace-cli-v0.3.11-linux-x64",
    },
    "linux-arm64": {
        "version": "0.3.11",
        "url": "https://update.zenithspace.net/AgentToolkit/20261023/zspace-cli-v0.3.11-linux-arm64",
        "sha256": "200099ea0cbae6e1a4769a68975e628493301a6a19b2912043053f1a29b33fa2",
        "bytes": 5456016,
        "filename": "zspace-cli-v0.3.11-linux-arm64",
    },
}

ALLOWED_ACTIONS = frozenset({"list", "dirs", "rescan", "rescan_result", "scan_status",
                             # 已看列表只读：列出已看专辑、专辑详情（季号/已看）、专辑里的文件
                             "collection_list", "collection_info", "collection_videos"})
WRITE_ACTIONS = frozenset({"rescan"})
PROFILE = "mp"
LOGIN_TIMEOUT = 180
_CODE_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{4,512}$")


class CliError(RuntimeError):
    """CLI 返回的业务错误，code 为 CLI 错误码（E_OAUTH 等）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def detect_platform() -> str:
    machine = os.uname().machine.lower()
    if machine in ("x86_64", "amd64"):
        return "linux-x64"
    if machine in ("aarch64", "arm64"):
        return "linux-arm64"
    raise CliError("E_UNSUPPORTED_PLATFORM", f"不支持的 CPU 架构：{machine}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class Binary:
    """负责下载并校验固定版本的 zspace-cli。"""

    def __init__(self, root: Path, platform: Optional[str] = None,
                 opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.root = Path(root)
        self.platform = platform or detect_platform()
        self.artifact = ARTIFACTS[self.platform]
        self._opener = opener
        self._verified: Optional[tuple] = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.root / self.artifact["filename"]

    def _valid(self, path: Path) -> bool:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(info.st_mode) or info.st_size != self.artifact["bytes"]:
            return False
        key = (info.st_ino, info.st_size, info.st_mtime_ns)
        if self._verified == key:
            return True
        if _sha256(path) != self.artifact["sha256"]:
            return False
        self._verified = key
        return True

    def status(self) -> Dict[str, Any]:
        return {
            "version": self.artifact["version"],
            "platform": self.platform,
            "sha256": self.artifact["sha256"],
            "installed": self._valid(self.path),
        }

    def ensure(self) -> Path:
        """返回已校验的二进制路径；缺失时下载，校验通过才落位。"""
        with self._lock:
            if self._valid(self.path):
                return self.path
            ensure_private_dir(self.root)
            tmp = self.root / (self.artifact["filename"] + ".part")
            digest = hashlib.sha256()
            size = 0
            with self._opener(self.artifact["url"], timeout=60) as response, tmp.open("wb") as out:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.artifact["bytes"]:
                        break
                    digest.update(chunk)
                    out.write(chunk)
            if size != self.artifact["bytes"] or digest.hexdigest() != self.artifact["sha256"]:
                tmp.unlink(missing_ok=True)
                raise CliError("E_RUNTIME_INTEGRITY", "zspace-cli 下载后校验不通过，已丢弃")
            os.chmod(tmp, 0o700)
            os.replace(tmp, self.path)
            self._verified = None
            if not self._valid(self.path):
                raise CliError("E_RUNTIME_INTEGRITY", "zspace-cli 落位后校验不通过")
            return self.path


@dataclass
class Connection:
    """连接方式。cloud=官方云中转（默认）；lan=局域网 HTTP 直连。"""

    mode: str = "cloud"
    lan_host: str = ""

    def args(self) -> List[str]:
        if self.mode == "lan":
            host = (self.lan_host or "").strip()
            if not re.match(r"^http://[0-9A-Za-z.\-\[\]:]+$", host):
                raise CliError("E_PARAM", "局域网直连地址应形如 http://nas.example.com:5055")
            return ["--host", host, "--allow-insecure-http"]
        # 云中转：清掉可能残留的固定地址，回到默认 HTTPS 云代理
        return ["--clear-host"]


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    for candidate in (text, text.splitlines()[-1]):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return None


class Cli:
    """同步调用封装；同一时刻只跑一个 CLI 进程（profile 有锁）。"""

    def __init__(self, binary: Binary, home: Path, connection: Optional[Connection] = None,
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.binary = binary
        self.home = Path(home)
        self.connection = connection or Connection()
        self._runner = runner
        self._lock = threading.RLock()

    def env(self) -> Dict[str, str]:
        ensure_private_dir(self.home)
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.home),
            "ZSPACE_CLI_HOME": str(self.home),
            "LANG": "C.UTF-8",
        }

    def base_args(self) -> List[str]:
        return [str(self.binary.ensure()), "--profile", PROFILE, "--credential-store", "file"]

    def run(self, args: Sequence[str], timeout: int = 60) -> Any:
        with self._lock:
            cmd = self.base_args() + list(args)
            proc = self._runner(cmd, capture_output=True, text=True, timeout=timeout,
                                env=self.env(), stdin=subprocess.DEVNULL)
        out = _parse_json(proc.stdout)
        if proc.returncode == 0 and out and out.get("ok") is True:
            data = out.get("data") if "data" in out else out
            return data if data is not None else {}
        err = _parse_json(proc.stderr) or out or {}
        error = err.get("error") if isinstance(err, dict) else None
        if isinstance(error, dict):
            raise CliError(str(error.get("code") or "E_UNKNOWN"), str(error.get("message") or ""))
        raise CliError("E_UNKNOWN", f"zspace-cli 退出码 {proc.returncode}")

    def status(self) -> Dict[str, Any]:
        return self.run(["status"], timeout=30)

    def logout(self) -> Dict[str, Any]:
        return self.run(["logout"], timeout=30)

    def video(self, action: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Any:
        if action not in ALLOWED_ACTIONS:
            raise CliError("E_POLICY", f"插件不允许调用 {action}")
        body = {"action": action, **(params or {})}
        args = self.connection.args() + ["media", "video-libraries", "--params",
                                          json.dumps(body, ensure_ascii=False)]
        if action in WRITE_ACTIONS:
            args.append("--yes")
        return self.run(args, timeout=timeout)

    # 业务便捷方法
    def libraries(self) -> List[Dict[str, Any]]:
        data = self.video("list")
        return data if isinstance(data, list) else []

    def all_dirs(self) -> List[str]:
        data = self.video("dirs")
        return [str(x) for x in data] if isinstance(data, list) else []

    def rescan(self, library_id: str, paths: Sequence[str]) -> str:
        if not paths:
            raise CliError("E_PARAM", "rescan 至少要一个目录")
        data = self.video("rescan", {"library_id": library_id, "paths": list(paths)})
        task_id = ((data or {}).get("result") or {}).get("task_id")
        if not task_id:
            raise CliError("E_API", "rescan 没有返回 task_id")
        return str(task_id)

    def rescan_result(self, task_id: str) -> int:
        data = self.video("rescan_result", {"task_id": task_id}, timeout=30)
        return int((data or {}).get("task_status", -1))

    def seen_collections(self, library_id: str, page_size: int = 500, limit: int = 20) -> List[Dict[str, Any]]:
        """某分类里被标记「已看过」的专辑（filters.seen=1），自动翻页。"""
        rows: List[Dict[str, Any]] = []
        start = 1
        for _ in range(limit):
            data = self.video("collection_list", {"library_id": library_id, "start": start, "num": page_size,
                                                  "filters": {"seen": 1}}, timeout=60) or {}
            batch = data.get("list") or []
            rows.extend(x for x in batch if isinstance(x, dict))
            total = int(data.get("count") or 0)
            if not batch or len(rows) >= total:
                break
            start += len(batch)
        return rows

    def collection_info(self, library_id: str, collection_id: str) -> Dict[str, Any]:
        data = self.video("collection_info", {"library_id": library_id, "collection_id": collection_id}, timeout=30)
        return data if isinstance(data, dict) else {}

    def collection_videos(self, library_id: str, collection_id: str) -> Dict[str, Any]:
        data = self.video("collection_videos", {"library_id": library_id, "collection_id": collection_id}, timeout=60)
        return data if isinstance(data, dict) else {}

    def scan_status(self, library_id: str) -> int:
        data = self.video("scan_status", {"library_id": library_id}, timeout=30)
        return int((data or {}).get("status", -1))


class LoginSession:
    """一次 OAuth 登录事务：起进程、拿授权链接、把授权码写进 stdin。

    进程对象只保存在内存；授权码不保存，写入后立即关闭 stdin。
    """

    def __init__(self, cli: Cli, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 clock: Callable[[], float] = time.time) -> None:
        self.cli = cli
        self._popen = popen
        self._clock = clock
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.url: Optional[str] = None
        self.started_at: float = 0.0
        self.expires_in: int = LOGIN_TIMEOUT
        self.state_prefix: str = ""

    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and \
            self._clock() - self.started_at < self.expires_in

    def remaining(self) -> int:
        if not self.active():
            return 0
        return max(0, int(self.expires_in - (self._clock() - self.started_at)))

    def cancel(self) -> None:
        with self._lock:
            self._kill()

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self.url = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass

    def start(self, read_timeout: float = 30.0) -> Dict[str, Any]:
        """起 login 进程，读到授权链接后返回；进程保持等待 stdin。"""
        with self._lock:
            self._kill()
            cmd = self.cli.base_args() + self.cli.connection.args() + [
                "login", "--no-open", "--auth-code-stdin"]
            proc = self._popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=self.cli.env(), bufsize=0)
            self._proc = proc
            self.started_at = self._clock()
            assert proc.stdout is not None and proc.stderr is not None and proc.stdin is not None
            deadline = time.monotonic() + read_timeout
            line = b""
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                event = _parse_json(line.decode("utf-8", "replace"))
                if event and event.get("event") == "oauth_authorization" and event.get("url"):
                    url = str(event["url"])
                    if not url.startswith("https://"):
                        self._kill()
                        raise CliError("E_OAUTH", "授权链接不是 https，已中止")
                    self.url = url
                    self.expires_in = int(event.get("expires_in") or LOGIN_TIMEOUT)
                    self.state_prefix = str(event.get("state_prefix") or "")
                    return {"url": self.url, "expires_in": self.expires_in,
                            "state_prefix": self.state_prefix}
            err = b""
            try:
                if proc.poll() is not None:
                    err = proc.stderr.read() or b""
            except Exception:  # noqa: BLE001
                pass
            self._kill()
            parsed = _parse_json(err.decode("utf-8", "replace")) or {}
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, dict):
                raise CliError(str(error.get("code")), str(error.get("message")))
            raise CliError("E_OAUTH", "没有拿到授权链接")

    def submit(self, code: str, timeout: float = 90.0) -> Dict[str, Any]:
        """把授权码写进等待中的进程 stdin，等待兑换结果。授权码不落盘、不记日志。"""
        code = (code or "").strip()
        if not _CODE_RE.match(code):
            raise CliError("E_PARAM", "授权码格式不对，请从授权页面完整复制")
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None or not self.active():
                self._kill()
                raise CliError("E_OAUTH", "本次授权已超时或已结束，请重新点「开始授权」")
            assert proc.stdin is not None
            try:
                proc.stdin.write(code.encode("utf-8") + b"\n")
                proc.stdin.flush()
                proc.stdin.close()
            finally:
                code = ""  # noqa: F841 丢弃引用
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._kill()
                raise CliError("E_OAUTH", "等待授权结果超时")
            self._proc = None
            self.url = None
        result = _parse_json((out or b"").decode("utf-8", "replace"))
        if proc.returncode == 0:
            return (result or {}).get("data", result or {})
        parsed = _parse_json((err or b"").decode("utf-8", "replace")) or result or {}
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict):
            raise CliError(str(error.get("code")), str(error.get("message")))
        raise CliError("E_OAUTH", f"授权失败，退出码 {proc.returncode}")
