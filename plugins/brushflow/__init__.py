import base64
import json
import random
import re
import threading
import time
from datetime import datetime, timedelta
from threading import Event
from typing import Any, List, Dict, Tuple, Optional, Union, Set
from urllib.parse import urlparse, parse_qs, unquote

import pytz
from app import schemas
from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.db.site_oper import SiteOper
from app.db.subscribe_oper import SubscribeOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import NotificationType, TorrentInfo
from app.utils.http import RequestUtils
from app.utils.string import StringUtils
from apscheduler.schedulers.background import BackgroundScheduler

lock = threading.Lock()


class BrushConfig:
    """
    刷流配置
    """

    def __init__(self, config: dict, process_site_config=True):
        self.enabled = config.get("enabled", False)
        self.notify = config.get("notify", True)
        self.onlyonce = config.get("onlyonce", False)
        self.brushsites = config.get("brushsites", [])
        self.downloader = config.get("downloader", "qbittorrent")
        self.disksize = self.__parse_number(config.get("disksize"))
        self.freeleech = config.get("freeleech", "free")
        self.hr = config.get("hr", "no")
        self.maxupspeed = self.__parse_number(config.get("maxupspeed"))
        self.maxdlspeed = self.__parse_number(config.get("maxdlspeed"))
        self.maxdlcount = self.__parse_number(config.get("maxdlcount"))
        self.include = config.get("include")
        self.exclude = config.get("exclude")
        self.size = config.get("size")
        self.seeder = config.get("seeder")
        self.pubtime = config.get("pubtime")
        self.seed_time = self.__parse_number(config.get("seed_time"))
        self.seed_ratio = self.__parse_number(config.get("seed_ratio"))
        self.seed_size = self.__parse_number(config.get("seed_size"))
        self.download_time = self.__parse_number(config.get("download_time"))
        self.seed_avgspeed = self.__parse_number(config.get("seed_avgspeed"))
        self.seed_inactivetime = self.__parse_number(config.get("seed_inactivetime"))
        self.delete_size_range = config.get("delete_size_range")
        self.up_speed = self.__parse_number(config.get("up_speed"))
        self.dl_speed = self.__parse_number(config.get("dl_speed"))
        self.save_path = config.get("save_path")
        self.clear_task = config.get("clear_task", False)
        self.archive_task = config.get("archive_task", False)
        self.except_tags = config.get("except_tags", True)
        self.except_subscribe = config.get("except_subscribe", True)
        self.brush_sequential = config.get("brush_sequential", False)
        self.proxy_download = config.get("proxy_download", True)
        self.proxy_delete = config.get("proxy_delete", False)
        self.log_more = config.get("log_more", False)
        self.active_time_range = config.get("active_time_range")
        self.enable_site_config = config.get("enable_site_config", False)
        self.brush_tag = "刷流"
        self.site_config = config.get("site_config", "[]")
        self.group_site_configs = {}

        if self.enable_site_config and process_site_config:
            self.__initialize_site_config()

    def __initialize_site_config(self):
        if not self.site_config:
            self.group_site_configs = {}

        # 定义允许覆盖的字段列表
        allowed_fields = {
            "freeleech",
            "hr",
            "include",
            "exclude",
            "size",
            "seeder",
            "pubtime",
            "seed_time",
            "seed_ratio",
            "seed_size",
            "download_time",
            "seed_avgspeed",
            "seed_inactivetime",
            "save_path",
            "proxy_download",
            "proxy_delete"
            # 当新增支持字段时，仅在此处添加字段名
        }
        try:
            site_configs = json.loads(self.site_config)
            self.group_site_configs = {}
            for config in site_configs:
                sitename = config.get("sitename")
                if not sitename:
                    continue

                # 只从站点特定配置中获取允许的字段
                site_specific_config = {key: config[key] for key in allowed_fields & set(config.keys())}

                full_config = {key: getattr(self, key) for key in vars(self) if
                               key not in ['group_site_configs', 'site_config']}
                full_config.update(site_specific_config)

                self.group_site_configs[sitename] = BrushConfig(config=full_config, process_site_config=False)
        except Exception as e:
            logger.error(f"解析站点配置失败，已停用插件并关闭站点独立配置，请检查配置项，错误详情: {e}")
            self.group_site_configs = {}
            self.enable_site_config = False
            self.enabled = False

    def get_site_config(self, sitename):
        """
        根据站点名称获取特定的BrushConfig实例。如果没有找到站点特定的配置，则返回全局的BrushConfig实例。
        """
        if not self.enable_site_config:
            return self
        return self if not sitename else self.group_site_configs.get(sitename, self)

    @staticmethod
    def __parse_number(value):
        if value is None or value == '':  # 更精确地检查None或空字符串
            return value
        elif isinstance(value, int):  # 直接判断是否为int
            return value
        elif isinstance(value, float):  # 直接判断是否为float
            return value
        else:
            try:
                number = float(value)
                # 检查number是否等于其整数形式
                if number == int(number):
                    return int(number)
                else:
                    return number
            except (ValueError, TypeError):
                return 0

    def __format_value(self, v):
        """
        Format the value to mimic JSON serialization. This is now an instance method.
        """
        if isinstance(v, str):
            return f'"{v}"'
        elif isinstance(v, (int, float, bool)):
            return str(v).lower() if isinstance(v, bool) else str(v)
        elif isinstance(v, list):
            return '[' + ', '.join(self.__format_value(i) for i in v) + ']'
        elif isinstance(v, dict):
            return '{' + ', '.join(f'"{k}": {self.__format_value(val)}' for k, val in v.items()) + '}'
        else:
            return str(v)

    def __str__(self):
        attrs = vars(self)
        # Note the use of self.format_value(v) here to call the instance method
        attrs_str = ', '.join(f'"{k}": {self.__format_value(v)}' for k, v in attrs.items())
        return f'{{ {attrs_str} }}'

    def __repr__(self):
        return self.__str__()


