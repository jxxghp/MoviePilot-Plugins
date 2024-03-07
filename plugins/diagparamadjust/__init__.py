import json
from datetime import datetime, timedelta

from app.modules.emby import Emby
from app.core.config import settings
from app.plugins import _PluginBase
from app.log import logger
from typing import List, Tuple, Dict, Any, Optional
import pytz
from app.schemas import WebhookEventInfo
from app.schemas.types import EventType
from app.core.event import eventmanager, Event

from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler


class DiagParamAdjust(_PluginBase):
    # 插件名称
    plugin_name = "诊断参数调整"
    # 插件描述
    plugin_desc = "Emby专用插件|暂时性解决emby字幕偏移问题，需要emby安装Diagnostics插件。"
    # 插件图标
    plugin_icon = "Themeengine_A.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "jeblove"
    # 作者主页
    author_url = "https://github.com/jeblove"
    # 插件配置项ID前缀
    plugin_config_prefix = "dpa_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled: bool = False
    _offset = True
    _onlyonce = False
    _base_url = None
    _endpoint = None
    _api_key = None
    _search_text = None
    _replace_text = None
    _cron = None
    _cron_switch = False
    _login_play = False
    # 请求接口
    _url = "[HOST]emby/EncodingDiagnostics/DiagnosticOptions?api_key=[APIKEY]"
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    # 目标消息
    _webhook_actions = {
        "playback.start": "开始播放",
        "user.authenticated": "登录成功"
    }

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._offset = config.get('offset')
            self._onlyonce = config.get("onlyonce")
            self._search_text = config.get("search")
            self._replace_text = config.get("replace")
            self._cron = config.get("cron")
            self._cron_switch = config.get("cron_switch")
            self._login_play = config.get("login_play")

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"诊断参数调整服务启动，立刻运行一次")
            self._scheduler.add_job(func=self.run, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="诊断参数调整")

            # 关闭一次性开关
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "offset": self._offset,
                "onlyonce": False,
                "search": self._search_text,
                "replace": self._replace_text,
                "cron": self._cron,
                "cron_switch": self._cron_switch,
                "login_play": self._login_play
            })

            # 启动任务
            # self.run()
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

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
        if self._enabled and self._cron and self._cron_switch:
            return [{
                "id": "DiagParamAdjust",
                "name": "诊断参数调整定时服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run,
                "kwargs": {}
            }]

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
                                            'model': 'offset',
                                            'label': '字幕偏移用途',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'search',
                                            'label': '搜索文本'
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
                                            'model': 'replace',
                                            'label': '替换文本'
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
                                            'model': 'cron',
                                            'label': '检测执行周期',
                                            'placeholder': '*/5 * * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cron_switch',
                                            'label': '周期模式',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'login_play',
                                            'label': '用户登录|播放时执行',
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
                                            'text': '暂时性解决emby字幕偏移问题，如默认参数不合适请在基础上修改x、y至适合，如[x=W/4:y=h/5]。\n 【用户登录|播放时执行】需要emby配置webhooks消息通知：勾选[播放-开始]、[用户-已验证用户身份]（具体可参考【媒体库服务器通知】插件）',
                                            'style': 'white-space: pre-line;'
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
                                            'text': '此替换文本参数应用于emby-Diagnostics-Parameter Adjustment。\n 默认参数用于修改ffmpeg中字幕覆盖在视频上的位置。\n 方案来源于https://opve.cn/archives/983.html',
                                            'style': 'white-space: pre-line;'
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
            "offset": True,
            "onlyonce": False,
            "search": "x=(W-w)/2:y=(H-h):repeatlast=0",
            "replace": "x=W/4:y=h/4:repeatlast=0",
            "cron": "*/5 * * * *",
            "cron_switch": True,
            "login_play": False
        }

    def detect(self):
        """
        检测是否存在目标参数

        :return True: 存在; False: 不存在
        """
        logger.info('字幕偏移修正，检测目标参数')
        try:
            res = Emby().get_data(self._url)
            result = res.json()
            data = result['Object']['CommandLineOptions']
            replaceText = data['ReplaceText']
        except json.JSONDecodeError:
            logger.error('服务停止，Emby请安装【Diagnostics】插件')
            return None
        except KeyError:
            # 已装插件，未设置过该参数
            # logger.info('目标参数为空')
            return False

        # 符合所有情况
        if 'repeatlast' in replaceText \
                and 'x=(W-w)/2:y=(H-h):repeatlast=0' in data['SearchText'] \
                and result['Object']['TranscodingOptions']['DisableHardwareSubtitleOverlay'] is True:
            return True

        return False

    def set_options(self):
        data = {
            "CommandLineOptions": {
                "SearchText": self._search_text,
                "ReplaceText": self._replace_text
            },
            "TranscodingOptions": {
                "DisableHardwareSubtitleOverlay": True
            }
        }
        data = json.dumps(data)
        headers = {
            'Content-Type': 'application/octet-stream'
        }
        res = Emby().post_data(self._url, data, headers)
        if res.status_code // 100 == 2:
            logger.info('参数设置成功')
            return True
        else:
            logger.error('参数设置失败 {}'.format(res.status_code))
            return False

    @eventmanager.register(EventType.WebhookMessage)
    def get_msg(self, event: Event):
        # 消息方式开关
        if not self._enabled or not self._login_play:
            return

        # 消息获取
        event_info: WebhookEventInfo = event.event_data
        if not event_info:
            return

        # 非目标消息
        if not self._webhook_actions.get(event_info.event):
            return

        self.run()

    def run(self):
        # 字幕偏移修正，则带检测
        if self._offset:
            state = self.detect()
            if state:
                logger.info('参数正常，无需修正')
                return True
            elif state is None:
                logger.info('插件退出')
                return None

        self.set_options()

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
