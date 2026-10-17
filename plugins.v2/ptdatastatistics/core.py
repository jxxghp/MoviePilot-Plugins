"""PT 数据统计的纯计算逻辑。

本模块不依赖 MoviePilot 运行时，便于对日期口径、十二大匹配与汇总结果做单元测试。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

TWELVE_SITES: tuple[dict[str, Any], ...] = (
    {
        "key": "mteam",
        "name": "馒头",
        "aliases": ("馒头", "mteam", "m-team"),
    },
    {
        "key": "audiences",
        "name": "观众",
        "aliases": ("观众", "audiences", "audience"),
    },
    {
        "key": "rainbow",
        "name": "彩虹岛",
        "aliases": ("彩虹岛", "rainbow", "chdbits"),
    },
    {
        "key": "hhan",
        "name": "憨憨",
        "aliases": ("憨憨", "hhan", "hhanclub"),
    },
    {
        "key": "spring",
        "name": "春天",
        "aliases": ("春天", "spring", "spring-sunday"),
    },
    {
        "key": "sky",
        "name": "天空",
        "aliases": ("天空", "hdsky", "skyey"),
    },
    {
        "key": "pter",
        "name": "猫站",
        "aliases": ("猫站", "pter", "pterclub"),
    },
    {
        "key": "home",
        "name": "家园",
        "aliases": ("家园", "hdhome"),
    },
    {
        "key": "friends",
        "name": "朋友",
        "aliases": ("朋友", "friend", "friends"),
    },
    {
        "key": "queen",
        "name": "皇后",
        "aliases": ("皇后", "open.cd", "opencd"),
    },
    {
        "key": "ttg",
        "name": "听听歌",
        "aliases": ("听听歌", "ttg", "totheglory"),
    },
    {
        "key": "ourbits",
        "name": "我堡",
        "aliases": ("我堡", "ourbits", "ob"),
    },
)


GIB = 1024 ** 3

from .site_rule_adapter import bundled_retirement_rules


DEFAULT_RETIREMENT_RULES: dict[str, Mapping[str, Any]] = bundled_retirement_rules()
MTEAM_RETIREMENT_RULE = DEFAULT_RETIREMENT_RULES["馒头"]


def as_int(value: Any) -> int:
    """把宿主可能返回的整数、浮点或字符串统一成非异常整数。"""

    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def as_float(value: Any) -> float | None:
    """把可选数值转换为浮点数，无法转换时返回 ``None``。"""

    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def as_text(value: Any) -> str:
    """把可选值转换为可存储文本。"""

    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def previous_day(day: str) -> str | None:
    """返回严格的前一服务器日期；非法日期不产生跨日猜测。"""

    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    return (parsed - timedelta(days=1)).isoformat()


def compute_daily_delta(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """按严格相邻日期计算站点日增量。

    缺少前一日、前一日失败或日期不连续时均视为基线不足。累计值下降通常表示
    站点重置了统计口径，负差值按零展示但保留 ``counter_reset`` 标记。
    """

    current_day = as_text(current.get("updated_day"))
    expected_previous = previous_day(current_day)
    if not previous or not expected_previous:
        return {
            "baseline_valid": False,
            "daily_upload": 0,
            "daily_download": 0,
            "counter_reset": False,
        }
    if as_text(previous.get("updated_day")) != expected_previous:
        return {
            "baseline_valid": False,
            "daily_upload": 0,
            "daily_download": 0,
            "counter_reset": False,
        }
    if as_text(previous.get("err_msg")).strip():
        return {
            "baseline_valid": False,
            "daily_upload": 0,
            "daily_download": 0,
            "counter_reset": False,
        }

    upload_delta = as_int(current.get("upload")) - as_int(previous.get("upload"))
    download_delta = as_int(current.get("download")) - as_int(previous.get("download"))
    return {
        "baseline_valid": True,
        "daily_upload": max(0, upload_delta),
        "daily_download": max(0, download_delta),
        "counter_reset": upload_delta < 0 or download_delta < 0,
    }


def build_hourly_traffic(
    snapshots: Iterable[Mapping[str, Any]],
    selected_day: str,
) -> dict[str, Any]:
    """把 MP 的站点累计采样转换为自然小时增量。

    MP 可能在同一天保存多次站点用户数据。这里按站点和采样时间排序，只使用
    同一自然日内相邻成功采样的累计值差额，并把增量记入后一条采样所在小时。
    当天首条记录不会与前一天的记录相减，避免把整日增量误记为某个小时的
    流量；累计值回退时相应差额按零处理。
    """

    points = [
        {"hour": f"{hour:02d}:00", "upload": 0, "download": 0, "samples": 0}
        for hour in range(24)
    ]
    grouped: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = {}

    for snapshot in snapshots:
        if as_text(snapshot.get("err_msg")).strip():
            continue
        day = as_text(snapshot.get("updated_day"))[:10]
        time_text = as_text(snapshot.get("updated_time")).strip()
        source_text = as_text(snapshot.get("source_updated_at")).strip()
        parsed = None
        for candidate in (source_text, f"{day} {time_text}".strip(), day):
            if not candidate:
                continue
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if parsed is None or parsed.date().isoformat() > selected_day:
            continue
        key = as_text(snapshot.get("domain")) or as_text(snapshot.get("site_id"))
        if not key:
            continue
        grouped.setdefault(key, []).append((parsed, snapshot))

    valid_samples = 0
    for values in grouped.values():
        values.sort(key=lambda item: item[0])
        previous: tuple[datetime, Mapping[str, Any]] | None = None
        for timestamp, snapshot in values:
            timestamp_day = timestamp.date().isoformat()
            if timestamp_day != selected_day:
                continue
            if previous is not None:
                upload_delta = as_int(snapshot.get("upload")) - as_int(previous[1].get("upload"))
                download_delta = as_int(snapshot.get("download")) - as_int(previous[1].get("download"))
                bucket = points[timestamp.hour]
                bucket["upload"] += max(0, upload_delta)
                bucket["download"] += max(0, download_delta)
                bucket["samples"] += 1
                valid_samples += 1
            previous = (timestamp, snapshot)

    return {
        "baseline_valid": valid_samples > 0,
        "sample_count": valid_samples,
        "points": points,
    }


def estimate_bonus_hourly(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> float | None:
    """根据最近两次成功的 MP 每日快照估算每小时魔力增长。

    该值只用于展示趋势。样本不足、时间无效或累计魔力下降（通常表示兑换、
    消费或站点调整）时不猜测结果。
    """

    if not previous:
        return None
    current_bonus = as_float(current.get("bonus"))
    previous_bonus = as_float(previous.get("bonus"))
    if current_bonus is None or previous_bonus is None or current_bonus < previous_bonus:
        return None

    def snapshot_time(snapshot: Mapping[str, Any]) -> datetime | None:
        source_value = as_text(snapshot.get("source_updated_at")).strip()
        candidates = [source_value]
        day = as_text(snapshot.get("updated_day")).strip()
        updated_time = as_text(snapshot.get("updated_time")).strip()
        if day:
            candidates.append(f"{day} {updated_time}".strip())
            candidates.append(day)
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                continue
        return None

    current_time = snapshot_time(current)
    previous_time = snapshot_time(previous)
    if current_time is None or previous_time is None:
        return None
    elapsed_hours = (current_time - previous_time).total_seconds() / 3600
    if elapsed_hours <= 0:
        return None
    return round((current_bonus - previous_bonus) / elapsed_hours, 2)


def normalize_identity(value: Any) -> str:
    """移除展示差异，生成站点名称的匹配字符串。"""

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", as_text(value).casefold())


def _match_named_rule(
    values: Any,
    rules: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """按站点名、域名、来源标识和别名匹配规则。"""

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        values = (values,)
    identities = {
        identity
        for value in values
        if (identity := normalize_identity(value))
    }
    if not identities:
        return None

    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for name, rule in rules.items():
        aliases = (
            name,
            rule.get("site"),
            *(rule.get("aliases") or ()),
            *(rule.get("domains") or ()),
        )
        rule_identities = {
            identity
            for alias in aliases
            if (identity := normalize_identity(alias))
        }
        if identities.intersection(rule_identities):
            return rule
        for identity in identities:
            for alias in rule_identities:
                # 短英文缩写容易误命中域名；中文双字站点和四位以上标识可安全模糊匹配。
                safe_length = len(alias) >= 4 or any("\u4e00" <= character <= "\u9fff" for character in alias)
                if safe_length and (alias in identity or identity in alias):
                    candidates.append((len(alias), rule))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _match_level_index(
    current_level: Any, levels: Iterable[Mapping[str, Any]], *, exact_only: bool = False
) -> int:
    """匹配 MP 等级文本，区分完整等级名和省略展示后缀的短文本。"""

    identity = normalize_identity(current_level)
    if not identity:
        return -1
    contained: list[tuple[int, int]] = []
    prefixes: list[tuple[int, int]] = []
    partial: list[tuple[int, int]] = []
    for index, level in enumerate(levels):
        level_identities = [
            normalize_identity(value)
            for value in (level.get("name"), *(level.get("aliases") or ()))
            if normalize_identity(value)
        ]
        for level_identity in level_identities:
            if level_identity == identity:
                return index
            if exact_only:
                continue
            if level_identity in identity:
                # MP 文本包含完整等级名时，选最具体的名称，避免 Power User 命中 User。
                contained.append((len(level_identity), index))
            elif level_identity.startswith(identity):
                # MP 仅返回英文部分时，优先对应前缀，避免 User 命中 Ultimate User。
                prefixes.append((len(level_identity), index))
            elif identity in level_identity:
                partial.append((len(level_identity), index))
    if contained:
        return max(contained, key=lambda item: (item[0], -item[1]))[1]
    if prefixes:
        return min(prefixes)[1]
    return min(partial, default=(0, -1))[1]


def match_twelve_site(
    definition: Mapping[str, Any],
    configured_site: Mapping[str, Any],
) -> bool:
    """只按 MoviePilot 站点名称和别名判断十二大站点。"""

    name = normalize_identity(configured_site.get("name") or configured_site.get("site_name"))
    for candidate in definition.get("aliases") or ():
        normalized = normalize_identity(candidate)
        if normalized and (normalized in name or name == normalized):
            return True
    return False


def build_twelve_progress(
    configured_sites: Iterable[Mapping[str, Any]],
    latest_by_site_id: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """构建十二节点时间线；用户可见结果不包含站点域名。"""

    sites = list(configured_sites)
    items: list[dict[str, Any]] = []
    joined_count = 0

    for definition in TWELVE_SITES:
        matched = next(
            (
                site
                for site in sites
                if match_twelve_site(definition, site)
            ),
            None,
        )
        site_id = matched.get("id") if matched else None
        snapshot = latest_by_site_id.get(site_id) if isinstance(site_id, int) else None
        has_data = bool(snapshot and not as_text(snapshot.get("err_msg")).strip())
        if has_data:
            state = "joined"
            joined_count += 1
        elif matched:
            state = "waiting"
        else:
            state = "missing"
        items.append(
            {
                "key": definition["key"],
                "name": definition["name"],
                "state": state,
                "site_id": site_id,
                "join_at": as_text(snapshot.get("join_at")) if snapshot else "",
            }
        )

    def joined_at_sort_value(value: Any) -> float:
        """使用 MP 保存的完整加入时间排序，同日加入时也保持真实先后。"""

        raw = as_text(value).strip()
        if not raw:
            return float("inf")
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OSError):
            return float("inf")

    items.sort(
        key=lambda item: (
            item["state"] != "joined",
            joined_at_sort_value(item.get("join_at")),
            as_text(item.get("name")),
        )
    )

    return {
        "joined": joined_count,
        "total": len(TWELVE_SITES),
        "percent": round(joined_count * 100 / len(TWELVE_SITES)),
        "items": items,
    }


def _requirement_missing(
    level: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    include_alternatives: bool = True,
) -> list[str]:
    """返回当前数据距离指定等级门槛仍缺少的条件。"""

    missing: list[str] = []
    joined = as_text(snapshot.get("join_at"))[:10]
    current_day = as_text(snapshot.get("updated_day"))[:10]
    minimum_days = max(as_int(level.get("min_join_days")), 0)
    if minimum_days:
        try:
            actual_days = max(
                (date.fromisoformat(current_day) - date.fromisoformat(joined)).days,
                0,
            )
        except (TypeError, ValueError):
            actual_days = 0
        strict_days = bool(level.get("min_join_days_strict"))
        if actual_days <= minimum_days if strict_days else actual_days < minimum_days:
            required_days = minimum_days + (1 if strict_days else 0)
            missing.append(f"账号时间剩余 {required_days - actual_days} 天")
    numeric_fields = (
        ("min_upload", "upload", "上传"),
        ("min_download", "download", "下载"),
        ("min_bonus", "bonus", "魔力"),
        ("min_seeding_points", "seeding_points", "做种积分"),
        ("min_seeding", "seeding", "做种数"),
        ("min_seeding_size", "seeding_size", "做种体积"),
        ("min_torrent_uploads", "torrent_uploads", "发布数"),
        ("min_average_seeding_time_days", "average_seeding_time_days", "平均做种时间"),
    )
    for rule_key, data_key, label in numeric_fields:
        target = as_float(level.get(rule_key)) or 0
        current_value = as_float(snapshot.get(data_key))
        if target and data_key in {
            "seeding_points",
            "torrent_uploads",
            "average_seeding_time_days",
        } and current_value is None:
            missing.append(f"{label}数据未提供")
            continue
        current = current_value or 0
        strict = bool(level.get(f"{rule_key}_strict"))
        if current <= target if strict else current < target:
            difference = target - current
            if data_key in {"upload", "download", "seeding_size"}:
                if strict and difference <= 0:
                    missing.append(f"{label}需大于 {format_bytes(target)}")
                else:
                    missing.append(f"{label}剩余 {format_bytes(difference)}")
            else:
                if strict and difference <= 0:
                    formatted_target = (
                        f"{int(target):,}"
                        if target.is_integer()
                        else f"{target:,.2f}".rstrip("0").rstrip(".")
                    )
                    missing.append(f"{label}需大于 {formatted_target}")
                    continue
                formatted_difference = (
                    f"{int(difference):,}"
                    if difference.is_integer()
                    else f"{difference:,.2f}".rstrip("0").rstrip(".")
                )
                suffix = " 天" if data_key == "average_seeding_time_days" else ""
                missing.append(f"{label}剩余 {formatted_difference}{suffix}")
    target_ratio = as_float(level.get("min_ratio"))
    current_ratio = as_float(snapshot.get("ratio"))
    ratio_strict = bool(level.get("min_ratio_strict"))
    ratio_missing = False
    if target_ratio is not None:
        ratio_missing = current_ratio is None or (
            current_ratio <= target_ratio
            if ratio_strict
            else current_ratio < target_ratio
        )
    if target_ratio is not None and ratio_missing:
        comparator = "大于" if ratio_strict else "达到"
        missing.append(f"分享率需{comparator} {target_ratio:g}")
    for requirement in level.get("unsupported_requirements") or ():
        label = as_text(requirement.get("label")) if isinstance(requirement, Mapping) else "其他要求"
        missing.append(f"{label}数据未提供")
    if include_alternatives:
        alternative_missing = [
            _requirement_missing(option, snapshot, include_alternatives=False)
            for option in level.get("alternatives") or ()
            if isinstance(option, Mapping)
        ]
        if alternative_missing and all(option for option in alternative_missing):
            descriptions = ["、".join(option) for option in alternative_missing]
            missing.append(f"任选条件未达成：{'；或 '.join(descriptions)}")
    return missing


def _with_derived_upload(level: Mapping[str, Any]) -> dict[str, Any]:
    """根据下载量与分享率补全等级隐含的最低上传量。"""

    normalized = dict(level)
    explicit_upload = max(as_int(level.get("min_upload")), 0)
    minimum_download = max(as_int(level.get("min_download")), 0)
    minimum_ratio = as_float(level.get("min_ratio"))
    if explicit_upload or not minimum_download or minimum_ratio is None or minimum_ratio <= 0:
        return normalized
    normalized["min_upload"] = int(round(minimum_download * minimum_ratio))
    normalized["min_upload_strict"] = bool(
        level.get("min_download_strict") or level.get("min_ratio_strict")
    )
    return normalized


def _eligible_date(join_at: Any, minimum_days: Any, strict: bool = False) -> str:
    """按加入日期和等级账号天数计算最早达标日期。"""

    try:
        joined = date.fromisoformat(as_text(join_at)[:10])
        days = max(as_int(minimum_days), 0)
    except (TypeError, ValueError):
        return ""
    return (joined + timedelta(days=days + (1 if strict and days else 0))).isoformat()


def _seeding_points_eta(
    requirement: Mapping[str, Any], site: Mapping[str, Any]
) -> dict[str, Any]:
    target = as_float(requirement.get("min_seeding_points"))
    current = site.get("seeding_points")
    rate = site.get("seeding_points_hourly")
    hours = None
    days = None
    eta_date = ""
    if target and current is not None and rate and rate > 0:
        required = target + (1 if requirement.get("min_seeding_points_strict") else 0)
        remaining = max(required - current, 0)
        hours = int(math.floor(remaining / rate))
        days = int(math.ceil(remaining / rate / 24))
        try:
            eta_date = (
                date.fromisoformat(as_text(site.get("updated_day"))[:10])
                + timedelta(days=days)
            ).isoformat()
        except (TypeError, ValueError):
            pass
    return {
        "seeding_points_eta_hours": hours,
        "seeding_points_eta_days": days,
        "seeding_points_eta_date": eta_date,
    }


def build_retirement_progress(
    snapshots: Iterable[Mapping[str, Any]],
    rules_by_name: Mapping[str, Mapping[str, Any]] | None = None,
    wealthy_retirement_sites: Iterable[Any] = (),
) -> dict[str, Any]:
    """构建全部站点升级与养老进度。

    MoviePilot 只提供当前等级和账户数值。找不到明确规则时必须返回
    ``rule_missing``，不能根据其它站点或等级名称猜测门槛。
    """

    source_rules = (
        DEFAULT_RETIREMENT_RULES if rules_by_name is None else rules_by_name
    )
    manually_wealthy = {
        identity
        for value in wealthy_retirement_sites
        if (identity := normalize_identity(value))
    }
    sites: list[dict[str, Any]] = []
    counts = {
        "retired": 0,
        "wealthy_retired": 0,
        "upgrading": 0,
        "rule_missing": 0,
    }
    for snapshot in snapshots:
        manual_candidates = (
            snapshot.get("domain"),
            snapshot.get("site_id"),
            snapshot.get("site_name"),
        )
        forced_wealthy = any(
            normalize_identity(value) in manually_wealthy
            for value in manual_candidates
            if normalize_identity(value)
        )
        base = {
            "site_id": snapshot.get("site_id"),
            "domain": as_text(snapshot.get("domain")).casefold(),
            "site_name": as_text(snapshot.get("site_name")),
            "site_priority": snapshot.get("site_priority"),
            "current_level": as_text(snapshot.get("user_level")),
            "next_level": "",
            "retirement_level": "",
            "status": "rule_missing",
            "is_vip": False,
            "wealthy_retirement_manual": forced_wealthy,
            "join_at": as_text(snapshot.get("join_at")),
            "upload": as_int(snapshot.get("upload")),
            "download": as_int(snapshot.get("download")),
            "ratio": as_float(snapshot.get("ratio")),
            "bonus": as_float(snapshot.get("bonus")),
            "seeding_points": as_float(snapshot.get("seeding_points")),
            "estimated_bonus_hourly": as_float(
                snapshot.get("estimated_bonus_hourly")
            ),
            "seeding_points_hourly": as_float(
                snapshot.get("seeding_points_hourly")
            ),
            "seeding": as_int(snapshot.get("seeding")),
            "seeding_size": as_int(snapshot.get("seeding_size")),
            "torrent_uploads": as_float(snapshot.get("torrent_uploads")),
            "average_seeding_time_days": as_float(snapshot.get("average_seeding_time_days")),
            "updated_day": as_text(snapshot.get("updated_day")),
            "levels_remaining": None,
            "route": [],
        }
        match_values = (snapshot.get("site_name"), snapshot.get("domain"))
        custom_rules = {
            name: candidate
            for name, candidate in source_rules.items()
            if candidate.get("_custom_rule")
        }
        rule = _match_named_rule(match_values, custom_rules)
        if not rule:
            builtin_rules = {
                name: candidate
                for name, candidate in source_rules.items()
                if not candidate.get("_custom_rule")
            }
            rule = _match_named_rule(match_values, builtin_rules)
        raw_levels = list(rule.get("levels") or []) if rule else []
        vip_levels = list(rule.get("vip_levels") or []) if rule else []
        retirement_name = as_text(rule.get("retirement_level")) if rule else ""
        vip_index = _match_level_index(base["current_level"], vip_levels)
        if not raw_levels:
            if forced_wealthy or vip_index >= 0:
                counts["wealthy_retired"] += 1
                sites.append(
                    {
                        **base,
                        "status": "wealthy_retired",
                        "is_vip": vip_index >= 0,
                        "levels_remaining": 0,
                    }
                )
                continue
            sites.append(base)
            counts["rule_missing"] += 1
            continue

        current_index = _match_level_index(base["current_level"], raw_levels)
        retirement_index = _match_level_index(retirement_name, raw_levels, exact_only=True)
        if retirement_name and retirement_index < 0:
            sites.append({**base, "retirement_level": retirement_name})
            counts["rule_missing"] += 1
            continue
        if retirement_index >= 0:
            retirement_name = as_text(raw_levels[retirement_index].get("name"))

        route: list[dict[str, Any]] = []
        for index, raw_level in enumerate(raw_levels):
            level = _with_derived_upload(raw_level)
            level_name = as_text(level.get("name"))
            points_eta = _seeding_points_eta(level, base)
            alternatives = [
                {**option, **_seeding_points_eta(option, base)}
                for option in level.get("alternatives") or []
            ]
            route.append(
                {
                    "name": level_name,
                    "aliases": list(level.get("aliases") or []),
                    "description": as_text(level.get("description")),
                    "min_join_days": max(as_int(level.get("min_join_days")), 0),
                    "min_join_days_strict": bool(level.get("min_join_days_strict")),
                    "min_upload": max(as_int(level.get("min_upload")), 0),
                    "min_upload_strict": bool(level.get("min_upload_strict")),
                    "min_download": max(as_int(level.get("min_download")), 0),
                    "min_download_strict": bool(level.get("min_download_strict")),
                    "min_ratio": as_float(level.get("min_ratio")),
                    "min_ratio_strict": bool(level.get("min_ratio_strict")),
                    "min_bonus": as_float(level.get("min_bonus")),
                    "min_bonus_strict": bool(level.get("min_bonus_strict")),
                    "min_seeding_points": as_float(level.get("min_seeding_points")),
                    "min_seeding_points_strict": bool(level.get("min_seeding_points_strict")),
                    **points_eta,
                    "min_seeding": max(as_int(level.get("min_seeding")), 0),
                    "min_seeding_strict": bool(level.get("min_seeding_strict")),
                    "min_seeding_size": max(as_int(level.get("min_seeding_size")), 0),
                    "min_seeding_size_strict": bool(level.get("min_seeding_size_strict")),
                    "min_torrent_uploads": max(as_int(level.get("min_torrent_uploads")), 0),
                    "min_torrent_uploads_strict": bool(level.get("min_torrent_uploads_strict")),
                    "min_average_seeding_time_days": as_float(level.get("min_average_seeding_time_days")),
                    "min_average_seeding_time_days_strict": bool(level.get("min_average_seeding_time_days_strict")),
                    "alternatives": alternatives,
                    "unsupported_requirements": list(level.get("unsupported_requirements") or []),
                    "eligible_date": _eligible_date(
                        base["join_at"],
                        level.get("min_join_days"),
                        bool(level.get("min_join_days_strict")),
                    ),
                    "reached": index <= current_index,
                    "is_current": index == current_index,
                    "is_retirement": index == retirement_index,
                    "missing": [] if index <= current_index else _requirement_missing(level, snapshot),
                }
            )
        if forced_wealthy or vip_index >= 0:
            counts["wealthy_retired"] += 1
            sites.append(
                {
                    **base,
                    "retirement_level": retirement_name,
                    "status": "wealthy_retired",
                    "is_vip": vip_index >= 0,
                    "levels_remaining": 0,
                    "route": route,
                }
            )
            continue
        if current_index < 0:
            sites.append(
                {
                    **base,
                    "retirement_level": retirement_name,
                    "route": route,
                }
            )
            counts["rule_missing"] += 1
            continue

        if not retirement_name:
            next_level = (
                as_text(raw_levels[current_index + 1].get("name"))
                if current_index + 1 < len(raw_levels)
                else ""
            )
            counts["upgrading"] += 1
            sites.append(
                {
                    **base,
                    "next_level": next_level,
                    "status": "upgrading",
                    "route": route,
                }
            )
            continue

        retired = current_index >= retirement_index
        status = "retired" if retired else "upgrading"
        counts[status] += 1
        sites.append(
            {
                **base,
                "next_level": as_text(raw_levels[current_index + 1].get("name")) if current_index + 1 < len(raw_levels) else "",
                "retirement_level": retirement_name,
                "status": status,
                "levels_remaining": max(retirement_index - current_index, 0),
                "route": route,
            }
        )

    sites.sort(key=lambda item: (item["status"] == "rule_missing", item["status"] != "upgrading", item["site_name"]))
    return {"total": len(sites), **counts, "sites": sites}


def overall_ratio(upload: int, download: int) -> float | None:
    """计算汇总分享率，下载为零时返回空值。"""

    if download <= 0:
        return None
    return round(upload / download, 3)


def earliest_join_date(records: Iterable[Mapping[str, Any]]) -> str:
    """从站点加入时间中选取最早的有效日期。"""

    values: list[str] = []
    for record in records:
        raw = as_text(record.get("join_at"))[:10]
        try:
            values.append(date.fromisoformat(raw).isoformat())
        except (TypeError, ValueError):
            continue
    return min(values) if values else ""


def career_days(earliest: str, server_day: str) -> int | None:
    """计算从最早加入站点到服务器日期的自然日数量。"""

    if not earliest:
        return None
    try:
        start = date.fromisoformat(earliest[:10])
        end = date.fromisoformat(server_day[:10])
    except (TypeError, ValueError):
        return None
    return max((end - start).days + 1, 1)


def format_bytes(value: Any) -> str:
    """按二进制 1024 进位格式化通知和导出图片共用的容量文本。"""

    number = float(max(as_int(value), 0))
    units = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
    unit = units[0]
    for unit in units:
        if number < 1024 or unit == units[-1]:
            break
        number /= 1024
    if unit == "B":
        return f"{int(number)} {unit}"
    precision = 2 if number < 100 else 1
    return f"{number:.{precision}f} {unit}"
