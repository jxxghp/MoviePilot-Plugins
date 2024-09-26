import concurrent
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List
from app.chain.media import MediaChain
from app.chain.tmdb import TmdbChain
from app.core.metainfo import MetaInfoPath
from app.log import logger
from app.schemas import MediaType

season_patterns = [
    {"pattern": re.compile(r"S(\d+)$", re.IGNORECASE), "group": 1},
    {"pattern": re.compile(r"(\d+)$", re.IGNORECASE), "group": 1},
    {"pattern": re.compile(r"(\d+)(st|nd|rd|th)?\s*season", re.IGNORECASE), "group": 1},
    {"pattern": re.compile(r"(.*) ?\s*season (\d+)", re.IGNORECASE), "group": 2},
    {"pattern": re.compile(r"\s(II|III|IV|V|VI|VII|VIII|IX|X)$", re.IGNORECASE), "group": "1"}
]
episode_patterns = [
    {"pattern": re.compile(r"(\d+)\((\d+)\)", re.IGNORECASE), "group": 2},
    {"pattern": re.compile(r"(\d+)", re.IGNORECASE), "group": 1},
    {"pattern": re.compile(r'(\d+)v\d+', re.IGNORECASE), "group": 1},
]

ova_patterns = [
    re.compile(r".*?(OVA|OAD).*?", re.IGNORECASE),
    re.compile(r"\d+\.5"),
    re.compile(r"00")
]

final_season_patterns = [
    re.compile('final season', re.IGNORECASE),
    re.compile('The Final', re.IGNORECASE),
    re.compile(r'\sFinal')
]

movie_patterns = [
    re.compile("Movie", re.IGNORECASE),
    re.compile("the Movie", re.IGNORECASE),
]


@dataclass
class VCBMetaBase:
    # 转化为小写后的原始文件名称 (不含后缀)
    original_title: str = ""
    # 解析后不包含季度和集数的标题
    title: str = ""
    # 类型:TV / Movie (默认TV)
    type: str = "TV"
    # 可能含有季度的标题，一级解析后的标题
    season_title: str = ""
    # 可能含有集数的字符串列表
    ep_title: List[str] = None
    # 识别出来的季度
    season: int = None
    # 识别出来的集数
    ep: int = None
    # 是否是OVA/OAD
    is_ova: bool = False
    # TMDB ID
    tmdb_id: int = None


blocked_words = ["vcb-studio", "360p", "480p", "720p", "1080p", "2160p", "hdr", "x265", "x264", "aac", "flac"]


