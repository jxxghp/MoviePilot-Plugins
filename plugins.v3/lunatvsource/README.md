# LunaTV 资源订阅（MoviePilot V3）

接入 MoonTV/LunaTV 的 Apple CMS 资源站，优先复用 MoviePilot 原生探索、搜索、订阅、目录、TMDB、整理和媒体库链路。插件只负责源适配、串行下载与任务状态。

## 使用要点

- 订阅地址内的资源站默认全部读取；目录复用 MoviePilot 的本地目录设置，不再重复配置白名单或下载路径。
- 队列严格串行，MoviePilot 重启后会恢复中断任务，不会并行下载。
- 片名自动读取 MoviePilot 智能助手（DeepSeek 等 OpenAI 兼容模型），未配置或失败时自动回退规则清理。
- 搜索结果默认选中 TMDB 关联，也可以重新搜索候选并手动切换；多季合集会按所选作品的季集数安全映射。
- 在 MoviePilot 原生“探索”中选择 `LunaTV / 苹果 CMS` 搜索并创建订阅；不增加独立订阅导航，工作台仅用于诊断、排队和状态，不内置 m3u8 播放器。
- 目录、智能助手、TMDB、整理规则、媒体服务器和链接权限无需在插件中重复配置；媒体库同步沿用 MoviePilot 已启用的服务器设置。
- 插件不会绕过 DRM、登录保护或付费限制，请只使用你有权访问的资源源。

默认配置地址：

```text
https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json
```

建议先只启用自己确认可用的站点，并确保目标路径是 MoviePilot 容器内已映射的路径。
