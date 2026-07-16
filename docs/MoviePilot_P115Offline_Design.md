# MoviePilot 115 离线下载独立桥接插件开发设计

> 文档状态：Draft 0.3  
> 方案类型：独立桥接插件  
> 目标读者：开发者、维护者、测试人员  
> 运行环境：MoviePilot V2、Docker、P115StrmHelper  
> 方案原则：不修改 MoviePilot 核心代码，不修改官方镜像，不 Fork P115StrmHelper 作为第一阶段前提

---

## 1. 背景

当前已经验证可用的媒体链路为：

```text
手动执行 /ol 提交磁力链接
        ↓
P115StrmHelper 提交 115 离线下载
        ↓
下载到 /media115/inbox
        ↓
P115StrmHelper 跟踪任务完成
        ↓
MoviePilot 对 115 文件执行识别、移动、分类和重命名
        ↓
/media115/source
        ↓
P115StrmHelper 监听 MoviePilot 整理完成事件
        ↓
在 /media/Strm 中生成 STRM，并下载关联外挂字幕
        ↓
MoviePilot 本地刮削
        ↓
刷新 Emby
```

该链路已经实际验证能够完成：

- 115 离线下载；
- 下载完成后自动整理；
- 115 内移动和重命名；
- STRM 生成；
- 本地元数据刮削；
- Emby 刷新和播放。

当前缺少的能力是：

> MoviePilot 订阅命中资源后，不能直接把磁力链接交给 P115StrmHelper，仍需用户手动执行 `/ol`。

MoviePilot V2 已提供两项现成扩展能力：

1. 在下载器设置中创建任意类型名称的“自定义下载器”；
2. 插件通过 `get_module()` 重载系统模块方法，例如 `download`。

因此本方案不再修改 MoviePilot 核心，也不再新增 `DownloaderType.P115Offline`，而是开发一个独立插件：

```text
P115OfflineDownloader
```

该插件负责把 MoviePilot 的磁力链接或公开 BitTorrent v1 `.torrent` 内容规范化为磁力链接，再转交给官方 `P115StrmHelper`，并向 MoviePilot 返回任务已提交成功的标准结果。

---

## 2. 方案结论

最终部署结构：

```text
官方 MoviePilot Docker 镜像
├── 官方 P115StrmHelper
└── 自定义 P115OfflineDownloader 桥接插件
```

核心原则：

```text
不修改 MoviePilot
不修改 MoviePilot 前端
不增加 DownloaderType
不注入 /app 核心代码
不构建定制 MoviePilot 镜像
不复制 P115StrmHelper 的 115 客户端实现
```

桥接插件职责：

```text
识别当前选择的自定义下载器
        ↓
接受原生 magnet 或公开 BitTorrent v1 torrent
        ↓
必要时将 torrent 转换为包含 BTIH/Tracker 的磁力链接
        ↓
调用 P115StrmHelper 的 add_offline_task API
        ↓
向 MoviePilot 返回标准下载成功四元组
```

后续任务生命周期仍由 P115StrmHelper 负责。

---

## 3. 目标

### 3.1 核心目标

1. MoviePilot 订阅可单独选择“115 离线下载”。
2. 全局默认下载器继续使用 qBittorrent、Transmission 或 rTorrent。
3. 只有明确指定 115 自定义下载器的订阅才交给 115。
4. 支持原生 `magnet:`，并支持把公开 BitTorrent v1 `.torrent` 转换为磁力链接。
5. P115StrmHelper 成功接受任务后，MoviePilot 正常记录下载历史和订阅进度。
6. 下载完成后继续复用当前已跑通的整理、STRM、字幕和 Emby 链路。
7. MoviePilot 和 P115StrmHelper 都保持官方版本，方便正常升级。
8. 不增加高频 115 目录扫描。
9. 不在 115 中写入海报、NFO 等刮削文件。

### 3.2 非目标

第一版不实现：

- PT 保种；
- 上传率和分享率管理；
- 文件级精确选集；
- 暂停、恢复和限速；
- Tracker 管理；
- 在 MoviePilot 下载管理页完整控制 115 任务；
- 自动把所有下载分流到 115；
- 将 115 设置成全局默认下载器；
- 私有 PT 种子转换或提交到 115；
- 纯 BitTorrent v2 `btmh` 种子支持；
- 将 Torrent 内的文件级选集能力映射到 115；
- 替代 P115StrmHelper 的下载完成监控和网盘整理逻辑。

---

## 4. 使用场景

### 4.1 推荐场景

- 单部电影磁力；
- 单集动画或电视剧磁力；
- 用户明确需要完整下载的季度包；
- 公开 BT、公开 RSS 和无需保种的资源；
- 公开站点只提供 `.torrent`、但种子本身不是私有种子的资源；
- 订阅中明确选择“115 离线下载”的项目。

### 4.2 不推荐场景

- 私有 PT；
- H&R 或必须保种的资源；
- 大合集只需要其中少量文件；
- 依赖 qBittorrent 文件优先级选集的种子；
- `private=1` 的私有 PT 种子；
- Tracker 中包含 passkey、authkey、token 等个人认证参数的种子；
- 纯 BitTorrent v2 种子；
- 需要在 MoviePilot 中暂停、恢复、限速或删除的下载任务。

---

## 4.3 输入支持矩阵

| 输入类型 | 处理结果 |
|---|---|
| 原生 `magnet:?xt=urn:btih:...` | 直接提交 |
| 公开 BitTorrent v1 `.torrent` | 转换为磁力后提交 |
| 公开 v1/v2 混合 Torrent | 能生成有效 `btih` 时允许，必须测试 |
| `private=1` Torrent | 拒绝 |
| 含敏感 Tracker 参数的 Torrent | 拒绝 |
| 纯 BitTorrent v2 `btmh` Torrent | 拒绝 |
| 损坏或伪 Torrent | 拒绝 |
| ED2K、普通 HTTP 文件链接 | 第一版不支持 |

## 5. 总体架构

