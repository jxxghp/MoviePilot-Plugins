from typing import Set, List, Optional
from enum import Enum
from app.plugins.downloaderhelper.convertor import IConvertor, ByteSizeConvertor, PercentageConvertor, StateConvertor, SpeedConvertor, RatioConvertor, TimestampConvertor, LimitSpeedConvertor, LimitRatioConvertor, TimeIntervalConvertor, TagsConvertor


class Downloader(Enum):
    """
    下载器枚举
    """
    QB = ('qbittorrent', 'qBittorrent', 'qb', 'QB')
    TR = ('transmission', 'Transmission', 'tr', 'TR')

    def __init__(self, id: str, name_: str, short_id: str, short_name: str):
        self.id: str = id
        self.name_: str = name_
        self.short_id: str = short_id
        self.short_name: str = short_name


# Downloader 映射
DownloaderMap = dict((d.id, d) for d in Downloader)


class TaskResult:
    """
    任务执行结果
    """

    def __init__(self, name: str):
        self.__name: str = name
        self.__success: bool = True
        self.__total: int = 0
        self.__seeding: int = 0
        self.__tagging: int = 0
        self.__delete: int = 0

    def get_name(self) -> str:
        return self.__name

    def set_success(self, success: bool):
        self.__success = success
        return self

    def is_success(self):
        return self.__success

    def set_total(self, total: int):
        self.__total = total
        return self

    def get_total(self):
        return self.__total

    def set_seeding(self, seeding: int):
        self.__seeding = seeding
        return self

    def get_seeding(self):
        return self.__seeding

    def set_tagging(self, tagging: int):
        self.__tagging = tagging
        return self

    def get_tagging(self):
        return self.__tagging

    def set_delete(self, delete: int):
        self.__delete = delete
        return self

    def get_delete(self):
        return self.__delete


class TaskContext:
    """
    任务上下文
    """

    def __init__(self):
        # 选择的下载器集合，为None时表示选择全部
        self.__selected_downloaders: Optional[Set[str]] = None

        # 启用的子任务
        # 启用做种
        self.__enable_seeding: bool = True
        # 启用打标
        self.__enable_tagging: bool = True
        # 启用删种
        self.__enable_delete: bool = True

        # 选择的种子，为None时表示选择全部
        # self.__selected_torrents: Set[str] = None
        self.__selected_torrents = None

        #  源文件删除事件数据
        self.__deleted_event_data = None

        # 任务结果集
        self.__results: Optional[List[TaskResult]] = None

        # 操作用户名
        self.__username: Optional[str] = None

    def select_downloader(self, downloader_id: str):
        """
        选择下载器
        :param downloader_id: 下载器id
        """
        if not downloader_id:
            return self
        if not self.__selected_downloaders:
            self.__selected_downloaders = set()
        self.__selected_downloaders.add(downloader_id)
        return self

    def select_downloaders(self, downloader_ids: List[str]):
        """
        选择下载器
        :param downloader_ids: 下载器ids
        """
        if not downloader_ids:
            return self
        for downloader_id in downloader_ids:
            self.select_downloader(downloader_id)
        return self

    def __is_selected_the_downloader(self, downloader_id: str) -> bool:
        """
        是否选择了指定的下载器
        :param downloader_id: 下载器id
        :return: 是否选择了指定的下载器
        """
        if not downloader_id:
            return False
        return True if self.__selected_downloaders is None or downloader_id in self.__selected_downloaders \
            else False

    def is_selected_qb_downloader(self) -> bool:
        """
        是否选择了qb下载器
        :return: 是否选择了qb下载器
        """
        return self.__is_selected_the_downloader(Downloader.QB.id)

    def is_selected_tr_downloader(self) -> bool:
        """
        是否选择了tr下载器
        :return: 是否选择了tr下载器
        """
        return self.__is_selected_the_downloader(Downloader.TR.id)

    def enable_seeding(self, enable_seeding: bool = True):
        """
        是否启用做种
        :param enable_seeding: 是否启用做种
        """
        self.__enable_seeding = enable_seeding if enable_seeding else False
        return self

    def is_enabled_seeding(self) -> bool:
        """
        是否启用了做种
        :return: 是否启用了做种
        """
        return self.__enable_seeding

    def enable_tagging(self, enable_tagging: bool = True):
        """
        是否启用打标
        :param enable_tagging: 是否启用打标
        """
        self.__enable_tagging = enable_tagging if enable_tagging else False
        return self

    def is_enabled_tagging(self) -> bool:
        """
        是否启用了打标
        :return: 是否启用了打标
        """
        return self.__enable_tagging

    def enable_delete(self, enable_delete: bool = True):
        """
        是否启用删种
        :param enable_delete: 是否启用删种
        """
        self.__enable_delete = enable_delete if enable_delete else False
        return self

    def is_enabled_delete(self) -> bool:
        """
        是否启用了删种
        :return: 是否启用了删种
        """
        return self.__enable_delete

    def select_torrent(self, torrent: str):
        """
        选择种子
        :param torrent: 种子key
        """
        if not torrent:
            return self
        if not self.__selected_torrents:
            self.__selected_torrents = set()
        self.__selected_torrents.add(torrent)
        return self

    def select_torrents(self, torrents: List[str]):
        """
        选择种子
        :param torrents: 种子keys
        """
        if not torrents:
            return self
        for torrent in torrents:
            self.select_torrent(torrent)
        return self

    # def get_selected_torrents(self) -> Set[str]:
    def get_selected_torrents(self):
        """
        获取所有选择的种子
        """
        return self.__selected_torrents

    def set_deleted_event_data(self, deleted_event_data: dict):
        """
        设置源文件删除事件数据
        """
        self.__deleted_event_data = deleted_event_data
        return self

    def get_deleted_event_data(self) -> dict:
        """
        获取源文件删除事件数据
        """
        return self.__deleted_event_data

    def save_result(self, result: TaskResult):
        """
        存储结果
        :param result: 结果
        """
        if not result:
            return self
        if not self.__results:
            self.__results = []
        self.__results.append(result)
        return self

    def get_results(self) -> List[TaskResult]:
        """
        获取结果集
        """
        return self.__results

    def set_username(self, username: str):
        """
        设置操作用户名
        """
        self.__username = username
        return self

    def get_username(self) -> str:
        """
        获取操作用户名
        """
        return self.__username


