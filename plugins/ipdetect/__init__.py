import re
import socket
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import set_key

from app.core.config import settings
from app.core.module import ModuleManager
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType


class IpDetect(_PluginBase):
    # 插件名称
    plugin_name = "本地IP检测"
    # 插件描述
    plugin_desc = "如果QB、TR等服务在本地部署，当本地IP改变时自动修改其Server IP。"
    # 插件图标
    plugin_icon = "ipAddress.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "DzAvril"
    # 作者主页
    author_url = "https://github.com/DzAvril"
    # 插件配置项ID前缀
    plugin_config_prefix = "ipdetect_"
    # 加载顺序
    plugin_order = 0
    # 可使用的用户级别
    auth_level = 1

    # preivate property
    _enabled = False
    _notify = False
    _enable_qb = False
    _enable_tr = False
    _enable_emby = False
    _enable_emby_play = False
    _enable_jellyfin = False
    _enable_jellyfin_play = False
    _enable_plex = False
    _enable_plex_play = False
    _onlyonce = False
    _cron = ""
    _setting_keys = []
    _scheduler = None

    def init_plugin(self, config: dict = None):
        logger.info(f"Hello IpDetect, config {config}")
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._enable_qb = config.get("enable_qb")
            self._enable_tr = config.get("enable_tr")
            self._enable_emby = config.get("enable_emby")
            self._enable_emby_play = config.get("enable_emby_play")
            self._enable_jellyfin = config.get("enable_jellyfin")
            self._enable_jellyfin_play = config.get("enable_jellyfin_play")
            self._enable_plex = config.get("enable_plex")
            self._enable_plex_play = config.get("enable_plex_play")

        if not self._enabled:
            return
        self._setting_keys = []
        if self._enable_qb:
            if settings.QB_HOST is not None:
                self._setting_keys.append("QB_HOST")
            else:
                logger.warn("QB服务地址未设置，请检查配置！")
        if self._enable_tr:
            if settings.TR_HOST is not None:
                self._setting_keys.append("TR_HOST")
            else:
                self._enable_tr = False
                logger.warn("TR服务地址未设置，请检查配置！")
        if self._enable_emby:
            if settings.EMBY_HOST is not None:
                self._setting_keys.append("EMBY_HOST")
            else:
                self._enable_emby = False
                logger.warn("Emby服务地址未设置，请检查配置！")
        if self._enable_emby_play:
            if settings.EMBY_PLAY_HOST is not None:
                self._setting_keys.append("EMBY_PLAY_HOST")
            else:
                self._enable_emby_play = False
                logger.warn("Emby外网播放地址未设置，请检查配置！")
        if self._enable_jellyfin:
            if settings.JELLYFIN_HOST is not None:
                self._setting_keys.append("JELLYFIN_HOST")
            else:
                self._enable_jellyfin = False
                logger.warn("Jellyfin服务地址未设置，请检查配置！")
        if self._enable_jellyfin_play:
            if settings.JELLYFIN_PLAY_HOST is not None:
                self._setting_keys.append("JELLYFIN_PLAY_HOST")
            else:
                self._enable_jellyfin_play = False
                logger.warn("Jellyfin外网播放地址未设置，请检查配置！")
        if self._enable_plex:
            if settings.PLEX_HOST is not None:
                self._setting_keys.append("PLEX_HOST")
            else:
                self._enable_plex = False
                logger.warn("Plex服务地址未设置，请检查配置！")
        if self._enable_plex_play:
            if settings.PLEX_PLAY_HOST is not None:
                self._setting_keys.append("PLEX_PLAY_HOST")
            else:
                self._enable_plex_play = False
                logger.warn("Plex外网播放地址未设置，请检查配置！")
        # 更新配置
        self.__update_config()
        logger.info(f"_setting_keys: {self._setting_keys}")
        if self._onlyonce:
            # 定时任务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"本地IP检测服务启动，立即运行一次")
            self._scheduler.add_job(
                self.detect_ip,
                "date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                + timedelta(seconds=3),
            )
            self._onlyonce = False
            self.__update_config()

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "notify": self._notify,
                "enable_qb": self._enable_qb,
                "enable_tr": self._enable_tr,
                "enable_emby": self._enable_emby,
                "enable_emby_play": self._enable_emby_play,
                "enable_jellyfin": self._enable_jellyfin,
                "enable_jellyfin_play": self._enable_jellyfin_play,
                "enable_plex": self._enable_plex,
                "enable_plex_play": self._enable_plex_play,
            }
        )

    def get_state(self) -> bool:
        return self._enabled

    def detect_ip(self):
        if len(self._setting_keys) == 0:
            return
        local_ip = self.get_local_ip()
        current_ip = self.parse_ip(self.get_value(self._setting_keys[0]))
        logger.info(f"current_ip: {current_ip}")
        if local_ip == current_ip:
            logger.info(f"当前IP地址为{local_ip}，没有变化！")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【本地IP检测】",
                    text=f"未检测到IP地址变化！",
                )

            return
        for key in self._setting_keys:
            prefix = (
                True
                if key == "EMBY_PLAY_HOST"
                or key == "PLEX_PLAY_HOST"
                or key == "JELLYFIN_PLAY_HOST"
                else False
            )
            self.update_key_value(key, local_ip, prefix)
        # 重新加载模块
        logger.info("重新加载模块")
        ModuleManager().reload()
        Scheduler().init()
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【本地IP检测】",
                text=f"检测到本地IP变为{local_ip}，已更新服务地址！",
            )

    def update_key_value(self, k, v, prefix):
        old_value = self.get_value(k)
        if prefix:  # http(s)://ip:port
            ip_pattern = r"https?://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)"
            v = re.sub(
                ip_pattern,
                lambda m: "{}://{}:{}".format(m.group(0).split(":")[0], v, m.group(2)),
                old_value,
            )
        else:  # ip:port
            ip_pattern = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)"
            v = re.sub(ip_pattern, r"{}:\2".format(v), old_value)
        if hasattr(settings, k):
            if v == "None":
                v = None
            setattr(settings, k, v)
            if v is None:
                v = ""
            else:
                v = str(v)
            set_key(settings.CONFIG_PATH / "app.env", k, v)
            logger.info(f"重新设置服务地址{k}成功！")

    @staticmethod
    def get_value(key):
        if key == "QB_HOST":
            return settings.QB_HOST
        elif key == "TR_HOST":
            return settings.TR_HOST
        elif key == "EMBY_HOST":
            return settings.EMBY_HOST
        elif key == "EMBY_PLAY_HOST":
            return settings.EMBY_PLAY_HOST
        elif key == "JELLYFIN_HOST":
            return settings.JELLYFIN_HOST
        elif key == "JELLYFIN_PLAY_HOST":
            return settings.JELLYFIN_PLAY_HOST
        elif key == "PLEX_HOST":
            return settings.PLEX_HOST
        elif key == "PLEX_PLAY_HOST":
            return settings.PLEX_PLAY_HOST
        else:
            return None

    @staticmethod
    def parse_ip(ip):
        ip_pattern = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
        match = re.search(ip_pattern, ip)
        if match:
            return match.group(1)
        else:
            return None

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
                    "id": "IpDetect",
                    "name": "检测本地IP变化",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.detect_ip,
                    "kwargs": {},
                }
            ]

    @staticmethod
    def get_local_ip():
        try:
            # 创建一个 UDP 套接字
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 连接到一个虚拟的目标IP和端口
            s.connect(("10.255.255.255", 1))
            # 获取本地 IP 地址
            local_ip = s.getsockname()[0]
            logger.info(f"当前本地IP为：{local_ip}")
            return local_ip
        except socket.error:
            return "127.0.0.1"  # 如果无法获取到本地IP，则返回本地回环地址

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
                                "props": {"cols": 12, "md": 6},
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "检测周期",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
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
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_qb",
                                            "label": "QB下载器",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_tr",
                                            "label": "TR下载器",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_emby",
                                            "label": "Emby服务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_emby_play",
                                            "label": "Emby外网播放",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_jellyfin",
                                            "label": "Jellyfin服务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_jellyfin_play",
                                            "label": "Jellyfin外网播放",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_plex",
                                            "label": "Plex服务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_plex_play",
                                            "label": "Plex外网播放",
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
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "本插件针对部署在本地的服务，如QB下载器、Emby服务等，检测到本地IP变化时同步修改服务地址，请勾选部署在本地的服务。",
                                        },
                                    }
                                ],
                            },
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
                                            "text": "本插件不适用于桥接模式的Docker，因为获取不到Host的IP地址",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "enable_qb": False,
            "enable_tr": False,
            "enable_emby": False,
            "enable_emby_play": False,
            "enable_jellyfin": False,
            "enable_jellyfin_play": False,
            "enable_plex": False,
            "enable_plex_play": False,
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
