import datetime
import re
import threading
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

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
    plugin_desc = "下载剧集时自动给任务打上每集独立标签（E01/E02/...），可读种子文件列表补全无历史种子，qB/Tr 通用"
    # 插件图标
    plugin_icon = "Youtube-dl_B.png"
    # 插件版本
    plugin_version = "1.1"
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
    _only_tv = True
    _skip_existing = True
    _tag_prefix = ""
    _downloaders = None

    # 文件兜底解析时识别的视频扩展名
    _VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv",
                   ".flv", ".mpeg", ".mpg", ".rmvb", ".iso", ".webm", ".m4v")

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._only_tv = config.get("only_tv", True)
            self._skip_existing = config.get("skip_existing", True)
            self._tag_prefix = (config.get("tag_prefix") or "").strip()
            self._downloaders = config.get("downloaders")

        # 停止现有任务
        self.stop_service()

        if self._enabled and self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 执行一次, 关闭 onlyonce
            self._onlyonce = False
            config.update({"onlyonce": self._onlyonce})
            self.update_config(config)
            self._scheduler.add_job(
                func=self._complement_history,
                trigger='date',
                run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
            )
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

    @staticmethod
    def _format_episodes(episodes: List[int]) -> List[str]:
        """
        每集一个独立标签，不压缩范围：[1,2,3] -> ['E01','E02','E03']
        """
        eps = sorted(set(int(e) for e in episodes))
        return [f"E{e:02d}" for e in eps]

    def _build_tags(self, episodes: List[int]) -> List[str]:
        tags = self._format_episodes(episodes)
        if self._tag_prefix:
            tags = [f"{self._tag_prefix}{t}" for t in tags]
        return tags

    # ============ 标签识别 ============

    @staticmethod
    def _is_episode_tag(tag: str) -> bool:
        """
        单集标签：以 E数字结尾（E03 / 集数-E03）
        """
        if not tag:
            return False
        return bool(re.search(r"E\d{1,3}$", tag))

    @staticmethod
    def _is_range_tag(tag: str) -> bool:
        """
        旧版范围标签：E01-E12（v1.0 产物，需迁移为每集）
        """
        if not tag:
            return False
        return bool(re.search(r"E\d{1,3}-E\d{1,3}$", tag))

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

    # ============ 打标签（含范围→每集迁移，幂等） ============

    def _apply_tags(self, service: ServiceInfo, _hash: str, new_tags: List[str]) -> bool:
        """
        追加缺失的每集标签，并移除旧版范围标签(E01-E12)。幂等：无变化则不写。
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
        to_add = [t for t in new_tags if t not in cur_set]
        to_remove = [t for t in cur if self._is_range_tag(t)]
        if not to_add and not to_remove:
            return False
        try:
            if dl_type == "qbittorrent":
                # 移除旧范围标签（参数名为 tag）
                if to_remove:
                    downloader.delete_torrents_tag(ids=_hash, tag=to_remove)
                # 追加缺失的每集标签
                if to_add:
                    downloader.set_torrents_tag(ids=_hash, tags=to_add)
            else:
                # Transmission 整体覆盖：去掉范围标签后合并每集标签
                merged = [t for t in cur if t not in set(to_remove)]
                merged = list(dict.fromkeys(merged + to_add))
                downloader.set_torrent_tag(ids=_hash, tags=merged)
            logger.info(f"{self.LOG_TAG}{service.name} {_hash[:12]} "
                        f"{('+标签 ' + ','.join(to_add)) if to_add else ''} "
                        f"{('-范围 ' + ','.join(to_remove)) if to_remove else ''}".strip())
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
            self._apply_tags(service, _hash, self._build_tags(episodes))
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
        logger.info(f"{self.LOG_TAG}开始补全集数标签 ...")
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
                    has_ep = any(self._is_episode_tag(t) for t in labels)
                    has_range = any(self._is_range_tag(t) for t in labels)
                    # 已是每集标签且无旧范围标签 → 跳过（避免重复处理）
                    if self._skip_existing and has_ep and not has_range:
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
                    self._apply_tags(service, _hash, self._build_tags(episodes))
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
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'only_tv', 'label': '跳过电影'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'skip_existing', 'label': '已标记则跳过'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即补全历史(一次)'}}
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tag_prefix',
                                            'label': '标签前缀(可选，如 集数-)',
                                            'placeholder': '留空则为纯 E01'
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
                                            'text': '每集拆成独立标签（E01、E02、E03…），不再使用 E01-E12 范围；'
                                                    '已有的范围标签会在补全时自动拆开。无下载记录的种子会读取种子文件列表解析集数。'
                                                    '电影默认跳过。'
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
            "only_tv": True,
            "skip_existing": True,
            "tag_prefix": "",
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
