import datetime
import json
import pytz
from typing import Any, Dict, List, Optional, Type

from app.chain.subscribe import SubscribeChain, Subscribe
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.metainfo import MetaInfo
from app.db.models.subscribehistory import SubscribeHistory
from app.db.site_oper import SiteOper
from app.db.subscribe_oper import SubscribeOper
from app.db import db_query
from app.helper.subscribe import SubscribeHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType
from app.utils.http import RequestUtils
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import JSON
from sqlalchemy.orm import Session


class BangumiColl(_PluginBase):
    # 插件名称
    plugin_name = "Bangumi收藏订阅"
    # 插件描述
    plugin_desc = "将Bangumi用户收藏添加到订阅"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/wikrin/MoviePilot-Plugins/main/icons/bangumi_b.png"
    # 插件版本
    plugin_version = "1.4"
    # 插件作者
    plugin_author = "Attente"
    # 作者主页
    author_url = "https://github.com/wikrin"
    # 插件配置项ID前缀
    plugin_config_prefix = "bangumicoll_"
    # 加载顺序
    plugin_order = 23
    # 可使用的用户级别
    auth_level = 1

    # 私有变量
    _scheduler: Optional[BackgroundScheduler] = None
    siteoper: SiteOper = None
    subscribehelper: SubscribeHelper = None
    subscribeoper: SubscribeOper = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _include: str = ""
    _exclude: str = ""
    _uid: str = ""
    _collection_type = []
    _save_path: str = ""
    _sites: list = []

    def init_plugin(self, config: dict = None):
        self.subscribechain = SubscribeChain()
        self.siteoper = SiteOper()
        self.subscribehelper = SubscribeHelper()
        self.subscribeoper = SubscribeOper()

        # 停止现有任务
        self.stop_service()
        self.load_config(config)

        if self._onlyonce:
            self.schedule_once()

    def load_config(self, config: dict):
        """加载配置"""
        if config:
            self._enabled = config.get("enabled", self._enabled)
            self._cron = config.get("cron", self._cron)
            self._notify = config.get("notify", self._notify)
            self._onlyonce = config.get("onlyonce", self._onlyonce)
            self._include = config.get("include", self._include)
            self._exclude = config.get("exclude", self._exclude)
            self._uid = config.get("uid", self._uid)
            self._collection_type = config.get("collection_type", [3])
            self._save_path = config.get("save_path", self._save_path)
            self._sites = config.get("sites", self._sites)

    def schedule_once(self):
        """调度一次性任务"""
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        logger.info("Bangumi收藏订阅，立即运行一次")
        self._scheduler.add_job(
            func=self.bangumi_coll,
            trigger='date',
            run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ))
            + datetime.timedelta(seconds=3),
        )
        self._scheduler.start()

        # 关闭一次性开关
        self._onlyonce = False
        self.__update_config()

    def __update_config(self):
        """更新设置"""
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "uid": self._uid,
                "collection_type": self._collection_type,
                "include": self._include,
                "exclude": self._exclude,
                "save_path": self._save_path,
                "sites": self._sites,
            }
        )

    def get_form(self):
        # 列出所有站点
        sites_options = [
            {"title": site.name, "value": site.id}
            for site in self.siteoper.list_order_by_pri()
        ]

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '自动取消订阅并通知',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动',
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'uid',
                                            'label': 'UID/用户名',
                                            'placeholder': '设置了用户名填写用户名，否则填写UID',
                                        },
                                    },
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'collection_type',
                                            'label': '收藏类型',
                                            'chips': True,
                                            'multiple': True,
                                            'items': [
                                                {'title': '在看', 'value': 3},
                                                {'title': '想看', 'value': 1},
                                            ],
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'include',
                                            'label': '包含',
                                            'placeholder': '暂未实现',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '排除',
                                            'placeholder': '暂未实现',
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'save_path',
                                            'label': '保存目录',
                                            'placeholder': '留空自动',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'sites',
                                            'label': '选择站点',
                                            'chips': True,
                                            'multiple': True,
                                            'items': sites_options,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "cron": "",
            "uid": "",
            "collection_type": [3],
            "include": "",
            "exclude": "",
            "save_path": "",
            "sites": [],
        }

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件公共服务"""
        if self._enabled:
            trigger = CronTrigger.from_crontab(self._cron) if self._cron else "interval"
            kwargs = {"hours": 6} if not self._cron else {}
            return [
                {
                    "id": "BangumiColl",
                    "name": "Bangumi收藏订阅",
                    "trigger": trigger,
                    "func": self.bangumi_coll,
                    "kwargs": kwargs,
                }
            ]
        return []

    def stop_service(self):
        """退出插件"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{str(e)}")

    def get_api(self):
        pass

    def get_command(self):
        pass

    def get_page(self):
        pass

    def get_state(self):
        return self._enabled

    def bangumi_coll(self):
        """订阅Bangumi用户收藏"""
        if not self._uid:
            logger.error("请设置UID")
            return

        try:
            res = self.get_bgm_res(addr="UserCollections", id=self._uid)
            items = self.parse_collection_items(res)

            # 新增和移除条目
            self.manage_subscriptions(items)

            logger.info("Bangumi收藏订阅执行完成")
        except Exception as e:
            logger.error(f"执行失败: {str(e)}")

    def parse_collection_items(self, response) -> Dict[int, Dict[str, Any]]:
        """解析获取的收藏条目"""
        data = response.json().get("data")
        if not data:
            logger.error(f"Bangumi用户：{self._uid} ，没有任何收藏")
            return {}

        items = {}
        logger.info("解析Bangumi条目信息...")
        for item in data:
            if item.get("type") not in self._collection_type:
                logger.debug(
                    f"条目: {item['subject'].get('name_cn')}  类型:{item.get('type')} 不符合"
                )
                continue

            items[item.get("subject_id")] = {
                "name": item['subject'].get('name'),
                "name_cn": item['subject'].get('name_cn'),
                "date": item['subject'].get('date'),
                "eps": item['subject'].get('eps'),
            }
        return items

    def manage_subscriptions(self, items: Dict[int, Dict[str, Any]]):
        """管理订阅的新增和删除"""
        db_sub = {
            i.bangumiid: i.id
            for i in self.subscribechain.subscribeoper.list()
            if i.bangumiid
        }
        db_hist = self.get_subscribe_history()
        new_sub = items.keys() - db_sub.keys() - db_hist
        del_sub = db_sub.keys() - items.keys()

        logger.debug(f"待新增条目：{new_sub}")
        logger.debug(f"待移除条目：{del_sub}")

        if del_sub and self._notify:
            del_items = {db_sub[i]: i for i in del_sub}
            logger.info("开始移除订阅...")
            self.delete_subscribe(del_items)

        if new_sub:
            logger.info("开始添加订阅...")
            msg = self.add_subscribe({i: items[i] for i in new_sub})
            if msg:
                logger.info("\n".ljust(49, ' ').join(list(msg.values())))

    # 添加订阅
    def add_subscribe(self, items: Dict[int, Dict[str, Any]]) -> Dict:
        """添加订阅"""
        fail_items = {}
        for self._subid, item in items.items():
            meta = MetaInfo(item.get("name_cn"))
            if not meta.name:
                fail_items[self._subid] = f"{item.get('name_cn')} 未识别到有效数据"
                logger.warn(f"{item.get('name_cn')} 未识别到有效数据")
                continue

            meta.year = item.get("date")[:4] if item.get("date") else None
            mediainfo = self.chain.recognize_media(meta=meta)
            if not mediainfo:
                fail_items[self._subid] = f"{item.get('name_cn')} 媒体信息识别失败"
                continue

            self.update_media_info(item, mediainfo)

            sid = self.subscribeoper.list_by_tmdbid(
                mediainfo.tmdb_id, mediainfo.number_of_seasons
            )
            if sid:
                logger.info(f"{mediainfo.title_year} {meta.season} 正在订阅中")
                if len(sid) == 1:
                    self.subscribeoper.update(
                        sid=sid[0].id, payload={"bangumiid": self._subid}
                    )
                    logger.info(
                        f"{mediainfo.title_year} {meta.season} Bangumi条目id更新成功"
                    )
                continue

            sid, msg = self.subscribechain.add(
                title=mediainfo.title,
                year=mediainfo.year,
                mtype=mediainfo.type,
                tmdbid=mediainfo.tmdb_id,
                bangumiid=self._subid,
                season=mediainfo.number_of_seasons,
                exist_ok=True,
                username="Bangumi订阅",
                **self.prepare_kwargs(item, meta.begin_season, mediainfo),
            )
            if not sid:
                fail_items[self._subid] = f"{item.get('name_cn')} {msg}"

        return fail_items

    def prepare_kwargs(self, item: dict, meta_season: int, mediainfo: MediaInfo):
        """准备额外参数"""
        kwargs = {
            "save_path": self._save_path,
            "sites": (
                self._sites
                if self.are_types_equal(attribute_name='sites')
                else json.dumps(self._sites)
            ),
        }

        if self.check_series_info(meta_season, item.get("eps", 0), mediainfo):
            begin_ep, total_ep = self.get_eps()
            prev_eps: list = [i for i in range(1, begin_ep)]
            kwargs.update(
                {
                    "total_episode": total_ep,
                    "start_episode": begin_ep,
                    "lack_episode": total_ep - begin_ep + 1,
                    "note": (
                        prev_eps
                        if self.are_types_equal("note")
                        else json.dumps(prev_eps)
                    ),
                }
            )
            logger.info(
                f"{mediainfo.title_year} 更新总集数为: {total_ep}，开始集数为: {begin_ep}"
            )

        return kwargs

    @staticmethod
    def check_series_info(meta_season: int, bgm_eps: int, mediainfo: MediaInfo) -> bool:
        """检查系列信息是否不一致"""
        total_episode = len(mediainfo.seasons.get(mediainfo.number_of_seasons) or [])
        return (
            meta_season
            and mediainfo.number_of_seasons != meta_season
            or (bgm_eps != 0 and total_episode != bgm_eps)
            or (bgm_eps == 0 and not total_episode >= 12)
        )

    def update_media_info(self, item, mediainfo):
        """更新媒体信息"""
        for info in mediainfo.season_info:
            if self.are_dates(item.get("date"), info.get("air_date")):
                mediainfo.number_of_seasons = info.get("season_number")
                mediainfo.number_of_episodes = info.get("episode_count")
                break

    def get_eps(self) -> tuple:
        """获取Bangumi条目的集数信息"""
        try:
            res = self.get_bgm_res(addr="getEpisodes", id=self._subid)
            data = res.json().get("data", [{}])[0]
            ep = data.get("ep", 1)
            sort = data.get("sort", 1)
            total = res.json().get("total", 24)
            begin_ep = sort - ep + 1
            total_ep = sort - ep + total
            return begin_ep, total_ep
        except Exception as e:
            logger.error(f"获取集数信息失败: {str(e)}")
            return 1, 24  # 默认值

    # 移除订阅
    def delete_subscribe(self, del_items: Dict[int, int]):
        """删除订阅"""
        for subscribe_id in del_items.keys():
            try:
                subscribe = self.subscribeoper.get(subscribe_id)
                if subscribe:
                    self.subscribeoper.delete(subscribe_id)
                    self.subscribehelper.sub_done_async(
                        {"tmdbid": subscribe.tmdbid, "doubanid": subscribe.doubanid}
                    )
                    self.post_message(
                        mtype=NotificationType.Subscribe,
                        title=f"{subscribe.name}({subscribe.year}) 第{subscribe.season}季 已取消订阅",
                        text=f"原因: 未在Bangumi收藏中找到该条目\n订阅用户: {subscribe.username}\n创建时间: {subscribe.date}",
                        image=subscribe.backdrop,
                    )
            except Exception as e:
                logger.error(f"删除订阅失败 {subscribe_id}: {str(e)}")

    @staticmethod
    def get_bgm_res(addr: str, id: int | str):
        url = {
            "UserCollections": f"https://api.bgm.tv/v0/users/{str(id)}/collections?subject_type=2",
            "getEpisodes": f"https://api.bgm.tv/v0/episodes?subject_id={str(id)}&type=0&limit=1",
        }
        headers = {
            "User-Agent": "wikrin/MoviePilot-Plugins (https://github.com/wikrin/MoviePilot-Plugins)"
        }
        return RequestUtils(headers=headers).get_res(url=url[addr])

    @staticmethod
    def are_dates(date_str1, date_str2, threshold_days: int = 7) -> bool:
        """对比两个日期字符串是否接近"""
        date1 = datetime.datetime.strptime(date_str1, '%Y-%m-%d')
        date2 = datetime.datetime.strptime(date_str2, '%Y-%m-%d')
        return abs((date1 - date2).days) <= threshold_days

    @db_query
    def get_subscribe_history(self, db: Session = None) -> set:
        """获取已完成的订阅"""
        try:
            result = (
                db.query(SubscribeHistory)
                .filter(SubscribeHistory.bangumiid.isnot(None))
                .all()
            )
            return {i.bangumiid for i in result}
        except Exception as e:
            logger.error(f"获取订阅历史失败: {str(e)}")
            return set()

    @staticmethod
    def are_types_equal(
        attribute_name: str, expected_type: Type[Any] = JSON(), class_=Subscribe
    ) -> bool:
        """比较类中属性的类型与expected_type是否一致"""
        column = class_.__table__.columns.get(attribute_name)
        if column is None:
            raise AttributeError(
                f"Class: {class_.__name__} 没有属性: '{attribute_name}'"
            )
        return isinstance(column.type, type(expected_type))