class TorrentField(Enum):
    """
    种子字段枚举
    """
    NAME = ('名称', 'name', 'name', None)
    SELECT_SIZE = ('选定大小', 'size', 'sizeWhenDone', ByteSizeConvertor())
    TOTAL_SIZE = ('总大小', 'total_size', 'totalSize', ByteSizeConvertor())
    PROGRESS = ('已完成', 'progress', 'percentDone', PercentageConvertor())
    STATE = ('状态', 'state', 'status', StateConvertor())
    DOWNLOAD_SPEED = ('下载速度', 'dlspeed', 'rateDownload', SpeedConvertor())
    UPLOAD_SPEED = ('上传速度', 'upspeed', 'rateUpload', SpeedConvertor())
    REMAINING_TIME = ('剩余时间', '#REMAINING_TIME', '#REMAINING_TIME', TimeIntervalConvertor())
    RATIO = ('比率', 'ratio', 'uploadRatio', RatioConvertor())
    CATEGORY = ('分类', 'category', None, None)
    TAGS = ('标签', 'tags', 'labels', TagsConvertor())
    ADD_TIME = ('添加时间', 'added_on', 'addedDate', TimestampConvertor())
    COMPLETE_TIME = ('完成时间', 'completion_on', 'doneDate', TimestampConvertor())
    DOWNLOAD_LIMIT = ('下载限制', 'dl_limit', 'downloadLimit', LimitSpeedConvertor())
    UPLOAD_LIMIT = ('上传限制', 'up_limit', 'uploadLimit', LimitSpeedConvertor())
    DOWNLOADED = ('已下载', 'downloaded', 'downloadedEver', ByteSizeConvertor())
    UPLOADED = ('已上传', 'uploaded', 'uploadedEver', ByteSizeConvertor())
    DOWNLOADED_SESSION = ('本次会话下载', 'downloaded_session', None, ByteSizeConvertor())
    UPLOADED_SESSION = ('本次会话上传', 'uploaded_session', None, ByteSizeConvertor())
    REMAINING = ('剩余', '#REMAINING', '#REMAINING', ByteSizeConvertor())
    SAVE_PATH = ('保存路径', 'save_path', 'downloadDir', None)
    COMPLETED = ('完成', 'completed', '#COMPLETED', ByteSizeConvertor())
    RATIO_LIMIT = ('比率限制', 'ratio_limit', 'seedRatioLimit', LimitRatioConvertor())

    def __init__(self, name_: str, qb: str, tr: str, convertor: IConvertor):
        self.name_ = name_
        self.qb = qb
        self.tr = tr
        self.convertor = convertor


# TorrentField 映射
TorrentFieldMap = dict((field.name, field) for field in TorrentField)
