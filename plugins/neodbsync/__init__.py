import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.event import Event
from app.core.event import eventmanager
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.schemas.types import MediaType

lock = Lock()


class NeoDBSync(_PluginBase):
    # 插件名称
    plugin_name = "NeoDB 想看"
    # 插件描述
    plugin_desc = "同步 NeoDB 想看数据，自动添加订阅。"
    # 插件图标
    plugin_icon = "NeoDB.jpeg"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "hcplantern"
    # 作者主页
    author_url = "https://hcplantern.top"
    # 插件配置项ID前缀
    plugin_config_prefix = "neodbsync_"
    # 加载顺序
    plugin_order = 3
    # 可使用的用户级别
    auth_level = 2

    # 私有变量
    _movie_url: str = "https://neodb.social/api/me/shelf/wishlist?category=movie"
    _tv_url: str = "https://neodb.social/api/me/shelf/wishlist?category=tv"

    _scheduler: Optional[BackgroundScheduler] = None
    _cache_path: Optional[Path] = None

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _notify: bool = False
    _days: int = 7
    _clear: bool = False
    _clearflag: bool = False
    _tokens: str = ""

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._days = config.get("days")
            self._onlyonce = config.get("onlyonce")
            self._clear = config.get("clear")
            self._tokens = config.get("tokens")

        if self._enabled or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"NeoDB 想看服务启动，立即运行一次")
                self._scheduler.add_job(func=self.sync, trigger='date',
                                        run_date=datetime.datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                        )

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

            if self._onlyonce or self._clear:
                # 关闭一次性开关
                self._onlyonce = False
                # 记录缓存清理标志
                self._clearflag = self._clear
                # 关闭清理缓存
                self._clear = False
                # 保存配置
                self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/neodb_sync",
            "event": EventType.PluginAction,
            "desc": "同步 NeoDB 想看",
            "category": "订阅",
            "data": {
                "action": "neodb_sync"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            return [
                {
                    "id": "NeoDBSync",
                    "name": "NeoDB 想看同步服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.sync,
                    "kwargs": {}
                }
            ]
        elif self._enabled:
            return [
                {
                    "id": "NeoDBSync",
                    "name": "NeoDB 想看同步服务",
                    "trigger": "interval",
                    "func": self.sync,
                    "kwargs": {"minutes": 30}
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'days',
                                            'label': '同步天数'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tokens',
                                            'label': '用户 Token 列表',
                                            'placeholder': 'NeoDB 用户 Token，多个用英文逗号分隔'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clear',
                                            'label': '清理历史记录',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
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
                                            'text': '获取 NeoDB Token 的方法请见：'
                                                    'https://www.eallion.com/neodb_token/'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "cron": "*/30 * * * *",
            "days": 7,
            "tokens": "",
            "clear": False
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get('time'), reverse=True)
        # 拼装页面
        contents = []
        for history in historys:
            title = history.get("title")
            poster = history.get("poster")
            mtype = history.get("type")
            time_str = history.get("time")
            neodb_id = history.get("neodb_id")
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex justify-space-start flex-nowrap flex-row',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': poster,
                                                'height': 120,
                                                'width': 80,
                                                'aspect-ratio': '2/3',
                                                'class': 'object-cover shadow ring-gray-500',
                                                'cover': True
                                            }
                                        }
                                    ]
                                },
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VCardTitle',
                                            'props': {
                                                'class': 'ps-1 pe-5 break-words whitespace-break-spaces'
                                            },
                                            'content': [
                                                {
                                                    'component': 'a',
                                                    'props': {
                                                        'href': f"https://neodb.social{neodb_id}",
                                                        'target': '_blank'
                                                    },
                                                    'text': title
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'类型：{mtype}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'时间：{time_str}'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            )

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "days": self._days,
            "tokens": self._tokens,
            "clear": self._clear
        })

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    def sync(self):
        """
        通过用户RSS同步豆瓣想看数据
        """
        if not self._tokens:
            return
        # 读取历史记录
        if self._clearflag:
            history = []
        else:
            history: List[dict] = self.get_data('history') or []
        # 遍历所有用户
        for token in self._tokens.split(","):
            if not token:
                continue
            # 请求头含 Token
            headers = {"Authorization": f"Bearer {token}"}
            # 获取用户名
            username = self.__get_username(token)
            # 同步每个 NeoDB 用户的数据
            logger.info(f"开始同步 NeoDB 用户 {username} 的想看数据 ...")
            try:
                movie_response = requests.get(self._movie_url, headers=headers)
                movie_response.raise_for_status()
                tv_response = requests.get(self._tv_url, headers=headers)
                tv_response.raise_for_status()

                try:
                    results = movie_response.json().get("data", []) + tv_response.json().get("data", [])
                except ValueError:
                    logger.error("用户数据解析失败")
                    continue
            except Exception as e:
                logger.error(f"获取数据失败：{str(e)}")
                continue
            if not results:
                logger.info(f"用户 {username} 没有想看数据")
                continue
            # 遍历该用户的所有想看条目
            downloadchain = DownloadChain()
            subscribechain = SubscribeChain()
            for result in results:
                try:
                    # Take the url as the unique identifier. For example: /movie/2fEdnxYWozPayayizQmk5M
                    item_id = result['item']['url']
                    title = result['item']['title']
                    category = result['item']['category']
                    api_url = result['item']['api_url']
                    # 判断是否在天数范围内
                    if not self.__is_in_date_range(result.get("created_time"), title):
                        continue
                    # 检查是否处理过
                    if not item_id or item_id in [h.get("neodb_id") for h in history]:
                        logger.info(f'标题：{title}，NeoDB ID：{item_id} 已处理过')
                        continue
                    # 获取条目详细信息 item_info
                    try:
                        item_info = requests.get(f"https://neodb.social{api_url}").json()
                    except Exception as e:
                        logger.error(f"获取条目信息失败：{str(e)}")
                        continue
                    # 识别媒体信息
                    meta = MetaInfo(title=title)
                    meta.year = item_info['year']
                    meta.type = MediaType.MOVIE if category == "movie" else MediaType.TV
                    mediainfo = self.__get_mediainfo(meta, item_info)
                    if not mediainfo:
                        logger.warn(f'未识别到媒体信息，标题：{title}')
                        continue
                    # 查询缺失的媒体信息
                    exist_flag, no_exists = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
                    if exist_flag:
                        logger.info(f'{mediainfo.title_year} 媒体库中已存在')
                    else:
                        # 添加订阅
                        logger.info(f'{mediainfo.title_year} 媒体库中不存在或不完整，添加订阅 ...')
                        subscribechain.add(title=mediainfo.title,
                                           year=mediainfo.year,
                                           mtype=mediainfo.type,
                                           tmdbid=mediainfo.tmdb_id,
                                           season=meta.begin_season,
                                           exist_ok=True,
                                           username="NeoDB 想看")
                        action = "subscribe"
                        # 存储历史记录
                        history.append({
                            "action": action,
                            "title": title,
                            "type": mediainfo.type.value,
                            "year": mediainfo.year,
                            "poster": mediainfo.get_poster_image(),
                            "overview": mediainfo.overview,
                            "tmdbid": mediainfo.tmdb_id,
                            "neodb_id": item_id,
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                except Exception as err:
                    logger.error(f'同步用户 {username} NeoDB 想看数据出错：{str(err)}')
            logger.info(f"用户 {username} NeoDB 想看同步完成")
        # 保存历史记录
        self.save_data('history', history)
        # 缓存只清理一次
        self._clearflag = False

    def __is_in_date_range(self, created_time_str: str, title):
        """
        检查是否在指定的天数范围内
        """
        if created_time_str:
            try:
                # 将字符串转换为 datetime 对象
                created_time = datetime.datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
                # 计算时间差并检查是否超过了特定的天数
                if (datetime.datetime.now(datetime.timezone.utc) - created_time).days > float(self._days):
                    logger.info(f"已超过同步天数，标题：{title}，标记时间：{created_time.date()}")
                    return False
            except ValueError:
                logger.error(f"日期时间格式错误：{created_time_str}")
                return False
        return True

    @staticmethod
    def __get_username(token: str):
        """
        获取 NeoDB 用户名
        """
        try:
            user_info = requests.get(f"https://neodb.social/api/me", headers={"Authorization": f"Bearer {token}"})
            user_info.raise_for_status()
            try:
                username = user_info.json().get("username")
            except ValueError:
                logger.error("用户数据解析失败")
                return {}
        except Exception as e:
            logger.error(f"获取用户信息失败：{str(e)}")
            return {}

        logger.info(f"成功获取用户名：{username}")
        return username

    def __get_mediainfo(self, meta, item_info):
        """
        通过豆瓣或者 TMDB 获取媒体信息
        """
        external_resources = item_info.get("external_resources", [])
        if not external_resources:
            return None
        category = item_info.get("category")  # 'movie' 或 'tv'
        # 初始化变量用于存储豆瓣 ID 和 TMDB ID
        doubanid = ""
        tmdbid = 0
        # 遍历 external_resources 列表
        for resource in external_resources:
            url = resource.get("url")
            if "douban.com" in url:
                # 分割 URL 来获取豆瓣 ID
                doubanid = url.split('/')[-2]
            elif "themoviedb.org" in url:
                # 根据 category 判断是 movie 还是 tv
                if category == "movie":
                    # 分割 URL 来获取 movie 的 TMDB ID
                    tmdbid = int(url.split('/')[-1])
                elif category == "tv":
                    # 分割 URL 来获取 tv 的 TMDB ID
                    # 例如 "https://www.themoviedb.org/tv/225780/season/1"，TMDB ID 是 225780
                    tmdbid = int(url.split('/')[-3])
        return self.chain.recognize_media(meta=meta, doubanid=doubanid, tmdbid=tmdbid)

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        """
        NeoDB 想看同步
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "neodb_sync":
                return

            logger.info("收到命令，开始执行 NeoDB 想看同步 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始同步 NeoDB 想看 ...",
                              userid=event.event_data.get("user"))
        self.sync()

        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="同步 NeoDB 想看数据完成！", userid=event.event_data.get("user"))
