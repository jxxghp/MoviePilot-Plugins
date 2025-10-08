import re
from typing import Any, Dict, List, Optional, Final, AsyncGenerator

import httpx
import requests
from pydantic import ValidationError

from app.core.cache import cached
from app.log import logger
from app.utils.common import retry
from app.utils.http import RequestUtils, AsyncRequestUtils

from .schema.imdbtypes import ImdbType
from .schema import VerticalList, AdvancedTitleSearchResponse, AdvancedTitleSearch, TitleEdge, SearchParams


INTERESTS_ID: Final[Dict[str, Dict[str, str]]] = {
    "Action": {
        "Action": "in0000001",
        "Action Epic": "in0000002",
        "B-Action": "in0000003",
        "Car Action": "in0000004",
        "Disaster": "in0000005",
        "Gun Fu": "in0000197",
        "Kung Fu": "in0000198",
        "Martial Arts": "in0000006",
        "One-Person Army Action": "in0000007",
        "Samurai": "in0000199",
        "Superhero": "in0000008",
        "Sword & Sandal": "in0000009",
        "War": "in0000010",
        "War Epic": "in0000011",
        "Wuxia": "in0000200"
    },
    "Adventure": {
        "Adventure": "in0000012",
        "Adventure Epic": "in0000015",
        "Desert Adventure": "in0000013",
        "Dinosaur Adventure": "in0000014",
        "Globetrotting Adventure": "in0000016",
        "Jungle Adventure": "in0000017",
        "Mountain Adventure": "in0000018",
        "Quest": "in0000019",
        "Road Trip": "in0000020",
        "Sea Adventure": "in0000021",
        "Swashbuckler": "in0000022",
        "Teen Adventure": "in0000023",
        "Urban Adventure": "in0000024"
    },
    "Animation": {
        "Adult Animation": "in0000025",
        "Animation": "in0000026",
        "Computer Animation": "in0000028",
        "Hand-Drawn Animation": "in0000029",
        "Stop Motion Animation": "in0000030"
    },
    "Anime": {
        "Anime": "in0000027",
        "Isekai": "in0000201",
        "Iyashikei": "in0000202",
        "Josei": "in0000203",
        "Mecha": "in0000204",
        "Seinen": "in0000205",
        "Shōjo": "in0000207",
        "Shōnen": "in0000206",
        "Slice of Life": "in0000208"
    },
    "Comedy": {
        "Body Swap Comedy": "in0000031",
        "Buddy Comedy": "in0000032",
        "Buddy Cop": "in0000033",
        "Comedy": "in0000034",
        "Dark Comedy": "in0000035",
        "Farce": "in0000036",
        "High-Concept Comedy": "in0000037",
        "Mockumentary": "in0000038",
        "Parody": "in0000039",
        "Quirky Comedy": "in0000040",
        "Raunchy Comedy": "in0000041",
        "Satire": "in0000042",
        "Screwball Comedy": "in0000043",
        "Sitcom": "in0000044",
        "Sketch Comedy": "in0000045",
        "Slapstick": "in0000046",
        "Stand-Up": "in0000047",
        "Stoner Comedy": "in0000048",
        "Teen Comedy": "in0000049"
    },
    "Crime": {
        "Caper": "in0000050",
        "Cop Drama": "in0000051",
        "Crime": "in0000052",
        "Drug Crime": "in0000053",
        "Film Noir": "in0000054",
        "Gangster": "in0000055",
        "Heist": "in0000056",
        "Police Procedural": "in0000057",
        "True Crime": "in0000058"
    },
    "Documentary": {
        "Crime Documentary": "in0000059",
        "Documentary": "in0000060",
        "Docuseries": "in0000061",
        "Faith & Spirituality Documentary": "in0000062",
        "Food Documentary": "in0000063",
        "History Documentary": "in0000064",
        "Military Documentary": "in0000065",
        "Music Documentary": "in0000066",
        "Nature Documentary": "in0000067",
        "Political Documentary": "in0000068",
        "Science & Technology Documentary": "in0000069",
        "Sports Documentary": "in0000070",
        "Travel Documentary": "in0000071"
    },
    "Drama": {
        "Biography": "in0000072",
        "Coming-of-Age": "in0000073",
        "Costume Drama": "in0000074",
        "Docudrama": "in0000075",
        "Drama": "in0000076",
        "Epic": "in0000077",
        "Financial Drama": "in0000078",
        "Historical Epic": "in0000079",
        "History": "in0000080",
        "Korean Drama": "in0000209",
        "Legal Drama": "in0000081",
        "Medical Drama": "in0000082",
        "Period Drama": "in0000083",
        "Political Drama": "in0000084",
        "Prison Drama": "in0000085",
        "Psychological Drama": "in0000086",
        "Showbiz Drama": "in0000087",
        "Soap Opera": "in0000088",
        "Teen Drama": "in0000089",
        "Telenovela": "in0000210",
        "Tragedy": "in0000090",
        "Workplace Drama": "in0000091"
    },
    "Family": {
        "Animal Adventure": "in0000092",
        "Family": "in0000093"
    },
    "Fantasy": {
        "Dark Fantasy": "in0000095",
        "Fairy Tale": "in0000097",
        "Fantasy": "in0000098",
        "Fantasy Epic": "in0000096",
        "Supernatural Fantasy": "in0000099",
        "Sword & Sorcery": "in0000100",
        "Teen Fantasy": "in0000101"
    },
    "Game Show": {
        "Beauty Competition": "in0000102",
        "Cooking Competition": "in0000103",
        "Game Show": "in0000105",
        "Quiz Show": "in0000104",
        "Survival Competition": "in0000106",
        "Talent Competition": "in0000107"
    },
    "Horror": {
        "B-Horror": "in0000108",
        "Body Horror": "in0000109",
        "Folk Horror": "in0000110",
        "Found Footage Horror": "in0000111",
        "Horror": "in0000112",
        "Monster Horror": "in0000113",
        "Psychological Horror": "in0000114",
        "Slasher Horror": "in0000115",
        "Splatter Horror": "in0000116",
        "Supernatural Horror": "in0000117",
        "Teen Horror": "in0000118",
        "Vampire Horror": "in0000119",
        "Werewolf Horror": "in0000120",
        "Witch Horror": "in0000121",
        "Zombie Horror": "in0000122"
    },
    "Lifestyle": {
        "Beauty Makeover": "in0000123",
        "Cooking & Food": "in0000124",
        "Home Improvement": "in0000125",
        "Lifestyle": "in0000126",
        "News": "in0000211",
        "Talk Show": "in0000127",
        "Travel": "in0000128"
    },
    "Music": {
        "Concert": "in0000129",
        "Music": "in0000130"
    },
    "Musical": {
        "Classic Musical": "in0000131",
        "Jukebox Musical": "in0000132",
        "Musical": "in0000133",
        "Pop Musical": "in0000134",
        "Rock Musical": "in0000135"
    },
    "Mystery": {
        "Bumbling Detective": "in0000136",
        "Cozy Mystery": "in0000137",
        "Hard-boiled Detective": "in0000138",
        "Mystery": "in0000139",
        "Suspense Mystery": "in0000140",
        "Whodunnit": "in0000141"
    },
    "Reality TV": {
        "Business Reality TV": "in0000142",
        "Crime Reality TV": "in0000143",
        "Dating Reality TV": "in0000144",
        "Docusoap Reality TV": "in0000145",
        "Hidden Camera": "in0000146",
        "Paranormal Reality TV": "in0000147",
        "Reality TV": "in0000148"
    },
    "Romance": {
        "Dark Romance": "in0000149",
        "Feel-Good Romance": "in0000151",
        "Romance": "in0000152",
        "Romantic Comedy": "in0000153",
        "Romantic Epic": "in0000150",
        "Steamy Romance": "in0000154",
        "Teen Romance": "in0000155",
        "Tragic Romance": "in0000156"
    },
    "Sci-Fi": {
        "Alien Invasion": "in0000157",
        "Artificial Intelligence": "in0000158",
        "Cyberpunk": "in0000159",
        "Dystopian Sci-Fi": "in0000160",
        "Kaiju": "in0000161",
        "Sci-Fi": "in0000162",
        "Sci-Fi Epic": "in0000163",
        "Space Sci-Fi": "in0000164",
        "Steampunk": "in0000165",
        "Time Travel": "in0000166"
    },
    "Seasonal": {
        "Holiday": "in0000192",
        "Holiday Animation": "in0000193",
        "Holiday Comedy": "in0000194",
        "Holiday Family": "in0000195",
        "Holiday Romance": "in0000196"
    },
    "Short": {
        "Short": "in0000212"
    },
    "Sport": {
        "Baseball": "in0000167",
        "Basketball": "in0000168",
        "Boxing": "in0000169",
        "Extreme Sport": "in0000170",
        "Football": "in0000171",
        "Motorsport": "in0000172",
        "Soccer": "in0000173",
        "Sport": "in0000174",
        "Water Sport": "in0000175"
    },
    "Thriller": {
        "Conspiracy Thriller": "in0000176",
        "Cyber Thriller": "in0000177",
        "Erotic Thriller": "in0000178",
        "Giallo": "in0000179",
        "Legal Thriller": "in0000180",
        "Political Thriller": "in0000181",
        "Psychological Thriller": "in0000182",
        "Serial Killer": "in0000183",
        "Spy": "in0000184",
        "Survival": "in0000185",
        "Thriller": "in0000186"
    },
    "Western": {
        "Classical Western": "in0000187",
        "Contemporary Western": "in0000188",
        "Spaghetti Western": "in0000190",
        "Western": "in0000191",
        "Western Epic": "in0000189"
    }
}
CACHE_LIFETIME: Final[int] = 86400
IMDB_GRAPHQL_QUERY: Final[str] = \
"""query VerticalListPageItems( $titles: [ID!]! $names: [ID!]! $images: [ID!]! $videos: [ID!]!) {
  titles(ids: $titles) { ...TitleParts meterRanking { currentRank meterType rankChange {changeDirection difference} } ratingsSummary { aggregateRating } }
  names(ids: $names) { ...NameParts }
  videos(ids: $videos) { ...VideoParts }
  images(ids: $images) { ...ImageParts }
}
fragment TitleParts on Title {
  id
  titleText { text }
  titleType { id }
  releaseYear { year }
  akas(first: 50) { edges { node { text country { id text } language { text } } } }
  plot { plotText {plainText}}
  primaryImage { id url width height }
  releaseDate {day month year}
  titleGenres {genres {genre { text }}}
  certificate { rating }
  originalTitleText{ text }
  runtime { seconds }
}
fragment NameParts on Name {
  id
  nameText { text }
  primaryImage { id url width height }
}
fragment ImageParts on Image {
  id
  height
  width
  url
}
fragment VideoParts on Video {
  id
  name { value }
  contentType { displayName { value } id }
  previewURLs { displayName { value } url videoDefinition videoMimeType }
  playbackURLs { displayName { value } url videoDefinition videoMimeType }
  thumbnail { height url width }
}"""


