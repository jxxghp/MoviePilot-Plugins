"""兼容 MoviePilot V3 新旧 Tracker 接口的替换插件。"""

import re
from typing import List, Tuple, Dict, Any, Union, Optional

from apscheduler.triggers.cron import CronTrigger
from packaging.version import Version
from version import APP_VERSION

from app.sdk.logging import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
try:
    from app.sdk.plugin import _PluginBase
except ModuleNotFoundError as err:
    if err.name != "app.sdk.plugin":
        raise
    # MP 3.0.0 尚未提供新 SDK 基类入口，沿用该版本公开的入口。
    from app.plugins import _PluginBase
from app.schemas.types import MessageType


class TrackerEditor(_PluginBase):
    """按替换规则修改 Tracker，并按种子记录执行结果。"""

    # 插件名称
    plugin_name = "Tracker替换"
    # 插件描述
    plugin_desc = "批量替换修改种子tracker"
    # 插件图标
    plugin_icon = "trackereditor_A.png"
    # 插件版本
    plugin_version = "2.0"
    # 插件作者
    plugin_author = "honue"
    # 作者主页
    author_url = "https://github.com/honue"
    # 插件配置项ID前缀
    plugin_config_prefix = "trackereditor_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    _downloader_type: str = None
    _username: str = None
    _password: str = None
    _host: str = None
    _port: int = None
    _tracker_config: str = None

    _onlyonce: bool = False
    _downloader: Union[Qbittorrent, Transmission] = None

    _run_con_enable: bool = False
    _run_con: Optional[str] = None
    _notify: bool = False

    def init_plugin(self, config: dict = None):
        """恢复配置，并在执行一次后保存定时任务设置。"""
        if config:
            self._onlyonce = config.get("onlyonce")
            self._downloader_type = config.get("downloader_type")
            self._host = config.get("host")
            self._port = config.get("port")
            self._username = config.get("username")
            self._password = config.get("password")
            self._tracker_config = config.get("tracker_config")
            self._run_con_enable = config.get("run_con_enable", config.get("run_cron_enable", False))
            self._run_con = config.get("run_con", config.get("run_cron", ""))
            self._notify = config.get("notify")

        if self._onlyonce:
            # 执行替换
            self.task()
            self._onlyonce = False
            # 更新onlyonce属性
            self.__update_config()

    def task(self):
        """查询任务，仅提交发生变化的种子，分别累计成功、未变更和失败。"""
        rules = self._parse_rules()
        if not rules:
            logger.error("【TrackerEditor】: 没有有效的 Tracker 替换规则，已结束执行")
            return

        clients = {"qbittorrent": Qbittorrent, "transmission": Transmission}
        updates = {
            "qbittorrent": self._update_qbittorrent,
            "transmission": self._update_transmission,
        }
        client_type = clients.get(self._downloader_type)
        if client_type is None:
            logger.error("【TrackerEditor】: 请选择有效的下载器类型，已结束执行")
            return

        logger.info(f"【TrackerEditor】: 开始执行 Tracker 替换，下载器：{self._downloader_type}")
        try:
            self._downloader = client_type(self._host, self._port, self._username, self._password)
            torrents, error = self._downloader.get_torrents()
        except Exception as err:
            logger.error(f"【TrackerEditor】: 连接下载器或读取种子失败，原因：{self._safe_error(err)}")
            return
        if error or torrents is None:
            logger.error("【TrackerEditor】: 连接下载器或读取种子失败，请检查地址、用户名和密码")
            return

        success = skipped = failed = 0
        update = updates[self._downloader_type]
        for torrent in torrents:
            name = getattr(torrent, "name", None) or "未命名种子"
            try:
                changed = update(torrent, rules)
            except Exception as err:
                failed += 1
                logger.error(f"【TrackerEditor】: Tracker 替换失败：{name}，原因：{self._safe_error(err)}")
                continue
            if changed:
                success += 1
                logger.info(f"【TrackerEditor】: Tracker 替换成功：{name}")
            else:
                skipped += 1

        summary = f"扫描 {len(torrents)} 个种子，成功 {success} 个，未变更 {skipped} 个，失败 {failed} 个"
        logger.info(f"【TrackerEditor】: Tracker 替换完成：{summary}")
        if self._notify and (self._run_con_enable or self._onlyonce):
            self.send_site_message('【Tracker替换】', f"下载器：{self._downloader_type}\n{summary}")

    def _parse_rules(self) -> list[tuple[str, str]]:
        """忽略空行，拒绝空匹配文本，并保留规则的配置顺序。"""
        rules = []
        for number, line in enumerate((self._tracker_config or "").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split('|')
            if len(parts) != 2 or not all(part.strip() for part in parts):
                logger.error(f"【TrackerEditor】: 第 {number} 行替换规则无效，应为 待替换文本|替换文本")
                continue
            rules.append((parts[0].strip(), parts[1].strip()))
        return rules

    @staticmethod
    def _replace_tracker(url: str, rules: list[tuple[str, str]]) -> str:
        """只应用首条匹配规则，保持未命中地址及 URL 其他内容不变。"""
        for old, new in rules:
            if old in url:
                return url.replace(old, new)
        return url

    def _update_transmission(self, torrent: Any, rules: list[tuple[str, str]]) -> bool:
        """仅提交有变化的地址，由统一适配方法准备宿主需要的参数。"""
        original = list(torrent.tracker_list)
        updated = [self._replace_tracker(url, rules) for url in original]
        if updated == original:
            return False
        payload = self._transmission_tracker_list(updated)
        if not self._downloader.update_tracker(hash_string=torrent.hashString, tracker_list=payload):
            raise RuntimeError("下载器未确认 Tracker 修改成功")
        return True

    @staticmethod
    def _transmission_tracker_list(urls: list[str]) -> list[str] | list[list[str]]:
        """正式版 MP 3.2.0 起由宿主分组；旧版仍由调用方提供分组。"""
        if Version(APP_VERSION) >= Version("3.2.0"):
            return urls
        return [urls]

    def _update_qbittorrent(self, torrent: Any, rules: list[tuple[str, str]]) -> bool:
        """逐个提交有变化的 Tracker，由任务层统一按种子统计结果。"""
        changed = False
        for tracker in torrent.trackers:
            updated = self._replace_tracker(tracker.url, rules)
            if updated != tracker.url:
                torrent.edit_tracker(orig_url=tracker.url, new_url=updated)
                changed = True
        return changed

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """保留错误说明，隐藏异常文本中的 URL，避免记录 Tracker 密钥。"""
        return re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+", "[URL 已隐藏]", str(error))

    def __update_config(self):
        """使用与配置表单一致的字段名保存所有选项。"""
        self.update_config({
            "onlyonce": self._onlyonce,
            "downloader_type": self._downloader_type,
            "username": self._username,
            "password": self._password,
            "host": self._host,
            "port": self._port,
            "tracker_config": self._tracker_config,
            "run_con_enable": self._run_con_enable,
            "run_con": self._run_con,
            "notify": self._notify
        })

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不提供远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """本插件不提供额外 API。"""
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """提供下载器、替换规则与定时执行配置。"""
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
                                            'model': 'run_con_enable',
                                            'label': '定时执行',
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }]
                    }, {
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
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            }]
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
                                            'model': 'run_con',
                                            'label': 'cron表达式',
                                            'placeholder': '* * * * *'
                                        }
                                    }
                                ]
                            }, {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'downloader_type',
                                            'label': '下载器类型',
                                            'items': [
                                                {'title': 'Qbittorrent', 'value': 'qbittorrent'},
                                                {'title': 'Transmission', 'value': 'transmission'}
                                            ]
                                        }
                                    }
                                ]
                            }]
                    }, {
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
                                            'model': 'host',
                                            'label': 'host主机ip',
                                            'placeholder': '192.168.2.100'
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
                                            'model': 'port',
                                            'label': 'qb/tr端口',
                                            'placeholder': '8989'
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
                                            'model': 'username',
                                            'label': '用户名',
                                            'placeholder': 'username'
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
                                            'model': 'password',
                                            'label': '密码',
                                            'placeholder': 'password'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'tracker_config',
                                            'label': 'tracker替换配置',
                                            'rows': 6,
                                            'placeholder': '每一行一个配置，中间以|分隔\n'
                                                           '待替换文本|替换的文本',
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
                                            'text': '对下载器中所有符合代替换文本的tacker进行字符串replace替换' + '\n' +
                                                    '现有tracker: https://baidu.com/announce.php?passkey=xxxx' + '\n' +
                                                    '待替换 baidu.com 或 https://baidu.com' + '\n' +
                                                    '用于替换的文本 qq.com 或 https://qq.com' + '\n' +
                                                    '结果为 https://qq.com/announce.php?passkey=xxxx',
                                            'style': 'white-space: pre-line;'
                                        }
                                    },
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '强烈建议自己先添加一个tracker测试替换是否符合预期，程序是否正常运行',
                                            'style': 'white-space: pre-line;'
                                        }
                                    },
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '支持 qBittorrent 和 Transmission 4.0 及以上，适用于 MoviePilot V3。',
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
            "onlyonce": False,
            "downloader_type": "qbittorrent",
            "host": "192.168.2.100",
            "port": 8989,
            "username": "username",
            "password": "password",
            "tracker_config":"",
            "run_con_enable": False,
            "run_con": "",
            "notify": True
        }

    def get_page(self) -> List[dict]:
        """保留占位实现，让宿主直接打开设置页。"""
        pass

    def get_state(self) -> bool:
        """沿用原插件的启用状态显示。"""
        return True

    def stop_service(self):
        """调度由宿主服务管理，本插件没有额外后台任务。"""
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """按已保存配置向宿主注册定时替换任务。"""
        if self._run_con_enable and self._run_con:
            logger.info(f"【TrackerEditor】: 注册定时任务")
            return [
                {
                    "id": "TrackerChangeRun",
                    "name": "定时Tracker替换",
                    "trigger": CronTrigger.from_crontab(self._run_con),
                    "func": self.task,
                    "kwargs": {}
                }]

        return []

    def send_site_message(self, title, message):
        """使用宿主站点通知发送本轮执行结果。"""
        self.post_message(
            mtype=MessageType.SiteMessage,
            title=title,
            text=message
        )
