import base64
import copy
import datetime
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional, Union

import pytz
import zhconv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from requests import RequestException

from app.chain.mediaserver import MediaServerChain
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.meta import MetaBase
from app.log import logger
from app.modules.emby import Emby
from app.modules.jellyfin import Jellyfin
from app.modules.plex import Plex
from app.plugins import _PluginBase
from app.schemas import MediaInfo, MediaServerItem
from app.schemas.types import EventType, MediaType
from app.utils.common import retry
from app.utils.http import RequestUtils
from app.utils.string import StringUtils

from app.modules.themoviedb.tmdbv3api import TMDb, Search, Movie, TV, Season, Episode, Discover, Trending, Person

from pydantic import BaseModel

class ExistMediaInfo(BaseModel):
    # 类型 电影、电视剧
    type: Optional[MediaType]
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
    plugin_version = "0.1"
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
    _delay = 0

    def init_plugin(self, config: dict = None):
        self.mschain = MediaServerChain()
        self.tv = TV()
        if config:
            self._enabled = config.get("enabled")
            self._delay = config.get("delay") or 0

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
                                            'placeholder': '30'
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
                                            'text': '注意：插件目前仅支持Emby和Jellyfin'
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
            "delay": 30
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
        mediainfo: MediaInfo = event.event_data.get("mediainfo")
        meta: MetaBase = event.event_data.get("meta")
        # self.log_error(f"{event.event_data}")
        if not mediainfo or not meta:
            return
        # 非TV类型不处理
        if mediainfo.type !=  MediaType.TV:
            self.log_warn(f"{mediainfo.title} 非TV类型, 无需处理")
            return
        # 没有tmdbID不处理
        if not mediainfo.tmdb_id:
            self.log_warn(f"{mediainfo.title} 没有tmdbID, 无需处理")
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
            time.sleep(int(self._delay))
        # 获取可用的媒体服务器
        _existsinfo = self.chain.media_exists(mediainfo=mediainfo)
        # 新增需要的属性
        existsinfo: ExistMediaInfo = self.__media_exists(server=_existsinfo.server, mediainfo=mediainfo)
        existsinfo.server = _existsinfo.server
        existsinfo.type = _existsinfo.type
        if not existsinfo or not existsinfo.itemid:
            self.log_warn(f"{mediainfo.title_year} 在媒体库中不存在")
            return
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
                    order = groups.get("order")
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
                        for _id in _ids:
                            # 获取媒体服务器媒体项
                            iteminfo = self.get_iteminfo(server=existsinfo.server, itemid=_id)
                            if not iteminfo:
                                self.log_info(f"未找到媒体项 - itemid: {_id},  第 {order} 季,  第 {str(_index + 1)} 集")
                                continue
                            if iteminfo["LockData"]:
                                self.log_warn(f"已锁定媒体项 - itemid: {_id},  第 {order} 季,  第 {str(_index + 1)} 集")
                                continue
                            # 替换项目数据
                            new_dict = {}
                            new_dict.update({k: v for k, v in iteminfo.items() if k in copy_keys})
                            new_dict["Name"] = episodes[_index]["name"]
                            new_dict["Overview"] = episodes[_index]["overview"]
                            new_dict["ParentIndexNumber"] = str(order)
                            new_dict["IndexNumber"] = str(_index + 1)
                            new_dict["LockData"] = True
                            # if not new_dict["LockedFields"]:
                            #     new_dict["LockedFields"] = []
                            # self.__append_to_list(new_dict["LockedFields"], "Name")
                            # self.__append_to_list(new_dict["LockedFields"], "Overview")
                            # self.__append_to_list(new_dict["LockedFields"], "ParentIndexNumber")
                            # self.__append_to_list(new_dict["LockedFields"], "IndexNumber")
                            # 更新数据
                            self.set_iteminfo(server=existsinfo.server, itemid=_id, iteminfo=new_dict)
                            # still_path 图片
                            if episodes[_index]["still_path"]:
                                self.set_item_image(server=existsinfo.server, itemid=_id, imageurl=f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episodes[_index]['still_path']}")
                            self.log_info(f"已修改剧集 - itemid: {_id},  第 {order} 季,  第 {str(_index + 1)} 集")
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

    def __media_exists(self, server: str, mediainfo: MediaInfo) -> ExistMediaInfo:
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
        
        if server == "emby":
            return __emby_media_exists()
        elif server == "jellyfin":
            return __jellyfin_media_exists()
        else:
            self.log_error(f"{mediainfo.title_year} 暂不支持当前媒体服务器")
            return None
        
    
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
