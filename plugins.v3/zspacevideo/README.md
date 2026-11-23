# 极空间影视（ZSpaceVideo）

用极空间官方 OAuth 授权（`zspace-cli`，不用 cookie）连接极影视：MoviePilot 整理完成后只刷新包含该目录的分类；极影视里看完的片子集中列出，可按选项移出库或连同做种一起删除。

完整说明与截图：<https://github.com/xiaoyaner0201/MoviePilot-ZSpaceVideo>

![已看列表](https://raw.githubusercontent.com/xiaoyaner0201/MoviePilot-ZSpaceVideo/main/docs/images/watched-list.png)

## 功能

- **官方授权**：插件页点「开始授权」→ 登录极空间 → 粘贴一次性授权码。凭证只存插件数据目录（0700），授权码不进日志、配置、命令参数和环境变量。`zspace-cli` 按版本、字节数和 SHA-256 固定，校验不过不执行。
- **按目录刷新**：整理完成事件 → 换算成极空间路径 → 找包含它的极影视分类 → 去抖合并（默认安静 60 秒、最多 300 秒）→ 重新扫描该目录并查询到完成。失败发站内消息，同类问题只提醒一次。
- **已看列表**：电影以「已看过」为准；剧集只认整季标记。每部片列出全部版本（洗版前后、辅种、库入口与做种文件按硬链接归组），显示大小、做种状态和站点。
- **三档删除**：`不删`（默认）/ `只从库里移除`（删库入口，继续做种，不腾空间）/ `真删除`（库入口 + 做种文件 + 全部相关 qB 任务含辅种）。先预览冻结清单，执行前逐项核对，变了就整单不执行。
- **保守默认**：认不出季号的文件（如蓝光原盘）真删除默认跳过，需手动确认；自动删除默认关闭，只处理打开之后才首次看完、且过了缓冲期（默认 7 天，最少 1 天）的条目。

## 前置条件

- MoviePilot V3 ≥ 3.2.8，运行在极空间 Docker（Linux x64 / arm64），可访问外网下载 `zspace-cli`。
- 推荐把极影视数据库目录只读挂进容器：`/zspace/zsrp/sqlite/zvideo:/zvideo:ro`。插件只用它查「分类 ↔ 目录」，不写入。不挂时在设置里手动填写分类目录。

## 注意

- 真删除会删除做种文件和 qB 任务（含辅种），删了只能重新下载。
- 同一极空间账号再次授权，会让之前的授权失效。
- 局域网直连是明文 HTTP；默认的官方云中转走 HTTPS。
- 极空间的重新扫描接口对不属于该分类的路径也返回成功，所以目录归属由插件读只读数据库或手动配置判断。

第三方组件：zspace-nas-agent-toolkit（MIT）。

<details>
<summary>English</summary>

# ZSpace Video (ZSpaceVideo)

Connects MoviePilot to ZSpace's video library (极影视) through ZSpace's official OAuth (`zspace-cli`, no cookies). After MoviePilot organizes a title, only the categories containing that folder are rescanned. Titles you have finished are listed in one place, and you can remove them from the library or delete them together with their seeding files.

Full documentation and screenshots: <https://github.com/xiaoyaner0201/MoviePilot-ZSpaceVideo>

![Watched list](https://raw.githubusercontent.com/xiaoyaner0201/MoviePilot-ZSpaceVideo/main/docs/images/watched-list.png)

## Features

- **Official authorization**: click "Start authorization" in the plugin, sign in to ZSpace, paste the one-time code back. Credentials stay in the plugin data directory (0700); the code never reaches logs, config, command-line arguments or environment variables. `zspace-cli` is pinned by version, byte size and SHA-256 and is not run if verification fails.
- **Per-folder rescans**: transfer-complete event → ZSpace path → categories containing it → debounce (60 s quiet, 300 s cap by default) → rescan that folder and poll until done. Failures send one in-app message per kind of problem.
- **Watched list**: movies follow the "watched" flag; TV only counts whole-season marks. Every version of a title is listed (before/after upgrades, cross-seeds, library entries and seeding files grouped by hard link) with size, seeding state and sites.
- **Three deletion modes**: `Keep` (default) / `Remove from library` (delete the library link, keep seeding, frees no space) / `Delete for real` (library entry + seeding files + every related qBittorrent task including cross-seeds). A preview freezes the plan; execution re-checks every item and refuses the whole plan if anything changed.
- **Conservative defaults**: files whose season cannot be determined (such as Blu-ray discs) are skipped by real deletion unless confirmed by hand; automatic deletion is off by default and only handles titles first seen as watched after it was enabled and past the buffer period (7 days by default, at least 1 day).

## Requirements

- MoviePilot V3 3.2.8 or later, in Docker on the ZSpace NAS (Linux x64 / arm64), with internet access to download `zspace-cli`.
- Recommended: mount ZSpace's video database folder read-only: `/zspace/zsrp/sqlite/zvideo:/zvideo:ro`. The plugin only reads category-to-folder mappings from it. Without the mount, enter category folders in the settings.

## Notes

- Real deletion removes seeding files and qBittorrent tasks (cross-seeds included); the only way back is downloading again.
- Authorizing the same ZSpace account again invalidates the previous authorization.
- LAN direct mode uses plain HTTP; the default official cloud relay uses HTTPS.
- ZSpace's rescan API reports success even for folders outside the category, so the plugin decides folder ownership from the read-only database or the manual settings.

Third-party component: zspace-nas-agent-toolkit (MIT).

</details>
