import json
import re
import warnings
from datetime import datetime, timedelta
from multiprocessing.dummy import Pool as ThreadPool
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ruamel.yaml import CommentedMap

from app import schemas
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.models import PluginData
from app.db.site_oper import SiteOper
from app.helper.browser import PlaywrightHelper
from app.helper.module import ModuleHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.sitestatistic.siteuserinfo import ISiteUserInfo
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.object import ObjectUtils
from app.utils.string import StringUtils
from app.utils.timer import TimerUtils

warnings.filterwarnings("ignore", category=FutureWarning)

lock = Lock()


class SiteStatistic(_PluginBase):
    # 插件名称
    plugin_name = "站点数据统计"
    # 插件描述
    plugin_desc = "自动统计和展示站点数据。"
    # 插件图标
    plugin_icon = "statistic.png"
    # 插件版本
    plugin_version = "4.0.1"
    # 插件作者
    plugin_author = "lightolly"
    # 作者主页
    author_url = "https://github.com/lightolly"
    # 插件配置项ID前缀
    plugin_config_prefix = "sitestatistic_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    sites = None
    siteoper = None
    _scheduler: Optional[BackgroundScheduler] = None
    _last_update_time: Optional[datetime] = None
    _sites_data: dict = {}
    _site_schema: List[ISiteUserInfo] = None

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _sitemsg: bool = True
    _cron: str = ""
    _notify: bool = False
    _queue_cnt: int = 5
    _remove_failed: bool = False
    _statistic_type: str = None
    _statistic_sites: list = []
    _dashboard_type: str = "today"

    def init_plugin(self, config: dict = None):
        self.sites = SitesHelper()
        self.siteoper = SiteOper()
        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._sitemsg = config.get("sitemsg")
            self._queue_cnt = config.get("queue_cnt")
            self._remove_failed = config.get("remove_failed")
            self._statistic_type = config.get("statistic_type") or "all"
            self._statistic_sites = config.get("statistic_sites") or []
            self._dashboard_type = config.get("dashboard_type") or "today"

            # 过滤掉已删除的站点
            all_sites = [site.id for site in self.siteoper.list_order_by_pri()] + [site.get("id") for site in
                                                                                   self.__custom_sites()]
            self._statistic_sites = [site_id for site_id in all_sites if site_id in self._statistic_sites]
            self.__update_config()

        if self._enabled or self._onlyonce:
            # 加载模块
            self._site_schema = ModuleHelper.load('app.plugins.sitestatistic.siteuserinfo',
                                                  filter_func=lambda _, obj: hasattr(obj, 'schema'))

            self._site_schema.sort(key=lambda x: x.order)
            # 站点上一次更新时间
            self._last_update_time = None
            # 站点数据
            self._sites_data = {}

            # 立即运行一次
            if self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"站点数据统计服务启动，立即运行一次")
                self._scheduler.add_job(self.refresh_all_site_data, 'date',
                                        run_date=datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False

                # 保存配置
                self.__update_config()

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/site_statistic",
            "event": EventType.PluginAction,
            "desc": "站点数据统计",
            "category": "站点",
            "data": {
                "action": "site_statistic"
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
        return [{
            "path": "/refresh_by_domain",
            "endpoint": self.refresh_by_domain,
            "methods": ["GET"],
            "summary": "刷新站点数据",
            "description": "刷新对应域名的站点数据",
        }]

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
            return [{
                "id": "SiteStatistic",
                "name": "站点数据统计服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.refresh_all_site_data,
                "kwargs": {}
            }]
        elif self._enabled:
            triggers = TimerUtils.random_scheduler(num_executions=1,
                                                   begin_hour=0,
                                                   end_hour=1,
                                                   min_interval=1,
                                                   max_interval=60)
            ret_jobs = []
            for trigger in triggers:
                ret_jobs.append({
                    "id": f"SiteStatistic|{trigger.hour}:{trigger.minute}",
                    "name": "站点数据统计服务",
                    "trigger": "cron",
                    "func": self.refresh_all_site_data,
                    "kwargs": {
                        "hour": trigger.hour,
                        "minute": trigger.minute
                    }
                })
            return ret_jobs
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点的可选项（内置站点 + 自定义站点）
        customSites = self.__custom_sites()

        site_options = ([{"title": site.name, "value": site.id}
                         for site in self.siteoper.list_order_by_pri()]
                        + [{"title": site.get("name"), "value": site.get("id")}
                           for site in customSites])

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
                                    'md': 3
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'queue_cnt',
                                            'label': '队列数量'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'statistic_type',
                                            'label': '统计类型',
                                            'items': [
                                                {'title': '全量', 'value': 'all'},
                                                {'title': '增量', 'value': 'add'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'dashboard_type',
                                            'label': '仪表板组件',
                                            'items': [
                                                {'title': '今日数据', 'value': 'today'},
                                                {'title': '汇总数据', 'value': 'total'},
                                                {'title': '所有数据', 'value': 'all'}
                                            ]
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
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'statistic_sites',
                                            'label': '统计站点',
                                            'items': site_options
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'sitemsg',
                                            'label': '站点未读消息',
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
                                            'model': 'remove_failed',
                                            'label': '移除失效站点',
                                        }
                                    }
                                ]
                            },
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "sitemsg": True,
            "cron": "5 1 * * *",
            "queue_cnt": 5,
            "remove_failed": False,
            "statistic_type": "all",
            "statistic_sites": [],
            "dashboard_type": 'today'
        }

    def __get_data(self) -> Tuple[str, dict, dict]:
        """
        获取今天的日期、今天的站点数据、昨天的站点数据
        """
        # 最近一天的签到数据
        stattistic_data: Dict[str, Dict[str, Any]] = {}
        # 昨天数据
        yesterday_sites_data: Dict[str, Dict[str, Any]] = {}
        # 获取最近所有数据
        data_list: List[PluginData] = self.get_data(key=None)
        if not data_list:
            return "", {}, {}
        # 取key符合日期格式的数据
        data_list = [data for data in data_list if re.match(r"\d{4}-\d{2}-\d{2}", data.key)]
        # 按日期倒序排序
        data_list.sort(key=lambda x: x.key, reverse=True)
        # 今天的日期
        today = data_list[0].key
        # 数据按时间降序排序
        datas = [json.loads(data.value) for data in data_list if ObjectUtils.is_obj(data.value)]
        if len(data_list) > 0:
            stattistic_data = datas[0]
        if len(data_list) > 1:
            yesterday_sites_data = datas[1]

        # 数据按时间降序排序
        stattistic_data = dict(sorted(stattistic_data.items(),
                                      key=lambda item: item[1].get('upload') or 0,
                                      reverse=True))
        return today, stattistic_data, yesterday_sites_data

    @staticmethod
    def __get_total_elements(today: str, stattistic_data: dict, yesterday_sites_data: dict,
                             dashboard: str = "today") -> List[dict]:
        """
        获取统计元素
        """

        def __gb(value: int) -> float:
            """
            转换为GB，保留1位小数
            """
            if not value:
                return 0
            return round(float(value) / 1024 / 1024 / 1024, 1)

        def __sub_dict(d1: dict, d2: dict) -> dict:
            """
            计算两个字典相同Key值的差值（如果值为数字），返回新字典
            """
            if not d1:
                return {}
            if not d2:
                return d1
            d = {k: int(d1.get(k)) - int(d2.get(k)) for k in d1
                 if k in d2 and str(d1.get(k)).isdigit() and str(d2.get(k)).isdigit()}
            # 把小于0的数据变成0
            for k, v in d.items():
                if str(v).isdigit() and int(v) < 0:
                    d[k] = 0
            return d

        if dashboard in ['total', 'all']:
            # 总上传量
            total_upload = sum([int(data.get("upload"))
                                for data in stattistic_data.values() if data.get("upload")])
            # 总下载量
            total_download = sum([int(data.get("download"))
                                  for data in stattistic_data.values() if data.get("download")])
            # 总做种数
            total_seed = sum([int(data.get("seeding"))
                              for data in stattistic_data.values() if data.get("seeding")])
            # 总做种体积
            total_seed_size = sum([int(data.get("seeding_size"))
                                   for data in stattistic_data.values() if data.get("seeding_size")])

            total_elements = [
                # 总上传量
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 6,
                        'md': 3
                    },
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'tonal',
                            },
                            'content': [
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'd-flex align-center',
                                    },
                                    'content': [
                                        {
                                            'component': 'VAvatar',
                                            'props': {
                                                'rounded': True,
                                                'variant': 'text',
                                                'class': 'me-3'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VImg',
                                                    'props': {
                                                        'src': '/plugin_icon/upload.png'
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'div',
                                            'content': [
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-caption'
                                                    },
                                                    'text': '总上传量'
                                                },
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'd-flex align-center flex-wrap'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-h6'
                                                            },
                                                            'text': StringUtils.str_filesize(total_upload)
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    ]
                },
                # 总下载量
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 6,
                        'md': 3,
                    },
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'tonal',
                            },
                            'content': [
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'd-flex align-center',
                                    },
                                    'content': [
                                        {
                                            'component': 'VAvatar',
                                            'props': {
                                                'rounded': True,
                                                'variant': 'text',
                                                'class': 'me-3'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VImg',
                                                    'props': {
                                                        'src': '/plugin_icon/download.png'
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'div',
                                            'content': [
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-caption'
                                                    },
                                                    'text': '总下载量'
                                                },
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'd-flex align-center flex-wrap'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-h6'
                                                            },
                                                            'text': StringUtils.str_filesize(total_download)
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    ]
                },
                # 总做种数
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 6,
                        'md': 3
                    },
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'tonal',
                            },
                            'content': [
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'd-flex align-center',
                                    },
                                    'content': [
                                        {
                                            'component': 'VAvatar',
                                            'props': {
                                                'rounded': True,
                                                'variant': 'text',
                                                'class': 'me-3'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VImg',
                                                    'props': {
                                                        'src': '/plugin_icon/seed.png'
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'div',
                                            'content': [
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-caption'
                                                    },
                                                    'text': '总做种数'
                                                },
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'd-flex align-center flex-wrap'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-h6'
                                                            },
                                                            'text': f'{"{:,}".format(total_seed)}'
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    ]
                },
                # 总做种体积
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 6,
                        'md': 3
                    },
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {
                                'variant': 'tonal',
                            },
                            'content': [
                                {
                                    'component': 'VCardText',
                                    'props': {
                                        'class': 'd-flex align-center',
                                    },
                                    'content': [
                                        {
                                            'component': 'VAvatar',
                                            'props': {
                                                'rounded': True,
                                                'variant': 'text',
                                                'class': 'me-3'
                                            },
                                            'content': [
                                                {
                                                    'component': 'VImg',
                                                    'props': {
                                                        'src': '/plugin_icon/database.png'
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'div',
                                            'content': [
                                                {
                                                    'component': 'span',
                                                    'props': {
                                                        'class': 'text-caption'
                                                    },
                                                    'text': '总做种体积'
                                                },
                                                {
                                                    'component': 'div',
                                                    'props': {
                                                        'class': 'd-flex align-center flex-wrap'
                                                    },
                                                    'content': [
                                                        {
                                                            'component': 'span',
                                                            'props': {
                                                                'class': 'text-h6'
                                                            },
                                                            'text': StringUtils.str_filesize(total_seed_size)
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        else:
            total_elements = []

        if dashboard in ["today", "all"]:
            # 计算增量数据集
            inc_data = {}
            for site, data in stattistic_data.items():
                inc = __sub_dict(data, yesterday_sites_data.get(site))
                if inc:
                    inc_data[site] = inc
            # 今日上传
            uploads = {k: v for k, v in inc_data.items() if v.get("upload")}
            # 今日上传站点
            upload_sites = [site for site in uploads.keys()]
            # 今日上传数据
            upload_datas = [__gb(data.get("upload")) for data in uploads.values()]
            # 今日上传总量
            today_upload = round(sum(upload_datas), 2)
            # 今日下载
            downloads = {k: v for k, v in inc_data.items() if v.get("download")}
            # 今日下载站点
            download_sites = [site for site in downloads.keys()]
            # 今日下载数据
            download_datas = [__gb(data.get("download")) for data in downloads.values()]
            # 今日下载总量
            today_download = round(sum(download_datas), 2)
            # 今日上传下载元素
            today_elements = [
                # 上传量图表
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 6
                    },
                    'content': [
                        {
                            'component': 'VApexChart',
                            'props': {
                                'height': 300,
                                'options': {
                                    'chart': {
                                        'type': 'pie',
                                    },
                                    'labels': upload_sites,
                                    'title': {
                                        'text': f'今日上传（{today}）共 {today_upload} GB'
                                    },
                                    'legend': {
                                        'show': True
                                    },
                                    'plotOptions': {
                                        'pie': {
                                            'expandOnClick': False
                                        }
                                    },
                                    'noData': {
                                        'text': '暂无数据'
                                    }
                                },
                                'series': upload_datas
                            }
                        }
                    ]
                },
                # 下载量图表
                {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 6
                    },
                    'content': [
                        {
                            'component': 'VApexChart',
                            'props': {
                                'height': 300,
                                'options': {
                                    'chart': {
                                        'type': 'pie',
                                    },
                                    'labels': download_sites,
                                    'title': {
                                        'text': f'今日下载（{today}）共 {today_download} GB'
                                    },
                                    'legend': {
                                        'show': True
                                    },
                                    'plotOptions': {
                                        'pie': {
                                            'expandOnClick': False
                                        }
                                    },
                                    'noData': {
                                        'text': '暂无数据'
                                    }
                                },
                                'series': download_datas
                            }
                        }
                    ]
                }
            ]
        else:
            today_elements = []
        # 合并返回
        return total_elements + today_elements

    def get_dashboard(self) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、仪表板页面元素配置json（含数据）；3、全局配置（自动刷新等）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        3、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        """
        # 列配置
        cols = {
            "cols": 12
        }
        # 全局配置
        attrs = {}
        # 获取数据
        today, stattistic_data, yesterday_sites_data = self.__get_data()
        # 汇总
        # 站点统计
        elements = [
            {
                'component': 'VRow',
                'content': self.__get_total_elements(
                    today=today,
                    stattistic_data=stattistic_data,
                    yesterday_sites_data=yesterday_sites_data,
                    dashboard=self._dashboard_type
                )
            }
        ]
        return cols, attrs, elements

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """

        def format_bonus(bonus):
            try:
                return f'{float(bonus):,.1f}'
            except ValueError:
                return '0.0'

        # 获取数据
        today, stattistic_data, yesterday_sites_data = self.__get_data()
        if not stattistic_data:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]

        # 站点统计
        site_totals = self.__get_total_elements(
            today=today,
            stattistic_data=stattistic_data,
            yesterday_sites_data=yesterday_sites_data,
            dashboard='all'
        )

        # 站点数据明细
        site_trs = [
            {
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [
                    {
                        'component': 'td',
                        'props': {
                            'class': 'whitespace-nowrap break-keep text-high-emphasis'
                        },
                        'text': site
                    },
                    {
                        'component': 'td',
                        'text': data.get("username")
                    },
                    {
                        'component': 'td',
                        'text': data.get("user_level")
                    },
                    {
                        'component': 'td',
                        'props': {
                            'class': 'text-success'
                        },
                        'text': StringUtils.str_filesize(data.get("upload"))
                    },
                    {
                        'component': 'td',
                        'props': {
                            'class': 'text-error'
                        },
                        'text': StringUtils.str_filesize(data.get("download"))
                    },
                    {
                        'component': 'td',
                        'text': data.get('ratio')
                    },
                    {
                        'component': 'td',
                        'text': format_bonus(data.get('bonus') or 0)
                    },
                    {
                        'component': 'td',
                        'text': data.get('seeding')
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get('seeding_size'))
                    }
                ]
            } for site, data in stattistic_data.items() if not data.get("err_msg")
        ]

        # 拼装页面
        return [
            {
                'component': 'VRow',
                'content': site_totals + [
                    # 各站点数据明细
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '站点'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '用户名'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '用户等级'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '上传量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '下载量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '分享率'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '魔力值'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '做种数'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '做种体积'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': site_trs
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

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

    def __build_class(self, html_text: str) -> Any:
        for site_schema in self._site_schema:
            try:
                if site_schema.match(html_text):
                    return site_schema
            except Exception as e:
                logger.error(f"站点匹配失败 {str(e)}")
        return None

    def build(self, site_info: CommentedMap) -> Optional[ISiteUserInfo]:
        """
        构建站点信息
        """
        site_name = site_info.get("name")
        site_cookie = site_info.get("cookie")
        apikey = site_info.get("apikey")
        token = site_info.get("token")
        if not site_cookie and not apikey and not token:
            return None
        url = site_info.get("url")
        proxy = site_info.get("proxy")
        ua = site_info.get("ua")
        # 会话管理
        with requests.Session() as session:
            proxies = settings.PROXY if proxy else None
            proxy_server = settings.PROXY_SERVER if proxy else None
            render = site_info.get("render")
            logger.debug(f"站点 {site_name} url={url}，site_cookie={site_cookie}，ua={ua}，api_key={apikey}，token={token}，proxy={proxy}")
            if render:
                # 演染模式
                html_text = PlaywrightHelper().get_page_source(url=url,
                                                               cookies=site_cookie,
                                                               ua=ua,
                                                               proxies=proxy_server)
            else:
                # 普通模式
                res = RequestUtils(cookies=site_cookie,
                                   session=session,
                                   ua=ua,
                                   proxies=proxies
                                   ).get_res(url=url)
                if res and res.status_code == 200:
                    if re.search(r"charset=\"?utf-8\"?", res.text, re.IGNORECASE):
                        res.encoding = "utf-8"
                    else:
                        res.encoding = res.apparent_encoding
                    html_text = res.text
                    # 第一次登录反爬
                    if html_text.find("title") == -1:
                        i = html_text.find("window.location")
                        if i == -1:
                            return None
                        tmp_url = url + html_text[i:html_text.find(";")] \
                            .replace("\"", "") \
                            .replace("+", "") \
                            .replace(" ", "") \
                            .replace("window.location=", "")
                        res = RequestUtils(cookies=site_cookie,
                                           session=session,
                                           ua=ua,
                                           proxies=proxies
                                           ).get_res(url=tmp_url)
                        if res and res.status_code == 200:
                            if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                                res.encoding = "UTF-8"
                            else:
                                res.encoding = res.apparent_encoding
                            html_text = res.text
                            if not html_text:
                                return None
                        elif res is not None:
                            logger.error("站点 %s 被反爬限制：%s, 状态码：%s" % (site_name, url, res.status_code))
                            return None
                        else:
                            logger.error("站点 %s 无法访问：%s" % (site_name, url))
                            return None

                    # 兼容假首页情况，假首页通常没有 <link rel="search" 属性
                    if '"search"' not in html_text and '"csrf-token"' not in html_text:
                        # 排除掉单页面应用，单页面应用首页包含一个 div 容器
                        if not re.search(r"id=\"?root\"?", res.text, re.IGNORECASE):
                            res = RequestUtils(cookies=site_cookie,
                                               session=session,
                                               ua=ua,
                                               proxies=proxies
                                               ).get_res(url=url + "/index.php")
                            if res and res.status_code == 200:
                                if re.search(r"charset=\"?utf-8\"?", res.text, re.IGNORECASE):
                                    res.encoding = "utf-8"
                                else:
                                    res.encoding = res.apparent_encoding
                                html_text = res.text
                                if not html_text:
                                    return None
                elif res is not None:
                    logger.error(f"站点 {site_name} 连接失败，状态码：{res.status_code}")
                    return None
                else:
                    logger.error(f"站点 {site_name} 无法访问：{url}")
                    return None
            # 解析站点类型
            if html_text:
                site_schema = self.__build_class(html_text)
                if not site_schema:
                    logger.error(f"站点 {site_name} 无法识别站点类型，可能是由于插件代码不全，请尝试强制重装插件以确保代码完整")
                    return None
                return site_schema(
                    site_name=site_name,
                    url=url,
                    site_cookie=site_cookie,
                    apikey=apikey,
                    token=token,
                    index_html=html_text,
                    session=session,
                    ua=ua,
                    proxy=proxy)
            return None

    def refresh_by_domain(self, domain: str, apikey: str) -> schemas.Response:
        """
        刷新一个站点数据，可由API调用
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        site_info = self.sites.get_indexer(domain)
        if site_info:
            site_data = self.__refresh_site_data(site_info)
            if site_data:
                return schemas.Response(
                    success=True,
                    message=f"站点 {domain} 刷新成功",
                    data=site_data.to_dict()
                )
            return schemas.Response(
                success=False,
                message=f"站点 {domain} 刷新数据失败，未获取到数据"
            )
        return schemas.Response(
            success=False,
            message=f"站点 {domain} 不存在"
        )

    def __refresh_site_data(self, site_info: CommentedMap) -> Optional[ISiteUserInfo]:
        """
        更新单个site 数据信息
        :param site_info:
        :return:
        """
        site_name = site_info.get('name')
        site_url = site_info.get('url')
        if not site_url:
            return None
        unread_msg_notify = True
        try:
            site_user_info: ISiteUserInfo = self.build(site_info=site_info)
            if site_user_info:
                logger.debug(f"站点 {site_name} 开始以 {site_user_info.site_schema()} 模型解析")
                # 开始解析
                site_user_info.parse()
                logger.debug(f"站点 {site_name} 解析完成")

                # 获取不到数据时，仅返回错误信息，不做历史数据更新
                if site_user_info.err_msg:
                    self._sites_data.update({site_name: {"err_msg": site_user_info.err_msg}})
                    return None

                if self._sitemsg:
                    # 发送通知，存在未读消息
                    self.__notify_unread_msg(site_name, site_user_info, unread_msg_notify)

                # 分享率接近1时，发送消息提醒
                if site_user_info.ratio and float(site_user_info.ratio) < 1:
                    self.post_message(mtype=NotificationType.SiteMessage,
                                      title=f"【站点分享率低预警】",
                                      text=f"站点 {site_user_info.site_name} 分享率 {site_user_info.ratio}，请注意！")

                self._sites_data.update(
                    {
                        site_name: {
                            "upload": site_user_info.upload,
                            "username": site_user_info.username,
                            "user_level": site_user_info.user_level,
                            "join_at": site_user_info.join_at,
                            "download": site_user_info.download,
                            "ratio": site_user_info.ratio,
                            "seeding": site_user_info.seeding,
                            "seeding_size": site_user_info.seeding_size,
                            "leeching": site_user_info.leeching,
                            "bonus": site_user_info.bonus,
                            "url": site_url,
                            "err_msg": site_user_info.err_msg,
                            "message_unread": site_user_info.message_unread,
                            "updated_at": datetime.now().strftime('%Y-%m-%d')
                        }
                    })
                return site_user_info

        except Exception as e:
            import traceback
            logger.error(f"站点 {site_name} 获取流量数据失败：{str(e)}")
            logger.error(traceback.format_exc())
        return None

    def __notify_unread_msg(self, site_name: str, site_user_info: ISiteUserInfo, unread_msg_notify: bool):
        if site_user_info.message_unread <= 0:
            return
        if self._sites_data.get(site_name, {}).get('message_unread') == site_user_info.message_unread:
            return
        if not unread_msg_notify:
            return

        # 解析出内容，则发送内容
        if len(site_user_info.message_unread_contents) > 0:
            for head, date, content in site_user_info.message_unread_contents:
                msg_title = f"【站点 {site_user_info.site_name} 消息】"
                msg_text = f"时间：{date}\n标题：{head}\n内容：\n{content}"
                self.post_message(mtype=NotificationType.SiteMessage, title=msg_title, text=msg_text)
        else:
            self.post_message(mtype=NotificationType.SiteMessage,
                              title=f"站点 {site_user_info.site_name} 收到 "
                                    f"{site_user_info.message_unread} 条新消息，请登陆查看")

    @eventmanager.register(EventType.PluginAction)
    def refresh(self, event: Event):
        """
        刷新站点数据
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "site_statistic":
                return
            logger.info("收到命令，开始刷新站点数据 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始刷新站点数据 ...",
                              userid=event.event_data.get("user"))
        self.refresh_all_site_data()
        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="站点数据刷新完成！", userid=event.event_data.get("user"))

    def refresh_all_site_data(self):
        """
        多线程刷新站点下载上传量，默认间隔6小时
        """
        if not self.sites.get_indexers():
            return

        logger.info("开始刷新站点数据 ...")

        with lock:

            all_sites = [site for site in self.sites.get_indexers() if not site.get("public")] + self.__custom_sites()
            # 没有指定站点，默认使用全部站点
            if not self._statistic_sites:
                refresh_sites = all_sites
            else:
                refresh_sites = [site for site in all_sites if
                                 site.get("id") in self._statistic_sites]
            if not refresh_sites:
                return

            # 将数据初始化为前一天，筛选站点
            yesterday_sites_data = {}
            today_date = datetime.now().strftime('%Y-%m-%d')
            if self._statistic_type == "add" or not self._remove_failed:
                if last_update_time := self.get_data("last_update_time"):
                    yesterday_sites_data = self.get_data(last_update_time) or {}

            if not self._remove_failed and yesterday_sites_data:
                site_names = [site.get("name") for site in refresh_sites]
                self._sites_data = {k: v for k, v in yesterday_sites_data.items() if k in site_names}

            # 并发刷新
            with ThreadPool(min(len(refresh_sites), int(self._queue_cnt or 5))) as p:
                p.map(self.__refresh_site_data, refresh_sites)

            # 通知刷新完成
            if self._notify:
                messages = {}
                # 总上传
                incUploads = 0
                # 总下载
                incDownloads = 0

                for rand, site in enumerate(self._sites_data.keys()):
                    upload = int(self._sites_data[site].get("upload") or 0)
                    download = int(self._sites_data[site].get("download") or 0)
                    updated_date = self._sites_data[site].get("updated_at")

                    if self._statistic_type == "add" and yesterday_sites_data.get(site):
                        upload -= int(yesterday_sites_data[site].get("upload") or 0)
                        download -= int(yesterday_sites_data[site].get("download") or 0)

                    if updated_date and updated_date != today_date:
                        updated_date = f"（{updated_date}）"
                    else:
                        updated_date = ""

                    if upload > 0 or download > 0:
                        incUploads += upload
                        incDownloads += download
                        messages[upload + (rand / 1000)] = (
                                f"【{site}】{updated_date}\n"
                                + f"上传量：{StringUtils.str_filesize(upload)}\n"
                                + f"下载量：{StringUtils.str_filesize(download)}\n"
                                + "————————————"
                        )

                if incDownloads or incUploads:
                    sorted_messages = [messages[key] for key in sorted(messages.keys(), reverse=True)]
                    sorted_messages.insert(0, f"【汇总】\n"
                                              f"总上传：{StringUtils.str_filesize(incUploads)}\n"
                                              f"总下载：{StringUtils.str_filesize(incDownloads)}\n"
                                              f"————————————")
                    self.post_message(mtype=NotificationType.SiteMessage,
                                      title="站点数据统计", text="\n".join(sorted_messages))

            # 保存数据
            self.save_data(today_date, self._sites_data)

            # 更新时间
            self.save_data("last_update_time", today_date)

            self.eventmanager.send_event(etype=EventType.PluginAction, data={
                "action": "sitestatistic_refresh_complete"
            })

            logger.info("站点数据刷新完成")

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "notify": self._notify,
            "sitemsg": self._sitemsg,
            "queue_cnt": self._queue_cnt,
            "remove_failed": self._remove_failed,
            "statistic_type": self._statistic_type,
            "statistic_sites": self._statistic_sites,
            "dashboard_type": self._dashboard_type
        })

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event):
        """
        删除对应站点选中
        """
        site_id = event.event_data.get("site_id")
        config = self.get_config()
        if config:
            statistic_sites = config.get("statistic_sites")
            if statistic_sites:
                if isinstance(statistic_sites, str):
                    statistic_sites = [statistic_sites]

                # 删除对应站点
                if site_id:
                    statistic_sites = [site for site in statistic_sites if int(site) != int(site_id)]
                else:
                    # 清空
                    statistic_sites = []

                # 若无站点，则停止
                if len(statistic_sites) == 0:
                    self._enabled = False

                self._statistic_sites = statistic_sites
                # 保存配置
                self.__update_config()
