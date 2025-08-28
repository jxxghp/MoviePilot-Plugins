# 基础库
import datetime
import json
from typing import Any, Dict, List

# 第三方库
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from sqlalchemy.orm import Session

# 项目库
from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.event import eventmanager, Event
from app.core.meta import MetaBase
from app.core.metainfo import MetaInfo
from app.db.models.subscribehistory import SubscribeHistory
from app.db.site_oper import SiteOper
from app.db.subscribe_oper import SubscribeOper
from app.db import db_query
from app.helper.subscribe import SubscribeHelper
from app.log import logger
from app.modules.themoviedb import TmdbApi
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, NotificationType
from app.utils.http import RequestUtils


class BangumiColl(_PluginBase):
    # 插件名称
    plugin_name = "Bangumi收藏订阅"
    # 插件描述
    plugin_desc = "将Bangumi用户收藏添加到订阅"
    # 插件图标
    plugin_icon = "bangumi_b.png"
    # 插件版本
    plugin_version = "1.5.8"
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

    # 私有属性
    _scheduler = None
    _is_v2 = hasattr(settings, "VERSION_FLAG")

    # 配置属性
    _enabled: bool = False
    _total_change: bool = False
    _cron: str = ""
    _notify: bool = False
    _onlyonce: bool = False
    _uid: str = ""
    _collection_type = []
    _save_path: str = ""
    _sites: list = []
    _match_groups: bool = False
    _group_select_order: list = []

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()
        self.load_config(config)

        if self._onlyonce:
            self.schedule_once()

    def load_config(self, config: dict):
        """加载配置"""
        if config:
            # 遍历配置中的键并设置相应的属性
            for key in (
                    "enabled",
                    "total_change",
                    "cron",
                    "notify",
                    "onlyonce",
                    "uid",
                    "collection_type",
                    "save_path",
                    "sites",
                    "match_groups",
                    "group_select_order",
            ):
                setattr(self, f"_{key}", config.get(key, getattr(self, f"_{key}")))
            # 获得所有站点
            site_ids = {site.id for site in SiteOper().list_order_by_pri()}
            # 过滤已删除的站点
            self._sites = [site_id for site_id in self._sites if site_id in site_ids]
            # 更新配置
            self.__update_config()

    def schedule_once(self):
        """调度一次性任务"""
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        logger.info("Bangumi收藏订阅，立即运行一次")
        self._scheduler.add_job(
            func=self.bangumi_coll,
            trigger='date',
            run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3),
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
                "total_change": self._total_change,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "uid": self._uid,
                "collection_type": self._collection_type,
                "save_path": self._save_path,
                "sites": self._sites,
                "match_groups": self._match_groups,
                "group_select_order": self._group_select_order,
            }
        )

    def get_form(self):

        # 列出所有站点
        sites_options = [
            {"title": site.name, "value": site.id}
            for site in SiteOper().list_order_by_pri()
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
                                'props': {'cols': 12, 'md': 3},
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
                                'props': {'cols': 12, 'md': 3},
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
                                'props': {'cols': 12, 'md': 3},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'total_change',
                                            'label': '固定总集数',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 3},
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
                                'props': {'cols': 8, 'md': 4},
                                'content': [
                                    {
                                        # 'component': 'VTextField', # 组件替换为VCronField
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 8, 'md': 4},
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
                                'props': {'cols': 8, 'md': 4},
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal',
                                            'text': True
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'innerHTML': '提示：<strong>剧集组优先级</strong>越靠前优先级越高。'}
                                            }
                                        ]
                                    }
                                ]
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 8, 'md': 4},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'match_groups',
                                            'disabled': not self._is_v2,
                                            'label': '剧集组填充(实验性)',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 8},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'group_select_order',
                                            'label': '剧集组优先级',
                                            'disabled': not self._is_v2,
                                            'chips': True,
                                            'multiple': True,
                                            'clearable': True,
                                            'items': [
                                                {"title": "初始播出日期", "value": 1},
                                                {"title": "绝对", "value": 2},
                                                {"title": "DVD", "value": 3},
                                                {"title": "数字", "value": 4},
                                                {"title": "故事线", "value": 5},
                                                {"title": "制片", "value": 6},
                                                {"title": "电视", "value": 7},
                                            ],
                                        },
                                    }
                                ]
                            },
                        ]
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
                                            'clearable': True,
                                            'items': sites_options,
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': True
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'innerHTML': '注意： 该插件仅会将<strong>公开</strong>的收藏添加到<strong>订阅</strong>。'}
                                            }
                                        ]
                                    }
                                ]
                            },
                        ],
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
                                            'text': True
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'innerHTML': '注意： 开启<strong>自动取消订阅并通知</strong>后，已添加的订阅在下一次执行时若不在已选择的<strong>收藏类型</strong>中，将会被取消订阅。'}
                                            }
                                        ]
                                    }
                                ]
                            },
                        ],
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
                                            'text': True
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'innerHTML': '注意： 开启<strong>固定总集数</strong>后，从<a href="https://bangumi.github.io/api/#/%E7%AB%A0%E8%8A%82/getEpisodes" target="_blank"><u>Bangumi API</u></a>获取到总集数将不会因<strong>订阅元数据更新</strong>改变。'
                                                    }
                                            }
                                        ]
                                    }
                                ]
                            },
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "total_change": False,
            "notify": False,
            "onlyonce": False,
            "cron": "",
            "uid": "",
            "collection_type": [3],
            "save_path": "",
            "sites": [],
            "match_groups": False,
            "group_select_order": [],
        }

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
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

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event: Event):
        """
        删除对应站点
        """
        site_id = event.event_data.get("site_id")
        if site_id in self._sites:
            self._sites.remove(site_id)
            self.__update_config()

    def get_api(self):
        pass

    def get_command(self):
        return [
            {
                "cmd": "/bangumi_coll",
                "event": EventType.PluginAction,
                "desc": "Bangumi收藏订阅",
                "category": "",
                "data": {"action": "bangumi_coll"}
            }
        ]

    def get_page(self):
        pass

    def get_state(self):
        return self._enabled

    @eventmanager.register(EventType.PluginAction)
    def action_event_handler(self, event: Event):
        """
        远程命令处理
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") != "bangumi_coll":
            return

        self.post_message(channel=event_data.get("channel"),
                          title=f"开始添加用户: {self._uid} 的收藏 ...",
                          userid=event_data.get("user"))
        # 运行任务
        msg = self.bangumi_coll()

        self.post_message(channel=event_data.get("channel"),
                          title="添加完成" if not msg else msg,
                          userid=event_data.get("user"))

    def bangumi_coll(self) -> str:
        """订阅Bangumi用户收藏"""
        if not self._uid:
            logger.error("未设置UID")
            return "未设置UID"
        msg = ""
        try:
            res = self.get_bgm_res(addr="UserCollections", id=self._uid)
            items = self.parse_collection_items(res)

            # 新增和移除条目
            if msg := self.manage_subscriptions(items):
                msg = "\n".join(list(msg.values()))
                logger.info(msg)
        except Exception as e:
            msg = f"执行失败: {str(e)}"
            logger.error(msg)
        finally:
            return msg

    def parse_collection_items(self, response) -> Dict[int, Dict[str, Any]]:
        """解析获取的收藏条目"""
        data = response.json().get("data", [])
        if not data:
            logger.error(f"Bangumi用户：{self._uid} ，没有任何收藏")
            return {}

        return {
            item.get("subject_id"): {
                "name": item['subject'].get('name'),
                "name_cn": item['subject'].get('name_cn'),
                "date": item['subject'].get('date'),
                "eps": item['subject'].get('eps'),
                "tags": [tag.get('name') for tag in item['subject'].get('tags', [{}])]
            }
            for item in data
            # 只添加未来30天内放送的条目
            if item.get("type") in self._collection_type and item['subject'].get('date') and self.is_date_in_range(item['subject'].get('date'), threshold_days=30)[0]
        }

    def manage_subscriptions(self, items: Dict[int, Dict[str, Any]]):
        """管理订阅的新增和删除"""
        # 查询订阅
        db_sub = {
            i.bangumiid: i.id
            for i in SubscribeOper().list()
            if i.bangumiid
        }
        # bangumi 条目
        _bgm = set(items.keys())
        # 订阅记录
        _sub = set(db_sub.keys())
        # 插件数据
        plugin_data: list = self.get_data(key="exclude") or []
        # 订阅历史记录
        db_hist: set = self.get_subscribe_history()
        # 更新插件数据
        _tmp = (set(plugin_data) & _bgm) - _sub - db_hist
        new_sub = _bgm - _sub - db_hist - _tmp
        del_sub = _sub - _bgm
        if _tmp:
            # 更新排除条目
            self.save_data(key="exclude", value=list(_tmp))

        if del_sub and self._notify:
            logger.info(f"开始移除订阅: {del_sub} ...")
            self.delete_subscribe({db_sub[i]: i for i in del_sub})
            logger.info("移除完成")

        if new_sub:
            logger.info(f"开始添加订阅: {new_sub} ...")
            msg = self.add_subscribe({i: items[i] for i in new_sub})
            logger.info("添加完成")
            return msg

    # 添加订阅
    def add_subscribe(self, items: Dict[int, Dict[str, Any]]) -> Dict:
        """添加订阅"""

        fail_items = {}
        subscribeoper = SubscribeOper()
        for subid, item in items.items():
            if item.get("name_cn"):
                meta = MetaInfo(item.get("name_cn"))
                meta.en_name = item.get("name")
            else:
                meta = MetaInfo(item.get("name"))
            if not meta.name:
                fail_items[subid] = f"{subid} 未识别到有效数据"
                logger.warn(f"{subid} 未识别到有效数据")
                continue
            # 年份信息
            sub_air_date = item.get("date")
            meta.year = sub_air_date[:4] if sub_air_date else None
            # 通过`tags`识别类型
            tags = item.get("tags") or []
            mtype = MediaType.MOVIE if "剧场版" in tags else MediaType.TV

            mediainfo = None
            for retry in range(2):
                if retry:
                    meta.cn_name = meta.org_string
                    meta.en_name = meta.title

                if (mediainfo := self.chain.recognize_media(
                        meta=meta,
                        mtype=mtype,
                        cache=False
                )) or any(
                    getattr(meta, attr) == meta.org_string
                    for attr in ('cn_name', 'en_name')
                ):
                    break

            if not mediainfo:
                fail_items[subid] = f"{item.get('name_cn')} 媒体信息识别失败"
                logger.debug(f"识别失败详情 | subid:{subid} meta:{vars(meta)}")
                continue
            meta.total_episode = item.get("eps", 0)
            mediainfo.bangumi_id = subid
            # 根据发行日期判断是不是续作
            if mediainfo.type == MediaType.TV \
                    and not self.is_date_in_range(sub_air_date, mediainfo.release_date)[0]:
                # 识别剧集组标志
                group_flag: bool = True
                season_info = []
                if "OVA" in item.get("tags"):
                    # 季0 处理
                    if tmdb_info := self.chain.tmdb_info(mediainfo.tmdb_id, mediainfo.type, 0):
                        for info in tmdb_info.get("episodes", []):
                            if self.is_date_in_range(sub_air_date, info.get("air_date"), 2)[0]:
                                mediainfo.season = 0
                                meta.begin_episode = info.get("episode_number")
                    else:  # 信息不完整, 跳过条目
                        continue

                else:
                    # 过滤信息不完整和第0季
                    season_info = [info for info in mediainfo.season_info if
                                   info.get("season_number") and info.get("air_date") and info.get("episode_count")]
                    # 获取 bangumi 信息
                    meta = self.get_eps(meta, subid)
                    # 先通过season_info处理三季及以上的情况, tmdb存在第二季也不能保证不会被合并
                    if len(season_info) > 2:
                        # tmdb不合并季, 更新季信息
                        mediainfo.season = self.get_best_season_number(sub_air_date, mediainfo.season_info)
                        group_flag = False
                    elif len(season_info) == 2:
                        # 第二季特殊处理, 通过bangumi 'sort'字段判断集号连续性
                        if meta.begin_episode:
                            if meta.begin_episode == 1:
                                # 不合并季
                                mediainfo.season = self.get_best_season_number(sub_air_date, mediainfo.season_info)
                                group_flag = False
                            else:
                                group_flag = True

                if self._match_groups and group_flag and mediainfo.episode_groups:
                    # tmdb季分割
                    season_data = self._season_split(mediainfo)
                    # 总季数传递
                    meta.total_season = len(season_data)
                    # 根据bgm 和 tmdb 信息判断
                    if len(season_data) > 1:
                        # 转换为方法入参格式
                        _season = [{"season_number": k, "air_date": v.get('air_date')} for k, v in season_data.items()]
                        # BGM条目在分割后的季号
                        _season_num = self.get_best_season_number(sub_air_date, _season)
                        # 季分割后的播出时间
                        air_date = season_data[_season_num].get('air_date')
                        # 季集的可能性
                        season_list = []
                        for info in mediainfo.season_info:
                            if info.get("season_number") == 0:
                                season_list.append(
                                    (len(season_info) + 1, len(mediainfo.seasons[1]) + info.get("episode_count")))
                        season_list.append((len(season_info), len(mediainfo.seasons[1])))
                        # 预匹配剧集组
                        candidate_groups = (
                            group for group in mediainfo.episode_groups
                            if any(group.get("group_count") == s[0] and
                                   group.get("episode_count") == s[1]
                                   for s in season_list
                                   )
                        )

                        for group in candidate_groups:
                            if season_num := self.get_group_season(group.get("id"), air_date, mediainfo):
                                mediainfo.episode_group = group.get("id")
                                mediainfo.season = season_num
                                break
                        else:
                            mediainfo = self._match_group(air_date, meta, mediainfo)
            # 非续作
            elif mediainfo.type == MediaType.TV:
                mediainfo.season = 1
            # 检查本地媒体
            exist_flag, no_exists = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
            if exist_flag:
                # 添加到排除
                self.update_data(key="exclude", value=subid)
                logger.info(f'{mediainfo.title_year} 媒体库中已存在')
                continue
            elif not no_exists.get(mediainfo.tmdb_id, {}).get(mediainfo.season):
                # 添加到排除
                self.update_data(key="exclude", value=subid)
                logger.info(f'{mediainfo.title_year} 媒体库中已存在 第 {mediainfo.season} 季')
                continue
            sid = subscribeoper.list_by_tmdbid(
                mediainfo.tmdb_id, mediainfo.season
            )
            if sid:
                logger.info(f"{mediainfo.title_year} 正在订阅中")
                if len(sid) == 1:
                    subscribeoper.update(
                        sid=sid[0].id, payload={"bangumiid": subid}
                    )
                    logger.info(f"{mediainfo.title_year} Bangumi条目id更新成功")
                continue
            # 添加订阅
            sid, msg = SubscribeChain().add(**self.prepare_add_args(meta, mediainfo))
            if not sid:
                fail_items[subid] = f"{item.get('name_cn') or item.get('name')} {msg}"

        return fail_items

    def _season_split(self, mediainfo: MediaInfo, season: int = 1) -> Dict[int, dict]:
        """
        将tmdb多季合并的季信息进行拆分
        """
        season_data = {}
        if tmdb_info := self.chain.tmdb_info(mediainfo.tmdb_id, mediainfo.type, season):
            season = 1
            air_date = tmdb_info.get("air_date")
            episodes: list[dict] = tmdb_info.get("episodes", [])
            season_data = {season: {"air_date": air_date, "count": 0}}

            for ep in episodes:
                if not air_date:
                    air_date = ep.get("air_date")
                    season_data[season] = {"air_date": air_date, "count": 0}

                season_data[season]["count"] += 1

                if ep.get("episode_type") == "finale":
                    air_date = None
                    # 季号递增
                    season += 1
        return season_data

    def _match_group(self, air_date: str, meta: MetaBase, mediainfo: MediaInfo) -> MediaInfo:
        """
        根据剧集组类型匹配剧集组
        :param air_date: 播出日期
        :param meta: bangumi 元数据
        :param mediainfo: 媒体信息
        :return: MediaInfo
        """
        if not mediainfo.episode_groups:
            return mediainfo

        # 处理元数据
        begin_ep = meta.begin_episode or 1
        total_season = meta.total_season or 2

        # 按类型预分组
        episode_groups_by_type: dict[int, list[dict]] = {}
        for group in mediainfo.episode_groups:
            group_type = group.get("type")
            if group_type not in episode_groups_by_type:
                episode_groups_by_type[group_type] = []
            episode_groups_by_type[group_type].append(group)

        # 按优先级遍历类型
        for group_type in self._group_select_order:
            # 获取当前类型的所有剧集组
            groups = episode_groups_by_type.get(group_type, [])
            for group in groups:
                group_count = group.get("group_count", 0)
                episode_count = group.get("episode_count", 0)

                if (
                        group_count >= total_season
                        and episode_count >= begin_ep
                ):
                    logger.info(
                        f"{mediainfo.title_year} 正在匹配 剧集组: "
                        f"{group.get('name', '未知')}({group.get('id')}) "
                        f"共 {group_count} 季 {episode_count} 集")

                    if season_num := self.get_group_season(
                            group.get("id"), air_date, mediainfo
                    ):
                        mediainfo.episode_group = group.get("id")
                        mediainfo.season = season_num
                        return mediainfo
        return mediainfo

    def get_group_season(self, group_id: str, air_date: str, mediainfo: MediaInfo) -> int:
        """
        根据播出日期赋值剧集组季号
        :param group_id: 剧集组id
        :param air_date: 播出日期
        :param mediainfo: MediaInfo
        :return: 季号
        """
        if group_seasons := TmdbApi().get_tv_group_seasons(group_id):
            for group_season in group_seasons:
                if self.is_date_in_range(air_date, group_season.get("episodes")[0].get("air_date"))[0]:
                    logger.info(f"{mediainfo.title_year} 剧集组: {group_id} 第{group_season.get('order')}季 ")
                    return group_season.get("order")

    def prepare_add_args(self, meta: MetaBase, mediainfo: MediaInfo) -> Dict:
        """
        订阅参数
        """
        add_args = {
            "title": mediainfo.title,
            "year": mediainfo.year,
            "mtype": mediainfo.type,
            "tmdbid": mediainfo.tmdb_id,
            "season": mediainfo.season or 1,
            "bangumiid": mediainfo.bangumi_id,
            "exist_ok": True,
            "username": "Bangumi订阅",
            "save_path": self._save_path,
            "sites": (
                self._sites
                if self._is_v2
                else json.dumps(self._sites)
            ),
        }
        # 仅v2支持剧集组
        if self._is_v2:
            add_args["episode_group"] = mediainfo.episode_group

        if self._match_groups and mediainfo.episode_group:
            return add_args

        total_episode = len(mediainfo.seasons.get(mediainfo.season or 1) or [])
        if (
                meta.begin_season
                and mediainfo.season != meta.begin_season
                or total_episode != meta.total_episode
        ):
            meta = self.get_eps(meta, mediainfo.bangumi_id)
            total_ep: int = meta.end_episode if meta.end_episode else total_episode
            lock_eps: int = total_ep - meta.begin_episode + 1
            prev_eps: list = [i for i in range(1, meta.begin_episode)]
            add_args.update(
                {
                    "total_episode": total_ep,
                    "start_episode": meta.begin_episode,
                    "lack_episode": lock_eps,
                    "manual_total_episode": (
                        1 if meta.total_episode and self._total_change else 0
                    ),  # 手动修改过总集数
                    "note": (
                        prev_eps
                        if self._is_v2
                        else json.dumps(prev_eps)
                    ),
                }
            )
            logger.info(
                f"{mediainfo.title_year} 更新总集数为: {total_ep}，开始集数为: {meta.begin_episode}"
            )

        return add_args

    def get_best_season_number(self, air_date: str, season_info: list[dict]) -> int:
        """更新媒体季信息"""
        best_info = None
        min_days = float('inf')

        for info in season_info:
            result, days = self.is_date_in_range(air_date, info.get("air_date"))
            if result:
                best_info = info
                break
            elif 0 < days < min_days:
                min_days = days
                best_info = info

        if best_info:
            return best_info.get("season_number")

    def get_eps(self, meta: MetaBase, sub_id: int) -> MetaBase:
        """获取Bangumi条目的集数信息"""
        try:
            res = self.get_bgm_res(addr="getEpisodes", id=sub_id)
            data = res.json().get("data", [{}])[0]
            prev = data.get("sort", 0) - data.get("ep", 1)
            total = res.json().get("total", None)
            begin = prev + 1
            end = prev + total if total else None
            meta.set_episodes(begin, end)
        except Exception as e:
            logger.error(f"获取集数信息失败: {str(e)}")
        finally:
            return meta

    # 移除订阅
    def delete_subscribe(self, del_items: dict[int, int]):
        """删除订阅"""
        subscribeoper = SubscribeOper()
        for subscribe_id in del_items.keys():
            try:
                if subscribe := subscribeoper.get(subscribe_id):
                    subscribeoper.delete(subscribe_id)
                    SubscribeHelper().sub_done_async(
                        {"tmdbid": subscribe.tmdbid, "doubanid": subscribe.doubanid}
                    )
                    self.post_message(
                        mtype=NotificationType.Subscribe,
                        title=f"{subscribe.name}({subscribe.year}) 第{subscribe.season}季 已取消订阅",
                        text=(
                            f"原因: 已选Bangumi收藏类型中不存在\n"
                            f"订阅用户: {subscribe.username}\n"
                            f"创建时间: {subscribe.date}"),
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
    def is_date_in_range(air_date: str, reference_date: str = None, threshold_days: int = 8) -> tuple[bool, int]:
        """
        两个日期接近或在未来指定天数内, 并返回target_date - reference_date(或当前时间)的天数差

        :param air_date: 目标日期
        :param reference_date: 参考日期
        :param threshold_days: 阈值天数
        :return: bool, int

        只传入 target_date 时，判断是否在未来 threshold_days 天内
        传入 target_date 和 reference_date 时，判断两个日期是否接近
        """
        try:
            # 解析目标日期
            date1 = datetime.datetime.strptime(air_date, '%Y-%m-%d').date()

            # 单日期模式：是否在未来threshold_days内
            if reference_date is None:
                today = datetime.datetime.now().date()
                delta = (date1 - today).days
                return delta <= threshold_days, delta

            # 双日期模式：两个日期是否接近
            date2 = datetime.datetime.strptime(reference_date, '%Y-%m-%d').date()
            # 天数差
            delta = (date1 - date2).days
            return abs(delta) <= threshold_days, delta

        except (ValueError, TypeError) as e:
            logger.error(f"日期格式错误: {str(e)}")
            return False, 0

    def update_data(self, key, value):
        # 获取插件数据
        data = self.get_data(key=key) or []
        if value not in data:
            data.append(value)
            self.save_data(key=key, value=data)

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
