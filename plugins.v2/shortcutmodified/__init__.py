from typing import List, Tuple, Dict, Any



from cachetools import cached, TTLCache



from app.api.endpoints.media import seasons

from app.chain.download import DownloadChain

from app.chain.media import MediaChain

from app.chain.search import SearchChain

from app.chain.subscribe import SubscribeChain

from app.core.config import settings

from app.core.metainfo import MetaInfo

from app.core.context import MediaInfo, Context, TorrentInfo

from app.log import logger

from app.plugins import _PluginBase

from app.schemas import MediaType





class ShortCutModified(_PluginBase):

    # 插件名称

    plugin_name = "修改版快捷指令"

    # 插件描述

    plugin_desc = "IOS快捷指令，快速选片添加订阅"

    # 插件图标

    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/shortcut.png"

    # 插件版本

    plugin_version = "2.6.8"

    # 插件作者

    plugin_author = "Sinterdial"

    # 作者主页

    author_url = "https://github.com/Sinterdial"

    # 插件配置项ID前缀

    plugin_config_prefix = "ShortCutModified_"

    # 加载顺序

    plugin_order = 15

    # 可使用的用户级别

    auth_level = 1



    _enable: bool = False

    _plugin_key: str = ""

    _num: int = 3



    downloadchain: DownloadChain = None

    subscribechain: SubscribeChain = None

    mediachain: MediaChain = None

    searchchain: SearchChain = None



    torrents_list = []



    def init_plugin(self, config: dict = None):

        self._enable = config.get("enable") if config.get("enable") else False

        self._plugin_key = config.get("plugin_key") if config.get("plugin_key") else settings.API_TOKEN

        self._num = int(config.get("num")) if config.get("num") else 3



        self.downloadchain = DownloadChain()

        self.subscribechain = SubscribeChain()

        self.mediachain = MediaChain()

        self.searchchain = SearchChain()

        self.torrents_list = []



    def search(self, title: str, plugin_key: str) -> Any:

        """

        模糊搜索媒体信息列表

        """

        if self._plugin_key != plugin_key:

            logger.error(f"plugin_key错误：{plugin_key}")

            return []

        _, medias = self.mediachain.search(title=title)

        if medias:

            ret = []

            for media in medias[:self._num]:

                # 降低图片质量

                media.poster_path.replace("/original/", "/w200/")

                ret.append(media)

            return ret

        logger.info(f"{title} 没有找到结果")

        return []



    def get_seasons_list(self, title: str, tmdbid: str, type: str = "电视剧", plugin_key: str = "") -> Any:

        """

        查询季数

        """

        if self._plugin_key != plugin_key:

            msg = f"plugin_key错误：{plugin_key}"

            logger.error(msg)

            return msg

        # 元数据

        meta = MetaInfo(title=title)

        meta.tmdbid = tmdbid

        mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, tmdbid=tmdbid,

                                                          mtype=MediaType(type))

        if not mediainfo:

            msg = f'未识别到媒体信息，标题：{title}，tmdb_id：{tmdbid}'

            logger.warn(msg)

            return msg



        # 创建季列表

        seasons_list = list(range(1, mediainfo.number_of_seasons + 1))

        seasons_info = [self.number_to_chinese(season) for season in seasons_list]

        seasons_list_str = [f"第{season_info}季" for season_info in seasons_info]

        exits_season_num = 0



        # 查询缺失的媒体信息

        for index, season in enumerate(seasons_list):

            # 标记订阅季数

            meta.begin_season = season

            mediainfo.season = season



            exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

            if exist_flag:

                msg = f'媒体库中已存在 {mediainfo.title_year} {seasons_list_str[index]} '

                logger.info(msg)

                seasons_list_str[index] += "（已入库，请勿重复选择）"

                exits_season_num += 1

            # 判断用户是否已经添加订阅

            if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):

                msg = f'{mediainfo.title_year} 订阅已存在'

                logger.info(msg)

                seasons_list_str[index] += "（已订阅，请勿重复选择）"

                exits_season_num += 1



        if exits_season_num == len(seasons_list):

            return f'已入库/订阅剧集 {mediainfo.title_year} 的所有季，请勿重复订阅'

        elif seasons_list_str:

            return seasons_list_str

        else:

            return "未识别到季数相关信息"



    def subscribe(self, title: str, tmdbid: str, type: str = "电视剧", seasons_str_encoded: str = "第一季", plugin_key: str = "") -> Any:

        """

        添加订阅

        """

        if self._plugin_key != plugin_key:

            msg = f"plugin_key错误：{plugin_key}"

            logger.error(msg)

            return msg

        # 元数据

        meta = MetaInfo(title=title)



        log_msg = f"接收到的参数seasons：{seasons_str_encoded},接收到的参数type：{type}"

        logger.info(log_msg)



        # 分解要订阅的季数

        seasons_str = seasons_str_encoded.split(",")



        meta.tmdbid = tmdbid

        mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, tmdbid=tmdbid,

                                                          mtype=MediaType(type))

        if not mediainfo:

            msg = f'未识别到媒体信息，标题：{title}，tmdb_id：{tmdbid}'

            logger.warn(msg)

            return msg



        # 判断是否为剧集

        if type == "电视剧":

            # 转化季信息到阿拉伯数字

            seasons_to_subscribe = [self.chinese_to_number(season_info) for season_info in seasons_str]

            # 记录已订阅季数

            seasons_subscribed = []



            if len(seasons_to_subscribe) == 1:

                # 标记订阅季数

                meta.begin_season = seasons_to_subscribe[0]

                mediainfo.season = seasons_to_subscribe[0]



                exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

                if exist_flag:

                    msg = f'媒体库中已存在 {mediainfo.title_year} {seasons_to_subscribe[0]}'

                    logger.info(msg)

                    return msg

                # 查询订阅是否存在

                if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):

                    msg = f'{mediainfo.title_year} {seasons_to_subscribe[0]} 订阅已存在'

                    logger.info(msg)

                    return msg



            # 依次订阅剧集

            for season_to_subscribe in seasons_to_subscribe:

                # 标记订阅季数

                mediainfo.season = season_to_subscribe



                # 添加订阅

                sid, msg = self.subscribechain.add(title=mediainfo.title,

                                                   year=mediainfo.year,

                                                   mtype=mediainfo.type,

                                                   tmdbid=mediainfo.tmdb_id,

                                                   season=season_to_subscribe,

                                                   exist_ok=True,

                                                   username="快捷指令")



                if not msg:

                    seasons_subscribed.append(self.number_to_chinese(season_to_subscribe))

                else:

                    return msg



            # 拼接成功订阅的信息并返回

            subscribed_info = mediainfo.title_year  + " 第" + "、".join(seasons_subscribed) + "季订阅成功！"

            return subscribed_info

        # 如果是电影，则不考虑季相关问题

        else:

            # 查询缺失的媒体信息

            exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)

            if exist_flag:

                msg = f'媒体库中已存在 {mediainfo.title_year}'

                logger.info(msg)

                return msg

            # 查询订阅是否存在

            if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):

                msg = f'{mediainfo.title_year} 订阅已存在'

                logger.info(msg)

                return msg

            # 添加订阅

            sid, msg = self.subscribechain.add(title=mediainfo.title,

                                               year=mediainfo.year,

                                               mtype=mediainfo.type,

                                               tmdbid=mediainfo.tmdb_id,

                                               exist_ok=True,

                                               username="快捷指令")

            if not msg:

                return f"{mediainfo.title_year} 订阅成功"

            else:

                return msg







    @cached(TTLCache(maxsize=100, ttl=300))
    def torrents(self, tmdbid: int, type: str = None, area: str = "title",

                 season: str = None, plugin_key: str = None):

        """

        根据TMDBID精确搜索站点资源

        """

        if self._plugin_key != plugin_key:

            logger.error(f"plugin_key错误：{plugin_key}")

            return []

        if type:

            type = MediaType(type)

        if season:

            season = int(season)

        self.torrents_list = []



        if settings.RECOGNIZE_SOURCE == "douban":

            # 通过TMDBID识别豆瓣ID

            doubaninfo = self.mediachain.get_doubaninfo_by_tmdbid(tmdbid=tmdbid, mtype=type)

            if doubaninfo:

                torrents = self.searchchain.search_by_id(doubanid=doubaninfo.get("id"),

                                                         mtype=type, area=area, season=season)

            else:

                logger.error("未识别到豆瓣媒体信息")

                return []

        else:

            torrents = self.searchchain.search_by_id(tmdbid=tmdbid, mtype=type, area=area, season=season)



        if not torrents:

            logger.error("未搜索到任何资源")

            return []

        else:

            self.torrents_list = [torrent.to_dict() for torrent in torrents]



        return self.torrents_list[:50]



    def download(self, idx: int, plugin_key: str = None):

        if self._plugin_key != plugin_key:

            logger.error(f"plugin_key错误：{plugin_key}")

            return f"plugin_key错误：{plugin_key}"



        idx = idx - 1

        if idx > len(self.torrents_list):

            return "超出范围，添加失败"

        selected_info: dict = self.torrents_list[idx]

        # 媒体信息

        mediainfo = MediaInfo()

        mediainfo.from_dict(selected_info.get("media_info"))

        # 种子信息

        torrentinfo = TorrentInfo()

        torrentinfo.from_dict(selected_info.get("torrent_info"))

        # 元数据

        metainfo = MetaInfo(title=torrentinfo.title, subtitle=torrentinfo.description)



        # 上下文

        context = Context(

            meta_info=metainfo,

            media_info=mediainfo,

            torrent_info=torrentinfo

        )

        did = self.downloadchain.download_single(context=context, username="快捷指令")

        if not did:

            return f"添加下载失败"

        else:

            return f"{mediainfo.title_year} 添加下载成功"



    def get_api(self) -> List[Dict[str, Any]]:

        return [

            {

                "path": "/search",

                "endpoint": self.search,

                "methods": ["GET"],

                "summary": "模糊搜索",

                "description": "模糊搜索",

            }, {

                "path": "/getseasonslist",

                "endpoint": self.get_seasons_list,

                "methods": ["GET"],

                "summary": "查询剧集季信息",

                "description": "查询剧集季信息",

            },{

                "path": "/subscribe",

                "endpoint": self.subscribe,

                "methods": ["GET"],

                "summary": "添加订阅",

                "description": "添加订阅",

            }, {

                "path": "/torrents",

                "endpoint": self.torrents,

                "methods": ["GET"],

                "summary": "搜索种子",

                "description": "搜索种子",

            }, {

                "path": "/download",

                "endpoint": self.download,

                "methods": ["GET"],

                "summary": "下载任务",

                "description": "下载任务",

            }

        ]



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



    @staticmethod

    def get_command() -> List[Dict[str, Any]]:

        pass



    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:

        return [

            {

                'component': 'VForm',

                'content': [

                    {

                        'component': 'VRow',

                        'content': [

                            {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                    'md': 2

                                },

                                'content': [

                                    {

                                        'component': 'VSwitch',

                                        'props': {

                                            'model': 'enable',

                                            'label': '启用插件',

                                        }

                                    }

                                ]

                            }, {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                    'md': 4

                                },

                                'content': [

                                    {

                                        'component': 'VTextField',

                                        'props': {

                                            'model': 'num',

                                            'label': '快捷指令列表展示数量',

                                            'placeholder': '数量过多会影响快捷指令速度',

                                        }

                                    }

                                ]

                            }, {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                    'md': 6

                                },

                                'content': [

                                    {

                                        'component': 'VTextField',

                                        'props': {

                                            'model': 'plugin_key',

                                            'label': '插件plugin_key',

                                            'placeholder': '留空默认是mp的api_key',

                                        }

                                    }

                                ]

                            }

                        ]

                    }, {

                        'component': 'VRow',

                        'content': [

                            {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                },

                                'content': [

                                    {

                                        'component': 'VAlert',

                                        'props': {

                                            'type': 'info',

                                            'variant': 'tonal',

                                            'text': '感谢Nest的想法和honue的原始代码。独立自 2025/06/04，MoviePilot版本需为 1.8.3+，只有订阅功能的快捷指令，暂无下载快捷指令。'

                                        }

                                    }

                                ]

                            }, {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                },

                                'content': [

                                    {

                                        'component': 'VAlert',

                                        'props': {

                                            'type': 'info',

                                            'variant': 'tonal',

                                            'text': '仅订阅功能，导入快捷指令后按提示填入MP网址和该插件的plugin_key：https://www.icloud.com/shortcuts/6da4dd25c6ff4fd68b5a76975ba33516'

                                        }

                                    }

                                ]

                            }, {

                                'component': 'VCol',

                                'props': {

                                    'cols': 12,

                                },

                                'content': [

                                    {

                                        'component': 'VAlert',

                                        'props': {

                                            'type': 'info',

                                            'variant': 'tonal',

                                            'text': '只有订阅功能，暂无下载快捷指令'

                                        }

                                    }

                                ]

                            }

                        ]

                    }

                ]

            }

        ], {

            "enable": self._enable,

            "num": self._num,

            "plugin_key": self._plugin_key,

        }



    def get_page(self) -> List[dict]:

        pass



    def get_state(self) -> bool:

        return self._enable



    def stop_service(self):

        pass

