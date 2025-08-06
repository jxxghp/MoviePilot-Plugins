import os
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, List, Dict, Tuple, Optional, Union

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from bencode import bdecode, bencode
from qbittorrentapi import TorrentDictionary

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.utils.string import StringUtils


class TorrentTransfer(_PluginBase):
    # 插件名称
    plugin_name = "自动转移做种"
    # 插件描述
    plugin_desc = "定期转移下载器中的做种任务到另一个下载器。"
    # 插件图标
    plugin_icon = "seed.png"
    # 插件版本
    plugin_version = "1.10.2"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "torrenttransfer_"
    # 加载顺序
    plugin_order = 18
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _scheduler = None

    # 开关
    _enabled = False
    _cron = None
    _onlyonce = False
    _fromdownloader = None
    _todownloader = None
    _frompath = None
    _topath = None
    _notify = False
    _nolabels = None
    _includelabels = None
    _includecategory = None
    _nopaths = None
    _deletesource = False
    _deleteduplicate = False
    _fromtorrentpath = None
    _autostart = False
    _skipverify = False
    _transferemptylabel = False
    _add_torrent_tags = None
    _remainoldcat = False
    _remainoldtag = False
    # 退出事件
    _event = Event()
    # 待检查种子清单
    _recheck_torrents = {}
    _is_recheck_running = False
    # 任务标签
    _torrent_tags = []

    def init_plugin(self, config: dict = None):

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._nolabels = config.get("nolabels")
            self._includelabels = config.get("includelabels")
            self._includecategory = config.get("includecategory")
            self._frompath = config.get("frompath")
            self._topath = config.get("topath")
            self._fromdownloader = config.get("fromdownloader")
            self._todownloader = config.get("todownloader")
            self._deletesource = config.get("deletesource")
            self._deleteduplicate = config.get("deleteduplicate")
            self._fromtorrentpath = config.get("fromtorrentpath")
            self._nopaths = config.get("nopaths")
            self._autostart = config.get("autostart")
            self._skipverify = config.get("skipverify")
            self._transferemptylabel = config.get("transferemptylabel")
            self._add_torrent_tags = config.get("add_torrent_tags") or ""
            self._torrent_tags = self._add_torrent_tags.strip().split(",") if self._add_torrent_tags else []
            self._remainoldcat = config.get("remainoldcat")
            self._remainoldtag = config.get("remainoldtag")

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:
            if not self.__validate_config():
                self._enabled = False
                self._onlyonce = False
                config["enabled"] = self._enabled
                config["onlyonce"] = self._onlyonce
                self.update_config(config=config)
                return

            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._autostart:
                # 追加种子校验服务
                self._scheduler.add_job(self.check_recheck, 'interval', minutes=0.5)

            if self._onlyonce:
                logger.info(f"转移做种服务启动，立即运行一次")
                self._scheduler.add_job(self.transfer, 'date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(
                                            seconds=3))
                self._onlyonce = False
                config["onlyonce"] = self._onlyonce
                self.update_config(config=config)
            # 启动服务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    @staticmethod
    def service_info(name: str) -> Optional[ServiceInfo]:
        """
        服务信息
        """
        if not name:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        service = DownloaderHelper().get_service(name)
        if not service or not service.instance:
            logger.warning(f"获取下载器 {name} 实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            logger.warning(f"下载器 {name} 未连接，请检查配置")
            return None

        return service

    def get_state(self):
        return True if self._enabled \
                       and self._cron \
                       and self._fromdownloader \
                       and self._todownloader \
                       and self._fromtorrentpath else False

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
        if self.get_state():
            return [
                {
                    "id": "TorrentTransfer",
                    "name": "转移做种服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.transfer,
                    "kwargs": {}
                }
            ]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        downloader_options = [{"title": config.name, "value": config.name}
                              for config in DownloaderHelper().get_configs().values()]
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
                                    'md': 3
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
                                    'md': 3
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
                                            'model': 'transferemptylabel',
                                            'label': '转移无标签种子',
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
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '0 0 0 ? *'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'add_torrent_tags',
                                            'label': '添加种子标签',
                                            'placeholder': '已整理,转移做种'
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'includecategory',
                                            'label': '转移种子分类',
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
                                            'model': 'nolabels',
                                            'label': '不转移种子标签',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'includelabels',
                                            'label': '转移种子标签',
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'fromdownloader',
                                            'label': '源下载器',
                                            'items': downloader_options
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
                                            'model': 'fromtorrentpath',
                                            'label': '源下载器种子文件路径',
                                            'placeholder': 'BT_backup、torrents'
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
                                            'model': 'frompath',
                                            'label': '源数据文件根路径',
                                            'placeholder': '根路径，留空不进行路径转换'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'todownloader',
                                            'label': '目的下载器',
                                            'items': downloader_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'topath',
                                            'label': '目的数据文件根路径',
                                            'placeholder': '根路径，留空不进行路径转换'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'nopaths',
                                            'label': '不转移数据文件目录',
                                            'rows': 3,
                                            'placeholder': '每一行一个目录'
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'autostart',
                                            'label': '校验完成后自动开始',
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "skipverify",
                                            "label": "跳过校验(仅QB有效)",
                                        },
                                    }
                                ],
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
                                            'model': 'deletesource',
                                            'label': '删除源种子',
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
                                            'model': 'deleteduplicate',
                                            'label': '删除重复种子',
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
                                            'model': 'remainoldcat',
                                            'label': '保留原分类',
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
                                            'model': 'remainoldtag',
                                            'label': '保留原标签',
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
            "notify": False,
            "onlyonce": False,
            "cron": "",
            "nolabels": "",
            "includelabels": "",
            "includecategory": "",
            "frompath": "",
            "topath": "",
            "fromdownloader": "",
            "todownloader": "",
            "deletesource": False,
            "deleteduplicate": False,
            "fromtorrentpath": "",
            "nopaths": "",
            "autostart": True,
            "skipverify": False,
            "transferemptylabel": False,
            "add_torrent_tags": "已整理,转移做种",
            "remainoldcat": False,
            "remainoldtag": False
        }

    def get_page(self) -> List[dict]:
        pass

    def __validate_config(self) -> bool:
        """
        校验配置
        """
        # 检查配置
        if self._fromtorrentpath and not Path(self._fromtorrentpath).exists():
            logger.error(f"源下载器种子文件保存路径不存在：{self._fromtorrentpath}")
            self.systemmessage.put(f"源下载器种子文件保存路径不存在：{self._fromtorrentpath}", title="自动转移做种")
            return False
        if self._fromdownloader == self._todownloader:
            logger.error(f"源下载器和目的下载器不能相同")
            self.systemmessage.put(f"源下载器和目的下载器不能相同", title="自动转移做种")
            return False
        return True

    def __download(self, service: ServiceInfo, content: bytes,
                   save_path: str, torrent: TorrentDictionary) -> Optional[str]:
        """
        添加下载任务
        """
        if not service or not service.instance:
            return
        downloader = service.instance
        from_service = self.service_info(self._fromdownloader)
        downloader_helper = DownloaderHelper()
        if downloader_helper.is_downloader("qbittorrent", service=service):
            # 生成随机Tag
            tag = StringUtils.generate_random_str(10)
            if self._remainoldtag:
                # 获取种子标签
                torrent_labels = self.__get_label(torrent, from_service.type)
                new_tag = list(set(torrent_labels + self._torrent_tags + [tag]))
            else:
                new_tag = self._torrent_tags + [tag]
            if self._remainoldcat:
                # 获取种子分类
                torrent_category = self.__get_category(torrent, from_service.type)
            else:
                torrent_category = None
            state = downloader.add_torrent(content=content,
                                           download_dir=save_path,
                                           is_paused=True,
                                           tag=new_tag,
                                           category=torrent_category,
                                           is_skip_checking=self._skipverify)
            if not state:
                return None
            else:
                # 获取种子Hash
                torrent_hash = downloader.get_torrent_id_by_tag(tags=tag)
                if not torrent_hash:
                    logger.error(f"{downloader} 下载任务添加成功，但获取任务信息失败！")
                    return None
            return torrent_hash
        elif downloader_helper.is_downloader("transmission", service=service):
            # 添加任务
            if self._remainoldtag:
                # 获取种子标签
                torrent_labels = self.__get_label(torrent, from_service.type)
                new_tag = list(set(torrent_labels + self._torrent_tags))
            else:
                new_tag = self._torrent_tags
            torrent = downloader.add_torrent(content=content,
                                             download_dir=save_path,
                                             is_paused=True,
                                             labels=new_tag)
            if not torrent:
                return None
            else:
                return torrent.hashString

        logger.error(f"不支持的下载器类型")
        return None

    def transfer(self):
        """
        开始转移做种
        """
        logger.info("开始转移做种任务 ...")

        if not self.__validate_config():
            return

        from_service = self.service_info(self._fromdownloader)
        from_downloader: Optional[Union[Qbittorrent, Transmission]] = from_service.instance if from_service else None
        to_service = self.service_info(self._todownloader)
        to_downloader: Optional[Union[Qbittorrent, Transmission]] = to_service.instance if to_service else None

        if not from_downloader or not to_downloader:
            return

        torrents = from_downloader.get_completed_torrents()
        if torrents:
            logger.info(f"下载器 {from_service.name} 已做种的种子数：{len(torrents)}")
        else:
            logger.info(f"下载器 {from_service.name} 没有已做种的种子")
            return

        # 过滤种子，记录保存目录
        trans_torrents = []
        for torrent in torrents:
            if self._event.is_set():
                logger.info(f"转移服务停止")
                return

            # 获取种子hash
            hash_str = self.__get_hash(torrent, from_service.type)
            # 获取保存路径
            save_path = self.__get_save_path(torrent, from_service.type)

            if self._nopaths and save_path:
                # 过滤不需要转移的路径
                nopath_skip = False
                for nopath in self._nopaths.split('\n'):
                    if os.path.normpath(save_path).startswith(os.path.normpath(nopath)):
                        logger.info(f"种子 {hash_str} 保存路径 {save_path} 不需要转移，跳过 ...")
                        nopath_skip = True
                        break
                if nopath_skip:
                    continue

            # 获取种子标签
            torrent_labels = self.__get_label(torrent, from_service.type)
            # 获取种子分类
            torrent_category = self.__get_category(torrent, from_service.type)
            # 种子为无标签,则进行规范化
            is_torrent_labels_empty = torrent_labels == [''] or torrent_labels == [] or torrent_labels is None
            if is_torrent_labels_empty:
                torrent_labels = []

            # 如果分类项存在数值，则进行判断
            if self._includecategory:
                # 排除未标记的分类
                if torrent_category not in self._includecategory.split(','):
                    logger.info(f"种子 {hash_str} 不含有转移分类 {self._includecategory}，跳过 ...")
                    continue
            # 根据设置决定是否转移无标签的种子
            if is_torrent_labels_empty:
                if not self._transferemptylabel:
                    continue
            else:
                # 排除含有不转移的标签
                if self._nolabels:
                    is_skip = False
                    for label in self._nolabels.split(','):
                        if label in torrent_labels:
                            logger.info(f"种子 {hash_str} 含有不转移标签 {label}，跳过 ...")
                            is_skip = True
                            break
                    if is_skip:
                        continue
                # 排除不含有转移标签的种子
                if self._includelabels:
                    is_skip = False
                    for label in self._includelabels.split(','):
                        if label not in torrent_labels:
                            logger.info(f"种子 {hash_str} 不含有转移标签 {label}，跳过 ...")
                            is_skip = True
                            break
                    if is_skip:
                        continue

            # 添加转移数据
            trans_torrents.append({
                "hash": hash_str,
                "save_path": save_path,
                "torrent": torrent
            })

        # 开始转移任务
        if trans_torrents:
            logger.info(f"需要转移的种子数：{len(trans_torrents)}")
            # 记数
            total = len(trans_torrents)
            # 总成功数
            success = 0
            # 总失败数
            fail = 0
            # 跳过数
            skip = 0
            # 删除重复数
            del_dup = 0

            downloader_helper = DownloaderHelper()
            for torrent_item in trans_torrents:
                # 检查种子文件是否存在
                torrent_file = Path(self._fromtorrentpath) / f"{torrent_item.get('hash')}.torrent"
                if not torrent_file.exists():
                    logger.error(f"种子文件不存在：{torrent_file}")
                    # 失败计数
                    fail += 1
                    continue

                # 查询hash值是否已经在目的下载器中
                torrent_info, _ = to_downloader.get_torrents(ids=[torrent_item.get('hash')])
                if torrent_info:
                    # 删除重复的源种子，不能删除文件！
                    if self._deleteduplicate:
                        logger.info(f"删除重复的源下载器任务（不含文件）：{torrent_item.get('hash')} ...")
                        from_downloader.delete_torrents(delete_file=False, ids=[torrent_item.get('hash')])
                        del_dup += 1
                    else:
                        logger.info(f"{torrent_item.get('hash')} 已在目的下载器中，跳过 ...")
                        # 跳过计数
                        skip += 1
                    continue

                # 转换保存路径
                download_dir = self.__convert_save_path(torrent_item.get('save_path'),
                                                        self._frompath,
                                                        self._topath)
                if not download_dir:
                    logger.error(f"转换保存路径失败：{torrent_item.get('save_path')}")
                    # 失败计数
                    fail += 1
                    continue

                # 如果源下载器是QB检查是否有Tracker，没有的话额外获取
                if downloader_helper.is_downloader("qbittorrent", service=from_service):
                    # 读取种子内容、解析种子文件
                    content = torrent_file.read_bytes()
                    if not content:
                        logger.warn(f"读取种子文件失败：{torrent_file}")
                        fail += 1
                        continue
                    # 读取trackers
                    try:
                        torrent_main = bdecode(content)
                        main_announce = torrent_main.get('announce')
                    except Exception as err:
                        logger.warn(f"解析种子文件 {torrent_file} 失败：{str(err)}")
                        fail += 1
                        continue

                    if not main_announce:
                        logger.info(f"{torrent_item.get('hash')} 未发现tracker信息，尝试补充tracker信息...")
                        # 读取fastresume文件
                        fastresume_file = Path(self._fromtorrentpath) / f"{torrent_item.get('hash')}.fastresume"
                        if not fastresume_file.exists():
                            logger.warn(f"fastresume文件不存在：{fastresume_file}")
                            fail += 1
                            continue
                        # 尝试补充trackers
                        try:
                            # 解析fastresume文件
                            fastresume = fastresume_file.read_bytes()
                            torrent_fastresume = bdecode(fastresume)
                            # 读取trackers
                            fastresume_trackers = torrent_fastresume.get('trackers')
                            if isinstance(fastresume_trackers, list) \
                                    and len(fastresume_trackers) > 0 \
                                    and fastresume_trackers[0]:
                                # 重新赋值
                                torrent_main['announce'] = fastresume_trackers[0][0]
                                # 保留其他tracker，避免单一tracker无法连接
                                if len(fastresume_trackers) > 1 or len(fastresume_trackers[0]) > 1:
                                    torrent_main['announce-list'] = fastresume_trackers
                                # 替换种子文件路径
                                torrent_file = settings.TEMP_PATH / f"{torrent_item.get('hash')}.torrent"
                                # 编码并保存到临时文件
                                torrent_file.write_bytes(bencode(torrent_main))
                        except Exception as err:
                            logger.error(f"解析fastresume文件 {fastresume_file} 出错：{str(err)}")
                            fail += 1
                            continue

                # 发送到另一个下载器中下载：默认暂停、传输下载路径、关闭自动管理模式
                logger.info(f"添加转移做种任务到下载器 {to_service.name}：{torrent_file}")
                download_id = self.__download(service=to_service,
                                              content=torrent_file.read_bytes(),
                                              save_path=download_dir,
                                              torrent=torrent_item.get('torrent'))
                if not download_id:
                    # 下载失败
                    fail += 1
                    logger.error(f"添加下载任务失败：{torrent_file}")
                    continue
                else:
                    # 下载成功
                    logger.info(f"成功添加转移做种任务，种子文件：{torrent_file}")

                    # TR会自动校验，QB需要手动校验
                    if downloader_helper.is_downloader("qbittorrent", service=to_service):
                        if self._skipverify:
                            if self._autostart:
                                logger.info(f"{download_id} 跳过校验，开启自动开始，注意观察种子的完整性")
                                self.__add_recheck_torrents(to_service, download_id)
                            else:
                                # 跳过校验
                                logger.info(f"{download_id} 跳过校验，请自行检查手动开始任务...")
                        else:
                            logger.info(f"qbittorrent 开始校验 {download_id} ...")
                            to_downloader.recheck_torrents(ids=[download_id])
                            self.__add_recheck_torrents(to_service, download_id)
                    else:
                        self.__add_recheck_torrents(to_service, download_id)

                    # 删除源种子，不能删除文件！
                    if self._deletesource:
                        logger.info(f"删除源下载器任务（不含文件）：{torrent_item.get('hash')} ...")
                        from_downloader.delete_torrents(delete_file=False, ids=[torrent_item.get('hash')])

                    # 成功计数
                    success += 1
                    # 插入转种记录
                    history_key = f"{from_service.name}-{torrent_item.get('hash')}"
                    self.save_data(key=history_key,
                                   value={
                                       "to_download": to_service.name,
                                       "to_download_id": download_id,
                                       "delete_source": self._deletesource,
                                       "delete_duplicate": self._deleteduplicate,
                                   })
            # 触发校验任务
            if success > 0 and self._autostart:
                self.check_recheck()

            # 发送通知
            if self._notify:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title="【转移做种任务执行完成】",
                    text=f"总数：{total}，成功：{success}，失败：{fail}，跳过：{skip}，删除重复：{del_dup}"
                )
        else:
            logger.info(f"没有需要转移的种子")
        logger.info("转移做种任务执行完成")

    def __add_recheck_torrents(self, service: ServiceInfo, download_id: str):
        # 追加校验任务
        logger.info(f"添加校验检查任务：{download_id} ...")
        if not self._recheck_torrents.get(service.name):
            self._recheck_torrents[service.name] = []
        self._recheck_torrents[service.name].append(download_id)

    def check_recheck(self):
        """
        定时检查下载器中种子是否校验完成，校验完成且完整的自动开始辅种
        """
        if not self._recheck_torrents:
            return
        if not self._todownloader:
            return
        if self._is_recheck_running:
            return

        # 校验下载器
        to_service = self.service_info(self._todownloader)
        to_downloader: Optional[Union[Qbittorrent, Transmission]] = to_service.instance if to_service else None

        if not to_downloader:
            return

        # 需要检查的种子
        recheck_torrents = self._recheck_torrents.get(to_service.name, [])
        if not recheck_torrents:
            return

        logger.info(f"开始检查下载器 {to_service.name} 的校验任务 ...")

        # 运行状态
        self._is_recheck_running = True

        torrents, _ = to_downloader.get_torrents(ids=recheck_torrents)
        if torrents:
            # 可做种的种子
            can_seeding_torrents = []
            for torrent in torrents:
                # 获取种子hash
                hash_str = self.__get_hash(torrent, to_service.type)
                # 判断是否可做种
                if self.__can_seeding(torrent, to_service.type):
                    can_seeding_torrents.append(hash_str)

            if can_seeding_torrents:
                logger.info(f"共 {len(can_seeding_torrents)} 个任务校验完成，开始做种")
                # 开始做种
                to_downloader.start_torrents(ids=can_seeding_torrents)
                # 去除已经处理过的种子
                self._recheck_torrents[to_service.name] = list(
                    set(recheck_torrents).difference(set(can_seeding_torrents)))
            else:
                logger.info(f"没有新的任务校验完成，将在下次个周期继续检查 ...")

        elif torrents is None:
            logger.info(f"下载器 {to_service.name} 查询校验任务失败，将在下次继续查询 ...")
        else:
            logger.info(f"下载器 {to_service.name} 中没有需要检查的校验任务，清空待处理列表")
            self._recheck_torrents[to_service.name] = []

        self._is_recheck_running = False

    @staticmethod
    def __get_hash(torrent: Any, dl_type: str):
        """
        获取种子hash
        """
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def __get_label(torrent: Any, dl_type: str):
        """
        获取种子标签
        """
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if dl_type == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    @staticmethod
    def __get_category(torrent: Any, dl_type: str):
        """
        获取种子分类
        """
        try:
            return torrent.get("category").strip() \
                if dl_type == "qbittorrent" else ""
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def __get_save_path(torrent: Any, dl_type: str):
        """
        获取种子保存路径
        """
        try:
            return torrent.get("save_path") if dl_type == "qbittorrent" else torrent.download_dir
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def __can_seeding(torrent: Any, dl_type: str):
        """
        判断种子是否可以做种并处于暂停状态
        """
        try:
            return (torrent.get("state") in ["pausedUP", "stoppedUP"]) if dl_type == "qbittorrent" \
                else (torrent.status.stopped and torrent.percent_done == 1)
        except Exception as e:
            print(str(e))
            return False

    @staticmethod
    def __convert_save_path(save_path: str, from_root: str, to_root: str):
        """
        转换保存路径
        """
        try:
            # 没有保存目录，以目的根目录为准
            if not save_path:
                return to_root
            # 没有设置根目录时返回save_path
            if not to_root or not from_root:
                return save_path
            # 统一目录格式
            save_path = os.path.normpath(save_path).replace("\\", "/")
            from_root = os.path.normpath(from_root).replace("\\", "/")
            to_root = os.path.normpath(to_root).replace("\\", "/")
            # 替换根目录
            if save_path.startswith(from_root):
                return save_path.replace(from_root, to_root, 1)
        except Exception as e:
            print(str(e))
        return None

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
