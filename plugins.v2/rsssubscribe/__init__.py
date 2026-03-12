import datetime
import re
import traceback
from pathlib import Path
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple
import json

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo, TorrentInfo, Context
from app.core.metainfo import MetaInfo
from app.helper.rss import RssHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ExistMediaInfo
from app.schemas.types import SystemConfigKey, MediaType

lock = Lock()


class RssSubscribe(_PluginBase):
    # 插件名称
    plugin_name = "自定义订阅缓存版"
    # 插件描述
    plugin_desc = "定时刷新RSS报文，识别内容后加入缓存，在等待窗口内收集同组种子，窗口到期后按优先级规则选出最优版本推送下载。"
    # 插件图标
    plugin_icon = "rss.png"
    # 插件版本
    plugin_version = "3.02"
    # 插件作者
    plugin_author = "jxxghp,jager"
    # 作者主页
    author_url = "https://github.com/jagernb/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "rsssubscribe_jager"
    # 加载顺序
    plugin_order = 19
    # 可使用的用户级别
    auth_level = 2

    # 私有变量
    _scheduler: Optional[BackgroundScheduler] = None
    _cache_path: Optional[Path] = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _address: str = ""
    _include: str = ""
    _exclude: str = ""
    _proxy: bool = False
    _filter: bool = False
    _clear: bool = False
    _clearflag: bool = False
    _action: str = "subscribe"
    _save_path: str = ""
    _size_range: str = ""
    _candidate_pool: bool = False
    _pool_wait_minutes: int = 60
    _instant_priority: int = 0
    _category_instant_priority_map: Dict[str, int] = {}
    _category_priority_model_prefix = "category_instant_priority__"

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self.__validate_and_fix_config(config=config)
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._address = config.get("address")
            self._include = config.get("include")
            self._exclude = config.get("exclude")
            self._proxy = config.get("proxy")
            self._filter = config.get("filter")
            self._clear = config.get("clear")
            self._action = config.get("action")
            self._save_path = config.get("save_path")
            self._size_range = config.get("size_range")
            self._candidate_pool = config.get("candidate_pool", False)
            self._pool_wait_minutes = int(config.get("pool_wait_minutes") or 60)
            self._instant_priority = int(config.get("instant_priority") or 0)
            self._category_instant_priority_map = self.__normalize_category_priority_map(
                config.get("category_instant_priority_map")
            )
            self._category_instant_priority_map.update(self.__extract_category_priority_from_config(config))

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"自定义订阅服务启动，立即运行一次")
            self._scheduler.add_job(func=self.check, trigger='date',
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
            # 记录清理缓存设置
            self._clearflag = self._clear
            # 关闭清理缓存开关
            self._clear = False
            # 保存设置
            self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

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
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除自定义订阅历史记录"
            }
        ]

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
                "id": "RssSubscribe",
                "name": "自定义订阅服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.check,
                "kwargs": {}
            }]
        elif self._enabled:
            return [{
                "id": "RssSubscribe",
                "name": "自定义订阅服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"minutes": 30}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        category_priority_rows = self.__build_category_priority_rows(filter_groups)

        form_content = [
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'action',
                                            'label': '动作',
                                            'items': [
                                                {'title': '订阅', 'value': 'subscribe'},
                                                {'title': '下载', 'value': 'download'}
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'address',
                                            'label': 'RSS地址',
                                            'rows': 3,
                                            'placeholder': '每行一个RSS地址'
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
                                            'model': 'include',
                                            'label': '包含',
                                            'placeholder': '支持正则表达式'
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
                                            'model': 'exclude',
                                            'label': '排除',
                                            'placeholder': '支持正则表达式'
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
                                            'model': 'size_range',
                                            'label': '种子大小(GB)',
                                            'placeholder': '如：3 或 3-5'
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
                                            'model': 'save_path',
                                            'label': '保存目录',
                                            'placeholder': '下载时有效，留空自动'
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
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'filter',
                                            'label': '使用订阅优先级规则',
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'candidate_pool',
                                            'label': '启用候选池',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'pool_wait_minutes',
                                            'label': '候选池等待时间',
                                            'items': [
                                                {'title': '15分钟', 'value': 15},
                                                {'title': '30分钟', 'value': 30},
                                                {'title': '1小时', 'value': 60},
                                                {'title': '2小时', 'value': 120},
                                                {'title': '4小时', 'value': 240},
                                            ]
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'instant_priority',
                                            'label': '即时推送优先级',
                                            'items': [
                                                {'title': '禁用', 'value': 0},
                                                {'title': '优先级1（仅最高档）', 'value': 1},
                                                {'title': '优先级2（前两档）', 'value': 2},
                                                {'title': '优先级3（前三档）', 'value': 3},
                                                {'title': '优先级4（前四档）', 'value': 4},
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        if category_priority_rows:
            form_content[0]['content'].extend([
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12
                            },
                            'content': [
                                {
                                    'component': 'VTextarea',
                                    'props': {
                                        'model': 'category_priority_desc',
                                        'label': '二级分类即时推送说明',
                                        'rows': 4,
                                        'readonly': True,
                                        'hint': '以下选项来自[设定-规则]中订阅优先级规则组的[二级分类]字段。如需按分类配置即时推送级别，请在[设定-规则]中为各规则组设置对应的二级分类。',
                                        'persistent-hint': True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ])
            form_content[0]['content'].extend(category_priority_rows)

        default_data = {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "cron": "*/30 * * * *",
            "address": "",
            "include": "",
            "exclude": "",
            "proxy": False,
            "clear": False,
            "filter": False,
            "action": "subscribe",
            "save_path": "",
            "size_range": "",
            "candidate_pool": False,
            "pool_wait_minutes": 60,
            "instant_priority": 0,
            "category_instant_priority_map": self._category_instant_priority_map or {},
            "category_priority_desc": '启用[使用订阅优先级规则]后，可按媒体二级分类分别设置即时推送级别(读取自[设定-规则]各订阅优先级规则组的[二级分类]字段)；未单独设置时，回退到上面的全局[即时推送优先级]。'
        }
        for group_name in self.__extract_rule_group_names(filter_groups):
            default_data[self.__get_category_priority_model_name(group_name)] = \
                self._category_instant_priority_map.get(group_name, self._instant_priority)

        return form_content, default_data

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
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                'innerClass': 'absolute top-0 right-0',
                            },
                            'events': {
                                'click': {
                                    'api': 'plugin/RssSubscribe/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'key': title,
                                        'apikey': settings.API_TOKEN
                                    }
                                }
                            },
                        },
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
                                                'class': 'pa-1 pe-5 break-words whitespace-break-spaces'
                                            },
                                            'text': title
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

    def delete_history(self, key: str, apikey: str):
        """
        删除同步历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        historys = self.get_data('history')
        if not historys:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        historys = [h for h in historys if h.get("title") != key]
        self.save_data('history', historys)
        return schemas.Response(success=True, message="删除成功")

    def __update_config(self):
        """
        更新设置
        """
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "address": self._address,
            "include": self._include,
            "exclude": self._exclude,
            "proxy": self._proxy,
            "clear": self._clear,
            "filter": self._filter,
            "action": self._action,
            "save_path": self._save_path,
            "size_range": self._size_range,
            "candidate_pool": self._candidate_pool,
            "pool_wait_minutes": self._pool_wait_minutes,
            "instant_priority": self._instant_priority,
            "category_instant_priority_map": self._category_instant_priority_map
        })

    def check(self):
        """
        通过用户RSS同步豆瓣想看数据
        """
        if not self._address:
            return
        # 读取历史记录
        if self._clearflag:
            history = []
            # 同时清理候选池和已读集合
            self.save_data('candidate_pool', {})
            self.save_data('rss_read', [])
        else:
            history: List[dict] = self.get_data('history') or []

        # 加载已读集合（已处理过的RSS条目title，避免重复识别和查重）
        rss_read: set = set(self.get_data('rss_read') or [])

        # 候选池模式
        if self._candidate_pool:
            self.__check_with_pool(history, rss_read)
        else:
            self.__check_direct(history, rss_read)

        # 保存历史记录
        self.save_data('history', history)
        # 保存已读集合
        self.save_data('rss_read', list(rss_read))
        # 缓存只清理一次
        self._clearflag = False

    def __check_direct(self, history: List[dict], rss_read: set):
        """
        原始模式：识别后直接下载或订阅
        """
        downloadchain = DownloadChain()
        subscribechain = SubscribeChain()
        filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        for url in self._address.split("\n"):
            if not url:
                continue
            logger.info(f"开始刷新RSS：{url} ...")
            results = RssHelper().parse(url, proxy=self._proxy)
            if not results:
                logger.error(f"未获取到RSS数据：{url}")
                continue
            for result in results:
                try:
                    title = result.get("title")
                    description = result.get("description")
                    enclosure = result.get("enclosure")
                    link = result.get("link")
                    size = result.get("size")
                    pubdate: datetime.datetime = result.get("pubdate")
                    if not title or title in [h.get("key") for h in history]:
                        continue
                    # 已读标记：跳过已处理过的条目，避免重复识别和查重
                    if title in rss_read:
                        continue
                    if self._include and not re.search(r"%s" % self._include,
                                                       f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合包含规则")
                        continue
                    if self._exclude and re.search(r"%s" % self._exclude,
                                                   f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合排除规则")
                        continue
                    if self._size_range:
                        sizes = [float(_size) * 1024 ** 3 for _size in self._size_range.split("-")]
                        if len(sizes) == 1 and float(size) < sizes[0]:
                            logger.info(f"{title} - 种子大小不符合条件")
                            continue
                        elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                            logger.info(f"{title} - 种子大小不在指定范围")
                            continue
                    meta = MetaInfo(title=title, subtitle=description)
                    if not meta.name:
                        logger.warn(f"{title} 未识别到有效数据")
                        continue
                    mediainfo: MediaInfo = self.chain.recognize_media(meta=meta)
                    if not mediainfo:
                        # 清理标题中的方括号内容，只保留主标题重试识别
                        clean_title = re.sub(r'\[.*?\]', '', title).strip()
                        if clean_title and clean_title != title:
                            logger.info(f'首次识别失败，清理标题后重试：{clean_title}')
                            meta = MetaInfo(title=clean_title, subtitle=description)
                            if meta.name:
                                mediainfo = self.chain.recognize_media(meta=meta)
                        if not mediainfo:
                            logger.warn(f'未识别到媒体信息，标题：{title}')
                            continue
                    torrentinfo = TorrentInfo(
                        title=title,
                        description=description,
                        enclosure=enclosure,
                        page_url=link,
                        size=size,
                        pubdate=pubdate.strftime("%Y-%m-%d %H:%M:%S") if pubdate else None,
                        site_proxy=self._proxy,
                    )
                    if self._filter:
                        filter_result = self.chain.filter_torrents(
                            rule_groups=filter_groups,
                            torrent_list=[torrentinfo],
                            mediainfo=mediainfo
                        )
                        if not filter_result:
                            logger.info(f"{title} {description} 不匹配过滤规则")
                            continue
                    # 通过基础过滤后标记为已读
                    rss_read.add(title)
                    if self.__check_media_exists(mediainfo, meta):
                        continue
                    if self._action == "download":
                        download_result = downloadchain.download_single(
                            context=Context(
                                meta_info=meta,
                                media_info=mediainfo,
                                torrent_info=torrentinfo,
                            ),
                            save_path=self._save_path,
                            username="RSS订阅"
                        )
                        if not download_result:
                            logger.error(f'{title} 下载失败')
                            continue
                    else:
                        subflag = subscribechain.exists(mediainfo=mediainfo, meta=meta)
                        if subflag:
                            logger.info(f'{mediainfo.title_year} {meta.season} 正在订阅中')
                            continue
                        subscribechain.add(title=mediainfo.title,
                                           year=mediainfo.year,
                                           mtype=mediainfo.type,
                                           tmdbid=mediainfo.tmdb_id,
                                           season=meta.begin_season,
                                           exist_ok=True,
                                           username="RSS订阅")
                    history.append({
                        "title": f"{mediainfo.title} {meta.season}",
                        "key": f"{title}",
                        "type": mediainfo.type.value,
                        "year": mediainfo.year,
                        "poster": mediainfo.get_poster_image(),
                        "overview": mediainfo.overview,
                        "tmdbid": mediainfo.tmdb_id,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as err:
                    logger.error(f'刷新RSS数据出错：{str(err)} - {traceback.format_exc()}')
            logger.info(f"RSS {url} 刷新完成")

    def __check_with_pool(self, history: List[dict], rss_read: set):
        """
        候选池模式：识别后进入候选池，等待窗口到期后择优推送
        """
        candidate_pool: dict = self.get_data('candidate_pool') or {}
        filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        history_keys = set(h.get("key") for h in history)
        # 媒体维度去重：记录已推送过的分组key（同一部剧同一集/同一部电影只推送一次）
        pushed_groups: set = set()

        for url in self._address.split("\n"):
            if not url:
                continue
            logger.info(f"开始刷新RSS（候选池模式）：{url} ...")
            results = RssHelper().parse(url, proxy=self._proxy)
            if not results:
                logger.error(f"未获取到RSS数据：{url}")
                continue
            for result in results:
                try:
                    title = result.get("title")
                    description = result.get("description")
                    enclosure = result.get("enclosure")
                    link = result.get("link")
                    size = result.get("size")
                    pubdate: datetime.datetime = result.get("pubdate")
                    # 跳过已处理或已在候选池中的
                    if not title or title in history_keys:
                        continue
                    if self.__is_in_candidate_pool(title, candidate_pool):
                        continue
                    # 已读标记：跳过已处理过的条目，避免重复识别和查重
                    if title in rss_read:
                        continue
                    # 包含/排除规则
                    if self._include and not re.search(r"%s" % self._include,
                                                       f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合包含规则")
                        continue
                    if self._exclude and re.search(r"%s" % self._exclude,
                                                   f"{title} {description}", re.IGNORECASE):
                        logger.info(f"{title} - {description} 不符合排除规则")
                        continue
                    # 种子大小过滤
                    if self._size_range:
                        sizes = [float(_size) * 1024 ** 3 for _size in self._size_range.split("-")]
                        if len(sizes) == 1 and float(size) < sizes[0]:
                            logger.info(f"{title} - 种子大小不符合条件")
                            continue
                        elif len(sizes) > 1 and not sizes[0] <= float(size) <= sizes[1]:
                            logger.info(f"{title} - 种子大小不在指定范围")
                            continue
                    # 识别媒体信息
                    meta = MetaInfo(title=title, subtitle=description)
                    if not meta.name:
                        logger.warn(f"{title} 未识别到有效数据")
                        continue
                    mediainfo: MediaInfo = self.chain.recognize_media(meta=meta)
                    if not mediainfo:
                        # 清理标题中的方括号内容，只保留主标题重试识别
                        clean_title = re.sub(r'\[.*?\]', '', title).strip()
                        if clean_title and clean_title != title:
                            logger.info(f'首次识别失败，清理标题后重试：{clean_title}')
                            meta = MetaInfo(title=clean_title, subtitle=description)
                            if meta.name:
                                mediainfo = self.chain.recognize_media(meta=meta)
                        if not mediainfo:
                            logger.warn(f'未识别到媒体信息，标题：{title}')
                            continue
                    # 媒体维度去重：同一部剧同一集/同一部电影已推送过则跳过
                    group_key = self.__build_group_key(mediainfo, meta)
                    if group_key in pushed_groups:
                        logger.info(f"{title} 所属分组 {group_key} 已推送过，跳过")
                        continue
                    # 构建种子信息
                    torrentinfo = TorrentInfo(
                        title=title,
                        description=description,
                        enclosure=enclosure,
                        page_url=link,
                        size=size,
                        pubdate=pubdate.strftime("%Y-%m-%d %H:%M:%S") if pubdate else None,
                        site_proxy=self._proxy,
                    )
                    # 基础过滤规则（同时设置 pri_order）
                    if self._filter:
                        filter_result = self.chain.filter_torrents(
                            rule_groups=filter_groups,
                            torrent_list=[torrentinfo],
                            mediainfo=mediainfo
                        )
                        if not filter_result:
                            logger.info(f"{title} {description} 不匹配过滤规则")
                            continue
                        # 取回带 pri_order 的 torrentinfo
                        torrentinfo = filter_result[0]
                    # 通过基础过滤后标记为已读
                    rss_read.add(title)
                    # Emby库去重
                    if self.__check_media_exists(mediainfo, meta):
                        continue
                    instant_priority = self.__get_instant_priority_for_mediainfo(mediainfo)
                    # 即时推送检查：pri_order 达到阈值则立即推送
                    if (instant_priority > 0
                            and self._filter
                            and torrentinfo.pri_order >= (101 - instant_priority)):
                        logger.info(f"{title} 分类 {self.__get_mediainfo_category(mediainfo) or '未分类'} "
                                    f"优先级 {torrentinfo.pri_order} 达到即时推送阈值"
                                    f"（需>={101 - instant_priority}），立即推送")
                        success = self.__push_torrent(meta=meta, mediainfo=mediainfo,
                                                      torrentinfo=torrentinfo)
                        if success:
                            history.append({
                                "title": f"{mediainfo.title} {meta.season}",
                                "key": f"{title}",
                                "type": mediainfo.type.value,
                                "year": mediainfo.year,
                                "poster": mediainfo.get_poster_image(),
                                "overview": mediainfo.overview,
                                "tmdbid": mediainfo.tmdb_id,
                                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            history_keys.add(title)
                            pushed_groups.add(group_key)
                            # 清除该分组的其他候选
                            candidate_pool.pop(group_key, None)
                            continue
                        elif self._action != "download":
                            # 订阅模式返回False表示已在订阅中，无需加入候选池
                            continue
                        # 下载模式推送失败，降级加入候选池等待重试
                        logger.warn(f"{title} 即时推送失败，降级加入候选池等待重试")
                    # 加入候选池
                    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if group_key not in candidate_pool:
                        candidate_pool[group_key] = {
                            "first_seen": now_str,
                            "candidates": []
                        }
                    # 单组候选上限50
                    if len(candidate_pool[group_key]["candidates"]) >= 50:
                        logger.warn(f"候选池分组 {group_key} 候选数已达上限，跳过 {title}")
                        continue
                    candidate_pool[group_key]["candidates"].append({
                        "title": title,
                        "description": description,
                        "enclosure": enclosure,
                        "link": link,
                        "size": size,
                        "pubdate": pubdate.strftime("%Y-%m-%d %H:%M:%S") if pubdate else None,
                        "added_time": now_str
                    })
                    logger.info(f"{title} 已加入候选池，分组：{group_key}，"
                                f"当前候选数：{len(candidate_pool[group_key]['candidates'])}")
                except Exception as err:
                    logger.error(f'刷新RSS数据出错：{str(err)} - {traceback.format_exc()}')
            logger.info(f"RSS {url} 刷新完成")

        # 保存候选池
        self.save_data('candidate_pool', candidate_pool)
        # 评估到期分组
        self.__process_candidate_pool(history)

    def __normalize_category_priority_map(self, value: Any) -> Dict[str, int]:
        """兼容字典/JSON 字符串形式的分类即时推送配置。"""
        if not value:
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return {}
        if not isinstance(value, dict):
            return {}

        normalized = {}
        for key, priority in value.items():
            name = str(key).strip()
            if not name:
                continue
            try:
                normalized[name] = max(0, min(4, int(priority or 0)))
            except Exception:
                normalized[name] = 0
        return normalized

    @staticmethod
    def __normalize_name(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "")).lower()

    def __extract_rule_group_names(self, filter_groups: Any) -> List[str]:
        """从订阅优先级规则组配置中提取已配置的二级分类名称（category字段）。"""
        categories = []
        items = []
        if isinstance(filter_groups, list):
            items = filter_groups
        elif isinstance(filter_groups, dict):
            items = filter_groups.values()
        for item in items:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            if category and category.lower() != "none" and category not in categories:
                categories.append(category)
        return categories

    def __build_category_priority_rows(self, filter_groups: Any) -> List[dict]:
        group_names = self.__extract_rule_group_names(filter_groups)
        rows = []
        priority_items = [
            {'title': '禁用', 'value': 0},
            {'title': '优先级1（仅最高档）', 'value': 1},
            {'title': '优先级2（前两档）', 'value': 2},
            {'title': '优先级3（前三档）', 'value': 3},
            {'title': '优先级4（前四档）', 'value': 4},
        ]

        for index in range(0, len(group_names), 3):
            cols = []
            for group_name in group_names[index:index + 3]:
                cols.append({
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'md': 4
                    },
                    'content': [
                        {
                            'component': 'VSelect',
                            'props': {
                                'model': self.__get_category_priority_model_name(group_name),
                                'label': f'{group_name} 即时推送级别',
                                'items': priority_items,
                                'hint': f'二级分类：{group_name}',
                                'persistent-hint': True
                            }
                        }
                    ]
                })
            rows.append({
                'component': 'VRow',
                'content': cols
            })
        return rows

    def __get_category_priority_model_name(self, group_name: str) -> str:
        safe_name = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]+', '_', str(group_name or '').strip())
        return f"{self._category_priority_model_prefix}{safe_name}"

    def __extract_category_priority_from_config(self, config: dict) -> Dict[str, int]:
        """从扁平配置项中回填每个规则组的即时推送级别。"""
        if not config:
            return {}

        result = {}
        filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
        for group_name in self.__extract_rule_group_names(filter_groups):
            model_name = self.__get_category_priority_model_name(group_name)
            if model_name not in config:
                continue
            try:
                result[group_name] = max(0, min(4, int(config.get(model_name) or 0)))
            except Exception:
                result[group_name] = 0
        return result

    @staticmethod
    def __get_mediainfo_category(mediainfo: MediaInfo) -> str:
        return str(getattr(mediainfo, 'category', '') or '').strip()

    def __get_instant_priority_for_mediainfo(self, mediainfo: MediaInfo) -> int:
        """按二级分类读取即时推送级别，未命中则回退全局配置。"""
        category = self.__get_mediainfo_category(mediainfo)
        if category:
            if category in self._category_instant_priority_map:
                return self._category_instant_priority_map[category]
            # 去除空格后做不区分大小写的精确匹配，避免子串误匹配
            normalized_category = self.__normalize_name(category)
            for key, value in self._category_instant_priority_map.items():
                if self.__normalize_name(key) == normalized_category:
                    return value
        return self._instant_priority

    def __push_torrent(self, meta: MetaInfo, mediainfo: MediaInfo, torrentinfo: TorrentInfo) -> bool:
        """
        执行下载或订阅操作，成功返回True
        """
        if self._action == "download":
            result = DownloadChain().download_single(
                context=Context(
                    meta_info=meta,
                    media_info=mediainfo,
                    torrent_info=torrentinfo,
                ),
                save_path=self._save_path,
                username="RSS订阅"
            )
            if not result:
                logger.error(f'{torrentinfo.title} 下载失败')
                return False
            return True
        else:
            subscribechain = SubscribeChain()
            subflag = subscribechain.exists(mediainfo=mediainfo, meta=meta)
            if subflag:
                logger.info(f'{mediainfo.title_year} {meta.season} 正在订阅中')
                return False
            subscribechain.add(
                title=mediainfo.title,
                year=mediainfo.year,
                mtype=mediainfo.type,
                tmdbid=mediainfo.tmdb_id,
                season=meta.begin_season,
                exist_ok=True,
                username="RSS订阅"
            )
            return True

    @staticmethod
    def __build_group_key(mediainfo: MediaInfo, meta: MetaInfo) -> str:
        """
        构建候选池分组key
        """
        if mediainfo.type == MediaType.TV:
            episodes = "-".join(str(e) for e in sorted(meta.episode_list or []))
            return f"tv_{mediainfo.tmdb_id}_s{meta.begin_season}_e{episodes}"
        return f"movie_{mediainfo.tmdb_id}"

    def __check_media_exists(self, mediainfo: MediaInfo, meta: MetaInfo) -> bool:
        """
        检查媒体库是否已存在，存在返回True
        """
        exist_info: Optional[ExistMediaInfo] = self.chain.media_exists(mediainfo=mediainfo)
        if mediainfo.type == MediaType.TV:
            if exist_info:
                exist_season = exist_info.seasons
                if exist_season:
                    exist_episodes = exist_season.get(meta.begin_season)
                    if exist_episodes and set(meta.episode_list).issubset(set(exist_episodes)):
                        logger.info(f'{mediainfo.title_year} {meta.season_episode} 己存在')
                        return True
        elif exist_info:
            logger.info(f'{mediainfo.title_year} 己存在')
            return True
        return False

    def __is_in_candidate_pool(self, title: str, candidate_pool: dict) -> bool:
        """
        检查种子是否已在候选池中
        """
        for group_data in candidate_pool.values():
            for c in group_data.get("candidates", []):
                if c.get("title") == title:
                    return True
        return False

    def __process_candidate_pool(self, history: List[dict]):
        """
        评估候选池中等待窗口已过期的分组，选择最优版本推送
        """
        candidate_pool: dict = self.get_data('candidate_pool') or {}
        if not candidate_pool:
            return

        now = datetime.datetime.now()
        wait_minutes = self._pool_wait_minutes
        groups_to_remove = []
        filter_groups = self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)

        for group_key, group_data in candidate_pool.items():
            try:
                first_seen = datetime.datetime.strptime(group_data["first_seen"], "%Y-%m-%d %H:%M:%S")
                elapsed = (now - first_seen).total_seconds() / 60

                if elapsed < wait_minutes:
                    logger.debug(f"候选池分组 {group_key} 等待中，已等待 {elapsed:.0f}/{wait_minutes} 分钟")
                    continue

                candidates = group_data.get("candidates", [])
                logger.info(f"候选池分组 {group_key} 等待窗口已过期，开始评估 {len(candidates)} 个候选...")

                if not candidates:
                    groups_to_remove.append(group_key)
                    continue

                # 用第一个候选重建 MetaInfo 和 MediaInfo
                first_c = candidates[0]
                meta = MetaInfo(title=first_c["title"], subtitle=first_c.get("description"))
                mediainfo = self.chain.recognize_media(meta=meta)
                if not mediainfo:
                    # 清理标题中的方括号内容，只保留主标题重试识别
                    clean_title = re.sub(r'\[.*?\]', '', first_c["title"]).strip()
                    if clean_title and clean_title != first_c["title"]:
                        logger.info(f'候选池 {group_key} 首次识别失败，清理标题后重试：{clean_title}')
                        meta = MetaInfo(title=clean_title, subtitle=first_c.get("description"))
                        if meta.name:
                            mediainfo = self.chain.recognize_media(meta=meta)
                    if not mediainfo:
                        logger.warn(f"候选池分组 {group_key} 无法识别媒体信息，清除分组")
                        groups_to_remove.append(group_key)
                        continue

                # 再次检查媒体库（等待期间可能已入库）
                if self.__check_media_exists(mediainfo, meta):
                    logger.info(f"候选池 {group_key}: 媒体库已存在，跳过")
                    groups_to_remove.append(group_key)
                    continue

                # 重建所有候选的 TorrentInfo
                torrent_list = []
                for c in candidates:
                    ti = TorrentInfo(
                        title=c["title"],
                        description=c.get("description"),
                        enclosure=c.get("enclosure"),
                        page_url=c.get("link"),
                        size=c.get("size"),
                        pubdate=c.get("pubdate"),
                        site_proxy=self._proxy,
                    )
                    torrent_list.append(ti)

                # 用优先级规则排序选最优
                best_torrent = torrent_list[0]
                if self._filter and filter_groups and len(torrent_list) > 1:
                    sorted_results = self.chain.filter_torrents(
                        rule_groups=filter_groups,
                        torrent_list=torrent_list,
                        mediainfo=mediainfo
                    )
                    if sorted_results:
                        best_torrent = sorted_results[0]
                    else:
                        logger.info(f"候选池 {group_key}: 所有候选均不匹配过滤规则，取首个候选")

                # 重建最优种子的 MetaInfo
                best_meta = MetaInfo(title=best_torrent.title, subtitle=best_torrent.description)

                # 推送
                success = self.__push_torrent(meta=best_meta, mediainfo=mediainfo, torrentinfo=best_torrent)
                if success:
                    history.append({
                        "title": f"{mediainfo.title} {best_meta.season}",
                        "key": f"{best_torrent.title}",
                        "type": mediainfo.type.value,
                        "year": mediainfo.year,
                        "poster": mediainfo.get_poster_image(),
                        "overview": mediainfo.overview,
                        "tmdbid": mediainfo.tmdb_id,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    logger.info(f"候选池 {group_key}: 已推送最优版本 {best_torrent.title}")
                    groups_to_remove.append(group_key)
                else:
                    logger.warn(f"候选池 {group_key}: 推送失败 {best_torrent.title}，保留分组待重试")

            except Exception as err:
                logger.error(f"候选池分组 {group_key} 处理出错：{str(err)} - {traceback.format_exc()}")
                groups_to_remove.append(group_key)

        # 清理已处理的分组
        for key in groups_to_remove:
            candidate_pool.pop(key, None)

        self.save_data('candidate_pool', candidate_pool)

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message, title="自定义订阅")

    def __validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """
        size_range = config.get("size_range")
        if size_range and not self.__is_number_or_range(str(size_range)):
            self.__log_and_notify_error(f"自定义订阅出错，种子大小设置错误：{size_range}")
            config["size_range"] = None
            return False
        return True

    @staticmethod
    def __is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
        """
        return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))
