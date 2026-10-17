"""PT 数据统计插件 API 的显式响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .core import normalize_identity


class SiteSnapshotData(BaseModel):
    """单个站点的累计值与当日增量。"""

    id: int | None = None
    site_id: int | None = None
    site_name: str = ""
    site_priority: int | None = None
    is_active: bool = False
    username: str = ""
    userid: str = ""
    join_at: str = ""
    user_level: str = ""
    upload: int = 0
    download: int = 0
    daily_upload: int = 0
    daily_download: int = 0
    baseline_valid: bool = False
    counter_reset: bool = False
    ratio: float | None = None
    bonus: float | None = None
    estimated_bonus_hourly: float | None = None
    seeding_points: float | None = None
    seeding_points_hourly: float | None = None
    seeding: int = 0
    seeding_size: int = 0
    torrent_uploads: float | None = None
    average_seeding_time_days: float | None = None
    updated_day: str = ""
    contribution: float = 0


class SummaryData(BaseModel):
    """侧栏总览和 PT 生涯共用的聚合指标。"""

    valid_sites: int = 0
    total_upload: int = 0
    total_download: int = 0
    overall_ratio: float | None = None
    total_seeding: int = 0
    total_seeding_size: int = 0
    today_upload: int = 0
    today_download: int = 0
    today_sites: int = 0
    earliest_join_at: str = ""
    career_days: int | None = None
    average_upload: int = 0
    average_download: int = 0
    top_upload_site: str = ""
    top_download_site: str = ""


class TwelveSiteData(BaseModel):
    """十二大中的单个站点状态。"""

    key: str
    name: str
    state: str
    site_id: int | None = None
    join_at: str = ""


class TwelveProgressData(BaseModel):
    """十二大完成进度。"""

    joined: int = 0
    total: int = 12
    percent: int = 0
    items: list[TwelveSiteData] = Field(default_factory=list)


class TrafficDistributionItem(BaseModel):
    """某个时间范围内单站的上传下载增量。"""

    site_id: int | None = None
    site_name: str = ""
    upload: int = 0
    download: int = 0


class TrafficDistributionResponse(BaseModel):
    """数据总览使用的月度与日度站点流量分布。"""

    month: str
    day: str
    monthly: list[TrafficDistributionItem] = Field(default_factory=list)
    daily: list[TrafficDistributionItem] = Field(default_factory=list)


class LevelRequirementData(BaseModel):
    """养老进度中的一个等级及其门槛。"""

    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    min_join_days: int = 0
    min_join_days_strict: bool = False
    min_upload: int = 0
    min_upload_strict: bool = False
    min_download: int = 0
    min_download_strict: bool = False
    min_ratio: float | None = None
    min_ratio_strict: bool = False
    min_bonus: float | None = None
    min_bonus_strict: bool = False
    min_seeding_points: float | None = None
    min_seeding_points_strict: bool = False
    seeding_points_eta_hours: int | None = None
    seeding_points_eta_days: int | None = None
    seeding_points_eta_date: str = ""
    min_seeding: int = 0
    min_seeding_strict: bool = False
    min_seeding_size: int = 0
    min_seeding_size_strict: bool = False
    min_torrent_uploads: int = 0
    min_torrent_uploads_strict: bool = False
    min_average_seeding_time_days: float | None = None
    min_average_seeding_time_days_strict: bool = False
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    unsupported_requirements: list[dict[str, Any]] = Field(default_factory=list)
    eligible_date: str = ""
    reached: bool = False
    is_current: bool = False
    is_retirement: bool = False
    missing: list[str] = Field(default_factory=list)


class RetirementSiteData(BaseModel):
    """单站升级路线与达到保号等级的进度。"""

    site_id: int | None = None
    site_name: str = ""
    site_priority: int | None = None
    current_level: str = ""
    next_level: str = ""
    retirement_level: str = ""
    status: str = "rule_missing"
    is_vip: bool = False
    wealthy_retirement_manual: bool = False
    join_at: str = ""
    upload: int = 0
    download: int = 0
    ratio: float | None = None
    bonus: float | None = None
    seeding_points: float | None = None
    estimated_bonus_hourly: float | None = None
    seeding_points_hourly: float | None = None
    seeding: int = 0
    seeding_size: int = 0
    torrent_uploads: float | None = None
    average_seeding_time_days: float | None = None
    updated_day: str = ""
    levels_remaining: int | None = None
    route: list[LevelRequirementData] = Field(default_factory=list)


class RetirementProgressData(BaseModel):
    """全部站点养老进度汇总。"""

    total: int = 0
    retired: int = 0
    wealthy_retired: int = 0
    upgrading: int = 0
    rule_missing: int = 0
    sites: list[RetirementSiteData] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    """侧栏与仪表盘读取的完整统计响应。"""

    server_date: str
    generated_at: str
    last_mp_update: str = ""
    first_history_day: str = ""
    last_history_day: str = ""
    summary: SummaryData
    sites: list[SiteSnapshotData] = Field(default_factory=list)
    today_sites: list[SiteSnapshotData] = Field(default_factory=list)
    history_sites: list[SiteSnapshotData] = Field(default_factory=list)
    twelve: TwelveProgressData
    retirement: RetirementProgressData


class HistoryResponse(BaseModel):
    """历史查询响应。"""

    start_day: str
    end_day: str
    count: int
    records: list[SiteSnapshotData] = Field(default_factory=list)


class HourlyTrafficPoint(BaseModel):
    """一个自然小时内由 MP 相邻采样计算出的真实流量增量。"""

    hour: str
    upload: int = 0
    download: int = 0
    samples: int = 0


class HourlyTrafficResponse(BaseModel):
    """指定日期及站点范围的小时流量曲线。"""

    day: str
    site_id: int | None = None
    site_name: str = "全部站点"
    baseline_valid: bool = False
    sample_count: int = 0
    points: list[HourlyTrafficPoint] = Field(default_factory=list)


class UploadedRequirementData(BaseModel):
    """用户上传规则中的一组可复用等级条件。"""

    model_config = ConfigDict(extra="forbid")

    min_join_days: int = Field(default=0, ge=0)
    min_join_days_strict: bool = False
    min_upload: int = Field(default=0, ge=0)
    min_upload_strict: bool = False
    min_download: int = Field(default=0, ge=0)
    min_download_strict: bool = False
    min_ratio: float | None = Field(default=None, ge=0)
    min_ratio_strict: bool = False
    min_bonus: float | None = Field(default=None, ge=0)
    min_bonus_strict: bool = False
    min_seeding_points: float | None = Field(default=None, ge=0)
    min_seeding_points_strict: bool = False
    min_seeding: int = Field(default=0, ge=0)
    min_seeding_strict: bool = False
    min_seeding_size: int = Field(default=0, ge=0)
    min_seeding_size_strict: bool = False
    min_torrent_uploads: int = Field(default=0, ge=0)
    min_torrent_uploads_strict: bool = False
    min_average_seeding_time_days: float | None = Field(default=None, ge=0)
    min_average_seeding_time_days_strict: bool = False
    unsupported_requirements: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class UploadedLevelRuleData(UploadedRequirementData):
    """用户上传规则中的单个等级。"""

    name: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=2000)
    alternatives: list[UploadedRequirementData] = Field(default_factory=list, max_length=20)

    @field_validator("name", "description")
    @classmethod
    def strip_level_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("aliases")
    @classmethod
    def normalize_level_aliases(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class UploadedRetirementRuleData(BaseModel):
    """用户上传的单站完整等级规则。"""

    model_config = ConfigDict(extra="forbid")

    site: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    retirement_level: str = Field(min_length=1, max_length=128)
    levels: list[UploadedLevelRuleData] = Field(min_length=1, max_length=100)
    vip_levels: list[UploadedLevelRuleData] = Field(default_factory=list, max_length=100)

    @field_validator("site", "retirement_level")
    @classmethod
    def strip_rule_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("aliases", "domains")
    @classmethod
    def normalize_site_aliases(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def validate_level_route(self):
        """等级名不可重复，保号等级必须存在于完整路线。"""

        identities: set[str] = set()
        retirement_identity = normalize_identity(self.retirement_level)
        retirement_found = False
        for level in self.levels:
            level_identities = {
                normalize_identity(value)
                for value in (level.name, *level.aliases)
            }
            if not level_identities or "" in level_identities:
                raise ValueError("等级名称不能为空")
            if identities.intersection(level_identities):
                raise ValueError(f"等级名称或别名重复：{level.name}")
            identities.update(level_identities)
            retirement_found = retirement_found or retirement_identity in level_identities
        if not retirement_found:
            raise ValueError(f"保号等级不在等级路线中：{self.retirement_level}")
        return self


class SettingsData(BaseModel):
    """插件可编辑设置。"""

    enabled: bool = False
    retention_days: int = 365
    notification_enabled: bool = False
    notification_cron: str = "0 9 * * *"
    notification_modes: list[str] = Field(default_factory=lambda: ["today"])
    ptd_cookiecloud_enabled: bool = False
    ptd_cookiecloud_uuid: str = ""
    ptd_cookiecloud_password: str = ""
    ptd_cookiecloud_headers: str = ""
    ptd_site_mappings: str = ""
    wealthy_retirement_sites: list[str] = Field(default_factory=list, max_length=500)
    custom_retirement_rules: list[UploadedRetirementRuleData] = Field(default_factory=list, max_length=100)

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, value: int) -> int:
        """保留期允许永久（0）或不超过一百年的正整数。"""

        return max(0, min(int(value), 36500))

    @field_validator("notification_cron")
    @classmethod
    def validate_notification_cron(cls, value: str) -> str:
        """使用 APScheduler 校验标准五段式 Cron。"""

        from apscheduler.triggers.cron import CronTrigger

        normalized = " ".join(str(value or "0 9 * * *").split())
        if len(normalized.split(" ")) != 5:
            raise ValueError("通知 Cron 必须为标准五段式表达式")
        try:
            CronTrigger.from_crontab(normalized)
        except ValueError as error:
            raise ValueError(f"通知 Cron 无效：{error}") from error
        return normalized

    @field_validator("notification_modes")
    @classmethod
    def validate_notification_modes(cls, value: list[str]) -> list[str]:
        """仅保留今日和所有数据两种通知内容。"""

        allowed = {"today", "all"}
        modes = [item for item in value if item in allowed]
        return list(dict.fromkeys(modes))

    @field_validator("wealthy_retirement_sites")
    @classmethod
    def normalize_wealthy_retirement_sites(cls, value: list[str]) -> list[str]:
        """规范化手动富贵养老的站点 ID，并兼容旧配置中的域名或站点名。"""

        normalized = [str(item).strip().casefold() for item in value if str(item).strip()]
        return list(dict.fromkeys(normalized))

    @field_validator("custom_retirement_rules")
    @classmethod
    def validate_custom_rule_sites(
        cls,
        value: list[UploadedRetirementRuleData],
    ) -> list[UploadedRetirementRuleData]:
        """同一上传文件中的站点名称和别名必须唯一，避免匹配歧义。"""

        identities: set[str] = set()
        for rule in value:
            for name in (rule.site, *rule.aliases, *rule.domains):
                identity = "".join(character for character in name.casefold() if character.isalnum())
                if identity in identities:
                    raise ValueError(f"站点名称或别名重复：{name}")
                identities.add(identity)
        return value

    @field_validator(
        "ptd_cookiecloud_uuid",
        "ptd_cookiecloud_headers",
        "ptd_site_mappings",
    )
    @classmethod
    def strip_ptd_text(cls, value: str) -> str:
        return str(value or "").strip()


class SettingsResponse(BaseModel):
    """设置读取或保存响应。"""

    settings: SettingsData
    rule_sites: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    """从 MP 同步数据的执行结果。"""

    imported: int = 0
    deleted: int = 0
    completed_at: str = ""


class MessageResponse(BaseModel):
    """通用动作结果。"""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


class CookieCloudUpdateData(BaseModel):
    """PTD CookieCloud 兼容上传请求。"""

    uuid: str = Field(min_length=5, max_length=256)
    encrypted: str = Field(min_length=1, max_length=64 * 1024 * 1024)


class CookieCloudEncryptedData(BaseModel):
    """PTD CookieCloud 兼容下载响应。"""

    encrypted: str


class CookieCloudActionResponse(BaseModel):
    """PTD CookieCloud 兼容写入结果。"""

    action: str
