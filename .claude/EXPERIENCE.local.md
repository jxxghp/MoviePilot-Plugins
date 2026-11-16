# TraktCleaner 插件开发经验总结

> ⚠️ 本节为 2026-07 实战总结，**优先级最高**，覆盖下方旧文档中与之冲突的部分（尤其 Trakt API 与认证方式）。

## 〇、oes 开发调试工作流（dev-plugin 热重载 + 实战坑点）

### 0.1 dev-plugin 机制（推荐用法）

MP 容器 `moviepilot-v2` 配了 `PLUGIN_LOCAL_REPO_PATHS=/config/dev-plugin`（宿主 `/opt/docker-apps/moviepilot/config/dev-plugin`）。把插件按仓库结构放进去，MP 会作为「本地插件仓库」识别：

```
/config/dev-plugin/
├── package.v2.json              # 清单（必须！缺它插件不被发现）
└── plugins.v2/
    └── traktcleaner/
        └── __init__.py
```

`package.v2.json` 只需含本插件条目即可（不必复制官方全量）：

```json
{ "TraktCleaner": { "name": "...", "version": "1.3", "level": 1, "history": {...} } }
```

### 0.2 部署/触发的坑（按踩坑顺序）

| 坑 | 现象 | 真因 / 解法 |
|---|---|---|
| host scp 不触发热重载 | 直接 scp 到 `/config/dev-plugin/`，服务器无反应 | Docker bind-mount 的 inotify **穿不透**到容器内。改在**容器内**写文件，或用下面的主动同步。 |
| watchfiles 按内容哈希 | cp 同内容文件不触发；改 mtime 也不触发 | 必须真改内容（追加注释 / 改代码）。 |
| dev 版未覆盖内置版 | TraktCleaner 已被**打包进镜像** `/app/app/plugins/traktcleaner/`，dev 副本不自动覆盖运行副本 | 主动同步（见 0.3）。 |
| 直写 DB 不刷新缓存 | 用独立进程 `SystemConfigOper().set("plugin.TraktCleaner", ...)` 改配置，服务器仍读旧值（`init_plugin` 读到旧 enabled） | 服务器进程有内存缓存，跨进程直写不失效。**必须走 API**（`save_plugin_config` 会刷缓存）或重启容器。 |
| 独立进程 PluginManager 是空壳 | 容器内 `python3 -c "PluginManager().get_plugin_config(...)"` 返回空 | 新进程的 PluginManager 单例未加载插件，`_plugins`/`_running_plugins` 为空。要读配置直接 `SystemConfigOper().get("plugin.TraktCleaner")`；要判断服务器运行态看日志（「加载插件：TraktCleaner 版本：x」）。 |
| 后台线程日志不落盘 | onlyonce 后台线程的 `logger.info` 不进 `moviepilot.log`，但 `post_message` 通知正常发 | 此环境线程日志不持久化。**取证就临时在 `__clean` 里写文件到 `/tmp`**，验证完删掉。 |

### 0.3 主动同步 dev → 运行副本（可靠）

在容器内跑（独立进程，退出时可能 segfault，不影响已完成的操作）：

```python
from app.core.plugin import PluginManager
from app.helper.plugin import PluginHelper
pm = PluginManager()
cand = PluginHelper().get_local_plugin_candidate("TraktCleaner")
pm._sync_local_plugin_if_installed("TraktCleaner", cand)  # 拷贝 dev→/app/app/plugins
```

同步会改 `/app/app/plugins/traktcleaner/__init__.py` 内容 → 主进程 watchfiles 捕获 → 自动热重载。

### 0.4 触发 onlyonce 试运行（API，正确姿势）

**认证**：`app.env` 里的 `API_TOKEN` 用于读类接口（`X-API-KEY` 头）；**改配置/PUT 等超级用户接口需登录拿 JWT**：

