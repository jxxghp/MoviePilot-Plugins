import base64
import json
import threading
import time
import importlib.util
import sys
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, Union
from pydantic import BaseModel
from requests import RequestException
from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.meta import MetaBase
from app.log import logger
from app.modules.emby import Emby
from app.modules.jellyfin import Jellyfin
from app.modules.plex import Plex
from app.modules.themoviedb.tmdbv3api import TV
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.common import retry
from app.utils.http import RequestUtils
from app.db.models import PluginData


class ExistMediaInfo(BaseModel):
    # 季, 集
    groupep: Optional[Dict[int, list]] = {}
    # 集在媒体服务器的ID
    groupid: Optional[Dict[int, List[list]]] = {}
    # 媒体服务器类型
    server_type: Optional[str] = None
    # 媒体服务器名字
    server: Optional[str] = None
    # 媒体ID
    itemid: Optional[Union[str, int]] = None


class EpisodeGroupMeta(_PluginBase):
    # 插件名称
    plugin_name = "TMDB剧集组刮削"
    # 插件描述
    plugin_desc = "从TMDB剧集组刮削季集的实际顺序。"
    # 插件图标
    plugin_icon = "Element_A.png"
    # 主题色
    plugin_color = "#098663"
    # 插件版本
    plugin_version = "2.6.1"
    # 插件作者
    plugin_author = "叮叮当"
    # 作者主页
    author_url = "https://github.com/cikezhu"
    # 插件配置项ID前缀
    plugin_config_prefix = "EpisodeGroupMeta_"
    # 加载顺序
    plugin_order = 29
    # 可使用的用户级别
    auth_level = 1

    # 退出事件
    _event = threading.Event()

    # 私有属性
    tv = None
    emby = None
    plex = None
    jellyfin = None
    mediaserver_helper = None

    _enabled = False
    _notify = True
    _autorun = True
    _ignorelock = False
    _delay = 0
    _allowlist = []

    def init_plugin(self, config: dict = None):
        self.tv = TV()
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._autorun = config.get("autorun")
            self._ignorelock = config.get("ignorelock")
            self._delay = config.get("delay") or 120
            self._allowlist = []
            for s in str(config.get("allowlist", "")).split(","):
                s = s.strip()
                if s and s not in self._allowlist:
                    self._allowlist.append(s)
            self.log_info(f"白名单数量: {len(self._allowlist)} > {self._allowlist}")
            if not ("notify" in config):
                # 新版本v2.0更新插件配置默认配置
                self._notify = True
                self._autorun = True
                config["notify"] = True
                config["autorun"] = True
                self.update_config(config)
                self.log_warn(f"新版本v{self.plugin_version} 配置修正 ...")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        # plugin/EpisodeGroupMeta/delete_media_database
        # plugin/EpisodeGroupMeta/start_rt
        self.log_warn("api已添加: /start_rt")
        self.log_warn("api已添加: /delete_media_database")
        return [
            {
                "path": "/delete_media_database",
                "endpoint": self.delete_media_database,
                "methods": ["GET"],
                "summary": "剧集组刮削",
                "description": "移除待处理媒体信息",
            },
            {
                "path": "/start_rt",
                "endpoint": self.go_start_rt,
                "methods": ["GET"],
                "summary": "剧集组刮削",
                "description": "刮削指定剧集组",
            }
        ]

    def delete_media_database(self, tmdb_id: str, apikey: str) -> schemas.Response:
        """
        删除待处理剧集组的媒体信息
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        if not tmdb_id:
            return schemas.Response(success=False, message="缺少重要参数")
        self.del_data(tmdb_id)
        return schemas.Response(success=True, message="删除成功")

    def go_start_rt(self, tmdb_id: str, group_id: str, apikey: str) -> schemas.Response:
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        if not tmdb_id or not group_id:
            return schemas.Response(success=False, message="缺少重要参数")
        # 解析待处理数据
        try:
            # 查询待处理数据
            data = self.get_data(tmdb_id)
            if not data:
                return schemas.Response(success=False, message="未找到待处理数据")
            mediainfo_dict = data.get("mediainfo_dict")
            mediainfo: schemas.MediaInfo = schemas.MediaInfo.parse_obj(mediainfo_dict)
            episode_groups = data.get("episode_groups")
        except Exception as e:
            self.log_error(f"解析媒体信息失败: {str(e)}")
            return schemas.Response(success=False, message="解析媒体信息失败")
        # 开始刮削
        self.log_info(f"开始刮削: {mediainfo.title} | {mediainfo.year} | {episode_groups}")
        self.systemmessage.put("正在刮削中，请稍等!", title="剧集组刮削")
        if self.start_rt(mediainfo, episode_groups, group_id):
            self.log_info("刮削剧集组, 执行成功!")
            self.systemmessage.put("刮削剧集组, 执行成功!", title="剧集组刮削")
            # 处理成功时， 发送通知
            if self._notify:
                self.post_message(
                    mtype=schemas.NotificationType.Manual,
                    title="【剧集组处理结果: 成功】",
                    text=f"媒体名称：{mediainfo.title}\n发行年份: {mediainfo.year}\n剧集组数: {len(episode_groups)}"
                )
            return schemas.Response(success=True, message="刮削剧集组, 执行成功!")
        else:
            self.log_error("执行失败, 请查看插件日志！")
            self.systemmessage.put("执行失败, 请查看插件日志！", title="剧集组刮削")
            # 处理成功时， 发送通知
            if self._notify:
                self.post_message(
                    mtype=schemas.NotificationType.Manual,
                    title="【剧集组处理结果: 失败】",
                    text=f"媒体名称：{mediainfo.title}\n发行年份: {mediainfo.year}\n剧集组数: {len(episode_groups)}\n注意: 失败原因请查看日志.."
                )
            return schemas.Response(success=False, message="执行失败, 请查看插件日志")

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
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'autorun',
                                            'label': '季集匹配时自动刮削',
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
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'ignorelock',
                                            'label': '锁定的剧集也刮削',
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
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        }
                                    }
                                ]
                            },
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
                                            'model': 'delay',
                                            'label': '入库延迟时间（秒）',
                                            'placeholder': '120'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'allowlist',
                                            'label': '刮削白名单',
                                            'rows': 6,
                                            'placeholder': '使用,分隔电视剧名称'
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
                                            'text': '注意：刮削白名单(留空)则全部刮削. 否则仅刮削白名单.'
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
                                            'text': '注意：如需刮削已经入库的项目, 可通过mp重新整理单集即可.'
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
            "notify": True,
            "autorun": True,
            "ignorelock": False,
            "allowlist": "",
            "delay": 120
        }

    def is_objstr(self, obj: Any):
        if not isinstance(obj, str):
            return False
        return str(obj).startswith("{") \
            or str(obj).startswith("[") \
            or str(obj).startswith("(")

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询待处理数据列表
        mediainfo_list: List[PluginData] = self.get_data()
        # 拼装页面
        contents = []
        for plugin_data in mediainfo_list:
            try:
                tmdb_id = plugin_data.key
                # fix v1版本数据读取问题
                if self.is_objstr(plugin_data.value):
                    data = json.loads(plugin_data.value)
                else:
                    data = plugin_data.value
                mediainfo: schemas.MediaInfo = schemas.MediaInfo.parse_obj(data.get("mediainfo_dict"))
                episode_groups = data.get("episode_groups")
            except Exception as e:
                self.log_error(f"解析媒体信息失败: {plugin_data.key} -> {plugin_data.value} \n ------ \n {str(e)}")
                continue
            # 剧集组菜单明细
            groups_menu = []
            index = 0
            for group in episode_groups:
                index += 1
                title = group.get('name')
                groups_menu.append({
                    'component': 'VListItem',
                    'props': {
                        ':key': str(index),
                        ':value': str(index)
                    },
                    'events': {
                        'click': {
                            'api': 'plugin/EpisodeGroupMeta/start_rt',
                            'method': 'get',
                            'params': {
                                'apikey': settings.API_TOKEN,
                                'tmdb_id': tmdb_id,
                                'group_id': group.get('id')
                            }
                        }
                    },
                    'content': [
                        {
                            'component': 'VListItemTitle',
                            'text': title
                        },
                        {
                            'component': 'VListItemSubtitle',
                            'text': f"{group.get('group_count')}组, {group.get('episode_count')}集"
                        },
                    ]
                })
            # 拼装待处理媒体卡片
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            'component': 'VImg',
                            'props': {
                                'src': mediainfo.backdrop_path or mediainfo.poster_path,
                                'height': '120px',
                                'cover': True
                            },
                        },
                        {
                            'component': 'VCardTitle',
                            'content': [
                                {
                                    'component': 'a',
                                    'props': {
                                        'href': f"{mediainfo.detail_link}/episode_groups",
                                        'target': '_blank'
                                    },
                                    'text': mediainfo.title
                                }
                            ]
                        },
                        {
                            'component': 'VCardSubtitle',
                            'content': [
                                {
                                    'component': 'a',
                                    'props': {
                                        'href': f"{mediainfo.detail_link}/episode_groups",
                                        'target': '_blank'
                                    },
                                    'text': f"{mediainfo.year} | 共{len(episode_groups)}个剧集组"
                                }
                            ]
                        },
                        {
                            'component': 'VCardActions',
                            'props': {
                                'style': 'min-height:64px;'
                            },
                            'content': [
                                {
                                    'component': 'VBtn',
                                    'props': {
                                        'class': 'ms-2',
                                        'size': 'small',
                                        'rounded': 'xl',
                                        'elevation': '20',
                                        'append-icon': 'mdi-chevron-right'
                                    },
                                    'text': '选择剧集组',
                                    'content': [
                                        {
                                            'component': 'VMenu',
                                            'props': {
                                                'activator': 'parent'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VList',
                                                    'content': groups_menu
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    'component': 'VBtn',
                                    'props': {
                                        'class': 'ms-2',
                                        'size': 'small',
                                        'elevation': '20',
                                        'rounded': 'xl',
                                    },
                                    'text': '忽略',
                                    'events': {
                                        'click': {
                                            'api': 'plugin/EpisodeGroupMeta/delete_media_database',
                                            'method': 'get',
                                            'params': {
                                                'apikey': settings.API_TOKEN,
                                                'tmdb_id': tmdb_id
                                            }
                                        }
                                    },
                                }
                            ]
                        }
                    ]
                }
            )

        if not contents:
            return [
                {
                    'component': 'div',
                    'text': '暂无待处理数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]

        return [
            {
                'component': 'VRow',
                'props': {
                    'class': 'mb-3'
                },
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
                                    'text': '注意：1. 点击名字可跳转tmdb剧集组页面。2. 选择剧集组时后台已经开始执行，请通过日志查看进度，不要重复执行。'
                                }
                            }
                        ]
                    }
                ]
            },
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-6 grid-info-card',
                },
                'content': contents
            }
        ]

    @eventmanager.register(EventType.TransferComplete)
    def scrap_rt(self, event: Event):
        """
        根据事件判断是否需要刮削
        """
        if not self.get_state():
            return
        # 事件数据
        mediainfo: schemas.MediaInfo = event.event_data.get("mediainfo")
        meta: MetaBase = event.event_data.get("meta")
        # self.log_error(f"{event.event_data}")
        if not mediainfo or not meta:
            return
        # 非TV类型不处理
        if mediainfo.type != schemas.MediaType.TV:
            self.log_warn(f"{mediainfo.title} 非TV类型, 无需处理")
            return
        # 没有tmdbID不处理
        if not mediainfo.tmdb_id:
            self.log_warn(f"{mediainfo.title} 没有tmdbID, 无需处理")
            return
        if len(self._allowlist) != 0 \
                and mediainfo.title not in self._allowlist:
            self.log_warn(f"{mediainfo.title} 不在白名单, 无需处理")
            return
        # 获取剧集组信息
        try:
            episode_groups = self.tv.episode_groups(mediainfo.tmdb_id)
            if not episode_groups:
                self.log_warn(f"{mediainfo.title} 没有剧集组, 无需处理")
                return
            self.log_info(f"{mediainfo.title_year} 剧集组数量: {len(episode_groups)} - {episode_groups}")
            # episodegroup = self.tv.group_episodes(episode_groups[0].get('id'))
        except Exception as e:
            self.log_error(f"{mediainfo.title} {str(e)}")
            return
        # 写入至插件数据
        mediainfo_dict = None
        try:
            # 实际传递的不是基于BaseModel的实例
            mediainfo_dict = mediainfo.dict()
        except Exception as e:
            # app.core.context.MediaInfo
            try:
                mediainfo_dict = mediainfo.to_dict()
            except Exception as e:
                self.log_error(f"{mediainfo.title} 无法处理MediaInfo数据 {str(e)}")
        if mediainfo_dict:
            data = {
                "episode_groups": episode_groups,
                "mediainfo_dict": mediainfo_dict
            }
            self.save_data(str(mediainfo.tmdb_id), data)
            self.log_info("写入待处理数据 - ok")
        # 禁止自动刮削时直接返回
        if not self._autorun:
            self.log_warn(f"{mediainfo.title} 未勾选自动刮削, 无需处理")
            # 发送通知
            if self._notify and mediainfo_dict:
                self.post_message(
                    mtype=schemas.NotificationType.Manual,
                    title="【待手动处理的剧集组】",
                    text=f"媒体名称：{mediainfo.title}\n发行年份: {mediainfo.year}\n剧集组数: {len(episode_groups)}"
                )
            return
        # 延迟
        if self._delay:
            self.log_warn(f"{mediainfo.title} 将在 {self._delay} 秒后开始处理..")
            time.sleep(int(self._delay))
        # 开始处理
        if self.start_rt(mediainfo=mediainfo, episode_groups=episode_groups):
            # 处理完成时， 属于自动匹配的, 发送通知
            if self._notify and mediainfo_dict:
                self.post_message(
                    mtype=schemas.NotificationType.Manual,
                    title="【已自动匹配的剧集组】",
                    text=f"媒体名称：{mediainfo.title}\n发行年份: {mediainfo.year}\n剧集组数: {len(episode_groups)}"
                )
            return

    def start_rt(self, mediainfo: schemas.MediaInfo, episode_groups: Any | None, group_id: str = None) -> bool:
        """
        通过媒体信息读取剧集组并刮削季集信息
        """
        # 当不是从事件触发时，应再次判断是否存在剧集组
        if not episode_groups:
            try:
                episode_groups = self.tv.episode_groups(mediainfo.tmdb_id)
                if not episode_groups:
                    self.log_warn(f"{mediainfo.title} 没有剧集组, 无需处理")
                    return False
                self.log_info(f"{mediainfo.title_year} 剧集组数量: {len(episode_groups)} - {episode_groups}")
                # episodegroup = self.tv.group_episodes(episode_groups[0].get('id'))
            except Exception as e:
                self.log_error(f"{mediainfo.title} {str(e)}")
                return False
        # 获取全部可用的媒体服务器, 兼容v2
        service_infos = self.service_infos()
        relust_bool = False
        if self.mediaserver_helper is None:
            # v1版本 单一媒体服务器的方式
            server_list = ["emby", "jellyfin", "plex"]
            # 遍历所有媒体服务器
            for server in server_list:
                self.log_info(f"正在查询媒体服务器: {server}")
                existsinfo: ExistMediaInfo = self.__media_exists(
                    mediainfo=mediainfo,
                    server=server,
                    server_type=server)
                if not existsinfo or not existsinfo.itemid:
                    self.log_warn(f"{mediainfo.title_year} 在媒体库 {server} 中不存在")
                    continue
                elif not existsinfo.groupep:
                    self.log_warn(f"{mediainfo.title_year} 在媒体库 {server} 中没有数据")
                    continue
                else:
                    self.log_info(
                        f"{mediainfo.title_year} 在媒体库 {existsinfo.server} 中找到了这些季集：{existsinfo.groupep}")
                _bool = self.__start_rt_mediaserver(mediainfo=mediainfo, existsinfo=existsinfo,
                                                    episode_groups=episode_groups, group_id=group_id)
                relust_bool = relust_bool or _bool
        else:
            # v2版本 遍历所有媒体服务器的方式
            if not service_infos:
                self.log_warn(f"{mediainfo.title_year} 无可用的媒体服务器")
                return False
            # 遍历媒体服务器
            for name, info in service_infos.items():
                self.log_info(f"正在查询媒体服务器: ({info.type}){name}")
                existsinfo: ExistMediaInfo = self.__media_exists(
                    mediainfo=mediainfo,
                    server=name,
                    server_type=info.type,
                    mediaserver_instance=info.instance)
                if not existsinfo or not existsinfo.itemid:
                    self.log_warn(f"{mediainfo.title_year} 在 ({info.type}){name} 媒体服务器中不存在")
                    continue
                elif not existsinfo.groupep:
                    self.log_warn(f"{mediainfo.title_year} 在 ({info.type}){name} 媒体服务器中没有数据")
                    continue
                else:
                    self.log_info(
                        f"{mediainfo.title_year} 在媒体库 ({existsinfo.server_type}){existsinfo.server} 中找到了这些季集：{existsinfo.groupep}")
                _bool = self.__start_rt_mediaserver(mediainfo=mediainfo, existsinfo=existsinfo,
                                                    episode_groups=episode_groups, group_id=group_id,
                                                    mediaserver_instance=info.instance)
                relust_bool = relust_bool or _bool
        return relust_bool

    def __start_rt_mediaserver(self,
                               mediainfo: schemas.MediaInfo,
                               existsinfo: ExistMediaInfo,
                               episode_groups: Any | None,
                               group_id: str = None,
                               mediaserver_instance: Any = None) -> bool:
        """
        遍历媒体服务器剧集信息，并匹配合适的剧集组刷新季集信息
        """
        self.log_info(f"{mediainfo.title_year} 存在于 {existsinfo.server_type} 媒体服务器: {existsinfo.server}")
        # 获取全部剧集组信息
        copy_keys = ['Id', 'Name', 'ChannelNumber', 'OriginalTitle', 'ForcedSortName', 'SortName', 'CommunityRating',
                     'CriticRating', 'IndexNumber', 'ParentIndexNumber', 'SortParentIndexNumber', 'SortIndexNumber',
                     'DisplayOrder', 'Album', 'AlbumArtists', 'ArtistItems', 'Overview', 'Status', 'Genres', 'Tags',
                     'TagItems', 'Studios', 'PremiereDate', 'DateCreated', 'ProductionYear', 'Video3DFormat',
                     'OfficialRating', 'CustomRating', 'People', 'LockData', 'LockedFields', 'ProviderIds',
                     'PreferredMetadataLanguage', 'PreferredMetadataCountryCode', 'Taglines']
        for episode_group in episode_groups:
            if not bool(existsinfo.groupep):
                break
            try:
                id = episode_group.get('id')
                name = episode_group.get('name')
                if not id:
                    continue
                # 指定剧集组id时, 跳过其他剧集组
                if group_id and str(id) != str(group_id):
                    continue
                # 处理
                self.log_info(f"正在匹配剧集组: {id}")
                groups_meta = self.tv.group_episodes(id)
                if not groups_meta:
                    continue
                for groups in groups_meta:
                    if not bool(existsinfo.groupep):
                        break
                    # 剧集组中的季
                    order = groups.get("order")
                    # 剧集组中的集列表
                    episodes = groups.get("episodes")
                    if order is None or not episodes or len(episodes) == 0:
                        continue
                    # 进行集数匹配, 确定剧集组信息
                    ep = existsinfo.groupep.get(order)
                    # 指定剧集组id时, 不再通过季集数量匹配
                    if group_id:
                        self.log_info(f"已指定剧集组: {name}, {id}, 第 {order} 季")
                    else:
                        # 进行集数匹配, 确定剧集组信息
                        if not ep or len(ep) != len(episodes):
                            continue
                        self.log_info(f"已匹配剧集组: {name}, {id}, 第 {order} 季")
                    # 遍历全部媒体项并更新
                    if existsinfo.groupid.get(order) is None:
                        self.log_info(f"媒体库中不存在: {mediainfo.title_year}, 第 {order} 季")
                        continue
                    for _index, _ids in enumerate(existsinfo.groupid.get(order)):
                        # 提取出媒体库中集id对应的集数index
                        ep_num = ep[_index]
                        for _id in _ids:
                            # 获取媒体服务器媒体项
                            iteminfo = self.get_iteminfo(server_type=existsinfo.server_type, itemid=_id,
                                                         mediaserver_instance=mediaserver_instance)
                            if not iteminfo:
                                self.log_info(f"未找到媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                                continue
                            # 锁定的剧集是否也刮削?
                            if not self._ignorelock:
                                if iteminfo.get("LockData") or (
                                        "Name" in iteminfo.get("LockedFields", [])
                                        and "Overview" in iteminfo.get("LockedFields", [])):
                                    self.log_warn(
                                        f"已锁定媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集, 如果需要刮削请打开设置中的“锁定的剧集也刮削”选项")
                                    continue
                            # 替换项目数据
                            episode = episodes[ep_num - 1]
                            new_dict = {}
                            new_dict.update({k: v for k, v in iteminfo.items() if k in copy_keys})
                            new_dict["Name"] = episode["name"]
                            new_dict["Overview"] = episode["overview"]
                            new_dict["ParentIndexNumber"] = str(order)
                            new_dict["IndexNumber"] = str(ep_num)
                            new_dict["LockData"] = True
                            if episode.get("vote_average"):
                                new_dict["CommunityRating"] = episode.get("vote_average")
                            if not new_dict["LockedFields"]:
                                new_dict["LockedFields"] = []
                            self.__append_to_list(new_dict["LockedFields"], "Name")
                            self.__append_to_list(new_dict["LockedFields"], "Overview")
                            # 更新数据
                            self.set_iteminfo(server_type=existsinfo.server_type, itemid=_id, iteminfo=new_dict,
                                              mediaserver_instance=mediaserver_instance)
                            # still_path 图片
                            if episode.get("still_path"):
                                self.set_item_image(server_type=existsinfo.server_type, itemid=_id,
                                                    imageurl=f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episode['still_path']}",
                                                    mediaserver_instance=mediaserver_instance)
                            self.log_info(f"已修改剧集 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                    # 移除已经处理成功的季
                    existsinfo.groupep.pop(order, 0)
                    existsinfo.groupid.pop(order, 0)
                    continue
            except Exception as e:
                self.log_warn(f"错误忽略: {str(e)}")
                continue

        self.log_info(f"{mediainfo.title_year} 已经运行完毕了..")
        return True

    @staticmethod
    def __append_to_list(list, item):
        if item not in list:
            list.append(item)

    def __media_exists(self, mediainfo: schemas.MediaInfo, server: str, server_type: str,
                       mediaserver_instance: Any = None) -> ExistMediaInfo:
        """
        根据媒体信息，返回是否存在于指定媒体服务器中，剧集列表与剧集ID列表
        :param mediainfo: 媒体信息
        :return: 剧集列表与剧集ID列表
        """

        def __emby_media_exists():
            # 获取系列id
            item_id = None
            try:
                instance = mediaserver_instance or self.emby
                res = instance.get_data(("[HOST]emby/Items?"
                                         "IncludeItemTypes=Series"
                                         "&Fields=ProductionYear"
                                         "&StartIndex=0"
                                         "&Recursive=true"
                                         "&SearchTerm=%s"
                                         "&Limit=10"
                                         "&IncludeSearchTypes=false"
                                         "&api_key=[APIKEY]") % mediainfo.title)
                res_items = res.json().get("Items")
                if res_items:
                    for res_item in res_items:
                        if res_item.get('Name') == mediainfo.title and (
                                not mediainfo.year or str(res_item.get('ProductionYear')) == str(mediainfo.year)):
                            item_id = res_item.get('Id')
            except Exception as e:
                self.log_error(f"媒体服务器 ({server_type}){server} 发生了错误, 连接Items出错：" + str(e))
            if not item_id:
                return None
            # 验证tmdbid是否相同
            item_info = instance.get_iteminfo(item_id)
            if item_info:
                if mediainfo.tmdb_id and item_info.tmdbid:
                    if str(mediainfo.tmdb_id) != str(item_info.tmdbid):
                        self.log_error(f"tmdbid不匹配或不存在")
                        return None
            try:
                res_json = instance.get_data(
                    "[HOST]emby/Shows/%s/Episodes?Season=&IsMissing=false&api_key=[APIKEY]" % item_id)
                if res_json:
                    tv_item = res_json.json()
                    res_items = tv_item.get("Items")
                    group_ep = {}
                    group_id = {}
                    for res_item in res_items:
                        season_index = res_item.get("ParentIndexNumber")
                        if season_index is None:
                            continue
                        episode_index = res_item.get("IndexNumber")
                        if episode_index is None:
                            continue
                        if season_index not in group_ep:
                            group_ep[season_index] = []
                            group_id[season_index] = []
                        if episode_index not in group_ep[season_index]:
                            group_ep[season_index].append(episode_index)
                            group_id[season_index].append([])
                        # 找到准确的插入索引
                        _index = group_ep[season_index].index(episode_index)
                        if res_item.get("Id") not in group_id[season_index][_index]:
                            group_id[season_index][_index].append(res_item.get("Id"))
                    # 返回
                    return ExistMediaInfo(
                        itemid=item_id,
                        groupep=group_ep,
                        groupid=group_id,
                        server_type=server_type,
                        server=server,
                    )
            except Exception as e:
                self.log_error(f"媒体服务器 ({server_type}){server} 发生了错误, 连接Shows/Id/Episodes出错：{str(e)}")
            return None

        def __jellyfin_media_exists():
            # 获取系列id
            item_id = None
            try:
                instance = mediaserver_instance or self.jellyfin
                res = instance.get_data(url=f"[HOST]Users/[USER]/Items?api_key=[APIKEY]"
                                            f"&searchTerm={mediainfo.title}"
                                            f"&IncludeItemTypes=Series"
                                            f"&Limit=10&Recursive=true")
                res_items = res.json().get("Items")
                if res_items:
                    for res_item in res_items:
                        if res_item.get('Name') == mediainfo.title and (
                                not mediainfo.year or str(res_item.get('ProductionYear')) == str(mediainfo.year)):
                            item_id = res_item.get('Id')
            except Exception as e:
                self.log_error(f"媒体服务器 ({server_type}){server} 发生了错误, 连接Items出错：" + str(e))
            if not item_id:
                return None
            # 验证tmdbid是否相同
            item_info = instance.get_iteminfo(item_id)
            if item_info:
                if mediainfo.tmdb_id and item_info.tmdbid:
                    if str(mediainfo.tmdb_id) != str(item_info.tmdbid):
                        self.log_error(f"tmdbid不匹配或不存在")
                        return None
            try:
                res_json = instance.get_data(
                    "[HOST]Shows/%s/Episodes?Season=&IsMissing=false&api_key=[APIKEY]" % item_id)
                if res_json:
                    tv_item = res_json.json()
                    res_items = tv_item.get("Items")
                    group_ep = {}
                    group_id = {}
                    for res_item in res_items:
                        season_index = res_item.get("ParentIndexNumber")
                        if season_index is None:
                            continue
                        episode_index = res_item.get("IndexNumber")
                        if episode_index is None:
                            continue
                        if season_index not in group_ep:
                            group_ep[season_index] = []
                            group_id[season_index] = []
                        if episode_index not in group_ep[season_index]:
                            group_ep[season_index].append(episode_index)
                            group_id[season_index].append([])
                        # 找到准确的插入索引
                        _index = group_ep[season_index].index(episode_index)
                        if res_item.get("Id") not in group_id[season_index][_index]:
                            group_id[season_index][_index].append(res_item.get("Id"))
                    # 返回
                    return ExistMediaInfo(
                        itemid=item_id,
                        groupep=group_ep,
                        groupid=group_id,
                        server_type=server_type,
                        server=server,
                    )
            except Exception as e:
                self.log_error(f"媒体服务器 ({server_type}){server} 发生了错误, 连接Shows/Id/Episodes出错：{str(e)}")
            return None

        def __plex_media_exists():
            try:
                instance = mediaserver_instance or self.plex
                _plex = instance.get_plex()
                if not _plex:
                    return None
                # 根据标题和年份模糊搜索，该结果不够准确
                videos = _plex.library.search(title=mediainfo.title,
                                              year=mediainfo.year,
                                              libtype="show")
                if (not videos
                        and mediainfo.original_title
                        and str(mediainfo.original_title) != str(mediainfo.title)):
                    videos = _plex.library.search(title=mediainfo.original_title,
                                                  year=mediainfo.year,
                                                  libtype="show")
                if not videos:
                    return None
                if isinstance(videos, list):
                    videos = videos[0]
                video_tmdbid = __get_ids(videos.guids).get('tmdb_id')
                if mediainfo.tmdb_id and video_tmdbid:
                    if str(video_tmdbid) != str(mediainfo.tmdb_id):
                        self.log_error(f"tmdbid不匹配或不存在")
                        return None
                episodes = videos.episodes()
                group_ep = {}
                group_id = {}
                for episode in episodes:
                    season_index = episode.seasonNumber
                    if season_index is None:
                        continue
                    episode_index = episode.index
                    if episode_index is None:
                        continue
                    episode_id = episode.key
                    if not episode_id:
                        continue
                    if season_index not in group_ep:
                        group_ep[season_index] = []
                        group_id[season_index] = []
                    if episode_index not in group_ep[season_index]:
                        group_ep[season_index].append(episode_index)
                        group_id[season_index].append([])
                    # 找到准确的插入索引
                    _index = group_ep[season_index].index(episode_index)
                    if episode_id not in group_id[season_index][_index]:
                        group_id[season_index][_index].append(episode_id)
                # 返回
                return ExistMediaInfo(
                    itemid=videos.key,
                    groupep=group_ep,
                    groupid=group_id,
                    server_type=server_type,
                    server=server,
                )
            except Exception as e:
                self.log_error(f"媒体服务器 ({server_type}){server} 发生了错误, 连接Shows/Id/Episodes出错：{str(e)}")
            return None

        def __get_ids(guids: List[Any]) -> dict:
            guid_mapping = {
                "imdb://": "imdb_id",
                "tmdb://": "tmdb_id",
                "tvdb://": "tvdb_id"
            }
            ids = {}
            for prefix, varname in guid_mapping.items():
                ids[varname] = None
            for guid in guids:
                for prefix, varname in guid_mapping.items():
                    if isinstance(guid, dict):
                        if guid['id'].startswith(prefix):
                            # 找到匹配的ID
                            ids[varname] = guid['id'][len(prefix):]
                            break
                    else:
                        if guid.id.startswith(prefix):
                            # 找到匹配的ID
                            ids[varname] = guid.id[len(prefix):]
                            break
            return ids

        if server_type == "emby":
            return __emby_media_exists()
        elif server_type == "jellyfin":
            return __jellyfin_media_exists()
        else:
            return __plex_media_exists()

    def get_iteminfo(self, server_type: str, itemid: str, mediaserver_instance: Any = None) -> dict:
        """
        获得媒体项详情
        """

        def __get_emby_iteminfo() -> dict:
            """
            获得Emby媒体项详情
            """
            try:
                instance = mediaserver_instance or self.emby
                url = f'[HOST]emby/Users/[USER]/Items/{itemid}?' \
                      f'Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = instance.get_data(url=url)
                if res:
                    return res.json()
            except Exception as err:
                self.log_error(f"获取Emby媒体项详情失败：{str(err)}")
            return {}

        def __get_jellyfin_iteminfo() -> dict:
            """
            获得Jellyfin媒体项详情
            """
            try:
                instance = mediaserver_instance or self.jellyfin
                url = f'[HOST]Users/[USER]/Items/{itemid}?Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = instance.jellyfin.get_data(url=url)
                if res:
                    result = res.json()
                    if result:
                        result['FileName'] = Path(result['Path']).name
                    return result
            except Exception as err:
                self.log_error(f"获取Jellyfin媒体项详情失败：{str(err)}")
            return {}

        def __get_plex_iteminfo() -> dict:
            """
            获得Plex媒体项详情
            """
            iteminfo = {}
            try:
                instance = mediaserver_instance or self.plex
                plexitem = instance.get_plex().library.fetchItem(ekey=itemid)
                if 'movie' in plexitem.METADATA_TYPE:
                    iteminfo['Type'] = 'Movie'
                    iteminfo['IsFolder'] = False
                elif 'episode' in plexitem.METADATA_TYPE:
                    iteminfo['Type'] = 'Series'
                    iteminfo['IsFolder'] = False
                    if 'show' in plexitem.TYPE:
                        iteminfo['ChildCount'] = plexitem.childCount
                iteminfo['Name'] = plexitem.title
                iteminfo['Id'] = plexitem.key
                iteminfo['ProductionYear'] = plexitem.year
                iteminfo['ProviderIds'] = {}
                for guid in plexitem.guids:
                    idlist = str(guid.id).split(sep='://')
                    if len(idlist) < 2:
                        continue
                    iteminfo['ProviderIds'][idlist[0]] = idlist[1]
                for location in plexitem.locations:
                    iteminfo['Path'] = location
                    iteminfo['FileName'] = Path(location).name
                iteminfo['Overview'] = plexitem.summary
                iteminfo['CommunityRating'] = plexitem.audienceRating
                # 增加锁定属性列表
                iteminfo['LockedFields'] = []
                try:
                    if plexitem.title.locked:
                        iteminfo['LockedFields'].append('Name')
                except Exception as err:
                    self.log_warn(f"获取Plex媒体项详情失败：{str(err)}")
                    pass
                try:
                    if plexitem.summary.locked:
                        iteminfo['LockedFields'].append('Overview')
                except Exception as err:
                    self.log_warn(f"获取Plex媒体项详情失败：{str(err)}")
                    pass
                return iteminfo
            except Exception as err:
                self.log_error(f"获取Plex媒体项详情失败：{str(err)}")
            return {}

        if server_type == "emby":
            return __get_emby_iteminfo()
        elif server_type == "jellyfin":
            return __get_jellyfin_iteminfo()
        else:
            return __get_plex_iteminfo()

    def set_iteminfo(self, server_type: str, itemid: str, iteminfo: dict, mediaserver_instance: Any = None):
        """
        更新媒体项详情
        """

        def __set_emby_iteminfo():
            """
            更新Emby媒体项详情
            """
            try:
                instance = mediaserver_instance or self.emby
                res = instance.post_data(
                    url=f'[HOST]emby/Items/{itemid}?api_key=[APIKEY]&reqformat=json',
                    data=json.dumps(iteminfo),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    self.log_error(f"更新Emby媒体项详情失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                self.log_error(f"更新Emby媒体项详情失败：{str(err)}")
            return False

        def __set_jellyfin_iteminfo():
            """
            更新Jellyfin媒体项详情
            """
            try:
                instance = mediaserver_instance or self.jellyfin
                res = instance.post_data(
                    url=f'[HOST]Items/{itemid}?api_key=[APIKEY]',
                    data=json.dumps(iteminfo),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    self.log_error(f"更新Jellyfin媒体项详情失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                self.log_error(f"更新Jellyfin媒体项详情失败：{str(err)}")
            return False

        def __set_plex_iteminfo():
            """
            更新Plex媒体项详情
            """
            try:
                instance = mediaserver_instance or self.plex
                plexitem = instance.get_plex().library.fetchItem(ekey=itemid)
                if 'CommunityRating' in iteminfo and iteminfo['CommunityRating']:
                    edits = {
                        'audienceRating.value': iteminfo['CommunityRating'],
                        'audienceRating.locked': 1
                    }
                    plexitem.edit(**edits)
                plexitem.editTitle(iteminfo['Name']).editSummary(iteminfo['Overview']).reload()
                return True
            except Exception as err:
                self.log_error(f"更新Plex媒体项详情失败：{str(err)}")
            return False

        if server_type == "emby":
            return __set_emby_iteminfo()
        elif server_type == "jellyfin":
            return __set_jellyfin_iteminfo()
        else:
            return __set_plex_iteminfo()

    @retry(RequestException, logger=logger)
    def set_item_image(self, server_type: str, itemid: str, imageurl: str, mediaserver_instance: Any = None):
        """
        更新媒体项图片
        """

        def __download_image():
            """
            下载图片
            """
            try:
                if "doubanio.com" in imageurl:
                    r = RequestUtils(headers={
                        'Referer': "https://movie.douban.com/"
                    }, ua=settings.USER_AGENT).get_res(url=imageurl, raise_exception=True)
                else:
                    r = RequestUtils().get_res(url=imageurl, raise_exception=True)
                if r:
                    return base64.b64encode(r.content).decode()
                else:
                    self.log_error(f"{imageurl} 图片下载失败，请检查网络连通性")
            except Exception as err:
                self.log_error(f"下载图片失败：{str(err)}")
            return None

        def __set_emby_item_image(_base64: str):
            """
            更新Emby媒体项图片
            """
            try:
                instance = mediaserver_instance or self.emby
                url = f'[HOST]emby/Items/{itemid}/Images/Primary?api_key=[APIKEY]'
                res = instance.post_data(
                    url=url,
                    data=_base64,
                    headers={
                        "Content-Type": "image/png"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    self.log_error(f"更新Emby媒体项图片失败，错误码：{res.status_code}")
                    return False
            except Exception as result:
                self.log_error(f"更新Emby媒体项图片失败：{result}")
            return False

        def __set_jellyfin_item_image():
            """
            更新Jellyfin媒体项图片
            # FIXME 改为预下载图片
            """
            try:
                instance = mediaserver_instance or self.jellyfin
                url = f'[HOST]Items/{itemid}/RemoteImages/Download?' \
                      f'Type=Primary&ImageUrl={imageurl}&ProviderName=TheMovieDb&api_key=[APIKEY]'
                res = instance.post_data(url=url)
                if res and res.status_code in [200, 204]:
                    return True
                elif res is not None:
                    self.log_error(f"更新Jellyfin媒体项图片失败，错误码：{res.status_code}")
                    return False
                else:
                    self.log_error(f"更新Jellyfin媒体项图片失败，返回空结果")
                    return False
            except Exception as err:
                self.log_error(f"更新Jellyfin媒体项图片失败：{err}")
            return False

        def __set_plex_item_image():
            """
            更新Plex媒体项图片
            # FIXME 改为预下载图片
            """
            try:
                instance = mediaserver_instance or self.plex
                plexitem = instance.get_plex().library.fetchItem(ekey=itemid)
                plexitem.uploadPoster(url=imageurl)
                return True
            except Exception as err:
                self.log_error(f"更新Plex媒体项图片失败：{err}")
            return False

        if server_type == "emby":
            # 下载图片获取base64
            image_base64 = __download_image()
            if image_base64:
                return __set_emby_item_image(image_base64)
        elif server_type == "jellyfin":
            return __set_jellyfin_item_image()
        else:
            return __set_plex_item_image()
        return None

    def service_infos(self, type_filter: Optional[str] = None):
        """
        服务信息
        """
        if self.mediaserver_helper is None:
            # 动态载入媒体服务器帮助类
            module_name = "app.helper.mediaserver"
            spec = importlib.util.find_spec(module_name)
            if spec is not None:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, 'MediaServerHelper'):
                    self.log_info(f"v2版本初始化媒体库类")
                    self.mediaserver_helper = module.MediaServerHelper()
        if self.mediaserver_helper is None:
            if self.emby is None:
                self.log_info(f"v1版本初始化媒体库类")
                self.emby = Emby()
                self.plex = Plex()
                self.jellyfin = Jellyfin()
            return None

        services = self.mediaserver_helper.get_services(type_filter=type_filter)  #, name_filters=self._mediaservers)
        if not services:
            self.log_warn("获取媒体服务器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                self.log_warn(f"媒体服务器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            self.log_warn("没有已连接的媒体服务器，请检查配置")
            return None

        return active_services

    def log_error(self, ss: str):
        logger.error(f"<{self.plugin_name}> {str(ss)}")

    def log_warn(self, ss: str):
        logger.warn(f"<{self.plugin_name}> {str(ss)}")

    def log_info(self, ss: str):
        logger.info(f"<{self.plugin_name}> {str(ss)}")

    def stop_service(self):
        """
        停止服务
        """
        pass
