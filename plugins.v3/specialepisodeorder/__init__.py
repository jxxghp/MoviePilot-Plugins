"""MoviePilot V3 特典播放顺序：刮削时补全与存量 NFO 修复。"""

from datetime import datetime, timezone
from os.path import split
from threading import Event, Lock, RLock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.sdk import scheduler
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.plugin import ModuleManager, _PluginBase
from app.schemas.types import MediaType

from .client import METADATA_CACHE_KEY, MetadataClient
from .nfo import POSITION_TAGS, NfoEnricher, format_position, integer, parse_overrides
from .repair import RepairRunner


SCAN_RESULTS = {
    "preview": ("待更新", "info"),
    "updated": ("已更新", "success"),
    "needs_correction": ("待修正", "warning"),
    "skipped": ("已跳过", "secondary"),
    "failed": ("失败", "error"),
}
DEFAULT_CONFIG = {
    "enabled": False,
    "paths": "",
    "overrides": "",
    "dry_run": True,
    "onlyonce": False,
    "clear_cache": False,
}


def scan_summary(report: dict) -> str:
    """将扫描状态和计数格式化为可直接阅读的摘要。"""
    mode = "预览" if report["dry_run"] else "修复"
    status = {"completed": "完成", "cancelled": "已取消"}.get(report["status"], "失败")
    counts = report["counts"]
    totals = " · ".join(
        f"{label} {counts[key]} 项" for key, (label, _) in SCAN_RESULTS.items() if counts.get(key)
    )
    return f"{mode}{status} · {totals or '0 项'}"


