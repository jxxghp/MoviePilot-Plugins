"""音乐合集识别与覆盖判定的纯函数。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

CoverageState = Literal["confirmed", "probable", "missing"]

_COLLECTION_TERMS = re.compile(
    r"(?:discograph(?:y|ies)|collection|complete(?:\s+(?:album|studio|works?))?|"
    r"anthology|box\s*set|\bpack\b|大合集|合集|全集|全套|全碟|全收[录錄]|全[专專]辑|"
    r"全作品|作品集|[历歷]年[专專]辑|[录錄]音室[专專]辑|无损合集|無損合集)",
    re.IGNORECASE,
)
_TOKEN_SPLIT = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
_YEAR_RANGE = re.compile(r"((?:19|20)\d{2})\s*[-–—~至]\s*((?:19|20)\d{2})")


@dataclass(frozen=True, slots=True)
class Work:
    """参与合集覆盖判断的最小官方作品投影。"""

    media_id: str
    title: str
    year: int | None = None
    album_type: str = "Album"
    aliases: tuple[str, ...] = ()


def normalize_text(value: str) -> str:
    """保守归一跨语言标题，不擅自转换简繁或译名。"""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(token for token in _TOKEN_SPLIT.split(text) if token)


def useful_artist_aliases(primary: str, aliases: Iterable[str]) -> list[str]:
    """去掉会污染全站搜索的过短拉丁昵称并稳定去重。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in (primary, *aliases):
        name = str(raw or "").strip()
        normalized = normalize_text(name)
        if not normalized or normalized in seen:
            continue
        if (
            name.isascii()
            and name.replace(" ", "").isalpha()
            and len(normalized.replace(" ", "")) < 5
        ):
            continue
        seen.add(normalized)
        result.append(name)
    return result


def collection_search_terms(primary: str, aliases: Iterable[str]) -> list[str]:
    """生成少量高信噪比的艺术家合集搜索词。"""
    names = useful_artist_aliases(primary, aliases)
    if not names:
        return []
    directed = (
        f"{names[0]} 合集"
        if re.search(r"[\u3400-\u9fff]", names[0])
        else f"{names[0]} discography"
    )
    terms = [names[0], *names[1:3], directed]
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))[:4]


def is_collection_resource(
    title: str, description: str, aliases: Iterable[str]
) -> bool:
    """合集词和艺术家别名必须同时命中，避免普通单专辑混入。"""
    text = f"{title or ''} {description or ''}"
    normalized = normalize_text(text)

    def artist_matches(alias: str) -> bool:
        key = normalize_text(alias)
        if not key:
            return False
        if re.search(r"[\u3400-\u9fff]", key):
            return key in normalized
        return f" {key} " in f" {normalized} "

    return bool(_COLLECTION_TERMS.search(text)) and any(
        artist_matches(alias) for alias in aliases
    )


def evaluate_coverage(
    works: Iterable[Work],
    file_paths: Iterable[str],
    resource_title: str,
    resource_description: str = "",
    folder_name: str = "",
) -> dict:
    """内部路径才能确认覆盖，标题与年份范围只记为“可能覆盖”。"""
    work_list = list(works)
    paths = list(file_paths)
    resource_text = normalize_text(
        f"{resource_title} {resource_description} {folder_name}"
    )
    aliases_by_work: dict[str, tuple[str, ...]] = {}
    owners: dict[str, set[str]] = {}
    for work in work_list:
        aliases = tuple(
            value
            for value in dict.fromkeys(
                normalize_text(item) for item in (work.title, *work.aliases)
            )
            if len(value) >= 2
        )
        aliases_by_work[work.media_id] = aliases
        for alias in aliases:
            owners.setdefault(alias, set()).add(work.media_id)
    ranges = [
        (int(match.group(1)), int(match.group(2)))
        for match in _YEAR_RANGE.finditer(
            f"{resource_title} {resource_description} {folder_name}"
        )
    ]
    rows: list[dict] = []
    for work in work_list:
        identity = {
            "media_id": work.media_id,
            "title": work.title,
            "year": work.year,
            "album_type": work.album_type,
        }
        aliases = aliases_by_work[work.media_id]

        def path_matches(
            path: str, target: Work = work, target_aliases: tuple = aliases
        ) -> bool:
            # 合集最外层名称与音频曲名不能证明 Album/EP 整张包含；只看子目录。
            parts = PurePosixPath(path.replace("\\", "/")).parts
            parts = parts[1:] if len(parts) > 1 else parts
            names = parts[:-1] if target.album_type != "Single" else parts
            for name in names:
                stem = PurePosixPath(name).stem if name == parts[-1] else name
                cleaned = re.sub(r"^\s*\d{1,3}[ ._-]+", "", stem)
                cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", cleaned)
                normalized = normalize_text(cleaned)
                for alias in target_aliases:
                    if normalized != alias:
                        continue
                    owners_for_alias = owners.get(alias, set())
                    if len(owners_for_alias) == 1:
                        return True
                    same_year = [
                        candidate
                        for candidate in work_list
                        if candidate.media_id in owners_for_alias
                        and candidate.year == target.year
                    ]
                    if target.year and str(target.year) in name and len(same_year) == 1:
                        return True
            return False

        matched_path = next(
            (original for original in paths if path_matches(original)),
            None,
        )
        if matched_path:
            rows.append(
                {
                    **identity,
                    "state": "confirmed",
                    "evidence": f"种子路径：{matched_path}",
                }
            )
            continue
        title_match = any(alias in resource_text for alias in aliases)
        year_match = not work.year or str(work.year) in resource_text
        range_match = bool(
            work.year and any(start <= work.year <= end for start, end in ranges)
        )
        if (title_match and year_match) or range_match:
            evidence = "资源标题或描述命中" if title_match else "资源年份范围命中"
            rows.append({**identity, "state": "probable", "evidence": evidence})
        else:
            rows.append({**identity, "state": "missing", "evidence": ""})
    return {
        "folder_name": folder_name,
        "file_count": len(paths),
        "confirmed_count": sum(row["state"] == "confirmed" for row in rows),
        "probable_count": sum(row["state"] == "probable" for row in rows),
        "missing_count": sum(row["state"] == "missing" for row in rows),
        "works": rows,
    }


def work_from_mapping(item: Mapping) -> Work:
    """从 API 音乐作品投影构造覆盖判断对象。"""
    return Work(
        media_id=str(item.get("media_id") or ""),
        title=str(item.get("title") or item.get("album") or ""),
        year=int(item["year"]) if item.get("year") else None,
        album_type=str(item.get("album_type") or "Album"),
        aliases=tuple(str(alias) for alias in item.get("title_aliases") or () if alias),
    )
