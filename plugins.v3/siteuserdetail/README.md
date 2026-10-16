# 站点用户详情采集

定时采集每个 PT 站**用户详情页**的两类数据，提供插件详情页展示，并暴露插件 API 供三方系统实时调用：

1. **BT 客户端列表**：`site / domain / agent / ipv4 / ipv6 / port`。
   每个站点至少返回一条记录，解析不到客户端信息的站点返回一条**全空值**记录。
2. **下载中种子列表**（仅下载中，不含做种）：`site / domain / id / hash / name / tags(促销标签) / size`。

后端只返回**两个平铺列表**，API 不做聚合；按站点、IP、促销标签等维度的分组聚合由调用方前端完成
（列表每项均含 `site`、`domain` 字段，可据此做两个列表的关联与聚合）。
插件自带**详情页**：摘要统计、客户端/种子明细表、IPv4/IPv6 跨站聚合（同一 IP 出现在哪些站点）、
促销分布与失败站点列表。

要求 MoviePilot v3.0.0 及以上。

## 前提条件

- 站点需在 MoviePilot「站点管理」中配置有效 Cookie/UA（Cloudflare 防护站点需开启浏览器仿真）；
- M-Team 等 API 型站点需在站点配置中填写 APIKEY（x-api-key）；
- 种子 `hash` 回填依赖已配置的下载器（qBittorrent / Transmission）。

## 工作方式

- **定时采集**：默认每 6 小时（可配置 5 位 cron 表达式或小时间隔数字），也可「立即运行一次」；
- **API 实时采集**：调用 `collect` 接口触发一次采集，与定时任务共用同一采集逻辑，结果会更新存储快照；
- **uid 缓存**：站点用户 ID 解析后缓存（`uid_map`），后续采集优先用 Cookie（`c_secure_uid`）或缓存定位，
  仅在失效时访问站点首页重新解析；
- **hash 回填顺序**：① 下载器种子列表按种子名精确匹配 → ② 种子详情页解析 infohash 兜底
  （每站每次采集有请求上限，默认 20，浏览器仿真站点跳过）→ ③ 留空；
- **礼貌性**：同站相邻请求默认间隔 3 秒（可配），站点间并发默认 3（可配）。

## 插件 API

认证方式：`apikey` 参数（值为 MoviePilot 的 `API_TOKEN`），支持 query 参数或请求头传递。

### 1. 实时采集：`GET /api/v1/plugin/SiteUserDetail/collect`

| 参数 | 说明 |
| --- | --- |
| `apikey` | MoviePilot API_TOKEN |
| `sites` | 可选，站点域名列表（逗号分隔，支持带协议的完整地址）；留空采集全部配置站点 |

```bash
curl "http://localhost:3000/api/v1/plugin/SiteUserDetail/collect?apikey=<API_TOKEN>&sites=kp.m-team.cc,hdsky.me"
```

### 2. 读取快照：`GET /api/v1/plugin/SiteUserDetail/snapshot`

参数同上。返回最近一次采集（定时任务或 collect 接口）存储的数据，不触发采集。

### 返回结构

```json
{
  "success": true,
  "data": {
    "update_time": 1760000000,
    "clients": [
      {"site": "M-Team", "domain": "m-team.cc", "agent": "qBittorrent v5.0.1",
       "ipv4": "1.2.3.4", "ipv6": "2408:...::1", "port": 51413},
      {"site": "HDSky", "domain": "hdsky.me", "agent": "", "ipv4": "", "ipv6": "", "port": null}
    ],
    "torrents": [
      {"site": "M-Team", "domain": "m-team.cc", "id": "123456", "hash": "<40位infohash>",
       "name": "Some.Torrent.2026.1080p.BluRay.x264-GRP", "tags": ["Free", "2x"], "size": 10737418240}
    ],
    "errors": [
      {"site": "xxx.org", "domain": "xxx.org", "error": "Cookie 已失效或未登录"}
    ]
  }
}
```

- `clients`：每站至少一条；`tags` 为促销标签（`Free` / `2x` / `50%` 等，站点支持才返回）；
- `hash` 可能为空（下载器未匹配到且详情页解析失败时）；
- `errors`：本轮采集失败的站点及原因，不影响其他站点。

## 站点适配器架构

站与站之间架构不同（NexusPHP / M-Team API / Unit3D…），同架构的用户详情页也可能有细微差异。
插件采用「通用架构采集 + 站点适配器」：

```
adapters/
├── __init__.py     # 工厂：站点专属适配器(精确域名) → 架构适配器 → 兜底空值
├── base.py         # 基类：抓取/限速/Cloudflare兜底/uid解析/详情页hash + 可覆写钩子
├── nexusphp.py     # NexusPHP 通用适配器（绝大多数站点的默认）
├── mteam.py        # M-Team API 适配器（x-api-key）
└── sites/          # 站点级微调适配器：新增站点适配 = 加一个小文件 + 注册一行
```

**新增一个站点的小适配**：在 `adapters/sites/` 下新建文件，继承架构适配器并只覆写差异钩子
（`client_table_locator` / `client_table_parse` / `parse_torrent_rows` / `promotion_tags` /
`leeching_url` 等），再在 `adapters/sites/__init__.py` 的 `SITE_ADAPTERS` 注册域名即可：

```python
# adapters/sites/hdsky.py
from ..nexusphp import NexusPhpAdapter

class HdskyAdapter(NexusPhpAdapter):
    """HDSky 模板差异：客户端表格位于独立 div。"""
    def client_table_locator(self, html):
        ...
```

```python
# adapters/sites/__init__.py
SITE_ADAPTERS["hdsky.me"] = HdskyAdapter
```

不匹配任何适配器的站点走 NexusPHP 通用解析，仍失败则返回全空值条目并在 `errors` 记录原因。

## 说明与限制

- M-Team：**客户端数据需在站点配置中填写 Token（浏览器登录态，localStorage.auth）**——
  通过 `/api/torrent/peers` 按 memberId 精确识别本人会话获取 agent/IPv4/IPv6（API 不提供端口）；
  Token 过期时回退为空值条目并记录提示。下载中列表来自 `getUserTorrentList`（type=INCOMPLETE）：
  该列表是**历史未完成**（含客户端已删除的种子），以 `myPeerStatus.leecher` 与行内 `peer`
  活动会话判定**当前真实下载**；种子 hash 仅能通过下载器名匹配回填（列表/详情 API
  均不返回 infohash）。若站点调整 API 字段，只需修改 `adapters/mteam.py` 的映射常量；
- NexusPHP 客户端表格解析为通用启发式（表头列名定位 + 单元格 IP/UA 特征识别），
  覆盖不到的站点请通过站点适配器微调；
- 种子详情页兜底会访问 `details.php`，注意配置合理的 `detail_limit` 与请求间隔，避免请求过多。
