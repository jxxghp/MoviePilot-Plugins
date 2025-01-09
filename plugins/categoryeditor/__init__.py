from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.modules.themoviedb import CategoryHelper
from app.plugins import _PluginBase


class CategoryEditor(_PluginBase):
    # 插件名称
    plugin_name = "二级分类策略"
    # 插件描述
    plugin_desc = "编辑下载和整理时自动二级分类的目录规则。"
    # 插件图标
    plugin_icon = "Bookstack_A.png"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "categoryeditor_"
    # 加载顺序
    plugin_order = 5
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _content = ""

    user_yaml = settings.CONFIG_PATH / "category.yaml"
    default_yaml = settings.INNER_CONFIG_PATH / "category.yaml"

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._content = config.get("content") or ""
            # 写入文件
            if self._enabled:
                self.user_yaml.write_text(self._content, encoding="utf-8")
                # 立即生效
                CategoryHelper().init()
                self.systemmessage.put("二级分类策略已更新，请注意同步调整目录设置，插件将恢复关闭状态！", title="二级分类策略")
                self._enabled = False
                self.update_config({
                    "enabled": False,
                    "content": self._content
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件（写入配置文件）',
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
                                        'component': 'VAceEditor',
                                        'props': {
                                            'modelvalue': 'content',
                                            'lang': 'yaml',
                                            'theme': 'monokai',
                                            'style': 'height: 30rem',
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
            "content": self.default_yaml.read_text(encoding="utf-8")
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