class PersistedQueryNotFound(Exception):
    def __init__(self, message: str, code: int = None):
        super().__init__(message)
        self.code = code


class OfficialApiClient:
    BASE_URL = "https://caching.graphql.imdb.com/"

    def __init__(self, proxies: Optional[Dict[str, str]] = None,
                 ua: Optional[str] = None):
        self._req = RequestUtils(accept_type="application/json",
                                 content_type="application/json",
                                 timeout=10,
                                 ua=None,
                                 proxies=proxies,
                                 session=requests.Session())
        if proxies:
            proxy_url = proxies.get("https") or proxies.get("http")
        else:
            proxy_url = None
        self._client = httpx.AsyncClient(timeout=10, proxy=proxy_url)
        self._async_req = AsyncRequestUtils(accept_type="application/json", content_type="application/json",
                                            client=self._client, ua=ua)
        self.flat_interest_id = {}
        for category, value in INTERESTS_ID.items():
            for name, in_id in value.items():
                self.flat_interest_id[name] = in_id

    @cached(maxsize=1024, ttl=CACHE_LIFETIME)
    async def _async_request(self, params: Dict[str, Any], sha256: str) -> Optional[Dict]:
        params["extensions"] = {"persistedQuery": {"sha256Hash": sha256, "version": 1}}
        data = await self._async_req.post_json(f"{self.BASE_URL}", json=params, raise_exception=True)
        if not data:
            return None
        if "errors" in data:
            error = data.get("errors")[0] if data.get("errors") else {}
            return {'error': error}
        return data.get("data")

    @retry(Exception, logger=logger)
    @cached(maxsize=1024, ttl=CACHE_LIFETIME)
    def _query_graphql(self, query: str, variables: Dict[str, Any]) -> Optional[dict]:
        params = {'query': query, 'variables': variables}
        data = self._req.post_json(f"{self.BASE_URL}", json=params, raise_exception=True)
        if not data:
            return {'error': 'Query failed.'}
        if "errors" in data:
            error = data.get("errors")[0] if data.get("errors") else {}
            return {'error': error}
        return data.get("data")

    @retry(Exception, logger=logger)
    @cached(maxsize=1024, ttl=CACHE_LIFETIME)
    async def _async_query_graphql(self, query: str, variables: Dict[str, Any]) -> Optional[Dict]:
        params = {'query': query, 'variables': variables}
        data = await self._async_req.post_json(f"{self.BASE_URL}", json=params, raise_exception=True)
        if not data:
            return None
        if "errors" in data:
            error = data.get("errors")[0] if data.get("errors") else {}
            return {'error': error}
        return data.get("data")

    @cached(maxsize=1024, ttl=CACHE_LIFETIME)
    def vertical_list_page_items(self,
                                 titles: Optional[List[str]] = None,
                                 names: Optional[List[str]] = None,
                                 images: Optional[List[str]] = None,
                                 videos: Optional[List[str]] = None,
                                 is_registered: bool = False
                                 ) -> Optional[VerticalList]:
        variables = {'images': images or [],
                     'titles': titles or [],
                     'names': names or [],
                     'videos': videos or [],
                     'isRegistered': is_registered,
                     }
        try:
            data = self._query_graphql(IMDB_GRAPHQL_QUERY, variables)
            if 'error' in data:
                error = data['error']
                if error:
                    logger.error(f"Error querying VerticalListPageItems: {error}")
                return None
            ret = VerticalList.parse_obj(data)
        except Exception as e:
            logger.debug(f"An error occurred while querying VerticalListPageItems: {e}")
            return None

        return ret

    @cached(maxsize=1024, ttl=CACHE_LIFETIME)
    async def async_vertical_list_page_items(self,
                                             titles: Optional[List[str]] = None,
                                             names: Optional[List[str]] = None,
                                             images: Optional[List[str]] = None,
                                             videos: Optional[List[str]] = None,
                                             is_registered: bool = False
                                             ) -> Optional[VerticalList]:
        variables = {'images': images or [],
                     'titles': titles or [],
                     'names': names or [],
                     'videos': videos or [],
                     'isRegistered': is_registered,
                     }
        try:
            data = await self._async_query_graphql(IMDB_GRAPHQL_QUERY, variables)
            if 'error' in data:
                error = data['error']
                if error:
                    logger.error(f"Error querying VerticalListPageItems: {error}")
                return None
            ret = VerticalList.parse_obj(data)
        except Exception as e:
            logger.debug(f"An error occurred while querying VerticalListPageItems: {e}")
            return None

        return ret

    @retry(Exception, logger=logger)
    async def async_advanced_title_search(self,
                                           params: SearchParams,
                                           sha256: str,
                                           last_cursor: Optional[str] = None,
                                           ) -> Optional[AdvancedTitleSearch]:

        variables: Dict[str, Any] = {"first": 50,
                                     "locale": "en-US",
                                     "sortBy": params.sort_by,
                                     "sortOrder": params.sort_order,
                                     }
        operation_name = 'AdvancedTitleSearch'
        if params.title_types:
            title_type_ids = []
            for title_type in params.title_types:
                if title_type in ImdbType._value2member_map_:
                    title_type_ids.append(title_type)
            if len(title_type_ids):
                variables["titleTypeConstraint"] = {"anyTitleTypeIds": params.title_types}
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
                c = self._award_to_constraint(award)
                if c:
                    constraints.append(c)
            variables["awardConstraint"] = {"allEventNominations": constraints}
        if params.ranked:
            constraints = []
            for r in params.ranked:
                c = OfficialApiClient._ranked_list_to_constraint(r)
                if c:
                    constraints.append(c)
            variables["rankedTitleListConstraint"] = {"allRankedTitleLists": constraints,
                                                      "excludeRankedTitleLists": []}
        if params.interests:
            constraints = []
            for interest in params.interests:
                in_id = self.flat_interest_id.get(interest)
                if in_id:
                    constraints.append(in_id)
            variables["interestConstraint"] = {"allInterestIds": constraints, "excludeInterestIds": []}
        if last_cursor:
            variables["after"] = last_cursor

        params = {"operationName": operation_name,
                  "variables": variables}
        try:
            data = await self._async_request(params, sha256)
        except Exception as e:
            logger.debug(f"An error occurred while querying {operation_name}: {e}")
            return None
        if not data:
            return None
        if 'error' in data:
            error = data['error']
            if error:
                if error.get('message') == 'PersistedQueryNotFound':
                    await self._async_request.cache_clear()
                    raise PersistedQueryNotFound(error['message'])
            return None
        try:
            ret = AdvancedTitleSearchResponse.parse_obj(data)
        except ValidationError as err:
            logger.error(f"{err}")
            return None
        return ret.advanced_title_search

    async def advanced_title_search_generator(self, params: SearchParams, sha256: str) -> AsyncGenerator[TitleEdge, None]:
        last_cursor = None
        while True:
            response = await self.async_advanced_title_search(params, sha256, last_cursor=last_cursor)
            if not response:
                return

            for edge in response.edges:
                yield edge

            last_cursor = response.page_info.end_cursor
            if not last_cursor or not response.page_info.has_next_page:
                break

    @staticmethod
    def _ranked_list_to_constraint(ranked: str) -> Optional[Dict]:
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
    def _award_to_constraint(award: str) -> Optional[Dict]:
        pattern = r'^(ev\d+)(?:-(best\w+))?-(Winning|Nominated)$'
        match = re.match(pattern, award)
        constraint = {}
        if match:
            # 第一部分：evXXXXXXXX
            ev_id = match.group(1)
            # 第二部分：bestXX（可选）
            best = match.group(2)
            # 第三部分：Winning/Nominated
            status = match.group(3)
            constraint["eventId"] = ev_id
            if status == "Winning":
                constraint["winnerFilter"] = "WINNER_ONLY"
            if best:
                constraint["searchAwardCategoryId"] = best
            return constraint
        else:
            return None

    @property
    def interests_id(self) -> Dict[str, str]:
        return self.flat_interest_id
