import hmac
import asyncio
import inspect
import json
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.chain.media import MediaChain
from app.core.config import settings
from app.core.event import eventmanager
from app.core.meta.words import WordsMatcher
from app.core.metainfo import MetaInfo
from app.db.systemconfig_oper import SystemConfigOper
try:
    from app.helper.llm import LLMHelper
except ImportError:  # MoviePilot 新版已迁移到 app.agent.llm
    from app.agent.llm import LLMHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, MediaType, SystemConfigKey


class AIRecognitionGuess(BaseModel):
    name: str = Field(default="", description="标准化后的影视标题；无法判断时返回空字符串")
    year: str = Field(default="", description="四位年份；无法判断时返回空字符串")
    media_type: str = Field(default="unknown", description="movie、tv 或 unknown")
    season: int = Field(default=0, description="剧集季号，电影填 0")
    episode: int = Field(default=0, description="剧集集号，电影或未知填 0")
    confidence: float = Field(default=0.0, description="0 到 1 之间的置信度")
    reason: str = Field(default="", description="简短说明为什么这样判断")


class IdentifierSuggestion(BaseModel):
    comment: str = Field(default="", description="可选注释，不带 #")
    rule: str = Field(default="", description="一条 MoviePilot 自定义识别词规则")
    confidence: float = Field(default=0.0, description="0 到 1 之间的置信度")
    reason: str = Field(default="", description="为什么建议这条规则")


class IdentifierSuggestionBundle(BaseModel):
    summary: str = Field(default="", description="整体建议摘要")
    suggestions: List[IdentifierSuggestion] = Field(default_factory=list, description="建议规则列表")


