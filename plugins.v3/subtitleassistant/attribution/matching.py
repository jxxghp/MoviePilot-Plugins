"""人工候选识别与常规字幕文件归属实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.chain.media import MediaChain
from app.core.context import MediaInfo as HostMediaInfo
from app.core.context import TorrentInfo
from app.core.metainfo import MetaInfo, MetaInfoPath
from app.helper.torrent import TorrentHelper
from app.schemas.types import MediaType as HostMediaType

from ..schemas.attribution import (
    AttributionEvidence,
    CandidateAttributionSnapshot,
    CandidateMatchContext,
    FileAttributionBatchResult,
    FileAttributionEvidence,
    FileAttributionMethod,
    FileAttributionRequest,
    PackageAttributionStrategy,
    UnmatchedReason,
)
from ..schemas.candidate import (
    CandidateRecognition,
    CandidateRecognitionStatus,
    PackageScope,
    SubtitleCandidate,
)
from ..schemas.target import (
    MediaType,
    SubtitleTarget,
)


class MoviePilotMatcher:
    """组合宿主公开元数据解析与媒体识别能力的匹配适配器。"""

    @staticmethod
    def _structured_id_result(candidate: SubtitleCandidate, context: SubtitleTarget) -> bool | None:
        """返回结构化 ID 的一致、冲突或不可比较结果。"""

        if candidate.tmdb_id is not None and context.tmdb_id is not None:
            # TMDB 是宿主与候选都有时的主身份；即使 IMDb 来源冲突，也不
            # 用次级字段推翻已一致的主身份。
            return candidate.tmdb_id == context.tmdb_id
        if candidate.imdb_id and context.imdb_id:
            left = MoviePilotMatcher._normalize_imdb(candidate.imdb_id)
            right = MoviePilotMatcher._normalize_imdb(context.imdb_id)
            return left == right
        return None

    @staticmethod
    def _normalize_imdb(value: str) -> str:
        """归一化 IMDb ID，兼容来源省略 tt 或前导零。"""

        return value.strip().lower().removeprefix("tt").lstrip("0") or "0"

    @staticmethod
    def _candidate_names(candidate: SubtitleCandidate) -> list[tuple[str, str]]:
        """按标题、文件名和描述返回候选自身的可解析文本。"""

        values = [
            ("title", candidate.name),
            ("file_name", candidate.file_name),
            ("description", candidate.metadata.get("description")),
        ]
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append((label, normalized))
        return result

    @staticmethod
    def _numbers(meta: Any, field: str) -> list[int]:
        """从宿主元数据字段读取稳定、去重的非负整数集合。"""

        values = getattr(meta, field, None) or []
        result: set[int] = set()
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number >= 0:
                result.add(number)
        return sorted(result)

    @staticmethod
    def _plugin_media_type(value: Any) -> MediaType:
        """把宿主媒体类型转换为插件稳定媒体类型。"""

        raw = getattr(value, "value", value)
        normalized = str(raw or "").strip().casefold()
        if normalized in {"电影", "movie"}:
            return MediaType.MOVIE
        if normalized in {"电视剧", "tv"}:
            return MediaType.TV
        return MediaType.UNKNOWN

    def _candidate_meta_entries(self, candidate: SubtitleCandidate) -> list[tuple[str, str, Any]]:
        """解析候选自身文本，忽略单个文本无法解析的情况。"""

        description = str(candidate.metadata.get("description") or "")
        result: list[tuple[str, str, Any]] = []
        for label, name in self._candidate_names(candidate):
            try:
                result.append((label, name, MetaInfo(title=name, subtitle=description)))
            except (AttributeError, TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _derive_package_scope(
        current: PackageScope,
        seasons: list[int],
        episodes: list[int],
        media_types: set[MediaType],
    ) -> PackageScope:
        """只根据候选自身事实推导候选包范围。"""

        if current is not PackageScope.UNKNOWN:
            return current
        if episodes:
            return PackageScope.EPISODE
        if seasons:
            return PackageScope.SEASON_PACK
        if media_types == {MediaType.MOVIE}:
            return PackageScope.EPISODE
        return PackageScope.UNKNOWN

    @staticmethod
    def _torrent_info(candidate: SubtitleCandidate, name: str, context: SubtitleTarget) -> TorrentInfo:
        """构造仅用于宿主公共匹配方法的候选种子信息。"""

        torrent_fields: dict[str, Any] = {
            "site_name": candidate.source.value,
            "title": name,
            "description": str(candidate.metadata.get("description") or ""),
            "category": "电视剧" if context.media_type is MediaType.TV else "电影",
        }
        if candidate.site_id is not None:
            torrent_fields["site"] = candidate.site_id
        return TorrentInfo(**torrent_fields)

    @staticmethod
    def _host_mediainfo(match_context: CandidateMatchContext) -> HostMediaInfo | None:
        """在宿主 adapter 内从插件快照重建公共匹配所需的临时媒体对象。"""

        host_type = {
            MediaType.MOVIE: HostMediaType.MOVIE,
            MediaType.TV: HostMediaType.TV,
        }.get(match_context.media_type)
        if host_type is None:
            return None
        return HostMediaInfo(
            type=host_type,
            title=match_context.title,
            original_title=match_context.original_title or "",
            names=list(match_context.aliases),
            year=str(match_context.year) if match_context.year is not None else "",
            tmdb_id=match_context.tmdb_id or 0,
            imdb_id=match_context.imdb_id or "",
            douban_id=match_context.douban_id or "",
            bangumi_id=match_context.bangumi_id or 0,
            anilist_id=match_context.anilist_id or 0,
            season_years=dict(match_context.season_years),
        )

    def _enrich_candidate(
        self,
        candidate: SubtitleCandidate,
    ) -> tuple[SubtitleCandidate, list[tuple[str, str, Any]]]:
        """从候选自身字段与文本补全安全季集和包范围。"""

        candidate = candidate.model_copy(deep=True)
        entries = self._candidate_meta_entries(candidate)
        seasons = set(candidate.seasons)
        episodes = set(candidate.episodes)
        if candidate.season is not None:
            seasons.add(candidate.season)
        if candidate.episode is not None:
            episodes.add(candidate.episode)
        media_types: set[MediaType] = set()
        for _label, _name, meta in entries:
            seasons.update(self._numbers(meta, "season_list"))
            episodes.update(self._numbers(meta, "episode_list"))
            media_type = self._plugin_media_type(getattr(meta, "type", None))
            if media_type is not MediaType.UNKNOWN:
                media_types.add(media_type)
        candidate.seasons = sorted(seasons)
        candidate.episodes = sorted(episodes)
        candidate.package_scope = self._derive_package_scope(
            candidate.package_scope,
            candidate.seasons,
            candidate.episodes,
            media_types,
        )
        return candidate, entries

    def _match_candidate(
        self,
        candidate: SubtitleCandidate,
        entries: list[tuple[str, str, Any]],
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> SubtitleCandidate | None:
        """用宿主公共规则判断已补全候选是否属于当前目标。"""

        season_episodes: dict[int, list[int]] | None = None
        candidate_range_covers_target = False
        if context.media_type is MediaType.TV:
            target_season = context.season
            target_episode = context.episode
            if target_season is None or target_episode is None:
                return None
            if candidate.seasons and target_season not in candidate.seasons:
                return None
            if candidate.episodes and target_episode not in candidate.episodes:
                return None
            season_episodes = {target_season: [target_episode]}
            candidate_range_covers_target = (
                bool(candidate.seasons)
                and target_season in candidate.seasons
                and (not candidate.episodes or target_episode in candidate.episodes)
            )

        id_result = self._structured_id_result(candidate, context)
        if id_result is False:
            return None

        if id_result is True:
            if season_episodes is not None and not candidate_range_covers_target:
                for _label, name, meta in entries:
                    try:
                        if TorrentHelper.match_season_episodes(
                            torrent=self._torrent_info(candidate, name, context),
                            meta=meta,
                            season_episodes=season_episodes,
                        ):
                            break
                    except (AttributeError, TypeError, ValueError):
                        continue
                else:
                    return None
            candidate.exact_id_match = True
            return candidate

        if match_context is None:
            return None
        host_mediainfo = self._host_mediainfo(match_context)
        if host_mediainfo is None:
            return None
        for _label, name, meta in entries:
            torrent = self._torrent_info(candidate, name, context)
            try:
                if (
                    season_episodes is not None
                    and not candidate_range_covers_target
                    and not TorrentHelper.match_season_episodes(
                        torrent=torrent,
                        meta=meta,
                        season_episodes=season_episodes,
                    )
                ):
                    continue
                if not TorrentHelper.match_torrent(
                    mediainfo=host_mediainfo,
                    torrent_meta=meta,
                    torrent=torrent,
                ):
                    continue
            except (AttributeError, TypeError, ValueError):
                continue
            candidate.exact_id_match = False
            return candidate
        return None

    def normalize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> SubtitleCandidate | None:
        """用宿主公共规则确认自动候选，并保留候选自身的完整季集范围。"""

        enriched, entries = self._enrich_candidate(candidate)
        return self._match_candidate(enriched, entries, context, match_context)

    def recognize_candidate(
        self,
        candidate: SubtitleCandidate,
        context: SubtitleTarget,
        match_context: CandidateMatchContext | None,
    ) -> CandidateRecognition:
        """复用自动匹配规则识别人工候选，并始终返回安全候选副本。"""

        enriched, entries = self._enrich_candidate(candidate)
        normalized = self._match_candidate(enriched, entries, context, match_context)
        if normalized is not None:
            return CandidateRecognition(
                candidate=normalized,
                status=CandidateRecognitionStatus.RECOGNIZED,
            )
        return CandidateRecognition(
            candidate=enriched,
            status=CandidateRecognitionStatus.UNRECOGNIZED,
        )

    def candidate_snapshot(self, candidate: SubtitleCandidate) -> CandidateAttributionSnapshot:
        """只聚合候选自身字段、解析结果与结构化 ID 形成归属快照。"""

        seasons = set(candidate.seasons)
        episodes = set(candidate.episodes)
        evidence: set[str] = set()
        media_types: set[MediaType] = set()
        if candidate.season is not None:
            seasons.add(candidate.season)
            evidence.add("structured_season")
        if candidate.episode is not None:
            episodes.add(candidate.episode)
            evidence.add("structured_episode")
        if candidate.seasons:
            evidence.add("candidate_seasons")
        if candidate.episodes:
            evidence.add("candidate_episodes")
        if candidate.tmdb_id is not None:
            evidence.add("structured_tmdb_id")
        if candidate.imdb_id:
            evidence.add("structured_imdb_id")
        if candidate.package_scope is not PackageScope.UNKNOWN:
            evidence.add("candidate_package_scope")

        for label, _name, meta in self._candidate_meta_entries(candidate):
            parsed_seasons = self._numbers(meta, "season_list")
            parsed_episodes = self._numbers(meta, "episode_list")
            if parsed_seasons:
                seasons.update(parsed_seasons)
                evidence.add(f"{label}_season")
            if parsed_episodes:
                episodes.update(parsed_episodes)
                evidence.add(f"{label}_episode")
            media_type = self._plugin_media_type(getattr(meta, "type", None))
            if media_type is not MediaType.UNKNOWN:
                media_types.add(media_type)
                evidence.add(f"{label}_media_type")

        season_list = sorted(seasons)
        episode_list = sorted(episodes)
        media_type = next(iter(media_types)) if len(media_types) == 1 else MediaType.UNKNOWN
        package_scope = self._derive_package_scope(
            candidate.package_scope,
            season_list,
            episode_list,
            media_types,
        )
        return CandidateAttributionSnapshot(
            media_type=media_type,
            year=candidate.year,
            tmdb_id=candidate.tmdb_id,
            imdb_id=candidate.imdb_id,
            seasons=season_list,
            episodes=episode_list,
            package_scope=package_scope,
            evidence=sorted(evidence),
        )

    @staticmethod
    def _path_meta(logical_source_path: Path) -> Any | None:
        """按不含临时目录的逻辑来源路径解析具体字幕元数据。"""

        try:
            return MetaInfoPath(Path(logical_source_path))
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _scope_value(
        path_values: list[int],
        snapshot_values: list[int],
    ) -> tuple[int | None, AttributionEvidence]:
        """按路径明确值优先、候选唯一范围后备解析单个季集字段。"""

        if len(path_values) == 1:
            return path_values[0], AttributionEvidence.PATH
        if not path_values and len(snapshot_values) == 1:
            return snapshot_values[0], AttributionEvidence.CANDIDATE_SNAPSHOT
        return None, AttributionEvidence.UNKNOWN

    @staticmethod
    def _scope_conflicts(path_values: list[int], snapshot_values: list[int]) -> bool:
        """判断文件明确季集是否超出候选明确范围。"""

        return bool(path_values and snapshot_values and not set(path_values).issubset(snapshot_values))

    def _trust_package_attribution(
        self,
        logical_source_path: Path,
        context: SubtitleTarget,
        snapshot: CandidateAttributionSnapshot,
    ) -> FileAttributionEvidence:
        """信任候选媒体归属，只从逻辑路径及候选唯一范围解析季集。"""

        if context.media_type is MediaType.MOVIE:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.TRUST_PACKAGE,
                belongs_to_target_media=True,
                media_type=context.media_type,
                year=context.year,
                tmdb_id=context.tmdb_id,
                imdb_id=context.imdb_id,
                season_evidence=AttributionEvidence.NOT_APPLICABLE,
                episode_evidence=AttributionEvidence.NOT_APPLICABLE,
                season_values=[],
                episode_values=[],
            )
        if context.media_type is not MediaType.TV:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.TRUST_PACKAGE,
                belongs_to_target_media=None,
                media_type=context.media_type,
                year=context.year,
                tmdb_id=context.tmdb_id,
                imdb_id=context.imdb_id,
                unmatched_reason=UnmatchedReason.MEDIA_UNRECOGNIZED,
                season_values=[],
                episode_values=[],
            )

        meta = self._path_meta(logical_source_path)
        path_seasons = self._numbers(meta, "season_list") if meta is not None else []
        path_episodes = self._numbers(meta, "episode_list") if meta is not None else []
        season, season_evidence = self._scope_value(path_seasons, snapshot.seasons)
        episode, episode_evidence = self._scope_value(path_episodes, snapshot.episodes)
        conflict = self._scope_conflicts(path_seasons, snapshot.seasons) or self._scope_conflicts(
            path_episodes,
            snapshot.episodes,
        )
        reason: UnmatchedReason | None = None
        if conflict:
            reason = UnmatchedReason.CANDIDATE_FILE_SCOPE_CONFLICT
        elif season is None:
            reason = UnmatchedReason.SEASON_AMBIGUOUS
        elif episode is None:
            reason = UnmatchedReason.EPISODE_AMBIGUOUS
        return FileAttributionEvidence(
            logical_source_path=logical_source_path,
            method=FileAttributionMethod.TRUST_PACKAGE,
            belongs_to_target_media=True,
            media_type=context.media_type,
            year=context.year,
            tmdb_id=context.tmdb_id,
            imdb_id=context.imdb_id,
            season=season,
            episode=episode,
            season_values=path_seasons,
            episode_values=path_episodes,
            season_evidence=season_evidence,
            episode_evidence=episode_evidence,
            unmatched_reason=reason,
        )

    @staticmethod
    def _identity_result(
        context: SubtitleTarget,
        tmdb_id: int | None,
        imdb_id: str | None,
    ) -> tuple[bool | None, str | None]:
        """按 TMDB 优先、IMDb 后备精确比较宿主识别身份。"""

        if context.tmdb_id is not None and tmdb_id is not None:
            return context.tmdb_id == tmdb_id, "tmdb"
        if context.imdb_id and imdb_id:
            return (
                MoviePilotMatcher._normalize_imdb(context.imdb_id) == MoviePilotMatcher._normalize_imdb(imdb_id),
                "imdb",
            )
        return None, None

    async def _host_recognition_attribution(
        self,
        logical_source_path: Path,
        context: SubtitleTarget,
    ) -> FileAttributionEvidence:
        """用 MoviePilot 公开异步识别逐文件确认媒体身份和季集。"""

        meta = self._path_meta(logical_source_path)
        path_seasons = self._numbers(meta, "season_list") if meta is not None else []
        path_episodes = self._numbers(meta, "episode_list") if meta is not None else []
        season = path_seasons[0] if len(path_seasons) == 1 else None
        episode = path_episodes[0] if len(path_episodes) == 1 else None
        season_evidence = AttributionEvidence.PATH if season is not None else AttributionEvidence.UNKNOWN
        episode_evidence = AttributionEvidence.PATH if episode is not None else AttributionEvidence.UNKNOWN
        if meta is None:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=None,
                season=season,
                episode=episode,
                season_values=path_seasons,
                episode_values=path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                unmatched_reason=UnmatchedReason.MEDIA_UNRECOGNIZED,
                host_recognition_summary={"recognized": False, "path_parsed": False},
            )

        # MediaChain 可能按 RECOGNIZE_PLUGIN_FIRST 原地补充同一个 MetaBase；
        # 先完成公开识别，再读取最终对象，不能继续使用调用前的季集快照。
        mediainfo = await MediaChain().async_recognize_by_meta(meta)
        final_path_seasons = self._numbers(meta, "season_list")
        final_path_episodes = self._numbers(meta, "episode_list")
        season = final_path_seasons[0] if len(final_path_seasons) == 1 else None
        episode = final_path_episodes[0] if len(final_path_episodes) == 1 else None
        season_evidence = AttributionEvidence.PATH if season is not None else AttributionEvidence.UNKNOWN
        episode_evidence = AttributionEvidence.PATH if episode is not None else AttributionEvidence.UNKNOWN
        if mediainfo is None:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=None,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                unmatched_reason=UnmatchedReason.MEDIA_UNRECOGNIZED,
                host_recognition_summary={"recognized": False, "path_parsed": True},
            )

        media_type = self._plugin_media_type(getattr(mediainfo, "type", None))
        raw_tmdb_id = getattr(mediainfo, "tmdb_id", None)
        try:
            tmdb_id = int(raw_tmdb_id) if raw_tmdb_id is not None else None
        except (TypeError, ValueError):
            tmdb_id = None
        raw_imdb_id = getattr(mediainfo, "imdb_id", None)
        imdb_id = str(raw_imdb_id).strip() if raw_imdb_id else None
        raw_year = getattr(mediainfo, "year", None)
        try:
            year = int(raw_year) if raw_year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        summary: dict[str, Any] = {
            "recognized": True,
            "media_type": media_type.value,
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "year": year,
        }
        # 即使宿主未返回可识别类型，也先检查双方明确的结构化身份；
        # 这样一个明确冲突不会被提前压扁成“未知”。
        identity_match, identity_source = self._identity_result(context, tmdb_id, imdb_id)
        summary.update(
            {
                "identity_source": identity_source,
                "identity_match": identity_match,
            }
        )
        if identity_match is False:
            summary["type_match"] = False if media_type is not context.media_type else None
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=False,
                media_type=media_type,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                host_recognition_summary=summary,
            )
        if media_type is MediaType.UNKNOWN or context.media_type is MediaType.UNKNOWN:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=None,
                media_type=media_type,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                unmatched_reason=UnmatchedReason.MEDIA_UNRECOGNIZED,
                host_recognition_summary=summary,
            )
        if media_type is not context.media_type:
            summary.update({"type_match": False, "identity_match": False})
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=False,
                media_type=media_type,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                host_recognition_summary=summary,
            )

        summary.update(
            {
                "type_match": True,
                "identity_source": identity_source,
                "identity_match": identity_match,
            }
        )
        if identity_match is False:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=False,
                media_type=media_type,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                host_recognition_summary=summary,
            )
        if identity_match is None:
            return FileAttributionEvidence(
                logical_source_path=logical_source_path,
                method=FileAttributionMethod.HOST_RECOGNITION,
                belongs_to_target_media=None,
                media_type=media_type,
                year=year,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                season_values=final_path_seasons,
                episode_values=final_path_episodes,
                season_evidence=season_evidence,
                episode_evidence=episode_evidence,
                unmatched_reason=UnmatchedReason.MEDIA_UNRECOGNIZED,
                host_recognition_summary=summary,
            )

        if media_type is MediaType.MOVIE:
            season = None
            episode = None
            season_evidence = AttributionEvidence.NOT_APPLICABLE
            episode_evidence = AttributionEvidence.NOT_APPLICABLE
            reason = None
        else:
            reason = None
            if season is None:
                reason = UnmatchedReason.SEASON_AMBIGUOUS
            elif episode is None:
                reason = UnmatchedReason.EPISODE_AMBIGUOUS
        return FileAttributionEvidence(
            logical_source_path=logical_source_path,
            method=FileAttributionMethod.HOST_RECOGNITION,
            belongs_to_target_media=True,
            media_type=media_type,
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            season=season,
            episode=episode,
            season_values=final_path_seasons,
            episode_values=final_path_episodes,
            season_evidence=season_evidence,
            episode_evidence=episode_evidence,
            unmatched_reason=reason,
            host_recognition_summary=summary,
        )

    async def attribute_file(
        self,
        path: Path,
        logical_source_path: Path,
        context: SubtitleTarget,
        snapshot: CandidateAttributionSnapshot,
        strategy: PackageAttributionStrategy,
    ) -> FileAttributionEvidence:
        """按任务策略识别一个包内具体字幕文件。"""

        del path
        if strategy is PackageAttributionStrategy.TRUST_PACKAGE:
            return self._trust_package_attribution(logical_source_path, context, snapshot)
        return await self._host_recognition_attribution(logical_source_path, context)

    async def attribute_requests(
        self,
        context: SubtitleTarget,
        candidate: SubtitleCandidate,
        snapshot: CandidateAttributionSnapshot,
        requests: list[FileAttributionRequest],
        strategy: PackageAttributionStrategy,
        *,
        evidence_by_key: dict[str, FileAttributionEvidence] | None = None,
    ) -> FileAttributionBatchResult:
        """通过一般化请求批量返回常规文件归属证据。"""

        del candidate, evidence_by_key
        result = FileAttributionBatchResult(request_count=len(requests), submitted_count=len(requests))
        for index, request in enumerate(requests, start=1):
            try:
                evidence = await self.attribute_file(
                    request.path,
                    request.logical_source_path,
                    context,
                    snapshot,
                    strategy,
                )
            except Exception:  # noqa: BLE001 - 单文件归属失败必须隔离
                result.error_count += 1
                result.reason_summary["adapter_error"] = result.reason_summary.get("adapter_error", 0) + 1
                continue
            result.evidence_by_key[f"file_{index:04d}"] = evidence
        return result