```bash
JWT=$(curl -s -X POST http://localhost:3000/api/v1/login/access-token \
  -d "username=admin&password=<SUPERUSER_PASSWORD>" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

**触发**（PUT 会**整体替换**配置，必须先 GET 再改再 PUT，否则丢 token）：

```bash
BASE="http://localhost:3000/api/v1/plugin/TraktCleaner"
curl -s -H "Authorization: Bearer $JWT" "$BASE" -o /tmp/c.json   # GET
python3 -c "import json;c=json.load(open('/tmp/c.json'));c['enabled']=True;c['dry_run']=True;c['onlyonce']=True;json.dump(c,open('/tmp/c.json','w'))"
curl -s -X PUT "$BASE" -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d @/tmp/c.json
```

`dry_run=True` 必开（只报不删）。`init_plugin` 收到 `onlyonce=True` 后起后台线程跑一次。

### 0.5 真实数据交叉验证（最可信）

不依赖插件运行，直接拿容器内 live token 调 Trakt 原始 API 核对：

```bash
cat > /tmp/diag.py <<'PY'
import requests
from app.db.systemconfig_oper import SystemConfigOper
c=SystemConfigOper().get("plugin.TraktCleaner")
H={"Authorization":f"Bearer {c['access_token']}","trakt-api-version":"2","trakt-api-key":c["client_id"]}
# 例：核对某剧真实已看集数
print(requests.get("https://api.trakt.tv/shows/188205/progress/watched",headers=H).json()["completed"])
PY
scp /tmp/diag.py oes:/tmp/diag.py && ssh oes 'docker cp /tmp/diag.py moviepilot-v2:/tmp/diag.py && docker exec moviepilot-v2 python3 /tmp/diag.py'
```

注意：插件 `__clean` 开头会 `__refresh_token()` 轮换 access_token，所以**调试时每次重新从 DB 读 token**，别缓存。

### 0.6 单元测试（容器内跑）

MP 核心不在本仓库，无法本地 import 插件。测试脚本放进容器跑（有完整 `app.*` 模块）。用 `__new__` 绕过 `_PluginBase.__init__`，mock `MetaInfo` 和 `self.chain.torrent_files`，按 name-mangling 调私有方法 `_{ClassName}__should_clean_torrent`。

## 环境信息

| 项目 | 值 |
|---|---|
| MP 容器名 | `moviepilot-v2` |
| SSH | `ssh oes`（无密码） |
| MP Web | `https://mp.wgy.us.kg` |
| API Token | `<见本地密码管理器>` |
| 容器内插件路径 | `/app/app/plugins/traktcleaner/__init__.py` |
| Trakt Client ID | `<见本地密码管理器>` |
| Trakt Client Secret | `<见本地密码管理器>` |
| 图标来源 | `https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/trakt.png` |

### 常用命令

```bash
# 部署插件
cat plugins.v2/traktcleaner/__init__.py | ssh oes "docker exec -i moviepilot-v2 tee /app/app/plugins/traktcleaner/__init__.py > /dev/null"

# 触发运行一次（注意：必须传完整配置，否则会覆盖丢失 token 等字段！）
curl -s -X PUT "https://mp.wgy.us.kg/api/v1/plugin/TraktCleaner" \
  -H "X-API-KEY: <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"onlyonce": true}'

# 查看日志
ssh oes "docker logs moviepilot-v2 2>&1 | grep 'Trakt' | tail -20"

# 查看数据页 API
curl -s "https://mp.wgy.us.kg/api/v1/plugin/page/TraktCleaner" \
  -H "X-API-KEY: <API_TOKEN>" | python3 -m json.tool

# 查看配置
curl -s "https://mp.wgy.us.kg/api/v1/plugin/TraktCleaner" \
  -H "X-API-KEY: <API_TOKEN>" | python3 -m json.tool
```

---

## 一、MoviePilot V2 插件开发要点

### 1.1 插件结构

- 单文件 `__init__.py`，类继承 `_PluginBase`
- 必须类属性：`plugin_name`, `plugin_desc`, `plugin_icon`, `plugin_version`, `plugin_author`, `plugin_config_prefix`, `plugin_order`, `auth_level`
- 关键方法：
  - `init_plugin(config)` — 初始化/加载配置
  - `get_state()` — 返回启用状态
  - `get_form()` — 配置表单（Vuetify 组件树）
  - `get_page()` — 数据详情页（Vuetify 组件树）
  - `get_api()` — 自定义 API 端点
  - `get_service()` — 定时任务注册
  - `stop_service()` — 停止时清理

