import random
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.core.context import MediaInfo
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import TransferInfo
from app.schemas.types import EventType, MediaType, NotificationType
from app.utils.system import SystemUtils

lock = threading.Lock()


class PlayletCategory(_PluginBase):
    # 插件名称
    plugin_name = "短剧自动分类"
    # 插件描述
    plugin_desc = "网络短剧自动分类到独立目录。"
    # 插件图标
    plugin_icon = "Amule_A.png"
    # 插件版本
    plugin_version = "2.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "playletcategory_"
    # 加载顺序
    plugin_order = 29
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _notify = True
    _delay = 0
    _category_dir = ""
    _episode_duration = 8

    def init_plugin(self, config: dict = None):

        if config:
            self._enabled = config.get("enabled")
            self._delay = config.get("delay") or 0
            self._notify = config.get("notify")
            self._category_dir = config.get("category_dir")
            self._episode_duration = config.get("episode_duration")

    def get_state(self) -> bool:
        return True if self._enabled and self._category_dir and self._episode_duration else False

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
                                            'model': 'notify',
                                            'label': '发送消息',
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
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'category_dir',
                                            'label': '分类目录路径',
                                            'placeholder': '/media/短剧'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'episode_duration',
                                            'label': '单集时长（分钟）',
                                            'placeholder': '8'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'delay',
                                            'label': '入库延迟时间（秒）',
                                            'placeholder': ''
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
                                            'text': '小于单集时长的剧集视频文件将会移动到分类目录，入库延迟适用于网盘等需要延后处理的场景，需要安装FFmpeg。'
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
            "notify": True,
            "delay": '',
            "category_dir": '短剧',
            "episode_duration": '8'
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.TransferComplete)
    def category_handler(self, event: Event):
        """
        根据事件实时刮削剧集组信息
        """
        if not event:
            return
        if not self.get_state():
            return
        event_data = event.event_data
        mediainfo: MediaInfo = event_data.get("mediainfo")
        transferinfo: TransferInfo = event_data.get("transferinfo")
        if not mediainfo or not transferinfo:
            return
        if not transferinfo.target_path:
            return
        if not transferinfo.target_path.exists():
            return
        if mediainfo.type != MediaType.TV:
            logger.info(f"{transferinfo.target_path} 不是电视剧，跳过分类处理")
            return
        # 加锁
        with lock:
            file_list = transferinfo.file_list_new or []
            # 过滤掉不存在的文件
            file_list = [file for file in file_list if Path(file).exists()]
            if not file_list:
                logger.warn(f"{transferinfo.target_path} 无文件，跳过分类处理")
                return
            logger.info(f"开始处理 {transferinfo.target_path} 短剧分类，共有 {len(file_list)} 个文件")
            # 从文件列表中随机抽取3个文件
            if len(file_list) > 3:
                check_files = random.choices(file_list, k=3)
            else:
                check_files = file_list
            # 计算文件时长，有任意文件时长大于单集时长则不处理
            need_category = True
            for file in check_files:
                duration = self.__get_duration(file)
                if duration > float(self._episode_duration):
                    logger.info(
                        f"{file} 时长 {duration} 分钟，大于单集时长 {self._episode_duration} 分钟，不需要分类处理")
                    need_category = False
                    break
                else:
                    logger.info(f"{file} 时长：{duration} 分钟")
            if need_category:
                logger.info(f"{transferinfo.target_path} 需要分类处理，开始移动文件...")
                self.__move_files(target_path=transferinfo.target_path)
                logger.info(f"{transferinfo.target_path} 短剧分类处理完成")
            else:
                logger.info(f"{transferinfo.target_path} 不是短剧，无需分类处理")

    @staticmethod
    def __get_duration(video_path: str) -> float:
        """
        获取视频文件时长（分钟）
        """

        # 使用FFmpeg命令行工具获取视频时长
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
               'default=noprint_wrappers=1:nokey=1', str(video_path)]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        # 如果有错误，输出错误信息
        if error:
            logger.error(f"FFmpeg处理出错: {error.decode('utf-8')}")
            return 0

        # 获取视频时长（秒），转换为分钟
        return round(float(output) / 60, 1)

    def __move_files(self, target_path: Path):
        """
        移动文件到分类目录
        :param target_path: 电视剧时为季的目录
        """
        if not target_path.exists():
            return
        if target_path.is_file():
            target_path = target_path.parent
        # 剧集的根目录
        tv_path = target_path.parent
        # 新的文件目录
        new_path = Path(self._category_dir) / tv_path.name
        if not new_path.exists():
            # 移动目录
            try:
                shutil.move(tv_path, new_path)
            except Exception as e:
                logger.error(f"移动文件失败：{e}")
                return
        else:
            # 遍历目录下的所有文件，并移动到目的目录
            for file in tv_path.iterdir():
                if file.is_file():
                    try:
                        # 相对路径
                        relative_path = file.relative_to(tv_path)
                        shutil.move(file, new_path / relative_path)
                    except Exception as e:
                        logger.error(f"移动文件失败：{e}")
                        return
            # 删除空目录
            if not SystemUtils.list_files(tv_path, extensions=settings.RMT_MEDIAEXT + settings.DOWNLOAD_TMPEXT):
                try:
                    shutil.rmtree(tv_path, ignore_errors=True)
                except Exception as e:
                    logger.error(f"删除空目录失败：{e}")

        # 发送消息
        if self._notify:
            self.post_message(
                mtype=NotificationType.Organize,
                title="【短剧自动分类】",
                text=f"已将 {tv_path.name} 分类到 {self._category_dir} 目录",
            )

    def stop_service(self):
        """
        停止服务
        """
        pass
