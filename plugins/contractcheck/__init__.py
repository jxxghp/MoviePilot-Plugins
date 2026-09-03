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

from app.core.config import settings
from app.core.event import Event
from app.core.event import eventmanager
from app.db.site_oper import SiteOper
from app.helper.browser import PlaywrightHelper
from app.helper.module import ModuleHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.contractcheck.siteuserinfo import ISiteUserInfo
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from app.utils.timer import TimerUtils

warnings.filterwarnings("ignore", category=FutureWarning)

lock = Lock()


class ContractCheck(_PluginBase):
    # 插件名称
    plugin_name = "契约检查"
    # 插件描述
    plugin_desc = "定时检查保种契约达成情况。"
    # 插件图标
    plugin_icon = "contract.png"
    # 插件版本
    plugin_version = "1.4.1"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "contractcheck_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 2

    class ContractInfo:
        def __init__(
                self,
                site_name: str = "",
                official: bool = False,
                size: int = 0,
                num: int = 0,
                duration: int = 0,
                date: datetime = datetime.now(),
        ):
            self.site_name: str = site_name
            self.official: bool = official
            self.size: int = size
            self.num: int = num
            self.duration: int = duration
            self.date: datetime = date

    # 私有属性
    statistic_sites: list = []
    contract_infos: list[ContractInfo] = []
    _scheduler: Optional[BackgroundScheduler] = None
    _sites_data: dict = {}
    _site_schema: List[ISiteUserInfo] = None

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _notify: bool = False
    _queue_cnt: int = 5
    _contract_infos: str = ""
    _dashboard_type: str = "brief"

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()
        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._queue_cnt = config.get("queue_cnt")
            self._contract_infos = config.get("contract_infos")
            self.parse_contract_infos(self._contract_infos)
            self._dashboard_type = config.get("dashboard_type") or "brief"

        # 获取历史数据
        self._sites_data = self.get_data("contractcheck")
        if self._enabled or self._onlyonce:
            # 加载模块
            self._site_schema = ModuleHelper.load(
                "app.plugins.contractcheck.siteuserinfo",
                filter_func=lambda _, obj: hasattr(obj, "schema"),
            )

            self._site_schema.sort(key=lambda x: x.order)

            # 立即运行一次
            if self._onlyonce:
                # 站点数据
                self._sites_data = {}
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"保种契约检查服务启动，立即运行一次")
                self._scheduler.add_job(
                    self.refresh_all_site_data,
                    "date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                )
                # 关闭一次性开关
                self._onlyonce = False

                # 保存配置
                self.__update_config()

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def parse_contract_infos(self, infos):
        if infos is None:
            return
        info_list = infos.split("\n")
        for info in info_list:
            _site_name, _official, _size, _num, _duration, date = info.split("|")
            site_id = self._get_site_id(_site_name)
            if site_id is None:
                logger.error(f"站点{_site_name}不在数据库中，请检查配置！")
                continue
            date_format = "%Y/%m/%d"
            date = datetime.strptime(date, date_format)
            _official = True if _official == "是" else False
            c_info = self.ContractInfo(
                _site_name,
                _official,
                int(_size) * 1024 * 1024 * 1024,
                int(_num),
                int(_duration),
                date,
            )
            self.contract_infos.append(c_info)
            self.statistic_sites.append(site_id)

    def _get_site_id(self, name):
        all_sites = [site for site in SiteOper().list_order_by_pri()] + [
            site for site in self.__custom_sites()
        ]
        for site in all_sites:
            if name == site.name:
                return site.id
        return None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/contract_check",
                "event": EventType.PluginAction,
                "desc": "保种契约检查",
                "category": "",
                "data": {"action": "contract_check"},
            }
        ]

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
                    "id": "ContractCheck",
                    "name": "契约检查服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.refresh_all_site_data,
                    "kwargs": {},
                }
            ]
        elif self._enabled:
            triggers = TimerUtils.random_scheduler(
                num_executions=1,
                begin_hour=0,
                end_hour=1,
                min_interval=1,
                max_interval=60,
            )
            ret_jobs = []
            for trigger in triggers:
                ret_jobs.append(
                    {
                        "id": f"ContractCheck|{trigger.hour}:{trigger.minute}",
                        "name": "契约检查服务",
                        "trigger": "cron",
                        "func": self.refresh_all_site_data,
                        "kwargs": {"hour": trigger.hour, "minute": trigger.minute},
                    }
                )
            return ret_jobs
        return []

    def __get_total_elements(self, dashboard_type: str) -> List[dict]:
        if dashboard_type == "detail":
            return self.__get_detail_report()
        else:
            return self.__get_brief_report()

    def __get_detail_report(self):
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        logger.info(f"self._sites_data: {self._sites_data} ")
        if not self._sites_data:
            return [
                {
                    "component": "div",
                    "text": "暂无数据",
                    "props": {
                        "class": "text-center",
                    },
                }
            ]

        # 站点数据明细
        site_trs = [
            {
                "component": "tr",
                "props": {"class": "text-sm"},
                "content": [
                    {
                        "component": "td",
                        "props": {
                            "class": "whitespace-nowrap break-keep text-high-emphasis"
                        },
                        "text": site,
                    },
                    {"component": "td", "text": data.get("is_official")},
                    {"component": "td", "text": data.get("contract_size")},
                    {"component": "td", "text": data.get("contract_num")},
                    {
                        "component": "td",
                        "text": str(data.get("contract_duration")) + " 天",
                    },
                    {"component": "td", "text": data.get("contract_start_on")},
                    {"component": "td", "text": data.get("total_seed_size")},
                    {"component": "td", "text": data.get("total_seed_num")},
                    {"component": "td", "text": data.get("official_seed_size")},
                    {"component": "td", "text": data.get("official_seed_num")},
                    {
                        "component": "td",
                        "props": {
                            "class": (
                                "text-success"
                                if data.get("is_satisfied")
                                else "text-error"
                            )
                        },
                        "text": "是" if data.get("is_satisfied") else "否",
                    },
                    {"component": "td", "text": data.get("size_gap")},
                    {"component": "td", "text": data.get("num_gap")},
                    {"component": "td", "text": str(data.get("duration_gap")) + " 天"},
                ],
            }
            for site, data in self._sites_data.items()
            if not data.get("err_msg")
        ]

        # 拼装页面
        return [
            # 各站点数据明细
            {
                "component": "VCol",
                "props": {
                    "cols": 12,
                },
                "content": [
                    {
                        "component": "VTable",
                        "props": {"hover": True},
                        "content": [
                            {
                                "component": "thead",
                                "content": [
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "契约站点",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "是否官种",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "契约体积",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "契约数量",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "契约周期",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "开始时间",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "保种体积",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "保种数量",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "官种体积",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "官种数量",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "是否满足",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "需增体积",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "需增数量",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "剩余时间",
                                    },
                                ],
                            },
                            {"component": "tbody", "content": site_trs},
                        ],
                    }
                ],
            }
        ]

    def __get_brief_report(self):
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        logger.info(f"self._sites_data: {self._sites_data} ")
        if not self._sites_data:
            return [
                {
                    "component": "div",
                    "text": "暂无数据",
                    "props": {
                        "class": "text-center",
                    },
                }
            ]

        # 站点数据明细
        site_trs = [
            {
                "component": "tr",
                "props": {"class": "text-sm"},
                "content": [
                    {
                        "component": "td",
                        "props": {
                            "class": "whitespace-nowrap break-keep text-high-emphasis"
                        },
                        "text": site,
                    },
                    {
                        "component": "td",
                        "props": {
                            "class": (
                                "text-success"
                                if data.get("is_satisfied")
                                else "text-error"
                            )
                        },
                        "text": "是" if data.get("is_satisfied") else "否",
                    },
                    {"component": "td", "text": data.get("size_gap")},
                    {"component": "td", "text": data.get("num_gap")},
                    {"component": "td", "text": str(data.get("duration_gap")) + " 天"},
                ],
            }
            for site, data in self._sites_data.items()
            if not data.get("err_msg")
        ]

        # 拼装页面
        return [
            # 各站点数据明细
            {
                "component": "VCol",
                "props": {
                    "cols": 12,
                },
                "content": [
                    {
                        "component": "VTable",
                        "props": {"hover": True},
                        "content": [
                            {
                                "component": "thead",
                                "content": [
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "契约站点",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "是否满足",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "需增体积",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "需增数量",
                                    },
                                    {
                                        "component": "th",
                                        "props": {"class": "text-start ps-4"},
                                        "text": "剩余时间",
                                    },
                                ],
                            },
                            {"component": "tbody", "content": site_trs},
                        ],
                    }
                ],
            }
        ]

    def get_dashboard(self, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        # 列配置
        cols = {"cols": 12}
        # 全局配置
        attrs = {}
        # 拼装页面元素
        elements = [
            {
                "component": "VRow",
                "content": self.__get_total_elements(self._dashboard_type),
            }
        ]
        return cols, attrs, elements

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
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
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "5位cron表达式，留空自动",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "queue_cnt",
                                            "label": "队列数量",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "dashboard_type",
                                            "label": "仪表板组件",
                                            "items": [
                                                {
                                                    "title": "详细数据",
                                                    "value": "detail",
                                                },
                                                {"title": "简洁数据", "value": "brief"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "contract_infos",
                                            "label": "契约信息",
                                            "rows": 6,
                                            "placeholder": "站点|是否官种|契约体积(G)|契约周期(天)|契约数量(没要求填0)|开始时间(2024/01/01)",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "契约格式为：站点名称|是否官种|体积|数量|周期|开始时间。其中站点名称和MP站点显示名称一致，是否官种填是或否，体积单位是GB，周期单位是天，时间格式为YYYY/MM/DD。例子：憨憨|是|2048|200|365|2024/2/6",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "部分站点的官种信息靠种子名称里的官组名称过滤，可能存在官组信息遗漏的情况导致统计信息有误，如遇到此情况请提issue告知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "插件作者的PT站点有限，没法适配所有站点，如有适配站点请与插件作者联系或自行提PR",
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
            "onlyonce": False,
            "notify": True,
            "cron": "5 1 * * *",
            "queue_cnt": 5,
            "dashboard_type": "brief",
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """

        # 拼装页面
        return [{"component": "VRow", "content": self.__get_detail_report()}]

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
        site_cookie = site_info.get("cookie")
        if not site_cookie:
            return None
        site_name = site_info.get("name")
        url = site_info.get("url")
        proxy = site_info.get("proxy")
        ua = site_info.get("ua")
        # 会话管理
        with requests.Session() as session:
            proxies = settings.PROXY if proxy else None
            proxy_server = settings.PROXY_SERVER if proxy else None
            render = site_info.get("render")

            logger.debug(
                f"站点 {site_name} url={url} site_cookie={site_cookie} ua={ua}"
            )
            if render:
                # 演染模式
                html_text = PlaywrightHelper().get_page_source(
                    url=url, cookies=site_cookie, ua=ua, proxies=proxy_server
                )
            else:
                # 普通模式
                res = RequestUtils(
                    cookies=site_cookie, session=session, ua=ua, proxies=proxies
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
                        tmp_url = url + html_text[i: html_text.find(";")].replace(
                            '"', ""
                        ).replace("+", "").replace(" ", "").replace(
                            "window.location=", ""
                        )
                        res = RequestUtils(
                            cookies=site_cookie, session=session, ua=ua, proxies=proxies
                        ).get_res(url=tmp_url)
                        if res and res.status_code == 200:
                            if (
                                    "charset=utf-8" in res.text
                                    or "charset=UTF-8" in res.text
                            ):
                                res.encoding = "UTF-8"
                            else:
                                res.encoding = res.apparent_encoding
                            html_text = res.text
                            if not html_text:
                                return None
                        elif res is not None:
                            logger.error(
                                "站点 %s 被反爬限制：%s, 状态码：%s"
                                % (site_name, url, res.status_code)
                            )
                            return None
                        else:
                            logger.error(f"站点 {site_name} 无法访问：{url}")
                            return None

                    # 兼容假首页情况，假首页通常没有 <link rel="search" 属性
                    if '"search"' not in html_text and '"csrf-token"' not in html_text:
                        res = RequestUtils(
                            cookies=site_cookie, session=session, ua=ua, proxies=proxies
                        ).get_res(url=url + "/index.php")
                        if res and res.status_code == 200:
                            if re.search(
                                    r"charset=\"?utf-8\"?", res.text, re.IGNORECASE
                            ):
                                res.encoding = "utf-8"
                            else:
                                res.encoding = res.apparent_encoding
                            html_text = res.text
                            if not html_text:
                                return None
                elif res is not None:
                    logger.error(
                        f"站点 {site_name} 连接失败，状态码：{res.status_code}"
                    )
                    return None
                else:
                    logger.error(f"站点 {site_name} 无法访问：{url}")
                    return None
            # 解析站点类型
            if html_text:
                site_schema = self.__build_class(html_text)
                if not site_schema:
                    logger.error("站点 %s 无法识别站点类型" % site_name)
                    return None
                return site_schema(
                    site_name,
                    url,
                    site_cookie,
                    html_text,
                    session=session,
                    ua=ua,
                    proxy=proxy,
                )
            return None

    # 检查契约达成情况，返回是否达成、差多少体积、差多少数量、还剩多少时间
    @staticmethod
    def _check_seed_states(contract_info, site_user_info):
        is_size_satisfied = False
        is_num_satisfied = False
        size_gap = 0
        num_gap = 0
        duration_gap = 0
        if contract_info.official:
            current_seeding_size = site_user_info.official_seeding_size
        else:
            current_seeding_size = site_user_info.total_seeding_size

        if contract_info.size < current_seeding_size[1]:
            is_size_satisfied = True
        else:
            size_gap = contract_info.size - current_seeding_size[1]
        if contract_info.num < current_seeding_size[0]:
            is_num_satisfied = True
        else:
            num_gap = contract_info.num - current_seeding_size[0]
        is_satisfied = is_size_satisfied and is_num_satisfied
        duration = (datetime.now() - contract_info.date).days
        if duration < contract_info.duration:
            duration_gap = contract_info.duration - duration
        return is_satisfied, size_gap, num_gap, duration_gap

    def __refresh_site_data(self, site_info: CommentedMap) -> Optional[ISiteUserInfo]:
        """
        更新单个site 数据信息
        :param site_info:
        :return:
        """
        site_name = site_info.get("name")
        site_url = site_info.get("url")
        if not site_url:
            return None
        try:
            site_user_info: ISiteUserInfo = self.build(site_info=site_info)
            if site_user_info:
                # 开始解析
                site_user_info.parse_official_seeding_info()
                logger.info(f"站点 {site_name} 解析完成")

                # 获取不到数据时，仅返回错误信息，不做历史数据更新
                if site_user_info.err_msg:
                    self._sites_data.update(
                        {site_name: {"err_msg": site_user_info.err_msg}}
                    )
                    return None
                contract_info = self.ContractInfo()
                for info in self.contract_infos:
                    if site_name == info.site_name:
                        contract_info = info
                if contract_info is None:
                    logger.error(f"站点{site_name}不在契约站点列表中，请检查配置")
                    return site_user_info

                is_satisfied, size_gap, num_gap, duration_gap = self._check_seed_states(
                    contract_info, site_user_info
                )

                self._sites_data.update(
                    {
                        site_name: {
                            "is_official": "是" if contract_info.official else "否",
                            "contract_size": StringUtils.str_filesize(
                                contract_info.size
                            ),
                            "contract_num": contract_info.num,
                            "contract_duration": contract_info.duration,
                            "contract_start_on": str(contract_info.date),
                            "total_seed_num": site_user_info.total_seeding_size[0],
                            "total_seed_size": StringUtils.str_filesize(
                                site_user_info.total_seeding_size[1]
                            ),
                            "official_seed_num": site_user_info.official_seeding_size[
                                0
                            ],
                            "official_seed_size": StringUtils.str_filesize(
                                site_user_info.official_seeding_size[1]
                            ),
                            "is_satisfied": is_satisfied,
                            "size_gap": StringUtils.str_filesize(size_gap),
                            "num_gap": num_gap,
                            "duration_gap": duration_gap,
                            "err_msg": site_user_info.err_msg,
                        }
                    }
                )
                return site_user_info

        except Exception as e:
            logger.error(f"站点 {site_name} 获取流量数据失败：{str(e)}")
        return None

    @eventmanager.register(EventType.PluginAction)
    def refresh(self, event: Event):
        """
        刷新站点数据
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "contract_check":
                return
            logger.info("收到命令，开始检查保种契约 ...")
            self.post_message(
                channel=event.event_data.get("channel"),
                title="开始检查保种契约 ...",
                userid=event.event_data.get("user"),
            )
        self.refresh_all_site_data()
        if event:
            self.post_message(
                channel=event.event_data.get("channel"),
                title="保种契约检查完成！",
                userid=event.event_data.get("user"),
            )

    def refresh_all_site_data(self):
        """
        多线程刷新站点下载上传量，默认间隔6小时
        """
        if not SitesHelper().get_indexers():
            return

        logger.info("开始刷新站点数据 ...")

        with lock:

            all_sites = [
                            site for site in SitesHelper().get_indexers() if not site.get("public")
                        ] + self.__custom_sites()
            # 没有指定站点，默认使用全部站点
            if not self.statistic_sites:
                refresh_sites = all_sites
            else:
                refresh_sites = [
                    site for site in all_sites if site.get("id") in self.statistic_sites
                ]
            if not refresh_sites:
                return

            # 并发刷新
            with ThreadPool(min(len(refresh_sites), int(self._queue_cnt or 5))) as p:
                p.map(self.__refresh_site_data, refresh_sites)

            # 保存数据
            self.save_data("contractcheck", self._sites_data)

            # 通知刷新完成
            if self._notify:
                notify_message = ""
                for site, data in self._sites_data.items():
                    notify_message += f"------- ***{site}*** -------\n"
                    if data.get("is_official") == "是":
                        notify_message += "***官种契约：***\n"
                    else:
                        notify_message += "***非官种契约：***\n"
                    notify_message += f'体积：{data.get("contract_size")}，数量：{data.get("contract_num")}，周期：{data.get("contract_duration")} 天\n'
                    notify_message += "***保种情况：***\n"
                    notify_message += f'保种总体积：{data.get("total_seed_size")}，数量：{data.get("total_seed_num")}\n'
                    notify_message += f'官种体积：{data.get("official_seed_size")}，数量：{data.get("official_seed_num")}\n'
                    if data.get("duration_gap") == 0:
                        notify_message += "契约已完成，恭喜！！\n\n"
                    else:
                        if data.get("is_satisfied"):
                            notify_message += f"***已满足***契约要求\n"
                        else:
                            notify_message += f'***未满足***契约要求，需增加保种体积{data.get("size_gap")}，需增保种数量：{data.get("num_gap")}\n'
                        notify_message += (
                            f'剩余契约时间***{data.get("duration_gap")}天***\n\n'
                        )
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【保种契约检查】",
                    text=notify_message,
                )

            logger.info("站点数据刷新完成")

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "notify": self._notify,
                "queue_cnt": self._queue_cnt,
                "contract_infos": self._contract_infos,
                "dashboard_type": self._dashboard_type,
            }
        )
