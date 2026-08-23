# LunaTV 资源订阅（MoviePilot V3）

接入 MoonTV/LunaTV 的 Apple CMS 资源站，复用 MoviePilot 原生搜索、订阅、目录、TMDB、整理和媒体库链路。插件只负责源适配与串行下载。

## 使用要点

- 订阅地址内的资源站默认全部读取；目录复用 MoviePilot 的本地目录设置，不再重复配置白名单或下载路径。
- 队列严格串行，MoviePilot 重启后会恢复中断任务，不会并行下载。
- 片名自动读取 MoviePilot 智能助手（DeepSeek 等 OpenAI 兼容模型），未配置或失败时自动回退规则清理。
- LunaTV 结果参与 MoviePilot 顶部全局搜索，并使用原生详情、资源搜索、订阅和下载入口；插件不再提供重复搜索页或独立订阅导航。
- 搜索结果自动关联 TMDB；多季合集会按作品季集数安全映射。
- 目录、智能助手、TMDB、整理规则、媒体服务器和链接权限无需在插件中重复配置；媒体库同步沿用 MoviePilot 已启用的服务器设置。
- 插件不会绕过 DRM、登录保护或付费限制，请只使用你有权访问的资源源。

默认配置地址：

```text
https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json
```

请只启用有权访问的站点，并确保 MoviePilot 目录已正确映射到容器。
