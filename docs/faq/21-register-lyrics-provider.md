# 21. 如何通过插件匹配和下载音乐歌词？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

MoviePilot V3 已通过插件模块方法 `music_lyrics_candidates` 开放歌词候选能力。
插件负责查询歌词源、确认音轨身份并下载歌词文本，返回 `list[MusicLyrics]`；宿主
负责与其他来源聚合、择优，并按音乐歌词刮削策略写入音频文件旁的歌词文件。

这项能力使用 `_PluginBase.get_module()`，不需要注册媒体来源、事件或 HTTP 路由。
它可以为来自不同音乐元数据源的音轨补充歌词，不要求 `music.media_source` 等于
歌词服务的名称。

## 1. 注册入口与输入

从稳定 SDK 导入请求类型和返回对象：

```python
from app.sdk.media import MetaMusic, MusicInfo, MusicLyrics


def get_module(self) -> dict:
    """插件启用时声明歌词候选提供方法。"""
    if not self.get_state():
        return {}
    return {"music_lyrics_candidates": self.music_lyrics_candidates}


def music_lyrics_candidates(self, music: MetaMusic | MusicInfo) -> list[MusicLyrics]:
    """查询与当前音轨匹配的歌词，未找到时返回空列表。"""
    return []
```

宿主以 `music=...` 关键字传参，常用字段如下。字段可能缺失，不能假定输入一定
来自 MusicBrainz，也不能把专辑标题当作单曲标题。

| 字段 | 含义 |
| --- | --- |
| `title` | 当前音轨标题 |
| `artists` / `album_artist` | 音轨艺术家列表 / 专辑艺术家 |
| `album` | 专辑名称 |
| `duration` | 时长，单位为秒，可能为空 |
| `isrc` | 录音 ISRC，可能为空 |
| `media_source` / `media_id` | 音乐元数据来源与来源内身份，不是歌词服务 ID |

使用同步 `def` 注册此入口。音乐刮削当前通过同步链调用；宿主的异步歌词链也能
调用同一个同步方法，会把它放入线程池。只注册 `async def` 无法覆盖同步刮削，
也不要新增 `async_music_lyrics_candidates` 键或返回协程对象。

## 2. 返回格式与匹配责任

`MusicLyrics` 的 `provider` 为必填项，其余字段按需要提供：

| 字段 | 使用方式 |
| --- | --- |
| `provider` | 稳定的歌词来源标识，例如 `acme.lyrics` |
| `provider_id` | 歌词源自身的条目 ID，建议转为字符串 |
| `synced_lyrics` | 已下载、已解码的 LRC 文本，保存为同名 `.lrc` |
| `plain_lyrics` | 已下载、已解码的纯文本歌词，无同步歌词时保存为 `.txt` |
| `lyricsfile` | 可选的 Lyricsfile 1.0 YAML 文本，宿主尝试提取 LRC / 纯文本，并保留 `.lyricsfile.yaml` |
| `instrumental` | 确认是纯音乐时设为 `True`；宿主不为该结果生成空歌词文件 |
| `language` | 歌词语言，可选 |
| `match_score` | 匹配置信度；建议统一用 0–100，默认 0 |
| `provider_priority` | 相同质量和匹配分数下的来源优先级，数值越大越优先，默认 0 |

返回的是文本内容，不能返回 URL、文件路径、字节串、生成器或单个 `MusicLyrics`。
未匹配、无歌词或请求失败时返回 `[]`。不要同时注册旧的 `music_lyrics` 单结果入口，
避免一次刮削重复查询自己的来源。

**匹配正确性由插件负责。** 宿主不重新核对返回歌词的标题、艺术家和版本，也没有
最低 `match_score` 过滤阈值。先按 ISRC 或标题、艺术家、版本、专辑、时长确认录音
身份，再返回候选；不能把错误候选打低分后交给宿主过滤。现场版、翻唱、混音版等
有疑问时应返回空列表，不能只取搜索结果第一条。

宿主按以下规则处理候选：

1. 合并所有启用插件和内置歌词源的列表；插件返回空列表或有效结果都不会阻断
   其他来源。各 provider 按目录顺序依次调用，不会并行请求所有插件。
