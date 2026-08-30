import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body

from app import schemas
from app.sdk.config import settings
from app.sdk.events import eventmanager, Event
from app.sdk.logging import logger
from app.sdk.services import ServiceConfigHelper
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class EmailMsg(_PluginBase):
    """邮箱消息通知插件。

    通过 SMTP 发送邮件通知，收件人根据通知发送范围设置（all/user/admin）
    从用户管理邮箱中获取，邮箱为空时跳过。
    """

    # 插件名称
    plugin_name = "邮箱通知"
    # 插件描述
    plugin_desc = "支持通过 SMTP 发送邮件通知，收件人根据通知发送范围设置从用户管理邮箱中获取。"
    # 插件图标
    plugin_icon = "Email_A.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "LLL001a"
    # 作者主页
    author_url = "https://github.com/LLL001a"
    # 插件配置项ID前缀
    plugin_config_prefix = "emailmsg_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _smtp_server = None
    _smtp_port = None
    _ssl = False
    _sender = None
    _password = None
    _msgtypes = []

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._smtp_server = config.get("smtp_server")
        self._smtp_port = config.get("smtp_port")
        self._ssl = bool(config.get("ssl"))
        self._sender = config.get("sender")
        self._password = config.get("password")
        self._msgtypes = config.get("msgtypes") or []

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled and bool(self._smtp_server and self._sender and self._password)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表。"""
        return [
            {
                "path": "/send",
                "endpoint": self.send_custom_notification,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动发送自定义通知",
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
        # 遍历 NotificationType 枚举，生成消息类型选项
        msg_type_options = []
        for item in NotificationType:
            msg_type_options.append({
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
                                            'model': 'smtp_server',
                                            'label': 'SMTP服务器',
                                            'placeholder': 'smtp.qq.com',
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
                                            'model': 'smtp_port',
                                            'label': 'SMTP端口',
                                            'placeholder': '465',
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
                                            'model': 'sender',
                                            'label': '发件人邮箱',
                                            'placeholder': 'xxx@qq.com',
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
                                            'label': 'SMTP授权码/密码',
                                            'placeholder': '邮箱授权码',
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ssl',
                                            'label': '使用SSL加密',
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
                                            'items': msg_type_options
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
                                            'text': '收件人根据通知发送范围设置（all/user/admin）从用户管理邮箱中获取，邮箱为空时跳过。多数邮箱需使用授权码而非登录密码。'
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
                                            'model': 'custom_title',
                                            'label': '手动发送 - 通知标题',
                                            'placeholder': '请输入通知标题',
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'custom_text',
                                            'label': '手动发送 - 通知内容',
                                            'placeholder': '请输入通知内容',
                                            'rows': 4,
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
                                        'component': 'VBtn',
                                        'props': {
                                            'color': 'primary',
                                            'variant': 'tonal',
                                            'prepend-icon': 'mdi-send',
                                            'onclick': "function(e) { window.MoviePilotAPI.post('plugin/EmailMsg/send', {title: model.custom_title, text: model.custom_text}).then(function(r) { if (r && r.success === false) { alert(r.message || '发送失败') } else { alert('发送成功'); model.custom_title = ''; model.custom_text = '' } }).catch(function(err) { console.error(err); alert('发送失败') }) }",
                                        },
                                        'text': '发送通知',
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "smtp_server": "",
            "smtp_port": "465",
            "sender": "",
            "password": "",
            "ssl": True,
            "msgtypes": []
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页面，包含插件介绍。"""
        return [
            {
                "component": "VCard",
                "props": {
                    "class": "mb-4",
                    "variant": "tonal",
                },
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {
                            "class": "d-flex align-center",
                        },
                        "content": [
                            {
                                "component": "VIcon",
                                "props": {
                                    "icon": "mdi-email-outline",
                                    "class": "mr-2",
                                },
                            },
                            "插件介绍",
                        ],
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": "邮箱消息通知插件通过 SMTP 服务器发送邮件通知。收件人根据通知发送范围设置（all/user/admin）从用户管理邮箱中获取，邮箱为空时跳过。配置 SMTP 服务器、发件人邮箱与授权码后即可启用。",
                                },
                            },
                        ],
                    },
                ],
            },
        ]

    def send_custom_notification(self, payload: Optional[dict] = Body(default=None)) -> schemas.Response:
        """手动发送自定义通知。

        :param payload: 请求体，包含 title 与 text
        :return: 发送结果
        """
        if not self.get_state():
            return schemas.Response(success=False, message="插件未启用或 SMTP 配置不完整")

        title = str((payload or {}).get("title") or "")
        text = str((payload or {}).get("text") or "")
        if not title and not text:
            return schemas.Response(success=False, message="标题和内容不能同时为空")

        # 手动发送默认发送给所有用户
        recipients = self._get_recipients(NotificationType.Other, None, force_all=True)
        if not recipients:
            return schemas.Response(success=False, message="未获取到收件人邮箱")

        if self._send_mail(recipients, title, text):
            return schemas.Response(success=True, message=f"通知发送成功，收件人：{', '.join(recipients)}")
        return schemas.Response(success=False, message="通知发送失败")

    def _get_recipients(self, msg_type: NotificationType, username: Optional[str], force_all: bool = False) -> List[str]:
        """根据通知发送范围设置获取收件人邮箱列表。

        :param msg_type: 消息类型
        :param username: 消息关联的用户名
        :param force_all: 是否强制发送给所有用户（手动发送时使用）
        :return: 收件人邮箱列表
        """
        from app.db.oper.user import UserOper

        # 获取通知发送范围
        if force_all:
            notify_action = "all"
        else:
            notify_action = ServiceConfigHelper.get_notification_switch(msg_type)
            if not notify_action:
                # 未设置范围时默认发送给管理员
                notify_action = "admin"

        actions = notify_action.split(",")
        recipients = []
        useroper = UserOper()
        superuser = settings.SUPERUSER or "admin"

        for action in actions:
            if action == "admin":
                user = useroper.get_by_name(superuser)
                if user and user.email:
                    recipients.append(user.email)
            elif action == "user" and username:
                user = useroper.get_by_name(str(username))
                if user and user.email:
                    recipients.append(user.email)
            elif action == "all":
                for user in useroper.list():
                    if user.email:
                        recipients.append(user.email)

        # 去重
        return list(dict.fromkeys(recipients))

    def _send_mail(self, recipients: List[str], title: str, text: str) -> bool:
        """通过 SMTP 发送邮件。

        :param recipients: 收件人邮箱列表
        :param title: 邮件标题
        :param text: 邮件正文
        :return: 发送是否成功
        """
        if not recipients:
            logger.warn("邮箱消息通知：没有有效的收件人邮箱，跳过发送")
            return False

        server = None
        try:
            port = int(self._smtp_port or 465)
            msg = MIMEText(text or "", "plain", "utf-8")
            msg["Subject"] = Header(title or "MoviePilot 通知", "utf-8")
            msg["From"] = formataddr((str(Header("MoviePilot", "utf-8")), self._sender))
            # To 使用发件人自身地址，收件人地址放入 Bcc（密送），避免收件人之间互相看到邮箱地址
            msg["To"] = formataddr((str(Header("MoviePilot", "utf-8")), self._sender))
            msg["Bcc"] = ",".join(recipients)

            if self._ssl:
                server = smtplib.SMTP_SSL(self._smtp_server, port, timeout=15)
            else:
                # 未启用 SSL 时使用普通 SMTP 连接，不强制 STARTTLS，
                # 避免不支持 STARTTLS 的服务器或 465 端口握手失败
                server = smtplib.SMTP(self._smtp_server, port, timeout=15)

            server.login(self._sender, self._password)
            # 序列化邮件内容前移除 Bcc 头，避免 Bcc 头进入邮件正文导致收件人地址泄露；
            # 收件人列表仍通过 SMTP envelope（sendmail 第二参数）投递。
            del msg["Bcc"]
            rejected = server.sendmail(self._sender, recipients, msg.as_string())
            if rejected:
                logger.warn(f"邮箱消息发送部分失败，拒收地址：{list(rejected.keys())}")
                return False
            logger.info(f"邮箱消息发送成功，收件人：{recipients}")
            return True
        except Exception as err:
            logger.error(f"邮箱消息发送异常，{str(err)}")
            return False
        finally:
            # 无论连接创建、握手、登录还是发送环节出错，都关闭 SMTP 连接，避免连接泄漏
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event) -> None:
        """消息发送事件。"""
        if not self.get_state():
            return

        if not event.event_data:
            return

        msg_body = event.event_data
        # 渠道
        channel = msg_body.get("channel")
        if channel:
            return
        # 类型
        msg_type: NotificationType = msg_body.get("type")
        # 标题
        title = msg_body.get("title")
        # 文本
        text = msg_body.get("text")
        # 用户名
        username = msg_body.get("username")

        if not title and not text:
            logger.warn("标题和内容不能同时为空")
            return

        if (msg_type and self._msgtypes
                and msg_type.name not in self._msgtypes):
            logger.info(f"消息类型 {msg_type.value} 未开启消息发送")
            return

        # 获取收件人
        recipients = self._get_recipients(msg_type, username)
        if not recipients:
            logger.warn("邮箱消息通知：未获取到收件人邮箱，跳过发送")
            return

        # 发送邮件
        self._send_mail(recipients, title, text)

    def stop_service(self) -> None:
        """退出插件。"""
        return None
