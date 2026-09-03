# MoviePilot V2 插件迁移到 V3

本文是迁移专题，不是从零开发插件的主入口。开发新的 V3 插件，请先阅读
[MoviePilot 插件开发指南（V3）](./Plugin_Development.md)。

本专题面向需要在 MoviePilot V3 中继续调用媒体识别、搜索、订阅、下载、整理、
刮削、媒体库或中心服务能力的旧插件作者。V3 将通用媒体主身份统一为
`MediaSource` 来源标识和来源原生 `media_id`，同时收紧数据库事务边界，调整了音乐
链职责和普通 REST 响应结构，并对后端模块重新分层。`MediaSource` 为内置来源提供
枚举常量，也允许插件注册新的来源标识，不是只能使用主程序当前列出的来源；已登记的
旧模块导入由宿主兼容层继续承接，新代码则应优先依赖稳定 SDK。

如果插件完全不读取媒体身份、不调用上述链路、不直接访问数据库，也不通过 HTTP 调用
宿主接口，通常无需为本次合同变化建立 V3 专用副本。

## 1. 先判断旧插件是否需要 V3 专用实现

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

## 2. 旧导入路径兼容与迁移

MoviePilot V3 对后端模块重新分层后，`app.core`、`app.helper` 和 `app.utils`
不再是物理源码目录。宿主提供精确的旧导入兼容层：映射表中已经登记的旧路径
仍可导入，并会绑定到新位置上的同一个模块对象。因此，插件不会仅仅因为这些
文件被移动就必须立即发布新版本。

兼容层不是通配转发，也不会根据类名猜测新位置。未登记的旧模块仍会抛出
`ModuleNotFoundError`；兼容层也不代表旧路径会永久作为新插件 API。新代码应优先
依赖 `app.sdk` 提供的稳定出口，避免继续耦合宿主的 `application`、`domain`、
`foundation`、`adapters` 或 `runtime` 内部布局。

例如，以下旧代码目前仍可运行：

```python
from app.core.config import settings
from app.core.event import EventManager
from app.utils.string import StringUtils
```

插件维护时应改为：

```python
from app.sdk.config import settings
from app.sdk.events import EventManager
from app.sdk.utilities import StringUtils
```

仅出现旧导入 Debug 警告，不代表必须建立 V3 专用副本。如果同一份插件代码仍需
运行在尚未提供这些 SDK 出口的 V2 宿主，可以暂时保留已登记的旧路径，并把警告
视为明确的兼容债务；不要通过拼接模块名或非字面量动态导入来隐藏警告。插件已经
是 V3 专用实现，或最低系统版本已提升到 V3 时，再统一迁移到 SDK。

常用迁移方向如下。具体符号是否公开，以对应 SDK 模块的 `__all__` 为准：

| 旧导入类别 | 插件推荐入口 |
| --- | --- |
| `app.log` | `app.sdk.logging` |
| `app.core.config` | `app.sdk.config` |
| `app.core.event` | `app.sdk.events` |
| `app.core.cache` | `app.sdk.cache` |
| `app.core.module`、`app.core.plugin` | `app.sdk.plugins` |
| `app.core.context`、`app.core.meta*`、`app.core.metainfo`、`app.utils.media`、`app.utils.tokens` | `app.sdk.media` |
| `app.utils.string`、`app.domain.string` 以及常用加密、DOM、反射、OTP、单例、系统和定时工具 | `app.sdk.utilities` |
| `app.utils.http`、`app.utils.ip`、`app.utils.url`、`app.utils.security`、`app.utils.site`、`app.utils.web` | `app.sdk.network` |
| 下载器、媒体服务器、通知、规则、存储、系统状态及服务发现类 Helper | `app.sdk.services` |
| `app.helper.browser`（PlaywrightHelper 等浏览器操作） | `app.sdk.browser` |

