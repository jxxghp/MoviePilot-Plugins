import json
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

from app.db import SessionFactory
from app.db.models import TransferHistory
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


class HistoryToV2(_PluginBase):
    # 插件名称
    plugin_name = "历史记录迁移"
    # 插件描述
    plugin_desc = "将MoviePilot V1版本的整理历史记录迁移至V2版本。"
    # 插件图标
    plugin_icon = "Moviepilot_A.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "historytov2_"
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
                            self.__insert_history(history)
                            # 处理成功一批
                            total += len(history)
                            logger.info(f"第 {page} 页处理完成，共处理 {total} 条记录")
                            # 获取下一页历史记录
                            page += 1
                            history = self.__get_history(token, page=page)
                        # 处理完成
                        logger.info(f"历史记录迁移完成，共迁移 {total} 条记录！")
                        self.systemmessage.put(f"历史记录迁移完成，共迁移 {total} 条记录！", title="MoviePilot历史记录迁移")
                else:
                    self.systemmessage.put(f"配置不完整，服务启动失败！", title="MoviePilot历史记录迁移")
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
        return self._enabled

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
                                            'text': 'MoviePilot V1 需要是启动状态且能正常访问，V1版本和V2版本目录映射需要保持一致，迁移时间可能较长，完成后会收到系统通知。'
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
        logger.info(f"登录MoviePilot: {url}")
        # 发送POST请求
        response = RequestUtils(headers=headers).post_res(url, data=data)
        # 检查响应状态
        if response.status_code == 200:
            # 成功获取token
            token_data = response.json()
            logger.info(f"登录MoviePilot成功，获取token：{token_data['access_token']}", )
            return token_data["access_token"]
        else:
            # 处理失败响应
            logger.warn(f"登录MoviePilot失败: {response.json()}")
            self.systemmessage.put(f"登录MoviePilot失败，无法同步历史记录！", title="MoviePilot历史记录迁移")
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
        logger.info(f"查询转移历史记录: {url}，params: {params}")
        # 发送GET请求
        response = RequestUtils(headers=headers).get_res(url, params=params)
        # 检查响应状态
        if response.status_code == 200:
            # 返回数据
            response_data = response.json()
            data = response_data.get("data")
            logger.info(f"查询转移历史记录成功，共 {len(data.get('list'))} 条记录")
            return data.get("list")
        else:
            # 处理失败响应
            logger.warn("查询转移历史记录失败:", response.json())
            self.systemmessage.put(f"查询转移历史记录失败，无法同步历史记录！", title="MoviePilot历史记录迁移")
            return []

    @staticmethod
    def __insert_history(history: List[dict]):
        """
        插入历史记录
        """
        if not history:
            return
        with SessionFactory() as db:
            for item in history:
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
                        tmdbid=item.get("tmdbid"),
                        imdbid=item.get("imdbid"),
                        tvdbid=item.get("tvdbid"),
                        doubanid=item.get("doubanid"),
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
                    logger.error(f"插入历史记录失败：{e}")
                    continue
