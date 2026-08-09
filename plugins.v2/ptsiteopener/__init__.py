"""MoviePilot V2 plugin for opening active PT sites through remote CDP."""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from apscheduler.triggers.cron import CronTrigger

from app.api.endpoints.plugin import register_plugin_api
from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


DEFAULT_CDP_URL = "http://music.lulin.fun:5656/json/version"
DEFAULT_SCHEDULE = "0 */6 * * *"
DEFAULT_TTL_MINUTES = 5
PLUGIN_ID = "PTSiteOpener"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def select_site_urls(
    sites: Iterable[Any],
    site_mode: str = "all",
    selected_site_ids: Optional[Iterable[Any]] = None,
) -> List[str]:
    """Return active, unique HTTP(S) site URLs in MoviePilot order."""
    selected = {str(site_id) for site_id in (selected_site_ids or [])}
    urls: List[str] = []
    seen = set()

    for site in sites or []:
        if not getattr(site, "is_active", False):
            continue
        if site_mode == "selected" and str(getattr(site, "id", "")) not in selected:
            continue

        raw_url = getattr(site, "url", None)
        if not isinstance(raw_url, str):
            continue
        url = raw_url.strip()
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    return urls


def resolve_websocket_url(version_info: Dict[str, Any], endpoint_url: str) -> str:
    """Resolve a CDP websocket URL returned by a remote /json/version endpoint."""
    raw_websocket_url = version_info.get("webSocketDebuggerUrl")
    if not isinstance(raw_websocket_url, str) or not raw_websocket_url:
        raise ValueError("CDP version response has no webSocketDebuggerUrl")

    endpoint = urlsplit(endpoint_url)
    websocket = urlsplit(raw_websocket_url)
    if websocket.scheme not in {"ws", "wss"}:
        raise ValueError(f"Unsupported CDP WebSocket protocol: {websocket.scheme}")

    if websocket.hostname in LOOPBACK_HOSTS:
        websocket = websocket._replace(
            scheme="wss" if endpoint.scheme == "https" else "ws",
            netloc=endpoint.netloc,
        )
    return urlunsplit(websocket)


def _validate_cdp_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("cdp_url must be an HTTP or HTTPS URL")


def _fetch_json(url: str, timeout: float = 15) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CDP version response is not an object")
    return payload


class _CdpConnection:
    """Small synchronous CDP command client for one browser websocket."""

    def __init__(self, socket: Any):
        self._socket = socket
        self._lock = threading.RLock()
        self._next_id = 0
        self._closed = False

    def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError("CDP connection is closed")
            self._next_id += 1
            message_id = self._next_id
            self._socket.send(
                json.dumps(
                    {
                        "id": message_id,
                        "method": method,
                        "params": params or {},
                    }
                )
            )

            while True:
                raw_message = self._socket.recv()
                if not raw_message:
                    raise RuntimeError("CDP websocket closed before command response")
                message = json.loads(raw_message)
                if message.get("id") != message_id:
                    continue
                if message.get("error"):
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result", {})
                return result if isinstance(result, dict) else {}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._socket.close()
            except Exception as error:
                logger.debug(f"?? CDP ?????{error}")


def _connect_cdp(endpoint_url: str) -> _CdpConnection:
    version_info = _fetch_json(endpoint_url)
    websocket_url = resolve_websocket_url(version_info, endpoint_url)

    import websocket

    socket = websocket.create_connection(
        websocket_url,
        timeout=15,
        enable_multithread=True,
        suppress_origin=True,
    )
    return _CdpConnection(socket)


@dataclass
class _OpenRun:
    cdp: _CdpConnection
    target_ids: List[str] = field(default_factory=list)
    timer: Any = None
    cleaned: bool = False
    lock: Any = field(default_factory=threading.RLock)


