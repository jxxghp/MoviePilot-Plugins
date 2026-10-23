# MoviePilot-Plugins（V3 · DC助手V3）

> **不用 MoviePilot？** 也有独立 Docker 版管理面板：[po9873/dc-panel](https://github.com/po9873/dc-panel)（`ghcr.io/po9873/dc-panel` 镜像，功能对齐，详见其 README）。

MoviePilot V3 第三方插件仓库，目前包含一个插件：**DC助手V3（DockerCopilotHelper）**，版本号 3.0.0（V3 版基线）。

## 安装方法（通过 MoviePilot 插件市场）

1. 打开 MoviePilot → **设定 → 插件 → 插件市场**
2. 点「插件市场设置」，在输入框填入本仓库地址并添加：
   ```
   https://github.com/po9873/MoviePilot-Plugins/
   ```
3. 保存后回到插件市场，刷新列表，搜索 **DC助手V3** → 安装
4. 以后有新版本，在插件页点「更新」即可自动升级（版本号以 `package.v3.json` 为准）

> 要求：MoviePilot **V3**（`system_version >= 3.0.0`）。V2 版 MoviePilot 无法安装本插件。
> 手动安装：下载本仓库 `plugins.v3/dockercopilothelper` 打包为 zip（根目录即插件目录），在 MoviePilot「插件 → 本地安装」导入。

## 功能

配合 [DockerCopilot](https://github.com/xcz1997/dockerCopilot) 使用，**一个插件实例联动局域网全部 DC 实例**：

> **镜像兼容性**：任何 DockerCopilot 镜像（官方原版 `muuua/docker-copilot`、增强版 `l429609201/dockercopilot`、`0nlylty/dockercopilot`）都能被本插件管理——加设备、看容器、更新业务容器全部可用。
> 唯一区别是「更新 DC 自己」：**只有增强版 `l429609201/dockercopilot` 支持**，其余镜像不支持（详见下面「DC 容器自更新」）。

- **多设备**：每台 DC 填一组「服务器地址 + secretKey」，保存后自动出现下一行，想加几台加几台
- **按设备独立勾选容器**：更新通知 / 自动更新 / 各自独立的容器清单
- **更新通知**：按周期检查所选容器更新并发送 MP 通知，标题标注来源设备
- **自动更新**：按周期对所选容器执行 DC 一键更新，可跟踪进度
- **自动备份**：按周期对所有设备执行容器配置备份
- **DC 程序自更新**：远程触发 DockerCopilot 自身的「更新程序」（容器内二进制热替换，不重建容器）。这是 DC 自己的 `/api/update` 接口，**所有镜像通用**——但它只是换二进制，不是换镜像，镜像有新版时仍需要「DC 容器自更新」
- **DC 容器自更新**：**仅支持增强版镜像 `l429609201/dockercopilot`**（内置 `-selfupdate-helper` 旁路容器）→ 数据页点「自更新DC容器」直接调 `POST /api/container/{自身id}/update`，拉镜像重建一步到位，**不需要任何外部组件**。
  其他镜像（官方 `muuua/docker-copilot`、`0nlylty/dockercopilot`）**不支持自更新**——DC 更新任何容器的第一步就是停掉目标容器，停掉自己后没有进程接手重建。这类设备数据页不显示自更新按钮（置灰并写明原因），解决办法就是换成增强版镜像。
- **TAG 异常自愈**：容器 `usingImage` 为空或为 `sha256:` 时，先删镜像按 ID 重拉，再用创建镜像名更新
- **数据页**：彩色统计 + 每设备「待更新」明细 + 原生展开查看全部容器 + 更新分布饼图 + 更新记录（**只显示当天**，标题带累计与历史跨度）
- **连不上要说人话**：某台 DC 连不上时，配置页下拉会显示「⚠ 读不到容器：端口拒绝连接…」而不是空白，
  数据页对应卡片也会写出具体原因；**此时不会清空你已勾选的通知容器**（修掉了以前一打开配置页就把勾选洗掉的 bug）。
  日后新增的 DC 设备 / 新建的容器不需要任何操作，配置页和数据页刷新后自动出现
- **配置导出 / 导入**：浏览器直接下载 / 上传 JSON 文件

## 配置导出格式（可移植，与独立 Docker 面板互通）

导出的 JSON 使用固定 schema，插件版与**独立 Docker 面板 [dc-panel](https://github.com/po9873/dc-panel)** 共用同一份结构——插件「导出配置」的文件可直接在 dc-panel「数据迁移 → 导入设备」使用，dc-panel「导出设备」的文件也能在本插件导入，两边自由搬家：

```json
{
  "schema": "dc-helper",
  "schema_version": 1,
  "exported_at": "2026-10-23 16:50:00",
  "source": "moviepilot-plugin/dockercopilothelper",
  "enabled": true,
  "devices": [
    {
      "name": "my-nas",
      "host": "http://192.168.1.100:12712",
      "secret_key": "你的secretKey",
      "updatable": ["moviepilot", "qbittorrent"],
      "auto_update": ["moviepilot"]
    }
  ],
  "notify": {
    "update_cron": "0 9 * * *",
    "update_notify": true,
    "auto_update_cron": "",
    "auto_update_notify": true,
    "schedule_report": false,
    "delete_images": false,
    "backup_cron": "",
    "backup_notify": true,
    "dc_update_cron": "",
    "dc_update_notify": true,
    "interval": 10,
    "interval_limit": 6,
  }
}
```

导入同时兼容两种格式：

1. 上面的 `dc-helper` 格式（推荐，跨版本/跨形态通用；dc-panel 导出的文件即此格式）
2. 旧版扁平格式（`host1` / `secretKey1` / `name1` / `updatablelist1` …）

## 接口一览（插件注册的动态 API）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/plugin/DockerCopilotHelper/container_update` | 数据页触发容器更新（JSON body: env/cid/cname/image） |
| GET | `/api/v1/plugin/DockerCopilotHelper/update_now` | 原生链接触发更新，结果显示在独立页面 |
| GET | `/api/v1/plugin/DockerCopilotHelper/download_config?apikey=` | 导出配置（附件下载） |
| POST | `/api/v1/plugin/DockerCopilotHelper/upload_config?apikey=` | 导入配置（multipart 上传） |
| GET | `/api/v1/plugin/DockerCopilotHelper/update_dc_container?apikey=&env=` | 更新 DC 自身容器（仅增强版镜像 l429609201/dockercopilot 支持） |
| POST | `/api/v1/plugin/DockerCopilotHelper/toggle_expand` | 展开/收起设备容器（保留接口） |

## 安装

本地安装：插件管理 → 上传 `DC助手V3-上传安装.zip`（zip 根目录为 `dockercopilothelper/`）。

仓库安装：在 `PLUGIN_MARKET` 添加本仓库地址，要求 main 分支且目录结构为 `plugins.v3/` + `package.v3.json`。

## 来源

**DC 自身容器如何更新**：只有增强版镜像 `l429609201/dockercopilot` 内置了自更新 helper，能自己停旧建新；其他镜像更新自己的第一步就是停掉自己，没有进程接手重建，因此不支持。

> 镜像提示：官方镜像是 `muuua/docker-copilot`（仓库 [xcz1997/dockerCopilot](https://github.com/xcz1997/dockerCopilot)，版本标签有 v2.12.0 ~ v2.14.0）。
> 增强版镜像 `l429609201/dockercopilot`（内置自更新旁路容器，支持「更新自己」）的仓库见 [l429609201/dockerCopilot](https://github.com/l429609201/dockerCopilot)。
> `0nlylty/dockercopilot` 是另一条发布线，内部版本 v2.1.3，缺群组/多环境/服务重启/私有仓库认证等接口，**两线版本号不可比**。

参考自 gxterry 的 V1 插件 `dockercopilothelper`，按 MoviePilot V3 规范重写并升级为多设备支持。DC API 逻辑：本地 HS256 签发 JWT，调用 `/api/containers`、`/api/container/{id}/update`、`/api/progress/{taskID}`、`/api/container/backup`、`/api/images`、`/api/image/{sha}`、`/api/version`、`/api/update`。
