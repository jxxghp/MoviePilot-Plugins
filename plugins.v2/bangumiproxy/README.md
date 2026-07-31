# Bangumi代理

为 MoviePilot 内置 Bangumi 数据源配置与 MoonPlus 相同语义的两个 Base URL。

- 动漫数据代理 Base URL：MoviePilot 会在此地址后追加原有接口路径，例如 `v0/subjects/1`、`calendar`。
- 动漫图片代理 Base URL：MoviePilot 会拼接为 `<Base URL>/<原始 Bangumi 图片完整 URL>`，例如 `https://proxy.example/https://lain.bgm.tv/pic/cover/l/example.jpg`。

两个地址可单独配置。插件启用后会覆盖内置 `BangumiApi` 的同步与异步请求结果；配置重载或停用时会恢复内置实现并清除 Bangumi 缓存。

该插件只处理 MoviePilot 内置 Bangumi 模块，不会重写第三方插件自行硬编码的 `api.bgm.tv` 请求。
