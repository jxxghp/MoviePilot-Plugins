# V1 历史记录迁移至 V3

该 V3 专用插件读取远端 MoviePilot V1 的整理历史，并直接写入当前 MoviePilot V3 数据库。
迁移时会把存量来源专有 ID 转换为 `media_source` 与 `media_id`；运行时插件 ID 和类名仍保留
`HistoryToV2`，用于兼容已保存的插件安装标识。