```mermaid
flowchart TD
    A[MoviePilot 订阅] --> B{订阅选择的下载器}
    B -->|留空或普通下载器| C[qBittorrent / Transmission / rTorrent]
    B -->|115 离线下载| D[P115OfflineDownloader]
    D --> E[P115StrmHelper add_offline_task API]
    E --> F[115 离线下载]
    F --> G[/media115/inbox]
    G --> H[P115StrmHelper 跟踪任务完成]
    H --> I[MoviePilot 115 网盘整理]
    I --> J[/media115/source]
    J --> K[P115StrmHelper 监控 MP 整理]
    K --> L[/media/Strm]
    L --> M[本地刮削、外挂字幕、Emby 刷新]
```

### 5.1 MoviePilot 的职责

- 订阅；
- 资源搜索和过滤；
- 为单个订阅选择下载器；
- 获取磁力链接或下载 `.torrent` 内容；
- 调用系统 `download` 模块；
- 记录下载历史；
- 更新订阅状态；
- 对下载完成的 115 文件执行识别和整理。

### 5.2 桥接插件的职责

- 判断调用是否指定了 `p115offline` 类型的自定义下载器；
- 不匹配时返回 `None`，把请求交给其他插件或系统下载器；
- 匹配时识别输入是磁力、Torrent 二进制还是 Torrent 文件路径；
- 对公开 BitTorrent v1 Torrent 计算 BTIH 并生成磁力链接；
- 拒绝私有种子、敏感 Tracker 和不支持的纯 v2 种子；
- 调用 P115StrmHelper API；
- 将 API 成功转换为 MoviePilot 标准下载成功结果；
- 将失败转换为 MoviePilot 可记录的错误结果；
- 提供配置、连接测试、日志和最小诊断信息。

### 5.3 P115StrmHelper 的职责

- 115 Cookie 和客户端管理；
- 提交离线任务；
- 把任务加入内部待整理列表；
- 查询任务状态；
- 下载完成后加入网盘整理；
- 监听 MoviePilot 整理完成；
- 生成 STRM；
- 下载关联字幕和音轨；
- 本地刮削；
- 刷新 Emby。

---

## 6. 关键设计决策

### 6.1 使用 MoviePilot 自定义下载器

在 MoviePilot 中创建：

```text
类型：p115offline
名称：115离线下载
启用：是
默认：否
路径映射：留空
```

插件通过下载器名称读取配置，并判断其类型是否为：

```text
p115offline
```

普通订阅：

```text
下载器留空
→ 使用全局默认 qBittorrent
```

指定订阅：

```text
下载器选择 115离线下载
→ 由桥接插件接管
```

### 6.2 插件优先，系统模块兜底

MoviePilot 的模块执行逻辑为：

```text
插件模块
→ 插件返回 None 时继续
→ 系统模块
```

因此桥接插件必须遵守以下返回规则。

#### 当前请求不是 115 自定义下载器

```python
return None
```

含义：

> 当前插件不处理，让 qBittorrent、Transmission 或其他插件继续处理。

#### 当前请求明确选择了 115，但输入不支持或提交失败

必须返回非空四元组：

```python
return downloader, None, None, "错误原因"
```

含义：

> 本次请求属于 115，但执行失败。不要自动落到全局 qBittorrent，避免同一个订阅资源被意外提交到另一个下载器。

#### 115 成功接受任务

```python
return downloader, info_hash, "Original", "115离线下载任务添加成功"
```

MoviePilot 检测到有效 Hash 后，会记录下载历史并把订阅任务视为已提交。

### 6.3 提交成功不等于下载完成

桥接插件返回成功只表示：

> P115StrmHelper 和 115 已经接受该离线下载任务。

下载完成由 P115StrmHelper 后续确认。

这与 qBittorrent 成功接收种子任务的语义一致。

### 6.4 支持磁力和公开 BitTorrent v1 Torrent

允许输入：

```text
str: magnet:?xt=urn:btih:...
bytes: BitTorrent v1 .torrent 二进制
Path: MoviePilot 本地缓存中的 .torrent 文件
```

处理规则：

```text
magnet
→ 直接解析 BTIH 并提交

公开 v1 torrent
→ torrentool 解析
→ 检查 private 标志和敏感 Tracker
→ 计算 info_hash
→ 生成包含 Tracker/WebSeed 的磁力链接
→ 提交 115
```

拒绝：

- `private=1` 的私有种子；
- Tracker URL 中出现个人 passkey、authkey、token 等敏感参数的种子；
- 纯 BitTorrent v2、无法生成 `btih` 的种子；
- ED2K；
- 普通 HTTP 文件下载链接；
- 无法解析的伪 Torrent 内容。

不支持时必须返回明确错误，不能伪装成功，也不能自动回退 qBittorrent。

### 6.5 不直接导入 P115StrmHelper 内部对象

桥接插件通过 HTTP API 调用官方 P115StrmHelper，而不是：

```python
from app.plugins.p115strmhelper... import ...
```

原因：

- 避免依赖插件内部目录结构；
- 避免依赖全局单例初始化顺序；
- P115StrmHelper 更新时兼容性更好；
- 桥接插件可以独立安装和卸载；
- API 是更清晰的扩展边界。

---

## 7. 运行时链路

### 7.1 成功链路

```text
1. 订阅命中资源
2. MoviePilot 获取 magnet，或先从站点下载 `.torrent` 内容
3. MoviePilot 调用 run_module("download", ...)
4. P115OfflineDownloader 判断 downloader 类型为 p115offline
5. 插件把输入规范化为磁力链接：原生磁力直接使用；公开 v1 Torrent 转换为磁力
6. 插件校验 private 标志、敏感 Tracker、BTIH 和种子版本
7. 插件 POST P115StrmHelper/add_offline_task
8. P115StrmHelper 把任务加入 115 和内部待整理列表
9. API 返回成功
10. 桥接插件向 MoviePilot 返回 downloader/hash/layout/message
11. MoviePilot 写入下载历史并更新订阅
12. P115StrmHelper 轮询任务状态
13. 下载完成后加入网盘整理
14. MoviePilot 在 115 内移动、识别和重命名
15. 监控 MP 整理生成 STRM 和字幕
16. 刷新 Emby
```

### 7.2 提交失败链路