class AIRecognizerEnhancer(_PluginBase):
    plugin_name = "AI识别增强"
    plugin_desc = "直接复用 MoviePilot 当前 LLM 配置，在原生识别失败后做本地结构化识别兜底，并交回原生链路继续二次识别。"
    plugin_icon = "https://raw.githubusercontent.com/liuyuexi1987/MoviePilot-Plugins/main/icons/airecognizerenhancer.png"
    plugin_version = "0.1.13"
    plugin_author = "liuyuexi1987"
    plugin_level = 1
    author_url = "https://github.com/liuyuexi1987"
    plugin_config_prefix = "arrecognizerenhancer_"
    plugin_order = 41
    auth_level = 1

    _enabled = False
    _debug = False
    _confidence_threshold = 0.65
    _request_timeout = 25
    _max_retries = 2
    _save_failed_samples = True
    _save_title_only_samples = False
    _max_failed_samples = 200
    _auto_remove_applied_sample = True
    _clear_failed_samples_once = False
    _systemconfig: Optional[SystemConfigOper] = None

    def init_plugin(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._debug = bool(config.get("debug", False))
        self._confidence_threshold = self._safe_float(config.get("confidence_threshold"), 0.65)
        self._request_timeout = self._safe_int(config.get("request_timeout"), 25)
        self._max_retries = max(1, min(5, self._safe_int(config.get("max_retries"), 2)))
        self._save_failed_samples = bool(config.get("save_failed_samples", True))
        self._save_title_only_samples = bool(config.get("save_title_only_samples", False))
        self._max_failed_samples = max(20, min(1000, self._safe_int(config.get("max_failed_samples"), 200)))
        self._auto_remove_applied_sample = bool(config.get("auto_remove_applied_sample", True))
        self._clear_failed_samples_once = bool(config.get("clear_failed_samples_once", False))
        self._systemconfig = SystemConfigOper()
        self._register_events()
        if self._clear_failed_samples_once:
            cleared = self._clear_failed_samples()
            self._clear_failed_samples_once = False
            self.update_config(self._build_config({"clear_failed_samples_once": False}))
            logger.info(f"[AI识别增强] 已按配置清空失败样本 {cleared} 条")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        try:
            eventmanager.disable_event_handler(self.on_chain_name_recognize)
        except Exception:
            pass

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _extract_apikey(request: Request, body: Optional[Dict[str, Any]] = None) -> str:
        header = str(request.headers.get("Authorization") or "").strip()
        if header.lower().startswith("bearer "):
            return header.split(" ", 1)[1].strip()
        if body:
            for key in ("apikey", "api_key", "token"):
                token = str(body.get(key) or "").strip()
                if token:
                    return token
        return str(request.query_params.get("apikey") or request.query_params.get("token") or "").strip()

    def _build_config(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = {
            "enabled": self._enabled,
            "debug": self._debug,
            "confidence_threshold": self._confidence_threshold,
            "request_timeout": self._request_timeout,
            "max_retries": self._max_retries,
            "save_failed_samples": self._save_failed_samples,
            "save_title_only_samples": self._save_title_only_samples,
            "max_failed_samples": self._max_failed_samples,
            "auto_remove_applied_sample": self._auto_remove_applied_sample,
            "clear_failed_samples_once": self._clear_failed_samples_once,
        }
        if overrides:
            config.update(overrides)
        return config

    def _check_api_access(self, request: Request, body: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        expected = str(getattr(settings, "API_TOKEN", "") or "").strip()
        if not expected:
            return False, "服务端未配置 API Token"
        actual = self._extract_apikey(request, body)
        if not hmac.compare_digest(actual, expected):
            return False, "API Token 无效"
        return True, ""

    def _register_events(self) -> None:
        try:
            eventmanager.register(ChainEventType.NameRecognize)(self.on_chain_name_recognize)
            if self._enabled:
                eventmanager.enable_event_handler(self.on_chain_name_recognize)
            else:
                eventmanager.disable_event_handler(self.on_chain_name_recognize)
        except Exception as exc:
            logger.warning(f"[AI识别增强] 注册链式识别事件失败: {exc}")

    @staticmethod
    def _extract_title_path(event_data: Any) -> Tuple[str, str]:
        title = ""
        path = ""
        if isinstance(event_data, dict):
            title = (
                event_data.get("title")
                or event_data.get("name")
                or event_data.get("org_string")
                or ""
            )
            path = (
                event_data.get("path")
                or event_data.get("file_path")
                or event_data.get("org_string")
                or ""
            )
        else:
            title = (
                getattr(event_data, "title", "")
                or getattr(event_data, "name", "")
                or getattr(event_data, "org_string", "")
                or ""
            )
            path = (
                getattr(event_data, "path", "")
                or getattr(event_data, "file_path", "")
                or getattr(event_data, "org_string", "")
                or ""
            )
        return str(title or "").strip(), str(path or "").strip()

    @staticmethod
    def _extract_provenance(event_data: Any) -> Dict[str, str]:
        """Extract lightweight provenance metadata from event data for sample recording."""
        source_plugin = ""
        if isinstance(event_data, dict):
            source_plugin = str(event_data.get("source_plugin") or "").strip()
        else:
            source_plugin = str(getattr(event_data, "source_plugin", "") or "").strip()

        title = ""
        path = ""
        if isinstance(event_data, dict):
            title = str(event_data.get("title") or event_data.get("name") or event_data.get("org_string") or "").strip()
            path = str(event_data.get("path") or event_data.get("file_path") or event_data.get("org_string") or "").strip()
        else:
            title = str(getattr(event_data, "title", "") or getattr(event_data, "name", "") or getattr(event_data, "org_string", "") or "").strip()
            path = str(getattr(event_data, "path", "") or getattr(event_data, "file_path", "") or getattr(event_data, "org_string", "") or "").strip()

        is_path_backed = bool(path) and path != title and "/" in path
        return {
            "sample_source_kind": "path_backed" if is_path_backed else "title_only",
            "sample_source_plugin": source_plugin,
        }

    def _build_meta_hint(self, raw_text: str) -> Dict[str, Any]:
        try:
            meta = MetaInfo(raw_text)
        except Exception:
            return {}
        return {
            "name": getattr(meta, "name", "") or "",
            "year": getattr(meta, "year", "") or "",
            "type": getattr(getattr(meta, "type", None), "to_agent", lambda: None)() or "",
            "season": getattr(meta, "begin_season", None) or 0,
            "episode": getattr(meta, "begin_episode", None) or 0,
            "org_string": getattr(meta, "org_string", "") or "",
        }

    @staticmethod
    def _clean_guess_name(name: str) -> str:
        text = str(name or "").strip()
        if not text:
            return ""
        text = text.split("/")[0].strip().replace(".", " ")
        return " ".join(text.split())

    def _normalize_guess(self, guess: AIRecognitionGuess) -> AIRecognitionGuess:
        name = self._clean_guess_name(guess.name)
        year = str(guess.year or "").strip()
        if not (len(year) == 4 and year.isdigit()):
            year = ""
        media_type = str(guess.media_type or "unknown").strip().lower()
        if media_type not in {"movie", "tv"}:
            media_type = "unknown"
        season = max(0, self._safe_int(guess.season, 0))
        episode = max(0, self._safe_int(guess.episode, 0))
        confidence = min(1.0, max(0.0, self._safe_float(guess.confidence, 0.0)))
        reason = str(guess.reason or "").strip()
        return AIRecognitionGuess(
            name=name,
            year=year,
            media_type=media_type,
            season=season,
            episode=episode,
            confidence=confidence,
            reason=reason,
        )

    def _sample_path(self) -> Path:
        return self.get_data_path() / "failed_samples.jsonl"

    def _llm_errors_path(self) -> Path:
        return self.get_data_path() / "llm_errors.jsonl"

    def _failed_sample_cap(self) -> int:
        return max(20, min(1000, self._safe_int(self._max_failed_samples, 200)))

    @staticmethod
    def _sample_identity(payload: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "title": str(payload.get("title") or "").strip(),
                "path": str(payload.get("path") or "").strip(),
                "reason": str(payload.get("reason") or "").strip(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _write_failed_samples(self, rows: List[Dict[str, Any]]) -> None:
        sample_path = self._sample_path()
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        filtered = [row for row in rows if not str(row.get("reason") or "").startswith("llm_error:")]
        trimmed = filtered[-self._max_failed_samples:]
        with sample_path.open("w", encoding="utf-8") as f:
            for row in trimmed:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _record_failed_sample(self, payload: Dict[str, Any]) -> None:
        if not self._save_failed_samples:
            return
        try:
            rows = self._read_failed_samples(limit=1000)
            rows.reverse()
            identity = self._sample_identity(payload)
            filtered = [row for row in rows if self._sample_identity(row) != identity]
            filtered.append(payload)
            self._write_failed_samples(filtered)
        except Exception as exc:
            logger.warning(f"[AI识别增强] 写入失败样本失败: {exc}")

    def _record_llm_error(self, title: str, path: str, meta_hint: Dict[str, Any], error: Any, provenance: Optional[Dict[str, str]] = None) -> None:
        try:
            error_path = self._llm_errors_path()
            error_path.parent.mkdir(parents=True, exist_ok=True)
            provenance = provenance or {}
            entry = {
                "title": title,
                "path": path,
                "meta_hint": meta_hint,
                "reason": f"llm_error:{error}",
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "sample_source_kind": provenance.get("sample_source_kind", "unknown"),
                "sample_source_plugin": provenance.get("sample_source_plugin", ""),
            }
            existing = self._read_llm_errors(limit=1000)
            existing.reverse()
            new_identity = json.dumps({"title": title, "path": path, "reason": entry["reason"]}, ensure_ascii=False, sort_keys=True)
            existing = [row for row in existing if json.dumps(
                {"title": row.get("title"), "path": row.get("path"), "reason": row.get("reason")},
                ensure_ascii=False, sort_keys=True,
            ) != new_identity]
            existing.append(entry)
            trimmed = existing[-self._max_failed_samples:]
            with error_path.open("w", encoding="utf-8") as f:
                for row in trimmed:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning(f"[AI识别增强] 写入 LLM 错误诊断记录失败: {exc}")

    def _read_llm_errors(self, limit: int = 20) -> List[Dict[str, Any]]:
        error_path = self._llm_errors_path()
        if not error_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with error_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning(f"[AI识别增强] 读取 LLM 错误诊断记录失败: {exc}")
            return []
        if limit > 0:
            rows = rows[-limit:]
        rows.reverse()
        return rows

    def _clear_llm_errors(self) -> int:
        rows = self._read_llm_errors(limit=10000)
        error_path = self._llm_errors_path()
        if error_path.exists():
            error_path.unlink()
        return len(rows)

    def _read_failed_samples(self, limit: int = 20) -> List[Dict[str, Any]]:
        sample_path = self._sample_path()
        if not sample_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with sample_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning(f"[AI识别增强] 读取失败样本失败: {exc}")
            return []
        if limit > 0:
            rows = rows[-limit:]
        rows.reverse()
        return rows

    def _clear_failed_samples(self) -> int:
        rows = self._read_failed_samples(limit=1000)
        sample_path = self._sample_path()
        if sample_path.exists():
            sample_path.unlink()
        return len(rows)

    def _remove_failed_sample(self, sample_index: Optional[Any], limit: int = 1000) -> Dict[str, Any]:
        rows = self._read_failed_samples(limit=max(1, min(limit, 1000)))
        if not rows:
            return {"removed": False, "message": "暂无失败样本", "removed_count": 0}
        index = self._safe_int(sample_index, 0)
        if index < 0:
            index = 0
        if index >= len(rows):
            return {
                "removed": False,
                "message": f"失败样本索引超出范围，当前共有 {len(rows)} 条",
                "removed_count": 0,
            }
        removed_sample = dict(rows[index] or {})
        del rows[index]
        if rows:
            rows.reverse()
            self._write_failed_samples(rows)
        else:
            self._clear_failed_samples()
        return {
            "removed": True,
            "message": "success",
            "removed_count": 1,
            "remaining_count": len(rows),
            "removed_sample": removed_sample,
            "removed_sample_index": index,
        }

    def _remove_failed_samples(self, sample_indexes: List[Any], limit: int = 1000) -> Dict[str, Any]:
        rows = self._read_failed_samples(limit=max(1, min(limit, 1000)))
        if not rows:
            return {"removed": False, "message": "暂无失败样本", "removed_count": 0, "remaining_count": 0}
        normalized_indexes = sorted(
            {self._safe_int(index, -1) for index in (sample_indexes or []) if self._safe_int(index, -1) >= 0},
            reverse=True,
        )
        valid_indexes = [index for index in normalized_indexes if index < len(rows)]
        if not valid_indexes:
            return {
                "removed": False,
                "message": "没有可移除的有效样本索引",
                "removed_count": 0,
                "remaining_count": len(rows),
            }
        removed_samples: List[Dict[str, Any]] = []
        for index in valid_indexes:
            removed_samples.append(dict(rows[index] or {}))
            del rows[index]
        if rows:
            rows.reverse()
            self._write_failed_samples(rows)
        else:
            self._clear_failed_samples()
        removed_samples.reverse()
        return {
            "removed": True,
            "message": "success",
            "removed_count": len(valid_indexes),
            "remaining_count": len(rows),
            "removed_sample_indexes": sorted(valid_indexes),
            "removed_samples": removed_samples,
        }

    def _resolve_failed_sample(
        self,
        sample_index: Optional[Any] = None,
        limit: int = 100,
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]], str]:
        samples = self._read_failed_samples(limit=max(1, min(limit, self._failed_sample_cap())))
        if not samples:
            return None, None, "暂无失败样本"
        index = self._safe_int(sample_index, 0)
        if index < 0:
            index = 0
        if index >= len(samples):
            return None, None, f"失败样本索引超出范围，当前共有 {len(samples)} 条"
        row = dict(samples[index] or {})
        row["sample_index"] = index
        return index, row, ""

    def _select_failed_sample_indexes(
        self,
        sample_indexes: Optional[List[Any]] = None,
        limit: int = 10,
        pool_limit: int = 0,
    ) -> Tuple[List[int], List[Dict[str, Any]], str]:
        if pool_limit <= 0:
            pool_limit = self._failed_sample_cap()
        current_samples = self._inject_sample_indices(
            self._read_failed_samples(limit=max(1, min(pool_limit, self._failed_sample_cap())))
        )
        if not current_samples:
            return [], [], "暂无失败样本"
        if isinstance(sample_indexes, list) and sample_indexes:
            selected_indexes: List[int] = []
            seen = set()
            for raw in sample_indexes:
                idx = self._safe_int(raw, -1)
                if idx < 0 or idx >= len(current_samples) or idx in seen:
                    continue
                seen.add(idx)
                selected_indexes.append(idx)
        else:
            selected_indexes = [int(sample.get("sample_index", 0)) for sample in current_samples[: max(1, min(limit, 50))]]
        if not selected_indexes:
            return [], current_samples, "没有可处理的有效样本索引"
        return selected_indexes, current_samples, ""

    def _inject_sample_indices(self, samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        indexed: List[Dict[str, Any]] = []
        for idx, sample in enumerate(samples):
            row = dict(sample or {})
            row["sample_index"] = idx
            indexed.append(row)
        return indexed

    def _summarize_sample(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        sample = dict(sample or {})
        guess = sample.get("guess") or {}
        verified = sample.get("verified_media_info") or {}
        inferred_target = {
            "name": verified.get("title") or guess.get("name") or "",
            "year": verified.get("year") or guess.get("year") or "",
            "media_type": self._normalize_media_type(verified.get("type") or guess.get("media_type")),
            "season": self._safe_int(guess.get("season"), 0),
            "episode": self._safe_int(guess.get("episode"), 0),
            "tmdb_id": self._safe_int(verified.get("tmdb_id"), 0),
        }
        return {
            "sample_index": sample.get("sample_index"),
            "title": sample.get("title"),
            "path": sample.get("path"),
            "reason": sample.get("reason"),
            "sample_source_kind": sample.get("sample_source_kind", ""),
            "sample_source_plugin": sample.get("sample_source_plugin", ""),
            "guess_name": guess.get("name"),
            "guess_confidence": self._safe_float(guess.get("confidence"), 0.0),
            "verified_title": verified.get("title"),
            "verified_year": verified.get("year"),
            "verified_tmdb_id": verified.get("tmdb_id"),
            "inferred_target": inferred_target,
            "can_auto_suggest": bool(inferred_target["name"]),
        }

    def _target_from_sample(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        summary = self._summarize_sample(sample)
        return summary.get("inferred_target") or {}

    @staticmethod
    def _normalize_reason_tag(reason: Any) -> str:
        text = str(reason or "").strip()
        if not text:
            return "unknown"
        if ":" in text:
            return text.split(":", 1)[0].strip() or "unknown"
        return text

    @staticmethod
    def _sample_group_key(summary: Dict[str, Any]) -> str:
        target = summary.get("inferred_target") or {}
        title = (
            str(target.get("name") or "").strip()
            or str(summary.get("verified_title") or "").strip()
            or str(summary.get("guess_name") or "").strip()
            or str(summary.get("title") or "").strip()
        )
        media_type = str(target.get("media_type") or "unknown").strip().lower()
        season = int(target.get("season") or 0)
        episode = int(target.get("episode") or 0)
        return json.dumps(
            {
                "title": title.lower(),
                "media_type": media_type,
                "season": season,
                "episode": episode,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _sample_display_name(summary: Dict[str, Any]) -> str:
        target = summary.get("inferred_target") or {}
        title = (
            str(target.get("name") or "").strip()
            or str(summary.get("verified_title") or "").strip()
            or str(summary.get("guess_name") or "").strip()
            or str(summary.get("title") or "").strip()
        )
        if not title:
            return "未命名样本"
        media_type = str(target.get("media_type") or "").strip().lower()
        season = int(target.get("season") or 0)
        episode = int(target.get("episode") or 0)
        suffix = ""
        if media_type == "tv" and (season or episode):
            suffix = f" S{season:02d}E{episode:02d}"
        return f"{title}{suffix}"

    def _build_sample_insights(self, samples: List[Dict[str, Any]], top: int = 10) -> Dict[str, Any]:
        summaries = [self._summarize_sample(sample) for sample in samples]
        reason_counter = Counter()
        title_counter = Counter()
        group_counter = Counter()
        for summary in summaries:
            reason_counter[self._normalize_reason_tag(summary.get("reason"))] += 1
            title_counter[self._sample_display_name(summary)] += 1
            group_counter[self._sample_group_key(summary)] += 1

        actionable: List[Dict[str, Any]] = []
        for summary in summaries:
            duplicate_count = group_counter[self._sample_group_key(summary)]
            priority_reasons: List[str] = []
            score = 0
            if duplicate_count >= 2:
                score += min(duplicate_count, 5)
                priority_reasons.append(f"同类样本重复出现 {duplicate_count} 次")
            if summary.get("verified_tmdb_id"):
                score += 3
                priority_reasons.append("已有 TMDB 命中")
            if summary.get("can_auto_suggest"):
                score += 2
                priority_reasons.append("可直接生成识别词")
            confidence = self._safe_float(summary.get("guess_confidence"), 0.0)
            if 0 < confidence < self._confidence_threshold:
                gap = round(self._confidence_threshold - confidence, 2)
                score += 1
                priority_reasons.append(f"距注入阈值还差 {gap}")
            row = dict(summary)
            row["duplicate_count"] = duplicate_count
            row["priority_score"] = score
            row["priority_reasons"] = priority_reasons
            actionable.append(row)

        actionable.sort(
            key=lambda item: (
                -int(item.get("priority_score") or 0),
                -int(item.get("duplicate_count") or 0),
                -self._safe_float(item.get("guess_confidence"), 0.0),
                int(item.get("sample_index") or 0),
            )
        )

        repeated_groups = [
            {"title": name, "count": count}
            for name, count in title_counter.most_common(top)
            if count >= 2
        ]

        return {
            "total_count": len(summaries),
            "reason_counts": [
                {"reason": reason, "count": count}
                for reason, count in reason_counter.most_common(top)
            ],
            "top_titles": [
                {"title": title, "count": count}
                for title, count in title_counter.most_common(top)
            ],
            "repeated_groups": repeated_groups,
            "priority_samples": actionable[:top],
        }

    def _render_sample_brief(self, samples: List[Dict[str, Any]], top: int = 5) -> str:
        summaries = [self._summarize_sample(sample) for sample in samples[: max(1, min(top, 20))]]
        if not summaries:
            return "当前没有失败样本。"
        lines = [f"失败样本 {len(samples)} 条，展示前 {len(summaries)} 条："]
        for summary in summaries:
            label = self._sample_display_name(summary)
            confidence = round(self._safe_float(summary.get("guess_confidence"), 0.0), 2)
            can_suggest = "可建议" if summary.get("can_auto_suggest") else "需人工"
            source_tag = "有路径" if summary.get("sample_source_kind") == "path_backed" else "仅标题"
            source_plugin = summary.get("sample_source_plugin") or ""
            source_info = f" | {source_tag}" + (f" ({source_plugin})" if source_plugin else "")
            lines.append(f"{summary.get('sample_index')}. {label} | 置信度 {confidence} | {can_suggest}{source_info}")
        lines.append("下一步：可直接调用批量建议或批量复查接口。")
        return "\n".join(lines)

    @staticmethod
    def _render_batch_results_brief(
        action_name: str,
        requested_count: int,
        success_count: int,
        failed_count: int,
        results: List[Dict[str, Any]],
    ) -> str:
        lines = [f"{action_name}：共处理 {requested_count} 条，成功 {success_count}，失败 {failed_count}。"]
        for item in results[:10]:
            idx = item.get("sample_index")
            if item.get("success"):
                label = (
                    ((item.get("source_sample") or {}).get("title"))
                    or ((item.get("target") or {}).get("name"))
                    or "样本"
                )
                lines.append(f"{idx}. 成功 | {label}")
            else:
                lines.append(f"{idx}. 失败 | {item.get('message', '未知错误')}")
        return "\n".join(lines)

    def _build_body_from_sample(self, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
        body = dict(body or {})
        title = str(body.get("title") or "").strip()
        path = str(body.get("path") or "").strip()
        sample_requested = body.get("use_latest_sample") or body.get("sample_index") is not None
        if title or path:
            return body, None, ""
        if not sample_requested:
            return body, None, ""

        sample_index, sample, message = self._resolve_failed_sample(body.get("sample_index"), limit=100)
        if not sample:
            return body, None, message
        body["title"] = str(sample.get("title") or "").strip()
        body["path"] = str(sample.get("path") or "").strip()
        verified = sample.get("verified_media_info") or {}
        guess = sample.get("guess") or {}
        if not body.get("desired_name"):
            body["desired_name"] = verified.get("title") or guess.get("name") or ""
        if not body.get("desired_year"):
            body["desired_year"] = verified.get("year") or guess.get("year") or ""
        if not body.get("desired_media_type"):
            body["desired_media_type"] = self._normalize_media_type(
                verified.get("type") or guess.get("media_type")
            )
        if body.get("desired_season") is None:
            body["desired_season"] = guess.get("season") or 0
        if body.get("desired_episode") is None:
            body["desired_episode"] = guess.get("episode") or 0
        if body.get("desired_tmdb_id") is None:
            body["desired_tmdb_id"] = verified.get("tmdb_id") or 0
        body["sample_index"] = sample_index
        return body, sample, ""

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是 MoviePilot 的影视文件名识别增强助手。

你的任务不是搜索 TMDB，也不是编造结果，而是根据文件名、路径和已有解析提示，尽量提炼出更适合 MoviePilot 二次识别的结构化信息。

规则：
1. 只依据输入内容推断，不要臆造不存在的信息。
2. 如果不确定，请返回空标题，并把 media_type 设为 unknown，confidence 降低。
3. title/name 只保留作品名，不要包含分辨率、制作组、音频编码、网盘标记等噪音。
4. year 只有在比较确定时才给四位年份。
5. 电影 season/episode 必须为 0。
6. 剧集如果能确定季集就填写，否则保持 0。
7. media_type 只能是 movie、tv、unknown。
8. confidence 范围为 0 到 1。
""",
                ),
                (
                    "human",
                    """原始标题：
{title}

原始路径：
{path}

MoviePilot 当前基础解析提示：
{meta_hint}
""",
                ),
            ]
        )

    def _build_identifier_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是 MoviePilot 自定义识别词规则助手。

你的任务是根据错误标题、当前解析结果和目标结果，生成尽量窄作用域、可直接用于 MoviePilot CustomIdentifiers 的规则。

支持格式只有四种：
1. 屏蔽词
2. 替换词：被替换词 => 替换词
3. 集偏移：前定位词 <> 后定位词 >> EP±N
4. 组合规则：被替换词 => 替换词 && 前定位词 <> 后定位词 >> EP±N

硬性要求：
1. 运算符两侧必须保留空格： => 、 <> 、 >> 、 &&
2. 优先生成窄作用域规则，尽量带发布组、年份、季集、分辨率等锚点
3. 不要生成过宽的裸屏蔽词，比如 1080p、WEB-DL、字幕
4. 如果需要强制绑 TMDB，可使用 {{[tmdbid=xxx;type=tv/movies;s=1;e=14]}} 这种替换词
5. comment 不带 #，rule 里不要再包 markdown 或代码块
6. 如果没有把握，请返回空 suggestions
""",
                ),
                (
                    "human",
                    """原始标题：
{title}

原始路径：
{path}

MoviePilot 当前基础解析：
{meta_hint}

AI 识别增强结果：
{guess}

二次校验到的媒体信息摘要：
{verified_summary}

希望修正成的目标结果：
{target}
""",
                ),
            ]
        )

    @staticmethod
    def _run_async_compatible(value: Any) -> Any:
        """
        兼容 MoviePilot 新版 `LLMHelper.get_llm()` 的异步返回。
        在同步上下文直接 asyncio.run；如果当前线程已有事件循环，则开一个短线程执行。
        """
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)

        result: Dict[str, Any] = {}
        error: Dict[str, BaseException] = {}

        def _worker() -> None:
            try:
                result["value"] = asyncio.run(value)
            except BaseException as exc:  # noqa: BLE001
                error["exc"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    def _get_llm(self):
        llm = LLMHelper.get_llm(streaming=False)
        return self._run_async_compatible(llm)

    def _invoke_llm(self, title: str, path: str) -> AIRecognitionGuess:
        raw_text = path or title
        meta_hint = self._build_meta_hint(raw_text)
        llm = self._get_llm()
        prompt = self._build_prompt()
        chain = (
            prompt
            | llm.with_structured_output(AIRecognitionGuess).with_retry(stop_after_attempt=self._max_retries)
        )
        result: AIRecognitionGuess = chain.invoke(
            {
                "title": title,
                "path": path,
                "meta_hint": meta_hint,
            },
            config={"configurable": {"timeout": self._request_timeout}},
        )
        return self._normalize_guess(result)

    @staticmethod
    def _normalize_media_type(value: Any) -> str:
        if value == MediaType.MOVIE:
            return "movie"
        if value == MediaType.TV:
            return "tv"
        text = str(value or "").strip().lower()
        if text in {"movie", "movies", "电影"}:
            return "movie"
        if text in {"tv", "电视剧", "剧集"}:
            return "tv"
        return "unknown"

    def _build_target(self, body: Dict[str, Any], result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = body or {}
        result = result or {}
        guess = result.get("guess") or {}
        verified = result.get("verified_media_info") or {}
        verified_type = self._normalize_media_type(verified.get("type"))
        target = {
            "name": str(body.get("desired_name") or verified.get("title") or guess.get("name") or "").strip(),
            "year": str(body.get("desired_year") or verified.get("year") or guess.get("year") or "").strip(),
            "media_type": self._normalize_media_type(
                body.get("desired_media_type") or verified_type or guess.get("media_type")
            ),
            "season": self._safe_int(
                body.get("desired_season"),
                self._safe_int(guess.get("season"), 0),
            ),
            "episode": self._safe_int(
                body.get("desired_episode"),
                self._safe_int(guess.get("episode"), 0),
            ),
            "tmdb_id": self._safe_int(body.get("desired_tmdb_id") or verified.get("tmdb_id"), 0),
        }
        if len(target["year"]) != 4 or not target["year"].isdigit():
            target["year"] = ""
        return target

    @staticmethod
    def _compact_verified_summary(verified: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        verified = verified or {}
        return {
            "title": verified.get("title"),
            "year": verified.get("year"),
            "type": verified.get("type"),
            "tmdb_id": verified.get("tmdb_id"),
            "title_year": verified.get("title_year"),
            "season_years": verified.get("season_years"),
            "seasons": verified.get("seasons"),
            "names": (verified.get("names") or [])[:8],
        }

    @staticmethod
    def _normalize_identifier_line(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    def _validate_identifier_rule(self, rule: str) -> bool:
        rule = self._normalize_identifier_line(rule)
        if not rule or rule.startswith("#"):
            return False
        if " => " in rule and " && " in rule and " >> " in rule and " <> " in rule:
            return True
        if " => " in rule:
            return True
        if " >> " in rule and " <> " in rule:
            return True
        return len(rule) >= 4

    def _enrich_identifier_rule(self, rule: str, target: Dict[str, Any]) -> str:
        rule = self._normalize_identifier_line(rule)
        target_name = str((target or {}).get("name") or "").strip()
        if not target_name or " => " not in rule:
            return rule
        left, right = rule.split(" => ", 1)
        suffix = ""
        replace_part = right
        if " && " in right:
            replace_part, extra = right.split(" && ", 1)
            suffix = f" && {extra}"
        if replace_part.startswith("{["):
            replace_part = f"{target_name}{replace_part}"
        return f"{left} => {replace_part}{suffix}"

    @staticmethod
    def _clean_comment_line(comment: str) -> str:
        text = str(comment or "").strip()
        if not text:
            return ""
        return f"#{text.lstrip('#').strip()}"

    def _preview_custom_words(self, title: str, custom_words: List[str], target: Dict[str, Any]) -> Dict[str, Any]:
        prepared_title, apply_words = WordsMatcher().prepare(title, custom_words=custom_words)
        meta = MetaInfo(title=title, custom_words=custom_words)
        preview = {
            "prepared_title": prepared_title,
            "applied_words": apply_words or [],
            "applied": bool(apply_words),
            "name": getattr(meta, "name", "") or "",
            "year": getattr(meta, "year", "") or "",
            "media_type": self._normalize_media_type(getattr(meta, "type", None)),
            "season": getattr(meta, "begin_season", None) or 0,
            "episode": getattr(meta, "begin_episode", None) or 0,
        }
        if target:
            matched = True
            if target.get("name"):
                matched = matched and (preview["name"].strip().lower() == str(target["name"]).strip().lower())
            if target.get("year"):
                matched = matched and (preview["year"] == target["year"])
            if target.get("media_type") and target.get("media_type") != "unknown":
                matched = matched and (preview["media_type"] == target["media_type"])
            if target.get("season"):
                matched = matched and (preview["season"] == target["season"])
            if target.get("episode"):
                matched = matched and (preview["episode"] == target["episode"])
            preview["matched_target"] = matched
        return preview

    def _preview_identifier_rule(self, title: str, rule: str, target: Dict[str, Any]) -> Dict[str, Any]:
        preview = self._preview_custom_words(title=title, custom_words=[rule], target=target)
        preview["applied"] = rule in (preview.get("applied_words") or [])
        return preview

    def _preview_current_identifiers(self, title: str, target: Dict[str, Any]) -> Dict[str, Any]:
        custom_words = self._get_custom_identifiers()
        preview = self._preview_custom_words(title=title, custom_words=custom_words, target=target)
        preview["custom_identifier_count"] = len(custom_words)
        preview["applied_count"] = len(preview.get("applied_words") or [])
        return preview

    @staticmethod
    def _match_recognize_result_to_target(result: Dict[str, Any], target: Dict[str, Any]) -> bool:
        if not target:
            return bool(result.get("success"))
        guess = result.get("guess") or {}
        matched = True
        if target.get("name"):
            matched = matched and (str(guess.get("name") or "").strip().lower() == str(target.get("name") or "").strip().lower())
        if target.get("year"):
            matched = matched and (str(guess.get("year") or "") == str(target.get("year") or ""))
        if target.get("media_type") and target.get("media_type") != "unknown":
            matched = matched and (str(guess.get("media_type") or "unknown") == str(target.get("media_type") or "unknown"))
        if target.get("season"):
            matched = matched and (int(guess.get("season") or 0) == int(target.get("season") or 0))
        if target.get("episode"):
            matched = matched and (int(guess.get("episode") or 0) == int(target.get("episode") or 0))
        return bool(result.get("success")) and matched

    def _replay_failed_sample(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(body or {})
        sample_index, sample, message = self._resolve_failed_sample(
            body.get("sample_index"),
            limit=1000,
        )
        if not sample:
            return {"success": False, "message": message}
        title = str(sample.get("title") or "").strip()
        path = str(sample.get("path") or "").strip()
        target = self._target_from_sample(sample)
        identifier_preview = self._preview_current_identifiers(title=title, target=target)
        recognize_result = self._recognize(title=title, path=path, record_failed_sample=False)
        resolved_by_identifiers = bool(identifier_preview.get("applied")) and bool(identifier_preview.get("matched_target"))
        resolved_by_recognizer = self._match_recognize_result_to_target(recognize_result, target)
        resolved = resolved_by_identifiers or resolved_by_recognizer
        removal_result = None
        if resolved and bool(body.get("remove_if_resolved")):
            removal_result = self._remove_failed_sample(sample_index, limit=1000)
        return {
            "success": True,
            "message": "success",
            "data": {
                "source_sample_index": sample_index,
                "source_sample": sample,
                "target": target,
                "identifier_preview": identifier_preview,
                "recognize_result": recognize_result,
                "resolved_by_identifiers": resolved_by_identifiers,
                "resolved_by_recognizer": resolved_by_recognizer,
                "resolved": resolved,
                "sample_removed": bool(removal_result and removal_result.get("removed")),
                "sample_removal_result": removal_result,
            },
        }

    def _replay_failed_samples(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(body or {})
        limit = max(1, min(self._safe_int(body.get("limit"), 10), 50))
        selected_indexes, _, message = self._select_failed_sample_indexes(
            sample_indexes=body.get("sample_indexes"),
            limit=limit,
            pool_limit=self._failed_sample_cap(),
        )
        if not selected_indexes:
            return {"success": False, "message": message}

        replay_results: List[Dict[str, Any]] = []
        resolved_indexes: List[int] = []
        for sample_index in selected_indexes:
            replay = self._replay_failed_sample(
                {
                    "sample_index": sample_index,
                    "remove_if_resolved": False,
                }
            )
            if not replay.get("success"):
                replay_results.append(
                    {
                        "sample_index": sample_index,
                        "success": False,
                        "message": replay.get("message", "复查失败"),
                    }
                )
                continue
            data = replay.get("data") or {}
            replay_results.append(
                {
                    "sample_index": sample_index,
                    "success": True,
                    "resolved": bool(data.get("resolved")),
                    "resolved_by_identifiers": bool(data.get("resolved_by_identifiers")),
                    "resolved_by_recognizer": bool(data.get("resolved_by_recognizer")),
                    "source_sample": data.get("source_sample"),
                    "target": data.get("target"),
                    "identifier_preview": data.get("identifier_preview"),
                    "recognize_result": data.get("recognize_result"),
                }
            )
            if data.get("resolved"):
                resolved_indexes.append(sample_index)

        removal_result = None
        if body.get("remove_if_resolved") and resolved_indexes:
            removal_result = self._remove_failed_samples(resolved_indexes, limit=1000)

        success_count = sum(1 for item in replay_results if item.get("success"))
        resolved_count = sum(1 for item in replay_results if item.get("resolved"))
        unresolved_count = success_count - resolved_count
        failed_count = len(replay_results) - success_count
        return {
            "success": True,
            "message": "success",
            "data": {
                "requested_count": len(selected_indexes),
                "success_count": success_count,
                "resolved_count": resolved_count,
                "unresolved_count": unresolved_count,
                "failed_count": failed_count,
                "sample_removed_count": int((removal_result or {}).get("removed_count") or 0),
                "sample_removal_result": removal_result,
                "results": replay_results,
            },
        }

    def _suggest_identifiers_for_failed_samples(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(body or {})
        limit = max(1, min(self._safe_int(body.get("limit"), 5), 20))
        selected_indexes, _, message = self._select_failed_sample_indexes(
            sample_indexes=body.get("sample_indexes"),
            limit=limit,
            pool_limit=self._failed_sample_cap(),
        )
        if not selected_indexes:
            return {"success": False, "message": message}

        results: List[Dict[str, Any]] = []
        success_count = 0
        for sample_index in selected_indexes:
            suggest_body = dict(body)
            suggest_body.pop("sample_indexes", None)
            suggest_body["sample_index"] = sample_index
            suggest_body["use_latest_sample"] = False
            suggested = self._suggest_identifiers(suggest_body)
            if suggested.get("success"):
                success_count += 1
                data = suggested.get("data") or {}
                results.append(
                    {
                        "sample_index": sample_index,
                        "success": True,
                        "summary": data.get("summary"),
                        "source_sample": data.get("source_sample"),
                        "target": data.get("target"),
                        "suggestions": data.get("suggestions") or [],
                    }
                )
            else:
                results.append(
                    {
                        "sample_index": sample_index,
                        "success": False,
                        "message": suggested.get("message", "建议生成失败"),
                        "data": suggested.get("data"),
                    }
                )
        return {
            "success": True,
            "message": "success",
            "data": {
                "requested_count": len(selected_indexes),
                "success_count": success_count,
                "failed_count": len(selected_indexes) - success_count,
                "brief": self._render_batch_results_brief(
                    action_name="批量建议",
                    requested_count=len(selected_indexes),
                    success_count=success_count,
                    failed_count=len(selected_indexes) - success_count,
                    results=results,
                ),
                "results": results,
            },
        }

    def _apply_suggested_identifier_internal(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(body or {})
        if body.get("title") is None and body.get("path") is None:
            body["use_latest_sample"] = True if body.get("use_latest_sample") is None else body.get("use_latest_sample")
        suggested = self._suggest_identifiers(body)
        if not suggested.get("success"):
            return suggested
        data = suggested.get("data") or {}
        suggestions = data.get("suggestions") or []
        suggestion_index = self._safe_int(body.get("suggestion_index"), 0)
        if suggestion_index < 0:
            suggestion_index = 0
        if suggestion_index >= len(suggestions):
            return {"success": False, "message": f"建议索引超出范围，当前共有 {len(suggestions)} 条"}
        chosen = suggestions[suggestion_index]
        applied = self._append_custom_identifiers(chosen.get("lines") or [])
        should_remove_sample = bool(
            self._auto_remove_applied_sample if body.get("remove_sample") is None else body.get("remove_sample")
        )
        removal_result = None
        source_sample = data.get("source_sample") or {}
        if should_remove_sample and source_sample.get("sample_index") is not None:
            removal_result = self._remove_failed_sample(source_sample.get("sample_index"), limit=1000)
        return {
            "success": True,
            "message": "success",
            "data": {
                "chosen_suggestion": chosen,
                "apply_result": applied,
                "source_sample_index": source_sample.get("sample_index"),
                "source_sample": source_sample,
                "sample_removed": bool(removal_result and removal_result.get("removed")),
                "sample_removal_result": removal_result,
                "target": data.get("target"),
            },
        }

    def _apply_suggested_identifiers_for_failed_samples(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(body or {})
        limit = max(1, min(self._safe_int(body.get("limit"), 5), 20))
        selected_indexes, _, message = self._select_failed_sample_indexes(
            sample_indexes=body.get("sample_indexes"),
            limit=limit,
            pool_limit=self._failed_sample_cap(),
        )
        if not selected_indexes:
            return {"success": False, "message": message}

        results: List[Dict[str, Any]] = []
        success_count = 0
        removable_indexes: List[int] = []
        should_remove_samples = bool(
            self._auto_remove_applied_sample if body.get("remove_sample") is None else body.get("remove_sample")
        )
        for sample_index in selected_indexes:
            apply_body = dict(body)
            apply_body.pop("sample_indexes", None)
            apply_body["sample_index"] = sample_index
            apply_body["use_latest_sample"] = False
            apply_body["remove_sample"] = False
            applied = self._apply_suggested_identifier_internal(apply_body)
            if applied.get("success"):
                success_count += 1
                data = applied.get("data") or {}
                if should_remove_samples:
                    removable_indexes.append(sample_index)
                results.append(
                    {
                        "sample_index": sample_index,
                        "success": True,
                        "source_sample": data.get("source_sample"),
                        "target": data.get("target"),
                        "chosen_suggestion": data.get("chosen_suggestion"),
                        "apply_result": data.get("apply_result"),
                        "sample_removed": False,
                    }
                )
            else:
                results.append(
                    {
                        "sample_index": sample_index,
                        "success": False,
                        "message": applied.get("message", "写入失败"),
                        "data": applied.get("data"),
                    }
                )
        removal_result = None
        if should_remove_samples and removable_indexes:
            removal_result = self._remove_failed_samples(removable_indexes, limit=1000)
            removed_index_set = set((removal_result or {}).get("removed_sample_indexes") or [])
            for item in results:
                if item.get("success"):
                    item["sample_removed"] = item.get("sample_index") in removed_index_set
        return {
            "success": True,
            "message": "success",
            "data": {
                "requested_count": len(selected_indexes),
                "success_count": success_count,
                "failed_count": len(selected_indexes) - success_count,
                "sample_removed_count": int((removal_result or {}).get("removed_count") or 0),
                "sample_removal_result": removal_result,
                "brief": self._render_batch_results_brief(
                    action_name="批量写入",
                    requested_count=len(selected_indexes),
                    success_count=success_count,
                    failed_count=len(selected_indexes) - success_count,
                    results=results,
                ),
                "results": results,
            },
        }

    def _build_exact_identifier_fallback(self, title: str, target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        target_name = str((target or {}).get("name") or "").strip()
        tmdb_id = self._safe_int((target or {}).get("tmdb_id"), 0)
        media_type = self._normalize_media_type((target or {}).get("media_type"))
        if not title or not target_name or not tmdb_id or media_type == "unknown":
            return None
        replace = target_name
        target_year = str((target or {}).get("year") or "").strip()
        if len(target_year) == 4 and target_year.isdigit():
            replace += f".{target_year}"
        replace += f"{{[tmdbid={tmdb_id};type={'tv' if media_type == 'tv' else 'movie'}"
        if media_type == "tv" and self._safe_int(target.get("season"), 0):
            replace += f";s={self._safe_int(target.get('season'), 0)}"
        if media_type == "tv" and self._safe_int(target.get("episode"), 0):
            replace += f";e={self._safe_int(target.get('episode'), 0)}"
        replace += "]}"
        rule = f"{re.escape(title)} => {replace}"
        preview = self._preview_identifier_rule(title=title, rule=rule, target=target)
        if not preview.get("applied"):
            return None
        return {
            "comment": "当 AI 建议无法稳定通过本地预演时，使用精确标题绑定规则直接固定到目标 TMDB 与季集",
            "comment_line": "#当 AI 建议无法稳定通过本地预演时，使用精确标题绑定规则直接固定到目标 TMDB 与季集",
            "rule": rule,
            "confidence": 0.95,
            "reason": "精确匹配当前标题并强制绑定目标 TMDB / 季集，作用域最窄，稳定性最高。",
            "preview": preview,
            "lines": [
                "#当 AI 建议无法稳定通过本地预演时，使用精确标题绑定规则直接固定到目标 TMDB 与季集",
                rule,
            ],
        }

    def _invoke_identifier_llm(
        self,
        title: str,
        path: str,
        result: Dict[str, Any],
        target: Dict[str, Any],
    ) -> IdentifierSuggestionBundle:
        llm = self._get_llm()
        prompt = self._build_identifier_prompt()
        chain = (
            prompt
            | llm.with_structured_output(IdentifierSuggestionBundle).with_retry(
                stop_after_attempt=self._max_retries
            )
        )
        bundle: IdentifierSuggestionBundle = chain.invoke(
            {
                "title": title,
                "path": path,
                "meta_hint": self._build_meta_hint(path or title),
                "guess": result.get("guess") or {},
                "verified_summary": self._compact_verified_summary(result.get("verified_media_info")),
                "target": target,
            },
            config={"configurable": {"timeout": self._request_timeout}},
        )
        return bundle

    def _suggest_identifiers(self, body: Dict[str, Any]) -> Dict[str, Any]:
        body, source_sample, sample_message = self._build_body_from_sample(body)
        if sample_message:
            return {"success": False, "message": sample_message}
        title = str(body.get("title") or "").strip()
        path = str(body.get("path") or "").strip()
        if not title and path:
            title = Path(path).name
        if not title:
            return {"success": False, "message": "标题为空"}

        result = self._recognize(title=title, path=path, record_failed_sample=False)
        target = self._build_target(body, result=result)
        invoke_error = ""
        try:
            bundle = self._invoke_identifier_llm(title=title, path=path, result=result, target=target)
        except Exception as exc:
            bundle = IdentifierSuggestionBundle(
                summary="识别词建议模型暂不可用，已自动回退到精确规则兜底。",
                suggestions=[],
            )
            invoke_error = str(exc)

        cleaned: List[Dict[str, Any]] = []
        for item in bundle.suggestions:
            rule = self._enrich_identifier_rule(item.rule, target=target)
            if not self._validate_identifier_rule(rule):
                continue
            comment_line = self._clean_comment_line(item.comment)
            preview = self._preview_identifier_rule(title=title, rule=rule, target=target)
            if not preview.get("applied"):
                continue
            if target and any(target.values()) and preview.get("matched_target") is False:
                continue
            cleaned.append(
                {
                    "comment": item.comment.strip(),
                    "comment_line": comment_line,
                    "rule": rule,
                    "confidence": min(1.0, max(0.0, self._safe_float(item.confidence, 0.0))),
                    "reason": str(item.reason or "").strip(),
                    "preview": preview,
                    "lines": [line for line in [comment_line, rule] if line],
                }
            )

        if not cleaned:
            fallback = self._build_exact_identifier_fallback(title=title, target=target)
            if fallback:
                if invoke_error:
                    fallback["reason"] = f"{fallback.get('reason', '')} 当前识别词建议模型不可用，已自动切到精确规则兜底。".strip()
                cleaned.append(fallback)

        if not cleaned:
            return {
                "success": False,
                "message": f"识别词建议生成失败: {invoke_error}" if invoke_error else "没有生成可直接使用的识别词规则",
                "data": {
                    "summary": bundle.summary,
                    "target": target,
                    "recognize_result": result,
                },
            }
        return {
            "success": True,
            "message": "success",
            "data": {
                "summary": bundle.summary,
                "source_sample_index": (source_sample or {}).get("sample_index"),
                "source_sample": source_sample,
                "target": target,
                "recognize_result": result,
                "suggestions": cleaned,
            },
        }

    def _get_custom_identifiers(self) -> List[str]:
        if not self._systemconfig:
            self._systemconfig = SystemConfigOper()
        return self._systemconfig.get(SystemConfigKey.CustomIdentifiers) or []

    def _append_custom_identifiers(self, lines: List[str]) -> Dict[str, Any]:
        existing = self._get_custom_identifiers()
        added: List[str] = []
        for line in lines:
            normalized = str(line or "").rstrip()
            if not normalized:
                continue
            if normalized in existing or normalized in added:
                continue
            added.append(normalized)
        if added:
            merged = existing + added
            self._systemconfig.set(SystemConfigKey.CustomIdentifiers, merged)
        return {
            "added": added,
            "added_count": len(added),
            "total_count": len(self._get_custom_identifiers()),
        }

    def _verify_guess(self, title: str, path: str, guess: AIRecognitionGuess) -> Optional[Dict[str, Any]]:
        if not guess.name:
            return None
        try:
            raw_text = path or title or guess.name
            meta = MetaInfo(raw_text)
            meta.name = guess.name
            meta.year = guess.year or None
            meta.begin_season = guess.season or None
            meta.begin_episode = guess.episode or None
            if guess.media_type == "tv" or meta.begin_season or meta.begin_episode:
                meta.type = MediaType.TV
            elif guess.media_type == "movie":
                meta.type = MediaType.MOVIE
            mediainfo = MediaChain().recognize_media(meta=meta, cache=False)
            if not mediainfo:
                return None
            return mediainfo.to_dict()
        except Exception as exc:
            if self._debug:
                logger.warning(f"[AI识别增强] 二次校验失败: {exc}")
            return None

    def _recognize(
        self, title: str, path: str = "", record_failed_sample: bool = True,
        provenance: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        title = str(title or "").strip()
        path = str(path or "").strip()
        if not title and path:
            title = Path(path).name
        if not title:
            return {"success": False, "message": "标题为空"}
        provenance = provenance or {}
        is_title_only = provenance.get("sample_source_kind") == "title_only"
        try:
            guess = self._invoke_llm(title, path)
        except Exception as exc:
            if record_failed_sample:
                if is_title_only and not self._save_title_only_samples:
                    if self._debug:
                        logger.info(f"[AI识别增强] 跳过保存仅标题 LLM 错误: {title} (save_title_only_samples=False)")
                else:
                    self._record_llm_error(title, path, self._build_meta_hint(path or title), exc, provenance=provenance)
            return {"success": False, "message": f"LLM 调用失败: {exc}"}

        verified = self._verify_guess(title, path, guess)
        passed = bool(guess.name and guess.confidence >= self._confidence_threshold)
        if not passed and record_failed_sample:
            if is_title_only and not self._save_title_only_samples:
                if self._debug:
                    logger.info(f"[AI识别增强] 跳过保存仅标题样本: {title} (save_title_only_samples=False)")
            else:
                self._record_failed_sample(
                    {
                        "title": title,
                        "path": path,
                        "meta_hint": self._build_meta_hint(path or title),
                        "guess": guess.model_dump(),
                        "verified_media_info": self._compact_verified_summary(verified),
                        "reason": "low_confidence_or_empty_name",
                        "sample_source_kind": provenance.get("sample_source_kind", "unknown"),
                        "sample_source_plugin": provenance.get("sample_source_plugin", ""),
                    }
                )
        return {
            "success": passed,
            "message": "success" if passed else "识别结果置信度不足，已放弃注入",
            "guess": guess.model_dump(),
            "verified_media_info": verified,
        }

    def on_chain_name_recognize(self, event) -> None:
        if not self._enabled:
            return
        event_data = getattr(event, "event_data", None) or {}
        title, path = self._extract_title_path(event_data)
        if not title and not path:
            return
        provenance = self._extract_provenance(event_data)
        result = self._recognize(title=title, path=path, provenance=provenance)
        if not result.get("success"):
            if self._debug:
                logger.info(f"[AI识别增强] 跳过注入: {title or path} - {result.get('message')}")
            return
        guess = result.get("guess") or {}
        if isinstance(event_data, dict):
            if event_data.get("source_plugin"):
                if self._debug:
                    logger.info(f"[AI识别增强] 已有插件处理识别结果，跳过覆盖: {event_data.get('source_plugin')}")
                return
            event_data["name"] = guess.get("name", "")
            event_data["year"] = guess.get("year", "")
            event_data["season"] = guess.get("season", 0)
            event_data["episode"] = guess.get("episode", 0)
            event_data["source_plugin"] = "AIRecognizerEnhancer"
            event_data["confidence"] = guess.get("confidence", 0)
            event_data["reason"] = guess.get("reason", "")

    async def api_health(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        llm_ready = bool(getattr(settings, "LLM_API_KEY", None))
        return {
            "success": True,
            "data": {
                "plugin_version": self.plugin_version,
                "enabled": self._enabled,
                "llm_ready": llm_ready,
                "llm_provider": getattr(settings, "LLM_PROVIDER", ""),
                "llm_model": getattr(settings, "LLM_MODEL", ""),
                "confidence_threshold": self._confidence_threshold,
                "request_timeout": self._request_timeout,
            },
        }

    async def api_recognize(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        title = str(body.get("title") or "").strip()
        path = str(body.get("path") or "").strip()
        result = self._recognize(title=title, path=path)
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "data": {
                "guess": result.get("guess"),
                "verified_media_info": result.get("verified_media_info"),
            },
        }

    async def api_failed_samples(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        limit = self._safe_int(request.query_params.get("limit"), 20)
        limit = max(1, min(limit, 100))
        samples = self._inject_sample_indices(self._read_failed_samples(limit=limit))
        return {
            "success": True,
            "data": {
                "count": len(samples),
                "samples": samples,
            },
        }

    async def api_sample_worklist(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        limit = self._safe_int(request.query_params.get("limit"), 20)
        limit = max(1, min(limit, 100))
        samples = self._inject_sample_indices(self._read_failed_samples(limit=limit))
        worklist = [self._summarize_sample(sample) for sample in samples]
        return {
            "success": True,
            "data": {
                "count": len(worklist),
                "samples": worklist,
            },
        }

    async def api_sample_insights(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        limit = self._safe_int(request.query_params.get("limit"), 50)
        limit = max(1, min(limit, self._failed_sample_cap()))
        top = self._safe_int(request.query_params.get("top"), 10)
        top = max(1, min(top, 20))
        samples = self._inject_sample_indices(self._read_failed_samples(limit=limit))
        insights = self._build_sample_insights(samples, top=top)
        return {
            "success": True,
            "data": insights,
        }

    async def api_sample_brief(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        limit = self._safe_int(request.query_params.get("limit"), 5)
        limit = max(1, min(limit, 20))
        samples = self._inject_sample_indices(self._read_failed_samples(limit=self._failed_sample_cap()))
        return {
            "success": True,
            "data": {
                "count": len(samples),
                "text": self._render_sample_brief(samples, top=limit),
            },
        }

    async def api_suggest_identifiers(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._suggest_identifiers(body)

    async def api_apply_identifiers(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        identifiers = body.get("identifiers") or []
        if not isinstance(identifiers, list):
            return {"success": False, "message": "identifiers 必须是数组"}
        result = self._append_custom_identifiers([str(line or "") for line in identifiers])
        return {
            "success": True,
            "message": "success",
            "data": result,
        }

    async def api_clear_failed_samples(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        cleared = self._clear_failed_samples()
        return {
            "success": True,
            "message": "success",
            "data": {
                "cleared_count": cleared,
            },
        }

    async def api_llm_errors(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        limit = self._safe_int(request.query_params.get("limit"), 20)
        limit = max(1, min(limit, 100))
        errors = self._read_llm_errors(limit=limit)
        return {
            "success": True,
            "data": {
                "count": len(errors),
                "errors": errors,
            },
        }

    async def api_clear_llm_errors(self, request: Request):
        ok, message = self._check_api_access(request)
        if not ok:
            return {"success": False, "message": message}
        cleared = self._clear_llm_errors()
        return {
            "success": True,
            "message": "success",
            "data": {
                "cleared_count": cleared,
            },
        }

    async def api_remove_failed_sample(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        result = self._remove_failed_sample(body.get("sample_index"), limit=1000)
        if not result.get("removed"):
            return {"success": False, "message": result.get("message", "移除失败"), "data": result}
        return {
            "success": True,
            "message": "success",
            "data": result,
        }

    async def api_replay_failed_sample(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._replay_failed_sample(body)

    async def api_replay_failed_samples(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._replay_failed_samples(body)

    async def api_suggest_identifiers_from_sample(self, request: Request):
        body = await request.json()
        body["use_latest_sample"] = True if body.get("use_latest_sample") is None else body.get("use_latest_sample")
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        if body.get("sample_index") is None and body.get("use_latest_sample") is False:
            body["use_latest_sample"] = True
        return self._suggest_identifiers(body)

    async def api_suggest_identifiers_for_failed_samples(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._suggest_identifiers_for_failed_samples(body)

    async def api_apply_suggested_identifier(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._apply_suggested_identifier_internal(body)

    async def api_apply_suggested_identifiers_for_failed_samples(self, request: Request):
        body = await request.json()
        ok, message = self._check_api_access(request, body)
        if not ok:
            return {"success": False, "message": message}
        if not self._enabled:
            return {"success": False, "message": "插件未启用"}
        return self._apply_suggested_identifiers_for_failed_samples(body)

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/health",
                "endpoint": self.api_health,
                "methods": ["GET"],
                "summary": "检查 AI识别增强 的运行状态",
            },
            {
                "path": "/recognize",
                "endpoint": self.api_recognize,
                "methods": ["POST"],
                "summary": "用当前 LLM 对失败标题做一次本地结构化识别测试",
            },
            {
                "path": "/failed_samples",
                "endpoint": self.api_failed_samples,
                "methods": ["GET"],
                "summary": "查看最近保存的低置信度失败样本",
            },
            {
                "path": "/sample_worklist",
                "endpoint": self.api_sample_worklist,
                "methods": ["GET"],
                "summary": "返回适合智能体使用的失败样本摘要列表",
            },
            {
                "path": "/sample_insights",
                "endpoint": self.api_sample_insights,
                "methods": ["GET"],
                "summary": "汇总失败样本原因、重复问题和优先处理样本",
            },
            {
                "path": "/sample_brief",
                "endpoint": self.api_sample_brief,
                "methods": ["GET"],
                "summary": "返回适合智能体低 token 消费的失败样本精简摘要",
            },
            {
                "path": "/suggest_identifiers",
                "endpoint": self.api_suggest_identifiers,
                "methods": ["POST"],
                "summary": "根据标题和目标结果生成 MoviePilot 自定义识别词建议",
            },
            {
                "path": "/suggest_identifiers_from_sample",
                "endpoint": self.api_suggest_identifiers_from_sample,
                "methods": ["POST"],
                "summary": "直接基于最近失败样本或指定样本生成自定义识别词建议",
            },
            {
                "path": "/suggest_identifiers_for_failed_samples",
                "endpoint": self.api_suggest_identifiers_for_failed_samples,
                "methods": ["POST"],
                "summary": "批量为失败样本生成自定义识别词建议",
            },
            {
                "path": "/apply_identifiers",
                "endpoint": self.api_apply_identifiers,
                "methods": ["POST"],
                "summary": "将确认后的自定义识别词追加写入系统 CustomIdentifiers",
            },
            {
                "path": "/clear_failed_samples",
                "endpoint": self.api_clear_failed_samples,
                "methods": ["POST"],
                "summary": "清空失败样本文件",
            },
            {
                "path": "/llm_errors",
                "endpoint": self.api_llm_errors,
                "methods": ["GET"],
                "summary": "查看 LLM 调用失败的诊断记录",
            },
            {
                "path": "/clear_llm_errors",
                "endpoint": self.api_clear_llm_errors,
                "methods": ["POST"],
                "summary": "清空 LLM 错误诊断记录",
            },
            {
                "path": "/remove_failed_sample",
                "endpoint": self.api_remove_failed_sample,
                "methods": ["POST"],
                "summary": "按索引移除单条失败样本",
            },
            {
                "path": "/replay_failed_sample",
                "endpoint": self.api_replay_failed_sample,
                "methods": ["POST"],
                "summary": "按当前识别词和当前识别器复查某条失败样本，并可在确认修复后自动出队",
            },
            {
                "path": "/replay_failed_samples",
                "endpoint": self.api_replay_failed_samples,
                "methods": ["POST"],
                "summary": "批量复查失败样本，并可在确认修复后批量出队",
            },
            {
                "path": "/apply_suggested_identifier",
                "endpoint": self.api_apply_suggested_identifier,
                "methods": ["POST"],
                "summary": "直接把最近失败样本或指定样本生成的建议规则写入 CustomIdentifiers，并按需移除该样本",
            },
            {
                "path": "/apply_suggested_identifiers_for_failed_samples",
                "endpoint": self.api_apply_suggested_identifiers_for_failed_samples,
                "methods": ["POST"],
                "summary": "批量把失败样本生成的建议规则写入 CustomIdentifiers，并按需移除对应样本",
            },
        ]

    def get_page(self) -> List[dict]:
        llm_ready = bool(getattr(settings, "LLM_API_KEY", None))
        failed_samples_count = len(self._read_failed_samples(limit=self._failed_sample_cap()))
        llm_errors_count = len(self._read_llm_errors(limit=self._max_failed_samples))
        custom_identifiers_count = len(self._get_custom_identifiers())
        llm_provider = getattr(settings, "LLM_PROVIDER", "—")
        llm_model = getattr(settings, "LLM_MODEL", "—")

        def stat_card(title: str, value: Any, subtitle: str = "") -> dict:
            content = [
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis mb-1"},
                    "text": title,
                },
                {
                    "component": "div",
                    "props": {"class": "text-h6 font-weight-bold"},
                    "text": str(value),
                },
            ]
            if subtitle:
                content.append(
                    {
                        "component": "div",
                        "props": {"class": "text-caption text-medium-emphasis mt-1"},
                        "text": subtitle,
                    }
                )
            return {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "pa-4 h-100"},
                "content": content,
            }

        return [
            {
                "component": "VContainer",
                "props": {"fluid": True, "class": "pa-0"},
                "content": [
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "class": "mb-4",
                            "title": "本地 LLM 识别兜底",
                            "text": "复用 MoviePilot 当前 LLM 配置，在原生识别失败时做结构化兜底，并把结果交回 MoviePilot 继续二次识别。",
                        },
                    },
                    {
                        "component": "VRow",
                        "props": {"dense": True, "class": "mb-2"},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 6, "md": 2},
                                "content": [stat_card("当前状态", "已启用" if self._enabled else "未启用")],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 6, "md": 2},
                                "content": [stat_card("LLM 可用", "是" if llm_ready else "否", f"{llm_provider} / {llm_model}")],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 6, "md": 3},
                                "content": [stat_card("可处理失败样本", f"{failed_samples_count} 条", f"上限 {self._max_failed_samples} 条")],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 6, "md": 2},
                                "content": [stat_card("LLM 错误", f"{llm_errors_count} 条", "诊断记录")],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 6, "md": 3},
                                "content": [stat_card("自定义识别词", f"{custom_identifiers_count} 条", "系统 CustomIdentifiers")],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "props": {"dense": True},
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 12},
                                "content": [
                                    {
                                        "component": "VCard",
                                        "props": {"variant": "outlined", "class": "pa-4 h-100"},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {"class": "text-subtitle-1 font-weight-bold mb-2"},
                                                "text": "识别词闭环",
                                            },
                                            {
                                                "component": "div",
                                                "props": {"class": "text-body-2 text-medium-emphasis"},
                                                "text": "失败样本可生成 CustomIdentifiers 建议，并按需追加写入系统配置。",
                                            },
                                            {
                                                "component": "div",
                                                "props": {"class": "text-caption text-medium-emphasis mt-3"},
                                                "text": f"写入后自动移除样本：{'是' if self._auto_remove_applied_sample else '否'}",
                                            },
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ]

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vuetify", None

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        failed_samples_count = len(self._read_failed_samples(limit=self._failed_sample_cap()))
        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "当前版本已改为直接复用 MoviePilot 当前启用的 LLM 配置，在原生识别失败后做本地结构化兜底。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": f"当前累计 {failed_samples_count} 条失败样本。如需重置噪音数据，请勾选下方“一次性清空”开关后点击保存。该操作只清空失败样本，不会删除已写入的 CustomIdentifiers。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用 AI识别增强"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "debug", "label": "调试模式"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "save_failed_samples", "label": "保存低置信度样本"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "save_title_only_samples",
                                            "label": "保存仅标题样本",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "confidence_threshold",
                                            "label": "置信度阈值",
                                            "type": "number",
                                            "hint": "低于该值的结果不注入 MoviePilot，默认 0.65",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "request_timeout",
                                            "label": "LLM 请求超时（秒）",
                                            "type": "number",
                                            "hint": "默认 25 秒",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_retries",
                                            "label": "结构化输出重试次数",
                                            "type": "number",
                                            "hint": "默认 2 次",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_failed_samples",
                                            "label": "失败样本保留上限",
                                            "type": "number",
                                            "hint": "默认保留最近 200 条，并对重复样本自动去重",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "clear_failed_samples_once",
                                            "label": "保存时清空失败样本（一次性）",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "auto_remove_applied_sample",
                                            "label": "写入识别词后自动移除对应失败样本",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
        return form, {
            "enabled": False,
            "debug": False,
            "confidence_threshold": 0.65,
            "request_timeout": 25,
            "max_retries": 2,
            "save_failed_samples": True,
            "save_title_only_samples": False,
            "max_failed_samples": 200,
            "auto_remove_applied_sample": True,
            "clear_failed_samples_once": False,
        }
