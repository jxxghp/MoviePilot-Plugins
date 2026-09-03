# 如何在插件中实现远程命令响应？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

- 实现 `get_command()` 方法，按以下格式返回命令列表：
    ```json
    [{
        "cmd": "/douban_sync", // 动作ID，必须以/开始
        "event": EventType.PluginAction,// 事件类型，固定值
        "desc": "命令名称",
        "category": "命令菜单（微信）",
        "data": {
            "action": "douban_sync" // 动作标识
        }
    }]
    ```

- 注册 `PluginAction` 事件响应，根据 `event_data.action` 是否为插件设定的动作标识来判断是否为本插件事件：

    注册事件：
    ```python
    @eventmanager.register(EventType.PluginAction)
    ```
    
    事件判定：
    ```python
    event_data = event.event_data
    if not event_data or event_data.get("action") != "douban_sync":
        return
    ```
