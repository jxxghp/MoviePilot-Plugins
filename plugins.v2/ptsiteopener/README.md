# PT 站点自动打开

这是一个 MoviePilot V2 插件。它从 MoviePilot 的站点配置中读取已启用站点，通过远程 Chrome DevTools Protocol 打开站点页面，不读取 Chrome 书签。

## 配置

- `远程 CDP 地址`：默认 `http://music.lulin.fun:5656/json/version`。
- `开启通知推送`：开启后，计划执行和手动执行完成时通过 MoviePilot 通知渠道推送结果，默认关闭。
- `复用站点 Cookie`：默认开启。打开站点前使用 MoviePilot 站点管理中保存的 Cookie，以便复用站点登录状态。
- `计划任务 Cron`：5 段 Cron 表达式，默认 `0 */6 * * *`，即每 6 小时执行一次。
- `标签页保留时间`：默认 5 分钟，到期后只关闭本插件本次创建的标签页。
- `站点范围`：默认打开全部启用站点，也可以切换为指定启用站点。
- `立即执行`：不等待 Cron，直接执行一次当前配置的站点打开任务。

Cookie 注入失败时会记录 MoviePilot 告警日志；开启通知推送后，还会发送站点、地址和失败原因通知，但不会输出 Cookie 内容。注入失败不会阻止站点继续打开。

示例：

```text
0 8,20 * * *
```

表示每天 08:00 和 20:00 执行。

## 依赖

插件目录中的 `requirements.txt` 需要安装 `websocket-client`。`apscheduler`、MoviePilot 数据库和插件基类由 MoviePilot V2 宿主提供。
