import json
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

from app.db import SessionFactory
from app.db.models import TransferHistory
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaSource
from app.sdk.network import RequestUtils
from app.sdk.media import resolve_media_identity


class HistoryToV2(_PluginBase):
    """把远端 MoviePilot V1 整理历史迁移到当前 V3 数据库。"""

    # 插件名称
    plugin_name = "V1历史记录迁移至V3"
    # 插件描述
    plugin_desc = "将 MoviePilot V1 的整理历史记录迁移至当前 MoviePilot V3。"
    # 插件图标
    plugin_icon = "Moviepilot_A.png"
    # 插件版本
    plugin_version = "2.1.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "historytov3_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _host = None
    _username = None
    _password = None

    def init_plugin(self, config: dict = None):
        """加载迁移配置，并在启用后分批执行 V1 至 V3 的历史迁移。"""
        if config:
            self._enabled = config.get("enabled")
            self._host = config.get("host")
            self._username = config.get("username")
            self._password = config.get("password")

            if self._enabled:
                if self._host and self._username and self._password:
                    # 关闭开关
                    self.__close_config()
                    # 登录MP获取token
                    token = self.__login_mp()
                    if token:
                        # 当前页码
                        page = 1
                        # 总记录数
                        total = 0
                        # 获取历史记录
                        history = self.__get_history(token)
                        while history:
                            # 处理历史记录
                            logger.info(f"开始处理第 {page} 页历史记录 ...")
                            self.__insert_v3_history(history)
                            # 处理成功一批
                            total += len(history)
                            logger.info(f"第 {page} 页处理完成，共处理 {total} 条记录")
                            # 获取下一页历史记录
                            page += 1
                            history = self.__get_history(token, page=page)
                        # 处理完成
                        logger.info(f"MoviePilot V1 历史记录迁移至 V3 完成，共迁移 {total} 条记录！")
                        self.systemmessage.put(
                            f"V1 历史记录迁移至 V3 完成，共迁移 {total} 条记录！",
                            title="MoviePilot V1 至 V3 历史记录迁移",
                        )
                else:
                    self.systemmessage.put(
                        "V1 连接配置不完整，历史记录迁移至 V3 启动失败！",
                        title="MoviePilot V1 至 V3 历史记录迁移",
                    )
                    # 关闭开关
                    self.__close_config()

    def __close_config(self):
        """
        关闭开关
        """
        self._enabled = False
        self.update_config({
            "enabled": self._enabled,
            "host": self._host,
            "username": self._username,
            "password": self._password
        })

    def get_state(self) -> bool:
        """返回一次性迁移开关的当前状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """该迁移插件不注册远程命令。"""
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """该迁移插件不暴露额外 API。"""
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '开始迁移至 V3',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'host',
                                            'label': 'MoviePilot V1地址',
                                            'placeholder': 'http://localhost:3000',
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
                                            'model': 'username',
                                            'label': '登录用户名',
                                            'placeholder': 'admin'
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
                                            'label': '登录密码',
                                            'type': 'password',
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
                                            'text': 'MoviePilot V1 需保持启动且可正常访问；V1 与当前 V3 的目录映射需保持一致。整理历史会直接写入当前 V3 数据库，完成后会收到系统通知。'
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
            "host": None,
            "username": None,
            "password": None
        }

    def get_page(self) -> List[dict]:
        """该迁移插件不提供独立详情页面。"""
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    def __login_mp(self) -> Optional[str]:
        """
        登录MP获取token
        """
        if not self._host or not self._username or not self._password:
            return None
        url = f"{self._host}/api/v1/login/access-token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "username": self._username,
            "password": self._password
        }
        logger.info(f"登录源 MoviePilot V1: {url}")
        # 发送POST请求
        response = RequestUtils(headers=headers).post_res(url, data=data)
        # 检查响应状态
        if response.status_code == 200:
            # 成功获取token
            token_data = response.json()
            logger.info("登录源 MoviePilot V1 成功")
            return token_data["access_token"]
        else:
            # 处理失败响应
            logger.warn(f"登录源 MoviePilot V1 失败: {response.json()}")
            self.systemmessage.put(
                "登录源 MoviePilot V1 失败，无法迁移历史记录至 V3！",
                title="MoviePilot V1 至 V3 历史记录迁移",
            )
            return None

    def __get_history(self, token: str, page: int = 1, count: int = 30) -> Optional[List[dict]]:
        """
        获取历史记录
        """
        if not token:
            return []
        url = f"{self._host}/api/v1/history/transfer"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        params = {
            "page": page,
            "count": count
        }
        logger.info(f"查询 MoviePilot V1 整理历史记录: {url}，params: {params}")
        # 发送GET请求
        response = RequestUtils(headers=headers).get_res(url, params=params)
        # 检查响应状态
        if response.status_code == 200:
            # 返回数据
            response_data = response.json()
            data = response_data.get("data")
            logger.info(f"查询 MoviePilot V1 整理历史成功，共 {len(data.get('list'))} 条记录")
            return data.get("list")
        else:
            # 处理失败响应
            logger.warn(f"查询 MoviePilot V1 整理历史失败: {response.json()}")
            self.systemmessage.put(
                "查询 MoviePilot V1 整理历史失败，无法迁移至 V3！",
                title="MoviePilot V1 至 V3 历史记录迁移",
            )
            return []

    @staticmethod
    def __resolve_history_identity(item: dict) -> Tuple[Optional[MediaSource], Optional[str]]:
        """将 V1 整理历史中的分散 ID 迁移为统一媒体身份。"""
        media_source, media_id = resolve_media_identity(
            media_source=item.get("media_source"),
            media_id=item.get("media_id"),
        )
        if media_source:
            return media_source, media_id
        legacy_fields = (
            (MediaSource.TMDB, "tmdbid"),
            (MediaSource.Douban, "doubanid"),
            (MediaSource.IMDb, "imdbid"),
            (MediaSource.TVDB, "tvdbid"),
        )
        for source, field in legacy_fields:
            media_source, media_id = resolve_media_identity(
                media_source=source,
                media_id=item.get(field),
            )
            if media_source:
                return media_source, media_id
        return None, None

    @staticmethod
    def __insert_v3_history(history: List[dict]):
        """
        将源 MoviePilot V1 的整理历史写入当前 MoviePilot V3 数据库。
        """
        if not history:
            return
        with SessionFactory() as db:
            for item in history:
                media_source, media_id = HistoryToV2.__resolve_history_identity(item)
                if item.get("src"):
                    transferhistory = TransferHistory.get_by_src(db, item.get("src"))
                    if transferhistory:
                        transferhistory.delete(db, transferhistory.id)
                try:
                    TransferHistory(
                        src=item.get("src"),
                        src_storage="local",
                        src_fileitem={
                            "storage": "local",
                            "type": "file",
                            "path": item.get("src"),
                            "name": Path(item.get("src")).name,
                            "basename": Path(item.get("src")).stem,
                            "extension": Path(item.get("src")).suffix[1:],
                        },
                        dest=item.get("dest"),
                        dest_storage="local",
                        dest_fileitem={
                            "storage": "local",
                            "type": "file",
                            "path": item.get("dest"),
                            "name": Path(item.get("dest")).name,
                            "basename": Path(item.get("dest")).stem,
                            "extension": Path(item.get("dest")).suffix[1:],
                        },
                        mode=item.get("mode"),
                        type=item.get("type"),
                        category=item.get("category"),
                        title=item.get("title"),
                        year=item.get("year"),
                        media_source=media_source,
                        media_id=media_id,
                        seasons=item.get("seasons"),
                        episodes=item.get("episodes"),
                        image=item.get("image"),
                        download_hash=item.get("download_hash"),
                        status=item.get("status"),
                        files=json.loads(item.get("files")) if item.get("files") else [],
                        date=item.get("date"),
                        errmsg=item.get("errmsg")
                    ).create(db)
                except Exception as e:
                    logger.error(f"写入 MoviePilot V3 整理历史失败：{e}")
                    continue
