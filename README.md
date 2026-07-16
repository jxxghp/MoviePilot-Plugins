# MoviePilot 115 离线下载器

`P115OfflineDownloader` 是 MoviePilot V2 的独立桥接插件。它只接管明确选择了
`p115offline` 自定义下载器的任务，将原生磁力或公开 BitTorrent v1 Torrent 转换后提交给
P115StrmHelper；MoviePilot、P115StrmHelper 和官方 Docker 镜像均无需修改。

## 功能

- 支持十六进制和 Base32 BTIH 磁力。
- 支持公开 BitTorrent v1 Torrent，以及包含 v1 `pieces` 的 v1/v2 混合 Torrent。
- 强制拒绝私有 Torrent、含敏感认证参数的 Tracker、纯 v2 Torrent 和损坏内容。
- 通过 P115StrmHelper `add_offline_task` API 提交任务，并保持 `path` 为空以进入自动整理链路。
- 非目标下载器请求直接跳过；明确选择 115 后的失败不会回退到其他下载器。
- 提供不提交真实任务的连接测试。

## 安装

本仓库遵循 MoviePilot V2 插件市场结构，可将仓库地址配置为自定义插件市场后安装
“115离线下载器”。最低 MoviePilot 版本为 `2.12.0`。

也可以在开发环境中把
`plugins.v2/p115offlinedownloader` 复制到 MoviePilot 的 `app/plugins` 下进行加载测试。

## 配置

1. 安装并启用 P115StrmHelper，确认其离线下载与网盘整理链路已经可用。
2. 在 MoviePilot“设置 → 下载器”新增自定义下载器：
   - 类型：`p115offline`
   - 名称：`115离线下载`
   - 启用：是
   - 默认：否
   - 路径映射：留空
3. 配置本插件：
   - API 根地址默认 `http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper`
   - Token 填写 MoviePilot API Token
   - 保存配置后点击“测试连接”
4. 只在适合 115 离线下载的订阅中选择“115离线下载”；普通/PT订阅继续使用默认下载器。

P115StrmHelper 建议保持离线下载目录和网盘待整理目录一致，例如
`/media115/inbox`。桥接请求始终发送空 `path`，不会使用 MoviePilot 传入的下载目录。

## 安全与限制

- 不支持私有 PT、保种、暂停/恢复、限速、任务删除和文件级精确选集。
- 发现选集参数时仍提交完整任务，但会写入警告日志。
- 不支持纯 BitTorrent v2 `btmh`。
- 日志不会记录完整磁力、Tracker、Token、115 Cookie 或站点 Cookie。
- “任务提交成功”仅表示 P115StrmHelper 和 115 接受了任务，不代表最终下载完成。
- P115StrmHelper 在任务完成前重启时，待整理内存状态能否恢复取决于其当前版本。

## 手工验收

在真实 MoviePilot/P115StrmHelper 环境中依次确认：

1. 普通订阅仍进入默认 qBittorrent/Transmission/rTorrent。
2. 115订阅的原生磁力能记录正确 Hash。
3. 公开 v1 Torrent 能转换并提交，随后完成115下载、网盘整理、STRM生成和Emby刷新。
4. 私有、敏感Tracker、纯v2和损坏种子被明确拒绝且不回退。
5. Token错误、P115StrmHelper未启用和客户端未初始化时显示明确错误。

## 开发验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
python3 -m compileall plugins.v2/p115offlinedownloader
python3 -m json.tool package.v2.json
```

详细设计见 [docs/MoviePilot_P115Offline_Design.md](docs/MoviePilot_P115Offline_Design.md)。
