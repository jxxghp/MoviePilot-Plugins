"""归一化、非敏感插件配置公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .attribution import PackageAttributionStrategy
from .source import SubtitleSource
from .target import PathMapping

__all__ = ["PluginConfig"]


@dataclass(slots=True)
class PluginConfig:
    """字幕助手运行所需的归一化非敏感配置。"""

    enabled: bool = False
    moviepilot_enabled: bool = True
    opensubtitles_enabled: bool = False
    assrt_enabled: bool = False
    allow_machine_translation: bool = False
    max_candidate_attempts: int = 3
    source_priority: list[SubtitleSource] = field(
        default_factory=lambda: [
            SubtitleSource.MOVIEPILOT,
            SubtitleSource.ASSRT,
            SubtitleSource.OPENSUBTITLES,
        ]
    )
    format_priority: list[str] = field(default_factory=list)
    path_mappings: tuple[PathMapping, ...] = field(default_factory=tuple)
    package_attribution_strategy: PackageAttributionStrategy = PackageAttributionStrategy.TRUST_PACKAGE

    def __post_init__(self) -> None:
        """把来源优先级收敛为来源能力拥有的枚举。"""

        self.source_priority = [
            source if isinstance(source, SubtitleSource) else SubtitleSource(source) for source in self.source_priority
        ]

    def enabled_sources(self) -> dict[SubtitleSource, bool]:
        """返回三个来源的启用状态。"""

        return {
            SubtitleSource.MOVIEPILOT: self.moviepilot_enabled,
            SubtitleSource.OPENSUBTITLES: self.opensubtitles_enabled,
            SubtitleSource.ASSRT: self.assrt_enabled,
        }

    def saved_payload(self) -> dict[str, object]:
        """返回可以交给宿主保存的完整非敏感配置。"""

        return {
            "enabled": self.enabled,
            "moviepilot_enabled": self.moviepilot_enabled,
            "opensubtitles_enabled": self.opensubtitles_enabled,
            "assrt_enabled": self.assrt_enabled,
            "allow_machine_translation": self.allow_machine_translation,
            "max_candidate_attempts": self.max_candidate_attempts,
            "source_priority": [source.value for source in self.source_priority],
            "format_priority": list(self.format_priority),
            "path_mappings": [mapping.as_dict() for mapping in self.path_mappings],
            "package_attribution_strategy": self.package_attribution_strategy.value,
        }
