# 如何扩展推荐功能的媒体数据源？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v2.2.8+` 版本）**
- 实现`ChainEventType.RecommendSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）

  - `name`：数据源名称
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有）。推荐页面使用宿主普通数据客户端，endpoint 必须显式返回并声明 `schemas.Response[List[schemas.MediaInfo]]`；宿主不会替插件包装。参考 `app/api/endpoints/recommend.py`
  - `type`：前端用于分组展示的数据源类型

```python
class RecommendMediaSource(BaseModel):
    """
    推荐媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    api_path: str = Field(..., description="媒体数据源API地址")
    type: str = Field(..., description="类型")

class RecommendSourceEventData(ChainEventData):
    """
    RecommendSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[RecommendMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[RecommendMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

返回的每个 `MediaInfo` 如携带主媒体身份，必须同时提供 `media_source` 和
`media_id`。插件 endpoint 应显式返回参数化的 `schemas.Response` 模型；完整说明见
[V2 插件迁移到 V3](../V3_Plugin_Adaptation.md)。