class PTSiteOpener(_PluginBase):
    """????? MoviePilot ????? PT ???"""

    plugin_name = "PT??????"
    plugin_desc = "??????????????? CDP ?? MoviePilot ????????"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.1.2"
    plugin_author = "Codex"
    author_url = "https://github.com/Lin-max1032/MoviePilot-Plugins"
    plugin_config_prefix = "ptsiteopener_"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._config_error: Optional[str] = None
        self._cdp_url = DEFAULT_CDP_URL
        self._schedule = DEFAULT_SCHEDULE
        self._ttl_minutes = DEFAULT_TTL_MINUTES
        self._notify_enabled = False
        self._site_mode = "all"
        self._selected_site_ids: List[str] = []
        self._runs: List[_OpenRun] = []
        self._runs_lock = threading.RLock()
        self._last_result = "????"

    def init_plugin(self, config: dict = None):
        """????????????"""
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._cdp_url = str(config.get("cdp_url") or DEFAULT_CDP_URL).strip()
        self._schedule = str(config.get("schedule") or DEFAULT_SCHEDULE).strip()
        self._ttl_minutes = self._coerce_ttl(config.get("ttl_minutes", DEFAULT_TTL_MINUTES))
        self._notify_enabled = bool(config.get("notify_enabled", False))
        self._site_mode = str(config.get("site_mode") or "all")
        if self._site_mode not in {"all", "selected"}:
            self._site_mode = "all"
        raw_site_ids = config.get("site_ids") or []
        if isinstance(raw_site_ids, (str, int)):
            raw_site_ids = [raw_site_ids]
        self._selected_site_ids = [str(site_id) for site_id in raw_site_ids]
        self._config_error = None

        try:
            _validate_cdp_url(self._cdp_url)
            CronTrigger.from_crontab(self._schedule)
        except Exception as error:
            self._config_error = str(error)
            logger.error(f"PT???????????{error}")

    @staticmethod
    def _coerce_ttl(value: Any) -> int:
        try:
            ttl_minutes = int(value)
        except (TypeError, ValueError):
            return DEFAULT_TTL_MINUTES
        return max(ttl_minutes, 0)

    def get_state(self) -> bool:
        return self._enabled and not self._config_error

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.run_now,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "???? PT ??",
                "description": "????????????",
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self.get_state():
            return []
        try:
            trigger = CronTrigger.from_crontab(self._schedule)
        except Exception as error:
            logger.error(f"PT?????? Cron ???{error}")
            return []
        return [
            {
                "id": PLUGIN_ID,
                "name": "PT????????",
                "trigger": trigger,
                "func": self.run_once,
                "kwargs": {},
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_items = []
        try:
            for site in SiteOper().list_active() or []:
                site_id = getattr(site, "id", None)
                if site_id is None:
                    continue
                site_items.append(
                    {
                        "title": getattr(site, "name", None) or getattr(site, "domain", None) or str(site_id),
                        "value": str(site_id),
                    }
                )
        except Exception as error:
            logger.warning(f"?? MoviePilot ???????{error}")

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "props": {"class": "mb-2"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "????"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify_enabled",
                                            "label": "??????",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mb-2"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cdp_url",
                                            "label": "?? CDP ??",
                                            "placeholder": DEFAULT_CDP_URL,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mb-2"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "schedule",
                                            "label": "???? Cron????",
                                            "placeholder": DEFAULT_SCHEDULE,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ttl_minutes",
                                            "label": "???????????",
                                            "type": "number",
                                            "min": 0,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mb-2"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "site_mode",
                                            "label": "????",
                                            "items": [
                                                {"title": "??????", "value": "all"},
                                                {"title": "??????", "value": "selected"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "site_ids",
                                            "label": "????",
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "items": site_items,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "cdp_url": DEFAULT_CDP_URL,
            "schedule": DEFAULT_SCHEDULE,
            "ttl_minutes": DEFAULT_TTL_MINUTES,
            "notify_enabled": False,
            "site_mode": "all",
            "site_ids": [],
        }

    def get_page(self) -> List[dict]:
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info" if self.get_state() else "warning",
                    "variant": "tonal",
                    "text": self._config_error or self._last_result,
                },
            },
            {
                "component": "VRow",
                "props": {"class": "mt-2"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "variant": "tonal",
                                    "block": True,
                                    "prepend-icon": "mdi-play-circle",
                                },
                                "text": "????",
                                "events": {
                                    "click": {
                                        "api": f"plugin/{self.__class__.__name__}/run",
                                        "method": "post",
                                    }
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    @eventmanager.register(EventType.PluginReload)
    def reload(self, event: Event) -> None:
        """????????????? API ???"""
        event_data = getattr(event, "event_data", None) or {}
        if event_data.get("plugin_id") == self.__class__.__name__:
            register_plugin_api(plugin_id=self.__class__.__name__)

    def _connect_cdp(self) -> _CdpConnection:
        return _connect_cdp(self._cdp_url)

    def _record_result(
        self,
        message: str,
        opened_urls: Optional[Iterable[str]] = None,
        level: str = "info",
    ) -> None:
        """Store the latest result and optionally publish it through MoviePilot."""
        self._last_result = message
        getattr(logger, level)(message)
        if not self._notify_enabled:
            return

        text = message
        urls = list(opened_urls or [])
        if urls:
            text = f"{message}\n?????\n" + "\n".join(urls)
        try:
            self.post_message(
                mtype=NotificationType.Plugin,
                title=self.plugin_name,
                text=text,
            )
        except Exception as error:
            logger.warning(f"?? PT ?????????{error}")

    def run_now(self) -> Dict[str, Any]:
        """Run one task from the configuration page button."""
        logger.info("????????")
        if self._config_error:
            message = f"??????????{self._config_error}"
            self._record_result(message, level="error")
            return {"success": False, "message": message, "opened": []}

        opened_urls = self.run_once(manual=True)
        return {
            "success": bool(opened_urls),
            "message": self._last_result,
            "opened": opened_urls,
        }

    def run_once(self, manual: bool = False) -> List[str]:
        """Execute one scheduled or manual run and return successfully opened URLs."""
        if self._config_error:
            self._record_result(
                f"??????????{self._config_error}",
                level="error",
            )
            return []
        if not manual and not self._enabled:
            logger.info("????????????")
            return []

        try:
            sites = SiteOper().list_active()
            urls = select_site_urls(
                sites,
                site_mode=self._site_mode,
                selected_site_ids=self._selected_site_ids,
            )
        except Exception as error:
            self._record_result(f"???????{error}", level="error")
            return []

        if not urls:
            self._record_result("??????????")
            return []

        try:
            cdp = self._connect_cdp()
        except Exception as error:
            self._record_result(f"???? CDP ???{error}", level="error")
            return []

        run = _OpenRun(cdp=cdp)
        with self._runs_lock:
            self._runs.append(run)

        opened_urls: List[str] = []
        for url in urls:
            try:
                with run.lock:
                    if run.cleaned:
                        break
                    target = cdp.send(
                        "Target.createTarget",
                        {"url": url, "background": True},
                    )
                    target_id = target.get("targetId") if isinstance(target, dict) else None
                    if not target_id:
                        raise RuntimeError("CDP did not return targetId")
                    run.target_ids.append(target_id)
                    opened_urls.append(url)
            except Exception as error:
                logger.warning(f"?????? {url}?{error}")

        with run.lock:
            if run.cleaned:
                return opened_urls
            has_targets = bool(run.target_ids)
            if has_targets:
                try:
                    cdp.send("Target.activateTarget", {"targetId": run.target_ids[0]})
                except Exception as error:
                    logger.warning(f"????????????{error}")

                run.timer = threading.Timer(
                    self._ttl_minutes * 60,
                    self._cleanup_run,
                    args=(run,),
                )
                run.timer.daemon = True
                run.timer.start()

        if has_targets:
            self._record_result(
                f"??? {len(opened_urls)} ????{self._ttl_minutes} ?????",
                opened_urls,
            )
        else:
            self._cleanup_run(run)
            self._record_result("????????", opened_urls)

        return opened_urls

    def _cleanup_run(self, run: _OpenRun) -> None:
        with run.lock:
            if run.cleaned:
                return
            run.cleaned = True
            target_ids = list(run.target_ids)
            with self._runs_lock:
                if run in self._runs:
                    self._runs.remove(run)

        if run.timer is not None:
            try:
                run.timer.cancel()
            except Exception:
                pass

        for target_id in target_ids:
            try:
                run.cdp.send("Target.closeTarget", {"targetId": target_id})
            except Exception as error:
                logger.warning(f"????????? {target_id}?{error}")
        run.cdp.close()

    def stop_service(self):
        """????????????????????????"""
        with getattr(self, "_runs_lock", threading.RLock()):
            runs = list(getattr(self, "_runs", []))
        for run in runs:
            self._cleanup_run(run)