```text
P115StrmHelper API 不可用
或插件未启用
或 115 Cookie 失效
或 115 API 返回失败
        ↓
桥接插件返回 hash=None 和错误信息
        ↓
MoviePilot 记录下载失败
        ↓
订阅资源进入失败冷却或等待后续重试
```

### 7.3 非 115 请求链路

```text
订阅没有选择 115离线下载
        ↓
桥接插件 return None
        ↓
MoviePilot 继续调用官方 qBittorrent 等模块
```

---

## 8. 插件目录结构

建议仓库结构：

```text
MoviePilot-P115OfflineDownloader/
├── README.md
├── package.v2.json
├── requirements.txt                 # 无额外依赖时可不提供
├── plugins.v2/
│   └── p115offlinedownloader/
│       ├── __init__.py
│       ├── client.py
│       ├── magnet.py
│       ├── torrent.py
│       └── schemas.py
└── tests/
    ├── test_magnet.py
    ├── test_client.py
    └── test_download_module.py
```

最小版本也可以只有：

```text
plugins.v2/p115offlinedownloader/__init__.py
```

但建议将 HTTP 客户端、磁力解析和 Torrent 转换拆开，便于测试。

---

## 9. 插件元数据

建议定义：

```python
class P115OfflineDownloader(_PluginBase):
    plugin_name = "115离线下载器"
    plugin_desc = "将MoviePilot自定义下载器任务桥接到115网盘STRM助手。"
    plugin_icon = "https://.../u115.png"
    plugin_version = "0.1.0"
    plugin_author = "YourName"
    author_url = "https://github.com/YourName"
    plugin_config_prefix = "p115offline_"
    plugin_order = 90
    auth_level = 1
```

插件 ID 建议固定为：

```text
P115OfflineDownloader
```

自定义下载器类型固定为：

```text
p115offline
```

不要把显示名称用于类型判断，因为显示名称可被用户修改。

---

## 10. 配置设计

建议配置项：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 启用插件 |
| `downloader_type` | `p115offline` | MoviePilot 自定义下载器类型 |
| `helper_base_url` | `http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper` | P115StrmHelper API 根地址 |
| `api_token` | 空 | MoviePilot Bearer Token |
| `timeout` | `30` | API 请求超时秒数 |
| `verify_ssl` | `true` | HTTPS 证书验证，本地 HTTP 不使用 |
| `allow_torrent_conversion` | `true` | 允许把公开 BitTorrent v1 Torrent 转换为磁力 |
| `normalize_hash` | `true` | 将 Base32 BTIH 转成 40 位十六进制 |
| `reject_private_torrent` | `true` | 拒绝 `private=1` 的私有种子，建议不可关闭 |
| `reject_sensitive_tracker` | `true` | 拒绝含 passkey/token 等敏感参数的 Tracker |
| `include_trackers` | `true` | 转换 Torrent 时把公开 Tracker/WebSeed 写入磁力 |
| `debug` | `false` | 输出调试日志，日志中不得输出完整磁力 |

### 10.1 API 地址

同容器调用建议：

```text
http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper
```

若 MoviePilot 后端端口通过环境变量修改，应同步修改此配置。

不要使用公网反向代理地址，避免：

- 绕行 Nginx；
- 外部 DNS；
- TLS 和证书问题；
- 将内部 Token 发往公网入口；
- 额外网络故障点。

### 10.2 Token

调用 P115StrmHelper API 时使用：

```http
Authorization: Bearer <token>
```

Token 只保存在 MoviePilot 插件配置中，不写入日志。

---

## 11. `get_module()` 设计

第一版只声明 `download`：

```python
def get_module(self) -> Dict[str, Any]:
    if not self._enabled:
        return {}
    return {
        "download": self.download,
    }
```

不声明以下方法：

```text
list_torrents
start_torrents
stop_torrents
remove_torrents
update_torrent
set_torrents_tag
transfer_completed
get_torrent_trackers
```

这样 MoviePilot 不会错误地认为插件支持对应操作。

后续版本可按需增加 `list_torrents`。

---

## 12. `download()` 接口

签名必须保持与 MoviePilot 一致：

```python
def download(
    self,
    content: Union[Path, str, bytes],
    download_dir: Path,
    cookie: str,
    episodes: Optional[Set[int]] = None,
    category: Optional[str] = None,
    label: Optional[str] = None,
    downloader: Optional[str] = None,
) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], str]]:
    ...
```

返回值：

```text
下载器配置名称
任务 Hash
种子布局
结果消息
```

### 12.1 下载器匹配

伪代码：

```python
from app.helper.downloader import DownloaderHelper

if not downloader:
    return None

if not DownloaderHelper().is_downloader(
    service_type=self._downloader_type,
    name=downloader,
):
    return None
```

必须按下载器配置的 `type` 判断，不按名称判断。

### 12.2 内容归一化

建议统一返回结构：

```python
@dataclass
class NormalizedDownload:
    magnet: Optional[str]
    info_hash: Optional[str]
    source_type: str              # magnet / torrent
    torrent_name: Optional[str]
    error: Optional[str]
```

归一化规则：

```text
str 且以 magnet: 开头
→ 解析 BTIH

bytes / bytearray
→ 先判断是否为文本磁力
→ 否则按 Torrent 二进制解析

Path
→ 读取文件内容后按 Torrent 解析

其他类型
→ 返回不支持
```

Torrent 解析使用 MoviePilot 已有依赖：

```python
from torrentool.api import Torrent
```

无需为桥接插件额外安装 Bencode 解析库。

### 12.3 完整流程伪代码

```python
def download(...):
    if not self._enabled:
        return None

    if not self._is_target_downloader(downloader):
        return None

    normalized = normalize_download_content(content)
    if normalized.error:
        return downloader, None, None, normalized.error

    magnet = normalized.magnet
    info_hash = normalized.info_hash
    if not magnet or not info_hash:
        return downloader, None, None, "无法生成可提交115的磁力链接"

    try:
        result = self._client.add_offline_task(magnet)
    except Exception as err:
        logger.error(f"115离线下载提交异常：{err}")
        return downloader, None, None, f"提交115离线下载异常：{err}"

    if not result.success:
        return downloader, None, None, result.message or "提交115离线下载失败"

    logger.info(
        "115离线下载任务提交成功："
        f"downloader={downloader}, hash={mask_hash(info_hash)}"
    )

    return downloader, info_hash, "Original", "115离线下载任务添加成功"
```

