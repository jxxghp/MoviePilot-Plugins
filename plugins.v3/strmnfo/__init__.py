# -*- coding: utf-8 -*-
"""
STRM媒体信息补全插件（MoviePilot v3）

MoviePilot 整理入库（TransferComplete 事件）后，自动从 .strm 文件名里的
技术标签生成同名的 .strm.nfo（Kodi streamdetails 格式），供 Emby 的
STRM Probe NFO 插件读取入库，让媒体播放器显示分辨率/编码/HDR/音频等
媒体信息。全程只读文件名，不访问云盘、不下载任何文件。

触发方式（双保险）：
  1. 整理完成事件：MoviePilot 每整理完一部影片/一季剧集就触发，插件
     立即给本次入库的 .strm 生成 nfo；
  2. 定时全量扫描：按配置的 cron 周期扫一遍监控目录，补齐事件漏掉的
     （比如插件停用期间入库的、或事件没覆盖到的）。

配合的 Emby 插件：https://github.com/oxios0x00/emby-strm-probe-nfo
  要求 Emby Server 4.10.1.0 或更高。装好后在插件设置里选要处理的媒体库。

解析规则见同目录的 nfo.py（从 strm_nfo_gen.py v3.1 移植，含 DV.P5.60fps
帧率修复）。
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.sdk.events import eventmanager, Event
from app.sdk.plugin import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.sdk.config import settings
from app.sdk.logging import logger

# nfo.py 与本文件同目录。MoviePilot 加载插件时可能是包加载（相对导入成立），
# 也可能是单文件 spec 加载（无包上下文），两种都试，失败则降级为不可用
# （插件仍能加载，触发时记日志，不让整个插件起不来）。
try:
    from .nfo import generate_nfo_for_strm
except ImportError:  # pragma: no cover - 取决于宿主加载方式
    try:
        from nfo import generate_nfo_for_strm
    except ImportError:
        generate_nfo_for_strm = None


class StrmNfo(_PluginBase):
    """STRM媒体信息补全：整理完自动从文件名生成 .strm.nfo。"""

    # 插件名称
    plugin_name = "STRM媒体信息补全"
    # 插件描述
    plugin_desc = "整理入库后自动从 .strm 文件名生成 .strm.nfo（分辨率/编码/HDR/音频/字幕），供 Emby 的 STRM Probe NFO 插件读取，让媒体播放器显示媒体信息；全程不访问云盘。"
    # 插件图标
    plugin_icon = "scraper.svg"
    # 插件版本
    plugin_version = "1.0.4"
    # 插件标签
    plugin_label = "媒体库"
    # 插件作者
    plugin_author = "dmw1215"
    # 插件配置项ID前缀
    plugin_config_prefix = "strmnfo_"
    # 加载顺序
    plugin_order = 20
    # 可使用的用户级别
    auth_level = 1

    # ---- 配置项 ----
    _enabled: bool = False
    _onlyonce: bool = False
    _watch_paths: str = "/media/Link"
    _exclude_paths: str = ""
    _cron: str = "0 */6 * * *"
    _force: bool = False
    _max_per_run: int = 500
    _notify: bool = False

    # ---- 运行时状态 ----
    _executor: Optional[ThreadPoolExecutor] = None
    _scheduler: Optional[BackgroundScheduler] = None
    # 扫描互斥锁。必须是 RLock（可重入）：_scan_with_trigger 持锁调用
    # _do_scan，扫描中 _process_one -> _record_failure 与结尾的 _save_run
    # 会在同一线程里再次加锁；用普通 Lock 会在第一次扫描结束时就死锁。
    _lock = threading.RLock()

    def init_plugin(self, config: dict = None) -> None:
        """读取配置；onlyonce 时安排一次全量扫描。"""
        # 先释放上一轮的资源（线程池、一次性调度器），再按新配置重建，
        # 保证重复初始化 / 插件重载时不会残留旧任务。
        self.stop_service()

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._watch_paths = config.get("watch_paths") or "/media/Link"
        self._exclude_paths = config.get("exclude_paths") or ""
        self._cron = config.get("cron") or "0 */6 * * *"
        self._force = bool(config.get("force"))
        self._max_per_run = self._safe_int(config.get("max_per_run"), 500)
        self._notify = bool(config.get("notify"))

        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="strmnfo"
            )

        if generate_nfo_for_strm is None:
            logger.error("STRM媒体信息补全：nfo 模块未加载，无法生成 .strm.nfo")

        if self._enabled and self._onlyonce:
            # 安排 3 秒后跑一次全量扫描（不在 init 里同步跑，避免拖住插件加载）
            try:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self._scan,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="STRM媒体信息补全-立即运行一次",
                )
                self._scheduler.start()
            except Exception as err:  # noqa: BLE001
                logger.warning(f"STRM媒体信息补全：立即运行调度失败（{err}），改为后台直接执行")
                self._executor.submit(self._scan)
            self._onlyonce = False
            self.update_config(self._current_config())

        if self._enabled:
            logger.info(
                f"STRM媒体信息补全已启用：监控目录={self._watch_paths or '(未配置)'}，"
                f"定时扫描={self._cron}，覆盖已有={self._force}"
            )

    def stop_service(self) -> None:
        """停止插件：释放后台线程池与一次性调度器。

        宿主在插件停用、重载或卸载时会调用本方法；init_plugin 开头也会
        先调一次，确保重复初始化时不残留旧任务。宿主 cron 服务（get_service
        注册的定时扫描）由宿主自行管理，不在这里处理。
        """
        self._enabled = False
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001 - 停止时尽力释放，不阻断流程
                pass
            self._scheduler = None
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001 - 同上
                pass
            self._executor = None

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """安全地把配置值转换为正整数。"""
        try:
            result = int(float(value))
            return result if result > 0 else default
        except (TypeError, ValueError):
            return default

    def _current_config(self) -> dict:
        """返回当前内存配置字典，用于回写持久化。"""
        return {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "watch_paths": self._watch_paths,
            "exclude_paths": self._exclude_paths,
            "cron": self._cron,
            "force": self._force,
            "max_per_run": self._max_per_run,
            "notify": self._notify,
        }

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册远程命令：手动触发一次全量扫描。"""
        return [
            {
                "cmd": "/strmnfo_scan",
                "event": EventType.PluginAction,
                "desc": "立即全量扫描生成 .strm.nfo",
                "category": "命令菜单",
                "data": {"action": "strmnfo_scan"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """不注册额外 API。"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """注册定时全量扫描服务。"""
        if not self._enabled:
            return []
        return [
            {
                "id": "StrmNfo",
                "name": "STRM媒体信息补全",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self._scan,
                "kwargs": {},
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "force", "label": "覆盖已有 .strm.nfo"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify", "label": "全量扫描后发通知"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "watch_paths", "label": "监控目录", "rows": 3,
                                    "placeholder": "每行一个目录，默认 /media/Link（容器内路径）"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "exclude_paths", "label": "排除目录", "rows": 2,
                                    "placeholder": "每行一个目录，该目录下的 .strm 不处理"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "cron", "label": "定时全量扫描周期",
                                    "placeholder": "0 */6 * * *"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "max_per_run", "label": "单次整理事件最多处理",
                                    "type": "number"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {
                                    "type": "info", "variant": "tonal",
                                    "text": "本插件只生成 .strm.nfo（写在 .strm 旁边），不访问云盘。Emby 里要先装好 STRM Probe NFO 插件（4.10.1.0+），并在它的设置里选好要处理的媒体库，Emby 下次扫描时就会把 nfo 里的媒体信息读进去，媒体播放器才能显示。文件名里没有任何技术标签的文件（如只有片名+集数）生成不了，只能留空或以后再探测。"}}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "watch_paths": "/media/Link",
            "exclude_paths": "",
            "cron": "0 */6 * * *",
            "force": False,
            "max_per_run": 500,
            "notify": False,
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回统计与最近处理记录页面。"""
        stats = self.get_data("stats") or {}
        history = self.get_data("history") or []
        failures = self.get_data("failures") or []
        summary = (f"累计生成 {stats.get('generated', 0)} ｜ "
                   f"跳过已有 {stats.get('skipped', 0)} ｜ "
                   f"无法解析 {stats.get('unparsed', 0)} ｜ "
                   f"失败 {stats.get('errors', 0)}")
        rows = [
            {
                "time": h.get("time", ""),
                "trigger": h.get("trigger", ""),
                "scanned": h.get("scanned", 0),
                "generated": h.get("generated", 0),
                "skipped": h.get("skipped", 0),
                "unparsed": h.get("unparsed", 0),
                "errors": h.get("errors", 0),
            }
            for h in history[-20:]
        ]
        rows.reverse()
        fail_rows = [
            {
                "path": f.get("path", ""),
                "status": f.get("status", ""),
                "error": f.get("error", ""),
                "time": f.get("time", ""),
            }
            for f in failures[-50:]
        ]
        fail_rows.reverse()
        return [
            {
                "component": "VCard",
                "props": {"title": "STRM媒体信息补全"},
                "content": [
                    {"component": "VCardText", "content": [
                        {"component": "VChip", "props": {"label": True, "color": "primary"}, "text": summary},
                    ]},
                    {"component": "VCardText", "content": [
                        {"component": "VDataTable", "props": {
                            "headers": [
                                {"title": "时间", "key": "time"},
                                {"title": "触发", "key": "trigger"},
                                {"title": "扫描", "key": "scanned"},
                                {"title": "生成", "key": "generated"},
                                {"title": "跳过", "key": "skipped"},
                                {"title": "无法解析", "key": "unparsed"},
                                {"title": "失败", "key": "errors"},
                            ],
                            "items": rows,
                            "density": "compact",
                            "hover": True,
                        }},
                    ]},
                    {"component": "VCardText", "content": [
                        {"component": "VDataTable", "props": {
                            "headers": [
                                {"title": "无法解析/失败的文件", "key": "path"},
                                {"title": "状态", "key": "status"},
                                {"title": "原因", "key": "error"},
                                {"title": "时间", "key": "time"},
                            ],
                            "items": fail_rows,
                            "density": "compact",
                            "hover": True,
                        }},
                    ]},
                ],
            },
        ]

    # ==================== 事件处理 ====================

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event):
        """整理入库完成事件：给本次入库的 .strm 生成 nfo。"""
        if not self._enabled:
            return
        if generate_nfo_for_strm is None:
            logger.error("STRM媒体信息补全：nfo 模块未加载，跳过本次生成")
            return
        event_data = event.event_data or {}
        paths = self._extract_strm_paths(event_data)
        if not paths:
            return
        logger.info(f"STRM媒体信息补全：收到整理完成事件，{len(paths)} 个目标待生成 nfo")
        self._submit_paths(paths, trigger="event")

    @eventmanager.register(EventType.PluginAction)
    def on_plugin_action(self, event: Event):
        """远程命令响应：/strmnfo_scan 手动全量扫描。"""
        if not event or not event.event_data:
            return
        if event.event_data.get("action") != "strmnfo_scan":
            return
        if not self._enabled:
            self.post_message(
                mtype=NotificationType.Plugin,
                title="[STRM媒体信息补全]",
                text="插件未启用，命令已忽略。",
            )
            return
        logger.info("STRM媒体信息补全：收到手动全量扫描命令")
        self._submit_scan(trigger="manual")

    @staticmethod
    def _extract_strm_paths(event_data: dict) -> List[str]:
        """从整理完成事件里提取需要生成 nfo 的路径。

        transferinfo 在不同版本里可能是 TransferInfo 对象，也可能是字典，
        两种都兼容；优先用 file_list_new（整季整理时一次包含全部集数），
        再用 target_path，target_item（FileItem）做补充。file_list_new
        里的条目也可能是字典（取 path/filepath/target_path 字段），
        target_path 也可能是列表，都做兼容。
        """
        ti = event_data.get("transferinfo")
        if ti is None:
            return []
        if isinstance(ti, dict):
            file_list_new = ti.get("file_list_new") or []
            target_path = ti.get("target_path") or ""
            target_item = ti.get("target_item")
        else:
            file_list_new = getattr(ti, "file_list_new", None) or []
            target_path = getattr(ti, "target_path", "") or ""
            target_item = getattr(ti, "target_item", None)

        paths: List[str] = []
        for p in file_list_new:
            if isinstance(p, dict):
                # 字典条目：取其中表示路径的字段
                for key in ("path", "filepath", "target_path", "file_path"):
                    if p.get(key):
                        paths.append(str(p[key]))
                        break
            elif p:
                paths.append(str(p))
        if isinstance(target_path, (list, tuple)):
            for p in target_path:
                if p:
                    paths.append(str(p))
        elif target_path:
            paths.append(str(target_path))
        if target_item:
            if isinstance(target_item, dict):
                tp = target_item.get("path") or ""
                tn = target_item.get("name") or ""
            else:
                tp = getattr(target_item, "path", "") or ""
                tn = getattr(target_item, "name") or ""
            if tp and tn:
                paths.append(os.path.join(str(tp), str(tn)))
            elif tp:
                paths.append(str(tp))

        # 去重（保持顺序）
        seen = set()
        out = []
        for p in paths:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    # ==================== 核心逻辑 ====================

    def _submit_paths(self, paths: List[str], trigger: str):
        """把一批路径投递到后台线程执行，避免阻塞事件总线。"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="strmnfo"
            )
        self._executor.submit(self._run_batch, list(paths), trigger)

    def _submit_scan(self, trigger: str):
        """投递一次全量扫描到后台线程。"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="strmnfo"
            )
        self._executor.submit(self._scan_with_trigger, trigger)

    def _scan_with_trigger(self, trigger: str):
        """带触发来源标记的全量扫描入口。"""
        if not self._lock.acquire(blocking=False):
            logger.info("STRM媒体信息补全：上一轮扫描尚未结束，跳过本轮")
            return
        try:
            self._do_scan(trigger=trigger)
        finally:
            self._lock.release()

    def _scan(self):
        """定时服务入口：全量扫描。"""
        if not self._enabled:
            return
        self._scan_with_trigger(trigger="scan")

    def _run_batch(self, paths: List[str], trigger: str):
        """处理事件给出的路径列表（文件/目录/媒体文件都兼容）。"""
        counts = {"scanned": 0, "generated": 0, "skipped": 0, "unparsed": 0, "errors": 0}
        for raw in paths:
            p = Path(raw)
            try:
                if p.is_dir():
                    found = list(p.rglob("*.strm")) + list(p.rglob("*.STRM"))
                    for f in found[: self._max_per_run]:
                        self._process_one(f, counts)
                elif p.suffix.lower() == ".strm":
                    self._process_one(p, counts)
                elif p.is_file():
                    # 媒体文件本身：找同名的 .strm（xxx.mkv.strm 或 xxx.strm）
                    for cand in (p.with_name(p.name + ".strm"),
                                 p.with_suffix(".strm")):
                        if cand.exists():
                            self._process_one(cand, counts)
                            break
                else:
                    # 路径已不存在（比如已被清理）：按 .strm 猜一次
                    if p.suffix.lower() == ".strm":
                        self._process_one(p, counts)
            except OSError as err:  # noqa: BLE001
                counts["errors"] += 1
                logger.warning(f"STRM媒体信息补全：处理 {p} 失败：{err}")
        self._save_run(trigger, counts)
        logger.info(
            f"STRM媒体信息补全（{trigger}）：扫描 {counts['scanned']}，"
            f"生成 {counts['generated']}，跳过 {counts['skipped']}，"
            f"无法解析 {counts['unparsed']}，失败 {counts['errors']}"
        )

    def _do_scan(self, trigger: str):
        """全量扫描：扫一遍所有监控目录，增量生成（已有 nfo 的跳过）。"""
        counts = {"scanned": 0, "generated": 0, "skipped": 0, "unparsed": 0, "errors": 0}
        watch = [line.strip() for line in self._watch_paths.splitlines() if line.strip()]
        exclude = [line.strip() for line in self._exclude_paths.splitlines() if line.strip()]
        if not watch:
            logger.warning("STRM媒体信息补全：未配置监控目录，本次扫描跳过")
            return
        for root in watch:
            root_path = Path(root)
            if not root_path.is_dir():
                logger.warning(f"STRM媒体信息补全：监控目录不存在或不可读：{root}")
                continue
            try:
                files = list(root_path.rglob("*.strm")) + list(root_path.rglob("*.STRM"))
            except OSError as err:  # noqa: BLE001
                counts["errors"] += 1
                logger.warning(f"STRM媒体信息补全：扫描 {root} 失败：{err}")
                continue
            for f in files:
                if any(str(f).startswith(ex) for ex in exclude if ex):
                    continue
                self._process_one(f, counts)
        self._save_run(trigger, counts)
        logger.info(
            f"STRM媒体信息补全（{trigger}）：扫描 {counts['scanned']}，"
            f"生成 {counts['generated']}，跳过 {counts['skipped']}，"
            f"无法解析 {counts['unparsed']}，失败 {counts['errors']}"
        )
        if self._notify and trigger in ("scan", "manual"):
            self.post_message(
                mtype=NotificationType.Plugin,
                title="[STRM媒体信息补全]",
                text=(f"全量扫描完成：扫描 {counts['scanned']} 个 .strm，"
                      f"生成 {counts['generated']} 个 nfo，跳过 {counts['skipped']}，"
                      f"无法解析 {counts['unparsed']}，失败 {counts['errors']}。"),
            )

    def _process_one(self, strm_path: Path, counts: dict):
        """给一个 .strm 生成 nfo，并累计计数与失败记录。"""
        counts["scanned"] += 1
        if generate_nfo_for_strm is None:
            counts["errors"] += 1
            return
        try:
            status, info = generate_nfo_for_strm(strm_path, force=self._force)
        except Exception as err:  # noqa: BLE001
            counts["errors"] += 1
            self._record_failure(strm_path, "error", str(err))
            logger.warning(f"STRM媒体信息补全：{strm_path} 生成失败：{err}")
            return
        if status == "generated":
            counts["generated"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        elif status == "unparsed":
            counts["unparsed"] += 1
            self._record_failure(strm_path, "unparsed", "文件名里没有分辨率/编码/HDR 标签")
        else:  # error
            counts["errors"] += 1
            err = (info or {}).get("error", "")
            self._record_failure(strm_path, "error", err)
            logger.warning(f"STRM媒体信息补全：{strm_path} 生成失败：{err}")

    # ==================== 记录 ====================

    def _save_run(self, trigger: str, counts: dict):
        """保存一次运行记录，并累计统计。"""
        with self._lock:
            stats = self.get_data("stats") or {}
            for key in ("generated", "skipped", "unparsed", "errors"):
                stats[key] = int(stats.get(key, 0)) + int(counts.get(key, 0))
            self.save_data("stats", stats)
            history = self.get_data("history") or []
            history.append({
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "trigger": trigger,
                "scanned": counts["scanned"],
                "generated": counts["generated"],
                "skipped": counts["skipped"],
                "unparsed": counts["unparsed"],
                "errors": counts["errors"],
            })
            self.save_data("history", history[-100:])

    def _record_failure(self, strm_path: Path, status: str, error: str):
        """记录一条无法解析/失败的文件（插件详情页可见）。"""
        with self._lock:
            failures = self.get_data("failures") or []
            failures.append({
                "path": str(strm_path),
                "status": status,
                "error": error,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            self.save_data("failures", failures[-300:])
