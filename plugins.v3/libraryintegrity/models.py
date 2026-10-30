"""影视库完整性检查的数据结构：扫描中间结构与对外报告模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceError(Exception):
    """数据源读取失败（媒体库列表、分页条目等）。"""


class IssueType(str, Enum):
    """报告问题分类。"""

    MISSING = "missing"
    VERSION = "version"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    UNCHECKED = "unchecked"
    SUGGESTION = "suggestion"


ISSUE_TYPE_LABELS: dict[IssueType, str] = {
    IssueType.MISSING: "缺集",
    IssueType.VERSION: "版本偏离",
    IssueType.DUPLICATE: "多文件",
    IssueType.CONFLICT: "编号冲突",
    IssueType.UNCHECKED: "无法核对",
    IssueType.SUGGESTION: "AI 建议",
}

# 数据来源：emby 为 Emby 媒体服务器，local 为插件直接扫描的本地目录
ORIGIN_EMBY = "emby"
ORIGIN_LOCAL = "local"


class Severity(str, Enum):
    """问题严重程度。"""

    WARNING = "warning"
    INFO = "info"


# 版本维度：键为配置值，值为展示名称
VERSION_DIMENSIONS: dict[str, str] = {
    "resolution": "分辨率",
    "video_codec": "视频编码",
    "hdr": "HDR",
    "bit_depth": "位深",
    "audio_codec": "音频编码",
    "release_group": "发布组/字幕组",
}

# 技术维度偏离视为警告，发布信息偏离仅作提示
DIMENSION_SEVERITY: dict[str, Severity] = {
    "resolution": Severity.WARNING,
    "video_codec": Severity.WARNING,
    "hdr": Severity.WARNING,
    "bit_depth": Severity.INFO,
    "audio_codec": Severity.INFO,
    "release_group": Severity.INFO,
}


@dataclass
class VersionInfo:
    """单个文件版本的技术与发布信息；字段为 None 表示未知，不参与比较。"""

    path: str = ""
    # file：本地文件；strm：strm 文件
    kind: str = "file"
    name: str = ""
    # strm 指向的远程地址，只用于解析文件名，不发起请求
    url: str = ""
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    hdr: Optional[str] = None
    bit_depth: Optional[str] = None
    audio_codec: Optional[str] = None
    release_group: Optional[str] = None
    # 维度 -> 取值来源（emby / nfo / filename / url）
    sources: dict[str, str] = field(default_factory=dict)

    def get(self, dimension: str) -> Optional[str]:
        """读取指定版本维度的取值。"""
        return getattr(self, dimension, None)

    def fill(self, dimension: str, value: Optional[str], source: str) -> None:
        """仅在维度未知时补充取值并记录来源，已有更可信的取值不被覆盖。"""
        if value is None or value == "" or self.get(dimension) is not None:
            return
        setattr(self, dimension, value)
        self.sources[dimension] = source


@dataclass
class LibraryEpisode:
    """媒体服务器中的一个单集条目（可能包含多集或多个版本）。"""

    item_id: str
    season: Optional[int]
    episode: Optional[int]
    episode_end: Optional[int] = None
    # 声明的单集 TMDB ID，使用前须按剧集的 TMDB 季集数据校验
    tmdb_id: Optional[int] = None
    tmdb_id_source: str = ""
    path: str = ""
    versions: list[VersionInfo] = field(default_factory=list)
    # 采集阶段发现的编号冲突说明（如 NFO 与媒体服务器季集号不一致）
    conflicts: list[str] = field(default_factory=list)

    @property
    def episode_numbers(self) -> list[int]:
        """返回条目覆盖的全部集号，多集文件按起止集号展开。"""
        if self.episode is None:
            return []
        end = self.episode_end if self.episode_end and self.episode_end > self.episode else self.episode
        return list(range(self.episode, end + 1))

    @property
    def label(self) -> str:
        """返回 SxxEyy 形式的展示标签。"""
        season = "S??" if self.season is None else f"S{self.season:02d}"
        if self.episode is None:
            return f"{season}E??"
        numbers = self.episode_numbers
        if len(numbers) > 1:
            return f"{season}E{numbers[0]:02d}-E{numbers[-1]:02d}"
        return f"{season}E{self.episode:02d}"


@dataclass
class LibrarySeries:
    """媒体服务器中的一部剧集及其单集。"""

    server: str
    library: str
    item_id: str
    title: str
    year: str = ""
    tmdb_id: Optional[int] = None
    tmdb_id_source: str = ""
    path: str = ""
    episodes: list[LibraryEpisode] = field(default_factory=list)
    origin: str = ORIGIN_EMBY
    # 读取单集失败的原因；非空时该剧归入"无法核对"
    error: str = ""


@dataclass
class LibraryMovie:
    """媒体服务器中的一部电影条目。"""

    server: str
    library: str
    item_id: str
    title: str
    year: str = ""
    tmdb_id: Optional[int] = None
    versions: list[VersionInfo] = field(default_factory=list)
    origin: str = ORIGIN_EMBY


@dataclass(frozen=True)
class TmdbEpisodeRef:
    """TMDB 中的一个单集。"""

    tmdb_id: int
    season: int
    episode: int
    air_date: str = ""
    name: str = ""


@dataclass
class TmdbSeries:
    """TMDB 剧集的季集结构。"""

    tmdb_id: int
    name: str = ""
    status: str = ""
    # 季号 -> 该季单集列表
    seasons: dict[int, list[TmdbEpisodeRef]] = field(default_factory=dict)

    def episode_by_id(self) -> dict[int, TmdbEpisodeRef]:
        """返回单集 TMDB ID 到单集的索引。"""
        return {ref.tmdb_id: ref for refs in self.seasons.values() for ref in refs}

    def episode_by_number(self) -> dict[tuple[int, int], TmdbEpisodeRef]:
        """返回 (季号, 集号) 到单集的索引。"""
        return {(ref.season, ref.episode): ref for refs in self.seasons.values() for ref in refs}


class Issue(BaseModel):
    """报告中的一条问题。"""

    type: IssueType = Field(description="问题分类")
    severity: Severity = Field(default=Severity.WARNING, description="严重程度")
    server: str = Field(default="", description="媒体服务器名称")
    library: str = Field(default="", description="媒体库名称")
    title: str = Field(default="", description="剧集或电影标题")
    media_type: str = Field(default="tv", description="媒体类型：tv 或 movie")
    media_source: Optional[str] = Field(default=None, description="媒体身份来源")
    media_id: Optional[str] = Field(default=None, description="媒体身份来源原生 ID")
    season: Optional[int] = Field(default=None, description="涉及的季号")
    episodes: list[int] = Field(default_factory=list, description="涉及的集号（缺集时为 TMDB 集号）")
    summary: str = Field(default="", description="一句话说明")
    details: list[str] = Field(default_factory=list, description="补充明细")
    scope: str = Field(default="", description="忽略规则使用的范围键，如 tmdb:123:S1")
    adopt_kind: str = Field(default="", description="AI 建议可采纳的规则类型：mapping 或 identity")
    adopt_rule: str = Field(default="", description="采纳后写入配置的规则文本")


class ReportStats(BaseModel):
    """扫描统计。"""

    servers: list[str] = Field(default_factory=list, description="参与扫描的服务器")
    libraries: int = Field(default=0, description="扫描的媒体库数量")
    series: int = Field(default=0, description="扫描的剧集数量")
    episodes: int = Field(default=0, description="扫描的单集条目数量")
    movies: int = Field(default=0, description="扫描的电影数量")
    nfo_reads: int = Field(default=0, description="读取的 NFO 文件数量")
    tmdb_requests: int = Field(default=0, description="TMDB 查询次数")
    probes: int = Field(default=0, description="本次新读取媒体信息的本地文件数量")
    ai_calls: int = Field(default=0, description="本次调用 AI 的次数")


class Report(BaseModel):
    """一次完整扫描的报告。"""

    started_at: str = Field(default="", description="开始时间")
    finished_at: str = Field(default="", description="结束时间")
    duration_seconds: float = Field(default=0, description="耗时（秒）")
    cancelled: bool = Field(default=False, description="是否被中途停止")
    stats: ReportStats = Field(default_factory=ReportStats, description="扫描统计")
    issues: list[Issue] = Field(default_factory=list, description="全部问题（未应用忽略规则）")
    errors: list[str] = Field(default_factory=list, description="扫描过程中的错误")
    truncated: bool = Field(default=False, description="问题数量超过上限时被截断")
    ai_summary: str = Field(default="", description="AI 生成的报告摘要")