---

## 13. 磁力解析与 Torrent 转换

### 13.1 原生磁力解析

支持：

```text
40 位十六进制 BTIH
32 位 Base32 BTIH
```

```python
import base64
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
BASE32_RE = re.compile(r"^[A-Z2-7a-z2-7]{32}$")


def extract_info_hash(magnet: str) -> Optional[str]:
    query = parse_qs(urlparse(magnet).query)

    for value in query.get("xt", []):
        prefix = "urn:btih:"
        if not value.lower().startswith(prefix):
            continue

        raw_hash = value[len(prefix):].strip()

        if HEX40_RE.fullmatch(raw_hash):
            return raw_hash.lower()

        if BASE32_RE.fullmatch(raw_hash):
            try:
                return base64.b32decode(raw_hash.upper()).hex()
            except Exception:
                return None

    return None
```

### 13.2 Torrent 转换原理

BitTorrent v1 磁力链接的核心是：

```text
info_hash = SHA-1(bencode(torrent["info"]))
magnet:?xt=urn:btih:<info_hash>
```

MoviePilot 已经使用 `torrentool` 解析 `.torrent`，该库提供：

```python
Torrent.from_string(content)
torrent.info_hash
torrent.magnet_link
torrent.get_magnet(detailed=True)
torrent.private
```

桥接插件直接复用这套依赖。

### 13.3 Torrent 转换实现

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from torrentool.api import Torrent


@dataclass
class NormalizedDownload:
    magnet: Optional[str] = None
    info_hash: Optional[str] = None
    source_type: str = ""
    torrent_name: Optional[str] = None
    error: Optional[str] = None


def normalize_download_content(
    content: Union[Path, str, bytes, bytearray],
) -> NormalizedDownload:
    if isinstance(content, str):
        value = content.strip()
        if not value.lower().startswith("magnet:"):
            return NormalizedDownload(error="不支持的字符串下载内容")
        info_hash = extract_info_hash(value)
        if not info_hash:
            return NormalizedDownload(error="磁力链接中不存在有效BTIH")
        return NormalizedDownload(
            magnet=value,
            info_hash=info_hash,
            source_type="magnet",
        )

    if isinstance(content, Path):
        try:
            torrent_content = content.read_bytes()
        except OSError as err:
            return NormalizedDownload(error=f"读取种子文件失败：{err}")
    elif isinstance(content, (bytes, bytearray)):
        torrent_content = bytes(content)
    else:
        return NormalizedDownload(error="不支持的下载内容类型")

    # 某些调用方可能把磁力以 bytes 传入
    if torrent_content.startswith(b"magnet:"):
        try:
            magnet = torrent_content.decode("utf-8").strip()
        except UnicodeDecodeError:
            return NormalizedDownload(error="磁力内容不是有效UTF-8")
        info_hash = extract_info_hash(magnet)
        if not info_hash:
            return NormalizedDownload(error="磁力链接中不存在有效BTIH")
        return NormalizedDownload(
            magnet=magnet,
            info_hash=info_hash,
            source_type="magnet",
        )

    try:
        torrent = Torrent.from_string(torrent_content)
    except Exception as err:
        return NormalizedDownload(error=f"种子文件解析失败：{err}")

    if torrent.private:
        return NormalizedDownload(
            torrent_name=torrent.name,
            error="检测到私有种子，禁止提交到115",
        )

    if contains_sensitive_tracker(torrent):
        return NormalizedDownload(
            torrent_name=torrent.name,
            error="检测到含敏感认证参数的Tracker，禁止提交到115",
        )

    if is_pure_v2_torrent(torrent):
        return NormalizedDownload(
            torrent_name=torrent.name,
            error="检测到纯BitTorrent v2种子，当前不支持btmh",
        )

    info_hash = torrent.info_hash
    if not info_hash:
        return NormalizedDownload(
            torrent_name=torrent.name,
            error="无法生成BitTorrent v1 BTIH",
        )

    try:
        magnet = torrent.get_magnet(detailed=True)
    except Exception as err:
        return NormalizedDownload(
            torrent_name=torrent.name,
            error=f"生成磁力链接失败：{err}",
        )

    return NormalizedDownload(
        magnet=magnet,
        info_hash=info_hash.lower(),
        source_type="torrent",
        torrent_name=torrent.name,
    )
```

### 13.4 私有种子与敏感 Tracker 检查

必须首先检查：

```python
if torrent.private:
    ...
```

私有种子不能因为“可以计算 BTIH”就提交到 115。私有 Torrent 通常：

- 禁止 DHT/PEX；
- 必须通过指定 Tracker 获取 Peer；
- Tracker URL 可能包含用户个人 passkey；
- 需要承担上传、保种或 H&R 义务。

建议再增加敏感参数检查作为第二道防线：

```python
from urllib.parse import parse_qs, urlparse

SENSITIVE_TRACKER_PARAMS = {
    "passkey",
    "authkey",
    "torrent_pass",
    "torrent_passkey",
    "token",
    "uid",
    "user_id",
}


def contains_sensitive_tracker(torrent: Torrent) -> bool:
    for tier in torrent.announce_urls or []:
        for tracker in tier:
            query = parse_qs(urlparse(str(tracker)).query)
            if any(
                key.lower() in SENSITIVE_TRACKER_PARAMS
                for key in query
            ):
                return True
    return False


def is_pure_v2_torrent(torrent: Torrent) -> bool:
    # torrentool 当前没有公开的 v2 判定属性，这里读取其已解析的 info 字典。
    struct = getattr(torrent, "_struct", {}) or {}
    info = struct.get("info", {}) or {}
    meta_version = info.get("meta version")
    has_v1_pieces = bool(info.get("pieces"))
    return meta_version == 2 and not has_v1_pieces
