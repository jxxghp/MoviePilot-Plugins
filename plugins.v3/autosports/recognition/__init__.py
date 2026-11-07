import base64
import datetime
import json
import math
import re
import time
import unicodedata
from copy import deepcopy
from dataclasses import fields
from typing import Optional, List


from app import schemas
from app.schemas import TmdbEpisode
from app.schemas.types import MediaType, MediaSource
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.media import MediaInfo, TorrentInfo, MetaVideo, MetaBase
from app.sdk.network import RequestUtils


from app.plugins.autosports.recognition.competitions import _COMPETITION_LOGOS, get_raw_competitions_parse


# 种子标题中跟在队名后的转播、压制、语言等噪音词，比较队名前需要剔除
_TEAM_NAME_TAIL_NOISE = frozenset({
    "int", "international", "feed", "sat", "sun", "hd", "fhd", "uhd", "sd",
    "dazn", "paramount", "tnt", "sports", "sport", "sky", "esp", "eng", "spa",
    "ita", "ger", "fra", "por", "pre", "post", "game", "match", "full", "show",
    "ppv", "raw", "hq", "web", "stan",
})

class Recognition:

    """AutoSports recognition 相关方法。"""

    def _competition_logo(self, competition_name: str = "") -> str:
        """
        返回赛事 logo 地址，用于插件数据页展示。

        内置赛事按 football-data.org 缩写取官方队徽；自定义赛事可以在配置里用
        ``logo`` 字段覆盖，没有配置时返回空字符串。

        :param competition_name: 赛事中文名
        :return: logo 图片地址，未知赛事返回空字符串
        """
        if not competition_name:
            return ""
        for competition_parse in self._competitions_parses:
            if competition_parse.get("title") != competition_name:
                continue
            logo = competition_parse.get("logo") or _COMPETITION_LOGOS.get(
                competition_parse.get("shortname") or "", "")
            if logo:
                return logo
        return ""

    def _match_crest_pair(self, matchmake: str = "") -> tuple:
        """
        返回对阵双方的球队 crest 地址。

        :param matchmake: 对阵文本，格式为“主队 vs 客队”
        :return: (主队 crest, 客队 crest)，未记录时为空字符串
        """
        return self._match_crests.get(matchmake or "", ("", ""))

    def get_media_source(self) -> List[dict]:
        """
        注册体育赛事媒体数据源。

        数据源只描述展示信息；实际识别能力由 get_module() 暴露的
        recognize_media 提供，未选中该来源时不会介入任何识别。

        :return: 媒体来源声明列表
        """
        try:
            return [schemas.MediaSourceInfo(
                name=self.MEDIA_SOURCE_NAME,
                media_source=MediaSource(self.MEDIA_SOURCE),
                media_types=[MediaType.TV],
            ).model_dump()]
        except Exception as err:
            logger.error(f"注册体育赛事媒体数据源失败：{str(err)}")
            return []

    def recognize_media(self, meta: MetaBase = None, mtype: MediaType = None,
                        media_source: MediaSource = None, media_id: str = None,
                        **kwargs) -> Optional[MediaInfo]:
        """
        按体育比赛规则识别媒体信息。

        只有请求显式指定本插件数据源时才处理，其它来源（含未指定来源的普通影视、
        音乐识别）一律返回 None，保证插件规则不会影响宿主原有识别流程。

        :param meta: 标题元数据，可按其中的赛事、赛季和轮次识别
        :param mtype: 媒体类型
        :param media_source: 请求指定的媒体数据源
        :param media_id: 插件数据源内的比赛标识
        :return: 体育赛事媒体信息；非本插件来源或无法识别时返回 None
        """
        if not media_source:
            return None
        try:
            if MediaSource(media_source) != MediaSource(self.MEDIA_SOURCE):
                return None
        except ValueError:
            return None
        if media_id:
            mediainfo = self._build_sports_mediainfo(str(media_id))
            if mediainfo:
                return mediainfo
        if meta:
            return self._recognize_sports_media(meta)
        return None

    async def async_recognize_media(self, **kwargs) -> Optional[MediaInfo]:
        """
        异步识别入口，复用同步识别逻辑。

        :param kwargs: 与 recognize_media 相同的命名参数
        :return: 体育赛事媒体信息；非本插件来源或无法识别时返回 None
        """
        return self.recognize_media(**kwargs)

    def _recognize_sports_media(self, meta: MetaBase) -> Optional[MediaInfo]:
        """
        按插件内置规则把标题识别为体育赛事媒体。

        :param meta: 待识别的标题元数据
        :return: 含插件来源身份的比赛媒体信息；无法识别时返回 None
        """
        if not meta or not self._football_apikey:
            return None
        try:
            competition = self.recognize_competition_mediainfo(meta_info=meta)
            if not competition:
                return None
            match_meta, _ = self.recognized_match_metainfo(competition, meta)
            if not match_meta:
                return None
            metadata = {
                "c": competition.title,
                "s": match_meta.begin_season,
                "e": match_meta.begin_episode,
                "d": match_meta.subtitle,
            }
            return self._build_sports_mediainfo(self._encode_media_id(metadata))
        except Exception as err:
            logger.debug(f"体育赛事识别失败：{str(err)}")
            return None

    def _build_sports_mediainfo(self, media_id: str) -> Optional[MediaInfo]:
        """
        由插件数据源标识还原比赛媒体信息。

        :param media_id: 插件数据源内的比赛标识
        :return: 比赛媒体信息；标识无效时返回 None
        """
        metadata = self._decode_media_id(media_id)
        if not metadata:
            return None
        competition_title = metadata.get("c")
        competition = next(
            (item for item in self._competitions_parses if item.get("title") == competition_title),
            None,
        )
        if not competition:
            return None
        mediainfo = MediaInfo()
        self.scrape_competition(mediainfo, competition)
        mediainfo.type = MediaType.TV
        mediainfo.category = self._category
        mediainfo.title = competition_title
        season = metadata.get("s")
        mediainfo.season = season if isinstance(season, int) else None
        mediainfo.year = str(season) if isinstance(season, int) else mediainfo.year
        match_name = metadata.get("d") or ""
        names = [name for name in (match_name, *match_name.split(" vs ")) if name]
        if names:
            mediainfo.names = list(dict.fromkeys([*(mediainfo.names or []), *names]))
        mediainfo.media_source = MediaSource(self.MEDIA_SOURCE)
        mediainfo.media_id = media_id
        return mediainfo

    @staticmethod
    def _encode_media_id(metadata: dict) -> str:
        """
        把比赛信息编码为可安全传递的媒体标识。

        :param metadata: 赛事、赛季、轮次和对阵信息
        :return: URL 安全的 base64 字符串
        """
        raw = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_media_id(media_id: str) -> Optional[dict]:
        """
        解析插件数据源内的比赛标识。

        :param media_id: URL 安全的 base64 字符串
        :return: 比赛信息字典；格式无效时返回 None
        """
        try:
            padded = media_id + "=" * (-len(media_id) % 4)
            metadata = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            return metadata if isinstance(metadata, dict) else None
        except Exception:
            return None

    def get_match_raw_metadata_offline(self, metainfo: MetaVideo = None, matched_competition_parse: json = None,
                                       home_team: str = '', away_team: str = ''):
        """
            从本地定义的元数据中获取比赛信息
        """
        match = {
            "competition":{
                "type": matched_competition_parse.get("type"),
            },
            "stage": 'KNOCKOUT_STAGE',
            "matchday": 0,
            "round_cn_name": "",
            "round_en_name": "",
            "homeTeam": {
                "name": "",
            },
            "awayTeam": {
                "name": "",
            },
        }

        match_org_title = metainfo.org_string
        match_org_title = match_org_title.lower()
        offline_info = matched_competition_parse.get("offline_info")

        # 包装比赛日信息
        # 计算比赛轮次
        match_org_title = match_org_title.lower()

        for pattern, team_count in self.knockout_parse.items():
            if re.search(pattern, match_org_title, re.IGNORECASE):
                single_start_num = offline_info.get("knockout_single")
                double_start_num = offline_info.get("knockout_double")
                if offline_info.get('knockout_double') < team_count:
                    # 还没到主客场淘汰赛阶段
                    match["matchday"] = int(math.log2(single_start_num / team_count)) + 1
                    match["round_cn_name"] = f"{self.number_to_chinese(team_count)}强赛"
                    match["round_en_name"] = f"R{self.number_to_chinese(team_count)}"
                    if team_count == 4:
                        # 判断是否为半决赛
                        match["round_cn_name"] = f"半决赛"
                        match["round_en_name"] = f"Semi Finals"
                    if team_count == 2:
                        # 决赛
                        match["round_cn_name"] = f"决赛"
                        match["round_en_name"] = f"The Final"
                else:
                    # 到了主客场双淘汰赛阶段
                    match["matchday"] = (int(math.log2(single_start_num / double_start_num)) + 1 +
                                         int(math.log2(double_start_num / team_count)) * 2)
                    match["round_cn_name"] = f"{self.number_to_chinese(team_count)}强赛"
                    match["round_en_name"] = f"R{team_count}"
                    if team_count == 4:
                        # 判断是否为半决赛
                        match["round_cn_name"] = f"半决赛 首回合"
                        match["round_en_name"] = f"Semi Finals 1st Leg"
                        if re.search(r'\b(?:leg\s*(?:2|2nd)|(?:2|2nd)\s*leg)\b', match_org_title, re.IGNORECASE):
                            match["matchday"] += 1
                            match["round_cn_name"] = f"半决赛 次回合"
                            match["round_en_name"] = f"Semi Finals 2nd Leg"
                    if team_count == 2:
                        # 决赛
                        match["round_cn_name"] = f"决赛"
                        match["round_en_name"] = f"The Final"
                break

        if match["matchday"] == 0:
            logger.warning(f"轮次未识别成功，建议手动修订: {metainfo.title}")
        else:
            logger.info(f"识别到轮次：{match["matchday"]}")


        # 包装对阵信息
        match['homeTeam']['name'] = home_team
        match['awayTeam']['name'] = away_team

        return match

    @staticmethod
    def normalize_team_name(name: str) -> str:
        """
        把球队名规范化为可比较的形式。

        去掉变音符号（如 Alavés -> Alaves）、统一大小写并清理标点，
        使种子标题里的英文队名能与 football-data.org 返回的队名对齐。

        :param name: 原始球队名
        :return: 规范化后的球队名，空值时返回空字符串
        """
        if not name:
            return ""
        normalized = unicodedata.normalize("NFKD", str(name))
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = normalized.casefold().replace("&", " and ")
        normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
        return " ".join(normalized.split())

    @classmethod
    def team_name_score(cls, names: list[str], full_name: str = "", short_name: str = "") -> int:
        """
        计算标题队名与 API 队名的匹配强度。

        先剔除标题里跟在队名后的转播/压制噪音词，再按强度比较：
        3 完全相同、2 词集合相同、1 互相包含或词集合包含、0 不匹配；
        同强度时名字多出的词越少得分越高，所以 ``Barcelona`` 更倾向
        ``FC Barcelona`` 而不是 ``RCD Espanyol de Barcelona``。

        :param names: 从种子标题中解析出的队名片段
        :param full_name: API 返回的球队全名
        :param short_name: API 返回的球队简称
        :return: 越大越可信的匹配得分，0 表示不匹配
        """
        candidates = [
            cls.normalize_team_name(full_name),
            cls.normalize_team_name(short_name),
        ]
        best = 0
        for name in names or []:
            name_tokens = cls.normalize_team_name(name).split()
            # 去掉队名末尾的转播、压制、语言等噪音词
            while name_tokens and name_tokens[-1] in _TEAM_NAME_TAIL_NOISE:
                name_tokens.pop()
            if not name_tokens:
                continue
            name_normalized = " ".join(name_tokens)
            name_tokens_set = set(name_tokens)
            for candidate in candidates:
                if not candidate:
                    continue
                candidate_tokens = set(candidate.split())
                # 名字比候选多出的词越少越可信
                extra_tokens = max(len(candidate_tokens - name_tokens_set), 0)
                if name_normalized == candidate:
                    strength = 3
                elif name_tokens_set == candidate_tokens:
                    strength = 2
                elif name_normalized in candidate or candidate in name_normalized:
                    strength = 1
                elif name_tokens_set <= candidate_tokens or candidate_tokens <= name_tokens_set:
                    strength = 1
                else:
                    continue
                best = max(best, strength * 10 - min(extra_tokens, 9))
        return best

    @classmethod
    def team_name_matches(cls, names: list[str], full_name: str = "", short_name: str = "") -> bool:
        """
        判断标题里解析出的队名是否与 API 返回的队名指同一支球队。

        :param names: 从种子标题中解析出的队名片段
        :param full_name: API 返回的球队全名
        :param short_name: API 返回的球队简称
        :return: 命中任意一支球队时返回 True
        """
        return cls.team_name_score(names, full_name, short_name) > 0

    def get_match_raw_metadata_online(self, competition_shortname: str = '', season:int = 0,
                                      home_team: list[str] = '', away_team: list[str] = '',
                                      match_date: tuple = None):
        """
            从 football-data.org 获取比赛信息

            :param competition_shortname: 赛事在 football-data.org 的缩写
            :param season: 赛季起始年份
            :param home_team: 标题中解析出的主队名片段
            :param away_team: 标题中解析出的客队名片段
            :param match_date: 标题中的比赛日期 (年, 月, 日)，用于消歧同队多场比赛
            :return: 匹配到的比赛原始数据
        """
        headers = {
            "X-Auth-Token": self._football_apikey,
            "Accept": "application/json"
        }

        proxies = settings.PROXY if self._proxy else None

        url = f"https://api.football-data.org/v4/competitions/{competition_shortname}/matches"
        params = {
            "season": season
        }

        requests_key = competition_shortname + "_" + str(season)
        # 短时间内失败过的赛事直接跳过，避免同一轮对同一接口反复重试
        failed_at = self._failed_matches.get(requests_key)
        if failed_at and time.time() - failed_at < self._FAILED_MATCH_TTL:
            logger.debug(f"{requests_key} 最近请求失败，本次跳过重复请求")
            return None
        # 判断当前订阅是否已经在缓存中，如果已经处理过，那么这里直接跳过
        if requests_key in self._cached_matches.keys():
            data = self._cached_matches.get(requests_key)
            logger.debug(f"从缓存 {requests_key} 中读取 football-data.org 赛事数据...")
        else:
            logger.debug(f"从 {url} 中读取 football-data.org 赛事数据...")
            resp = RequestUtils(headers=headers, proxies=proxies, timeout=30).get_res(url, params=params)
            if not resp:
                logger.warning(f"请求 football-data.org 失败，请检查网络或插件代理设置，"
                               f"competition_shortname: {competition_shortname}，season: {season}")
                self._failed_matches[requests_key] = time.time()
                return None
            if resp.status_code != 200:
                logger.warning(f"football-data.org 返回状态码 {resp.status_code}，"
                               f"competition_shortname: {competition_shortname}，season: {season}，"
                               f"响应：{resp.text[:200]}")
                self._failed_matches[requests_key] = time.time()
                return None
            try:
                data = resp.json()
            except ValueError:
                logger.warning(f"football-data.org 返回内容不是合法 JSON，"
                               f"competition_shortname: {competition_shortname}，season: {season}")
                self._failed_matches[requests_key] = time.time()
                return None
            self._cached_matches[requests_key] = data
            self._failed_matches.pop(requests_key, None)

        if "matches" not in data:
            logger.warning(f"未在 football-data.org 上获取到比赛信息，请检查"
                           f"输入信息，competition_shortname: {competition_shortname}，"
                           f"season: {season}")
            self._failed_matches[requests_key] = time.time()
            return None

        # 在所有赛程里挑匹配强度最高的一场，避免“巴萨”先命中西班牙人这类只包含队名的球队
        best_match = None
        best_score = 0
        for match in data["matches"]:
            home_team_info = match.get("homeTeam") or {}
            away_team_info = match.get("awayTeam") or {}
            # 全名 (优先匹配) 与简称
            home = home_team_info.get("name")
            away = away_team_info.get("name")
            home_short = home_team_info.get("shortName")
            away_short = away_team_info.get("shortName")
            if not home or not away:
                # 该比赛还未排期，后面的比赛也同样没排期，直接退出循环
                break

            home_score = self.team_name_score(home_team, home, home_short)
            away_score = self.team_name_score(away_team, away, away_short)
            if not home_score or not away_score:
                continue
            score = home_score + away_score
            # 标题里带完整日期时，日期相同或相差一天视为同一场，优先于仅队名命中
            if match_date and self._match_date_within(match, match_date):
                score += 50
            if score > best_score:
                best_score = score
                best_match = match

        return best_match

    @staticmethod
    def _match_date_within(match: dict, match_date: tuple) -> bool:
        """
        判断 API 比赛的日期是否与标题日期一致（允许时区造成的一天偏差）。

        :param match: football-data.org 的单场比赛数据
        :param match_date: 标题中解析出的 (年, 月, 日)
        :return: 日期一致或相差一天时返回 True
        """
        try:
            utc_date = datetime.datetime.fromisoformat(
                str(match.get("utcDate") or "").replace("Z", "+00:00"))
            wanted = datetime.date(*match_date)
            return abs((utc_date.date() - wanted).days) <= 1
        except Exception:
            return False

    def get_match_raw_metadata(self, metainfo: MetaBase = None, competition_name:str = '', season:int = 0,
                               home_team: list[str] = '', away_team: list[str] = '',
                               match_date: tuple = None):
        """
          刮削单场比赛元数据
        """
        if not metainfo or not competition_name or not season or not home_team or not away_team:
            logger.error(f'缺少必须比赛信息，无法进行刮削，'
                         f'metainfo: {metainfo}, competition_name: {competition_name}，'
                         f'season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None

        matched_competition_parse = {}
        competition_shortname = ''
        competition_offline_info = {}

        # 寻找比赛缩写
        for competition_parse in self._competitions_parses:
            if competition_name == competition_parse["title"]:
                matched_competition_parse = competition_parse
                competition_shortname = competition_parse.get("shortname")
                competition_offline_info = competition_parse.get("offline_info")
                break
            else:
                continue

        # 判断是进行在线刮削还是离线刮削
        if not competition_offline_info:
            # 未定义离线信息，在线刮削
            logger.debug(f"在线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_online(competition_shortname, season, home_team, away_team,
                                                              match_date=match_date)
        else:
            # 定义离线信息，离线刮削
            logger.debug(f"离线刮削赛事 {competition_name} 中的比赛")
            match_result = self.get_match_raw_metadata_offline(metainfo, matched_competition_parse, home_team[0], away_team[0])

        if match_result:
            return match_result
        else:
            logger.warning(f'未匹配到相关比赛，请检查输入信息，competition_name: {competition_name}，season: {season}, home_team: {home_team}, away_team: {away_team}')
            return None

    def recognized_match_metainfo(self, match_mediainfo: MediaInfo, metainfo: MetaBase) -> (MetaBase | None, TmdbEpisode | None) :
        """
          根据给定的规则刮削单场比赛信息
        """
        match_metainfo = deepcopy(metainfo)
        episode_metainfo = TmdbEpisode()

        competition_cn_name = match_mediainfo.title

        org_str = metainfo.org_string
        # 标题里的完整比赛日期，用于推算赛季并消歧同队多场比赛
        match_date = self.extract_date(org_str)
        season_from_date = match_date is not None
        # 获取赛季信息
        try:
            season_name = metainfo.year
            if season_from_date:
                # 有完整日期时以日期为准：七月之后属于当年开始的赛季
                season = match_date[0] - 1 if match_date[1] < 7 else match_date[0]
            elif not season_name:
                logger.warning("未获取到比赛日期")
                logger.warning("未成功匹配到赛季信息，跳过")
                return None, None
            else:
                season = int(season_name)

            # 赛季数修正（仅依据标题年份推算的赛季需要修正，日期推算的更准确）
            season_spaced_str = re.sub(r"[._/]+", " ", org_str or "")
            if not season_from_date and any(
                season_str in org_str or season_str.replace(".", " ") in season_spaced_str
                for season_str in
                [
                    str(season - 1) + "." + str(season),
                    str(season - 1) + "/" + str(season)
                ]):
                # 适配特殊格式的西甲比赛
                season -= 1
                match_mediainfo.season = season
            if (not season_from_date and match_mediainfo.title in ["西班牙超级杯", "西班牙国王杯"]
                and season == datetime.date.today().year):
                # 杯赛特殊处理
                season -= 1
                match_mediainfo.season = season
            if not season_from_date and season == datetime.date.today().year \
                    and datetime.date.today().month < 8:
                # 联赛前九月视为上一个赛季
                season -= 1
                match_mediainfo.season = season

            # 年份信息回填赛事元数据
            metainfo.year = str(season)

            season_shortname = season % 100
            # 解析赛季信息
            season_cn_name = f"{season_shortname:02d}-{(season_shortname + 1):02d}赛季"
            season_en_name = f"Season {season_shortname:02d}-{(season_shortname + 1):02d}"
            match_mediainfo.season = int(metainfo.year)
            logger.info(f"成功匹配到赛季信息：{season_cn_name}")
        except AttributeError:
            logger.warn("未成功匹配到赛季信息，跳过")
            return None, None

        # 分析主客场球队
        try:
            # 点、下划线分隔统一成空格后再匹配；队名允许 - & ' 等真实字符
            org_match_str = re.sub(r"[._]+", " ", org_str or "")
            team_chars = r"[A-Za-zÀ-ÿ&'\- ]"
            # 匹配对阵信息
            matchup = re.search(
                rf'({team_chars}+?)\s+vs\s+({team_chars}+?)(?=\s*\||\s+\d|\.|$)',
                org_match_str, re.IGNORECASE)
            if not matchup:
                # 适配种子名里有 'v.s.' 等简写格式
                matchup = re.search(
                    rf'({team_chars}+?)\s*\.?\s*v\.?\s*s\.?\s*\.?\s*({team_chars}+?)(?=\s*\||\s+\d|\.|$)',
                    org_match_str, re.IGNORECASE)
            if not matchup:
                # 适配种子名里有 ',' 的格式
                matchup = re.search(
                    rf'({team_chars}+?)\s+vs\s+({team_chars}+?)(?=\s*\||\s+\d|\.|,|$)',
                    org_match_str, re.IGNORECASE)
            if not matchup:
                # 匹配带有转播信息，压制信息等后缀的格式
                matchup = re.search(
                    r'(.+?)\s+vs\s+(.+?)(?=\s+(?:WEB|HDTV|UHD|BluRay|\d{3,4}p)|$)',
                    org_match_str,
                    re.IGNORECASE
                )

            home_team: list[str] = re.findall(r'\D+', matchup.group(1))
            away_team: list[str] =  re.findall(r'\D+', matchup.group(2))

            # 组装名称中的非法字符排除器
            illegal_fix = []
            # 各赛事名
            for competition_parse in self._competitions_parses:
                illegal_fix.extend(competition_parse.get("names") or [])
            # 赛事阶段标识
            illegal_fix.extend(["League Phase", "st leg", "st Leg", "WEB", "STAN"])

            # 处理主队名：去掉多余的前后缀
            home_team = [home_team_str_i.strip(" -&'") for home_team_str_i in home_team]
            for p in illegal_fix:
                for i, home_team_str_i in enumerate(home_team):
                    if home_team_str_i.startswith(p):
                        home_team[i] = home_team_str_i[len(p):]
                    elif home_team_str_i.endswith(p):
                        home_team[i] = home_team_str_i[:-len(p)]
            home_team = [home_team_str_i.strip(" -&'") for home_team_str_i in home_team]

            # 处理客队名：去掉多余的前后缀
            away_team = [away_team_str_i.strip(" -&'") for away_team_str_i in away_team]
            for p in illegal_fix:
                for i, away_team_str_i in enumerate(away_team):
                    if away_team_str_i.startswith(p):
                        away_team[i] = away_team_str_i[len(p):]
                    elif away_team_str_i.endswith(p):
                        away_team[i] = away_team_str_i[:-len(p)]
            away_team = [away_team_str_i.strip(" -&'") for away_team_str_i in away_team]

            # 去掉长度过短的字符串
            min_len = 3
            home_team = [home_team_str_i for home_team_str_i in home_team if len(home_team_str_i) >= min_len]
            away_team = [away_team_str_i for away_team_str_i in away_team if len(away_team_str_i) >= min_len]
            logger.info(f"成功匹配到对阵信息：{home_team} vs {away_team}")
        except AttributeError:
            logger.warning("未成功匹配到对阵信息，跳过")
            return None, None

        # 获取比赛相关元数据
        raw_matchdata = self.get_match_raw_metadata(metainfo, competition_cn_name, season, home_team, away_team,
                                                    match_date=match_date)
        if not raw_matchdata:
            logger.warning("未获取到比赛元数据，跳过")
            return None, None

        # 解析轮次信息
        # 根据赛事类型决定解析方式
        if raw_matchdata['competition']['type'] != 'CUP':
            # 联赛，比赛日即为轮次
            try:
                round_info = raw_matchdata['matchday']
                round_cn_name = f"第{self.number_to_chinese(round_info)}轮"
                round_en_name = f"Round {round_info}"
                logger.info(f"成功匹配到轮次信息：{round_cn_name}")
            except AttributeError:
                logger.warn("未成功匹配到轮次信息，跳过")
                return None, None
        else:
            round_info = raw_matchdata['matchday']
            if raw_matchdata['stage'] == 'LEAGUE_STAGE':
                # 小组赛阶段
                round_cn_name = f"联赛阶段 第{self.number_to_chinese(round_info)}轮"
                round_en_name = f"Group Stage Round {round_info}"
            else:
                if competition_cn_name == "欧洲冠军联赛":
                    # 欧冠赛制特殊处理
                    # football-data.org stage 字段映射
                    stage_parse = {
                        'PLAYOFFS': 0,
                        'LAST_16': 1,
                        # 'LAST_8': 2,
                        'QUARTER_FINALS': 2,
                        'SEMI_FINALS': 3,
                        'FINAL': 4,
                    }
                    round_cn_name_list = [
                        "联赛阶段附加赛 首回合", "联赛阶段附加赛 次回合",
                        # "32强赛 首回合", "32强赛 次回合",
                        "十六强赛 首回合", "十六强赛 次回合",
                        "八强赛 首回合", "八强赛 次回合",
                        "半决赛 首回合", "半决赛 次回合",
                        "决赛"
                    ]
                    round_en_name_list = [
                        "联赛阶段附加赛 次回合", "联赛阶段附加赛 次回合",
                        # "R32 1st Round", "R32 2nd Round",
                        "R16 1st Round", "R16 2nd Round",
                        "R8 1st Round", "R8 2nd Round",
                        "Semi Finals 1st Round", "Semi Finals 2nd Round",
                        "Final"
                    ]
                    # 淘汰赛
                    stage = raw_matchdata.get('stage')
                    if stage not in stage_parse:
                        logger.warning(
                            f"未找到欧冠淘汰赛阶段 {stage} 对应的轮次信息，跳过：{metainfo.title or ''}")
                        return None, None
                    stage_index = stage_parse[stage]
                    round_idx = stage_index * 2 + raw_matchdata.get('matchday', 0) - 1
                    if not 0 <= round_idx < len(round_cn_name_list):
                        logger.warning(
                            f"欧冠淘汰赛阶段 {stage} 的轮次下标 {round_idx} 超出范围，跳过：{metainfo.title or ''}")
                        return None, None
                    round_info = 8 + stage_index * 2 + raw_matchdata.get('matchday', 0)
                    round_cn_name = round_cn_name_list[round_idx]
                    round_en_name = round_en_name_list[round_idx]
                else:
                    round_cn_name = raw_matchdata['round_cn_name']
                    round_en_name = raw_matchdata['round_en_name']
            logger.info(f"成功匹配到轮次信息：{round_cn_name}")

        # 解析对阵信息
        home_team = raw_matchdata['homeTeam']['name']
        away_team = raw_matchdata['awayTeam']['name']
        matchmake_en_name = matchmake_cn_name = f"{home_team} vs {away_team}"
        # 记录球队 crest 地址，供历史记录展示球队 logo
        home_crest = (raw_matchdata.get('homeTeam') or {}).get('crest') or ""
        away_crest = (raw_matchdata.get('awayTeam') or {}).get('crest') or ""
        if len(self._match_crests) > 500:
            self._match_crests.clear()
        self._match_crests[matchmake_cn_name] = (home_crest, away_crest)

        # 刮削比赛信息
        match_metainfo.cn_name = " - ".join([season_cn_name, round_cn_name, matchmake_cn_name])
        match_metainfo.en_name = " - ".join([season_en_name, round_en_name, matchmake_en_name])
        match_metainfo.type = MediaType.TV
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.subtitle = matchmake_cn_name
        match_metainfo.title = competition_cn_name
        match_metainfo.title_year = f"{competition_cn_name} ({season_cn_name})"
        match_metainfo.begin_episode = round_info
        match_metainfo.begin_season = season

        # 解析清晰度信息
        if any(pix_alia in org_str for pix_alia in ['4k', '4K', '2160p']):
            match_metainfo.resource_pix = '2160p'
        elif any(pix_alia in org_str for pix_alia in ['2k', '2K', '1440p']):
            match_metainfo.resource_pix = '1440p'

        # 刮削集信息
        match_date = raw_matchdata.get('utcDate')
        if match_date:
            match_date_utc = datetime.datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            match_date = match_date_utc.astimezone(tz=None)
        episode_metainfo.air_date = match_date
        episode_metainfo.episode_number = round_info
        episode_metainfo.name = match_metainfo.cn_name
        episode_metainfo.overview = match_metainfo.cn_name
        episode_metainfo.runtime = 90
        episode_metainfo.season_number = season

        return match_metainfo, episode_metainfo

    def recognize_competition_mediainfo(self, torrent_info: TorrentInfo = None, meta_info: MetaBase = None) -> MediaInfo | None:
        """
          根据自定义规则刮削赛事信息
        """
        competition_mediainfo = MediaInfo()

        if torrent_info:
            # 若传入了种子信息，从其中获取种子标题
            title = torrent_info.title
        else:
            # 否则，从文件元数据中获取文件标题
            title = meta_info.org_string

        # 文件名和部分种子标题用点、下划线分隔，归一化后再匹配赛事别名
        normalized_title = re.sub(r"[._]+", " ", title or "")
        for competition_parse in self._competitions_parses:
            if any(alia.lower() in title.lower() or alia.lower() in normalized_title.lower()
                   for alia in competition_parse["names"]):
                # 匹配任意一个别名，开始解析
                self.scrape_competition(competition_mediainfo, competition_parse)
                competition_mediainfo.type = MediaType.TV
                # competition_mediainfo.season = int(meta_info.year)
                competition_mediainfo.category = self._category
                break
            else:
                continue

        if not competition_mediainfo.title:
            # 未成功刮削，返回空对象
            logger.info(f"未识别到赛事信息")
            return None

        # 成功刮削，返回刮削后对象
        logger.info(f"成功匹配到赛事信息：{competition_mediainfo.title}")
        return competition_mediainfo

    @staticmethod
    def extract_date(s: str):
        """
            从种子名中提取日期
        """
        date_re = re.compile(
            r"""
            \b
            (?:                                  # 非捕获组：两种顺序
                ((?:19|20)\d{2})\s+(\d{1,2})\s+(\d{1,2})   # YYYY MM DD
              |
                (\d{1,2})\s+(\d{1,2})\s+((?:19|20)\d{2})   # DD MM YYYY
              |
                (\d{2})\.(\d{2})\.(\d{4})   # DD MM YYYY  
              |
                ((?:19|20)\d{2})\s*(\d{1,2})\s*(\d{1,2})   # YYYY MM DD 忽略空格
              |
                (\d{1,2})\s*(\d{1,2})\s*((?:19|20)\d{2})   # DD MM YYYY 忽略空格
            )
            \b
            """,
            re.VERBOSE
        )

        m = date_re.search(s)
        if not m:
            return None

        groups = m.groups()
        # 每个分支依次给出 (年, 月, 日) 在分组中的下标
        for year_index, month_index, day_index in (
            (0, 1, 2),     # YYYY MM DD
            (5, 4, 3),     # DD MM YYYY
            (8, 7, 6),     # DD.MM.YYYY
            (9, 10, 11),   # YYYYMMDD
            (14, 13, 12),  # DDMMYYYY
        ):
            if groups[year_index]:
                year, month, day = int(groups[year_index]), int(groups[month_index]), int(groups[day_index])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return year, month, day
                return None
        return None

    @staticmethod
    def recognize_language(metainfo: MetaVideo) -> str:
        """
        从种子标题中识别解说语言。
        """
        # 语言标识出现在种子标题里，赛事名中一般不体现，优先使用识别字符串
        source = metainfo.org_string or metainfo.name or ""
        if any(lang in source for lang in ["EN", "English"]):
            return "en"
        elif any(lang in source for lang in ["PL", "Polish", "POLISH"]):
            return "pl"
        elif any(lang in source for lang in ["Spanish", "SPANISH", "spanish"]):
            return "sp"
        elif any(lang in source for lang in ["French", "FRENCH", "french"]):
            return "fr"
        elif any(lang in source for lang in ["Dutch", "DUTCH", "drench"]):
            return "dt"

        # 默认英语
        return "en"

    @staticmethod
    def scrape_competition(matchinfo: MediaInfo, competition_parse: {}):
        """
          根据给定的 JSON 规则刮削体育比赛
        """
        for f in fields(matchinfo):
            if f.name in competition_parse:
                setattr(matchinfo, f.name, competition_parse[f.name])
        pass

    @staticmethod
    def recognized_saved_match_metainfo(metainfo: MetaBase) -> (MetaVideo | None, TmdbEpisode | None):
        """
          根据给定的规则刮削已入库的单场比赛的元数据
        """
        match_metainfo = deepcopy(metainfo)
        episode_metainfo = TmdbEpisode()

        competition_cn_name = metainfo.name

        org_str = metainfo.org_string

        # 解析集数信息
        season_round_info = re.search(r'\bS(\d+)E(\d+)\b', org_str, re.I)
        if not season_round_info:
            logger.warning(f"{metainfo.title or ''} 未识别到季集信息（SxxEyy），跳过")
            return None, None
        season = int(season_round_info.group(1))
        round_info = int(season_round_info.group(2))
        match_metainfo.set_season(season)
        match_metainfo.set_episode(round_info)
        match_metainfo.subtitle = ""
        match_metainfo.title = competition_cn_name
        match_metainfo.begin_episode = round_info
        match_metainfo.begin_season = season

        return match_metainfo, episode_metainfo

    @staticmethod
    def chinese_to_number(chinese_num: str) -> int:
        """
        将中文大写数字（如 第二十三季）转换为阿拉伯数字
        """
        char_to_digit = {
            '零': 0,
            '一': 1,
            '二': 2,
            '两': 2,
            '三': 3,
            '四': 4,
            '五': 5,
            '六': 6,
            '七': 7,
            '八': 8,
            '九': 9,
            '十': 10,
            '百': 100,
            '千': 1000,
            '万': 10000,
            '亿': 100000000
        }

        # 去除“第X季”的格式
        if chinese_num.startswith("第") and chinese_num.endswith("季"):
            chinese_num = chinese_num[1:-1]

        current_value = 0
        prev_value = 0

        i = 0
        while i < len(chinese_num):
            char = chinese_num[i]
            value = char_to_digit.get(char, None)

            if value is None:
                raise ValueError(f"不支持的字符：{char}")

            if value in [10, 100, 1000]:  # 处理“十百千”
                if prev_value == 0:
                    prev_value = 1  # 如“十五”中“十”前无数字，默认为1
                current_value += prev_value * value
                prev_value = 0
            else:
                prev_value = value
            i += 1

        current_value += prev_value  # 加上最后的个位数
        return current_value

    @staticmethod
    def number_to_chinese(num: int) -> str:
        """
        将阿拉伯数字转换为中文大写数字表示

        支持将整数转换为对应的中文字符表达，包括零、一到九的基础数字，
        以及十、百、千、万、亿等单位组合。适用于需要将数字以中文形式展示的场景。

        参数:
            num (int): 需要转换的整数

        返回:
            str: 转换后的中文大写数字字符串

        示例:
            输入: 1234
            输出: "一千二百三十四"
        """
        if num == 0:
            return "零"

        # 定义基础数字和单位
        digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        units = ["", "十", "百", "千"]  # 十进制单位
        large_units = ["", "万", "亿", "万亿"]  # 大单位

        def chunk(number: int) -> str:
            """
            将小于10000的数字分解并转换为中文表示

            参数:
                number (int): 小于10000的整数

            返回:
                str: 中文表示的字符串片段
            """
            res = ""
            count = 0
            while number > 0:
                digit = number % 10
                if digit != 0:
                    res = digits[digit] + units[count] + res
                else:
                    # 处理连续的零，避免出现多个“零”
                    if res and res[0] != '零':
                        res = '零' + res
                number //= 10
                count += 1
            return res

        result = ""
        chunk_index = 0
        while num > 0:
            part = num % 10000
            if part != 0:
                # 对每个不超过10000的部分进行处理，并加上对应的大单位
                result = chunk(part) + large_units[chunk_index] + result
            num //= 10000
            chunk_index += 1

        # 特殊情况处理，如"一十"应简化为"十"
        if result.startswith("一十"):
            result = result[1:]

        return result

    def _initialize_competition_config(self):
        """
        整合自定义赛事信息和内置赛事信息
        @return:
        """
        # 重置赛事元数据信息
        self._competitions_parses = get_raw_competitions_parse()

        # 只去掉整行注释，避免误伤字符串里的 http:// 等双斜杠内容
        selfdefined_competitions_config = re.sub(
            r'(?m)^\s*//.*$', '', self._competitions_config or "").strip()
        if not selfdefined_competitions_config:
            return
        try:
            custom_competitions = json.loads(selfdefined_competitions_config)
        except (TypeError, ValueError) as err:
            logger.error(f"自定义赛事配置不是合法 JSON，已忽略并使用内置赛事：{str(err)}")
            return
        if not isinstance(custom_competitions, list):
            logger.error("自定义赛事配置必须是数组（[]），已忽略并使用内置赛事")
            return
        for selfdefined_config in custom_competitions:
            if not isinstance(selfdefined_config, dict) or not selfdefined_config:
                # 自定义配置为空，跳过
                continue
            if selfdefined_config.get("homepage"):
                # 用户自定义了赛事配置
                selfdefined_config["homepage"] = f"https://{selfdefined_config['homepage']}"
            self._competitions_parses.append(selfdefined_config)
