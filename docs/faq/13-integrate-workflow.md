# 如何将插件功能集成到工作流？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 v2.4.8+ 版本）**
- 插件实现以下接口，声明插件支持的动作实现
```python
def get_actions(self) -> List[Dict[str, Any]]:
    """
    获取插件工作流动作
    [{
        "id": "动作ID",
        "name": "动作名称",
        "func": self.xxx,
        "kwargs": {} # 需要附加传递的参数
    }]

    对实现函数的要求：
    1、函数的第一个参数固定为 ActionContent 实例，如需要传递额外参数，在kwargs中定义
    2、函数的返回：执行状态 True / False，更新后的 ActionContent 实例
    """
    pass
```
- 编辑工作流流程，添加`调用插件`组件，选择该插件的对应动作，将插件的功能串接到工作流程中
