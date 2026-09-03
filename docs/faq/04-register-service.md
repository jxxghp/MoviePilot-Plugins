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
