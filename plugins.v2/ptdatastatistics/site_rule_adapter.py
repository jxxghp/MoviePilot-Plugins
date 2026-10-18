"""Adapt bundled PTDepilerMp rules to PTDataStatistics' progress schema."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .site_rules_builtin import SITE_LEVEL_RULES


_DURATION_RE = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?(?:T?(?P<hours>\d+)H)?$",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGTPE]?I?B)\s*$", re.IGNORECASE)
_SIZE_FACTORS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
    "PB": 1024**5,
    "EB": 1024**6,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
    "PIB": 1024**5,
    "EIB": 1024**6,
}
_CONDITION_FIELDS = {
    "uploaded": "min_upload",
    "downloaded": "min_download",
    "ratio": "min_ratio",
    "bonus": "min_bonus",
    "seedingBonus": "min_seeding_points",
    "seeding": "min_seeding",
    "seedingSize": "min_seeding_size",
    "uploads": "min_torrent_uploads",
    "averageSeedingTime": "min_average_seeding_time_days",
}
_UNSUPPORTED_LABELS = {
    "snatches": "下载完成数",
    "seedingTime": "做种时间",
    "posts": "发帖数",
    "hnrUnsatisfied": "未解决 H&R 数",
    "totalTraffic": "总流量",
    "trueDownloaded": "真实下载量",
    "perfectFlacs": "Perfect FLAC 数",
    "adoptions": "领养数",
}
_LEVEL_SUFFIXES = (
    "User",
    "Power User",
    "Elite User",
    "Crazy User",
    "Insane User",
    "Veteran User",
    "Extreme User",
    "Ultimate User",
    "Nexus Master",
    "mTorrent Master",
)

# MoviePilot 部分站点返回本地化等级名，而固定来源规则只记录英文等级名。
# 这里仅补充已经在插件旧版中验证过的兼容别名，不修改上游门槛。
_LEVEL_COMPATIBILITY_ALIASES = {
    "RailgunPT": {
        "Lv0": ("User", "Peasant"),
        "Lv1": ("Power User",),
        "Lv2": ("Elite User",),
        "Lv3": ("Crazy User",),
        "Lv4": ("Insane User",),
        "Lv5": ("Veteran User",),
        "Lv6": ("Extreme User",),
        "Lv7": ("Ultimate User",),
        "Lv8": ("Nexus Master",),
    },
    "藏宝阁": {
        "寻宝学徒": ("User", "Peasant"),
        "初入江湖": ("Power User",),
        "熟练巧匠": ("Elite User",),
        "慧眼识珍": ("Crazy User",),
        "护阁精英": ("Insane User",),
        "传法执事": ("Veteran User",),
        "藏经长老": ("Extreme User",),
        "镇阁宗师": ("Ultimate User",),
        "殿堂尊者": ("Nexus Master",),
    },
    "皇后": {
        "Elite User": ("貴人-正六品",),
        "Insane User": ("容華-正四品",),
        "Veteran User": ("貴嬪-正三品",),
        "Extreme User": ("淑儀-正二品",),
        "Ultimate User": ("貴妃-正一品",),
    },
    "馒头": {
        "User": ("小卒",),
        "Power User": ("捕头",),
        "Elite User": ("知县",),
        "Crazy User": ("通判",),
        "Insane User": ("知州",),
        "Veteran User": ("府丞",),
        "Extreme User": ("府尹",),
        "Ultimate User": ("总督", "總督"),
        "mTorrent Master": ("大臣",),
    },
}

_SITE_COMPATIBILITY_ALIASES = {
    "Monikadesign": ("莫妮卡",),
    "MyPT": ("我的PT",),
    "PTTime": ("PT时间",),
    "传道院": ("修道院",),
    "馒头": ("M-Team", "MTeam", "m-team"),
    "观众": ("Audiences", "Audience"),
    "彩虹岛": ("Rainbow", "CHDBits"),
    "憨憨": ("HHan", "HHanClub"),
    "春天": ("Spring", "Spring-Sunday"),
    "天空": ("HDSky", "Skyey"),
    "猫站": ("Pter", "PterClub"),
    "家园": ("HDHome",),
    "朋友": ("Friend", "Friends"),
    "皇后": ("OpenCD", "open.cd"),
    "听听歌": ("TTG", "ToTheGlory"),
    "我堡": ("OurBits", "OB"),
    "ilolicon": ("萝莉",),
}


def _downgrade_description(threshold: float) -> str:
    """生成仅用于说明的降级阈值；升级计算仍只使用升级条件。"""

    return f"分享率低于 {threshold:g} 时自动降级。"


def _level_patch(
    *,
    alias: str,
    ratio_strict: bool = False,
    points_strict: bool = False,
    downgrade_ratio: float | None = None,
    **requirements: Any,
) -> dict[str, Any]:
    patch = {
        "aliases": (alias,),
        "min_ratio_strict": ratio_strict,
        "min_seeding_points_strict": points_strict,
        **requirements,
    }
    if downgrade_ratio is not None:
        patch["description_suffix"] = _downgrade_description(downgrade_ratio)
    return patch


def _spring_alternatives(download: int, real_download: str, points: int, uploads: int, points_only: int) -> list[dict[str, Any]]:
    """展开下载二选一与积分/发种二选一的组合，保留 AND/OR 语义。"""
    return [
        {**download_requirement, **points_requirement}
        for download_requirement in (
            {"min_download": download, "min_download_strict": True},
            {"unsupported_requirements": [{"key": "real_download", "label": "真实下载量", "target": f"> {real_download}"}]},
        )
        for points_requirement in (
            {"min_seeding_points": points, "min_torrent_uploads": uploads, "min_torrent_uploads_strict": True},
            {"min_seeding_points": points_only},
        )
    ]


# 用户依据各站当前等级页校正的规则。上游生成文件保持原样，便于后续重新生成和审计。
_SITE_RULE_PATCHES: dict[str, dict[str, Any]] = {
    "憨憨": {
        "retirement_source_id": 8,
        "levels": {
            7: {"description": "得到一个邀请名额。"},
            8: {"description": "得到两个邀请名额。Nexus Master及以上用户会永远保留账号。"},
        },
    },
    "Monikadesign": {"retirement_source_id": 8},
    "MyPT": {"retirement_source_id": 10},
    "PTTime": {"retirement_source_id": 9},
    "传道院": {"retirement_source_id": 10},
    "朱雀": {"retirement_source_id": 8},
    "春天": {
        "retirement_source_id": 6,
        "additional_levels": [
            {"id": 0, "name": "吸血鬼(Peasant)", "privilege": "被降级的用户，有7天时间提升分享率，否则会被踢。"},
            {"id": 6, "name": "传说(Legend)", "privilege": "权限和神王相同。传说及以上等级免除自动降级。由管理员授予，或使用茉莉购买限时传说。"},
        ],
        "vip_levels": [{"id": 100, "name": "荣誉会员(Honor)", "privilege": "在某些方面做出特殊贡献的会员。由管理员授予。"}],
        "levels": {
            1: {"description_suffix": "等级提升从第5周结束后开始；系统每24小时调整一次，非实时。分享率要求使用站点分享率，并非实际分享率。"},
            2: {
                "min_join_days": 35,
                "min_download": None,
                "min_download_strict": False,
                "min_ratio_strict": True,
                "description": "可以查看排行榜；可以浏览论坛邀请区；自助申请保种员；等级加成0.05。",
                "description_suffix": _downgrade_description(1.1),
                "alternatives": _spring_alternatives(500 * 1024**3, "2048 GB", 100_000, 1, 150_000),
            },
            3: {
                "min_join_days": 35,
                "min_download": None,
                "min_download_strict": False,
                "min_ratio_strict": True,
                "description_suffix": _downgrade_description(1.1),
                "alternatives": _spring_alternatives(1024**4, "4 TB", 500_000, 100, 1_000_000),
            },
            4: {
                "min_join_days": 35,
                "min_download": None,
                "min_download_strict": False,
                "min_ratio_strict": True,
                "description_suffix": _downgrade_description(2),
                "alternatives": _spring_alternatives(3 * 1024**4, "12 TB", 1_200_000, 300, 2_400_000),
            },
            5: {
                "min_join_days": 35,
                "description_suffix": "每月最后一天按保种或发种两条路线评选，精英、大师、神仙或上月神王有晋级资格。此等级不免除自动降级。",
                "alternatives": [
                    {
                        "unsupported_requirements": [
                            {"key": "monthly_seeding_upload", "label": "当月保种上传", "target": "不少于 300 GB"},
                            {"key": "monthly_seeding_bonus_rank", "label": "当月做种积分排名", "target": "前 65 名"},
                        ],
                    },
                    {
                        "unsupported_requirements": [
                            {
                                "key": "monthly_qualified_upload_rank",
                                "label": "当月合规非中性活种发布数排名",
                                "target": "前 15 名",
                            },
                        ],
                    },
                ],
            },
            6: {"unsupported_requirements": [{"key": "legend_grant", "label": "传说资格", "target": "管理员授予，或茉莉购买限时资格"}]},
        },
    },
    "ilolicon": {
        "levels": {
            3: _level_patch(alias="Power User", ratio_strict=True, downgrade_ratio=.95),
            4: _level_patch(alias="Elite User", ratio_strict=True, downgrade_ratio=1.45),
            5: _level_patch(alias="Crazy User", ratio_strict=True, downgrade_ratio=1.95),
            6: _level_patch(alias="Insane User", ratio_strict=True, downgrade_ratio=2.45),
            7: _level_patch(alias="Veteran User", ratio_strict=True, downgrade_ratio=2.95),
            8: _level_patch(alias="Extreme User", ratio_strict=True, downgrade_ratio=3.45),
            9: _level_patch(alias="Ultimate User", ratio_strict=True, downgrade_ratio=3.95),
            10: _level_patch(alias="Nexus Master", ratio_strict=True, downgrade_ratio=4.45),
        },
    },
    "天空": {
        "retirement_source_id": 6,
        "levels": {
            2: _level_patch(alias="Power User", ratio_strict=True, downgrade_ratio=1.9),
            3: _level_patch(alias="Elite User", ratio_strict=True, downgrade_ratio=2.4),
            4: _level_patch(alias="Crazy User", ratio_strict=True, downgrade_ratio=2.9),
            5: _level_patch(alias="Insane User", ratio_strict=True, downgrade_ratio=3.4),
            6: _level_patch(alias="Veteran User", ratio_strict=True, downgrade_ratio=3.9),
            7: _level_patch(alias="Extreme User", ratio_strict=True, downgrade_ratio=4.4),
            8: _level_patch(alias="Ultimate User", ratio_strict=True, downgrade_ratio=4.9),
            9: _level_patch(alias="Nexus Master", ratio_strict=True, downgrade_ratio=5.4),
        },
    },
    "音乐乌托邦": {
        "retirement_source_id": 7,
        "levels": {
            3: _level_patch(alias="Power User", ratio_strict=True, points_strict=True, downgrade_ratio=.95),
            4: _level_patch(alias="Elite User", ratio_strict=True, points_strict=True, downgrade_ratio=1.45),
            5: _level_patch(alias="Crazy User", ratio_strict=True, points_strict=True, downgrade_ratio=1.95),
            6: _level_patch(alias="Insane User", ratio_strict=True, points_strict=True, downgrade_ratio=2.45),
            7: _level_patch(alias="Veteran User", ratio_strict=True, points_strict=True, downgrade_ratio=2.95),
            8: _level_patch(alias="Extreme User", ratio_strict=True, points_strict=True, downgrade_ratio=3.45),
            9: _level_patch(alias="Ultimate User", ratio_strict=True, points_strict=True, downgrade_ratio=3.95),
            10: _level_patch(alias="Nexus Master", ratio_strict=True, points_strict=True, downgrade_ratio=4.45),
        },
    },
    "Depth Studio": {
        "retirement_source_id": 10,
        "levels": {
            1: {"description": "被降级的用户，他们有15天时间来提升分享率，否则会被踢。不能发表趣味盒内容；不能申请友情链接；不能上传字幕。"},
            2: {"description": "新用户的默认级别。"},
            3: _level_patch(alias="Power User", ratio_strict=True, points_strict=True, downgrade_ratio=1.2, min_ratio=1.2,
                            description="可以查看NFO文档；可以请求续种；可以查看排行榜；可以查看其它用户的种子历史（隐私等级未设置为强时）；可以删除自己上传的字幕。"),
            4: _level_patch(alias="Elite User", ratio_strict=True, points_strict=True, downgrade_ratio=2.55, min_ratio=2.55, description=""),
            5: _level_patch(alias="Crazy User", ratio_strict=True, points_strict=True, downgrade_ratio=2.55, min_ratio=2.55,
                            description="可以在做种、下载、发布的时候选择匿名模式。"),
            6: _level_patch(alias="Insane User", ratio_strict=True, points_strict=True, downgrade_ratio=3.2, min_ratio=3.2,
                            description="可以查看普通日志。"),
            7: _level_patch(alias="Veteran User", ratio_strict=True, points_strict=True, downgrade_ratio=4.05, min_ratio=4.05,
                            description="可以查看其它用户的评论、帖子历史。"),
            8: _level_patch(alias="Extreme User", ratio_strict=True, points_strict=True, downgrade_ratio=5, min_ratio=5,
                            description="可以更新过期的外部信息；可以查看Extreme User论坛。Extreme User及以上用户封存账号后不会被删除。"),
            9: _level_patch(alias="Ultimate User", ratio_strict=True, points_strict=True, downgrade_ratio=6, min_ratio=6, description=""),
            10: _level_patch(alias="Nexus Master", ratio_strict=True, points_strict=True, downgrade_ratio=7, min_ratio=7,
                             description="Nexus Master及以上用户会永远保留账号。"),
        },
    },
    "GGPT": {
        "levels": {
            1: _level_patch(alias="Power User", points_strict=True, downgrade_ratio=1.9),
            2: _level_patch(alias="Elite User", points_strict=True, downgrade_ratio=2.4),
            3: _level_patch(alias="Crazy User", points_strict=True, downgrade_ratio=2.9),
            4: _level_patch(alias="Insane User", points_strict=True, downgrade_ratio=3.4),
            5: _level_patch(alias="Veteran User", points_strict=True, downgrade_ratio=3.9),
            6: _level_patch(alias="Extreme User", points_strict=True, downgrade_ratio=4.4),
            7: _level_patch(alias="Ultimate User", points_strict=True, downgrade_ratio=4.9),
            8: _level_patch(alias="Nexus Master", points_strict=True, downgrade_ratio=5.4),
        },
    },
}


_ZIMIAO_LEVELS = (
    ("Power User", 4, 50, 1, 40_000, 1, 1),
    ("Elite User", 8, 100, 2, 100_000, 5, .5),
    ("Crazy User", 15, 150, 3, 300_000, 10, 1.5),
    ("Insane User", 25, 200, 4, 500_000, 20, 2),
    ("Veteran User", 40, 250, 5, 1_000_000, 40, 2.5),
    ("Extreme User", 60, 300, 6, 1_500_000, 80, 3),
    ("Ultimate User", 80, 350, 7, 2_000_000, 150, 3.5),
    ("Nexus Master", 100, 400, 8, 5_000_000, 200, 4),
)


def _zimiao_rule() -> dict[str, Any]:
    """构造用户提供的梓喵等级表；以最高固定等级作为完整路线目标。"""

    levels: list[dict[str, Any]] = [{"name": "User", "aliases": (), "description": "新用户默认等级。"}]
    for name, weeks, download_gb, ratio, points, uploads, downgrade_ratio in _ZIMIAO_LEVELS:
        levels.append({
            "name": name,
            "aliases": (),
            "description": _downgrade_description(downgrade_ratio),
            "min_join_days": weeks * 7,
            "min_download": download_gb * 1024**3,
            "min_ratio": ratio,
            "min_ratio_strict": True,
            "min_seeding_points": points,
            "min_seeding_points_strict": True,
            "min_torrent_uploads": uploads,
        })
    return {
        "site": "梓喵",
        "aliases": ("Zimiao",),
        "domains": (),
        "retirement_level": "Nexus Master",
        "levels": levels,
        "vip_levels": [],
        "source": "user-provided",
    }


def _unique_aliases(values: list[str], *, primary: str = "") -> tuple[str, ...]:
    """按与运行时相同的展示归一化规则去重别名。"""

    seen = {re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", primary.casefold())}
    result: list[str] = []
    for value in values:
        identity = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return tuple(result)


def _duration_days(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    matched = _DURATION_RE.fullmatch(value.strip())
    if not matched:
        return None
    parts = {key: int(raw or 0) for key, raw in matched.groupdict().items()}
    return (
        parts["years"] * 365
        + parts["months"] * 30
        + parts["weeks"] * 7
        + parts["days"]
        + parts["hours"] / 24
    )


def _size_bytes(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(int(value), 0)
    if not isinstance(value, str):
        return None
    matched = _SIZE_RE.fullmatch(value)
    if not matched:
        return None
    return max(int(float(matched.group(1)) * _SIZE_FACTORS[matched.group(2).upper()]), 0)


def _converted_value(source_key: str, value: Any) -> int | float | None:
    if source_key in {"uploaded", "downloaded", "seedingSize"}:
        return _size_bytes(value)
    if source_key == "averageSeedingTime":
        return _duration_days(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _adapt_condition(raw: Mapping[str, Any]) -> dict[str, Any]:
    condition: dict[str, Any] = {}
    unsupported: list[dict[str, Any]] = []
    for source_key, target_key in _CONDITION_FIELDS.items():
        if source_key not in raw:
            continue
        value = _converted_value(source_key, raw[source_key])
        if value is not None:
            condition[target_key] = value
    for source_key, label in _UNSUPPORTED_LABELS.items():
        if source_key in raw:
            unsupported.append({"key": source_key, "label": label, "target": raw[source_key]})
    if unsupported:
        condition["unsupported_requirements"] = unsupported
    return condition


def _adapt_level(raw: Mapping[str, Any], *, site_name: str = "") -> dict[str, Any]:
    name = str(raw.get("name") or "").strip()
    aliases = [str(item).strip() for item in raw.get("nameAka") or () if str(item).strip()]
    aliases.extend(_LEVEL_COMPATIBILITY_ALIASES.get(site_name, {}).get(name, ()))
    for suffix in sorted(_LEVEL_SUFFIXES, key=len, reverse=True):
        if name.casefold().endswith(suffix.casefold()):
            if name.casefold() != suffix.casefold():
                aliases.append(suffix)
            break
    level: dict[str, Any] = {
        "name": name,
        "aliases": tuple(dict.fromkeys(aliases)),
        "description": str(raw.get("privilege") or "").strip(),
        "source_id": raw.get("id"),
    }
    interval = _duration_days(raw.get("interval"))
    if interval is not None:
        level["min_join_days"] = int(interval)
    level.update(_adapt_condition(raw))
    alternatives = [
        adapted
        for item in raw.get("alternative") or ()
        if isinstance(item, Mapping) and (adapted := _adapt_condition(item))
    ]
    if alternatives:
        level["alternatives"] = alternatives
    return level


def _apply_level_patches(
    levels: list[dict[str, Any]],
    patches: Mapping[int, Mapping[str, Any]],
) -> None:
    """按上游稳定的等级 ID 应用站点校正，不改写生成源文件。"""

    for level in levels:
        patch = patches.get(level.get("source_id"))
        if not patch:
            continue
        aliases = [*level.get("aliases", ()), *patch.get("aliases", ())]
        suffix = str(patch.get("description_suffix") or "").strip()
        level.update({
            key: value
            for key, value in patch.items()
            if key not in {"aliases", "description_suffix"}
        })
        level["aliases"] = _unique_aliases(aliases, primary=level["name"])
        if suffix and suffix not in level["description"]:
            level["description"] = " ".join(item for item in (level["description"], suffix) if item)


def bundled_retirement_rules() -> dict[str, Mapping[str, Any]]:
    """Return live-site keep-account rules plus VIP-only rules for wealthy retirement."""

    result: dict[str, Mapping[str, Any]] = {}
    for raw_rule in SITE_LEVEL_RULES:
        if raw_rule.get("is_dead"):
            continue
        site_name = str(raw_rule.get("name") or "").strip()
        rule_patch = _SITE_RULE_PATCHES.get(site_name, {})
        normal_levels = [
            level
            for level in raw_rule.get("levels") or ()
            if isinstance(level, Mapping) and level.get("groupType") not in {"vip", "manager"}
        ]
        normal_levels.extend(rule_patch.get("additional_levels", ()))
        if rule_patch.get("additional_levels"):
            normal_levels.sort(key=lambda level: level.get("id", 0))
        kept = next((level for level in normal_levels if level.get("isKept") is True), None)
        levels = [_adapt_level(level, site_name=site_name) for level in normal_levels]
        levels = [level for level in levels if level["name"]]
        _apply_level_patches(levels, rule_patch.get("levels", {}))
        vip_levels = [
            _adapt_level(level, site_name=site_name)
            for level in rule_patch.get("vip_levels", [
                level for level in raw_rule.get("levels") or ()
                if isinstance(level, Mapping) and level.get("groupType") == "vip"
            ])
        ]
        vip_levels = [level for level in vip_levels if level["name"]]
        retirement_name = str(kept.get("name") or "").strip() if kept else ""
        retirement_source_id = rule_patch.get("retirement_source_id")
        if retirement_source_id is not None:
            retirement_name = next(
                (
                    level["name"]
                    for level in levels
                    if level.get("source_id") == retirement_source_id
                ),
                retirement_name,
            )
        # 即使站点没有公开保号等级，也保留普通等级路线，供下一级进度展示。
        if not levels and not vip_levels:
            continue
        aliases = [str(raw_rule.get("source_key") or "").strip()]
        aliases.extend(str(item).strip() for item in raw_rule.get("aliases") or ())
        aliases.extend(_SITE_COMPATIBILITY_ALIASES.get(site_name, ()))
        domains = [str(item).strip() for item in raw_rule.get("domains") or ()]
        for field in ("domain", "url"):
            if raw_rule.get(field):
                domains.append(str(raw_rule[field]).strip())
        result[site_name] = {
            "site": site_name,
            "aliases": _unique_aliases([item for item in aliases if item], primary=site_name),
            "domains": tuple(dict.fromkeys(item for item in domains if item)),
            "retirement_level": retirement_name,
            "levels": levels,
            "vip_levels": vip_levels,
            "source": "PTDepilerMp",
        }
    result["梓喵"] = _zimiao_rule()
    return result
