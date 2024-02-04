from typing import List, Tuple, Dict, Any

from app.core.context import Context
from app.core.event import eventmanager, Event
from app.schemas.types import EventType, MediaType
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission

class DownloadSiteTag(_PluginBase):
    # 插件名称
    plugin_name = "下载任务分类与标签"
    # 插件描述
    plugin_desc = "自动给下载任务分类与打站点标签"
    # 插件图标
    plugin_icon = "nfo.png"
    # 插件版本
    plugin_version = "1.1"
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

    # 私有属性
    downloader_name = None
    downloader_example = None
    _enabled = False
    _enabled_tag = True
    _enabled_category = False
    _category_movie = None
    _category_tv = None
    _category_anime = None

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._enabled_tag = config.get("enabled_tag")
            self._enabled_category = config.get("enabled_category")
            self._category_movie = config.get("category_movie") or "电影"
            self._category_tv = config.get("category_tv") or "电视"
            self._category_anime = config.get("category_anime") or "动漫"

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    @eventmanager.register(EventType.DownloadAdded)
    def DownloadAdded(self, event: Event):
        """
        添加下载事件
        """
        if not self.get_state():
            return

        if not event.event_data:
            return

        DOWNLOADER = getattr(settings, "DOWNLOADER")
        if self.downloader_name != DOWNLOADER:
            if DOWNLOADER == "qbittorrent":
                self.downloader_example = Qbittorrent()
                self.downloader_name = DOWNLOADER
            elif DOWNLOADER == "transmission":
                self.downloader_example = Transmission()
                self.downloader_name = DOWNLOADER
            else:
                self.downloader_example = None
                self.downloader_name = None
        if self.downloader_name and self.downloader_example:
            context: Context = event.event_data.get("context")
            _hash = event.event_data.get("hash")
            _torrent = context.torrent_info
            _media = context.media_info
            _media_type = None

            if self.downloader_name == "qbittorrent":
                # 设置标签, 如果勾选开关的话
                if self._enabled_tag:
                    self.downloader_example.set_torrents_tag(ids=_hash, tags=[_torrent.site_name])
                # 设置分类, 如果勾选开关的话 <tr暂不支持>
                if self._enabled_category:
                    if _media.type == MediaType.MOVIE:
                        # 电影
                        _media_type = self._category_movie
                    else:
                        ANIME_GENREIDS = getattr(settings, "ANIME_GENREIDS")
                        if _media.genre_ids \
                                and set(_media.genre_ids).intersection(set(ANIME_GENREIDS)):
                            # 动漫
                            _media_type = self._category_anime
                        else:
                            # 电视剧
                            _media_type = self._category_tv
                    # 使用qbapi进行设置
                    if _media_type:
                        self.downloader_example.qbc.torrents_set_category(category=_media_type, torrent_hashes=_hash)
            else:
                # 设置标签, 如果勾选开关的话
                if self._enabled_tag:
                    self.downloader_example.set_torrent_tag(ids=_hash, tags=[_torrent.site_name])
            logger.warn(f"[DownloadSiteTag] 当前下载器: {self.downloader_name}{('  TAG: ' + _torrent.site_name) if self._enabled_tag else ''}{('  CAT: ' + _media_type) if _media_type else ''}")

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
                                    'md': 4
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
                                    'md': 4
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
                                    'md': 4
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
                                            'text': '注意：分类功能只支持qbittorrent下载器'
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
            "enabled_tag": True,
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
