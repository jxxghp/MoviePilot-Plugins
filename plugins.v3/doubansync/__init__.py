import datetime
import re
from pathlib import Path
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.media import MediaChain
from app.db.oper.subscribe import SubscribeOper
from app.db.oper.user import UserOper
from app.schemas.types import MediaType, MediaSource, EventType, SystemConfigKey

from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.chain.subscribe import SubscribeChain
from app.sdk.config import settings
from app.sdk.events import Event
from app.sdk.events import eventmanager
from app.sdk.media import MetaInfo
from app.sdk.network import RssHelper
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.sdk.media import normalize_media_source, resolve_media_identity

lock = Lock()

# 豆瓣会把剧集的后续季建成独立条目（如「某剧 2」），而 TMDB 通常只在原剧下以季的形式
# 存在，因此豆瓣 → TMDB 的身份转换对这类条目必然失败。以下辅助函数只在转换失败后使用，
# 且必须同时满足「唯一精确同名原剧」「目标季存在且有集数」「该季首播年份与豆瓣年份一致」；
# 任一条件不满足就放弃，交回原有的豆瓣身份识别回退。
_SEQUEL_TITLE_PATTERN = re.compile(r"^(?P<base>.+?)\s*(?P<season>\d{1,2})$")
_SEQUEL_MIN_SEASON = 2
_SEQUEL_MAX_SEASON = 20
_TV_TYPE_VALUES = frozenset({"电视剧", "tv", "tv_series", "tvseries", "剧集"})


def _raw_value(value: Any) -> Any:
    """枚举取原始值，便于离线用例注入普通字符串。"""
    return getattr(value, "value", value)


def _compact_title(text: Any) -> str:
    """标题精确比较用：只保留字母数字并 casefold，不做任何模糊匹配。"""
    if not text:
        return ""
    return "".join(ch for ch in str(text).casefold() if ch.isalnum())


def _read_field(item: Any, key: str) -> Any:
    """同时兼容 dict 与 MediaInfo 对象读取字段。"""
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _is_tv_candidate(candidate: Any) -> bool:
    """只接受电视剧候选：类型未知一律拒绝；来源缺省按 TMDB 处理，显式来源必须是 TMDB。"""
    mtype = _raw_value(_read_field(candidate, "type"))
    if mtype is None or str(mtype).strip().lower() not in _TV_TYPE_VALUES:
        return False
    source = _raw_value(_read_field(candidate, "media_source"))
    if source is None:
        return True
    return str(source).strip().lower() == MediaSource.TMDB.value


def _candidate_names(candidate: Any) -> set:
    """候选的可用标题集合（含别名），统一归一化后比较。"""
    names = set()
    for key in ("title", "original_title", "original_name", "en_title"):
        normalized = _compact_title(_raw_value(_read_field(candidate, key)))
        if normalized:
            names.add(normalized)
    for alias in _read_field(candidate, "names") or []:
        normalized = _compact_title(_raw_value(alias))
        if normalized:
            names.add(normalized)
    return names


def _candidate_tmdb_id(candidate: Any) -> Optional[int]:
    """取候选的 TMDB ID；媒体 ID 缺失时退回辅助 TMDB 标识字段。"""
    for key in ("media_id", "tmdb_id", "id"):
        value = _raw_value(_read_field(candidate, key))
        if value in (None, ""):
            continue
        try:
            parsed = int(value)
            return parsed if parsed > 0 and not isinstance(value, bool) else None
        except (TypeError, ValueError):
            return None
    return None


