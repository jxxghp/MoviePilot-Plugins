import datetime

from typing import Optional, Any, List, Dict

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from apscheduler.triggers.cron import CronTrigger

from app.chain.subscribe import SubscribeChain
from app.core.config import settings

from app.core.context import MediaInfo
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.db.site_oper import SiteOper
from app.utils.http import RequestUtils


class BangumiColl(_PluginBase):
    # 插件名称
    plugin_name = "bangumi收藏订阅"
    # 插件描述
    plugin_desc = "将bangumi用户收藏添加到订阅"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/wikrin/MoviePilot-Plugins/main/icons/bangumi_b.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "Attente"
    # 作者主页
    author_url = "https://github.com/wikrin"
    # 插件配置项ID前缀
    plugin_config_prefix = "bangumicoll_"
    # 加载顺序
    plugin_order = 23
    # 可使用的用户级别
    auth_level = 2

    # 私有变量
    _scheduler: Optional[BackgroundScheduler] = None
    siteoper: SiteOper = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _include: str = ""
    _exclude: str = ""
    _uid: str = ""
    _collection_type = []
    _collection: Dict = {}
    _save_path: str = ""
    _sites: list = []


    def init_plugin(self, config: dict = None):
        self.subscribechain = SubscribeChain()
        self.siteoper = SiteOper()

        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._include = config.get("include")
            self._exclude = config.get("exclude")
            self._uid = config.get("uid")
            self._collection_type = config.get("collection_type") or [3]
            self._collection = config.get("collection")
            self._save_path = config.get("save_path")
            self._sites = config.get("sites")

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"bangumi收藏订阅启动，立即运行一次")
            self._scheduler.add_job(
                func=self.bangumi_coll,
                trigger='date',
                run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ))
                + datetime.timedelta(seconds=3),
            )

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        if self._onlyonce:
            # 关闭一次性开关
            self._onlyonce = False
            # 保存设置
            self.__update_config()

    def __update_config(self):
        """
        更新设置
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "uid": self._uid,
                "collection_type": self._collection_type,
                "collection": self._collection,
                "include": self._include,
                "exclude": self._exclude,
                "save_path": self._save_path,
                "sites": self._sites,
            }
        )

    def get_api(self):
        pass

    def get_command(self):
        pass

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
                                            'label': '发送通知',
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

    def get_page(self):
        pass

        # 注册定时任务
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
                    "id": "BangumiColl",
                    "name": "Bangumi收藏订阅",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.bangumi_coll,
                    "kwargs": {},
                }
            ]
        elif self._enabled:
            return [
                {
                    "id": "BangumiColl",
                    "name": "Bangumi收藏订阅",
                    "trigger": "interval",
                    "func": self.bangumi_coll,
                    "kwargs": {"hours": 6},
                }
            ]
        return []

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

    def get_state(self):
        return self._enabled

    def bangumi_coll(self):
        """
        订阅bangumi用户收藏
        """
        if not self._uid:
            logger.error("请设置UID")
            return

        addr = f"https://api.bgm.tv/v0/users/{self._uid}/collections?subject_type=2"
        headers = {
            "User-Agent": "jxxghp/MoviePilot-Plugins (https://github.com/jxxghp/MoviePilot-Plugins)"
        }

        try:
            logger.info(f"查询bangumi条目信息：{addr} ...")
            res = RequestUtils(headers=headers).get_res(url=addr)
            res = res.json().get("data")
            if not res:
                logger.error(f"bangumi用户：{self._uid} ，未查询到数据")
        except Exception as e:
            logger.error(f"获取bangumi收藏数据失败：{addr} 失败：{str(e)}")

        # 解析出必要数据
        items: Dict[int, Dict[str, Any]] = {}
        logger.info(f"解析bangumi条目信息...")
        for item in res:
            if item.get("type") not in self._collection_type:
                continue
            # 条目id
            subject_id = item.get("subject_id")
            # 主标题
            name = item['subject'].get('name')
            # 中文标题
            name_cn = item['subject'].get('name_cn')
            # 放送时间
            date = item['subject'].get('date')
            ## 这里在后面添加排除规则
            items.update({subject_id: {"name": name, "name_cn": name_cn, "date": date}})
        ## 获取此插件添加的订阅
        db_sub = {i.bangumiid: i.id for i in self.subscribechain.subscribeoper.list() if i.bangumiid and i.username == "Bangumi订阅"}
        # 新增条目
        new_sub = items.keys() - db_sub.keys()
        # 移除条目, 这里暂时不做
        # del_sub = dbrid.keys() - items.keys()
        logger.info(f"解析bangumi条目信息完成，共{len(items)}条,新增{len(new_sub)}条")

        # # 执行移除操作
        # if del_sub:
        #     del_items = {dbrid[i]: i for i in del_sub}
        #     logger.info(f"开始移除订阅...")
        #     self.delete_subscribe(del_items)
        
        # 执行添加操作
        if new_sub:
            new_sub = {i: items[i] for i in new_sub}
            logger.info(f"开始添加订阅...")
            self.add_subscribe(new_sub)
        
        # 结束
        logger.info(f"bangumi收藏订阅执行完成")
        
        

        # 添加订阅
    def add_subscribe(self, items: Dict[int, Dict[str, Any]]):
        for subject_id, item in items.items():
            meta = MetaInfo(item.get("name_cn"))
            if not meta.name:
                logger.warn(f"{item.get('name_cn')} 未识别到有效数据")
                continue
            # 由于bangumi的api不包含季度信息,不传入bangumi条目id,默认使用tmdb
            mediainfo: MediaInfo = self.chain.recognize_media(meta=meta)
            # 对比bangumi和tmdb的信息确定季度
            for info in mediainfo.season_info:
                # 对比日期, 误差默认7天
                if not self.are_dates(item.get("date"), info.get("air_date")):
                    continue
                else:
                    # 更新季度信息
                    mediainfo.number_of_seasons = info.get("season_number")
                    # 更新集数信息
                    mediainfo.number_of_episodes = info.get("episode_count")

            # 检查是否已经订阅
            subflag = self.subscribechain.exists(mediainfo=mediainfo, meta=meta)
            if subflag:
                logger.info(f'{mediainfo.title_year} {meta.season} 正在订阅中')
                continue

            # 额外参数
            kwargs = {
                "save_path": self._save_path,
                "sites": self._sites,
            }
            # 添加到订阅
            self.subscribechain.add(
                title=mediainfo.title,
                year=mediainfo.year,
                mtype=mediainfo.type,
                tmdbid=mediainfo.tmdb_id,
                bangumiid=subject_id,
                season=mediainfo.number_of_seasons,
                exist_ok=True,
                username="Bangumi订阅",
                **kwargs,
            )
    
    def delete_subscribe(self, del_items: dict):
        pass

    @staticmethod
    def are_dates(date_str1, date_str2, threshold_days: int = 7) -> bool:
        """
        对比两个日期字符串是否接近
        :param date_str1: 第一个日期字符串，格式为'YYYY-MM-DD'
        :param date_str2: 第二个日期字符串，格式为'YYYY-MM-DD'
        :param threshold_days: 阈值天数，默认为1天
        :return: 如果两个日期之间的差异小于等于阈值天数，则返回True，否则返回False
        """
        # 将日期字符串转换为datetime对象
        date1 = datetime.datetime.strptime(date_str1, '%Y-%m-%d')
        date2 = datetime.datetime.strptime(date_str2, '%Y-%m-%d')

        # 计算两个日期之间的差异
        delta = abs(date1 - date2)

        # 将阈值转换为timedelta对象
        threshold = datetime.timedelta(days=threshold_days)

        # 比较差异和阈值
        return delta <= threshold
