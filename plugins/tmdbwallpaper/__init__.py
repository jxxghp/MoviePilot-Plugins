from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Dict, Tuple
from urllib.parse import urlparse, parse_qs

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.helper.wallpaper import WallpaperHelper
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class TmdbWallpaper(_PluginBase):
    # 插件名称
    plugin_name = "登录壁纸本地化"
    # 插件描述
    plugin_desc = "将MoviePilot的登录壁纸下载到本地。"
    # 插件图标
    plugin_icon = "Macos_Sierra.png"
    # 插件版本
    plugin_version = "1.4.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "tmdbwallpaper_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _hours = None
    _savepath = None
    _enabled = False
    _onlyonce = False
    _scheduler = None

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._hours = int(config.get("hours")) if config.get("hours") else None
            self._savepath = config.get('savepath')
            self._onlyonce = config.get("onlyonce")
            if self._enabled or self._onlyonce:
                savepath = Path(self._savepath)
                if self._savepath and not savepath.exists():
                    logger.info(f"创建保存目录：{self._savepath}")
                    savepath.mkdir(parents=True, exist_ok=True)
                # 立即运行一次
                if self._onlyonce:
                    # 定时服务
                    self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                    logger.info(f"登录壁纸本地化服务启动，立即运行一次")
                    self._scheduler.add_job(self.wallpaper_local, 'date',
                                            run_date=datetime.now(
                                                tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
                                            )
                    # 关闭一次性开关
                    self._onlyonce = False

                    # 保存配置
                    self.update_config({
                        "enabled": self._enabled,
                        "hours": self._hours,
                        "savepath": self._savepath,
                        "onlyonce": self._onlyonce
                    })
                    if self._scheduler.get_jobs():
                        # 启动服务
                        self._scheduler.print_jobs()
                        self._scheduler.start()

    def get_state(self) -> bool:
        return True if self._enabled and self._hours and self._savepath else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'hours',
                                            'label': '更新频率（小时）',
                                            'placeholder': '1'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'savepath',
                                            'label': '保存路径',
                                            'placeholder': '/config/wallpapers'
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
            "hours": 1,
            "savepath": "/config/wallpapers"
        }

    def get_page(self) -> List[dict]:
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
        if self.get_state():
            return [{
                "id": "TmdbWallpaper",
                "name": "登录壁纸本地化服务",
                "trigger": "interval",
                "func": self.wallpaper_local,
                "kwargs": {
                    "minutes": self._hours * 60
                }
            }]
        return []

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
            print(str(e))

    def wallpaper_local(self):
        """
        下载MoviePilot的登录壁纸到本地
        """

        def __save_file(_url: str, _filename: str):
            """
            保存文件
            """
            try:
                savepath = Path(self._savepath)
                logger.info(f"下载壁纸：{_url}")
                r = RequestUtils().get_res(_url)
                if r and r.status_code == 200:
                    with open(savepath / _filename, "wb") as f:
                        f.write(r.content)
            except Exception as e:
                logger.error(f"下载壁纸失败：{str(e)}")

        if not self._savepath:
            return
        urls = WallpaperHelper().get_wallpapers(10) or []
        for url in urls:
            if settings.WALLPAPER == "tmdb":
                filename = url.split("/")[-1]
            elif settings.WALLPAPER == "bing":
                # 解析url参数，获取id的值
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                param_value = query_params.get("id")
                filename = param_value[0] if param_value else None
            else:
                # 其他壁纸类型，直接使用url的文件名hash
                filename = url.split("/")[-1]
                # 没有后缀的文件名，添加.jpg后缀
                if not filename.endswith(".jpg"):
                    filename += ".jpg"
            __save_file(url, filename)