def parse_sequel_title(title: Any, begin_season: Any = None,
                       base_title: Any = None) -> Optional[Tuple[str, int]]:
    """从豆瓣标题推导「原剧标题 + 季号」，无法安全推导时返回 None。

    标题已解析出季号时原剧标题取 meta.name（已去掉季标记）；否则只认标题尾部的裸数字。
    季号必须落在 2..20，原剧标题至少 3 个字符、不以数字结尾且含字母——标题里的其他数字
    一律不剥离，也不做模糊匹配。

    :param title: 豆瓣条目原始标题
    :param begin_season: 元数据解析出的季号
    :param base_title: 元数据解析出的原剧标题
    :return: ``(原剧标题, 季号)``；无法安全推导时返回 None
    """
    if begin_season is not None:
        try:
            season = int(begin_season)
        except (TypeError, ValueError):
            return None
        base = str(base_title or title or "").strip()
    else:
        matched = _SEQUEL_TITLE_PATTERN.match(str(title or "").strip())
        if not matched:
            return None
        season = int(matched.group("season"))
        base = matched.group("base").strip()
    if not (_SEQUEL_MIN_SEASON <= season <= _SEQUEL_MAX_SEASON):
        return None
    if len(base) < 3 or base[-1].isdigit() or not any(ch.isalpha() for ch in base):
        return None
    return base, season


def find_unique_exact_tv(candidates: Any, base: Any) -> Optional[int]:
    """唯一精确同名电视剧的 TMDB ID；无候选或多条同名都返回 None（fail closed）。

    :param candidates: TMDB 搜索候选（MediaInfo 或 dict）
    :param base: 原剧标题
    :return: 唯一候选的 TMDB ID；无法确认唯一性时返回 None
    """
    normalized = _compact_title(base)
    if not normalized:
        return None
    ids = set()
    for candidate in candidates or []:
        if not _is_tv_candidate(candidate):
            continue
        if normalized not in _candidate_names(candidate):
            continue
        candidate_id = _candidate_tmdb_id(candidate)
        if candidate_id is None:
            return None
        ids.add(candidate_id)
    return ids.pop() if len(ids) == 1 else None


def verify_sequel_season(season_info: Any, season: int,
                         year: Any) -> Optional[Dict[str, Any]]:
    """校验目标季存在、有集数且首播年份与豆瓣年份一致。

    :param season_info: ``tmdb_info(season=...)`` 返回的季详情
    :param season: 目标季号
    :param year: 豆瓣条目年份
    :return: 校验通过的季字段；任一条件不满足时返回 None
    """
    try:
        target_season = int(season)
        target_year = str(int(str(year).strip()))
    except (TypeError, ValueError):
        return None
    if not season_info:
        return None
    payload = {key: _read_field(season_info, key)
               for key in ("season_number", "air_date", "episode_count")}
    season_number = payload.get("season_number")
    if season_number not in (None, ""):
        try:
            if int(season_number) != target_season:
                return None
        except (TypeError, ValueError):
            return None
    try:
        episode_count = int(payload.get("episode_count") or 0)
    except (TypeError, ValueError):
        episode_count = 0
    if episode_count <= 0 and not (_read_field(season_info, "episodes") or []):
        return None
    if str(payload.get("air_date") or "")[:4] != target_year:
        return None
    payload["season_number"] = target_season
    return payload



