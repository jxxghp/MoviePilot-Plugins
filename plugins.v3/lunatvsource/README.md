# LunaTV 资源订阅（MoviePilot V3）

接入 MoonTV/LunaTV 的 Apple CMS 资源站，串行下载到 MoviePilot 的系统目录或插件指定目录。支持 MoviePilot V3 探索源、订阅刷新、TMDB 默认关联与候选切换、多季边界保护、`.strm`、整理历史和媒体库刷新。

## 使用要点

- 下载目录留空时复用 MoviePilot 的本地目录设置；填写插件目录时优先使用插件目录。
- 队列严格串行，MoviePilot 重启后会恢复中断任务，不会并行下载。
- 片名会先尝试系统智能助手（DeepSeek 等 OpenAI 兼容模型），未配置或失败时自动回退规则清理。
- 搜索结果默认选中 TMDB 关联，也可以重新搜索候选并手动切换；多季合集会按所选作品的季集数安全映射。
- 工作台负责搜索、排队和状态，不内置 m3u8 播放器；播放继续由 Emby/Jellyfin 等媒体服务器负责。
- 插件不会绕过 DRM、登录保护或付费限制，请只使用你有权访问的资源源。

默认配置地址：

```text
https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json
```

建议先只启用自己确认可用的站点，并确保目标路径是 MoviePilot 容器内已映射的路径。
