# 如何将插件内容显示到仪表板？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v1.8.7+` 版本）**
- 将插件的内容显示到仪表盘，并支持定义占据的单元格大小，插件产生的仪表板仅管理员可见。
- 1. 根据插件需要展示的Widget内容规划展示内容的样式和规格，也可设计多个规格样式并提供配置项供用户选择。
- 2. 实现 `get_dashboard_meta` 方法，定义仪表板key及名称，支持一个插件有多个仪表板：
```python
def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
    """
    获取插件仪表盘元信息
    返回示例：
        [{
            "key": "dashboard1", // 仪表盘的key，在当前插件范围唯一
            "name": "仪表盘1" // 仪表盘的名称
        }, {
            "key": "dashboard2",
            "name": "仪表盘2"
        }]
    """
    pass
```
- 3. 实现 `get_dashboard` 方法，根据key返回仪表盘的详细配置信息，包括仪表盘的cols列配置（适配不同屏幕），以及仪表盘的页面配置json，具体可参考插件`站点数据统计`：
```python
def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
    """
    获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
    1、col配置参考：
    {
        "cols": 12, "md": 6
    }
    2、全局配置参考：
    {
        "refresh": 10, // 自动刷新时间，单位秒
        "border": True, // 是否显示边框，默认True，为False时取消组件边框和边距，由插件自行控制
        "title": "组件标题", // 组件标题，如有将显示该标题，否则显示插件名称
        "subtitle": "组件子标题", // 组件子标题，缺省时不展示子标题
    }
    3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/

    kwargs参数可获取的值：1、user_agent：浏览器UA

    :param key: 仪表盘key，根据指定的key返回相应的仪表盘数据，缺省时返回一个固定的仪表盘数据（兼容旧版）
    """
    pass
```
