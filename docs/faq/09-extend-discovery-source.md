# 如何扩展探索功能的媒体数据源？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v2.2.7+` 版本）**
- 探索功能仅内置`TheMovieDb`、`豆瓣`和`Bangumi`数据源，可通过插件扩展探索功能的数据源范围，按以下方法开发插件（参考`TheTVDB探索`插件）：
- 1. 实现`ChainEventType.DiscoverSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）
  
  - `name`：数据源名称
  - `media_source`：V3 规范数据源身份；内置来源使用 `MediaSource` 常量，插件
    新来源使用稳定扩展成员（例如 `MediaSource("acmevideo")`），不受当前内置
    来源列表限制。标识必须以小写字母开头，仅包含小写字母、数字、点、下划线
    或短横线，最长 64 个字符
  - `mediaid_prefix`：旧插件和前端标签使用的兼容前缀；V3 新代码只提供
    `media_source` 即可，宿主会双向补齐
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有）。探索页面使用宿主普通数据客户端，endpoint 必须显式返回并声明 `schemas.Response[List[schemas.MediaInfo]]`；宿主不会替插件包装。每个 `MediaInfo` 必须设置 `media_source` 和 `media_id`，用于唯一索引媒体详细信息和转换媒体数据
  - `filter_params`：数据源过滤参数名的字典，相关参数会传入插件API的GET请求中
  - `filter_ui`：数据过滤选项的UI配置json，与插件配置表单方式一致
  - `depends`: UI依赖关系字典Dict[str, list]，关过滤条件存在依赖关系时需要设置，以便上级条件变化时清空下级条件值

```python
class DiscoverMediaSource(BaseModel):
    """
    探索媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    media_source: MediaSource = Field(..., description="内置或插件扩展媒体来源")
    mediaid_prefix: str = Field(..., description="兼容插件使用的媒体ID前缀")
    api_path: str = Field(..., description="媒体数据源API地址")
    filter_params: Optional[Dict[str, Any]] = Field(default=None, description="过滤参数")
    filter_ui: Optional[List[dict]] = Field(default=[], description="过滤参数UI配置")

class DiscoverSourceEventData(ChainEventData):
    """
    DiscoverSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[DiscoverMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[DiscoverMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

- 2. 实现`ChainEventType.MediaRecognizeConvert`链式事件响应（**可选**，如不实现则默认按标题重新识别媒体信息），根据规范输入身份与目标来源返回对应媒体数据，并将结果注入事件数据`media_dict`中。通用转换也可参考 `MediaChain.convert_media_identity()`。

  - `media_source`：输入的内置或插件扩展媒体来源
  - `media_id`：输入来源原生 ID
  - `target_media_source`：目标的内置或插件扩展媒体来源
  - `media_dict`：转换后的目标来源媒体数据；能够确定目标身份时同时写入目标
    `media_source` 和 `media_id`

```python
class MediaRecognizeConvertEventData(ChainEventData):
    """
    MediaRecognizeConvert 事件的数据模型
    Attributes:
        # 输入参数
        media_source (MediaSource): 输入媒体来源
        media_id (str): 输入来源原生 ID
        target_media_source (MediaSource): 目标媒体来源
        # 输出参数
        media_dict (dict): TheMovieDb/豆瓣的媒体数据
    """
    # 输入参数
    media_source: MediaSource = Field(..., description="媒体来源")
    media_id: str = Field(..., description="数据源原生 ID")
    target_media_source: MediaSource = Field(..., description="目标媒体来源")
    # 输出参数
    media_dict: dict = Field(default=dict, description="转换后的媒体信息（TheMovieDb/豆瓣）")
```
- 3. 启用插件后，点击探索功能将自动生成额外的数据源标签及页面，页面中选择不同的过滤条件时会重新触发API请求。

V3 新插件应直接按以上统一字段实现；`mediaid_prefix` 仅用于读取尚未升级的已安装
插件。完整迁移和单源例外见 [V2 插件迁移到 V3](../V3_Plugin_Adaptation.md)。