class SpecialEpisodeOrder(_PluginBase):
    """通过公开的 NFO 模块扩展点补全 TVDB 特典播放位置。"""

    plugin_name = "特典播放顺序"
    plugin_desc = "精确映射 TMDb 与 TVDB 单集，同步 Season 0 特典播放位置，支持预览和修复已有 NFO。"
    plugin_icon = "specialepisodeorder.png"
    plugin_version = "3.2.0"
    plugin_author = "OpportunityLiu"
    author_url = "https://github.com/OpportunityLiu"
    plugin_config_prefix = "specialepisodeorder_"
    plugin_order = 20
    auth_level = 1

    def __init__(self) -> None:
        """为每个插件实例创建独立锁与取消信号。"""
        super().__init__()
        self._write_lock = RLock()
        self._scan_lock = Lock()
        self._stopped = Event()
        self._stopped.set()
        self._engine = None
        self._enabled = False
        self._config = {}
        self._config_error = ""
        self._cache_cleared = False
        self._last_report: dict | None = None

    def init_plugin(self, config: dict | None = None) -> None:
        """校验配置、替换运行代际，并只调度明确请求的一次性任务。"""
        self.stop_service()
        self._config = {**DEFAULT_CONFIG, **(config or {})}
        onlyonce = bool(self._config.get("onlyonce"))
        clear_cache = bool(self._config.get("clear_cache"))
        if onlyonce or clear_cache:
            self._config.update(onlyonce=False, clear_cache=False)
            self.update_config(self._config)
        self._config_error = ""
        self._cache_cleared = False
        if clear_cache:
            try:
                self.del_data(METADATA_CACHE_KEY)
                MetadataClient.clear_temporary_cache()
                RepairRunner.clear_file_cache()
            except Exception as error:
                self._config_error = f"清空缓存失败，请重试（{type(error).__name__}）"
                logger.error(f"特典播放顺序：{self._config_error}")
                onlyonce = False
            else:
                self._cache_cleared = True
                logger.info("特典播放顺序：已清空缓存")
        try:
            overrides = parse_overrides(str(self._config.get("overrides") or ""))
        except ValueError as error:
            self._config_error = str(error)
            logger.error(f"特典播放顺序：{self._config_error}")
            return
        self._enabled = bool(self._config.get("enabled"))
        self._stopped = Event()
        client = MetadataClient(
            self.get_data, self.save_data, stopped=self._stopped, cache_lock=self._write_lock,
        )
        self._engine = NfoEnricher(client, overrides)
        if not self._enabled:
            self._stopped.set()
            return
        if onlyonce:
            paths = [line.strip() for line in str(self._config.get("paths") or "").splitlines() if line.strip()]
            if not paths:
                logger.warning("特典播放顺序：请先填写扫描目录")
                return
            runner = RepairRunner(self._engine, self._stopped, self._write_lock)
            accepted = scheduler.add_plugin_once_job(
                self.__class__.__name__, "repair", self._run_repair,
                "特典播放顺序：预览或修复 NFO", delay_seconds=2,
                func_kwargs={"runner": runner, "paths": paths, "dry_run": bool(self._config.get("dry_run", True))},
            )
            if not accepted:
                logger.warning("特典播放顺序：宿主调度器未接受任务，请稍后重新运行一次")

    def _run_repair(self, runner: RepairRunner, paths: list[str], dry_run: bool) -> None:
        """避免扫描重叠；仅当前代际可更新最近报告。"""
        if not self._scan_lock.acquire(blocking=False):
            logger.warning("特典播放顺序：上一轮扫描尚未结束，请稍后重新运行")
            return
        try:
            if runner.stopped.is_set():
                return
            report = runner.run(paths, dry_run)
            runner.engine.client.flush_cache()
            report["finished_at"] = datetime.now(timezone.utc)
            with self._write_lock:
                if runner.stopped is self._stopped and not runner.stopped.is_set():
                    self._last_report = report
            logger.info(f"特典播放顺序：{scan_summary(report)}")
        except Exception as error:
            logger.error(f"特典播放顺序：扫描失败 {type(error).__name__}")
        finally:
            self._scan_lock.release()

    def metadata_nfo(self, meta, mediainfo, season=None, episode=None) -> str | None:
        """仅接管目标特典；直接调用基础模块，避免再次分派到自身。"""
        engine, stopped = self._engine, self._stopped
        if (not self._enabled or stopped.is_set() or engine is None or mediainfo is None
                or mediainfo.type != MediaType.TV or season != 0 or isinstance(season, bool)
                or integer(episode, minimum=1) is None or mediainfo.episode_group
                or (mediainfo.scrape_source or settings.SCRAP_SOURCE) != "themoviedb"
                or integer(mediainfo.tmdb_id, minimum=1) is None):
            return None
        if not engine.client.configured and not engine.has_local_overrides:
            logger.debug("特典播放顺序：缺少 TMDb 或 TVDB 密钥，沿用基础刮削")
            return None
        try:
            content = None
            for module in ModuleManager().get_running_modules("metadata_nfo"):
                content = module.metadata_nfo(meta=meta, mediainfo=mediainfo, season=season, episode=episode)
                if content:
                    break
            if not isinstance(content, (bytes, str)) or not content or stopped.is_set():
                return None
            result = engine.enrich(content, int(mediainfo.tmdb_id), int(episode))
            engine.client.flush_cache()
            logger.info(f"特典播放顺序：TMDb {mediainfo.tmdb_id} S00E{int(episode):02d}：{result.reason}")
            if result.status != "updated" or stopped.is_set():
                return None
            output = result.content.decode("utf-8") if isinstance(result.content, bytes) else result.content
            logger.debug(
                f"特典播放顺序：已为 TMDb {mediainfo.tmdb_id} S00E{int(episode):02d} 生成补全后的 NFO"
                f"（{result.mapping_source}），{result.describe_changes()}"
            )
            return output
        except Exception as error:
            logger.warning(f"特典播放顺序：自动补全失败，沿用基础刮削 {type(error).__name__}")
            return None

    def get_state(self) -> bool:
        """返回插件有效启用状态。"""
        return self._enabled

    def get_module(self) -> dict:
        """稳定注册模块入口，配置开关由处理函数判断。"""
        return {"metadata_nfo": self.metadata_nfo}

    def stop_service(self) -> None:
        """取消待运行任务，并与文件写入互斥地停止旧代际。"""
        with self._write_lock:
            self._stopped.set()
            self._enabled = False
        try:
            scheduler.remove_plugin_once_job(self.__class__.__name__, "repair")
        except Exception:
            logger.debug("特典播放顺序：没有可取消的一次性任务或调度器尚未就绪")

    def get_api(self) -> list:
        """使用宿主配置及详情页接口，不另开插件 API。"""
        return []

    @staticmethod
    def get_form() -> tuple[list, dict]:
        """提供与文档一致的开关、范围、人工映射和预览选项。"""
        return [{"component": "VForm", "content": [
            {"component": "VRow", "props": {"class": "mb-2"}, "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "dry_run", "label": "仅预览（不修改 NFO）"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}]},
            ]},
            {"component": "VTextarea", "props": {"class": "mb-4", "model": "paths", "label": "扫描目录（每行一个）", "rows": 3, "hint": "填写 MP 内可访问的本地目录；范围内须含 tvshow.nfo；留空不扫描。"}},
            {"component": "VTextarea", "props": {
                "class": "mb-4", "model": "overrides", "label": "手动映射修正", "rows": 4,
                "placeholder": "938553,tvdb=8636540\n938554,airsafter_season=1\n938555,tvdb=8636542,airsbefore_episode=\n1174618,ignore",
                "hint": "每行以 TMDb 单集 ID 开头。使用 ,ignore 保留该集原有位置，或用逗号分隔 tvdb 和位置字段。映射成功后按结果更新三项位置，支持 # 注释。",
            }},
            {"component": "VCheckbox", "props": {
                "class": "mb-4", "model": "clear_cache", "label": "清空缓存",
                "hint": "保存时执行一次。下次扫描会重新查询元数据。",
                "persistent-hint": True,
            }},
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "启用后按映射同步 TMDb 默认编号的 Season 0 特典播放位置。修复已有 NFO 请先预览，再关闭仅预览并运行一次。修复会直接更新 NFO。"}},
        ]}], dict(DEFAULT_CONFIG)

    def get_page(self) -> list:
        """展示当前实例最近一次扫描的结果和位置变化。"""
        content = []
        if self._config_error:
            content.append({"component": "VAlert", "props": {"type": "error", "text": self._config_error}})
        if self._cache_cleared:
            content.append({"component": "VAlert", "props": {"type": "success", "class": "mb-4", "text": "缓存已清空。"}})
        report = self._last_report
        if not report:
            content.append({"component": "VAlert", "props": {"type": "info", "text": "暂无本次运行的扫描结果。可在配置页勾选「立即运行一次」进行预览。"}})
        else:
            records = report["records"]
            finished_at = report["finished_at"]
            try:
                finished_at = finished_at.astimezone(ZoneInfo(settings.TZ))
            except (ValueError, ZoneInfoNotFoundError):
                pass  # 宿主时区不可用时，使用记录的 UTC 时间。
            time_text = finished_at.isoformat(sep=" ", timespec="seconds")
            content.append({
                "component": "VAlert",
                "props": {"type": "info", "class": "mb-4"},
                "content": [
                    {"component": "div", "text": scan_summary(report)},
                    {"component": "div", "props": {"class": "text-caption"}, "text": f"扫描结束于 {time_text}"},
                ],
            })
            content.append(self._report_table(records))
        return [{"component": "VCol", "props": {"cols": 12}, "content": content}]

    @staticmethod
    def _report_table(records: list[dict]) -> dict:
        """显式声明表头和行，兼容 PageRender 默认插槽并安全呈现文件名。"""
        rows = []
        for record in records:
            label, color = SCAN_RESULTS[record["status"]]
            path = record["path"]
            directory, filename = split(path)
            path_lines = []
            if directory and filename:
                path_lines.append({
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis"},
                    "text": path.removesuffix(filename),
                })
            path_lines.append({"component": "div", "text": filename or path})
            rows.append({
                "component": "tr",
                "content": [
                    {
                        "component": "td",
                        "props": {"style": "overflow-wrap: anywhere; min-width: 10rem; max-width: 28rem"},
                        "content": path_lines,
                    },
                    {
                        "component": "td",
                        "props": {"style": "min-width: 10rem"},
                        "content": [
                            {"component": "strong", "props": {"class": f"text-{color}"}, "text": label},
                            {"component": "div", "props": {"class": "text-caption"}, "text": record["reason"]},
                        ],
                    },
                    {"component": "td", "props": {"class": "text-no-wrap"}, "content": SpecialEpisodeOrder._mapping_details(record)},
                    {"component": "td", "content": SpecialEpisodeOrder._position_diff(record)},
                ],
            })
        if not rows:
            rows.append({"component": "tr", "content": [{"component": "td", "props": {"colspan": 4}, "text": "本次扫描未找到符合条件的特典 NFO。"}]})
        # PageRender 总会提供默认插槽，VDataTable 的内置行会被覆盖，故使用显式 VTable。
        return {
            "component": "VTable",
            "props": {"density": "compact", "hover": True, "fixed-header": True, "height": 480 if len(records) > 10 else None},
            "content": [
                {"component": "thead", "content": [{"component": "tr", "content": [{"component": "th", "text": title} for title in ["文件", "结果", "映射", "播放位置"]]}]},
                {"component": "tbody", "content": rows},
            ],
        }

    @staticmethod
    def _mapping_details(record: dict) -> list[dict]:
        """展示映射来源与可独立选中的单集 ID。"""
        content = [{"component": "strong", "text": record.get("mapping_source") or "—"}]
        for label, key in (("TMDb", "tmdb_episode_id"), ("TVDB", "tvdb_episode_id")):
            episode_id = record.get(key)
            if episode_id is None:
                continue
            content.append({"component": "div", "props": {"class": "text-caption"}, "content": [
                {"component": "span", "text": f"{label} "},
                {"component": "code", "props": {"style": "font-size: inherit; padding-block: 0; user-select: all"}, "text": str(episode_id)},
            ]})
        return content

    @staticmethod
    def _position_diff(record: dict) -> list[dict]:
        """逐项显示三个位置字段，高亮发生变化的旧值和新值。"""
        before, after = record.get("before", {}), record.get("after", {})
        fields = []
        for _, tag, _ in POSITION_TAGS:
            old = SpecialEpisodeOrder._position_value(before, tag)
            new = SpecialEpisodeOrder._position_value(after, tag)
            if old == new:
                value = {"component": "span", "text": new}
            else:
                value = {
                    "component": "span", "props": {"class": "d-inline-flex flex-wrap ga-1"},
                    "content": [
                        {"component": element, "text": text, "props": {"style": (
                            "border-radius: 3px; padding-inline: 0.3em; text-decoration: none; "
                            f"background-color: rgba(var(--v-theme-{tone}), 0.16); "
                            f"color: color-mix(in srgb, rgb(var(--v-theme-{tone})) 55%, rgb(var(--v-theme-on-surface)))"
                        )}}
                        for element, tone, text in (("del", "error", old), ("ins", "success", new))
                    ],
                }
            fields.append({
                "component": "div",
                "props": {
                    "class": "text-body-2",
                    "style": "display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 0.5rem; min-width: 12rem; overflow-wrap: anywhere",
                },
                "content": [
                    {"component": "code", "props": {"style": "min-width: 10rem; padding-block: 0"}, "text": tag},
                    value,
                ],
            })
        return fields

    @staticmethod
    def _position_value(positions: dict, tag: str) -> str:
        """区分未读取、未设置、空值和实际值。"""
        if tag not in positions:
            return "未读取"
        return format_position(positions[tag])