class BrushFlow(_PluginBase):
    # region 全局定义

    # 插件名称
    plugin_name = "站点刷流"
    # 插件描述
    plugin_desc = "自动托管刷流，将会提高对应站点的访问频率。"
    # 插件图标
    plugin_icon = "brush.jpg"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "jxxghp,InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "brushflow_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    siteshelper = None
    siteoper = None
    torrents = None
    subscribeoper = None
    qb = None
    tr = None
    # 刷流配置
    _brush_config = None
    # Brush任务是否启动
    _task_brush_enable = False
    # Brush定时
    _brush_interval = 10
    # Check定时
    _check_interval = 5
    # 退出事件
    _event = Event()
    _scheduler = None

    # endregion

    def init_plugin(self, config: dict = None):
        logger.info(f"站点刷流服务初始化")
        self.siteshelper = SitesHelper()
        self.siteoper = SiteOper()
        self.torrents = TorrentsChain()
        self.subscribeoper = SubscribeOper()
        self._task_brush_enable = False

        if not config:
            logger.info("站点刷流任务出错，无法获取插件配置")
            return False

        # 如果没有站点配置时，增加默认的配置项
        if not config.get("site_config"):
            config["site_config"] = self.__get_demo_site_config()

        # 如果配置校验没有通过，那么这里修改配置文件后退出
        if not self.__validate_and_fix_config(config=config):
            self._brush_config = BrushConfig(config=config)
            self._brush_config.enabled = False
            self.__update_config()
            return

        self._brush_config = BrushConfig(config=config)

        brush_config = self._brush_config

        # 这里先过滤掉已删除的站点并保存，特别注意的是，这里保留了界面选择站点时的顺序，以便后续站点随机刷流或顺序刷流
        site_id_to_public_status = {site.get("id"): site.get("public") for site in self.siteshelper.get_indexers()}
        brush_config.brushsites = [
            site_id for site_id in brush_config.brushsites
            if site_id in site_id_to_public_status and not site_id_to_public_status[site_id]
        ]

        self.__update_config()

        if brush_config.clear_task:
            self.__clear_tasks()
            brush_config.clear_task = False
            brush_config.archive_task = False
            self.__update_config()

        elif brush_config.archive_task:
            self.__archive_tasks()
            brush_config.archive_task = False
            self.__update_config()

        if brush_config.log_more:
            if brush_config.enable_site_config:
                logger.info(f"已开启站点独立配置，配置信息：{brush_config}")
            else:
                logger.info(f"没有开启站点独立配置，配置信息：{brush_config}")

        # 停止现有任务
        self.stop_service()

        if not self.__setup_downloader():
            return

        # 如果下载器都没有配置，那么这里也不需要继续
        if not brush_config.downloader:
            brush_config.enabled = False
            self.__update_config()
            logger.info(f"站点刷流服务停止，没有配置下载器")
            return

        # 如果站点都没有配置，则不开启定时刷流服务
        if not brush_config.brushsites:
            logger.info(f"站点刷流Brush定时服务停止，没有配置站点")

        # 如果开启&存在站点时，才需要启用后台任务
        self._task_brush_enable = brush_config.enabled and brush_config.brushsites

        # brush_config.onlyonce = True

        # 检查是否启用了一次性任务
        if brush_config.onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            logger.info(f"站点刷流Brush服务启动，立即运行一次")
            self._scheduler.add_job(self.brush, 'date',
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="站点刷流Brush服务")

            logger.info(f"站点刷流Check服务启动，立即运行一次")
            self._scheduler.add_job(self.check, 'date',
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="站点刷流Check服务")

            # 关闭一次性开关
            brush_config.onlyonce = False
            self.__update_config()

            # 存在任务则启动任务
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        brush_config = self.__get_brush_config()
        return True if brush_config and brush_config.enabled else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
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
        services = []

        brush_config = self.__get_brush_config()
        if not brush_config:
            return services

        if self._task_brush_enable:
            logger.info(f"站点刷流Brush定时服务启动，时间间隔 {self._brush_interval} 分钟")
            services.append({
                "id": "BrushFlow",
                "name": "站点刷流Brush服务",
                "trigger": "interval",
                "func": self.brush,
                "kwargs": {"minutes": self._brush_interval}
            })

        if brush_config.enabled:
            logger.info(f"站点刷流Check定时服务启动，时间间隔 {self._check_interval} 分钟")
            services.append({
                "id": "BrushFlowCheck",
                "name": "站点刷流Check服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"minutes": self._check_interval}
            })

        if not services:
            logger.info("站点刷流服务未开启")

        return services

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """

        # 站点的可选项
        site_options = [{"title": site.get("name"), "value": site.get("id")}
                        for site in self.siteshelper.get_indexers()]
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
                                    "cols": 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'brushsites',
                                            'label': '刷流站点',
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
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'downloader',
                                            'label': '下载器',
                                            'items': [
                                                {'title': 'Qbittorrent', 'value': 'qbittorrent'},
                                                {'title': 'Transmission', 'value': 'transmission'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'disksize',
                                            'label': '保种体积（GB）',
                                            'placeholder': '如：500，达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'freeleech',
                                            'label': '促销',
                                            'items': [
                                                {'title': '全部（包括普通）', 'value': ''},
                                                {'title': '免费', 'value': 'free'},
                                                {'title': '2X免费', 'value': '2xfree'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'hr',
                                            'label': '排除H&R',
                                            'items': [
                                                {'title': '是', 'value': 'yes'},
                                                {'title': '否', 'value': 'no'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxupspeed',
                                            'label': '总上传带宽（KB/s）',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxdlspeed',
                                            'label': '总下载带宽（KB/s）',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxdlcount',
                                            'label': '同时下载任务数',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'include',
                                            'label': '包含规则',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '排除规则',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size',
                                            'label': '种子大小（GB）',
                                            'placeholder': '如：5 或 5-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seeder',
                                            'label': '做种人数',
                                            'placeholder': '如：5 或 5-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pubtime',
                                            'label': '发布时间（分钟）',
                                            'placeholder': '如：5 或 5-10'
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
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_time',
                                            'label': '做种时间（小时）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'delete_size_range',
                                            'label': '动态删种阈值（GB）',
                                            'placeholder': '如：500 或 500-1000，达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_ratio',
                                            'label': '分享率',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_size',
                                            'label': '上传量（GB）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'download_time',
                                            'label': '下载超时时间（小时）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_avgspeed',
                                            'label': '平均上传速度（KB/s）',
                                            'placeholder': '低于时删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_inactivetime',
                                            'label': '未活动时间（分钟） ',
                                            'placeholder': '超过时删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'up_speed',
                                            'label': '单任务上传限速（KB/s）',
                                            'placeholder': '种子上传限速'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'dl_speed',
                                            'label': '单任务下载限速（KB/s）',
                                            'placeholder': '种子下载限速'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'save_path',
                                            'label': '保存目录',
                                            'placeholder': '留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'active_time_range',
                                            'label': '开启时间段',
                                            'placeholder': '如：00:00-08:00'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [

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
                                            'model': 'brush_sequential',
                                            'label': '站点顺序刷流',
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
                                            'model': 'except_tags',
                                            'label': '删种排除MoviePilot任务',
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
                                            'model': 'except_subscribe',
                                            'label': '排除订阅（实验性功能）',
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
                                            'model': 'clear_task',
                                            'label': '清除统计数据',
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
                                            'model': 'archive_task',
                                            'label': '归档已删除种子',
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
                                            'model': 'proxy_delete',
                                            'label': '动态删除种子（实验性功能）',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        "content": [
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
                                            'model': 'enable_site_config',
                                            'label': '站点独立配置',
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 4,
                                    # "class": "d-flex justify-end"
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "dialog_closed",
                                            "label": "设置站点"
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
                                            'model': 'proxy_download',
                                            'label': '代理下载种子',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        "content": [
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
                                            'model': 'log_more',
                                            'label': '记录更多日志',
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
                                            'type': 'success',
                                            'variant': 'tonal'
                                        },
                                        'html': "<span class=\"v-alert__underlay\"></span><div class=\"v-alert__prepend\"><svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\"             aria-hidden=\"true\" role=\"img\" tag=\"i\" class=\"v-icon notranslate v-theme--purple iconify iconify--mdi\"             density=\"default\" width=\"1em\" height=\"1em\" viewBox=\"0 0 24 24\"             style=\"font-size: 28px; height: 28px; width: 28px;\">             <path fill=\"currentColor\"                 d=\"M11 9h2V7h-2m1 13c-4.41 0-8-3.59-8-8s3.59-8 8-8s8 3.59 8 8s-3.59 8-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10a10 10 0 0 0 10-10A10 10 0 0 0 12 2m-1 15h2v-6h-2v6Z\">             </path>         </svg></div>     <div class=\"v-alert__content\">部分配置项以及细节请参考<a href='https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/README.md' target='_blank'>https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/README.md</a></div>"
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
                                            'text': '注意：排除H&R并不保证能完全适配所有站点（部分站点在列表页不显示H&R标志，但实际上是有H&R的），请注意核对使用！'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_closed",
                            "max-width": "80rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "content": [
                                    {
                                        "component": "VCardItem",
                                        "text": "设置站点配置"
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {},
                                        "content": [
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
                                                                "component": "VTextarea",
                                                                "props": {
                                                                    "model": "site_config",
                                                                    "placeholder": "请输入站点配置",
                                                                    "label": "站点配置",
                                                                    "rows": 16
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
                                                                    'variant': 'tonal'
                                                                },
                                                                'html': "<span class=\"v-alert__underlay\"></span><div class=\"v-alert__prepend\"><svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\"             aria-hidden=\"true\" role=\"img\" tag=\"i\" class=\"v-icon notranslate v-theme--purple iconify iconify--mdi\"             density=\"default\" width=\"1em\" height=\"1em\" viewBox=\"0 0 24 24\"             style=\"font-size: 28px; height: 28px; width: 28px;\">             <path fill=\"currentColor\"                 d=\"M11 9h2V7h-2m1 13c-4.41 0-8-3.59-8-8s3.59-8 8-8s8 3.59 8 8s-3.59 8-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10a10 10 0 0 0 10-10A10 10 0 0 0 12 2m-1 15h2v-6h-2v6Z\">             </path>         </svg></div>     <div class=\"v-alert__content\">注意：只有启用站点独立配置时，该配置项才会生效，详细配置参考<a href='https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/README.md' target='_blank'>https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/README.md</a></div>"
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
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "clear_task": False,
            "archive_task": False,
            "except_tags": True,
            "except_subscribe": True,
            "brush_sequential": False,
            "proxy_download": True,
            "proxy_delete": False,
            "freeleech": "free",
            "hr": "yes",
            "enable_site_config": False,
            "log_more": False
        }

    def get_page(self) -> List[dict]:
        # 种子明细
        torrents = self.get_data("torrents") or {}
        # 统计数据
        statistic_info = self.__get_statistic_info()

        if not torrents:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        else:
            data_list = torrents.values()
            # 按time倒序排序
            data_list = sorted(data_list, key=lambda x: x.get("time") or 0, reverse=True)
        # 总上传量
        total_uploaded = StringUtils.str_filesize(statistic_info.get("uploaded") or 0)
        # 总下载量
        total_downloaded = StringUtils.str_filesize(statistic_info.get("downloaded") or 0)
        # 下载种子数
        total_count = statistic_info.get("count") or 0
        # 删除种子数
        total_deleted = statistic_info.get("deleted") or 0
        # 待归档种子数
        total_unarchived = statistic_info.get("unarchived") or 0
        # 活跃种子数
        total_active = statistic_info.get("active") or 0
        # 活跃上传量
        total_active_uploaded = StringUtils.str_filesize(statistic_info.get("active_uploaded") or 0)
        # 活跃下载量
        total_active_downloaded = StringUtils.str_filesize(statistic_info.get("active_downloaded") or 0)
        # 种子数据明细
        torrent_trs = [
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
                        'text': data.get("site_name")
                    },
                    {
                        'component': 'td',
                        'html': f'<span style="font-size: .85rem;">{data.get("title")}</span>' +
                                (f'<br><span style="font-size: 0.75rem;">{data.get("description")}</span>' if data.get(
                                    "description") else "")

                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("size"))
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("uploaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("downloaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': round(data.get('ratio') or 0, 2)
                    },
                    {
                        'component': 'td',
                        'text': "是" if data.get("hit_and_run") else "否"
                    },
                    {
                        'component': 'td',
                        'text': f"{data.get('seeding_time') / 3600:.1f}" if data.get('seeding_time') else "N/A"
                    },
                    {
                        'component': 'td',
                        'props': {
                            'class': 'text-no-wrap'
                        },
                        'text': "已删除" if data.get("deleted") else "正常"
                    }
                ]
            } for data in data_list
        ]

        # 拼装页面
        return [
            {
                'component': 'VRow',
                'content': [
                    # 总上传量
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
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
                                                        'text': '总上传量(活跃)'
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
                                                                'text': f"{total_uploaded}({total_active_uploaded})"
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
                            'cols': 12,
                            'md': 3,
                            'sm': 6
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
                                                        'text': '总下载量(活跃)'
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
                                                                'text': f"{total_downloaded}({total_active_downloaded})"
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
                    # 下载种子数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
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
                                                        'text': '下载种子数(活跃)'
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
                                                                'text': f"{total_count}({total_active})"
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
                    # 删除种子数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
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
                                                            'src': '/plugin_icon/delete.png'
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
                                                        'text': '删除种子数(待归档)'
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
                                                                'text': f"{total_deleted}({total_unarchived})"
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
                    },
                    # 种子明细
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
                                        'props': {
                                            'class': 'text-no-wrap'
                                        },
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
                                                'text': '标题'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '大小'
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
                                                'text': 'HR'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '做种时间'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '状态'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': torrent_trs
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
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    # region Brush

    def brush(self):
        """
        定时刷流，添加下载任务
        """
        brush_config = self.__get_brush_config()

        if not brush_config.brushsites or not brush_config.downloader:
            return

        if not self.__is_current_time_in_range():
            logger.info(f"当前不在指定的刷流时间区间内，刷流操作将暂时暂停")
            return

        with lock:
            logger.info(f"开始执行刷流任务 ...")

            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

            # 判断能否通过保种体积前置条件
            size_condition_passed, reason = self.__evaluate_size_condition_for_brush(torrents_size=torrents_size)
            self.__log_brush_conditions(passed=size_condition_passed, reason=reason)
            if not size_condition_passed:
                return

            # 判断能否通过刷流前置条件
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush()
            self.__log_brush_conditions(passed=pre_condition_passed, reason=reason)
            if not pre_condition_passed:
                return

            statistic_info = self.__get_statistic_info()

            # 获取所有站点的信息，并过滤掉不存在的站点
            site_infos = []
            for siteid in brush_config.brushsites:
                siteinfo = self.siteoper.get(siteid)
                if siteinfo:
                    site_infos.append(siteinfo)

            # 根据是否开启顺序刷流来决定是否需要打乱顺序
            if not brush_config.brush_sequential:
                random.shuffle(site_infos)

            logger.info(f"即将针对站点 {', '.join(site.name for site in site_infos)} 开始刷流")

            # 处理所有站点
            for site in site_infos:
                # 如果站点刷流没有正确响应，说明没有通过前置条件，其他站点也不需要继续刷流了
                if not self.__brush_site_torrents(siteid=site.id, torrent_tasks=torrent_tasks,
                                                  statistic_info=statistic_info):
                    logger.info(f"站点 {site.name} 刷流中途结束，停止后续刷流")
                    break
                else:
                    logger.info(f"站点 {site.name} 刷流完成")

            # 保存数据
            self.save_data("torrents", torrent_tasks)
            # 保存统计数据
            self.save_data("statistic", statistic_info)
            logger.info(f"刷流任务执行完成")

    def __brush_site_torrents(self, siteid, torrent_tasks, statistic_info) -> bool:
        """
        针对站点进行刷流
        """
        siteinfo = self.siteoper.get(siteid)
        if not siteinfo:
            logger.warn(f"站点不存在：{siteid}")
            return True

        logger.info(f"开始获取站点 {siteinfo.name} 的新种子 ...")
        torrents = self.torrents.browse(domain=siteinfo.domain)
        if not torrents:
            logger.info(f"站点 {siteinfo.name} 没有获取到种子")
            return True

        brush_config = self.__get_brush_config(sitename=siteinfo.name)

        # 排除包含订阅的种子
        if brush_config.except_subscribe:
            torrents = self.__filter_torrents_contains_subscribe(torrents=torrents)

        # 按发布日期降序排列
        torrents.sort(key=lambda x: x.pubdate or '', reverse=True)

        torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

        logger.info(f"正在准备种子刷流，数量：{len(torrents)}")

        # 过滤种子
        for torrent in torrents:
            # 判断能否通过刷流前置条件
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush(include_network_conditions=False)
            self.__log_brush_conditions(passed=pre_condition_passed, reason=reason, torrent=torrent)
            if not pre_condition_passed:
                return False

            # 判断能否通过保种体积刷流条件
            size_condition_passed, reason = self.__evaluate_size_condition_for_brush(torrents_size=torrents_size,
                                                                                     brush_torrent_size=torrent.size)
            self.__log_brush_conditions(passed=size_condition_passed, reason=reason, torrent=torrent)
            if not size_condition_passed:
                continue

            # 判断能否通过刷流条件
            condition_passed, reason = self.__evaluate_conditions_for_brush(torrent=torrent,
                                                                            torrent_tasks=torrent_tasks)
            self.__log_brush_conditions(passed=condition_passed, reason=reason, torrent=torrent)
            if not condition_passed:
                continue

            # 添加下载任务
            hash_string = self.__download(torrent=torrent)
            if not hash_string:
                logger.warn(f"{torrent.title} 添加刷流任务失败！")
                continue

            # 保存任务信息
            torrent_tasks[hash_string] = {
                "site": siteinfo.id,
                "site_name": siteinfo.name,
                "title": torrent.title,
                "size": torrent.size,
                "pubdate": torrent.pubdate,
                # "site_cookie": torrent.site_cookie,
                # "site_ua": torrent.site_ua,
                # "site_proxy": torrent.site_proxy,
                # "site_order": torrent.site_order,
                "description": torrent.description,
                "imdbid": torrent.imdbid,
                # "enclosure": torrent.enclosure,
                "page_url": torrent.page_url,
                # "seeders": torrent.seeders,
                # "peers": torrent.peers,
                # "grabs": torrent.grabs,
                "date_elapsed": torrent.date_elapsed,
                "freedate": torrent.freedate,
                "uploadvolumefactor": torrent.uploadvolumefactor,
                "downloadvolumefactor": torrent.downloadvolumefactor,
                "hit_and_run": torrent.hit_and_run,
                "volume_factor": torrent.volume_factor,
                "freedate_diff": torrent.freedate_diff,
                # "labels": torrent.labels,
                # "pri_order": torrent.pri_order,
                # "category": torrent.category,
                "ratio": 0,
                "downloaded": 0,
                "uploaded": 0,
                "seeding_time": 0,
                "deleted": False,
                "time": time.time()
            }

            # 统计数据
            torrents_size += torrent.size
            statistic_info["count"] += 1
            logger.info(f"站点 {siteinfo.name}，新增刷流种子下载：{torrent.title}|{torrent.description}")
            self.__send_add_message(torrent)

        return True

    def __evaluate_size_condition_for_brush(self, torrents_size: float,
                                            brush_torrent_size: float = 0.0) -> Tuple[bool, Optional[str]]:
        """
        过滤体积不符合条件的种子
        """
        total_size = self.__bytes_to_gb(torrents_size + brush_torrent_size)  # 预计总做种体积

        def generate_message(config):
            if brush_torrent_size > 0:
                return (f"当前做种体积 {self.__bytes_to_gb(torrents_size):.1f} GB，"
                        f"刷流种子 {self.__bytes_to_gb(brush_torrent_size):.1f} GB，"
                        f"预计做种体积 {total_size:.1f} GB，已超过做种体积 {config} GB")
            else:
                return f"当前做种体积 {self.__bytes_to_gb(torrents_size):.1f} GB，已超过做种体积 {config} GB，暂时停止新增任务"

        reasons = [
            ("disksize",
             lambda config: torrents_size + brush_torrent_size > float(config) * 1024 ** 3, generate_message)
        ]

        brush_config = self.__get_brush_config()
        for condition, check, message in reasons:
            config_value = getattr(brush_config, condition, None)
            if config_value and check(config_value):
                reason = message(config_value)
                return False, reason

        return True, None

    def __evaluate_pre_conditions_for_brush(self, include_network_conditions: bool = True) \
            -> Tuple[bool, Optional[str]]:
        """
        前置过滤不符合条件的种子
        """
        reasons = [
            ("maxdlcount", lambda config: self.__get_downloading_count() >= int(config),
             lambda config: f"当前同时下载任务数已达到最大值 {config}，暂时停止新增任务")
        ]

        if include_network_conditions:
            downloader_info = self.__get_downloader_info()
            if downloader_info:
                current_upload_speed = downloader_info.upload_speed or 0
                current_download_speed = downloader_info.download_speed or 0
                reasons.extend([
                    ("maxupspeed", lambda config: current_upload_speed >= float(config) * 1024,
                     lambda config: f"当前总上传带宽 {StringUtils.str_filesize(current_upload_speed)}，"
                                    f"已达到最大值 {config} KB/s，暂时停止新增任务"),
                    ("maxdlspeed", lambda config: current_download_speed >= float(config) * 1024,
                     lambda config: f"当前总下载带宽 {StringUtils.str_filesize(current_download_speed)}，"
                                    f"已达到最大值 {config} KB/s，暂时停止新增任务"),
                ])

        brush_config = self.__get_brush_config()
        for condition, check, message in reasons:
            config_value = getattr(brush_config, condition, None)
            if config_value and check(config_value):
                reason = message(config_value)
                return False, reason

        return True, None

    def __evaluate_conditions_for_brush(self, torrent, torrent_tasks) -> Tuple[bool, Optional[str]]:
        """
        过滤不符合条件的种子
        """
        brush_config = self.__get_brush_config(torrent.site_name)

        task_key = f"{torrent.site_name}{torrent.title}"
        if any(task_key == f"{task.get('site_name')}{task.get('title')}" for task in torrent_tasks.values()):
            return False, "重复种子"

        # 促销条件
        if brush_config.freeleech and torrent.downloadvolumefactor != 0:
            return False, "非免费种子"
        if brush_config.freeleech == "2xfree" and torrent.uploadvolumefactor != 2:
            return False, "非双倍上传种子"

        # H&R
        if brush_config.hr == "yes" and torrent.hit_and_run:
            return False, "存在H&R"

        # 包含规则
        if brush_config.include and not (
                re.search(brush_config.include, torrent.title, re.I) or re.search(brush_config.include,
                                                                                  torrent.description, re.I)):
            return False, "不符合包含规则"

        # 排除规则
        if brush_config.exclude and (
                re.search(brush_config.exclude, torrent.title, re.I) or re.search(brush_config.exclude,
                                                                                  torrent.description, re.I)):
            return False, "符合排除规则"

        # 种子大小（GB）
        if brush_config.size:
            sizes = [float(size) * 1024 ** 3 for size in brush_config.size.split("-")]
            if len(sizes) == 1 and torrent.size < sizes[0]:
                return False, f"种子大小 {self.__bytes_to_gb(torrent.size):.1f} GB，不符合条件"
            elif len(sizes) > 1 and not sizes[0] <= torrent.size <= sizes[1]:
                return False, f"种子大小 {self.__bytes_to_gb(torrent.size):.1f} GB，不在指定范围内"

        # 做种人数
        if brush_config.seeder:
            seeders_range = [int(n) for n in brush_config.seeder.split("-")]
            # 检查是否仅指定了一个数字，即做种人数需要小于等于该数字
            if len(seeders_range) == 1:
                # 当做种人数大于该数字时，不符合条件
                if torrent.seeders > seeders_range[0]:
                    return False, f"做种人数 {torrent.seeders}，超过单个指定值"
            # 如果指定了一个范围
            elif len(seeders_range) > 1:
                # 检查做种人数是否在指定的范围内（包括边界）
                if not (seeders_range[0] <= torrent.seeders <= seeders_range[1]):
                    return False, f"做种人数 {torrent.seeders}，不在指定范围内"

        # 发布时间
        pubdate_minutes = self.__get_pubminutes(torrent.pubdate)
        pubdate_minutes = self.__adjust_site_pubminutes(pubdate_minutes, torrent)
        if brush_config.pubtime:
            pubtimes = [int(n) for n in brush_config.pubtime.split("-")]
            if len(pubtimes) == 1:
                # 单个值：选择发布时间小于等于该值的种子
                if pubdate_minutes > pubtimes[0]:
                    return False, f"发布时间 {pubdate_minutes:.0f} 分钟前，不符合条件"
            else:
                # 范围值：选择发布时间在范围内的种子
                if not (pubtimes[0] <= pubdate_minutes <= pubtimes[1]):
                    return False, f"发布时间 {pubdate_minutes:.0f} 分钟前，不在指定范围内"

        return True, None

    def __log_brush_conditions(self, passed: bool, reason: str, torrent: Any = None):
        """
        记录刷流日志
        """
        if not passed:
            if not torrent:
                logger.warn(f"种子没有通过前置刷流条件校验，原因：{reason}")
            else:
                brush_config = self.__get_brush_config()
                if brush_config.log_more:
                    logger.warn(f"种子没有通过刷流条件校验，原因：{reason} 种子：{torrent.title}|{torrent.description}")

    # endregion

    # region Check

    def check(self):
        """
        定时检查，删除下载任务
        """
        brush_config = self.__get_brush_config()

        if not brush_config.downloader:
            return

        if not self.__is_current_time_in_range():
            logger.info(f"当前不在指定的刷流时间区间内，检查操作将暂时暂停")
            return

        with lock:
            logger.info("开始检查刷流下载任务 ...")
            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            unmanaged_tasks: Dict[str, dict] = self.get_data("unmanaged") or {}

            downloader = self.__get_downloader(brush_config.downloader)
            if not downloader:
                logger.warn("无法获取下载器实例，将在下个时间周期重试")
                return

            seeding_torrents, error = downloader.get_torrents()
            if error:
                logger.warn("连接下载器出错，将在下个时间周期重试")
                return

            seeding_torrents_dict = {self.__get_hash(torrent): torrent for torrent in seeding_torrents}

            self.__update_seeding_tasks_based_on_tags(torrent_tasks=torrent_tasks, unmanaged_tasks=unmanaged_tasks,
                                                      seeding_torrents_dict=seeding_torrents_dict)

            torrent_check_hashes = list(torrent_tasks.keys())
            if not torrent_tasks or not torrent_check_hashes:
                logger.info("没有需要检查的刷流下载任务")
                return

            logger.info(f"共有 {len(torrent_check_hashes)} 个任务正在刷流，开始检查任务状态")

            # 获取到当前所有做种数据中需要被检查的种子数据
            check_torrents = [seeding_torrents_dict[th] for th in torrent_check_hashes if th in seeding_torrents_dict]

            # 先更新刷流任务的最新状态，上下传，分享率
            self.__update_torrent_tasks_state(torrents=check_torrents, torrent_tasks=torrent_tasks)

            # 先通过获取的全量种子，判断已经被删除，但是任务记录中还没有被标记删除的种子
            undeleted_hashes = self.__get_undeleted_torrents_missing_in_downloader(torrent_tasks, torrent_check_hashes,
                                                                                   check_torrents) or []

            # 这里提前把已经被删除的种子进行标记，避免开启动态删除种子统计体积有时差
            if undeleted_hashes:
                for torrent_hash in undeleted_hashes:
                    torrent_tasks[torrent_hash]["deleted"] = True

            # 排除MoviePilot种子
            if check_torrents and brush_config.except_tags:
                check_torrents = self.__filter_torrents_by_tag(torrents=check_torrents,
                                                               exclude_tag=settings.TORRENT_TAG)

            need_delete_hashes = []

            # 如果配置了删种阈值，则根据动态删种进行分组处理
            if brush_config.proxy_delete and brush_config.delete_size_range:
                logger.info("已开启动态删种，按系统默认动态删种条件开始检查任务")
                proxy_delete_hashs = self.__delete_torrent_for_proxy(torrents=check_torrents,
                                                                     torrent_tasks=torrent_tasks) or []
                need_delete_hashes.extend(proxy_delete_hashs)
            # 否则均认为是没有开启动态删种
            else:
                logger.info("没有开启动态删种，按用户设置删种条件开始检查任务")
                not_proxy_delete_hashs = self.__delete_torrent_for_evaluate_conditions(torrents=check_torrents,
                                                                                       torrent_tasks=torrent_tasks) or []
                need_delete_hashes.extend(not_proxy_delete_hashs)

            if need_delete_hashes:
                if downloader.delete_torrents(ids=need_delete_hashes, delete_file=True):
                    for torrent_hash in need_delete_hashes:
                        torrent_tasks[torrent_hash]["deleted"] = True

            self.__update_and_save_statistic_info(torrent_tasks)

            self.save_data("torrents", torrent_tasks)

            logger.info("刷流下载任务检查完成")

    def __update_torrent_tasks_state(self, torrents: List[Any], torrent_tasks: Dict[str, dict]):
        """
        更新刷流任务的最新状态，上下传，分享率
        """
        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            torrent_info = self.__get_torrent_info(torrent)

            # 更新上传量、下载量
            torrent_task.update({
                "downloaded": torrent_info.get("downloaded"),
                "uploaded": torrent_info.get("uploaded"),
                "ratio": torrent_info.get("ratio"),
                "seeding_time": torrent_info.get("seeding_time"),
            })

    def __update_seeding_tasks_based_on_tags(self, torrent_tasks: Dict[str, dict], unmanaged_tasks: Dict[str, dict],
                                             seeding_torrents_dict: Dict[str, Any]):
        brush_config = self.__get_brush_config()

        if not brush_config.downloader == "qbittorrent":
            return

        # 基于 seeding_torrents_dict 的信息更新或添加到 torrent_tasks
        for torrent_hash, torrent in seeding_torrents_dict.items():
            tags = self.__get_label(torrent=torrent)
            # 判断是否包含刷流标签
            if brush_config.brush_tag in tags:
                # 如果包含刷流标签又不在刷流任务中，则需要加入管理
                if torrent_hash not in torrent_tasks:
                    # 检查该种子是否在 unmanaged_tasks 中
                    if torrent_hash in unmanaged_tasks:
                        # 如果在 unmanaged_tasks 中，移除并转移到 torrent_tasks
                        torrent_task = unmanaged_tasks.pop(torrent_hash)
                        torrent_tasks[torrent_hash] = torrent_task
                        logger.info(
                            f"站点 {torrent_task.get('site_name')}，种子再次加入刷流任务：{torrent_task.get('title')}|{torrent_task.get('description')}")
                        self.__send_add_message(torrent=torrent_task, title="【刷流任务种子再次加入】")
                    else:
                        # 否则，创建一个新的任务
                        torrent_task = self.__convert_torrent_info_to_task(torrent)
                        torrent_tasks[torrent_hash] = torrent_task
                        logger.info(
                            f"站点 {torrent_task.get('site_name')}，种子加入刷流任务：{torrent_task.get('title')}|{torrent_task.get('description')}")
                        self.__send_add_message(torrent=torrent_task, title="【刷流任务种子加入】")
                # 包含刷流标签又在刷流任务中，这里额外处理一个特殊逻辑，就是种子在刷流任务中可能被标记删除但实际上又还在下载器中，这里进行重置
                else:
                    torrent_task = torrent_tasks[torrent_hash]
                    if torrent_task.get("deleted"):
                        torrent_task["deleted"] = False
                        logger.info(
                            f"站点 {torrent_task.get('site_name')}，种子再次加入刷流任务：{torrent_task.get('title')}|{torrent_task.get('description')}")
                        self.__send_add_message(torrent=torrent_task, title="【刷流任务种子再次加入】")
            else:
                # 不包含刷流标签但又在刷流任务中，则移除管理
                if torrent_hash in torrent_tasks:
                    # 如果种子不符合刷流条件但在 torrent_tasks 中，移除并加入 unmanaged_tasks
                    torrent_task = torrent_tasks.pop(torrent_hash)
                    unmanaged_tasks[torrent_hash] = torrent_task
                    logger.info(
                        f"站点 {torrent_task.get('site_name')}，种子移除刷流任务：{torrent_task.get('title')}|{torrent_task.get('description')}")
                    self.__send_delete_message(site_name=torrent_task.get("site_name"),
                                               torrent_title=torrent_task.get("title"),
                                               torrent_desc=torrent_task.get("description"),
                                               reason="刷流标签移除",
                                               title="【刷流任务种子移除】")

        self.save_data("torrents", torrent_tasks)
        self.save_data("unmanaged", unmanaged_tasks)

    def __group_torrents_by_proxy_delete(self, torrents: List[Any], torrent_tasks: Dict[str, dict]):
        """
        根据是否启用动态删种进行分组
        """
        proxy_delete_torrents = []
        not_proxy_delete_torrents = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)

            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            site_name = torrent_task.get("site_name", "")

            brush_config = self.__get_brush_config(site_name)
            if brush_config.proxy_delete:
                proxy_delete_torrents.append(torrent)
            else:
                not_proxy_delete_torrents.append(torrent)

        return proxy_delete_torrents, not_proxy_delete_torrents

    def __evaluate_conditions_for_delete(self, site_name: str, torrent_info: dict) -> Tuple[bool, str]:
        """
        评估删除条件并返回是否应删除种子及其原因
        """
        brush_config = self.__get_brush_config(sitename=site_name)

        if brush_config.seed_time and torrent_info.get("seeding_time") >= float(brush_config.seed_time) * 3600:
            reason = f"做种时间 {torrent_info.get('seeding_time') / 3600:.1f} 小时，大于 {brush_config.seed_time} 小时"
        elif brush_config.seed_ratio and torrent_info.get("ratio") >= float(brush_config.seed_ratio):
            reason = f"分享率 {torrent_info.get('ratio'):.2f}，大于 {brush_config.seed_ratio}"
        elif brush_config.seed_size and torrent_info.get("uploaded") >= float(brush_config.seed_size) * 1024 ** 3:
            reason = f"上传量 {torrent_info.get('uploaded') / 1024 ** 3:.1f} GB，大于 {brush_config.seed_size} GB"
        elif brush_config.download_time and torrent_info.get("downloaded") < torrent_info.get(
                "total_size") and torrent_info.get("dltime") >= float(brush_config.download_time) * 3600:
            reason = f"下载耗时 {torrent_info.get('dltime') / 3600:.1f} 小时，大于 {brush_config.download_time} 小时"
        elif brush_config.seed_avgspeed and torrent_info.get("avg_upspeed") <= float(
                brush_config.seed_avgspeed) * 1024 and torrent_info.get("seeding_time") >= 30 * 60:
            reason = f"平均上传速度 {torrent_info.get('avg_upspeed') / 1024:.1f} KB/s，低于 {brush_config.seed_avgspeed} KB/s"
        elif brush_config.seed_inactivetime and torrent_info.get("iatime") >= float(
                brush_config.seed_inactivetime) * 60:
            reason = f"未活动时间 {torrent_info.get('iatime') / 60:.0f} 分钟，大于 {brush_config.seed_inactivetime} 分钟"
        else:
            return False, ""

        return True, reason

    def __delete_torrent_for_evaluate_conditions(self, torrents: List[Any], torrent_tasks: Dict[str, dict],
                                                 proxy_delete: bool = False) -> List:
        """
        根据条件删除种子并获取已删除列表
        """
        delete_hashs = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue
            site_name = torrent_task.get("site_name", "")
            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")

            torrent_info = self.__get_torrent_info(torrent)

            # 删除种子的具体实现可能会根据实际情况略有不同
            should_delete, reason = self.__evaluate_conditions_for_delete(site_name=site_name,
                                                                          torrent_info=torrent_info)
            if should_delete:
                delete_hashs.append(torrent_hash)
                reason = "触发动态删除，" + reason if proxy_delete else reason
                self.__send_delete_message(site_name=site_name, torrent_title=torrent_title, torrent_desc=torrent_desc,
                                           reason=reason)
                logger.info(f"站点：{site_name}，{reason}，删除种子：{torrent_title}|{torrent_desc}")

        return delete_hashs

    def __delete_torrent_for_proxy(self, torrents: List[Any], torrent_tasks: Dict[str, dict]) -> List:
        """
        支持动态删除种子，当设置了动态删种（全局）和删除阈值时，当做种体积达到删除阈值时，优先按设置规则进行删除，若还没有达到阈值，则排除HR种子后按加入时间倒序进行删除
        删除阈值：100，当做种体积 > 100G 时，则开始删除种子，直至降低至 100G
        删除阈值：50-100，当做种体积 > 100G 时，则开始删除种子，直至降至为 50G
        """
        brush_config = self.__get_brush_config()

        # 如果没有启用动态删除或没有设置删除阈值，则不执行删除操作
        if not (brush_config.proxy_delete and brush_config.delete_size_range):
            return []

        # 解析删除阈值范围
        sizes = [float(size) * 1024 ** 3 for size in brush_config.delete_size_range.split("-")]
        min_size = sizes[0]  # 至少需要达到的做种体积
        max_size = sizes[1] if len(sizes) > 1 else sizes[0]  # 触发删除操作的做种体积上限

        torrent_info_map = {self.__get_hash(torrent): self.__get_torrent_info(torrent=torrent) for torrent in torrents}

        # 计算当前总做种体积
        # total_torrent_size = sum(info.get("total_size", 0) for info in torrent_info_map.values())
        total_torrent_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

        # 当总体积未超过最大阈值时，不需要执行删除操作
        if total_torrent_size < max_size:
            logger.info(
                f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB，上限 {self.__bytes_to_gb(max_size):.1f} GB，下限 {self.__bytes_to_gb(min_size):.1f} GB，未触发动态删除")
            return []
        else:
            logger.info(
                f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB，上限 {self.__bytes_to_gb(max_size):.1f} GB，下限 {self.__bytes_to_gb(min_size):.1f} GB，触发动态删除")

        need_delete_hashes = []

        # 即使开了动态删除，但是也有可能部分站点单独设置了关闭，这里根据种子托管进行分组，先处理不需要托管的种子，按设置的规则进行删除
        proxy_delete_torrents, not_proxy_delete_torrents = self.__group_torrents_by_proxy_delete(torrents=torrents,
                                                                                                 torrent_tasks=torrent_tasks)
        logger.info(f"托管种子数 {len(proxy_delete_torrents)}，未托管种子数 {len(not_proxy_delete_torrents)}")
        if not_proxy_delete_torrents:
            not_proxy_delete_hashes = self.__delete_torrent_for_evaluate_conditions(torrents=not_proxy_delete_torrents,
                                                                                    torrent_tasks=torrent_tasks) or []
            need_delete_hashes.extend(not_proxy_delete_hashes)
            total_torrent_size -= sum(
                torrent_info_map[self.__get_hash(torrent)].get("total_size", 0) for torrent in not_proxy_delete_torrents
                if self.__get_hash(torrent) in not_proxy_delete_hashes)

        # 如果删除非托管种子后仍未达到最小体积要求，则处理托管种子
        if total_torrent_size > min_size and proxy_delete_torrents:
            proxy_delete_hashes = self.__delete_torrent_for_evaluate_conditions(torrents=proxy_delete_torrents,
                                                                                torrent_tasks=torrent_tasks,
                                                                                proxy_delete=True) or []
            need_delete_hashes.extend(proxy_delete_hashes)
            total_torrent_size -= sum(
                torrent_info_map[self.__get_hash(torrent)].get("total_size", 0) for torrent in proxy_delete_torrents if
                self.__get_hash(torrent) in proxy_delete_hashes)

        # 在完成初始删除步骤后，如果总体积仍然超过最小阈值，则进一步找到已完成种子并排除HR种子后按做种时间正序进行删除
        if total_torrent_size > min_size:
            # 重新计算当前的种子列表，排除已删除的种子
            remaining_hashes = list(
                {self.__get_hash(torrent) for torrent in proxy_delete_torrents} - set(need_delete_hashes))
            # 这里根据排除后的种子列表，再次从下载器中找到已完成的任务
            downloader = self.__get_downloader(brush_config.downloader)
            completed_torrents = downloader.get_completed_torrents(ids=remaining_hashes)
            remaining_hashes = {self.__get_hash(torrent) for torrent in completed_torrents}
            remaining_torrents = [(_hash, torrent_info_map[_hash]) for _hash in remaining_hashes]

            # 准备一个列表，用于存放满足条件的种子，即非HR种子且有明确做种时间
            filtered_torrents = [(_hash, info['seeding_time']) for _hash, info in remaining_torrents if
                                 not torrent_tasks[_hash].get("hit_and_run", False)]
            sorted_torrents = sorted(filtered_torrents, key=lambda x: x[1], reverse=True)

            # 进行额外的删除操作，直到满足最小阈值或没有更多种子可删除
            for torrent_hash, _ in sorted_torrents:
                if total_torrent_size <= min_size:
                    break
                torrent_task = torrent_tasks.get(torrent_hash, None)
                torrent_info = torrent_info_map.get(torrent_hash, None)
                if not torrent_task or not torrent_info:
                    continue

                need_delete_hashes.append(torrent_hash)
                total_torrent_size -= torrent_info.get("total_size", 0)

                site_name = torrent_task.get("site_name", "")
                torrent_title = torrent_task.get("title", "")
                torrent_desc = torrent_task.get("description", "")
                seeding_time = torrent_task.get("seeding_time", 0)
                if seeding_time:
                    reason = f"触发动态删除，做种时间 {seeding_time / 3600:.1f} 小时，系统自动删除"
                    self.__send_delete_message(site_name=site_name, torrent_title=torrent_title,
                                               torrent_desc=torrent_desc,
                                               reason=reason)
                    logger.info(f"站点：{site_name}，{reason}，删除种子：{torrent_title}|{torrent_desc}")

        msg = f"已完成 {len(need_delete_hashes)} 个种子删除，当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB"
        self.post_message(mtype=NotificationType.SiteMessage, title="【刷流任务种子删除】", text=msg)
        logger.info(msg)

        # 返回所有需要删除的种子的哈希列表
        return need_delete_hashes

    def __get_undeleted_torrents_missing_in_downloader(self, torrent_tasks, torrent_check_hashes, torrents) -> List:
        """
        处理已经被删除，但是任务记录中还没有被标记删除的种子
        """
        torrent_all_hashes = self.__get_all_hashes(torrents)
        missing_hashes = [hash_value for hash_value in torrent_check_hashes if hash_value not in torrent_all_hashes]
        undeleted_hashes = [hash_value for hash_value in missing_hashes if not torrent_tasks[hash_value].get("deleted")]

        if not undeleted_hashes:
            return []

        # 处理每个符合条件的任务
        for hash_value in undeleted_hashes:
            # 获取对应的任务信息
            torrent_info = torrent_tasks[hash_value]
            # 获取site_name和torrent_title
            site_name = torrent_info.get("site_name", "")
            torrent_title = torrent_info.get("title", "")
            torrent_desc = torrent_info.get("description", "")
            self.__send_delete_message(site_name=site_name, torrent_title=torrent_title, torrent_desc=torrent_desc,
                                       reason="下载器中找不到种子")
            logger.info(f"站点：{site_name}，下载器中找不到种子，删除种子：{torrent_title}|{torrent_desc}")
        return undeleted_hashes

    def __convert_torrent_info_to_task(self, torrent: Any) -> dict:
        """
        根据torrent_info转换成torrent_task
        """
        torrent_info = self.__get_torrent_info(torrent=torrent)

        site_id, site_name = self.__get_site_by_torrent(torrent=torrent)

        torrent_task = {
            "site": site_id,
            "site_name": site_name,
            "title": torrent_info.get("title", ""),
            "size": torrent_info.get("total_size", 0),  # 假设total_size对应于size
            "pubdate": None,
            "description": None,
            "imdbid": None,
            "page_url": None,
            "date_elapsed": None,
            "freedate": None,
            "uploadvolumefactor": None,
            "downloadvolumefactor": None,
            "hit_and_run": None,
            "volume_factor": None,
            "freedate_diff": None,  # 假设无法从torrent_info直接获取
            "ratio": torrent_info.get("ratio", 0),
            "downloaded": torrent_info.get("downloaded", 0),
            "uploaded": torrent_info.get("uploaded", 0),
            "deleted": False,
            "time": torrent_info.get("add_on", time.time())
        }
        return torrent_task

    # endregion

    def __update_and_save_statistic_info(self, torrent_tasks):
        """
        更新并保存统计信息
        """
        total_count, total_uploaded, total_downloaded, total_deleted = 0, 0, 0, 0
        active_uploaded, active_downloaded, active_count, total_unarchived = 0, 0, 0, 0

        statistic_info = self.__get_statistic_info()
        archived_tasks = self.get_data("archived") or {}
        combined_tasks = {**torrent_tasks, **archived_tasks}

        for task in combined_tasks.values():
            if task.get("deleted", False):
                total_deleted += 1
            total_downloaded += task.get("downloaded", 0)
            total_uploaded += task.get("uploaded", 0)

        # 计算torrent_tasks中未标记为删除的活跃任务的统计信息，及待归档的任务数
        for task in torrent_tasks.values():
            if not task.get("deleted", False):
                active_uploaded += task.get("uploaded", 0)
                active_downloaded += task.get("downloaded", 0)
                active_count += 1
            else:
                total_unarchived += 1

        # 更新统计信息
        total_count = len(combined_tasks)
        statistic_info.update({
            "uploaded": total_uploaded,
            "downloaded": total_downloaded,
            "deleted": total_deleted,
            "unarchived": total_unarchived,
            "count": total_count,
            "active": active_count,
            "active_uploaded": active_uploaded,
            "active_downloaded": active_downloaded
        })

        logger.info(f"刷流任务统计数据：总任务数：{total_count}，活跃任务数：{active_count}，已删除：{total_deleted}，"
                    f"待归档：{total_unarchived}，"
                    f"活跃上传量：{StringUtils.str_filesize(active_uploaded)}，"
                    f"活跃下载量：{StringUtils.str_filesize(active_downloaded)}，"
                    f"总上传量：{StringUtils.str_filesize(total_uploaded)}，"
                    f"总下载量：{StringUtils.str_filesize(total_downloaded)}")

        self.save_data("statistic", statistic_info)
        self.save_data("torrents", torrent_tasks)

    def __get_brush_config(self, sitename: str = None) -> BrushConfig:
        """
        获取BrushConfig
        """
        return self._brush_config if not sitename else self._brush_config.get_site_config(sitename=sitename)

    def __validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """
        if config is None:
            logger.error("配置为None，无法验证和修正")
            return False

        # 设置一个标志，用于跟踪是否发现校验错误
        found_error = False

        config_number_attr_to_desc = {
            "disksize": "保种体积",
            "maxupspeed": "总上传带宽",
            "maxdlspeed": "总下载带宽",
            "maxdlcount": "同时下载任务数",
            "seed_time": "做种时间",
            "seed_ratio": "分享率",
            "seed_size": "上传量",
            "download_time": "下载超时时间",
            "seed_avgspeed": "平均上传速度",
            "seed_inactivetime": "未活动时间",
            "up_speed": "单任务上传限速",
            "dl_speed": "单任务下载限速"
        }

        config_range_number_attr_to_desc = {
            "pubtime": "发布时间",
            "size": "种子大小",
            "seeder": "做种人数",
            "delete_size_range": "动态删种阈值"
        }

        for attr, desc in config_number_attr_to_desc.items():
            value = config.get(attr)
            if value and not self.__is_number(value):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = None
                found_error = True  # 更新错误标志

        for attr, desc in config_range_number_attr_to_desc.items():
            value = config.get(attr)
            # 检查 value 是否存在且是否符合数字或数字-数字的模式
            if value and not self.__is_number_or_range(str(value)):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = None
                found_error = True  # 更新错误标志

        active_time_range = config.get("active_time_range")
        if active_time_range and not self.__is_valid_time_range(time_range=active_time_range):
            self.__log_and_notify_error(f"站点刷流任务出错，开启时间段设置错误：{active_time_range}")
            config["active_time_range"] = None
            found_error = True  # 更新错误标志

        # 如果发现任何错误，返回False；否则返回True
        return not found_error

    def __update_config(self, brush_config: BrushConfig = None):
        """
        根据传入的BrushConfig实例更新配置
        """
        if brush_config is None:
            brush_config = self._brush_config

        if brush_config is None:
            return

        # 创建一个将配置属性名称映射到BrushConfig属性值的字典
        config_mapping = {
            "onlyonce": brush_config.onlyonce,
            "enabled": brush_config.enabled,
            "notify": brush_config.notify,
            "brushsites": brush_config.brushsites,
            "downloader": brush_config.downloader,
            "disksize": brush_config.disksize,
            "freeleech": brush_config.freeleech,
            "hr": brush_config.hr,
            "maxupspeed": brush_config.maxupspeed,
            "maxdlspeed": brush_config.maxdlspeed,
            "maxdlcount": brush_config.maxdlcount,
            "include": brush_config.include,
            "exclude": brush_config.exclude,
            "size": brush_config.size,
            "seeder": brush_config.seeder,
            "pubtime": brush_config.pubtime,
            "seed_time": brush_config.seed_time,
            "seed_ratio": brush_config.seed_ratio,
            "seed_size": brush_config.seed_size,
            "download_time": brush_config.download_time,
            "seed_avgspeed": brush_config.seed_avgspeed,
            "seed_inactivetime": brush_config.seed_inactivetime,
            "delete_size_range": brush_config.delete_size_range,
            "up_speed": brush_config.up_speed,
            "dl_speed": brush_config.dl_speed,
            "save_path": brush_config.save_path,
            "clear_task": brush_config.clear_task,
            "archive_task": brush_config.archive_task,
            "except_tags": brush_config.except_tags,
            "except_subscribe": brush_config.except_subscribe,
            "brush_sequential": brush_config.brush_sequential,
            "proxy_download": brush_config.proxy_download,
            "proxy_delete": brush_config.proxy_delete,
            "log_more": brush_config.log_more,
            "active_time_range": brush_config.active_time_range,
            "enable_site_config": brush_config.enable_site_config,
            "site_config": brush_config.site_config
        }

        # 使用update_config方法或其等效方法更新配置
        self.update_config(config_mapping)

    def __setup_downloader(self):
        """
        根据下载器类型初始化下载器实例
        """
        brush_config = self.__get_brush_config()

        if brush_config.downloader == "qbittorrent":
            self.qb = Qbittorrent()
            if self.qb.is_inactive():
                self.__log_and_notify_error("站点刷流任务出错：Qbittorrent未连接")
                return False

        elif brush_config.downloader == "transmission":
            self.tr = Transmission()
            if self.tr.is_inactive():
                self.__log_and_notify_error("站点刷流任务出错：Transmission未连接")
                return False

        return True

    def __get_downloader(self, dtype: str) -> Optional[Union[Transmission, Qbittorrent]]:
        """
        根据类型返回下载器实例
        """
        if dtype == "qbittorrent":
            return self.qb
        elif dtype == "transmission":
            return self.tr
        else:
            return None

    @staticmethod
    def __get_redict_url(url: str, proxies: str = None, ua: str = None, cookie: str = None) -> Optional[str]:
        """
        获取下载链接， url格式：[base64]url
        """
        # 获取[]中的内容
        m = re.search(r"\[(.*)](.*)", url)
        if m:
            # 参数
            base64_str = m.group(1)
            # URL
            url = m.group(2)
            if not base64_str:
                return url
            # 解码参数
            req_str = base64.b64decode(base64_str.encode('utf-8')).decode('utf-8')
            req_params: Dict[str, dict] = json.loads(req_str)
            # 是否使用cookie
            if not req_params.get('cookie'):
                cookie = None
            # 请求头
            if req_params.get('header'):
                headers = req_params.get('header')
            else:
                headers = None
            if req_params.get('method') == 'get':
                # GET请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).get_res(url, params=req_params.get('params'))
            else:
                # POST请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).post_res(url, params=req_params.get('params'))
            if not res:
                return None
            if not req_params.get('result'):
                return res.text
            else:
                data = res.json()
                for key in str(req_params.get('result')).split("."):
                    data = data.get(key)
                    if not data:
                        return None
                logger.info(f"获取到下载地址：{data}")
                return data
        return None

    def __download(self, torrent: TorrentInfo) -> Optional[str]:
        """
        添加下载任务
        """
        if not torrent.enclosure:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return None

        brush_config = self.__get_brush_config(torrent.site_name)

        # 上传限速
        up_speed = int(brush_config.up_speed) if brush_config.up_speed else None
        # 下载限速
        down_speed = int(brush_config.dl_speed) if brush_config.dl_speed else None
        # 保存地址
        download_dir = brush_config.save_path or None
        # 获取下载链接
        torrent_content = torrent.enclosure
        # 部分站点下载种子不需要传递Cookie
        need_download_cookie = True
        if torrent_content.startswith("["):
            torrent_content = self.__get_redict_url(url=torrent_content,
                                                    proxies=settings.PROXY if torrent.site_proxy else None,
                                                    ua=torrent.site_ua,
                                                    cookie=torrent.site_cookie)
            need_download_cookie = False
        if not torrent_content:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return None

        if brush_config.downloader == "qbittorrent":
            if not self.qb:
                return None
            # 限速值转为bytes
            up_speed = up_speed * 1024 if up_speed else None
            down_speed = down_speed * 1024 if down_speed else None
            # 生成随机Tag
            tag = StringUtils.generate_random_str(10)
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if brush_config.proxy_download and not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=torrent.site_cookie if need_download_cookie else None,
                                        proxies=settings.PROXY if torrent.site_proxy else None,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error('代理下载种子失败，继续尝试传递种子地址到下载器进行下载')
            if torrent_content:
                state = self.qb.add_torrent(content=torrent_content,
                                            download_dir=download_dir,
                                            cookie=torrent.site_cookie if need_download_cookie else None,
                                            tag=["已整理", brush_config.brush_tag, tag],
                                            upload_limit=up_speed,
                                            download_limit=down_speed)
                if not state:
                    return None
                else:
                    # 获取种子Hash
                    torrent_hash = self.qb.get_torrent_id_by_tag(tags=tag)
                    if not torrent_hash:
                        logger.error(f"{brush_config.downloader} 获取种子Hash失败"
                                     f"{'，请尝试开启代理下载种子' if not brush_config.proxy_download else ''}")
                        return None
                    return torrent_hash
            return None

        elif brush_config.downloader == "transmission":
            if not self.tr:
                return None
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if brush_config.proxy_download and not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=torrent.site_cookie if need_download_cookie else None,
                                        proxies=settings.PROXY if torrent.site_proxy else None,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error('代理下载种子失败，继续尝试传递种子地址到下载器进行下载')
            if torrent_content:
                torrent = self.tr.add_torrent(content=torrent_content,
                                              download_dir=download_dir,
                                              cookie=torrent.site_cookie if need_download_cookie else None,
                                              labels=["已整理", brush_config.brush_tag])
                if not torrent:
                    return None
                else:
                    if brush_config.up_speed or brush_config.dl_speed:
                        self.tr.change_torrent(hash_string=torrent.hashString,
                                               upload_limit=up_speed,
                                               download_limit=down_speed)
                    return torrent.hashString
        return None

    def __get_hash(self, torrent: Any):
        """
        获取种子hash
        """
        brush_config = self.__get_brush_config()
        try:
            return torrent.get("hash") if brush_config.downloader == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""

    def __get_all_hashes(self, torrents):
        """
        获取torrents列表中所有种子的Hash值

        :param torrents: 包含种子信息的列表
        :return: 包含所有Hash值的列表
        """
        brush_config = self.__get_brush_config()
        try:
            all_hashes = []
            for torrent in torrents:
                # 根据下载器类型获取Hash值
                hash_value = torrent.get("hash") if brush_config.downloader == "qbittorrent" else torrent.hashString
                if hash_value:
                    all_hashes.append(hash_value)
            return all_hashes
        except Exception as e:
            print(str(e))
            return []

    def __get_label(self, torrent: Any):
        """
        获取种子标签
        """
        brush_config = self.__get_brush_config()
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if brush_config.downloader == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    def __get_torrent_info(self, torrent: Any) -> dict:
        """
        获取种子信息
        """
        date_now = int(time.time())
        brush_config = self.__get_brush_config()
        # QB
        if brush_config.downloader == "qbittorrent":
            """
            {
              "added_on": 1693359031,
              "amount_left": 0,
              "auto_tmm": false,
              "availability": -1,
              "category": "tJU",
              "completed": 67759229411,
              "completion_on": 1693609350,
              "content_path": "/mnt/sdb/qb/downloads/Steel.Division.2.Men.of.Steel-RUNE",
              "dl_limit": -1,
              "dlspeed": 0,
              "download_path": "",
              "downloaded": 67767365851,
              "downloaded_session": 0,
              "eta": 8640000,
              "f_l_piece_prio": false,
              "force_start": false,
              "hash": "116bc6f3efa6f3b21a06ce8f1cc71875",
              "infohash_v1": "116bc6f306c40e072bde8f1cc71875",
              "infohash_v2": "",
              "last_activity": 1693609350,
              "magnet_uri": "magnet:?xt=",
              "max_ratio": -1,
              "max_seeding_time": -1,
              "name": "Steel.Division.2.Men.of.Steel-RUNE",
              "num_complete": 1,
              "num_incomplete": 0,
              "num_leechs": 0,
              "num_seeds": 0,
              "priority": 0,
              "progress": 1,
              "ratio": 0,
              "ratio_limit": -2,
              "save_path": "/mnt/sdb/qb/downloads",
              "seeding_time": 615035,
              "seeding_time_limit": -2,
              "seen_complete": 1693609350,
              "seq_dl": false,
              "size": 67759229411,
              "state": "stalledUP",
              "super_seeding": false,
              "tags": "",
              "time_active": 865354,
              "total_size": 67759229411,
              "tracker": "https://tracker",
              "trackers_count": 2,
              "up_limit": -1,
              "uploaded": 0,
              "uploaded_session": 0,
              "upspeed": 0
            }
            """
            # ID
            torrent_id = torrent.get("hash")
            # 标题
            torrent_title = torrent.get("name")
            # 下载时间
            if (not torrent.get("added_on")
                    or torrent.get("added_on") < 0):
                dltime = 0
            else:
                dltime = date_now - torrent.get("added_on")
            # 做种时间
            if (not torrent.get("completion_on")
                    or torrent.get("completion_on") < 0):
                seeding_time = 0
            else:
                seeding_time = date_now - torrent.get("completion_on")
            # 分享率
            ratio = torrent.get("ratio") or 0
            # 上传量
            uploaded = torrent.get("uploaded") or 0
            # 平均上传速度 Byte/s
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 已未活动 秒
            if (not torrent.get("last_activity")
                    or torrent.get("last_activity") < 0):
                iatime = 0
            else:
                iatime = date_now - torrent.get("last_activity")
            # 下载量
            downloaded = torrent.get("downloaded")
            # 种子大小
            total_size = torrent.get("total_size")
            # 添加时间
            add_on = (torrent.get("added_on") or 0)
            add_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(add_on))
            # 种子标签
            tags = torrent.get("tags")
            # tracker
            tracker = torrent.get("tracker")
        # TR
        else:
            # ID
            torrent_id = torrent.hashString
            # 标题
            torrent_title = torrent.name
            # 做种时间
            if (not torrent.date_done
                    or torrent.date_done.timestamp() < 1):
                seeding_time = 0
            else:
                seeding_time = date_now - int(torrent.date_done.timestamp())
            # 下载耗时
            if (not torrent.date_added
                    or torrent.date_added.timestamp() < 1):
                dltime = 0
            else:
                dltime = date_now - int(torrent.date_added.timestamp())
            # 下载量
            downloaded = int(torrent.total_size * torrent.progress / 100)
            # 分享率
            ratio = torrent.ratio or 0
            # 上传量
            uploaded = int(downloaded * torrent.ratio)
            # 平均上传速度
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 未活动时间
            if (not torrent.date_active
                    or torrent.date_active.timestamp() < 1):
                iatime = 0
            else:
                iatime = date_now - int(torrent.date_active.timestamp())
            # 种子大小
            total_size = torrent.total_size
            # 添加时间
            add_on = (torrent.date_added.timestamp() if torrent.date_added else 0)
            add_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(add_on))
            # 种子标签
            tags = torrent.get("tags")
            # tracker
            tracker = torrent.get("tracker")

        return {
            "hash": torrent_id,
            "title": torrent_title,
            "seeding_time": seeding_time,
            "ratio": ratio,
            "uploaded": uploaded,
            "downloaded": downloaded,
            "avg_upspeed": avg_upspeed,
            "iatime": iatime,
            "dltime": dltime,
            "total_size": total_size,
            "add_time": add_time,
            "add_on": add_on,
            "tags": tags,
            "tracker": tracker
        }

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message)

    def __send_delete_message(self, site_name: str, torrent_title: str, torrent_desc: str, reason: str,
                              title: str = "【刷流任务种子删除】"):
        """
        发送删除种子的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return
        msg_text = ""
        if site_name:
            msg_text = f"站点：{site_name}"
        if torrent_title:
            msg_text = f"{msg_text}\n标题：{torrent_title}"
        if torrent_desc:
            msg_text = f"{msg_text}\n内容：{torrent_desc}"
        if reason:
            msg_text = f"{msg_text}\n原因：{reason}"

        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=msg_text)

    @staticmethod
    def __build_add_message_text(torrent):
        """
        构建消息文本，兼容TorrentInfo对象和torrent_task字典
        """

        # 定义一个辅助函数来统一获取数据的方式
        def get_data(_key, default=None):
            if isinstance(torrent, dict):
                return torrent.get(_key, default)
            else:
                return getattr(torrent, _key, default)

        # 构造消息文本，确保使用中文标签
        msg_parts = []
        label_mapping = {
            "site_name": "站点",
            "title": "标题",
            "description": "内容",
            "size": "大小",
            "pubdate": "发布时间",
            "seeders": "做种数",
            "volume_factor": "促销",
            "hit_and_run": "Hit&Run"
        }
        for key in label_mapping:
            value = get_data(key)
            if key == "size" and value and str(value).replace(".", "", 1).isdigit():
                value = StringUtils.str_filesize(value)
            if value:
                msg_parts.append(f"{label_mapping[key]}：{'是' if key == 'hit_and_run' and value else value}")

        return "\n".join(msg_parts)

    def __send_add_message(self, torrent, title: str = "【刷流任务种子下载】"):
        """
        发送添加下载的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return

        # 使用辅助方法构建消息文本
        msg_text = self.__build_add_message_text(torrent)
        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=msg_text)

    def __get_torrents_size(self) -> int:
        """
        获取任务中的种子总大小
        """
        # 读取种子记录
        task_info = self.get_data("torrents") or {}
        if not task_info:
            return 0
        total_size = sum([task.get("size") or 0 for task in task_info.values()])
        return total_size

    def __get_downloader_info(self) -> schemas.DownloaderInfo:
        """
        获取下载器实时信息（所有下载器）
        """
        ret_info = schemas.DownloaderInfo()

        # Qbittorrent
        if self.qb:
            info = self.qb.transfer_info()
            if info:
                ret_info.download_speed += info.get("dl_info_speed")
                ret_info.upload_speed += info.get("up_info_speed")
                ret_info.download_size += info.get("dl_info_data")
                ret_info.upload_size += info.get("up_info_data")

        # Transmission
        if self.tr:
            info = self.tr.transfer_info()
            if info:
                ret_info.download_speed += info.download_speed
                ret_info.upload_speed += info.upload_speed
                ret_info.download_size += info.current_stats.downloaded_bytes
                ret_info.upload_size += info.current_stats.uploaded_bytes

        return ret_info

    def __get_downloading_count(self) -> int:
        """
        获取正在下载的任务数量
        """
        brush_config = self.__get_brush_config()
        downlader = self.__get_downloader(brush_config.downloader)
        if not downlader:
            return 0
        torrents = downlader.get_downloading_torrents()
        return len(torrents) or 0

    @staticmethod
    def __get_pubminutes(pubdate: str) -> float:
        """
        将字符串转换为时间，并计算与当前时间差）（分钟）
        """
        try:
            if not pubdate:
                return 0
            pubdate = pubdate.replace("T", " ").replace("Z", "")
            pubdate = datetime.strptime(pubdate, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            return (now - pubdate).total_seconds() // 60
        except Exception as e:
            print(str(e))
            return 0

    @staticmethod
    def __adjust_site_pubminutes(pub_minutes: float, torrent: TorrentInfo) -> float:
        """
        处理部分站点的时区逻辑
        """
        try:
            if not torrent:
                return pub_minutes

            if torrent.site_name == "我堡":
                # 获取当前时区的UTC偏移量（以秒为单位）
                utc_offset_seconds = time.timezone

                # 将UTC偏移量转换为分钟
                utc_offset_minutes = utc_offset_seconds / 60

                # 增加UTC偏移量到pub_minutes
                adjusted_pub_minutes = pub_minutes + utc_offset_minutes

                return adjusted_pub_minutes

            return pub_minutes
        except Exception as e:
            logger.error(str(e))
            return 0

    def __filter_torrents_by_tag(self, torrents: List[Any], exclude_tag: str) -> List[Any]:
        """
        根据标签过滤torrents
        """
        filter_torrents = []
        for torrent in torrents:
            # 使用 __get_label 方法获取每个 torrent 的标签列表
            labels = self.__get_label(torrent)
            # 如果排除的标签不在这个列表中，则添加到过滤后的列表
            if exclude_tag not in labels:
                filter_torrents.append(torrent)
        return filter_torrents

    def __get_subscribe_titles(self) -> Set[str]:
        """
        获取当前订阅的所有标题，返回一个不包含None的集合
        """
        self.subscribeoper = SubscribeOper()
        subscribes = self.subscribeoper.list()

        # 使用 filter() 函数筛选出有 'name' 属性且该属性值不为 None 的 Subscribe 对象
        # 然后使用 map() 函数获取每个对象的 'name' 属性值
        # 最后，使用 set() 函数将结果转换为集合，自动去除重复项和 None
        subscribe_titles = set(filter(None, map(lambda sub: getattr(sub, 'name', None), subscribes)))

        # 返回不包含 None 的名称集合
        return subscribe_titles

    def __filter_torrents_contains_subscribe(self, torrents: Any):
        subscribe_titles = self.__get_subscribe_titles()
        logger.info(f"当前订阅的名称集合为：{subscribe_titles}")

        # 初始化两个列表，一个用于收集未被排除的种子，一个用于记录被排除的种子
        included_torrents = []
        excluded_torrents = []

        # 单次遍历处理
        for torrent in torrents:
            # 确保title和description至少是空字符串
            title = torrent.title or ''
            description = torrent.description or ''

            if any(subscribe_title in title or subscribe_title in description for subscribe_title in subscribe_titles):
                # 如果种子的标题或描述包含订阅标题中的任一项，则记录为被排除
                excluded_torrents.append(torrent)
                logger.info(f"命中订阅内容，排除种子：{title}|{description}")
            else:
                # 否则，收集为未被排除的种子
                included_torrents.append(torrent)

        if not excluded_torrents:
            logger.info(f"没有命中订阅内容，不需要排除种子")

        # 返回未被排除的种子列表
        return included_torrents

    @staticmethod
    def __bytes_to_gb(size_in_bytes: float) -> float:
        """
        将字节单位的大小转换为千兆字节（GB）。

        :param size_in_bytes: 文件大小，单位为字节。
        :return: 文件大小，单位为千兆字节（GB）。
        """
        return size_in_bytes / (1024 ** 3)

    @staticmethod
    def __is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5'或'5-10'）
        """
        return bool(re.match(r"^\d+(-\d+)?$", value))

    @staticmethod
    def __is_number(value):
        """
        检查给定的值是否可以被转换为数字（整数或浮点数）
        """
        try:
            float(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def __calculate_seeding_torrents_size(torrent_tasks: Dict[str, dict]) -> float:
        """
        计算保种种子体积
        """
        return sum(task.get("size", 0) for task in torrent_tasks.values() if not task.get("deleted", False))

    def __archive_tasks(self):
        """
        归档已经删除的种子数据
        """
        torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}

        # 用于存储已删除的数据
        archived_tasks: Dict[str, dict] = self.get_data("archived") or {}

        # 准备一个列表，记录所有需要从原始数据中删除的键
        keys_to_delete = []

        # 遍历所有 torrent 条目
        for key, value in torrent_tasks.items():
            # 检查是否标记为已删除
            if value.get("deleted"):
                # 如果是，加入到归档字典中
                archived_tasks[key] = value
                # 记录键，稍后删除
                keys_to_delete.append(key)

        # 从原始字典中移除已删除的条目
        for key in keys_to_delete:
            del torrent_tasks[key]

        self.save_data("archived", archived_tasks)
        self.save_data("torrents", torrent_tasks)
        # 归档需要更新一下统计数据
        self.__update_and_save_statistic_info(torrent_tasks=torrent_tasks)

    def __clear_tasks(self):
        """
        清除统计数据（清理已删除和已归档的数据，保留活跃种子数据）
        """
        torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}

        to_delete = [key for key, value in torrent_tasks.items() if value.get("deleted")]
        for key in to_delete:
            del torrent_tasks[key]

        self.save_data("torrents", torrent_tasks)
        self.save_data("archived", {})
        self.save_data("unmanaged", {})
        # 需要更新一下统计数据
        self.__update_and_save_statistic_info(torrent_tasks=torrent_tasks)

    def __get_statistic_info(self) -> Dict[str, int]:
        """
        获取统计数据
        """
        statistic_info = self.get_data("statistic") or {
            "count": 0,
            "deleted": 0,
            "uploaded": 0,
            "downloaded": 0,
            "unarchived": 0,
            "active": 0,
            "active_uploaded": 0,
            "active_downloaded": 0
        }
        return statistic_info

    @staticmethod
    def __get_demo_site_config() -> str:
        desc = ("以下为配置示例，请参考 "
                "https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/README.md "
                "进行配置，请注意，只需要保留实际配置内容（删除这段）\n")
        config = """[{
    "sitename": "测试站点",
    "freeleech": "free",
    "hr": "no",
    "include": "",
    "exclude": "",
    "size": "10-500",
    "seeder": "1",
    "pubtime": "5-120",
    "seed_time": 120,
    "seed_ratio": "",
    "seed_size": "",
    "download_time": "",
    "seed_avgspeed": "",
    "seed_inactivetime": "",
    "save_path": "/downloads/site1",
    "proxy_download": false
}]"""
        return desc + config

    @staticmethod
    def __is_valid_time_range(time_range: str) -> bool:
        """检查时间范围字符串是否有效：格式为"HH:MM-HH:MM"，且时间有效"""
        if not time_range:
            return False

        # 使用正则表达式匹配格式
        pattern = re.compile(r'^\d{2}:\d{2}-\d{2}:\d{2}$')
        if not pattern.match(time_range):
            return False

        try:
            start_str, end_str = time_range.split('-')
            datetime.strptime(start_str, '%H:%M').time()
            datetime.strptime(end_str, '%H:%M').time()
        except Exception as e:
            print(str(e))
            return False

        return True

    def __is_current_time_in_range(self) -> bool:
        """判断当前时间是否在开启时间区间内"""

        brush_config = self.__get_brush_config()
        active_time_range = brush_config.active_time_range

        if not self.__is_valid_time_range(active_time_range):
            # 如果时间范围格式不正确或不存在，说明当前没有开启时间段，返回True
            return True

        start_str, end_str = active_time_range.split('-')
        start_time = datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.strptime(end_str, '%H:%M').time()
        now = datetime.now().time()

        if start_time <= end_time:
            # 情况1: 时间段不跨越午夜
            return start_time <= now <= end_time
        else:
            # 情况2: 时间段跨越午夜
            return now >= start_time or now <= end_time

    def __get_site_by_torrent(self, torrent: Any) -> Tuple[int, str]:
        """
        根据tracker获取站点信息
        """
        trackers = []
        try:
            tracker_url = torrent.get("tracker")
            if tracker_url:
                trackers.append(tracker_url)

            magnet_link = torrent.get("magnet_uri")
            if magnet_link:
                query_params = parse_qs(urlparse(magnet_link).query)
                encoded_tracker_urls = query_params.get('tr', [])
                # 解码tracker URLs然后扩展到trackers列表中
                decoded_tracker_urls = [unquote(url) for url in encoded_tracker_urls]
                trackers.extend(decoded_tracker_urls)
        except Exception as e:
            logger.error(e)

        domain = "未知"
        if not trackers:
            return 0, domain

        # 特定tracker到域名的映射
        tracker_mappings = {
            "chdbits.xyz": "ptchdbits.co",
            "agsvpt.trackers.work": "agsvpt.com",
            "tracker.cinefiles.info": "audiences.me",
        }

        for tracker in trackers:
            if not tracker:
                continue
            # 检查tracker是否包含特定的关键字，并进行相应的映射
            for key, mapped_domain in tracker_mappings.items():
                if key in tracker:
                    domain = mapped_domain
                    break
            else:
                # 使用StringUtils工具类获取tracker的域名
                domain = StringUtils.get_url_domain(tracker)

            site_info = self.siteshelper.get_indexer(domain)
            if site_info:
                return site_info.get("id"), site_info.get("name")

        # 当找不到对应的站点信息时，返回一个默认值
        return 0, domain
