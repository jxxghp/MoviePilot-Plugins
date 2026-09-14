# Bangumi代理

为 MoviePilot 内置 Bangumi 客户端配置数据与图片代理 Base URL。

## 功能

- 可分别配置动漫数据代理和图片代理，留空表示不代理。
- 自动包装 `BangumiApi` 的所有公共方法，图片 URL 重写覆盖所有入口。
- 图片代理支持三种拼接风格，由 Base URL 写法自动判断：
  - 仅替换主机：`https://proxy.example/`
  - 查询参数：`https://proxy.example/?url=`
  - 路径拼接：`https://proxy.example`
- 只重写 Bangumi 图片字段（`images` / `image` / `avatar`），且只代理
  `bgm.tv`、`bangumi.tv`、`bangumi.lol` 及其子域名。
- 切换代理后自动清理内置 Bangumi 缓存。

## 配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 总开关 |
| 动漫数据代理 Base URL | 仅支持路径风格，如 `https://bangumi-proxy.example` |
| 动漫图片代理 Base URL | 支持以下三种风格 |

图片代理示例（原始图片 `https://lain.bgm.tv/pic/cover/l/xx.jpg`）：

| Base URL | 模式 | 生成结果 |
| --- | --- | --- |
| `https://proxy.example/` | 仅替换主机 | `https://proxy.example/pic/cover/l/xx.jpg` |
| `https://proxy.example/?url=` | 查询参数 | `https://proxy.example/?url=https%3A%2F%2Flain.bgm.tv%2Fpic%2Fcover%2Fl%2Fxx.jpg` |
| `https://proxy.example` | 路径拼接 | `https://proxy.example/https://lain.bgm.tv/pic/cover/l/xx.jpg` |

- 以 `/` 结尾表示“目录”，只替换主机，原始 path 和 query 保留。
- 含 `?` 表示查询参数风格，原始 URL 会被 URL 编码后拼接。
- 其它情况按 `<Base URL>/<原始图片URL>` 拼接。
- 带附加参数时直接写进 Base URL，例如 `https://proxy.example/?w=600&output=webp&url=`。

## 注意

- 仅替换主机模式会丢弃原始域名信息，代理服务无法区分多个源站。
- 插件会接管宿主全局类 `BangumiApi`，**不适合创建多个虚拟分身**。
- 免费公共图片代理可能有速率限制，正式环境建议自建。