```

`Torrent.info_hash` 会无条件对 `info` 字典计算 SHA-1；这不能单独用于判断种子是否具备合法的 BitTorrent v1 部分。因此必须先检查 `meta version` 和 v1 的 `pieces` 字段，再决定是否可以生成 `btih`。

该检查不能覆盖所有站点自定义参数，因此：

```text
private=1 是主要拒绝条件
敏感 Tracker 参数检查是补充保护
```

### 13.5 Tracker 与 WebSeed

转换公开 Torrent 时优先使用：

```python
torrent.get_magnet(detailed=True)
```

这样会尽量把 Torrent 中的公开 Tracker 和 WebSeed 写入磁力，提高 115 获取 Peer 和元数据的成功率。

日志中不得输出完整 Tracker 列表，因为 Tracker 可能携带敏感查询参数。

### 13.6 BitTorrent v2 限制

当前设计正式支持：

```text
BitTorrent v1：支持
已有 btih magnet：支持
公开 v1/v2 混合种子：同时存在 v1 `pieces` 时允许
纯 BitTorrent v2 btmh：不支持
```

纯 v2 使用 SHA-256 和 `urn:btmh:`，而当前桥接链路和 `P115StrmHelper` 主要围绕 `btih` 工作。不能仅检查 `torrent.info_hash`，因为 `torrentool` 仍可对纯 v2 的 `info` 字典计算一个 SHA-1 值；该值不能被当作合法 v1 BTIH。必须根据 `meta version=2` 且不存在 v1 `pieces` 来拒绝纯 v2 种子。

### 13.7 转换成功不代表 115 一定能下载

Torrent 转磁力只是把完整元信息变成 BTIH 和可选 Tracker/WebSeed。115 仍需要从 Tracker、DHT 或 Peer 获取元数据和内容。

可能失败的原因：

- Tracker 已失效或 115 无法访问；
- DHT 中没有可用 Peer；
- 没有在线做种者；
- Peer 不支持元数据交换；
- 资源太旧；
- 115 不支持该种子协议特性。

因此桥接插件的成功语义仍然只是：

```text
磁力生成成功，并且 115 已接受离线任务
```

不是“最终下载一定成功”。

### 13.8 日志脱敏

不记录完整磁力链接。

允许记录：

```text
Hash 前 8 位
资源标题
输入类型：magnet/torrent
下载器名称
API 状态码
错误摘要
```

禁止记录：

```text
完整 magnet
完整 Tracker 列表
API Token
115 Cookie
站点 Cookie
```

## 14. P115StrmHelper API 客户端

### 14.1 目标接口

```text
POST /api/v1/plugin/P115StrmHelper/add_offline_task
```

完整地址示例：

```text
http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper/add_offline_task
```

### 14.2 请求头

```http
Authorization: Bearer <token>
Content-Type: application/json
```

### 14.3 请求体

```json
{
  "links": [
    "magnet:?xt=urn:btih:..."
  ],
  "path": ""
}
```

`path` 必须为空。

原因：

```text
path 为空
→ P115StrmHelper 调用 add_urls_to_transfer
→ 加入下载完成后的网盘整理跟踪

path 非空
→ P115StrmHelper 调用 add_urls_to_path
→ 只添加下载，不进入自动整理闭环
```

### 14.4 响应处理

客户端不能只依赖 HTTP 200，还需检查 JSON 中的业务状态。

建议统一模型：

```python
@dataclass
class SubmitResult:
    success: bool
    message: str
    raw: Optional[dict] = None
