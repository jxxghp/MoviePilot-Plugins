# 如何在插件中注册公共定时服务？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

- 注册公共定时服务后，可以在`设定-服务`中查看运行状态和手动启动，更加便捷。
- 实现 `get_service()` 方法，按以下格式返回服务注册信息：
    ```json
    [{
        "id": "服务ID", // 不能与其它服务ID重复
        "name": "服务名称", // 显示在服务列表中的名称
        "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
        "func": self.xxx, // 服务方法
        "kwargs": {} // 定时器参数，参考APScheduler
    }]
    ```

## 一次性任务

“立即运行一次”或“事件后延迟执行”不需要注册成公共服务，也不要自建 `BackgroundScheduler`。调用 `app.sdk.scheduler.add_plugin_once_job(插件ID, 任务ID, self.xxx, 名称, delay_seconds=3, func_kwargs={})` 交给宿主调度器执行。同 ID 重复追加时替换尚未执行的旧任务，用 `remove_plugin_once_job(插件ID, 任务ID)` 取消。完整说明见 [插件开发指南 9.3](../Plugin_Development.md#93-定时服务)。
