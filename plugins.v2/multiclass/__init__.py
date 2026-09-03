from pathlib import Path
from typing import Any, List, Dict, Tuple

from app.core.context import MediaInfo
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, MediaType, NotificationType

class MultiClass(_PluginBase):
    # 插件名称
    plugin_name = "视频多级分类"
    # 插件描述
    plugin_desc = "支持电影按照评分，年代和系列分类"
    # 插件图标
    plugin_icon = "Calibreweb_B.png"
    # 插件版本
    plugin_version = "0.1"
    # 插件作者
    plugin_author = "liuhangbin"
    # 作者主页
    author_url = "https://github.com/liuhangbin"
    # 插件配置项ID前缀
    plugin_config_prefix = "multiclass_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _notify = False
    _year_class = False
    _vote_class = False
    _collection_class = False

    def init_plugin(self, config: dict = None):

        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", False)
            self._year_class = config.get("year_class", False)
            self._vote_class = config.get("vote_class", False)
            self._collection_class = config.get("collection_class", False)

    def get_state(self) -> bool:
        return self._enabled

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
                                            'model': 'year_class',
                                            'label': '按照年代分类',
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
                                            'model': 'vote_class',
                                            'label': '按照评分分类',
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
                                            'model': 'collection_class',
                                            'label': '按照系列分类',
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
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '插件目前仅支持电影(需要开启智能重命名)。如果按评分分类，7-9 高分，4-6 一般，1-3 垃圾。 系列电影不参与评分, 不按年代分类。'
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
            "year_class": False,
            "vote_class": False,
            "collection_class": False
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(ChainEventType.TransferRename)
    def category_handler(self, event: Event):
        """
        根据多级分类规则重新分类组装地址
        """
        logger.debug(f"多级分类插件触发！")

        # 基础验证
        if not self.get_state():
            logger.debug(f"多级分类插件未启用！")
            return
        if not event:
            logger.warning(f"多级分类异常：事件对象为空")
            return
        if not hasattr(event, 'event_data'):
            logger.warning(f"多级分类异常：事件数据为空")
            return

        try:
            data = event.event_data

            # 验证必要的数据字段
            if not hasattr(data, 'render_str') or not data.render_str:
                logger.warning(f"多级分类异常：render_str为空")
                return
            else:
                render_str = data.render_str

            # 暂时只支持电影分类
            if not hasattr(data, 'rename_dict') or not data.rename_dict:
                logger.warning(f"多级分类异常：rename_dict为空")
                return
            else:
                rename_dict = data.rename_dict
                video_type = rename_dict.get("type", "")
                if video_type != "电影":
                    logger.debug(f"多级分类异常：不支持的媒体类型: {video_type}, 只支持电影分类")
                    return

            # 安全获取数据字段
            title = rename_dict.get("title", "")
            en_title = rename_dict.get("en_title", "")
            year = rename_dict.get("year")
            vote_average = rename_dict.get("vote_average")
            media_info = rename_dict.get("__mediainfo__")

            # 初始化默认值
            vote_count = 0
            c_name = None
            vote_path = "未知评分"
            decade = 0

            # 安全处理媒体信息
            if media_info and hasattr(media_info, 'vote_count'):
                try:
                    vote_count = int(media_info.vote_count) if media_info.vote_count else 0
                except (ValueError, TypeError):
                    vote_count = 0

                if hasattr(media_info, 'tmdb_info') and media_info.tmdb_info:
                    collection = media_info.tmdb_info.get("belongs_to_collection")
                    if collection and isinstance(collection, dict):
                        c_name = collection.get("name")

            # 安全处理评分数据
            try:
                if vote_average is not None:
                    vote_average = float(vote_average)
                else:
                    vote_average = 0
            except (ValueError, TypeError):
                vote_average = 0

            # 评分分类逻辑
            if vote_count < 10:
                vote_average = 0
                vote_path = "评分不足"
            elif vote_average >= 7:
                vote_path = "高分电影"
            elif vote_average >= 4:
                vote_path = "一般电影"
            else:
                vote_path = "垃圾电影"

            # 安全处理年份数据
            try:
                if year and str(year).isdigit():
                    year_int = int(year)
                    if 1900 <= year_int <= 2100:  # 合理的年份范围
                        decade = (year_int // 10) * 10
                    else:
                        decade = 0
                        logger.warning(f"年份超出合理范围: {year}")
                else:
                    decade = 0
            except (ValueError, TypeError):
                decade = 0
                logger.warning(f"年份转换失败: {year}")


            # 构建分类路径
            path_parts = []

            if self._collection_class and c_name:
                # 当collection为true时，只添加collection name
                # 清理collection名称，移除特殊字符
                clean_c_name = str(c_name).strip()
                if clean_c_name:
                    path_parts.append("系列电影")
                    path_parts.append(clean_c_name)
            else:
                # 当collection不为true时，根据其他配置添加路径
                if self._vote_class and vote_path:
                    path_parts.append(vote_path)
                if self._year_class and decade > 0:
                    path_parts.append(f"{decade}s")

            # 构建最终的路径
            if path_parts:
                # 确保render_str不为空
                safe_render_str = str(render_str).strip() if render_str else ""
                event.event_data.updated_str = f"{'/'.join(path_parts)}/{safe_render_str}"
                # 更新事件数据
                event.event_data.updated = True
                event.event_data.source = "MultiClass"

                # 发送消息
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.Organize,
                        title="多级分类完成",
                        text=f"已重新分类: {event.event_data.updated_str}",
                    )
            else:
                event.event_data.updated = False
                logger.warning(f"多级分类失败: 未找到分类路径，请检查配置是否已开启")

        except Exception as e:
            logger.error(f"多级分类异常: {str(e)}", exc_info=True)
            # 确保即使出错也不会影响原始数据
            if hasattr(event, 'event_data') and event.event_data:
                event.event_data.updated = False
                event.event_data.updated_str = getattr(data, 'render_str', '') if data else ''

    def stop_service(self):
        """
        停止服务
        """
        pass
