import re
from typing import Optional, Dict, List
from io import StringIO

import graphene
from requests_html import HTMLSession
import ijson
import json
import base64

from app.log import logger
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.schemas.types import MediaType
from app.core.cache import cached


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
        MediaType.TV: ["tvSeries", "tvMiniSeries"],
        MediaType.MOVIE: ["movie"]
    }
    _imdb_headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome"
                      "/84.0.4147.105 Safari/537.36",
        "Referer": "https://www.imdb.com/",
    }

    def __init__(self, proxies=None):
        self._proxies = proxies
        self._session = HTMLSession()
        self._req_utils = RequestUtils(headers=self._imdb_headers, session=self._session, timeout=10, proxies=proxies)
        self._imdb_req = RequestUtils(accept_type="application/json", content_type="application/json",
                                      headers=self._imdb_headers, timeout=10, proxies=proxies)
        self._last_cursor = ''
        self._imdb_api_hash = {"AdvancedTitleSearch": None, "TitleAkasPaginated": None}

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

    @cached(maxsize=1000, ttl=3600)
    def __episodes_by_season(self, imdbid: str, build_id: str, season: str) -> Optional[Dict]:
        if not build_id or not season:
            return None
        prefix = "pageProps.contentData.section"
        url = (f"https://www.imdb.com/_next/data/{build_id}"
               f"/en-US/title/{imdbid}/episodes.json?season={season}&ref_=ttep&tconst={imdbid}")
        response = self._req_utils.get_res(url)
        if not response or response.status_code != 200:
            return
        json_content = response.text
        try:
            section = next(ijson.items(json_content, prefix))
        except StopIteration:
            logger.warn(f"No data found at prefix: {prefix}")
            return None
        except (ijson.JSONError, ValueError) as e:
            logger.warn(f"JSON parsing error: {e}")
            return None
        except TypeError as e:
            logger.warn(f"Invalid input type: {e}")
            return None
        return section

    @cached(maxsize=1000, ttl=3600)
    def __episodes(self, imdbid: str) -> Optional[Dict]:
        prefix = "props.pageProps.contentData.section"
        url = f"https://www.imdb.com/title/{imdbid}/episodes/"

        response = self._req_utils.get_res(url)
        if not response or response.status_code != 200:
            return
        script_content = response.html.xpath('//script[@id="__NEXT_DATA__"]/text()')
        if len(script_content) == 0:
            return None
        json_content = script_content[0]
        # 直接定位到目标路径提取 items
        try:
            section = next(ijson.items(json_content, prefix))
        except StopIteration:
            logger.warn(f"No data found at prefix: {prefix}")
            return None
        except (ijson.JSONError, ValueError) as e:
            logger.warn(f"JSON parsing error: {e}")
            return None
        except TypeError as e:
            logger.warn(f"Invalid input type: {e}")
            return None
        total_seasons = []
        for s in section.get("seasons"):
            if s.get("value") and s.get("value") not in total_seasons:
                total_seasons.append(s.get("value"))
        build_id = next(ijson.items(json_content, 'buildId'))
        current_season = section.get('currentSeason') or '1'
        total_seasons.remove(current_season)
        for season in total_seasons:
            section_next = self.__episodes_by_season(imdbid, build_id=build_id, season=season)
            if section_next:
                section["episodes"]["items"].extend(section_next.get("episodes", {}).get("items", []))
                section["episodes"]["total"] += section_next.get("episodes", {}).get("total", 0)
        return section

    @cached(maxsize=32, ttl=1800)
    def __request(self, params: Dict, sha256) -> Optional[Dict]:
        params["extensions"] = {"persistedQuery": {"sha256Hash": sha256, "version": 1}}
        ret = self._imdb_req.post_res(f"{self._official_endpoint}", json=params)
        if not ret:
            return None
        data = ret.json()
        if "errors" in data:
            logger.error(f"Imdb query errors")
            return None
        return data.get("data")

    @cached(maxsize=1, ttl=30 * 24 * 3600)
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
            logger.error("获取IMDb hash")
            return None
        return res.json()

    def __update_hash(self):
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

    def advanced_title_search(self,
                              sha256: str = 'be358d7b41add9fd174461f4c8c673dfee5e2a88744e2d5dc037362a96e2b4e4',
                              first_page: bool = True,
                              title_type: MediaType = MediaType.TV,
                              genres: Optional[List] = None,
                              sort_by: str = 'POPULARITY',
                              sort_order: str = 'ASC',
                              rating_min: Optional[float] = None,
                              rating_max: Optional[float] = None,
                              countries: Optional[List] = None,
                              languages: Optional[list] = None,
                              release_date_end: Optional[str] = None,
                              release_date_start: Optional[str] = None,
                              award_constraint: Optional[List[str]] = None
                              ) -> Optional[Dict]:
        self.__update_hash()
        if self._imdb_api_hash.get("AdvancedTitleSearch"):
            sha256 = self._imdb_api_hash["AdvancedTitleSearch"]
        if title_type not in [MediaType.TV, MediaType.MOVIE]:
            return None
        variables = {"first": 50,
                     "locale": "en-US",
                     "sortBy": sort_by,
                     "sortOrder": sort_order,
                     "titleTypeConstraint": {"anyTitleTypeIds": self._qid_map[title_type],
                                             "excludeTitleTypeIds": []}}
        if genres:
            variables["genreConstraint"] = {"allGenreIds": genres, "excludeGenreIds": []}
        if countries:
            variables["originCountryConstraint"] = {"allCountries": countries}
        if languages:
            variables["languageConstraint"] = {"anyPrimaryLanguages": languages}
        if rating_min or rating_max:
            rating_min = rating_min if rating_min else 1
            rating_min = max(rating_min, 1)
            rating_max = rating_max if rating_max else 10
            rating_max = min(rating_max, 10)
            variables["userRatingsConstraint"] = {"aggregateRatingRange": {"max": rating_max, "min": rating_min}}
        if release_date_start or release_date_end:
            release_dict = {}
            if release_date_start:
                release_dict["start"] = release_date_start
            if release_date_end:
                release_dict["end"] = release_date_end
            variables["releaseDateConstraint"] = {"releaseDateRange": release_dict}
        if award_constraint:
            constraints = []
            for award in award_constraint:
                c = self.__award_to_constraint(award)
                if c:
                    constraints.append(c)
            variables["awardConstraint"] = {"allEventNominations": constraints}
        if not first_page and self._last_cursor:
            variables["after"] = self._last_cursor

        params = {"operationName": "AdvancedTitleSearch",
                  "variables": variables}
        data = self.__request(params, sha256)
        if not data:
            return None
        page_info = data.get("advancedTitleSearch", {}).get("pageInfo", {})
        end_cursor = page_info.get("endCursor", "")
        self._last_cursor = end_cursor
        return data.get("advancedTitleSearch")

    def __known_as(self, imdbid: str,
                   sha256='48d4f7bfa73230fb550147bd4704d8050080e65fe2ad576da6276cac2330e446') -> Optional[List]:
        """
        获取电影和电视别名
        :param imdbid: IMBd id
        :return: 别名列表
        """
        self.__update_hash()
        if self._imdb_api_hash.get("TitleAkasPaginated"):
            sha256 = self._imdb_api_hash["TitleAkasPaginated"]
        params = {"operationName": "TitleAkasPaginated",
                  "variables": {"const": imdbid, "first": 50, "locale": "en-US", "originalTitleText": False}}
        data = self.__request(params=params, sha256=sha256)
        if not data:
            return None
        if not data.get("data", {}).get("title", {}).get("akas", {}).get("total"):
            return None
        akas = []
        for edge in data["data"]["title"]["akas"]["edges"]:
            title = edge.get("node", {}).get("displayableProperty", {}).get("value", {}).get("plainText")
            if not title:
                continue
            country = edge.get("node", {}).get("country", {})
            language = edge.get("node", {}).get("language", {})
            akas.append({"title": title, "country": country, "language": language})
        return akas

    def __search_on_imdb(self, term, mtype, release_year=None):
        params = f"{term}"
        if release_year is not None:
            params += f" {release_year}"
        ret = RequestUtils(
            accept_type="application/json",
        ).get_res(f"{self._search_endpoint % params}")
        if not ret:
            return None
        data = ret.json()
        if "d" not in data:
            return None
        result = [d for d in data["d"] if d.get("qid") in self._qid_map.get(mtype)]
        return result

    def search_tvs(self, title: str, year: str = None) -> List[dict]:
        if not title:
            return []
        if year:
            tvs = self.__search_on_imdb(title, MediaType.TV, year) or []
        else:
            tvs = self.__search_on_imdb(title, MediaType.TV, ) or []
        ret_infos = []
        for tv in tvs:
            # if title in tv.get("l"):
            # if self.__compare_names(title, [tv.get("l")]):
            #     tv['media_type'] = MediaType.TV
            ret_infos.append(tv)
        return ret_infos

    def search_movies(self, title: str, year: str = None) -> List[dict]:
        if not title:
            return []
        if year:
            movies = self.__search_on_imdb(title, MediaType.MOVIE, year) or []
        else:
            movies = self.__search_on_imdb(title, MediaType.MOVIE) or []
        ret_infos = []
        for movie in movies:
            # if title in movie.get("l"):
            # if self.__compare_names(title, [movie.get("l")]):
            #     movie['media_type'] = MediaType.MOVIE
            ret_infos.append(movie)
        return ret_infos

    @staticmethod
    def __compare_names(file_name: str, tmdb_names: list) -> bool:
        """
        比较文件名是否匹配，忽略大小写和特殊字符
        :param file_name: 识别的文件名或者种子名
        :param tmdb_names: TMDB返回的译名
        :return: True or False
        """
        if not file_name or not tmdb_names:
            return False
        if not isinstance(tmdb_names, list):
            tmdb_names = [tmdb_names]
        file_name = StringUtils.clear(file_name).upper()
        for tmdb_name in tmdb_names:
            tmdb_name = StringUtils.clear(tmdb_name).strip().upper()
            if file_name == tmdb_name:
                return True
        return False

    def __search_movie_by_name(self, name: str, year: str) -> Optional[dict]:
        """
        根据名称查询电影IMDB匹配
        :param name: 识别的文件名或种子名
        :param year: 电影上映日期
        :return: 匹配的媒体信息
        """
        movies = self.search_movies(name, year=year)
        if (movies is None) or (len(movies) == 0):
            logger.debug(f"{name} 未找到相关电影信息!")
            return {}
        movies = sorted(
            movies,
            key=lambda x: str(x.get("y") or '0000'),
            reverse=True
        )
        for movie in movies:
            movie_year = f"{movie.get('y')}"
            if year and movie_year != year:
                # 年份不匹配
                continue
            # 匹配标题、原标题
            movie_info = self.imdbid(movie.get("id"))
            if not movie_info:
                continue
            if self.__compare_names(name, [movie_info.get("primary_title")]):
                return movie_info
            if movie_info.get("original_title") and self.__compare_names(name, [movie_info.get("original_title")]):
                return movie_info
            akas = self.__known_as(movie.get("id"))
            if not akas:
                continue
            akas_names = [item.get("title") for item in akas]
            if self.__compare_names(name, akas_names):
                return movie_info
        return {}

    def __search_tv_by_name(self, name: str, year: str) -> Optional[dict]:
        """
        根据名称查询电视剧IMDB匹配
        :param name: 识别的文件名或者种子名
        :param year: 电视剧的首播年份
        :return: 匹配的媒体信息
        """
        tvs = self.search_tvs(name, year=year)
        if (tvs is None) or (len(tvs) == 0):
            logger.debug(f"{name} 未找到相关电影信息!")
            return {}
        tvs = sorted(
            tvs,
            key=lambda x: str(x.get("y") or '0000'),
            reverse=True
        )
        for tv in tvs:
            tv_year = f"{tv.get('y')}"
            if year and tv_year != year:
                # 年份不匹配
                continue
            # 匹配标题、原标题
            tv_info = self.imdbid(tv.get("id"))
            if not tv_info:
                continue
            if self.__compare_names(name, [tv_info.get("primary_title")]):
                return tv_info
            if tv_info.get("original_title") and self.__compare_names(name, [tv_info.get("original_title")]):
                return tv_info
            akas = self.__known_as(tv.get("id"))
            if not akas:
                continue
            akas_names = [item.get("title") for item in akas]
            if self.__compare_names(name, akas_names):
                return tv_info
        return {}

    def __search_tv_by_season(self, name: str, season_year: str, season_number: int) -> Optional[dict]:
        """
                根据电视剧的名称和季的年份及序号匹配IMDB
                :param name: 识别的文件名或者种子名
                :param season_year: 季的年份
                :param season_number: 季序号
                :return: 匹配的媒体信息
                """

        def __season_match(_tv_info: dict, _season_year: str) -> bool:
            tv_extra_info = self.__episodes(_tv_info.get("id"))
            if not tv_extra_info:
                return False
            release_year = []
            for item in tv_extra_info["episodes"]["items"]:
                if item.get("season") == season_number:
                    release_year.append(item.get("releaseDate").get("year") or item.get("releaseYear"))
                first_release_year = min(release_year) if release_year else tv_extra_info["currentYear"]
                if first_release_year == _season_year:
                    _tv_info["seasons"] = tv_extra_info["seasons"]
                    _tv_info["episodes"] = tv_extra_info["episodes"]
                    return True

        tvs = self.search_tvs(title=name)
        if (tvs is None) or (len(tvs) == 0):
            logger.debug("%s 未找到季%s相关信息!" % (name, season_number))
            return {}
        tvs = sorted(
            tvs,
            key=lambda x: str(x.get('y') or '0000'),
            reverse=True
        )
        for tv in tvs:
            tv_info = self.imdbid(tv.get("id"))
            if not tv_info:
                continue
            tv_year = f"{tv.get('y')}" if tv.get('y') else None
            if (self.__compare_names(name, [tv_info.get('primary_title')])
                or (tv_info.get('original_title') and self.__compare_names(name, [tv_info.get('original_title')]))) \
                    and (tv_year == str(season_year)):
                return tv_info
            akas = self.__known_as(tv.get("id"))
            if not akas:
                continue
            akas_names = [item.get("title") for item in akas]
            if not self.__compare_names(name, akas_names):
                continue
            if __season_match(_tv_info=tv_info, _season_year=season_year):
                return tv_info

    def get_info(self,
                 mtype: MediaType,
                 imdbid: str) -> dict:
        """
                给定IMDB号，查询一条媒体信息
                :param mtype: 类型：电影、电视剧，为空时都查（此时用不上年份）
                :param imdbid: IMDB的ID
                """
        # 查询TMDB详情
        if mtype == MediaType.MOVIE:
            imdb_info = self.imdbid(imdbid)
            if imdb_info:
                imdb_info['media_type'] = MediaType.MOVIE
        elif mtype == MediaType.TV:
            imdb_info = self.imdbid(imdbid)
            if imdb_info:
                imdb_info['media_type'] = MediaType.TV
                tv_extra_info = self.__episodes(imdbid)
                imdb_info["seasons"] = tv_extra_info["seasons"]
                imdb_info["episodes"] = tv_extra_info["episodes"]
        else:
            imdb_info = None
            logger.warn(f"IMDb id:{imdbid} 未查询到媒体信息")
        return imdb_info

    def match_multi(self, name: str) -> Optional[dict]:
        """
        根据名称同时查询电影和电视剧，没有类型也没有年份时使用
        :param name: 识别的文件名或种子名
        :return: 匹配的媒体信息
        """

        multis = self.search_tvs(name) + self.search_movies(name)
        ret_info = {}
        if len(multis) == 0:
            logger.debug(f"{name} 未找到相关媒体息!")
            return {}
        else:
            multis = sorted(
                multis,
                key=lambda x: ("1" if x.get("media_type") == MediaType.MOVIE else "0") + str(x.get('y') or '0000'),
                reverse=True
            )
            media_t = MediaType.UNKNOWN
            for multi in multis:
                media_info = self.imdbid(multi.get("id"))
                if not media_info:
                    continue
                if multi.get("media_type") == MediaType.MOVIE:
                    if self.__compare_names(name, media_info.get('primary_title')) \
                            or self.__compare_names(name, multi.get('primary_title')):
                        ret_info = media_info
                        media_t = MediaType.MOVIE
                        break
                elif multi.get("media_type") == MediaType.TV:
                    if self.__compare_names(name, media_info.get('primary_title')) \
                            or self.__compare_names(name, multi.get('primary_title')):
                        ret_info = media_info
                        media_t = MediaType.TV
                        break
        if ret_info and not isinstance(ret_info.get("media_type"), MediaType):
            ret_info['media_type'] = media_t
        return ret_info

    def match(self, name: str,
              mtype: MediaType,
              year: Optional[str] = None,
              season_year: Optional[str] = None,
              season_number: Optional[int] = None,
              group_seasons: Optional[List[dict]] = None) -> Optional[dict]:
        """
                搜索imdb中的媒体信息，匹配返回一条尽可能正确的信息
                :param name: 检索的名称
                :param mtype: 类型：电影、电视剧
                :param year: 年份，如要是季集需要是首播年份(first_air_date)
                :param season_year: 当前季集年份
                :param season_number: 季集，整数
                :param group_seasons: 集数组信息
                :return: TMDB的INFO，同时会将mtype赋值到media_type中
        """
        if not name:
            return None
        info = {}
        if mtype != MediaType.TV:
            year_range = [year]
            if year:
                year_range.append(str(int(year) + 1))
                year_range.append(str(int(year) - 1))
            for year in year_range:
                logger.debug(
                    f"正在识别{mtype.value}：{name}, 年份={year} ...")
                info = self.__search_movie_by_name(name, year)
                if info:
                    info['media_type'] = MediaType.MOVIE
                    break
        else:
            # 有当前季和当前季集年份，使用精确匹配
            if season_year and season_number:
                logger.debug(
                    f"正在识别{mtype.value}：{name}, 季集={season_number}, 季集年份={season_year} ...")
                info = self.__search_tv_by_season(name,
                                                  season_year,
                                                  season_number)
            if not info:
                year_range = [year]
                if year:
                    year_range.append(str(int(year) + 1))
                    year_range.append(str(int(year) - 1))
                for year in year_range:
                    logger.debug(
                        f"正在识别{mtype.value}：{name}, 年份={year} ...")
                    info = self.__search_tv_by_name(name, year)
                    if info:
                        break
            if info:
                info['media_type'] = MediaType.TV
                if not info.get("seasons"):
                    tv_extra_info = self.__episodes(info.get('id'))
                    if tv_extra_info:
                        info["seasons"] = tv_extra_info["seasons"]
                        info["episodes"] = tv_extra_info["episodes"]
        return info
