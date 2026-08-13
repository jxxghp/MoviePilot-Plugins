# MoviePilot V3 插件适配指南

本文面向需要在 MoviePilot V3 中继续调用媒体识别、搜索、订阅、下载、整理、
刮削、媒体库或中心服务能力的插件作者。V3 将通用媒体主身份统一为
`MediaSource` 枚举和来源原生 `media_id`，同时调整了音乐链职责和普通 REST
响应结构。

如果插件完全不读取媒体身份、不调用上述链路，也不通过 HTTP 调用宿主接口，
通常无需为本次合同变化建立 V3 专用副本。

## 1. 先判断是否需要建立 V3 专用实现

V3 默认兼容 V2 插件。只有插件使用了 V3 已变更的合同，才需要进行以下处理：

1. 将 V2 实现复制到 `plugins.v3/<plugin_id_lower>/`，不要修改原
   `plugins.v2/` 实现。
2. 在 `package.v3.json` 增加 V3 条目，并声明
   `"system_version": ">=3.0.0"`。
3. 在原索引的同名条目上声明 `"v3": false`，避免 V3 回退加载旧合同实现。
4. 插件版本跃迁到来源版本的下一个主版本并归零，例如
   `2.6.1 -> 3.0.0`，不要只增加次版本或修订版本。
5. 同步修改插件类的 `plugin_version`、`package.v3.json` 的 `version`，并将
   当前版本历史置顶；全部 `history` 必须按语义版本降序排列。

未建立 V3 专用副本的 V2 插件默认兼容 V3；无需为了声明兼容而批量增加
`"v3": true`。只有确认不兼容或已有 V3 专用副本时才设置 `"v3": false`。

## 2. 通用媒体身份合同

### 2.1 固定来源枚举

插件应从宿主导入枚举，不要自行维护字符串集合：

```python
from app.schemas.types import MediaSource
```

当前固定值如下：

| 枚举 | 传输与存储值 |
| --- | --- |
| `MediaSource.TMDB` | `themoviedb` |
| `MediaSource.Douban` | `douban` |
| `MediaSource.Bangumi` | `bangumi` |
| `MediaSource.AniList` | `anilist` |
| `MediaSource.IMDb` | `imdb` |
| `MediaSource.TVDB` | `tvdb` |
| `MediaSource.MusicBrainz` | `musicbrainz` |
| `MediaSource.TheAudioDB` | `theaudiodb` |
| `MediaSource.DoubanMusic` | `doubanmusic` |
| `MediaSource.Bilibili` | `bilibili` |
| `MediaSource.MangoTV` | `mangguodiscover` |
| `MediaSource.MiguVideo` | `migu` |
| `MediaSource.TencentVideo` | `tencentvideodiscover` |

`media_source` 与 `media_id` 是一个不可拆分的身份对：两者必须同时为空，或
同时有效。空字符串、未知来源和字符串 `"0"` 都不是有效身份。不要把枚举名
`TMDB` 当成传输值；需要序列化时使用 `media_source.value`。

### 2.2 调用通用链路

旧的来源专用参数不再用于通用入口：

```python
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.schemas.types import MediaSource, MediaType

media = MediaChain().recognize_media(
    media_source=MediaSource.Douban,
    media_id="1295644",
    mtype=MediaType.MOVIE,
)
if not media:
    return []

contexts = SearchChain().search_by_id(
    media_source=media.media_source,
    media_id=media.media_id,
    mtype=media.type,
)
```

不要再调用类似下面的旧形式：

```python
# 错误：通用入口不再接收来源专用 ID 参数
SearchChain().search_by_id(tmdbid="550", doubanid=None)
```

订阅、下载任务、整理任务、识别结果、下载历史、整理历史、媒体服务器事件和
Webhook 载荷中的主身份也遵守同一字段对。插件比较身份时必须同时比较来源和
ID，不能只比较裸 `media_id`：

```python
same_media = (
    left.media_source == right.media_source
    and str(left.media_id) == str(right.media_id)
)
```

### 2.3 规范化、复合键和来源转换

统一使用宿主工具处理不可信输入：

```python
from app.schemas.types import MediaSource
from app.utils.media import (
    build_media_key,
    parse_media_key,
    resolve_media_identity,
)

media_source, media_id = resolve_media_identity(
    media_source=payload.get("media_source"),
    media_id=payload.get("media_id"),
)
if not media_source:
    return

cache_key = build_media_key(media_source, media_id)  # 例如 douban:1295644
source_from_key, id_from_key = parse_media_key(cache_key)
```

需要从一个来源转换到另一个来源时，使用统一转换入口：