`StringUtils` 的实现已经按文本、容量、时间、URL、DOM、媒体标题、剧集、站点和
种子等职责拆分；这些内部实现位置不是插件合同。插件若仍需要历史的完整静态方法
集合，应统一从 `app.sdk.utilities` 导入 `StringUtils`。旧的
`app.utils.string` 和 `app.domain.string` 会映射到同一个 SDK 兼容门面，方法名、
旧关键字参数和常见边缘行为均继续保留。

### 2.1 处理 Debug 兼容警告

当宿主启用 `DEBUG=true` 时，插件加载器会记录运行时命中的旧导入，并扫描插件
Python 源码，输出类似下面的警告：

```text
[兼容导入] 插件 MyPlugin（__init__.py:12）使用旧路径 app.utils.string，已映射到 app.sdk.string；请迁移到 app.sdk.utilities
```

源码扫描用于补足模块已被其他插件加载、Python 直接复用 `sys.modules` 而不再触发
导入钩子的情况。警告会按插件和旧路径去重；生产模式保持静默，不会因为警告阻止
插件加载。

处理警告时遵循以下顺序：

1. 按警告末尾给出的推荐路径修改导入，不要从实际内部目标路径反向导入。
2. 只迁移插件实际使用的符号；不要为了消除警告复制宿主实现或创建自己的兼容包。
3. 在 `DEBUG=true` 的 V3 宿主中重新加载插件，确认该插件不再产生旧导入警告。
4. 再执行插件原有功能回归；导入成功只说明路径兼容，不代表调用参数或返回合同未变化。

