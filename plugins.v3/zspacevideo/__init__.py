"""极空间影视：极空间官方 OAuth 授权 + 整理完成后按目录精确刷新极影视分类 + 已看列表与删除。

只调用官方 zspace-cli 的 video-libraries list / dirs / rescan / rescan_result / scan_status，
以及只读的 collection_list / collection_info / collection_videos。不做字幕、豆瓣、分类增删改、
移除目录、标记已看，也不写极影视数据库。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.types import EventType, MessageType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase

from .core import watched as W
from .core.cli import Binary, Cli, CliError, Connection, ensure_private_dir
from .core.service import Service, Settings
from .core.watch_service import WatchHost, WatchService, WatchSettings


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def transfer_target_path(event_data: Any) -> Optional[str]:
    """从整理完成事件里取媒体在库里的目录（媒体根目录优先）。"""
    info = _get(event_data, "transferinfo")
    if info is None or _get(info, "success") is False:
        return None
    for key in ("target_diritem", "target_item"):
        item = _get(info, key)
        path = _get(item, "path")
        if path:
            path = str(path)
            if key == "target_item" and _get(item, "type") != "dir":
                path = str(Path(path).parent)
            return path
    files = _get(info, "file_list_new") or []
    if files:
        return str(Path(str(files[0])).parent)
    return None


class ZSpaceVideo(_PluginBase):
    """通过官方授权刷新极影视，并按用户选择管理已看媒体。"""
    plugin_name = "极空间影视"
    plugin_desc = "极空间官方授权登录（不用 cookie），整理后只刷新对应目录；极影视已看列表，可按选项移出库或连同做种一起删除。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/Zspace_A.png"
    plugin_version = "0.2.2"
    plugin_author = "xiaoyaner0201"
    author_url = "https://github.com/xiaoyaner0201/MoviePilot-ZSpaceVideo"
    plugin_config_prefix = "zspacevideo_"
    plugin_label = "极空间,媒体库"
    plugin_order = 30
    auth_level = 1

    _service: Optional[Service] = None
    _settings: Settings = Settings()
    _watch: Optional[WatchService] = None
    _watch_settings: WatchSettings = WatchSettings()

    # ------------------------------------------------------------------ 生命周期
    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.stop_service()
        self._settings = Settings.from_config(config)
        self._watch_settings = WatchSettings.from_config(config)
        data = Path(self.get_data_path())
        cli = Cli(
            Binary(ensure_private_dir(data / "bin")),
            home=ensure_private_dir(data / "cli"),
            connection=Connection(mode=self._settings.connection_mode, lan_host=self._settings.lan_host),
        )
        self._service = Service(
            cli, self._settings, log=logger, notify=self._send_notify,
            load_history=lambda: self.get_data("history") or [],
            save_history=lambda items: self.save_data("history", items),
        )
        self._watch = self._build_watch(cli)
        if self._settings.enabled:
            self._service.start()
            # 预热二进制，失败只记日志
            threading.Thread(target=self._warmup, daemon=True, name="zspacevideo-warmup").start()

    def _build_watch(self, cli: Cli) -> WatchService:
        from . import host as H
        qb = H.QbAdapter()
        service = self._service

        def exec_host() -> W.Host:
            return W.Host(delete_path=H.delete_path, list_torrents=lambda hs: qb.torrents(hs),
                          delete_torrents=qb.delete, delete_records=H.delete_records,
                          forget_sources=H.forget_sources, prune_dir=H.prune_dir)

        def rescan(paths: Any, why: str) -> List[Dict[str, Any]]:
            assert service is not None
            return service.refresh_paths(list(paths), why)

        whost = WatchHost(transfers_by_tmdb=H.transfers_by_tmdb, downloads_by_tmdb=H.downloads_by_tmdb,
                          torrents=lambda: qb.torrents(), torrent_files=qb.files, roots=H.library_roots,
                          exec_host=exec_host, rescan=rescan)
        assert service is not None
        return WatchService(cli, self._watch_settings, whost, mappings=service.mappings, log=logger,
                            notify=self._send_watch_notify, load=self.get_data, save=self.save_data)

    def _send_watch_notify(self, title: str, text: str) -> None:
        self.post_message(mtype=MessageType.Plugin, title=title, text=text)

    def _watch_job(self) -> None:
        if not self._watch:
            return
        try:
            out = self._watch.run_auto()
            logger.info(f"极空间影视：已看同步完成 {out.get('sync') or out}")
        except Exception as error:  # noqa: BLE001
            logger.error(f"极空间影视：已看同步失败：{error}")

    def _warmup(self) -> None:
        try:
            if self._service:
                self._service.cli.binary.ensure()
        except Exception as error:  # noqa: BLE001
            logger.warning(f"极空间影视：准备 zspace-cli 失败：{error}")

    def get_state(self) -> bool:
        return bool(self._settings.enabled)

    def stop_service(self) -> None:
        if self._service:
            self._service.stop()
        self._service = None

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not (self._settings.enabled and self._watch_settings.enabled):
            return []
        return [{
            "id": "ZSpaceVideoWatched",
            "name": "极影视已看同步与自动删除",
            "trigger": "interval",
            "func": self._watch_job,
            "kwargs": {"minutes": self._watch_settings.sync_minutes},
        }]

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_page(self) -> List[dict]:
        return []

    # ------------------------------------------------------------------ 事件
    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event) -> None:
        if not self._settings.enabled or not self._service:
            return
        try:
            data = getattr(event, "event_data", None)
            path = transfer_target_path(data)
            if not path:
                return
            title = _get(_get(data, "mediainfo"), "title") or ""
            self._service.on_transfer(path, source=str(title))
        except Exception as error:  # noqa: BLE001
            logger.error(f"极空间影视：处理整理事件失败：{error}")

    def _send_notify(self, title: str, text: str) -> None:
        self.post_message(mtype=MessageType.Plugin, title=title, text=text)

    # ------------------------------------------------------------------ API
    def get_api(self) -> List[Dict[str, Any]]:
        def route(path: str, endpoint: Any, method: str, summary: str) -> Dict[str, Any]:
            return {"path": path, "endpoint": endpoint, "methods": [method], "auth": "bear", "summary": summary}
        return [
            route("/status", self.api_status, "GET", "授权与运行状态"),
            route("/login/start", self.api_login_start, "POST", "开始极空间授权"),
            route("/login/submit", self.api_login_submit, "POST", "提交一次性授权码"),
            route("/login/cancel", self.api_login_cancel, "POST", "取消授权"),
            route("/logout", self.api_logout, "POST", "清除本地授权"),
            route("/libraries", self.api_libraries, "GET", "分类与目录"),
            route("/refresh", self.api_refresh, "POST", "立即刷新一个分类"),
            route("/history", self.api_history, "GET", "最近刷新记录"),
            route("/resolve", self.api_resolve, "POST", "预览路径会刷新哪个分类"),
            route("/watched", self.api_watched, "GET", "已看列表（含各版本文件）"),
            route("/watched/sync", self.api_watched_sync, "POST", "立即读一次极影视已看"),
            route("/watched/preview", self.api_watched_preview, "POST", "预览删除清单"),
            route("/watched/execute", self.api_watched_execute, "POST", "按预览清单执行删除"),
            route("/watched/history", self.api_watched_history, "GET", "删除记录"),
            route("/watched/run", self.api_watched_run, "POST", "立即跑一次定时任务（读已看；选了删除选项时处理到期的）"),
            route("/watched/apply", self.api_watched_apply, "POST", "只对指定条目按选项删除"),
            route("/watched/notice", self.api_watched_notice, "POST", "发一条站内消息（运维更正用）"),
            route("/watched/reset", self.api_watched_reset, "POST", "清掉条目的已处理状态"),
            route("/config", self.api_config, "GET", "读取配置"),
            route("/config", self.api_save_config, "POST", "保存配置"),
        ]

    def _svc(self) -> Service:
        if self._service is None:
            self.init_plugin(self.get_config())
        assert self._service is not None
        return self._service

    @staticmethod
    def _ok(data: Any = None, message: str = "") -> Dict[str, Any]:
        return {"success": True, "message": message, "data": data}

    @staticmethod
    def _fail(error: Any) -> Dict[str, Any]:
        return {"success": False, "message": str(error), "data": None}

    def api_status(self) -> Dict[str, Any]:
        svc = self._svc()
        try:
            data = svc.auth_status()
        except CliError as error:
            data = {"logged_in": False, "error": str(error)}
        data.update({"enabled": self._settings.enabled, "pending_batches": svc.batcher.pending_count()})
        try:
            data["mappings"] = [m.__dict__ for m in svc.mappings()]
        except ValueError as error:
            data["mappings_error"] = str(error)
        return self._ok(data)

    def api_login_start(self) -> Dict[str, Any]:
        try:
            return self._ok(self._svc().login.start())
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_login_submit(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        code = str((payload or {}).get("code") or "")
        if payload is not None:
            payload.pop("code", None)
        try:
            result = self._svc().login.submit(code)
            code = ""
            logger.info("极空间影视：极空间授权成功")
            safe = {k: result.get(k) for k in ("nas_id", "expires_at", "credential_store", "backend")
                    if isinstance(result, dict)}
            return self._ok(safe, "授权成功")
        except Exception as error:  # noqa: BLE001
            code = ""
            logger.warning(f"极空间影视：授权失败：{getattr(error, 'code', '')}")
            return self._fail(error)

    def api_login_cancel(self) -> Dict[str, Any]:
        self._svc().login.cancel()
        return self._ok()

    def api_logout(self) -> Dict[str, Any]:
        try:
            return self._ok(self._svc().cli.logout(), "已清除本地授权")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_libraries(self, force: bool = False) -> Dict[str, Any]:
        svc = self._svc()
        try:
            libs = svc.libraries(force=bool(force))
            status = {}
            for lib in libs:
                try:
                    status[lib.id] = svc.cli.scan_status(lib.id)
                except CliError:
                    status[lib.id] = None
            return self._ok({
                "source": svc.libraries_source,
                "libraries": [{"id": x.id, "name": x.name, "dirs": x.dirs, "is_system": x.is_system,
                               "scan_status": status.get(x.id)} for x in libs],
            })
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_refresh(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        library_id = str((payload or {}).get("library_id") or "")
        try:
            return self._ok(self._svc().refresh_library(library_id), "已提交")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_history(self) -> Dict[str, Any]:
        return self._ok(self._svc().history())

    def api_resolve(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        path = str((payload or {}).get("path") or "")
        try:
            return self._ok(self._svc().resolve(path))
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def _watch_svc(self) -> WatchService:
        if self._watch is None:
            self.init_plugin(self.get_config())
        assert self._watch is not None
        return self._watch

    def api_watched(self) -> Dict[str, Any]:
        try:
            return self._ok(self._watch_svc().listing())
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_sync(self) -> Dict[str, Any]:
        try:
            return self._ok(self._watch_svc().sync(), "已读取")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_preview(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        try:
            ids = payload.get("version_ids") or None
            return self._ok(self._watch_svc().preview(str(payload.get("key") or ""), str(payload.get("mode") or ""),
                                                     list(ids) if ids else None,
                                                     confirm_unknown_season=payload.get("confirm_unknown_season") is True))
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_execute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        try:
            svc = self._watch_svc()
            result = svc.execute(str(payload.get("plan_id") or ""), trigger="manual")
            svc.notify_manual(result)
            return self._ok(result, "已执行")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_run(self) -> Dict[str, Any]:
        try:
            return self._ok(self._watch_svc().run_auto(), "已执行")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_apply(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        try:
            svc = self._watch_svc()
            keys = [str(k) for k in (payload.get("keys") or [])]
            if not keys:
                raise ValueError("没有指定条目")
            results = svc.run_keys(keys, str(payload.get("mode") or ""),
                                   confirm_unknown_season=payload.get("confirm_unknown_season") is True)
            svc._notify("极空间影视：已看手动删除", W.summarize(results))
            return self._ok(results, "已执行")
        except Exception as error:  # noqa: BLE001
            return self._fail(error)

    def api_watched_reset(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        keys = [str(k) for k in ((payload or {}).get("keys") or [])]
        return self._ok(self._watch_svc().reset(keys))

    def api_watched_notice(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        title, text = str(payload.get("title") or "").strip(), str(payload.get("text") or "").strip()
        if not title or not text:
            return self._fail("title/text 不能为空")
        self.post_message(mtype=MessageType.Plugin, title=title[:80], text=text[:2000])
        return self._ok()

    def api_watched_history(self) -> Dict[str, Any]:
        return self._ok(list(self._watch_svc().history))

    def _full_config(self) -> Dict[str, Any]:
        config = self._settings.to_config()
        config.update(self._watch_settings.to_config())
        return config

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], self._full_config()

    def api_config(self) -> Dict[str, Any]:
        return self._ok(self._full_config())

    def api_save_config(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import time as _time
        settings = Settings.from_config(payload)
        watch = WatchSettings.from_config(payload).stamped(self._watch_settings, _time.time())
        config = settings.to_config()
        config.update(watch.to_config())
        self.update_config(config)
        self.init_plugin(config)
        return self._ok(config, "已保存")
