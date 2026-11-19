"""校验特典身份，补全或按手动规则修正 NFO 播放位置。"""

import re
from dataclasses import dataclass, field
from typing import Any
from xml.dom import minidom

from .client import LookupFailure, TvdbEpisodeNotFound


POSITION_TAGS = (
    ("airsAfterSeason", "airsafter_season", "displayafterseason"),
    ("airsBeforeSeason", "airsbefore_season", "displayseason"),
    ("airsBeforeEpisode", "airsbefore_episode", "displayepisode"),
)


def integer(value: Any, *, minimum: int = 0) -> int | None:
    """只接受符合范围的整数，排除布尔值、小数和负数。"""
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value).strip()):
        return None
    number = int(str(value).strip())
    return number if number >= minimum else None


@dataclass
class EpisodeOverride:
    """保存指定的 TVDB 单集、位置字段或忽略规则。"""

    tvdb_id: int | None
    positions: dict[str, int | None]
    ignore: bool = False


def parse_overrides(text: str) -> dict[int, EpisodeOverride]:
    """按 TMDb 单集 ID 解析修正规则并拒绝歧义配置。"""
    result: dict[int, EpisodeOverride] = {}
    allowed = {"tvdb", *(tag for _, tag, _ in POSITION_TAGS)}
    for index, line in enumerate(text.splitlines(), 1):
        line = line.partition("#")[0].strip()
        if not line:
            continue
        source_text, *assignments = line.split(",")
        if not assignments:
            source_text, equals, value = source_text.partition("=")
            if equals:
                assignments = [f"tvdb={value}"]
        source = integer(source_text, minimum=1)
        label = f"手动映射第 {index} 行"
        if source is None or not assignments:
            raise ValueError(f"{label}请使用 TMDb单集ID,tvdb=TVDB单集ID 或指定播放位置字段")
        if len(assignments) == 1 and assignments[0].strip() == "ignore":
            override = EpisodeOverride(tvdb_id=None, positions={}, ignore=True)
        else:
            values: dict[str, int | None] = {}
            for assignment in assignments:
                name, equals, raw_value = assignment.partition("=")
                name, raw_value = name.strip(), raw_value.strip()
                if not equals or name not in allowed or name in values:
                    raise ValueError(f"{label}含未知、重复或格式无效的字段。ignore 须单独使用")
                if name != "tvdb" and not raw_value:
                    values[name] = None
                    continue
                value = integer(raw_value, minimum=1 if name == "tvdb" else 0)
                if value is None:
                    valid_values = "正整数" if name == "tvdb" else "非负整数或留空"
                    raise ValueError(f"{label}的 {name} 必须为{valid_values}")
                values[name] = value
            override = EpisodeOverride(tvdb_id=values.pop("tvdb", None), positions=values)
        if source in result and result[source] != override:
            raise ValueError(f"{label}与同一 TMDb 单集的其他规则冲突")
        result[source] = override
    return result


def parse_document(content: bytes | str) -> minidom.Document:
    """解析普通 NFO；拒绝 DTD 和实体声明，不加载外部资源。"""
    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("NFO 包含不支持的 DTD 或实体声明")
    return minidom.parseString(content)


def children(root: minidom.Element) -> dict[str, minidom.Element]:
    """读取根节点的直接子标签，拒绝身份或位置字段重复造成的歧义。"""
    result = {}
    guarded = {"season", "episode", "tmdbid", *(tag for _, tag, _ in POSITION_TAGS), *(alias for _, _, alias in POSITION_TAGS)}
    for node in root.childNodes:
        if isinstance(node, minidom.Element):
            if node.tagName in guarded and node.tagName in result:
                raise ValueError(f"NFO 包含重复的 {node.tagName} 字段")
            result[node.tagName] = node
    return result


def node_text(node: minidom.Element | None) -> str:
    """读取文本和 CDATA，保留其他 XML 内容。"""
    if node is None:
        return ""
    return "".join(child.nodeValue or "" for child in node.childNodes).strip()


