# 蓝光原盘重封装

MoviePilot v2 插件：查询最近整理历史中的蓝光原盘记录，使用媒体库中现有的 BDMV 作为 MakeMKV 输入，重封装为 MKV 后直接输出到当前媒体库条目目录。

## 依赖

- 需要 `makemkvcon` 命令可用。
- 如果未检测到 `makemkvcon`，插件会尝试在 MoviePilot container 内编译安装 MakeMKV。

> 注意：在 MoviePilot container 内安装 MakeMKV 不是标准容器用法。更稳妥的方式是自定义镜像，或在外部准备 MakeMKV 后再挂载/调用。

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 启用插件 | 开关 | 关闭 |
| 定时运行策略 | Cron 表达式 | `0 3 * * *` |
| 查询最近整理记录天数 | 使用 `TransferHistoryOper().list_by_date(since_time)` 查询最近 N 天记录 | `7` |
| 跳过阈值 | 目标 MKV 已存在且大于该大小时跳过 | `5GB` |
| 只处理电影 | 仅处理整理历史类型为电影的记录 | 开启 |
| 旧媒体库 BDMV 处理方式 | 创建 `.ignore` 或删除旧 `BDMV` / `CERTIFICATE` | 创建 `.ignore` |
| 成功后删除下载源和整理记录 | 删除下载源文件，并删除对应整理记录 | 关闭 |
| 尝试刷新对应媒体库 | 调用媒体服务器按条目刷新能力，不主动全库扫描 | 开启 |

## 工作流程

1. 按 Cron 表达式启动任务，计算 `since_time = 当前时间 - 最近天数`，格式为 `%Y-%m-%d %H:%M:%S`。
2. 使用 `TransferHistoryOper().list_by_date(since_time)` 获取整理历史。
3. 根据 `history.dest` 定位媒体库旧 BDMV，并检查 `index.bdmv` 或 `MovieObject.bdmv` 标志文件。
4. 默认只处理电影；如关闭该选项，也会处理其他类型的 BDMV 记录。
5. 使用媒体库旧 BDMV 的父目录作为 MakeMKV 输入，提取最长正片。
6. 输出到媒体库当前条目目录，文件名为 `条目目录名.mkv`，例如 `/media/Movies/Movie Name (2024)/Movie Name (2024).mkv`。
7. 重封装过程中先生成 `.partial.mkv`，完成后再重命名为最终 MKV。
8. 成功后按配置创建旧 BDMV 的 `.ignore` 或删除旧 `BDMV` / `CERTIFICATE`。
9. 可选删除下载源，并删除整理记录。
10. 记录已处理的 history id，避免重复处理。

## 跳过条件

- 目标 MKV 已存在且大小大于配置阈值。
- 旧媒体库 BDMV 内已存在 `.ignore`。
- 插件数据中已记录该 history id。
- 媒体库旧 BDMV 不存在，或缺少 `index.bdmv` / `MovieObject.bdmv` 标志文件。

## 说明

- 插件详情页会显示插件数据目录和最近处理记录。
- 媒体服务器刷新使用 MoviePilot 现有 `refresh_library_by_items` 能力；不同媒体服务器的精确刷新范围由 MoviePilot 主项目对应模块决定。
- 插件不会调用 `TransferChain().manual_transfer()`，不会重新整理文件。
- `history.src` 只在启用“删除下载源和整理记录”时用于删除下载源，不作为 MakeMKV 输入。