### 1.2 配置持久化

- `self.update_config(dict)` — 保存配置（会触发 `init_plugin` 重新加载）
- `self.get_config()` — 读取当前配置
- `self.save_data(key, value)` — 保存插件数据（JSON 序列化）
- `self.get_data(key)` — 读取插件数据（自动反序列化）

### 1.3 ⚠️ 重要坑点

#### PUT API 会覆盖完整配置

`PUT /api/v1/plugin/{plugin_id}` 的 body 会**完全替换**配置，不是合并！如果只传 `{"onlyonce": true}`，其他字段（token 等）全部丢失。

**正确做法**：要么传完整配置，要么不要用 API 触发 onlyonce，改用 UI 操作。

#### `update_config` 会触发 `init_plugin`

在 `init_plugin` 内调用 `update_config` 会导致递归重载。避免在 `init_plugin` 中调用，除非确认流程不会循环。

---

## 二、通知系统

### 2.1 post_message 正确用法

```python
from app.schemas.types import NotificationType

self.post_message(
    mtype=NotificationType.Plugin,  # ← 必须！否则通知不会路由到 Telegram
    title="标题",
    text="内容",
)
```

**关键**：必须指定 `mtype=NotificationType.Plugin`。MP 有通知隔离机制，不指定 mtype 的消息不会发送到 Telegram 等外部渠道。

### 2.2 Markdown 支持

- `text` 字段支持 Markdown 格式（标题、粗体 `**bold**`、列表等）
- Telegram 通知会正确渲染 Markdown

---

## 三、Vuetify 数据页（get_page）

### 3.1 返回结构

```python
def get_page(self) -> List[dict]:
    return [
        {
            "component": "VCard",
            "props": {"variant": "outlined"},
            "content": [...]
        }
    ]
```

**注意**：不需要外层 `{render_mode: "vuetify", page: [...]}` 包裹，直接返回组件列表即可。MP 框架会自动包装。

### 3.2 可用组件

VCard, VCardText, VList, VListItem, VListItemTitle, VListItemSubtitle, VChip, VIcon, VRow, VCol, VDivider, VAlert, VSwitch, VTextField, VCronField

### 3.3 ⚠️ Vuetify 不渲染 Markdown

- `**bold**` 在 `text` 字段中**不会**显示为粗体
- 要实现粗体/着色，必须用 Vuetify 的 `props.class`：
  - 粗体：`"class": "font-weight-bold"`
  - 颜色：`"class": "text-success"` (绿), `"class": "text-error"` (红), `"class": "text-grey-darken-1"` (灰)
  - 组合：`"class": "text-success font-weight-bold"`

### 3.4 逐集着色方案

为每集生成独立的 `<span>` 组件，通过 class 区分已看/未看：

```python
ep_spans = []
for ep in ep_details:
    cls = "text-success font-weight-bold" if ep["watched"] else "text-grey-darken-1"
    ep_spans.append({
        "component": "span",
        "props": {"class": cls},
        "text": f"E{ep['episode']:02d}",
    })
```

### 3.5 布局技巧

- 水平排列：`"class": "d-flex align-center"`
- 换行：`"class": "flex-wrap"`
- 间距：`"class": "mr-2 ml-2 mt-1 mb-2 pa-2"`
- 文字截断：`"style": "word-break: break-all;"`
- 卡片样式：`"variant": "outlined", "class": "rounded-lg"`

---

## 四、Trakt API

> 2026-07 实测纠正：下方「已观看接口」的响应行为与本账户实际不符，以本节为准。

### 4.1 已观看接口（实测）