def read_positions(nodes: dict[str, minidom.Element]) -> dict[str, str | None]:
    """按标准标签名读取现有位置，兼容 Jellyfin 别名并区分空值和缺失。"""
    positions = {}
    for _, tag, alias in POSITION_TAGS:
        node = nodes.get(tag, nodes.get(alias))
        positions[tag] = node_text(node) if node is not None else None
    return positions


def format_position(value: str | None) -> str:
    """区分缺失节点、空节点和实际值。"""
    return "未设置" if value is None else value or "空值"


def apply_positions(
    document: minidom.Document,
    nodes: dict[str, minidom.Element],
    positions: dict[str, int | None],
) -> dict[str, tuple[str | None, str | None]]:
    """按本次映射结果同步三项位置，并记录新增、替换和移除。"""
    changes: dict[str, tuple[str | None, str | None]] = {}
    root = document.documentElement
    for _, tag, alias in POSITION_TAGS:
        names = [name for name in (tag, alias) if name in nodes]
        value = positions.get(tag)
        new = str(value) if value is not None else None
        if not names and new is not None:
            node = document.createElement(tag)
            node.appendChild(document.createTextNode(new))
            root.appendChild(node)
            nodes[tag] = node
            changes[tag] = (None, new)
        for name in names:
            node = nodes[name]
            old = node_text(node)
            if old == new:
                continue
            if new is None:
                root.removeChild(node)
                del nodes[name]
            else:
                while node.firstChild:
                    node.removeChild(node.firstChild)
                node.appendChild(document.createTextNode(new))
            changes[name] = (old, new)
    return changes


def tmdb_identity(root: minidom.Element) -> int | None:
    """读取传统及 uniqueid 格式，要求所有 TMDb 身份均有效且一致。"""
    values = []
    for node in root.childNodes:
        if not isinstance(node, minidom.Element):
            continue
        if node.tagName == "tmdbid" or (node.tagName == "uniqueid" and node.getAttribute("type").lower() == "tmdb"):
            values.append(integer(node_text(node), minimum=1))
    if not values or any(value is None for value in values) or len(set(values)) != 1:
        return None
    return values[0]


@dataclass
class Enrichment:
    """携带原始或补全后的内容，以及可供日志和预览使用的无凭据结果。"""

    content: bytes | str
    status: str = "skipped"
    reason: str = ""
    tmdb_episode_id: int | None = None
    tvdb_episode_id: int | None = None
    mapping_source: str = ""
    changes: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    positions_after: dict[str, str | None] = field(default_factory=dict)

    @property
    def replaces_positions(self) -> bool:
        """判断有无已有位置被覆盖或移除。"""
        return any(old is not None for old, _ in self.changes.values())

    def describe_changes(self) -> str:
        """格式化新增、替换和移除的字段，供修改日志使用。"""
        return "，".join(
            f"{tag}：{format_position(old)} → {format_position(new)}"
            for tag, (old, new) in self.changes.items()
        )


