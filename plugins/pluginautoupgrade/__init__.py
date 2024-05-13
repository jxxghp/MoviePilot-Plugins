from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from threading import Event as ThreadEvent, RLock
from typing import Any, List, Dict, Tuple, Optional
import pytz
from app import schemas
from app.core.config import settings
from app.core.plugin import PluginManager
from app.db.systemconfig_oper import SystemConfigOper
from app.helper.plugin import PluginHelper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas.types import SystemConfigKey


class PluginAutoUpgrade(_PluginBase):
    # 插件名称
    plugin_name = "插件自动升级"
    # 插件描述
    plugin_desc = "定时检测、升级插件。"
    # 插件图标
    plugin_icon = "PluginAutoUpgrade.png"
    # 插件版本
    plugin_version = "1.6"
    # 插件作者
    plugin_author = "hotlcc"
    # 作者主页
    author_url = "https://github.com/hotlcc"
    # 插件配置项ID前缀
    plugin_config_prefix = "com.hotlcc.pluginautoupgrade."
    # 加载顺序
    plugin_order = 66
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    # 调度器
    __scheduler: Optional[BackgroundScheduler] = None
    # 退出事件
    __exit_event: ThreadEvent = ThreadEvent()
    # 任务锁
    __task_lock: RLock = RLock()
    # 插件数据key：升级记录
    __data_key_upgrade_records = "upgrade_records"

    # 依赖组件
    # 插件管理器
    __plugin_manager: PluginManager = PluginManager()

    # 配置相关
    # 插件缺省配置
    __config_default: Dict[str, Any] = {
        'cron': '* 0/4 * * *',
        'save_record_quantity': 100,
        'display_record_quantity': 10,
    }
    # 插件用户配置
    __config: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 修正配置
        config = self.__fix_config(config=config)
        # 加载插件配置
        self.__config = config
        # 停止现有服务
        self.stop_service()
        # 如果需要立即运行一次
        if self.__get_config_item(config_key='run_once'):
            if self.__start_scheduler():
                self.__scheduler.add_job(func=self.__try_run,
                                         trigger='date',
                                         run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                         name=f'{self.plugin_name}-立即运行一次')
                logger.info(f"立即运行一次成功")
            # 关闭一次性开关
            self.__config['run_once'] = False
            self.update_config(self.__config)

    def get_state(self) -> bool:
        """
        获取插件状态
        """
        state = True if self.__get_config_item(config_key='enable') and self.__get_config_item(config_key='cron') \
            else False
        return state

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
        try:
            if self.get_state():
                cron = self.__get_config_item(config_key='cron')
                return [{
                    "id": "PluginAutoUpgradeTimerService",
                    "name": f"{self.plugin_name}定时服务",
                    "trigger": CronTrigger.from_crontab(cron),
                    "func": self.__try_run,
                    "kwargs": {}
                }]
            else:
                return []
        except Exception as e:
            logger.error(f"注册插件公共服务异常: {str(e)}", exc_info=True)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 建议的配置
        config_suggest = {}
        # 合并默认配置
        config_suggest.update(self.__config_default)
        # 定时周期
        cron = self.__config_default.get('cron')
        # 保存记录数量
        save_record_quantity = self.__config_default.get('save_record_quantity')
        # 展示记录数量
        display_record_quantity = self.__config_default.get('display_record_quantity')
        # 已安装的在线插件下拉框数据
        installed_online_plugin_options = self.__get_installed_online_plugin_options()
        form = [{
            'component': 'VForm',
            'content': [{  # 业务无关总控
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable',
                            'label': '启用插件',
                            'hint': '插件总开关'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'enable_notify',
                            'label': '发送通知',
                            'hint': '执行插件任务后是否发送通知'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSwitch',
                        'props': {
                            'model': 'run_once',
                            'label': '立即运行一次',
                            'hint': '保存插件配置后是否立即触发一次插件任务运行'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'cron',
                            'label': '定时执行周期',
                            'placeholder': cron,
                            'hint': f'设置插件任务执行周期。支持5位cron表达式，应避免任务执行过于频繁，缺省时为：【{cron}】'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'save_record_quantity',
                            'label': '保存记录数量',
                            'type': 'number',
                            'placeholder': save_record_quantity,
                            'hint': f'设置插件最多保存多少条插件升级记录。缺省时为{save_record_quantity}。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VTextField',
                        'props': {
                            'model': 'display_record_quantity',
                            'label': '展示记录数量',
                            'type': 'number',
                            'placeholder': display_record_quantity,
                            'hint': f'设置插件数据页最多展示多少条插件升级记录。缺省时为{display_record_quantity}。'
                        }
                    }]
                }]
            }, {
                'component': 'VRow',
                'content': [{
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'include_plugins',
                            'label': '包含的插件',
                            'multiple': True,
                            'chips': True,
                            'items': installed_online_plugin_options,
                            'hint': '选择哪些插件需要自动升级，不选时默认全部已安装插件。'
                        }
                    }]
                }, {
                    'component': 'VCol',
                    'props': {
                        'cols': 12,
                        'xxl': 6, 'xl': 6, 'lg': 6, 'md': 6, 'sm': 6, 'xs': 12
                    },
                    'content': [{
                        'component': 'VSelect',
                        'props': {
                            'model': 'exclude_plugins',
                            'label': '排除的插件',
                            'multiple': True,
                            'chips': True,
                            'items': installed_online_plugin_options,
                            'hint': '选择哪些插件需要排除升级（在【包含的插件】的基础上排除），不选时默认不排除。'
                        }
                    }]
                }]
            }]
        }]
        return form, config_suggest

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        page_data = self.__get_upgrade_records_to_page_data()
        if page_data:
            contents = [{
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [{
                    'component': 'td',
                    'props': {
                        'class': 'whitespace-nowrap'
                    },
                    'text': item.get('datetime_str')
                }, {
                    'component': 'td',
                    'props': {
                        'class': 'whitespace-nowrap'
                    },
                    'text': item.get('plugin_name')
                }, {
                    'component': 'td',
                    'props': {
                        'class': 'whitespace-nowrap'
                    },
                    'text': f'v{item.get("old_plugin_version")}'
                }, {
                    'component': 'td',
                    'props': {
                        'class': 'whitespace-nowrap'
                    },
                    'text': f'v{item.get("new_plugin_version")}'
                }, {
                    'component': 'td',
                    'text': item.get('info')
                }, {
                    'component': 'td',
                    'text': item.get('upgrade_info')
                }]
            } for item in page_data if item]
        else:
            contents = [{
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [{
                    'component': 'td',
                    'props': {
                        'colspan': '6',
                        'class': 'text-center'
                    },
                    'text': '暂无数据'
                }]
            }]
        return [{
            'component': 'VTable',
            'props': {
                'hover': True
            },
            'content': [{
                'component': 'thead',
                'content': [{
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '时间'
                }, {
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '插件名称'
                }, {
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '旧版本'
                }, {
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '新版本'
                }, {
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '执行结果'
                }, {
                    'component': 'th',
                    'props': {
                        'class': 'text-start ps-4'
                    },
                    'text': '升级描述'
                }]
            }, {
                'component': 'tbody',
                'content': contents
            }]
        }]

    def stop_service(self):
        """
        退出插件
        """
        try:
            logger.info('尝试停止插件服务...')
            self.__exit_event.set()
            self.__stop_scheduler()
            logger.info('插件服务停止成功')
        except Exception as e:
            logger.error(f"插件服务停止异常: {str(e)}", exc_info=True)
        finally:
            self.__exit_event.clear()

    def __fix_config(self, config: dict) -> dict:
        """
        修正配置
        """
        if not config:
            config = {}
        save_record_quantity = config.get("save_record_quantity")
        config['save_record_quantity'] = int(save_record_quantity) if save_record_quantity else None
        display_record_quantity = config.get("display_record_quantity")
        config['display_record_quantity'] = int(display_record_quantity) if display_record_quantity else None
        self.update_config(config=config)
        return config

    def __get_config_item(self, config_key: str, use_default: bool = True) -> Any:
        """
        获取插件配置项
        :param config_key: 配置键
        :param use_default: 是否使用缺省值
        :return: 配置值
        """
        if not config_key:
            return None
        config = self.__config if self.__config else {}
        config_value = config.get(config_key)
        if (config_value is None or config_value == '') and use_default:
            config_default = self.__config_default if self.__config_default else {}
            config_value = config_default.get(config_key)
        return config_value

    @classmethod
    def __get_local_plugins(cls) -> List[schemas.Plugin]:
        """
        获取所有本地插件信息
        """
        local_plugins = cls.__plugin_manager.get_local_plugins()
        return local_plugins

    @classmethod
    def __get_installed_local_plugins(cls) -> List[schemas.Plugin]:
        """
        获取所有已安装的本地插件信息
        """
        local_plugins = cls.__get_local_plugins()
        installed_local_plugins = [local_plugin for local_plugin in local_plugins if
                                   local_plugin and local_plugin.installed]
        return installed_local_plugins

    @classmethod
    def __get_installed_local_plugin(cls, plugin_id: str) -> Optional[schemas.Plugin]:
        """
        获取指定的已安装的本地插件信息
        """
        if not plugin_id:
            return None
        # 已安装的本地插件
        installed_plugins = cls.__get_installed_local_plugins()
        for installed_plugin in installed_plugins:
            if installed_plugin and installed_plugin.id and installed_plugin.id == plugin_id:
                return installed_plugin
        return None

    @classmethod
    def __get_online_plugins(cls) -> List[schemas.Plugin]:
        """
        获取所有在线插件
        """
        online_plugins = cls.__plugin_manager.get_online_plugins()
        return online_plugins

    @classmethod
    def __get_installed_online_plugins(cls) -> List[schemas.Plugin]:
        """
        获取所有已安装的在线插件
        """
        online_plugins = cls.__get_online_plugins()
        installed_online_plugins = [online_plugin for online_plugin in online_plugins if
                                    online_plugin and online_plugin.installed]
        return installed_online_plugins

    @classmethod
    def __get_installed_online_plugin_options(cls) -> list:
        """
        获取所有已安装的在线插件的选项数据
        """
        installed_online_plugin_options = []
        installed_online_plugins = cls.__get_installed_online_plugins()
        for installed_online_plugin in installed_online_plugins:
            if not installed_online_plugin:
                continue
            installed_online_plugin_options.append({
                'value': installed_online_plugin.id,
                'title': installed_online_plugin.plugin_name
            })
        return installed_online_plugin_options

    @classmethod
    def __get_has_update_online_plugins(cls) -> Optional[List[schemas.Plugin]]:
        """
        获取所有可升级的在线插件
        """
        installed_online_plugins = cls.__get_installed_online_plugins()
        if not installed_online_plugins:
            return None
        has_update_online_plugins = [installed_online_plugin for installed_online_plugin in installed_online_plugins if
                                     installed_online_plugin and installed_online_plugin.has_update]
        return has_update_online_plugins

    def __start_scheduler(self, timezone=None) -> bool:
        """
        启动调度器
        :param timezone: 时区
        """
        try:
            if not self.__scheduler:
                if not timezone:
                    timezone = settings.TZ
                self.__scheduler = BackgroundScheduler(timezone=timezone)
                logger.debug(f"插件服务调度器初始化完成: timezone = {str(timezone)}")
            if not self.__scheduler.running:
                self.__scheduler.start()
                logger.debug(f"插件服务调度器启动成功")
                self.__scheduler.print_jobs()
            return True
        except Exception as e:
            logger.error(f"插件服务调度器启动异常: {str(e)}", exc_info=True)
            return False

    def __stop_scheduler(self):
        """
        停止调度器
        """
        try:
            logger.info('尝试停止插件服务调度器...')
            if self.__scheduler:
                self.__scheduler.remove_all_jobs()
                if self.__scheduler.running:
                    self.__scheduler.shutdown()
                self.__scheduler = None
                logger.info('插件服务调度器停止成功')
            else:
                logger.info('插件未启用服务调度器，无须停止')
        except Exception as e:
            logger.error(f"插件服务调度器停止异常: {str(e)}", exc_info=True)

    def __check_allow_upgrade(self, plugin_id: str) -> bool:
        """
        判断插件是否允许升级：包含、排除
        """
        if not plugin_id:
            return False
        exclude_plugins = self.__get_config_item('exclude_plugins')
        if exclude_plugins and plugin_id in exclude_plugins:
            return False
        include_plugins = self.__get_config_item('include_plugins')
        if not include_plugins or plugin_id in include_plugins:
            return True
        else:
            return False

    @staticmethod
    def __install_plugin(plugin_id: str, repo_url: str = "", force: bool = False) -> Tuple[bool, Optional[str]]:
        """
        安装插件，参考：app.api.endpoints.plugin.install
        :param plugin_id: 插件ID
        :param repo_url: 插件仓库URL
        :param force: 是否强制安装
        """
        # 已安装插件
        install_plugins = SystemConfigOper().get(SystemConfigKey.UserInstalledPlugins) or []
        # 如果是非本地括件，或者强制安装时，则需要下载安装
        if repo_url and (force or plugin_id not in PluginManager().get_plugin_ids()):
            # 下载安装
            state, msg = PluginHelper().install(pid=plugin_id, repo_url=repo_url)
            if not state:
                # 安装失败
                return False, msg
        # 安装插件
        if plugin_id not in install_plugins:
            install_plugins.append(plugin_id)
            # 保存设置
            SystemConfigOper().set(SystemConfigKey.UserInstalledPlugins, install_plugins)
        # 加载插件到内存
        PluginManager().reload_plugin(plugin_id)
        # 注册插件服务
        Scheduler().update_plugin_job(plugin_id)
        return True, None

    def __try_run(self):
        """
        尝试运行插件任务
        """
        if not self.__task_lock.acquire(blocking=False):
            logger.info('已有进行中的任务，本次不执行')
            return
        try:
            self.__run()
        finally:
            self.__task_lock.release()

    def __run(self):
        """"
        运行插件任务
        """
        self.__upgrade_batch()

    def __upgrade_batch(self):
        """
        批量升级
        """
        has_update_online_plugins = self.__get_has_update_online_plugins()
        upgrade_results = []
        for has_update_online_plugin in has_update_online_plugins:
            upgrade_result = self.__upgrade_single(has_update_online_plugin)
            if upgrade_result:
                upgrade_results.append(upgrade_result)
        # 保存升级记录
        self.__save_upgrade_records(records=upgrade_results)
        # 发送通知
        self.__send_notify(results=upgrade_results)

    def __upgrade_single(self, online_plugin: schemas.Plugin) -> Optional[Dict[str, Any]]:
        """
        单个升级
        """
        if not online_plugin or not online_plugin.has_update or not online_plugin.id or not online_plugin.repo_url or not self.__check_allow_upgrade(
                plugin_id=online_plugin.id):
            return None
        installed_local_plugin = self.__get_installed_local_plugin(plugin_id=online_plugin.id)
        if not installed_local_plugin:
            return None
        success, message = self.__install_plugin(plugin_id=online_plugin.id, repo_url=online_plugin.repo_url,
                                                 force=True)
        logger.info(
            f"插件升级结果: plugin_name = {online_plugin.plugin_name}, plugin_version = v{installed_local_plugin.plugin_version} -> v{online_plugin.plugin_version}, success = {success}, message = {message}")
        return {
            'success': success,
            'message': message,
            'plugin_id': online_plugin.id,
            'plugin_name': online_plugin.plugin_name,
            'new_plugin_version': online_plugin.plugin_version,
            'old_plugin_version': installed_local_plugin.plugin_version,
            'datetime_str': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'upgrade_info': self.__extract_upgrade_history(online_plugin)
        }

    def __send_notify(self, results: List[Dict[str, Any]]):
        """
        发送通知
        :param results: 插件升级结果
        """
        if not results or not self.__get_config_item('enable_notify'):
            return
        text = self.__build_notify_message(results=results)
        if not text:
            return
        self.post_message(title=f'{self.plugin_name}任务执行结果', text=text)

    @staticmethod
    def __build_notify_message(results: List[Dict[str, Any]]) -> str:
        """
        构建通知消息内容
        """
        text = ''
        if not results:
            return text
        for result in results:
            if not result:
                continue
            text += f"【{result.get('plugin_name')}】[v{result.get('old_plugin_version')} -> v{result.get('new_plugin_version')}]："
            if result.get('success'):
                text += f"成功\n"
            else:
                text += f"{result.get('message')}\n"
        return text

    def __save_upgrade_records(self, records: List[Dict[str, Any]]):
        """
        保存升级记录
        """
        if not records:
            return
        upgrade_records = self.get_data(self.__data_key_upgrade_records)
        if not upgrade_records:
            upgrade_records = []
        upgrade_records.extend(records)
        # 最多保存多少条
        save_record_quantity = self.__get_config_item('save_record_quantity')
        upgrade_records = upgrade_records[-save_record_quantity:]
        self.save_data(self.__data_key_upgrade_records, upgrade_records)

    @staticmethod
    def __convert_upgrade_record_to_page_data(upgrade_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not upgrade_record:
            return None
        info = "成功" if upgrade_record.get("success") else upgrade_record.get("message")
        upgrade_record.update({"info": info})
        return upgrade_record

    def __get_upgrade_records_to_page_data(self) -> List[Dict[str, Any]]:
        """
        获取升级记录为page数据
        """
        upgrade_records = self.get_data(self.__data_key_upgrade_records)
        if not upgrade_records:
            return []
        # 只展示最近多少条
        display_record_quantity = self.__get_config_item('display_record_quantity')
        upgrade_records = upgrade_records[-display_record_quantity:]
        page_data = [self.__convert_upgrade_record_to_page_data(upgrade_record) for upgrade_record in upgrade_records if
                     upgrade_record]
        # 按时间倒序
        page_data = sorted(page_data, key=lambda item: item.get("datetime_str"), reverse=True)
        return page_data

    @staticmethod
    def __extract_upgrade_history(plugin: schemas.Plugin, version: str = None) -> Optional[str]:
        """
        提取指定版本的升级历史信息
        """
        if not plugin or not plugin.history:
            return None
        if not version:
            version = plugin.plugin_version
        if not version:
            return None
        version_history = plugin.history.get(f'v{version}')
        if not version_history:
            # 兼容处理
            version_history = plugin.history.get(version)
        return version_history
