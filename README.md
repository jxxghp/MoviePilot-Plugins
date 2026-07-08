# MoviePilot-Plugins

个人自用第三方 MoviePilot 插件库。

本仓库基于官方插件库结构维护，原始项目请见：

- 官方插件库：<https://github.com/jxxghp/MoviePilot-Plugins>
- MoviePilot 主项目：<https://github.com/jxxghp/MoviePilot>

本仓库不保证通用性，也不保证适合直接用于你的 MoviePilot 环境。使用前请先阅读插件说明，并确认插件行为符合你的媒体库、下载器和容器部署方式。

## 当前插件

### 蓝光原盘重封装

目录：`plugins.v2/discremuxplugin`

这个插件用于处理已经整理进媒体库的蓝光原盘目录。读取 MoviePilot 的整理历史，找到最近整理过的 BDMV 记录，然后在媒体库当前条目目录中用 MakeMKV 将原盘重封装为 MKV。

大致流程：

1. 查询最近 N 天的整理历史。
2. 找到真实存在的 BDMV 目录。
3. 使用媒体库中的 BDMV 作为 MakeMKV 输入。
4. 输出 `电影目录名.mkv` 到同一个媒体库条目目录。
5. 成功后按配置创建 `.ignore` 或删除旧 `BDMV` / `CERTIFICATE`。
6. 可选删除下载源和对应整理记录。

#### 重要提醒

蓝光原盘重封装插件会在 MoviePilot container 内尝试安装 MakeMKV。

这不是标准或推荐的容器使用方式。容器内编译/安装系统软件可能带来这些问题：

- 依赖和系统库变化可能影响 MoviePilot 运行环境。
- 容器重建后安装结果可能丢失。
- 不同基础镜像、系统版本、网络环境下安装结果可能不一致。
- MakeMKV 官网会移除旧版本下载链接，脚本虽然会尝试自动解析可下载版本，但仍可能失败。

更稳妥的方式通常是自定义 MoviePilot 镜像，或在外部环境准备好 MakeMKV 后再挂载/调用，

## 使用方式

将本仓库作为第三方插件库添加到 MoviePilot 后，安装需要的插件即可。

插件索引：

- `package.v2.json`

图标资源：

- `icons/`
