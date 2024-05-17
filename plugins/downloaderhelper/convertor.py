from abc import ABCMeta, abstractmethod
from qbittorrentapi import TorrentState

from app.utils.string import StringUtils
from app.utils.singleton import Singleton
from app.log import logger


class IConvertor(metaclass=ABCMeta):
    """
    转换器接口
    """

    @abstractmethod
    def convert(self, data: any) -> any:
        """
        转换
        """
        pass


class ByteSizeConvertor(IConvertor, metaclass=Singleton):
    """
    byte size 转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            return StringUtils.str_filesize(data)
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class PercentageConvertor(IConvertor, metaclass=Singleton):
    """
    百分比转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            return f'{round(data * 100)}%'
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class StateConvertor(IConvertor, metaclass=Singleton):
    """
    状态转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            # qb
            if data == TorrentState.UPLOADING.value:
                return '做种'
            if data == TorrentState.DOWNLOADING.value:
                return '下载中'
            if data == TorrentState.PAUSED_DOWNLOAD.value:
                return '暂停'
            if data == TorrentState.STALLED_DOWNLOAD.value:
                return '等待'
            if data == TorrentState.CHECKING_DOWNLOAD.value:
                return '校验'
            # tr
            if data == 6:
                return '做种'
            if data == 4:
                return '下载中'
            if data == 0:
                return '暂停'
            if data == 3:
                return '等待'
            if data == 2:
                return '校验'
            return data
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class SpeedConvertor(IConvertor, metaclass=Singleton):
    """
    速度转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            data = ByteSizeConvertor().convert(data=data)
            if not data:
                data = '0B'
            return f'{data}/s'
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class RatioConvertor(IConvertor, metaclass=Singleton):
    """
    比率(分享率)转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            return round(data, 2)
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class TimestampConvertor(IConvertor, metaclass=Singleton):
    """
    时间戳转换器
    """

    def convert(self, data: any) -> any:
        if not data or data <= 0:
            return None
        try:
            return StringUtils.format_timestamp(timestamp=data, date_format='%Y/%m/%d %H:%M:%S')
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class TimeIntervalConvertor(IConvertor, metaclass=Singleton):
    """
    时间间隔转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            if data < 0:
                return '∞'
            if data == 0:
                return '0'
            return StringUtils.str_secends(time_sec=data)
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class LimitSpeedConvertor(IConvertor, metaclass=Singleton):
    """
    限制速度转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            if data <= 0:
                return '∞'
            return SpeedConvertor().convert(data=data)
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class LimitRatioConvertor(IConvertor, metaclass=Singleton):
    """
    限制比率(分享率)转换器
    """

    def convert(self, data: any) -> any:
        if data is None:
            return None
        try:
            if data <= 0:
                return '∞'
            return RatioConvertor().convert(data=data)
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None


class TagsConvertor(IConvertor, metaclass=Singleton):
    """
    标签转换器
    """

    def convert(self, data: any) -> any:
        if not data:
            return None
        try:
            if isinstance(data, list):
                return ', '.join(data)
            return data
        except Exception as e:
            logger.error(f'{__name__} Error: {str(e)}, data = {data}', exc_info=True)
            return None
