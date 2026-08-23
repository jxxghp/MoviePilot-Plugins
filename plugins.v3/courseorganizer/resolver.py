from __future__ import annotations

import copy
import math
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import naming
from .providers import AIReviewResult, MoviePilotAIReviewer, ProviderSearchResult

DataLoader = Callable[[str, Any], Any]
DataSaver = Callable[[str, Any], None]


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"false", "0", "no", "off", ""}:
            return False
        if lower in {"1", "true", "yes", "on", "t", "y"}:
            return True
        return default
    if value is None:
        return default
    return bool(value)



def _coerce_str(value: Any, default: str = "") -> str:
    return str(value) if value is not None else default


def _coerce_iter(value: Any, default: Tuple[str, ...]) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        output: List[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                output.append(text.lower())
        return tuple(output)
    if isinstance(value, str):
        return tuple(item.strip().lower() for item in value.split(",") if item.strip())
    return default


@dataclass(frozen=True)
class NamingConfig:
    mode: str = "off"
    sources: Tuple[str, ...] = ("themoviedb", "douban")
    auto_threshold: int = 90
    min_margin: int = 12
    uncertain_policy: str = "local"
    append_tmdb_id: bool = False
    ai_review: bool = False
    manual_overrides: str = ""

    @classmethod
    def sanitize(cls, raw: Any) -> "NamingConfig":
        def _read_field(mapping: Any, attr: str, default: Any) -> Any:
            if isinstance(mapping, dict):
                return mapping.get(attr)
            if isinstance(mapping, str):
                return None
            if hasattr(mapping, attr):
                return getattr(mapping, attr)
            return default

        mode = ""
        sources_value = ()
        raw_payload: Dict[str, Any]
        if isinstance(raw, dict):
            mode = str(raw.get("mode", raw.get("naming_mode", "off")) or "off")
            sources_value = raw.get(
                "sources",
                raw.get("naming_sources", cls.__dataclass_fields__["sources"].default),
            )
            auto_threshold_raw = raw.get(
                "auto_threshold",
                raw.get("naming_auto_threshold", cls.__dataclass_fields__["auto_threshold"].default),
            )
            min_margin_raw = raw.get(
                "min_margin",
                raw.get("naming_min_margin", cls.__dataclass_fields__["min_margin"].default),
            )
            uncertain_policy_raw = raw.get(
                "uncertain_policy",
                raw.get("naming_uncertain_policy", cls.__dataclass_fields__["uncertain_policy"].default),
            )
            append_tmdb_id_raw = raw.get(
                "append_tmdb_id",
                raw.get("naming_append_tmdb_id", cls.__dataclass_fields__["append_tmdb_id"].default),
            )
            ai_review_raw = raw.get(
                "ai_review",
                raw.get("naming_ai_review", cls.__dataclass_fields__["ai_review"].default),
            )
            manual_overrides_raw = raw.get(
                "manual_overrides",
                raw.get("naming_manual_overrides", cls.__dataclass_fields__["manual_overrides"].default),
            )
            incoming = raw.get("incoming", "")
            output = raw.get("output", "")
        else:
            mode = str(_read_field(raw, "mode", _read_field(raw, "naming_mode", "off")) or "off")
            sources_value = _read_field(
                raw,
                "sources",
                _read_field(raw, "naming_sources", cls.__dataclass_fields__["sources"].default),
            )
            auto_threshold_raw = _read_field(
                raw,
                "auto_threshold",
                _read_field(raw, "naming_auto_threshold", cls.__dataclass_fields__["auto_threshold"].default),
            )
            min_margin_raw = _read_field(
                raw,
                "min_margin",
                _read_field(raw, "naming_min_margin", cls.__dataclass_fields__["min_margin"].default),
            )
            uncertain_policy_raw = _read_field(
                raw,
                "uncertain_policy",
                _read_field(raw, "naming_uncertain_policy", cls.__dataclass_fields__["uncertain_policy"].default),
            )
            append_tmdb_id_raw = _read_field(
                raw,
                "append_tmdb_id",
                _read_field(raw, "naming_append_tmdb_id", cls.__dataclass_fields__["append_tmdb_id"].default),
            )
            ai_review_raw = _read_field(
                raw,
                "ai_review",
                _read_field(raw, "naming_ai_review", cls.__dataclass_fields__["ai_review"].default),
            )
            manual_overrides_raw = _read_field(
                raw,
                "manual_overrides",
                _read_field(raw, "naming_manual_overrides", cls.__dataclass_fields__["manual_overrides"].default),
            )
            incoming = _read_field(raw, "incoming", "")
            output = _read_field(raw, "output", "")

        mode = _coerce_str(mode).lower()
        if mode not in {"off", "preview", "apply"}:
            mode = "off"

        normalized_sources: List[str] = []
        for source in _coerce_iter(
            sources_value if sources_value is not None else (), ()
        ):
            if source in {"hk", "tw", "sg"}:
                source = "themoviedb"
            if source in {"themoviedb", "douban"} and source not in normalized_sources:
                normalized_sources.append(source)
        sources = tuple(normalized_sources)
        if not sources:
            sources = ("themoviedb", "douban")

        auto_threshold = _coerce_int(auto_threshold_raw, cls.__dataclass_fields__["auto_threshold"].default)
        auto_threshold = max(80, min(100, auto_threshold))

        min_margin = _coerce_int(min_margin_raw, cls.__dataclass_fields__["min_margin"].default)
        min_margin = max(5, min(30, min_margin))

        uncertain_policy = _coerce_str(uncertain_policy_raw, cls.__dataclass_fields__["uncertain_policy"].default).lower()
        if uncertain_policy not in {"local", "hold"}:
            uncertain_policy = "local"

        ai_review = _coerce_bool(ai_review_raw, cls.__dataclass_fields__["ai_review"].default)
        append_tmdb_id = _coerce_bool(
            append_tmdb_id_raw,
            cls.__dataclass_fields__["append_tmdb_id"].default,
        )
        manual_overrides = _coerce_str(manual_overrides_raw)

        # Keep host-facing keys available on identity/config diagnostics.
        _ = incoming
        _ = output

        return cls(
            mode=mode,
            sources=sources,
            auto_threshold=auto_threshold,
            min_margin=min_margin,
            uncertain_policy=uncertain_policy,
            append_tmdb_id=append_tmdb_id,
            ai_review=ai_review,
            manual_overrides=manual_overrides,
        )


@dataclass(frozen=True)
class NamingDecision:
    status: str
    raw_title: str
    local_title: str
    final_root: str
    final_prefix: str
    source: str = ""
    media_id: str = ""
    media_type: str = "unknown"
    score: int = 0
    margin: int = 0
    candidate_key: str = ""
    reason_codes: Tuple[str, ...] = ()
    source_errors: Tuple[str, ...] = ()
    blocked_reason: str = ""
    legacy_output_root: str = ""
    target_output_root: str = ""
    target_library: str = ""

    @property
    def allowed_to_move(self) -> bool:
        return self.status in {"auto_external", "local_fallback"}


class SmartNamingResolver:
    SEARCH_TTL_SECONDS = 30 * 24 * 60 * 60
    ERROR_TTL_SECONDS = 60 * 60
    SEARCH_CACHE_MAX = 500
    AI_QUERY_TTL_SECONDS = 30 * 24 * 60 * 60
    AI_QUERY_ERROR_TTL_SECONDS = 60 * 60
    AI_QUERY_CACHE_MAX = 500
    AI_QUERY_CACHE_KEY = "naming_ai_query_cache_v1"
    IDENTITY_MAX = 500
    PREVIEW_MAX = 200
    AI_ERROR_MAX = 100

    def __init__(
        self,
        load_data: DataLoader,
        save_data: DataSaver,
        provider: Any,
        ai_reviewer: Optional[MoviePilotAIReviewer] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._load_data = load_data
        self._save_data = save_data
        self._provider = provider
        self._ai_reviewer = ai_reviewer
        self._clock = clock

    def clear(self) -> None:
        self._save_data("naming_search_cache_v1", {})
        self._save_data(self.AI_QUERY_CACHE_KEY, {})
        self._save_data("naming_identity_v1", {})
        self._save_data("naming_preview_v1", [])
        self._save_data("naming_ai_errors_v1", [])

    @staticmethod
    def _resolve_uncertain(
        decision: "NamingDecision",
        config: NamingConfig,
        hints: naming.TitleHints,
    ) -> NamingDecision:
        if decision.status != "review":
            return decision
        status = "manual_review" if config.uncertain_policy == "hold" else "local_fallback"
        reason_codes = tuple(
            code for code in decision.reason_codes if code in {"needs_ai", "review"}
        )
        if not reason_codes:
            reason_codes = ("needs_ai",)
        final_root = naming.format_root_name(hints, None)
        final_prefix = naming.format_file_prefix(final_root)
        blocked_reason = "manual_review" if status == "manual_review" else ""
        return NamingDecision(
            status=status,
            raw_title=decision.raw_title,
            local_title=decision.local_title,
            final_root=final_root,
            final_prefix=final_prefix,
            source=decision.source,
            media_id=decision.media_id,
            media_type=decision.media_type,
            score=decision.score,
            margin=decision.margin,
            reason_codes=reason_codes,
            source_errors=decision.source_errors,
            blocked_reason=blocked_reason,
            candidate_key=decision.candidate_key,
            legacy_output_root=decision.legacy_output_root,
            target_output_root=decision.target_output_root,
        )

    def resolve(
        self,
        raw_title: str,
        directory: naming.DirectoryHints,
        config: NamingConfig,
        legacy_output_root: str = "",
        target_output_root: str = "",
        manual_decision: Optional[naming.ManualOverride] = None,
    ) -> NamingDecision:
        now = int(self._clock())
        config = NamingConfig.sanitize(config)
        hints = naming.parse_title(raw_title)
        if config.mode == "off":
            return self._decision(
                status="local_fallback",
                raw_title=raw_title,
                hints=hints,
            )
        directory_hints = naming.DirectoryHints(
            media_count=directory.media_count,
            seasons=directory.seasons,
            episodic=bool(directory.episodic) or bool(hints.season_hints) or bool(directory.seasons),
        )
        decision_fingerprint = naming.decision_hash(
            directory_hints=directory_hints,
            auto_threshold=config.auto_threshold,
            min_margin=config.min_margin,
            append_tmdb_id=config.append_tmdb_id,
            uncertain_policy=config.uncertain_policy,
        )

        overrides = naming.parse_manual_overrides(config.manual_overrides)
        override_diagnostics = () if manual_decision is not None else tuple(
            code for left, code in overrides.line_errors if not left
        )
        raw_override_errors = () if manual_decision is not None else tuple(
            code
            for code_left, code in overrides.line_errors
            if code_left == raw_title
        )
        if raw_override_errors:
            return self.record_decision(
                self._decision(
                    status="blocked",
                    raw_title=raw_title,
                    hints=hints,
                    reason_codes=self._merge_reason_codes(raw_override_errors, override_diagnostics),
                    blocked_reason="manual_override_error",
                    source_errors=raw_override_errors,
                ),
                legacy_output_root=legacy_output_root,
                target_output_root=target_output_root,
            )

        matched_override = manual_decision
        if matched_override is None:
            for item in overrides.overrides:
                if item.raw_title == raw_title:
                    matched_override = item
                    break
        has_matching_local_override = (
            matched_override is not None and matched_override.action == "local"
        )

        if matched_override is not None:
            if matched_override.action == "invalid":
                return self.record_decision(
                    self._decision(
                        status="invalid_manual_decision",
                        raw_title=raw_title,
                        hints=hints,
                        reason_codes=("invalid_manual_decision",),
                        blocked_reason="invalid_manual_decision",
                    ),
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )
            if matched_override.action == "ignore":
                return self.record_decision(
                    self._decision(
                        status="ignore",
                        raw_title=raw_title,
                        hints=hints,
                        reason_codes=self._merge_reason_codes(("manual_ignore",), override_diagnostics),
                        blocked_reason="manual_ignore",
                    ),
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )

            if matched_override.action == "confirm":
                # Manual confirmation is deliberately a local fallback: it
                # bypasses metadata and uses the exact, validated final name.
                decision = self._decision(
                    status="local_fallback",
                    raw_title=raw_title,
                    hints=naming.TitleHints(
                        raw_title=hints.raw_title,
                        local_title=matched_override.value,
                        year=None,
                        season_hints=hints.season_hints,
                        query_candidates=hints.query_candidates,
                        reason_codes=tuple(hints.reason_codes) + ("manual_confirm",),
                    ),
                    reason_codes=self._merge_reason_codes(
                        ("manual_confirm",), override_diagnostics
                    ),
                    final_root=matched_override.value,
                    final_prefix=naming.format_file_prefix(matched_override.value),
                    target_library=matched_override.target_library,
                )
                return self.record_decision(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                    target_library=matched_override.target_library,
                    library_confidence=1.0,
                    library_reason_codes=("manual_confirm",),
                )

            if matched_override.action == "local":
                decision = self._decision(
                    status="local_fallback",
                    raw_title=raw_title,
                    hints=naming.TitleHints(
                        raw_title=hints.raw_title,
                        local_title=matched_override.value,
                        year=hints.year,
                        season_hints=hints.season_hints,
                        query_candidates=hints.query_candidates,
                        reason_codes=tuple(hints.reason_codes) + ("manual_local",),
                    ),
                    reason_codes=self._merge_reason_codes(("manual_local",), override_diagnostics),
                )
                self._save_identity(
                    raw_title=raw_title,
                    decision=decision,
                    now=now,
                    config=config,
                    hints=hints,
                    directory=directory_hints,
                    search_key=self._query_hash(hints, self._provider_search_sources(config.sources)),
                    decision_fingerprint=decision_fingerprint,
                    candidates=(),
                    manual_local=True,
                )
                return self.record_decision(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )

            if matched_override.action == "query":
                query_hints = naming.parse_title(raw_title, manual_query=matched_override.value)
                search_sources = self._provider_search_sources(config.sources)
                search_key = self._query_hash(query_hints, search_sources)
                search_result = self._load_search_result(search_key, now, query_hints, search_sources)
                candidates = search_result.candidates
                if not candidates:
                    return self.record_decision(
                        self._decision(
                            status="query_blocked",
                            raw_title=raw_title,
                            hints=query_hints,
                            reason_codes=self._merge_reason_codes(
                                ("manual_query_no_candidates",),
                                override_diagnostics,
                            ),
                            blocked_reason="manual_query",
                            source_errors=search_result.errors,
                        ),
                        legacy_output_root=legacy_output_root,
                        target_output_root=target_output_root,
                    )

                evaluation = naming.evaluate_candidates(
                    query_hints,
                    directory_hints,
                    candidates,
                    auto_threshold=config.auto_threshold,
                    min_margin=config.min_margin,
                )
                top = evaluation.top
                if top is not None:
                    decision = self._decision(
                        status="query_blocked",
                        raw_title=raw_title,
                        hints=query_hints,
                        candidate=top.candidate,
                        score=top.score,
                        margin=evaluation.margin,
                        reason_codes=self._merge_reason_codes(("manual_query",), override_diagnostics),
                        source_errors=search_result.errors,
                        final_root=naming.format_root_name(
                            query_hints,
                            top.candidate,
                            append_tmdb_id=(
                                config.append_tmdb_id
                                and top.candidate.source == "themoviedb"
                            ),
                        ),
                        final_prefix=naming.format_file_prefix(
                            naming.format_root_name(
                                query_hints,
                                top.candidate,
                                append_tmdb_id=(
                                    config.append_tmdb_id
                                    and top.candidate.source == "themoviedb"
                                ),
                            )
                        ),
                    )
                else:
                    decision = self._decision(
                        status="query_blocked",
                        raw_title=raw_title,
                        hints=query_hints,
                        reason_codes=self._merge_reason_codes(("manual_query",), override_diagnostics),
                        source_errors=search_result.errors,
                    )

                self._save_query_override(
                    raw_title=raw_title,
                    now=now,
                    query_hints=query_hints,
                    query=matched_override.value,
                    search_key=search_key,
                    candidates=candidates,
                    config=config,
                )
                return self.record_decision(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )

            if matched_override.action == "candidate":
                cached = self._load_query_candidate_cache(raw_title)
                search_sources = self._provider_search_sources(config.sources)
                allowed_sources = set(config.sources)
                search_key = self._query_hash(hints, search_sources)
                candidates_by_key = {
                    item.key: item
                    for item in self._identity_candidates(self._load_identity(raw_title))
                    if item.source in allowed_sources
                }
                candidates_by_key.update(
                    {
                        item.key: item
                        for item in cached
                        if item.source in allowed_sources
                    }
                )
                stored_candidate = self._load_manual_candidate(raw_title, matched_override.value)
                if (
                    stored_candidate is not None
                    and stored_candidate.source in allowed_sources
                ):
                    candidates_by_key[stored_candidate.key] = stored_candidate
                if not candidates_by_key:
                    search_result = self._load_search_result(search_key, now, hints, search_sources)
                    candidates_by_key = {
                        item.key: item
                        for item in search_result.candidates
                        if item.source in allowed_sources
                    }
                candidate = candidates_by_key.get(matched_override.value)
                if candidate is None:
                    return self.record_decision(
                        self._decision(
                            status="invalid_override",
                            raw_title=raw_title,
                            hints=hints,
                            reason_codes=self._merge_reason_codes(("candidate_not_found",), override_diagnostics),
                            source_errors=(f"candidate_not_found:{matched_override.value}",),
                            blocked_reason="candidate_not_found",
                        ),
                        legacy_output_root=legacy_output_root,
                        target_output_root=target_output_root,
                    )

                decision = self._decision(
                    status="auto_external",
                    raw_title=raw_title,
                    hints=hints,
                    candidate=candidate,
                    score=100,
                    margin=config.min_margin,
                    final_root=naming.format_root_name(
                        hints,
                        candidate,
                        append_tmdb_id=(
                            config.append_tmdb_id
                            and candidate.source == "themoviedb"
                        ),
                    ),
                    final_prefix=naming.format_file_prefix(
                        naming.format_root_name(hints, candidate, append_tmdb_id=False)
                    ),
                    reason_codes=self._merge_reason_codes(("manual_candidate",), override_diagnostics),
                )
                self._save_identity(
                    raw_title=raw_title,
                    decision=decision,
                    now=now,
                    config=config,
                    hints=hints,
                    directory=directory_hints,
                    search_key=search_key,
                    decision_fingerprint=decision_fingerprint,
                    candidates=tuple(candidates_by_key.values()),
                    manual_local=False,
                )
                return self.record_decision(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )

        # AI only contributes a bounded search phrase.  All candidate scoring,
        # whitelisting, and final media selection remain on the normal path.
        hints = self._enrich_hints_with_ai_query(hints, raw_title, now, config)
        search_sources = self._provider_search_sources(config.sources)
        search_key = self._query_hash(hints, search_sources)
        identity = self._load_identity(raw_title)

        cached_candidates: Tuple[naming.MetadataCandidate, ...] = ()
        identity_candidates = self._identity_candidates(identity) if identity else ()

        if identity is not None and self._identity_reusable(
            identity, search_key, now, has_matching_local_override, config.uncertain_policy
        ):
            try:
                identity_updated = int(identity.get("updated", now))
            except (TypeError, ValueError):
                identity_updated = now
            cached_candidates = identity_candidates
            adopted = self._identity_to_decision(
                identity,
                raw_title=raw_title,
                hints=hints,
            )
            if adopted is not None and not cached_candidates:
                return self.record_decision(
                    adopted,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )
            if cached_candidates:
                identity_source_errors = tuple(identity.get("source_errors", ()))
                evaluation = naming.evaluate_candidates(
                    hints,
                    directory_hints,
                    cached_candidates,
                    auto_threshold=config.auto_threshold,
                    min_margin=config.min_margin,
                )
                decision = self._decision_from_evaluation(
                    evaluation,
                    hints,
                    config,
                    raw_title=raw_title,
                    source_errors=identity_source_errors,
                    reason_codes=override_diagnostics,
                    candidates=cached_candidates,
                )
                if decision.status == "review" and (not config.ai_review or self._ai_reviewer is None):
                    decision = self._resolve_uncertain(decision, config, hints)
                if decision.status != "review" or not config.ai_review or self._ai_reviewer is None:
                    if decision.status in {"auto_external", "local_fallback"}:
                        self._save_identity(
                            raw_title=raw_title,
                            decision=decision,
                            now=identity_updated,
                            config=config,
                            hints=hints,
                            directory=directory_hints,
                            search_key=search_key,
                            decision_fingerprint=decision_fingerprint,
                            candidates=cached_candidates,
                        )
                    return self.record_decision(
                        decision,
                        legacy_output_root=legacy_output_root,
                        target_output_root=target_output_root,
                    )

                if decision.status == "review" and config.ai_review and self._ai_reviewer is not None:
                    reviewed = self._ai_reviewer.review(
                        raw_title=raw_title,
                        hints=hints,
                        candidates=list(evaluation.eligible),
                        score_lookup={item.candidate.key: item.score for item in evaluation.eligible},
                    )
                    decision = self._merge_ai_review(
                        raw_title=raw_title,
                        result=reviewed,
                        decision=decision,
                        evaluation=evaluation,
                        config=config,
                        candidates=evaluation.eligible,
                        score_lookup={item.candidate.key: item.score for item in evaluation.eligible},
                        hints=hints,
                    )
                    if reviewed.error:
                        self._append_ai_error(raw_title, reviewed)
                    if decision.status in {"auto_external", "local_fallback"}:
                        self._save_identity(
                            raw_title=raw_title,
                            decision=decision,
                            now=identity_updated,
                            config=config,
                            hints=hints,
                            directory=directory_hints,
                            search_key=search_key,
                            decision_fingerprint=decision_fingerprint,
                            candidates=cached_candidates,
                            manual_local=has_matching_local_override,
                        )
                    return self.record_decision(
                        decision,
                        legacy_output_root=legacy_output_root,
                        target_output_root=target_output_root,
                    )
                return self.record_decision(
                    decision,
                    legacy_output_root=legacy_output_root,
                    target_output_root=target_output_root,
                )

        search_result = self._load_search_result(search_key, now, hints, search_sources)
        candidates = search_result.candidates

        if search_result.all_failed and not candidates:
            fallback_status = "manual_review" if config.uncertain_policy == "hold" else "local_fallback"
            return self.record_decision(
                self._decision(
                    status=fallback_status,
                    raw_title=raw_title,
                    hints=hints,
                    reason_codes=self._merge_reason_codes(("all_search_failed",), override_diagnostics),
                    source_errors=search_result.errors,
                    score=0,
                    margin=0,
                ),
                legacy_output_root=legacy_output_root,
                target_output_root=target_output_root,
            )

        if not candidates:
            fallback_status = (
                "manual_review"
                if config.uncertain_policy == "hold"
                else "local_fallback"
            )
            decision = self._decision(
                status=fallback_status,
                raw_title=raw_title,
                hints=hints,
                reason_codes=self._merge_reason_codes(("no_candidates",), override_diagnostics),
                source_errors=search_result.errors,
                blocked_reason="manual_review" if fallback_status == "manual_review" else "",
            )
            self._save_identity(
                raw_title=raw_title,
                decision=decision,
                now=now,
                config=config,
                hints=hints,
                directory=directory_hints,
                search_key=search_key,
                decision_fingerprint=decision_fingerprint,
                candidates=(),
            )
            return self.record_decision(
                decision,
                legacy_output_root=legacy_output_root,
                target_output_root=target_output_root,
            )

        evaluation = naming.evaluate_candidates(
            hints,
            directory_hints,
            candidates,
            auto_threshold=config.auto_threshold,
            min_margin=config.min_margin,
        )
        decision = self._decision_from_evaluation(
            evaluation,
            hints,
            config,
            raw_title=raw_title,
            source_errors=search_result.errors,
            reason_codes=override_diagnostics,
            candidates=candidates,
        )
        if decision.status == "review" and (not config.ai_review or self._ai_reviewer is None):
            decision = self._resolve_uncertain(decision, config, hints)

        if decision.status != "review" or not config.ai_review or self._ai_reviewer is None:
            if decision.status in {"auto_external", "local_fallback"}:
                self._save_identity(
                    raw_title=raw_title,
                    decision=decision,
                    now=now,
                    config=config,
                    hints=hints,
                    directory=directory_hints,
                    search_key=search_key,
                    decision_fingerprint=decision_fingerprint,
                    candidates=candidates,
                    manual_local=has_matching_local_override,
                )
            return self.record_decision(
                decision,
                legacy_output_root=legacy_output_root,
                target_output_root=target_output_root,
            )

        if decision.status == "review" and config.ai_review and self._ai_reviewer is not None:
            reviewed = self._ai_reviewer.review(
                raw_title=raw_title,
                hints=hints,
                candidates=list(evaluation.eligible),
                score_lookup={item.candidate.key: item.score for item in evaluation.eligible},
            )
            decision = self._merge_ai_review(
                raw_title=raw_title,
                result=reviewed,
                decision=decision,
                evaluation=evaluation,
                config=config,
                candidates=evaluation.eligible,
                score_lookup={item.candidate.key: item.score for item in evaluation.eligible},
                hints=hints,
            )
            if reviewed.error:
                self._append_ai_error(raw_title, reviewed)

            if decision.status in {"auto_external", "local_fallback"}:
                self._save_identity(
                    raw_title=raw_title,
                    decision=decision,
                    now=now,
                    config=config,
                    hints=hints,
                    directory=directory_hints,
                    search_key=search_key,
                    decision_fingerprint=decision_fingerprint,
                    candidates=candidates,
                    manual_local=has_matching_local_override,
                )

        return self.record_decision(
            decision,
            legacy_output_root=legacy_output_root,
            target_output_root=target_output_root,
        )

    def _identity_reusable(
        self,
        identity: Dict[str, Any],
        search_key: str,
        now: int,
        has_matching_local_override: bool = False,
        uncertain_policy: str = "local",
    ) -> bool:
        if not isinstance(identity, dict):
            return False
        if identity.get("search_key") != search_key:
            return False
        if bool(identity.get("no_reuse", False)):
            return False
        status = str(identity.get("status", ""))
        if status in {"blocked", "invalid_override", "ignore", "query_blocked", "manual_review"}:
            return False
        if status == "local_fallback" and identity.get("manual_local") and not has_matching_local_override:
            return False
        if status == "local_fallback" and str(identity.get("uncertain_policy", "local")) != str(uncertain_policy):
            return False
        if bool(identity.get("all_search_failed", False)):
            return False
        reason_codes = tuple(identity.get("reason_codes", ()))
        source_errors = tuple(identity.get("source_errors", ()))
        manually_selected = bool(identity.get("manual_local", False)) or (
            "manual_candidate" in reason_codes
        )
        if not manually_selected:
            try:
                updated = int(identity.get("updated", 0))
            except (TypeError, ValueError):
                updated = 0
            ttl = self.ERROR_TTL_SECONDS if source_errors else self.SEARCH_TTL_SECONDS
            if not 0 <= now - updated < ttl:
                return False
        if status == "local_fallback" and (
            "all_search_failed" in reason_codes
            or "all_search_failed" in source_errors
        ):
            return False
        return True

    def _identity_to_decision(
        self,
        identity: Dict[str, Any],
        raw_title: str,
        hints: naming.TitleHints,
    ) -> Optional[NamingDecision]:
        status = str(identity.get("status", ""))
        if status not in {"local_fallback", "auto_external"}:
            return None
        final_root = str(identity.get("final_root", "")) if status == "auto_external" else ""
        return self._decision(
            status=status,
            raw_title=raw_title,
            hints=hints,
            final_root=final_root or naming.format_root_name(hints, None),
            score=int(identity.get("score", 0)),
            margin=int(identity.get("margin", 0)),
            reason_codes=tuple(identity.get("reason_codes", ())),
            source_errors=tuple(identity.get("source_errors", ())),
            candidate_key=str(identity.get("candidate_key", "")),
            source=str(identity.get("source", "")),
            media_id=str(identity.get("media_id", "")),
            media_type=str(identity.get("media_type", "unknown")),
        )

    def _identity_candidate_by_key(
        self,
        candidates: Sequence[Any],
        candidate_key: str,
    ) -> Optional[naming.MetadataCandidate]:
        for candidate in candidates:
            selected_key = None
            if isinstance(candidate, naming.MetadataCandidate):
                selected_key = candidate.key
            elif hasattr(candidate, "candidate") and isinstance(candidate.candidate, naming.MetadataCandidate):
                selected_key = candidate.candidate.key
            else:
                selected_key = getattr(candidate, "key", None)
            if selected_key == candidate_key:
                if isinstance(candidate, naming.MetadataCandidate):
                    return candidate
                return candidate.candidate
        return None

    def _provider_search_sources(self, requested: Sequence[str]) -> Tuple[str, ...]:
        getter = getattr(self._provider, "resolve_sources", None)
        if callable(getter):
            return tuple(getter(requested))
        resolved: List[str] = []
        for value in requested:
            source = str(value or "").strip().lower()
            if source in {"hk", "tw", "sg"}:
                source = "themoviedb"
            if source in {"themoviedb", "douban"} and source not in resolved:
                resolved.append(source)
        return tuple(resolved)

    @staticmethod
    def _with_query_candidates(
        hints: "naming.TitleHints",
        candidates: Sequence["naming.QueryCandidate"],
    ) -> "naming.TitleHints":
        return naming.TitleHints(
            raw_title=hints.raw_title,
            local_title=hints.local_title,
            year=hints.year,
            season_hints=hints.season_hints,
            query_candidates=tuple(candidates),
            reason_codes=hints.reason_codes,
        )

    @staticmethod
    def _needs_ai_query(hints: "naming.TitleHints") -> bool:
        """Reserve LLM calls for names where rules have visibly removed noise."""
        if len(hints.season_hints) >= 2:
            return True
        return naming.normalize_title(hints.raw_title) != naming.normalize_title(
            hints.local_title
        )

    def _ai_query_schema(self) -> str:
        return str(getattr(self._ai_reviewer, "QUERY_SCHEMA_VERSION", "1"))

    def _ai_query_cache_key(self, hints: "naming.TitleHints") -> str:
        return naming.query_hash(
            raw_title=hints.raw_title,
            queries=(
                naming.QueryCandidate(
                    text=hints.local_title,
                    origin="ai_query_input",
                    quality_bonus=0,
                ),
            ),
            sources=("ai_query",),
            provider_schema=self._ai_query_schema(),
        )

    def _prepend_ai_query(
        self,
        hints: "naming.TitleHints",
        query: str,
    ) -> "naming.TitleHints":
        normalized = naming.normalize_title(query)
        if not normalized:
            return hints
        remaining = [
            candidate
            for candidate in hints.query_candidates
            if naming.normalize_title(candidate.text) != normalized
        ]
        return self._with_query_candidates(
            hints,
            (
                naming.QueryCandidate(text=query, origin="ai_query", quality_bonus=5),
                *remaining,
            )[:3],
        )

    def _enrich_hints_with_ai_query(
        self,
        hints: "naming.TitleHints",
        raw_title: str,
        now: int,
        config: NamingConfig,
    ) -> "naming.TitleHints":
        """Prepend a cached, safe LLM query without giving it decision authority."""
        reviewer = self._ai_reviewer
        suggest = getattr(reviewer, "suggest_query", None)
        if (
            not config.ai_review
            or reviewer is None
            or not callable(suggest)
            or not self._needs_ai_query(hints)
        ):
            return hints

        cache = self._load_json(self.AI_QUERY_CACHE_KEY, {})
        if not isinstance(cache, dict):
            cache = {}
        cache_key = self._ai_query_cache_key(hints)
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            parser_schema = str(cached.get("parser_schema", ""))
            query_schema = str(cached.get("query_schema", ""))
            if (
                parser_schema == naming.PARSER_SCHEMA_VERSION
                and query_schema == self._ai_query_schema()
                and cached.get("raw_title") == hints.raw_title
            ):
                try:
                    updated = int(cached.get("updated", 0))
                except (TypeError, ValueError):
                    updated = 0
                ttl = (
                    self.AI_QUERY_ERROR_TTL_SECONDS
                    if bool(cached.get("failed", False))
                    else self.AI_QUERY_TTL_SECONDS
                )
                if 0 <= now - updated < ttl:
                    query = MoviePilotAIReviewer.validate_search_query(
                        cached.get("query", "")
                    )
                    return self._prepend_ai_query(hints, query) if query else hints
            cache.pop(cache_key, None)
            self._save_data(self.AI_QUERY_CACHE_KEY, cache)

        try:
            query = MoviePilotAIReviewer.validate_search_query(
                suggest(hints.raw_title, hints)
            )
        except Exception:
            query = ""

        cache[cache_key] = {
            "updated": now,
            "raw_title": hints.raw_title,
            "query": query,
            "failed": not bool(query),
            "parser_schema": naming.PARSER_SCHEMA_VERSION,
            "query_schema": self._ai_query_schema(),
        }
        self._prune_cache(cache, self.AI_QUERY_CACHE_MAX)
        self._save_data(self.AI_QUERY_CACHE_KEY, cache)
        return self._prepend_ai_query(hints, query) if query else hints

    def _augment_fallback_queries(
        self,
        hints: "naming.TitleHints",
        raw_title: str,
    ) -> "naming.TitleHints":
        """在主解析查询词之外，追加去掉常见修饰词后的短名查询，作为搜索回退。"""
        primary = tuple(hints.query_candidates or ())
        seen = set()
        extra_texts = []
        for cand in primary:
            seen.add(naming.normalize_title(cand.text))
        # Derive short fallbacks from the parsed title and every primary query.
        # An AI term can occupy slot zero, so using only the first candidate
        # would otherwise miss a useful shorter rule-based form.
        bases = [hints.local_title or hints.raw_title or raw_title]
        bases.extend(candidate.text for candidate in primary if candidate.text)
        for base in bases:
            for text in self._trim_variants(base):
                key = naming.normalize_title(text)
                if key and key not in seen:
                    seen.add(key)
                    extra_texts.append(text)
        if not extra_texts:
            return hints
        fallback_queries = [
            naming.QueryCandidate(text=text, origin="fallback", quality_bonus=0)
            for text in extra_texts
        ]
        if len(primary) + len(fallback_queries) <= 3:
            return self._with_query_candidates(hints, list(primary) + fallback_queries)

        # The provider receives at most three terms.  When the parser already
        # filled all three slots, reserve the last slot for a genuinely new
        # shorter fallback while retaining the first (possibly AI) term.
        return self._with_query_candidates(
            hints,
            list(primary[:2]) + [fallback_queries[0]],
        )

    def _trim_variants(self, text: str) -> list:
        """生成从完整名逐步去掉常见修饰词后的短名变体。"""
        text = str(text or "").strip()
        if not text:
            return []
        out = []
        cur = text
        # 常见中文/标题修饰后缀
        suffixes = [
            "高清修复版", "修复版", "高清版", "未删减版", "未删减",
            "高清", "修复", "蓝光", "收藏版", "全集", "国语", "中字",
        ]
        changed = True
        while changed:
            changed = False
            for suf in suffixes:
                if cur.endswith(suf):
                    cur = cur[: -len(suf)].strip()
                    if cur:
                        out.append(cur)
                    changed = True
                    break
            if len(cur) <= 1:
                break
        # 若存在全角/半角括号年份，保留核心名
        import re
        core = re.sub(r"[（(\s]*\d{4}[）)\s]*$", "", cur)
        if core and core != cur:
            out.append(core.strip())
        if cur and all(cur != x for x in out):
            out.append(cur)
        return list(dict.fromkeys([x for x in out if x]))

    def search_tmdb_candidates(
        self,
        raw_title: str,
        config: NamingConfig,
        limit: int = 10,
    ) -> ProviderSearchResult:
        """Search TMDB using the parsed directory name and the shared cache."""
        config = NamingConfig.sanitize(config)
        if config.mode == "off":
            return ProviderSearchResult((), ("naming_disabled",), (), True)
        if "themoviedb" not in config.sources:
            return ProviderSearchResult((), ("themoviedb_not_enabled",), (), True)

        try:
            now = int(self._clock())
        except (TypeError, ValueError, OverflowError):
            now = int(time.time())
        hints = naming.parse_title(raw_title)
        # Keep the AI term first when enabled; rule-generated variants remain
        # available as low-cost fallbacks if the provider finds no exact match.
        hints = self._enrich_hints_with_ai_query(hints, raw_title, now, config)
        # 搜索词自动回退：主解析词搜不到时，追加去掉常见修饰词后的短名，
        # 提高命中率（例如"黑冰高清修复版"→回退"黑冰"）。
        hints = self._augment_fallback_queries(hints, raw_title)
        sources = self._provider_search_sources(("themoviedb",))
        if "themoviedb" not in sources:
            return ProviderSearchResult((), ("themoviedb_unavailable",), (), True)

        search_key = self._query_hash(hints, sources)
        identity = self._load_identity(raw_title)
        if (
            isinstance(identity, dict)
            and identity.get("raw_title", raw_title) == raw_title
            and identity.get("search_key") == search_key
        ):
            try:
                updated = int(identity.get("updated", 0))
            except (TypeError, ValueError):
                updated = 0
            identity_errors = tuple(identity.get("source_errors", ()))
            identity_ttl = (
                self.ERROR_TTL_SECONDS if identity_errors else self.SEARCH_TTL_SECONDS
            )
            if 0 <= now - updated < identity_ttl:
                identity_candidates = tuple(
                    candidate
                    for candidate in self._identity_candidates(identity)
                    if candidate.source == "themoviedb"
                )[: max(1, min(int(limit), 10))]
                if identity_candidates:
                    return ProviderSearchResult(
                        candidates=identity_candidates,
                        errors=tuple(identity.get("source_errors", ())),
                        attempted_sources=("themoviedb",),
                        all_failed=False,
                    )
        result = self._load_search_result(
            search_key, now, hints, sources, retry_failed=True
        )
        candidates = tuple(
            candidate
            for candidate in result.candidates
            if candidate.source == "themoviedb"
        )[: max(1, min(int(limit), 10))]
        return ProviderSearchResult(
            candidates=candidates,
            errors=result.errors,
            attempted_sources=result.attempted_sources,
            all_failed=result.all_failed and not bool(candidates),
        )

    def _decision_from_evaluation(
        self,
        evaluation: naming.MatchEvaluation,
        hints: naming.TitleHints,
        config: NamingConfig,
        raw_title: Optional[str] = None,
        source_errors: Tuple[str, ...] = (),
        reason_codes: Tuple[str, ...] = (),
        candidates: Optional[Sequence[naming.MetadataCandidate]] = None,
    ) -> NamingDecision:
        _ = candidates
        decision_raw_title = raw_title if raw_title is not None else hints.raw_title
        if evaluation.top is None:
            return self._decision(
                status=evaluation.status,
                raw_title=decision_raw_title,
                hints=hints,
                margin=evaluation.margin,
                reason_codes=self._merge_reason_codes(evaluation.reason_codes, reason_codes),
                source_errors=source_errors,
            )

        top = evaluation.top.candidate
        final_root: Optional[str] = None
        if evaluation.status == "auto_external":
            final_root = naming.format_root_name(
                hints,
                top,
                append_tmdb_id=config.append_tmdb_id and top.source == "themoviedb",
            )
        return self._decision(
            status=evaluation.status,
            raw_title=decision_raw_title,
            hints=hints,
            candidate=top,
            score=evaluation.top.score,
            margin=evaluation.margin,
            reason_codes=self._merge_reason_codes(evaluation.reason_codes + evaluation.top.reason_codes, reason_codes),
            source_errors=source_errors,
            final_root=final_root,
            candidate_key=top.key,
        )

    @staticmethod
    def _valid_ai_confidence(confidence: Any) -> bool:
        return (
            not isinstance(confidence, bool)
            and isinstance(confidence, (int, float))
            and math.isfinite(float(confidence))
            and 0.85 <= float(confidence) <= 1.0
        )

    @staticmethod
    def _merge_reason_codes(
        *parts: Tuple[str, ...],
    ) -> Tuple[str, ...]:
        ordered: List[str] = []
        seen = set()
        for part in parts:
            for code in part:
                if code in seen:
                    continue
                ordered.append(code)
                seen.add(code)
        return tuple(ordered)

    def _merge_ai_review(
        self,
        raw_title: str,
        result: AIReviewResult,
        decision: NamingDecision,
        evaluation: naming.MatchEvaluation,
        config: NamingConfig,
        candidates: Sequence[naming.MetadataCandidate],
        hints: naming.TitleHints,
        score_lookup: Optional[Dict[str, int]] = None,
    ) -> NamingDecision:
        if not result.accepted or result.decision != "choose":
            status = "manual_review" if config.uncertain_policy == "hold" else "local_fallback"
            source_errors = tuple(decision.source_errors)
            if result.error:
                source_errors = tuple(source_errors) + (f"ai_review:{result.error}",)
            return self._decision(
                status=status,
                raw_title=raw_title,
                hints=hints,
                score=decision.score,
                margin=decision.margin,
                reason_codes=tuple(decision.reason_codes) + tuple(result.reason_codes),
                source_errors=source_errors,
                blocked_reason="ai_review_blocked" if status == "manual_review" else "",
            )

        selected = self._identity_candidate_by_key(candidates, result.candidate_key)
        if selected is None:
            return self._merge_ai_review(
                raw_title=raw_title,
                result=AIReviewResult(
                    accepted=False,
                    decision="choose",
                    candidate_key=result.candidate_key,
                    confidence=result.confidence,
                    reason_codes=tuple(result.reason_codes) + ("candidate_not_whitelisted",),
                    error="candidate_not_whitelisted",
                ),
                decision=decision,
                evaluation=evaluation,
                config=config,
                candidates=candidates,
                hints=hints,
                score_lookup=score_lookup,
            )

        if score_lookup is None:
            score_lookup = {}

        try:
            score = int(score_lookup[selected.key])
        except (TypeError, ValueError, KeyError):
            return self._merge_ai_review(
                raw_title=raw_title,
                result=AIReviewResult(
                    accepted=False,
                    decision="choose",
                    candidate_key=result.candidate_key,
                    confidence=result.confidence,
                    reason_codes=tuple(result.reason_codes) + ("candidate_not_whitelisted",),
                    error="candidate_not_whitelisted",
                ),
                decision=decision,
                evaluation=evaluation,
                config=config,
                candidates=candidates,
                hints=hints,
                score_lookup=score_lookup,
            )

        if score < 70:
            return self._decision(
                status="manual_review" if config.uncertain_policy == "hold" else "local_fallback",
                raw_title=raw_title,
                hints=hints,
                score=score,
                margin=decision.margin,
                reason_codes=tuple(decision.reason_codes) + ("score_too_low",),
                source_errors=decision.source_errors,
                blocked_reason="ai_review_blocked" if config.uncertain_policy == "hold" else "",
            )

        if not self._valid_ai_confidence(result.confidence):
            return self._decision(
                status="manual_review" if config.uncertain_policy == "hold" else "local_fallback",
                raw_title=raw_title,
                hints=hints,
                score=score,
                margin=decision.margin,
                reason_codes=tuple(decision.reason_codes) + ("low_confidence",),
                source_errors=decision.source_errors,
                blocked_reason="ai_review_blocked" if config.uncertain_policy == "hold" else "",
            )

        final_root = naming.format_root_name(
            hints,
            selected,
            append_tmdb_id=config.append_tmdb_id and selected.source == "themoviedb",
        )
        return self._decision(
            status="auto_external",
            raw_title=raw_title,
            hints=hints,
            candidate=selected,
            score=score,
            margin=decision.margin,
            reason_codes=tuple(decision.reason_codes) + tuple(result.reason_codes) + ("ai_review",),
            source_errors=decision.source_errors,
            candidate_key=selected.key,
            final_root=final_root,
        )

    @staticmethod
    def _eligible_keys(candidates: Sequence[naming.MetadataCandidate]) -> Tuple[str, ...]:
        return tuple(candidate.key for candidate in candidates)

    def _save_query_override(
        self,
        raw_title: str,
        now: int,
        query_hints: naming.TitleHints,
        query: str,
        search_key: str,
        candidates: Tuple[naming.MetadataCandidate, ...],
        config: NamingConfig,
    ) -> None:
        identities = self._load_json("naming_identity_v1", {})
        if not isinstance(identities, dict):
            identities = {}

        identity = identities.get(raw_title)
        if not isinstance(identity, dict):
            identity = {}
        identity.update(
            {
                "last_query_override": query,
                "last_query_key": search_key,
                "last_query_candidates": [item.to_dict() for item in candidates],
                "last_query_updated": now,
                "manual_override_config": config.manual_overrides,
            }
        )
        identities.pop(raw_title, None)
        identities[raw_title] = identity
        self._prune_cache(identities, self.IDENTITY_MAX)
        self._save_data("naming_identity_v1", identities)

    def _load_query_candidate_cache(self, raw_title: str) -> Tuple[naming.MetadataCandidate, ...]:
        identity = self._load_identity(raw_title)
        if not isinstance(identity, dict):
            return ()
        payload = identity.get("last_query_candidates")
        if not isinstance(payload, list):
            return ()
        output: List[naming.MetadataCandidate] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                output.append(naming.MetadataCandidate.from_dict(item))
            except Exception:
                continue
        return tuple(output)

    def _load_manual_candidate(
        self, raw_title: str, candidate_key: str
    ) -> Optional[naming.MetadataCandidate]:
        payload = self._load_json("naming_manual_decisions_v1", {})
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return None
        items = payload.get("items")
        entry = items.get(raw_title) if isinstance(items, dict) else None
        candidate_payload = entry.get("candidate") if isinstance(entry, dict) else None
        if not isinstance(candidate_payload, dict):
            return None
        try:
            candidate = naming.MetadataCandidate.from_dict(candidate_payload)
        except Exception:
            return None
        if (
            candidate.key != candidate_key
            or candidate.source != "themoviedb"
            or not candidate.key.startswith("themoviedb:")
            or not candidate.media_id
            or not candidate.title
            or candidate.media_type not in {"tv", "movie", "unknown"}
            or candidate.key != f"themoviedb:{candidate.media_id}:{candidate.media_type}"
        ):
            return None
        return candidate

    def _identity_candidates(self, identity: Dict[str, Any]) -> Tuple[naming.MetadataCandidate, ...]:
        payload = identity.get("cached_candidates") if isinstance(identity, dict) else ()
        if not isinstance(payload, list):
            return ()
        output: List[naming.MetadataCandidate] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                output.append(naming.MetadataCandidate.from_dict(item))
            except Exception:
                continue
        return tuple(output)

    def _load_identity(self, raw_title: str) -> Optional[Dict[str, Any]]:
        identities = self._load_json("naming_identity_v1", {})
        if not isinstance(identities, dict):
            return None
        identity = identities.get(raw_title)
        return identity if isinstance(identity, dict) else None

    def _load_search_result(
        self,
        search_key: str,
        now: int,
        hints: naming.TitleHints,
        sources: Sequence[str],
        retry_failed: bool = False,
    ) -> ProviderSearchResult:
        cache = self._load_json("naming_search_cache_v1", {})
        if not isinstance(cache, dict):
            cache = {}
        if isinstance(cache, dict):
            cached = cache.get(search_key)
            if isinstance(cached, dict):
                parser_schema = str(cached.get("parser_schema", ""))
                provider_schema = str(cached.get("provider_schema", ""))
                if parser_schema != naming.PARSER_SCHEMA_VERSION or provider_schema != self._provider_schema():
                    cache.pop(search_key, None)
                    self._save_data("naming_search_cache_v1", cache)
                else:
                    if retry_failed and (
                        cached.get("all_failed", False)
                        or not cached.get("candidates")
                        or cached.get("errors")
                    ):
                        cache.pop(search_key, None)
                        self._save_data("naming_search_cache_v1", cache)
                    else:
                        ttl = (
                            self.ERROR_TTL_SECONDS
                            if cached.get("all_failed", False) or cached.get("errors")
                            else self.SEARCH_TTL_SECONDS
                        )
                        try:
                            updated = int(cached.get("updated", 0))
                        except (TypeError, ValueError):
                            updated = 0
                        if 0 <= now - updated < ttl:
                            candidates = tuple(
                                naming.MetadataCandidate.from_dict(item)
                                for item in cached.get("candidates", ())
                                if isinstance(item, dict)
                            )
                            return ProviderSearchResult(
                                candidates=candidates,
                                errors=tuple(cached.get("errors", ())),
                                attempted_sources=tuple(cached.get("attempted_sources", ())),
                                all_failed=bool(cached.get("all_failed", False)),
                            )
                        cache.pop(search_key, None)
                        self._save_data("naming_search_cache_v1", cache)

        result = self._provider.search(hints.query_candidates, sources)
        cache[search_key] = {
            "updated": now,
            "candidates": [item.to_dict() for item in result.candidates],
            "errors": list(result.errors),
            "attempted_sources": list(result.attempted_sources),
            "all_failed": bool(result.all_failed),
            "parser_schema": naming.PARSER_SCHEMA_VERSION,
            "provider_schema": self._provider_schema(),
        }
        self._prune_cache(cache, self.SEARCH_CACHE_MAX)
        self._save_data("naming_search_cache_v1", cache)
        return result

    def _load_json(self, key: str, default: Any) -> Any:
        raw = self._load_data(key, default)
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return default
        return raw if raw is not None else default

    def _prune_cache(self, value: Any, max_items: int, by_key: str = "updated") -> None:
        """Keep the most recently written entries using persisted collection order.

        Wall-clock timestamps can move backwards after a VM/NAS snapshot restore.
        JSON object/list order is stable, so writers touch refreshed entries by moving
        them to the end and pruning always removes from the front.  ``by_key`` stays
        in the signature for compatibility with older callers and stored payloads.
        """
        del by_key
        if isinstance(value, dict):
            overflow = len(value) - max_items
            for key in tuple(value.keys())[:max(0, overflow)]:
                value.pop(key, None)
            return
        if not isinstance(value, list):
            return
        if len(value) > max_items:
            del value[: len(value) - max_items]

    def _provider_schema(self) -> str:
        return str(getattr(self._provider, "PROVIDER_SCHEMA_VERSION", "1"))

    def _query_hash(self, hints: naming.TitleHints, sources: Sequence[str]) -> str:
        return naming.query_hash(
            raw_title=hints.raw_title,
            queries=hints.query_candidates,
            sources=sources,
            provider_schema=self._provider_schema(),
        )

    def record_decision(
        self,
        decision: NamingDecision,
        legacy_output_root: str = "",
        target_output_root: str = "",
        target_library: str = "",
        library_confidence: float = 0.0,
        library_reason_codes: Tuple[str, ...] = (),
    ) -> NamingDecision:
        return self._append_and_record(
            decision=decision,
            legacy_output_root=legacy_output_root,
            target_output_root=target_output_root,
            target_library=target_library,
            library_confidence=library_confidence,
            library_reason_codes=library_reason_codes,
        )

    def record_output_conflict(
        self,
        decision: NamingDecision,
        legacy_output_root: str = "",
        target_output_root: str = "",
        target_library: str = "",
        library_confidence: float = 0.0,
        library_reason_codes: Tuple[str, ...] = (),
    ) -> NamingDecision:
        return self._append_and_record(
            decision=self._decision(
                status="legacy_output_conflict",
                raw_title=decision.raw_title,
                hints=naming.TitleHints(
                    raw_title=decision.raw_title,
                    local_title=decision.local_title,
                    year=None,
                    season_hints=(),
                    query_candidates=(),
                    reason_codes=(),
                ),
            source=decision.source,
            media_id=decision.media_id,
            media_type=decision.media_type,
                score=decision.score,
                margin=decision.margin,
                reason_codes=("legacy_output_conflict",),
                source_errors=decision.source_errors,
                blocked_reason="legacy_output_conflict",
                final_root=decision.final_root,
                final_prefix=decision.final_prefix,
                candidate_key=decision.candidate_key,
            ),
            legacy_output_root=legacy_output_root,
            target_output_root=target_output_root,
            target_library=target_library,
            library_confidence=library_confidence,
            library_reason_codes=library_reason_codes,
        )

    def _append_and_record(
        self,
        decision: NamingDecision,
        legacy_output_root: str = "",
        target_output_root: str = "",
        target_library: str = "",
        library_confidence: float = 0.0,
        library_reason_codes: Tuple[str, ...] = (),
    ) -> NamingDecision:
        row = {
            "raw_title": decision.raw_title,
            "local_title": decision.local_title,
            "final_title": decision.final_root,
            "source": decision.source,
            "media_id": decision.media_id,
            "media_type": decision.media_type,
            "score": decision.score,
            "margin": decision.margin,
            "status": decision.status,
            "reason_codes": list(decision.reason_codes),
            "source_errors": list(decision.source_errors),
            "blocked_reason": decision.blocked_reason,
            "timestamp": int(self._clock()),
            "legacy_output_root": legacy_output_root,
            "target_output_root": target_output_root,
            "target_library": target_library or decision.target_library,
            "library_confidence": library_confidence,
            "library_reason_codes": list(library_reason_codes),
        }
        rows = self._load_json("naming_preview_v1", [])
        if not isinstance(rows, list):
            rows = []

        for index, item in enumerate(rows):
            if isinstance(item, dict) and item.get("raw_title") == decision.raw_title:
                rows.pop(index)
                rows.append(row)
                break
        else:
            rows.append(row)

        self._prune_cache(rows, self.PREVIEW_MAX)
        self._save_data("naming_preview_v1", rows)
        return decision

    def preview_rows(self) -> List[Dict[str, Any]]:
        rows = self._load_json("naming_preview_v1", [])
        return rows if isinstance(rows, list) else []

    def mark_completed(self, raw_title: str) -> bool:
        """Mark a successfully moved preview while retaining its history row."""
        completed_at = int(self._clock())
        for _attempt in range(2):
            loaded_rows = self._load_json("naming_preview_v1", [])
            if not isinstance(loaded_rows, list):
                return False
            try:
                rows = copy.deepcopy(loaded_rows)
            except Exception:
                return False
            for index, item in enumerate(rows):
                if not isinstance(item, dict) or item.get("raw_title") != raw_title:
                    continue
                if item.get("completed_at") is not None:
                    return True
                completed = dict(item)
                completed["completed_at"] = completed_at
                rows.pop(index)
                rows.append(completed)
                try:
                    saved = self._save_data("naming_preview_v1", rows)
                except Exception:
                    saved = False
                if saved is False:
                    break
                try:
                    verified = copy.deepcopy(self._load_json("naming_preview_v1", []))
                except Exception:
                    verified = []
                if isinstance(verified, list) and any(
                    isinstance(candidate, dict)
                    and candidate.get("raw_title") == raw_title
                    and candidate.get("completed_at") is not None
                    for candidate in verified
                ):
                    return True
                break
        return False

    def _append_ai_error(self, raw_title: str, result: AIReviewResult) -> None:
        rows = self._load_json("naming_ai_errors_v1", [])
        if not isinstance(rows, list):
            rows = []
        rows.append(
            {
                "raw_title": raw_title,
                "error": result.error,
                "decision": result.decision,
                "candidate_key": result.candidate_key,
                "confidence": result.confidence,
                "timestamp": int(self._clock()),
            }
        )
        self._prune_cache(rows, self.AI_ERROR_MAX)
        self._save_data("naming_ai_errors_v1", rows)

    def _save_identity(
        self,
        raw_title: str,
        decision: NamingDecision,
        now: int,
        config: NamingConfig,
        hints: naming.TitleHints,
        directory: naming.DirectoryHints,
        search_key: str,
        decision_fingerprint: str,
        candidates: Sequence[Any],
        manual_local: bool = False,
    ) -> None:
        if decision.status == "local_fallback" and (
            "all_search_failed" in decision.reason_codes
            or "all_search_failed" in decision.source_errors
        ):
            return
        if decision.status not in {"auto_external", "local_fallback"}:
            return

        identities = self._load_json("naming_identity_v1", {})
        if not isinstance(identities, dict):
            identities = {}

        identities.pop(raw_title, None)
        identities[raw_title] = {
            "updated": now,
            "status": decision.status,
            "raw_title": decision.raw_title,
            "local_title": decision.local_title,
            "final_root": decision.final_root,
            "source": decision.source,
            "media_id": decision.media_id,
            "media_type": decision.media_type,
            "candidate_key": decision.candidate_key,
            "search_key": search_key,
            "decision_fingerprint": decision_fingerprint,
            "score": decision.score,
            "margin": decision.margin,
            "reason_codes": list(decision.reason_codes),
            "source_errors": list(decision.source_errors),
            "all_search_failed": (
                "all_search_failed" in decision.reason_codes
                or "all_search_failed" in decision.source_errors
            ),
            "cached_candidates": [
                self._candidate_to_dict(item) for item in candidates
            ],
            "mode": config.mode,
            "append_tmdb_id": config.append_tmdb_id,
            "uncertain_policy": config.uncertain_policy,
            "auto_threshold": config.auto_threshold,
            "min_margin": config.min_margin,
            "directory": directory.to_dict(),
            "raw_year": hints.year,
            "manual_local": bool(manual_local),
        }

        self._prune_cache(identities, self.IDENTITY_MAX)
        self._save_data("naming_identity_v1", identities)

    @staticmethod
    def _candidate_to_dict(candidate: Any) -> Dict[str, Any]:
        if isinstance(candidate, naming.MetadataCandidate):
            return candidate.to_dict()
        if hasattr(candidate, "candidate") and isinstance(candidate.candidate, naming.MetadataCandidate):
            return candidate.candidate.to_dict()
        return {}

    def _decision(
        self,
        status: str,
        raw_title: str,
        hints: naming.TitleHints,
        candidate: Optional[naming.MetadataCandidate] = None,
        source: str = "",
        media_id: str = "",
        media_type: str = "unknown",
        score: int = 0,
        margin: int = 0,
        reason_codes: Tuple[str, ...] = (),
        source_errors: Tuple[str, ...] = (),
        blocked_reason: str = "",
        final_root: Optional[str] = None,
        final_prefix: Optional[str] = None,
        candidate_key: str = "",
        target_library: str = "",
    ) -> NamingDecision:
        if final_root is None:
            if status in {"auto_external", "review"} and candidate is not None:
                final_root = naming.format_root_name(hints, candidate)
            else:
                final_root = naming.format_root_name(hints, None)

        if final_prefix is None:
            final_prefix = naming.format_file_prefix(final_root)
            final_prefix = naming.format_file_prefix(final_prefix)

        return NamingDecision(
            status=status,
            raw_title=raw_title,
            local_title=hints.local_title,
            final_root=final_root,
            final_prefix=final_prefix,
            source=(candidate.source if candidate is not None else source),
            media_id=(candidate.media_id if candidate is not None else media_id),
            media_type=(candidate.media_type if candidate is not None else media_type),
            score=score,
            margin=margin,
            candidate_key=(candidate.key if candidate is not None else candidate_key),
            reason_codes=tuple(reason_codes),
            source_errors=tuple(source_errors),
            blocked_reason=blocked_reason,
            target_library=target_library,
        )
