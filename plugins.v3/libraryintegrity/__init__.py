"""影视库完整性检查：基于 Emby 检查缺集、同季版本一致性与多文件，只生成报告。"""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field

from app.schemas import Response
from app.schemas.types import MessageType
from app.sdk import scheduler as scheduler_sdk
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase

from .ai import AiAdvisor, ai_available
from .checks import (
    apply_ignore_rules,
    parse_identity_overrides,
    parse_ignore_rules,
    parse_number_mappings,
    parse_scope,
)
from .config import DEFAULT_CONFIG, local_dirs, normalize_config, to_scan_options
from .emby import EmbyReader, EmbySource
from .local import LocalSource
from .models import ISSUE_TYPE_LABELS, Issue, IssueType, Report
from .nfo import NfoReader, PathMapper
from .page import build_form, build_page, build_summary_text
from .probe import MediaProbe, find_probe_binary
from .scanner import LibrarySource, LibraryScanner
from .tmdb import TmdbSource

# 一次性扫描任务 ID
SCAN_JOB_ID = "scan"
# 报告保存在插件数据目录中的文件名；旧版本保存在插件数据（数据库）中的键名
REPORT_FILE = "report.json"
LEGACY_REPORT_KEY = "report"


class ScanTriggerData(BaseModel):
    """触发扫描接口的业务数据。"""

    queued: bool = Field(description="是否已加入执行队列")


class IgnoreRequest(BaseModel):
    """添加忽略规则的请求体。"""

    key: str = Field(description="范围键，如 tmdb:1399:S2")
    type: Optional[str] = Field(default=None, description="限定的问题类型；为空时忽略该范围的全部问题")


class IgnoreData(BaseModel):
    """添加忽略规则接口的业务数据。"""

    rule: str = Field(description="添加的规则")
    total: int = Field(description="当前规则总数")


class AdoptRequest(BaseModel):
    """采纳 AI 建议的请求体。"""

    kind: str = Field(description="规则类型：mapping（编号映射）或 identity（身份指定）")
    rule: str = Field(description="规则文本，可包含多行")


class AdoptData(BaseModel):
    """采纳接口的业务数据。"""

    rule: str = Field(description="写入的规则")
    total: int = Field(description="该类规则当前总数")


class ReportView(BaseModel):
    """报告查询接口的业务数据。"""

    running: bool = Field(description="是否正在扫描")
    progress: str = Field(default="", description="当前扫描进度")
    report: Optional[Report] = Field(default=None, description="最近一次完整扫描的报告（含全部问题）")
    issues: List[Issue] = Field(default_factory=list, description="应用忽略规则后的问题")
    ignored: int = Field(default=0, description="被忽略规则隐藏的问题数量")


