from typing import List, Tuple, Dict, Any

from app.core.context import Context
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, MediaType
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.modules.themoviedb.tmdbapi import TmdbHelper

class DownloadSiteTag(_PluginBase):
    # 插件名称
    plugin_name = "下载任务分类与标签"
    # 插件描述
    plugin_desc = "自动给下载任务分类与打站点标签、剧集名称标签"
    # 插件图标
    plugin_icon = "Youtube-dl_B.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "叮叮当"
    # 作者主页
    author_url = "https://github.com/cikezhu"
    # 插件配置项ID前缀
    plugin_config_prefix = "DownloadSiteTag_"
    # 加载顺序
    plugin_order = 2
    # 可使用的用户级别
    auth_level = 1
    # 日志前缀
    LOG_TAG = "[DownloadSiteTag] "

    # 私有属性
    downloader_qb = None
    downloader_tr = None
    downloadhistory_oper = None
    tmdb_helper = None
    _enabled = False
    _onlyonce = False
    _enabled_media_tag = False
    _enabled_tag = True
    _enabled_category = False
    _category_movie = None
    _category_tv = None
    _category_anime = None

    def init_plugin(self, config: dict = None):
        self.downloader_qb = Qbittorrent()
        self.downloader_tr = Transmission()
        self.downloadhistory_oper = DownloadHistoryOper()
        self.tmdb_helper = TmdbHelper()
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._enabled_media_tag = config.get("enabled_media_tag")
            self._enabled_tag = config.get("enabled_tag")
            self._enabled_category = config.get("enabled_category")
            self._category_movie = config.get("category_movie") or "电影"
            self._category_tv = config.get("category_tv") or "电视"
            self._category_anime = config.get("category_anime") or "动漫"
        
        if self._onlyonce:
            # 执行一次, 关闭onlyonce
            self._onlyonce = False
            config.update({"onlyonce": self._onlyonce})
            self.update_config(config)
            # 补全下载历史的标签与分类
            self._complemented_history()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def _complemented_history(self):
        """
        补全下载历史的标签与分类
        """
        for DOWNLOADER in ["qbittorrent", "transmission"]:
            logger.info(f"{self.LOG_TAG}开始扫描下载器 {DOWNLOADER} ...")
            # 获取下载器中的种子
            downloader_obj = self._get_downloader(DOWNLOADER)
            if not downloader_obj:
                logger.error(f"{self.LOG_TAG} 获取下载器失败 {DOWNLOADER}")
                continue
            torrents, error = downloader_obj.get_torrents()
            # 如果下载器获取种子发生错误 或 没有种子 则跳过
            if error or not torrents:
                continue
            else:
                logger.info(f"{self.LOG_TAG}下载器 {DOWNLOADER} 种子数：{len(torrents)}")
            for torrent in torrents:
                # 获取种子hash
                _hash = self._get_hash(torrent=torrent, dl_type=DOWNLOADER)
                if not _hash:
                    continue
                # 提取种子hash对应的下载历史
                history = self.downloadhistory_oper.get_by_hash(_hash)
                if not history:
                    continue
                # 获取种子当前标签
                torrent_tags = self._get_label(torrent=torrent, dl_type=DOWNLOADER)
                torrent_cat = self._get_category(torrent=torrent, dl_type=DOWNLOADER)
                # 按设置生成需要写入的标签与分类
                _tags = []
                _cat = None
                tmdbid = history.tmdbid
                mtype = history.type
                # 站点标签, 如果勾选开关的话
                if self._enabled_tag and history.torrent_site:
                    _tags.append(history.torrent_site)
                # 媒体标题标签, 如果勾选开关的话
                if self._enabled_media_tag and history.title:
                    _tags.append(history.title)
                # 分类, 如果勾选开关的话 <tr暂不支持>
                if DOWNLOADER == "qbittorrent" and self._enabled_category:
                    # 如果是电视剧 需要区分是否动漫
                    genre_ids = None
                    if mtype == MediaType.TV:
                        # tmdb_id获取tmdb信息
                        tmdb_info = self.tmdb_helper.get_info(mtype=mtype, tmdbid=tmdbid)
                        if tmdb_info:
                            genre_ids = tmdb_info.get("genre_ids")
                    _cat = self._genre_ids_get_cat(mtype, genre_ids)
                
                # 去除种子已经存在的标签
                if _tags and torrent_tags:
                    _tags = list(set(_tags) - set(torrent_tags))
                # 如果分类一样, 那么不需要修改
                if _cat == torrent_cat:
                    _cat = None
                # 判断当前种子是否不需要修改
                if not _cat and not _tags:
                    continue
                # 执行通用方法, 设置种子标签与分类
                self._set_torrent_info(DOWNLOADER=DOWNLOADER, _hash=_hash, _tags=_tags, _cat=_cat, _original_tags=torrent_tags)

    def _genre_ids_get_cat(self, mtype, genre_ids = None):
        """
        根据genre_ids判断是否<动漫>分类
        """
        _cat = None
        if mtype == MediaType.MOVIE:
            # 电影
            _cat = self._category_movie
        elif mtype:
            ANIME_GENREIDS = settings.ANIME_GENREIDS
            if genre_ids \
                    and set(genre_ids).intersection(set(ANIME_GENREIDS)):
                # 动漫
                _cat = self._category_anime
            else:
                # 电视剧
                _cat = self._category_tv
        return _cat

    def _get_downloader(self, dtype: str):
        """
        根据类型返回下载器实例
        """
        if dtype == "qbittorrent":
            return self.downloader_qb
        elif dtype == "transmission":
            return self.downloader_tr
        else:
            return None

    def _get_hash(self, torrent: Any, dl_type: str):
        """
        获取种子hash
        """
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""

    def _get_label(self, torrent: Any, dl_type: str):
        """
        获取种子标签
        """
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if dl_type == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    def _get_category(self, torrent: Any, dl_type: str):
        """
        获取种子分类
        """
        try:
            return torrent.get("category") if dl_type == "qbittorrent" else None
        except Exception as e:
            print(str(e))
            return None

    def _set_torrent_info(self, DOWNLOADER: str, _hash: str, _tags: list, _cat: str, _original_tags: list = None):
        """
        设置种子标签与分类
        """
        # 当前下载器
        downloader_obj = self._get_downloader(DOWNLOADER)
        # 判断是否可执行
        if DOWNLOADER and downloader_obj and _hash:
            # 下载器api不通用, 因此需分开处理
            if DOWNLOADER == "qbittorrent":
                # 设置标签
                if _tags:
                    downloader_obj.set_torrents_tag(ids=_hash, tags=_tags)
                # 设置分类 <tr暂不支持>
                if _cat:
                    downloader_obj.qbc.torrents_set_category(category=_cat, torrent_hashes=_hash)
            else:
                # 设置标签
                if _tags:
                    # _original_tags = None表示未指定, 因此需要获取原始标签
                    if _original_tags == None:
                        torrent = downloader_obj.trc.get_torrent(torrent_id=_hash)
                        if torrent:
                            _original_tags = self._get_label(torrent=torrent, dl_type=DOWNLOADER)
                    # 如果原始标签不是空的, 那么合并原始标签
                    if _original_tags:
                        _tags = list(set(_original_tags).union(set(_tags)))
                    downloader_obj.set_torrent_tag(ids=_hash, tags=_tags)
            logger.warn(
                f"{self.LOG_TAG}当前下载器: {DOWNLOADER} {('  TAG: ' + ','.join(_tags)) if _tags else ''} {('  CAT: ' + _cat) if _cat else ''}")

    @eventmanager.register(EventType.DownloadAdded)
    def DownloadAdded(self, event: Event):
        """
        添加下载事件
        """
        if not self.get_state():
            return

        if not event.event_data:
            return
        
        context: Context = event.event_data.get("context")
        _hash = event.event_data.get("hash")
        _torrent = context.torrent_info
        _media = context.media_info
        _tags = []
        _cat = None
        # 站点标签, 如果勾选开关的话
        if self._enabled_tag:
           _tags.append(_torrent.site_name)
        # 媒体标题标签, 如果勾选开关的话
        if self._enabled_media_tag:
            _tags.append(_media.title)
        # 分类, 如果勾选开关的话 <tr暂不支持>
        if self._enabled_category:
            _cat = self._genre_ids_get_cat(_media.type, _media.genre_ids)
        # 执行通用方法, 设置种子标签与分类
        self._set_torrent_info(DOWNLOADER=settings.DOWNLOADER, _hash=_hash, _tags=_tags, _cat=_cat)


    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled_tag',
                                            'label': '自动站点标签',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled_media_tag',
                                            'label': '自动剧名标签',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled_category',
                                            'label': '自动设置分类',
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_movie',
                                            'label': '电影分类名称(默认: 电影)',
                                            'placeholder': '电影'
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_tv',
                                            'label': '电视分类名称(默认: 电视)',
                                            'placeholder': '电视'
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_anime',
                                            'label': '动漫分类名称(默认: 动漫)',
                                            'placeholder': '动漫'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'onlyonce',
                                    'label': '立即执行一次: 补全下载历史的标签与分类',
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：本插件将自动对下载任务打上站点标签'
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：分类只支持qb, 并提前在qb创建好分类'
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
            "enabled_tag": True,
            "enabled_media_tag": False,
            "enabled_category": False,
            "category_movie": "电影",
            "category_tv": "电视",
            "category_anime": "动漫",
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
