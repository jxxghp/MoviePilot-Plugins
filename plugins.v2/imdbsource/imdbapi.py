from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Final

import requests
import httpx

from app.core.cache import cached
from app.log import logger
from app.utils.common import retry
from app.utils.http import RequestUtils, AsyncRequestUtils

from .schema.imdbapi import ImdbApiTitle, ImdbApiEpisode, ImdbApiCredit
from .schema.imdbapi import ImdbApiSearchTitlesResponse, ImdbApiListTitlesResponse, ImdbApiListTitleEpisodesResponse, \
    ImdbApiListTitleSeasonsResponse, ImdbApiListTitleCreditsResponse, ImdbapiListTitleAKAsResponse
from .schema.imdbtypes import ImdbType


CACHE_LIFESPAN: Final[int] = 86400


class ImdbApiClient:
    BASE_URL = 'https://api.imdbapi.dev'

    def __init__(self, proxies: Optional[Dict[str, str]] = None, ua: Optional[str] = None) -> None:
        self._req = RequestUtils(ua=ua, accept_type="application/json",
                                 proxies=proxies, session=requests.Session())
        if proxies:
            proxy_url = proxies.get("https") or proxies.get("http")
        else:
            proxy_url = None
        self._free_api_client = httpx.AsyncClient(timeout=10, proxy=proxy_url)

        self._async_req = AsyncRequestUtils(
            ua=ua,
            accept_type="application/json",
            client=self._free_api_client
        )

    @retry(Exception, logger=logger)
    @cached(maxsize=1024, ttl=CACHE_LIFESPAN)
    def _free_imdb_api(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        r = self._req.get_res(url=f"{self.BASE_URL}{path}", params=params, raise_exception=True)
        if r is None:
            return None
        if r.status_code != 200:
            try:
                logger.warn(f"{r.json().get('message')}")
            except requests.exceptions.JSONDecodeError:
                return None
            return None
        return r.json()

    @retry(Exception, logger=logger)
    @cached(maxsize=1024, ttl=CACHE_LIFESPAN)
    async def _async_free_imdb_api(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        r = await self._async_req.get_res(url=f"{self.BASE_URL}{path}", params=params, raise_exception=True)
        if r is None:
            return None
        if r.status_code != 200:
            try:
                logger.warn(f"{path}: {r.json().get('message')}")
            except requests.exceptions.JSONDecodeError:
                return None
            return None
        return r.json()

    def search_titles(self, query: str, limit: Optional[int] = None) -> Optional[ImdbApiSearchTitlesResponse]:
        """
        Search for titles using a query string.
        :param query: Required. The search query for titles.
        :param limit: Optional. Limit the number of results returned. Maximum is 50.
        :return: Search results.
        See `curl -X 'GET' 'https://api.imdbapi.dev/search/titles?query=Kite' -H 'accept: application/json'`
        """
        path = '/search/titles'
        params: Dict[str, Any] = {'query': query}
        if limit:
            params['limit'] = limit
        try:
            r = self._free_imdb_api(path=path, params=params)
            if r is None:
                return None
            ret = ImdbApiSearchTitlesResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while searching for titles: {e}")
            return None
        return ret

    async def async_search_titles(self, query: str, limit: Optional[int] = None
                                  ) -> Optional[ImdbApiSearchTitlesResponse]:
        endpoint = '/search/titles'
        params: Dict[str, Any] = {'query': query}
        if limit:
            params['limit'] = limit
        try:
            r = await self._async_free_imdb_api(path=endpoint, params=params)
            if r is None:
                return None
            ret = ImdbApiSearchTitlesResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while searching for titles: {e}")
            return None
        return ret

    def advanced_search(self, query: str, limit: Optional[int] = None,
                        media_types: Optional[List[ImdbType]] = None,
                        year: Optional[int] = None) -> Optional[List[ImdbApiTitle]]:
        """
        Perform an advanced search for titles using a query string with
            additional filters.
        :param query: The search query for titles.
        :param limit: The maximum number of results to return.
        :param media_types: The type of titles to filter by.
        :param year: The start year for filtering titles.
        :return: Search results.
        See `curl -X 'GET' 'https://api.imdbapi.dev/search/titles?query=Kite' -H 'accept: application/json'`
        """

        data = self.search_titles(query=query, limit=limit)
        if data is None:
            return None
        ret = data.titles
        if year:
            ret = [title for title in ret if title.start_year == year]
        if media_types:
            ret = [title for title in ret if title.type in media_types]
        return ret

    async def async_advanced_search(self, query: str, limit: Optional[int] = None,
                                    media_types: Optional[List[ImdbType]] = None,
                                    year: Optional[int] = None) -> Optional[List[ImdbApiTitle]]:
        """
        Perform an advanced search for titles using a query string with additional filters.
        :param query: The search query for titles.
        :param limit: The maximum number of results to return.
        :param media_types: The type of titles to filter by.
        :param year: The start year for filtering titles.
        :return: Search results.
        See `curl -X 'GET' 'https://api.imdbapi.dev/search/titles?query=Kite' -H 'accept: application/json'`
        """

        data = await self.async_search_titles(query=query, limit=limit)
        if data is None:
            return None
        if year:
            data = [title for title in data.titles if title.start_year == year]
        if media_types:
            data = [title for title in data.titles if title.type in media_types]
        return data

    def titles(self,
               types: Optional[List[ImdbType]] = None,
               genres: Optional[List[str]] = None,
               country_codes: Optional[List[str]] = None,
               language_codes: Optional[List[str]] = None,
               name_ids: Optional[List[str]] = None,
               interest_ids: Optional[List[str]] = None,
               start_year: Optional[int] = None,
               end_year: Optional[int] = None,
               min_vote_count: Optional[int] = None,
               max_vote_count: Optional[int] = None,
               min_aggregate_rating: Optional[float] = None,
               max_aggregate_rating: Optional[float] = None,
               sort_by: Optional[str] = None,
               sort_order: Optional[str] = None,
               page_token: Optional[str] = None) -> Optional[ImdbApiListTitlesResponse]:
        """
        Retrieve a list of titles with optional filters.
        :param types: Optional. The type of titles to filter by. If not specified,
            all types are returned.
            - MOVIE: Represents a movie title.
            - TV_SERIES: Represents a TV series title.
            - TV_MINI_SERIES: Represents a TV miniseries title.
            - TV_SPECIAL: Represents a TV special title.
            - TV_MOVIE: Represents a TV movie title.
            - SHORT: Represents a short title.
            - VIDEO: Represents a video title.
            - VIDEO_GAME: Represents a video game title.
        :param genres: Optional. The genres to filter titles by. If not specified,
            titles from all genres are returned.
        :param country_codes: Optional. The ISO 3166-1 alpha-2 country codes to
            filter titles by. If not specified, titles from all countries are
            returned. Example: "US" for the United States, "GB" for the United
            Kingdom.
        :param language_codes: Optional. The ISO 639-1 or ISO 639-2 language codes
            to filter titles by. If not specified, titles in all languages are
            returned.
        :param name_ids: Optional. The IDs of names to filter titles by.
        :param interest_ids: Optional. The IDs of interests to filter titles by.
            If not specified, titles associated with all interests are returned.
        :param start_year: Optional. The start year for filtering titles.
        :param end_year: Optional. The end year for filtering titles.
        :param min_vote_count: Optional. The minimum number of votes a title must
            have to be included. If not specified, titles with any number of votes
            are included. The value must be between 0 and 1,000,000,000. Default is 0.
        :param max_vote_count: Optional. The maximum number of votes a title can
            have to be included. If not specified, titles with any number of votes
            are included. The value must be between 0 and 1,000,000,000.
        :param min_aggregate_rating: Optional. The minimum rating a title must have
            to be included. If not specified, titles with any rating are included.
            The value must be between 0.0 and 10.0.
        :param max_aggregate_rating: Optional. The maximum rating a title can have
            to be included. If not specified, titles with any rating are included.
            The value must be between 0.0 and 10.0.
        :param sort_by: Optional. The sorting order for the titles. If not
            specified, titles are sorted by popularity.
            - SORT_BY_POPULARITY: Sort by popularity. Used to rank titles based on
              viewership, ratings, or cultural impact.
            - SORT_BY_RELEASE_DATE: Sort by release date. Newer titles typically
              appear before older ones.
            - SORT_BY_USER_RATING: Sort by average user rating, reflecting audience
              reception.
            - SORT_BY_USER_RATING_COUNT: Sort by number of user ratings, indicating
              engagement or popularity.
            - SORT_BY_YEAR: Sort by release year, with newer titles typically first.
        :param sort_order: Optional. The sorting order for the titles. If not
            specified, titles are sorted in ascending order.
            - ASC: Sort in ascending order.
            - DESC: Sort in descending order.
        :param page_token: Optional. Token for pagination, if applicable.
        :return: A dictionary containing the list of titles and pagination info.
"""

        path = '/titles'
        params: Dict[str, Any] = {}
        if types:
            params['types'] = [t.value for t in types]
        if genres:
            params['genres'] = genres
        if country_codes:
            params['countryCodes'] = country_codes
        if language_codes:
            params['languageCodes'] = language_codes
        if name_ids:
            params['nameIds'] = name_ids
        if interest_ids:
            params['interestIds'] = interest_ids
        if start_year:
            params['startYear'] = start_year
        if end_year:
            params['endYear'] = end_year
        if min_vote_count:
            params['minVoteCount'] = min_vote_count
        if max_vote_count:
            params['maxVoteCount'] = max_vote_count
        if min_aggregate_rating:
            params['minAggregateRating'] = min_aggregate_rating
        if max_aggregate_rating:
            params['maxAggregateRating'] = max_aggregate_rating
        if sort_by:
            params['sortBy'] = sort_by
        if sort_order:
            params['sortOrder'] = sort_order
        if page_token:
            params['pageToken'] = page_token

        try:
            return ImdbApiListTitlesResponse.parse_obj(self._free_imdb_api(path=path, params=params))
        except Exception as e:
            logger.debug(f"An error occurred while listing titles: {e}")
            return None

    async def async_titles(self,
                           types: Optional[List[ImdbType]] = None,
                           genres: Optional[List[str]] = None,
                           country_codes: Optional[List[str]] = None,
                           language_codes: Optional[List[str]] = None,
                           name_ids: Optional[List[str]] = None,
                           interest_ids: Optional[List[str]] = None,
                           start_year: Optional[int] = None,
                           end_year: Optional[int] = None,
                           min_vote_count: Optional[int] = None,
                           max_vote_count: Optional[int] = None,
                           min_aggregate_rating: Optional[float] = None,
                           max_aggregate_rating: Optional[float] = None,
                           sort_by: Optional[str] = None,
                           sort_order: Optional[str] = None,
                           page_token: Optional[str] = None) -> Optional[ImdbApiListTitlesResponse]:
        path = '/titles'
        params: Dict[str, Any] = {}
        if types:
            params['types'] = [t.value for t in types]
        if genres:
            params['genres'] = genres
        if country_codes:
            params['countryCodes'] = country_codes
        if language_codes:
            params['languageCodes'] = language_codes
        if name_ids:
            params['nameIds'] = name_ids
        if interest_ids:
            params['interestIds'] = interest_ids
        if start_year:
            params['startYear'] = start_year
        if end_year:
            params['endYear'] = end_year
        if min_vote_count:
            params['minVoteCount'] = min_vote_count
        if max_vote_count:
            params['maxVoteCount'] = max_vote_count
        if min_aggregate_rating:
            params['minAggregateRating'] = min_aggregate_rating
        if max_aggregate_rating:
            params['maxAggregateRating'] = max_aggregate_rating
        if sort_by:
            params['sortBy'] = sort_by
        if sort_order:
            params['sortOrder'] = sort_order
        if page_token:
            params['pageToken'] = page_token

        try:
            r = await self._async_free_imdb_api(path=path, params=params)
            if r is None:
                return None
            return ImdbApiListTitlesResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while listing titles: {e}")
            return None

    def titles_generator(self,
                         types: Optional[List[ImdbType]] = None,
                         genres: Optional[List[str]] = None,
                         country_codes: Optional[List[str]] = None,
                         language_codes: Optional[List[str]] = None,
                         name_ids: Optional[List[str]] = None,
                         interest_ids: Optional[List[str]] = None,
                         start_year: Optional[int] = None,
                         end_year: Optional[int] = None,
                         min_vote_count: Optional[int] = None,
                         max_vote_count: Optional[int] = None,
                         min_aggregate_rating: Optional[float] = None,
                         max_aggregate_rating: Optional[float] = None,
                         sort_by: Optional[str] = None,
                         sort_order: Optional[str] = None,
                         ) -> Generator[ImdbApiTitle, None, None]:
        page_token = None
        while True:
            response = self.titles(
                types=types,
                genres=genres,
                country_codes=country_codes,
                language_codes=language_codes,
                name_ids=name_ids,
                interest_ids=interest_ids,
                start_year=start_year,
                end_year=end_year,
                min_vote_count=min_vote_count,
                max_vote_count=max_vote_count,
                min_aggregate_rating=min_aggregate_rating,
                max_aggregate_rating=max_aggregate_rating,
                sort_by=sort_by,
                sort_order=sort_order,
                page_token=page_token
            )
            if not response:
                return
            for title in response.titles:
                yield title
            if not page_token:
                break

    async def async_titles_generator(self,
                                     types: Optional[List[ImdbType]] = None,
                                     genres: Optional[List[str]] = None,
                                     country_codes: Optional[List[str]] = None,
                                     language_codes: Optional[List[str]] = None,
                                     name_ids: Optional[List[str]] = None,
                                     interest_ids: Optional[List[str]] = None,
                                     start_year: Optional[int] = None,
                                     end_year: Optional[int] = None,
                                     min_vote_count: Optional[int] = None,
                                     max_vote_count: Optional[int] = None,
                                     min_aggregate_rating: Optional[float] = None,
                                     max_aggregate_rating: Optional[float] = None,
                                     sort_by: Optional[str] = None,
                                     sort_order: Optional[str] = None,
                                     ) -> AsyncGenerator[ImdbApiTitle, None]:

        page_token = None
        while True:
            response = await self.async_titles(
                types=types,
                genres=genres,
                country_codes=country_codes,
                language_codes=language_codes,
                name_ids=name_ids,
                interest_ids=interest_ids,
                start_year=start_year,
                end_year=end_year,
                min_vote_count=min_vote_count,
                max_vote_count=max_vote_count,
                min_aggregate_rating=min_aggregate_rating,
                max_aggregate_rating=max_aggregate_rating,
                sort_by=sort_by,
                sort_order=sort_order,
                page_token=page_token
            )
            if not response:
                return

            for title in response.titles:
                yield title

            page_token = response.next_page_token
            if not page_token:
                break

    def title(self, title_id: str) -> Optional[ImdbApiTitle]:
        """
        Retrieve a title's details using its IMDb ID.
        :param title_id: The IMDb title ID in the format 'tt1234567'.
        :return: Details.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947' -H 'accept: application/json'`
        """
        path = '/titles/%s'
        try:
            r = self._free_imdb_api(path=path % title_id)
            ret = ImdbApiTitle.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving details: {e}")
            return None
        return ret

    async def async_title(self, title_id: str) -> Optional[ImdbApiTitle]:
        path = '/titles/%s'
        try:
            r = await self._async_free_imdb_api(path=path % title_id)
            if r is None:
                return None
            ret = ImdbApiTitle.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving details: {e}")
            return None
        return ret

    def episodes(self, title_id: str, season: Optional[str] = None,
                 page_size: Optional[int] = None, page_token: Optional[str] = None) -> Optional[
        ImdbApiListTitleEpisodesResponse]:
        """
        Retrieve the episodes associated with a specific title.
        :param title_id: Required. IMDb title ID in the format "tt1234567".
        :param season: Optional. The season number to filter episodes by.
        :param page_size: Optional. The maximum number of episodes to return per page.
            The value must be between 1 and 50. Default is 20.
        :param page_token: Optional. Token for pagination, if applicable.
        :return: Episodes.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947/episodes?season=1&pageSize=5' \
            -H 'accept: application/json'`
        """
        path = '/titles/%s/episodes'
        param: Dict[str, Any] = {}
        if season is not None:
            param['season'] = season
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        try:
            r = self._free_imdb_api(path=path % title_id, params=param)
            ret = ImdbApiListTitleEpisodesResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving episodes: {e}")
            return None
        return ret

    async def async_episodes(self, title_id: str, season: Optional[str] = None,
                             page_size: Optional[int] = None, page_token: Optional[str] = None
                             ) -> Optional[ImdbApiListTitleEpisodesResponse]:

        path = '/titles/%s/episodes'
        param: Dict[str, Any] = {}
        if season is not None:
            param['season'] = season
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        try:
            r = await self._async_free_imdb_api(path=path % title_id, params=param)
            if r is None:
                return None
            ret = ImdbApiListTitleEpisodesResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving episodes: {e}")
            return None
        return ret

    def episodes_generator(self, title_id: str, season: Optional[str] = None) -> Generator[ImdbApiEpisode, None, None]:
        page_token = None
        while True:
            response = self.episodes(
                title_id=title_id,
                season=season,
                page_size=50,
                page_token=page_token
            )
            if not response:
                return

            for episode in response.episodes:
                yield episode

            page_token = response.next_page_token
            if not page_token:
                break

    async def async_episodes_generator(self, title_id: str, season: Optional[str] = None
                                       ) -> AsyncGenerator[ImdbApiEpisode, None]:
        page_token = None
        while True:
            response = await self.async_episodes(
                title_id=title_id,
                season=season,
                page_size=50,
                page_token=page_token
            )
            if not response:
                return

            for episode in response.episodes:
                yield episode

            page_token = response.next_page_token
            if not page_token:
                break

    def seasons(self, title_id: str) -> Optional[ImdbApiListTitleSeasonsResponse]:
        """
        Retrieve the seasons associated with a specific title.
        :param title_id: Required. IMDb title ID in the format "tt1234567".
        :return: Seasons.
        """
        path = '/titles/%s/seasons'
        try:
            r = self._free_imdb_api(path=path % title_id)
            ret = ImdbApiListTitleSeasonsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving seasons: {e}")
            return None
        return ret

    async def async_seasons(self, title_id: str) -> Optional[ImdbApiListTitleSeasonsResponse]:
        path = '/titles/%s/seasons'
        try:
            r = await self._async_free_imdb_api(path=path % title_id)
            if r is None:
                return None
            ret = ImdbApiListTitleSeasonsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving seasons: {e}")
            return None
        return ret

    def credits(self, title_id: str, categories: Optional[List[str]] = None,
                page_size: Optional[int] = None, page_token: Optional[str] = None
                ) -> Optional[ImdbApiListTitleCreditsResponse]:
        """
        Retrieve the credits associated with a specific title.
        :param title_id: Required. IMDb title ID in the format "tt1234567".
        :param categories: Optional. The categories of credits to filter by.
        :param page_size: Optional. The maximum number of credits to return per page.
            The value must be between 1 and 50. Default is 20.
        :param page_token: Optional. Token for pagination, if applicable.
        :return: Credits.
        See `curl -X 'GET' 'https://api.imdbapi.dev/titles/tt0944947/credits?categories=CAST' \
            -H 'accept: application/json'`
        """
        path = '/titles/%s/credits'
        param: Dict[str, Any] = {}
        if categories:
            param['categories'] = categories
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        try:
            r = self._free_imdb_api(path=path % title_id, params=param)
            ret = ImdbApiListTitleCreditsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving credits: {e}")
            return None
        return ret

    async def async_credits(self, title_id: str, categories: Optional[List[str]] = None,
                            page_size: Optional[int] = None, page_token: Optional[str] = None) -> Optional[
        ImdbApiListTitleCreditsResponse]:

        path = '/titles/%s/credits'
        param: Dict[str, Any] = {}
        if categories:
            param['categories'] = categories
        if page_size is not None:
            param['pageSize'] = page_size
        if page_token is not None:
            param['pageToken'] = page_token
        try:
            r = await self._async_free_imdb_api(path=path % title_id, params=param)
            if r is None:
                return None
            ret = ImdbApiListTitleCreditsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving credits: {e}")
            return None
        return ret

    def credits_generator(self, title_id: str, categories: Optional[List[str]] = None
                          ) -> Generator[ImdbApiCredit, None, None]:
        page_token = None
        while True:
            response = self.credits(
                title_id=title_id,
                categories=categories,
                page_size=50,
                page_token=page_token
            )
            if not response:
                return

            for credit in response.credits:
                yield credit

            page_token = response.next_page_token
            if not page_token:
                break

    async def async_credits_generator(self, title_id: str, categories: Optional[List[str]] = None
                                      ) -> AsyncGenerator[ImdbApiCredit, None]:
        page_token = None
        while True:
            response = await self.async_credits(
                title_id=title_id,
                categories=categories,
                page_size=50,
                page_token=page_token
            )
            if not response:
                return

            for credit in response.credits:
                yield credit

            page_token = response.next_page_token
            if not page_token:
                break

    def akas(self, title_id: str) -> Optional[ImdbapiListTitleAKAsResponse]:
        """
        Retrieve the alternative titles (AKAs) associated with a specific title.
        :param title_id: Required. IMDb title ID in the format "tt1234567".
        :return: AKAs.
        """
        path = '/titles/%s/akas'
        try:
            r = self._free_imdb_api(path=path % title_id)
            ret = ImdbapiListTitleAKAsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving alternative titles: {e}")
            return None
        if r is None:
            return None
        return ret

    async def async_akas(self, title_id: str) -> Optional[ImdbapiListTitleAKAsResponse]:
        path = '/titles/%s/akas'
        try:
            r = await self._async_free_imdb_api(path=path % title_id)
            if r is None:
                return None
            ret = ImdbapiListTitleAKAsResponse.parse_obj(r)
        except Exception as e:
            logger.debug(f"An error occurred while retrieving alternative titles: {e}")
            return None
        return ret
