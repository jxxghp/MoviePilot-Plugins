import datetime
import re
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.system import SystemChain
from app.core.config import settings
from app.helper.system import SystemHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.utils.http import RequestUtils


class MoviePilotUpdateNotify(_PluginBase):
    # 插件名称
    plugin_name = "MoviePilot更新推送"
    # 插件描述
    plugin_desc = "MoviePilot推送release更新通知、自动重启。"
    # 插件图标
    plugin_icon = "Moviepilot_A.png"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "moviepilotupdatenotify_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _restart = False
    _notify = False
    _update_types = []

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._restart = config.get("restart")
            self._notify = config.get("notify")
            self._update_types = config.get("update_types") or []

    def __check_update(self):
        """
        检查MoviePilot更新
        """
        # 检查后端更新
        server_update = self.__check_server_update() if self._update_types and "后端" in self._update_types else False

        # 检查前端更新
        front_update = self.__check_front_update() if self._update_types and "前端" in self._update_types else False

        # 自动重启
        if (server_update or front_update) and self._restart:
            logger.info("开始执行自动重启…")
            SystemHelper.restart()

    def __check_server_update(self):
        """
        检查后端更新
        """
        release_version, description, update_time = self.__get_backend_latest()
        if not release_version:
            logger.error("后端最新版本获取失败")
            return False

        # 本地版本
        local_version = SystemChain().get_server_local_version()
        if local_version and release_version <= local_version:
            logger.info(f"当前后端版本：{local_version} 远程版本：{release_version} 停止运行")
            return False

        logger.info(f"发现MoviePilot后端更新：{release_version} {description} {update_time}")

        # 推送更新消息
        self.__notify_update(update_time=update_time,
                             release_version=release_version,
                             description=description,
                             mtype="后端")

        return True

    def __check_front_update(self):
        """
        检查前端更新
        """
        release_version, description, update_time = self.__get_front_latest()
        if not release_version:
            logger.error("前端最新版本获取失败")
            return False

        # 本地版本
        local_version = SystemChain().get_frontend_version()
        if local_version and release_version <= local_version:
            logger.info(f"当前前端版本：{local_version} 远程版本：{release_version} 停止运行")
            return False

        logger.info(f"发现MoviePilot前端更新：{release_version} {description} {update_time}")

        # 推送更新消息
        self.__notify_update(update_time=update_time,
                             release_version=release_version,
                             description=description,
                             mtype="前端")

        return True

    def __notify_update(self, update_time, release_version, description, mtype):
        """
        推送更新消息
        """
        # 推送更新消息
        if self._notify:
            # 将时间字符串转为datetime对象
            dt = datetime.datetime.strptime(update_time, "%Y-%m-%dT%H:%M:%SZ")
            # 设置时区
            timezone = pytz.timezone(settings.TZ)
            dt = dt.replace(tzinfo=timezone)
            # 将datetime对象转换为带时区的字符串
            update_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            if not description.startswith(release_version):
                description = f"{release_version}\n\n{description}"
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【MoviePilot{mtype}更新通知】",
                text=f"{description}\n\n{update_time}")

    @staticmethod
    def __get_latest_version(repo_url: str) -> Optional[dict]:
        """
        获取最新版本
        """
        # 获取所有发布的版本列表
        response = RequestUtils(
            proxies=settings.PROXY,
            headers=settings.GITHUB_HEADERS
        ).get_res(repo_url)
        if response:
            v2_releases = [r for r in response.json() if re.match(r"^v2\.", r['tag_name'])]
            if not v2_releases:
                logger.warn("未获取到最新版本号！")
                return None
            # 找到最新的v2版本
            latest_v2 = sorted(v2_releases, key=lambda s: list(map(int, re.findall(r'\d+', s['tag_name']))))[-1]
            logger.info(f"获取到最新版本：{latest_v2}")
            return latest_v2
        else:
            logger.error("无法获取版本信息，请检查网络连接或GitHub API请求。")
            return None

    def __get_backend_latest(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        获取最新版本
        """
        result = self.__get_latest_version("https://api.github.com/repos/jxxghp/MoviePilot/releases")
        if result:
            return result['tag_name'], result['body'], result['published_at']
        return None, None, None

    def __get_front_latest(self):
        """
        获取前端最新版本
        """
        result = self.__get_latest_version("https://api.github.com/repos/jxxghp/MoviePilot-Frontend/releases")
        if result:
            return result['tag_name'], result['body'], result['published_at']
        return None, None, None

    def get_state(self) -> bool:
        return self._enabled

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
        if self._enabled and self._cron:
            return [
                {
                    "id": "MoviePilotUpdateNotify",
                    "name": "MoviePilot更新检查服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.__check_update,
                    "kwargs": {}
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
                                            'model': 'restart',
                                            'label': '自动重启',
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
                                            'label': '检查周期',
                                            'placeholder': '5位cron表达式'
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
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'update_types',
                                            'label': '更新类型',
                                            'items': [
                                                {
                                                    "title": "后端",
                                                    "vale": "后端"
                                                },
                                                {
                                                    "title": "前端",
                                                    "vale": "前端"
                                                }
                                            ]
                                        }
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '如要开启自动重启，请确认MOVIEPILOT_AUTO_UPDATE设置为true，重启即更新。'
                                        }
                                    }
                                ]
                            },
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "restart": False,
            "notify": False,
            "cron": "0 9 * * *",
            "update_types": ["后端", "前端"]
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
