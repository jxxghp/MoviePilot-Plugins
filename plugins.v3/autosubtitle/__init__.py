import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import aioshutil
import yake
from anyio import Path as AsyncPath
from app.chain.search import SearchChain
from app.core.cache import TTLCache, cached
from app.core.config import settings
from app.core.context import MediaInfo, SubtitleInfo, TorrentInfo
from app.core.event import eventmanager
from app.core.meta.metabase import MetaBase
from app.core.metainfo import MetaInfo
from app.helper.torrent import TorrentHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.file import FileItem
from app.schemas.transfer import TransferInfo
from app.schemas.types import EventType, MediaType
from app.utils.http import AsyncRequestUtils
from app.utils.system import SystemUtils


class AutoSubtitle(_PluginBase):
    # 插件名称
    plugin_name = "自动字幕下载"
    # 插件描述
    plugin_desc = "文件整理完成后自动搜索并下载缺失的字幕"
    # 插件图标
    # plugin_icon = "https://raw.githubusercontent.com/yubanmeiqin9048/MoviePilot-Plugins/main/icons/subtitle.png"
    # 插件版本
    plugin_version = "2.0.0"
    # 插件作者
    plugin_author = "yubanmeiqin9048"
    # 作者主页
    author_url = "https://github.com/yubanmeiqin9048"
    # 插件配置项ID前缀
    plugin_config_prefix = "autosubtitle_"
    # 加载顺序
    plugin_order = 2
    # 可使用的用户级别
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False
        # 文件名中的语言标识（仅用于检测已有字幕）
        self._SIMPLIFIED_FILE_MARKERS = {"zh-cn"}
        self._TRADITIONAL_FILE_MARKERS = {"zh-tw"}
        # 用于文件内容检测的常见繁体字集合
        self._TRAD_CHARS = set(
            "說見時會過個们來學開關頭門體國對發現後經麼樣點從當還沒給讓問聽"
            "實際報長東動裡種類華機產萬話風電業處際識達爾羅馬魚鳥龍書馬長"
            "兒義區彆彆後麵愛專門難擊讓體處變聲讀寫買賣進遠運"
        )
        self._HISTORY_KEY = "download_history"
        self._HISTORY_MAX = 50
        # 搜索限流：确保并发 TransferComplete 事件不会同时发起搜索
        self._search_lock = asyncio.Lock()
        # 下载去重：同一字幕 URL 30 分钟内不重复下载（剧集批量整理时防止重复下载整季包）
        self._download_cache = TTLCache(region="autosubtitle_download", maxsize=256, ttl=1800)

    # ------------------------------------------------------------------
    # 插件生命周期
    # ------------------------------------------------------------------

    def init_plugin(self, config: dict | None = None) -> None:
        if config:
            self._enabled = config.get("enabled", False) or False
            self._media_types = config.get("media_types") or ["电影"]
            self._subtitle_langs = config.get("subtitle_langs") or ["简体中文"]
            self._subtitle_priorities = config.get("subtitle_priorities") or []
            self._request_delay = float(config.get("request_delay") or 2.0)
            self._save_path_strategy = config.get("save_path_strategy") or "same"
            self._custom_save_path = config.get("custom_save_path") or ""
            self._notify = config.get("notify", False)
            self._multi_keyword = config.get("multi_keyword", False)
            self._auto_sync = config.get("auto_sync", False)
            self._skip_sync_pattern = config.get("skip_sync_pattern") or ""
            # YAKE 关键词提取器实例（top=3 配合多关键词开关使用）
            self._kw_extractor = yake.KeywordExtractor(
                n=1,
                top=3,
                lan="en",
            )
            self._subtitle_exts = set(settings.RMT_SUBEXT)
            # ffprobe 内封字幕语言标签 → 简/繁体映射
            self._embedded_simple_tags: frozenset[str] = frozenset(
                {
                    "zh-cn",
                    "zh_cn",
                    "zh-hans",
                    "zh_hans",
                    "zho-hans",
                    "zho_hans",
                    "chs",
                    "chi_sim",
                    "chi-hans",
                    "chi_hans",
                }
            )
            self._embedded_trad_tags: frozenset[str] = frozenset(
                {
                    "zh-tw",
                    "zh_tw",
                    "zh-hant",
                    "zh_hant",
                    "zho-hant",
                    "zho_hant",
                    "zh-hk",
                    "zh_hk",
                    "zh-mo",
                    "zh_mo",
                    "cht",
                    "chi_tra",
                    "chi-hant",
                    "chi_hant",
                }
            )
            self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> list[dict[str, Any]]:
        return []

    def get_page(self) -> list[dict]:
        """
        数据页面：展示最近的字幕下载历史。
        """
        return self.__build_page()

    def get_form(self) -> tuple[list[dict], dict[str, Any]]:
        return self.__build_form()

    def stop_service(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    @eventmanager.register(EventType.TransferComplete)
    async def on_transfer_complete(self, event) -> None:  # noqa: C901
        """
        监听文件整理完成事件，检查并补全缺失的字幕。

        整体流程（单次大循环）：
        1. 检查已有字幕 → missing_langs
        2. 提取关键词 → 搜索字幕
        3. __filter_results 一次遍历完成：媒体匹配 + 语言匹配 + 季/集匹配 + 排序
        4. 遍历过滤结果下载，跟踪已满足的语言，全部补齐即停止
        """
        if not self._enabled:
            return

        event_data = event.event_data
        meta: MetaBase = event_data.get("meta")
        mediainfo: MediaInfo = event_data.get("mediainfo")
        transferinfo: TransferInfo = event_data.get("transferinfo")

        if not meta or not mediainfo or not transferinfo:
            return

        # 判定媒体类型
        if mediainfo.type.value not in self._media_types:
            return

        # 确保有目标视频文件
        video_file = transferinfo.target_item
        if not video_file or not video_file.path:
            return

        logger.info(f"[AutoSubtitle] 开始处理: {video_file.name} ({mediainfo.type.value})")

        # 获取源目录（整理前的目录），用于"源目录"存放策略
        fileitem = transferinfo.fileitem
        source_dir = Path(fileitem.path).parent if fileitem and fileitem.path else None

        # 1. 检查已有字幕（直接扫描视频所在目录）
        missing_langs = await self.__check_missing_subtitles(video_file.path)
        if not missing_langs:
            logger.info("[AutoSubtitle] 已有符合要求的字幕，跳过")
            return
        missing_set = set(missing_langs)

        # 2. 提取英文关键词列表
        all_keywords = self.__extract_keywords(meta, mediainfo)
        if not all_keywords:
            logger.warning("[AutoSubtitle] 无法获取英文关键词，跳过")
            return

        # 多关键词开关控制：关闭时只用第一个，开启时逐个尝试直到有结果
        keywords = all_keywords if self._multi_keyword else all_keywords[:1]
        logger.info(f"[AutoSubtitle] 提取关键词: {keywords} (多关键词={'开' if self._multi_keyword else '关'})")

        # 3. 搜索字幕：逐个关键词尝试，成功即停止
        search_results = None
        used_keyword = None
        async with self._search_lock:
            for kw in keywords:
                results = await self.__search_subtitles(kw)
                if results:
                    search_results = results
                    used_keyword = kw
                    break
                logger.info(f"[AutoSubtitle] 关键词无结果: {kw}")

        if not search_results:
            logger.info(f"[AutoSubtitle] 所有关键词均无结果: {keywords}")
            return

        logger.info(f"[AutoSubtitle] 搜索字幕: {used_keyword} → 找到 {len(search_results)} 个结果")

        # 4. 过滤 + 匹配（一次遍历完成：媒体匹配 → 语言匹配 → 季/集匹配 → 排序）
        filtered = self.__filter_results(search_results, missing_set, meta, mediainfo)
        if not filtered:
            logger.info(f"[AutoSubtitle] 无匹配该媒体的字幕: {mediainfo.title_year or mediainfo.title}")
            return

        logger.info(f"[AutoSubtitle] 过滤后共 {len(filtered)} 个候选字幕，缺失语言: {missing_set}")

        # 5. 单次遍历下载，跟踪已满足的语言
        satisfied: set[str] = set()
        request_count = 0
        for target_sub in filtered:
            assigned_lang = getattr(target_sub, "_matched_lang", None)
            if not assigned_lang:
                continue

            sub_lang = (target_sub.language or "").strip()

            # 未知语言字幕：若当前分配的语言已满足，重分配到其他缺失语言
            if sub_lang in ("other", ""):
                remaining = missing_set - satisfied
                if assigned_lang in satisfied:
                    if not remaining:
                        continue
                    assigned_lang = next(iter(remaining))
            elif assigned_lang in satisfied:
                continue

            # 下载去重：同一字幕 URL 30 分钟内不重复下载
            download_url = (target_sub.enclosure or "").strip()
            if download_url and download_url in self._download_cache:
                logger.info(f"[AutoSubtitle] 该字幕已在 30min 内下载过，跳过: {target_sub.title}")
                continue

            # 限流：非首次请求前等待指定间隔
            if request_count > 0:
                await asyncio.sleep(self._request_delay)

            success, sub_name, effective_lang = await self.__download_and_place(
                target_sub, video_file, assigned_lang, mediainfo, source_dir, meta
            )
            request_count += 1
            if download_url:
                self._download_cache[download_url] = True

            if not success or not effective_lang:
                logger.warning(f"[AutoSubtitle] 下载失败: {sub_name}，尝试下一个")
                self._add_history(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    media_type=mediainfo.type.value,
                    lang=assigned_lang,
                    sub_name=sub_name,
                    success=False,
                )
                continue

            # effective_lang 由文件内容检测确认，可能和 assigned_lang 不同
            if effective_lang not in missing_set or effective_lang in satisfied:
                logger.info(f"[AutoSubtitle] 字幕语言({effective_lang})无需或已满足: {sub_name}，尝试下一个")
                self._add_history(
                    title=mediainfo.title,
                    year=mediainfo.year,
                    media_type=mediainfo.type.value,
                    lang=effective_lang,
                    sub_name=sub_name,
                    success=False,
                )
                continue

            satisfied.add(effective_lang)
            self._add_history(
                title=mediainfo.title,
                year=mediainfo.year,
                media_type=mediainfo.type.value,
                lang=effective_lang,
                sub_name=sub_name,
                success=True,
            )
            logger.info(f"[AutoSubtitle] 下载字幕: {sub_name} → 成功 ({effective_lang})")
            if self._notify:
                self.__send_notification(mediainfo, sub_name, effective_lang)

            if satisfied == missing_set:
                logger.info("[AutoSubtitle] 所有缺失语言已补齐，停止下载")
                break

        for lang in missing_set - satisfied:
            logger.warning(f"[AutoSubtitle] 未找到匹配的{lang}字幕")

        logger.info("[AutoSubtitle] 处理完成")

    # ------------------------------------------------------------------
    # 字幕检测
    # ------------------------------------------------------------------

    async def __check_missing_subtitles(self, video_path: str) -> list[str]:
        """
        检查已有字幕（外挂 + 内封），返回缺失的语言列表。

        三层检测：
        1. 扫描视频所在目录的外挂字幕文件（含 .!qB 等未完成 torrent 临时文件）
        2. stem 匹配但无语言标记的字幕 → 读文件内容精确判定
        3. ffprobe 检测 MKV 等容器的内封字幕流

        该方法替代了先前依赖 TransferInfo.file_list_new 的实现。
        """
        video_file = Path(video_path)
        video_stem = video_file.stem.lower()
        has_simplified, has_traditional, need_verify = self.__scan_subtitles_in_dir(video_file.parent, video_stem)

        # 对 stem 匹配的无标记字幕做内容检测
        for f in need_verify:
            if has_simplified and has_traditional:
                break
            detected = await self.__detect_subtitle_lang(f)
            if detected == "简体中文":
                has_simplified = True
            elif detected == "繁體中文":
                has_traditional = True

        # 检测内封字幕（MKV 等容器的内嵌字幕流）
        if not has_simplified or not has_traditional:
            emb_simple, emb_trad = await self.__probe_embedded_subtitles(video_path)
            has_simplified = has_simplified or emb_simple
            has_traditional = has_traditional or emb_trad

        missing: list[str] = []
        if "简体中文" in self._subtitle_langs and not has_simplified:
            missing.append("简体中文")
        if "繁體中文" in self._subtitle_langs and not has_traditional:
            missing.append("繁體中文")

        logger.info(
            f"[AutoSubtitle] 字幕检查 (目录扫描): "
            f"简体{'✓' if has_simplified else '✗'} "
            f"繁体{'✓' if has_traditional else '✗'}"
        )
        return missing

    def __scan_subtitles_in_dir(self, video_dir: Path, video_stem: str) -> tuple[bool, bool, list[Path]]:
        """扫描目录中的字幕文件，返回 (has_simplified, has_traditional, need_verify)."""
        has_simplified = False
        has_traditional = False
        need_verify: list[Path] = []

        for f in video_dir.iterdir():
            if not f.is_file():
                continue
            # 识别字幕文件：suffix 命中 OR 双层 suffix 命中（如 .srt.!qB）
            if not any(s.lower() in self._subtitle_exts for s in f.suffixes):
                continue

            name = f.name.lower()
            name_has_marker = False
            if any(m in name for m in self._SIMPLIFIED_FILE_MARKERS):
                has_simplified = True
                name_has_marker = True
            if any(m in name for m in self._TRADITIONAL_FILE_MARKERS):
                has_traditional = True
                name_has_marker = True

            if not name_has_marker and f.stem.lower() == video_stem:
                need_verify.append(f)

        return has_simplified, has_traditional, need_verify

    # ------------------------------------------------------------------
    # 关键词提取
    # ------------------------------------------------------------------

    def __extract_keywords(self, meta: MetaBase, mediainfo: MediaInfo) -> list[str]:
        """
        使用 YAKE 从英文名中提取关键词列表（按相关性排序）。

        优先 meta.en_name，备选 mediainfo.en_title。
        """
        en_name = (meta.en_name or "").strip()
        if not en_name:
            en_name = (mediainfo.en_title or "").strip()
        if not en_name:
            return []

        try:
            # 清理分隔符
            cleaned = en_name.replace(".", " ").replace("_", " ").strip()
            keywords = self._kw_extractor.extract_keywords(cleaned)
            # 去重保序
            seen: set[str] = set()
            result: list[str] = []
            for kw, _ in keywords:
                if kw and kw not in seen:
                    seen.add(kw)
                    result.append(kw)
            return result
        except Exception as e:
            logger.warning(f"[AutoSubtitle] YAKE 提取关键词失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 字幕搜索
    # ------------------------------------------------------------------

    @cached(region="autosubtitle", ttl=600, skip_none=False)
    async def __search_subtitles(self, keyword: str) -> list[SubtitleInfo] | None:
        """
        调用 SearchChain 搜索字幕。
        skip_none=False：失败结果也缓存，批量整理时同一无结果关键词不会重复搜索。
        """
        try:
            results = await SearchChain().async_search_subtitles_by_title(
                title=keyword,
                page=0,
            )
            return results if results else None
        except Exception as e:
            logger.error(f"[AutoSubtitle] 搜索异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 结果过滤（媒体匹配 → 语言匹配 → 季/集匹配 → 排序）
    # ------------------------------------------------------------------

    def __filter_results(
        self,
        results: list[SubtitleInfo],
        missing_langs: set[str],
        meta: MetaBase,
        mediainfo: MediaInfo,
    ) -> list[SubtitleInfo]:
        """
        一次遍历完成所有过滤：媒体精确匹配 → 语言匹配 → 季/集匹配 → 排序。

        每条通过过滤的字幕会被标记 `_matched_lang`（匹配到的缺失语言）。
        """
        filtered: list[SubtitleInfo] = []
        for sub in results:
            # 1. 语言匹配（返回匹配到的缺失语言名称，或 None）
            matched_lang = self.__match_language(sub, missing_langs)
            if not matched_lang:
                continue

            # 2. 媒体精确匹配（模糊搜索结果可能包含其他影视，剔除不属于本影视的字幕）
            if not self.__match_single_media(sub, mediainfo):
                continue

            # 3. 季/集匹配（电视剧）
            if not self.__match_season_episode(sub, meta, mediainfo):
                continue

            sub._matched_lang = matched_lang  # type: ignore[attr-defined]
            filtered.append(sub)

        # 4. 排序：语言精确度 > 格式偏好 > 站点优先级
        filtered.sort(key=lambda s: self.__subtitle_sort_key(s, s._matched_lang), reverse=True)  # type: ignore[attr-defined]
        return filtered

    def __match_single_media(self, sub: SubtitleInfo, mediainfo: MediaInfo) -> bool:
        """
        判断单条字幕是否属于目标影视。

        复用本体 TorrentHelper.match_torrent（标题/原标题/别名/类型/年份），
        对字幕的候选名逐一尝试匹配。
        """
        # 候选名：标题/下载文件名/描述，去空去重保持顺序
        names = list(dict.fromkeys(n.strip() for n in (sub.title, sub.file_name, sub.description) if n and n.strip()))
        for name in names:
            sub_meta = MetaInfo(title=name, subtitle=sub.description)
            sub_torrent = TorrentInfo(
                site=sub.site,
                site_name=sub.site_name,
                title=name,
                description=sub.description,
            )
            if TorrentHelper.match_torrent(mediainfo=mediainfo, torrent_meta=sub_meta, torrent=sub_torrent):
                return True
        return False

    def __match_language(self, sub: SubtitleInfo, missing_langs: set[str]) -> str | None:
        """
        判断字幕语言是否属于缺失语言集合。

        - 明确匹配：sub.language ∈ missing_langs → 返回该语言
        - 未知语言：sub.language 为 other/空 → 返回任一缺失语言（下载后通过文件内容精确判断）
        - 不匹配：→ 返回 None
        """
        sub_lang = (sub.language or "").strip()

        if sub_lang in missing_langs:
            return sub_lang

        # other / 空值 → 无法判断，归入首个缺失语言，下载后读取文件内容判定
        if sub_lang in ("other", "") and missing_langs:
            return next(iter(missing_langs))

        return None

    def __match_season_episode(self, sub: SubtitleInfo, meta: MetaBase, mediainfo: MediaInfo) -> bool:
        """
        电视剧：匹配字幕的季/集信息与目标视频。

        SubtitleInfo.to_dict() 内建的 __build_meta_info()
        会自动从标题/文件名/描述中提取 season_episode 和 episode_list。
        """
        if mediainfo.type != MediaType.TV:
            return True  # 电影跳过匹配

        sub_dict = sub.to_dict()
        sub_se = sub_dict.get("season_episode")  # e.g. "S01E05"
        sub_ep_list = sub_dict.get("episode_list")  # e.g. [5, 6, 7]

        # 字幕无季/集信息 → 可能是合集字幕，宽松通过
        if not sub_se and not sub_ep_list:
            return True

        # 目标视频的季/集
        target_season = meta.begin_season
        target_ep = meta.begin_episode
        target_ep_list = meta.episode_list

        # 精确匹配 season_episode
        if sub_se and target_season is not None and target_ep is not None:
            expected = f"S{target_season:02d}E{target_ep:02d}"
            if sub_se.upper() == expected.upper():
                return True

        # 交集匹配 episode_list
        return bool(sub_ep_list and target_ep_list and set(sub_ep_list) & set(target_ep_list))

    def __subtitle_sort_key(self, sub: SubtitleInfo, lang: str) -> tuple[int, ...]:
        """
        排序键：语言精确度 > 整季覆盖 > 字幕优先级（下载次数 > 发布时间 > 站点优先级）。
        仅启用的维度参与评分，未启用的维度得 0。高分优先。

        整季字幕（episode_list 覆盖集数多）优先于单集字幕，
        如果整季字幕下载后发现不包含目标剧集，自动回退到下一个候选。
        """
        sub_lang = (sub.language or "").strip()

        # 语言精确度：明确匹配 > other/未知
        lang_score = 0
        if sub_lang == lang:
            lang_score = 2
        elif sub_lang in ("other", ""):
            lang_score = 1

        # 整季覆盖加分：字幕覆盖集数越多越优先（最多 99 集封顶）
        season_coverage = 0
        sub_dict = sub.to_dict()
        sub_ep_list = sub_dict.get("episode_list") or []
        if sub_ep_list:
            season_coverage = min(len(sub_ep_list), 99)

        priorities = self._subtitle_priorities

        # 下载次数（越多越好）
        downloads_score = sub.grabs or 0 if "downloads" in priorities else 0

        # 发布时间（越新越好）
        pubdate_score = 0
        if "pubdate" in priorities and sub.pubdate:
            try:
                pubdate_score = datetime.strptime(sub.pubdate.split("T")[0], "%Y-%m-%d").toordinal()
            except (ValueError, IndexError):
                pass

        # 站点优先级（数字越小越优先，取反）
        site_score = -(sub.site_order or 0) if "site_order" in priorities else 0

        return (lang_score, season_coverage, downloads_score, pubdate_score, site_score)

    # ------------------------------------------------------------------
    # 文件内容语言检测
    # ------------------------------------------------------------------

    async def __detect_subtitle_lang(self, file_path: Path) -> str | None:
        """
        通过读取字幕文件内容，精确判断实际语言。

        检测策略：统计文本中的繁体特征字数量。
        - 繁体特征字 ≥ 3 个 → 判定为繁体
        - 否则 → 判定为简体

        返回 "简体中文" / "繁體中文" / None（读取失败时放行）。
        """
        try:
            content = await AsyncPath(file_path).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"[AutoSubtitle] 无法读取字幕文件内容: {e}")
            return None

        trad_count = sum(1 for c in content if c in self._TRAD_CHARS)
        return "繁體中文" if trad_count >= 3 else "简体中文"

    # ------------------------------------------------------------------
    # 内封字幕检测
    # ------------------------------------------------------------------

    async def __probe_embedded_subtitles(self, video_path: str) -> tuple[bool, bool]:
        """
        使用 ffprobe 检测视频容器内封字幕流。

        返回 (has_simplified, has_traditional)。
        ffprobe 不可用或解析失败时返回 (False, False)，不阻塞主流程。
        """
        # 检查 ffprobe 是否可用
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except FileNotFoundError:
            logger.info("[AutoSubtitle] ffprobe 未安装，跳过内封字幕检测")
            return False, False

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "s",
                video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return False, False

            streams = json.loads(stdout).get("streams") or []
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[AutoSubtitle] ffprobe 解析失败: {e}")
            return False, False

        has_simplified = False
        has_traditional = False

        for stream in streams:
            if stream.get("codec_type") != "subtitle":
                continue

            tags = stream.get("tags") or {}
            lang = (tags.get("language") or "").strip().lower()
            title = (tags.get("title") or "").strip().lower()

            simple, trad = self.__classify_embedded_lang(lang, title)
            if simple:
                has_simplified = True
            if trad:
                has_traditional = True
            if has_simplified and has_traditional:
                break

        if has_simplified or has_traditional:
            logger.info(
                f"[AutoSubtitle] 内封字幕检测: "
                f"简体{'✓' if has_simplified else '✗'} "
                f"繁体{'✓' if has_traditional else '✗'}"
            )
        return has_simplified, has_traditional

    def __classify_embedded_lang(self, lang: str, title: str) -> tuple[bool, bool]:
        """
        根据 ffprobe 语言标签判断简/繁体。返回 (is_simplified, is_traditional)。

        仅有 chi/zho/zh 标签时从 title 字段辅助推断；无法判断的标签不做假定。
        """
        if lang in self._embedded_simple_tags:
            return True, False
        if lang in self._embedded_trad_tags:
            return False, True

        # chi/zho/zh: 标签本身不分简繁，尝试从 title 推断
        if lang in ("chi", "zho", "zh"):
            if any(k in title for k in ("简", "cn", "chs", "hans")):
                return True, False
            if any(k in title for k in ("繁", "tw", "cht", "hant", "hk")):
                return False, True

        # 无法识别的标签 → 不假定包含任何一种需要的字幕
        return False, False

    # ------------------------------------------------------------------
    # 字幕时间轴同步
    # ------------------------------------------------------------------

    async def __sync_subtitle(self, sub_file: Path, video_path: str) -> bool:
        """
        使用 ffsubsync 以视频音频为参考调整字幕时间轴。

        仅在 _auto_sync 开启时调用。ffsubsync 不可用时优雅跳过。
        返回 True 表示同步成功。
        """
        if not self._auto_sync:
            return False

        # 不调轴关键字豁免：文件名匹配正则时跳过调轴
        if self._skip_sync_pattern:
            try:
                if re.search(self._skip_sync_pattern, sub_file.name):
                    logger.info(f"[AutoSubtitle] 字幕文件名匹配跳过规则，不调轴: {sub_file.name}")
                    return False
            except re.error as e:
                logger.warning(f"[AutoSubtitle] 调轴跳过规则正则错误: {e}")

        # 检查 ffsubsync 是否可用
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffsubsync",
                "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except FileNotFoundError:
            logger.warning("[AutoSubtitle] 未安装 ffsubsync，跳过调轴")
            return False

        synced = sub_file.with_name(f"{sub_file.stem}.synced{sub_file.suffix}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffsubsync",
                video_path,
                "-i",
                str(sub_file),
                "-o",
                str(synced),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0 and await AsyncPath(synced).exists():
                # 用同步后的版本替换原始文件
                await AsyncPath(synced).replace(AsyncPath(sub_file))
                logger.info(f"[AutoSubtitle] ffsubsync 调轴成功: {sub_file.name}")
                return True
            else:
                err_msg = stderr.decode(errors="ignore")[:200] if stderr else "unknown"
                logger.warning(f"[AutoSubtitle] ffsubsync 调轴失败: {err_msg}")
                return False
        except Exception as e:
            logger.warning(f"[AutoSubtitle] ffsubsync 调轴异常: {e}")
            return False

    # ------------------------------------------------------------------
    # 字幕下载与放置
    # ------------------------------------------------------------------

    async def __download_and_place(  # noqa: C901
        self,
        target_sub: SubtitleInfo,
        video_file: FileItem,
        lang: str,
        mediainfo: MediaInfo,
        source_dir: Path | None,
        meta: MetaBase,
    ) -> tuple[bool, str, str | None]:
        """
        下载字幕到临时目录 → 解压 → 内容验证 → 季包完整性校验 → 重命名 → 移动到目标位置。

        返回 (下载成功, 字幕名称, 确认的语言)。
        确认的语言为 None 表示下载失败或内容无法判定。
        """
        sub_name = target_sub.title or target_sub.file_name or "unknown"
        sub_lang = (target_sub.language or "").strip()

        # 1. 准备独立工作目录（每次下载用 uuid 子目录，并发时互不干扰）
        work_dir = self.get_data_path() / "downloads" / uuid4().hex
        await AsyncPath(work_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 2. HTTP 下载
            client = AsyncRequestUtils(
                cookies=target_sub.site_cookie,
                ua=target_sub.site_ua or settings.USER_AGENT,
                proxies=settings.PROXY if target_sub.site_proxy and settings.PROXY else {},
            )
            try:
                response = await client.get_res(target_sub.enclosure)
            except Exception as e:
                logger.error(f"[AutoSubtitle] 下载请求失败: {e}")
                return False, sub_name, None

            if not response or response.status_code != 200:
                logger.error(
                    f"[AutoSubtitle] 下载失败 "
                    f"HTTP {response.status_code if response else 'N/A'}: {target_sub.enclosure}"
                )
                return False, sub_name, None

            # 3. 解析文件名并写入临时文件
            file_name = TorrentHelper.get_url_filename(response, target_sub.enclosure)
            if not file_name:
                logger.error(f"[AutoSubtitle] 无法解析文件名: {target_sub.enclosure}")
                return False, sub_name, None

            temp_file = work_dir / file_name
            await AsyncPath(temp_file).write_bytes(response.content)

            # 4. 处理压缩包 / 提取字幕文件
            subtitle_files = await self.__extract_subtitle_files(temp_file, work_dir)
            if not subtitle_files:
                return False, sub_name, None

            # 5. 电视剧季包完整性校验：整季字幕可能不包含目标剧集
            if mediainfo.type == MediaType.TV and meta:
                target_season = getattr(meta, "begin_season", None)
                target_ep = getattr(meta, "begin_episode", None)
                if target_season is not None and target_ep is not None:
                    matching_files = []
                    for f in subtitle_files:
                        fm = MetaInfo(title=f.stem)
                        if (fm.begin_season == target_season and fm.begin_episode == target_ep) or (
                            fm.episode_list and target_ep in fm.episode_list
                        ):
                            matching_files.append(f)
                    if matching_files:
                        # 只保留匹配目标剧集的字幕文件
                        subtitle_files = matching_files
                    else:
                        # 季包未包含目标剧集，回退到下一个候选
                        logger.warning(
                            f"[AutoSubtitle] 季包不含目标剧集 S{target_season:02d}E{target_ep:02d}，回退: {sub_name}"
                        )
                        return False, sub_name, None

            # 6. 内容验证：当 sub.language 为 other/空 时，读取文件内容判断实际语言
            need_verify = sub_lang in ("other", "")
            effective_lang = lang  # 默认使用传入的语言
            if need_verify:
                detected_langs = []
                for f in subtitle_files:
                    d = await self.__detect_subtitle_lang(f)
                    if d:
                        detected_langs.append(d)
                # 以多数检测结果为准；全部不可读时放行
                effective_lang = max(set(detected_langs), key=detected_langs.count) if detected_langs else lang

            # 7. 自动调轴（以视频音频为参考，修正字幕时间偏差）
            if self._auto_sync and video_file.path:
                for f in subtitle_files:
                    await self.__sync_subtitle(f, video_file.path)

            # 8. 重命名并移动到目标目录（使用确认后的语言名）
            video_stem = Path(cast(str, video_file.name)).stem
            target_dir = self.__resolve_target_dir(video_file, mediainfo, source_dir)

            for sub_file in subtitle_files:
                dest = await self.__move_subtitle_file(sub_file, video_stem, target_dir, effective_lang)
                if dest:
                    logger.info(f"[AutoSubtitle] 字幕已移动: {dest}")

            return True, sub_name, effective_lang
        finally:
            # 9. 清理（仅清理本次下载的独立子目录，不影响其他并发下载）
            await aioshutil.rmtree(work_dir, ignore_errors=True)

    async def __extract_subtitle_files(self, temp_file: Path, save_dir: Path) -> list[Path]:
        """
        处理下载的字幕文件：压缩包解压，单文件直接返回。
        """
        ext = temp_file.suffix.lower()
        subtitle_files = []

        if ext in self._subtitle_exts:
            subtitle_files.append(temp_file)
        else:
            extract_dir = save_dir / temp_file.stem
            try:
                await asyncio.to_thread(SystemUtils.unpack_archive, temp_file, extract_dir)
                async for sub_path in AsyncPath(extract_dir).iterdir():
                    if await sub_path.is_file() and sub_path.suffix.lower() in self._subtitle_exts:
                        dest = save_dir / sub_path.name
                        await aioshutil.move(str(sub_path), str(dest))
                        subtitle_files.append(dest)
            except Exception as e:
                logger.error(f"[AutoSubtitle] 压缩包解压失败: {e}")
            finally:
                try:
                    await AsyncPath(temp_file).unlink(missing_ok=True)
                    if await AsyncPath(extract_dir).exists():
                        await aioshutil.rmtree(extract_dir, ignore_errors=True)
                except Exception:
                    pass

        return subtitle_files

    async def __move_subtitle_file(
        self,
        sub_file: Path,
        video_stem: str,
        target_dir: Path,
        lang: str,
    ) -> Path | None:
        """
        将单个字幕文件重命名并移动到目标目录。

        文件名始终包含语言标识（与 transhandler 命名规范一致）：
        - 简体中文：{video_stem}.chi.zh-cn{ext}
        - 繁体中文：{video_stem}.zh-tw{ext}
        """
        await AsyncPath(target_dir).mkdir(parents=True, exist_ok=True)

        lang_suffix = ".chi.zh-cn" if lang == "简体中文" else ".zh-tw"
        new_name = f"{video_stem}{lang_suffix}{sub_file.suffix}"
        new_path = target_dir / new_name

        if await AsyncPath(new_path).exists():
            logger.warning(f"[AutoSubtitle] 字幕文件已存在: {new_path}")
            return None

        await aioshutil.move(str(sub_file), str(new_path))
        return new_path

    def __resolve_target_dir(self, video_file: FileItem, mediainfo: MediaInfo, source_dir: Path | None) -> Path:
        """
        根据配置决定字幕存放目录。

        - same: 与目标视频同目录
        - source: 视频源目录（整理前的目录），用于触发目录监控
        - custom: 自定义路径模板
        """
        if self._save_path_strategy == "source" and source_dir:
            return source_dir
        if self._save_path_strategy == "custom" and self._custom_save_path:
            return self.__render_custom_path(mediainfo)
        # 默认：视频同目录
        return Path(cast(str, video_file.path)).parent

    def __render_custom_path(self, mediainfo: MediaInfo) -> Path:
        """
        将自定义路径模板渲染为 Path。
        支持的变量: {media_type} {title} {en_title} {year} {season} {tmdb_id}
        """
        template = self._custom_save_path
        media_type = mediainfo.type.value
        season_str = f"S{mediainfo.season:02d}" if mediainfo.season else ""

        replacements = {
            "{media_type}": media_type or "",
            "{title}": mediainfo.title or "",
            "{en_title}": mediainfo.en_title or "",
            "{year}": str(mediainfo.year) if mediainfo.year else "",
            "{season}": season_str,
            "{tmdb_id}": str(mediainfo.tmdb_id) if mediainfo.tmdb_id else "",
        }
        for var, val in replacements.items():
            template = template.replace(var, val)

        return Path(template)

    # ------------------------------------------------------------------
    # 通知
    # ------------------------------------------------------------------

    def __send_notification(self, mediainfo: MediaInfo, subtitle_name: str, lang: str) -> None:
        """发送下载完成系统通知。"""
        self.post_message(
            title=f"字幕下载完成 - {mediainfo.title_year or mediainfo.title}",
            text=f"已下载并安装{lang}中文字幕: {subtitle_name}",
            mtype=NotificationType.Plugin,
        )

    # ------------------------------------------------------------------
    # 下载历史（供数据页面展示）
    # ------------------------------------------------------------------

    def _load_history(self) -> list[dict]:
        """加载下载历史。"""
        data = self.get_data(self._HISTORY_KEY)
        if isinstance(data, str):
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return []
        if isinstance(data, list):
            return data
        return []

    def _add_history(
        self, title: str, year: str | int, media_type: str, lang: str, sub_name: str, success: bool
    ) -> None:
        """追加一条下载记录，保留最近 _HISTORY_MAX 条。"""
        history = self._load_history()
        history.insert(
            0,
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "title": str(title),
                "year": str(year) if year else "",
                "type": media_type,
                "lang": lang,
                "sub_name": sub_name,
                "success": success,
            },
        )
        if len(history) > self._HISTORY_MAX:
            history = history[: self._HISTORY_MAX]
        self.save_data(self._HISTORY_KEY, json.dumps(history, ensure_ascii=False))

    # ------------------------------------------------------------------
    # 配置表单
    # ------------------------------------------------------------------

    def __build_page(self) -> list[dict]:
        history = self._load_history()
        if not history:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": ("暂无字幕下载记录，插件启用后会自动在文件整理完成时搜索并下载缺失的字幕。"),
                    },
                }
            ]

        total = len(history)
        success_count = sum(1 for h in history if h.get("success"))
        fail_count = total - success_count

        page: list[dict] = [
            {
                "component": "VAlert",
                "props": {
                    "type": "success" if fail_count == 0 else "warning",
                    "variant": "tonal",
                    "text": (
                        f"共 {total} 次下载记录，成功 {success_count} 次，"
                        f"失败 {fail_count} 次。最多保留最近 {self._HISTORY_MAX} 条。"
                    ),
                    "class": "mb-2",
                },
            }
        ]

        for entry in history:
            success = entry.get("success")
            time_str = entry.get("time", "")
            title_str = entry.get("title", "")
            year = entry.get("year", "")
            lang_str = entry.get("lang", "")
            sub_str = entry.get("sub_name", "")

            page.append(
                {
                    "component": "VCard",
                    "props": {"class": "mb-2"},
                    "content": [
                        {
                            "component": "VCardText",
                            "content": [
                                {
                                    "component": "VRow",
                                    "props": {"align": "center"},
                                    "content": [
                                        {
                                            "component": "VCol",
                                            "props": {"cols": "auto"},
                                            "content": [
                                                {
                                                    "component": "span",
                                                    "props": {
                                                        "class": (
                                                            "text-success font-weight-bold text-h6"
                                                            if success
                                                            else "text-error font-weight-bold text-h6"
                                                        ),
                                                    },
                                                    "text": "✓" if success else "✗",
                                                }
                                            ],
                                        },
                                        {
                                            "component": "VCol",
                                            "content": [
                                                {
                                                    "component": "span",
                                                    "props": {},
                                                    "text": (f"[{time_str}] {title_str} ({year}) — {lang_str}"),
                                                },
                                                {
                                                    "component": "br",
                                                    "props": {},
                                                },
                                                {
                                                    "component": "span",
                                                    "props": {
                                                        "class": "text-caption text-grey",
                                                    },
                                                    "text": f"字幕: {sub_str}",
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )

        return page

    def __build_form(self) -> tuple[list[dict], dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    # ── 开关行 (一行四列) ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "multi_keyword",
                                            "label": "多关键词搜索",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "auto_sync",
                                            "label": "自动调轴 (需另装 ffsubsync)",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 不调轴关键字 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "skip_sync_pattern",
                                            "label": "不调轴关键字",
                                            "placeholder": "e.g. WEB|NF|Amazon",
                                            "v-show": "auto_sync",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 媒体类型 + 字幕语言 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "media_types",
                                            "label": "媒体类型",
                                            "multiple": True,
                                            "chips": True,
                                            "items": [
                                                {"title": "电影", "value": "电影"},
                                                {"title": "电视剧", "value": "电视剧"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "subtitle_langs",
                                            "label": "字幕语言",
                                            "multiple": True,
                                            "chips": True,
                                            "items": [
                                                {"title": "简体中文", "value": "简体中文"},
                                                {"title": "繁体中文", "value": "繁體中文"},
                                            ],
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 字幕优先级 + 请求间隔 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "subtitle_priorities",
                                            "label": "字幕优先级",
                                            "multiple": True,
                                            "chips": True,
                                            "items": [
                                                {"title": "下载次数", "value": "downloads"},
                                                {"title": "发布时间", "value": "pubdate"},
                                                {"title": "站点优先级", "value": "site_order"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "request_delay",
                                            "label": "请求间隔(秒)",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "save_path_strategy",
                                            "label": "存放位置",
                                            "items": [
                                                {"title": "视频同目录", "value": "same"},
                                                {"title": "视频源目录", "value": "source"},
                                                {"title": "自定义路径", "value": "custom"},
                                            ],
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 自定义路径 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "custom_save_path",
                                            "label": "自定义路径模板",
                                            "placeholder": "/media/subtitles/{media_type}/{title} ({year})",
                                            "v-show": "save_path_strategy === 'custom'",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    # ── 提示 ──
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "过多请求可能导致字幕站点封禁 IP !",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "多关键词搜索搜到即停，可能会增加搜索次数但可提高命中率。",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "media_types": ["电影"],
            "subtitle_langs": ["简体中文"],
            "subtitle_priorities": ["downloads", "pubdate", "site_order"],
            "request_delay": 2.0,
            "save_path_strategy": "same",
            "custom_save_path": "",
            "notify": False,
            "multi_keyword": False,
            "auto_sync": False,
            "skip_sync_pattern": "",
        }

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------

    def __update_config(self) -> None:
        self.update_config(
            {
                "enabled": self._enabled,
                "media_types": self._media_types,
                "subtitle_langs": self._subtitle_langs,
                "subtitle_priorities": self._subtitle_priorities,
                "request_delay": self._request_delay,
                "save_path_strategy": self._save_path_strategy,
                "custom_save_path": self._custom_save_path,
                "notify": self._notify,
                "multi_keyword": self._multi_keyword,
                "auto_sync": self._auto_sync,
                "skip_sync_pattern": self._skip_sync_pattern,
            }
        )
