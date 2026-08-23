import threading

from gotify import Gotify

from queue import Queue
from time import monotonic, time
from typing import Any, List, Dict, Tuple
from urllib.parse import urlencode

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class GotifyMsg(_PluginBase):
    """通过单一后台队列向 Gotify 服务发送 MoviePilot 通知。"""

    # 后台发送结束的最长等待时间，超时后保留线程句柄供宿主重试收敛。
    SHUTDOWN_TIMEOUT = 3.0
    _STOP_SENTINEL = object()

    # 插件名称
    plugin_name = "gotify消息通知"
    # 插件描述
    plugin_desc = "支持使用gotify发送消息通知。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/gotify/logo/refs/heads/master/gotify-logo.png"
    # 插件版本
    plugin_version = "1.2"
    # 插件作者
    plugin_author = "lethargicScribe"
    # 作者主页
    author_url = "https://github.com/lethargicScribe"
    # 插件配置项ID前缀
    plugin_config_prefix = "gotifymsg_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _server = None
    _token = None
    _msgtypes = []

    # 上次发送时间
    last_send_time = 0
    # 消息发送间隔（秒）
    send_interval = 5
    # gotify实例
    gotify = None

    def __init__(self):
        """初始化实例级队列及其生命周期所有权。"""
        super().__init__()
        self._lifecycle_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._accepting_messages = False
        self.message_queue = Queue()
        self.processing_thread = None

    def init_plugin(self, config: dict = None):
        """应用配置，并在旧队列线程完全退出后启动新线程。"""
        if not self._quiesce():
            logger.error("Gotify 消息发送线程尚未退出，跳过本次重新初始化")
            return

        with self._lifecycle_lock:
            self._stop_event = threading.Event()
            self.message_queue = Queue()
            if config:
                self._enabled = config.get("enabled")
                self._server = config.get("server")
                self._token = config.get("token")
                self._msgtypes = config.get("msgtypes") or []

                if self._enabled and self._token and self._server:
                    # 初始化gotify客户端实例
                    self.gotify = Gotify(
                        base_url=self._server,
                        app_token=self._token,
                    )
                    # 启动处理队列的后台线程
                    thread = threading.Thread(
                        target=self.process_queue,
                        name="gotifymsg-worker",
                        daemon=True,
                    )
                    self.processing_thread = thread
                    thread.start()
                    self._accepting_messages = True

    def get_state(self) -> bool:
        """返回插件配置是否满足发送条件。"""
        return self._enabled and (True if self._server and self._token else False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """该消息插件不注册远程命令。"""
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """该消息插件不注册动态 API。"""
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 编历 NotificationType 枚举，生成消息类型选项
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'server',
                                            'label': '服务器',
                                            'placeholder': 'https://gotify.example.com',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': 'gotify 令牌',
                                            'placeholder': 'xxxxx',
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型',
                                            'items': MsgTypeOptions
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            'server': '',
            'token': '',
            'msgtypes': []
        }

    def get_page(self) -> List[dict]:
        """该消息插件不提供详情页面。"""
        pass

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        """
        消息发送事件，将消息加入队列
        """
        with self._lifecycle_lock:
            if not self._accepting_messages or not self.get_state() or not event.event_data:
                return

            msg_body = event.event_data
            # 验证消息的有效性
            if not msg_body.get("title") and not msg_body.get("text"):
                logger.warn("标题和内容不能同时为空")
                return

            # admission 与入队共用一把锁，确保停止封口后不会再产生尾任务。
            self.message_queue.put(msg_body)
            logger.info("消息已加入队列等待发送")

    def process_queue(self):
        """
        处理队列中的消息，按间隔时间发送
        """
        message_queue = self.message_queue
        stop_event = self._stop_event
        while True:
            msg_body = message_queue.get()
            try:
                if msg_body is self._STOP_SENTINEL or stop_event.is_set():
                    logger.info("消息发送线程正在退出...")
                    return

                # Event.wait 让限流等待也能被停止信号立即唤醒。
                wait_time = self.send_interval - (time() - self.last_send_time)
                if wait_time > 0 and stop_event.wait(wait_time):
                    return
                if stop_event.is_set():
                    return

                channel = msg_body.get("channel")
                if channel:
                    continue
                msg_type: NotificationType = msg_body.get("type")
                title = msg_body.get("title")
                text = msg_body.get("text")
                if msg_type and self._msgtypes and msg_type.name not in self._msgtypes:
                    logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
                    continue

                try:
                    self.gotify.create_message(text, title=title, priority=0)
                except Exception as msg_e:
                    logger.error(f"gotify消息发送失败，{str(msg_e)}")
            finally:
                message_queue.task_done()

    def _quiesce(self, timeout: float = None) -> bool:
        """封闭新消息并在共享预算内等待后台发送线程退出。"""
        budget = self.SHUTDOWN_TIMEOUT if timeout is None else max(0.0, timeout)
        deadline = monotonic() + budget
        with self._lifecycle_lock:
            self._accepting_messages = False
            self._stop_event.set()
            thread = self.processing_thread
            if thread is None:
                return True
            if thread.is_alive():
                self.message_queue.put(self._STOP_SENTINEL)
                if thread is threading.current_thread():
                    return False
                thread.join(timeout=max(0.0, deadline - monotonic()))
            if thread.is_alive():
                logger.warning("Gotify 消息发送线程未在停止预算内退出")
                return False
            if self.processing_thread is thread:
                self.processing_thread = None
            return True

    def close(self) -> bool:
        """兼容新版宿主的第一阶段关闭钩子。"""
        return self._quiesce()

    def stop_service(self) -> bool:
        """兼容旧版宿主的停止钩子，并复用幂等收敛逻辑。"""
        return self._quiesce()