```python
tmdb_info = MediaChain().convert_media_identity(
    target_source=MediaSource.TMDB,
    media_source=MediaSource.Douban,
    media_id="1295644",
    mtype=MediaType.MOVIE,
)
```

不要在插件中重新实现来源别名、复合键或跨源匹配规则。

### 2.4 常用替换速查

| 旧写法 | V3 写法 |
| --- | --- |
| 通用对象中只保存 `tmdbid` / `doubanid` | 同时保存 `media_source` / `media_id` |
| `search_by_id(tmdbid=..., doubanid=...)` | `search_by_id(media_source=..., media_id=...)` |
| `get_tmdbinfo_by_doubanid(doubanid)` | `convert_media_identity(target_source=MediaSource.TMDB, media_source=MediaSource.Douban, media_id=...)` |
| `MediaChain.scrape_metadata(...)` | `ScrapingChain.scrape_metadata(...)` |
| `MusicChain.*` | 按职责使用 `MediaChain`、`RecommendChain`、`SearchChain`、`ScrapingChain` 或来源链 |
| 用裸 ID 查询下载/整理历史 | `get_by_media_identity(media_source, media_id, ...)` |
| 从普通 REST 顶层读取业务字段 | 从统一 envelope 的 `data` 读取 |

## 3. 插件自有数据的迁移

插件新写入的数据只保存 `media_source` 和 `media_id`，不再同时保存
`tmdbid`、`doubanid`、`bangumiid` 等冗余主身份字段。推荐结构如下：

```json
{
  "media_source": "douban",
  "media_id": "1295644"
}
```

如果插件已有存量数据，应在 V3 插件初始化阶段执行幂等迁移：

1. 先通过 `resolve_media_identity()` 验证现有统一字段。
2. 现有身份无效时，再按插件历史优先级读取旧字段。
3. 只有取得完整有效身份后，才写入新字段并删除旧字段。
4. 复合 key 使用 `build_media_key()`；需要更换 key 时先保存新 key，成功后再
   删除旧 key。
5. 找不到有效回填来源时保留原记录，不要为了“清理”而丢失数据。
6. 迁移必须可重复执行，并覆盖 `None`、空白、`"0"`、未知来源、半对和目标
   key 已存在等情况。

示例：

```python
from app.schemas.types import MediaSource
from app.utils.media import resolve_media_identity

media_source, media_id = resolve_media_identity(
    media_source=item.get("media_source"),
    media_id=item.get("media_id"),
)
if not media_source:
    for legacy_source, legacy_key in (
        (MediaSource.Douban, "doubanid"),
        (MediaSource.TMDB, "tmdbid"),
    ):
        media_source, media_id = resolve_media_identity(
            media_source=legacy_source,
            media_id=item.get(legacy_key),
        )
        if media_source:
            break

if media_source:
    migrated = {
        key: value
        for key, value in item.items()
        if key not in {"doubanid", "tmdbid"}
    }
    migrated["media_source"] = media_source.value
    migrated["media_id"] = media_id
    self.update_config(migrated)
```

迁移代码读取旧字段是允许的；迁移完成后的业务流程不应继续把旧字段作为通用
主身份。

## 4. 链职责变化

`MusicChain` 已删除，插件需要按能力归属修改导入和调用：

| 旧职责或调用 | V3 入口 |
| --- | --- |
| 通用影视/音乐识别 | `MediaChain.recognize_media()` / `async_recognize_media()` |
| 音乐搜索、专辑与艺术家详情 | `MediaChain.search_music()`、`get_music_album()` 及对应异步方法 |
| 本地音乐文件、专辑目录识别 | `MediaChain.recognize_music_by_path()` 等公共识别入口 |
| 站点资源搜索 | `SearchChain` |
| 榜单、最新发行、媒体探索 | `RecommendChain` |
| 文件与目录刮削 | `ScrapingChain.scrape_metadata()` |
| MusicBrainz、豆瓣音乐等来源原子能力 | 对应的 `MusicBrainzChain`、`DoubanChain`、`TheAudioDbChain` 等来源链 |

插件不应重新创建 `MusicChain` 兼容包装，也不要让来源链反向依赖公共编排链。
歌词属于刮削流程；需要完整刮削时调用 `ScrapingChain`，不要在插件中复制歌词、
封面和标签写入逻辑。

## 5. 普通 REST 响应合同

本节只列迁移结论。后端输出模型、Python HTTP 调用、Vue 远程组件、统一 Toast、
多语言和原生响应的完整示例见
[V3 插件 API 响应适配指南](./V3_API_Response_Adaptation.md)。

MoviePilot 普通 JSON API 统一返回三个顶层字段：

