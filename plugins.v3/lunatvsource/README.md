# LunaTV 资源订阅（MoviePilot V3）

独立的 MoviePilot V3 插件，读取 MoonTV/LunaTV 的 `api_site` 配置，接入标准苹果 CMS V10 资源站。

## 当前范围

- 读取可配置的 LunaTV JSON 配置地址；默认使用个人可维护的配置仓库。
- 资源站按 allowlist 启用，单个源失败不阻塞其它源。
- 使用 MoviePilot 活跃订阅名称搜索资源。
- 注册为 MoviePilot V3 原生“探索”数据源，搜索结果带有稳定的 `lunatv` 媒体身份，可继续创建订阅。
- 任务严格串行执行，不启动并行下载。
- 支持 m3u8/HTTP 资源下载到指定目录，或生成 `.strm`。
- 可选调用 MoviePilot 原生整理链；未开启时使用插件的稳定电影/电视剧命名结构，并保留插件内任务历史。
- 下载完成后可触发 Emby/Jellyfin 媒体库刷新；播放不放在插件页，仍由既有媒体服务器页面负责。
- 可选复用 MoviePilot“智能助手配置”（DeepSeek 等 OpenAI 兼容模型）清理片名后再搜索；未配置或调用失败自动回退原名称。
- 任务通知通过 MoviePilot 插件消息能力发送；MoviePilot 的媒体库扫描可以继续接管已完成文件。

## 目录与命名

下载目录由你在插件设置中指定。插件不会擅自修改 MoviePilot 的目录设置；可开启“下载后调用 MoviePilot 整理链”复用系统规则，也可以直接写入指定媒体库目录。

```text
电影名 (年份)/电影名 (年份).mp4
剧名 (年份)/Season 01/剧名 (年份) - S01E01.mp4
```

下载先写入 `.part`，成功后再改为正式文件名，避免媒体库扫描到半成品。目录内没有正在下载的缓存文件时，媒体库才会显示完整文件夹；MoviePilot/Emby 的自动监控建议在确认前暂时关闭。

同一任务只会进入一次队列；队列每次只执行一个任务，不会并行下载。详情接口缺少播放地址时，插件会自动补查 Apple CMS `ac=detail`，并识别 `S01E01`、`第 8 集`、`第 1 季` 等标记。

## 配置

默认配置地址：

```text
https://raw.githubusercontent.com/hafrey1/LunaTV-config/main/LunaTV-config.json
```

建议先只启用自己确认可用、且有权访问的资源源。插件不会绕过 DRM、登录保护或付费限制。

使用顺序：保存配置并启用插件 → 配置下载目录和处理方式 → （可选）开启系统智能助手识别和媒体服务器刷新 → 在 MoviePilot 中创建或修改订阅 → 点击“刷新订阅”；也可以在插件工作台搜索后单集加入队列。下载目录必须是容器内路径，不能填宿主机未映射的路径。

插件工作台只负责搜索、排队、整理状态和历史，不内置 m3u8 播放器。你已有 Emby 时，把下载目录映射到 Emby 媒体库，并填写媒体服务器名称（如 `Emby`），完成后会自动请求 MoviePilot 的媒体库同步。

## 开发检查

```bash
python3 -m pytest tests
python3 -m compileall plugins.v3/lunatvsource
git diff --check
```