class ReMeta:

    def __init__(self, ova_switch: bool = False, custom_season_patterns: list[dict] = None):
        self.meta = None
        # TODO:自定义季度匹配规则
        self.custom_season_patterns = custom_season_patterns
        self.season_patterns = season_patterns
        self.ova_switch = ova_switch
        self.vcb_meta = VCBMetaBase()
        self.is_ova = False

    def is_tv(self, title: str) -> bool:
        """
        判断是否是TV
        """
        if title.count("[") != 4 and title.count("]") != 4:
            self.vcb_meta.type = "Movie"
            self.vcb_meta.title = re.sub(r'\[.*?\]', '', title).strip()
            return False
        return True

    def handel_file(self, file_path: Path):
        file_name = file_path.stem.strip().lower()
        self.vcb_meta.original_title = file_name
        if not self.is_tv(file_name):
            logger.warn(
                "不符合VCB-Studio的剧集命名规范，归类为电影,跳过剧集模块处理。注意：年份较为久远的作品可能在此会判断错误")
            self.parse_movie()
        else:
            self.tv_mode()
        self.is_ova = self.vcb_meta.is_ova
        meta = MetaInfoPath(file_path)
        meta.title = self.vcb_meta.title
        meta.en_name = self.vcb_meta.title
        if self.vcb_meta.type == "Movie":
            meta.type = MediaType.MOVIE
        else:
            meta.type = MediaType.TV
            if self.vcb_meta.ep is not None:
                meta.begin_episode = self.vcb_meta.ep
            if self.vcb_meta.season is not None:
                meta.begin_season = self.vcb_meta.season
        if self.vcb_meta.tmdb_id is not None:
            meta.tmdbid = self.vcb_meta.tmdb_id
        return meta

    def split_season_ep(self):
        # 把所有的[] 里面的内容获取出来,不需要[]本身
        self.vcb_meta.ep_title = re.findall(r'\[(.*?)\]', self.vcb_meta.original_title)
        # 去除所有[]后只剩下剧名
        self.vcb_meta.season_title = re.sub(r"\[.*?\]", "", self.vcb_meta.original_title).strip()
        if self.vcb_meta.ep_title:
            self.culling_blocked_words()
            logger.info(
                f"分离出包含可能季度的内容部分：{self.vcb_meta.season_title} | 可能包含集数的内容部分： {self.vcb_meta.ep_title}")
            self.vcb_meta.title = self.vcb_meta.season_title
        if not self.vcb_meta.ep_title:
            self.vcb_meta.title = self.vcb_meta.season_title
            logger.warn("未识别出可能存在集数位置的信息，跳过剩余识别步骤！")

    def tv_mode(self):
        logger.info("开始分离季度和集数部分")
        self.split_season_ep()
        if not self.vcb_meta.ep_title:
            return
        self.parse_season()
        self.parse_episode()

    def parse_season(self):
        """
        从标题中解析季度
        """
        flag = False
        for pattern in season_patterns:
            match = pattern["pattern"].search(self.vcb_meta.season_title)
            if match:
                if isinstance(pattern["group"], int):
                    self.vcb_meta.season = int(match.group(pattern["group"]))
                else:
                    self.vcb_meta.season = self.roman_to_int(match.group(pattern["group"]))
                # 匹配成功后，标题中去除季度信息
                self.vcb_meta.title = pattern["pattern"].sub("", self.vcb_meta.season_title).strip
                logger.info(f"识别出季度为{self.vcb_meta.season}")
                return
        logger.info(f"正常匹配季度失败，开始匹配ova/oad/最终季度")
        if not flag:
            # 匹配是否为最终季
            for pattern in final_season_patterns:
                if pattern.search(self.vcb_meta.season_title):
                    logger.info("命中到最终季匹配规则")
                    self.vcb_meta.title = pattern.sub("", self.vcb_meta.season_title).strip()
                    self.handle_final_season()
                    return
            logger.info("未识别出最终季度，开始匹配OVA/OAD")
            # 匹配是否为OVA/OAD
            if "ova" in self.vcb_meta.season_title or "oad" in self.vcb_meta.season_title:
                logger.info("季度部分命中到OVA/OAD匹配规则")
                if self.ova_switch:
                    logger.info("开启OVA/OAD处理逻辑")
                    self.vcb_meta.is_ova = True
                    for pattern in ova_patterns:
                        if pattern.search(self.vcb_meta.season_title):
                            self.vcb_meta.title = pattern.sub("", self.vcb_meta.season_title).strip()
                    self.vcb_meta.title = re.sub("ova|oad", "", self.vcb_meta.season_title).strip()
                    self.vcb_meta.season = 0
                    return
            logger.warn("未识别出季度,默认处理逻辑返回第一季")
            self.vcb_meta.title = self.vcb_meta.season_title
            self.vcb_meta.season = 1

    def parse_episode(self):
        """
        从标题中解析集数
        """
        # 从ep_title中剔除不相关的内容之后只剩下存在集数的字符串
        ep = self.vcb_meta.ep_title[0]
        for pattern in episode_patterns:
            match = pattern["pattern"].search(ep)
            if match:
                self.vcb_meta.ep = int(match.group(pattern["group"]))
                logger.info(f"识别出集数为{self.vcb_meta.ep}")
                return
        # 直接进入判断是否为OVA/OAD
        for pattern in ova_patterns:
            if pattern.search(ep):
                self.vcb_meta.is_ova = True
                # 直接获取数字
                self.vcb_meta.ep = int(re.search(r"\d+", ep).group()) or 1
                logger.info(f"OVA模式下识别出集数为{self.vcb_meta.ep}")
                self.vcb_meta.season = 0
                return

    def culling_blocked_words(self):
        """
        从ep_title中剔除不相关的内容
        """
        blocked_set = set(blocked_words)  # 将阻止词列表转换为集合
        result = [ep for ep in self.vcb_meta.ep_title if not any(word in ep for word in blocked_set)]
        self.vcb_meta.ep_title = result

    def handle_final_season(self):

        _, medias = MediaChain().search(title=self.vcb_meta.title)
        if not medias:
            logger.warning("匹配到最终季时无法找到对应的媒体信息！季度返回默认值：1")
            self.vcb_meta.season = 1
            return

        filter_medias = [media for media in medias if media.type == MediaType.TV]
        if not filter_medias:
            logger.warning("匹配到最终季时无法找到对应的媒体信息！季度返回默认值：1")
            self.vcb_meta.season = 1
            return
        medias = [media for media in filter_medias if media.popularity or media.vote_average]
        if not medias:
            logger.warning("匹配到最终季时无法找到对应的媒体信息！季度返回默认值：1")
            self.vcb_meta.season = 1
            return
        # 获取欢迎度最高或者评分最高的媒体
        medias_sorted = sorted(medias, key=lambda x: x.popularity or x.vote_average, reverse=True)[0]
        self.vcb_meta.tmdb_id = medias_sorted.tmdb_id
        if medias_sorted.tmdb_id:
            seasons_info = TmdbChain().tmdb_seasons(tmdbid=medias_sorted.tmdb_id)
            if seasons_info:
                self.vcb_meta.season = len(seasons_info)
                logger.info(f"获取到最终季度，季度为{self.vcb_meta.season}")
                return
        logger.warning("无法获取到最终季度信息，季度返回默认值：1")
        self.vcb_meta.season = 1



    def parse_movie(self):
        logger.info("开始尝试剧场版模式解析")
        for pattern in movie_patterns:
            if pattern.search(self.vcb_meta.title):
                logger.info("命中剧场版匹配规则,加上剧场版标识辅助识别")
                self.vcb_meta.type = "Movie"
                self.vcb_meta.title = pattern.sub("", self.vcb_meta.title).strip()
                self.vcb_meta.title = self.vcb_meta.title
                return

    def find_ova_episode(self):
        """
        搜索OVA的集数
        TODO:模糊匹配OVA的集数
        """
        pass


    @staticmethod
    def roman_to_int(s) -> int:
        """
        :param s: 罗马数字字符串
        罗马数字转整数
        """
        roman_dict = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        total = 0
        prev_value = 0

        for char in reversed(s):  # 反向遍历罗马数字字符串
            current_value = roman_dict[char]
            if current_value >= prev_value:
                total += current_value  # 如果当前值大于等于前一个值，加上当前值
            else:
                total -= current_value  # 如果当前值小于前一个值，减去当前值
            prev_value = current_value

        return total



# if __name__ == '__main__':
#     ReMeta(
#         ova_switch=True,
#     ).handel_file(Path(
#         r"[Airota&Nekomoe kissaten&VCB-Studio] Yuru Camp [Heya Camp EP00][Ma10p_1080p][x265_flac].mkv"))
