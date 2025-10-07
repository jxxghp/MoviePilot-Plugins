import base64
from collections import OrderedDict
from json import JSONDecodeError
import json
from typing import Dict, List, Optional, Union, AsyncGenerator

from pydantic import ValidationError

from app import schemas
from app.core.cache import cached
from app.core.config import settings
from app.core.context import MediaInfo
from app.log import logger
from app.schemas.types import MediaType
from app.utils.http import AsyncRequestUtils
from app.utils.string import StringUtils

from .imdbapi import ImdbApiClient
from .officialapi import SearchParams, OfficialApiClient, PersistedQueryNotFound
from .schema import StaffPickApiResponse, ImdbMediaInfo, ImdbApiHash, TitleEdge
from .schema.imdbapi import ImdbapiPrecisionDate, ImdbApiTitle
from .schema.imdbtypes import ImdbType, AkasNode, ImdbTitle, ImdbDate


class ImdbHelper:
    MAX_STATES = 128

    def __init__(self, proxies = None):
        self._proxies = proxies
        self.imdbapi_client = ImdbApiClient(proxies=self._proxies, ua=settings.NORMAL_USER_AGENT)
        self.official_api_client = OfficialApiClient(proxies=self._proxies, ua=settings.NORMAL_USER_AGENT)
        self._imdb_api_hash = ImdbApiHash(
            AdvancedTitleSearch='d32303ed2711e4d03bd5e36cfe0e5304bcffd7e31d1898695f6b6919736ff2a8'
        )
        self._search_states = OrderedDict()
        self._title_generators: OrderedDict[SearchParams, AsyncGenerator[TitleEdge, None]] = OrderedDict()

    def get_interests_id(self) -> Dict[str, str]:
        return self.official_api_client.interests_id

    async def async_fetch_github_file(self, repo: str, owner: str, file_path: str, branch: str = None) -> Optional[str]:
        """
        异步从GitHub仓库获取指定文本文件内容
        :param repo: 仓库名称
        :param owner: 仓库所有者
        :param file_path: 文件路径(相对于仓库根目录)
        :param branch: 分支名称，默认为 None(使用默认分支)
        :return: 文件内容字符串，若获取失败则返回 None
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
        if branch:
            api_url = f"{api_url}?ref={branch}"
        response = await AsyncRequestUtils(headers=settings.GITHUB_HEADERS, proxies=self._proxies).get_res(api_url)
        if not response or response.status_code != 200:
            return None
        try:
            data = response.json()
            content_base64 = data['content']
            json_bytes = base64.b64decode(content_base64)
            json_text = json_bytes.decode('utf-8')
        except (TypeError, ValueError, KeyError, UnicodeDecodeError):
            return None
        return json_text

    @cached(maxsize=1)
    async def async_fetch_hash(self) -> Optional[ImdbApiHash]:
        """
        异步获取 IMDb hash
        """
        res = await self.async_fetch_github_file(
            'MoviePilot-Plugins',
            'wumode',
            'plugins.v2/imdbsource/imdb_hash.json',
            'imdbsource_assets'
        )
        if not res:
            logger.error("Error getting hash")
            return None
        try:
            hash_data = json.loads(res)
            data = ImdbApiHash.parse_obj(hash_data)
        except (JSONDecodeError, ValidationError):
            return None
        return data

    @cached(maxsize=2, ttl=6 * 3600)
    async def async_fetch_staff_picks(self, zh: bool = False) -> Optional[StaffPickApiResponse]:
        """
        获取 IMDb Staff Picks
        """
        file = 'staff_picks.zh.json' if zh else 'staff_picks.json'
        res = await self.async_fetch_github_file(
            'MoviePilot-Plugins',
            'wumode',
            f'plugins.v2/imdbsource/{file}',
            'imdbsource_assets'
        )
        if not res:
            logger.error("Error getting staff picks")
            return None
        try:
            data = StaffPickApiResponse.parse_obj(json.loads(res))
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

    async def advanced_title_search_generator(self, params: SearchParams, first_page: bool = True) -> AsyncGenerator[TitleEdge, None]:
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

    def match_by(self, name: str, mtype: Optional[MediaType] = None, year: Optional[str] = None) -> Optional[ImdbMediaInfo]:
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
            akas = [edge.node for edge in title.akas.edges]
            start_year = result.start_year
            if year and str(start_year) != year:
                continue
            if ImdbHelper.compare_names(name, [result.primary_title or '', result.original_title or '']):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
            names = [edge.node.text for edge in title.akas.edges]
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
            akas = title.akas
            start_year = result.start_year
            if year and str(start_year) != year:
                continue
            if ImdbHelper.compare_names(name, [result.primary_title or '', result.original_title or '']):
                ret_info = ImdbMediaInfo.from_title(result, akas=akas)
                return ret_info
            names = [edge.node.text for edge in title.akas.edges]
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

    def match(self, name: str,
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

    async def async_match(self, name: str,
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
            akas = self.imdbapi_client.akas(title_id) or []
        credit_list = [credit for credit in self.imdbapi_client.credits_generator(title_id)]
        episodes = [episode for episode in self.imdbapi_client.episodes_generator(title_id)]
        return ImdbMediaInfo.from_title(details, akas=akas, credits=credit_list, episodes=episodes)

    async def async_update_info(self, title_id: str, info: ImdbMediaInfo) -> ImdbMediaInfo:
        details = await self.imdbapi_client.async_title(title_id) or info
        akas = info.akas
        if not akas:
            akas = await self.imdbapi_client.async_akas(title_id) or []
        credit_list = [credit async for credit in self.imdbapi_client.async_credits_generator(title_id)]
        episodes = [episode async for episode in self.imdbapi_client.async_episodes_generator(title_id)]
        return ImdbMediaInfo.from_title(details, akas=akas, credits=credit_list, episodes=episodes)

    @staticmethod
    def convert_mediainfo(info: ImdbMediaInfo) -> MediaInfo:
        mediainfo = MediaInfo()
        mediainfo.source = 'imdb'
        mediainfo.type = ImdbHelper.type_to_mtype(info.type.value)
        mediainfo.title = info.primary_title
        mediainfo.year = f"{info.start_year or 0}"
        mediainfo.imdb_id = info.id
        mediainfo.overview = info.plot
        spoken_languages = info.spoken_languages
        mediainfo.original_language = spoken_languages[0].code if spoken_languages else None
        mediainfo.original_title = info.original_title
        mediainfo.names = [aka.text for aka in info.akas]
        mediainfo.origin_country = [origin_country.code for origin_country in info.origin_countries]
        mediainfo.poster_path = info.primary_image.url if info.primary_image else None
        mediainfo.genres = [{"id": genre, "name": genre} for genre in info.genres or []]
        directors = []
        actors = []
        for credit in (info.credits or []):
            if not credit.name:
                continue
            if credit.category == 'DIRECTOR':
                directors.append({'name': f"{credit.name.display_name or ''}"})
            elif credit.category in ['CAST', 'ACTOR', 'ACTRESS']:
                actors.append({'name': f"{credit.name.display_name or ''}"})
        mediainfo.director = directors
        mediainfo.actor = actors
        vote = info.rating.aggregate_rating if info.rating and info.rating.aggregate_rating else None
        mediainfo.vote_average = round(float(vote), 1) if vote else None
        season_years: Dict[int, int] = {}
        if mediainfo.type == MediaType.TV:
            for episode in info.episodes:
                season = int(episode.season) if StringUtils.is_number(episode.season) else 0
                if season not in season_years:
                    season_years[season] = episode.release_date.year if episode.release_date else 0
                mediainfo.seasons.setdefault(season, []).append(episode)
                mediainfo.season_years[season] = season_years[season]

        return mediainfo

    @staticmethod
    def title_to_mediainfo(info: ImdbTitle) -> schemas.MediaInfo:
        mediainfo = schemas.MediaInfo(mediaid_prefix="imdb", media_id=info.id, imdb_id=info.id)
        mediainfo.title = info.title_text.text if info.title_text else ''
        if ImdbHelper.type_to_mtype(info.title_type.id.value) == MediaType.TV:
            mediainfo.type = '电视剧'
        elif ImdbHelper.type_to_mtype(info.title_type.id.value) == MediaType.MOVIE:
            mediainfo.type = '电影'
        if info.release_year:
            mediainfo.year = f"{info.release_year.year}"
            mediainfo.title_year = f"{mediainfo.title} ({mediainfo.year})" if mediainfo.year else mediainfo.title
        if info.primary_image:
            primary_image = info.primary_image.url if info.primary_image else None
            if primary_image:
                poster_path = primary_image.replace('@._V1', '@._V1_QL75_UY414_CR6,0,280,414_')
                mediainfo.poster_path = poster_path
        if info.ratings_summary:
            mediainfo.vote_average = info.ratings_summary.aggregate_rating
        if info.runtime:
            mediainfo.runtime = info.runtime.seconds
        if info.plot and info.plot.plot_text:
            mediainfo.overview = info.plot.plot_text.plain_text
        if info.release_date:
            mediainfo.release_date = ImdbHelper.release_date_string(info.release_date)

        return mediainfo

