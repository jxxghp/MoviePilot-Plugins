# 19. 如何通过插件注册媒体数据源？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

插件可以注册一个稳定的媒体来源标识，让 MoviePilot 的来源选择器、媒体搜索、
名称识别、详情查询和手动刮削都使用同一组 `media_source` + `media_id` 身份。
来源注册只描述展示信息；真正的搜索、识别和刮削能力仍通过插件模块方法提供。

## 1. 声明媒体来源

在插件类中实现 `get_media_source()`，返回一个或多个来源描述：

```python
from app import schemas
from app.plugins import _PluginBase
from app.schemas.types import MediaSource, MediaType


class AcmeVideo(_PluginBase):
    """提供 Acme Video 媒体数据源。"""

    def get_media_source(self) -> list[dict]:
        """声明来源名称、稳定标识和支持的媒体类型。"""
        return [
            schemas.MediaSourceInfo(
                name="Acme Video",
                media_source=MediaSource("acme.video"),
                media_types=[MediaType.MOVIE, MediaType.TV],
            ).model_dump()
        ]
```

`media_source` 必须是全局稳定的扩展标识：以小写字母开头，只能包含小写字母、数字、
点、下划线或短横线，最长 64 个字符。发布后不要因为显示名称、接口地址或插件版本
变化而修改它。来源描述中的 `media_types` 支持 `MediaType.MOVIE`、`MediaType.TV`
和 `MediaType.MUSIC`；宿主前端会据此把来源放入对应的各类列表选项。

## 2. 提供识别、搜索和刮削实现

在 `get_module()` 中按需暴露以下方法。每个方法都应先判断 `media_source` 是否为本
插件来源，不匹配时返回 `None` 或空列表，避免拦截其它来源：

| 方法 | 用途 |
| --- | --- |
| `recognize_media` / `async_recognize_media` | 按标题或 `media_source` + `media_id` 返回 `schemas.MediaInfo` |
| `search_medias` / `async_search_medias` | 在统一媒体搜索中返回候选媒体列表 |
| `get_media_auxiliary_info` / `async_get_media_auxiliary_info` | 为已有电影或电视剧返回本来源的附加信息列表，宿主会聚合其中的别名 |
| `obtain_images` / `async_obtain_images` | 补充来源图片到媒体对象 |
| `metadata_nfo` | 生成该来源的 NFO 内容 |
| `metadata_img` | 返回 `poster`、`backdrop` 等图片 URL |

示例（识别入口）：

```python
def recognize_media(self, meta=None, media_source=None, media_id=None, **kwargs):
    """按 Acme Video 来源识别媒体。"""
    if media_source != MediaSource("acme.video"):
        return None
    # 按 media_id 查询详情，或按 meta.title / meta.year 搜索后返回唯一结果。
    return schemas.MediaInfo(
        type=MediaType.MOVIE.value,
        title="示例电影",
        media_source=MediaSource("acme.video"),
        media_id="acme-123",
    )


def get_media_auxiliary_info(self, mediainfo=None, media_source=None, **kwargs):
    """在本来源启用时返回可参与搜索和订阅匹配的别名。"""
    selected = (media_source,) if isinstance(media_source, MediaSource) else media_source
    if selected and MediaSource("acme.video") not in selected:
        return []
    # 可按 mediainfo.title / year 查询当前来源；每个 provider 必须返回列表。
    result = query_acme_video(
        title=mediainfo.title,
        year=mediainfo.year,
        media_source=MediaSource("acme.video"),
    )
    return [result] if result else []


def get_module(self) -> dict:
    """注册来源相关的模块方法。"""
    return {
        "recognize_media": self.recognize_media,
        "search_medias": self.search_medias,
        "get_media_auxiliary_info": self.get_media_auxiliary_info,
        "metadata_nfo": self.metadata_nfo,
        "metadata_img": self.metadata_img,
    }
```

返回的每个 `MediaInfo` 必须同时包含该来源的 `media_source` 和来源原生 `media_id`。
不要把来源 ID 写入 `tmdbid`、`doubanid` 等其它来源专用字段，也不要只返回标题而省略
身份；缺少完整身份的结果会被识别链忽略。

