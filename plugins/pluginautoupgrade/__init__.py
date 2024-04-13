from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from threading import Event as ThreadEvent, RLock
from typing import Any, List, Dict, Tuple, Optional
import pytz
from app import schemas
from app.api.endpoints.plugin import install
from app.core.config import settings
from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase


class PluginAutoUpgrade(_PluginBase):
    # 插件名称
    plugin_name = "插件自动升级"
    # 插件描述
    plugin_desc = "定时检测、升级插件。"
    # 插件图标
    plugin_icon = "PluginAutoUpgrade.png"
    # 插件版本
    plugin_version = "1.0"
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

    # 依赖组件
    # 插件管理器
    __plugin_manager: PluginManager = PluginManager()

    # 配置相关
    # 插件缺省配置
    __config_default: Dict[str, Any] = {
        'cron': '* 0/4 * * *'
    }
    # 插件用户配置
    __config: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 加载插件配置
        self.__config = config
        # 停止现有服务
        self.stop_service()
        # 如果需要立即运行一次
        if self.__get_config_item(config_key='run_once'):
            if (self.__start_scheduler()):
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
        state = True if self.__get_config_item(config_key='enable') \
                        and self.__get_config_item(config_key='cron') \
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
        # 已安装的在线插件下拉框数据
        installed_online_plugin_options = self.__get_installed_online_plugin_options()
        form = [{
            'component': 'VForm',
            'content': [{ # 业务无关总控
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
                        'xxl': 4, 'xl': 4, 'lg': 4, 'md': 4, 'sm': 6, 'xs': 12
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
        pass

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
        if config_value is None and use_default:
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
        installed_local_plugins = [local_plugin for local_plugin in local_plugins if local_plugin and local_plugin.installed]
        return installed_local_plugins

    @classmethod
    def __get_installed_local_plugin(cls, plugin_id: str) -> List[schemas.Plugin]:
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
        installed_online_plugins = [online_plugin for online_plugin in online_plugins if online_plugin and online_plugin.installed]
        return installed_online_plugins

    @classmethod
    def __get_installed_online_plugin_options(cls) -> Dict[str, Any]:
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
    def __get_has_update_online_plugins(cls) -> List[schemas.Plugin]:
        """
        获取所有可升级的在线插件
        """
        installed_online_plugins = cls.__get_installed_online_plugins()
        if not installed_online_plugins:
            return None
        has_update_online_plugins = [installed_online_plugin for installed_online_plugin in installed_online_plugins if installed_online_plugin and installed_online_plugin.has_update]
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
        self.__send_notify(results=upgrade_results)

    def __upgrade_single(self, online_plugin: schemas.Plugin) -> Dict[str, Any]:
        """
        单个升级
        """
        if not online_plugin or not online_plugin.has_update or not online_plugin.id or not online_plugin.repo_url or not self.__check_allow_upgrade(plugin_id=online_plugin.id):
            return None
        installed_local_plugin = self.__get_installed_local_plugin(plugin_id=online_plugin.id)
        if not installed_local_plugin:
            return None
        response = install(plugin_id=online_plugin.id, repo_url=online_plugin.repo_url, force=True)
        logger.info(f"插件升级结果: plugin_name = {online_plugin.plugin_name}, plugin_version = v{installed_local_plugin.plugin_version} -> v{online_plugin.plugin_version}, success = {response.success}, message = {response.message}")
        return {
            'success': response.success,
            'message': response.message,
            'plugin_id': online_plugin.id,
            'plugin_name': online_plugin.plugin_name,
            'new_plugin_version': online_plugin.plugin_version,
            'old_plugin_version': installed_local_plugin.plugin_version
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
            if result.get('success'):
                text += f"{result.get('plugin_name')}升级[v{result.get('old_plugin_version')} -> v{result.get('new_plugin_version')}]成功\n"
            else:
                text += f"{result.get('plugin_name')}升级[v{result.get('old_plugin_version')} -> v{result.get('new_plugin_version')}]失败：{result.get('message')}\n"
        return text
