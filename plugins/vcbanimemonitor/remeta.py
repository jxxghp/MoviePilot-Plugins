import concurrent
import re
from pathlib import Path
from typing import List

import roman

from app.chain.media import MediaChain
from app.chain.tmdb import TmdbChain
from app.core.metainfo import MetaInfoPath
from app.log import logger
from app.schemas import MediaType


class ReMeta:
    # 解析之后的标题：
    title: str = None
    # 识别出来的集数
    ep: int = None
    # 识别出来的季度
    season: int = None
    # 特殊季识别开关
    is_special = False
    # OVA/OAD识别开关
    ova_switch: bool = False
    # 高性能处理开关
    high_performance = False

    season_patterns = [
        {"pattern": re.compile(r"S(\d+)$"), "group": 1},
        {"pattern": re.compile(r"(\d+)$"), "group": 1},
        {"pattern": re.compile(r"(\d+)(st|nd|rd|th)?\s*[Ss][Ee][Aa][Ss][Oo][Nn]"), "group": 1},
        {"pattern": re.compile(r"(.*) ?\s*[Ss][Ee][Aa][Ss][Oo][Nn] (\d+)"), "group": 2},
        {"pattern": re.compile(r"\s(II|III|IV|V|VI|VII|VIII|IX|X)$"), "group": "1"}
    ]
    episode_patterns = [
        {"pattern": re.compile(r"\[(\d+)\((\d+)\)]"), "group": 2},
        {"pattern": re.compile(r"\[(\d+)]"), "group": 1},
        {"pattern": re.compile(r'\[(\d+)v\d+]'), "group": 1},

    ]
    _ova_patterns = [re.compile(r"\[.*?(OVA|OAD).*?]"),
                     re.compile(r"\[\d+\.5]"),
                     re.compile(r"\[00]")]

    final_season_patterns = [re.compile('final season', re.IGNORECASE),
                             re.compile('The Final', re.IGNORECASE),
                             re.compile(r'\sFinal')
                             ]
    # 自定义添加的季度正则表达式
    _custom_season_patterns = []

    def __init__(self, ova_switch: bool = False, high_performance: bool = False):
        self.ova_switch = ova_switch
        self.high_performance = high_performance

    def handel_file(self, file_path: Path):
        meta = MetaInfoPath(file_path)
        self.title = meta.title
        if 'VCB-Studio' not in meta.title:
            logger.warn("不属于VCB的作品，不处理！")
            return None
        if meta.title.count("[") != 4 and meta.title.count("]") != 4:
            # 可能是电影，电影只有三组[]，因此去除所有[]后只剩下电影名
            logger.warn("不符合VCB-Studio的剧集命名规范，跳过剧集模块处理！交给默认处理逻辑")
            meta.title = re.sub(r'\[.*?]', '', meta.title).strip()
            meta.en_name = meta.title
            return meta
        split_title: List[str] | None = self.split_season_ep(self.title)
        if split_title:
            self.handle_season_ep(split_title)
            if self.season is not None:
                meta.begin_season = self.season
            else:
                logger.warn("未识别出季度,默认处理逻辑返回第一季")
            if self.ep is not None:
                meta.begin_episode = self.ep
            else:
                logger.warn("未识别出集数,默认处理逻辑返回第一集")
            meta.title = self.title
            meta.en_name = self.title
            logger.info(f"识别出季度为{self.season}，集数为{self.ep},标题为：{self.title}")

        return meta

    # 分离季度部分和集数部分
    @staticmethod
    def split_season_ep(pre_title: str):
        split_ep = re.findall(r"(\[.*?])", pre_title)[1]
        if not split_ep:
            logger.warn("未识别出集数位置信息，结束识别！")
            return None
        split_title = re.sub(r"\[.*?]", "", pre_title).strip()
        logger.info(f"分离出包含季度的部分：{split_title} \n 分离出包含集数的部分： {split_ep}")
        return [split_title, split_ep]

    def handle_season_ep(self, title: List[str]):
        if self.high_performance:
            with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:
                title_season_result = executor.submit(self.handle_season, title[0])
                ep_result = executor.submit(self.re_ep, title[1], )
            try:
                title_season_result = title_season_result.result()  # Blocks until the task is complete.
                ep_result = ep_result.result()  # Blocks until the task is complete.
            except Exception as exc:
                print('Generated an exception: %s' % exc)
        else:
            title_season_result = self.handle_season(title[0])
            ep_result = self.re_ep(title[1])
        self.title = title_season_result["title"]
        is_ova = ep_result["is_ova"]
        if ep_result["ep"] is not None:
            self.ep = ep_result["ep"]
        if title_season_result["season"]:
            self.season = title_season_result["season"]
        if is_ova:
            self.season = 0
            self.is_special = True

    # 处理季度
    def handle_season(self, pre_title: str) -> dict:
        title_season = {"title": pre_title, "season": 1}
        for season_pattern in self.season_patterns:
            pattern = season_pattern["pattern"]
            group = season_pattern["group"]
            match = pattern.search(pre_title)
            if match:
                if type(group) == str:
                    title_season["season"] = int(roman.fromRoman(match.group(int(group))))
                    title_season["title"] = re.sub(pattern, "", pre_title).strip()
                else:
                    title_season["season"] = int(match.group(group))
                    title_season["title"] = re.sub(pattern, "", pre_title).strip()
                return title_season
        for final_season_pattern in self.final_season_patterns:
            match = final_season_pattern.search(pre_title)
            if match:
                logger.info("识别出最终季度，开始处理！")
                title_season["title"] = re.sub(final_season_pattern, "", pre_title).strip()
                title_season["season"] = self.handle_final_season(title=pre_title)
                break
        return title_season

    # 处理存在“Final”字样命名的季度
    @staticmethod
    def handle_final_season(title: str) -> int | None:
        medias = MediaChain().search(title=title)[1]
        if not medias:
            logger.warn("没有找到对应的媒体信息！")
            return
        # 根据类型进行过滤，只取类型是电视剧和动漫的media
        medias = [media for media in medias if media.type == MediaType.TV]
        if not medias:
            logger.warn("没有找到动漫或电视剧的媒体信息！")
            return
        media = sorted(medias, key=lambda x: x.popularity, reverse=True)[0]
        media_tmdb_id = media.tmdb_id
        seasons_info = TmdbChain().tmdb_seasons(tmdbid=media_tmdb_id)
        if seasons_info is None:
            logger.warn("无法获取最终季")
        else:
            logger.info(f"获取到最终季，季度为{len(seasons_info)}")
            return len(seasons_info)

    def re_ep(self, ep_title: str, ) -> dict:
        """
        # 集数匹配处理模块
        :param ep_title: 从title解析出的集数,ep_title固定格式[集数]
            1.先判断是否存在OVA/OAD,形如：[OVA],[12(OVA)],[12.5]这种形式都是属于OVA/OAD，交给处理OVA模块处理
            2.集数通常有两种情况一种：[12]直接性，另一种：[12(24)]，这一种应该去括号内的为集数
        :return: 集数(int)
        """
        ep_ova = {"ep": None, "is_ova": False}
        for ova_pattern in self._ova_patterns:
            match = ova_pattern.search(ep_title)
            if match:
                ep_ova["is_ova"] = True
                ep_ova["ep"] = 1
                return ep_ova
        for ep_pattern in self.episode_patterns:
            pattern = ep_pattern["pattern"]
            group = ep_pattern["group"]
            match = pattern.search(ep_title)
            if match:
                ep_ova["ep"] = int(match.group(group))
                return ep_ova
        return ep_ova