完整兼容清单以 MoviePilot 主仓库的
[`app/runtime/compat/manifest.py`](https://github.com/jxxghp/MoviePilot/blob/v3/app/runtime/compat/manifest.py)
为准。插件仓文档只维护迁移原则和稳定 SDK 入口，不复制整份映射表。

## 3. 通用媒体身份合同

### 3.1 内置枚举与插件扩展来源

使用内置来源时应从宿主导入枚举，不要自行维护内置字符串集合：

```python
from app.schemas.types import MediaSource
```

当前内置常量如下；该表不是插件来源白名单：

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

插件提供新数据源时，使用全局稳定的扩展标识构造同一类型：

```python
from app.schemas.types import MediaSource

PLUGIN_SOURCE = MediaSource("acmevideo")
```

扩展标识必须以小写字母开头，只能包含小写字母、数字、点、下划线或短横线，
最长 64 个字符；发布后不能随显示名称或 API 地址变化。建议使用能避免与其他
插件冲突的品牌或插件命名空间，例如 `acmevideo` 或 `acme.video`。不要修改宿主
枚举源码来增加插件来源，宿主会把合法扩展标识解析为动态 `MediaSource` 成员。

`media_source` 与 `media_id` 是一个不可拆分的身份对：两者必须同时为空，或
同时有效。空字符串、格式非法的来源和字符串 `"0"` 都不是有效身份。不要把
枚举名 `TMDB` 当成传输值；内置与扩展成员序列化时都使用 `media_source.value`。

插件注册探索来源时，`DiscoverMediaSource.media_source` 使用上述扩展成员；旧版
`mediaid_prefix` 可以继续传入同一个稳定标识，V3 模型会在缺少其中一项时双向
补齐：

```python
source = schemas.DiscoverMediaSource(
    name="Acme Video",
    media_source=PLUGIN_SOURCE,
    api_path="plugin/AcmeVideo/discover",
)
```

插件返回的每个 `MediaInfo` 也必须使用同一 `PLUGIN_SOURCE` 和该来源原生
`media_id`。如需参与跨源转换，实现 `ChainEventType.MediaRecognizeConvert`，读取
`event.event_data.media_source`、`media_id` 和 `target_media_source`，再把带目标
身份的结果写入 `media_dict`。`MediaChain.convert_media_identity()` 对内置转换
无匹配时会继续分派该插件事件。

插件提供音乐元数据源时，不需要修改宿主的音乐来源集合。按能力注册现有插件
模块端口即可：搜索实现 `search_music`（异步插件方法也可直接实现为协程），识别
实现 `recognize_media` / `async_recognize_media`，专辑和艺术家详情按需实现
`music_album`、`music_album_related`、`music_artist`、`music_artist_albums`、
`music_artist_related`。这些端口都接收同一扩展 `media_source`；插件只处理自身
来源并返回带完整 `media_source`、`media_id` 的 `MusicInfo`、`MusicAlbumInfo` 或
`MusicArtistInfo`。通用搜索与详情 REST 路由会把合法扩展来源原样传给这些端口；
MusicBrainz 榜单、豆瓣音乐分类等来源专属浏览接口不属于扩展入口。

### 3.2 调用通用链路

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

### 3.3 规范化、复合键和来源转换

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

### 3.4 常用替换速查

| 旧写法 | V3 写法 |
| --- | --- |
| 通用对象中只保存 `tmdbid` / `doubanid` | 同时保存 `media_source` / `media_id` |
| `search_by_id(tmdbid=..., doubanid=...)` | `search_by_id(media_source=..., media_id=...)` |
| `get_tmdbinfo_by_doubanid(doubanid)` | `convert_media_identity(target_source=MediaSource.TMDB, media_source=MediaSource.Douban, media_id=...)` |
| `MediaChain.scrape_metadata(...)` | `ScrapingChain.scrape_metadata(...)` |
| `MusicChain.*` | 按职责使用 `MediaChain`、`RecommendChain`、`SearchChain`、`ScrapingChain` 或来源链 |
| 用裸 ID 查询下载/整理历史 | `get_by_media_identity(media_source, media_id, ...)` |
| 从普通 REST 顶层读取业务字段 | 从统一 envelope 的 `data` 读取 |

## 4. 插件自有数据的迁移

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
6. 迁移必须可重复执行，并覆盖 `None`、空白、`"0"`、格式非法来源、半对和
   目标 key 已存在等情况；合法的插件扩展来源必须原样保留。

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

## 5. 数据库访问与事务变化

V2 插件常见的数据库写法包括直接导入宿主 Model、调用 Model 的无会话 CRUD、使用
`SessionFactory` 自行创建会话，或把 `@db_query` / `@db_update` 装饰在宿主 Model
操作上。V3 已将宿主 Model 和 Base 改为显式 Session 原语：它们只在调用方事务内查询
或暂存，不再自行创建、提交、回滚或关闭事务。

迁移时按以下规则处理：

| V2 写法 | V3 写法 |
| --- | --- |
| 直接导入 `app.db.models.*` 查询或写入宿主表 | 使用对应 `app.db.oper.<entity>`，优先使用已有 Chain / SDK |
| `Model.get(id)`、`model.update(payload)` 等无会话调用 | 不再从插件调用宿主 Model；改用 Oper 的公开方法 |
| 插件导入 `SessionFactory` / `AsyncSessionFactory` / `ScopedSession` | 删除裸会话工厂依赖，由 Oper 或公共事务装饰器管理会话 |
| `@db_query` / `@db_update` 操作宿主 Model | 改用宿主 Oper；四个装饰器只用于插件自有表 |
| SQLAlchemy 1.x 注解或依赖 `__allow_unmapped__` | 自有表改用 SQLAlchemy 2.0 `Mapped` / `mapped_column()` |
| 返回会话绑定的 ORM 对象后再读取懒加载字段 | 在装饰器结束前转换为列表、标量或 DTO/字典 |

宿主 Oper 在未传 Session 时仍保留插件兼容行为，但每次调用各自拥有事务。不要为了把
多个调用拼成一个事务而重新引入裸 Session；涉及多个宿主写入且要求原子性时，应改用
宿主已有业务入口，或先在主仓增加明确的应用服务。

插件配置、少量结构化状态和文件仍优先使用 `_PluginBase` 的 `update_config()`、
`save_data()` 和 `get_data_path()`。只有确实需要独立索引、筛选或大量记录时才建立插件
自有表，并使用 `Base`、`db_query`、`db_update`、`async_db_query`、
`async_db_update`。完整示例和建表迁移要求见
[V3 开发指南的数据库章节](./Plugin_Development.md#73-数据库访问与-v3-事务规则)。

旧代码即使当前仍能导入宿主 Model 或裸会话工厂，也只代表兼容实现尚未删除，不代表
它们仍是 V3 插件合同。迁移完成后应在真实 V3 宿主中覆盖查询、成功写入、异常回滚、
异步调用和插件重载场景。

## 6. 链职责变化

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

## 7. 普通 REST 响应合同

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

插件通过 `get_api()` 注册的路由不进入宿主统一响应路由，宿主不会隐式包装插件
返回值。插件可直接返回业务模型，也可显式返回 `app.schemas.Response[T]`；路由的
`response_model` 必须与所选结构一致。接入宿主探索、推荐等普通数据页面的接口应
显式使用 envelope，因为这些页面按宿主普通 JSON 合同读取 `data`。

Vue 远程组件应使用宿主注入的 `api` 属性或 `window.MoviePilotAPI`。该客户端会
原样返回插件 payload；下例插件显式选择 envelope，因此业务对象位于 `data`：

```javascript
const response = await window.MoviePilotAPI.get('plugin/MyPlugin/items')
if (response.success) {
  items.value = response.data
}
```

注入客户端的 `baseURL` 已包含 `/api/v1/`。默认错误 Toast 也由宿主统一处理，
远程组件不要再为同一次失败重复提示。

## 8. 明确保留来源专用 ID 的边界

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

## 9. 两个不参与统一的用户格式

以下两个用户配置继续保留历史来源专用 ID 格式：

1. 自定义识别词中的强制识别标签：
   `{[tmdbid=xxx;type=movie/tv;s=xxx;e=xxx]}`，以及 `doubanid`、
   `bangumiid`、`anilistid`。
2. 文件重命名 Jinja2 变量：`tmdbid`、`imdbid`、`doubanid` 等既有变量。

不要把它们改成 `media_source` / `media_id`。曾经出现过的统一字段格式没有正式
发布，因此插件不需要为该短暂格式增加兼容解析或配置迁移。

## 10. 发布前检查清单

- 通用方法调用、事件载荷、任务模型和插件数据只使用成对的
  `media_source` / `media_id`。
- 新增代码优先从 `app.sdk` 导入宿主能力；在 `DEBUG=true` 的 V3 宿主中加载时，
  插件不再产生能够迁移的旧导入警告。
- 不直接依赖 `app.sdk._legacy`，也不新增 `app.core.*`、`app.helper.*`、
  `app.utils.*` 旧路径导入。
- 内置来源使用 `MediaSource` 常量；插件来源使用稳定的扩展成员；ID 在持久化与
  比较前转换为规范字符串。
- 半对、空白、格式非法来源和 `"0"` 不会进入缓存、数据库或插件数据，合法
  插件来源不会被内置列表过滤。
- 插件自有数据迁移幂等，且不会先删旧数据再保存新数据。
- 不直接访问宿主 Model，也不依赖 `SessionFactory`、`AsyncSessionFactory` 或
  `ScopedSession`；宿主数据使用 Oper、Chain 或稳定 SDK。
- `db_query` / `db_update` 及异步变体只操作插件自有表；查询结果在会话释放前完成
  物化，自有表结构迁移可重复运行并经过备份验证。
- 已移除 `MusicChain` 导入，并按职责使用 `MediaChain`、`RecommendChain`、
  `SearchChain`、`ScrapingChain` 或来源链。
- 调用宿主普通 REST API 时按统一 envelope 读取 `success`、`message`、`data`；
  调用插件自有 API 时按该 endpoint 声明的裸数据或 envelope 合同解析。
- `get_api()` 的普通 JSON endpoint 声明与实际结构一致的输出模型，且不依赖宿主
  隐式包装。
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
