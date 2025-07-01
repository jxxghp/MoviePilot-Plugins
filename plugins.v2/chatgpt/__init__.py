from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.chatgpt.openai import OpenAi
from app.schemas.types import EventType, ChainEventType
from app.schemas import NotificationType


class ChatGPT(_PluginBase):
    # 插件名称
    plugin_name = "ChatGPT"
    # 插件描述
    plugin_desc = "大模型对话与媒体识别增强。"
    # 插件图标
    plugin_icon = "Chatgpt_A.png"
    # 插件版本
    plugin_version = "2.1.7"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "chatgpt_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    openai = None
    _enabled = False
    _proxy = False
    _compatible = False
    _recognize = False
    _openai_url = None
    _openai_key = None
    _model = None
    # 存储多个API密钥
    _api_keys = []
    # 当前使用的密钥索引
    _current_key_index = 0
    # 密钥失效状态
    _key_status = {}
    # 是否发送通知
    _notify = False
    # 自定义提示词
    _customize_prompt = '接下来我会给你一个电影或电视剧的文件名，你需要识别文件名中的名称、版本、分段、年份、分瓣率、季集等信息，并按以下JSON格式返回：{"name":string,"version":string,"part":string,"year":string,"resolution":string,"season":number|null,"episode":number|null}，特别注意返回结果需要严格附合JSON格式，不需要有任何其它的字符。如果中文电影或电视剧的文件名中存在谐音字或字母替代的情况，请还原最有可能的结果。'

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._proxy = config.get("proxy")
            self._compatible = config.get("compatible")
            self._recognize = config.get("recognize")
            self._openai_url = config.get("openai_url")
            self._openai_key = config.get("openai_key")
            self._model = config.get("model")
            self._notify = config.get("notify")
            self._customize_prompt = config.get("customize_prompt")
            # 处理多个API密钥
            if self._openai_key:
                self._api_keys = [key.strip() for key in self._openai_key.split(',') if key.strip()]
                # 初始化密钥状态
                self._key_status = {key: True for key in self._api_keys}
                logger.info(f"ChatGPT插件加载了 {len(self._api_keys)} 个API密钥")

            if self._openai_url and self._api_keys:
                # 使用第一个密钥初始化
                self._current_key_index = 0
                self.init_openai(self._api_keys[self._current_key_index])

    def init_openai(self, api_key):
        """
        初始化OpenAI客户端
        """
        if self._openai_url and api_key:
            self.openai = OpenAi(api_key=api_key, api_url=self._openai_url,
                                 proxy=settings.PROXY if self._proxy else None,
                                 model=self._model, compatible=bool(self._compatible), customize_prompt=self._customize_prompt)
            logger.info(f"ChatGPT插件初始化API客户端成功")
            return True
        return False

    def switch_to_next_key(self, failed_key):
        """
        切换到下一个可用的API密钥
        :return: (is_switched, error_message) 元组，表示是否切换成功及错误信息
        """
        # 标记当前密钥为失效
        self._key_status[failed_key] = False

        # 寻找下一个可用的密钥
        original_index = self._current_key_index
        while True:
            self._current_key_index = (self._current_key_index + 1) % len(self._api_keys)
            next_key = self._api_keys[self._current_key_index]

            # 如果密钥标记为可用或者已经尝试了所有密钥，则使用该密钥
            if self._key_status.get(next_key, True) or self._current_key_index == original_index:
                break

        # 检查是否所有密钥都失效
        if all(not status for status in self._key_status.values()):
            logger.error("所有API密钥均已失效")
            return False, "所有API密钥均已失效，请检查配置"

        # 使用新密钥重新初始化客户端
        next_key = self._api_keys[self._current_key_index]
        logger.info(f"切换到下一个API密钥 {next_key}")
        success = self.init_openai(next_key)
        return success, ""

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
                            },
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
                                            'model': 'proxy',
                                            'label': '使用代理服务器',
                                        }
                                    }
                                ]
                            },
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
                                            'model': 'compatible',
                                            'label': '兼容模式',
                                        }
                                    }
                                ]
                            },
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
                                            'model': 'recognize',
                                            'label': '辅助识别',
                                        }
                                    }
                                ]
                            },
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
                                            'model': 'notify',
                                            'label': '开启通知',
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'openai_url',
                                            'label': 'OpenAI API Url',
                                            'placeholder': 'https://api.openai.com',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'openai_key',
                                            'label': 'API密钥 (多个密钥以逗号分隔)',
                                            'placeholder': 'sk-xxx,sk-yyy'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'model',
                                            'label': '自定义模型',
                                            'placeholder': 'gpt-3.5-turbo',
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
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'rows': 2,
                                            'auto-grow': True,
                                            'model': 'customize_prompt',
                                            'label': '辅助识别提示词',
                                            'hint': '在辅助识别时的给AI的提示词',
                                            'clearable': True,
                                            'persistent-hint': True,
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
                                            'text': '开启插件后，消息交互时使用请[问帮你]开头，或者以？号结尾，或者超过10个汉字/单词，则会触发ChatGPT回复。'
                                                    '开启辅助识别后，内置识别功能无法正常识别种子/文件名称时，将使用ChatGTP进行AI辅助识别，可以提升动漫等非规范命名的识别成功率。'
                                                    '支持输入多个API密钥（以逗号分隔），在密钥调用失败时将自动切换到下一个可用密钥。'
                                                    '开启通知选项后，将在API密钥调用失败时发送系统通知。'
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
            "proxy": False,
            "compatible": False,
            "recognize": False,
            "notify": False,
            "openai_url": "https://api.openai.com",
            "openai_key": "",
            "model": "gpt-3.5-turbo",
            "customize_prompt": '接下来我会给你一个电影或电视剧的文件名，你需要识别文件名中的名称、版本、分段、年份、分瓣率、季集等信息，并按以下JSON格式返回：{"name":string, '
                                '"version":string,"part":string,"year":string,"resolution":string,"season":number|null,"episode":number|null}，特别注意返回结果需要严格附合JSON格式，不需要有任何其它的字符。如果中文电影或电视剧的文件名中存在谐音字或字母替代的情况，请还原最有可能的结果。'
        }

    def get_page(self) -> List[dict]:
        pass

    @staticmethod
    def is_api_error(response):
        """
        判断响应是否表示API错误
        :param response: API响应
        :return: (is_error, error_message) 元组，表示是否错误及错误信息
        """

        # 检查响应是否为字典且包含errorMsg
        if isinstance(response, dict) and response.get("errorMsg"):
            return True, response.get("errorMsg")

        # 检查响应是否为字符串且包含错误信息
        if isinstance(response, str) and "请求ChatGPT出现错误" in response:
            return True, response

        # 如果没有错误信息，则表示调用成功
        return False, ""

    @eventmanager.register(EventType.UserMessage)
    def talk(self, event: Event):
        """
        监听用户消息，获取ChatGPT回复
        """
        if not self._enabled:
            return
        if not self.openai:
            return
        text = event.event_data.get("text")
        userid = event.event_data.get("userid")
        channel = event.event_data.get("channel")
        if not text:
            return
        if text.startswith("http") or text.startswith("magnet") or text.startswith("ftp"):
            return

        # 尝试获取响应，失败时切换API密钥
        retry_count = 0
        max_retries = len(self._api_keys)

        while retry_count < max_retries:
            response = self.openai.get_response(text=text, userid=userid)

            # 判断响应是否正常
            is_error, error_msg = self.is_api_error(response)
            logger.info(f"ChatGPT返回结果：{response}")

            if is_error:
                current_key = self._api_keys[self._current_key_index]
                switched, switch_error = self.switch_to_next_key(current_key)

                # 发送密钥失效通知
                if self._notify:
                    message = f"API密钥 {current_key} 调用失败: {error_msg}"
                    self.post_message(channel=channel, title=message, userid=userid)

                    # 如果所有密钥都失效，发送额外通知
                    if not switched:
                        message = switch_error
                        self.post_message(mtype=NotificationType.Plugin, title="ChatGpt", text=message)

                if not switched:
                    # 所有密钥都失效，发送消息并退出
                    return

                retry_count += 1
            else:
                # 成功获取响应
                self.post_message(channel=channel, title=response, userid=userid)
                return

        # 所有重试都失败
        if self._notify:
            self.post_message(channel=channel,
                              title="无法获取ChatGPT响应，所有API密钥都已失效",
                              userid=userid)

    @eventmanager.register(ChainEventType.NameRecognize)
    def recognize(self, event: Event):
        """
        监听识别事件，使用ChatGPT辅助识别名称
        """
        if not self.openai:
            return
        if not self._recognize:
            return
        if not event.event_data:
            return
        title = event.event_data.get("title")
        if not title:
            return

        # 尝试获取媒体名称，失败时切换API密钥
        retry_count = 0
        max_retries = len(self._api_keys)

        while retry_count < max_retries:
            response = self.openai.get_media_name(filename=title)
            logger.info(f"ChatGPT返回结果：{response}")

            # 判断响应是否正常
            is_error, error_msg = self.is_api_error(response)

            # 如果不是错误但返回字典中没有name字段，也视为错误
            if not is_error and isinstance(response, dict) and not response.get("name"):
                is_error = True
                error_msg = "未返回有效识别结果"

            if is_error:
                # 发生错误，尝试切换密钥
                current_key = self._api_keys[self._current_key_index]
                switched, switch_error = self.switch_to_next_key(current_key)

                # 发送密钥失效通知 (通过系统通知，因为这里没有用户交互)
                if self._notify:
                    message = f"API密钥 {current_key} 调用失败: {error_msg}"
                    self.post_message(mtype=NotificationType.Plugin, title="ChatGpt", text=message)

                    # 如果所有密钥都失效，发送额外通知
                    if not switched:
                        message = switch_error
                        self.post_message(mtype=NotificationType.Plugin, title="ChatGpt", text=message)

                if not switched:
                    # 所有密钥都失效
                    return

                retry_count += 1
            else:
                # 成功获取结果
                event.event_data = {
                    'title': title,
                    'name': response.get("name"),
                    'year': response.get("year"),
                    'season': response.get("season"),
                    'episode': response.get("episode")
                }
                return

        # 所有重试都失败
        if self._notify:
            logger.error(f"无法识别标题 {title}，所有API密钥都已失效")
            self.post_message(mtype=NotificationType.Plugin,
                              title="ChatGpt",
                              text=f"无法识别标题 {title}，所有API密钥都已失效")

    def stop_service(self):
        """
        退出插件
        """
        pass