| 接口 | 实测行为 |
|---|---|
| `GET /sync/watched/movies` | 正常，每条有 `movie` + `plays` + `last_watched_at`。`plays>=1` 即视为已看完（唯一事实来源）。 |
| `GET /sync/watched/shows` | ⚠️ **本账户不返回 `seasons` 字段**（9 部剧全无，`extended=full` 也没用，疑似接口更新）。只有 `plays`/`show`。**不能**用它拿集数。 |
| `GET /sync/watched/episodes` | ⚠️ 每条**只有 `episode`（含 season/number/ids），没有 `show`**，无法按剧分组。可用于核对总观看集数。 |
| `GET /shows/{trakt_id}/progress/watched` | ✅ **剧集集数的权威来源**。但 `seasons[].episodes` 列的是**全部已播出集**，每集带 `completed`/`last_watched_at`；**必须按 `last_watched_at` 非空过滤**才是真正看过的（数量等于顶层 `completed`）。 |

### 4.2 progress/watched 响应与正确解析

```json
{
  "completed": 25,           // 真正看过的集数（已播出 40 中的 25）
  "aired": 40,
  "seasons": [
    { "number": 4, "episodes": [
      { "number": 1, "completed": false, "last_watched_at": null, "stats": {...} },
      ...
    ] }
  ]
}
```

正确解析（v1.3 实现）：

```python
for season in data.get("seasons", []):
    eps = [e["number"] for e in season["episodes"] if e.get("last_watched_at")]
    if eps:
        watched_seasons[str(season["number"])] = eps
```

交叉验证：9 部剧过滤后 `completed` 总和 = 106，与 `/sync/watched/episodes` 总量一致 → 数据准确。

### 4.3 分页

- 参数：`page`, `limit`
- 响应头：`X-Pagination-Page-Count` 表示总页数

### 4.4 Token 管理

- 授权流程：Client ID → 授权链接 → 用户获取 PIN → PIN 换 Token
- PIN 换 Token：`POST /oauth/token` (`grant_type: authorization_code`)
- 刷新 Token：`POST /oauth/token` (`grant_type: refresh_token`)
- **PIN 只能用一次**，过期或使用后失效
- **Refresh Token 有速率限制**：429 Too Many Requests，观测到 2307 秒冷却时间
- 建议：距上次刷新超过 12 小时才刷新
- ⚠️ `__clean` 每次开头会 `__refresh_token()` 轮换 access_token；**调试时别缓存 token，每次从 DB 现取**。

### 4.5 Token 错误处理策略

1. PIN 换取成功后立即更新 `last_token_refresh` 时间戳，避免立即触发 refresh
2. `init_plugin` 中 refresh 失败**不标记** `_token_error`（access_token 可能仍有效）
3. 只在实际 API 调用返回 401 且 refresh 也失败时才标记 `_token_error`

### 4.6 关于「只看几分钟的电影被清」

不是 bug：查 AI 电影实际 `plays: 2`，Trakt 已记录看完两遍。**Trakt 是唯一事实来源**，watched/movies 里 `plays>=1` 即应清理；不要用 `/sync/playback`（断点）等第二数据源去覆盖 Trakt 的 watched 判定（v1.2 试过、v1.3 已移除）。

---

## 五、种子匹配与清理逻辑

### 5.1 标题匹配

用 MP 内置的 `MetaInfo(title)` 解析种子标题，提取 `cn_name`/`en_name`/`name`，标准化后与 Trakt 观看记录匹配。

```python
from app.core.metainfo import MetaInfo
meta = MetaInfo(torrent_title)
names = {meta.cn_name, meta.en_name, meta.name}
```

### 5.2 文件级集数判断

```python
from app.helper.torrent import TorrentHelper
files = self.chain.torrent_files(tid=torrent_hash)
```

通过 MetaInfo 解析每个视频文件名的季集信息，与 Trakt 已看集数做交集。

### 5.3 种子状态获取

```python
from app.schemas.types import TorrentStatus
completed = self.chain.list_torrents(status=TorrentStatus.TRANSFER)  # 已完成
downloading = self.chain.list_torrents(status=TorrentStatus.DOWNLOADING)  # 下载中
```

---

## 六、数据存储格式（history）

每条记录是一个字典，包含：