class DoubanSync(_PluginBase):
    # 插件名称
    """同步豆瓣想看记录，按统一媒体身份搜索下载或添加订阅。"""
    plugin_name = "豆瓣想看"
    # 插件描述
    plugin_desc = "同步豆瓣想看数据，自动添加订阅。"
    # 插件图标
    plugin_icon = "douban.png"
    # 插件版本
    plugin_version = "3.1.3"
    # 插件作者
    plugin_author = "jxxghp,dwhmofly"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "doubansync_"
    # 加载顺序
    plugin_order = 3
    # 可使用的用户级别
    auth_level = 2

    # 私有变量
    _interests_url: str = "https://www.douban.com/feed/people/%s/interests"
    _scheduler: Optional[BackgroundScheduler] = None
    _cache_path: Optional[Path] = None

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _notify: bool = False
    _days: int = 7
    _users: str = ""
    _clear: bool = False
    _clearflag: bool = False
    _search_download = False

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        """停止旧任务并读取配置，按启用状态安排本实例任务。"""
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._days = config.get("days")
            self._users = config.get("users")
            self._onlyonce = config.get("onlyonce")
            self._clear = config.get("clear")
            self._search_download = config.get("search_download")

        self.__migrate_history_identity()

        if self._enabled or self._onlyonce:
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"豆瓣想看服务启动，立即运行一次")
                self._scheduler.add_job(func=self.sync, trigger='date',
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
                # 记录缓存清理标志
                self._clearflag = self._clear
                # 关闭清理缓存
                self._clear = False
                # 保存配置
                self.__update_config()

    def get_state(self) -> bool:
        """返回插件启用状态，供宿主决定是否注册服务。"""
        return self._enabled

    def __migrate_history_identity(self) -> None:
        """将旧想看历史的分散媒体 ID 原地迁移为统一媒体身份。"""
        history = self.get_data("history")
        if not isinstance(history, list):
            return
        changed = False
        for item in history:
            if not isinstance(item, dict):
                continue
            media_source, media_id = resolve_media_identity(
                media_source=item.get("media_source"),
                media_id=item.get("media_id"),
            )
            if not media_source:
                for legacy_source, legacy_key in (
                    (MediaSource.Douban, "doubanid"),
                    (MediaSource.TMDB, "tmdbid"),
                ):
                    media_source, media_id = resolve_media_identity(
                        media_source=legacy_source,
                        media_id=item.get(legacy_key),
                    )
                    if media_source:
                        break
            if not media_source:
                continue
            migrated = {
                key: value for key, value in item.items()
                if key not in {"tmdbid", "doubanid"}
            }
            migrated["media_source"] = media_source.value
            migrated["media_id"] = media_id
            if migrated != item:
                item.clear()
                item.update(migrated)
                changed = True
        if changed:
            self.save_data("history", history)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/douban_sync",
            "event": EventType.PluginAction,
            "desc": "同步豆瓣想看",
            "category": "订阅",
            "data": {
                "action": "douban_sync"
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
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除豆瓣同步历史记录"
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
            return [
                {
                    "id": "DoubanSync",
                    "name": "豆瓣想看同步服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.sync,
                    "kwargs": {}
                }
            ]
        elif self._enabled:
            return [
                {
                    "id": "DoubanSync",
                    "name": "豆瓣想看同步服务",
                    "trigger": "interval",
                    "func": self.sync,
                    "kwargs": {"minutes": 30}
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'days',
                                            'label': '同步天数'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'users',
                                            'label': '用户列表',
                                            'placeholder': '豆瓣用户ID，多个用英文逗号分隔'
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
                                            'model': 'clear',
                                            'label': '清理历史记录',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                    'style': 'display:flex;align-items: center;'
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'search_download',
                                            'label': '搜索下载',
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
                                            'text': '搜索下载开启后，会优先按订阅优先级规则组搜索过滤下载，搜索站点为设置的订'
                                                    '阅站点，下载失败/无资源/剧集不完整时仍会添加订阅'
                                        }
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
            "cron": "*/30 * * * *",
            "days": 7,
            "users": "",
            "clear": False,
            "search_download": False
        }

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
            media_id = history.get("media_id")
            action = "下载" if history.get("action") == "download" else "订阅" if history.get("action") == "subscribe" \
                else "存在" if history.get("action") == "exist" else history.get("action")
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
                                    'api': 'plugin/DoubanSync/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'media_source': MediaSource.Douban.value,
                                        'media_id': media_id,
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
                                                'class': 'ps-1 pe-5 break-words whitespace-break-spaces'
                                            },
                                            'content': [
                                                {
                                                    'component': 'a',
                                                    'props': {
                                                        'href': f"https://movie.douban.com/subject/{media_id}",
                                                        'target': '_blank'
                                                    },
                                                    'text': title
                                                }
                                            ]
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
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'操作：{action}'
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

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "days": self._days,
            "users": self._users,
            "clear": self._clear,
            "search_download": self._search_download
        })

    def delete_history(self, media_source: MediaSource, media_id: str, apikey: str):
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
        historys = [
            h for h in historys
            if not (
                normalize_media_source(h.get("media_source")) == media_source
                and str(h.get("media_id")) == str(media_id)
            )
        ]
        self.save_data('history', historys)
        return schemas.Response(success=True, message="删除成功")

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

    @staticmethod
    def __get_username_by_douban(user_id: str) -> Optional[str]:
        """
        根据豆瓣ID获取用户名
        """
        try:
            return UserOper().get_name(douban_userid=user_id)
        except Exception as err:
            logger.warn(f'根据豆瓣 ID 查询用户失败：{err}')
        return None

    @staticmethod
    def __resolve_sequel_identity(chain, title: Any, year: Any, mtype: Any,
                                  begin_season: Any = None,
                                  base_title: Any = None) -> Optional[Dict[str, Any]]:
        """豆瓣续集条目 → 原剧第 N 季的安全回退（仅在身份转换失败后调用）。

        只有「唯一精确同名原剧」「目标季存在且有集数」「该季首播年份与豆瓣年份一致」
        同时成立时才返回结果；任何异常都只记日志并返回 None，由调用方继续原有的
        豆瓣身份识别回退，不影响同一轮次的其它条目。

        :param chain: 插件使用的媒体链
        :param title: 豆瓣条目标题
        :param year: 豆瓣条目年份
        :param mtype: 媒体类型
        :param begin_season: 元数据解析出的季号
        :param base_title: 元数据解析出的原剧标题
        :return: ``{"id", "season", "air_date", "episode_count"}``；无法安全命中时返回 None
        """
        try:
            if str(_raw_value(mtype)).strip().lower() not in _TV_TYPE_VALUES:
                return None
            year_text = str(year).strip() if year is not None else ""
            if len(year_text) != 4 or not year_text.isdigit():
                return None
            target = parse_sequel_title(title, begin_season=begin_season,
                                        base_title=base_title)
            if not target:
                return None
            base, season = target
            # 不做年份过滤：原剧首播年份属于第 1 季，年份由目标季的首播日期校验。
            search_meta = MetaInfo(title=base)
            search_meta.type = MediaType.TV
            candidates = chain.search_medias(meta=search_meta,
                                             media_source=MediaSource.TMDB)
            tmdb_id = find_unique_exact_tv(candidates, base)
            if not tmdb_id:
                logger.info(f'续集回退未命中：{base} 在 TMDB 无唯一精确同名电视剧')
                return None
            season_info = chain.tmdb_info(tmdbid=tmdb_id, mtype=MediaType.TV,
                                         season=season)
            payload = verify_sequel_season(season_info, season, year_text)
            if not payload:
                logger.info(f'续集回退未命中：TMDB {tmdb_id} 第 {season} 季不存在'
                            f'或首播年份不是 {year_text}')
                return None
            return {"id": tmdb_id, "season": season,
                    "air_date": payload.get("air_date"),
                    "episode_count": payload.get("episode_count")}
        except Exception as err:
            logger.warn(f'续集回退异常，按未命中处理：{err}')
            return None

    def sync(self):
        """
        通过用户RSS同步豆瓣想看数据
        """
        if not self._users:
            return
        # 读取历史记录
        if self._clearflag:
            history = []
        else:
            history: List[dict] = self.get_data('history') or []
        for user_id in self._users.split(","):
            # 同步每个用户的豆瓣数据
            if not user_id:
                continue
            logger.info(f"开始同步用户 {user_id} 的豆瓣想看数据 ...")
            url = self._interests_url % user_id
            results = RssHelper().parse(url, headers={
                "User-Agent": settings.USER_AGENT
            })
            if not results:
                logger.warn(f"未获取到用户 {user_id} 豆瓣RSS数据：{url}")
                continue
            else:
                logger.info(f"获取到用户 {user_id} 豆瓣RSS数据：{len(results)}")
            # 解析数据
            mediachain = MediaChain()
            downloadchain = DownloadChain()
            subscribechain = SubscribeChain()
            searchchain = SearchChain()
            subscribeoper = SubscribeOper()
            for result in results:
                try:
                    dtype = result.get("title", "")[:2]
                    title = result.get("title", "")[2:]
                    # 增加豆瓣昵称，数据来源自app.helper.rss.py
                    nickname = result.get("nickname", "")
                    if nickname:
                        nickname = f"[{nickname}]"
                    if dtype not in ["想看"]:
                        logger.info(f'标题：{title}，非想看数据，跳过')
                        continue
                    if not result.get("link"):
                        logger.warn(f'标题：{title}，未获取到链接，跳过')
                        continue
                    # 判断是否在天数范围
                    pubdate: Optional[datetime.datetime] = result.get("pubdate")
                    if pubdate:
                        if (datetime.datetime.now(datetime.timezone.utc) - pubdate).days > float(self._days):
                            logger.info(f'已超过同步天数，标题：{title}，发布时间：{pubdate}')
                            continue
                    douban_id = result.get("link", "").split("/")[-2]
                    # 检查是否处理过
                    if not douban_id or any(
                            normalize_media_source(h.get("media_source")) == MediaSource.Douban
                            and str(h.get("media_id")) == str(douban_id)
                            for h in history
                    ):
                        logger.info(f'标题：{title}，豆瓣ID：{douban_id} 已处理过')
                        continue
                    # 识别媒体信息
                    meta = MetaInfo(title=title)
                    douban_info = self.chain.douban_info(doubanid=douban_id)
                    meta.type = MediaType.MOVIE if douban_info.get("type") == "movie" else MediaType.TV
                    if settings.RECOGNIZE_SOURCE == "themoviedb":
                        tmdbinfo = mediachain.convert_media_identity(
                            target_source=MediaSource.TMDB,
                            media_source=MediaSource.Douban,
                            media_id=douban_id,
                            mtype=meta.type,
                        )
                        if not tmdbinfo:
                            # 豆瓣续集条目在 TMDB 只是原剧的某一季，身份转换必然失败；
                            # 仅在此时尝试安全回退，未命中则保持原有的豆瓣数据识别回退。
                            sequel = self.__resolve_sequel_identity(
                                self.chain, title, douban_info.get("year"), meta.type,
                                begin_season=meta.begin_season, base_title=meta.name)
                            if sequel:
                                meta.begin_season = sequel["season"]
                                tmdbinfo = {"id": sequel["id"]}
                                logger.info(
                                    f"续集回退命中：豆瓣 {douban_id} {title} → "
                                    f"TMDB {sequel['id']} S{sequel['season']}"
                                    f"（{sequel.get('air_date') or '-'}，"
                                    f"{sequel.get('episode_count') or '-'} 集）")
                        if tmdbinfo:
                            mediainfo = self.chain.recognize_media(
                                meta=meta,
                                media_source=MediaSource.TMDB,
                                media_id=str(tmdbinfo.get("id")),
                            )
                            if not mediainfo:
                                logger.warn(f'TMDBID {tmdbinfo.get("id")} 未识别到媒体信息')
                                continue
                        else:
                            logger.warn(f'未能通过豆瓣ID {douban_id} 获取到TMDB信息，标题：{title}，尝试使用豆瓣数据识别')
                            mediainfo = self.chain.recognize_media(
                                meta=meta,
                                media_source=MediaSource.Douban,
                                media_id=str(douban_id),
                            )
                            if not mediainfo:
                                logger.warn(f'豆瓣ID {douban_id} 未识别到媒体信息')
                                continue
                    else:
                        mediainfo = self.chain.recognize_media(
                            meta=meta,
                            media_source=MediaSource.Douban,
                            media_id=str(douban_id),
                        )
                        if not mediainfo:
                            logger.warn(f'豆瓣ID {douban_id} 未识别到媒体信息')
                            continue
                    # 查询缺失的媒体信息
                    exist_flag, no_exists = downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
                    if exist_flag:
                        logger.info(f'{mediainfo.title_year} 媒体库中已存在')
                        action = "exist"
                    else:
                        # 用户转换
                        real_name = self.__get_username_by_douban(user_id)
                        if self._search_download:
                            # 先搜索资源
                            logger.info(
                                f'媒体库中不存在或不完整，开启搜索下载，开始搜索 {mediainfo.title_year} 的资源...')
                            # 按订阅优先级规则组搜索过滤，站点为设置的订阅站点
                            filter_results = searchchain.process(
                                mediainfo=mediainfo,
                                no_exists=no_exists,
                                sites=self.systemconfig.get(SystemConfigKey.RssSites),
                                rule_groups=self.systemconfig.get(SystemConfigKey.SubscribeFilterRuleGroups)
                            )
                            if filter_results:
                                logger.info(f'找到符合条件的资源，开始下载 {mediainfo.title_year} ...')
                                action = "download"
                                if mediainfo.type == MediaType.MOVIE:
                                    # 电影类型调用单次下载
                                    download_id = downloadchain.download_single(
                                        context=filter_results[0],
                                        username=real_name or f"豆瓣{nickname}想看"
                                    )
                                    if not download_id:
                                        logger.info(f'下载失败，添加订阅 {mediainfo.title_year} ...')
                                        self.add_subscribe(mediainfo, meta, nickname, real_name)
                                        action = "subscribe"
                                else:
                                    # 电视剧类型调用批量下载
                                    downloaded_list, no_exists = downloadchain.batch_download(
                                        contexts=filter_results,
                                        no_exists=no_exists,
                                        username=real_name or f"豆瓣{nickname}想看"
                                    )
                                    if no_exists:
                                        logger.info(f'下载失败或未下载完所有剧集，添加订阅 {mediainfo.title_year} ...')
                                        sub_id, message = self.add_subscribe(mediainfo, meta, nickname, real_name)
                                        action = "subscribe"

                                        # 更新订阅信息
                                        logger.info(f'根据缺失剧集更新订阅信息 {mediainfo.title_year} ...')
                                        subscribe = subscribeoper.get(sub_id)
                                        if subscribe:
                                            subscribechain.finish_subscribe_or_not(subscribe=subscribe,
                                                                                   meta=meta,
                                                                                   mediainfo=mediainfo,
                                                                                   downloads=downloaded_list,
                                                                                   lefts=no_exists)

                            else:
                                logger.info(f'未找到符合条件资源，添加订阅 {mediainfo.title_year} ...')
                                self.add_subscribe(mediainfo, meta, nickname, real_name)
                                action = "subscribe"
                        else:
                            logger.info(f'媒体库中不存在或不完整，未开启搜索下载，添加订阅 {mediainfo.title_year} ...')
                            self.add_subscribe(mediainfo, meta, nickname, real_name)
                            action = "subscribe"
                    # 存储历史记录
                    history.append({
                        "action": action,
                        "title": title,
                        "type": mediainfo.type.value,
                        "year": mediainfo.year,
                        "poster": mediainfo.get_poster_image(),
                        "overview": mediainfo.overview,
                        "media_source": MediaSource.Douban.value,
                        "media_id": str(douban_id),
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as err:
                    logger.error(f'同步用户 {user_id} 豆瓣想看数据出错：{str(err)}')
            logger.info(f"用户 {user_id} 豆瓣想看同步完成")
        # 保存历史记录
        self.save_data('history', history)
        # 缓存只清理一次
        self._clearflag = False

    @staticmethod
    def add_subscribe(mediainfo, meta, nickname, real_name):
        """把已识别作品及指定季加入订阅，保留发起用户。"""
        return SubscribeChain().add(
            title=mediainfo.title,
            year=mediainfo.year,
            mtype=mediainfo.type,
            media_source=mediainfo.media_source,
            media_id=mediainfo.media_id,
            season=meta.begin_season,
            exist_ok=True,
            username=real_name or f"豆瓣{nickname}想看"
        )

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        """
        豆瓣想看同步
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "douban_sync":
                return

            logger.info("收到命令，开始执行豆瓣想看同步 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始同步豆瓣想看 ...",
                              userid=event.event_data.get("user"))
        self.sync()

        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="同步豆瓣想看数据完成！", userid=event.event_data.get("user"))
