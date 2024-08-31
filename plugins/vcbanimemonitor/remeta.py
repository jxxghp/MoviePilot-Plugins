import concurrent
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List
from app.chain.media import MediaChain
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
                "不符合VCB-Studio的剧集命名规范，归类为电影,跳过剧集模块处理。注意：年份较为久远的作品可能会判断错误")
        else:
            self.tv_mode()
        self.is_ova = self.vcb_meta.is_ova
        meta = MetaInfoPath(file_path)
        meta.title = self.vcb_meta.title
        meta.en_name = self.vcb_meta.title
        meta.begin_season = self.vcb_meta.season
        if self.vcb_meta.ep:
            meta.begin_episode = self.vcb_meta.ep
        if self.vcb_meta.type == "Movie":
            meta.type = MediaType.MOVIE
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
                logger.info(f"识别出集数为{self.vcb_meta.ep}")
                return

    def culling_blocked_words(self):
        """
        从ep_title中剔除不相关的内容
        """
        blocked_set = set(blocked_words)  # 将阻止词列表转换为集合
        result = [ep for ep in self.vcb_meta.ep_title if not any(word in ep for word in blocked_set)]
        self.vcb_meta.ep_title = result

    def handle_final_season(self):

        meta, medias = MediaChain().search(title=self.vcb_meta.title)
        if not medias:
            logger.warning("匹配到最终季时无法找到对应的媒体信息！季度返回默认值：1")
            self.vcb_meta.season = 1
            return

        max_season_number = 1
        # 当没有季度参考时用评分来决定
        vote_average = 0
        season_info = False
        for media in medias:
            if media.type != MediaType.TV:
                logger.info(f"搜索到的: {media.title}, 媒体类型为 {media.type}，跳过")
                continue
            if media.season_info:
                season_info = True
                last_season_number = int(media.season_info[-1].get("season_number", 1))
                if last_season_number > max_season_number:
                    max_season_number = last_season_number
            else:
                logger.info(f"媒体: {media.title} 没有季信息，跳过")
        if not season_info:
            # 备用方案
            for media in medias:
                if media.seasons:
                    seasons: dict
                    # 获取最大的键，即最大季度
                    last_season_number = max(media.seasons.keys())
                    if last_season_number > max_season_number:
                        max_season_number = last_season_number
                        logger.info(f"获取到最终季，季度为 {max_season_number},标题为 {media.title},年份为 {media.year}")
                else:
                    logger.info(f"媒体: {media.title} 没有季信息，跳过")

        self.vcb_meta.season = max_season_number
        logger.info(f"获取到最终季，季度为 {self.vcb_meta.season}")

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


def test(title: str):
    # 示例文件名
    pre_title = title

    # 提取方括号内的内容，不包括方括号
    content = re.findall(r'\[(.*?)\]', pre_title)

    print(content)


if __name__ == '__main__':
    # title = "[BeanSub&VCB-Studio] Jujutsu Kaisen [26][Ma10p_1080p][x265_flac].mkv "
    # test(title)

    ReMeta(
        ova_switch=True,
    ).handel_file(Path(
        r"[Nekomoe kissaten&VCB-Studio] Fruits Basket The Final [08][Ma10p_1080p][x265_flac].mkv"))
