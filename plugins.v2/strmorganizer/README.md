# STRM 整理工具（MoviePilot V2）

一款专为 MoviePilot V2 设计的 STRM 文件整理插件，支持：
- 🔍 缺失 STRM 扫描
- 🗑 批量删除 STRM
- 📂 完整库 STRM 复制
- 📊 CSV 报告
- ⏱ 定时任务
- 🧪 Dry-Run 安全模拟

---

## 安装方式

1. Fork 本仓库
2. MoviePilot → 插件市场 → 添加插件源
3. 填写你的 GitHub 仓库地址
4. 安装 **STRM 整理工具**

---

## 操作模式

| 模式 | 说明 |
|----|----|
| scan | 仅扫描并生成 CSV |
| delete | 删除缺失 STRM 目录中的 `.strm` |
| copy | 从完整库复制 STRM + 元文件 |

⚠️ **delete 模式强烈建议先 Dry-Run**

---

## 配置说明

| 项 | 说明 |
|--|--|
| 当前影视库 | 扫描 / 删除目标 |
| 完整影视库 | copy 源 |
| 输出路径 | copy 目标 |
| cron | 定时执行（5 位） |
| Dry-Run | 模拟运行 |

---

## 状态页

插件详情页可实时查看：
- 当前状态
- 执行进度
- 最近一次结果
- 一键手动执行

---

## CSV 报告

- 路径：`data/plugins/`
- 编码：UTF-8 BOM
- 自动加时间戳

---

## 注意事项

- delete 不可恢复
- Linux 区分大小写
- 建议使用绝对路径
- 大目录请降低线程数

---

## License

GPL-3.0
