import json
from typing import Any, List, Dict, Tuple, Optional

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.cache import cached
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import DiscoverSourceEventData
from app.schemas.types import ChainEventType
from app.utils.http import RequestUtils


# 爱奇艺频道映射：key 为频道标识，value 为频道名称与 channel_id
CHANNEL_PARAMS = {
    "tv": {"channel_id": "2", "name": "电视剧"},
    "movie": {"channel_id": "1", "name": "电影"},
    "anime": {"channel_id": "4", "name": "动漫"},
    "variety": {"channel_id": "6", "name": "综艺"},
}

# 筛选分组名称到 filter_params 参数名的映射
# 爱奇艺多个筛选分组共用相同的 query_param，需要映射为独立的参数名
GROUP_MODEL_MAP = {
    "排序": "mode",
    "类型": "type",
    "地区": "area",
    "时间": "year",
    "资费": "pay",
    "付费": "pay",
    "殿堂": "hall",
    "推荐": "recommend",
    "连载": "serial",
    "版本": "version",
    "风格": "style",
    "明星": "star",
    "奖项": "award",
    "剧场": "theater",
}

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.iqiyi.com/",
}

# 爱奇艺筛选数据接口
VIDEOLIB_DATA_URL = "https://mesh.if.iqiyi.com/portal/lw/videolib/data"
# 爱奇艺筛选标签接口
VIDEOLIB_TAG_URL = "https://mesh.if.iqiyi.com/portal/lw/videolib/tag"

# 请求基础参数
BASE_PARAMS = {
    "uid": "",
    "passport_id": "",
    "ret_num": "60",
    "pcv": "17.084.26143",
    "version": "17.084.26143",
    "device_id": "4b0c3e7cb568d5e6ccc4bf823293e709",
    "session": "",
    "token": "",
    "os": "10.0",
    "conduit_id": "",
    "vip": "0",
    "auth": "",
    "recent_selected_tag": "",
}

# 筛选标签缓存
BASE_UI: Optional[List] = None


def init_base_ui() -> List[dict]:
    """
    初始化爱奇艺筛选 UI。

    通过 videolib/tag 接口获取各频道的筛选标签，生成 Vuetify 筛选组件。
    每个筛选分组的 model 使用 GROUP_MODEL_MAP 映射为独立的参数名。
    """
    ui = []
    for key, value in CHANNEL_PARAMS.items():
        params = {
            "channel_id": value["channel_id"],
            "tagAdd": "",
            "selected_tag_name": "免费",
            "version": "17.084.26143",
            "device": "4b0c3e7cb568d5e6ccc4bf823293e709",
            "uid": "",
        }
        try:
            res = RequestUtils(headers=HEADERS).get_res(VIDEOLIB_TAG_URL, params=params)
            if res is None or not res.ok:
                logger.warning(f"获取爱奇艺筛选标签失败: {key}")
                continue
            tag_groups = res.json()
        except Exception as err:
            logger.warning(f"获取爱奇艺筛选标签异常: {key} {err}")
            continue
        if not isinstance(tag_groups, list):
            continue
        for group in tag_groups:
            if not group.get("display"):
                continue
            group_name = group.get("group")
            tags = group.get("tags", [])
            if not tags:
                continue
            # 映射分组名称为独立的参数名
            model = GROUP_MODEL_MAP.get(group_name, group_name)
            chip_data = [
                {
                    "component": "VChip",
                    "props": {
                        "filter": True,
                        "tile": True,
                        "value": tag.get("query_value", ""),
                    },
                    "text": tag.get("text", ""),
                }
                for tag in tags
            ]
            ui.append(
                {
                    "component": "div",
                    "props": {
                        "class": "flex justify-start items-center",
                        "show": "{{mtype == '" + key + "'}}",
                    },
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "mr-5"},
                            "content": [
                                {"component": "VLabel", "text": group_name}
                            ],
                        },
                        {
                            "component": "VChipGroup",
                            "props": {"model": model},
                            "content": chip_data,
                        },
                    ],
                }
            )
    return ui


