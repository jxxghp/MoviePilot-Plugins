import base64
import json
import threading
import time
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, Union

from requests import RequestException

from app.chain.mediaserver import MediaServerChain
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.meta import MetaBase
from app.log import logger
from app.modules.emby import Emby
from app.modules.jellyfin import Jellyfin
from app.modules.plex import Plex
from app.plugins import _PluginBase
from app import schemas
from app.schemas.types import EventType, MediaType
from app.utils.common import retry
from app.utils.http import RequestUtils

from app.modules.themoviedb.tmdbv3api import TV

from pydantic import BaseModel

class ExistMediaInfo(BaseModel):
    # 类型 电影、电视剧
    type: Optional[schemas.MediaType]
    # 季, 集
    groupep: Optional[Dict[int, list]] = {}
    # 集在媒体服务器的ID
    groupid: Optional[Dict[int, List[list]]] = {}
    # 媒体服务器
    server: Optional[str] = None
    # 媒体ID
    itemid: Optional[Union[str, int]] = None

class EpisodeGroupMeta(_PluginBase):
    # 插件名称
    plugin_name = "TMDB剧集组刮削"
    # 插件描述
    plugin_desc = "从TMDB剧集组刮削季集的实际顺序"
    # 插件图标
    plugin_icon = "Element_A.png"
    # 主题色
    plugin_color = "#098663"
    # 插件版本
    plugin_version = "1.0"
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
    mschain = None
    tv = None
    _enabled = False
    _ignorelock = False
    _delay = 0
    _allowlist = []

    def init_plugin(self, config: dict = None):
        self.mschain = MediaServerChain()
        self.tv = TV()
        if config:
            self._enabled = config.get("enabled")
            self._ignorelock = config.get("ignorelock")
            self._delay = config.get("delay") or 120
            self._allowlist = []
            for s in str(config.get("allowlist", "")).split(","):
                s = s.strip()
                if s and s not in self._allowlist:
                    self._allowlist.append(s)
            self.log_info(f"白名单数量: {len(self._allowlist)} > {self._allowlist}")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
                                    'md': 6
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ignorelock',
                                            'label': '媒体信息锁定时也进行刮削',
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
                                            'text': '注意：刮削白名单(留空), 则全部刮削. 否则仅刮削白名单.'
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
            "ignorelock": False,
            "allowlist": [],
            "delay": 120
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.TransferComplete)
    def scrap_rt(self, event: Event):
        """
        根据事件实时刮削剧集组信息
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
        if mediainfo.type !=  schemas.MediaType.TV:
            self.log_warn(f"{mediainfo.title} 非TV类型, 无需处理")
            return
        # 没有tmdbID不处理
        if not mediainfo.tmdb_id:
            self.log_warn(f"{mediainfo.title} 没有tmdbID, 无需处理")
            return
        if len(self._allowlist) != 0 and not mediainfo.title in self._allowlist:
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
        # 延迟
        if self._delay:
            self.log_warn(f"{mediainfo.title} 将在 {self._delay} 秒后开始处理..")
            time.sleep(int(self._delay))
        # 获取可用的媒体服务器
        _existsinfo = self.chain.media_exists(mediainfo=mediainfo)
        existsinfo: ExistMediaInfo = self.__media_exists(server=_existsinfo.server, mediainfo=mediainfo, existsinfo=_existsinfo)
        if not existsinfo or not existsinfo.itemid:
            self.log_warn(f"{mediainfo.title_year} 在媒体库中不存在")
            return
        # 新增需要的属性
        existsinfo.server = _existsinfo.server
        existsinfo.type = _existsinfo.type
        self.log_info(f"{mediainfo.title_year} 存在于媒体服务器: {_existsinfo.server}")
        # 获取全部剧集组信息
        copy_keys = ['Id', 'Name', 'ChannelNumber', 'OriginalTitle', 'ForcedSortName', 'SortName', 'CommunityRating', 'CriticRating', 'IndexNumber', 'ParentIndexNumber', 'SortParentIndexNumber', 'SortIndexNumber', 'DisplayOrder', 'Album', 'AlbumArtists', 'ArtistItems', 'Overview', 'Status', 'Genres', 'Tags', 'TagItems', 'Studios', 'PremiereDate', 'DateCreated', 'ProductionYear', 'Video3DFormat', 'OfficialRating', 'CustomRating', 'People', 'LockData', 'LockedFields', 'ProviderIds', 'PreferredMetadataLanguage', 'PreferredMetadataCountryCode', 'Taglines']
        for episode_group in episode_groups:
            if not bool(existsinfo.groupep):
                break
            try:
                id = episode_group.get('id')
                name = episode_group.get('name')
                if not id:
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
                    if not order or not episodes or len(episodes) == 0:
                        continue
                    # 进行集数匹配, 确定剧集组信息
                    ep = existsinfo.groupep.get(order)
                    if not ep or len(ep) != len(episodes):
                        continue
                    self.log_info(f"已匹配剧集组: {name}, {id}, 第 {order} 季")
                    # 遍历全部媒体项并更新
                    for _index, _ids in enumerate(existsinfo.groupid.get(order)):
                        # 提取出媒体库中集id对应的集数index
                        ep_num = ep[_index]
                        for _id in _ids:
                            # 获取媒体服务器媒体项
                            iteminfo = self.get_iteminfo(server=existsinfo.server, itemid=_id)
                            if not iteminfo:
                                self.log_info(f"未找到媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                                continue
                            # 是否无视项目锁定
                            if not self._ignorelock:
                                if iteminfo.get("LockData") or ("Name" in iteminfo.get("LockedFields",[]) and "Overview" in iteminfo.get("LockedFields",[])):
                                    self.log_warn(f"已锁定媒体项 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
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
                            self.set_iteminfo(server=existsinfo.server, itemid=_id, iteminfo=new_dict)
                            # still_path 图片
                            if episodes[_index]["still_path"]:
                                self.set_item_image(server=existsinfo.server, itemid=_id, imageurl=f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episode['still_path']}")
                            self.log_info(f"已修改剧集 - itemid: {_id},  第 {order} 季,  第 {ep_num} 集")
                    # 移除已经处理成功的季
                    existsinfo.groupep.pop(order, 0)
                    existsinfo.groupid.pop(order, 0)
                    continue
            except Exception as e:
                self.log_warn(f"错误忽略: {str(e)}")
                continue

        self.log_info(f"{mediainfo.title_year} 已经运行完毕了..")
    
    def __append_to_list(self, list, item):
        if item not in list:
            list.append(item)

    def __media_exists(self, server: str, mediainfo: schemas.MediaInfo, existsinfo: schemas.ExistMediaInfo) -> ExistMediaInfo:
        """
        根据媒体信息，返回剧集列表与剧集ID列表
        :param mediainfo: 媒体信息
        :return: 剧集列表与剧集ID列表
        """
        def __emby_media_exists():
            # 获取系列id
            item_id = None
            try:
                res = Emby().get_data(("[HOST]emby/Items?"
                   "IncludeItemTypes=Series"
                   "&Fields=ProductionYear"
                   "&StartIndex=0"
                   "&Recursive=true"
                   "&SearchTerm=%s"
                   "&Limit=10"
                   "&IncludeSearchTypes=false"
                   "&api_key=[APIKEY]") % (mediainfo.title))
                res_items = res.json().get("Items")
                if res_items:
                    for res_item in res_items:
                        if res_item.get('Name') == mediainfo.title and (
                                not mediainfo.year or str(res_item.get('ProductionYear')) == str(mediainfo.year)):
                            item_id = res_item.get('Id')
            except Exception as e:
                self.log_error(f"连接Items出错：" + str(e))
            if not item_id:
                return None
            # 验证tmdbid是否相同
            item_info = Emby().get_iteminfo(item_id)
            if item_info:
                if mediainfo.tmdb_id and item_info.tmdbid:
                    if str(mediainfo.tmdb_id) != str(item_info.tmdbid):
                        self.log_error(f"tmdbid不匹配或不存在")
                        return None
            try:
                res_json = Emby().get_data("[HOST]emby/Shows/%s/Episodes?Season=&IsMissing=false&api_key=[APIKEY]" % (item_id))
                if res_json:
                    tv_item = res_json.json()
                    res_items = tv_item.get("Items")
                    group_ep = {}
                    group_id = {}
                    for res_item in res_items:
                        season_index = res_item.get("ParentIndexNumber")
                        if not season_index:
                            continue
                        episode_index = res_item.get("IndexNumber")
                        if not episode_index:
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
                        groupid=group_id
                    )
            except Exception as e:
                self.log_error(f"连接Shows/Id/Episodes出错：{str(e)}")
            return None
        
        def __jellyfin_media_exists():
            # 获取系列id
            item_id = None
            try:
                res = Jellyfin.get_data(("[HOST]Users/[USER]/Items?"
                   "api_key=[APIKEY]&searchTerm=%s&IncludeItemTypes=Series&Limit=10&Recursive=true") % (mediainfo.title))
                res_items = res.json().get("Items")
                if res_items:
                    for res_item in res_items:
                        if res_item.get('Name') == mediainfo.title and (
                                not mediainfo.year or str(res_item.get('ProductionYear')) == str(mediainfo.year)):
                            item_id = res_item.get('Id')
            except Exception as e:
                self.log_error(f"连接Items出错：" + str(e))
            if not item_id:
                return None
            # 验证tmdbid是否相同
            item_info = Jellyfin().get_iteminfo(item_id)
            if item_info:
                if mediainfo.tmdb_id and item_info.tmdbid:
                    if str(mediainfo.tmdb_id) != str(item_info.tmdbid):
                        self.log_error(f"tmdbid不匹配或不存在")
                        return None
            try:
                res_json = Jellyfin().get_data("[HOST]emby/Shows/%s/Episodes?Season=&IsMissing=false&api_key=[APIKEY]" % (item_id))
                if res_json:
                    tv_item = res_json.json()
                    res_items = tv_item.get("Items")
                    group_ep = {}
                    group_id = {}
                    for res_item in res_items:
                        season_index = res_item.get("ParentIndexNumber")
                        if not season_index:
                            continue
                        episode_index = res_item.get("IndexNumber")
                        if not episode_index:
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
                        groupid=group_id
                    )
            except Exception as e:
                self.log_error(f"连接Shows/Id/Episodes出错：{str(e)}")
            return None
        
        def __plex_media_exists():
            try:
                _plex = Plex().get_plex()
                if not _plex:
                    return None
                if existsinfo.itemid:
                    videos = _plex.fetchItem(existsinfo.itemid)
                else:
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
                    if not season_index:
                        continue
                    episode_index = episode.index
                    if not episode_index:
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
                    groupid=group_id
                )
            except Exception as e:
                self.log_error(f"连接Shows/Id/Episodes出错：{str(e)}")
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
            
        if server == "emby":
            return __emby_media_exists()
        elif server == "jellyfin":
            return __jellyfin_media_exists()
        else:
            return __plex_media_exists()
            
    def get_iteminfo(self, server: str, itemid: str) -> dict:
        """
        获得媒体项详情
        """

        def __get_emby_iteminfo() -> dict:
            """
            获得Emby媒体项详情
            """
            try:
                url = f'[HOST]emby/Users/[USER]/Items/{itemid}?' \
                      f'Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = Emby().get_data(url=url)
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
                url = f'[HOST]Users/[USER]/Items/{itemid}?Fields=ChannelMappingInfo&api_key=[APIKEY]'
                res = Jellyfin().get_data(url=url)
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
                plexitem = Plex().get_plex().library.fetchItem(ekey=itemid)
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
                    pass
                try:
                    if plexitem.summary.locked:
                        iteminfo['LockedFields'].append('Overview')
                except Exception as err:
                    pass
                return iteminfo
            except Exception as err:
                self.log_error(f"获取Plex媒体项详情失败：{str(err)}")
            return {}

        if server == "emby":
            return __get_emby_iteminfo()
        elif server == "jellyfin":
            return __get_jellyfin_iteminfo()
        else:
            return __get_plex_iteminfo()
        
    def set_iteminfo(self, server: str, itemid: str, iteminfo: dict):
        """
        更新媒体项详情
        """

        def __set_emby_iteminfo():
            """
            更新Emby媒体项详情
            """
            try:
                res = Emby().post_data(
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
                res = Jellyfin().post_data(
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
                plexitem = Plex().get_plex().library.fetchItem(ekey=itemid)
                if 'CommunityRating' in iteminfo:
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

        if server == "emby":
            return __set_emby_iteminfo()
        elif server == "jellyfin":
            return __set_jellyfin_iteminfo()
        else:
            return __set_plex_iteminfo()
        
    @retry(RequestException, logger=logger)
    def set_item_image(self, server: str, itemid: str, imageurl: str):
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
                url = f'[HOST]emby/Items/{itemid}/Images/Primary?api_key=[APIKEY]'
                res = Emby().post_data(
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
                url = f'[HOST]Items/{itemid}/RemoteImages/Download?' \
                      f'Type=Primary&ImageUrl={imageurl}&ProviderName=TheMovieDb&api_key=[APIKEY]'
                res = Jellyfin().post_data(url=url)
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    self.log_error(f"更新Jellyfin媒体项图片失败，错误码：{res.status_code}")
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
                plexitem = Plex().get_plex().library.fetchItem(ekey=itemid)
                plexitem.uploadPoster(url=imageurl)
                return True
            except Exception as err:
                self.log_error(f"更新Plex媒体项图片失败：{err}")
            return False

        if server == "emby":
            # 下载图片获取base64
            image_base64 = __download_image()
            if image_base64:
                return __set_emby_item_image(image_base64)
        elif server == "jellyfin":
            return __set_jellyfin_item_image()
        else:
            return __set_plex_item_image()
        return None

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
