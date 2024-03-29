import os
import re
import urllib
from datetime import datetime, timedelta
from threading import Event as ThreadEvent, RLock
from typing import Any, List, Dict, Tuple, Optional, Set
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from qbittorrentapi import TorrentDictionary
from transmission_rpc import Torrent

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.sites import SitesHelper
from app.log import logger
from app.modules.qbittorrent.qbittorrent import Qbittorrent
from app.modules.transmission.transmission import Transmission
from app.plugins import _PluginBase
from app.plugins.downloaderhelper.module import Constants, TaskContext, TaskResult
from app.schemas.types import EventType
from app.utils.string import StringUtils


class DownloaderHelper(_PluginBase):
    # 插件名称
    plugin_name = "下载器助手"
    # 插件描述
    plugin_desc = "自动做种、站点标签、自动删种。"
    # 插件图标
    plugin_icon = "DownloaderHelper.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "hotlcc"
    # 作者主页
    author_url = "https://github.com/hotlcc"
    # 插件配置项ID前缀
    plugin_config_prefix = "com.hotlcc.downloaderhelper."
    # 加载顺序
    plugin_order = 66
    # 可使用的用户级别
    auth_level = 2

    # 插件说明链接
    __help_url = 'https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins/downloaderhelper'

    # 私有属性
    # 调度器
    __scheduler: Optional[BackgroundScheduler] = None
    # 退出事件
    __exit_event: ThreadEvent = ThreadEvent()
    # 任务锁
    __task_lock: RLock = RLock()

    # 依赖组件
    # 站点帮助组件
    __sites_helper: SitesHelper = SitesHelper()

    # 配置相关
    # 插件缺省配置
    __config_default: Dict[str, Any] = {
        'site_name_priority': True,
        'tag_prefix': '站点/'
    }
    # 插件用户配置
    __config: Dict[str, Any] = {}
    # 缺省traker映射
    __tracker_mappings_default: Dict[str, str] = {
        'chdbits.xyz': 'ptchdbits.co',
        'agsvpt.trackers.work': 'agsvpt.com',
        'tracker.cinefiles.info': 'audiences.me'
    }
    # 用户配置的tracker映射
    __tracker_mappings: Dict[str, str] = {}
    # 排除种子标签
    __exclude_tags: Set[str] = set()
    # 多级根域名，用于在打标时做特殊处理
    __multi_level_root_domain: List[str] = ['edu.cn', 'com.cn', 'net.cn', 'org.cn']

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 加载插件配置
        self.__config = config
        # 解析tracker映射
        tracker_mappings = self.__get_config_item(config_key='tracker_mappings')
        self.__tracker_mappings = self.__parse_tracker_mappings(tracker_mappings=tracker_mappings)
        # 解析排除种子标签
        exclude_tags = self.__get_config_item(config_key='exclude_tags')
        self.__exclude_tags = self.__split_tags(tags=exclude_tags)
        logger.info(f"插件配置加载完成：{config}")

        # 停止现有服务
        self.stop_service()

        # 如果需要立即运行一次
        if self.__get_config_item(config_key='run_once'):
            if self.__check_enable_any_task():
                self.__start_scheduler()
                self.__scheduler.add_job(func=self.__run,
                                         trigger='date',
                                         run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                         name='下载器助手任务-立即运行一次')
                logger.info(f"立即运行一次成功")
            else:
                logger.warn(f"任务配置无效，立即运行一次未执行")
            # 关闭一次性开关
            self.__config['run_once'] = False
            self.update_config(self.__config)

    def get_state(self) -> bool:
        """
        获取插件状态
        """
        state = True if self.__get_config_item(config_key='enable') and (
                self.__get_config_item(config_key='cron') or self.__check_enable_listen()
        ) and self.__check_enable_any_task() \
            else False
        return state

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        try:
            cron = self.__get_config_item(config_key='cron')
            if self.get_state() and cron:
                return [{
                    "id": "DownloaderHelperTimerService",
                    "name": "下载器助手定时服务",
                    "trigger": CronTrigger.from_crontab(cron),
                    "func": self.__run,
                    "kwargs": {}
                }]
            else:
                return []
        except Exception as e:
            logger.error(f"注册插件公共服务异常: {str(e)}", exc_info=True)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 建议的配置
        config_suggest = {
            'listen_download_event': True,
            'listen_source_file_event': True,
            'cron': '0/30 * * * *',
            'exclude_tags': 'BT,刷流'
        }
        # 合并默认配置
        config_suggest.update(self.__config_default)

        return [{
            'component': 'VForm',
            'content': [{
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '插件总开关'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable',
                            'label': '启用插件'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '执行插件任务后是否发送通知'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable_notify',
                            'label': '发送通知'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '保存插件配置后是否立即触发一次插件任务运行'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'run_once',
                            'label': '立即运行一次'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '监听下载添加事件。当MoviePilot添加下载任务时，会触发执行本插件进行自动做种和添加站点标签。'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'listen_download_event',
                            'label': '监听下载事件'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '监听源文件删除事件。当在【历史记录】中删除源文件时，会自动触发运行本插件任务进行自动删种。'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'listen_source_file_event',
                            'label': '监听源文件事件'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '给种子添加站点标签时，是否优先以站点名称作为标签内容（否则将使用域名关键字）？'
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'site_name_priority',
                            'label': '站点名称优先'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '设置插件任务执行周期。支持5位cron表达式，应避免任务执行过于频繁，例如：0/30 * * * *。缺省时不执行定时任务，但不影响监听任务的执行。'
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'cron',
                            'label': '定时执行周期',
                            'placeholder': '0/30 * * * *'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '下载器中的种子有这些标签时不进行任何操作，多个标签使用英文“,”分割'
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'exclude_tags',
                            'label': '排除种子标签'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12,
                        'title': '给种子添加站点标签时的标签前缀，默认值为“站点/”'
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'tag_prefix',
                            'label': '站点标签前缀',
                            'placeholder': '站点/'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'title': 'Tracker映射。用于在站点打标签时，指定tracker和站点域名不同的种子的域名对应关系；前面为tracker域名（完整域名或者主域名皆可），中间是英文冒号，后面是站点域名。'
                    },
                    'content': [{
                        'component': 'VTextarea',
                        'props': {
                            'model': 'tracker_mappings',
                            'label': 'Tracker映射',
                            'placeholder': '格式：\n'
                                           '<tracker-domain>:<site-domain>\n'
                                           '例如：\n'
                                           'chdbits.xyz:ptchdbits.co'
                        }
                    }]
                }]
            }, {
                'component': 'VTabs',
                'props': {
                    'model': '_tabs',
                    'height': 72,
                    'style': {
                        'margin-top': '20px',
                        'margin-bottom': '20px'
                    }
                },
                'content': [{
                    'component': 'VTab',
                    'props': {
                        'value': 'qbittorrent'
                    },
                    'text': 'qbittorrent'
                }, {
                    'component': 'VTab',
                    'props': {
                        'value': 'transmission'
                    },
                    'text': 'transmission'
                }]
            }, {
                'component': 'VWindow',
                'props': {
                    'model': '_tabs'
                },
                'content': [{
                    'component': 'VWindowItem',
                    'props': {
                        'value': 'qbittorrent'
                    },
                    'content': [{
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'qb_enable',
                                    'label': '任务开关'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'qb_enable_seeding',
                                    'label': '自动做种'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'qb_enable_tagging',
                                    'label': '站点标签'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'qb_enable_delete',
                                    'label': '自动删种'
                                }
                            }]
                        }]
                    }]
                }, {
                    'component': 'VWindowItem',
                    'props': {
                        'value': 'transmission'
                    },
                    'content': [{
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'tr_enable',
                                    'label': '任务开关'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'tr_enable_seeding',
                                    'label': '自动做种'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'tr_enable_tagging',
                                    'label': '站点标签'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'tr_enable_delete',
                                    'label': '自动删种'
                                }
                            }]
                        }]
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'style': {
                            'margin-top': '20px'
                        }
                    },
                    'content': [{
                        'component': 'VAlert',
                        'props': {
                            'type': 'info',
                            'variant': 'tonal',
                            'text': f'插件使用说明见: {self.__help_url}'
                        }
                    }]
                }]
            }]
        }], config_suggest

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            logger.info('尝试停止插件服务...')
            self.__exit_event.set()
            self.__stop_scheduler()
            logger.info('插件服务停止成功')
        except Exception as e:
            logger.error(f"插件服务停止异常: {str(e)}", exc_info=True)
        finally:
            self.__exit_event.clear()

    def __parse_tracker_mappings(self, tracker_mappings: str) -> Dict[str, str]:
        """
        解析配置的tracker映射
        :param tracker_mappings: 配置的tracker映射
        :return: tracker映射，词典
        """
        mappings = {}
        if not tracker_mappings:
            return mappings
        lines = tracker_mappings.split('\n')
        for line in lines:
            if not line:
                continue
            line = line.strip()
            arr = line.split(':')
            if len(arr) < 2:
                continue
            key, value = arr[0], arr[1]
            if not key or not value:
                continue
            key, value = key.strip(), value.strip()
            if not key or not value:
                continue
            if self.__is_valid_domain(key) and self.__is_valid_domain(value):
                mappings[key] = value
        return mappings

    @staticmethod
    def __split_tags(tags: str = None) -> Set[str]:
        """
        分割tags字符串为set
        :param tags: tags字符串
        """
        return set(re.split(r"\s*,\s*", tags.strip())) if tags else set()

    def __exists_exclude_tag(self, tags=None) -> bool:
        """
        判断多个标签中是否存在被排除的标签
        :param tags: 字符串或者集合
        """
        if not tags:
            return False
        tags_type = type(tags)
        if tags_type == str:
            return self.__exists_exclude_tag(self.__split_tags(tags))
        elif tags_type == set or tags_type == list:
            if not self.__exclude_tags:
                return False
            for tag in tags:
                if tag in self.__exclude_tags:
                    return True
            return False
        else:
            return False

    def __start_scheduler(self, timezone=None):
        """
        启动调度器
        :param timezone: 时区
        """
        try:
            if not self.__scheduler:
                if not timezone:
                    timezone = settings.TZ
                self.__scheduler = BackgroundScheduler(timezone=timezone)
                logger.debug(f"插件服务调度器初始化完成: timezone = {str(timezone)}")
            if not self.__scheduler.running:
                self.__scheduler.start()
                logger.debug(f"插件服务调度器启动成功")
                self.__scheduler.print_jobs()
        except Exception as e:
            logger.error(f"插件服务调度器启动异常: {str(e)}", exc_info=True)

    def __stop_scheduler(self):
        """
        停止调度器
        """
        try:
            logger.info('尝试停止插件服务调度器...')
            if self.__scheduler:
                self.__scheduler.remove_all_jobs()
                if self.__scheduler.running:
                    self.__scheduler.shutdown()
                self.__scheduler = None
                logger.info('插件服务调度器停止成功')
            else:
                logger.info('插件未启用服务调度器，无须停止')
        except Exception as e:
            logger.error(f"插件服务调度器停止异常: {str(e)}", exc_info=True)

    def __get_config_item(self, config_key: str, use_default: bool = True) -> Any:
        """
        获取插件配置项
        :param config_key: 配置键
        :param use_default: 是否使用缺省值
        :return: 配置值
        """
        if not config_key:
            return None
        config = self.__config if self.__config else {}
        config_value = config.get(config_key)
        if config_value is None and use_default:
            config_default = self.__config_default if self.__config_default else {}
            config_value = config_default.get(config_key)
        return config_value

    def __match_site_domain_by_tracker_domain(self, tracker_domain: str, use_default: bool = True) -> Optional[str]:
        """
        通过tracker映射配置根据tracker域名匹配站点域名
        :param tracker_domain: tracker域名
        :param use_default: 是否使用缺省值
        :return: 站点域名
        """
        if not tracker_domain:
            return None
        tracker_mappings = self.__tracker_mappings if self.__tracker_mappings else {}
        site_domain = tracker_mappings.get(tracker_domain)
        if site_domain:
            return site_domain
        for key, value in tracker_mappings.items():
            if tracker_domain.endswith('.' + key):
                return value
        if not use_default:
            return None
        tracker_mappings_default = self.__tracker_mappings_default if self.__tracker_mappings_default else {}
        site_domain = tracker_mappings_default.get(tracker_domain)
        if site_domain:
            return site_domain
        for key, value in tracker_mappings_default.items():
            if tracker_domain.endswith('.' + key):
                return value
        return None

    def __get_site_info_by_domain(self, site_domain: str) -> Optional[str]:
        """
        根据站点域名从索引中获取站点信息
        :param site_domain: 站点域名
        :return: 站点信息
        """
        if not site_domain or not self.__sites_helper:
            return None
        return self.__sites_helper.get_indexer(site_domain)

    def __check_enable_listen(self) -> bool:
        """
        判断是否启用了事件监听
        :return: 是否启用了事件监听
        """
        return True if self.__get_config_item(config_key='listen_download_event') \
                       or self.__get_config_item(config_key='listen_source_file_event') else False

    def __check_enable_qb_sub_task(self) -> bool:
        """
        判断是否启用了qb子任务
        :return: 是否启用了qb子任务
        """
        return True if self.__get_config_item(config_key='qb_enable_seeding') \
                       or self.__get_config_item(config_key='qb_enable_tagging') \
                       or self.__get_config_item(config_key='qb_enable_delete') else False

    def __check_enable_qb_task(self) -> bool:
        """
        判断是否启用了qb任务
        :return: 是否启用了qb任务
        """
        return True if self.__get_config_item(config_key='qb_enable') \
                       and self.__check_enable_qb_sub_task() else False

    def __check_enable_tr_sub_task(self) -> bool:
        """
        判断是否启用了tr子任务
        :return: 是否启用了tr子任务
        """
        return True if self.__get_config_item(config_key='tr_enable_seeding') \
                       or self.__get_config_item(config_key='tr_enable_tagging') \
                       or self.__get_config_item(config_key='tr_enable_delete') else False

    def __check_enable_tr_task(self) -> bool:
        """
        判断是否启用了tr任务
        :return: 是否启用了tr任务
        """
        return True if self.__get_config_item(config_key='tr_enable') \
                       and self.__check_enable_tr_sub_task() else False

    def __check_enable_any_task(self) -> bool:
        """
        判断是否启用了任意任务
        :return: 是否启用了任意任务
        """
        return True if self.__check_enable_qb_task() \
                       or self.__check_enable_tr_task() else False

    @classmethod
    def __parse_tracker_for_qbittorrent(cls, torrent: TorrentDictionary) -> Optional[str]:
        """
        qb解析 tracker
        :return: tracker url
        """
        if not torrent:
            return None
        tracker = torrent.get('tracker')
        if tracker and len(tracker) > 0:
            return tracker
        magnet_uri = torrent.get('magnet_uri')
        if not magnet_uri or len(magnet_uri) <= 0:
            return None
        magnet_uri_obj = urlparse(magnet_uri)
        query = cls.__parse_url_query(magnet_uri_obj.query)
        tr = query['tr']
        if not tr or len(tr) <= 0:
            return None
        return tr[0]

    @classmethod
    def __parse_tracker_for_transmission(cls, torrent: Torrent) -> Optional[str]:
        """
        tr解析 tracker
        :return: tracker url
        """
        if not torrent:
            return None
        trackers = torrent.trackers
        if not trackers or len(trackers) <= 0:
            return None
        tracker = trackers[0]
        if not tracker:
            return None
        return tracker.get('announce')

    @staticmethod
    def __parse_url_query(query) -> dict:
        """
        解析url的query
        :param query 字典
        """
        if not query or len(query) <= 0:
            return {}
        return urllib.parse.parse_qs(query)

    @staticmethod
    def __get_url_domain(url: str) -> Optional[str]:
        """
        获取url的域名
        """
        if not url:
            return None
        scheme, netloc = StringUtils.get_url_netloc(url)
        return netloc

    def __get_main_domain(self, domain: str) -> Optional[str]:
        """
        获取域名的主域名
        :param domain: 原域名
        :return: 主域名
        """
        if not domain:
            return None
        domain_arr = domain.split('.')
        domain_len = len(domain_arr)
        if domain_len < 2:
            return None
        root_domain, root_domain_len = self.__match_multi_level_root_domain(domain=domain)
        if root_domain:
            return f'{domain_arr[-root_domain_len - 1]}.{root_domain}'
        else:
            return f'{domain_arr[-2]}.{domain_arr[-1]}'

    def __get_domain_keyword(self, domain: str) -> Optional[str]:
        """
        获取域名关键字
        """
        main_domain = self.__get_main_domain(domain=domain)
        if not main_domain:
            return None
        return main_domain.split('.')[0]

    def __match_multi_level_root_domain(self, domain: str) -> Tuple[Optional[str], int]:
        """
        匹配多级根域名
        :param domain: 被匹配的域名
        :return: 匹配的根域名, 匹配的根域名长度
        """
        if not domain or not self.__multi_level_root_domain:
            return None, 0
        for root_domain in self.__multi_level_root_domain:
            if domain.endswith('.' + root_domain):
                root_domain_len = len(root_domain.split('.'))
                return root_domain, root_domain_len
        return None, 0

    def __is_valid_domain(self, domain: str) -> bool:
        """
        判断域名是否有效
        :param domain: 被判断的域名
        :return: 是否有效
        """
        if not domain:
            return False
        domain_len = len(domain.split('.'))
        root_domain, root_domain_len = self.__match_multi_level_root_domain(domain)
        if root_domain:
            return domain_len > root_domain_len
        return domain_len > 1

    def __generate_site_tag(self, site: str) -> Optional[str]:
        """
        生成站点标签
        """
        if not site:
            return None
        tag_prefix = self.__get_config_item('tag_prefix')
        if not tag_prefix:
            return site
        return f'{tag_prefix}{site}'

    def __consult_site_tag_by_tracker(self, tracker_url: str) -> Tuple[Optional[str], Optional[Set[str]]]:
        """
        根据tracker地址咨询站点标签
        :return: ('本次需要添加的站点标签', '建议移除的可能存在的历史标签集合')
        """
        if not tracker_url:
            return None, None

        # tracker的完整域名
        tracker_domain = self.__get_url_domain(url=tracker_url)
        if not tracker_domain:
            return None, None

        # 建议移除的可能存在的历史标签集合
        delete_suggest = set()

        # tracker域名关键字
        tracker_domain_keyword = self.__get_domain_keyword(domain=tracker_domain)
        if tracker_domain_keyword:
            # 建议移除
            delete_suggest.add(tracker_domain_keyword)
            delete_suggest.add(self.__generate_site_tag(site=tracker_domain_keyword))

        # 首先根据tracker的完整域名去匹配站点信息
        site_info = self.__get_site_info_by_domain(site_domain=tracker_domain)

        # 如果没有匹配到，再根据主域名去匹配
        if not site_info:
            tracker_main_domain = self.__get_main_domain(domain=tracker_domain)
            if tracker_main_domain and tracker_main_domain != tracker_domain:
                site_info = self.__get_site_info_by_domain(tracker_main_domain)

        # 如果还是没有匹配到，就根据tracker映射的域名匹配
        matched_site_domain = None
        if not site_info:
            matched_site_domain = self.__match_site_domain_by_tracker_domain(tracker_domain)
            if matched_site_domain:
                site_info = self.__get_site_info_by_domain(matched_site_domain)

                matched_site_domain_keyword = self.__get_domain_keyword(matched_site_domain)
                if matched_site_domain_keyword:
                    # 建议移除
                    delete_suggest.add(matched_site_domain_keyword)
                    delete_suggest.add(self.__generate_site_tag(matched_site_domain_keyword))

        # 如果匹配到了站点信息
        if site_info:
            site_name = site_info.get('name')
            site_tag_by_name = self.__generate_site_tag(site_name)
            site_domain_keyword = self.__get_domain_keyword(self.__get_url_domain(site_info.get('domain')))
            site_tag_by_domain_keyword = self.__generate_site_tag(site_domain_keyword)
            # 站点名称优先
            site_name_priority = self.__get_config_item('site_name_priority')
            site_tag = site_tag_by_name if site_name_priority else site_tag_by_domain_keyword
            # 建议移除
            delete_suggest.add(site_name)
            delete_suggest.add(site_tag_by_name)
            delete_suggest.add(site_domain_keyword)
            delete_suggest.add(site_tag_by_domain_keyword)
        else:
            if matched_site_domain:
                site_tag = self.__generate_site_tag(self.__get_domain_keyword(matched_site_domain))
            else:
                site_tag = self.__generate_site_tag(self.__get_domain_keyword(tracker_domain))

        if site_tag and site_tag in delete_suggest:
            delete_suggest.remove(site_tag)

        return site_tag, delete_suggest

    @classmethod
    def __check_need_delete_for_qbittorrent(cls, torrent: TorrentDictionary, deleted_event_data: dict = None) -> bool:
        """
        检查qb种子是否满足删除条件
        :param deleted_event_data: 任务执行伴随的源文件删除事件数据
        """
        if not torrent:
            return False

        # 根据种子状态判断是否应该删种：状态为丢失文件时需要删除
        if torrent.get('state') == 'missingFiles':
            return True

        # 根据伴随的源文件删除事件判断是否应该删种：如果当前种子和事件匹配并且种子中已经不存在数据文件时就需要删除
        match, torrent_data_path = cls.__check_torrent_match_file_for_qbittorrent(torrent=torrent,
                                                                                  source_file_info=deleted_event_data)
        if not match:
            return False
        # 如果匹配的种子数据路径不存在，说明数据文件已经（全部）被删除了，那么就允许删种
        return not os.path.exists(torrent_data_path)

    @classmethod
    def __check_need_delete_for_transmission(cls, torrent: Torrent, deleted_event_data: dict = None) -> bool:
        """
        检查tr种子是否满足删除条件
        :param deleted_event_data: 任务执行伴随的源文件删除事件数据
        """
        if not torrent:
            return False

        # 根据种子状态判断是否应该删种：状态为丢失文件时需要删除
        if torrent.error == 3 and torrent.error_string and 'No data found' in torrent.error_string:
            return True

        # 根据伴随的源文件删除事件判断是否应该删种：如果当前种子和事件匹配并且种子中已经不存在数据文件时就需要删除
        match, torrent_data_path = cls.__check_torrent_match_file_for_transmission(torrent=torrent,
                                                                                   source_file_info=deleted_event_data)
        if not match:
            return False
        # 如果匹配的种子数据路径不存在，说明数据文件已经（全部）被删除了，那么就允许删种
        return not os.path.exists(torrent_data_path)

    @classmethod
    def __check_torrent_match_file_for_qbittorrent(cls, torrent: TorrentDictionary,
                                                   source_file_info: dict) -> Tuple[bool, Optional[str]]:
        """
        检查种子和源文件是否匹配
        :param torrent: 种子
        :param source_file_info: 源文件信息：src=源文件路径，hash=源文件对应的种子hash
        :return: 是否匹配, 匹配的种子数据文件路径
        """
        if not torrent or not source_file_info:
            return False, None
        return cls.__check_torrent_match_file(torrent_hash=torrent.get('hash'),
                                              torrent_data_file_name=torrent.get('name'),
                                              source_hash=None,
                                              source_file_path=source_file_info.get('src'))

    @classmethod
    def __check_torrent_match_file_for_transmission(cls, torrent: Torrent,
                                                    source_file_info: dict) -> Tuple[bool, Optional[str]]:
        """
        检查种子和源文件是否匹配
        :param torrent: 种子
        :param source_file_info: 源文件信息：src=源文件路径，hash=源文件对应的种子hash
        :return: 是否匹配, 匹配的种子数据文件路径
        """
        if not torrent or not source_file_info:
            return False, None
        return cls.__check_torrent_match_file(torrent_hash=torrent.hashString,
                                              torrent_data_file_name=torrent.get('name'),
                                              source_hash=None,
                                              source_file_path=source_file_info.get('src'))

    @classmethod
    def __check_torrent_match_file(cls, torrent_hash: str,
                                   torrent_data_file_name: str,
                                   source_hash: Optional[str],
                                   source_file_path: str) -> Tuple[bool, Optional[str]]:
        """
        检查种子和源文件是否匹配
        :param torrent_hash: 种子hash
        :param torrent_data_file_name: 种子数据文件名
        :param source_hash: 源文件对应的种子hash
        :param source_file_path: 源文件路径
        :return: 是否匹配, 匹配的种子数据文件（在MoviePilot中的）路径
        """
        if not torrent_hash or not torrent_data_file_name or not source_file_path:
            return False, None
        # 当前传入源hash时，先根据hash判断是否匹配
        if source_hash and torrent_hash != hash:
            return False, None

        # 从源文件路径中分离文件夹路径和文件名称
        source_file_dir, source_file_name = os.path.split(source_file_path)
        # 情况一：如果源文件名称和种子数据文件（夹）名称一致，则认为匹配，适用于单文件种子和原盘资源的情况
        if source_file_name == torrent_data_file_name:
            return True, source_file_path
        # 情况二：如果原文件父目录名称和种子数据文件（夹）名称一致，则认为匹配，适用于多文件剧集种子的情况
        _, source_file_dir_name = os.path.split(source_file_dir)
        if source_file_dir_name == torrent_data_file_name:
            return True, source_file_dir
        # 情况三：如果种子数据文件（夹）名称是源文件路径的一部分，则认为匹配
        torrent_data_file_name_wrap = os.path.sep + torrent_data_file_name + os.path.sep
        index = source_file_path.find(torrent_data_file_name_wrap)
        if index >= 0:
            return True, source_file_path[0:index] + os.path.sep + torrent_data_file_name

        return False, None

    def __send_notify(self, context: TaskContext):
        """
        发送通知
        :param context: 任务执行上下文
        """
        if not context or not self.__get_config_item('enable_notify'):
            return
        text = self.__build_notify_message(context=context)
        if not text:
            return
        self.post_message(title=f'{self.plugin_name}任务执行结果', text=text, userid=context.get_username())

    @staticmethod
    def __build_notify_message(context: TaskContext):
        """
        构建通知消息内容
        """
        text = ''
        if not context:
            return text
        results = context.get_results()
        if not results or len(results) <= 0:
            return text
        for result in results:
            if not result:
                continue
            seeding = result.get_seeding()
            tagging = result.get_tagging()
            delete = result.get_delete()
            if result.is_success() and not seeding and not tagging and not delete:
                continue
            text += f'【任务：{result.get_name()}】\n'
            if result.is_success():
                text += f'总种数：{result.get_total()}\n'
                if seeding:
                    text += f'做种数：{seeding}\n'
                if tagging:
                    text += f'打标数：{tagging}\n'
                if delete:
                    text += f'删种数：{delete}\n'
            else:
                text += '执行失败\n'
            text += '\n————————————\n'
        return text

    def __run(self):
        """
        运行插件任务
        """
        if not self.__task_lock.acquire(blocking=False):
            logger.info('已有进行中的任务，本次不执行')
            return
        try:
            context = TaskContext()
            self.__run_for_all(context=context)
        finally:
            self.__task_lock.release()

    def __run_for_all(self, context: TaskContext = None) -> TaskContext:
        """
        针对所有下载器运行插件任务
        :param context: 任务上下文
        :return: 任务上下文
        """
        if not context:
            context = TaskContext()

        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，任务终止')
            return context

        self.__run_for_qbittorrent(context=context)

        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，任务终止')
            return context

        self.__run_for_transmission(context=context)

        # 发送通知
        self.__send_notify(context=context)

        return context

    def __run_for_qbittorrent(self, context: TaskContext = None) -> TaskContext:
        """
        针对qb下载器运行插件任务
        :param context: 任务上下文
        :return: 任务上下文
        """
        if not context:
            context = TaskContext()
        downloader_name = 'qBittorrent'

        # 处理前置条件
        if not self.__check_enable_qb_task():
            return context
        if not context.is_selected_qb_downloader():
            return context
        enable_seeding = True if self.__get_config_item(
            config_key='qb_enable_seeding') and context.is_enabled_seeding() else False
        enable_tagging = True if self.__get_config_item(
            config_key='qb_enable_tagging') and context.is_enabled_tagging() else False
        enable_delete = True if self.__get_config_item(
            config_key='qb_enable_delete') and context.is_enabled_delete() else False
        if not enable_seeding and not enable_tagging and not enable_delete:
            return context
        # 任务结果
        result = TaskResult(downloader_name)
        try:
            qbittorrent = Qbittorrent()
            if not qbittorrent.qbc:
                return context

            logger.info(f'下载器[{downloader_name}]任务执行开始...')

            if self.__exit_event.is_set():
                logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                return context

            context.save_result(result=result)

            torrents, error = qbittorrent.get_torrents()
            if error:
                logger.warn(f'从下载器[{downloader_name}]中获取种子失败，任务终止')
                return context
            if not torrents or len(torrents) <= 0:
                logger.warn(f'下载器[{downloader_name}]中没有种子，任务终止')
                return context
            result.set_total(len(torrents))

            # 根据上下文过滤种子
            selected_torrents = context.get_selected_torrents()
            torrents = torrents if selected_torrents is None \
                else [torrent for torrent in torrents if torrent and torrent.hash in selected_torrents]
            if not torrents or len(torrents) <= 0:
                logger.warn(f'下载器[{downloader_name}]中没有目标种子，任务终止')
                return context

            logger.info(
                f'子任务执行状态: 自动做种={enable_seeding}, 自动打标={enable_tagging}, 自动删种={enable_delete}')

            # 做种
            if enable_seeding:
                result.set_seeding(self.__seeding_batch_for_qbittorrent(torrents=torrents))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context
            # 打标
            if enable_tagging:
                result.set_tagging(self.__tagging_batch_for_qbittorrent(torrents=torrents))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context
            # 删种
            if enable_delete:
                result.set_delete(self.__delete_batch_for_qbittorrent(qbittorrent=qbittorrent, torrents=torrents,
                                                                      deleted_event_data=context.get_deleted_event_data()))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context

            logger.info(f'下载器[{downloader_name}]任务执行成功')
        except Exception as e:
            result.set_success(False)
            logger.error(f'下载器[{downloader_name}]任务执行失败: {str(e)}', exc_info=True)
        return context

    def __seeding_batch_for_qbittorrent(self, torrents: List[TorrentDictionary]) -> int:
        """
        qb批量做种
        :return: 做种数
        """
        logger.info('[QB]批量做种开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if self.__seeding_single_for_qbittorrent(torrent=torrent):
                count += 1
        logger.info('[QB]批量做种结束')
        return count

    def __seeding_single_for_qbittorrent(self, torrent: TorrentDictionary) -> bool:
        """
        qb单个做种
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = self.__split_tags(torrent.get('tags'))
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        need_seeding = torrent.state_enum.is_complete and torrent.state_enum.is_paused
        if not need_seeding:
            return False
        torrent.resume()
        logger.info(f"[QB]单个做种完成: hash = {torrent.get('hash')}, name = {torrent.get('name')}")
        return True

    def __tagging_batch_for_qbittorrent(self, torrents: List[TorrentDictionary]) -> int:
        """
        qb批量打标
        :return: 打标数
        """
        logger.info('[QB]批量打标开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if self.__tagging_single_for_qbittorrent(torrent=torrent):
                count += 1
        logger.info('[QB]批量打标结束')
        return count

    def __tagging_single_for_qbittorrent(self, torrent: TorrentDictionary) -> bool:
        """
        qb单个打标签
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = self.__split_tags(torrent.get('tags'))
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        # 种子的tracker地址
        tracker_url = self.__parse_tracker_for_qbittorrent(torrent=torrent)
        if not tracker_url:
            return False
        # 获取标签建议
        site_tag, delete_suggest = self.__consult_site_tag_by_tracker(tracker_url=tracker_url)
        # 移除建议删除的标签
        if delete_suggest and len(delete_suggest) > 0:
            to_deletes = [to_delete for to_delete in delete_suggest if to_delete in torrent_tags]
            if to_deletes and len(to_deletes) > 0:
                torrent.remove_tags(to_deletes)
        # 如果本次不需要打标签
        if not site_tag or site_tag in torrent_tags:
            return False
        # 打标签
        torrent.add_tags(site_tag)
        logger.info(f"[QB]单个打标成功: hash = {torrent.get('hash')}, name = {torrent.get('name')}")
        return True

    def __delete_batch_for_qbittorrent(self, qbittorrent: Qbittorrent, torrents: List[TorrentDictionary],
                                       deleted_event_data: dict = None) -> int:
        """
        qb批量删种
        :return: 删种数
        """
        logger.info('[QB]批量删种开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if (self.__delete_single_for_qbittorrent(qbittorrent=qbittorrent, torrent=torrent,
                                                     deleted_event_data=deleted_event_data)):
                count += 1
        logger.info('[QB]批量删种结束')
        return count

    def __delete_single_for_qbittorrent(self, qbittorrent: Qbittorrent, torrent: TorrentDictionary,
                                        deleted_event_data: dict = None) -> bool:
        """
        qb单个删种
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = self.__split_tags(torrent.get('tags'))
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        if not self.__check_need_delete_for_qbittorrent(torrent=torrent, deleted_event_data=deleted_event_data):
            return False
        qbittorrent.delete_torrents(True, torrent.get('hash'))
        logger.info(f"[QB]单个删种完成: hash = {torrent.get('hash')}, name = {torrent.get('name')}")
        return True

    def __run_for_transmission(self, context: TaskContext = None) -> TaskContext:
        """
        针对tr下载器运行插件任务
        :param context: 任务上下文
        :return: 运行结果
        """
        if not context:
            context = TaskContext()
        downloader_name = 'Transmission'

        # 处理前置条件
        if not self.__check_enable_tr_task():
            return context
        if not context.is_selected_tr_downloader():
            return context
        enable_seeding = True if self.__get_config_item(
            config_key='tr_enable_seeding') and context.is_enabled_seeding() else False
        enable_tagging = True if self.__get_config_item(
            config_key='tr_enable_tagging') and context.is_enabled_tagging() else False
        enable_delete = True if self.__get_config_item(
            config_key='tr_enable_delete') and context.is_enabled_delete() else False
        if not enable_seeding and not enable_tagging and not enable_delete:
            return context

        # 任务结果
        result = TaskResult(downloader_name)

        try:
            transmission = Transmission()
            if not transmission.trc:
                return context

            logger.info(f'下载器[{downloader_name}]任务执行开始...')

            if self.__exit_event.is_set():
                logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                return context

            context.save_result(result=result)

            torrents, error = transmission.get_torrents()
            if error:
                logger.warn(f'从下载器[{downloader_name}]中获取种子失败，任务终止')
                return context
            if not torrents or len(torrents) <= 0:
                logger.warn(f'下载器[{downloader_name}]中没有种子，任务终止')
                return context
            result.set_total(len(torrents))

            # 根据上下文过滤种子
            selected_torrents = context.get_selected_torrents()
            torrents = torrents if selected_torrents is None \
                else [torrent for torrent in torrents if torrent in selected_torrents]
            if not torrents or len(torrents) <= 0:
                logger.warn(f'下载器[{downloader_name}]中没有目标种子，任务终止')
                return context

            logger.info(
                f'子任务执行状态: 自动做种={enable_seeding}, 自动打标={enable_tagging}, 自动删种={enable_delete}')

            # 做种
            if enable_seeding:
                result.set_seeding(self.__seeding_batch_for_transmission(transmission=transmission, torrents=torrents))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context
            # 打标
            if enable_tagging:
                result.set_tagging(self.__tagging_batch_for_transmission(transmission=transmission, torrents=torrents))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context
            # 删种
            if enable_delete:
                result.set_delete(self.__delete_batch_for_transmission(transmission=transmission, torrents=torrents,
                                                                       deleted_event_data=context.get_deleted_event_data()))
                if self.__exit_event.is_set():
                    logger.warn(f'插件服务正在退出，任务终止[{downloader_name}]')
                    return context

            logger.info(f'下载器[{downloader_name}]任务执行成功')
        except Exception as e:
            result.set_success(False)
            logger.error(f'下载器[{downloader_name}]任务执行失败: {str(e)}', exc_info=True)
        return context

    def __seeding_batch_for_transmission(self, transmission: Transmission, torrents: List[Torrent]) -> int:
        """
        tr批量做种
        :return: 做种数
        """
        logger.info('[TR]批量做种开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if self.__seeding_single_for_transmission(transmission=transmission, torrent=torrent):
                count += 1
        logger.info('[TR]批量做种结束')
        return count

    def __seeding_single_for_transmission(self, transmission: Transmission, torrent: Torrent) -> bool:
        """
        tr单个做种
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = torrent.get('labels')
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        need_seeding = torrent.progress == 100 and torrent.stopped and torrent.error == 0
        if not need_seeding:
            return False
        transmission.start_torrents(torrent.hashString)
        logger.info(f"[TR]单个做种完成: hash = {torrent.hashString}, name = {torrent.get('name')}")
        return True

    def __tagging_batch_for_transmission(self, transmission: Transmission, torrents: List[Torrent]) -> int:
        """
        tr批量打标
        :return: 打标数
        """
        logger.info('[TR]批量打标开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if self.__tagging_single_for_transmission(transmission=transmission, torrent=torrent):
                count += 1
        logger.info('[TR]批量打标结束')
        return count

    def __tagging_single_for_transmission(self, transmission: Transmission, torrent: Torrent) -> bool:
        """
        tr单个打标签
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = torrent.get('labels')
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        # 种子的tracker地址
        tracker_url = self.__parse_tracker_for_transmission(torrent=torrent)
        if not tracker_url:
            return False
        # 获取标签建议
        site_tag, delete_suggest = self.__consult_site_tag_by_tracker(tracker_url=tracker_url)
        # 种子标签副本
        torrent_tags_copy = torrent_tags.copy()
        # 移除建议删除的标签
        if delete_suggest and len(delete_suggest) > 0:
            for to_delete in delete_suggest:
                if to_delete and to_delete in torrent_tags_copy:
                    torrent_tags_copy.remove(to_delete)
        # 如果本次需要打标签
        if site_tag and site_tag not in torrent_tags_copy:
            torrent_tags_copy.append(site_tag)
        # 如果没有变化就不继续保存
        if torrent_tags_copy == torrent_tags:
            return False
        # 保存标签
        transmission.set_torrent_tag(torrent.hashString, torrent_tags_copy)
        logger.info(f"[TR]单个打标成功: hash = {torrent.hashString}, name = {torrent.get('name')}")
        return True

    def __delete_batch_for_transmission(self, transmission: Transmission, torrents: List[Torrent],
                                        deleted_event_data: dict = None) -> int:
        """
        tr批量删种
        :return: 删种数
        """
        logger.info('[TR]批量删种开始...')
        count = 0
        if not torrents:
            return count
        for torrent in torrents:
            if self.__exit_event.is_set():
                logger.warn('插件服务正在退出，子任务终止')
                return count
            if (self.__delete_single_for_transmission(transmission=transmission, torrent=torrent,
                                                      deleted_event_data=deleted_event_data)):
                count += 1
        logger.info('[TR]批量删种结束')
        return count

    def __delete_single_for_transmission(self, transmission: Transmission, torrent: Torrent,
                                         deleted_event_data: dict = None) -> bool:
        """
        tr单个删种
        :return: 是否执行
        """
        if not torrent:
            return False
        # 种子当前已经存在的标签
        torrent_tags = torrent.get('labels')
        # 判断种子中是否存在排除的标签
        if self.__exists_exclude_tag(torrent_tags):
            return False
        if not self.__check_need_delete_for_transmission(torrent=torrent, deleted_event_data=deleted_event_data):
            return False
        transmission.delete_torrents(True, torrent.hashString)
        logger.info(f"'[TR]单个删种完成: hash = {torrent.hashString}, name = {torrent.get('name')}")
        return True

    @eventmanager.register(EventType.DownloadAdded)
    def listen_download_added_event(self, event: Event = None):
        """
        监听下载添加事件
        """
        logger.info('监听到下载添加事件')
        if not event or not event.event_data:
            logger.warn('事件信息无效，忽略事件')
            return
        if not self.get_state() or not self.__get_config_item(config_key='listen_download_event'):
            logger.warn('插件状态无效或未开启监听，忽略事件')
            return
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，忽略事件')
            return
        # 执行
        logger.info('下载添加事件监听任务执行开始...')
        context = TaskContext().enable_seeding(False).enable_tagging(True).enable_delete(False)
        hash_str = event.event_data.get('hash')
        if hash:
            context.select_torrent(hash_str)
        username = event.event_data.get('username')
        if username:
            context.select_username(username)
        self.__run_for_all(context=context)
        logger.info('下载添加事件监听任务执行结束')

    @eventmanager.register(EventType.DownloadFileDeleted)
    def listen_download_file_deleted_event(self, event: Event = None):
        """
        监听源文件删除事件
        """
        logger.info('监听到源文件删除事件')
        if not event or not event.event_data:
            logger.warn('事件信息无效，忽略事件')
            return
        if not self.get_state() or not self.__get_config_item(config_key='listen_source_file_event'):
            logger.warn('插件状态无效或未开启监听，忽略事件')
            return
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，忽略事件')
            return
        # 执行
        logger.info('源文件删除事件监听任务执行开始...')
        context = TaskContext().enable_seeding(False).enable_tagging(False).enable_delete(True).set_deleted_event_data(
            event.event_data)
        self.__run_for_all(context=context)
        logger.info('源文件删除事件监听任务执行结束')
