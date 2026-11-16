"""
AutoSports 插件入口。

主类 AutoSports 保留在本模块，其余实现按职责拆分到同名小写子包：
recognition（识别刮削）、search（搜索下载）、monitor（目录监控整理）、ui（页面渲染）。
"""

import datetime
import re
import threading
from pathlib import Path
from typing import Optional, Any, List, Dict
from typing import Union

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.chain.subscribe import SubscribeChain
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import ServiceInfo
from app.sdk.cache import TTLCache
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import SitesHelper
from app.sdk.services import DownloaderHelper


from app.plugins.autosports.recognition.competitions import get_demo_competitions_config, get_raw_competitions_parse
from app.plugins.autosports.search.indexer import build_sportscult_indexer
from app.plugins.autosports.search.models import Matchinfo
from app.plugins.autosports.monitor import FileMonitorHandler, Monitor
from app.plugins.autosports.recognition import Recognition
from app.plugins.autosports.search import Search
from app.plugins.autosports.ui import Ui


class AutoSports(Recognition, Search, Monitor, Ui, _PluginBase):

    """体育比赛自动下载与整理插件。"""

    Matchinfo = Matchinfo

    # 插件名称
    plugin_name = "AutoSports"

    # 插件描述
    plugin_desc = "根据设置的球队名自动下载最新比赛，进行文件整理及简单的刮削"

    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Sinterdial/MoviePilot-Plugins/main/icons/autosports.png"

    # 插件版本
    plugin_version = "3.1.0"

    # 插件作者
    plugin_author = "Sinterdial"

    # 作者主页
    author_url = "https://github.com/Sinterdial"

    # 插件配置项ID前缀
    plugin_config_prefix = "AutoSports_"

    # 加载顺序
    plugin_order = 15

    # 可使用的用户级别
    auth_level = 1

    name = "AutoSports"

    # 插件注册的媒体数据源标识，只有选中该来源时才使用体育比赛识别规则
    MEDIA_SOURCE = "autosports"

    # 媒体数据源展示名称
    MEDIA_SOURCE_NAME = "AutoSports"

    _enabled: bool = False

    _teams_info: str = ""

    _football_apikey: str = ""

    _cron: str = "27 6-8 * * *"

    _notify: bool = False

    _onlyonce: bool = False

    _include: str = ""

    _exclude: str = ""

    _proxy: bool = False

    _filter: bool = False

    # 内置搜索是否也应用宿主过滤规则（默认关闭，本站种子直接放行）
    _filter_builtin_search: bool = False

    _force_en: bool = False

    _lowest_pix: int = 720

    _clear: bool = False

    _clearflag: bool = False

    _action: str = "download"

    _save_path: str = ""  # 下载路径

    _dest_path: str = ""  # 媒体库路径

    _category: str = ""

    _tags: list[str] = []

    _size_range: str = ""

    _start_paused: bool = True  # 添加种子后暂停下载

    _max_download: int = 2  # 单次最多下多少场比赛

    # 转移与刮削相关
    _sync_all: bool = False

    _monitor_mode: str = 'normal'  # 增量监控目录模式

    _observer: list[Observer | PollingObserver] = []  # 目录监控工具对象

    _transfer_type: str = "link"

    _need_rename: bool = True

    _downloaders = None

    _scheduler: BackgroundScheduler | None = None

    _timeline = "00:00:10"

    _matches = {}

    _competitions_config = get_demo_competitions_config()  # 自定义赛事信息

    # 订阅缓存信息
    _cached_matches = {}

    # football-data.org 请求失败后的短时负缓存，避免同一轮反复请求被限流
    _failed_matches: Dict[str, float] = {}

    _FAILED_MATCH_TTL = 600

    # 已入库比赛索引的短时缓存，避免目录监控每个文件事件都全量扫描媒体库
    _vault_cache: Optional[Dict[str, Dict[int, list]]] = None

    _vault_cache_at: float = 0.0

    _VAULT_CACHE_TTL = 60

    _vault_cache_lock = threading.Lock()

    # 内置搜索结果身份识别的短时缓存，避免重复搜索时反复识别同一标题
    _stamp_cache: Dict[str, tuple] = {}

    _STAMP_CACHE_TTL = 1800

    # 对阵 -> (主队 crest, 客队 crest)，用于历史记录展示球队 logo
    _match_crests: Dict[str, tuple] = {}

    # 历史记录分页，每页上限 35 条
    _HISTORY_PAGE_SIZE = 35

    _history_page: int = 1

    _system_cache = None  # 系统缓存，默认12小时过期

    # 当前 Sportscult 站点 ID，用于识别种子来源
    _sportscult_site_id: Optional[int] = None

    # 插件自身调用过滤时置位（线程本地），避免重载的 filter_torrents 绕过插件配置的规则组
    _filter_isolation = threading.local()

    # 赛事刮削信息
    # 自定义映射关系
    _competitions_parses = get_raw_competitions_parse()

    knockout_parse = {  # 杯赛 -> 参赛球队数映射表
        # Round of 32
        r"\br32\b|\bround\s+of\s+32\b": 32,

        # Round of 16
        r"\br16\b|\bround\s+of\s+16\b": 16,

        # Quarter Final
        r"\bquarter[\s-]?final\b|\bqf\b": 8,

        # Semi Final
        r"\bsemi[\s-]?final\b|\bsf\b": 4,

        # Final
        r"\bfinal\b": 2,

        # Round of 32
        r"\b三十二强赛\b": 32,

        # Round of 16
        r"\b十六强赛\b": 16,

        # Quarter Final
        r"\b八强赛\b": 8,

        # Semi Final
        r"\b半决赛\b": 4,

        # Final
        r"\b决赛\b": 2,
    }

    downloadchain: DownloadChain = None

    subscribechain: SubscribeChain = None

    mediachain: MediaChain = None

    searchchain: SearchChain = None

    torrents_list = []

    def __init__(self):
        super().__init__()

    @property
    def _downloader(self) -> Optional[Union[Qbittorrent, Transmission]]:
        """
        下载器实例
        """
        return self._service_info.instance if self._service_info else None

    @property
    def _service_info(self) -> Optional[ServiceInfo]:
        """
        服务信息
        """
        service = DownloaderHelper().get_service(name=self._downloaders)
        if not service:
            self._log_and_notify_error("自动下载/整理体育比赛任务出错，获取下载器实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            self._log_and_notify_error("自动下载/整理体育比赛任务出错，下载器未连接")
            return None

        return service

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        sportscult_json = build_sportscult_indexer()
        # 添加 SportsCult 站点；已存在时保留用户对站点/索引器的自定义修改
        if not self._has_indexer(domain="sportscult.org"):
            SitesHelper().add_indexer(domain="sportscult.org", indexer=sportscult_json)
        else:
            logger.debug("Sportscult 索引器已存在，跳过重复添加")
        # 创建缓存实例
        self._system_cache = TTLCache(region='autosports', maxsize=128, ttl=43200)

        # 载入配置
        if config:
            self._validate_and_fix_config(config=config)
            self._football_apikey = config.get("football_apikey")
            self._teams_info = config.get("teams_info")
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._include = config.get("include")
            self._exclude = config.get("exclude")
            self._proxy = config.get("proxy")
            self._force_en = config.get("force_en") or False
            self._lowest_pix = self._to_int(config.get("lowest_pix"), 720)
            self._filter = config.get("filter")
            self._filter_builtin_search = config.get("filter_builtin_search") or False
            self._clear = config.get("clear")
            self._action = config.get("action")
            self._save_path = config.get("save_path")
            self._dest_path = config.get("dest_path")
            self._downloaders = config.get("downloaders")
            self._transfer_type = config.get("transfer_type") or "link"
            self._start_paused = config.get("start_paused")
            self._max_download = self._to_int(config.get("max_download"), 0)
            self._competitions_config = config.get("competitions_config", "[]")
            monitor_mode_gotten = config.get("monitor_mode")
            self._monitor_mode = monitor_mode_gotten \
                if monitor_mode_gotten in ("normal", "compatibility") else "normal"
            self._sync_all = config.get("sync_all")
            if config.get("need_rename"):
                self._need_rename = config.get("need_rename")
            else:
                self._need_rename = True
            # 如果未设置下载器，使用默认的下载器
            if not self._downloaders:
                for downloader_config in DownloaderHelper().get_configs().values():
                    if downloader_config.default:
                        self._downloaders = downloader_config.name
                        break

            try:
                category_gotten = config.get("category")
                self._category = category_gotten
            except AttributeError:
                self._category = ""
            tags_gotten = config.get("tags")
            if isinstance(tags_gotten, str):
                self._tags = [tag.strip() for tag in tags_gotten.split(",") if tag.strip()]
            elif isinstance(tags_gotten, (list, tuple)):
                self._tags = [str(tag).strip() for tag in tags_gotten if str(tag).strip()]
            else:
                self._tags = []
            self._size_range = config.get("size_range")

        if (self._enabled or self._onlyonce) and not self._football_apikey:
            logger.error("无法对比赛进行刮削，请填入有效的 football-data.org API key，插件已停止运行")
            self.systemmessage.put("未配置 football-data.org API key，AutoSports 已停止运行")
            self._enabled = False
            self._onlyonce = False
            self.stop_service()
            self._update_config()
            return

        # 启用目录监控
        if self._enabled:
            # 检查媒体库目录是不是下载目录的子目录
            try:
                if self._dest_path and Path(self._dest_path).is_relative_to(Path(self._save_path)):
                    logger.warn(f"{self._dest_path} 是下载目录 {self._save_path} 的子目录，无法监控")
                    self.systemmessage.put(f"{self._dest_path} 是下载目录 {self._save_path} 的子目录，无法监控")
            except Exception as e:
                logger.debug(str(e))
                pass

            try:
                if self._monitor_mode == "compatibility":
                    # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                    observer = PollingObserver(timeout=10)
                else:
                    # 内部处理系统操作类型选择最优解
                    observer = Observer(timeout=10)
                self._observer.append(observer)
                observer.schedule(FileMonitorHandler(self._save_path, self), path=self._save_path, recursive=True)
                observer.daemon = True
                observer.start()
                logger.info(f"{self._save_path} 的目录监控服务启动")
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
                    logger.error(f"{self._save_path} 启动目录监控失败：{err_msg}")
                self.systemmessage.put(f"{self._save_path} 启动目录监控失败：{err_msg}")
        else:
            # 未启用插件，关闭目录监控服务
            self.stop_service()

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"自定义订阅服务启动，立即运行一次")
            self._scheduler.add_job(func=self.check, trigger='date',
                                     run_date=datetime.datetime.now(
                                         tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                     )

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        if self._onlyonce or self._clear:
            # 关闭一次性开关
            self._onlyonce = False
            # 记录清理缓存设置
            self._clearflag = self._clear
            # 关闭清理缓存开关
            self._clear = False

        # 保存设置
        self._update_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除体育比赛自动下载整理历史记录"
            },
            {
                "path": "/history_page",
                "endpoint": self.history_page,
                "methods": ["GET"],
                "summary": "翻页体育比赛自动下载整理历史记录"
            }
        ]

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
                "id": "AutoSports",
                "name": "自动下载体育比赛服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.check,
                "kwargs": {}
            }]
        elif self._enabled:
            return [{
                "id": "AutoSports",
                "name": "自动下载体育比赛服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"hours": 12}
            }]
        return []

    # 声明重新实现的方法
    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）

        :return: 模块方法名到具体实现的映射
        """
        return {
            # 本站种子不受 MoviePilot 搜索过滤规则限制
            "filter_torrents": self.filter_torrents,
            # 仅在请求指定本插件数据源时，用体育比赛规则识别种子
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

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

        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    logger.debug(f"停止目录监控失败：{str(e)}")
        self._observer = []

    def _update_config(self):
        """
        更新设置
        """
        self.update_config({
            "enabled": self._enabled,
            "football_apikey": self._football_apikey,
            "teams_info": self._teams_info,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "include": self._include,
            "exclude": self._exclude,
            "proxy": self._proxy,
            "filter": self._filter,
            "filter_builtin_search": self._filter_builtin_search,
            "clear": self._clear,
            "action": self._action,
            "save_path": self._save_path,
            "dest_path": self._dest_path,
            "category": self._category,
            "tags": ",".join(self._tags),
            "size_range": self._size_range,
            "downloaders": self._downloaders,
            "force_en": self._force_en,
            "lowest_pix": self._lowest_pix,
            "transfer_type": self._transfer_type,
            "need_rename": self._need_rename,
            "start_paused": self._start_paused,
            "max_download": self._max_download,
            "competitions_config": self._competitions_config,
            "monitor_mode": self._monitor_mode,
            "sync_all": False,
        })

        # 组装赛事识别器（内置加用户自定义）
        self._initialize_competition_config()

    def _validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """
        size_range = config.get("size_range")
        if size_range and not self._is_number_or_range(str(size_range)):
            self._log_and_notify_error(f"AutoSports 种子大小设置错误，已忽略：{size_range}")
            config["size_range"] = None
            return False
        return True

    @staticmethod
    def _is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
        """
        return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        """
        把配置值安全转换为整数，非法或缺失时返回默认值。

        :param value: 配置中的原始值
        :param default: 转换失败时使用的默认值
        :return: 转换后的整数
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
