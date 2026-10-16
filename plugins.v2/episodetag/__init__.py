import datetime
import re
import threading
from typing import List, Tuple, Dict, Any, Optional, Set

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.context import Context
from app.core.event import eventmanager, Event
from app.core.metainfo import MetaInfo
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo
from app.schemas.types import EventType, MediaType


class EpisodeTag(_PluginBase):
    # 插件名称
    plugin_name = "集数标签"
    # 插件描述
    plugin_desc = "下载剧集时自动给任务打集数标签（E01、E02-03），连续集数按阈值合并，前缀/分隔符可配，改配置自动刷新存量标签，qB/Tr 通用"
    # 插件图标
    plugin_icon = "Youtube-dl_B.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "devin"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "EpisodeTag_"
    # 加载顺序
    plugin_order = 50
    # 可使用的用户级别
    auth_level = 1
    # 日志前缀
    LOG_TAG = "[EpisodeTag] "

    # 退出事件
    _event = threading.Event()
    # 私有属性
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _cron = None
    _only_tv = True
    # 标签格式：{前缀}{集数:02d}[{分隔符}{结束集数:02d}]
    _tag_prefix = "E"  # 必填，留空自动回退 E（老版本默认即 E，保持兼容）
    _merge_threshold = 2  # 连续段超过该集数时合并为一个标签；<=1 时永不合并
    _tag_separator = "-"  # 合并标签起止集数分隔符，允许为空
    _known_prefixes = ["E"]  # 历史使用过的前缀，用于识别并清理旧格式标签
    _include_tags: Set[str] = set()
    _exclude_tags: Set[str] = set()
    _downloaders = None

    # 文件兜底解析时识别的视频扩展名
    _VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv",
                   ".flv", ".mpeg", ".mpg", ".rmvb", ".iso", ".webm", ".m4v")

    def init_plugin(self, config: dict = None):
        # 记录本次 init 是否需要触发一次全量刷新（立即补全 / 标签格式变更）
        need_run_once = False
        config_changed = False
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = (config.get("cron") or "").strip()
            self._only_tv = config.get("only_tv", True)
            # 前缀必填：留空回退 E（老版本空前缀即默认 E，标签不变）
            self._tag_prefix = (config.get("tag_prefix") or "").strip() or "E"
            # 合并阈值：非法回退 2，范围 [0, 99]，<=1 视为不合并
            try:
                self._merge_threshold = int(str(config.get("merge_threshold", "2")).strip() or 2)
            except (TypeError, ValueError):
                self._merge_threshold = 2
            self._merge_threshold = max(0, min(self._merge_threshold, 99))
            # 分隔符允许为空串（区别于未配置：未配置时用默认 -）
            sep = config.get("tag_separator")
            self._tag_separator = "-" if sep is None else str(sep).strip()
            self._include_tags = self._parse_tag_filter(config.get("include_tags"))
            self._exclude_tags = self._parse_tag_filter(config.get("exclude_tags"))
            self._downloaders = config.get("downloaders")

            # 历史前缀集合：持久化到插件独立 data（不随插件配置保存/回放被覆盖回滚，
            # 否则改回旧前缀配置快照时会丢失历史前缀，导致旧格式标签无法识别清理）
            stored = self.get_data("known_prefixes") or []
            known = set(stored) | set(config.get("known_prefixes") or [])
            known.add("E")
            known.add(self._tag_prefix)
            self._known_prefixes = sorted(known)
            if self._known_prefixes != stored:
                self.save_data("known_prefixes", self._known_prefixes)

            if self._onlyonce:
                need_run_once = True
            # 标签格式快照变化（前缀/合并阈值/分隔符）→ 全量刷新已有标签
            fmt_key = f"{self._tag_prefix}|{self._merge_threshold}|{self._tag_separator}"
            if config.get("last_format") != fmt_key:
                config["last_format"] = fmt_key
                need_run_once = True
                config_changed = True
            if config.get("known_prefixes") is not None:
                # 旧值已迁移到插件 data，从配置中移除
                config.pop("known_prefixes", None)
                config_changed = True
            # 关闭 onlyonce
            if self._onlyonce:
                self._onlyonce = False
                config.update({"onlyonce": self._onlyonce})
                config_changed = True
            if config_changed:
                self.update_config(config)

        # 停止现有任务
        self.stop_service()

        if self._enabled and (need_run_once or self._cron):
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if need_run_once:
                self._scheduler.add_job(
                    func=self._complement_history,
                    trigger='date',
                    name="集数标签立即补全/格式刷新",
                    run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                )
            if self._cron:
                try:
                    self._scheduler.add_job(
                        func=self._complement_history,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="集数标签定时补全"
                    )
                except Exception as e:
                    logger.error(f"{self.LOG_TAG}定时周期配置错误，请检查: {e}")
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        根据配置返回已连接的下载器实例 {name: ServiceInfo}
        """
        if not self._downloaders:
            logger.warn(f"{self.LOG_TAG}尚未配置下载器，请检查配置")
            return None
        services = DownloaderHelper().get_services(name_filters=self._downloaders)
        if not services:
            logger.warn(f"{self.LOG_TAG}获取下载器实例失败，请检查配置")
            return None
        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warn(f"{self.LOG_TAG}下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info
        return active_services or None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    # ============ 集数提取 ============

    def _extract_episodes(self, context: Context, _hash: str,
                          service: ServiceInfo = None,
                          torrent_name: str = None) -> Optional[List[int]]:
        """
        按优先级提取集数列表：meta_info → 下载历史 → 种子标题 → 种子文件列表
        """
        # 1. 事件上下文的 meta_info
        meta = getattr(context, "meta_info", None) if context else None
        episodes = self._episodes_from_meta(meta)
        if episodes:
            return episodes

        # 2. 下载历史 episodes 字段
        history = None
        if _hash:
            try:
                history = DownloadHistoryOper().get_by_hash(_hash)
            except Exception as e:
                logger.warn(f"{self.LOG_TAG}查询下载历史失败: {e}")
        if history:
            episodes = self._parse_episodes_str(history.episodes)
            if episodes:
                return episodes

        # 3. 种子标题解析兜底
        title = torrent_name
        if not title and history:
            title = history.torrent_name
        if not title and context:
            title = getattr(getattr(context, "torrent_info", None), "title", None)
        if title:
            episodes = self._episodes_from_meta(MetaInfo(title))
            if episodes:
                return episodes

        # 4. 种子文件列表兜底（读 qB/Tr 种子内容，覆盖无下载历史的种子）
        if service and _hash:
            episodes = self._episodes_from_torrent_files(service, _hash)
            if episodes:
                return episodes

        return None

    @staticmethod
    def _episodes_from_meta(meta) -> Optional[List[int]]:
        """
        从 MetaInfo 提取集数列表
        """
        if not meta:
            return None
        try:
            episode_list = getattr(meta, "episode_list", None)
            if episode_list:
                eps = [int(e) for e in episode_list if e]
                if eps:
                    return eps
        except Exception:
            pass
        begin = getattr(meta, "begin_episode", None)
        end = getattr(meta, "end_episode", None)
        try:
            if begin and end:
                a, b = int(begin), int(end)
                if a <= b:
                    return list(range(a, b + 1))
            if begin:
                return [int(begin)]
            if end:
                return [int(end)]
        except Exception:
            return None
        return None

    @staticmethod
    def _parse_episodes_str(s: Optional[str]) -> Optional[List[int]]:
        """
        解析历史 episodes 字符串：E01 / E01-E12 / 1-12 / E01,E03 等
        """
        if not s:
            return None
        eps = []
        for part in re.split(r"[,，、\s/]+", str(s)):
            part = part.strip()
            if not part:
                continue
            # 跳过纯季号(如 S01 / S01-S02)
            if re.search(r"S\d", part) and not re.search(r"E\d", part):
                continue
            m = re.search(r"E?(\d+)\s*[-~]\s*E?(\d+)", part)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if a <= b and b - a < 1000:
                    eps.extend(range(a, b + 1))
                continue
            m = re.search(r"E?(\d+)", part)
            if m:
                eps.append(int(m.group(1)))
        return sorted(set(eps)) if eps else None

    def _episodes_from_torrent_files(self, service: ServiceInfo, _hash: str) -> Optional[List[int]]:
        """
        读取 qB/Tr 种子文件列表，仅从视频文件名中严格匹配 SxxExx / Exx 解析集数
        （严格匹配避免整季 Complete 标题被误判为某集）
        """
        if not service or not service.instance or not _hash:
            return None
        try:
            files = service.instance.get_files(_hash)
        except Exception as e:
            logger.warn(f"{self.LOG_TAG}读取种子文件列表失败: {e}")
            return None
        if not files:
            return None
        eps = []
        for f in files:
            fn = getattr(f, "name", None) or (f.get("name") if isinstance(f, dict) else str(f))
            if not fn or not fn.lower().endswith(self._VIDEO_EXTS):
                continue
            # 优先 SxxExx
            ms = re.findall(r"[Ss]\d{1,2}[Ee](\d{1,3})", fn)
            if ms:
                eps.extend(int(x) for x in ms)
                continue
            # 其次独立的 Exx（前后需有边界，避免误抓数字）
            ms = re.findall(r"(?:^|[._\-\s])[Ee](\d{1,3})(?!\d)", fn)
            if ms:
                eps.extend(int(x) for x in ms)
        return sorted(set(eps)) if eps else None

    # ============ 标签构造 ============

    def _format_episodes(self, episodes: List[int]) -> List[str]:
        """
        按当前配置生成集数标签：连续集数段超过合并阈值时合并为一个标签，
        否则每集独立。格式：{前缀}{集:02d} 或 {前缀}{起:02d}{分隔符}{止:02d}
        例（前缀E、阈值2、分隔符-）：[1,2] -> E01,E02；[1,2,3] -> E01-03
        """
        eps = sorted(set(int(e) for e in episodes))
        if not eps:
            return []
        prefix, sep, threshold = self._tag_prefix, self._tag_separator, self._merge_threshold
        if threshold <= 1:
            # 阈值 <=1：不合并，每集独立标签
            return [f"{prefix}{e:02d}" for e in eps]
        tags = []
        seg = [eps[0]]
        for e in eps[1:]:
            if e == seg[-1] + 1:
                seg.append(e)
            else:
                tags.extend(self._segment_tags(seg, prefix, sep, threshold))
                seg = [e]
        tags.extend(self._segment_tags(seg, prefix, sep, threshold))
        return tags

    @staticmethod
    def _segment_tags(seg: List[int], prefix: str, sep: str, threshold: int) -> List[str]:
        """
        单个连续集数段 -> 标签列表：段长 > 阈值合并，否则拆开
        """
        if len(seg) > threshold:
            return [f"{prefix}{seg[0]:02d}{sep}{seg[-1]:02d}"]
        return [f"{prefix}{e:02d}" for e in seg]

    # ============ 插件标签识别（含历史格式迁移清理） ============

    def _is_plugin_tag(self, tag: str) -> bool:
        """
        判断标签是否为本插件产物（含所有历史版本格式），用于迁移/清理：
        1. 老版默认格式：以 E数字 结尾（E01 / 自定义前缀-E03 / v1.0 范围 E01-E12）
        2. 新格式：{已知前缀}{1-3位数字}[{<=3位分隔}{1-3位数字}]
        """
        if not tag:
            return False
        if re.search(r"E\d{1,3}$", tag):
            return True
        for p in self._known_prefixes:
            if re.match(rf"^{re.escape(p)}\d{{1,3}}(?:\S{{0,3}}\d{{1,3}})?$", tag):
                return True
        return False
    # ============ 存量扫描标签过滤 ============

    @staticmethod
    def _parse_tag_filter(s: Any) -> Set[str]:
        """
        解析包含/排除标签配置：逗号（中英文/顿号）分隔，去重。
        不按空格分词，以支持含空格的标签名整名匹配
        """
        if not s:
            return set()
        return {t.strip() for t in re.split(r"[,，、]+", str(s)) if t.strip()}

    def _match_tags(self, labels: List[str]) -> bool:
        """
        存量种子按标签过滤：命中任一排除标签 → 跳过；配置了包含标签且未命中任一 → 跳过；包含为空 → 全部处理
        """
        if not self._include_tags and not self._exclude_tags:
            return True
        label_set = set(labels or [])
        if self._exclude_tags and (label_set & self._exclude_tags):
            return False
        if self._include_tags and not (label_set & self._include_tags):
            return False
        return True

    # ============ qB / Tr 种子字段兼容 ============

    @staticmethod
    def _get_hash(torrent: Any, dl_type: str) -> Optional[str]:
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception:
            return None

    @staticmethod
    def _get_labels(torrent: Any, dl_type: str) -> List[str]:
        try:
            if dl_type == "qbittorrent":
                return [t.strip() for t in (torrent.get("tags") or "").split(",") if t.strip()]
            return [str(t).strip() for t in (torrent.labels or []) if str(t).strip()]
        except Exception:
            return []

    @staticmethod
    def _get_torrent_name(torrent: Any, dl_type: str) -> Optional[str]:
        try:
            return torrent.get("name") if dl_type == "qbittorrent" else torrent.name
        except Exception:
            return None

    # ============ 打标签（含旧格式迁移，幂等） ============

    def _apply_tags(self, service: ServiceInfo, _hash: str, new_tags: List[str]) -> bool:
        """
        按当前格式对齐标签：追加缺失标签，移除所有旧格式/多余的本插件标签。
        幂等：无变化则不写。非本插件标签不受影响。
        """
        if not service or not service.instance or not _hash or not new_tags:
            return False
        downloader = service.instance
        dl_type = service.type
        try:
            torrents, error = downloader.get_torrents(ids=_hash)
            cur = self._get_labels(torrents[0], dl_type) if (torrents and not error) else []
        except Exception as e:
            logger.warn(f"{self.LOG_TAG}读取种子当前标签失败: {e}")
            cur = []
        cur_set = set(cur)
        new_set = set(new_tags)
        to_add = [t for t in new_tags if t not in cur_set]
        to_remove = [t for t in cur if self._is_plugin_tag(t) and t not in new_set]
        if not to_add and not to_remove:
            return False
        try:
            if dl_type == "qbittorrent":
                # 移除旧格式标签（参数名为 tag）
                if to_remove:
                    downloader.delete_torrents_tag(ids=_hash, tag=to_remove)
                # 追加缺失标签
                if to_add:
                    downloader.set_torrents_tag(ids=_hash, tags=to_add)
            else:
                # Transmission 整体覆盖：去掉旧标签后合并新标签
                merged = [t for t in cur if t not in set(to_remove)]
                merged = list(dict.fromkeys(merged + to_add))
                downloader.set_torrent_tag(ids=_hash, tags=merged)
            logger.info(f"{self.LOG_TAG}{service.name} {_hash[:12]} "
                        f"{('+标签 ' + ','.join(to_add)) if to_add else ''} "
                        f"{('-旧 ' + ','.join(to_remove)) if to_remove else ''}".strip())
            return True
        except Exception as e:
            logger.error(f"{self.LOG_TAG}设置标签失败: {e}")
            return False

    # ============ 即时打标签：下载加入事件 ============

    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
        """
        下载加入事件：自动给剧集任务打每集标签
        """
        if not self.get_state() or not event.event_data:
            return
        try:
            downloader = event.event_data.get("downloader")
            service = self.service_infos.get(downloader) if downloader else None
            if not service:
                return
            context: Context = event.event_data.get("context")
            _hash = event.event_data.get("hash")
            if not _hash:
                return
            # 仅剧集：跳过电影
            if self._only_tv:
                media = getattr(context, "media_info", None) if context else None
                if media and getattr(media, "type", None) == MediaType.MOVIE:
                    return
            episodes = self._extract_episodes(context, _hash, service=service)
            if not episodes:
                return
            self._apply_tags(service, _hash, self._format_episodes(episodes))
        except Exception as e:
            logger.error(f"{self.LOG_TAG}处理下载加入事件失败: {e}")

    # ============ 一次性补全历史 ============

    def _complement_history(self):
        """
        扫描所有监听下载器，给剧集种子补每集标签（含无历史种子的文件列表兜底，迁移旧范围标签）
        """
        services = self.service_infos
        if not services:
            logger.warning(f"{self.LOG_TAG}没有可用的下载器，跳过补全")
            return
        logger.info(f"{self.LOG_TAG}开始补全集数标签 ..."
                    f"{(' 包含标签[' + ','.join(sorted(self._include_tags)) + ']') if self._include_tags else ''}"
                    f"{(' 排除标签[' + ','.join(sorted(self._exclude_tags)) + ']') if self._exclude_tags else ''}")
        downloadhis = DownloadHistoryOper()
        for service in services.values():
            if self._event.is_set():
                logger.info(f"{self.LOG_TAG}停止服务")
                return
            downloader = service.instance
            dl_type = service.type
            logger.info(f"{self.LOG_TAG}扫描下载器 {service.name} ...")
            try:
                torrents, error = downloader.get_torrents()
            except Exception as e:
                logger.error(f"{self.LOG_TAG}获取种子失败 {service.name}: {e}")
                continue
            if error or not torrents:
                continue
            for torrent in torrents:
                try:
                    if self._event.is_set():
                        return
                    _hash = self._get_hash(torrent, dl_type)
                    if not _hash:
                        continue
                    labels = self._get_labels(torrent, dl_type)
                    # 包含/排除标签过滤（仅影响存量扫描，不影响下载加入事件）
                    if not self._match_tags(labels):
                        continue
                    # 仅剧集：跳过电影
                    history = downloadhis.get_by_hash(_hash)
                    if self._only_tv:
                        try:
                            if history and history.type and MediaType(history.type) == MediaType.MOVIE:
                                continue
                        except Exception:
                            pass
                    torrent_name = self._get_torrent_name(torrent, dl_type)
                    episodes = self._extract_episodes(None, _hash, service=service, torrent_name=torrent_name)
                    if not episodes:
                        continue
                    new_tags = self._format_episodes(episodes)
                    # 已是当前格式（插件标签集合完全一致）→ 跳过，无需重打；
                    # 旧格式标签（v1.0 范围 / v1.x 前缀或阈值差异）会在 _apply_tags 中自动迁移
                    if {t for t in labels if self._is_plugin_tag(t)} == set(new_tags):
                        continue
                    self._apply_tags(service, _hash, new_tags)
                except Exception as e:
                    logger.error(f"{self.LOG_TAG}补全种子失败: {e}")
        logger.info(f"{self.LOG_TAG}补全完成")

    # ============ 配置页面 ============

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'only_tv', 'label': '跳过电影'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即补全/刷新(一次)'}}
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{'title': config.name, 'value': config.name}
                                                      for config in DownloaderHelper().get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '定时补全周期',
                                            'placeholder': '0 3 * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'include_tags',
                                            'label': '包含标签(可选)',
                                            'placeholder': '逗号分隔，如：电视剧,动漫；留空则处理全部'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude_tags',
                                            'label': '排除标签(可选)',
                                            'placeholder': '逗号分隔，如：电影,手动管理'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tag_prefix',
                                            'label': '标签前缀',
                                            'placeholder': '默认 E，必填；留空自动回退 E'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'merge_threshold',
                                            'label': '合并阈值',
                                            'placeholder': '默认 2；连续超过该集数则合并，≤1 不合并'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tag_separator',
                                            'label': '合并分隔符',
                                            'placeholder': '默认 -，可改为空或其他字符'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '标签格式：{前缀}{集数}，连续集数超过合并阈值时合并为一个标签（如 E01-03）。'
                                                    '前缀默认 E（必填，留空自动回退 E，老版本默认 E 无缝兼容）；'
                                                    '合并阈值默认 2（连续 ≤2 集各打一个标签，≥3 集合并为一个；≤1 则永不合并）；'
                                                    '分隔符默认 -（可改为空）。'
                                                    '修改前缀/合并阈值/分隔符保存后会自动全量刷新所有种子的标签到新格式，'
                                                    '旧版本标签（E01-E12 范围、旧前缀）在补全/刷新时自动迁移。'
                                                    '无下载记录的种子会读取种子文件列表解析集数；电影默认跳过。'
                                                    '命中任一排除标签的种子跳过；配置了包含标签时仅处理命中任一包含标签的种子（留空则处理全部）。'
                                                    '标签过滤仅影响存量扫描（定时/立即补全），不影响新下载任务的即时打标签。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "",
            "only_tv": True,
            "tag_prefix": "E",
            "merge_threshold": 2,
            "tag_separator": "-",
            "include_tags": "",
            "exclude_tags": "",
            "downloaders": None
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