```json
{
  "success": true,
  "message": "",
  "data": {}
}
```

通过 Python HTTP 客户端调用宿主 REST API 时，业务数据从 `data` 读取，错误
使用 HTTP 状态码以及顶层 `message`。不要继续从 `message` 读取业务对象，也
不要依赖旧的额外顶层字段。SSE、文件、图片、HTML、OAuth2、OpenAI、
Anthropic 和 MCP JSON-RPC 等标准协议端点保持各自原生响应。

插件通过 `get_api()` 注册的普通 JSON endpoint 同样由宿主自动包装。endpoint
直接返回业务对象即可；需要显式返回操作结果时使用宿主的
`app.schemas.Response`。不要手工返回一个普通 `{success, message, data}` 字典，
否则它会再次进入自动包装并形成双层 `data`。

Vue 远程组件应使用宿主注入的 `api` 属性或 `window.MoviePilotAPI`。该客户端为
插件保留完整 envelope，因此返回值本身是 `{ success, message, data }`，业务
对象位于其 `data` 字段：

```javascript
const response = await window.MoviePilotAPI.get('plugin/MyPlugin/items')
if (response.success) {
  items.value = response.data
}
```

注入客户端的 `baseURL` 已包含 `/api/v1/`。默认错误 Toast 也由宿主统一处理，
远程组件不要再为同一次失败重复提示。

## 6. 明确保留来源专用 ID 的边界

统一身份合同针对通用业务链路，不要求抹掉真实的单数据源协议：

- `TmdbChain`、`DoubanChain`、`BangumiChain`、`AniListChain` 等明确来源链的原子
  方法可以继续接收该来源原生 ID。
- `/tmdb`、`/douban`、`/bangumi`、`/anilist` 等明确单源 API，以及 TMDB 剧集、
  剧集组、排期等固定单源能力，继续使用其原生参数。
- NFO `uniqueid`、Emby/Jellyfin/Plex `ProviderIds`、外部服务 URL 和跨源映射
  辅助字段仍按外部协议读写。
- `MediaInfo` 中的 `tmdb_id`、`imdb_id` 等可作为辅助输出或单源调用参数，但不
  能替代通用链路的主身份对。
- 搜索策略字段（例如是否使用 IMDb 关键字搜索）不是媒体主身份字段。

调用明确单源接口前，应先判断统一主身份是否属于该来源；如果只有跨源辅助 ID，
需明确这是单源适配行为，不能静默改写对象的主身份。

## 7. 两个不参与统一的用户格式

以下两个用户配置继续保留历史来源专用 ID 格式：

1. 自定义识别词中的强制识别标签：
   `{[tmdbid=xxx;type=movie/tv;s=xxx;e=xxx]}`，以及 `doubanid`、
   `bangumiid`、`anilistid`。
2. 文件重命名 Jinja2 变量：`tmdbid`、`imdbid`、`doubanid` 等既有变量。

不要把它们改成 `media_source` / `media_id`。曾经出现过的统一字段格式没有正式
发布，因此插件不需要为该短暂格式增加兼容解析或配置迁移。

## 8. 发布前检查清单

- 通用方法调用、事件载荷、任务模型和插件数据只使用成对的
  `media_source` / `media_id`。
- 来源使用 `MediaSource` 枚举；ID 在持久化与比较前转换为规范字符串。
- 半对、空白、未知来源和 `"0"` 不会进入缓存、数据库或插件数据。
- 插件自有数据迁移幂等，且不会先删旧数据再保存新数据。
- 已移除 `MusicChain` 导入，并按职责使用 `MediaChain`、`RecommendChain`、
  `SearchChain`、`ScrapingChain` 或来源链。
- REST 调用按统一 envelope 读取 `success`、`message`、`data`。
- `get_api()` 的普通 JSON endpoint 声明具体输出模型，且没有手工双层套壳。
- Vue 远程组件使用相对 API 路径，并避免重复错误 Toast。
- 自定义识别词和重命名格式仍使用历史来源专用 ID。
- V3 专用副本位于 `plugins.v3/`，版本完成主版本跃迁，且声明
  `system_version: ">=3.0.0"`。
- 原 V1/V2 代码未被顺手修改；旧索引仅在对应条目增加 `"v3": false`。
- 代码、索引和历史版本一致，历史按语义版本降序排列。

建议至少执行：

```bash
python3 -m compileall plugins.v3/myplugin
python3 .github/scripts/check_plugin_versions.py \
  package.json package.v2.json package.v3.json
git diff --check
```

涉及存量数据迁移、事件载荷或 Vue 远程组件时，还应在 MoviePilot V3 宿主环境
补充聚焦测试和真实加载验证。
