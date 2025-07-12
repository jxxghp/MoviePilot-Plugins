import re
from json import JSONDecodeError
from typing import Optional, Any, Dict, Tuple, List
from collections import OrderedDict
from dataclasses import dataclass
import json
import base64

import requests

from app.core.config import settings
from app.log import logger
from app.utils.http import RequestUtils
from app.utils.common import retry
from app.core.cache import cached


@dataclass(frozen=True)
class SearchParams:
    title_types: Optional[Tuple[str, ...]] = None
    genres: Optional[Tuple[str, ...]] = None
    sort_by: str = 'POPULARITY'
    sort_order: str = 'ASC'
    rating_min: Optional[float] = None
    rating_max: Optional[float] = None
    countries: Optional[Tuple[str, ...]] = None
    languages: Optional[Tuple[str, ...]] = None
    release_date_end: Optional[str] = None
    release_date_start: Optional[str] = None
    award_constraint: Optional[Tuple[str, ...]] = None
    ranked: Optional[Tuple[str, ...]] = None
    interests: Optional[Tuple[str, ...]] = None


class SearchState:
    def __init__(self, pageinfo: dict, total: int):
        self.pageinfo = pageinfo
        self.total = total


class ImdbHelper:
    _official_endpoint = "https://caching.graphql.imdb.com/"
    _imdb_headers = {
        "Accept": "text/html,application/json,text/plain,*/*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome"
                      "/84.0.4147.105 Safari/537.36",
        "Referer": "https://www.imdb.com/",
    }
    all_title_types = ["tvSeries", "tvMiniSeries", "movie", "tvMovie", "musicVideo", "tvShort", "short",
                       "tvEpisode", "tvSpecial", "videoGame"]
    interest_id = {
        "Anime": "in0000027",
        "Superhero": "in0000008",
        "Sitcom": "in0000044",
        "Coming-of-Age": "in0000073",
        "Slasher Horror": "in0000115",
        "Raunchy Comedy": "in0000041",
        "Documentary": "in0000060"
    }

    def __init__(self, proxies=None):
        self._proxies = proxies
        self._imdb_req = RequestUtils(accept_type="application/json",
                                      content_type="application/json",
                                      headers=self._imdb_headers,
                                      timeout=10,
                                      proxies=proxies,
                                      session=requests.Session())
        self._imdb_api_hash = {"AdvancedTitleSearch": None, "TitleAkasPaginated": None}
        self.hash_status = {"AdvancedTitleSearch": False, "TitleAkasPaginated": False}
        self._search_states = OrderedDict()
        self._max_states = 30

    @retry(Exception, logger=logger)
    @cached(maxsize=32, ttl=1800)
    def __query_graphql (self, query: str, variables: Dict[str, Any]) -> Optional[Dict]:
        params = {'query': query, 'variables': variables}
        ret = self._imdb_req.post_res(f"{self._official_endpoint}", json=params, raise_exception=True)
        if not ret:
            return None
        data = ret.json()
        if "errors" in data:
            error = data.get("errors")[0] if data.get("errors") else {}
            return {'error': error}
        return data.get("data")

    @retry(Exception, logger=logger)
    @cached(maxsize=32, ttl=1800)
    def __request(self, params: Dict, sha256) -> Optional[Dict]:
        params["extensions"] = {"persistedQuery": {"sha256Hash": sha256, "version": 1}}
        ret = self._imdb_req.post_res(f"{self._official_endpoint}", json=params, raise_exception=True)
        if not ret:
            return None
        data = ret.json()
        if "errors" in data:
            error = data.get("errors")[0] if data.get("errors") else {}
            if error and error.get("message") == 'PersistedQueryNotFound':
                logger.warn(f"PersistedQuery hash has expired, trying to update...")
                self.__get_hash.cache_clear()
            return {'error': error}
        return data.get("data")

    def get_github_file(self, repo: str, owner: str, file_path: str, branch: str = None) -> Optional[str]:
        """
        从GitHub仓库获取指定文本文件内容
        :param repo: 仓库名称
        :param owner: 仓库所有者
        :param file_path: 文件路径(相对于仓库根目录)
        :param branch: 分支名称，默认为 None(使用默认分支)
        :return: 文件内容字符串，若获取失败则返回 None
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
        if branch:
            api_url = f"{api_url}?ref={branch}"
        response = RequestUtils(headers=settings.GITHUB_HEADERS).get_res(
            api_url,
            proxies=self._proxies
        )
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

    @cached(maxsize=1, ttl=6 * 3600)
    def __get_hash(self) -> Optional[dict]:
        """
        获取 IMDb hash
        """
        res = self.get_github_file(
            'MoviePilot-Plugins',
            'wumode',
            '/plugins.v2/imdbsource/imdb_hash.json',
            'imdbsource_assets'
        )
        if not res:
            logger.error("Error getting hash")
            return None
        try:
            hash_data = json.loads(res)
        except JSONDecodeError:
            return None
        return hash_data

    @cached(maxsize=1, ttl=6 * 3600)
    def __get_staff_picks(self) -> Optional[dict]:
        """
        获取 IMDb Staff Picks
        """
        res = self.get_github_file(
            'MoviePilot-Plugins',
            'wumode',
            '/plugins.v2/imdbsource/staff_picks.json',
            'imdbsource_assets'
        )
        if not res:
            logger.error("Error getting staff picks")
            return None
        try:
            json_data = json.loads(res)
        except JSONDecodeError:
            return None
        return json_data

    def __update_hash(self, force: bool = False) -> None:
        if force:
            self.__get_hash.cache_clear()
        imdb_hash = self.__get_hash()
        if imdb_hash:
            self._imdb_api_hash["AdvancedTitleSearch"] = imdb_hash.get("AdvancedTitleSearch")
            self._imdb_api_hash["TitleAkasPaginated"] = imdb_hash.get("TitleAkasPaginated")

    @staticmethod
    def __award_to_constraint(award: str) -> Optional[Dict]:
        pattern = r'^(ev\d+)(?:-(best\w+))?-(Winning|Nominated)$'
        match = re.match(pattern, award)
        constraint = {}
        if match:
            ev_id = match.group(1)  # 第一部分：evXXXXXXXX
            best = match.group(2)  # 第二部分：bestXX（可选）
            status = match.group(3)  # 第三部分：Winning/Nominated
            constraint["eventId"] = ev_id
            if status == "Winning":
                constraint["winnerFilter"] = "WINNER_ONLY"
            if best:
                constraint["searchAwardCategoryId"] = best
            return constraint
        else:
            return None

    @staticmethod
    def __ranked_list_to_constraint(ranked: str) -> Optional[Dict]:
        """
            "TOP_RATED_MOVIES-100": "IMDb Top 100",
            "TOP_RATED_MOVIES-250": "IMDb Top 250",
            "TOP_RATED_MOVIES-1000": "IMDb Top 1000",
            "LOWEST_RATED_MOVIES-100": "IMDb Bottom 100",
            "LOWEST_RATED_MOVIES-250": "IMDb Bottom 250",
            "LOWEST_RATED_MOVIES-1000": "IMDb Bottom 1000"
        """
        pattern = r'^(TOP_RATED_MOVIES|LOWEST_RATED_MOVIES)-(\d+)$'
        match = re.match(pattern, ranked)
        if match:
            ranked_title_list_type = match.group(1)
            rank_range = int(match.group(2))
            constraint = {"rankRange": {"max": rank_range}, "rankedTitleListType": ranked_title_list_type}
            return constraint
        return None

    def advanced_title_search(self,
                              first_page: bool = True,
                              title_types: Optional[Tuple[str, ...]] = None,
                              genres: Optional[Tuple[str, ...]] = None,
                              sort_by: str = 'POPULARITY',
                              sort_order: str = 'ASC',
                              rating_min: Optional[float] = None,
                              rating_max: Optional[float] = None,
                              countries: Optional[Tuple[str, ...]] = None,
                              languages: Optional[Tuple[str, ...]] = None,
                              release_date_end: Optional[str] = None,
                              release_date_start: Optional[str] = None,
                              award_constraint: Optional[Tuple[str, ...]] = None,
                              ranked: Optional[Tuple[str, ...]] = None,
                              interests: Optional[Tuple[str, ...]] = None
                              )->Optional[Dict]:
        # 创建参数对象
        params = SearchParams(
            title_types=title_types,
            genres=genres,
            sort_by=sort_by,
            sort_order=sort_order,
            rating_min=rating_min,
            rating_max=rating_max,
            countries=countries,
            languages=languages,
            release_date_end=release_date_end,
            release_date_start=release_date_start,
            award_constraint=award_constraint,
            ranked=ranked,
            interests=interests
        )
        sha256 = '81b46290a78cc1e8b3d713e6a43c191c55b4dccf3e1945d6b46668945846d832'
        self.__update_hash()
        if self._imdb_api_hash.get("AdvancedTitleSearch"):
            sha256 = self._imdb_api_hash["AdvancedTitleSearch"]
        # 获取或创建搜索状态
        last_cursor = None
        if not first_page and params in self._search_states:
            search_state: SearchState = self._search_states.pop(params)  # 移除并获取
            self._search_states[params] = search_state
            # 不是第一页且已有状态 - 使用上次的结果
            if not search_state.pageinfo.get("hasNextPage"):
                return {'pageInfo': {'endCursor': None, 'hasNextPage': False, 'hasPreviousPage': True,
                                     'startCursor': None},
                        'edges': [], 'total': search_state.total, 'genres': [], 'keywords': [],
                        'titleTypes': [], 'jobCategories': []}
            if search_state.pageinfo.get('endCursor'):
                last_cursor = search_state.pageinfo.get('endCursor')
                # 实现基于上次结果的逻辑
            else:
                # 重新搜索
                first_page = True
        else:
            first_page = True
        result = self.__advanced_title_search(params, sha256, first_page, last_cursor)
        if result:
            page_info = result.get("pageInfo", {})
            total = result.get("total", 0)
            search_state = SearchState(page_info, total)
            self._search_states[params] = search_state
        if len(self._search_states) > self._max_states:
            self._search_states.popitem(last=False)  # 移除最旧的条目
        return result

    def __advanced_title_search(self,
                                params: SearchParams,
                                sha256: str,
                                first_page: bool = True,
                                last_cursor: Optional[str] = None,
                                ) -> Optional[Dict]:

        variables: Dict[str, Any] = {"first": 50,
                     "locale": "en-US",
                     "sortBy": params.sort_by,
                     "sortOrder": params.sort_order,
                     }
        operation_name = 'AdvancedTitleSearch'
        if params.title_types:
            title_type_ids = []
            for title_type in params.title_types:
                if title_type in self.all_title_types:
                    title_type_ids.append(title_type)
            if len(title_type_ids):
                variables["titleTypeConstraint"] = {"anyTitleTypeIds": params.title_types,
                                                    "excludeTitleTypeIds": []}
        if params.genres:
            variables["genreConstraint"] = {"allGenreIds": params.genres, "excludeGenreIds": []}
        if params.countries:
            variables["originCountryConstraint"] = {"allCountries": params.countries}
        if params.languages:
            variables["languageConstraint"] = {"anyPrimaryLanguages": params.languages}
        if params.rating_min or params.rating_max:
            rating_min = params.rating_min if params.rating_min else 1
            rating_min = max(rating_min, 1)
            rating_max = params.rating_max if params.rating_max else 10
            rating_max = min(rating_max, 10)
            variables["userRatingsConstraint"] = {"aggregateRatingRange": {"max": rating_max, "min": rating_min}}
        if params.release_date_start or params.release_date_end:
            release_dict = {}
            if params.release_date_start:
                release_dict["start"] = params.release_date_start
            if params.release_date_end:
                release_dict["end"] = params.release_date_end
            variables["releaseDateConstraint"] = {"releaseDateRange": release_dict}
        if params.award_constraint:
            constraints = []
            for award in params.award_constraint:
                c = self.__award_to_constraint(award)
                if c:
                    constraints.append(c)
            variables["awardConstraint"] = {"allEventNominations": constraints}
        if params.ranked:
            constraints = []
            for r in params.ranked:
                c = self.__ranked_list_to_constraint(r)
                if c:
                    constraints.append(c)
            variables["rankedTitleListConstraint"] = {"allRankedTitleLists": constraints,
                                                      "excludeRankedTitleLists": []}
        if params.interests:
            constraints = []
            for interest in params.interests:
                in_id = self.interest_id.get(interest)
                if in_id:
                    constraints.append(in_id)
            variables["interestConstraint"] = {"allInterestIds": constraints, "excludeInterestIds": []}
        if not first_page and last_cursor:
            variables["after"] = last_cursor

        params = {"operationName": operation_name,
                  "variables": variables}
        data = self.__request(params, sha256)
        if not data:
            return None
        if 'error' in data:
            error = data['error']
            if error:
                logger.error(f"Error querying {operation_name}: {error.get('message')}")
                if error.get('message') == 'PersistedQueryNotFound':
                    self.hash_status[operation_name] = False
            return None
        self.hash_status[operation_name] = True
        return data.get('advancedTitleSearch')

    def staff_picks(self) -> Optional[List[Dict[str, Any]]]:
        """
        {
            'name': 'Jurassic World Rebirth',
            'editor': 'SWG',
            'complete': 'TRUE',
            'ttconst': 'tt31036941',
            'rmconst': 'rm1150392066',
            'imagealign': 'center top',
            'detail': 'In theaters Wednesday, July 2',
            'description': '',
            'viconst': 'vi3122317593',
            'relatedconst': ['nm0424060', 'nm0991810']
        }
        """
        return self.__get_staff_picks().get('entries')

    def vertical_list_page_items(self,
                                 titles: Optional[List[str]] = None,
                                 names: Optional[List[str]] = None,
                                 images: Optional[List[str]] = None,
                                 videos: Optional[List[str]] = None,
                                 is_registered: bool = False
                                 ) -> Optional[Dict[str, Any]]:
        """
        {
            'titles': [
                {
                    'id': 'tt31036941',
                    'titleText': {
                        'text': 'Jurassic World: Rebirth'
                    },
                    'titleType': {'id': 'movie'},
                    'releaseYear': {'year': 2025},
                    'primaryImage': {
                        'id': 'rm3920935426',
                        'url': '',
                        'width': 1257,
                        'height': 1800
                    },
                    'meterRanking': {
                        'currentRank': 8,
                        'meterType': 'MOVIE_METER',
                        'rankChange': {
                            'changeDirection': 'UP',
                            'difference': 15
                        }
                    },
                    'ratingsSummary': {'aggregateRating': 6.5}},
            ],
            'images': [
                {
                    'id': 'rm1150392066',
                    'height': 5504,
                    'width': 8256,
                    'url': ''
                },
            ]
            'names': [
                {
                    'id': 'nm0424060',
                    'nameText': {'text': 'Scarlett Johansson'},
                    'primaryImage': {
                        'id': 'rm1916122112',
                        'url': '',
                        'width': 1689,
                        'height': 2048
                    }
                },
            ]
        }
        """
        query = "query VerticalListPageItems( $titles: [ID!]! $names: [ID!]! $images: [ID!]! $videos: [ID!]! ) {\n        titles(ids: $titles) { ...TitleParts meterRanking { currentRank meterType rankChange {changeDirection difference} } ratingsSummary { aggregateRating } }\n        names(ids: $names) { ...NameParts }\n        videos(ids: $videos) { ...VideoParts }\n        images(ids: $images) { ...ImageParts }\n      }\n      fragment TitleParts on Title {\n    id\n    titleText { text }\n    titleType { id }\n    releaseYear { year }\n    plot { plotText {plainText}}\n    primaryImage { id url width height }\n}\n      fragment NameParts on Name {\n    id\n    nameText { text }\n    primaryImage { id url width height }\n}\n      fragment ImageParts on Image {\n    id\n    height\n    width\n    url \n}\n      fragment VideoParts on Video {\n    id\n    name { value }\n    contentType { displayName { value } id }\n    previewURLs { displayName { value } url videoDefinition videoMimeType }\n    playbackURLs { displayName { value } url videoDefinition videoMimeType }\n    thumbnail { height url width }\n}\n    "
        variables = {'images': images or [],
                     'titles': titles or [],
                     'names': names or [],
                     'videos': videos or [],
                     'isRegistered': is_registered,
                     }
        data = self.__query_graphql(query, variables)
        if 'error' in data:
            error = data['error']
            if error:
                logger.error(f"Error querying VerticalListPageItems: {error}")
            return None
        return data

