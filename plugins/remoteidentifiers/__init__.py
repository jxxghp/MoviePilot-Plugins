from typing import List, Tuple, Dict, Any

import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.utils.http import RequestUtils
from app.log import logger

from app.plugins import _PluginBase
from ...db.systemconfig_oper import SystemConfigOper
from ...schemas.types import SystemConfigKey
from app.utils.common import retry


class RemoteIdentifiers(_PluginBase):
    # 插件名称
    plugin_name = "共享识别词"
    # 插件描述
    plugin_desc = "从Github、Etherpad远程文件中获取共享识别词并应用"
    # 插件图标
    plugin_icon = "words.png"
    # 插件版本
    plugin_version = "2.3"
    # 插件作者
    plugin_author = "honue"
    # 作者主页
    author_url = "https://github.com/honue"
    # 插件配置项ID前缀
    plugin_config_prefix = "RemoteIdentifiers_"
    # 加载顺序
    plugin_order = 10
    # 可使用的用户级别
    auth_level = 1

    _enable = False
    _cron = '30 4 * * *'
    _file_urls = ''
    _onlyonce = False
    _flitter = True
    # 定时器
    _scheduler = None
    systemconfig = None

    def init_plugin(self, config: dict = None):
        # 停止后台任务
        self.stop_service()
        if config:
            self._enable = config.get("enable") if config.get("enable") is not None else False
            self._onlyonce = config.get("onlyonce") if config.get("onlyonce") is not None else False
            self._flitter = config.get("flitter") if config.get("flitter") is not None else False
            self._cron = config.get("cron") or '30 4 * * *'
            self._file_urls = config.get("file_urls") or ''
            # config操作
            self.systemconfig = SystemConfigOper()

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("获取远端识别词,订阅服务启动，立即运行一次")
            self._scheduler.add_job(func=self.__task, trigger='date',
                                    run_date=datetime.datetime.now(
                                        tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                    )
            self._onlyonce = False
            self.__update_config()
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    @retry(Exception, tries=3, delay=5, backoff=2, logger=logger)
    def get_file_content(self, file_urls: list) -> List[str]:
        ret: List[str] = ['#========以下识别词由 RemoteIdentifiers 插件添加========#']
        for file_url in file_urls:
            # https://movie-pilot.org/etherpad/p/MoviePilot_TV_Words
            if file_url.count("etherpad") != 0 and file_url.count("export") == 0:
                real_url = file_url + "/export/txt"
            else:
                real_url = file_url
            response = RequestUtils(proxies=settings.PROXY,
                                    headers=settings.GITHUB_HEADERS if real_url.count("github") else None,
                                    timeout=15).get_res(real_url)
            if not response:
                raise Exception(f"文件 {real_url} 下载失败！")
            elif response.status_code != 200:
                raise Exception(f"下载文件 {real_url} 失败：{response.status_code} - {response.reason}")
            text = response.content.decode('utf-8')
            if text.find("doctype html") > 0:
                raise Exception(f"下载文件 {real_url} 失败：{response.status_code} - {response.reason}")
            if "try again later" in text:
                raise Exception(f"下载文件 {real_url} 失败：{text}")
            identifiers: List[str] = text.split('\n')
            ret += identifiers
        # flitter 过滤空行
        if self._flitter:
            filtered_ret = []
            for item in ret:
                if item != '':
                    filtered_ret.append(item)
            ret = filtered_ret
        logger.info(f"获取到远端识别词{len(ret) - 1}条: {ret[1:]}")
        return ret

    def __task(self):
        words: List[str] = self.systemconfig.get(SystemConfigKey.CustomIdentifiers) or []
        file_urls: list = self._file_urls.split('\n') if self._file_urls else []
        remote_words: list = self.get_file_content(file_urls)
        # 找出用户自己加的
        cnt = 0
        for word in words:
            if "RemoteIdentifiers" in word:
                break
            else:
                cnt += 1
        words = words[:cnt]
        words += remote_words
        self.systemconfig.set(SystemConfigKey.CustomIdentifiers, words)
        logger.info("远端识别词添加成功")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enable',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'flitter',
                                            'label': '过滤空白行',
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
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
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '定时任务周期',
                                            'placeholder': '30 4 * * *',
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
                                    'md': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'file_urls',
                                            'rows': 6,
                                            'label': '远程文件地址（一行一个）',
                                            'placeholder': '如果是Github文件地址请注意填写包含raw的! 这个才是文件地址，其他的是这个文件的页面地址',
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
                                            'type': 'success',
                                            'variant': 'tonal',
                                            'text': '可自己创建分享地址（支持Github及Etherpad），Github需要raw的源文件地址，文件格式与系统中配置格式一致即可。'
                                                    '以下为官方托管的共享识别词，开放给大家共同维护，但由于经常有人捣乱，且体量越来越大影响运行效率，'
                                                    '【建议仅供分享和参考】，不在插件中引用：https://movie-pilot.org/etherpad/p/MoviePilot_TV_Words、https://movie-pilot.org/etherpad/p/MoviePilot_Anime_Words'
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
                                            'text': '以下共享识别词由第三方审核维护，推荐使用：https://raw.githubusercontent.com/Putarku/MoviePilot-Help/main/Words/TV.txt、https://raw.githubusercontent.com/Putarku/MoviePilot-Help/main/Words/anime.txt'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enable": False,
            "onlyonce": False,
            "flitter": True,
            "cron": '30 4 * * *',
            "file_urls": "https://raw.githubusercontent.com/Putarku/MoviePilot-Help/main/Words/TV.txt\n"
                         "https://raw.githubusercontent.com/Putarku/MoviePilot-Help/main/Words/anime.txt",
        }

    def __update_config(self):
        self.update_config({
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "enable": self._enable,
            "flitter": self._flitter,
            "file_urls": self._file_urls,
        })

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    def get_page(self) -> List[dict]:
        pass

    def get_state(self) -> bool:
        return self._enable

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
        if self._enable and self._cron:
            return [{
                "id": "RemoteIdentifiers",
                "name": "获取远端识别词",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__task,
                "kwargs": {}
            }]
