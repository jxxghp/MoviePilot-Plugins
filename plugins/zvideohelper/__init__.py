from datetime import datetime, timedelta
import sqlite3
import json
from app.plugins.zvideohelper.DoubanHelper import *
from enum import Enum

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.schemas.types import EventType, NotificationType
from app.core.event import eventmanager, Event
from pathlib import Path

from app.core.config import settings
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
import time

# 豆瓣状态
class DoubanStatus(Enum):
    WATCHING = "do"
    DONE = "collect"


class ZvideoHelper(_PluginBase):
    # 插件名称
    plugin_name = "极影视助手"
    # 插件描述
    plugin_desc = "极影视功能扩展"
    # 插件图标
    plugin_icon = "zvideo.png"
    # 插件版本
    plugin_version = "1.6"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "zvideohelper"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _cron = None
    _notify = False
    _onlyonce = False
    _sync_douban_status = False
    _clean_cache = False
    _use_douban_score = False
    _douban_helper = None
    _cached_data: dict = {}
    _db_path = ""
    _cookie = ""
    _douban_score_update_days = 0
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._db_path = config.get("db_path")
            self._cookie = config.get("cookie")
            self._sync_douban_status = config.get("sync_douban_status")
            self._clean_cache = config.get("clean_cache")
            self._use_douban_score = config.get("use_douban_score")
            self._douban_score_update_days = int(config.get("douban_score_update_days"))
            self._douban_helper = DoubanHelper(user_cookie=self._cookie)

        # 获取历史数据
        self._cached_data = (
            self.get_data("zvideohelper")
            if self.get_data("zvideohelper") != None
            else dict()
        )
        # 加载模块
        if self._onlyonce:
            if self._clean_cache:
                self._cached_data = {}
                self.save_data("zvideohelper", self._cached_data)
                self._clean_cache = False
            # 检查数据库路径是否存在
            path = Path(self._db_path)
            if not path.exists():
                logger.error(f"极影视数据库路径不存在: {self._db_path}")
                self._onlyonce = False
                self._clean_cache = False
                self._update_config()
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=f"【极影视助手】",
                        text=f"极影视数据库路径不存在: {self._db_path}",
                    )
                return

            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"极影视助手服务启动，立即运行一次")
            self._scheduler.add_job(
                func=self.do_job,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                + timedelta(seconds=3),
                name="极影视助手",
            )
            # 关闭一次性开关
            self._onlyonce = False
            self._update_config()

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def _update_config(self):
        self.update_config(
            {
                "onlyonce": False,
                "cron": self._cron,
                "enabled": self._enabled,
                "notify": self._notify,
                "db_path": self._db_path,
                "cookie": self._cookie,
                "sync_douban_status": self._sync_douban_status,
                "clean_cache": self._clean_cache,
                "use_douban_score": self._use_douban_score,
                "douban_score_update_days": self._douban_score_update_days,
            }
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/sync_zvideo_to_douban",
                "event": EventType.PluginAction,
                "desc": "同步极影视观影状态",
                "category": "",
                "data": {"action": "sync_zvideo_to_douban"},
            },
            {
                "cmd": "/use_douban_score",
                "event": EventType.PluginAction,
                "desc": "极影视使用豆瓣评分",
                "category": "",
                "data": {"action": "use_douban_score"},
            },
            {
                "cmd": "/use_tmdb_score",
                "event": EventType.PluginAction,
                "desc": "极影视使用tmdb评分",
                "category": "",
                "data": {"action": "use_tmdb_score"},
            },
        ]

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        if event:
            event_data = event.event_data
            if event_data:
                if (
                    event_data.get("action") == "sync_zvideo_to_douban"
                    or event_data.get("action") == "use_douban_score"
                    or event_data.get("action") == "use_tmdb_score"
                ):
                    if event_data.get("action") == "sync_zvideo_to_douban":
                        logger.info("收到命令，开始同步极影视观影状态 ...")
                        self.post_message(
                            channel=event.event_data.get("channel"),
                            title="开始同步极影视观影状态 ...",
                            userid=event.event_data.get("user"),
                        )
                        self.sync_douban_status()
                        if event:
                            self.post_message(
                                channel=event.event_data.get("channel"),
                                title="同步极影视观影状态完成！",
                                userid=event.event_data.get("user"),
                            )
                    elif event_data.get("action") == "use_douban_score":
                        logger.info("收到命令，开始使用豆瓣评分 ...")
                        self.post_message(
                            channel=event.event_data.get("channel"),
                            title="开始使用豆瓣评分 ...",
                            userid=event.event_data.get("user"),
                        )
                        self.use_douban_score()
                        if event:
                            self.post_message(
                                channel=event.event_data.get("channel"),
                                title="使用豆瓣评分完成！",
                                userid=event.event_data.get("user"),
                            )
                    elif event_data.get("action") == "use_tmdb_score":
                        logger.info("收到命令，开始使用tmdb评分 ...")
                        self.post_message(
                            channel=event.event_data.get("channel"),
                            title="开始使用tmdb评分 ...",
                            userid=event.event_data.get("user"),
                        )
                        self.use_tmdb_score()
                        if event:
                            self.post_message(
                                channel=event.event_data.get("channel"),
                                title="使用tmdb评分完成！",
                                userid=event.event_data.get("user"),
                            )

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
        if self._enabled and self._cron:
            return [
                {
                    "id": "ZvideoHelper",
                    "name": "极影视助手",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.do_job,
                    "kwargs": {},
                }
            ]

    def do_job(self):
        if self._sync_douban_status:
            self.sync_douban_status()

        if self._use_douban_score:
            self.use_douban_score()
        else:
            self.use_tmdb_score()

    def set_douban_watching(self):
        watching_douban_id = []
        try:
            # 连接到SQLite数据库
            conn = sqlite3.connect(self._db_path)

            # 创建一个游标对象
            cursor = conn.cursor()

            # 查询表格zvideo_playlist中的collection_id列
            cursor.execute("SELECT collection_id FROM zvideo_playlist")
            collection_ids = cursor.fetchall()

            # 去重collection_id
            collection_ids = set([collection_id[0] for collection_id in collection_ids])

            # 创建一个列表来保存符合条件的meta_info列的JSON对象
            meta_info_list = []

            # 查询zvideo_collection表中对应的行并筛选type == 200的记录，只有电视剧才有在看状态
            for collection_id in collection_ids:
                cursor.execute(
                    "SELECT meta_info FROM zvideo_collection WHERE collection_id = ? AND type = 200",
                    (collection_id,),
                )
                rows = cursor.fetchall()

                # 将meta_info列的信息转换为JSON对象并保存到列表中
                for row in rows:
                    try:
                        meta_info_json = json.loads(row[0])
                        meta_info_list.append(meta_info_json)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"An error occurred while decoding JSON for collection_id {collection_id}: {e}"
                        )

            for meta_info in meta_info_list:
                try:
                    douban_id = meta_info["relation"]["douban"]["douban_id"]
                    title = meta_info["title"]
                except Exception as e:
                    logger.error(f"meta_info: {meta_info}，解析失败: {e}")
                    continue
                if self._cached_data.get(title) != None:
                    logger.info(f"已处理过: {title}，跳过...")
                    continue
                if douban_id == 0:
                    _, douban_id, _ = self.get_douban_info_by_name(title)
                if douban_id != None:
                    watching_douban_id.append((title, douban_id))
                else:
                    logger.error(f"未找到豆瓣ID: {title}")

        except sqlite3.Error as e:
            logger.error(f"An error occurred: {e}")

        finally:
            # 确保游标和连接在使用完后关闭
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            message = ""
            for item in watching_douban_id:
                status = DoubanStatus.WATCHING.value
                ret = self._douban_helper.set_watching_status(
                    subject_id=item[1], status=status, private=True
                )
                if ret:
                    self._cached_data[item[0]] = status
                    logger.info(f"title: {item[0]}, douban_id: {item[1]}，已标记为在看")
                    message += f"{item[0]}，已标记为在看\n"
                else:
                    logger.error(
                        f"title: {item[0]}, douban_id: {item[1]}，标记在看失败"
                    )
                    message += f"{item[0]}，***标记在看失败***\n"
            if self._notify and len(message) > 0:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="【极影视助手】",
                    text=message,
                )

    def set_douban_done(self):
        watching_douban_id = []
        try:
            # 连接到SQLite数据库
            conn = sqlite3.connect(self._db_path)

            # 创建一个游标对象
            cursor = conn.cursor()

            # 通过表格`zvideo_collecion_tags`的`tag_name==是否看过`找到对应的`collcetion_id`，在到`zvideo_collection`中查找将其标记为已看
            cursor.execute(
                "SELECT collection_id FROM zvideo_collection_tags WHERE tag_name='是否看过'"
            )
            collection_ids = cursor.fetchall()

            # 去重collection_id
            collection_ids = set([collection_id[0] for collection_id in collection_ids])

            # 创建一个列表来保存符合条件的meta_info列的JSON对象
            meta_info_list = []

            for collection_id in collection_ids:
                cursor.execute(
                    "SELECT meta_info FROM zvideo_collection WHERE collection_id = ?",
                    (collection_id,),
                )
                rows = cursor.fetchall()

                # 将meta_info列的信息转换为JSON对象并保存到列表中
                for row in rows:
                    try:
                        meta_info_json = json.loads(row[0])
                        meta_info_list.append(meta_info_json)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"An error occurred while decoding JSON for collection_id {collection_id}: {e}"
                        )

            for meta_info in meta_info_list:
                try:
                    douban_id = meta_info["relation"]["douban"]["douban_id"]
                    title = meta_info["title"]
                except Exception as e:
                    logger.error(f"meta_info: {meta_info}，解析失败: {e}")
                    continue
                if self._cached_data.get(title) == DoubanStatus.DONE.value:
                    logger.info(f"已处理过: {title}，跳过...")
                    continue
                if douban_id == 0:
                    _, douban_id, _ = self.get_douban_info_by_name(title)
                if douban_id != None:
                    watching_douban_id.append((title, douban_id))
                else:
                    logger.error(f"未找到豆瓣ID: {title}")

        except sqlite3.Error as e:
            logger.error(f"An error occurred: {e}")

        finally:
            # 确保游标和连接在使用完后关闭
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            message = ""
            for item in watching_douban_id:
                status = DoubanStatus.DONE.value
                ret = self._douban_helper.set_watching_status(
                    subject_id=item[1], status=status, private=True
                )
                if ret:
                    self._cached_data[item[0]] = status
                    logger.info(f"title: {item[0]}, douban_id: {item[1]},已标记为已看")
                    message += f"{item[0]}，已标记为已看\n"
                else:
                    logger.error(
                        f"title: {item[0]}, douban_id: {item[1]}, 标记已看失败"
                    )
                    message += f"{item[0]}，***标记已看失败***\n"
            if self._notify and len(message) > 0:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="【极影视助手】",
                    text=message,
                )

    def get_douban_info_by_name(self, title):
        logger.info(f"正在查询：{title}")
        # 延迟10s，以防频繁请求被豆瓣封接口
        time.sleep(10)
        subject_name, subject_id, score = self._douban_helper.get_subject_id(
            title=title
        )
        logger.info(
            f"查询到：subject_name: {subject_name}, subject_id: {subject_id}, score: {score}"
        )
        return subject_name, subject_id, score

    # 填充zvideo_collection中所有行的douban_score
    def fill_douban_score(self):
        logger.info("获取豆瓣评分...")
        conn = sqlite3.connect(self._db_path)
        # 使用UTF-8编码处理文本
        conn.text_factory = str
        cursor = conn.cursor()

        cursor.execute("SELECT rowid, extend_type, meta_info, updated_at FROM zvideo_collection")
        rows = cursor.fetchall()
        message = ""
        for row in rows:
            rowid, extend_type, meta_info_json, updated_at = row
            # 合集，不处理
            if extend_type == 7:
                continue
            meta_info_dict = json.loads(meta_info_json)
            # 如果meta_info为空，跳过
            if meta_info_dict.get("douban_score") == None:
                continue
                
            title = meta_info_dict["title"]
            current_time = datetime.now()
            need_update = False
            
            # 检查是否需要更新评分
            try:
                # 确保douban_score是数值类型
                douban_score = float(meta_info_dict.get("douban_score", 0))
            except (TypeError, ValueError):
                douban_score = 0
                
            if douban_score == 0:
                need_update = True
                logger.info(f"未找到豆瓣评分，需要更新：{title}")
            elif updated_at and self._douban_score_update_days > 0:
                try:
                    # 处理update_at的时间格式，去掉时区信息
                    update_at_str = updated_at.split('+')[0]
                    
                    # 根据格式选择不同的解析方式
                    if '.' in update_at_str:
                        # 处理微秒部分，确保最多6位数字
                        parts = update_at_str.split('.')
                        if len(parts) > 1:
                            # 截取微秒部分最多6位
                            microseconds = parts[1][:6]
                            update_at_str = f"{parts[0]}.{microseconds}"
                        update_time = datetime.strptime(update_at_str, "%Y-%m-%d %H:%M:%S.%f")
                    else:
                        # 没有微秒部分的时间格式
                        update_time = datetime.strptime(update_at_str, "%Y-%m-%d %H:%M:%S")
                    
                    time_diff = current_time - update_time
                    # 检查是否超过更新周期
                    if time_diff.days >= self._douban_score_update_days:
                        need_update = True
                        logger.info(f"豆瓣评分已过期，需要更新：{title}，上次更新时间：{update_at_str}")
                except Exception as e:
                    logger.error(f"解析update_at时间失败: {e}, 原始值: {updated_at}")
                    need_update = True
            elif not updated_at and self._douban_score_update_days > 0:
                need_update = True
                logger.info(f"未找到更新时间，需要更新豆瓣评分：{title}")
                
            if need_update:
                # 记录原来的评分
                old_score = meta_info_dict.get("douban_score", 0)
                # 确保转换为浮点数进行比较
                try:
                    old_score = float(old_score)
                except (TypeError, ValueError):
                    old_score = 0
                
                _, _, score = self.get_douban_info_by_name(title)
                if score:
                    # 确保score也是浮点数
                    try:
                        score = float(score)
                    except (TypeError, ValueError):
                        score = 0
                        
                    # 判断评分是否变化
                    score_changed = old_score > 0 and old_score != score
                    meta_info_dict["douban_score"] = score
                    # 更新meta_info
                    updated_meta_info_json = json.dumps(meta_info_dict, ensure_ascii=False)
                    # 生成带微秒和时区信息的时间字符串，确保与原格式一致
                    tz = pytz.timezone(settings.TZ)
                    current_time = datetime.now(tz)
                    # 格式化为"2024-01-31 23:25:28.609023+08:00"格式
                    current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S.%f") + current_time.strftime("%z")[:3] + ":" + current_time.strftime("%z")[3:]
                    # 更新meta_info和updated_at
                    cursor.execute(
                        "UPDATE zvideo_collection SET meta_info = ?, updated_at = ? WHERE rowid = ?",
                        (updated_meta_info_json, current_time_str, rowid),
                    )
                    conn.commit()
                    
                    # 生成包含评分变化的日志和通知信息
                    if score_changed:
                        change_direction = "上升" if score > old_score else "下降"
                        change_amount = abs(score - old_score)
                        change_msg = f"更新豆瓣评分：{title} {old_score} → {score} ({change_direction}{change_amount:.1f})"
                        logger.info(change_msg)
                        message += f"{title} 评分{change_direction}：{old_score} → {score}\n"
                    elif old_score == 0 and score > 0:
                        # 首次获取评分
                        logger.info(f"首次获取豆瓣评分：{title} {score}")
                        message += f"{title} 获取豆瓣评分：{score}\n"
                    else:
                        # 评分未变化，只记录日志不发送通知
                        logger.info(f"豆瓣评分未变化：{title} {score}")
                else:
                    logger.error(f"未找到豆瓣评分：{title}")
            else:
                logger.info(
                    f"无需更新豆瓣评分：{title} {meta_info_dict['douban_score']}"
                )
                
        if self._notify and len(message) > 0:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title="【极影视助手】",
                text=message,
            )
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    def use_douban_score(self):
        logger.info("使用豆瓣评分...")
        self.fill_douban_score()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        # 将meta_info的douban_score值同步到zvideo_collection表的score列
        cursor.execute(
            """
            UPDATE zvideo_collection
            SET score = CAST(JSON_EXTRACT(meta_info, '$.douban_score') AS DECIMAL(3,1))
            WHERE CAST(JSON_EXTRACT(meta_info, '$.douban_score') AS DECIMAL(3,1)) <> 0.0
            """
        )
        conn.commit()

        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logger.info("更新极影视为豆瓣评分...")

    def use_tmdb_score(self):
        logger.info("使用tmdb评分...")
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        # 将meta_info的score值同步到zvideo_collection表的score列
        cursor.execute(
            """
            UPDATE zvideo_collection
            SET score = CAST(JSON_EXTRACT(meta_info, '$.score') AS DECIMAL(3,1))
            WHERE JSON_EXTRACT(meta_info, '$.score') IS NOT NULL
            """
        )
        conn.commit()
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logger.info("更新极影视为tmdb评分...")

    def sync_douban_status(self):
        self.set_douban_watching()
        self.set_douban_done()
        # 缓存数据
        self.save_data("zvideohelper", self._cached_data)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                            "label": "开启通知",
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
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "sync_douban_status",
                                            "label": "同步在看/已看至豆瓣",
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
                                            "model": "use_douban_score",
                                            "label": "使用豆瓣评分",
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
                                            "model": "clean_cache",
                                            "label": "清理缓存数据",
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
                                        "props": {"model": "cron", "label": "执行周期"},
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
                                            "model": "douban_score_update_days",
                                            "label": "豆瓣评分更新周期(天)",
                                            "placeholder": "0则不更新",
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "豆瓣cookie",
                                            "rows": 1,
                                            "placeholder": "留空则从cookiecloud获取",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "db_path",
                                            "label": "极影视数据库路径",
                                            "rows": 1,
                                            "placeholder": "极影视路径为/zspace/zsrp/sqlite/zvideo/zvideo.db，需先映射路径",
                                        },
                                    }
                                ],
                            }
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
                                            "type": "error",
                                            "variant": "tonal",
                                            "text": "强烈建议使用前备份数据库，以免因插件bug导致数据库异常",
                                        },
                                    }
                                ],
                            }
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
                                            "text": "本插件基于极影视数据库扩展功能，需开启ssh后通过portainer、1panel等工具映射极影视数据库路径",
                                        },
                                    }
                                ],
                            }
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
                                            "text": "极影视默认使用tmdb评分，勾选'使用豆瓣评分'后，将使用豆瓣评分。豆瓣无评分的继续使用tmdb评分",
                                        },
                                    }
                                ],
                            }
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
                                            "text": "豆瓣评分更新周期是指多少天后重新获取豆瓣评分，防止评分变化。设为0则不更新已有评分",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "cron": "0 0 * * *",
            "douban_score_update_days": 0,
        }

    def get_page(self) -> List[dict]:
        pass

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