class NfoEnricher:
    """为已确认的 TMDb 默认 Season 0 单集提供同一套补全规则。"""

    def __init__(self, client: Any, overrides: dict[int, EpisodeOverride] | None = None) -> None:
        """注入外部查询客户端与手动修正规则。"""
        self.client = client
        self.overrides = dict(overrides or {})

    @property
    def has_local_overrides(self) -> bool:
        """检查是否有可直接应用到基础刮削结果的位置规则。"""
        return any(override.tvdb_id is None and not override.ignore for override in self.overrides.values())

    def enrich(self, content: bytes | str, series_id: int | None, episode: int) -> Enrichment:
        """严格验证身份；所有失败均携带未改动的原始内容返回。"""
        result = Enrichment(content)
        try:
            document = parse_document(content)
            root = document.documentElement
            if root.tagName != "episodedetails":
                result.reason = "不是单集 NFO"
                return result
            nodes = children(root)
            if integer(node_text(nodes.get("season"))) != 0 or integer(node_text(nodes.get("episode")), minimum=1) != episode:
                result.reason = "NFO 季集身份与请求不一致"
                return result
            result.tmdb_episode_id = tmdb_identity(root)
            override = self.overrides.get(result.tmdb_episode_id) if result.tmdb_episode_id is not None else None
            if override is not None:
                result.mapping_source = "手动修正"
                result.tvdb_episode_id = override.tvdb_id
                if override.ignore:
                    result.reason = "已按手动规则忽略"
                    return result
            if series_id is None:
                result.reason = "扫描范围内缺少有效的 tvshow.nfo 剧集身份"
                return result
            if result.tmdb_episode_id is None:
                result.reason = "缺少有效且一致的 TMDb 单集身份"
                return result
            if override is not None and override.tvdb_id is None:
                positions = override.positions
            else:
                positions = self._lookup_positions(result, series_id, episode, override)
                if positions is None:
                    return result
            result.changes = apply_positions(document, nodes, positions)
            if not result.changes:
                result.reason = "播放位置与映射结果一致"
                return result
            for element in document.getElementsByTagName("*"):
                if any(child.nodeType == child.ELEMENT_NODE for child in element.childNodes):
                    for child in tuple(element.childNodes):
                        if child.nodeType == child.TEXT_NODE and not (child.nodeValue or "").strip():
                            element.removeChild(child)
            result.content = document.toprettyxml(indent="  ", encoding="utf-8") if isinstance(content, bytes) else document.toprettyxml(indent="  ")
            result.positions_after = read_positions(nodes)
            result.status = "updated"
            result.reason = "已更新播放位置" if result.replaces_positions else "已补全缺失播放位置"
        except LookupFailure as error:
            result.status, result.reason = "failed", str(error)
        except Exception as error:
            result.status, result.reason = "failed", f"NFO 补全失败：{type(error).__name__}"
        return result

    def _lookup_positions(
        self, result: Enrichment, series_id: int, episode: int, override: EpisodeOverride | None,
    ) -> dict[str, int | None] | None:
        """核实 TMDb 默认季集与 TVDB 归属，再合并手动指定的位置。"""
        if not self.client.configured:
            result.reason = "未配置 TMDb 或 TVDB 密钥"
            return None
        ids = self.client.episode_ids(series_id, episode)
        if integer(ids.get("id"), minimum=1) != result.tmdb_episode_id:
            result.reason = "单集 ID 与 TMDb 默认季集编号不一致；可能使用了剧集组"
            return None
        if override is None:
            result.tvdb_episode_id = integer(ids.get("tvdb_id"), minimum=1)
            if result.tvdb_episode_id is not None:
                result.mapping_source = "TMDb"
        if result.tvdb_episode_id is None:
            result.status, result.reason = "needs_correction", "TMDb 未提供 TVDB 单集映射"
            return None
        try:
            tvdb = self.client.episode(result.tvdb_episode_id)
        except TvdbEpisodeNotFound as error:
            if override is None:
                self.client.invalidate_episode_mapping(series_id, episode, ids)
            result.status, result.reason = "needs_correction", f"{error}，可配置手动映射修正"
            return None
        if not tvdb:
            result.status, result.reason = "needs_correction", "TVDB 未返回单集数据"
            return None
        if integer(tvdb.get("id"), minimum=1) != result.tvdb_episode_id:
            result.status, result.reason = "needs_correction", "TVDB 返回了不同的单集身份"
            return None
        show_id = integer(self.client.series_ids(series_id).get("tvdb_id"), minimum=1)
        if show_id is None or integer(tvdb.get("seriesId"), minimum=1) != show_id:
            result.status, result.reason = "needs_correction", "无法确认 TVDB 单集属于当前剧集，已拒绝补全"
            return None
        positions = {tag: integer(tvdb.get(source)) for source, tag, _ in POSITION_TAGS}
        if override is not None:
            positions.update(override.positions)
        return positions