```python
{
    "title": "原始种子名",
    "hash": "种子hash",
    "matched_type": "show" | "movie",
    "matched_title": "识别出的剧名",
    "matched_year": "年份",
    "season": 1,
    "episodes": [33, 34],
    "season_ep_text": "S01E33E34",
    "file_eps_text": "S01E33E34",       # 种子文件包含的集数
    "watched_eps_text": "S01E29E34E37E38",  # Trakt 全部已看集数
    "matched_watched_text": "S01E34",   # 种子文件与已看的交集
    "notify_eps_text": "S01E33**E34**", # 通知用（markdown粗体标记已看）
    "ep_details": [                     # 数据页用（逐集标记）
        {"season": 1, "episode": 33, "watched": False},
        {"season": 1, "episode": 34, "watched": True}
    ],
    "reason": "清理原因",
    "clean_time": "2026-06-08 22:58:00",
    "dry_run": True,
    "skipped": True,        # 可选，跳过
    "excluded": True,       # 可选，排除
    "tags": "H&R",          # 排除标签
    "error": "错误信息",     # 可选
}
```

---

## 七、数据库操作（调试用）

```bash
# 在容器内执行 Python 脚本
cat /tmp/script.py | ssh oes "docker exec -i moviepilot-v2 tee /tmp/script.py > /dev/null"
ssh oes "docker exec moviepilot-v2 python3 /tmp/script.py"
```

```python
# 查询插件数据
from app.db.plugindata_oper import PluginDataOper
pdo = PluginDataOper()
data_list = await pdo.async_get_data_all(plugin_id="TraktCleaner")
for d in data_list:
    if d.key == "history":
        history = json.loads(d.value)  # 注意：value 是 JSON 字符串
```

注意：`save()` 是同步方法，`async_get_data_all()` 是异步方法。

---

## 八、常见问题与解决方案

| 问题 | 原因 | 解决 |
|---|---|---|
| TG 通知不发送 | `post_message` 缺少 `mtype` | 加 `mtype=NotificationType.Plugin` |
| API 认证失败（PUT/写接口 403） | 用了 `API_TOKEN` 或 `X-API-KEY` | 超级用户写接口需登录 JWT：`POST /api/v1/login/access-token` 拿 access_token，再用 `Authorization: Bearer <JWT>`（见 0.4）。读接口 `X-API-KEY` 仍可用 |
| 数据页返回空 `{}` | `get_page` 抛异常 | 检查日志中的 `'str' object has no attribute 'get'` 等错误 |
| Vuetify 不显示粗体 | 用了 Markdown `**bold**` | 用 `props.class: "font-weight-bold"` |
| 种子状态重复显示 | `seed_rows.append` 被调用两次 | 检查是否有残留的重复 append |
| Token 频繁失效 | `init_plugin` 每次 refresh 失败就标记 error | 只在 401 时标记；PIN 成功后更新时间戳 |
| PUT API 丢失配置 | 只传了部分字段 | 必须传完整配置 |
| Trakt API 429 | refresh_token 速率限制 | 等待冷却，12小时刷新间隔 |

---

## 九、提交 PR 规范（官方仓库）

### 9.1 文件要求

- 插件代码放 `plugins.v2/<plugin_id_lower>/__init__.py`
- 元数据写入 `package.v2.json`，字段：`name`, `description`, `labels`, `version`, `icon`, `author`, `level`, `history`
- 目录名必须是类名小写，`version` 和 `icon` 必须与代码一致

### 9.2 图标策略

- 优先复用官方 `icons/` 目录已有图标（如 `Trakt_A.png`）
- 自定义图标可用完整 HTTP URL（jsdelivr CDN 等），需确认 CORS 支持 `access-control-allow-origin: *`

### 9.3 版本更新流程

1. 修改 `plugin_version`（如 `1.0` → `1.1`）
2. 同步更新 `package.v2.json` 的 `version` 和 `history`
3. `git commit --amend` 可合并到同一次 commit 保持 PR 干净
4. `git push --force-with-lease` 更新已有 PR
