import re
from json import JSONDecodeError
from typing import Optional, Any, Dict, Tuple, List, Union
from collections import OrderedDict
from dataclasses import dataclass
import json
import base64

import requests

from app.core.config import settings
from app.log import logger
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.utils.common import retry
from app.core.cache import cached
from app.schemas.types import MediaType


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

    all_title_types = ["tvSeries", "tvMiniSeries", "movie", "tvMovie", "musicVideo", "tvShort", "short",
                       "tvEpisode", "tvSpecial"]
    interests = {'Action': {'Action': 'in0000001', 'Action Epic': 'in0000002', 'B-Action': 'in0000003', 'Car Action': 'in0000004', 'Disaster': 'in0000005', 'Gun Fu': 'in0000197', 'Kung Fu': 'in0000198', 'Martial Arts': 'in0000006', 'One-Person Army Action': 'in0000007', 'Samurai': 'in0000199', 'Superhero': 'in0000008', 'Sword & Sandal': 'in0000009', 'War': 'in0000010', 'War Epic': 'in0000011', 'Wuxia': 'in0000200'}, 'Adventure': {'Adventure': 'in0000012', 'Adventure Epic': 'in0000015', 'Desert Adventure': 'in0000013', 'Dinosaur Adventure': 'in0000014', 'Globetrotting Adventure': 'in0000016', 'Jungle Adventure': 'in0000017', 'Mountain Adventure': 'in0000018', 'Quest': 'in0000019', 'Road Trip': 'in0000020', 'Sea Adventure': 'in0000021', 'Swashbuckler': 'in0000022', 'Teen Adventure': 'in0000023', 'Urban Adventure': 'in0000024'}, 'Animation': {'Adult Animation': 'in0000025', 'Animation': 'in0000026', 'Computer Animation': 'in0000028', 'Hand-Drawn Animation': 'in0000029', 'Stop Motion Animation': 'in0000030'}, 'Anime': {'Anime': 'in0000027', 'Isekai': 'in0000201', 'Iyashikei': 'in0000202', 'Josei': 'in0000203', 'Mecha': 'in0000204', 'Seinen': 'in0000205', 'Shōjo': 'in0000207', 'Shōnen': 'in0000206', 'Slice of Life': 'in0000208'}, 'Comedy': {'Body Swap Comedy': 'in0000031', 'Buddy Comedy': 'in0000032', 'Buddy Cop': 'in0000033', 'Comedy': 'in0000034', 'Dark Comedy': 'in0000035', 'Farce': 'in0000036', 'High-Concept Comedy': 'in0000037', 'Mockumentary': 'in0000038', 'Parody': 'in0000039', 'Quirky Comedy': 'in0000040', 'Raunchy Comedy': 'in0000041', 'Satire': 'in0000042', 'Screwball Comedy': 'in0000043', 'Sitcom': 'in0000044', 'Sketch Comedy': 'in0000045', 'Slapstick': 'in0000046', 'Stand-Up': 'in0000047', 'Stoner Comedy': 'in0000048', 'Teen Comedy': 'in0000049'}, 'Crime': {'Caper': 'in0000050', 'Cop Drama': 'in0000051', 'Crime': 'in0000052', 'Drug Crime': 'in0000053', 'Film Noir': 'in0000054', 'Gangster': 'in0000055', 'Heist': 'in0000056', 'Police Procedural': 'in0000057', 'True Crime': 'in0000058'}, 'Documentary': {'Crime Documentary': 'in0000059', 'Documentary': 'in0000060', 'Docuseries': 'in0000061', 'Faith & Spirituality Documentary': 'in0000062', 'Food Documentary': 'in0000063', 'History Documentary': 'in0000064', 'Military Documentary': 'in0000065', 'Music Documentary': 'in0000066', 'Nature Documentary': 'in0000067', 'Political Documentary': 'in0000068', 'Science & Technology Documentary': 'in0000069', 'Sports Documentary': 'in0000070', 'Travel Documentary': 'in0000071'}, 'Drama': {'Biography': 'in0000072', 'Coming-of-Age': 'in0000073', 'Costume Drama': 'in0000074', 'Docudrama': 'in0000075', 'Drama': 'in0000076', 'Epic': 'in0000077', 'Financial Drama': 'in0000078', 'Historical Epic': 'in0000079', 'History': 'in0000080', 'Korean Drama': 'in0000209', 'Legal Drama': 'in0000081', 'Medical Drama': 'in0000082', 'Period Drama': 'in0000083', 'Political Drama': 'in0000084', 'Prison Drama': 'in0000085', 'Psychological Drama': 'in0000086', 'Showbiz Drama': 'in0000087', 'Soap Opera': 'in0000088', 'Teen Drama': 'in0000089', 'Telenovela': 'in0000210', 'Tragedy': 'in0000090', 'Workplace Drama': 'in0000091'}, 'Family': {'Animal Adventure': 'in0000092', 'Family': 'in0000093'}, 'Fantasy': {'Dark Fantasy': 'in0000095', 'Fairy Tale': 'in0000097', 'Fantasy': 'in0000098', 'Fantasy Epic': 'in0000096', 'Supernatural Fantasy': 'in0000099', 'Sword & Sorcery': 'in0000100', 'Teen Fantasy': 'in0000101'}, 'Game Show': {'Beauty Competition': 'in0000102', 'Cooking Competition': 'in0000103', 'Game Show': 'in0000105', 'Quiz Show': 'in0000104', 'Survival Competition': 'in0000106', 'Talent Competition': 'in0000107'}, 'Horror': {'B-Horror': 'in0000108', 'Body Horror': 'in0000109', 'Folk Horror': 'in0000110', 'Found Footage Horror': 'in0000111', 'Horror': 'in0000112', 'Monster Horror': 'in0000113', 'Psychological Horror': 'in0000114', 'Slasher Horror': 'in0000115', 'Splatter Horror': 'in0000116', 'Supernatural Horror': 'in0000117', 'Teen Horror': 'in0000118', 'Vampire Horror': 'in0000119', 'Werewolf Horror': 'in0000120', 'Witch Horror': 'in0000121', 'Zombie Horror': 'in0000122'}, 'Lifestyle': {'Beauty Makeover': 'in0000123', 'Cooking & Food': 'in0000124', 'Home Improvement': 'in0000125', 'Lifestyle': 'in0000126', 'News': 'in0000211', 'Talk Show': 'in0000127', 'Travel': 'in0000128'}, 'Music': {'Concert': 'in0000129', 'Music': 'in0000130'}, 'Musical': {'Classic Musical': 'in0000131', 'Jukebox Musical': 'in0000132', 'Musical': 'in0000133', 'Pop Musical': 'in0000134', 'Rock Musical': 'in0000135'}, 'Mystery': {'Bumbling Detective': 'in0000136', 'Cozy Mystery': 'in0000137', 'Hard-boiled Detective': 'in0000138', 'Mystery': 'in0000139', 'Suspense Mystery': 'in0000140', 'Whodunnit': 'in0000141'}, 'Reality TV': {'Business Reality TV': 'in0000142', 'Crime Reality TV': 'in0000143', 'Dating Reality TV': 'in0000144', 'Docusoap Reality TV': 'in0000145', 'Hidden Camera': 'in0000146', 'Paranormal Reality TV': 'in0000147', 'Reality TV': 'in0000148'}, 'Romance': {'Dark Romance': 'in0000149', 'Feel-Good Romance': 'in0000151', 'Romance': 'in0000152', 'Romantic Comedy': 'in0000153', 'Romantic Epic': 'in0000150', 'Steamy Romance': 'in0000154', 'Teen Romance': 'in0000155', 'Tragic Romance': 'in0000156'}, 'Sci-Fi': {'Alien Invasion': 'in0000157', 'Artificial Intelligence': 'in0000158', 'Cyberpunk': 'in0000159', 'Dystopian Sci-Fi': 'in0000160', 'Kaiju': 'in0000161', 'Sci-Fi': 'in0000162', 'Sci-Fi Epic': 'in0000163', 'Space Sci-Fi': 'in0000164', 'Steampunk': 'in0000165', 'Time Travel': 'in0000166'}, 'Seasonal': {'Holiday': 'in0000192', 'Holiday Animation': 'in0000193', 'Holiday Comedy': 'in0000194', 'Holiday Family': 'in0000195', 'Holiday Romance': 'in0000196'}, 'Short': {'Short': 'in0000212'}, 'Sport': {'Baseball': 'in0000167', 'Basketball': 'in0000168', 'Boxing': 'in0000169', 'Extreme Sport': 'in0000170', 'Football': 'in0000171', 'Motorsport': 'in0000172', 'Soccer': 'in0000173', 'Sport': 'in0000174', 'Water Sport': 'in0000175'}, 'Thriller': {'Conspiracy Thriller': 'in0000176', 'Cyber Thriller': 'in0000177', 'Erotic Thriller': 'in0000178', 'Giallo': 'in0000179', 'Legal Thriller': 'in0000180', 'Political Thriller': 'in0000181', 'Psychological Thriller': 'in0000182', 'Serial Killer': 'in0000183', 'Spy': 'in0000184', 'Survival': 'in0000185', 'Thriller': 'in0000186'}, 'Western': {'Classical Western': 'in0000187', 'Contemporary Western': 'in0000188', 'Spaghetti Western': 'in0000190', 'Western': 'in0000191', 'Western Epic': 'in0000189'}}
    _official_endpoint = "https://caching.graphql.imdb.com/"
    _imdb_headers = {
        "Accept": "text/html,application/json,text/plain,*/*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Referer": "https://www.imdb.com/",
    }
    _free_api = "https://api.imdbapi.dev"

    def __init__(self, proxies=None):
        self._proxies = proxies
        self._imdb_req = RequestUtils(accept_type="application/json",
                                      content_type="application/json",
                                      headers=self._imdb_headers,
                                      timeout=10,
                                      proxies=proxies,
                                      session=requests.Session())
        self._free_imdb_req = RequestUtils(accept_type="application/json", proxies=proxies, session=requests.Session())
        self._imdb_api_hash = {"AdvancedTitleSearch": None, "TitleAkasPaginated": None}
        self.hash_status = {"AdvancedTitleSearch": False, "TitleAkasPaginated": False}
        self._search_states = OrderedDict()
        self._max_states = 30
        self.interest_id = {}
        for category, value in self.interests.items():
            for name, in_id in value.items():
                self.interest_id[name] = in_id

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
            'plugins.v2/imdbsource/imdb_hash.json',
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
            'plugins.v2/imdbsource/staff_picks.json',
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

    @staticmethod
    def compare_names(file_name: str, names: Union[list,str]) -> bool:
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
    def release_date_string(release_date: Dict) -> Optional[str]:
        year = release_date.get('year') or 0
        month = release_date.get('month') or 0
        day = release_date.get('day') or 0
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
        return (self.__get_staff_picks() or {}).get('entries')

    @cached(maxsize=128, ttl=3600)
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
                    'akas': {'edges': [{'node': {'text': 'Kite Festival of Love', 'country': None, 'language': None}}]}
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
        query = "query VerticalListPageItems( $titles: [ID!]! $names: [ID!]! $images: [ID!]! $videos: [ID!]!) {\n  titles(ids: $titles) { ...TitleParts meterRanking { currentRank meterType rankChange {changeDirection difference} } ratingsSummary { aggregateRating } }\n  names(ids: $names) { ...NameParts }\n  videos(ids: $videos) { ...VideoParts }\n  images(ids: $images) { ...ImageParts }\n}\nfragment TitleParts on Title {\n  id\n  titleText { text }\n  titleType { id }\n  releaseYear { year }\n  akas(first: 50) { edges { node { text country { id text } language { text text } } } }\n  plot { plotText {plainText}}\n  primaryImage { id url width height }\n}\nfragment NameParts on Name {\n  id\n  nameText { text }\n  primaryImage { id url width height }\n}\nfragment ImageParts on Image {\n  id\n  height\n  width\n  url\n}\nfragment VideoParts on Video {\n  id\n  name { value }\n  contentType { displayName { value } id }\n  previewURLs { displayName { value } url videoDefinition videoMimeType }\n  playbackURLs { displayName { value } url videoDefinition videoMimeType }\n  thumbnail { height url width }\n}"
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

    @retry(Exception, logger=logger)
    @cached(ttl=6 * 3600)
    def __free_imdb_api(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        r = self._free_imdb_req.get_res(url=f"{self._free_api}{path}", params=params, raise_exception=True)
        if r is None:
            return None
        if r.status_code != 200:
            try:
                logger.warn(f"{r.json().get('message')}")
            except requests.exceptions.JSONDecodeError:
                return None
            return None
        return r.json()

    def advanced_search(self, query: str, media_types: Optional[List[str]] = None, start_year: Optional[int] = None,
               end_year: Optional[int] = None, country_code: Optional[str] = None) -> Optional[list]:
        """
        Perform an advanced search for titles using a query string with additional filters.
        :param query: The search query for titles.
        :param media_types: The type of titles to filter by.
            MOVIE: Represents a movie title.
            TV_SERIES: Represents a TV series title.
            TV_MINI_SERIES: Represents a TV mini-series title.
            TV_SPECIAL: Represents a TV special title.
            TV_MOVIE: Represents a TV movie title.
            SHORT: Represents a short title.
            VIDEO: Represents a video title.
        :param start_year: The start year for filtering titles.
        :param end_year: The end year for filtering titles.
        :param country_code: The country code for filtering titles.
        :return: Search results.
        See `curl -X 'GET' 'https://api.imdbapi.dev/search/titles?query=Kite' -H 'accept: application/json'`
        """
        endpoint = '/advancedSearch/titles'
        params: Dict[str, Any] = {'query': query}
        if media_types:
            params['types'] = media_types
        if start_year:
            params['startYear'] = start_year
        if end_year:
            params['endYear'] = end_year
        if country_code:
            params['countryCode'] = country_code
        r = self.__free_imdb_api(path=endpoint, params=params)
        if r is None:
            return None
        return r.get('titles')

    def details(self, title_id: str) -> Optional[dict]:
        """
        Retrieve a title's details using its IMDb ID.
        :param title_id: IMDb title ID in the format "tt1234567".
        :return: Details.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947' -H 'accept: application/json'`
        """
        endpoint = '/titles/%s'
        r = self.__free_imdb_api(path=endpoint % title_id)
        return r

    def episodes(self, title_id: str, season: Optional[str]=None,
                 page_size: Optional[int] = None, page_token: Optional[str] = None) -> Optional[dict]:
        """
        Retrieve the episodes associated with a specific title.
        :param title_id: IMDb title ID in the format "tt1234567".
        :param season: The season number to filter episodes by.
        :param page_size: The maximum number of episodes to return per page.
            The value must be between 1 and 50. Default is 20.
        :param page_token: Token for pagination, if applicable.
        :return: Episodes.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947/episodes?season=1&pageSize=5' \
            -H 'accept: application/json'`
        """
        endpoint = '/titles/%s/episodes'
        param: Dict[str, Any] = {}
        if season is not None:
            param['season'] = season
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        r = self.__free_imdb_api(path=endpoint % title_id, params=param)
        return r

    def seasons(self, title_id: str) -> Optional[List[dict]]:
        """
        Retrieve the seasons associated with a specific title.
        :param title_id: IMDb title ID in the format "tt1234567".
        :return: Seasons.
        """
        """
        {[{"season": "1",  "episodeCount": 11}]}
        """
        endpoint = '/titles/%s/seasons'
        r = self.__free_imdb_api(path=endpoint % title_id)
        if r is None:
            return None
        return r.get('seasons')

    def credits(self, title_id: str, categories: Optional[List[str]] = None,
                page_size: Optional[int] = None, page_token: Optional[str] = None) -> Optional[dict]:
        """
        Retrieve the credits associated with a specific title.
        :param title_id: IMDb title ID in the format "tt1234567".
        :param categories: The categories to filter credits by.
            DIRECTOR: The director category.
            WRITER: The writer category.
            CAST: The cast category, which includes all actors and actresses.
            ACTOR: The actor category.
            ACTRESS: The actress category.
        :param page_size: The maximum number of episodes to return per page.
            The value must be between 1 and 50. Default is 20.
        :param page_token: Token for pagination, if applicable.
        :return: Credits.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947/credits?categories=CAST' \
            -H 'accept: application/json'`
        """
        endpoint = '/titles/%s/credits'
        param: Dict[str, Any] = {}
        if categories:
            param['categories'] = categories
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        r = self.__free_imdb_api(path=endpoint % title_id, params=param) or {}
        return r.get('credits')

    def akas(self, title_id: str) -> Optional[list]:
        """
        Retrieve the alternative titles (AKAs) associated with a specific title.
        :param title_id: IMDb title ID in the format "tt1234567".
        :return: AKAs.
        [{
            "text": "Kite Festival of Love",
            "country": {
                "code": "CA",
                "name": "Canada"
            },
            "language": {
                "code": "fra",
                "name": "French"
            }
        },]
        """
        endpoint = '/titles/%s/akas'
        r = self.__free_imdb_api(path=endpoint % title_id)
        if r is None:
            return None
        return r.get('akas')

    def __get_tv_seasons(self, title_id: str) -> Optional[dict]:
        seasons = self.seasons(title_id)
        if not seasons:
            return None
        seasons_dict = {season.get('season'): {**season, 'episode_count': 0, 'air_date': '0000-00-00'}
                        for season in seasons}
        page_token = None
        while True:
            episodes = self.episodes(title_id, page_size=50, page_token=page_token) or {}
            for episode in episodes.get('episodes', []):
                s = episode.get('season')
                seasons_dict[s]['episode_count'] += 1
                if not seasons_dict[s].get('release_date'):
                    seasons_dict[s]['air_date'] = ImdbHelper.release_date_string(episode.get('releaseDate', {}))
                    seasons_dict[s]['release_date'] = episode.get('releaseDate')
            page_token = episodes.get('nextPageToken')
            if not page_token:
                break
        return seasons_dict

    def match_by(self, name: str, mtype: Optional[MediaType] = None, year: Optional[str] = None) -> Optional[dict]:
        """
        根据名称同时查询电影和电视剧，没有类型也没有年份时使用
        :param name: 识别的文件名或种子名
        :param mtype: 类型：电影、电视剧
        :param year: 年份，如要是季集需要是首播年份
        :return: 匹配的媒体信息
        """

        mtypes = [MediaType.MOVIE, MediaType.TV] if not mtype else [mtype]
        search_types = []
        if MediaType.TV in mtypes:
            search_types.extend(['TV_SERIES', 'TV_MINI_SERIES', 'TV_SPECIAL'])
        if MediaType.MOVIE in mtypes:
            search_types.extend(['MOVIE', 'TV_MOVIE'])
        if year:
            multi_res = self.advanced_search(query=name, start_year=int(year), end_year=int(year), media_types=search_types)
        else:
            multi_res = self.advanced_search(query=name, media_types=search_types)
        ret_info = {}
        if multi_res is None or len(multi_res) == 0:
            logger.debug(f"{name} 未找到相关媒体息!")
            return None
        multi_res = [r for r in multi_res if r.get('id') and ImdbHelper.type_to_mtype(r.get('type')) in mtypes]
        multi_res = sorted(
            multi_res,
            key=lambda x: ('1' if x.get('type') in ['movie', 'tvMovie'] else '0') + (f"{x.get('startYear')}" or '0000'),
            reverse=True
        )
        items = self.vertical_list_page_items([ x.get('id') for x in multi_res])
        titles = items.get('titles') if items else []
        titles_dict = {}
        for title in titles:
            titles_dict[title.get('id')] = title
        for result in multi_res:
            title = titles_dict.get(result.get('id'), {})
            start_year = result.get('startYear')
            if year and str(start_year) != year:
                continue
            if ImdbHelper.compare_names(name, [result.get('primaryTitle', ''), result.get('originalTitle', '')]):
                ret_info = result
                break
            names = [edge.get('node', {}).get('text', '') for edge in title.get('akas', {}).get('edges', [])]
            if ImdbHelper.compare_names(name, names):
                ret_info = result
                break
        if ret_info:
            title = titles_dict.get(ret_info.get('id'), {})
            ret_info['akas'] = [e.get('node', {}) for e in title.get('akas', {}).get('edges', [])]
            ret_info['rating'] = title.get('ratingsSummary') or {}
            ret_info['media_type'] = ImdbHelper.type_to_mtype(ret_info.get('type'))
        return ret_info

    def match_by_season(self, name: str, season_year: str, season_number: int) -> Optional[dict]:
        """
        根据电视剧的名称和季的年份及序号匹配 IMDb
        :param name: 识别的文件名或者种子名
        :param season_year: 季的年份
        :param season_number: 季序号
        :return: 匹配的媒体信息
        """

        def __season_match(_tv_info: dict, _season_year: str) -> bool:
            if not _tv_info:
                return False
            seasons = self.__get_tv_seasons(_tv_info.get('id')) or {}
            for season, season_info in seasons.items():
                if season_info.get("air_date"):
                    if season_info.get("air_date")[0:4] == str(_season_year) \
                            and season == str(season_number):
                        _tv_info['seasons'] = seasons
                        return True
            return False

        search_types = ['TV_SERIES', 'TV_MINI_SERIES', 'TV_SPECIAL']
        res = self.advanced_search(query=name, media_types=search_types)
        if not res:
            logger.debug(f"{name} 未找到季{season_number}相关信息!")
            return None
        tvs =  [r for r in res if r.get('id') and ImdbHelper.type_to_mtype(r.get('type')) == MediaType.TV]
        tvs = sorted(tvs, key=lambda x: x.get('startYear') or 0, reverse=True)
        items = self.vertical_list_page_items([x.get('id') for x in tvs])
        titles = items.get('titles') if items else []
        titles_dict = {}
        for title in titles:
            titles_dict[title.get('id')] = title
        for tv in tvs:
            # 年份
            title = titles_dict.get(tv.get('id'), {})
            akas = [e.get('node', {}) for e in title.get('akas', {}).get('edges', [])]
            tv_year = tv.get('startYear')
            if self.compare_names(name, [tv.get('primaryTitle', ''), tv.get('originalTitle', '')]) and \
                    str(tv_year) == season_year:
                tv['akas'] = akas
                tv['rating'] = title.get('ratingsSummary') or {}
                return tv
            names = [aka.get('text', '') for aka in akas]
            if not tv or not self.compare_names(name, names):
                continue
            if __season_match(_tv_info=tv, _season_year=season_year):
                tv['akas'] = akas
                tv['rating'] = title.get('ratingsSummary') or {}
                return tv
        return None

    def match(self, name: str,
              mtype: MediaType,
              year: Optional[str] = None,
              season_year: Optional[str] = None,
              season_number: Optional[int] = None,
              ) -> Optional[dict]:
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
        info = {}
        if mtype == MediaType.TV:
            # 有当前季和当前季集年份，使用精确匹配
            if season_year and season_number:
                logger.debug(f"正在识别{mtype.value}：{name}, 季集={season_number}, 季集年份={season_year} ...")
                info = self.match_by_season(name, season_year, season_number)
                if info:
                    info['media_type'] = MediaType.TV
                    return info
        year_range = [year, str(int(year) + 1), str(int(year) - 1)] if year else [None]
        for year in year_range:
            logger.debug(f"正在识别{mtype.value}：{name}, 年份={year} ...")
            info = self.match_by(name, mtype, year)
            if info:
                break
        return info

    def update_info(self, title_id: str, info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Given a Title ID, update its media information.
        :param title_id: IMDb ID.
        :param info: Media information to be updated.
        :return: IMDb info.
        """
        details = self.details(title_id) or {}
        info = info or {}
        info.update(details)
        if info.get("akas") is None:
            info['akas'] = self.akas(title_id) or []
        info['credits'] = self.credits(title_id, page_size=30)
        if info.get('media_type') == MediaType.TV and info.get('seasons') is None:
            info['seasons'] = self.__get_tv_seasons(info.get('id')) or {}
        return info