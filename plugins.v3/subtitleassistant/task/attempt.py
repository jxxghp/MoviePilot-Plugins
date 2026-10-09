"""单个字幕候选尝试的下载、解包、归属与落盘流水线。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from anyio import Path as AsyncPath

from app.log import logger

from ..attribution import CandidateRecognizer, FileAttributor
from ..record import RecordCommitter
from ..schemas.attribution import (
    AttributionEvidence,
    FileAttributionEvidence,
    FileAttributionMethod,
    FileAttributionRequest,
    PackageAttributionStrategy,
    UnmatchedReason,
)
from ..schemas.candidate import SubtitleCandidate
from ..schemas.config import PluginConfig
from ..schemas.event import SubtitleWrittenOperation
from ..schemas.file import ExtractedSubtitle
from ..schemas.record import (
    CommittedFileFact,
    FileLocation,
    MatchRecord,
    RecordStatus,
)
from ..schemas.source import CandidateHandle, DownloadedAsset, SubtitleSource
from ..schemas.target import (
    MediaType,
    PathMappingSnapshot,
    SubtitleTarget,
)
from ..schemas.task import (
    AttemptResult,
    CandidateAttemptReasonCode,
)
from ..schemas.task import (
    _CandidateAttemptRetention as FailureResultRetention,
)
from ..source import CandidatePool


@dataclass(frozen=True, slots=True)
class AttributedSubtitle:
    """运行期物理字幕文件及其归属证据。"""

    extracted: ExtractedSubtitle
    evidence: FileAttributionEvidence


@dataclass(frozen=True, slots=True)
class CandidateAttemptRequest:
    """候选尝试所需的冻结输入，不持有任务或人工会话实体。"""

    task_id: str
    handle: CandidateHandle
    target: SubtitleTarget
    operation: SubtitleWrittenOperation
    retention: FailureResultRetention
    package_attribution_strategy: PackageAttributionStrategy
    attempt_number: int
    target_history_id: int | None = None
    history_target_path: Path | None = None
    matched_path_mapping: PathMappingSnapshot | None = None
    target_file_exists: bool | None = None


@dataclass(frozen=True, slots=True)
class CandidateAttemptResult:
    """候选尝试返回的唯一业务结论。"""

    records: tuple[MatchRecord, ...]
    result: AttemptResult
    reason_code: CandidateAttemptReasonCode | None = None
    error_summary: str | None = None
    committed_media_records: tuple[MatchRecord, ...] = ()
    committed_files: tuple[CommittedFileFact, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CandidateWriteResult:
    """单个候选字幕写入的结构化结果。"""

    record: MatchRecord | None = None
    committed_file: CommittedFileFact | None = None
    error_summary: str | None = None
    reason_code: CandidateAttemptReasonCode | None = None


class _AttemptPhase(StrEnum):
    """候选流水线的内部阶段，仅用于失败归类与阶段文案。"""

    DOWNLOAD = "download"
    EXTRACT = "extract"
    MATCH = "match"
    WRITE = "write"


class CandidateAttemptFileSystemPort(Protocol):
    """候选尝试所需的字幕文件操作能力。"""

    async def make_task_directory(self, task_id: str) -> Path:
        """创建候选尝试临时目录。"""

    async def target_directory_status(self, target: Path) -> tuple[bool, str | None]:
        """检查目标字幕目录是否可用。"""


class CandidateAttemptArchivePort(Protocol):
    """候选尝试所需的字幕归档解包能力。"""

    async def extract(
        self,
        asset: DownloadedAsset,
        output: Path,
        allowed_formats: set[str],
    ) -> list[ExtractedSubtitle]:
        """解包下载结果并返回受支持的字幕文件。"""


class CandidateAttemptSourcePort(Protocol):
    """候选尝试所需的字幕源下载能力。"""

    async def download(self, handle: CandidateHandle, directory: Path) -> DownloadedAsset:
        """下载候选到指定临时目录。"""


_PHASE_RESULTS: Mapping[_AttemptPhase, AttemptResult] = {
    _AttemptPhase.DOWNLOAD: AttemptResult.DOWNLOAD_FAILED,
    _AttemptPhase.EXTRACT: AttemptResult.EXTRACT_FAILED,
    _AttemptPhase.MATCH: AttemptResult.NO_MATCH,
    _AttemptPhase.WRITE: AttemptResult.WRITE_FAILED,
}

_PHASE_NAMES: Mapping[_AttemptPhase, str] = {
    _AttemptPhase.DOWNLOAD: "候选下载",
    _AttemptPhase.EXTRACT: "下载结果解包",
    _AttemptPhase.MATCH: "字幕匹配",
    _AttemptPhase.WRITE: "字幕落盘",
}

CandidateLabel = Callable[[SubtitleCandidate], str]
TaskLabel = Callable[[str], str]


class CandidateAttemptService:
    """处理一个字幕候选，不读取任务触发方式或任务队列状态。"""

    def __init__(
        self,
        filesystem: CandidateAttemptFileSystemPort,
        archive: CandidateAttemptArchivePort,
        matcher: CandidateRecognizer,
        sources: CandidatePool,
        config: PluginConfig,
        inventory: RecordCommitter,
        attributor: FileAttributor | None = None,
        source_adapters: Mapping[SubtitleSource, CandidateAttemptSourcePort] | None = None,
        *,
        task_label: TaskLabel | None = None,
        candidate_label: CandidateLabel | None = None,
    ) -> None:
        """绑定候选流水线所需的文件、来源、归属和记录协作者。"""

        self.filesystem = filesystem
        self.archive = archive
        self.matcher = matcher
        if attributor is not None:
            self.attributor = attributor
        elif callable(getattr(matcher, "attribute_requests", None)):
            self.attributor = cast(FileAttributor, matcher)
        else:
            raise TypeError("候选流水线必须注入文件归属 facade")
        self._source_downloader = sources
        self._source_adapters = source_adapters
        self.sources = sources
        self.config = config
        self.inventory = inventory
        self._task_label = task_label or (lambda task_id: f"任务 {task_id}")
        self._candidate_label = candidate_label or (lambda candidate: f"候选“{candidate.name}”")

    async def attempt(self, request: CandidateAttemptRequest) -> CandidateAttemptResult:
        """执行单个候选的下载、解包、归属和落盘并返回业务结论。"""

        context = request.target
        handle = request.handle
        retention = request.retention
        candidate = handle.candidate
        attempt_result = AttemptResult.NO_MATCH
        error_summary: str | None = None
        active_phase = _AttemptPhase.DOWNLOAD
        selected_results: list[AttributedSubtitle] = []
        additional: list[AttributedSubtitle] = []
        extracted_files: list[ExtractedSubtitle] = []
        written_records: list[MatchRecord] = []
        committed_files: list[CommittedFileFact] = []
        preserved_records: list[MatchRecord] = []
        warnings: list[str] = []
        first_write_failure_seen = False
        write_reason_code: CandidateAttemptReasonCode | None = None

        def result_reason_code(
            reason_code: CandidateAttemptReasonCode | None,
        ) -> CandidateAttemptReasonCode | None:
            """把通用失败收敛为保留策略对应的人工失败原因。"""

            if reason_code is not None or retention is FailureResultRetention.DISCARD:
                return reason_code
            if attempt_result is AttemptResult.INTERRUPTED:
                return None
            return CandidateAttemptReasonCode.MANUAL_CANDIDATE_FAILED

        def conclude(
            records: Sequence[MatchRecord],
            reason_code: CandidateAttemptReasonCode | None,
            committed: Sequence[CommittedFileFact] = (),
        ) -> CandidateAttemptResult:
            """把业务记录、终态原因与已提交文件收敛为候选结论。"""

            return CandidateAttemptResult(
                records=(*records, *preserved_records),
                result=attempt_result,
                reason_code=result_reason_code(reason_code),
                error_summary=error_summary,
                committed_media_records=tuple(records),
                committed_files=tuple(committed),
                warnings=tuple(warnings),
            )

        task_dir = await self.filesystem.make_task_directory(request.task_id)
        candidate_dir = task_dir / f"candidate-{request.attempt_number}"
        await AsyncPath(candidate_dir).mkdir(parents=True, exist_ok=True)
        try:
            active_phase = _AttemptPhase.DOWNLOAD
            logger.info(f"{self._task_label(request.task_id)}开始下载{self._candidate_label(candidate)}")
            downloader = getattr(self._source_downloader, "download", None)
            if callable(downloader):
                asset = await downloader(handle, candidate_dir)
            else:
                getter = getattr(self._source_downloader, "__getitem__", None)
                if callable(getter):
                    asset = await getter(candidate.source).download(handle, candidate_dir)
                elif self._source_adapters is not None:
                    asset = await self._source_adapters[candidate.source].download(handle, candidate_dir)
                else:
                    raise TypeError("来源下载能力未装配")
            logger.info(
                f"{self._task_label(request.task_id)}已下载{self._candidate_label(candidate)}，得到文件“{asset.file_name}”"
            )
            asset_extension = asset.path.suffix.lower().lstrip(".")
            archive_extensions = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "cab", "iso"}
            allowed_extensions = {value.lower().lstrip(".") for value in self.config.format_priority}
            if (
                retention is FailureResultRetention.PRESERVE
                and asset_extension not in allowed_extensions | archive_extensions
            ):
                unsupported = AttributedSubtitle(
                    extracted=ExtractedSubtitle(
                        physical_path=asset.path,
                        logical_source_path=Path(asset.file_name),
                        is_direct_file=True,
                    ),
                    evidence=FileAttributionEvidence(
                        logical_source_path=Path(asset.file_name),
                        method=FileAttributionMethod.DIRECT_FILE,
                        belongs_to_target_media=None,
                        unmatched_reason=UnmatchedReason.UNSUPPORTED_FORMAT,
                    ),
                )
                extracted_files.append(unsupported.extracted)
                record = await self._save_plugin_result(
                    request,
                    context,
                    candidate,
                    unsupported,
                    bind_target=True,
                )
                preserved_records.append(record)
                attempt_result = AttemptResult.NO_MATCH
                error_summary = "字幕格式未知或不受宿主支持，文件已保存为未匹配"
                logger.warning(
                    f"{self._task_label(request.task_id)}下载的文件“{asset.file_name}”格式不受宿主支持，"
                    f"已保存为未匹配记录 {record.id}"
                )
                return conclude([], CandidateAttemptReasonCode.UNSUPPORTED_FORMAT)

            active_phase = _AttemptPhase.EXTRACT
            extracted_files = await self.archive.extract(
                asset,
                candidate_dir / "extracted",
                set(self.config.format_priority),
            )
            if not extracted_files:
                attempt_result = AttemptResult.NO_MATCH
                error_summary = "候选包没有允许格式字幕"
                return conclude([], None)
            logger.info(
                f"{self._task_label(request.task_id)}已从{self._candidate_label(candidate)}中取得 "
                f"{len(extracted_files)} 个受支持的字幕文件"
            )
            active_phase = _AttemptPhase.MATCH
            selected_results, additional = await self._candidate_files(
                request,
                context,
                handle,
                extracted_files,
            )
            if not selected_results:
                attempt_result = AttemptResult.NO_MATCH
                if retention is FailureResultRetention.PRESERVE:
                    saved, save_warnings = await self._save_additional_results(
                        request,
                        context,
                        candidate,
                        additional,
                    )
                    preserved_records.extend(saved)
                    warnings.extend(save_warnings)
                    error_summary = "候选包未找到当前目标字幕，其他有效结果已保留"
                else:
                    error_summary = "候选包未找到当前目标字幕"
                return conclude([], CandidateAttemptReasonCode.CANDIDATE_MISSING_TARGET_SUBTITLE)

            if retention is FailureResultRetention.PRESERVE:
                directory_available, directory_error = await self.filesystem.target_directory_status(
                    context.target_path
                )
                if not directory_available:
                    saved, save_warnings = await self._save_additional_results(
                        request,
                        context,
                        candidate,
                        selected_results + additional,
                    )
                    preserved_records.extend(saved)
                    warnings.extend(save_warnings)
                    attempt_result = AttemptResult.WRITE_FAILED
                    error_summary = f"目标目录不可用：{directory_error or '无法写入'}，下载结果已保留"
                    return conclude([], CandidateAttemptReasonCode.TARGET_DIRECTORY_UNAVAILABLE)

            active_phase = _AttemptPhase.WRITE
            write_errors: list[str] = []
            for selected in selected_results:
                write_result = await self._write_candidate_file(
                    request,
                    context,
                    candidate,
                    selected,
                )
                record = write_result.record
                if record is None:
                    if write_result.error_summary is not None:
                        write_errors.append(write_result.error_summary)
                    if not first_write_failure_seen:
                        first_write_failure_seen = True
                        write_reason_code = write_result.reason_code
                    continue
                written_records.append(record)
                if write_result.committed_file is None:
                    raise AssertionError("已提交媒体字幕缺少文件事实")
                committed_files.append(write_result.committed_file)
                logger.info(
                    f"{self._task_label(request.task_id)}已将字幕"
                    f"“{selected.extracted.logical_source_path}”写入“{record.final_subtitle_path}”，"
                    f"匹配记录为 {record.id}"
                )
            if not written_records:
                attempt_result = AttemptResult.WRITE_FAILED
                error_summary = write_errors[0] if write_errors else "没有形成已匹配记录"
                if retention is FailureResultRetention.PRESERVE:
                    saved, save_warnings = await self._save_additional_results(
                        request,
                        context,
                        candidate,
                        selected_results + additional,
                    )
                    preserved_records.extend(saved)
                    warnings.extend(save_warnings)
                    error_summary += "，下载结果已保留"
                return conclude([], write_reason_code)
            if write_errors:
                error_summary = f"部分字幕文件落盘失败：{'；'.join(write_errors)}"
                warnings.extend(f"部分字幕文件落盘失败：{error}" for error in write_errors)
            active_phase = _AttemptPhase.MATCH
            saved, save_warnings = await self._save_additional_results(
                request,
                context,
                candidate,
                additional,
            )
            preserved_records.extend(saved)
            warnings.extend(save_warnings)
            attempt_result = AttemptResult.SUCCESS
            return conclude(written_records, None, committed_files)
        except asyncio.CancelledError:
            attempt_result = AttemptResult.INTERRUPTED
            return conclude(written_records, None, committed_files)
        except FileExistsError:
            attempt_result = AttemptResult.WRITE_FAILED
            error_summary = "目标字幕已存在，未覆盖"
            if retention is FailureResultRetention.PRESERVE and selected_results:
                try:
                    saved, save_warnings = await self._save_additional_results(
                        request,
                        context,
                        candidate,
                        selected_results + additional,
                    )
                    preserved_records.extend(saved)
                    warnings.extend(save_warnings)
                    error_summary = "目标字幕已存在，下载结果已保留"
                except Exception as exc:  # noqa: BLE001 - 保留下载结果失败应返回安全失败
                    error_summary = f"目标字幕已存在，下载结果保留失败：{type(exc).__name__}"
            return conclude(written_records, CandidateAttemptReasonCode.SUBTITLE_DESTINATION_CONFLICT, committed_files)
        except OSError as exc:
            attempt_result = AttemptResult.WRITE_FAILED
            error_summary = f"文件操作失败：{type(exc).__name__}"
            if (
                retention is FailureResultRetention.PRESERVE
                and active_phase is _AttemptPhase.WRITE
                and selected_results
            ):
                try:
                    saved, save_warnings = await self._save_additional_results(
                        request,
                        context,
                        candidate,
                        selected_results + additional,
                    )
                    preserved_records.extend(saved)
                    warnings.extend(save_warnings)
                    error_summary += "，下载结果已保留"
                except Exception as preserve_exc:  # noqa: BLE001 - 保留下载结果失败应返回安全失败
                    error_summary += f"，下载结果保留失败：{type(preserve_exc).__name__}"
            return conclude(written_records, None, committed_files)
        except RuntimeError as exc:
            attempt_result = _PHASE_RESULTS[active_phase]
            if type(exc).__name__ in {"SourceRequestError", "SourceLimitedError"}:
                error_summary = str(exc)
            else:
                error_summary = f"{_PHASE_NAMES[active_phase]}阶段失败：{exc}"
            return conclude(written_records, None, committed_files)
        except Exception as exc:  # noqa: BLE001 - 候选边界必须收敛运行时失败
            attempt_result = _PHASE_RESULTS[active_phase]
            error_summary = f"候选处理失败：{type(exc).__name__}"
            return conclude(written_records, None, committed_files)

    async def _candidate_files(
        self,
        request: CandidateAttemptRequest,
        context: SubtitleTarget,
        handle: CandidateHandle,
        files: list[ExtractedSubtitle],
    ) -> tuple[list[AttributedSubtitle], list[AttributedSubtitle]]:
        """逐文件归属并选出当前目标第一优先字幕。"""

        candidate = handle.candidate
        snapshot = self.matcher.candidate_snapshot(candidate)
        attributed: list[AttributedSubtitle] = []
        other_media_count = 0
        use_direct_file_evidence = (
            request.operation is SubtitleWrittenOperation.MANUAL_CANDIDATE
            or request.package_attribution_strategy is PackageAttributionStrategy.TRUST_PACKAGE
        )
        host_file_count = sum(1 for extracted in files if not extracted.is_direct_file or not use_direct_file_evidence)
        if request.package_attribution_strategy is PackageAttributionStrategy.HOST_RECOGNITION and host_file_count:
            logger.info(
                f"{self._task_label(request.task_id)}开始调用 MoviePilot 文件识别处理"
                f"{self._candidate_label(candidate)}中的 {host_file_count} 个字幕"
            )
        for extracted in files:
            if extracted.is_direct_file and use_direct_file_evidence:
                evidence = FileAttributionEvidence(
                    logical_source_path=Path(extracted.logical_source_path),
                    method=FileAttributionMethod.DIRECT_FILE,
                    belongs_to_target_media=True,
                    media_type=context.media_type,
                    tmdb_id=context.tmdb_id,
                    imdb_id=context.imdb_id,
                    season=context.season,
                    episode=context.episode,
                    season_evidence=AttributionEvidence.NOT_APPLICABLE,
                    episode_evidence=AttributionEvidence.NOT_APPLICABLE,
                )
            else:
                file_request = FileAttributionRequest(
                    path=extracted.physical_path,
                    logical_source_path=Path(extracted.logical_source_path),
                    target=context,
                    candidate_snapshot=snapshot,
                    strategy=request.package_attribution_strategy,
                )
                batch = await self.attributor.attribute_requests(
                    context,
                    candidate,
                    snapshot,
                    [file_request],
                    request.package_attribution_strategy,
                    evidence_by_key={},
                )
                evidence = next(iter(batch.evidence_by_key.values()), None)
                if evidence is None:
                    raise RuntimeError("文件归属能力未返回证据")
            if evidence.belongs_to_target_media is False:
                other_media_count += 1
                continue
            attributed.append(AttributedSubtitle(extracted=extracted, evidence=evidence))
        if request.package_attribution_strategy is PackageAttributionStrategy.HOST_RECOGNITION and host_file_count:
            logger.info(
                f"{self._task_label(request.task_id)}已完成 MoviePilot 文件识别，"
                f"处理 {host_file_count} 个字幕，其中明确属于其他媒体 {other_media_count} 个"
            )

        current_files, additional, _ambiguous_count, _other_episode_count = self._classify_files(
            attributed,
            context,
        )
        if not current_files:
            return [], additional
        format_order = {value.upper().lstrip("."): index for index, value in enumerate(self.config.format_priority)}
        current_files.sort(
            key=lambda result: (
                format_order.get(result.extracted.physical_path.suffix.lstrip(".").upper(), 999),
                result.extracted.logical_source_path,
            )
        )
        return current_files, additional

    def _classify_files(
        self,
        attributed: list[AttributedSubtitle],
        context: SubtitleTarget,
    ) -> tuple[list[AttributedSubtitle], list[AttributedSubtitle], int, int]:
        """按最新证据重算当前集、附加集和漏斗计数。"""

        current: list[AttributedSubtitle] = []
        extra: list[AttributedSubtitle] = []
        ambiguous = 0
        other_episode = 0
        for candidate_result in attributed:
            evidence = candidate_result.evidence
            season_value, season_count = self._unique_scope_value(evidence, "season")
            episode_value, episode_count = self._unique_scope_value(evidence, "episode")
            complete = evidence.belongs_to_target_media is True and (
                context.media_type is MediaType.MOVIE
                or (season_count == 1 and episode_count == 1 and season_value is not None and episode_value is not None)
            )
            if not complete or evidence.unmatched_reason is not None:
                ambiguous += 1
                extra.append(candidate_result)
                continue
            is_current = context.media_type is MediaType.MOVIE or (
                season_value == context.season and episode_value == context.episode
            )
            if is_current:
                current.append(candidate_result)
            else:
                other_episode += 1
                extra.append(candidate_result)
        return current, extra, ambiguous, other_episode

    async def _make_record(
        self,
        request: CandidateAttemptRequest,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        result: AttributedSubtitle,
        status: RecordStatus,
        location: FileLocation,
        path: str | Path,
        final_path: str | Path | None,
        bind_target: bool,
    ) -> MatchRecord:
        """构造一条安全匹配记录，提交副作用由记录能力统一处理。"""

        source_path = result.extracted.physical_path
        evidence = result.evidence
        size: int | None = None
        try:
            size = (await AsyncPath(source_path).stat()).st_size
        except OSError:
            size = None
        identity = context.canonical_identity if evidence.belongs_to_target_media is True else None
        record = MatchRecord(
            subtitle_file_name=source_path.name,
            format=source_path.suffix.lstrip(".").upper(),
            size=size,
            media_title=context.title if evidence.belongs_to_target_media is True else None,
            year=context.year if evidence.belongs_to_target_media is True else None,
            media_type=evidence.media_type,
            season=evidence.season,
            episode=evidence.episode,
            status=status,
            source=candidate.source,
            package_scope=candidate.package_scope,
            location=location,
            path=Path(path),
            canonical_identity_type=identity[0] if identity else None,
            canonical_identity_value=identity[1] if identity else None,
            tmdb_id=evidence.tmdb_id,
            imdb_id=evidence.imdb_id,
            target_history_id=request.target_history_id if bind_target else None,
            history_target_path=request.history_target_path if bind_target else None,
            target_path=context.target_path if bind_target else None,
            matched_path_mapping=request.matched_path_mapping if bind_target else None,
            target_file_exists=request.target_file_exists if bind_target else None,
            final_subtitle_path=Path(final_path) if final_path is not None else None,
            source_task_id=request.task_id,
            candidate_key=candidate.candidate_key,
            candidate_name=candidate.name,
            logical_source_path=evidence.logical_source_path,
            file_attribution_method=evidence.method,
            unmatched_reason=evidence.unmatched_reason,
            language=candidate.language,
            translation_type=candidate.translation_type,
            hearing_impaired=candidate.hearing_impaired,
            exact_id_match=candidate.exact_id_match,
            site_priority=candidate.site_priority,
            trusted=candidate.trusted,
            score=candidate.score,
            votes=candidate.votes,
            download_count=candidate.download_count,
            uploaded_at=candidate.uploaded_at,
            revision=candidate.revision,
        )
        if status is RecordStatus.STAGED:
            record.staged_at = record.created_at
        return record

    async def _write_candidate_file(
        self,
        request: CandidateAttemptRequest,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        result: AttributedSubtitle,
    ) -> _CandidateWriteResult:
        """写入一个候选字幕并只在匹配记录保存成功后返回文件事实。"""

        try:
            record = await self._make_record(
                request,
                context,
                candidate,
                result,
                RecordStatus.MATCHED,
                FileLocation.MEDIA_DIRECTORY,
                "",
                None,
                True,
            )
            committed_file = await self.inventory.commit_media(
                record,
                result.extracted.physical_path,
                context.target_path,
            )
        except asyncio.CancelledError:
            raise
        except FileExistsError:
            return _CandidateWriteResult(
                error_summary="目标字幕已存在，未覆盖",
                reason_code=CandidateAttemptReasonCode.SUBTITLE_DESTINATION_CONFLICT,
            )
        except OSError as exc:
            return _CandidateWriteResult(error_summary=f"文件操作失败：{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 - 单文件记录失败不吞掉其它已提交文件
            return _CandidateWriteResult(error_summary=f"匹配记录保存失败：{type(exc).__name__}")
        return _CandidateWriteResult(record=committed_file.record, committed_file=committed_file)

    @staticmethod
    def _can_stage(result: AttributedSubtitle, context: SubtitleTarget) -> bool:
        """判断具体字幕归属是否足够进入暂存库存。"""

        evidence = result.evidence
        if evidence.belongs_to_target_media is not True or evidence.unmatched_reason is not None:
            return False
        if context.media_type is MediaType.MOVIE:
            return context.canonical_identity is not None
        return bool(
            context.canonical_identity is not None and evidence.season is not None and evidence.episode is not None
        )

    async def _save_plugin_result(
        self,
        request: CandidateAttemptRequest,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        result: AttributedSubtitle,
        *,
        bind_target: bool,
    ) -> MatchRecord:
        """把归属完整或不完整的字幕保存为暂存或未匹配记录。"""

        status = RecordStatus.STAGED if self._can_stage(result, context) else RecordStatus.UNMATCHED
        record = await self._make_record(
            request,
            context,
            candidate,
            result,
            status,
            FileLocation.PLUGIN_DATA,
            "",
            None,
            bind_target,
        )
        record = await self.inventory.commit_plugin(record, result.extracted.physical_path)
        return record

    async def _save_additional_results(
        self,
        request: CandidateAttemptRequest,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        results: list[AttributedSubtitle],
    ) -> tuple[list[MatchRecord], list[str]]:
        """保存附加字幕并把单文件失败返回给外层任务处理。"""

        records: list[MatchRecord] = []
        warnings: list[str] = []
        for result in results:
            evidence = result.evidence
            bind_target = bool(
                evidence.belongs_to_target_media is True
                and (
                    context.media_type is MediaType.MOVIE
                    or (evidence.season == context.season and evidence.episode == context.episode)
                )
            )
            try:
                record = await self._save_plugin_result(
                    request,
                    context,
                    candidate,
                    result,
                    bind_target=bind_target,
                )
            except Exception as exc:  # noqa: BLE001 - 附加字幕失败不能中断候选处理
                warnings.append(f"附加字幕保存失败：{type(exc).__name__}")
                logger.warning(
                    f"{self._task_label(request.task_id)}保存附加字幕"
                    f"“{result.extracted.logical_source_path}”失败，将继续处理任务："
                    f"{type(exc).__name__}"
                )
                continue
            records.append(record)
            if record.status is RecordStatus.STAGED:
                logger.info(
                    f"{self._task_label(request.task_id)}已将附加字幕"
                    f"“{result.extracted.logical_source_path}”保存为暂存记录 {record.id}"
                )
            else:
                logger.info(
                    f"{self._task_label(request.task_id)}无法完整确认附加字幕"
                    f"“{result.extracted.logical_source_path}”的归属，"
                    f"已保存为未匹配记录 {record.id}"
                )
        return records, warnings

    @staticmethod
    def _unique_scope_value(evidence: FileAttributionEvidence, field: str) -> tuple[int | None, int]:
        """读取保留基数的季集字段，兼容旧测试替身的单值证据。"""

        values = list(getattr(evidence, f"{field}_values", []) or [])
        scalar = getattr(evidence, field, None)
        if not values and scalar is not None:
            values = [scalar]
        return (values[0], 1) if len(values) == 1 else (None, len(values))
