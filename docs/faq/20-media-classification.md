# 20. 如何让媒体来源接入自动分类？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

MoviePilot V3 的自动分类支持电影、电视剧和音乐，也支持内置来源与插件来源。
插件不需要读取或修改 `category.yaml`。只要来源返回标准媒体信息，主程序就会把这些信息交给统一的分类规则。

来源注册和协议版本的完整说明见 [如何通过插件注册媒体数据源？](19-register-media-source.md)。本文只列出接入分类时最容易遗漏的内容。

## 1. 先返回完整的标准媒体信息

来源识别结果至少要包含来源自己的 `media_source` 和 `media_id`，并尽量返回下面这些字段：

- 影视：标题、年份、语言、国家或地区、风格、内容分级。
- 音乐：音乐类型、专辑类型、年份、流派、标签、艺术家和发行状态。

这些字段会自动参与分类。不要把来源自己的编号写进 `tmdbid`、`doubanid` 等其它来源字段；不同来源的编号必须各自保留。

```python
return schemas.MediaInfo(
    type=MediaType.MOVIE,
    title="示例电影",
    media_source=MediaSource("acme.video"),
    media_id="acme-123",
    genres=[{"name": "动画"}],
    origin_country=["JP"],
)
```

## 2. 需要来源专有条件时，声明一个扩展字段

如果规则需要使用“发行渠道”“节目分区”这类标准字段之外的信息，可以在来源描述中声明字段：

```python
from app import schemas


def get_media_source(self) -> list[dict]:
    """声明来源名称、支持的媒体类型和来源专有分类字段。"""
    return [
        schemas.MediaSourceInfo(
            name="Acme Video",
            media_source=MediaSource("acme.video"),
            media_types=[MediaType.MOVIE, MediaType.TV],
            classification_fields=[
                schemas.ClassificationFieldDefinition(
                    id="extensions.acme.video.release_channel",
                    label="发行渠道",
                    value_type="enum",
                    operators=["equals", "in"],
                    media_types=[MediaType.MOVIE, MediaType.TV],
                    options=["院线", "网络", "电视"],
                    allow_custom_values=False,
                )
            ],
        ).model_dump()
    ]
```

识别结果用同一个字段编号返回值：

```python
classification_facts={
    "extensions.acme.video.release_channel": "网络",
}
```

字段编号必须以 `extensions.<来源编号>.` 开头，只能使用自己来源的命名空间。字段名称要写成用户能理解的文字，不能覆盖
`identity.*`、`media.*` 或 `music.*`。值只能是字符串、数字、布尔值、空值或这些值组成的列表。

管理员在“设置 → 目录 → 自动分类策略 → 规则”中就能选择这个字段；预览时搜索并选择媒体，不需要手工填写字段值。

## 3. 能补充其它来源的缺失信息时，再注册补充方法

如果插件能通过精确的外部编号确认同一媒体，并能补充国家、风格或音乐信息，可以实现
`get_media_classification_facts`。只有管理员选择“补充缺少的信息”后，主程序才会调用它。

```python
def get_media_classification_facts(self, *, request):
    """只按精确外部编号补充请求中缺失的标准分类信息。"""
    external_id = request.external_ids.get("imdb")
    if not external_id:
        return None

    detail = query_acme_by_imdb_id(external_id, timeout=request.timeout_seconds)
    if detail is None or str(detail.imdb_id) != external_id:
        return None

    available = {
        "media.countries": list(detail.country_codes),
        "media.genre_names": list(detail.genre_names),
    }
    return schemas.ClassificationEnrichmentResponse(
        media_source="acme.video",
        match=schemas.ClassificationEnrichmentMatch(
            kind="external_id",
            media_source="imdb",
            media_id=external_id,
        ),
        facts={
            field: available[field]
            for field in request.missing_fields
            if field in available and available[field]
        },
    ).model_dump()
```

补充方法必须通过外部编号证明是同一媒体，不能只按标题或年份猜测。网络失败、超时或无法确认身份时返回 `None`，不要影响主来源的识别和整理。

## 4. 开发完成后的检查清单

- 来源描述中的 `name` 是页面显示名称，`media_source` 是发布后不能随意修改的来源编号。
- 识别结果同时包含 `media_source` 和 `media_id`。
- 标准媒体信息和来源扩展信息都来自当前来源，不跨来源伪造编号。
- 字段的媒体类型、值类型和操作符彼此匹配，选项文字能被普通用户理解。
- 补充信息只返回请求要求的字段，并通过精确身份匹配。
- 插件停用、卸载或旧宿主不支持分类协议时，普通搜索和识别仍能正常工作。

管理员可以在自动分类窗口中先搜索媒体查看预览，再运行影响分析，确认后发布规则。插件不需要保存分类路径，也不需要直接移动媒体文件。
