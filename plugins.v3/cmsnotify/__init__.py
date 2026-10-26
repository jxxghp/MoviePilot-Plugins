import time

from typing import List, Tuple, Dict, Any, Optional
from apscheduler.triggers.cron import CronTrigger

# V3 适配：以下模块在 MoviePilot V3 中已从 app.core.* / app.utils.* / app.log
# 迁移到统一的 app.sdk.* 命名空间，旧路径已移除，必须改用新路径导入。
from app.sdk.events import eventmanager
from app.sdk.network import RequestUtils
from app.sdk.logging import logger
from app.schemas.types import EventType
from app.plugins import _PluginBase


class CMSNotify(_PluginBase):
    # 插件名称
    plugin_name = "CMS通知V3"
    # 插件描述
    plugin_desc = "整理完成115里的媒体后，通知CMS进行增量同步（strm生成）"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/po9873/MoviePilot-Plugins/main/icons/cms.png"
    # 插件版本
    plugin_version = "0.7"
    # 插件作者
    plugin_author = "po9873"
    # 适配者
    author_url = "https://github.com/po9873"
    # 插件配置项ID前缀
    plugin_config_prefix = "cmsnotify_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _cms_notify_type = None
    _cms_domain = None
    _cms_api_token = None
    _enabled = False
    _last_event_time = 0
    # 等待通知数量
    _wait_notify_count = 0

    # 需要触发通知的存储类型
    _SUPPORTED_STORAGE = ("u115", "115网盘Plus", "CloudDrive储存")

    # CMS 返回体里代表「成功」的业务 code（不同 CMS 版本可能不同，可在日志中核对）
    _SUCCESS_CODES = ("0", "200")

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._cms_notify_type = config.get("cms_notify_type")
            self._cms_domain = config.get("cms_domain")
            self._cms_api_token = config.get('cms_api_token')

    def get_state(self) -> bool:
        return self._enabled

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
        if self._enabled:
            return [{
                "id": "CMSNotify",
                "name": "CMS通知",
                "trigger": CronTrigger.from_crontab("* * * * *"),
                "func": self.__notify_cms,
                "kwargs": {}
            }]
        return []

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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'cms_notify_type',
                                            'label': '通知类型',
                                            'items': [
                                                {'title': '增量同步',
                                                    'value': 'lift_sync'},
                                                {'title': '增量同步+自动整理',
                                                    'value': 'auto_organize'},
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cms_domain',
                                            'label': 'CMS地址'
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
                                            'model': 'cms_api_token',
                                            'label': 'CMS_API_TOKEN'
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
                                            'text': '当MP整理或刮削好115里的媒体后，会通知CMS进行增量同步（strm生成）；CMS版本需要0.3.5.11及以上：https://wiki.cmscc.cc'
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
                                            'text': '支持跨机器访问：CMS地址填写任意可达地址即可（如 http://192.168.6.244:9527）。默认值 172.17.0.1 仅适用于 CMS 与 MoviePilot 在同一台宿主机上的情况；若 CMS 部署在别的机器，请改为该机器的局域网 IP 并确保端口可连通。'
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
                                            'text': '为了防止通知次数过于频繁，会有1-2分钟的等待，只有在此期间再无其它整理或刮削时，才会进行通知'
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
            "cms_notify_type": "lift_sync",
            "cms_api_token": "cloud_media_sync",
            "cms_domain": "http://172.17.0.1:9527"
        }

    def get_page(self) -> List[dict]:
        pass

    # V3 适配：V3 不再支持「注册基类 EventType 全量捕获」的写法，
    # 必须显式注册具体事件类型（官方 V3 插件均为此写法）。
    @eventmanager.register([EventType.TransferComplete, EventType.MetadataScrape])
    def monitor(self, event):
        """
        监听整理完成 / 刮削完成事件
        """
        if not self._enabled or not self._cms_domain or not self._cms_api_token:
            return

        if not event:
            return

        # V3 的事件负载是 pydantic 契约对象，不再是 dict，
        # 因此改为直接读取属性（字段名均保留：transferinfo / fileitem / storage / name）。
        event_data = getattr(event, "event_data", None)
        if not event_data:
            return

        event_type = getattr(event, "event_type", None)
        etype = event_type.value if hasattr(event_type, "value") else str(event_type)
        logger.debug(f"event_type: {etype}")

        if etype == "transfer.complete":
            self.__handle_transfer(event_data)
        elif etype == "metadata.scrape":
            self.__handle_scrape(event_data)

    def __handle_transfer(self, event_data):
        """
        处理整理完成事件
        """
        transferinfo = getattr(event_data, "transferinfo", None)
        if not transferinfo or not getattr(transferinfo, "success", False):
            return

        target_diritem = getattr(transferinfo, "target_diritem", None)
        target_item = getattr(transferinfo, "target_item", None)
        storage = getattr(target_diritem, "storage", None)
        name = getattr(target_item, "name", None)

        if storage in self._SUPPORTED_STORAGE:
            logger.info(f"115整理完成：{name}")
            self._wait_notify_count += 1
            self._last_event_time = self.__get_time()

    def __handle_scrape(self, event_data):
        """
        处理刮削完成事件

        注：原 V2 版本此处为 `storage = event_data["fileitem"]`，
        取到的是文件对象而非存储类型，导致该分支永远不会命中；
        本适配版已修正为读取 fileitem.storage。
        """
        fileitem = getattr(event_data, "fileitem", None)
        if not fileitem:
            return

        storage = getattr(fileitem, "storage", None)
        name = getattr(fileitem, "name", None)

        if storage in self._SUPPORTED_STORAGE:
            logger.info(f"115刮削完成：{name}")
            self._wait_notify_count += 1
            self._last_event_time = self.__get_time()

    def __get_time(self):
        return int(time.time())

    def __notify_cms(self):
        try:
            # 当等待通知数量超过1000或者有等待通知且最后事件时间超过60秒时触发通知
            if self._wait_notify_count > 0 and (self._wait_notify_count > 1000 or self.__get_time() - self._last_event_time > 60):
                url = f"{self._cms_domain}/api/sync/lift_by_token?token={self._cms_api_token}&type={self._cms_notify_type}"
                ret = RequestUtils().get_res(url)

                if ret is None:
                    logger.error("通知CMS失败，未获取到返回信息")
                    return

                # 关键修复：CMS 无论成功或失败都返回 HTTP 200，
                # 真正的业务结果放在响应体的 code 字段里（如 {"code":"400","message":"token错误"}）。
                # 原 V2 版本只判断 ret 是否为真，会导致 token 错误时也误报「通知成功」。
                ok = False
                detail = ""
                try:
                    payload = ret.json()
                    if isinstance(payload, dict):
                        detail = str(payload.get("message") or "")
                        ok = str(payload.get("code")) in self._SUCCESS_CODES
                    else:
                        ok = True
                except Exception:
                    # 响应不是 JSON 时，退化为按 HTTP 状态码判断
                    ok = 200 <= ret.status_code < 300
                    detail = (ret.text or "")[:200]

                if ok:
                    logger.info("通知CMS执行增量同步成功")
                    self._wait_notify_count = 0
                else:
                    logger.error(
                        f"通知CMS失败，状态码：{ret.status_code}，返回信息：{detail or ret.text[:200]} {ret.reason}")
            else:
                if self._wait_notify_count > 0:
                    logger.info(
                        f"等待通知数量：{self._wait_notify_count}，最后事件时间：{self._last_event_time}")
        except Exception as e:
            logger.error(f"通知CMS发生异常：{e}")

    def stop_service(self):
        """
        退出插件
        """
        pass
