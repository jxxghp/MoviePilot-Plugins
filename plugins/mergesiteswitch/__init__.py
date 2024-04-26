import inspect
import os
from typing import Any, List, Dict, Tuple

from app.core.event import eventmanager, Event
from app.db.models.site import Site
from app.db.site_oper import SiteOper
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import SystemConfigKey, EventType


class MergeSiteSwitch(_PluginBase):
    # 插件名称
    plugin_name = "聚合站点开关"
    # 插件描述
    plugin_desc = "统一管理所有与站点相关的开关。"
    # 插件图标
    plugin_icon = "world.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "hotlcc"
    # 作者主页
    author_url = "https://github.com/hotlcc"
    # 插件配置项ID前缀
    plugin_config_prefix = "com.hotlcc.mergesiteswitch."
    # 加载顺序
    plugin_order = 66
    # 可使用的用户级别
    auth_level = 2

    # 依赖组件
    # 站点操作
    __site_oper: SiteOper = SiteOper()
    # 系统配置操作
    __system_config_oper: SystemConfigOper = SystemConfigOper()

    # 其它插件ID
    # 站点自动签到
    __plugin_id_auto_signin: str = 'AutoSignIn'
    # 站点数据统计
    __plugin_id_site_statistic: str = 'SiteStatistic'
    # IYUU自动辅种
    __plugin_id_iyuu_auto_seed: str = 'IYUUAutoSeed'
    # 站点刷流
    __plugin_id_brush_flow: str = 'BrushFlow'

    # 配置相关
    # 插件缺省配置
    __config_default: Dict[str, Any] = {}
    # 插件用户配置
    __config: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 加载配置
        self.__config = config
        # 当页面通过调用接口保存配置时保存其它各项配置
        if self.__check_stack_is_save_config_request():
            self.__set_config(config=config)

    def get_state(self) -> bool:
        """
        获取插件状态
        """
        return self.__check_any_follow_enable_sites()

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
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点选项
        site_options = self.__get_site_options()
        # 已安装的插件IDs
        installed_plugin_ids = self.__get_installed_plugin_ids()
        # 建议的配置
        config_suggest = {}

        # 表单内容
        form_content = [{
            'component': 'VRow',
            'content': [{
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 12, 'xl': 12, 'lg': 12, 'md': 12, 'sm': 12, 'xs': 12
                },
                'content': [{
                    'component': 'VSelect',
                    'props': {
                        'model': 'enable_sites',
                        'label': '启用的站点',
                        'multiple': True,
                        'chips': True,
                        'items': site_options,
                        'hint': '对应功能【站点管理 / 添加编辑站点 / 启用】'
                    }
                }]
            }]
        }, {
            'component': 'VRow',
            'content': [{
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                },
                'content': [{
                    'component': 'VSelect',
                    'props': {
                        'model': 'search_sites',
                        'label': '设定 / 搜索 / 搜索站点',
                        'multiple': True,
                        'chips': True,
                        'items': site_options,
                        'hint': '只有选中的站点才会在搜索中使用。'
                    }
                }]
            }, {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                },
                'content': [{
                    'component': 'VSwitch',
                    'props': {
                        'model': 'search_follow_enable_sites',
                        'label': '跟随启用的站点',
                        'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                    }
                }]
            }]
        }, {
            'component': 'VRow',
            'content': [{
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                },
                'content': [{
                    'component': 'VSelect',
                    'props': {
                        'model': 'rss_sites',
                        'label': '设定 / 订阅 / 订阅站点',
                        'multiple': True,
                        'chips': True,
                        'items': site_options,
                        'hint': '只有选中的站点才会在订阅中使用。'
                    }
                }]
            }, {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                },
                'content': [{
                    'component': 'VSwitch',
                    'props': {
                        'model': 'rss_follow_enable_sites',
                        'label': '跟随启用的站点',
                        'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                    }
                }]
            }]
        }]
        # 站点自动签到
        if self.__plugin_id_auto_signin in installed_plugin_ids:
            form_content.append({
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'signin_sites',
                            'label': '插件 / 站点自动签到 / 签到站点',
                            'multiple': True,
                            'chips': True,
                            'items': site_options,
                            'hint': '只有选中的站点才会在签到中使用。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'signin_follow_enable_sites',
                            'label': '跟随启用的站点',
                            'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'login_sites',
                            'label': '插件 / 站点自动签到 / 登录站点',
                            'multiple': True,
                            'chips': True,
                            'items': site_options,
                            'hint': '只有选中的站点才会在登录中使用。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'login_follow_enable_sites',
                            'label': '跟随启用的站点',
                            'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                        }
                    }]
                }]
            })
        # 站点数据统计
        if self.__plugin_id_site_statistic in installed_plugin_ids:
            form_content.append({
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'statistic_sites',
                            'label': '插件 / 站点数据统计 / 统计站点',
                            'multiple': True,
                            'chips': True,
                            'items': site_options,
                            'hint': '缺省时默认全部站点。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'statistic_follow_enable_sites',
                            'label': '跟随启用的站点',
                            'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                        }
                    }]
                }]
            })
        # IYUU自动辅种
        if self.__plugin_id_iyuu_auto_seed in installed_plugin_ids:
            form_content.append({
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'iyuu_seed_sites',
                            'label': '插件 / IYUU自动辅种 / 辅种站点',
                            'multiple': True,
                            'chips': True,
                            'items': site_options,
                            'hint': '缺省时默认全部站点。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'iyuu_seed_follow_enable_sites',
                            'label': '跟随启用的站点',
                            'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                        }
                    }]
                }]
            })
        # 站点刷流
        if self.__plugin_id_brush_flow in installed_plugin_ids:
            form_content.append({
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 9, 'xl': 9, 'lg': 9, 'md': 9, 'sm': 8, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'brush_flow_sites',
                            'label': '插件 / 站点刷流 / 刷流站点',
                            'multiple': True,
                            'chips': True,
                            'items': site_options,
                            'hint': '只有选中的站点才会在刷流中使用。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 3, 'xl': 3, 'lg': 3, 'md': 3, 'sm': 4, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'brush_flow_follow_enable_sites',
                            'label': '跟随启用的站点',
                            'hint': '与站点的启用状态保持一致，保存时会立即生效，并在后台监听站点状态变化实时生效。'
                        }
                    }]
                }]
            })
        # 提示信息
        form_content.append({
            'component': 'VRow',
            'content': [{
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'xxl': 12, 'xl': 12, 'lg': 12, 'md': 12, 'sm': 12, 'xs': 12
                },
                'content': [{
                    'component': 'VAlert',
                    'props': {
                        'type': 'warning',
                        'variant': 'tonal'
                    },
                    'text': '点击保存后会立即生效，各项站点开关配置即会更新！'
                }]
            }]
        })
        # 表单
        form = [{
            'component': 'VForm',
            'content': form_content
        }]

        # 重载配置
        self.__get_config()
        return form, config_suggest

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    @classmethod
    def __check_stack_exist_function(cls, package_name: str, function_name: str) -> bool:
        """
        判断当前调用栈是否存在指定的函数
        """
        if not package_name or not function_name:
            return False
        for stack in inspect.stack():
            if stack.function != 'set_plugin_config':
                continue
            package_path = package_name.replace('.', os.sep)
            if stack.filename.endswith(f"{package_path}.py") or stack.filename.endswith(f"{package_path}{os.sep}__init__.py"):
                return True
        return False

    @classmethod
    def __check_stack_is_save_config_request(cls) -> bool:
        """
        判断当前调用栈是否来源于“插件配置保存”接口
        """
        return cls.__check_stack_exist_function('app.api.endpoints.plugin', 'set_plugin_config')

    def __get_config_value(self, config_key: str, use_default: bool = True) -> Any:
        """
        获取插件配置值
        :param config_key: 配置键
        :param use_default: 是否使用缺省值
        :return: 配置值
        """
        if not config_key:
            return None
        config = self.__config if self.__config else {}
        config_value = config.get(config_key)
        if config_value is None and use_default:
            config_default = self.__config_default if self.__config_default else {}
            config_value = config_default.get(config_key)
        return config_value

    def __check_follow_enable_sites(self, config_key: str, plugin_id: str = None, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断某个跟随按钮是否打开
        :param plugin_id: 传插件ID时还要同时根据插件是否安装进行判断
        """
        if not self.__get_config_value(config_key=config_key):
            return False
        if not plugin_id:
            return True
        if not installed_plugin_ids:
            installed_plugin_ids = self.__get_installed_plugin_ids()
        return plugin_id in installed_plugin_ids

    def __check_search_follow_enable_sites(self) -> bool:
        """
        判断搜索站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='search_follow_enable_sites')

    def __check_rss_follow_enable_sites(self) -> bool:
        """
        判断订阅站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='rss_follow_enable_sites')

    def __check_signin_follow_enable_sites(self, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断签到站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='signin_follow_enable_sites', plugin_id=self.__plugin_id_auto_signin, installed_plugin_ids=installed_plugin_ids)

    def __check_login_follow_enable_sites(self, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断登录站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='login_follow_enable_sites', plugin_id=self.__plugin_id_auto_signin, installed_plugin_ids=installed_plugin_ids)

    def __check_statistic_follow_enable_sites(self, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断统计站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='statistic_follow_enable_sites', plugin_id=self.__plugin_id_site_statistic, installed_plugin_ids=installed_plugin_ids)

    def __check_iyuu_seed_follow_enable_sites(self, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断iyuu辅种站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='iyuu_seed_follow_enable_sites', plugin_id=self.__plugin_id_iyuu_auto_seed, installed_plugin_ids=installed_plugin_ids)

    def __check_brush_flow_follow_enable_sites(self, installed_plugin_ids: List[str] = None) -> bool:
        """
        判断刷流站点的跟随按钮是否打开
        """
        return self.__check_follow_enable_sites(config_key='brush_flow_follow_enable_sites', plugin_id=self.__plugin_id_brush_flow, installed_plugin_ids=installed_plugin_ids)

    def __check_any_follow_enable_sites(self) -> bool:
        """
        判断是否开启任意跟随按钮
        """
        # 已安装的插件IDs
        installed_plugin_ids = self.__get_installed_plugin_ids()
        return True if self.__check_search_follow_enable_sites() \
                    or self.__check_rss_follow_enable_sites() \
                    or self.__check_signin_follow_enable_sites(installed_plugin_ids=installed_plugin_ids) \
                    or self.__check_login_follow_enable_sites(installed_plugin_ids=installed_plugin_ids) \
                    or self.__check_statistic_follow_enable_sites(installed_plugin_ids=installed_plugin_ids) \
                    or self.__check_iyuu_seed_follow_enable_sites(installed_plugin_ids=installed_plugin_ids) \
                    or self.__check_brush_flow_follow_enable_sites(installed_plugin_ids=installed_plugin_ids) else False

    def __get_site_options(self) -> List[Dict[str, Any]]:
        """
        获取站点选项
        """
        sites = self.__site_oper.list_order_by_pri()
        if not sites:
            return []
        return [{
            'title': site.name,
            'value': site.id
        } for site in sites if site]

    def __get_installed_plugin_ids(self):
        """
        获取已安装的插件IDs
        """
        installed_plugin_ids = self.__system_config_oper.get(SystemConfigKey.UserInstalledPlugins)
        return installed_plugin_ids if installed_plugin_ids else []

    def __get_config(self):
        """
        获取配置，包含聚合外部配置
        """
        config = self.get_config()
        if not config:
            config = {}
        config.update({
            'enable_sites': self.__get_enable_site_ids(),
            'search_sites': self.__get_search_site_ids(),
            'rss_sites': self.__get_rss_site_ids(),
        })
        # 已安装的插件IDs
        installed_plugin_ids = self.__get_installed_plugin_ids()
        if self.__plugin_id_auto_signin in installed_plugin_ids:
            config.update({
                'signin_sites': self.__get_signin_site_ids(),
                'login_sites': self.__get_login_site_ids(),
            })
        if self.__plugin_id_site_statistic in installed_plugin_ids:
            config.update({
                'statistic_sites': self.__get_statistic_site_ids(),
            })
        if self.__plugin_id_iyuu_auto_seed in installed_plugin_ids:
            config.update({
                'iyuu_seed_sites': self.__get_iyuu_seed_site_ids(),
            })
        if self.__plugin_id_brush_flow in installed_plugin_ids:
            config.update({
                'brush_flow_sites': self.__get_brush_flow_site_ids(),
            })
        self.update_config(config=config)
        return config

    def __pre_config_follow_enable_sites(self, config: dict) -> dict:
        """
        处理跟随站点
        """
        if not config:
            config = {}
        enable_sites = config.get('enable_sites') or []
        if config.get('search_follow_enable_sites'):
            config.update({"search_sites": enable_sites.copy()})
        if config.get('rss_follow_enable_sites'):
            config.update({"rss_sites": enable_sites.copy()})
        if config.get('signin_follow_enable_sites'):
            config.update({"signin_sites": enable_sites.copy()})
        if config.get('login_follow_enable_sites'):
            config.update({"login_sites": enable_sites.copy()})
        if config.get('statistic_follow_enable_sites'):
            config.update({"statistic_sites": enable_sites.copy()})
        if config.get('iyuu_seed_follow_enable_sites'):
            config.update({"iyuu_seed_sites": enable_sites.copy()})
        if config.get('brush_flow_follow_enable_sites'):
            config.update({"brush_flow_sites": enable_sites.copy()})
        return config

    def __pre_config(self, config: dict) -> dict:
        """
        预处理配置
        """
        config = self.__pre_config_follow_enable_sites(config=config)
        logger.debug(f"配置预处理完成: {config}")
        return config

    def __set_config(self, config: dict):
        """
        保存配置，包含保存外部配置到各自表
        """
        # 预处理配置
        config = self.__pre_config(config=config)
        # 更新各项配置
        self.update_config(config=config)
        logger.info("插件配置更新完成")
        self.__set_enable_site_ids(config.get('enable_sites'))
        self.__set_search_site_ids(config.get('search_sites'))
        self.__set_rss_site_ids(config.get('rss_sites'))
        # 已安装的插件IDs
        installed_plugin_ids = self.__get_installed_plugin_ids()
        if self.__plugin_id_auto_signin in installed_plugin_ids:
            self.__set_signin_site_ids(config.get('signin_sites'))
            self.__set_login_site_ids(config.get('login_sites'))
        if self.__plugin_id_site_statistic in installed_plugin_ids:
            self.__set_statistic_site_ids(config.get('statistic_sites'))
        if self.__plugin_id_iyuu_auto_seed in installed_plugin_ids:
            self.__set_iyuu_seed_site_ids(config.get('iyuu_seed_sites'))
        if self.__plugin_id_brush_flow in installed_plugin_ids:
            self.__set_brush_flow_site_ids(config.get('brush_flow_sites'))
        return config

    def __get_enable_site_ids(self) -> List[int]:
        """
        获取启用的站点IDs
        """
        sites = self.__site_oper.list_order_by_pri()
        if not sites:
            return []
        return [site.id for site in sites if site and site.is_active]

    def __set_enable_site_ids(self, site_ids: List[int]):
        """
        设置启用的站点IDs
        """
        sites = self.__site_oper.list_order_by_pri()
        if not sites:
            return
        for site in sites:
            if not site_ids or site.id not in site_ids:
                if site.is_active:
                    self.__site_oper.update(site.id, {'is_active': False})
            else:
                if not site.is_active:
                    self.__site_oper.update(site.id, {'is_active': True})
        logger.info("启用的站点配置完成")

    def __get_search_site_ids(self) -> List[int]:
        """
        获取搜索站点IDs
        """
        sites = self.__system_config_oper.get(SystemConfigKey.IndexerSites)
        return sites if sites else []

    def __set_search_site_ids(self, site_ids: List[int]):
        """
        设置搜索站点IDs
        """
        self.__system_config_oper.set(SystemConfigKey.IndexerSites, site_ids)
        logger.info("搜索站点配置完成")

    def __get_rss_site_ids(self) -> List[int]:
        """
        获取订阅站点IDs
        """
        sites = self.__system_config_oper.get(SystemConfigKey.RssSites)
        return sites if sites else []

    def __set_rss_site_ids(self, site_ids: List[int]):
        """
        设置订阅站点IDs
        """
        self.__system_config_oper.set(SystemConfigKey.RssSites, site_ids)
        logger.info("订阅站点配置完成")

    def __get_plugin_config_value(self, plugin_id: str, config_key: str) -> Any:
        """
        获取插件配置值
        """
        if not plugin_id or not config_key:
            return None
        config = self.get_config(plugin_id)
        if not config:
            return None
        return config.get(config_key)

    def __set_plugin_config_value(self, plugin_id: str, config_key: str, config_value: Any) -> Any:
        """
        设置插件配置值
        """
        if not plugin_id or not config_key:
            return
        config = self.get_config(plugin_id)
        if not config:
            config = {}
        config.update({config_key: config_value})
        self.update_config(plugin_id=plugin_id, config=config)

    def __get_signin_site_ids(self) -> List[int]:
        """
        获取签到站点IDs
        """
        sites = self.__get_plugin_config_value(self.__plugin_id_auto_signin, 'sign_sites')
        return sites if sites else []

    def __set_signin_site_ids(self, site_ids: List[int]):
        """
        设置签到站点IDs
        """
        self.__set_plugin_config_value(self.__plugin_id_auto_signin, 'sign_sites', site_ids)
        logger.info("签到站点配置完成")

    def __get_login_site_ids(self) -> List[int]:
        """
        获取登录站点IDs
        """
        sites = self.__get_plugin_config_value(self.__plugin_id_auto_signin, 'login_sites')
        return sites if sites else []

    def __set_login_site_ids(self, site_ids: List[int]):
        """
        设置登录站点IDs
        """
        self.__set_plugin_config_value(self.__plugin_id_auto_signin, 'login_sites', site_ids)
        logger.info("登录站点配置完成")

    def __get_statistic_site_ids(self) -> List[int]:
        """
        获取统计站点IDs
        """
        sites = self.__get_plugin_config_value(self.__plugin_id_site_statistic, 'statistic_sites')
        return sites if sites else []

    def __set_statistic_site_ids(self, site_ids: List[int]):
        """
        设置统计站点IDs
        """
        self.__set_plugin_config_value(self.__plugin_id_site_statistic, 'statistic_sites', site_ids)
        logger.info("统计站点配置完成")

    def __get_iyuu_seed_site_ids(self) -> List[int]:
        """
        获取iyuu自动辅种站点IDs
        """
        sites = self.__get_plugin_config_value(self.__plugin_id_iyuu_auto_seed, 'sites')
        return sites if sites else []

    def __set_iyuu_seed_site_ids(self, site_ids: List[int]):
        """
        设置iyuu自动辅种站点IDs
        """
        self.__set_plugin_config_value(self.__plugin_id_iyuu_auto_seed, 'sites', site_ids)
        logger.info("IYUU辅种站点配置完成")

    def __get_brush_flow_site_ids(self) -> List[int]:
        """
        获取刷流站点IDs
        """
        sites = self.__get_plugin_config_value(self.__plugin_id_brush_flow, 'brushsites')
        return sites if sites else []

    def __set_brush_flow_site_ids(self, site_ids: List[int]):
        """
        设置刷流站点IDs
        """
        self.__set_plugin_config_value(self.__plugin_id_brush_flow, 'brushsites', site_ids)
        logger.info("刷流站点配置完成")

    def __update_search_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_search_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_search_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_search_site_ids(site_ids=site_ids)

    def __update_rss_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_rss_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_rss_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_rss_site_ids(site_ids=site_ids)

    def __update_signin_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_signin_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_signin_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_signin_site_ids(site_ids=site_ids)

    def __update_login_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_login_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_login_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_login_site_ids(site_ids=site_ids)

    def __update_statistic_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_statistic_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_statistic_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_statistic_site_ids(site_ids=site_ids)

    def __update_iyuu_seed_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_iyuu_seed_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_iyuu_seed_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_iyuu_seed_site_ids(site_ids=site_ids)

    def __update_brush_flow_site_ids_by_site(self, site_id: int, site_status: bool):
        if site_id == None:
            return
        site_ids = self.__get_brush_flow_site_ids() or []
        if site_id not in site_ids and site_status:
            site_ids.append(site_id)
            self.__set_brush_flow_site_ids(site_ids=site_ids)
        elif site_id in site_ids and not site_status:
            site_ids.remove(site_id)
            self.__set_brush_flow_site_ids(site_ids=site_ids)

    def __update_site_ids_for_site_event(self, site_id: int, site_status: bool):
        """
        针对站点事件更新各项配置
        """
        if site_id == None:
            return
        if self.__check_search_follow_enable_sites():
            self.__update_search_site_ids_by_site(site_id=site_id, site_status=site_status)
        if self.__check_rss_follow_enable_sites():
            self.__update_rss_site_ids_by_site(site_id=site_id, site_status=site_status)
        # 已安装的插件IDs
        installed_plugin_ids = self.__get_installed_plugin_ids()
        if self.__check_signin_follow_enable_sites(installed_plugin_ids=installed_plugin_ids):
            self.__update_signin_site_ids_by_site(site_id=site_id, site_status=site_status)
        if self.__check_login_follow_enable_sites(installed_plugin_ids=installed_plugin_ids):
            self.__update_login_site_ids_by_site(site_id=site_id, site_status=site_status)
        if self.__check_statistic_follow_enable_sites(installed_plugin_ids=installed_plugin_ids):
            self.__update_statistic_site_ids_by_site(site_id=site_id, site_status=site_status)
        if self.__check_iyuu_seed_follow_enable_sites(installed_plugin_ids=installed_plugin_ids):
            self.__update_iyuu_seed_site_ids_by_site(site_id=site_id, site_status=site_status)
        if self.__check_brush_flow_follow_enable_sites(installed_plugin_ids=installed_plugin_ids):
            self.__update_brush_flow_site_ids_by_site(site_id=site_id, site_status=site_status)

    @eventmanager.register(EventType.SiteUpdated)
    def listen_site_updated_event(self, event: Event = None):
        """
        监听站点更新事件
        """
        logger.info('监听到站点更新事件')
        if not event or not event.event_data:
            logger.warn('事件信息无效，忽略事件')
            return
        domain = event.event_data.get("domain")
        if not domain:
            logger.warn('事件信息无效，忽略事件')
            return
        if not self.__check_any_follow_enable_sites():
            logger.warn('未打开任一【跟随启用的站点】开关，忽略事件')
            return
        site = self.__site_oper.get_by_domain(domain=domain)
        if not site:
            logger.warn(f'目标站点不存在，忽略事件: domain = {domain}')
            return
        self.__update_site_ids_for_site_event(site_id=site.id, site_status=site.is_active)
        logger.info('站点更新事件监听任务执行完成')

    @eventmanager.register(EventType.SiteDeleted)
    def listen_site_deleted_event(self, event: Event = None):
        """
        监听站点删除事件
        """
        logger.info('监听到站点删除事件')
        if not event or not event.event_data:
            logger.warn('事件信息无效，忽略事件')
            return
        site_id = event.event_data.get("site_id")
        if site_id == None:
            logger.warn('事件信息无效，忽略事件')
            return
        if not self.__check_any_follow_enable_sites():
            logger.warn('未打开任一【跟随启用的站点】开关，忽略事件')
            return
        self.__update_site_ids_for_site_event(site_id=site_id, site_status=False)
        logger.info('站点删除事件监听任务执行完成')
