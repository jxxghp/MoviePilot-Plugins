from typing import List, Tuple, Dict, Any, Union, Optional

from apscheduler.triggers.cron import CronTrigger

from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from qbittorrentapi.torrents import TorrentInfoList
from app.modules.transmission import Transmission
from transmission_rpc.torrent import Torrent
from app.plugins import _PluginBase
from app.schemas import NotificationType


class TrackerEditor(_PluginBase):
    # 插件名称
    plugin_name = "Tracker替换"
    # 插件描述
    plugin_desc = "批量替换修改种子tracker"
    # 插件图标
    plugin_icon = "trackereditor_A.png"
    # 插件版本
    plugin_version = "1.9"
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
        if config:
            self._onlyonce = config.get("onlyonce")
            self._downloader_type = config.get("downloader_type")
            self._host = config.get("host")
            self._port = config.get("port")
            self._username = config.get("username")
            self._password = config.get("password")
            self._tracker_config = config.get("tracker_config")
            self._run_con_enable = config.get("run_con_enable")
            self._run_con = config.get("run_con")
            self._notify = config.get("notify")

        if self._onlyonce:
            # 执行替换
            self.task()
            self._onlyonce = False
            # 更新onlyonce属性
            self.__update_config()

    def task(self):
        tracker_configs: List[str] = self._tracker_config.split("\n")
        tracker_dict = {}
        for tracker_config in tracker_configs:
            if tracker_config.count('|') == 1:
                tracker_dict[tracker_config.split('|')[0]] = tracker_config.split('|')[1]
            else:
                logger.error(f"配置行错误: {tracker_config}")
        logger.info(f"【TrackerEditor】: 开始执行Tracker替换")
        torrent_total_cnt: int = 0
        torrent_update_cnt: int = 0
        if self._downloader_type == "qbittorrent":
            self._downloader = Qbittorrent(self._host, self._port, self._username, self._password)
            torrent_info_list: TorrentInfoList
            torrent_info_list, error = self._downloader.get_torrents()
            torrent_total_cnt = len(torrent_info_list)
            if error:
                return
            for torrent in torrent_info_list:
                for tracker in torrent.trackers:
                    for target_domain in tracker_dict.keys():
                        if target_domain in tracker.url:
                            original_url = tracker.url
                            new_url = tracker.url.replace(target_domain, tracker_dict[target_domain])
                            logger.info(f"{original_url[:30]}... 替换为 {new_url[:30]}...")
                            torrent.edit_tracker(orig_url=original_url, new_url=new_url)
                            torrent_update_cnt += 1

        elif self._downloader_type == "transmission":
            self._downloader = Transmission(self._host, self._port, self._username, self._password)
            tr_version = self._downloader.get_session().get('version')
            # "4.0.3 (6b0e49bbb2)"  "3.00 (bb6b5a062e)"
            torrent_list: List[Torrent]
            torrent_list, error = self._downloader.get_torrents()
            torrent_total_cnt = len(torrent_list)
            if error:
                return
            for torrent in torrent_list:
                new_tracker_list = []
                for tracker in torrent.tracker_list:
                    tracker_replaced = False
                    for target_domain in tracker_dict.keys():
                        if target_domain in tracker:
                            new_url = tracker.replace(target_domain, tracker_dict[target_domain])
                            new_tracker_list.append(new_url)
                            logger.info(f"{tracker[:30]}... 替换为 {new_url[:30]}...")
                            torrent_update_cnt += 1
                            tracker_replaced = True
                            break
                    if not tracker_replaced:
                        new_tracker_list.append(tracker)
                if int(tr_version[0]) >= 4:
                    # 版本大于等于4.x
                    __tracker_list = [new_tracker_list]
                else:
                    __tracker_list = new_tracker_list
                if torrent_update_cnt > 0:
                    update_result = self._downloader.update_tracker(hash_string=torrent.hashString, tracker_list=__tracker_list)
                    if not update_result:
                        logger.error(f"执行tracker修改出错，中止本次执行")
                        torrent_update_cnt = 0
                        break
            if torrent_update_cnt == 0:
                logger.info(f"tracker修改条数为0")
        logger.info(f"【TrackerEditor】: Tracker替换完成")
        if (self._run_con_enable and self._notify) or (self._onlyonce and self._notify):
            title = '【Tracker替换】'
            msg = f'''扫描下载器{self._downloader_type}\n总的种子数: {torrent_total_cnt}\n已修改种子数: {torrent_update_cnt}'''
            self.send_site_message(title, msg)

    def __update_config(self):
        self.update_config({
            "onlyonce": self._onlyonce,
            "downloader_type": self._downloader_type,
            "username": self._username,
            "password": self._password,
            "host": self._host,
            "port": self._port,
            "tracker_config": self._tracker_config,
            "run_cron_enable": self._run_con_enable,
            "run_cron": self._run_con,
            "notify": self._notify
        })

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
                                            'text': '支持qb，tr仅支持4.0以上版本' + '\n',
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
        pass

    def get_state(self) -> bool:
        return True

    def stop_service(self):
        pass

    def get_service(self) -> List[Dict[str, Any]]:
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
        self.post_message(
            mtype=NotificationType.SiteMessage,
            title=title,
            text=message
        )