附加信息方法是可选能力，旧插件无需修改即可继续运行。宿主会把用户在
`SEARCH_SOURCE` 中启用的一个或多个来源传入该方法，并对所有 provider 返回的
`title`、`original_title`、`en_title`、地区标题和 `names` 做有序合集去重。插件只应
返回本来源的媒体信息，不应直接修改传入对象；分类、风格、TMDB/IMDb/TVDB 等外部
ID 仍只允许由内置 TheMovieDB provider 补充，避免跨来源字段冲突。

## 3. 前端与后端行为

插件启用后，MoviePilot 会从 `/api/v1/media/source` 返回该来源。前端的搜索设置、
搜索框、手动刮削、重新识别、整理和字幕相关来源选择器会自动显示注册项；用户选择
来源后，后端会把同一个 `media_source` 继续传入搜索、识别、详情和刮削链路。

如果需要跨来源订阅或整理，实现 `ChainEventType.MediaRecognizeConvert`，读取输入的
`media_source`、`media_id` 和 `target_media_source`，并在 `media_dict` 中返回目标来源
的媒体信息。来源注册本身不会自动生成跨来源转换关系。

停用或卸载插件后，来源不会再出现在来源目录中；历史数据仍保留原始的
`media_source` 和 `media_id`，因此重新启用插件即可继续识别。

## 4. 声明来源分类字段

MoviePilot 支持协议版本 1 后，媒体来源插件可以从稳定入口
`app.sdk.classification` 声明来源专用分类字段。插件必须先检测协议版本；旧宿主、
导入失败或声明构造失败时继续返回原有来源描述或空列表，不能让可选分类能力阻断
插件加载、搜索或识别。

```python
def _classification_source():
    """只在宿主支持分类来源协议版本 1 时构造声明。"""
    try:
        from app.sdk.classification import (
            MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION,
            ClassificationFieldDefinition,
            MediaSourceInfo,
        )
    except (ImportError, AttributeError):
        return None
    if MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION < 1:
        return None
    return MediaSourceInfo(
        name="Acme Video",
        media_source="acme.video",
        media_types=["电影", "电视剧"],
        classification_fields=[
            ClassificationFieldDefinition(
                id="extensions.acme.video.release_channel",
                label="发行渠道",
                value_type="string",
                operators=["equals", "in", "exists", "not_exists"],
                media_types=["电影", "电视剧"],
            )
        ],
    )


def get_media_source(self) -> list:
    """返回宿主当前能够理解的媒体来源声明。"""
    source = _classification_source()
    return [source] if source is not None else []
```

字段 ID 必须使用完整 `extensions.<media_source>.<field>` 命名空间，只能声明本
来源事实，不能覆盖 `identity.*`、`media.*` 或 `music.*` 标准字段。字段值仅允许
有限 JSON 标量或声明类型对应的字符串列表；封闭枚举必须同时提供稳定选项目录。
宿主会覆盖插件自行填写的所有权信息，并校验来源、媒体类型、操作符和值类型。

识别结果通过 `MediaInfo.classification_facts` 提交已经随本次来源响应取得的事实：

```python
return schemas.MediaInfo(
    type=MediaType.MOVIE,
    title="示例电影",
    media_source=MediaSource("acme.video"),
    media_id="acme-123",
    classification_facts={
        "extensions.acme.video.release_channel": "official",
    },
)
```

事实提取不得新增网络请求，也不得修改主 `media_source + media_id`。未登记、跨来源、
类型不符或插件停用后的陈旧事实会被宿主记录诊断并忽略，但不会导致识别失败。插件
禁用、停止、卸载、重载失败或声明无效时，宿主会立即撤销该运行实例的字段目录；
引用这些字段的既有策略会保留，但重新校验时会提示字段不可用。

## 5. 可选补充缺失的标准分类事实

协议版本 2 增加 `get_media_classification_facts`。它用于用户在分类策略中显式开启
`enrich_missing` 后，由其它已登记来源补充活动规则实际引用、但主来源没有提供的
`media.*` 或 `music.*` 标准事实。默认 `primary_only` 模式不会发现或调用该方法，
因此仅实现来源注册和版本 1 扩展字段的插件不需要修改。

该方法必须满足以下边界：

- 插件必须先通过 `get_media_source()` 登记响应中的 `media_source`，并检测
  `MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION >= 2` 后再注册方法。