```

示例：

```python
class P115HelperClient:
    def add_offline_task(self, magnet: str) -> SubmitResult:
        url = f"{self.base_url.rstrip('/')}/add_offline_task"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            json={"links": [magnet], "path": ""},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )

        if response.status_code != 200:
            return SubmitResult(
                success=False,
                message=f"P115StrmHelper API返回HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            return SubmitResult(False, "P115StrmHelper API返回非JSON响应")

        code = payload.get("code")
        message = payload.get("msg") or payload.get("message") or ""

        return SubmitResult(
            success=code == 0,
            message=message,
            raw=payload,
        )
```

具体成功字段需以当前 P115StrmHelper 实际响应为准，测试时固定样例。

---

## 15. 连接测试

插件配置页建议提供“测试连接”按钮，测试内容：

1. 后端地址可访问；
2. Token 有效；
3. P115StrmHelper 已安装；
4. P115StrmHelper 已启用；
5. 115 客户端已初始化；
6. 不提交真实下载任务。

优先调用 P115StrmHelper 的状态接口，例如：

```text
GET /api/v1/plugin/P115StrmHelper/get_status
```

若状态接口版本存在差异，可只验证 HTTP、认证和插件响应。

测试结果应显示：

```text
连接成功
插件已启用
115客户端可用
```

或明确错误：

```text
401 Token无效
404 插件接口不存在
插件未启用
115客户端未初始化
连接超时
```

---

## 16. MoviePilot 下载历史语义

MoviePilot 收到有效 Hash 后会记录：

- 下载器名称；
- 下载任务 Hash；
- 媒体标题和年份；
- 季和集；
- 订阅来源；
- 下载目录；
- 资源站点；
- 自定义识别词。

需要注意：

> MoviePilot 记录的下载路径来自其目录配置，而 115 实际下载目录来自 P115StrmHelper 配置。

两者应保持一致：

```text
MoviePilot 资源目录：/media115/inbox
P115StrmHelper 离线下载目录：/media115/inbox
P115StrmHelper 网盘待整理目录：/media115/inbox
```

桥接插件不要把 MoviePilot 传入的 `download_dir` 作为非空 `path` 发送给 P115StrmHelper，否则会绕过下载后自动整理逻辑。

---

## 17. 字幕处理

### 17.1 Torrent 内独立字幕

当磁力资源包含：

```text
Video.S01E01.mkv
Video.S01E01.zh-CN.ass
```

P115StrmHelper 下载完成后把视频和字幕交给 MoviePilot 网盘整理。

整理完成后：

```text
/media/Strm/.../Video.S01E01.strm
/media/Strm/.../Video.S01E01.zh-CN.ass
```

Emby 可直接识别外挂字幕。

### 17.2 第一版不处理站点单独字幕搜索

桥接插件不新增字幕下载逻辑。

字幕仍由：

- Torrent 自带字幕；
- P115StrmHelper 的整理事件；
- MoviePilot 原有字幕能力；

共同处理。

---

## 18. 幂等和重复提交

### 18.1 MoviePilot 侧

MoviePilot 会根据下载历史和订阅状态减少重复提交。

### 18.2 桥接插件侧

第一版不维护独立下载数据库，以 BTIH 作为任务标识。

同一个磁力被重复调用时：

- 115 可能返回重复任务；
- P115StrmHelper 可能把相同 Hash 再加入待整理跟踪；
- 具体行为依赖官方插件和 115 API。

建议增加短期内存去重：

```text
缓存键：info_hash
缓存时间：60秒
```

用途仅是防止同一调用被短时间重复提交，不替代 MoviePilot 下载历史。

不要把长期状态保存在桥接插件中，否则会与 P115StrmHelper 的任务状态形成双重状态源。

---

## 19. 已知限制

### 19.1 P115StrmHelper 待整理任务可能是内存状态

当前官方实现中，下载后待整理任务可能保存在内存列表中。

因此：

```text
任务已提交
→ MoviePilot或P115StrmHelper在下载完成前重启
→ 115仍继续下载
→ P115StrmHelper可能丢失自动整理跟踪
→ 文件留在 /media115/inbox
```

恢复方式：

```text
P115StrmHelper
→ 网盘整理
→ 手动整理 /media115/inbox
```

第一版桥接插件不解决这一问题，因为它不应复制 P115StrmHelper 的任务生命周期管理。

后续应优先向 P115StrmHelper 上游提交：

- 待整理任务持久化；
- 插件启动后恢复未完成任务；
- API 返回真实 info_hash；
- 下载失败状态通知。

### 19.2 115 下载失败后的订阅状态

MoviePilot 在任务被 115 接受时记录下载成功。

如果 115 后续下载失败：

```text
MoviePilot 已记录任务
但媒体文件没有完成
```

第一版处理方式：

- P115StrmHelper 发送失败通知；
- 用户清理对应下载历史后重新搜索或订阅；
- 后续版本再设计失败回写。

### 19.3 Torrent 转磁力的可用性限制

公开 Torrent 成功转换为磁力后，115 仍可能因为 Tracker、DHT、Peer 或元数据交换问题而下载失败。

桥接插件不得把“转换成功”解释为“资源可下载”。实际完成状态仍由 P115StrmHelper 和 115 后续任务状态决定。

### 19.4 不支持精确选集

当 MoviePilot 传入：

```python
episodes={3}
```

但磁力包含整季时，115 通常仍会下载整个任务。

插件应在日志中提示：

```text
当前任务包含选集参数，但115离线下载不支持文件级选集
```

第一版不因此拒绝任务，由用户决定哪些订阅使用 115。

---

## 20. 错误处理

### 20.1 错误分类

#### 配置错误

- 插件未启用；
- 下载器类型为空；
- API 地址为空；
- Token 为空。

#### 输入错误

- 非磁力且不是有效 Torrent；
- 磁力缺少 BTIH；
- BTIH 格式非法；
- Torrent 解析失败；
- 私有种子；
- Tracker 含敏感认证参数；
- 纯 BitTorrent v2，无法生成 BTIH。

#### API 错误

- 连接超时；
- 连接拒绝；
- HTTP 401；
- HTTP 404；
- HTTP 500；
- 非 JSON 响应；
- P115StrmHelper 返回业务失败。

#### 115 业务错误

- Cookie 失效；
- 离线任务额度或限制；
- 下载链接无效；
- 任务重复；
- 目录不可用。

### 20.2 返回策略

| 场景 | 返回值 |
|---|---|
| 不是 `p115offline` 下载器 | `None` |
| 插件未启用且选择了其他下载器 | `None` |
| 选择了 115，但输入既不是磁力也不是支持的公开 v1 Torrent | `(downloader, None, None, error)` |
| API 失败 | `(downloader, None, None, error)` |
| 提交成功 | `(downloader, hash, "Original", message)` |

### 20.3 不自动回退 qB

明确选择 115 后失败，不自动回退全局下载器。

原因：

- 可能是 PT 资源；
- 可能导致重复下载；
- 用户已经明确选择分流目标；
- 失败应可见，而不是静默改变行为。

---

## 21. 日志设计

### 21.1 正常日志

```text
【115离线下载器】接收到下载请求：downloader=115离线下载
【115离线下载器】解析磁力成功：hash=7a026b14...
【115离线下载器】任务提交成功：hash=7a026b14...
```

### 21.2 跳过日志

默认不记录所有非 115 下载请求，避免 qB 下载时刷屏。

调试模式可记录：

```text
【115离线下载器】当前下载器类型不匹配，跳过
```

### 21.3 错误日志

```text
【115离线下载器】P115StrmHelper连接超时
【115离线下载器】P115StrmHelper返回401，请检查Token
【115离线下载器】输入不是磁力或受支持的公开v1 Torrent
```

### 21.4 敏感数据

日志不得输出：

- 完整磁力；
- Tracker 参数；
- MoviePilot Token；
- 115 Cookie；
- P115StrmHelper完整响应中的敏感字段。

---

## 22. 插件配置页面

建议表单：

```text
[开关] 启用插件
[文本] 自定义下载器类型：p115offline
[文本] P115StrmHelper API地址
[密码] MoviePilot API Token
[数字] 请求超时：30
[开关] 验证HTTPS证书
[开关] 允许公开v1 Torrent转磁力
[开关] 拒绝私有Torrent（建议锁定开启）
[开关] 拒绝敏感Tracker
[开关] 转换时包含公开Tracker/WebSeed
[开关] 调试日志
[按钮] 测试连接
```

页面说明：

```text
1. 请先在MoviePilot下载器设置中创建自定义下载器。
2. 类型必须与这里一致，默认为 p115offline。
3. 不要把115离线下载器设为全局默认。
4. 只在适合的订阅中选择该下载器。
5. 支持磁力和公开 BitTorrent v1 Torrent；不支持私有PT、纯v2和精确选集。
```

---

## 23. MoviePilot 配置步骤

### 23.1 创建自定义下载器

```text
设置
→ 下载器
→ 新增自定义下载器
```

填写：

```text
类型：p115offline
名称：115离线下载
启用：开启
默认：关闭
路径映射：留空
```

### 23.2 保持普通下载器为默认

```text
qBittorrent
启用：开启
默认：开启
```

### 23.3 指定订阅

适合 115 的订阅：

```text
下载器：115离线下载
```

普通或 PT 订阅：

```text
下载器：留空
```

或明确选择 qBittorrent。

---

## 24. P115StrmHelper 配置前提

必须保持当前已验证配置：

```text
网盘整理：开启
离线下载目录：/media115/inbox
网盘待整理目录：/media115/inbox
监控MP整理：开启
本地STRM目录：/media/Strm
网盘媒体库目录：/media115/source
STRM自动刮削：开启
Emby刷新：开启
```

关闭：

```text
定时全量同步
定时增量同步
115生活事件STRM生成
云端元数据刮削
```

调用 API 时：

```json
"path": ""
```

不要改为 `/media115/inbox`。

---

## 25. Docker 部署

### 25.1 MoviePilot 保持官方镜像

```yaml
services:
  moviepilot:
    image: jxxghp/moviepilot-v2:latest
    container_name: moviepilot
    restart: unless-stopped
    environment:
      PUID: "1000"
      PGID: "1000"
      UMASK: "022"
      TZ: Asia/Shanghai
    volumes:
      - ./config:/config
      - /host/media:/media
    ports:
      - "3000:3000"
```

本方案不需要：

```text
自定义 entrypoint
/app 代码注入
Dockerfile overlay
git apply 补丁
MOVIEPILOT_AUTO_UPDATE=false 的强制要求
```

MoviePilot可继续使用官方推荐更新方式。

### 25.2 插件发布

推荐维护一个独立 MoviePilot 插件仓库，将：

```text
plugins.v2/p115offlinedownloader
package.v2.json
```

提交到自己的 GitHub 仓库。

安装方式可采用：

- MoviePilot 自定义插件市场仓库；
- 向 MoviePilot-Plugins 上游提交 PR；
- 开发阶段临时复制插件目录测试。

正式使用优先选择插件市场方式，使插件代码和数据由 MoviePilot 插件机制管理，而不是修改官方容器文件。

### 25.3 更新职责

```text
MoviePilot更新：使用官方镜像或官方内置更新
P115StrmHelper更新：使用官方插件市场
桥接插件更新：使用自己的插件仓库
```

三者独立更新。

---

## 26. 测试计划

### 26.1 单元测试

#### BTIH解析

- 40位小写十六进制；
- 40位大写十六进制；
- 32位Base32；
- 多个 `xt` 参数；
- 缺少 `xt`；
- 非BTIH `xt`；
- 非法Base32；
- 非磁力字符串。

#### 内容归一化与Torrent转换

- `str magnet`；
- `bytes magnet`；
- UTF-8解码失败；
- 合法公开v1 Torrent二进制；
- 合法Torrent `Path`；
- `private=1` Torrent；
- 含敏感Tracker参数的Torrent；
- 损坏Torrent；
- 纯v2 Torrent；
- v1/v2混合Torrent；
- `None`。

#### 下载器匹配

- 类型为 `p115offline`；
- 同名但类型不是 `p115offline`；
- 类型正确但名称不同；
- downloader为空；
- 普通qB下载器。

#### HTTP客户端

- 200成功；
- 200业务失败；
- 401；
- 404；
- 500；
- 超时；
- 非JSON；
- JSON缺少字段。

### 26.2 集成测试

#### 用例A：普通订阅

```text
下载器留空
预期：桥接插件return None，qB正常下载
```

#### 用例B：115单集磁力

```text
订阅指定115离线下载
预期：
- API成功
- MoviePilot记录Hash
- 115下载完成
- 自动整理
- STRM生成
- Emby播放
```

#### 用例C：带外挂字幕

```text
磁力包含视频和ASS/SRT
预期：
- 视频STRM生成
- 字幕保存到相同本地目录
- Emby可选择外挂字幕
```

#### 用例D：公开 Torrent 转磁力

```text
订阅指定115，站点返回公开BitTorrent v1 Torrent二进制
预期：
- 解析Torrent成功
- 生成带BTIH和公开Tracker的磁力
- 提交P115StrmHelper成功
- MoviePilot记录正确Hash
```

#### 用例E：私有 Torrent

```text
订阅指定115，站点返回private=1 Torrent
预期：明确拒绝，不提交115，不回退qB，日志不输出Tracker和passkey
```

#### 用例F：损坏或纯v2 Torrent

```text
预期：返回明确错误，不提交115，不回退qB
```

#### 用例G：Token错误

```text
预期：MoviePilot显示提交失败，日志不泄露Token
```

#### 用例H：P115StrmHelper未启用

```text
预期：连接测试失败，下载请求返回明确错误
```

#### 用例I：MoviePilot重启

分两种：

```text
提交完成前重启
提交成功但115下载未完成时重启
```

记录 P115StrmHelper 是否丢失待整理跟踪，并验证手动整理恢复流程。

### 26.3 回归测试

每次桥接插件更新后确认：

- qB默认下载不受影响；
- 手动下载不受影响；
- `/ol`仍可使用；
- P115StrmHelper网盘整理正常；
- 监控MP整理正常；
- Emby刷新正常；
- 普通PT订阅不经过115。

---

## 27. 验收标准

第一版完成需满足：

1. MoviePilot核心和前端零修改；
2. 官方Docker镜像可直接运行；
3. 插件可以通过MoviePilot插件机制安装；
4. MoviePilot可创建 `p115offline` 自定义下载器；
5. 单个订阅可选择该下载器；
6. 普通订阅继续使用默认qB；
7. 原生磁力可以提交到P115StrmHelper；
8. 公开BitTorrent v1 Torrent可以转换为磁力并提交；
9. 私有Torrent、敏感Tracker和不支持的纯v2 Torrent会被拒绝；
10. MoviePilot正确记录下载Hash；
11. 115下载完成后自动网盘整理；
12. 最终STRM生成到 `/media/Strm`；
13. 带独立字幕的资源可在Emby中使用字幕；
14. API失败不会静默回退到qB；
15. 日志不泄露Token、Cookie、完整磁力和Tracker；
16. MoviePilot和P115StrmHelper升级不直接覆盖桥接插件代码。

---

## 28. 分阶段实施

### 阶段一：最小可用版本

实现：

```text
插件基础结构
配置页面
自定义下载器类型匹配
磁力解析
公开v1 Torrent解析与转磁力
私有Torrent和敏感Tracker拒绝
P115StrmHelper API调用
download四元组返回
连接测试
日志脱敏
```

不实现：

```text
任务列表
删除任务
暂停恢复
失败回写
任务持久化
```

### 阶段二：健壮性

实现：

- Base32 BTIH；
- 混合v1/v2 Torrent兼容测试；
- 更完整的敏感Tracker规则；
- 60秒短期去重；
- 更完整错误映射；
- API兼容检测；
- 插件诊断页；
- 集成测试和CI。

### 阶段三：下载任务展示

可选实现 `list_torrents()`：

```text
P115StrmHelper /offline_tasks
        ↓
转换成 MoviePilot DownloaderTorrent
        ↓
在 MoviePilot 下载管理页只读展示115任务
```

第一阶段不应为了展示功能扩大范围。

### 阶段四：上游能力改进

向 P115StrmHelper 提交独立 PR：

- API返回实际info_hash；
- 待整理任务持久化；
- 重启恢复；
- 下载失败通知或回调；
- 按Hash查询单任务状态。

这些能力不应阻塞桥接插件第一版。

---

## 29. 安全设计

1. Token使用密码输入框；
2. 配置和日志中不输出Token；
3. 默认使用容器内部回环地址；
4. API请求设置超时；
5. HTTPS场景默认验证证书；
6. 不上传完整磁力到除P115StrmHelper之外的服务；
7. 不启用P115StrmHelper的“上传离线下载链接”；
8. 不把私有PT种子和带passkey的Tracker交给115；
9. 转换前必须检查 `private` 标志；
10. 日志不得输出完整Tracker和站点Cookie；
11. 插件只处理用户明确指定的自定义下载器；
12. 失败不自动改走其他下载器。

---

## 30. 参考代码骨架

```python
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase

from .client import P115HelperClient
from .torrent import normalize_download_content


class P115OfflineDownloader(_PluginBase):
    plugin_name = "115离线下载器"
    plugin_desc = "将MoviePilot自定义下载器任务桥接到115网盘STRM助手。"
    plugin_version = "0.1.0"
    plugin_author = "YourName"
    plugin_config_prefix = "p115offline_"
    plugin_order = 90
    auth_level = 1

    _enabled = False
    _downloader_type = "p115offline"
    _client: Optional[P115HelperClient] = None

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._downloader_type = (
            config.get("downloader_type") or "p115offline"
        ).strip().lower()

        self._client = P115HelperClient(
            base_url=config.get("helper_base_url")
            or "http://127.0.0.1:3001/api/v1/plugin/P115StrmHelper",
            token=config.get("api_token") or "",
            timeout=int(config.get("timeout") or 30),
            verify_ssl=bool(config.get("verify_ssl", True)),
        )

    def get_state(self) -> bool:
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        if not self._enabled:
            return {}
        return {"download": self.download}

    def download(
        self,
        content: Union[Path, str, bytes],
        download_dir: Path,
        cookie: str,
        episodes: Optional[Set[int]] = None,
        category: Optional[str] = None,
        label: Optional[str] = None,
        downloader: Optional[str] = None,
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], str]]:
        if not downloader:
            return None

        if not DownloaderHelper().is_downloader(
            service_type=self._downloader_type,
            name=downloader,
        ):
            return None

        normalized = normalize_download_content(content)
        if normalized.error:
            return downloader, None, None, normalized.error

        magnet = normalized.magnet
        info_hash = normalized.info_hash
        if not magnet or not info_hash:
            return downloader, None, None, "无法生成可提交115的磁力链接"

        if episodes:
            logger.warning(
                "【115离线下载器】任务包含选集参数，"
                "115离线下载不支持文件级精确选集"
            )

        result = self._client.add_offline_task(magnet)
        if not result.success:
            return downloader, None, None, result.message

        logger.info(
            f"【115离线下载器】任务提交成功：{info_hash[:8]}..."
        )
        return downloader, info_hash, "Original", "115离线下载任务添加成功"

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self):
        return None

    def stop_service(self):
        self._client = None
