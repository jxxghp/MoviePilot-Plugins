"""Authenticated bridge from MoviePilot to the PiNAS cleanup control plane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_GATEWAY = "http://nas-host:3000/control"
DEFAULT_TOKEN_FILE = "/run/storage-cleanup/control-token"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class CleanupBridge:
    """Call the existing safety controller without exposing its token to Vue."""

    def __init__(
        self,
        *,
        gateway: str = DEFAULT_GATEWAY,
        token_file: str = DEFAULT_TOKEN_FILE,
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.token_file = Path(token_file)

    def _token(self) -> str:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("清理控制令牌不可用，请检查清理台服务。") from exc
        if not token:
            raise RuntimeError("清理控制令牌为空，请重启清理台控制服务。")
        return token

    @staticmethod
    def _decode(raw: bytes, status: int) -> dict[str, Any]:
        if len(raw) > MAX_RESPONSE_BYTES:
            return {
                "ok": False,
                "error": {
                    "code": "bridge_response_too_large",
                    "message": "清理控制服务返回内容过大。",
                },
            }
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {
                "ok": False,
                "error": {
                    "code": "bridge_invalid_response",
                    "message": f"清理控制服务返回了无法识别的响应（HTTP {status}）。",
                },
            }
        return payload if isinstance(payload, dict) else {
            "ok": False,
            "error": {
                "code": "bridge_invalid_response",
                "message": "清理控制服务返回格式不正确。",
            },
        }

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: int = 900,
    ) -> tuple[int, dict[str, Any]]:
        token = self._token()
        data = (
            json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            if method != "GET"
            else None
        )
        request = Request(
            f"{self.gateway}/{path.lstrip('/')}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-PiNAS-Bridge-Token": token,
                "X-PiNAS-Session": token,
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                return response.status, self._decode(raw, response.status)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            return exc.code, self._decode(raw, exc.code)
        except (URLError, OSError) as exc:
            return 502, {
                "ok": False,
                "error": {
                    "code": "cleanup_bridge_unavailable",
                    "message": f"无法连接 PiNAS 清理控制服务：{exc.reason if isinstance(exc, URLError) else exc}",
                },
            }