- 方法是同步方法；宿主在同步识别中使用受控线程池，在异步识别中把同一方法放入
  有并发上限的工作线程，插件不要再返回协程。
- 只能返回 `request.missing_fields` 中的标准字段，不能返回 `identity.*`、
  `extensions.*`，也不能覆盖主来源已经存在的事实。
- 必须通过请求中已有的精确外部 ID，或插件维护的明确身份映射，证明结果属于同一
  媒体。仅按标题、年份或相似度模糊命中不够安全。
- 网络请求和内部等待必须小于 `request.timeout_seconds`；超时、异常、空结果或无效
  字段会被宿主隔离，原识别和分类仍使用已有事实继续执行。
- 宿主负责 TTL 缓存、最终字段类型校验、顺序合并和 provider 来源记录。插件不得
  修改 `request.identity`，也不得把补充来源改成新的主 `media_source + media_id`。

以下示例通过已知 TMDB ID 查询 Acme Video 的精确映射，再补充缺失的国家和来源
类型。响应事实仍使用宿主标准字段；来源自己的 `release_channel` 等字段继续使用第
4 节的版本 1 扩展事实机制。

```python
def _classification_protocol_version() -> int:
    """读取宿主公开协议版本；旧宿主按不支持处理。"""
    try:
        from app.sdk.classification import (
            MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION,
        )
    except (ImportError, AttributeError):
        return 0
    return int(MEDIA_SOURCE_CLASSIFICATION_PROTOCOL_VERSION)


def get_media_classification_facts(self, *, request):
    """按精确 TMDB 映射补充请求中的缺失标准事实。"""
    from app.sdk.classification import (
        ClassificationEnrichmentMatch,
        ClassificationEnrichmentResponse,
    )

    tmdb_id = request.external_ids.get("themoviedb")
    if not tmdb_id or request.media_type not in {"电影", "电视剧"}:
        return None
    # 客户端超时必须不大于宿主传入的剩余预算。
    detail = query_acme_by_tmdb_id(
        tmdb_id,
        timeout=request.timeout_seconds,
    )
    if detail is None or str(detail.tmdb_id) != tmdb_id:
        return None

    available = {
        "media.countries": list(detail.country_codes),
        "media.genre_names": list(detail.genre_names),
    }
    facts = {
        field_id: available[field_id]
        for field_id in request.missing_fields
        if field_id in available and available[field_id]
    }
    return ClassificationEnrichmentResponse(
        media_source="acme.video",
        match=ClassificationEnrichmentMatch(
            kind="external_id",
            media_source="themoviedb",
            media_id=tmdb_id,
        ),
        facts=facts,
    )


def get_module(self) -> dict:
    """只向支持协议版本 2 的宿主注册缺失事实补充方法。"""
    modules = {
        "recognize_media": self.recognize_media,
        "search_medias": self.search_medias,
    }
    if _classification_protocol_version() >= 2:
        modules["get_media_classification_facts"] = (
            self.get_media_classification_facts
        )
    return modules
```

当插件没有可靠外部 ID 或明确映射时，应直接返回 `None`，不要为了提高命中率使用
标题模糊搜索。插件可以返回 `kind="explicit_mapping"`，但此时 `match.media_source`
和 `match.media_id` 必须完整回指 `request.identity`，且映射关系应来自插件持久化的
确定性绑定或来源 API 的精确结果。宿主会把实际提供每个字段的 provider 名称和来源
写入预览 trace，便于用户判断规则为何命中。

## 6. 插件如何读取统一分类结果？

V3 插件不要再导入 `app.modules.themoviedb.CategoryHelper`，也不要读取或写入
`category.yaml`。宿主已经把电影、电视剧、音乐和插件媒体源收口到同一套版本化策略，
插件需要展示当前分类时应调用：

```python
from app.sdk.classification import classify_media
from app.sdk.media import MediaInfo

classified = classify_media(MediaInfo(tmdb_info=tmdb_info))
category_path = classified.library_category
```

`classify_media()` 返回隔离副本，不会修改传入对象；宿主尚未完成运行时装配时会返回
未分类副本。插件应把分类视为可选展示信息，不能因分类缺失阻断通知、搜索或整理主流程。
旧 `CategoryHelper` 仅保留只读导入兼容，`save()` 永远拒绝写入，后续版本会移除该兼容
符号。
