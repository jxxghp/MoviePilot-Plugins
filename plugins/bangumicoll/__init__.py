# 基础库
import datetime
import json
from typing import Any, Dict, List, Optional, Type

# 第三方库
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from sqlalchemy import JSON
from sqlalchemy.orm import Session

# 项目库
from app.chain.subscribe import SubscribeChain, Subscribe
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
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class BangumiColl(_PluginBase):
    # 插件名称
    plugin_name = "Bangumi收藏订阅"
    # 插件描述
    plugin_desc = "将Bangumi用户收藏添加到订阅"
    # 插件图标
    plugin_icon = "bangumi_b.png"
    # 插件版本
    plugin_version = "1.5.3"
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
    siteoper: SiteOper = None
    subscribehelper: SubscribeHelper = None
    subscribeoper: SubscribeOper = None

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

    def init_plugin(self, config: dict = None):
        self.subscribechain = SubscribeChain()
        self.siteoper = SiteOper()
        self.subscribehelper = SubscribeHelper()
        self.subscribeoper = SubscribeOper()

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
            ):
                setattr(self, f"_{key}", config.get(key, getattr(self, f"_{key}")))
            # 获得所有站点
            site_ids = {site.id for site in self.siteoper.list_order_by_pri()}
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
            run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ))
            + datetime.timedelta(seconds=3),
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
            }
        )

    def get_form(self):
        from .page_components import form

        # 列出所有站点
        sites_options = [
            {"title": site.name, "value": site.id}
            for site in self.siteoper.list_order_by_pri()
        ]
        return form(sites_options)

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
        pass

    def get_page(self):
        pass

    def get_state(self):
        return self._enabled

    def bangumi_coll(self):
        """订阅Bangumi用户收藏"""
        if not self._uid:
            logger.error("请设置UID")
            return

        try:
            res = self.get_bgm_res(addr="UserCollections", id=self._uid)
            items = self.parse_collection_items(res)

            # 新增和移除条目
            self.manage_subscriptions(items)
        except Exception as e:
            logger.error(f"执行失败: {str(e)}")

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
            }
            for item in data
            if item.get("type") in self._collection_type
        }

    def manage_subscriptions(self, items: Dict[int, Dict[str, Any]]):
        """管理订阅的新增和删除"""
        db_sub = {
            i.bangumiid: i.id
            for i in self.subscribechain.subscribeoper.list()
            if i.bangumiid
        }
        db_hist = self.get_subscribe_history()
        new_sub = items.keys() - db_sub.keys() - db_hist
        del_sub = db_sub.keys() - items.keys()

        logger.debug(f"待新增条目：{new_sub}")
        logger.debug(f"待移除条目：{del_sub}")

        if del_sub and self._notify:
            del_items = {db_sub[i]: i for i in del_sub}
            logger.info("开始移除订阅...")
            self.delete_subscribe(del_items)
            logger.info("移除完成")

        if new_sub:
            logger.info("开始添加订阅...")
            msg = self.add_subscribe({i: items[i] for i in new_sub})
            logger.info("添加完成")
            if msg:
                logger.info("\n".ljust(49, ' ').join(list(msg.values())))

    # 添加订阅
    def add_subscribe(self, items: Dict[int, Dict[str, Any]]) -> Dict:
        """添加订阅"""

        fail_items = {}
        for self._subid, item in items.items():
            if item.get("name_cn"):
                meta = MetaInfo(item.get("name_cn"))
                meta.en_name = item.get("name")
            else:
                meta = MetaInfo(item.get("name"))
            if not meta.name:
                fail_items[self._subid] = f"{self._subid} 未识别到有效数据"
                logger.warn(f"{self._subid} 未识别到有效数据")
                continue

            meta.year = item.get("date")[:4] if item.get("date") else None
            mediainfo = self.chain.recognize_media(meta=meta, cache=False)
            meta.total_episode = item.get("eps", 0)
            if not mediainfo:
                fail_items[self._subid] = f"{item.get('name_cn')} 媒体信息识别失败"
                continue

            self.update_media_info(item, mediainfo)

            sid = self.subscribeoper.list_by_tmdbid(
                mediainfo.tmdb_id, mediainfo.number_of_seasons
            )
            if sid:
                logger.info(f"{mediainfo.title_year} 正在订阅中")
                if len(sid) == 1:
                    self.subscribeoper.update(
                        sid=sid[0].id, payload={"bangumiid": self._subid}
                    )
                    logger.info(f"{mediainfo.title_year} Bangumi条目id更新成功")
                continue

            sid, msg = self.subscribechain.add(
                title=mediainfo.title,
                year=mediainfo.year,
                season=mediainfo.number_of_seasons,
                bangumiid=self._subid,
                exist_ok=True,
                username="Bangumi订阅",
                **self.prepare_kwargs(meta, mediainfo),
            )
            if not sid:
                fail_items[self._subid] = f"{item.get('name_cn') or item.get('name')} {msg}"

        return fail_items

    def prepare_kwargs(self, meta: MetaBase, mediainfo: MediaInfo) -> Dict:
        """准备额外参数"""
        kwargs = {
            "save_path": self._save_path,
            "sites": (
                self._sites
                if self.are_types_equal(attribute_name='sites')
                else json.dumps(self._sites)
            ),
        }

        total_episode = len(mediainfo.seasons.get(mediainfo.number_of_seasons) or [])
        if (
            meta.begin_season
            and mediainfo.number_of_seasons != meta.begin_season
            or total_episode != meta.total_episode
        ):
            meta = self.get_eps(meta)
            total_ep: int = meta.end_episode if meta.end_episode else total_episode
            lock_eps: int = total_ep - meta.begin_episode + 1
            prev_eps: list = [i for i in range(1, meta.begin_episode)]
            kwargs.update(
                {
                    "total_episode": total_ep,
                    "start_episode": meta.begin_episode,
                    "lack_episode": lock_eps,
                    "manual_total_episode": (
                        1 if meta.total_episode and self._total_change else 0
                    ),  # 手动修改过总集数
                    "note": (
                        prev_eps
                        if self.are_types_equal("note")
                        else json.dumps(prev_eps)
                    ),
                }
            )
            logger.info(
                f"{mediainfo.title_year} 更新总集数为: {total_ep}，开始集数为: {meta.begin_episode}"
            )

        return kwargs

    def update_media_info(self, item: dict, mediainfo: MediaInfo):
        """更新媒体信息"""
        for info in mediainfo.season_info:
            if self.are_dates(item.get("date"), info.get("air_date")):
                mediainfo.number_of_seasons = info.get("season_number")
                mediainfo.number_of_episodes = info.get("episode_count")
                break

    def get_eps(self, meta: MetaBase) -> MetaBase:
        """获取Bangumi条目的集数信息"""
        try:
            res = self.get_bgm_res(addr="getEpisodes", id=self._subid)
            data = res.json().get("data", [{}])[0]
            prev = data.get("sort", 1) - data.get("ep", 1)
            total = res.json().get("total", None)
            begin = prev + 1
            end = prev + total if total else None
            meta.set_episodes(begin, end)
        except Exception as e:
            logger.error(f"获取集数信息失败: {str(e)}")
        finally:
            return meta

    # 移除订阅
    def delete_subscribe(self, del_items: Dict[int, int]):
        """删除订阅"""
        for subscribe_id in del_items.keys():
            try:
                subscribe = self.subscribeoper.get(subscribe_id)
                if subscribe:
                    self.subscribeoper.delete(subscribe_id)
                    self.subscribehelper.sub_done_async(
                        {"tmdbid": subscribe.tmdbid, "doubanid": subscribe.doubanid}
                    )
                    self.post_message(
                        mtype=NotificationType.Subscribe,
                        title=f"{subscribe.name}({subscribe.year}) 第{subscribe.season}季 已取消订阅",
                        text=f"原因: 未在Bangumi收藏中找到该条目\n订阅用户: {subscribe.username}\n创建时间: {subscribe.date}",
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
    def are_dates(date_str1, date_str2, threshold_days: int = 7) -> bool:
        """对比两个日期字符串是否接近"""
        date1 = datetime.datetime.strptime(date_str1, '%Y-%m-%d')
        date2 = datetime.datetime.strptime(date_str2, '%Y-%m-%d')
        return abs((date1 - date2).days) <= threshold_days

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

    @staticmethod
    def are_types_equal(
        attribute_name: str, expected_type: Type[Any] = JSON(), class_=Subscribe
    ) -> bool:
        """比较类中属性的类型与expected_type是否一致"""
        column = class_.__table__.columns.get(attribute_name)
        if column is None:
            raise AttributeError(
                f"Class: {class_.__name__} 没有属性: '{attribute_name}'"
            )
        return isinstance(column.type, type(expected_type))