class LibraryIntegrity(_PluginBase):
    """影视库完整性检查插件主类：管理配置、定时与手动扫描、报告页和接口。"""

    plugin_name = "影视库完整性检查"
    plugin_desc = "检查剧集缺集、同季版本不一致与多文件，支持 Emby 与本地目录（含 strm、NFO、媒体信息），可选 AI 建议，只生成报告不改动文件。"
    plugin_icon = "Emby_A.png"
    plugin_version = "1.0.7"
    plugin_label = "媒体库,Emby,检查,AI"
    plugin_author = "Derrors"
    author_url = "https://github.com/Derrors"
    plugin_config_prefix = "libraryintegrity_"
    plugin_order = 60
    auth_level = 1

    _enabled = False
    _config: Dict[str, Any]
    _stop_event: Optional[threading.Event] = None
    _scan_lock: Optional[threading.Lock] = None
    _progress = ""

    def __init__(self) -> None:
        """初始化宿主提供的插件能力，并为每个实例准备独立的默认配置副本。"""
        super().__init__()
        self._config = normalize_config(None)

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """读取配置并重建运行状态；迁移旧版报告；保存时勾选了立即扫描则加入一次性任务。"""
        self.stop_service()
        self._migrate_legacy_report()
        self._config = normalize_config(config)
        self._enabled = self._config["enabled"]
        self._stop_event = threading.Event()
        self._scan_lock = threading.Lock()
        self._progress = ""
        if self._config["onlyonce"]:
            self._config["onlyonce"] = False
            self.update_config(self._config)
            if self._enabled:
                self._queue_scan()
            else:
                logger.warning("影视库完整性检查：插件未启用，已忽略立即扫描")

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册报告页按钮与外部查询使用的接口。"""
        return [
            {
                "path": "/scan",
                "endpoint": self.api_scan,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即扫描",
                "response_model": Response[ScanTriggerData],
            },
            {
                "path": "/ignore",
                "endpoint": self.api_ignore,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "添加忽略规则",
                "response_model": Response[IgnoreData],
            },
            {
                "path": "/adopt",
                "endpoint": self.api_adopt,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "采纳 AI 建议",
                "response_model": Response[AdoptData],
            },
            {
                "path": "/report",
                "endpoint": self.api_report,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询扫描报告",
                "response_model": Response[ReportView],
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """插件启用且配置了 cron 时注册定时扫描。"""
        if not self._enabled or not self._config.get("cron"):
            return []
        try:
            trigger = CronTrigger.from_crontab(self._config["cron"])
        except ValueError as err:
            logger.error(f"影视库完整性检查：cron 表达式无效：{err}")
            return []
        return [{
            "id": f"{self.__class__.__name__}.Scan",
            "name": "影视库完整性检查",
            "trigger": trigger,
            "func": self.run_scan,
            "kwargs": {},
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置页面与默认配置。"""
        return build_form(self._emby_server_names()), dict(DEFAULT_CONFIG)

    def get_page(self) -> List[dict]:
        """返回报告详情页。"""
        report = self._load_report()
        visible, ignored = self._visible_issues(report)
        return build_page(self.__class__.__name__, report, visible, ignored, self._progress)

    def get_agent_tools(self) -> List[type]:
        """插件启用时为智能助手提供只读的报告查询工具。"""
        if not self._enabled:
            return []
        try:
            from .agent import build_agent_tools

            return build_agent_tools(self.__class__.__name__)
        except Exception as err:  # noqa: BLE001 - 宿主未提供智能助手时不注册工具
            logger.debug(f"影视库完整性检查：智能助手工具不可用：{err}")
            return []

    def stop_service(self) -> None:
        """通知正在执行的扫描尽快结束，并取消尚未执行的一次性扫描。"""
        if self._stop_event is not None:
            self._stop_event.set()
        try:
            scheduler_sdk.remove_plugin_once_job(self.__class__.__name__, SCAN_JOB_ID)
        except Exception as err:  # noqa: BLE001 - 调度器未运行时不影响停止
            logger.debug(f"影视库完整性检查：取消一次性扫描失败：{err}")

    # ------------------------------------------------------------------
    # 接口
    # ------------------------------------------------------------------

    def api_scan(self) -> Response[ScanTriggerData]:
        """加入一次性扫描任务。"""
        if not self._enabled:
            return Response(success=False, message="请先启用插件", data=ScanTriggerData(queued=False))
        if self._is_running():
            return Response(success=False, message="已有扫描正在进行", data=ScanTriggerData(queued=False))
        queued = self._queue_scan()
        return Response(
            success=queued,
            message="已开始扫描，稍后刷新查看进度" if queued else "调度器未运行，无法开始扫描",
            data=ScanTriggerData(queued=queued),
        )

    def api_ignore(self, payload: IgnoreRequest) -> Response[IgnoreData]:
        """把范围键（可限定问题类型）追加到忽略规则。"""
        key = str(payload.key or "").strip()
        if not key or parse_scope(key) is None or "@" in key:
            return Response(success=False, message="范围键无效", data=None)
        rule = key
        if payload.type:
            try:
                rule = f"{IssueType(payload.type).value}@{key}"
            except ValueError:
                return Response(success=False, message="问题类型无效", data=None)
        lines = [line for line in self._config["ignore_rules"].splitlines() if line.strip()]
        if rule not in (line.strip() for line in lines):
            lines.append(rule)
            self._config["ignore_rules"] = "\n".join(lines)
            self.update_config(self._config)
        return Response(
            success=True,
            message=f"已忽略：{rule}",
            data=IgnoreData(rule=rule, total=len(parse_ignore_rules(self._config["ignore_rules"]))),
        )

    def api_adopt(self, payload: AdoptRequest) -> Response[AdoptData]:
        """把 AI 建议的编号映射或身份指定写入对应规则；只接受能被解析的规则。"""
        lines = [line.strip() for line in str(payload.rule or "").splitlines() if line.strip()]
        if payload.kind == "mapping":
            key, parser = "number_mappings", parse_number_mappings
        elif payload.kind == "identity":
            key, parser = "identity_overrides", parse_identity_overrides
        else:
            return Response(success=False, message="规则类型无效", data=None)
        if not lines or any(not parser(line) for line in lines):
            return Response(success=False, message="规则格式无效", data=None)
        existing = [line for line in self._config[key].splitlines() if line.strip()]
        added = [line for line in lines if line not in (e.strip() for e in existing)]
        if added:
            self._config[key] = "\n".join(existing + added)
            self.update_config(self._config)
        total = sum(len(v) for v in parser(self._config[key]).values()) if payload.kind == "mapping" \
            else len(parser(self._config[key]))
        return Response(
            success=True,
            message="已采纳，下次扫描生效",
            data=AdoptData(rule="\n".join(lines), total=total),
        )

    def api_report(self) -> Response[ReportView]:
        """返回最近一次报告及应用忽略规则后的问题。"""
        report = self._load_report()
        visible, ignored = self._visible_issues(report)
        return Response(
            success=True,
            data=ReportView(
                running=self._is_running(),
                progress=self._progress,
                report=report,
                issues=visible,
                ignored=ignored,
            ),
        )

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------

    def run_scan(self) -> None:
        """执行一次完整扫描；同一实例同时只运行一个扫描，被停止的扫描不覆盖已有报告。"""
        lock = self._scan_lock
        stop_event = self._stop_event
        if lock is None or stop_event is None:
            return
        if not lock.acquire(blocking=False):
            logger.info("影视库完整性检查：已有扫描正在进行，跳过本次触发")
            return
        probe: Optional[MediaProbe] = None
        tmdb: Optional[TmdbSource] = None
        try:
            config = self._config
            probe = self._build_probe()
            sources, errors = self._build_sources(stop_event, probe)
            tmdb = TmdbSource(self.get_data_path() / "tmdb_cache.json") if config["check_missing"] else None
            scanner = LibraryScanner(
                to_scan_options(config), tmdb, stop_event,
                progress=self._set_progress, advisor=self._build_advisor(errors),
            )
            logger.info("影视库完整性检查：开始扫描")
            report = scanner.scan(sources)
            if probe is not None:
                report.stats.probes = probe.probed
                if probe.skipped:
                    report.errors.append(f"本轮新读取媒体信息已达上限，{probe.skipped} 个文件留到下次扫描")
            report.errors = errors + report.errors
            if report.cancelled:
                logger.info("影视库完整性检查：扫描被停止，保留上一次报告")
                return
            self._save_report(report)
            visible, ignored = self._visible_issues(report)
            logger.info(
                f"影视库完整性检查：扫描完成，{report.stats.series} 部剧，"
                f"{len(visible)} 条问题，忽略 {ignored} 条，耗时 {report.duration_seconds} 秒"
            )
            if config["notify"]:
                self.post_message(
                    mtype=MessageType.Plugin,
                    title="【影视库完整性检查】扫描完成",
                    text=build_summary_text(report, visible, ignored),
                )
        except Exception as err:  # noqa: BLE001 - 后台任务需记录异常而不是静默退出
            logger.error(f"影视库完整性检查：扫描失败：{err}", exc_info=True)
        finally:
            if tmdb is not None:
                tmdb.save()
                tmdb.close()
            if probe is not None:
                probe.save()
            self._progress = ""
            lock.release()

    def _queue_scan(self) -> bool:
        """把扫描交给宿主调度器执行一次。"""
        queued = scheduler_sdk.add_plugin_once_job(
            self.__class__.__name__, SCAN_JOB_ID, self.run_scan, "影视库完整性检查", delay_seconds=3
        )
        if not queued:
            logger.warning("影视库完整性检查：调度器未运行，无法加入扫描任务")
        return bool(queued)

    def _build_sources(
        self, stop_event: threading.Event, probe: Optional[MediaProbe]
    ) -> Tuple[List[LibrarySource], List[str]]:
        """按配置组装数据源：已连接的 Emby 服务器与本地扫描目录。"""
        config = self._config
        sources: List[LibrarySource] = []
        errors: List[str] = []
        if config["use_emby"]:
            readers, emby_errors = self._build_readers()
            errors.extend(emby_errors)
            nfo = NfoReader(PathMapper(config["path_mappings"])) if config["read_nfo"] else None
            sources.extend(EmbySource(reader, config["libraries"], nfo) for reader in readers)
        roots = local_dirs(config)
        if roots:
            sources.append(LocalSource(roots, stop_event, probe=probe))
        if not sources and not errors:
            errors.append("没有可扫描的数据源：请启用 Emby 或填写本地扫描目录")
        return sources, errors

    def _build_readers(self) -> Tuple[List[EmbyReader], List[str]]:
        """按配置获取已启用且已连接的 Emby 服务实例。"""
        from app.sdk.services import MediaServerHelper

        names = self._config["servers"] or None
        services = MediaServerHelper().get_services(type_filter="emby", name_filters=names)
        readers: List[EmbyReader] = []
        errors: List[str] = []
        for name, service in services.items():
            instance = service.instance
            if instance is None or (hasattr(instance, "is_inactive") and instance.is_inactive()):
                errors.append(f"Emby 服务器 {name} 未连接")
                continue
            readers.append(EmbyReader(str(name), instance))
        if not services:
            errors.append("未找到已启用的 Emby 媒体服务器")
        return readers, errors

    def _build_probe(self) -> Optional[MediaProbe]:
        """启用本地媒体信息读取且找到 ffprobe/mediainfo 时创建读取器。"""
        config = self._config
        if not config["local_probe"] or not local_dirs(config):
            return None
        kind, binary = find_probe_binary(config["probe_path"])
        if not binary:
            logger.warning("影视库完整性检查：未找到 ffprobe 或 mediainfo，跳过本地媒体信息读取")
            return None
        return MediaProbe(self.get_data_path() / "probe_cache.json", binary, kind, max_new=config["probe_max_files"])

    def _build_advisor(self, errors: List[str]) -> Optional[AiAdvisor]:
        """启用 AI 建议且系统智能助手可用时创建 AI 顾问。"""
        config = self._config
        if not config["ai_enabled"]:
            return None
        if not ai_available():
            errors.append("已启用 AI 建议，但系统未启用智能助手，本轮未调用 AI")
            return None
        return AiAdvisor()

    def _emby_server_names(self) -> List[str]:
        """返回已配置的 Emby 服务器名称，供配置页选择。"""
        try:
            from app.sdk.services import MediaServerHelper

            configs = MediaServerHelper().get_configs()
        except Exception as err:  # noqa: BLE001
            logger.debug(f"影视库完整性检查：读取媒体服务器配置失败：{err}")
            return []
        return [name for name, conf in configs.items() if str(getattr(conf, "type", "")).lower() == "emby"]

    def _set_progress(self, text: str) -> None:
        """记录当前扫描进度。"""
        self._progress = text

    def _is_running(self) -> bool:
        """判断是否有扫描正在执行。"""
        return self._scan_lock is not None and self._scan_lock.locked()

    def _report_path(self) -> Path:
        """返回报告文件路径；报告体积可能较大，按开发指南写入插件数据目录而不是插件数据表。"""
        return self.get_data_path() / REPORT_FILE

    def _save_report(self, report: Report) -> None:
        """先写临时文件再替换，避免读取到写了一半的报告。"""
        path = self._report_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _load_report(self) -> Optional[Report]:
        """读取最近一次报告，文件不存在或损坏时视为没有报告。"""
        path = self._report_path()
        try:
            return Report.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as err:
            logger.warning(f"影视库完整性检查：报告文件无法解析：{err}")
            return None

    def _migrate_legacy_report(self) -> None:
        """把旧版本保存在插件数据表中的报告搬到数据目录的文件中，成功后删除旧数据。"""
        try:
            data = self.get_data(LEGACY_REPORT_KEY)
            if not data:
                return
            if not self._report_path().exists():
                self._save_report(Report.model_validate(data))
                logger.info("影视库完整性检查：已把旧版报告迁移到插件数据目录")
            self.del_data(LEGACY_REPORT_KEY)
        except Exception as err:  # noqa: BLE001 - 迁移失败不影响插件启动，下次扫描会生成新报告
            logger.warning(f"影视库完整性检查：迁移旧版报告失败：{err}")

    async def async_query_text(
        self, issue_type: Optional[str] = None, keyword: Optional[str] = None, limit: int = 20
    ) -> str:
        """供智能助手工具调用：按类型与关键词筛选报告并返回文本。"""
        report = await asyncio.to_thread(self._load_report)
        if report is None:
            return "还没有可用的影视库完整性报告，请先在插件中执行扫描。"
        visible, ignored = self._visible_issues(report)
        if issue_type:
            try:
                wanted = IssueType(issue_type.strip().lower())
            except ValueError:
                return f"不支持的问题类型：{issue_type}"
            visible = [issue for issue in visible if issue.type == wanted]
        if keyword:
            text = keyword.strip().lower()
            visible = [issue for issue in visible if text in issue.title.lower()]
        limit = max(1, min(100, int(limit or 20)))
        lines = [
            f"报告时间 {report.finished_at}，共 {len(visible)} 条匹配问题（已忽略 {ignored} 条）"
            + (f"，以下列出前 {limit} 条" if len(visible) > limit else "")
        ]
        for issue in visible[:limit]:
            lines.append(f"- [{ISSUE_TYPE_LABELS[issue.type]}] {issue.title}（{issue.server}/{issue.library}）：{issue.summary}")
            lines.extend(f"    {detail}" for detail in issue.details[:5])
        if report.ai_summary and not issue_type and not keyword:
            lines.append(f"AI 摘要：{report.ai_summary}")
        return "\n".join(lines)

    def _visible_issues(self, report: Optional[Report]) -> Tuple[List[Issue], int]:
        """按当前忽略规则过滤报告中的问题。"""
        if report is None:
            return [], 0
        return apply_ignore_rules(report.issues, parse_ignore_rules(self._config.get("ignore_rules", "")))