```

此代码仅用于表达结构，实际开发时需根据当前 MoviePilot 插件基类要求补齐 `get_form()` 等抽象方法。

---

## 31. 与旧方案的差异

旧方案：

```text
修改MoviePilot核心
增加DownloaderType.P115Offline
新增系统下载器模块
构建薄定制镜像或启动注入
维护MoviePilot补丁
```

新方案：

```text
使用官方自定义下载器
独立桥接插件get_module("download")
调用官方P115StrmHelper API
官方镜像零修改
官方插件零修改
```

废弃内容：

- 修改 `app/schemas/types.py`；
- 新增 `app/modules/p115offline`；
- 自定义 Dockerfile；
- 启动前注入补丁；
- `git apply` 兼容检查；
- 为 MoviePilot 维护长期 Fork。

---

## 32. 最终推荐

正式实施方案：

```text
MoviePilot：官方Docker镜像
P115StrmHelper：官方插件
自定义部分：独立P115OfflineDownloader插件
```

第一版实现范围：

```text
自定义下载器类型：p115offline
支持原生magnet和公开BitTorrent v1 Torrent转磁力
拒绝私有Torrent、敏感Tracker和纯v2 Torrent
调用P115StrmHelper add_offline_task
path保持空字符串
本地解析BTIH
返回MoviePilot标准下载成功四元组
失败不回退qB
```

这一方案具备以下优势：

- 改动范围最小；
- 与MoviePilot现有扩展机制一致；
- Docker部署保持官方方式；
- MoviePilot、P115StrmHelper和桥接插件可以独立更新；
- 不会因官方镜像更新覆盖核心补丁；
- 出现问题时只需停用或卸载桥接插件；
- 后续可平滑增加任务只读展示和失败恢复。

