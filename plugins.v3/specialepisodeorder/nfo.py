"""特典身份校验与 NFO 补全；仅修改缺失的播放位置字段。"""

import re
from dataclasses import dataclass, field
from typing import Any
from xml.dom import minidom

from .client import LookupFailure


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


def parse_overrides(text: str) -> dict[int, int]:
    """解析每行 TMDb 单集 ID=TVDB 单集 ID；拒绝冲突或无效配置。"""
    result: dict[int, int] = {}
    for index, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("=")
        if len(parts) != 2:
            raise ValueError(f"手动映射第 {index} 行格式应为 TMDb单集ID=TVDB单集ID")
        source, target = (integer(part, minimum=1) for part in parts)
        if source is None or target is None or (source in result and result[source] != target):
            raise ValueError(f"手动映射第 {index} 行 ID 无效或与已有配置冲突")
        result[source] = target
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
    added: dict[str, int] = field(default_factory=dict)

    def describe_changes(self) -> str:
        """格式化实际新增字段，供 NFO 修改日志使用。"""
        return "，".join(f"{tag}：未设置 → {value}" for tag, value in self.added.items())


class NfoEnricher:
    """为已确认的 TMDb 默认 Season 0 单集提供同一套补全规则。"""

    def __init__(self, client: Any, overrides: dict[int, int] | None = None) -> None:
        """注入外部查询客户端与人工核实的映射。"""
        self.client = client
        self.overrides = dict(overrides or {})

    def enrich(self, content: bytes | str, series_id: int, episode: int) -> Enrichment:
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
            if all(tag in nodes or alias in nodes for _, tag, alias in POSITION_TAGS):
                result.reason = "播放位置字段已齐全"
                return result
            result.tmdb_episode_id = tmdb_identity(root)
            if result.tmdb_episode_id is None:
                result.reason = "缺少有效且一致的 TMDb 单集身份"
                return result
            if not self.client.configured:
                result.reason = "未配置 TMDb 或 TVDB 密钥"
                return result
            ids = self.client.episode_ids(series_id, episode)
            if integer(ids.get("id"), minimum=1) != result.tmdb_episode_id:
                result.reason = "单集 ID 与 TMDb 默认季集编号不一致；可能使用了剧集组"
                return result
            result.tvdb_episode_id = self.overrides.get(result.tmdb_episode_id)
            if result.tvdb_episode_id is not None:
                result.mapping_source = "手动修正"
            else:
                result.tvdb_episode_id = integer(ids.get("tvdb_id"), minimum=1)
                if result.tvdb_episode_id is not None:
                    result.mapping_source = "TMDb"
            if result.tvdb_episode_id is None:
                result.reason = "TMDb 未提供 TVDB 单集映射"
                return result
            tvdb = self.client.episode(result.tvdb_episode_id)
            if not tvdb:
                result.reason = "TVDB 单集不存在（404），可配置手动映射修正"
                return result
            if integer(tvdb.get("id"), minimum=1) != result.tvdb_episode_id:
                result.reason = "TVDB 返回了不同的单集身份"
                return result
            show_ids = self.client.series_ids(series_id)
            show_id = integer(show_ids.get("tvdb_id"), minimum=1)
            if show_id is None or integer(tvdb.get("seriesId"), minimum=1) != show_id:
                result.reason = "无法确认 TVDB 单集属于当前剧集，已拒绝补全"
                return result
            for source, tag, alias in POSITION_TAGS:
                value = integer(tvdb.get(source))
                if tag in nodes or alias in nodes or value is None:
                    continue
                node = document.createElement(tag)
                node.appendChild(document.createTextNode(str(value)))
                root.appendChild(node)
                result.added[tag] = value
            if not result.added:
                result.reason = "TVDB 无可补全位置或已有位置无需修改"
                return result
            for element in document.getElementsByTagName("*"):
                if any(child.nodeType == child.ELEMENT_NODE for child in element.childNodes):
                    for child in tuple(element.childNodes):
                        if child.nodeType == child.TEXT_NODE and not (child.nodeValue or "").strip():
                            element.removeChild(child)
            result.content = document.toprettyxml(indent="  ", encoding="utf-8") if isinstance(content, bytes) else document.toprettyxml(indent="  ")
            result.status, result.reason = "updated", "已补全缺失播放位置"
        except LookupFailure as error:
            result.status, result.reason = "failed", str(error)
        except Exception as error:
            result.status, result.reason = "failed", f"NFO 补全失败：{type(error).__name__}"
        return result
