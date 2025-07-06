import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.config import settings
from app.core.plugin import PluginManager
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import SystemConfigKey


class CleanInvalidPlugin(_PluginBase):
    # 插件名称
    plugin_name = "清理无效插件"
    # 插件描述
    plugin_desc = "删除数据库中无法安装的插件记录，避免反复重装。"
    # 插件图标
    plugin_icon = "delete.jpg"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "cddjr"
    # 作者主页
    author_url = "https://github.com/cddjr"
    # 插件配置项ID前缀
    plugin_config_prefix = "cleaninvalidplugin_"
    # 加载顺序
    plugin_order = 999
    # 可使用的用户级别
    auth_level = 1

    # 需要清理的插件
    _invalid_plugin_ids = []

    def init_plugin(self, config: dict = None):
        """
        生效配置信息

        :param config: 配置信息字典
        """
        try:
            if not config:
                return
            self._invalid_plugin_ids = config.get("invalid_plugin_ids") or []
            if not self._invalid_plugin_ids:
                return

            config_oper = SystemConfigOper()
            plugin_manager = PluginManager()

            valid_plugins = set(plugin_manager.get_plugin_ids() or [])
            all_plugins: List[str] = (
                config_oper.get(SystemConfigKey.UserInstalledPlugins) or []
            )

            all_plugins_modified = []
            for plugin_id in all_plugins:
                if plugin_id not in self._invalid_plugin_ids:
                    all_plugins_modified.append(plugin_id)
                    continue
                try:
                    # 再一次确保是无效
                    if plugin_id in valid_plugins:
                        all_plugins_modified.append(plugin_id)
                        logger.warn(f"{plugin_id} 是有效插件")
                        continue
                    logger.info(f"正在清理无效插件 {plugin_id}")
                    plugin_dir = (
                        Path(settings.ROOT_PATH) / "app" / "plugins" / plugin_id.lower()
                    )
                    if plugin_dir.exists():
                        shutil.rmtree(plugin_dir, ignore_errors=True)
                    else:
                        logger.warn(f"插件目录 {plugin_dir} 不存在")
                except Exception as e:
                    logger.warn(
                        f"清理无效插件 {plugin_id} 产生异常: {e}", exc_info=True
                    )

            # 更新安装记录
            config_oper.set(SystemConfigKey.UserInstalledPlugins, all_plugins_modified)
            self._invalid_plugin_ids = []
            self.update_config(
                {
                    "invalid_plugin_ids": [],
                }
            )
        except Exception as e:
            logger.error(f"异常: {e}", exc_info=True)

    def get_state(self) -> bool:
        """
        获取插件运行状态
        """
        return False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册插件远程命令

        [{
            "cmd": "/xx",
            "event": EventType.xx,
            "desc": "名称",
            "category": "分类，需要注册到Wechat时必须有分类",
            "data": {}
        }]
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件API

        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "auth: "apikey",  # 鉴权类型：apikey/bear
            "summary": "API名称",
            "description": "API说明"
        }]
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，插件配置页面使用Vuetify组件拼装，参考：https://vuetifyjs.com/

        :return: 1、页面配置（vuetify模式）或 None（vue模式）；2、默认数据结构
        """
        invalid_items = self.get_invalid_plugins()
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "multiple": True,
                                            "chips": True,
                                            "model": "invalid_plugin_ids",
                                            "label": "插件ID",
                                            "items": invalid_items,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": (
                                                f"当前有{len(invalid_items)}个插件无法安装，选择需要清理的插件，点击【保存】"
                                                if invalid_items
                                                else "所有插件均已成功安装，无需清理"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "invalid_plugin_ids": self._invalid_plugin_ids,
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        插件详情页面使用Vuetify组件拼装，参考：https://vuetifyjs.com/

        :return: 页面配置（vuetify模式）或 None（vue模式）
        """
        pass

    def stop_service(self):
        """
        停止插件
        """
        pass

    @staticmethod
    def get_invalid_plugins():
        """
        获取本地无效插件
        """
        try:
            # 已安装插件
            config_oper = SystemConfigOper()
            plugin_manager = PluginManager()

            # 所有安装的插件（包括安装后未能成功加载的插件）
            all_plugins = set(
                config_oper.get(SystemConfigKey.UserInstalledPlugins) or []
            )

            # 获取有效插件(成功安装并能正常加载)
            valid_plugins = set(plugin_manager.get_plugin_ids() or [])

            # 过滤无效的插件
            invalid_plugins = all_plugins - valid_plugins

            # 构建 VSelect 数据
            return [
                {"title": f"{plugin_id}", "value": plugin_id}
                for plugin_id in invalid_plugins
            ]
        except Exception as e:
            logger.error(f"异常: {e}", exc_info=True)
            return []
