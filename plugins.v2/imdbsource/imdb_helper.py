import re
from typing import Optional, Any, Dict, Tuple
from collections import OrderedDict
from dataclasses import dataclass

import requests

from app.log import logger
from app.utils.http import RequestUtils
from app.utils.common import retry
from app.schemas.types import MediaType
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
    _query_by_id = """query queryWithVariables($id: ID!) {
  title(id: $id) {
    id
    type
    is_adult
    primary_title
    original_title
    start_year
    end_year
    runtime_minutes
    plot
    rating {
      aggregate_rating
      votes_count
    }
    genres
    posters {
      url
      width
      height
    }
    certificates {
      country {
        code
        name
      }
      rating
    }
    spoken_languages {
      code
      name
    }
    origin_countries {
      code
      name
    }
    critic_review {
      score
      review_count
    }
    directors: credits(first: 5, categories: ["director"]) {
      name {
        id
        display_name
        avatars {
          url
          width
          height
        }
      }
    }
    writers: credits(first: 5, categories: ["writer"]) {
      name {
        id
        display_name
        avatars {
          url
          width
          height
        }
      }
    }
    casts: credits(first: 5, categories: ["actor", "actress"]) {
      name {
        id
        display_name
        avatars {
          url
          width
          height
        }
      }
      characters
    }
  }
}"""
    _endpoint = "https://graph.imdbapi.dev/v1"
    _search_endpoint = "https://v3.sg.media-imdb.com/suggestion/x/%s.json?includeVideos=0"
    _official_endpoint = "https://caching.graphql.imdb.com/"
    _hash_update_url = ("https://raw.githubusercontent.com/wumode/MoviePilot-Plugins/"
                        "refs/heads/imdbsource_assets/plugins.v2/imdbsource/imdb_hash.json")
    _qid_map = {
        MediaType.TV: ["tvSeries", "tvMiniSeries", "tvShort", "tvEpisode"],
        MediaType.MOVIE: ["movie"]
    }

    _imdb_headers = {
        "Accept": "application/json, text/plain, */*",
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

    def imdbid(self, imdbid: str) -> Optional[Dict]:
        params = {"operationName": "queryWithVariables", "query": self._query_by_id, "variables": {"id": imdbid}}
        ret = RequestUtils(
            accept_type="application/json", content_type="application/json"
        ).post_res(f"{self._endpoint}", json=params)
        if not ret:
            return None
        data = ret.json()
        if "errors" in data:
            logger.error(f"Imdb query ({imdbid}) errors {data.get('errors')}")
            logger.error(f"{params}")
            return None
        info = data.get("data").get("title", None)
        return info

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

    @cached(maxsize=1, ttl=6 * 3600)
    def __get_hash(self) -> Optional[dict]:
        """
        根据IMDb hash使用
        """
        headers = {
            "Accept": "text/html",
        }
        res = RequestUtils(headers=headers).get_res(
            self._hash_update_url,
            proxies=self._proxies
        )
        if not res:
            logger.error("Error getting hash")
            return None
        return res.json()

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