class IqiyiDiscover(_PluginBase):
    """
    爱奇艺探索插件，让探索支持爱奇艺的数据浏览。
    """

    # 插件名称
    plugin_name = "爱奇艺探索"
    # 插件描述
    plugin_desc = "让探索支持爱奇艺的数据浏览。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/iqiyi_A.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "LLL001a"
    # 作者主页
    author_url = "https://github.com/LLL001a"
    # 插件配置项ID前缀
    plugin_config_prefix = "iqiyidiscover_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False

    def init_plugin(self, config: dict = None):
        """
        根据配置初始化插件启用状态。

        :param config: 插件配置字典
        """
        global BASE_UI
        if config:
            self._enabled = config.get("enabled")
        if "iqiyipic.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("iqiyipic.com")
        BASE_UI = init_base_ui()

    def get_state(self) -> bool:
        """
        返回插件是否已启用。

        :return: 插件启用状态
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件命令列表。

        :return: 命令列表
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表。

        :return: API 端点列表
        """
        return [
            {
                "path": "/iqiyi_discover",
                "endpoint": self.iqiyi_discover,
                "methods": ["GET"],
                "summary": "爱奇艺探索数据源",
                "description": "获取爱奇艺探索数据",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构。
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ], {"enabled": False}

    def get_page(self) -> List[dict]:
        """
        返回插件静态页面列表。

        :return: 静态页面列表
        """
        pass

    @cached(region="iqiyi_discover", ttl=1800, skip_none=True)
    def __request(self, channel_id: str, page: int, filter_params: str = None) -> List[dict]:
        """
        请求爱奇艺筛选数据接口。

        :param channel_id: 频道ID
        :param page: 页码
        :param filter_params: 筛选参数JSON字符串
        :return: 媒体数据列表
        """
        params = dict(BASE_PARAMS)
        params["channel_id"] = channel_id
        params["page_id"] = str(page)
        params["filter"] = filter_params or '{"mode":"11"}'
        try:
            res = RequestUtils(headers=HEADERS).get_res(VIDEOLIB_DATA_URL, params=params)
            if res is None:
                raise ConnectionError("无法连接爱奇艺，请检查网络连接！")
            if not res.ok:
                raise ValueError(f"请求爱奇艺 API失败：{res.text}")
            return res.json().get("data") or []
        except Exception as err:
            logger.error(f"获取爱奇艺数据失败: {str(err)}")
            raise

    def iqiyi_discover(
        self,
        mtype: str = "tv",
        mode: str = None,
        type: str = None,
        area: str = None,
        year: str = None,
        pay: str = None,
        hall: str = None,
        recommend: str = None,
        award: str = None,
        theater: str = None,
        page: int = 1,
        count: int = 60,
    ) -> List[schemas.MediaInfo]:
        """
        获取爱奇艺探索数据。

        :param mtype: 频道类型，tv/movie/anime/variety
        :param mode: 排序方式，11最热/4最新/8高分
        :param type: 类型筛选
        :param area: 地区筛选
        :param year: 年份筛选
        :param pay: 资费筛选，0免费
        :param hall: 殿堂筛选
        :param recommend: 推荐筛选
        :param award: 奖项筛选
        :param theater: 剧场筛选
        :param page: 页码
        :param count: 每页数量
        """
        if mtype not in CHANNEL_PARAMS:
            logger.warning(f"未知的爱奇艺频道类型: {mtype}")
            return []

        def __movie_to_media(movie_info: dict) -> schemas.MediaInfo:
            """
            电影数据转换为MediaInfo。
            """
            return schemas.MediaInfo(
                type="电影",
                title=movie_info.get("display_name") or movie_info.get("title"),
                year=self.__get_year(movie_info),
                title_year=self.__get_title_year(movie_info),
                mediaid_prefix="iqiyi",
                media_id=str(movie_info.get("album_id") or movie_info.get("entity_id")),
                poster_path=self.__get_poster(movie_info),
            )

        def __series_to_media(series_info: dict) -> schemas.MediaInfo:
            """
            电视剧数据转换为MediaInfo。
            """
            return schemas.MediaInfo(
                type="电视剧",
                title=series_info.get("display_name") or series_info.get("title"),
                year=self.__get_year(series_info),
                title_year=self.__get_title_year(series_info),
                mediaid_prefix="iqiyi",
                media_id=str(series_info.get("album_id") or series_info.get("entity_id")),
                poster_path=self.__get_poster(series_info),
            )

        try:
            filter_params = {}
            if mode:
                filter_params["mode"] = mode
            if type:
                filter_params["three_category_id_v2"] = type
            if area:
                filter_params["three_category_id_v2"] = area
            if year:
                filter_params["market_release_date_level"] = year
            if pay:
                filter_params["is_purchase"] = pay
            if hall:
                filter_params["smart_tag_v2"] = hall
            if recommend:
                filter_params["smart_tag_v2"] = recommend
            if award:
                filter_params["structure_id"] = award
            if theater:
                filter_params["smart_tag_v2"] = theater
            if not filter_params:
                filter_params = {"mode": "11"}
            result = self.__request(
                CHANNEL_PARAMS[mtype]["channel_id"],
                page,
                json.dumps(filter_params, ensure_ascii=False),
            )
        except Exception as err:
            logger.error(str(err))
            return []
        if not result:
            return []
        # 根据 channel_id 过滤，确保只返回当前频道的准确数据
        target_channel_id = CHANNEL_PARAMS[mtype]["channel_id"]
        result = [item for item in result if str(item.get("channel_id")) == target_channel_id]
        if mtype == "movie":
            results = [__movie_to_media(movie) for movie in result]
        else:
            results = [__series_to_media(series) for series in result]
        return results[:count]

    @staticmethod
    def __get_year(media_info: dict) -> Optional[str]:
        """
        从媒体数据中提取年份。

        :param media_info: 爱奇艺媒体数据
        :return: 年份字符串
        """
        date = media_info.get("date") or {}
        if isinstance(date, dict) and date.get("year"):
            return str(date.get("year"))
        if media_info.get("showDate"):
            return str(media_info.get("showDate")).split("-")[0]
        return None

    @staticmethod
    def __get_title_year(media_info: dict) -> Optional[str]:
        """
        生成标题（年份）格式。

        :param media_info: 爱奇艺媒体数据
        :return: 标题（年份）
        """
        title = media_info.get("display_name") or media_info.get("title")
        year = IqiyiDiscover.__get_year(media_info)
        if title and year:
            return f"{title} ({year})"
        return title

    @staticmethod
    def __get_poster(media_info: dict) -> Optional[str]:
        """
        获取高清海报地址。

        优先使用接口返回的高清字段 image_url_2x（318x424），
        其次从 image_cover 基础地址构造 300x450 高清竖版海报（JPEG），
        最后回退到 image_cover（120x160）。

        :param media_info: 爱奇艺媒体数据
        :return: 海报地址
        """
        # 优先使用接口直接返回的高清海报
        poster = media_info.get("image_url_2x") or media_info.get("image_url_normal")
        if poster:
            return poster
        # 从 image_cover 基础地址构造高清竖版海报
        cover = media_info.get("image_cover")
        if cover:
            import re
            # 去掉尺寸后缀和格式后缀，例如 a_xxx_m_601_m7.avif -> a_xxx_m_601_m7
            base = re.sub(r"_\d+_\d+\.\w+$", "", cover)
            base = re.sub(r"\.\w+$", "", base)
            if base:
                return f"{base}_300_450.jpg"
        return cover

    @staticmethod
    def iqiyi_filter_ui() -> List[dict]:
        """
        爱奇艺过滤参数UI配置。
        """
        mtype_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": value["name"],
            }
            for key, value in CHANNEL_PARAMS.items()
        ]
        ui = [
            {
                "component": "div",
                "props": {"class": "flex justify-start items-center"},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "种类"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "mtype"},
                        "content": mtype_ui,
                    },
                ],
            },
        ]
        if BASE_UI:
            for i in BASE_UI:
                ui.append(i)
        return ui

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听探索事件，注册爱奇艺探索数据源。
        """
        if not self._enabled:
            return
        event_data: DiscoverSourceEventData = event.event_data
        iqiyi_source = schemas.DiscoverMediaSource(
            name="爱奇艺",
            mediaid_prefix="iqiyi",
            api_path=f"plugin/IqiyiDiscover/iqiyi_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "tv",
                "mode": None,
                "type": None,
                "area": None,
                "year": None,
                "pay": None,
                "hall": None,
                "recommend": None,
                "award": None,
                "theater": None,
                "page": 1,
                "count": 60,
            },
            filter_ui=self.iqiyi_filter_ui(),
            depends={
                "mode": ["mtype"],
                "type": ["mtype"],
                "area": ["mtype"],
                "year": ["mtype"],
                "pay": ["mtype"],
                "hall": ["mtype"],
                "recommend": ["mtype"],
                "award": ["mtype"],
                "theater": ["mtype"],
                "page": ["mtype"],
                "count": ["mtype"],
            },
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [iqiyi_source]
        else:
            event_data.extra_sources.append(iqiyi_source)

    def stop_service(self):
        """
        退出插件。
        """
        pass
