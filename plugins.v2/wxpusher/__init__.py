from typing import Any, List, Dict, Tuple, Optional

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class WxPusher(_PluginBase):
    # 插件名称
    plugin_name = "WxPusher消息通知"
    # 插件描述
    plugin_desc = "支持使用 WxPusher 将通知推送到微信及全平台 App（极简推送 SPT / 标准推送 AppToken）。"
    # 插件图标
    plugin_icon = "WxPusher_A.png"
    # 插件版本
    plugin_version = "1.1.2"
    # 插件作者
    plugin_author = "zjiecode"
    # 作者主页
    author_url = "https://github.com/wxpusher/wxpusher-docs"
    # 插件配置项ID前缀
    plugin_config_prefix = "wxpusher_"
    # 加载顺序
    plugin_order = 28
    # 可使用的用户级别
    auth_level = 1

    # WxPusher 官方地址（托管服务，地址固定）
    _base_url = "https://wxpusher.zjiecode.com"
    # 内容格式固定为 HTML
    _content_type = 2
    # SPT 单次最多接收者
    _max_spt = 10
    # 引导用户获取 SPT 的二维码
    _spt_qrcode = ("https://wxpusher.zjiecode.com/api/qrcode/"
                   "RwjGLMOPTYp35zSYQr0HxbCPrV9eU0wKVBXU1D5VVtya0cQXEJWPjqBdW3gKLifS.jpg")
    # 帮助链接（带 utm 归因）
    _doc_spt = "https://wxpusher.zjiecode.com/docs/?utm_source=moviepilot#/?id=spt"
    _admin_url = "https://wxpusher.zjiecode.com/admin/?utm_source=moviepilot"
    _doc_url = "https://wxpusher.zjiecode.com/docs/?utm_source=moviepilot"

    # 私有属性
    _enabled = False
    _onlyonce = False
    _push_mode = "simple"
    _spt = None
    _app_token = None
    _uids = None
    _topic_ids = None
    _msgtypes = []

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._push_mode = config.get("push_mode") or "simple"
            self._spt = config.get("spt")
            self._app_token = config.get("app_token")
            self._uids = config.get("uids")
            self._topic_ids = config.get("topic_ids")
            self._msgtypes = config.get("msgtypes") or []

        # 校验：极简推送最多 10 个 SPT，超过则拒绝保存生效
        if self._push_mode == "simple":
            spts = self._split(self._spt)
            if len(spts) > self._max_spt:
                msg = f"WxPusher 极简推送最多填写 {self._max_spt} 个 SPT，当前 {len(spts)} 个，配置未生效，请删减后重新保存。"
                logger.error(msg)
                self.systemmessage.put(msg)
                self._enabled = False
                self._onlyonce = False
                self.__save_config()
                return

        if self._onlyonce:
            logger.info("WxPusher 测试插件，立即运行一次")
            self._onlyonce = False
            self.__save_config()
            self._send("WxPusher消息测试通知", "WxPusher 消息通知插件已启用")

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "push_mode": self._push_mode,
            "spt": self._spt,
            "app_token": self._app_token,
            "uids": self._uids,
            "topic_ids": self._topic_ids,
            "msgtypes": self._msgtypes,
        })

    def get_state(self) -> bool:
        if not self._enabled:
            return False
        if self._push_mode == "standard":
            return bool(self._app_token) and bool(self._uids or self._topic_ids)
        spts = self._split(self._spt)
        return 1 <= len(spts) <= self._max_spt

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 遍历 NotificationType 枚举，生成消息类型选项
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
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '发送测试消息（勾选后点「保存」立即发送）'}
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
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'push_mode',
                                            'label': '推送方式',
                                            'items': [
                                                {'title': '极简推送（SPT，最简单）', 'value': 'simple'},
                                                {'title': '标准推送（AppToken）', 'value': 'standard'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型（留空=全部推送）',
                                            'items': MsgTypeOptions
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 极简推送：SPT 输入
                    {
                        'component': 'VRow',
                        'props': {'show': "{{push_mode == 'simple'}}"},
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'spt',
                                            'label': 'SPT（可填多个，英文逗号分隔，最多 10 个）',
                                            'placeholder': 'SPT_xxx,SPT_yyy',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 标准推送：AppToken
                    {
                        'component': 'VRow',
                        'props': {'show': "{{push_mode == 'standard'}}"},
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'app_token',
                                            'label': '应用 AppToken',
                                            'placeholder': 'AT_xxx（在管理后台创建应用后获得）',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 标准推送：UID / 主题
                    {
                        'component': 'VRow',
                        'props': {'show': "{{push_mode == 'standard'}}"},
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'uids',
                                            'label': '用户 UID（逗号分隔）',
                                            'placeholder': 'UID_xxx,UID_yyy',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'topic_ids',
                                            'label': '主题 ID（逗号分隔，用于群发）',
                                            'placeholder': '123,456',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 极简推送说明 + 二维码（二维码内嵌在提示框内，与文字融为一体）
                    {
                        'component': 'VRow',
                        'props': {'show': "{{push_mode == 'simple'}}"},
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {'type': 'info', 'variant': 'tonal', 'class': 'align-start'},
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {'class': 'd-flex align-start justify-space-between'},
                                                'content': [
                                                    {
                                                        'component': 'div',
                                                        'props': {'class': 'text-body-2 me-4', 'style': 'max-width: 330px;'},
                                                        'text': '极简推送（SPT）：发送和接收是同一个人，无需注册、无需创建应用。'
                                                                '下载 WxPusher App 或用微信扫描右侧二维码，即可获得你的专属 SPT（形如 SPT_xxx）。'
                                                                '可填写多个 SPT（英文逗号分隔），单次最多 10 个，超过将无法保存生效。'
                                                                'SPT 相当于收件地址+密钥，请勿泄漏。'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {'class': 'text-center flex-shrink-0'},
                                                        'content': [
                                                            {
                                                                'component': 'VImg',
                                                                'props': {
                                                                    'src': self._spt_qrcode,
                                                                    'width': 120,
                                                                    'height': 120,
                                                                    'class': 'rounded',
                                                                }
                                                            },
                                                            {
                                                                'component': 'div',
                                                                'props': {'class': 'text-caption text-medium-emphasis mt-1'},
                                                                'text': '微信扫码获取 SPT'
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VBtn',
                                                'props': {
                                                    'variant': 'tonal',
                                                    'color': 'primary',
                                                    'size': 'small',
                                                    'class': 'mt-3',
                                                    'href': self._doc_spt,
                                                    'target': '_blank',
                                                    'prependIcon': 'mdi-open-in-new',
                                                },
                                                'text': 'SPT 官方说明'
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 标准推送说明 + 官方链接
                    {
                        'component': 'VRow',
                        'props': {'show': "{{push_mode == 'standard'}}"},
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {'type': 'info', 'variant': 'tonal', 'class': 'align-start'},
                                        'content': [
                                            {
                                                'component': 'div',
                                                'props': {'class': 'text-body-2'},
                                                'text': '标准推送（AppToken）：发送者与接收者一般不是同一人，可管理接收用户，支持一对多群发等高级能力。'
                                                        '需先在管理后台创建应用，获得 AppToken（形如 AT_xxx，仅你本人可见，请严格保密）。'
                                                        '用户扫码关注你的应用后，获取用户UID（形如 UID_xxx），填入 UID 可单独发送；'
                                                        '也可让用户订阅「主题」，填入主题 ID 向所有订阅者群发（用户扫码订阅主题接口，不用维护UID列表）。'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {'class': 'mt-3 d-flex flex-wrap ga-2'},
                                                'content': [
                                                    {
                                                        'component': 'VBtn',
                                                        'props': {
                                                            'variant': 'tonal',
                                                            'color': 'primary',
                                                            'size': 'small',
                                                            'href': self._admin_url,
                                                            'target': '_blank',
                                                            'prependIcon': 'mdi-open-in-new',
                                                        },
                                                        'text': '打开管理后台'
                                                    },
                                                    {
                                                        'component': 'VBtn',
                                                        'props': {
                                                            'variant': 'tonal',
                                                            'color': 'primary',
                                                            'size': 'small',
                                                            'href': self._doc_url,
                                                            'target': '_blank',
                                                            'prependIcon': 'mdi-open-in-new',
                                                        },
                                                        'text': '标准推送文档'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "push_mode": "simple",
            "spt": "",
            "app_token": "",
            "uids": "",
            "topic_ids": "",
            "msgtypes": [],
        }

    def get_page(self) -> List[dict]:
        pass

    def _build_content(self, title: str, text: str) -> Tuple[str, str]:
        """
        组装 WxPusher 的 HTML 内容与纯文本摘要
        """
        def br(s: Optional[str]) -> str:
            return (s or "").replace("\n", "<br/>")

        if title and text:
            content = f"<b>{br(title)}</b><br/><br/>{br(text)}"
        else:
            content = br(title or text or "")
        # summary 接口侧最长 100 字，用纯文本
        summary = (title or text or "").replace("\n", " ")[:100]
        return content, summary

    def _send(self, title: str, text: str) -> Optional[Tuple[bool, str]]:
        """
        发送消息
        :param title: 标题
        :param text: 内容
        """
        try:
            content, summary = self._build_content(title, text)
            payload = {"content": content, "summary": summary, "contentType": self._content_type}
            if self._push_mode == "standard":
                if not self._app_token or not (self._uids or self._topic_ids):
                    return False, "参数未配置"
                payload["appToken"] = self._app_token
                payload["uids"] = self._split(self._uids)
                payload["topicIds"] = [int(i) for i in self._split(self._topic_ids)]
                url = f"{self._base_url}/api/send/message"
            else:
                spts = self._split(self._spt)
                if not spts:
                    return False, "参数未配置"
                if len(spts) > self._max_spt:
                    return False, f"SPT 最多 {self._max_spt} 个"
                if len(spts) == 1:
                    payload["spt"] = spts[0]
                else:
                    payload["sptList"] = spts
                url = f"{self._base_url}/api/send/message/simple-push"

            res = RequestUtils(content_type="application/json").post_res(url, json=payload)
            if res and res.status_code == 200:
                res_json = res.json() or {}
                code = res_json.get("code")
                message = res_json.get("msg")
                if code == 1000:
                    logger.info(f"WxPusher 消息发送成功，消息内容：{title}")
                    return True, "发送成功"
                logger.warn(f"WxPusher 消息发送失败：{message}（code={code}）")
                return False, message
            elif res is not None:
                logger.warn(f"WxPusher 消息发送失败，错误码：{res.status_code}，错误原因：{res.reason}")
                return False, f"错误码：{res.status_code}"
            else:
                logger.warn("WxPusher 消息发送失败：未获取到返回信息")
                return False, "未获取到返回信息"
        except Exception as e:
            logger.error(f"WxPusher 消息发送失败：{str(e)}")
            return False, str(e)

    @staticmethod
    def _split(value: Optional[str]) -> List[str]:
        """
        将逗号分隔字符串拆成非空数组（兼容中文逗号）
        """
        if not value:
            return []
        value = value.replace("，", ",")
        return [item.strip() for item in value.split(",") if item.strip()]

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        """
        消息发送事件
        """
        if not self.get_state():
            return

        if not event.event_data:
            return

        msg_body = event.event_data
        # 渠道，值不为 None 时为交互消息，跳过
        channel = msg_body.get("channel")
        if channel:
            return
        # 类型
        msg_type: NotificationType = msg_body.get("type")
        # 标题
        title = msg_body.get("title")
        # 文本
        text = msg_body.get("text")

        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return

        if (msg_type and self._msgtypes
                and msg_type.name not in self._msgtypes):
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        return self._send(title, text)

    def stop_service(self):
        """
        退出插件
        """
        pass
