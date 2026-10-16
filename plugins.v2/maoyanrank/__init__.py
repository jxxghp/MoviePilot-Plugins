import datetime
import json
import random
import re
from threading import Event
from typing import Tuple, List, Dict, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.helper.browser import PlaywrightHelper
from app.core.metainfo import MetaInfo
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType
from app.utils.http import RequestUtils


class MaoyanRank(_PluginBase):
    """
    获取猫眼的排行榜进行订阅,建议每天一次
    电影获取的url: https://piaofang.maoyan.com/dashboard-ajax/movie
    电视剧获取的url: {tv_url}?showDate=20240223&seriesType=0&platformType=0
        参数 showDate: 时间具体到天
        参数 seriesType: 代表类型 0: 电视剧 1: 网络剧 2: 综艺 不传递-1代表电视剧+网络剧
        参数 platformType: 代表平台 0 全网 3 腾讯视频 2 爱奇艺 1 优酷 7 芒果 5 搜狐 4 乐视 6 PPTV 20 网络电影networkHot=3

    详情链接:
    https://piaofang.maoyan.com/dashboard/movie?movieId=1489349
    https://piaofang.maoyan.com/dashboard/web-heat?movieId=1484643

    """
    # 插件名称
    plugin_name = "猫眼榜单订阅"
    # 插件描述
    plugin_desc = "监控猫眼数据，自动添加订阅。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/baozaodetudou/MoviePilot-Plugins/main/icons/maoyan.jpg"
    # 插件版本
    plugin_version = "3.6"
    # 插件作者
    plugin_author = "逗猫"
    # 作者主页
    author_url = "https://github.com/baozaodetudou"
    # 插件配置项ID前缀
    plugin_config_prefix = "maoyanrank_"
    # 加载顺序
    plugin_order = 6
    # 可使用的用户级别
    auth_level = 1

    # 退出事件
    _event = Event()
    # 私有属性
    downloadchain: DownloadChain = None
    subscribechain: SubscribeChain = None
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _cron = ""
    _clear = False
    # type细分 movie: 电影 web-heat 电视榜单 web-tv 网剧 zongyi 综艺  web-movie 网络电影
    _type = ['movie', 'web-heat', 'web-tv', 'zongyi', 'web-movie']

    _num = 10
    _all_enabled: bool = False
    _all_num = 10
    _tx_enabled: bool = False
    _tx_num = 10
    _iqy_enabled: bool = False
    _iqy_num = 10
    _mg_enabled: bool = False
    _mg_num = 10
    _yk_enabled: bool = False
    _yk_num = 10

    def init_plugin(self, config: dict = None):
        """加载榜单配置并按周期或一次性开关注册刷新任务。"""
        self.downloadchain = DownloadChain()
        self.subscribechain = SubscribeChain()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._clear = config.get("clear")
            self._onlyonce = config.get("onlyonce")

            self._type = config.get("type")
            self._num = config.get("num", 10)

            self._all_enabled = config.get("all_enabled", False)
            self._tx_enabled = config.get("tx_enabled", False)
            self._iqy_enabled = config.get("iqy_enabled", False)
            self._mg_enabled = config.get("mg_enabled", False)
            self._yk_enabled = config.get("yk_enabled", False)
            self._all_num = config.get("all_num", 10)
            self._tx_num = config.get("tx_num", 10)
            self._iqy_num = config.get("iqy_num", 10)
            self._mg_num = config.get("mg_num", 10)
            self._yk_num = config.get("yk_num", 10)


        # 停止现有任务
        self.stop_service()

        # 启动服务
        # 清理插件历史
        if self._clear:
            self.del_data(key="history")
            self._clear = False
            self.__update_config()
            logger.info("历史清理完成")

        if self._enabled or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 周期执行
            if self._cron:
                logger.info(f"猫眼榜单订阅服务启动，周期：{self._cron}")
                try:
                    self._scheduler.add_job(func=self.__refresh_maoyan,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="猫眼榜单订阅")
                except Exception as e:
                    logger.error(f"猫眼榜单订阅服务启动失败，错误信息：{str(e)}")
                    self.systemmessage.put(f"猫眼榜单订阅服务启动失败，错误信息：{str(e)}")
            else:
                self._scheduler.add_job(func=self.__refresh_maoyan, trigger=CronTrigger.from_crontab("0 9 * * *"),
                                        name="猫眼榜单订阅")
                logger.info("猫眼榜单订阅服务启动，周期：每天 09:00")

            # 一次性执行
            if self._onlyonce:
                logger.info("猫眼榜单订阅服务启动，立即运行一次")
                self._scheduler.add_job(func=self.__refresh_maoyan, trigger='date',
                                        run_date=datetime.datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.__update_config()

            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册聊天命令。"""
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """本插件不注册额外 API。"""
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """提供榜单类型、平台、数量和执行周期配置。"""
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
                                    'md': 6
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
                                    'md': 6
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
                                        'component': 'VCronField',
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
                                    'cols': 22,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'type',
                                            'label': '订阅类型',
                                            'items': [
                                                {'title': '电影票房榜单', 'value': 'movie'},
                                                {'title': '电视剧热度榜单', 'value': 'web-heat'},
                                                {'title': '网剧热度榜单', 'value': 'web-tv'},
                                                {'title': '综艺热度榜单', 'value': 'zongyi'},
                                                {'title': '网络电影榜单', 'value': 'web-movie'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 22,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'num',
                                            'label': '电影榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '下边针对电视剧，网剧，综艺的细分类进行设置不开启则不订阅电视剧；'
                                                    '控制是并行的都打开会都进行订阅当然重复会进行过滤。'
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
                                            'model': 'all_enabled',
                                            'label': '全网热门订阅',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'all_num',
                                            'label': '榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'tx_enabled',
                                            'label': '腾讯热门订阅',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'tx_num',
                                            'label': '腾讯榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'iqy_enabled',
                                            'label': '爱奇艺热门订阅',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'iqy_num',
                                            'label': '爱奇艺榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'mg_enabled',
                                            'label': '芒果热门订阅',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'mg_num',
                                            'label': '芒果榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'yk_enabled',
                                            'label': '优酷热门订阅',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'chips': True,
                                            'model': 'yk_num',
                                            'label': '优酷榜单条数',
                                            'items': [
                                                {'title': '1', 'value': 1},
                                                {'title': '2', 'value': 2},
                                                {'title': '3', 'value': 3},
                                                {'title': '5', 'value': 5},
                                                {'title': '7', 'value': 7},
                                                {'title': '10', 'value': 10}
                                            ]
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
            "onlyonce": False,
            "cron": "",
            "clear": False,
            "type": ['movie', 'web-heat', 'web-tv', 'zongyi', 'web-movie'],
            "num": 10,
            "all_enabled": False,
            "tx_enabled": False,
            "iqy_enabled": False,
            "mg_enabled": False,
            "yk_enabled": False,
            "all_num": 10,
            "tx_num": 10,
            "iqy_num": 10,
            "yk_num": 10,
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询历史记录
        historys = self.get_data('history') or []
        if not historys:
            return [
                {
                    'component': 'div',
                    'text': '暂无订阅历史',
                    'props': {
                        'class': 'text-center pa-6 text-medium-emphasis',
                    }
                }
            ]
        if not isinstance(historys, list):
            historys = [historys]

        def safe_text(value, default: str = "—") -> str:
            """
            统一处理历史记录里的空值，避免详情页直接显示 None。
            """
            if value is None:
                return default
            text = str(value).strip()
            if not text or text.lower() == "none":
                return default
            return text

        def tmdb_href(media_type: str, tmdb_id) -> str:
            """
            根据媒体类型生成 TMDB 链接，缺少 ID 时显示占位。
            """
            clean_id = safe_text(tmdb_id, "")
            if not clean_id:
                return ""
            if media_type == MediaType.TV.value:
                return f"https://www.themoviedb.org/tv/{clean_id}"
            return f"https://www.themoviedb.org/movie/{clean_id}"

        # 数据按时间降序排序，并兼容旧历史中 time 为空的情况。
        historys = sorted(historys, key=lambda x: x.get('time') or "", reverse=True)
        items = []
        for index, history in enumerate(historys, start=1):
            media_type = safe_text(history.get("type"), "未知")
            platform = safe_text(history.get("platformDesc"), "未知")
            items.append({
                "index": index,
                "title": safe_text(history.get("title"), "未命名"),
                "release_info": safe_text(history.get("releaseInfo"), "暂无上线信息"),
                "platform": platform,
                "type": media_type,
                "time": safe_text(history.get("time"), "未知时间"),
                "poster": safe_text(history.get("poster"), ""),
                "tmdb_href": tmdb_href(media_type, history.get("tmdbid")),
            })

        movie_count = sum(1 for item in items if item.get("type") == MediaType.MOVIE.value)
        tv_count = sum(1 for item in items if item.get("type") == MediaType.TV.value)
        platform_count = len({item.get("platform") for item in items if item.get("platform") != "未知"})

        def stat_card(title: str, value: str, color: str) -> dict:
            """
            顶部统计卡片，帮助快速掌握历史记录规模。
            """
            return {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 3
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                            'color': color,
                            'class': 'pa-2'
                        },
                        'content': [
                            {
                                'component': 'VCardSubtitle',
                                'props': {
                                    'class': 'pb-0'
                                },
                                'text': title
                            },
                            {
                                'component': 'VCardTitle',
                                'props': {
                                    'class': 'text-h6 pt-1'
                                },
                                'text': value
                            }
                        ]
                    }
                ]
            }

        def history_card(item: dict) -> dict:
            """
            订阅历史卡片，保留海报和关键信息，同时压缩卡片高度。
            """
            title_node = {
                'component': 'a' if item.get("tmdb_href") else 'span',
                'props': {
                    'href': item.get("tmdb_href"),
                    'target': '_blank',
                    'class': 'text-decoration-none'
                } if item.get("tmdb_href") else {},
                'text': item.get("title")
            }
            poster_node = {
                'component': 'VImg',
                'props': {
                    'src': item.get("poster"),
                    'height': 132,
                    'width': 88,
                    'aspect-ratio': '2/3',
                    'class': 'rounded flex-shrink-0',
                    'cover': True
                }
            } if item.get("poster") else {
                'component': 'div',
                'props': {
                    'class': 'd-flex align-center justify-center rounded bg-grey-lighten-3 text-caption text-medium-emphasis flex-shrink-0',
                    'style': {
                        'width': '88px',
                        'height': '132px'
                    }
                },
                'text': '无海报'
            }

            return {
                'component': 'VCard',
                'props': {
                    'variant': 'outlined',
                    'class': 'h-100'
                },
                'content': [
                    {
                        'component': 'div',
                        'props': {
                            'class': 'd-flex flex-nowrap ga-3 pa-3'
                        },
                        'content': [
                            poster_node,
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'min-w-0 flex-grow-1'
                                },
                                'content': [
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'text-subtitle-2 font-weight-bold text-truncate mb-2'
                                        },
                                        'content': [title_node]
                                    },
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'd-flex flex-wrap ga-1 mb-2'
                                        },
                                        'content': [
                                            {
                                                'component': 'VChip',
                                                'props': {
                                                    'size': 'x-small',
                                                    'variant': 'tonal',
                                                    'color': 'indigo'
                                                },
                                                'text': item.get("type")
                                            },
                                            {
                                                'component': 'VChip',
                                                'props': {
                                                    'size': 'x-small',
                                                    'variant': 'tonal',
                                                    'color': 'teal'
                                                },
                                                'text': item.get("platform")
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'text-body-2 mb-1'
                                        },
                                        'text': item.get("release_info")
                                    },
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'text-caption text-medium-emphasis'
                                        },
                                        'text': f"订阅时间：{item.get('time')}"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

        page_size = 8
        pages = [items[index:index + page_size] for index in range(0, len(items), page_size)]
        page_items = []
        for page_index, page_records in enumerate(pages, start=1):
            page_items.append({
                'component': 'VWindowItem',
                'content': [
                    {
                        'component': 'div',
                        'props': {
                            'class': 'd-flex justify-space-between align-center mb-2 text-caption text-medium-emphasis'
                        },
                        'content': [
                            {
                                'component': 'span',
                                'text': f"第 {page_index} / {len(pages)} 页"
                            },
                            {
                                'component': 'span',
                                'text': f"本页 {len(page_records)} 条"
                            }
                        ]
                    },
                    {
                        'component': 'div',
                        'props': {
                            'class': 'grid gap-3 grid-info-card'
                        },
                        'content': [history_card(item) for item in page_records]
                    }
                ]
            })

        return [
            {
                'component': 'VRow',
                'props': {
                    'class': 'mb-2'
                },
                'content': [
                    stat_card("订阅记录", f"{len(items)} 条", "primary"),
                    stat_card("电影", f"{movie_count} 条", "deep-orange"),
                    stat_card("剧集/综艺", f"{tv_count} 条", "indigo"),
                    stat_card("来源平台", f"{platform_count} 个", "teal"),
                ]
            },
            {
                'component': 'VWindow',
                'props': {
                    'show-arrows': 'hover'
                },
                'content': page_items
            }
        ]

    def stop_service(self):
        """
        停止服务
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

    def __update_config(self):
        """
        列新配置
        """

        self.update_config({
            "enabled": self._enabled,
            "cron": self._cron,
            "clear": self._clear,
            "onlyonce": self._onlyonce,
            "type": self._type,
            "num": self._num,
            "all_enabled": self._all_enabled,
            "tx_enabled": self._tx_enabled,
            "iqy_enabled": self._iqy_enabled,
            "mg_enabled": self._mg_enabled,
            "yk_enabled": self._yk_enabled,
            "all_num": self._all_num,
            "tx_num": self._tx_num,
            "iqy_num": self._iqy_num,
            "mg_num": self._mg_num,
            "yk_num": self._yk_num,
        })

    def __refresh_maoyan(self):
        """
        刷新猫眼榜单数据
        电影获取的url:
        https://piaofang.maoyan.com/dashboard-ajax/movie
        电视剧获取的url:
        {tv_url}?showDate=20240223&seriesType=0&platformType=0
        参数 showDate: 时间具体到天
        参数 seriesType: 代表类型 0: 电视剧 1: 网络剧 2: 综艺 不传递-1代表电视剧+网络剧
        参数 platformType: 代表平台 0 全网 3 腾讯视频 2 爱奇艺 1 优酷 7 芒果 5 搜狐 4 乐视 6 PPTV
        """
        logger.info(f"开始刷新猫眼榜单...")
        # 获取当前日期时间
        current_time = datetime.datetime.now()
        nums = self._num
        #
        history: List[dict] = self.get_data('history') or []
        #
        movie_url = ''
        web_movie_url = ''
        tv_urls = []
        # 获取当前日期时间格式化为字符串
        show_date = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y%m%d')
        maoyan_url = 'https://piaofang.maoyan.com'
        if 'movie' in self._type:
            movie_url = f'{maoyan_url}/dashboard-ajax/movie'
        if 'web-movie' in self._type:

            web_movie_url = (f'{maoyan_url}/i/api/encrypt/dashboard/webHeatNetData?'
                             f'showDate={show_date}&platformType=3&dateType=0&rankType=0')
        # 0: 电视剧  1: 网络剧 2: 综艺 不传递-1代表电视剧+网络剧
        # 参数 platformType: 代表平台 0 全网 3 腾讯视频 2 爱奇艺 1 优酷 7 芒果
        # 电视剧
        tv_url = f'{maoyan_url}/i/api/encrypt/dashboard/webHeatData'
        if 'web-heat' in self._type:
            # 全网
            if self._all_enabled:
                url = f'{tv_url}?seriesType=0&showDate={show_date}'
                tv_urls.append([url, self._all_num])
            # tx
            if self._tx_enabled:
                url = f'{tv_url}?seriesType=0&platformType=3&showDate={show_date}'
                tv_urls.append([url, self._tx_num])
            # iqy
            if self._iqy_enabled:
                url = f'{tv_url}?seriesType=0&platformType=2&showDate={show_date}'
                tv_urls.append([url, self._iqy_num])
            # mg
            if self._mg_enabled:
                url = f'{tv_url}?seriesType=0&platformType=7&showDate={show_date}'
                tv_urls.append([url, self._mg_num])
            # yk
            if self._yk_enabled:
                url = f'{tv_url}?seriesType=0&platformType=1&showDate={show_date}'
                tv_urls.append([url, self._yk_num])
        # 网剧
        if 'web-tv' in self._type:
            # 全网
            if self._all_enabled:
                url = f'{tv_url}?seriesType=1&showDate={show_date}'
                tv_urls.append([url, self._all_num])
            # tx
            if self._tx_enabled:
                url = f'{tv_url}?seriesType=1&platformType=3&showDate={show_date}'
                tv_urls.append([url, self._tx_num])
            # iqy
            if self._iqy_enabled:
                url = f'{tv_url}?seriesType=1&platformType=2&showDate={show_date}'
                tv_urls.append([url, self._iqy_num])
            # mg
            if self._mg_enabled:
                url = f'{tv_url}?seriesType=1&platformType=7&showDate={show_date}'
                tv_urls.append([url, self._mg_num])
            # yk
            if self._yk_enabled:
                url = f'{tv_url}?seriesType=1&platformType=1&showDate={show_date}'
                tv_urls.append([url, self._yk_num])
        # 综艺
        if 'zongyi' in self._type:
            # 全网
            if self._all_enabled:
                url = f'{tv_url}?seriesType=2&showDate={show_date}'
                tv_urls.append([url, self._all_num])
            # tx
            if self._tx_enabled:
                url = f'{tv_url}?seriesType=2&platformType=3&showDate={show_date}'
                tv_urls.append([url, self._tx_num])
            # iqy
            if self._iqy_enabled:
                url = f'{tv_url}?seriesType=2&platformType=2&showDate={show_date}'
                tv_urls.append([url, self._iqy_num])
            # mg
            if self._mg_enabled:
                url = f'{tv_url}?seriesType=2&platformType=7&showDate={show_date}'
                tv_urls.append([url, self._mg_num])
            # yk
            if self._yk_enabled:
                url = f'{tv_url}?seriesType=2&platformType=1&showDate={show_date}'
                tv_urls.append([url, self._yk_num])
        tv_list = []
        movie_list = []
        try:
            movie_list, tv_list = self.__get_url_info(movie_url, tv_urls, web_movie_url, nums)
        except Exception as e:
            logger.error(f"获取猫眼榜单失败：{e}")
        self.set_sub(movie_list, history, MediaType.MOVIE)
        self.set_sub(tv_list, history, MediaType.TV)
        # 保存历史记录
        self.save_data('history', history)
        logger.info(f"猫眼订阅刷新完成")

    def set_sub(self, addr_list, history, mtype):
        """
        将猫眼榜单条目识别为媒体信息，并添加到 MoviePilot 订阅。
        """
        # 获取当前日期时间
        current_time = datetime.datetime.now()
        for addr in addr_list:
            title = "未知标题"
            try:
                title = addr.get('title')
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("缺少有效标题")
                year = self.__release_year(addr.get('releaseInfo'), current_time)
                # 元数据
                meta = MetaInfo(title)
                meta.year = year
                unique_flag = f"maoyanrank: {mtype}_{title}_{year}"
                # 检查是否已处理过
                if unique_flag in [h.get("unique") for h in history]:
                    continue
                # 匹配媒体信息
                mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, mtype=mtype, cache=False)
                if not mediainfo:
                    logger.warn(f'未识别到媒体信息，标题：{title}，年份：{year}')
                    continue
                # 查询缺失的媒体信息
                exist_flag, _ = self.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
                if exist_flag:
                    logger.info(f'{mediainfo.title_year} 媒体库中已存在')
                    continue
                # 判断用户是否已经添加订阅
                if self.subscribechain.exists(mediainfo=mediainfo, meta=meta):
                    logger.info(f'{mediainfo.title_year} 订阅已存在')
                    continue
                # 添加订阅
                season = self.__resolve_tv_subscribe_season(title=title, meta=meta, mediainfo=mediainfo) \
                    if mtype == MediaType.TV else None
                self.subscribechain.add(title=mediainfo.title,
                                        year=mediainfo.year,
                                        mtype=mediainfo.type,
                                        tmdbid=mediainfo.tmdb_id,
                                        season=season,
                                        exist_ok=True,
                                        username="猫眼订阅")
                # 存储历史记录
                history.append({
                    "title": title,
                    "releaseInfo": addr.get('releaseInfo'),
                    "platformDesc": addr.get('platformDesc', '未知'),
                    "type": mediainfo.type.value,
                    "year": mediainfo.year,
                    "poster": mediainfo.get_poster_image(),
                    "overview": mediainfo.overview,
                    "tmdbid": mediainfo.tmdb_id,
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "unique": unique_flag
                })
            except Exception as e:
                logger.error(f"猫眼{mtype.value}条目 {title} 处理失败，继续处理下一条：{e}")

    @staticmethod
    def __release_year(release_info, current_time: datetime.datetime) -> int | None:
        """仅从明确上映日期或已上映天数推算年份；缺失和未知文案保留未知年份。"""
        if not isinstance(release_info, str):
            return None
        release_info = release_info.strip()
        if release_info in ("上映首日", "上线首日", "开播首日", "今日上映", "今日上线", "今日开播"):
            return current_time.year
        date_match = re.match(r"^(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})(?!\d)", release_info)
        days_match = re.fullmatch(r"(?:上映|上线|开播)\s*(\d+)\s*天", release_info)
        try:
            if date_match:
                return datetime.date(*(int(part) for part in date_match.groups())).year
            if days_match:
                return (current_time - datetime.timedelta(days=int(days_match.group(1)))).year
        except (ValueError, OverflowError):
            # 上游可能包含非法日期或异常大的天数，不应阻断媒体识别。
            return None
        return None

    @staticmethod
    def __safe_int(value) -> int | None:
        """
        将季号字段安全转换为整数，转换失败时返回空值。
        """
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def __get_season_number(cls, season_info) -> int | None:
        """
        从 TMDB 季信息对象或字典中提取有效季号。
        """
        if isinstance(season_info, dict):
            return cls.__safe_int(season_info.get("season_number"))
        return cls.__safe_int(getattr(season_info, "season_number", None))

    @classmethod
    def __latest_season_from_info(cls, season_infos) -> int | None:
        """
        从 TMDB 季列表中过滤第 0 季后取最新季号。
        """
        seasons = []
        for season_info in season_infos or []:
            season = cls.__get_season_number(season_info)
            if season is not None and season > 0:
                seasons.append(season)
        return max(seasons) if seasons else None

    @classmethod
    def __latest_season_from_media_seasons(cls, seasons) -> int | None:
        """
        从 MediaInfo.seasons 的季号键中过滤第 0 季后取最新季号。
        """
        season_numbers = []
        for season in (seasons or {}).keys():
            season_number = cls.__safe_int(season)
            if season_number is not None and season_number > 0:
                season_numbers.append(season_number)
        return max(season_numbers) if season_numbers else None

    def __latest_tmdb_season(self, mediainfo: MediaInfo) -> int | None:
        """
        查询 TMDB 或识别结果中的季信息，返回最新的有效季号。
        """
        tmdbid = getattr(mediainfo, "tmdb_id", None)
        if tmdbid:
            try:
                latest_season = self.__latest_season_from_info(TmdbChain().tmdb_seasons(tmdbid=tmdbid))
                if latest_season:
                    return latest_season
            except Exception as err:
                logger.warn(f"查询 TMDB 季信息失败，标题：{getattr(mediainfo, 'title', '')}，错误：{err}")

        latest_season = self.__latest_season_from_info(getattr(mediainfo, "season_info", None))
        if latest_season:
            return latest_season

        latest_season = self.__latest_season_from_media_seasons(getattr(mediainfo, "seasons", None))
        if latest_season:
            return latest_season

        return self.__safe_int(getattr(mediainfo, "number_of_seasons", None))

    def __resolve_tv_subscribe_season(self, title: str, meta: MetaInfo, mediainfo: MediaInfo) -> int | None:
        """
        决定猫眼剧集订阅季号：标题显式季号优先，否则使用 TMDB 最新季。
        """
        if meta.begin_season:
            return meta.begin_season

        latest_season = self.__latest_tmdb_season(mediainfo=mediainfo)
        if latest_season:
            meta.begin_season = latest_season
            logger.info(f"猫眼标题 {title} 未指定季号，按 TMDB 最新季 S{latest_season:02d} 订阅")
            return latest_season

        return None

    def __get_url_info(self, movie_url, tv_urls, web_movie_url, num=10):
        """复用一个官网浏览器会话获取榜单，页面校验失败仅影响对应来源。"""
        movies_list = []
        tv_list = []
        sources = []
        if movie_url:
            sources.append((movie_url, num, '电影票房榜单', 'movieList', 'movieInfo', 'movieName', movies_list))
        if web_movie_url:
            sources.append((web_movie_url, num, '网络电影榜单', 'dataList', None, 'movieName', movies_list))
        for tv_url, tv_num in tv_urls:
            sources.append((tv_url, tv_num, '剧集热度榜单', 'dataList', 'seriesInfo', 'name', tv_list))
        if not sources:
            return movies_list, tv_list

        processed = set()

        def collect(page=None):
            """按来源隔离请求；浏览器收尾异常时避免重复请求已经处理的榜单。"""
            headers = {'User-Agent': self.get_random_user_agent()}
            cookies = {}
            if page is not None:
                headers['User-Agent'] = page.evaluate('navigator.userAgent')
                cookies = {cookie['name']: cookie['value'] for cookie in page.context.cookies()}
            for index, (url, limit, name, data_key, info_key, title_key, target) in enumerate(sources):
                if index in processed:
                    continue
                processed.add(index)
                source = f"{name}（{url}）"
                try:
                    if page is not None and '/i/api/encrypt/dashboard/' in url:
                        payload = self.__request_browser_json(page, url)
                        if url == web_movie_url and isinstance(payload, dict) and payload.get('status') is False:
                            calendar = payload.get('calendarNet')
                            latest = calendar.get('selectMaxDate') if isinstance(calendar, dict) else None
                            if isinstance(latest, str):
                                latest = latest.replace('-', '')
                                if re.fullmatch(r'\d{8}', latest):
                                    datetime.datetime.strptime(latest, '%Y%m%d')
                                    parts = urlsplit(url)
                                    query = dict(parse_qsl(parts.query))
                                    if latest != query.get('showDate'):
                                        query['showDate'] = latest
                                        retry_url = urlunsplit(parts._replace(query=urlencode(query)))
                                        logger.info(f"猫眼网络电影榜单暂未提供当日数据，重试最新可用日期 {latest}")
                                        payload = self.__request_browser_json(page, retry_url)
                    else:
                        response = RequestUtils().get_res(url, cookies=cookies, headers=headers)
                        if response is None:
                            raise ValueError("未收到有效响应")
                        response.raise_for_status()
                        payload = response.json()
                    container = payload.get(data_key) if isinstance(payload, dict) else None
                    data = container.get('list') if isinstance(container, dict) else None
                    if not isinstance(data, list):
                        raise ValueError(f"响应缺少有效的 {data_key}.list 榜单列表")
                    items = self.__parse_rank_items(data, limit, info_key, title_key, source)
                    target.extend(items)
                    logger.info(f"猫眼{source}获取到 {len(items)} 条有效记录")
                except Exception as err:
                    logger.error(f"猫眼{source}获取失败，继续处理其他榜单：{err}")

        try:
            self.__with_browser(collect)
        except Exception as err:
            logger.warning(f"猫眼浏览器会话异常：{err}")
        if len(processed) < len(sources):
            logger.warning("猫眼浏览器不可用，将继续无 Cookie 请求未处理榜单，热度接口可能拒绝访问")
            collect()

        # 同一剧集可能出现在多个平台，保留原有按标题去重的行为。
        return movies_list, list({item['title']: item for item in tv_list}.values())

    @staticmethod
    def __request_browser_json(page, url):
        """在官网页面内请求当前接口，由网站自身脚本维护会话与请求校验信息。"""
        return page.evaluate("""async url => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 15000);
            try {
                const headers = {Accept: 'application/json, text/plain, */*'};
                for (const [name, key] of [['csrf', 'uid'], ['deviceId', 'uuid'], ['channelId', 'channelId']]) {
                    const value = document.querySelector(`meta[name="${name}"]`)?.content;
                    if (value) headers[key] = value;
                }
                const response = await fetch(url, {
                    headers, credentials: 'same-origin', signal: controller.signal,
                });
                if (!response.ok) throw new Error(`HTTP ${response.status} ${response.statusText}`);
                return await response.json();
            } finally {
                clearTimeout(timer);
            }
        }""", url)

    @staticmethod
    def __parse_rank_items(data, limit, info_key, title_key, source) -> List[dict]:
        """仅解析配置排名范围内的条目，保留同榜有效数据并记录坏条目的位置。"""
        items = []
        for rank, item in enumerate(data[:limit], start=1):
            try:
                if not isinstance(item, dict):
                    raise ValueError("条目不是对象")
                info = item.get(info_key) if info_key else item
                if not isinstance(info, dict):
                    raise ValueError("缺少媒体详情")
                title = info.get(title_key)
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("缺少有效标题")
                items.append({
                    "title": title.strip(),
                    "releaseInfo": info.get('releaseInfo'),
                    "platformDesc": info.get('platformDesc'),
                })
            except (TypeError, ValueError) as err:
                logger.warning(f"猫眼{source}第 {rank} 条数据无效，跳过该条目：{err}")
        return items

    @staticmethod
    def get_random_user_agent():
        """从桌面浏览器标识中选择请求头。"""
        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        ]
        return random.choice(user_agents)

    @staticmethod
    def __with_browser(callback):
        """通过 V2 宿主管理官网浏览器会话，回调内完成所有榜单请求。"""
        return PlaywrightHelper().action(url='https://piaofang.maoyan.com/dashboard/web-heat',
                                         callback=callback,
                                         headless=True,
                                         timeout=30)
