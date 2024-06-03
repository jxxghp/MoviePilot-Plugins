import os
import re
import urllib
from datetime import datetime, timedelta
from threading import Event as ThreadEvent, RLock
from typing import Any, List, Dict, Tuple, Optional, Set, Union
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from cachetools import TTLCache
from qbittorrentapi import TorrentDictionary, TorrentState
from transmission_rpc.torrent import Torrent, Status as TorrentStatus
from ruamel.yaml.comments import CommentedMap

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.module import ModuleManager
from app.helper.sites import SitesHelper
from app.log import logger
from app.modules.qbittorrent.qbittorrent import Qbittorrent
from app.modules.transmission.transmission import Transmission
from app.plugins import _PluginBase
from app.plugins.downloaderhelper.module import TaskContext, TaskResult, Downloader, TorrentField, TorrentFieldMap, DownloaderMap, DownloaderTransferInfo
from app.schemas import NotificationType
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
    plugin_version = "2.7"
    # 插件作者
    plugin_author = "hotlcc"
    # 作者主页
    author_url = "https://github.com/hotlcc"
    # 插件配置项ID前缀
    plugin_config_prefix = "com.hotlcc.downloaderhelper."
    # 加载顺序
    plugin_order = 66
    # 可使用的用户级别
    auth_level = 1

    # 插件说明链接
    __help_url = 'https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins/downloaderhelper'

    # 私有属性
    # 调度器
    __scheduler: Optional[BackgroundScheduler] = None
    # 退出事件
    __exit_event: ThreadEvent = ThreadEvent()
    # 任务锁
    __task_lock: RLock = RLock()
    # 缓存
    __ttl_cache = TTLCache(maxsize=128, ttl=1800)

    # 配置相关
    # 插件缺省配置
    __config_default: Dict[str, Any] = {
        'site_name_priority': True,
        'tag_prefix': '站点/',
        'dashboard_widget_size': 12,
        'dashboard_widget_target_downloaders': ['default'],
        'dashboard_widget_display_fields': [
            TorrentField.NAME.name,
            TorrentField.SELECT_SIZE.name,
            TorrentField.COMPLETED.name,
            TorrentField.STATE.name,
            TorrentField.DOWNLOAD_SPEED.name,
            TorrentField.UPLOAD_SPEED.name,
            TorrentField.REMAINING_TIME.name,
            TorrentField.RATIO.name,
            TorrentField.TAGS.name,
            TorrentField.ADD_TIME.name,
            TorrentField.UPLOADED.name,
        ],
        'dashboard_speed_widget_target_downloaders': ['default'],
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
    # vuetifyjs mdi 图标 svg path 值
    __mdi_icon_svg_path = {
        'mdi-cloud-upload': 'M11 20H6.5q-2.28 0-3.89-1.57Q1 16.85 1 14.58q0-1.95 1.17-3.48q1.18-1.53 3.08-1.95q.63-2.3 2.5-3.72Q9.63 4 12 4q2.93 0 4.96 2.04Q19 8.07 19 11q1.73.2 2.86 1.5q1.14 1.28 1.14 3q0 1.88-1.31 3.19T18.5 20H13v-7.15l1.6 1.55L16 13l-4-4l-4 4l1.4 1.4l1.6-1.55Z',
        'mdi-download-box': 'M5 3h14a2 2 0 0 1 2 2v14c0 1.11-.89 2-2 2H5a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2m3 14h8v-2H8zm8-7h-2.5V7h-3v3H8l4 4z',
        'mdi-content-save': 'M15 9H5V5h10m-3 14a3 3 0 0 1-3-3a3 3 0 0 1 3-3a3 3 0 0 1 3 3a3 3 0 0 1-3 3m5-16H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7z',
    }

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 停止现有服务
        self.stop_service()

        # 检查环境
        self.__check_environment()

        # 修正配置
        config = self.__fix_config(config=config)
        # 加载插件配置
        self.__config = config
        # 解析tracker映射
        tracker_mappings = self.__get_config_item(config_key='tracker_mappings')
        self.__tracker_mappings = self.__parse_tracker_mappings(tracker_mappings=tracker_mappings)
        # 解析排除种子标签
        exclude_tags = self.__get_config_item(config_key='exclude_tags')
        self.__exclude_tags = self.__split_tags(tags=exclude_tags)
        logger.info(f"插件配置加载完成：{config}")

        # 如果需要立即运行一次
        if self.__get_config_item(config_key='run_once'):
            if self.__check_enable_any_task():
                self.__start_scheduler()
                self.__scheduler.add_job(func=self.__try_run,
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
                (
                        (
                                self.__get_config_item(config_key='cron')
                                or self.__check_enable_listen()
                        )
                        and self.__check_enable_any_task()
                )
                or self.__check_enable_dashboard_active_torrent_widget()
                or self.__check_enable_dashboard_speed_widget()
        ) else False
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
                    "func": self.__try_run,
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
            'exclude_tags': 'BT,刷流',
            'dashboard_widget_refresh': 5,
        }
        # 合并默认配置
        config_suggest.update(self.__config_default)
        # 下载器tabs
        downloader_tabs = [{
            'component': 'VTab',
            'props': {
                'value': d.id
            },
            'text': d.name_
        } for d in Downloader if d]
        # 下载器tab items
        downloader_tab_items = [{
            'component': 'VWindowItem',
            'props': {
                'value': d.id
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
                            'model': f'{d.short_id}_enable',
                            'label': '任务开关',
                            'hint': '该下载器子任务的开关'
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
                            'model': f'{d.short_id}_enable_seeding',
                            'label': '自动做种',
                            'hint': '是否开启自动做种功能'
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
                            'model': f'{d.short_id}_enable_tagging',
                            'label': '站点标签',
                            'hint': '是否开启站点标签功能'
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
                            'model': f'{d.short_id}_enable_delete',
                            'label': '自动删种',
                            'hint': '是否开启自动删种功能'
                        }
                    }]
                }]
            }]
        } for d in Downloader if d]
        # 下载器字段选项
        downloader_field_options = [{
            'title': field.name_,
            'value': field.name
        } for field in TorrentField if field]
        # 返回form
        return [{
            'component': 'VForm',
            'content': [{  # 业务无关总控
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable',
                            'label': '启用插件',
                            'hint': '插件总开关'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable_notify',
                            'label': '发送通知',
                            'hint': '执行插件任务后是否发送通知'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'run_once',
                            'label': '立即运行一次',
                            'hint': '保存插件配置后是否立即触发一次插件任务运行'
                        }
                    }]
                }]
            }, {  # 业务相关总控
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'listen_download_event',
                            'label': '监听下载事件',
                            'hint': '监听下载添加事件。当MoviePilot添加下载任务时，会触发执行本插件进行自动做种和添加站点标签。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'listen_source_file_event',
                            'label': '监听源文件事件',
                            'hint': '监听源文件删除事件。当在【历史记录】中删除源文件时，会自动触发运行本插件任务进行自动删种。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'site_name_priority',
                            'label': '站点名称优先',
                            'hint': '给种子添加站点标签时，是否优先以站点名称作为标签内容（否则将使用域名关键字）？MoviePilot需要认证，否则将不生效。'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'cron',
                            'label': '定时执行周期',
                            'placeholder': '0/30 * * * *',
                            'hint': '设置插件任务执行周期。支持5位cron表达式，应避免任务执行过于频繁，例如：0/30 * * * *。缺省时不执行定时任务，但不影响监听任务的执行。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'exclude_tags',
                            'label': '排除种子标签',
                            'hint': '下载器中的种子有这些标签时不进行任何操作，多个标签使用英文“,”分割'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'tag_prefix',
                            'label': '站点标签前缀',
                            'placeholder': '站点/',
                            'hint': '给种子添加站点标签时的标签前缀，默认值为“站点/”'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': '_config_tracker_mappings_dialog_closed',
                            'label': '配置Tracker映射',
                            'hint': '点击展开Tracker映射配置窗口。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': '_config_dashboard_active_torrent_dialog_closed',
                            'label': '配置仪表板活动种子组件',
                            'hint': '点击展开仪表板活动种子组件配置窗口。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': '_config_dashboard_speed_dialog_closed',
                            'label': '配置仪表板实时速率组件',
                            'hint': '点击展开仪表板实时速率组件配置窗口。'
                        }
                    }]
                }]
            }, {
                'component': 'VDialog',
                'props': {
                    'model': '_config_tracker_mappings_dialog_closed',
                    'max-width': '40rem'
                },
                'content': [{
                    'component': 'VCard',
                    'props': {
                        'title': '配置Tracker映射',
                        'style': {
                            'padding': '0 20px 20px 20px'
                        }
                    },
                    'content': [{
                        'component': 'VDialogCloseBtn',
                        'props': {
                            'model': '_config_tracker_mappings_dialog_closed'
                        }
                    }, {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12
                            },
                            'content': [{
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'tracker_mappings',
                                    'label': 'Tracker映射',
                                    'placeholder': '格式：\n'
                                                   '<tracker-domain>:<site-domain>\n\n'
                                                   '例如：\n'
                                                   'chdbits.xyz:ptchdbits.co',
                                    'hint': 'Tracker映射。用于在站点打标签时，指定tracker和站点域名不同的种子的域名对应关系；前面为tracker域名（完整域名或者主域名皆可），中间是英文冒号，后面是站点域名。'
                                }
                            }]
                        }]
                    }]
                }]
            }, {
                'component': 'VDialog',
                'props': {
                    'model': '_config_dashboard_active_torrent_dialog_closed',
                    'max-width': '40rem'
                },
                'content': [{
                    'component': 'VCard',
                    'props': {
                        'title': '配置仪表板活动种子组件',
                        'style': {
                            'padding': '0 20px 20px 20px'
                        }
                    },
                    'content': [{
                        'component': 'VDialogCloseBtn',
                        'props': {
                            'model': '_config_dashboard_active_torrent_dialog_closed'
                        }
                    }, {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'enable_dashboard_widget',
                                    'label': '启用组件',
                                    'hint': '是否启用仪表板活动种子组件。'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'dashboard_widget_size',
                                    'label': '组件尺寸',
                                    'items': [
                                        {'title': '100%', 'value': 12},
                                        {'title': '2/3', 'value': 8},
                                        {'title': '50%', 'value': 6},
                                        {'title': '1/3', 'value': 4}
                                    ],
                                    'hint': '选择仪表板组件尺寸。'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': 'dashboard_widget_refresh',
                                    'label': '刷新间隔(秒)',
                                    'placeholder': '5',
                                    'type': 'number',
                                    'hint': '组件刷新时间间隔，单位为秒，缺省时不刷新。请合理配置，间隔太短可能会导致下载器假死。'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'dashboard_widget_target_downloaders',
                                    'label': '目标下载器',
                                    'multiple': True,
                                    'items': [
                                        {'title': '系统默认下载器', 'value': 'default'},
                                        {'title': Downloader.QB.name_, 'value': Downloader.QB.id},
                                        {'title': Downloader.TR.name_, 'value': Downloader.TR.id}
                                    ],
                                    'hint': '选择要展示的目标下载器。'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 12, 'xl': 12, 'lg': 12, 'md': 12, 'sm': 12, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'dashboard_widget_display_fields',
                                    'label': '展示的字段',
                                    'multiple': True,
                                    'chips': True,
                                    'items': downloader_field_options,
                                    'hint': '选择要展示的字段，展示顺序以选择的顺序为准。'
                                }
                            }]
                        }]
                    }]
                }]
            }, {
                'component': 'VDialog',
                'props': {
                    'model': '_config_dashboard_speed_dialog_closed',
                    'max-width': '40rem'
                },
                'content': [{
                    'component': 'VCard',
                    'props': {
                        'title': '配置仪表板实时速率组件',
                        'style': {
                            'padding': '0 20px 20px 20px'
                        }
                    },
                    'content': [{
                        'component': 'VDialogCloseBtn',
                        'props': {
                            'model': '_config_dashboard_speed_dialog_closed'
                        }
                    }, {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'enable_dashboard_speed_widget',
                                    'label': '启用组件',
                                    'hint': '是否启用仪表板实时速率组件。'
                                }
                            }]
                        }]
                    }, {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VTextField',
                                'props': {
                                    'model': 'dashboard_speed_widget_refresh',
                                    'label': '刷新间隔(秒)',
                                    'placeholder': '5',
                                    'type': 'number',
                                    'hint': '组件刷新时间间隔，单位为秒，缺省时不刷新。请合理配置，间隔太短可能会导致下载器假死。'
                                }
                            }]
                        }, {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                            },
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'dashboard_speed_widget_target_downloaders',
                                    'label': '目标下载器',
                                    'multiple': True,
                                    'items': [
                                        {'title': '系统默认下载器', 'value': 'default'},
                                        {'title': Downloader.QB.name_, 'value': Downloader.QB.id},
                                        {'title': Downloader.TR.name_, 'value': Downloader.TR.id}
                                    ],
                                    'hint': '选择要展示的目标下载器。'
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
                        'cols': 12
                    },
                    'content': [{
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'height': 72,
                            'style': {
                                'margin-top-': '20px',
                                'margin-bottom-': '20px'
                            }
                        },
                        'content': downloader_tabs
                    }, {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs'
                        },
                        'content': downloader_tab_items
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
                            'variant': 'tonal'
                        },
                        'content': [{
                            'component': 'a',
                            'props': {
                                'href': self.__help_url,
                                'target': '_blank'
                            },
                            'text': '点此查看详细的插件使用说明'
                        }]
                    }]
                }]
            }]
        }], config_suggest

    def get_page(self) -> List[dict]:
        pass

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """
        获取插件仪表盘元信息
        返回示例：
            [{
                "key": "dashboard1", // 仪表盘的key，在当前插件范围唯一
                "name": "仪表盘1" // 仪表盘的名称
            }, {
                "key": "dashboard2",
                "name": "仪表盘2"
            }]
        """
        dashboard_meta = []
        if not self.get_state():
            return dashboard_meta
        if self.__check_enable_dashboard_active_torrent_widget():
            target_downloader_ids = self.__get_dashboard_active_torrent_widget_target_downloader_ids()
            for target_downloader_id in target_downloader_ids:
                downloader = self.__get_downloader_enum_by_id(downloader_id=target_downloader_id)
                if not downloader:
                    continue
                dashboard_meta.append({
                    "key": downloader.id,
                    "name": f"活动种子 #{downloader.short_name}",
                })
        if self.__check_enable_dashboard_speed_widget():
            target_downloader_ids = self.__get_dashboard_speed_widget_target_downloader_ids()
            for target_downloader_id in target_downloader_ids:
                downloader = self.__get_downloader_enum_by_id(downloader_id=target_downloader_id)
                if not downloader:
                    continue
                dashboard_meta.append({
                    "key": f"{downloader.id}_speed",
                    "name": f"实时速率 #{downloader.short_name}",
                })
        return dashboard_meta

    def get_dashboard(self, key: str = None, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
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

        kwargs参数可获取的值：1、user_agent：浏览器UA

        :param key: 仪表盘key，根据指定的key返回相应的仪表盘数据，缺省时返回一个固定的仪表盘数据（兼容旧版）
        """
        if not self.get_state():
            return None
        enable_dashboard_active_torrent_widget = self.__check_enable_dashboard_active_torrent_widget()
        enable_dashboard_speed_widget = self.__check_enable_dashboard_speed_widget()
        if not enable_dashboard_active_torrent_widget and not enable_dashboard_speed_widget:
            return None
        # 无key兼容历史
        dashboard_active_torrent_widget_target_downloader_ids = self.__get_dashboard_active_torrent_widget_target_downloader_ids()
        if not key:
            if enable_dashboard_active_torrent_widget and dashboard_active_torrent_widget_target_downloader_ids:
                return self.__get_dashboard_active_torrent_widget(downloader_id=dashboard_active_torrent_widget_target_downloader_ids[0])
            else:
                return None
        # 有key
        dashboard_speed_widget_target_downloader_ids = self.__get_dashboard_speed_widget_target_downloader_ids()
        if key == Downloader.QB.id and enable_dashboard_active_torrent_widget and Downloader.QB.id in dashboard_active_torrent_widget_target_downloader_ids:
            return self.__get_dashboard_active_torrent_widget(downloader_id=Downloader.QB.id)
        if key == Downloader.TR.id and enable_dashboard_active_torrent_widget and Downloader.TR.id in dashboard_active_torrent_widget_target_downloader_ids:
            return self.__get_dashboard_active_torrent_widget(downloader_id=Downloader.TR.id)
        if key == f"{Downloader.QB.id}_speed" and enable_dashboard_speed_widget and Downloader.QB.id in dashboard_speed_widget_target_downloader_ids:
            return self.__get_dashboard_speed_widget(downloader_id=Downloader.QB.id)
        if key == f"{Downloader.TR.id}_speed" and enable_dashboard_speed_widget and Downloader.TR.id in dashboard_speed_widget_target_downloader_ids:
            return self.__get_dashboard_speed_widget(downloader_id=Downloader.TR.id)
        return None

    def __get_dashboard_active_torrent_widget(self,
                                              downloader_id: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取仪表板活动种子组件
        """
        downloader = self.__get_downloader_enum_by_id(downloader_id=downloader_id)
        if not downloader:
            return None
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None

        # 列配置
        dashboard_widget_size = self.__get_config_item('dashboard_widget_size')
        cols = {
            'cols': 12,
            'xxl': dashboard_widget_size,
            'xl': dashboard_widget_size,
            'lg': dashboard_widget_size,
            'md': dashboard_widget_size,
            'sm': 12,
            'xs': 12
        }

        # 全局配置
        attrs = {
            'title': f'活动种子 #{downloader.short_name}'
        }
        if self.__check_target_downloader(downloader_id=downloader_id):
            attrs['refresh'] = self.__get_config_item('dashboard_widget_refresh')

        # 页面元素
        elements = self.__get_dashboard_active_torrent_widget_elememts(downloader_id=downloader_id)

        return cols, attrs, elements

    def __get_dashboard_speed_widget(self,
                                     downloader_id: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取仪表板实时速率组件
        """
        downloader = self.__get_downloader_enum_by_id(downloader_id=downloader_id)
        if not downloader:
            return None
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None

        # 列配置
        cols = {
            'cols': 12,
            'xxl': 4,
            'xl': 4,
            'lg': 4,
            'md': 4,
            'sm': 12,
            'xs': 12
        }

        # 全局配置
        attrs = {
            'title': f'实时速率 #{downloader.short_name}'
        }
        if self.__check_target_downloader(downloader_id=downloader_id):
            attrs['refresh'] = self.__get_config_item('dashboard_speed_widget_refresh')

        # 页面元素
        elements = self.__get_dashboard_speed_widget_elememts(downloader_id=downloader_id)

        return cols, attrs, elements

    def stop_service(self):
        """
        退出插件
        """
        try:
            logger.info('尝试停止插件服务...')
            self.__exit_event.set()
            self.__stop_scheduler()
            self.__clear_cache()
            logger.info('插件服务停止完成')
        except Exception as e:
            logger.error(f"插件服务停止异常: {str(e)}", exc_info=True)
        finally:
            self.__exit_event.clear()

    @staticmethod
    def __check_mp_user_auth() -> bool:
        """
        检查mp用户认证
        :return: True表示已认证
        """
        return SitesHelper().auth_level >= 2

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

    def __clear_cache(self):
        """
        清除缓存
        """
        try:
            logger.info('尝试清除插件缓存...')
            if self.__ttl_cache:
                self.__ttl_cache.clear()
                logger.info('插件缓存清除成功')
            else:
                logger.info('插件未启用缓存，无须清除')
        except Exception as e:
            logger.error(f"插件缓存清除异常: {str(e)}", exc_info=True)

    def __fix_config(self, config: dict) -> dict:
        """
        修正配置
        """
        if not config:
            return None
        # 忽略主程序在reset时赋予的内容
        reset_config = {
            "enabled": False,
            "enable": False
        }
        if config == reset_config:
            return None

        config_keys = config.keys()
        if 'dashboard_widget_size' in config_keys:
            dashboard_widget_size = config.get('dashboard_widget_size')
            config['dashboard_widget_size'] = int(dashboard_widget_size) if dashboard_widget_size else None
        if 'dashboard_widget_refresh' in config_keys:
            dashboard_widget_refresh = config.get('dashboard_widget_refresh')
            config['dashboard_widget_refresh'] = int(dashboard_widget_refresh) if dashboard_widget_refresh else None
        if 'dashboard_widget_display_fields' in config_keys:
            dashboard_widget_display_fields = config.get('dashboard_widget_display_fields')
            config['dashboard_widget_display_fields'] = list(filter(lambda field: TorrentFieldMap.get(field),
                                                                    dashboard_widget_display_fields)) if dashboard_widget_display_fields else []
        self.update_config(config=config)
        return config

    def __check_environment(self):
        """"
        检查环境
        """
        if not self.__check_mp_user_auth():
            logger.warn("MoviePilot未认证，【站点名称优先】功能将不可用。")

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

    def __get_site_info_by_domain(self, site_domain: str) -> CommentedMap:
        """
        根据站点域名从索引中获取站点信息
        :param site_domain: 站点域名
        :return: 站点信息
        """
        if not site_domain:
            return None
        return SitesHelper().get_indexer(site_domain)

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

    def __check_enable_dashboard_active_torrent_widget(self) -> bool:
        """
        判断是否启用了仪表板活动种子组件
        :return: 是否启用了仪表板活动种子组件
        """
        return True if self.__get_config_item('enable_dashboard_widget') else False

    def __check_enable_dashboard_speed_widget(self) -> bool:
        """
        判断是否启用了仪表板实时速率组件
        :return: 是否启用了仪表板实时速率组件
        """
        return True if self.__get_config_item('enable_dashboard_speed_widget') else False

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
        self.post_message(title=f'{self.plugin_name}任务执行结果', text=text, mtype=NotificationType.Plugin)

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

    def __get_qbittorrent(self) -> Qbittorrent:
        """
        获取qb实例
        """
        module = ModuleManager().get_running_module(module_id='QbittorrentModule')
        if not module:
            return None
        qbittorrent = getattr(module, 'qbittorrent')
        if not qbittorrent or not getattr(qbittorrent, 'qbc'):
            return None
        return qbittorrent

    def __get_transmission(self) -> Transmission:
        """
        获取tr实例
        """
        module = ModuleManager().get_running_module(module_id='TransmissionModule')
        if not module:
            return None
        transmission = getattr(module, 'transmission')
        if not transmission or not getattr(transmission, 'trc'):
            return None
        return transmission

    def __try_run(self, context: TaskContext = None):
        """
        尝试运行插件任务
        """
        if not self.__task_lock.acquire(blocking=False):
            logger.info('已有进行中的任务，本次不执行')
            return
        try:
            self.__run_for_all(context=context)
        finally:
            self.__task_lock.release()

    def __block_run(self, context: TaskContext = None):
        """
        阻塞运行插件任务
        """
        self.__task_lock.acquire()
        try:
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

        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，任务终止')
            return context

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
            qbittorrent = self.__get_qbittorrent()
            if not qbittorrent:
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
            transmission = self.__get_transmission()
            if not transmission:
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
                else [torrent for torrent in torrents if torrent and torrent.hashString in selected_torrents]
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

    @staticmethod
    def __ensure_torrent_fields(fields: List[Union[str, TorrentField]]) -> List[TorrentField]:
        """
        确保种子字段类型
        """
        result = []
        if not fields:
            return result
        for field in fields:
            if not field:
                continue
            if isinstance(field, str):
                field = TorrentFieldMap.get(field)
            if not field:
                continue
            if isinstance(field, TorrentField):
                result.append(field)
        return result

    def __build_dashboard_widget_torrent_table_head_content(self,
                                                    fields: List[TorrentField] = None) -> list:
        """
        构造仪表板组件种子表头内容
        """
        if not fields:
            fields = self.__get_dashboard_active_torrent_widget_display_fields()
        if not fields:
            return []
        return [{
            'component': 'th',
            'props': {
                'class': 'text-start ps-4'
            },
            'text': field.name_
        } for field in fields if field]

    def __build_dashboard_widget_torrent_table_head(self,
                                            fields: List[TorrentField] = None) -> dict:
        """
        构造仪表板组件种子表头
        """
        return {
            'component': 'thead',
            'content': self.__build_dashboard_widget_torrent_table_head_content(fields=fields)
        }

    def __build_dashboard_widget_torrent_table_body_content(self,
                                                    data: List[List[Any]],
                                                    field_count: int,
                                                    downloader_id: str) -> list:
        """
        构造仪表板组件种子表体内容
        :param downloader_id: 下载器ID
        :param data: 表格数据
        :param field_count: 字段数量
        """
        if data:
            return [{
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [{
                    'component': 'td',
                    'props': {
                        'class': 'whitespace-nowrap'
                    },
                    'text': col
                } for col in row]
            } for row in data if row]
        else:
            empty_text = '暂无数据' if self.__check_target_downloader(downloader_id=downloader_id) else '目标下载器配置无效'
            return [{
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [{
                    'component': 'td',
                    'props': {
                        'colspan': field_count,
                        'class': 'text-center'
                    },
                    'text': empty_text
                }]
            }]

    def __build_dashboard_widget_torrent_table_body(self,
                                            data: List[List[Any]],
                                            field_count: int,
                                            downloader_id: str) -> dict:
        """
        构造仪表板组件种子表体
        """
        return {
            'component': 'tbody',
            'content': self.__build_dashboard_widget_torrent_table_body_content(data=data, field_count=field_count, downloader_id=downloader_id)
        }

    def __get_dashboard_widget_target_downloader_ids(self, config_key: str) -> List[str]:
        """
        获取仪表板组件目标下载器ids
        """
        target_downloader_ids = []
        if not config_key:
            return target_downloader_ids
        target_downloaders = self.__get_config_item(config_key)
        if not target_downloaders:
            return target_downloader_ids
        for target_downloader in target_downloaders:
            if target_downloader == 'default':
                target_downloader = settings.DEFAULT_DOWNLOADER
            if target_downloader and target_downloader not in target_downloader_ids:
                target_downloader_ids.append(target_downloader)
        return target_downloader_ids

    def __get_dashboard_active_torrent_widget_target_downloader_ids(self) -> List[str]:
        """
        获取仪表板活动种子组件目标下载器ids
        """
        return self.__get_dashboard_widget_target_downloader_ids(config_key='dashboard_widget_target_downloaders')

    def __get_dashboard_speed_widget_target_downloader_ids(self) -> List[str]:
        """
        获取仪表板实时速率组件目标下载器ids
        """
        return self.__get_dashboard_widget_target_downloader_ids(config_key='dashboard_speed_widget_target_downloaders')

    def __get_dashboard_active_torrent_widget_display_fields(self) -> List[TorrentField]:
        """
        获取仪表板活动种子组件展示字段
        """
        fields = self.__get_config_item('dashboard_widget_display_fields')
        return self.__ensure_torrent_fields(fields=fields)

    @staticmethod
    def __get_downloader_enum_by_id(downloader_id: str) -> Downloader:
        """
        根据下载器id获取枚举
        """
        if not downloader_id:
            return None
        return DownloaderMap.get(downloader_id)

    def __check_target_downloader(self, downloader_id: str) -> bool:
        """
        检查目标下载器是否有效
        """
        if not downloader_id:
            return False
        if downloader_id == Downloader.QB.id:
            return self.__get_qbittorrent() is not None
        elif downloader_id == Downloader.TR.id:
            return self.__get_transmission() is not None
        else:
            return False

    def __get_downloader_active_torrent_data(self,
                                             downloader_id: str,
                                             fields: List[TorrentField] = None):
        """
        获取下载器活动种子数据
        """
        if not downloader_id:
            return None
        # 字段
        if not fields:
            fields = self.__get_dashboard_active_torrent_widget_display_fields()
        if downloader_id == Downloader.QB.id:
            return self.__get_qbittorrent_active_torrent_data(fields=fields)
        elif downloader_id == Downloader.TR.id:
            return self.__get_transmission_active_torrent_data(fields=fields)
        else:
            return None

    def __get_qbittorrent_active_torrent_data(self,
                                              fields: List[TorrentField] = None):
        """
        获取qb活动种子数据
        """
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        qbittorrent = self.__get_qbittorrent()
        if not qbittorrent:
            return None
        # 字段
        if not fields:
            fields = self.__get_dashboard_active_torrent_widget_display_fields()
        # 活动种子
        torrents, error = qbittorrent.get_torrents(status=['active'])
        if error:
            return None
        torrent_hashs = set([torrent.get('hash') for torrent in torrents if torrent and torrent.get('hash')])
        # 未下载完的种子
        downloading_torrents, _ = qbittorrent.get_torrents(status=['downloading'])
        if downloading_torrents:
            for downloading_torrent in downloading_torrents:
                torrent_hash = downloading_torrent.get('hash')
                if not torrent_hash or torrent_hash in torrent_hashs:
                    continue
                torrents.append(downloading_torrent)
        # 按添加时间倒序排序
        torrents = sorted(torrents, key=lambda torrent: torrent.get(TorrentField.ADD_TIME.qb), reverse=True)
        return self.__convert_qbittorrent_torrents_data(torrents=torrents, fields=fields)

    def __convert_qbittorrent_torrents_data(self, torrents: List[TorrentDictionary],
                                            fields: List[TorrentField]) -> Optional[List[List[Any]]]:
        """
        转换qb种子数据
        """
        if not torrents or not fields:
            return None
        return [self.__convert_qbittorrent_torrent_data(torrent=torrent, fields=fields) for torrent in torrents if
                torrent]

    @staticmethod
    def __process_torrent_for_qbittorrent(torrent: TorrentDictionary,
                                          fields: List[TorrentField]):
        """
        加工qb种子
        """
        if not torrent:
            return

        def calculate_remaining_size(torrent: TorrentDictionary):
            """
            计算剩余大小
            """
            remaining_size = torrent.get(TorrentField.REMAINING.qb)
            if not remaining_size:
                remaining_size =  torrent.get(TorrentField.SELECT_SIZE.qb) - torrent.get(TorrentField.COMPLETED.qb)
                torrent[TorrentField.REMAINING.qb] = remaining_size
            return remaining_size

        try:
            # 剩余大小
            if TorrentField.REMAINING in fields:
                calculate_remaining_size(torrent=torrent)
            # 剩余时间
            if TorrentField.REMAINING_TIME in fields:
                if torrent.get(TorrentField.STATE.qb) == TorrentState.DOWNLOADING.value:
                    download_speed = torrent.get(TorrentField.DOWNLOAD_SPEED.qb)
                    if download_speed <= 0:
                        remaining_time = -1
                    else:
                        remaining_size = calculate_remaining_size(torrent=torrent)
                        remaining_time = remaining_size / download_speed
                else:
                    remaining_time = 0
                torrent[TorrentField.REMAINING_TIME.qb] = remaining_time
        except Exception as e:
            logger.error(f'加工qb种子: {str(e)}, torrent = {str(torrent)}', exc_info=True)
            return None

    def __convert_qbittorrent_torrent_data(self,
                                           torrent: TorrentDictionary,
                                           fields: List[TorrentField]) -> Optional[List[Any]]:
        """
        转换qb种子数据
        """
        if not torrent or not fields:
            return None
        # 加工qb种子
        self.__process_torrent_for_qbittorrent(torrent=torrent, fields=fields)
        data = []
        for field in fields:
            value = self.__extract_torrent_value_for_qbittorrent(torrent=torrent, field=field)
            data.append(value)
        return data

    @staticmethod
    def __extract_torrent_value_for_qbittorrent(torrent: TorrentDictionary,
                                                field: TorrentField) -> Any:
        """
        从qb种子中提取值
        """
        if not torrent or not field:
            return None
        try:
            if not field.qb:
                return None
            value = torrent.get(field.qb)
            if field.convertor:
                value = field.convertor.convert(value)
            return value
        except Exception as e:
            logger.error(f'从qb种子中提取值异常: {str(e)}, torrent = {str(torrent)}', exc_info=True)
            return None

    def __build_transmission_field_arguments(self, fields: List[TorrentField]) -> List[str]:
        """
        构造tr字段查询参数
        """
        if not fields:
            return []
        arguments = [field.tr for field in fields if field and field.tr and not field.tr.startswith('#')]
        arguments.append('id')
        arguments.append(TorrentField.NAME.tr)
        arguments.append('hashString')
        arguments.append(TorrentField.ADD_TIME.tr)
        # 处理依赖的字段
        if TorrentField.COMPLETED in fields:
            arguments.append('fileStats')
        if TorrentField.REMAINING in fields:
            arguments.append(TorrentField.SELECT_SIZE.tr)
            arguments.append('fileStats')
        if TorrentField.REMAINING_TIME in fields:
            arguments.append(TorrentField.STATE.tr)
            arguments.append(TorrentField.DOWNLOAD_SPEED.tr)
            arguments.append(TorrentField.SELECT_SIZE.tr)
            arguments.append('fileStats')
        if TorrentField.DOWNLOAD_LIMIT in fields:
            arguments.append('downloadLimited')
        if TorrentField.UPLOAD_LIMIT in fields:
            arguments.append('uploadLimited')
        return list(set(arguments))

    def __get_transmission_active_torrent_data(self,
                                               fields: List[TorrentField] = None):
        """
        获取tr活动种子数据
        """
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        transmission = self.__get_transmission()
        if not transmission:
            return None
        # 字段
        if not fields:
            fields = self.__get_dashboard_active_torrent_widget_display_fields()
        torrents, _ = transmission.trc.get_recently_active_torrents(arguments=self.__build_transmission_field_arguments(fields=fields))
        if not torrents:
            return None
        # 按添加时间倒序排序
        torrents = sorted(torrents, key=lambda torrent: torrent.fields.get(TorrentField.ADD_TIME.tr), reverse=True)
        return self.__convert_transmission_torrents_data(torrents=torrents, fields=fields)

    def __convert_transmission_torrents_data(self,
                                             torrents: List[Torrent],
                                             fields: List[TorrentField]) -> Optional[List[List[Any]]]:
        """
        转换tr种子数据
        """
        if not torrents or not fields:
            return None
        return [self.__convert_transmission_torrent_data(torrent=torrent, fields=fields) for torrent in torrents if
                torrent]

    @staticmethod
    def __process_torrent_for_transmission(torrent: Torrent,
                                           fields: List[TorrentField]):
        """
        加工tr种子
        """
        if not torrent or not fields:
            return

        def calculate_completed(torrent: Torrent):
            """
            计算已完成大小
            """
            completed = torrent.get(TorrentField.COMPLETED.tr)
            if not completed:
                completed = sum(x["bytesCompleted"] for x in torrent.fields["fileStats"])
                torrent.fields[TorrentField.COMPLETED.tr] = completed
            return completed

        def calculate_remaining_size(torrent: Torrent):
            """
            计算剩余大小
            """
            remaining_size = torrent.get(TorrentField.REMAINING.tr)
            if not remaining_size:
                select_size = torrent.get(TorrentField.SELECT_SIZE.tr)
                completed = calculate_completed(torrent=torrent)
                remaining_size = select_size - completed
                torrent.fields[TorrentField.REMAINING.tr] = remaining_size
            return remaining_size

        try:
            # 已完成大小
            if TorrentField.COMPLETED in fields:
                calculate_completed(torrent=torrent)
            # 剩余大小
            if TorrentField.REMAINING in fields:
                calculate_remaining_size(torrent=torrent)
            # 剩余时间
            if TorrentField.REMAINING_TIME in fields:
                if torrent.get(TorrentField.STATE.tr) == TorrentStatus.DOWNLOADING.value:
                    download_speed = torrent.get(TorrentField.DOWNLOAD_SPEED.tr)
                    if download_speed <= 0:
                        remaining_time = -1
                    else:
                        remaining_size = calculate_remaining_size(torrent=torrent)
                        remaining_time = remaining_size / download_speed
                else:
                    remaining_time = 0
                torrent.fields[TorrentField.REMAINING_TIME.tr] = remaining_time
            # 下载限速
            if TorrentField.DOWNLOAD_LIMIT in fields:
                if not torrent.get('downloadLimited'):
                    torrent.fields[TorrentField.DOWNLOAD_LIMIT.tr] = None
            # 上传限速
            if TorrentField.UPLOAD_LIMIT in fields:
                if not torrent.get('uploadLimited'):
                    torrent.fields[TorrentField.UPLOAD_LIMIT.tr] = None
        except Exception as e:
            logger.error(f'加工tr种子异常: {str(e)}, torrent = {str(torrent.fields)}', exc_info=True)
            return None

    def __convert_transmission_torrent_data(self,
                                            torrent: Torrent,
                                            fields: List[TorrentField]) -> Optional[List[Any]]:
        """
        转换tr种子数据
        """
        if not torrent or not fields:
            return None
        # 加工tr种子
        self.__process_torrent_for_transmission(torrent=torrent,fields=fields)
        data = []
        for field in fields:
            value = self.__extract_torrent_value_for_transmission(torrent=torrent, field=field)
            data.append(value)
        return data

    @staticmethod
    def __extract_torrent_value_for_transmission(torrent: Torrent,
                                                 field: TorrentField) -> Any:
        """
        从tr种子中提取值
        """
        if not torrent or not field:
            return None
        try:
            if not field.tr:
                return None
            value = torrent.get(field.tr)
            if field.convertor:
                value = field.convertor.convert(value)
            return value
        except Exception as e:
            logger.error(f'从tr种子中提取值异常: {str(e)}, torrent = {str(torrent.fields)}', exc_info=True)
            return None

    def __get_dashboard_active_torrent_widget_elememts(self, downloader_id: str) -> list:
        """
        获取仪表板活动种子组件元素
        """
        if not downloader_id:
            return None
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        fields = self.__get_dashboard_active_torrent_widget_display_fields()
        field_count=len(fields)
        data = self.__get_downloader_active_torrent_data(downloader_id=downloader_id, fields=fields)
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        return [{
            'component': 'VTable',
            'props': {
                'hover': True,
                'fixed-header': True,
                'density': 'compact',
                'style': {
                    'height': '242px'
                }
            },
            'content': [
                self.__build_dashboard_widget_torrent_table_head(fields=fields),
                self.__build_dashboard_widget_torrent_table_body(data=data, field_count=field_count, downloader_id=downloader_id)
            ]
        }]

    def __get_downloader_transfer_info(self,
                                       downloader_id: str) -> DownloaderTransferInfo:
        """
        获取下载器传输信息
        """
        if downloader_id == Downloader.QB.id:
            return self.__get_qbittorrent_transfer_info()
        elif downloader_id == Downloader.TR.id:
            return self.__get_transmission_transfer_info()
        else:
            return DownloaderTransferInfo()

    def __get_qbittorrent_transfer_info(self) -> DownloaderTransferInfo:
        """
        获取qb下载器传输信息
        """
        result = DownloaderTransferInfo()
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return result
        qbittorrent = self.__get_qbittorrent()
        if not qbittorrent:
            return result
        info = qbittorrent.transfer_info()
        if info:
            result.download_speed = f'{StringUtils.str_filesize(info.get("dl_info_speed"))}/s'
            result.upload_speed = f'{StringUtils.str_filesize(info.get("up_info_speed"))}/s'
            result.download_size = StringUtils.str_filesize(info.get("dl_info_data"))
            result.upload_size = StringUtils.str_filesize(info.get("up_info_data"))
        maindata = self.__get_qbittorrent_maindata()
        if maindata:
            server_state = maindata.get("server_state")
            if server_state:
                result.free_space = StringUtils.str_filesize(server_state.get("free_space_on_disk"))
        return result

    def __get_qbittorrent_maindata(self):
        """
        获取qb的maindata
        """
        cache_key = "qbittorrent_maindata"
        maindata = self.__ttl_cache.get(cache_key)
        if not maindata:
            qbittorrent = self.__get_qbittorrent()
            if qbittorrent:
                maindata = qbittorrent.qbc.sync_maindata()
                self.__ttl_cache[cache_key] = maindata
        return maindata

    def __get_transmission_transfer_info(self) -> DownloaderTransferInfo:
        """
        获取qb下载器传输信息
        """
        result = DownloaderTransferInfo()
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return result
        transmission = self.__get_transmission()
        if not transmission:
            return result
        info = transmission.transfer_info()
        if info:
            result.download_speed = f"{StringUtils.str_filesize(info.download_speed)}/s"
            result.upload_speed = f"{StringUtils.str_filesize(info.upload_speed,)}/s"
            result.download_size = StringUtils.str_filesize(info.current_stats.downloaded_bytes)
            result.upload_size = StringUtils.str_filesize(info.current_stats.uploaded_bytes)
        session = self.__get_transmission_session()
        if session:
            result.free_space = StringUtils.str_filesize(session.download_dir_free_space)
        return result

    def __get_transmission_session(self):
        """
        获取tr的session
        """
        cache_key = "transmission_session"
        session = self.__ttl_cache.get(cache_key)
        if not session:
            transmission = self.__get_transmission()
            if transmission:
                session = transmission.get_session()
                self.__ttl_cache[cache_key] = session
        return session

    def __build_mdi_icon_svg_elememt(self, mdi_icon: str) -> dict:
        """
        构造 svg mdi 图标元素
        """
        if not mdi_icon:
            return None
        path = self.__mdi_icon_svg_path.get(mdi_icon)
        if not path:
            return None
        return {
            'component': 'svg',
            'props': {
                'class': 'v-icon notranslate v-icon--size-default iconify iconify--mdi',
                'rounded': True,
                'width': '1em',
                'height': '1em',
                'viewBox': '0 0 24 24',
                'style': {
                    'top': '-1px'
                }
            },
            'content': [{
                'component': 'path',
                'props': {
                    'fill': 'currentColor',
                    'd': path
                }
            }]
        }

    def __build_dashboard_speed_widget_list_item_element(self, mdi_icon: str, label: str, value: str, is_last: bool = False) -> dict:
        """
        构造仪表板实时速率组件列表item元素
        """
        if not mdi_icon or not label or not value:
            return None
        div_style = {
            'display': 'grid',
            'grid-template-areas': '"prepend content append"',
            'grid-template-columns': 'max-content 1fr auto',
            'padding-bottom': '16px'
        }
        if is_last:
            del div_style['padding-bottom']
        return {
            'component': 'div',
            'props': {
                'style': div_style
            },
            'content': [{
                'component': 'div',
                'props': {
                    'style': {
                        'grid-area': 'prepend',
                        'height': '21px'
                    }
                },
                'content': [self.__build_mdi_icon_svg_elememt(mdi_icon=mdi_icon)]
            }, {
                'component': 'div',
                'props': {
                    'style': {
                        'grid-area': 'content',
                        'margin-left': '15px'
                    }
                },
                'content': [{
                    'component': 'h6',
                    'props': {
                        'class': 'text-sm font-weight-medium mb-1'
                    },
                    'text': label
                }]
            }, {
                'component': 'div',
                'props': {
                    'style': {
                        'grid-area': 'append'
                    }
                },
                'content': [{
                    'component': 'h6',
                    'props': {
                        'class': 'text-sm font-weight-medium mb-2'
                    },
                    'text': value
                }]
            }]
        }

    def __get_dashboard_speed_widget_elememts(self, downloader_id: str) -> list:
        """
        获取仪表板实时速率组件元素
        """
        if not downloader_id:
            return None
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        data = self.__get_downloader_transfer_info(downloader_id=downloader_id)
        if self.__exit_event.is_set():
            logger.warn('插件服务正在退出，操作取消')
            return None
        list_items = [
            self.__build_dashboard_speed_widget_list_item_element(mdi_icon='mdi-cloud-upload', label='总上传量', value=data.upload_size),
            self.__build_dashboard_speed_widget_list_item_element(mdi_icon='mdi-download-box', label='总下载量', value=data.download_size),
            self.__build_dashboard_speed_widget_list_item_element(mdi_icon='mdi-content-save', label='磁盘剩余空间', value=data.free_space, is_last=True),
        ]
        return [{
            'component': 'div',
            'props': {
                'style': {
                    'padding': '16px 0 0 0'
                }
            },
            'content': [{
                'component': 'div',
                'content': [{
                    'component': 'p',
                    'props': {
                        'class': 'text-h5 me-2'
                    },
                    'text': f'↑{data.upload_speed}'
                }, {
                    'component': 'p',
                    'props': {
                        'class': 'text-h4 me-2'
                    },
                    'text': f'↓{data.download_speed}'
                }]
            }, {
                'component': 'div',
                'props': {
                    'class': 'card-list mt-9'
                },
                'content': list_items
            }]
        }]

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
        # enable_seeding=True是针对辅种添加种子并跳过校验的场景
        context = TaskContext().enable_seeding(True) \
            .enable_tagging(True) \
            .enable_delete(False)
        _hash = event.event_data.get('hash')
        if _hash:
            context.select_torrent(torrent=_hash)
        username = event.event_data.get('username')
        if username:
            context.set_username(username=username)
        self.__block_run(context=context)
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
        # 针对源文件监听事件只需要处理删种
        context = TaskContext().enable_seeding(False) \
            .enable_tagging(False) \
            .enable_delete(True) \
            .set_deleted_event_data(event.event_data)
        self.__block_run(context=context)
        logger.info('源文件删除事件监听任务执行结束')
