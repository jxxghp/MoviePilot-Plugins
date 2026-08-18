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


def get_module(self) -> dict:
    """注册来源相关的模块方法。"""
    return {
        "recognize_media": self.recognize_media,
        "search_medias": self.search_medias,
        "metadata_nfo": self.metadata_nfo,
        "metadata_img": self.metadata_img,
    }
```

返回的每个 `MediaInfo` 必须同时包含该来源的 `media_source` 和来源原生 `media_id`。
不要把来源 ID 写入 `tmdbid`、`doubanid` 等其它来源专用字段，也不要只返回标题而省略
身份；缺少完整身份的结果会被识别链忽略。

## 3. 前端与后端行为

插件启用后，MoviePilot 会从 `/api/v1/media/source` 返回该来源。前端的搜索设置、
搜索框、手动刮削、重新识别、整理和字幕相关来源选择器会自动显示注册项；用户选择
来源后，后端会把同一个 `media_source` 继续传入搜索、识别、详情和刮削链路。

如果需要跨来源订阅或整理，实现 `ChainEventType.MediaRecognizeConvert`，读取输入的
`media_source`、`media_id` 和 `target_media_source`，并在 `media_dict` 中返回目标来源
的媒体信息。来源注册本身不会自动生成跨来源转换关系。

停用或卸载插件后，来源不会再出现在来源目录中；历史数据仍保留原始的
`media_source` 和 `media_id`，因此重新启用插件即可继续识别。