2. 按来源标识、来源 ID 和内容去重。相同身份内容的重复项依次比较匹配分数、
   质量和来源优先级，保留较优项。
3. 在去重后的候选中，依次按内容质量、匹配分数和来源优先级择优。质量顺序为
   有逐字时间的有效 Lyricsfile > 同步歌词 > 纯文本或纯音乐；全部相同时保留先出现项。

因此匹配分数较低的同步歌词仍可能优于匹配分数较高的纯文本歌词。`provider_priority`
只用于最终候选比较，不能改变插件执行顺序，也不能绕过匹配责任或写入策略。

Lyricsfile 需要符合宿主支持的 1.0 结构；不能把任意 YAML 或原歌词源的 JSON
直接放入该字段。已有 LRC / 纯文本的来源优先填写相应文本字段即可。

## 3. 查询、匹配和下载示例

下面是可以补入[最小插件](../Plugin_Development.md#4-最小可运行插件)的完整方法
骨架。保留主指南中的插件元数据、`get_form()`、`get_api()` 和 `get_page()`，并在
配置表单增加 `api_url` 文本项。这里的 `/search` 与 JSON 字段是**示例歌词源协议**，
不是 MoviePilot 提供的服务；接入实际歌词源时应替换请求参数、鉴权和字段映射。

示例服务返回一个列表，每项含 `id`、`title`、`artists`（字符串列表）、`album`、
`duration`（秒）、`synced_lyrics` 和 `plain_lyrics`。歌词文本随响应下载；若实际
服务只返回下载地址，需要在插件内部再次下载、解码后填入 `MusicLyrics`。

```python
import unicodedata

from app.sdk.logging import logger
from app.sdk.media import MetaMusic, MusicInfo, MusicLyrics
from app.sdk.network import RequestUtils


def init_plugin(self, config: dict | None = None) -> None:
    """读取歌词来源地址及启用状态，不在初始化时发起请求。"""
    config = config or {}
    self._enabled = bool(config.get("enabled"))
    self._api_url = str(config.get("api_url") or "").strip().rstrip("/")


def get_state(self) -> bool:
    """只有启用且已配置来源地址时参与歌词查询。"""
    return self._enabled and bool(self._api_url)


def get_module(self) -> dict:
    """注册同步歌词候选方法，供同步及异步歌词链复用。"""
    if not self.get_state():
        return {}
    return {"music_lyrics_candidates": self.music_lyrics_candidates}


@staticmethod
def _normalize_lyrics_text(value: object) -> str:
    """统一全半角、大小写和空白，保留现场版等版本文字。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def music_lyrics_candidates(self, music: MetaMusic | MusicInfo) -> list[MusicLyrics]:
    """下载示例源结果，仅返回标题、艺人及已有专辑和时长一致的歌词。"""
    if not self.get_state():
        return []
    title = self._normalize_lyrics_text(music.title)
    artists = {
        self._normalize_lyrics_text(item)
        for item in (music.artists or [music.album_artist])
        if item
    }
    if not title or not artists:
        return []
    # 示例无法独立判断版本信息；已有版本标记时保守跳过，实际来源应显式匹配。
    if getattr(music, "version", None):
        return []
    album = self._normalize_lyrics_text(music.album)
    results = self._query_lyrics_source(music)
    candidates = []
    for item in results:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        if self._normalize_lyrics_text(item.get("title")) != title:
            continue
        source_artists = item.get("artists")
        if not isinstance(source_artists, list):
            continue
        if {self._normalize_lyrics_text(value) for value in source_artists} != artists:
            continue
        if album and self._normalize_lyrics_text(item.get("album")) != album:
            continue
        if music.duration:
            duration = item.get("duration")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                continue
            if not abs(music.duration - duration) <= 2:
                continue
        synced = item.get("synced_lyrics")
        plain = item.get("plain_lyrics")
        synced = synced.strip() if isinstance(synced, str) else ""
        plain = plain.strip() if isinstance(plain, str) else ""
        if not synced and not plain:
            continue
        candidates.append(MusicLyrics(
            provider="acme.lyrics",
            provider_id=str(item["id"]),
            synced_lyrics=synced or None,
            plain_lyrics=plain or None,
            match_score=90,
            provider_priority=0,
        ))
    return candidates


def _query_lyrics_source(self, music: MetaMusic | MusicInfo) -> list[dict]:
    """使用有限网络超时下载歌词响应，失败或响应形状异常时返回空列表。"""
    response = RequestUtils(timeout=5).get_res(
        f"{self._api_url}/search",
        params={
            "title": music.title,
            "artist": " / ".join(music.artists or [music.album_artist or ""]),
            "album": music.album or "",
        },
    )
    if response is None or response.status_code != 200:
        logger.warning("歌词来源请求失败，本次不返回候选")
        return []
    try:
        payload = response.json()
    except ValueError:
        logger.warning("歌词来源返回了无效 JSON，本次不返回候选")
        return []
    return payload if isinstance(payload, list) else []


def stop_service(self) -> None:
    """停用查询；实际插件若持有客户端或后台任务，还应在此释放。"""
    self._enabled = False
```

上面的函数都应作为插件类方法加入，保留 `_normalize_lyrics_text` 的 `@staticmethod`。
匹配示例故意采用保守条件，实际源可增加可靠 ISRC 匹配、语言选择、候选数量上限与
自身版本识别规则，但不能省略身份核验。它不验证 LRC 语法；实际接入还应校验歌词
源格式，防止把 HTML 错误页或无时间戳的纯文本标记成同步歌词。

## 4. 调用时机、超时与保存策略

- 插件需已安装且 `get_state()` 为真。音乐歌词刮削策略为“跳过”时不查询；仅补充
  缺失歌词时，已有同名旁挂文件也会跳过查询。仅开启音乐标签或封面刮削不会调用此入口。
- 宿主还会聚合音频内嵌歌词及可用的内置来源。升级歌词策略允许查询更高质量候选；
  已有更高质量的旁挂文件受到保护，即使指定覆盖也不会被低质量结果替换。
- 插件不接收目标文件路径、存储类型或覆盖标志。由宿主统一为本地或远端文件命名、
  写入或上传旁挂歌词；不要从这个回调直接改写音频标签或另行创建歌词文件。
- 普通插件异常由模块调度器记录并隔离，其他来源继续执行。预期的未命中、无权限、
  限流或网络失败应自行处理并返回 `[]`，不要把占位提示当作歌词。
- `LYRICS_BATCH_TIMEOUT` 是宿主批次查询预算，进入单曲歌词聚合前检查；没有通过该
  接口传给插件，也不会强行中止已经运行的插件请求。插件必须自行设置连接和读取
  超时，约束重试、等待与候选数量；不要认为批次预算会终止无限等待。
- 插件自行管理来源鉴权、请求频率和缓存。可使用[统一缓存](15-use-system-cache.md)
  缓存命中与未命中，键中应包含来源配置、标题、艺术家、专辑、时长及必要的版本身份。
  异步歌词链可能从工作线程调用同步插件方法，共享客户端和缓存状态需保证线程安全。

## 5. 接入验证

在与插件配套的 V3 宿主中确认 `app.sdk.media` 能导入三个类型，并按
[插件测试说明](../../tests/README.md)使用宿主虚拟环境验证：

- 模拟来源返回同步歌词和纯文本，确认输出为包含真实 `MusicLyrics` 的列表。
- 错误标题、艺术家、版本、专辑或时长，以及空响应、无效 JSON、限流和网络超时，
  均不返回错误歌词。
- 多个插件、内置来源和内嵌歌词共存时，空结果与异常不会阻断其他来源；验证质量
  优先于匹配分数，以及重复候选去重。
- 插件停用、歌词策略跳过、旁挂已存在、升级与覆盖时的调用及保存行为符合预期。
- 同步与异步歌词链都能调用同一个同步插件方法，不遗留未等待的协程。

示例依赖包含 `MusicInfo`、`MusicLyrics` SDK 导出的新版 V3 宿主。发布插件时按
[版本限制说明](18-limit-moviepilot-version.md)设置实际验证过的最低宿主版本。
