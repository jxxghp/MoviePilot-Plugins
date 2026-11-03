import base64
import json
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, List, Dict, Tuple, Optional, Union
from pydantic import BaseModel
from requests import RequestException
from app import schemas
from app.chain.storage import StorageChain
from app.sdk.config import settings
from app.sdk.events import eventmanager, Event
from app.sdk.media import MetaBase
from app.sdk.logging import logger
from app.sdk.services import MediaServerHelper
from app.modules.themoviedb.tmdbv3api import TV
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaSource
from app.sdk.utilities import retry
from app.sdk.network import RequestUtils
from app.sdk.media import (
    build_media_key,
    normalize_media_source,
    parse_media_key,
    resolve_media_identity,
)


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
    plugin_version = "3.2.3"
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
    mediaserver_helper: MediaServerHelper = None

    _enabled = False
    _notify = True
    _autorun = True
    _ignorelock = False
    _delay = 0
    _allowlist = []
    # 分集图本地落盘模式：off 沿用媒体服务器写入，auto 本地失败时回退，local_only 只写本地
    _local_image_mode = "off"
    # 分集图落盘使用的存储标识，远程挂载用户可改成对应的存储名称
    _local_image_storage = "local"
    # 已存在同名分集图时是否覆盖
    _local_image_overwrite = False
    # 媒体服务器路径到 MoviePilot 存储路径的前缀映射，按源前缀长度倒序
    _local_image_mappings: List[Tuple[str, str]] = []
    # 延迟创建的存储处理链，重载插件时重建
    _storage_chain = None

    def init_plugin(self, config: dict = None):
        # 每次装配使用独立取消令牌，避免重载时清除旧实例仍在等待的停止信号。
        self._event = threading.Event()
        self.tv = TV()
        self.mediaserver_helper = MediaServerHelper()
        self.__migrate_media_identity_data()
        # 存储链与路径映射随配置重建，避免重载后继续沿用旧实例
        self._storage_chain = None
        self._local_image_mappings = []
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify", True)
            self._autorun = config.get("autorun", True)
            self._ignorelock = config.get("ignorelock")
            self._delay = config.get("delay") or 120
            self._allowlist = []
            for s in str(config.get("allowlist", "")).split(","):
                s = s.strip()
                if s and s not in self._allowlist:
                    self._allowlist.append(s)
            self._local_image_mode = str(config.get("local_image_mode") or "off")
            self._local_image_storage = str(config.get("local_image_storage") or "local")
            self._local_image_overwrite = bool(config.get("local_image_overwrite"))
            self._local_image_mappings = self._parse_local_image_mappings(
                config.get("local_image_mapping")
            )
            self.log_info(f"白名单数量: {len(self._allowlist)} > {self._allowlist}")

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
                "auth": "bear",
                "summary": "剧集组刮削",
                "description": "移除待处理媒体信息",
                "response_model": schemas.Response[None],
            },
            {
                "path": "/start_rt",
                "endpoint": self.go_start_rt,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "剧集组刮削",
                "description": "刮削指定剧集组",
                "response_model": schemas.Response[None],
            }
        ]

    def delete_media_database(
            self,
            media_source: MediaSource,
            media_id: str,
    ) -> schemas.Response:
        """
        删除待处理剧集组的媒体信息
        """
        media_key = build_media_key(media_source, media_id)
        if normalize_media_source(media_source) != MediaSource.TMDB or not media_key:
            return schemas.Response(success=False, message="缺少有效的 TMDB 媒体身份")
        self.del_data(media_key)
        return schemas.Response(success=True, message="删除成功")

    def go_start_rt(
            self,
            media_source: MediaSource,
            media_id: str,
            group_id: str,
    ) -> schemas.Response:
        """按统一媒体身份读取待处理记录并刮削指定剧集组。"""
        media_key = build_media_key(media_source, media_id)
        if normalize_media_source(media_source) != MediaSource.TMDB or not media_key or not group_id:
            return schemas.Response(success=False, message="缺少重要参数")
        # 解析待处理数据
        try:
            # 查询待处理数据
            data = self.get_data(media_key)
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
                    },
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'local_image_mode',
                                            'label': '分集图落盘方式',
                                            'items': [
                                                {'title': '仅媒体服务器写入（默认）', 'value': 'off'},
                                                {'title': '优先写入媒体目录，失败时回退', 'value': 'auto'},
                                                {'title': '只写入媒体目录', 'value': 'local_only'}
                                            ]
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'local_image_storage',
                                            'label': '落盘存储标识',
                                            'placeholder': 'local'
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
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'local_image_overwrite',
                                            'label': '覆盖已有分集图'
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
                                            'model': 'local_image_mapping',
                                            'label': '分集图落盘路径映射',
                                            'rows': 3,
                                            'placeholder': '/data/media=/media'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：分集图按 MoviePilot 命名（视频文件名.jpg）写入媒体目录；'
                                                    '媒体服务器与 MoviePilot 挂载路径不一致时，每行配置一条'
                                                    '「媒体服务器前缀=MoviePilot前缀」；路径访问不到时自动改用媒体服务器写入，不会创建目录。'
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
            "delay": 120,
            "local_image_mode": "off",
            "local_image_storage": "local",
            "local_image_overwrite": False,
            "local_image_mapping": ""
        }

    def is_objstr(self, obj: Any):
        if not isinstance(obj, str):
            return False
        return str(obj).startswith("{") \
            or str(obj).startswith("[") \
            or str(obj).startswith("(")

    @staticmethod
    def __tmdb_media_id(mediainfo: Any) -> Optional[str]:
        """从统一媒体身份中提取 TMDB 专用接口所需的原生 ID。"""
        media_source, media_id = resolve_media_identity(media=mediainfo)
        if media_source != MediaSource.TMDB:
            return None
        return media_id

    @staticmethod
    def __sanitize_mediainfo_dict(
            mediainfo_dict: dict,
            media_source: MediaSource,
            media_id: str,
    ) -> dict:
        """移除待处理记录中的来源专有辅助 ID，仅保留统一媒体身份。"""
        legacy_identity_fields = {
            "tmdb_id",
            "douban_id",
            "bangumi_id",
            "anilist_id",
            "imdb_id",
            "tvdb_id",
            "tvdb_slug",
            "anidb_id",
        }
        sanitized = {
            key: value for key, value in mediainfo_dict.items()
            if key not in legacy_identity_fields
        }
        sanitized["media_source"] = media_source.value
        sanitized["media_id"] = str(media_id)
        return sanitized

    def __migrate_media_identity_data(self) -> None:
        """将旧裸 TMDB key 和冗余 ID 字段迁移为统一媒体身份结构。"""
        for plugin_data in self.get_data() or []:
            try:
                data = json.loads(plugin_data.value) if self.is_objstr(plugin_data.value) else plugin_data.value
                if not isinstance(data, dict):
                    continue
                mediainfo_dict = data.get("mediainfo_dict")
                if not isinstance(mediainfo_dict, dict):
                    continue
                media_source, media_id = resolve_media_identity(
                    media_source=mediainfo_dict.get("media_source"),
                    media_id=mediainfo_dict.get("media_id"),
                )
                key_source, key_media_id = parse_media_key(plugin_data.key)
                if not media_source:
                    media_source, media_id = resolve_media_identity(
                        media_source=key_source,
                        media_id=key_media_id,
                    )
                if not media_source:
                    media_source, media_id = resolve_media_identity(
                        media_source=MediaSource.TMDB,
                        media_id=mediainfo_dict.get("tmdb_id"),
                    )
                if not media_source and ":" not in str(plugin_data.key):
                    media_source, media_id = resolve_media_identity(
                        media_source=MediaSource.TMDB,
                        media_id=plugin_data.key,
                    )
                if media_source != MediaSource.TMDB:
                    continue
                media_key = build_media_key(media_source, media_id)
                if not media_key:
                    continue
                migrated = dict(data)
                migrated["mediainfo_dict"] = self.__sanitize_mediainfo_dict(
                    mediainfo_dict,
                    media_source,
                    media_id,
                )
                if media_key != plugin_data.key or migrated != data:
                    self.save_data(media_key, migrated)
                    if media_key != plugin_data.key:
                        self.del_data(plugin_data.key)
            except Exception as err:
                self.log_warn(f"迁移待处理媒体身份失败：{plugin_data.key} - {err}")

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询待处理数据列表
        mediainfo_list: List[Any] = self.get_data()
        # 拼装页面
        contents = []
        for plugin_data in mediainfo_list:
            try:
                if self.is_objstr(plugin_data.value):
                    data = json.loads(plugin_data.value)
                else:
                    data = plugin_data.value
                mediainfo: schemas.MediaInfo = schemas.MediaInfo.parse_obj(data.get("mediainfo_dict"))
                media_source, media_id = resolve_media_identity(media=mediainfo)
                if media_source != MediaSource.TMDB:
                    raise ValueError("待处理记录缺少有效的 TMDB 媒体身份")
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
                                'media_source': media_source.value,
                                'media_id': media_id,
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
                                                'media_source': media_source.value,
                                                'media_id': media_id
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
        tmdb_media_id = self.__tmdb_media_id(mediainfo)
        if not tmdb_media_id:
            self.log_warn(f"{mediainfo.title} 没有有效的 TMDB 媒体身份, 无需处理")
            return
        if len(self._allowlist) != 0 \
                and mediainfo.title not in self._allowlist:
            self.log_warn(f"{mediainfo.title} 不在白名单, 无需处理")
            return
        # 获取剧集组信息
        try:
            episode_groups = self.tv.episode_groups(tmdb_media_id)
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
            # app.sdk.media.MediaInfo
            try:
                mediainfo_dict = mediainfo.to_dict()
            except Exception as e:
                self.log_error(f"{mediainfo.title} 无法处理MediaInfo数据 {str(e)}")
        if mediainfo_dict:
            data = {
                "episode_groups": episode_groups,
                "mediainfo_dict": self.__sanitize_mediainfo_dict(
                    mediainfo_dict,
                    MediaSource.TMDB,
                    tmdb_media_id,
                )
            }
            self.save_data(build_media_key(MediaSource.TMDB, tmdb_media_id), data)
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
            if self._event.wait(int(self._delay)):
                return
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
                tmdb_media_id = self.__tmdb_media_id(mediainfo)
                if not tmdb_media_id:
                    self.log_warn(f"{mediainfo.title} 没有有效的 TMDB 媒体身份")
                    return False
                episode_groups = self.tv.episode_groups(tmdb_media_id)
                if not episode_groups:
                    self.log_warn(f"{mediainfo.title} 没有剧集组, 无需处理")
                    return False
                self.log_info(f"{mediainfo.title_year} 剧集组数量: {len(episode_groups)} - {episode_groups}")
                # episodegroup = self.tv.group_episodes(episode_groups[0].get('id'))
            except Exception as e:
                self.log_error(f"{mediainfo.title} {str(e)}")
                return False
        # 获取全部可用的媒体服务器
        service_infos = self.service_infos()
        relust_bool = False
        if not service_infos:
            self.log_warn(f"{mediainfo.title_year} 无可用的媒体服务器")
            return False
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
        updated = False
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
                    # 媒体库该季按集号升序排列后, 第 _index 项对应剧集组第 _index 集;
                    # 集号可以从 0 开始 (含特别篇), 不能直接把集号当作剧集组内的位置
                    for _index, (ep_num, _ids) in enumerate(
                            sorted(zip(ep, existsinfo.groupid.get(order)), key=lambda _pair: _pair[0])):
                        for _id in _ids:
                            # 获取媒体服务器媒体项
                            iteminfo = self.get_iteminfo(server_type=existsinfo.server_type, itemid=_id,
                                                         mediaserver_instance=mediaserver_instance)
                            if not iteminfo:
                                self.log_info(f"未找到媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                                continue
                            # 用排序后的序号定位剧集组分集，媒体库条目多于剧集组时为 None，
                            # 不得用负索引回绕取到剧集组最后一集的数据
                            episode = episodes[_index] if _index < len(episodes) else None
                            # 锁定的剧集是否也刮削?
                            if not self._ignorelock and self.__is_locked_item(iteminfo):
                                # 已锁定：不改元数据、不改锁定状态，仅在剧集组该位置有分集图时补图
                                if episode and episode.get("still_path"):
                                    self.apply_episode_image(
                                        server_type=existsinfo.server_type,
                                        itemid=_id,
                                        imageurl=f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episode['still_path']}",
                                        iteminfo=iteminfo,
                                        mediaserver_instance=mediaserver_instance)
                                    self.log_info(
                                        f"已锁定媒体项, 仅补充分集图片 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                                else:
                                    self.log_warn(
                                        f"已锁定媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集, 如果需要刮削请打开设置中的“锁定的剧集也刮削”选项")
                                continue
                            if episode is None:
                                self.log_info(
                                    f"剧集组只有 {len(episodes)} 集, 跳过 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                                continue
                            new_dict = {}
                            new_dict.update({k: v for k, v in iteminfo.items() if k in copy_keys})
                            new_dict["Name"] = episode["name"]
                            new_dict["Overview"] = episode["overview"]
                            new_dict["ParentIndexNumber"] = str(order)
                            new_dict["IndexNumber"] = str(ep_num)
                            new_dict["LockData"] = True
                            if episode.get("vote_average"):
                                new_dict["CommunityRating"] = episode.get("vote_average")
                            if not new_dict.get("LockedFields"):
                                new_dict["LockedFields"] = []
                            self.__append_to_list(new_dict["LockedFields"], "Name")
                            self.__append_to_list(new_dict["LockedFields"], "Overview")
                            # 更新数据
                            if self.set_iteminfo(server_type=existsinfo.server_type, itemid=_id, iteminfo=new_dict,
                                                 mediaserver_instance=mediaserver_instance):
                                updated = True
                            # still_path 图片
                            if episode.get("still_path"):
                                self.apply_episode_image(server_type=existsinfo.server_type, itemid=_id,
                                                         imageurl=f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episode['still_path']}",
                                                         iteminfo=iteminfo,
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
        return updated

    @staticmethod
    def __is_locked_item(iteminfo: dict) -> bool:
        """
        判断媒体项是否已被锁定：整项锁定，或标题与简介都被列为锁定字段。

        ``LockedFields`` 可能缺失或为空，这里按缺省处理，不能因字段缺失报错。
        """

        if not iteminfo:
            return False
        if iteminfo.get("LockData"):
            return True
        locked_fields = iteminfo.get("LockedFields") or []
        return "Name" in locked_fields and "Overview" in locked_fields

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
                instance = mediaserver_instance
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
                if (mediainfo.media_source == MediaSource.TMDB
                        and item_info.media_source == MediaSource.TMDB
                        and mediainfo.media_id
                        and item_info.media_id):
                    if str(mediainfo.media_id) != str(item_info.media_id):
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
                instance = mediaserver_instance
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
                if (mediainfo.media_source == MediaSource.TMDB
                        and item_info.media_source == MediaSource.TMDB
                        and mediainfo.media_id
                        and item_info.media_id):
                    if str(mediainfo.media_id) != str(item_info.media_id):
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
                instance = mediaserver_instance
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
                tmdb_media_id = self.__tmdb_media_id(mediainfo)
                if tmdb_media_id and video_tmdbid:
                    if str(video_tmdbid) != tmdb_media_id:
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
        获得媒体项详情。

        媒体服务器适配器的实例方法属于本插件必须承担的运行态侵入；宿主
        ``>=3.0.0`` 需保持对应 ``get_data`` 与 Plex library 访问协议，
        调用失败统一返回空字典并跳过当前媒体项。
        """

        def __get_emby_iteminfo() -> dict:
            """
            获得Emby媒体项详情
            """
            try:
                instance = mediaserver_instance
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
                instance = mediaserver_instance
                url = f'[HOST]Users/[USER]/Items/{itemid}?Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = instance.get_data(url=url)
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
                instance = mediaserver_instance
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
        更新媒体项详情。

        该写入依赖媒体服务器适配器实例的具体协议；宿主版本变化时由插件
        维护者负责适配，所有异常路径均返回 ``False`` 以阻止误报成功。
        """

        def __set_emby_iteminfo():
            """
            更新Emby媒体项详情
            """
            try:
                instance = mediaserver_instance
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
                instance = mediaserver_instance
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
                instance = mediaserver_instance
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

    def _parse_local_image_mappings(self, raw: Any) -> List[Tuple[str, str]]:
        """
        解析「媒体服务器路径前缀=MoviePilot存储路径前缀」映射配置。

        每行一条，按源前缀长度倒序返回，保证嵌套前缀（如 /media 与 /media/links）
        始终由更长的一条命中，避免替换出错误路径。
        """
        mappings: List[Tuple[str, str]] = []
        for line in str(raw or "").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            source, _, target = line.partition("=")
            source = source.strip().rstrip("/")
            target = target.strip().rstrip("/")
            if not source or not target:
                continue
            if (source, target) not in mappings:
                mappings.append((source, target))
        return sorted(mappings, key=lambda pair: len(pair[0]), reverse=True)

    def _map_media_server_path(self, server_path: str) -> str:
        """
        把媒体服务器视角的路径换算成 MoviePilot 存储视角的路径。

        未配置或未命中映射时原样返回，交由后续存在性校验判断能否写入；
        这里不猜测目录，映射缺失只会退回媒体服务器写入，不会凭空创建路径。
        """
        path = str(server_path or "")
        for source, target in (self._local_image_mappings or []):
            if path == source or path.startswith(source + "/"):
                return target + path[len(source):]
        return path

    def _get_storage_chain(self):
        """
        取得存储处理链实例，单独抽出便于插件重载与测试替换。
        """
        if self._storage_chain is None:
            self._storage_chain = StorageChain()
        return self._storage_chain

    def _resolve_local_image_target(self, iteminfo: Any) -> Optional[Tuple[Any, str]]:
        """
        由媒体项详情反推可写入的目标目录项与视频文件名主干。

        顺序是硬约束：先用视频文件本身证明 MoviePilot 能访问该路径，再由文件项取上级目录；
        全程不使用会递归创建缺失路径的 get_folder，避免映射写错时在存储里长出假目录树。
        """
        if self._local_image_mode == "off":
            return None
        server_path = iteminfo.get("Path") if isinstance(iteminfo, dict) else None
        if not server_path:
            self.log_info("媒体项缺少路径信息，分集图改用媒体服务器写入")
            return None
        storage = self._local_image_storage or "local"
        mapped_path = self._map_media_server_path(str(server_path))
        try:
            chain = self._get_storage_chain()
            video_item = chain.get_file_item(storage=storage, path=Path(mapped_path))
        except Exception as err:
            self.log_warn(f"查询媒体文件失败：{err}")
            return None
        if not video_item or not video_item.path:
            self.log_warn(f"MoviePilot 无法访问媒体路径，请配置路径映射：{mapped_path}")
            return None
        try:
            folder_item = chain.get_parent_item(video_item)
        except Exception as err:
            self.log_warn(f"查询媒体文件上级目录失败：{err}")
            return None
        if not folder_item or not folder_item.path:
            self.log_warn(f"未取到分集图目标目录：{mapped_path}")
            return None
        return folder_item, Path(video_item.path).stem

    def _download_image_bytes(self, imageurl: str) -> Optional[bytes]:
        """
        下载图片并返回原始字节，失败时返回 None。
        """
        try:
            if "doubanio.com" in imageurl:
                r = RequestUtils(headers={
                    'Referer': "https://movie.douban.com/"
                }, ua=settings.USER_AGENT).get_res(url=imageurl, raise_exception=True)
            else:
                r = RequestUtils().get_res(url=imageurl, raise_exception=True)
            if r:
                return r.content
            self.log_error(f"{imageurl} 图片下载失败，请检查网络连通性")
        except Exception as err:
            self.log_error(f"下载图片失败：{str(err)}")
        return None

    def save_item_image_local(self, iteminfo: Any, imageurl: str) -> bool:
        """
        按 MoviePilot 命名规则把分集图直接写入媒体目录。

        目标文件名固定为 <视频文件名>.<图片后缀>，与核心刮削产物同名，
        Jellyfin 读取端同样识别这个名字，因此不再需要 RemoteImages 下载指令。
        """
        target = self._resolve_local_image_target(iteminfo)
        if not target:
            return False
        folder_item, video_stem = target
        storage = self._local_image_storage or "local"
        suffix = Path(str(imageurl).split("?")[0]).suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
            suffix = ".jpg"
        new_name = f"{video_stem}{suffix}"
        folder_path = Path(str(folder_item.path).rstrip("/"))
        try:
            chain = self._get_storage_chain()
            existing = chain.get_file_item(storage=storage, path=folder_path / new_name)
            legacy = chain.get_file_item(storage=storage,
                                         path=folder_path / f"{video_stem}-thumb{suffix}")
        except Exception as err:
            self.log_warn(f"检查分集图现状失败：{err}")
            return False
        if legacy:
            self.log_warn(f"媒体目录存在旧命名分集图，建议删除以免重复：{legacy.path}")
        if existing and not self._local_image_overwrite:
            self.log_info(f"分集图已存在，跳过本地写入：{existing.path}")
            return True
        image_bytes = self._download_image_bytes(imageurl)
        if not image_bytes:
            return False
        tmp_path = None
        try:
            # delete_on_close 仅 Python 3.12 支持，统一使用 delete=False 后手动清理
            with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(image_bytes)
                tmp_file.flush()
                tmp_path = Path(tmp_file.name)
            tmp_path.chmod(0o644)
            saved = chain.upload_file(fileitem=folder_item, path=tmp_path, new_name=new_name)
            if not saved:
                self.log_warn(f"分集图写入失败：{new_name}")
                return False
            self.log_info(f"已保存图片：{saved.path}")
            return True
        except Exception as err:
            self.log_warn(f"分集图本地落盘失败：{err}")
            return False
        finally:
            # 本地存储上传成功后会自行删除源文件，这里只兜底清理异常残留
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def apply_episode_image(self, server_type: str, itemid: str, imageurl: str,
                            iteminfo: Any = None, mediaserver_instance: Any = None) -> bool:
        """
        按配置写入分集图：本地落盘、媒体服务器写入，或本地失败后回退媒体服务器。

        默认模式 off 完整保留历史行为，只有开启本地落盘才会改变写入路径。
        """
        if self._local_image_mode in ("auto", "local_only"):
            if self.save_item_image_local(iteminfo, imageurl):
                return True
            if self._local_image_mode == "local_only":
                self.log_warn("分集图本地落盘未成功，已按配置跳过媒体服务器写入")
                return False
        return bool(self.set_item_image(server_type=server_type, itemid=itemid,
                                        imageurl=imageurl,
                                        mediaserver_instance=mediaserver_instance))

    @retry(RequestException, logger=logger)
    def set_item_image(self, server_type: str, itemid: str, imageurl: str, mediaserver_instance: Any = None):
        """
        更新媒体项图片
        """

        def __download_image():
            """
            下载图片
            """
            image_bytes = self._download_image_bytes(imageurl)
            if image_bytes is None:
                return None
            return base64.b64encode(image_bytes).decode()

        def __set_emby_item_image(_base64: str):
            """
            更新Emby媒体项图片
            """
            try:
                instance = mediaserver_instance
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
                instance = mediaserver_instance
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
                instance = mediaserver_instance
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
        停止服务并唤醒等待中的整理任务。
        """
        self._event.set()
