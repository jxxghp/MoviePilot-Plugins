import datetime
import re
import shutil
import threading
import time
import traceback
from pathlib import Path
from time import sleep
from typing import List, Tuple, Dict, Any, Optional
import pytz
import qbittorrentapi
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from app import schemas
from app.chain.media import MediaChain
from app.chain.tmdb import TmdbChain
from app.chain.transfer import TransferChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.plugins import _PluginBase
from app.plugins.vcbanimemonitor.remeta import ReMeta
from app.schemas import Notification, NotificationType, TransferInfo
from app.schemas.types import EventType, MediaType, SystemConfigKey
from app.utils.string import StringUtils
from app.utils.system import SystemUtils

lock = threading.Lock()


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控响应类
    """

    def __init__(self, monpath: str, sync: Any, **kwargs):
        super(FileMonitorHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.event_handler(event=event, text="创建",
                                mon_path=self._watch_path, event_path=event.src_path)

    def on_moved(self, event):
        self.sync.event_handler(event=event, text="移动",
                                mon_path=self._watch_path, event_path=event.dest_path)


class TorrentHandler(FileSystemEventHandler):
    def __init__(self, monpath: str, sync: Any, **kwargs):
        super(TorrentHandler, self).__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.torrent_event(event=event, text="创建",
                                mon_path=self._watch_path)

    def on_moved(self, event):
        self.sync.torrent_event(event=event, text="移动",
                                mon_path=self._watch_path)


class VCBAnimeMonitor(_PluginBase):
    # 插件名称
    plugin_name = "整理VCB动漫压制组作品"
    # 插件描述
    plugin_desc = "一款辅助整理&提高识别VCB-Stuido动漫压制组作品的插件"
    # 插件图标
    plugin_icon = "vcbmonitor.png"
    # 插件版本
    plugin_version = "1.8.2.2"
    # 插件作者
    plugin_author = "pixel@qingwa"
    # 作者主页
    author_url = "https://github.com/Pixel-LH"
    # 插件配置项ID前缀
    plugin_config_prefix = "vcbanimemonitor_"
    # 加载顺序
    plugin_order = 4
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _switch_ova = False
    _torrents_path = None
    new_save_path = None
    qb = None
    _scheduler = None
    transferhis = None
    downloadhis = None
    transferchian = None
    tmdbchain = None
    mediaChain = None
    _observer = []
    _enabled = False
    _notify = False
    _onlyonce = False
    _cron = None
    _size = 0
    _scrape = True
    # 模式 compatibility/fast
    _mode = "fast"
    # 转移方式
    _transfer_type = settings.TRANSFER_TYPE
    _monitor_dirs = ""
    _exclude_keywords = ""
    _interval: int = 10
    # 存储源目录与目的目录关系
    _dirconf: Dict[str, Optional[Path]] = {}
    # 存储源目录转移方式
    _transferconf: Dict[str, Optional[str]] = {}
    _medias = {}
    # 退出事件
    _event = threading.Event()

    def init_plugin(self, config: dict = None):
        self.transferhis = TransferHistoryOper()
        self.downloadhis = DownloadHistoryOper()
        self.transferchian = TransferChain()
        self.mediaChain = MediaChain()
        self.tmdbchain = TmdbChain()
        # 清空配置
        self._dirconf = {}
        self._transferconf = {}

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._mode = config.get("mode")
            self._transfer_type = config.get("transfer_type")
            self._monitor_dirs = config.get("monitor_dirs") or ""
            self._exclude_keywords = config.get("exclude_keywords") or ""
            self._interval = config.get("interval") or 10
            self._cron = config.get("cron")
            self._size = config.get("size") or 0
            self._scrape = config.get("scrape")
            self._switch_ova = config.get("ova")
            self._torrents_path = config.get("torrents_path") or ""

        # 停止现有任务
        self.stop_service()

        if self._enabled or self._onlyonce:
            # 定时服务管理器
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 追加入库消息统一发送服务
            self._scheduler.add_job(self.send_msg, trigger='interval', seconds=15)
            self.qb = Qbittorrent()

            # 读取目录配置
            monitor_dirs = self._monitor_dirs.split("\n")
            if not monitor_dirs:
                return

            # 启用种子目录监控
            if self._torrents_path and Path(self._torrents_path).exists() and self._enabled:
                # 只取第一个目录作为新的保存
                try:
                    first_path = monitor_dirs[0]
                    if SystemUtils.is_windows():
                        self.new_save_path = first_path.split(':')[0] + ":" + first_path.split(':')[1]
                    else:
                        self.new_save_path = first_path.split(':')[0]
                except Exception:
                    logger.error(f"目录保存失败,请检查输入目录是否合法")
                # print(self.new_save_path)
                try:
                    observer = Observer()
                    self._observer.append(observer)
                    observer.schedule(TorrentHandler(monpath=self._torrents_path, sync=self), path=self._torrents_path,
                                      recursive=True)
                    observer.daemon = True
                    observer.start()
                    logger.info(f"{self._torrents_path} 的种子目录监控服务启动，开启监控新增的VCB-Studio种子文件")
                except Exception as e:
                    logger.debug(f"{self._torrents_path} 启动种子目录监控失败：{str(e)}")
            else:
                logger.info("种子目录为空，不转移qb中正在下载的VCB-Studio文件")

            for mon_path in monitor_dirs:
                # 格式源目录:目的目录
                if not mon_path:
                    continue

                # 自定义转移方式
                _transfer_type = self._transfer_type
                if mon_path.count("#") == 1:
                    _transfer_type = mon_path.split("#")[1]
                    mon_path = mon_path.split("#")[0]

                # 存储目的目录
                if SystemUtils.is_windows():
                    if mon_path.count(":") > 1:
                        paths = [mon_path.split(":")[0] + ":" + mon_path.split(":")[1],
                                 mon_path.split(":")[2] + ":" + mon_path.split(":")[3]]
                    else:
                        paths = [mon_path]
                else:
                    paths = mon_path.split(":")

                # 目的目录
                target_path = None
                if len(paths) > 1:
                    mon_path = paths[0]
                    target_path = Path(paths[1])
                    self._dirconf[mon_path] = target_path
                else:
                    self._dirconf[mon_path] = None

                # 转移方式
                self._transferconf[mon_path] = _transfer_type

                # 启用目录监控
                if self._enabled:
                    # 检查媒体库目录是不是下载目录的子目录
                    try:
                        if target_path and target_path.is_relative_to(Path(mon_path)):
                            logger.warn(f"{target_path} 是监控目录 {mon_path} 的子目录，无法监控")
                            self.systemmessage.put(f"{target_path} 是下载目录 {mon_path} 的子目录，无法监控",
                                                   title="整理VCB动漫压制组作品")
                            continue
                    except Exception as e:
                        logger.debug(str(e))
                        pass

                    try:
                        if self._mode == "compatibility":
                            # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                            observer = PollingObserver(timeout=10)
                        else:
                            # 内部处理系统操作类型选择最优解
                            observer = Observer(timeout=10)
                        self._observer.append(observer)
                        observer.schedule(FileMonitorHandler(mon_path, self), path=mon_path, recursive=True)
                        observer.daemon = True
                        observer.start()
                        logger.info(f"{mon_path} 的目录监控服务启动")
                    except Exception as e:
                        err_msg = str(e)
                        if "inotify" in err_msg and "reached" in err_msg:
                            logger.warn(
                                f"目录监控服务启动出现异常：{err_msg}，请在宿主机上（不是docker容器内）执行以下命令并重启："
                                + """
                                     echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
                                     echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
                                     sudo sysctl -p
                                     """)
                        else:
                            logger.error(f"{mon_path} 启动目录监控失败：{err_msg}")
                        self.systemmessage.put(f"{mon_path} 启动目录监控失败：{err_msg}", title="整理VCB动漫压制组作品")

            # 运行一次定时服务
            if self._onlyonce:
                logger.info("目录监控服务启动，立即运行一次")
                self._scheduler.add_job(func=self.sync_all, trigger='date',
                                        run_date=datetime.datetime.now(
                                            tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                        )
                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.__update_config()

            # 启动定时服务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "mode": self._mode,
            "transfer_type": self._transfer_type,
            "monitor_dirs": self._monitor_dirs,
            "exclude_keywords": self._exclude_keywords,
            "interval": self._interval,
            "cron": self._cron,
            "size": self._size,
            "scrape": self._scrape,
            "ova": self._switch_ova,
            "torrents_path": self._torrents_path
        })

    def __save_data(self, key: str, value: Any):
        self.save_data(key, value)

    def __get_data(self, key: str):
        return self.get_data(key)

    def sync_all(self):
        """
        立即运行一次，全量同步目录中所有文件
        """
        logger.info("开始全量同步监控目录 ...")
        # 清空历史的ova记录
        self.plugindata.truncate()

        # 遍历所有监控目录
        for mon_path in self._dirconf.keys():
            # 遍历目录下所有文件
            for file_path in SystemUtils.list_files(Path(mon_path), settings.RMT_MEDIAEXT):
                self.__handle_file(event_path=str(file_path), mon_path=mon_path)

        logger.info("全量同步监控目录完成！")

    def event_handler(self, event, mon_path: str, text: str, event_path: str):
        """
        处理文件变化
        :param event: 事件
        :param mon_path: 监控目录
        :param text: 事件描述
        :param event_path: 事件文件路径
        """
        if not event.is_directory:
            # 文件发生变化
            logger.debug("文件%s：%s" % (text, event_path))
            self.__handle_file(event_path=event_path, mon_path=mon_path)

    def __handle_file(self, event_path: str, mon_path: str):
        """
        同步一个文件
        :param event_path: 事件文件路径
        :param mon_path: 监控目录
        """
        file_path = Path(event_path)
        try:
            if not file_path.exists():
                return
            # 全程加锁
            with lock:
                transfer_history = self.transferhis.get_by_src(event_path)
                if transfer_history:
                    logger.debug("文件已处理过：%s" % event_path)
                    return

                # 回收站及隐藏的文件不处理
                if event_path.find('/@Recycle/') != -1 \
                        or event_path.find('/#recycle/') != -1 \
                        or event_path.find('/.') != -1 \
                        or event_path.find('/@eaDir') != -1:
                    logger.debug(f"{event_path} 是回收站或隐藏的文件")
                    return

                # 命中过滤关键字不处理
                if self._exclude_keywords:
                    for keyword in self._exclude_keywords.split("\n"):
                        if keyword and re.findall(keyword, event_path):
                            logger.info(f"{event_path} 命中过滤关键字 {keyword}，不处理")
                            return

                # 整理屏蔽词不处理
                transfer_exclude_words = self.systemconfig.get(SystemConfigKey.TransferExcludeWords)
                if transfer_exclude_words:
                    for keyword in transfer_exclude_words:
                        if not keyword:
                            continue
                        if keyword and re.search(r"%s" % keyword, event_path, re.IGNORECASE):
                            logger.info(f"{event_path} 命中整理屏蔽词 {keyword}，不处理")
                            return

                # 不是媒体文件不处理
                if file_path.suffix not in settings.RMT_MEDIAEXT:
                    logger.debug(f"{event_path} 不是媒体文件")
                    return

                # 判断是不是蓝光目录
                bluray_flag = False
                if re.search(r"BDMV[/\\]STREAM", event_path, re.IGNORECASE):
                    bluray_flag = True
                    # 截取BDMV前面的路径
                    blurray_dir = event_path[:event_path.find("BDMV")]
                    file_path = Path(blurray_dir)
                    logger.info(f"{event_path} 是蓝光目录，更正文件路径为：{str(file_path)}")

                # 查询历史记录，已转移的不处理
                if self.transferhis.get_by_src(str(file_path)):
                    logger.info(f"{file_path} 已整理过")
                    return

                # 元数据
                if file_path.parent.name.lower() in ["sps", "scans", "cds", "previews", "extras"]:
                    logger.warn("位于特典或其他特殊目录下，跳过处理")
                    return

                if 'VCB-Studio' not in file_path.stem.strip():
                    logger.warn("不属于VCB的作品，不处理！")
                    return

                remeta = ReMeta(ova_switch=self._switch_ova)
                file_meta = remeta.handel_file(file_path=file_path)
                if file_meta:
                    if not file_meta.name:
                        logger.error(f"{file_path.name} 无法识别有效信息")
                        return
                    if remeta.is_ova and not self._switch_ova:
                        logger.warn(f"{file_path.name} 为OVA资源，未开启OVA开关，不处理")
                        return
                    if remeta.is_ova and self._switch_ova:
                        logger.info(f"{file_path.name} 为OVA资源,开始历史记录处理")
                        ova_history_ep_list = self.get_data(file_meta.title)
                        if ova_history_ep_list and isinstance(ova_history_ep_list, list):
                            ep = file_meta.begin_episode
                            if ep in ova_history_ep_list:
                                for i in range(1, 100):
                                    if ep + i not in ova_history_ep_list:
                                        ova_history_ep_list.append(ep + i)
                                        file_meta.begin_episode = ep + i
                                        logger.info(
                                            f"{file_path.name} 为OVA资源,历史记录中已存在，自动识别为第{ep + i}集")
                                        break
                            else:
                                ova_history_ep_list.append(ep)
                            self.save_data(file_meta.title, ova_history_ep_list)
                        else:
                            self.save_data(file_meta.title, [file_meta.begin_episode])
                else:
                    return

                # 判断文件大小
                if self._size and float(self._size) > 0 and file_path.stat().st_size < float(self._size) * 1024 ** 3:
                    logger.info(f"{file_path} 文件大小小于监控文件大小，不处理")
                    return

                # 查询转移目的目录
                target: Path = self._dirconf.get(mon_path)
                # 查询转移方式
                transfer_type = self._transferconf.get(mon_path)

                # 根据父路径获取下载历史
                download_history = None
                if bluray_flag:
                    # 蓝光原盘，按目录名查询
                    # FIXME 理论上DownloadHistory表中的path应该是全路径，但实际表中登记的数据只有目录名，暂按目录名查询
                    download_history = self.downloadhis.get_by_path(file_path.name)
                else:
                    # 按文件全路径查询
                    download_file = self.downloadhis.get_file_by_fullpath(str(file_path))
                    if download_file:
                        download_history = self.downloadhis.get_by_hash(download_file.download_hash)

                # 识别媒体信息
                if download_history and download_history.tmdbid:
                    mediainfo: MediaInfo = self.mediaChain.recognize_media(mtype=MediaType(download_history.type),
                                                                           tmdbid=download_history.tmdbid,
                                                                           doubanid=download_history.doubanid)
                else:
                    mediainfo: MediaInfo = self.mediaChain.recognize_by_meta(file_meta)

                if not mediainfo:
                    logger.warn(f'未识别到媒体信息，标题：{file_meta.name}')
                    # self.save_data(plugin_id="vcbanimemonitor", key=file_meta.title, value="null")
                    # 新增转移成功历史记录
                    his = self.transferhis.add_fail(
                        src_path=file_path,
                        mode=transfer_type,
                        meta=file_meta
                    )
                    if self._notify:
                        self.chain.post_message(Notification(
                            mtype=NotificationType.Manual,
                            title=f"{file_path.name} 未识别到媒体信息，无法入库！\n"
                                  f"回复：```\n/redo {his.id} [tmdbid]|[类型]\n``` 手动识别转移。"
                        ))
                    return

                # 如果未开启新增已入库媒体是否跟随TMDB信息变化则根据tmdbid查询之前的title
                if not settings.SCRAP_FOLLOW_TMDB:
                    transfer_history = self.transferhis.get_by_type_tmdbid(tmdbid=mediainfo.tmdb_id,
                                                                           mtype=mediainfo.type.value)
                    if transfer_history:
                        mediainfo.title = transfer_history.title
                logger.info(f"{file_path.name} 识别为：{mediainfo.type.value} {mediainfo.title_year}")

                # 更新媒体图片
                self.chain.obtain_images(mediainfo=mediainfo)

                # 获取集数据
                if mediainfo.type == MediaType.TV:
                    episodes_info = self.tmdbchain.tmdb_episodes(tmdbid=mediainfo.tmdb_id,
                                                                 season=file_meta.begin_season or 1)
                else:
                    episodes_info = None

                # 获取下载Hash
                download_hash = None
                if download_history:
                    download_hash = download_history.download_hash

                # 转移
                transferinfo: TransferInfo = self.chain.transfer(mediainfo=mediainfo,
                                                                 path=file_path,
                                                                 transfer_type=transfer_type,
                                                                 target=target,
                                                                 meta=file_meta,
                                                                 episodes_info=episodes_info)

                if not transferinfo:
                    logger.error("文件转移模块运行失败")
                    return

                if not transferinfo.success:
                    # 转移失败
                    logger.warn(f"{file_path.name} 入库失败：{transferinfo.message}")
                    # 新增转移失败历史记录
                    self.transferhis.add_fail(
                        src_path=file_path,
                        mode=transfer_type,
                        download_hash=download_hash,
                        meta=file_meta,
                        mediainfo=mediainfo,
                        transferinfo=transferinfo
                    )
                    if self._notify:
                        self.chain.post_message(Notification(
                            mtype=NotificationType.Manual,
                            title=f"{mediainfo.title_year}{file_meta.season_episode} 入库失败！",
                            text=f"原因：{transferinfo.message or '未知'}",
                            image=mediainfo.get_message_image()
                        ))
                    return

                # 新增转移成功历史记录
                self.transferhis.add_success(
                    src_path=file_path,
                    mode=transfer_type,
                    download_hash=download_hash,
                    meta=file_meta,
                    mediainfo=mediainfo,
                    transferinfo=transferinfo
                )

                # 刮削单个文件
                if self._scrape:
                    self.chain.scrape_metadata(path=transferinfo.target_path,
                                               mediainfo=mediainfo,
                                               transfer_type=transfer_type)

                """
                {
                    "title_year season": {
                        "files": [
                            {
                                "path":,
                                "mediainfo":,
                                "file_meta":,
                                "transferinfo":
                            }
                        ],
                        "time": "2023-08-24 23:23:23.332"
                    }
                }
                """
                # 发送消息汇总
                media_list = self._medias.get(mediainfo.title_year + " " + file_meta.season) or {}
                if media_list:
                    media_files = media_list.get("files") or []
                    if media_files:
                        file_exists = False
                        for file in media_files:
                            if str(file_path) == file.get("path"):
                                file_exists = True
                                break
                        if not file_exists:
                            media_files.append({
                                "path": str(file_path),
                                "mediainfo": mediainfo,
                                "file_meta": file_meta,
                                "transferinfo": transferinfo
                            })
                    else:
                        media_files = [
                            {
                                "path": str(file_path),
                                "mediainfo": mediainfo,
                                "file_meta": file_meta,
                                "transferinfo": transferinfo
                            }
                        ]
                    media_list = {
                        "files": media_files,
                        "time": datetime.datetime.now()
                    }
                else:
                    media_list = {
                        "files": [
                            {
                                "path": str(file_path),
                                "mediainfo": mediainfo,
                                "file_meta": file_meta,
                                "transferinfo": transferinfo
                            }
                        ],
                        "time": datetime.datetime.now()
                    }
                self._medias[mediainfo.title_year + " " + file_meta.season] = media_list

                # 广播事件
                self.eventmanager.send_event(EventType.TransferComplete, {
                    'meta': file_meta,
                    'mediainfo': mediainfo,
                    'transferinfo': transferinfo
                })

                # 移动模式删除空目录
                if transfer_type == "move":
                    for file_dir in file_path.parents:
                        if len(str(file_dir)) <= len(str(Path(mon_path))):
                            # 重要，删除到监控目录为止
                            break
                        files = SystemUtils.list_files(file_dir, settings.RMT_MEDIAEXT)
                        if not files:
                            logger.warn(f"移动模式，删除空目录：{file_dir}")
                            shutil.rmtree(file_dir, ignore_errors=True)

        except Exception as e:
            logger.error("目录监控发生错误：%s - %s" % (str(e), traceback.format_exc()))

    def torrent_event(self, event, mon_path: str, text: str):
        """
        处理种子文件
        :param mon_path: 种子目录
        """
        evc_path = Path(event.src_path)
        if not event.is_directory and (evc_path.suffix == ".torrent" or str(evc_path).split('.')[1] == "torrent"):
            # 文件发生变化
            logger.debug("文件%s：%s" % (text, mon_path))
            self.__handle_torrent(torrent_path=self._torrents_path)
        else:
            logger.debug("不是种子文件：%s" % mon_path)

    def __handle_torrent(self, torrent_path: str):
        torrent_path = Path(torrent_path)
        try:
            if not torrent_path.exists():
                return
                # 只处理刚刚添加的种子也就是获取正在下载的种子
            # 等待种子文件下载完成
            time.sleep(5)
            with lock:
                torrents = self.qb.get_downloading_torrents()
                for torrent in torrents:
                    if "VCB-Studio" in torrent.name:
                        logger.info(f"开始转移qb中正在下载的VCB资源,转移目录为：{self.new_save_path}")
                        # 原本存在的暂停的种子不处理
                        if torrent.state_enum == qbittorrentapi.TorrentState.PAUSED_DOWNLOAD:
                            continue
                        if torrent.save_path == self.new_save_path:
                            continue
                        torrent.pause()
                        torrent.set_save_path(save_path=self.new_save_path)
                        torrent.resume()
                    else:
                        continue
        except qbittorrentapi.exceptions.APIError as e:
            logger.error(f"VCB辅助整理模块转移qb文件移动失败：{e}")

    def send_msg(self):
        """
        定时检查是否有媒体处理完，发送统一消息
        """
        if not self._medias or not self._medias.keys():
            return

        # 遍历检查是否已刮削完，发送消息
        for medis_title_year_season in list(self._medias.keys()):
            media_list = self._medias.get(medis_title_year_season)
            logger.info(f"开始处理媒体 {medis_title_year_season} 消息")

            if not media_list:
                continue

            # 获取最后更新时间
            last_update_time = media_list.get("time")
            media_files = media_list.get("files")
            if not last_update_time or not media_files:
                continue

            transferinfo = media_files[0].get("transferinfo")
            file_meta = media_files[0].get("file_meta")
            mediainfo = media_files[0].get("mediainfo")
            # 判断剧集最后更新时间距现在是已超过10秒或者电影，发送消息
            if (datetime.datetime.now() - last_update_time).total_seconds() > int(self._interval) \
                    or mediainfo.type == MediaType.MOVIE:
                # 发送通知
                if self._notify:

                    # 汇总处理文件总大小
                    total_size = 0
                    file_count = 0

                    # 剧集汇总
                    episodes = []
                    for file in media_files:
                        transferinfo = file.get("transferinfo")
                        total_size += transferinfo.total_size
                        file_count += 1

                        file_meta = file.get("file_meta")
                        if file_meta and file_meta.begin_episode:
                            episodes.append(file_meta.begin_episode)

                    transferinfo.total_size = total_size
                    # 汇总处理文件数量
                    transferinfo.file_count = file_count

                    # 剧集季集信息 S01 E01-E04 || S01 E01、E02、E04
                    season_episode = None
                    # 处理文件多，说明是剧集，显示季入库消息
                    if mediainfo.type == MediaType.TV:
                        # 季集文本
                        season_episode = f"{file_meta.season} {StringUtils.format_ep(episodes)}"
                    # 发送消息
                    self.transferchian.send_transfer_message(meta=file_meta,
                                                             mediainfo=mediainfo,
                                                             transferinfo=transferinfo,
                                                             season_episode=season_episode)
                # 发送完消息，移出key
                del self._medias[medis_title_year_season]
                continue

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
        if self._enabled and self._cron:
            return [{
                "id": "vcbanimemonitor",
                "name": "vcbanimemonitor",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.sync_all,
                "kwargs": {}
            }]
        return []

    def sync(self) -> schemas.Response:
        """
        API调用目录同步
        """
        self.sync_all()
        return schemas.Response(success=True)

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_command(self) -> List[Dict[str, Any]]:
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ova',
                                            'label': '开启识别OVA/OAD文件',
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
                                            'model': 'scrape',
                                            'label': '刮削元数据',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'mode',
                                            'label': '监控模式',
                                            'items': [
                                                {'title': '兼容模式', 'value': 'compatibility'},
                                                {'title': '性能模式', 'value': 'fast'}
                                            ]
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
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'transfer_type',
                                            'label': '转移方式',
                                            'items': [
                                                {'title': '移动', 'value': 'move'},
                                                {'title': '复制', 'value': 'copy'},
                                                {'title': '硬链接', 'value': 'link'},
                                                {'title': '软链接', 'value': 'softlink'},
                                                {'title': 'Rclone复制', 'value': 'rclone_copy'},
                                                {'title': 'Rclone移动', 'value': 'rclone_move'}
                                            ]
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
                                            'model': 'interval',
                                            'label': '入库消息延迟',
                                            'placeholder': '10'
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
                                            'model': 'cron',
                                            'label': '定时全量同步周期',
                                            'placeholder': '5位cron表达式，留空关闭'
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
                                            'model': 'size',
                                            'label': '监控文件大小（GB）',
                                            'placeholder': '0'
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
                                            'model': 'torrents_path',
                                            'label': '监控种子目录',
                                            'placeholder': '填入路径代表启用'
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
                                            'model': 'monitor_dirs',
                                            'label': '监控目录',
                                            'rows': 4,
                                            'placeholder': '每一行一个目录，支持以下几种配置方式，转移方式支持 move、copy、link、softlink、rclone_copy、rclone_move：\n'
                                                           '监控目录\n'
                                                           '监控目录#转移方式\n'
                                                           '监控目录:转移目的目录\n'
                                                           '监控目录:转移目的目录#转移方式'
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
                                            'model': 'exclude_keywords',
                                            'label': '排除关键词',
                                            'rows': 2,
                                            'placeholder': '每一行一个关键词'
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
                                            'text': '核心用法与目录同步插件相同，不同点在于只识别处理VCB-Studio资源。'
                                                    '默认不处理SPs、CDs、SCans目录下的文件，OVA/OAD集数暂时根据入库顺序累加命名，'
                                                    '因此不保证与TMDB集数匹配。部分季度以罗马音音译为名的作品暂时无法识别出准确季度。'
                                                    '有想法，有问题欢迎点击插件作者主页提issue！'
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
                                            'text': '最佳使用方式：监控目录单独设置一个作为保存VCB-Studio资源的目录，'
                                                    '填入监控种子目录，开启后会将正在QB(仅支持QB)下载器内正在下载的VCB-Studio资源转移到监控目录实现自动整理('
                                                    '仅支持第一个监控目录)，'
                                                    '监控种子目录为空则不转移文件'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
        ], {
            "enabled": False,
            "notify": False,
            "onlyonce": False,
            "mode": "fast",
            "transfer_type": settings.TRANSFER_TYPE,
            "monitor_dirs": "",
            "exclude_keywords": "",
            "interval": 10,
            "cron": "",
            "size": 0,
            "ova": False,
            "torrents_path": "",
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    print(str(e))
        self._observer = []
        if self._scheduler:
            self._scheduler.remove_all_jobs()
            if self._scheduler.running:
                self._event.set()
                self._scheduler.shutdown()
                self._event.clear()
            self._scheduler = None
