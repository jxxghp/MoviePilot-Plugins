import asyncio
import base64
import json
from collections import OrderedDict
from json import JSONDecodeError
from typing import Dict, List, Optional, Union, AsyncGenerator, Any

import httpx2
import requests
from pydantic import ValidationError

from app import schemas
from app.sdk.cache import cached
from app.sdk.config import settings
from app.sdk.media import MediaInfo, MetaBase, resolve_media_identity
from app.sdk.logging import logger
from app.schemas.types import MediaSource, MediaType
from app.sdk.network import AsyncRequestUtils, RequestUtils
from app.sdk.utilities import StringUtils, convert, retry

from .imdbapi import ImdbApiClient
from .officialapi import SearchParams, OfficialApiClient, PersistedQueryNotFound
from .schema import StaffPickApiResponse, ImdbMediaInfo, ImdbApiHash, TitleEdge
from .schema.imdbapi import ImdbapiPrecisionDate, ImdbApiTitle, ImdbApiListTitleSeasonsResponse
from .schema.imdbtypes import ImdbType, AkasNode, ImdbTitle, ImdbDate


class ImdbHelper:
    MAX_STATES = 128

    def __init__(self, proxies: Dict[str, str] | None = None):
        self._proxies = proxies
        self._session = requests.Session()
        if proxies:
            proxy_url = proxies.get("https") or proxies.get("http")
        else:
            proxy_url = None
        self._async_client = httpx2.AsyncClient(timeout=30, proxy=proxy_url)
        self.imdbapi_client = ImdbApiClient(
            session=self._session,
            async_client=self._async_client,
            proxies=self._proxies,
            ua=settings.NORMAL_USER_AGENT
        )
        self.official_api_client = OfficialApiClient(
            session=self._session,
            async_client=self._async_client,
            proxies=self._proxies,
            ua=settings.NORMAL_USER_AGENT
        )
        self._imdb_api_hash = ImdbApiHash(
            AdvancedTitleSearch='d32303ed2711e4d03bd5e36cfe0e5304bcffd7e31d1898695f6b6919736ff2a8'
        )
        self._search_states = OrderedDict()
        self._title_generators: OrderedDict[SearchParams, AsyncGenerator[TitleEdge, None]] = OrderedDict()

    def get_interests_id(self) -> Dict[str, str]:
        return self.official_api_client.interests_id

    @staticmethod
    @retry(Exception, logger=logger, delay=1)
    async def _async_fetch_github_file(proxies: Dict[str, str] | None, repo: str, owner: str, file_path: str,
                                       branch: str = None) -> Optional[str]:
        """
        异步从GitHub仓库获取指定文本文件内容

        :param proxies: 代理配置
        :param repo: 仓库名称
        :param owner: 仓库所有者
        :param file_path: 文件路径(相对于仓库根目录)
        :param branch: 分支名称，默认为 None(使用默认分支)
        :return: 文件内容字符串，若获取失败则返回 None
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
        if branch:
            api_url = f"{api_url}?ref={branch}"
        response = await AsyncRequestUtils(headers=settings.GITHUB_HEADERS, proxies=proxies
                                           ).get_res(api_url, raise_exception=True)
        if not response or response.status_code != 200:
            return None
        data = response.json()
        content_base64 = data['content']
        json_bytes = base64.b64decode(content_base64)
        json_text = json_bytes.decode('utf-8')
        return json_text

    @staticmethod
    async def async_fetch_github_file(proxies: Dict[str, str] | None, repo: str, owner: str, file_path: str,
                                      branch: str = None) -> Optional[str]:
        try:
            return await ImdbHelper._async_fetch_github_file(proxies, repo, owner, file_path, branch)
        except Exception as e:
            logger.error(f"Error getting GitHub file: {str(e)}")
            return None

    @cached(maxsize=1)
    async def async_fetch_hash(self) -> Optional[ImdbApiHash]:
        """
        异步获取 IMDb hash
        """
        res = await ImdbHelper.async_fetch_github_file(
            self._proxies,
            'MoviePilot-Plugins',
            'wumode',
            'plugins.v3/imdbsource/imdb_hash.json',
            'imdbsource_assets'
        )
        if not res:
            return None
        try:
            hash_data = json.loads(res)
            data = ImdbApiHash.model_validate(hash_data)
        except (JSONDecodeError, ValidationError):
            return None
        return data

    @cached(maxsize=2, ttl=6 * 3600)
    async def async_fetch_staff_picks(self, zh: bool = False) -> Optional[StaffPickApiResponse]:
        """
        获取 IMDb Staff Picks
        """
        file = 'staff_picks.zh.json' if zh else 'staff_picks.json'
        res = await ImdbHelper.async_fetch_github_file(
            self._proxies,
            'MoviePilot-Plugins',
            'wumode',
            f'plugins.v3/imdbsource/{file}',
            'imdbsource_assets'
        )
        if not res:
            logger.error("Error getting staff picks")
            return None
        try:
            data = StaffPickApiResponse.model_validate_json(res, by_name=True)
        except (JSONDecodeError, ValidationError):
            return None
        return data

    async def _async_update_hash(self, force: bool = False):
        if force:
            await self.async_fetch_hash.cache_clear()
        imdb_hash = await self.async_fetch_hash()
        if isinstance(imdb_hash, ImdbApiHash):
            self._imdb_api_hash = imdb_hash

    @staticmethod
    def compare_names(file_name: str, names: Union[list, str]) -> bool:
        """
        比较文件名是否匹配，忽略大小写和特殊字符

        :param file_name: 识别的文件名或者种子名
        :param names: TMDB返回的译名
        :return: True or False
        """
        if not file_name or not names:
            return False
        if not isinstance(names, list):
            names = [names]
        names = [name for name in names if name]
        file_name = StringUtils.clear(file_name).upper()
        for name in names:
            name = StringUtils.clear(name).strip().upper()
            if file_name == name:
                return True
        return False

    @staticmethod
    def type_to_mtype(title_id: str) -> MediaType:
        if title_id in ["tvSeries", "tvMiniSeries", "tvShort", "tvEpisode"]:
            return MediaType.TV
        elif title_id in ["movie", "tvMovie"]:
            return MediaType.MOVIE
        return MediaType.UNKNOWN

    @staticmethod
    def release_date_string(release_date: ImdbDate) -> Optional[str]:
        year = release_date.year or 0
        month = release_date.month or 0
        day = release_date.day or 0
        return f"{year:04d}-{month:02d}-{day:02d}"

    @staticmethod
    def get_category(mtype: MediaType, imdb_info: dict) -> str:
        tv_category = {
            '国漫': {'genres': 'Animation', 'originCountries': 'CN,TW,HK'},
            '日番': {'genres': 'Animation', 'originCountries': 'JP'},
            '纪录片': {'genres': 'Documentary'},
            '综艺': {'genres': 'Reality-TV,Game-Show'},
            '国产剧': {'originCountries': 'CN,TW,HK'},
            '欧美剧': {'originCountries': 'US,FR,GB,DE,ES,IT,NL,PT,RU,UK'},
            '日韩剧': {'originCountries': 'JP,KP,KR,TH,IN,SG'},
            '未分类': None
        }
        movie_category = {
            '动画电影': {'genres': 'Animation'},
            '华语电影': {'spokenLanguages': 'zho,cmn,yue,nan'},
            '外语电影': None}
        categories = {MediaType.TV: tv_category, MediaType.MOVIE: movie_category}
        category = categories.get(mtype)
        if not imdb_info or not category:
            return ""
        for key, item in category.items():
            if not item:
                return key
            match_flag = True
            for attr, value in item.items():
                if not value:
                    continue
                if attr == 'originCountries':
                    origin_countries = imdb_info.get('originCountries')
                    info_value = origin_countries[0].get('code') or [] if origin_countries else []
                elif attr == 'spokenLanguages':
                    spoken_languages = imdb_info.get('spokenLanguages')
                    info_value = spoken_languages[0].get('code') or [] if spoken_languages else []
                else:
                    info_value = imdb_info.get(attr)
                if isinstance(info_value, list):
                    info_values = info_value
                else:
                    info_values = [info_value]
                if value.find(',') != -1:
                    values = [str(val) for val in value.split(',') if val]
                else:
                    values = [str(value)]
                if not set(values).intersection(set(info_values)):
                    match_flag = False
            if match_flag:
                return key
        return ""

    async def advanced_title_search_generator(self, params: SearchParams, first_page: bool = True
                                              ) -> AsyncGenerator[TitleEdge, None]:
        await self._async_update_hash()
        sha256 = self._imdb_api_hash.advanced_title_search
        if not first_page and params in self._title_generators:
            return self._title_generators[params]
        generator = self.official_api_client.advanced_title_search_generator(params, sha256)
        self._title_generators[params] = generator
        if len(self._title_generators) > ImdbHelper.MAX_STATES:
            _, popped = self._title_generators.popitem(last=False)
            await popped.aclose()
        return generator

    async def async_advanced_title_search(self, params: SearchParams, first_page: bool = True, count: int = 50
                                          ) -> List[TitleEdge]:
        edges: List[TitleEdge] = []
        generator = await self.advanced_title_search_generator(params=params, first_page=first_page)
        try:
            async for edge in generator:
                edges.append(edge)
                if len(edges) >= count:
                    break
        except PersistedQueryNotFound:
            await self.async_fetch_hash.cache_clear()
        except RuntimeError:
            pass
        return edges

    def _tv_release_data_by_season(self, title_id: str) -> Optional[Dict[str, ImdbapiPrecisionDate]]:
        seasons_dict = {}
        for episode in self.imdbapi_client.episodes_generator(title_id):
            s = episode.season
            if not seasons_dict.get(s):
                seasons_dict[s] = episode.release_date
        return seasons_dict

    async def _async_tv_release_data_by_season(self, title_id: str) -> Optional[Dict[str, ImdbapiPrecisionDate]]:
        seasons_dict = {}
        async for episode in self.imdbapi_client.async_episodes_generator(title_id):
            s = episode.season
            if not seasons_dict.get(s):
                seasons_dict[s] = episode.release_date
        return seasons_dict

    def get_info_by_imdbid(self, imdbid: str) -> ImdbMediaInfo | None:
        title = self.imdbapi_client.title(imdbid)
        if not title:
            return None
        return ImdbMediaInfo.from_title(title)

    async def async_get_info_by_imdbid(self, imdbid: str) -> ImdbMediaInfo | None:
        title = await self.imdbapi_client.async_title(imdbid)
        if not title:
            return None
        return ImdbMediaInfo.from_title(title)

    def match_by(self, name: str, mtype: MediaType | None = None, year: str | None = None) -> ImdbMediaInfo | None:
        """
        根据名称同时查询电影和电视剧，没有类型也没有年份时使用

        :param name: 识别的文件名或种子名
        :param mtype: 类型：电影、电视剧
        :param year: 年份，如要是季集需要是首播年份
        :return: 匹配的媒体信息
        """

        mtypes = [MediaType.MOVIE, MediaType.TV] if not mtype else [mtype]
        search_types: List[ImdbType] = []
        if MediaType.TV in mtypes:
            search_types.extend([ImdbType.TV_SERIES, ImdbType.TV_MINI_SERIES, ImdbType.TV_SPECIAL])
        if MediaType.MOVIE in mtypes:
            search_types.extend([ImdbType.MOVIE, ImdbType.TV_MOVIE])
        if year:
            multi_res = self.imdbapi_client.advanced_search(query=name, year=int(year),
                                                            media_types=search_types)
        else:
            multi_res = self.imdbapi_client.advanced_search(query=name, media_types=search_types)
        ret_info = None
        if multi_res is None or len(multi_res) == 0:
            logger.debug(f"{name} 未找到相关媒体息!")
            return None
        multi_res = [r for r in multi_res if r.id and ImdbHelper.type_to_mtype(r.type.value) in mtypes]
        multi_res = sorted(
            multi_res,
            key=lambda x: ('1' if x.type in [ImdbType.MOVIE, ImdbType.TV_MOVIE] else '0') + f"{x.start_year}",
            reverse=True
        )
        items = self.official_api_client.vertical_list_page_items([x.id for x in multi_res])
        titles = items.titles if items else []

        for result in multi_res:
            title = next((t for t in titles if t.id == result.id), None)
            if not title:
                continue
            title_akas = title.akas
            akas = [edge.node for edge in title_akas.edges] if title_akas is not None else []
            start_year = result.start_year
            if year and str(start_year) != year:
                continue
            if ImdbHelper.compare_names(name, [result.primary_title or '', result.original_title or '']):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
            names = [edge.node.text for edge in title.akas.edges] if title.akas is not None else []
            if ImdbHelper.compare_names(name, names):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
        return ret_info

    async def async_match_by(self, name: str, mtype: Optional[MediaType] = None, year: Optional[str] = None
                             ) -> Optional[ImdbMediaInfo]:
        mtypes = [MediaType.MOVIE, MediaType.TV] if not mtype else [mtype]
        search_types: List[ImdbType] = []
        if MediaType.TV in mtypes:
            search_types.extend([ImdbType.TV_SERIES, ImdbType.TV_MINI_SERIES, ImdbType.TV_SPECIAL])
        if MediaType.MOVIE in mtypes:
            search_types.extend([ImdbType.MOVIE, ImdbType.TV_MOVIE])
        if year:
            multi_res = await self.imdbapi_client.async_advanced_search(query=name, year=int(year),
                                                                        media_types=search_types)
        else:
            multi_res = await self.imdbapi_client.async_advanced_search(query=name, media_types=search_types)
        ret_info = None
        if multi_res is None or len(multi_res) == 0:
            logger.debug(f"{name} 未找到相关媒体息!")
            return None
        multi_res = [r for r in multi_res if r.id and ImdbHelper.type_to_mtype(r.type.value) in mtypes]
        multi_res = sorted(
            multi_res,
            key=lambda x: ('1' if x.type in [ImdbType.MOVIE, ImdbType.TV_MOVIE] else '0') + f"{x.start_year}",
            reverse=True
        )
        items = await self.official_api_client.async_vertical_list_page_items([x.id for x in multi_res])
        titles = items.titles if items else []

        for result in multi_res:
            title = next((t for t in titles if t.id == result.id), None)
            if not title:
                continue
            title_akas = title.akas
            akas = [edge.node for edge in title_akas.edges] if title_akas is not None else []
            start_year = result.start_year
            if year and str(start_year) != year:
                continue
            if ImdbHelper.compare_names(name, [result.primary_title or '', result.original_title or '']):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
            names = [edge.node.text for edge in title.akas.edges] if title.akas is not None else []
            if ImdbHelper.compare_names(name, names):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
        return ret_info

    def match_by_season(self, name: str, season_year: str, season_number: int) -> Optional[ImdbMediaInfo]:
        """
        根据电视剧的名称和季的年份及序号匹配 IMDb

        :param name: 识别的文件名或者种子名
        :param season_year: 季的年份
        :param season_number: 季序号
        :return: 匹配的媒体信息
        """

        def __season_match(imdb_id: str, _season_year: str, _season_number: int) -> bool:
            release_dates = self._tv_release_data_by_season(imdb_id)
            for s, release_date in release_dates.items():
                if not release_date or not release_date.year:
                    continue
                if str(release_date.year) == _season_year and s == str(_season_number):
                    return True
            return False

        search_types = [ImdbType.TV_SERIES, ImdbType.TV_MINI_SERIES, ImdbType.TV_SPECIAL]
        res = self.imdbapi_client.advanced_search(query=name, media_types=search_types)
        if not res:
            logger.debug(f"{name} 未找到季{season_number}相关信息!")
            return None
        tvs: List[ImdbApiTitle] = [r for r in res if r.id and ImdbHelper.type_to_mtype(r.type.value) == MediaType.TV]
        tvs = sorted(tvs, key=lambda x: x.start_year or 0, reverse=True)
        items = self.official_api_client.vertical_list_page_items([x.id for x in tvs])
        titles = items.titles if items else []
        titles_dict: Dict[str, ImdbTitle] = {}
        for title in titles:
            titles_dict[title.id] = title
        for tv in tvs:
            # 年份
            title = titles_dict.get(tv.id)
            if not title:
                continue
            akas: List[AkasNode] = [e.node for e in title.akas.edges]
            tv_year = tv.start_year
            if self.compare_names(name, [tv.primary_title or '', tv.original_title or '']) and str(tv_year) == season_year:
                info = ImdbMediaInfo.from_title(tv, akas=akas)
                return info
            names = [aka.text for aka in akas]
            if not tv or not self.compare_names(name, names):
                continue
            if __season_match(imdb_id=tv.id, _season_year=season_year, _season_number=season_number):
                info = ImdbMediaInfo.from_title(tv, akas=akas)
                return info
        return None

    async def async_match_by_season(self, name: str, season_year: str, season_number: int) -> Optional[ImdbMediaInfo]:

        async def __season_match(imdb_id: str, _season_year: str, _season_number: int) -> bool:
            release_dates = await self._async_tv_release_data_by_season(imdb_id)
            if not release_dates:
                return False
            for s, release_date in release_dates.items():
                if not release_date or not release_date.year:
                    continue
                if str(release_date.year) == _season_year and s == str(_season_number):
                    return True
            return False

        search_types = [ImdbType.TV_SERIES, ImdbType.TV_MINI_SERIES, ImdbType.TV_SPECIAL]
        res = await self.imdbapi_client.async_advanced_search(query=name, media_types=search_types)
        if not res:
            logger.debug(f"{name} 未找到季{season_number}相关信息!")
            return None
        tvs: List[ImdbApiTitle] = [r for r in res if r.id and ImdbHelper.type_to_mtype(r.type.value) == MediaType.TV]
        tvs = sorted(tvs, key=lambda x: x.start_year or 0, reverse=True)
        items = await self.official_api_client.async_vertical_list_page_items([x.id for x in tvs])
        titles = items.titles if items else []
        titles_dict: Dict[str, ImdbTitle] = {}
        for title in titles:
            titles_dict[title.id] = title
        for tv in tvs:
            # 年份
            title = titles_dict.get(tv.id)
            if not title:
                continue
            akas: List[AkasNode] = [e.node for e in title.akas.edges]
            tv_year = tv.start_year
            if self.compare_names(name, [tv.primary_title or '', tv.original_title or '']) and str(tv_year) == season_year:
                info = ImdbMediaInfo.from_title(tv, akas=akas)
                return info
            names = [aka.text for aka in akas]
            if not tv or not self.compare_names(name, names):
                continue
            if await __season_match(imdb_id=tv.id, _season_year=season_year, _season_number=season_number):
                info = ImdbMediaInfo.from_title(tv, akas=akas)
                return info
        return None

    def match(
            self, name: str,
            mtype: MediaType,
            year: Optional[str] = None,
            season_year: Optional[str] = None,
            season_number: Optional[int] = None,
    ) -> Optional[ImdbMediaInfo]:
        """
        搜索 IMDb 中的媒体信息，匹配返回一条尽可能正确的信息

        :param name: 检索的名称
        :param mtype: 类型：电影、电视剧
        :param year: 年份，如要是季集需要是首播年份
        :param season_year: 当前季集年份
        :param season_number: 季集，整数
        :return: 匹配的媒体信息
        """
        if not name:
            return None
        info = None
        if mtype == MediaType.TV:
            # 有当前季和当前季集年份，使用精确匹配
            if season_year and season_number:
                logger.debug(f"正在识别{mtype.value}：{name}, 季集={season_number}, 季集年份={season_year} ...")
                info = self.match_by_season(name, season_year, season_number)
                if info:
                    return info
        year_range = [year, str(int(year) + 1), str(int(year) - 1)] if year else [None]
        for year in year_range:
            logger.debug(f"正在识别{mtype.value}：{name}, 年份={year} ...")
            info = self.match_by(name, mtype, year)
            if info:
                break
        return info

    async def async_match(
            self, name: str,
            mtype: MediaType,
            year: Optional[str] = None,
            season_year: Optional[str] = None,
            season_number: Optional[int] = None,
    ) -> Optional[ImdbMediaInfo]:

        if not name:
            return None
        info = None
        if mtype == MediaType.TV:
            # 有当前季和当前季集年份，使用精确匹配
            if season_year and season_number:
                logger.debug(f"正在识别{mtype.value}：{name}, 季集={season_number}, 季集年份={season_year} ...")
                info = await self.async_match_by_season(name, season_year, season_number)
                if info:
                    return info
        year_range = [year, str(int(year) + 1), str(int(year) - 1)] if year else [None]
        for year in year_range:
            logger.debug(f"正在识别{mtype.value}：{name}, 年份={year} ...")
            info = await self.async_match_by(name, mtype, year)
            if info:
                break
        return info

    def update_info(self, title_id: str, info: ImdbMediaInfo) -> ImdbMediaInfo:
        """
        Given a Title ID, update its media information.

        :param title_id: IMDb ID.
        :param info: Media information to be updated.
        :return: IMDb info.
        """
        details = self.imdbapi_client.title(title_id) or info
        akas = info.akas
        if not akas:
            resp = self.imdbapi_client.akas(title_id)
            akas = resp.akas if resp else []
        credit_list = [credit for credit in self.imdbapi_client.credits_generator(title_id)]
        episodes = [episode for episode in self.imdbapi_client.episodes_generator(title_id)]
        images = [image for image in self.imdbapi_client.images_generator(title_id)]
        seasons = self.imdbapi_client.seasons(title_id)
        return ImdbMediaInfo.from_title(details, akas=akas, api_credits=credit_list, episodes=episodes, images=images,
                                        seasons=seasons.seasons if seasons else None)

    async def async_update_info(self, title_id: str, info: ImdbMediaInfo) -> ImdbMediaInfo:
        """
        异步更新 IMDb 媒体信息，使用 asyncio.gather 进行多接口并发请求优化
        """
        async def _fetch_akas():
            if info and info.akas:
                return info.akas
            resp = await self.imdbapi_client.async_akas(title_id)
            return resp.akas if resp else []

        async def _fetch_credits():
            return [credit async for credit in self.imdbapi_client.async_credits_generator(title_id)]

        async def _fetch_episodes():
            return [episode async for episode in self.imdbapi_client.async_episodes_generator(title_id)]

        async def _fetch_images():
            return [image async for image in self.imdbapi_client.async_images_generator(title_id)]

        async def _fetch_seasons():
            return await self.imdbapi_client.async_seasons(title_id)

        async def _empty_list():
            return []

        async def _none():
            return None

        # 判断媒体类型是否为电影（电影不需要拉取剧集和季度信息）
        is_movie = False
        if info and info.type and info.type.value:
            mtype = ImdbHelper.type_to_mtype(info.type.value)
            if mtype == MediaType.MOVIE:
                is_movie = True

        title_task = self.imdbapi_client.async_title(title_id)
        akas_task = _fetch_akas()
        credits_task = _fetch_credits()
        images_task = _fetch_images()

        if is_movie:
            episodes_task = _empty_list()
            seasons_task = _none()
        else:
            episodes_task = _fetch_episodes()
            seasons_task = _fetch_seasons()

        details, akas, credit_list, episodes, images, seasons = await asyncio.gather(
            title_task,
            akas_task,
            credits_task,
            episodes_task,
            images_task,
            seasons_task,
            return_exceptions=True
        )

        details = details if isinstance(details, ImdbApiTitle) else info
        akas = akas if isinstance(akas, list) else (info.akas or [])
        credit_list = credit_list if isinstance(credit_list, list) else []
        episodes = episodes if isinstance(episodes, list) else []
        images = images if isinstance(images, list) else []
        seasons_resp = seasons if isinstance(seasons, ImdbApiListTitleSeasonsResponse) else None

        return ImdbMediaInfo.from_title(
            details,
            akas=akas,
            api_credits=credit_list,
            episodes=episodes,
            images=images,
            seasons=seasons_resp.seasons if seasons_resp else None
        )

    @staticmethod
    def convert_mediainfo(info: ImdbMediaInfo) -> MediaInfo:
        """将 ImdbMediaInfo 转换为 MediaInfo"""
        mediainfo = MediaInfo()
        mediainfo.media_source = MediaSource.IMDb
        mediainfo.media_id = info.id
        mediainfo.type = ImdbHelper.type_to_mtype(info.type.value)
        mediainfo.title = info.primary_title or ""
        mediainfo.en_title = info.primary_title

        mediainfo.year = f"{info.start_year}" if info.start_year else ""
        mediainfo.overview = info.plot or ""
        mediainfo.imdb_id = info.id

        if info.spoken_languages:
            original_language = info.spoken_languages[0].code
            if original_language:
                mediainfo.original_language = original_language
        if info.original_title:
            mediainfo.original_title = info.original_title
        mediainfo.names = [aka.text for aka in info.akas]
        if info.origin_countries:
            mediainfo.origin_country = [origin_country.code for origin_country in info.origin_countries if
                                        origin_country.code]
            mediainfo.production_countries = [{"name": origin_country.name} for origin_country in info.origin_countries
                                              if origin_country.name]
        if info.primary_image and info.primary_image.url:
            mediainfo.poster_path = info.primary_image.url
        if info.images:
            mediainfo.backdrop_path = info.backdrop_path()  # noqa
        mediainfo.genres = [{"id": genre, "name": genre} for genre in info.genres or []]
        directors = []
        actors = []
        for credit in (info.credits or []):
            if not credit.name:
                continue
            category = credit.category.upper() if credit.category else ""
            if category == "DIRECTOR":
                directors.append(
                    credit.to_media_credit().model_dump()
                )
            elif category in ["CAST", "ACTOR", "ACTRESS"]:
                actors.append(credit.to_media_credit().model_dump())
        mediainfo.directors = directors[:3]
        mediainfo.actors = actors[:6]
        vote = info.rating.aggregate_rating if info.rating and info.rating.aggregate_rating else None
        if vote:
            mediainfo.vote_average = round(float(vote), 1)
        season_years: Dict[int, int] = {}

        if mediainfo.type == MediaType.TV:
            season_info: dict[str, dict[str, Any]] = {
                s.season: {
                    "season_number": int(s.season) if StringUtils.is_number(s.season) else None,
                    "episode_count": s.episode_count,
                    "name": s.season
                }
                for s in (info.seasons or []) if s and s.season
            }
            for episode in (info.episodes or []):
                ep_season = episode.season
                if ep_season is None:
                    continue
                season = int(ep_season) if StringUtils.is_number(ep_season) else 0
                if season not in season_years:
                    if episode.release_date and episode.release_date.year:
                        season_years[season] = episode.release_date.year
                    else:
                        season_years[season] = 0
                if episode.season in season_info:
                    season_info[episode.season]['season_number'] = season
                mediainfo.seasons.setdefault(season, []).append(episode.episode_number or 0)
                mediainfo.season_years[season] = f"{season_years[season]}"
            mediainfo.season_info = list(season_info.values())
            mediainfo.number_of_seasons = len(info.seasons or [])
            mediainfo.number_of_episodes = len(info.episodes or [])
        return mediainfo

    @staticmethod
    def title_to_mediainfo(info: ImdbTitle) -> schemas.MediaInfo:
        mediainfo = schemas.MediaInfo(
            media_source=MediaSource.IMDb,
            media_id=info.id,
        )
        mediainfo.title = info.title_text.text if info.title_text else ''
        if ImdbHelper.type_to_mtype(info.title_type.id.value) == MediaType.TV:
            mediainfo.type = '电视剧'
        elif ImdbHelper.type_to_mtype(info.title_type.id.value) == MediaType.MOVIE:
            mediainfo.type = '电影'
        if info.release_year:
            mediainfo.year = f"{info.release_year.year}"
            mediainfo.title_year = f"{mediainfo.title} ({mediainfo.year})" if mediainfo.year else mediainfo.title
        if info.primary_image:
            mediainfo.poster_path = info.primary_image.poster_path()
        if info.ratings_summary:
            mediainfo.vote_average = info.ratings_summary.aggregate_rating
        if info.runtime:
            mediainfo.runtime = info.runtime.seconds
        if info.plot and info.plot.plot_text:
            mediainfo.overview = info.plot.plot_text.plain_text
        if info.release_date:
            mediainfo.release_date = ImdbHelper.release_date_string(info.release_date)

        return mediainfo

    @cached(maxsize=4096, ttl=86400)
    def find_imdb_id(self, imdb_id: str) -> Optional[dict]:
        api_key = settings.TMDB_API_KEY
        api_url = (
            f"https://{settings.TMDB_API_DOMAIN}/3/find/{imdb_id}"
            f"?api_key={api_key}&external_source=imdb_id"
        )
        data = RequestUtils(
            accept_type="application/json",
            proxies=settings.PROXY if self._proxies else None,
            session=self._session
        ).get_json(api_url)
        return data

    @cached(maxsize=4096, ttl=86400)
    async def async_find_imdb_id(self, imdb_id: str) -> Optional[dict]:
        api_key = settings.TMDB_API_KEY
        api_url = (
            f"https://{settings.TMDB_API_DOMAIN}/3/find/{imdb_id}"
            f"?api_key={api_key}&external_source=imdb_id"
        )
        data = await AsyncRequestUtils(
            accept_type="application/json",
            proxies=settings.PROXY if self._proxies else None,
            client=self._async_client
        ).get_json(api_url)
        return data

    @staticmethod
    def _match_results(data: dict, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        # 合并两种结果
        all_results = []
        for key in ["movie_results", "tv_results"]:
            all_results.extend(data.get(key, []))
        if not all_results:
            return None  # 无匹配结果

        def pick_most_popular(results):
            return max(results, key=lambda x: x.get("popularity", -1), default=None)

        # 未提供 media_info：直接返回人气最高的
        if not media_info:
            most_popular = pick_most_popular(all_results)
            return most_popular.get("id") if most_popular else None
        # 按类型过滤
        type_map = {
            MediaType.TV: ['tv'],
            MediaType.MOVIE: ['movie'],
            None: ['tv', 'movie']
        }
        allowed_types = type_map.get(media_info.type, ['tv', 'movie'])
        filtered = [res for res in all_results if res.get('media_type') in allowed_types]

        # 定义一个过滤链：每次过滤后如果只剩一个结果就返回
        def filter_and_return(results, predicate):
            filtered_res = [res for res in results if predicate(res)]
            if not filtered_res:
                return None, []
            if len(filtered_res) == 1:
                return filtered_res[0].get("id"), []
            return None, filtered_res

        # 通过年份过滤
        if media_info.year:
            def match_year(res):
                date = res.get('first_air_date') or res.get('release_date') or ''
                return date[:4] == media_info.year

            result_id, filtered = filter_and_return(filtered, match_year)
            if result_id:
                return result_id
            if not filtered:
                return None
        # 通过名称过滤
        if media_info.names:
            def match_name(res):
                name = res.get('name') or res.get('title') or ''
                return ImdbHelper.compare_names(name, media_info.names)

            result_id, filtered = filter_and_return(filtered, match_name)
            if result_id:
                return result_id
            if not filtered:
                return None
        # 最终按人气返回
        most_popular = pick_most_popular(filtered)
        return most_popular.get("id") if most_popular else None

    def imdb_to_tmdb(self, imdb_id: str, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        data = self.find_imdb_id(imdb_id)
        if not data:
            return None
        return ImdbHelper._match_results(data, media_info)

    async def async_imdb_to_tmdb(self, imdb_id: str, media_info: Optional[MediaInfo] = None) -> Optional[int]:
        data = await self.async_find_imdb_id(imdb_id)
        if not data:
            return None
        return ImdbHelper._match_results(data, media_info)

    def recognize_media(
            self, meta: MetaBase = None,
            mtype: MediaType = None,
            media_source: MediaSource | None = None,
            media_id: str | None = None,
            add_tmdb_id: bool = False,
    ) -> Optional[MediaInfo]:
        """
        识别媒体信息
        :param meta: 识别的元数据
        :param mtype: 识别的媒体类型
        :param media_source: 媒体数据源
        :param media_id: 数据源原生 ID,
        :param add_tmdb_id: 添加 tmdb id 到元数据
        :return: 识别的媒体信息，包括剧集信息
        """
        explicit_identity = media_source is not None or media_id is not None
        if explicit_identity:
            source, normalized_media_id = resolve_media_identity(
                media_source=media_source,
                media_id=media_id,
            )
            if source != MediaSource.IMDb or not normalized_media_id:
                return None
            info = self.get_info_by_imdbid(normalized_media_id)
        else:
            if not meta:
                return None
            elif not meta.name:
                logger.warn("识别媒体信息时未提供元数据名称")
                return None
            else:
                if mtype:
                    meta.type = mtype
            info: Optional[ImdbMediaInfo] = None
            # 简体名称
            zh_name = convert(meta.cn_name, 'zh-hans') if meta.cn_name else None
            media_names = list(dict.fromkeys([k for k in [meta.cn_name, zh_name, meta.en_name] if k]))
            names: list[str] = [name for name in media_names if isinstance(name, str)]
            for name in names:
                if meta.begin_season:
                    logger.info(f"正在识别 {name} 第{meta.begin_season}季 ...")
                else:
                    logger.info(f"正在识别 {name} ...")
                if meta.type == MediaType.UNKNOWN and not meta.year:
                    info = self.match_by(name)
                else:
                    if meta.type == MediaType.TV:
                        info = self.match(name=name, year=meta.year, mtype=meta.type, season_year=meta.year,
                                                       season_number=meta.begin_season)
                        if not info:
                            # 去掉年份再查一次
                            info = self.match(name=name, mtype=meta.type)
                    else:
                        # 有年份先按电影查
                        info = self.match(name=name, year=meta.year, mtype=MediaType.MOVIE)
                        # 没有再按电视剧查
                        if not info:
                            info = self.match(name=name, year=meta.year, mtype=MediaType.TV)
                        if not info:
                            # 去掉年份和类型再查一次
                            info = self.match_by(name=name)
                if info:
                    break
        if info:
            info: ImdbMediaInfo = self.update_info(info.id, info=info)
            mediainfo = ImdbHelper.convert_mediainfo(info)
            if add_tmdb_id:
                tmdb_id = self.imdb_to_tmdb(info.id, mediainfo)
                if tmdb_id:
                    mediainfo.tmdb_id = tmdb_id
            cat = ImdbHelper.get_category(ImdbHelper.type_to_mtype(info.type.value),
                                          info.model_dump(by_alias=True, exclude_none=True))
            mediainfo.set_category(cat)
            name = meta.name if meta else mediainfo.title
            logger.info(f"{name} IMDb 识别结果：{mediainfo.type.value} "
                        f"{mediainfo.title_year} "
                        f"{mediainfo.media_source}:{mediainfo.media_id}")
            return mediainfo
        return None

    async def async_recognize_media(
            self, meta: MetaBase = None,
            mtype: MediaType = None,
            media_source: MediaSource | None = None,
            media_id: str | None = None,
            add_tmdb_id: bool = False,
    ) -> Optional[MediaInfo]:
        explicit_identity = media_source is not None or media_id is not None
        if explicit_identity:
            source, normalized_media_id = resolve_media_identity(
                media_source=media_source,
                media_id=media_id,
            )
            if source != MediaSource.IMDb or not normalized_media_id:
                return None
            info = await self.async_get_info_by_imdbid(normalized_media_id)
        else:
            if not meta:
                return None
            elif not meta.name:
                logger.warn("识别媒体信息时未提供元数据名称")
                return None
            else:
                if mtype:
                    meta.type = mtype
            info: Optional[ImdbMediaInfo] = None
            # 简体名称
            zh_name = convert(meta.cn_name, 'zh-hans') if meta.cn_name else None
            media_names = list(dict.fromkeys([k for k in [meta.cn_name, zh_name, meta.en_name] if k]))
            names: list[str] = [name for name in media_names if isinstance(name, str)]
            for name in names:
                if meta.begin_season:
                    logger.info(f"正在识别 {name} 第{meta.begin_season}季 ...")
                else:
                    logger.info(f"正在识别 {name} ...")
                if meta.type == MediaType.UNKNOWN and not meta.year:
                    info = await self.async_match_by(name)
                else:
                    if meta.type == MediaType.TV:
                        info = await self.async_match(name=name, year=meta.year, mtype=meta.type,
                                                                   season_year=meta.year,
                                                                   season_number=meta.begin_season)
                        if not info:
                            # 去掉年份再查一次
                            info = await self.async_match(name=name, mtype=meta.type)
                    else:
                        # 有年份先按电影查
                        info = await self.async_match(name=name, year=meta.year, mtype=MediaType.MOVIE)
                        # 没有再按电视剧查
                        if not info:
                            info = await self.async_match(name=name, year=meta.year, mtype=MediaType.TV)
                        if not info:
                            # 去掉年份和类型再查一次
                            info = await self.async_match_by(name=name)
                if info:
                    break
        if info:
            info: ImdbMediaInfo = await self.async_update_info(info.id, info=info)
            mediainfo = ImdbHelper.convert_mediainfo(info)
            if add_tmdb_id:
                tmdb_id = await self.async_imdb_to_tmdb(info.id, mediainfo)
                if tmdb_id:
                    mediainfo.tmdb_id = tmdb_id
            cat = ImdbHelper.get_category(ImdbHelper.type_to_mtype(info.type.value),
                                          info.model_dump(by_alias=True, exclude_none=True))
            mediainfo.set_category(cat)
            name = meta.name if meta else mediainfo.title
            logger.info(f"{name} IMDb 识别结果：{mediainfo.type.value} "
                        f"{mediainfo.title_year} "
                        f"{mediainfo.media_source}:{mediainfo.media_id}")
            return mediainfo
        return None
