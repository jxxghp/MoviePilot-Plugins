import ipaddress
import json
import random
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from requests import RequestException, Response as RequestsResponse

from app.schemas.notification import ChannelCapability, ChannelCapabilityManager
from app.schemas.types import EventType, ModuleType, NotificationChannel
from app.sdk.config import settings
from app.sdk.network import RequestUtils
from app.sdk.events import eventmanager, Event
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase


class UpdateWeChatIp(_PluginBase):
    """
    动态维护企业微信应用可信IP，并在需要时扫码刷新登录 Cookie。
    """

    # 插件在界面中的展示名称
    plugin_name = "动态企微可信IP"
    # 插件描述
    plugin_desc = "修改企微应用可信IP，可本地扫码刷新Cookie"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本，必须和 package.v3.json 中保持一致
    plugin_version = "2.0.3"
    # 作者信息
    plugin_author = "书小白,iamchq"
    author_url = "https://github.com/thshu/MoviePilot-Plugins"
    # 配置项前缀，建议保持唯一，避免与其他插件冲突
    plugin_config_prefix = "UpdateWeChatIp_"
    # 插件加载顺序，数值越小越早
    plugin_order = 50
    # 插件可见权限级别
    auth_level = 1

    # 运行时状态字段
    _enabled = False
    _se = None
    _qrcode_key = None
    _tl_key = None
    _captcha = {}
    # 短信验证码长度
    _captcha_length = 6
    # 在 MoviePilot 页面内渲染的渠道，图片使用同源相对地址
    _same_origin_channels = (NotificationChannel.Web, NotificationChannel.WebAgent)
    # 二维码图片令牌有效期（秒）
    _img_token_ttl = 180
    # 当前有效的二维码图片访问令牌，{令牌: 过期时间戳}
    _img_tokens: Dict[str, float] = {}
    _img_token_lock = threading.Lock()
    # 最近一次登录二维码 (图片内容, Content-Type)；只留内存，不落盘
    _qr_image: Optional[Tuple[bytes, str]] = None
    _qr_image_lock = threading.Lock()
    # 聊天框文本输入会话超时时间（秒）
    _text_input_timeout = 120
    _wwrtx_sid = None
    _party_cache_data = None
    _app_id = ""
    _ip = None
    _is_login = False
    onlyonce = False
    _cron = ""
    _timer: threading.Timer = None

    _UpdateLogKey = 'UpdateLog'
    # IP 更新记录保留条数
    _update_log_limit = 5

    # 登录失效后连续失败多少次开始降频
    _fail_backoff_after = 3
    # 降频后的重试与提醒间隔（分钟）
    _fail_backoff_minutes = 30
    _fail_state_key = 'FailState'
    # 不维护渠道名单，只排除站内：站内仅在首次提醒，其余渠道按间隔重复
    _notify_silent_channels = ('Web', 'WebAgent')

    # 内置 IPv4 查询地址（均为实测可用接口，已移除失效域名）
    _default_ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip",
                        "https://ip.3322.net", "https://ipv4.ddnspod.com",
                        "https://ipv4.ip.mir6.com"]
    # init_plugin 之前直接调用查询时也有内置列表可用
    _ip_urls = list(_default_ip_urls)
    _ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'

    _headers = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        'Accept-Encoding': "gzip, deflate, br, zstd",
        'pragma': "no-cache",
        'cache-control': "no-cache",
        'sec-ch-ua-platform': "\"Windows\"",
        'x-requested-with': "XMLHttpRequest",
        'sec-ch-ua': "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
        'sec-ch-ua-mobile': "?0",
        'sec-fetch-site': "same-origin",
        'sec-fetch-mode': "cors",
        'sec-fetch-dest': "empty",
        'referer': "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/login_qrcode",
        'accept-language': "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
        'priority': "u=1, i",
    }

    def init_plugin(self, config: dict = None):
        """根据当前配置初始化插件。"""
        # init_plugin 可能被重复调用，先清理上一轮资源
        self.stop_service()
        
        config = config or {}
        self._enabled = bool(config.get("_enabled"))
        self._wwrtx_sid = config.get("_wwrtx_sid")
        self._app_id = config.get("_app_id")
        self._cron = config.get("_cron")
        self._party_cache_data = config.get("_party_cache_data")
        configured_ip_urls = config.get("_ip_urls")
        parsed_ip_urls = self._parse_ip_urls(configured_ip_urls)
        if str(configured_ip_urls or "").strip() and not parsed_ip_urls:
            logger.warning("IPv4 查询接口配置均无效，已使用内置列表")
        self._ip_urls = parsed_ip_urls or list(self._default_ip_urls)

        # 宿主同步 HTTP 工具自带持久会话，Cookie 由会话跨请求维护
        self._se = RequestUtils(headers=self._headers, verify=True, use_session=True)
        self._se.update_cookies({'wwrtx.sid': self._wwrtx_sid})

        if config.get("onlyonce"):
            # 立即检测一次：延迟 3 秒后单次执行，不影响 cron 周期服务
            self._timer = threading.Timer(3, self._run_check_safe)
            self._timer.daemon = True
            self._timer.start()
            config["onlyonce"] = False
            self.update_config(config)

    def stop_service(self):
        """停用插件时清理后台任务、调度器、网络会话等资源。"""
        timer = getattr(self, "_timer", None)
        if timer:
            try:
                timer.cancel()
            except Exception as e:
                logger.error(f"取消定时器失败: {e}")
            finally:
                self._timer = None
        
        session = getattr(self, "_se", None)
        if session:
            try:
                session.close()
            except Exception as e:
                logger.error(f"关闭网络会话失败: {e}")
            finally:
                self._se = None

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        """返回按 cron 执行登录检查的周期服务。"""
        if self._enabled and self._cron:
            return [
                {
                    "id": self.__class__.__name__,
                    "name": f"{self.__class__.__name__}_{self.plugin_name}服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.check,
                    "kwargs": {}
                },
            ]
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册插件远程命令
        """
        return [{
            "cmd": "/update_wechat_ip",
            "event": EventType.PluginAction,
            "desc": "获取企业微信二维码",
            "category": "获取企业微信二维码",
            "data": {
                "action": "update_wechat_ip"
            }
        }
        ]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """
        远程命令响应
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") not in [i['data']['action'] for i in self.get_command()]:
            return

        # 获取用户信息
        channel = event_data.get("channel")
        arg_str = event_data.get("arg_str")
        source = event_data.get("source")
        user = event_data.get("user")

        def remind_missing_qrcode() -> None:
            """提示先获取登录二维码。"""
            self.post_message(
                channel=channel,
                title="未获取二维码",
                userid=user,
                text="请先执行 /update_wechat_ip 获取登录二维码。",
            )

        if arg_str is not None and str(arg_str).strip():
            arg_text = str(arg_str).strip()
            if arg_text == '扫码完成':
                if not self._qrcode_key:
                    remind_missing_qrcode()
                    return
                self._login(channel, user, source=source)
            elif len(self._digits_of(arg_text)) == self._captcha_length:
                if not self._qrcode_key:
                    remind_missing_qrcode()
                    return
                # 命令一次性提交完整验证码：先归一化再校验长度
                self._captcha[self._qrcode_key] = self._digits_of(arg_text)
                self._submit_captcha(channel, user, self._qrcode_key, source=source)
            else:
                self.post_message(
                    channel=channel,
                    title="无效的输入",
                    userid=user,
                    text=f"未识别到 {self._captcha_length} 位数字验证码，可回复：\n```\n/update_wechat_ip 验证码内容\n```",
                )
        else:
            # 只保留一个待扫码的二维码，新的会覆盖上一次
            replaced = bool(self._qrcode_key)
            # 初始化变量
            self._qrcode_key = None
            self._tl_key = None
            self._captcha = {}

            self._qrcode_key = self._get_key()
            if not self._qrcode_key:
                self.post_message(
                    channel=channel,
                    title="获取二维码失败",
                    userid=user,
                    text="企业微信登录二维码获取失败，请稍后重试。",
                )
                return
            image_url = self._qrcode(self._qrcode_key, channel=channel)
            if not image_url:
                self.post_message(
                    channel=channel,
                    title="获取二维码失败",
                    userid=user,
                    text="企业微信登录二维码图片获取失败，请稍后重试。",
                )
                return
            self.post_message(**self._qrcode_message(channel, user, image_url, replaced=replaced))

    def _qrcode_message(self, channel, user, image_url: str,
                        replaced: bool = False) -> Dict[str, Any]:
        """
        投递二维码：原图上传与降级由宿主统一处理，插件只补地址兜底与可达性判断。
        """
        lines = ["请选择要执行的操作：", "请识别或扫描二维码完成登录。",
                 "如果按钮不可用，可回复：\n```\n/update_wechat_ip 扫码完成\n```"]
        if replaced:
            lines.insert(0, "上一次待扫码的二维码已失效，请以本次为准。")
        message: Dict[str, Any] = {
            "channel": channel,
            "title": "登录二维码",
            "userid": user,
            "buttons": [[{
                "text": "扫码完成",
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|扫码完成|{self._qrcode_key}",
            }]],
        }
        if self._is_same_origin_channel(channel):
            message.update({"text": "\n".join(lines), "image": image_url})
            return message
        shareable = self._shareable_image_url(image_url)
        if not shareable:
            # 宿主不会校验地址可达性，回环地址发出去就是一张抓不到的图
            message.update({"text": "\n".join(lines + [
                "当前渠道不能上传原图，也没有配置可对外访问的地址，"
                "请在 MoviePilot 页面打开本插件获取二维码。",
            ])})
            return message
        if (self._channel_supports(channel, ChannelCapability.IMAGES)
                and not self._channel_supports(channel, ChannelCapability.NATIVE_IMAGES)):
            # 这类渠道由客户端抓图，抓不到时正文里的地址还能救场
            lines.append(f"二维码地址（图片未显示时可打开）：{shareable}")
        message.update({"text": "\n".join(lines), "image": image_url, "native_image": True})
        return message

    @staticmethod
    def _shareable_image_url(image_url: str) -> Optional[str]:
        """返回可交给外部客户端打开的图片地址；相对地址与本地保留地址不可用。"""
        candidate = str(image_url or "").strip()
        if not candidate.startswith(("http://", "https://")):
            return None
        host = (urlparse(candidate).hostname or "").lower()
        if not host:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # RFC 6761 规定 localhost 及其子域都解析到回环
            if host == "localhost" or host.endswith(".localhost"):
                return None
            return candidate
        if address.is_loopback or address.is_unspecified or address.is_link_local:
            return None
        return candidate

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """
        处理消息按钮回调
        """
        event_data = event.event_data
        if not event_data:
            return

        # 检查是否为本插件的回调
        plugin_id = event_data.get("plugin_id")
        if plugin_id != self.__class__.__name__:
            return

        # 获取回调数据
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        # 获取原始消息ID和聊天ID（用于直接更新原消息）
        original_message_id = event_data.get("original_message_id")
        original_chat_id = event_data.get("original_chat_id")

        callback_text = event_data.get("text", "")
        if not isinstance(callback_text, str):
            callback_text = str(callback_text or "")

        # 宿主文本输入会话回调（plugin_input / _cancel / _expired），需先于按钮解析处理
        if callback_text.startswith("plugin_input"):
            self._handle_text_input_event(event_data, callback_text)
            return

        if "|" not in callback_text:
            self.post_message(
                channel=channel,
                title="登录失败",
                userid=userid,
                text="未获取到本次登录对应的qrcode_key",
            )
            return
        text, qrcode_key = callback_text.split("|", 1)
        qrcode_key = self._resolve_captcha_key(qrcode_key)

        def resend_prompt(note: Optional[str] = None) -> None:
            """按当前会话重发验证码输入提示。"""
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
                note=note,
            )

        if text == "扫码完成":
            self._qrcode_key = qrcode_key
            self._login(
                channel,
                userid,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
            )
        elif text == "输入完毕":
            # 使用回调携带的 qrcode_key，避免多轮登录后读到已重置的实例值
            self._submit_captcha(channel, userid, qrcode_key, source=source)
        elif text == "退格":
            self._captcha[qrcode_key] = self._captcha.get(qrcode_key, "")[:-1]
            resend_prompt()
        elif text == "清空":
            self._captcha[qrcode_key] = ""
            resend_prompt(note="已清空输入，可重新输入验证码。")
        elif text == "文本输入":
            if self._request_text_input(channel, userid, source, qrcode_key):
                resend_prompt(note=self._text_input_note(channel))
            else:
                resend_prompt(note="当前宿主未提供文本输入会话接口，请使用数字按钮或 /update_wechat_ip 命令输入。")
        elif len(re.findall('[0-9]', text)) != 0:
            if qrcode_key not in self._captcha.keys():
                self._captcha[qrcode_key] = ""
            self._captcha[qrcode_key] += text
            resend_prompt()
        else:
            self.post_message(
                channel=channel,
                title="无效的输入",
                userid=userid,
                text="无效的输入",
            )

    def get_api(self) -> List[Dict[str, Any]]:
        """返回二维码图片与 IP 更新接口。"""
        return [
            {
                "path": "/img/{uuid}",
                "endpoint": self.get_img,
                "methods": ["GET"],
                # 图片在通知里直接展示，浏览器带不了鉴权头：匿名路由 + 端点内校验令牌 t
                "allow_anonymous": True,
                "summary": "获取图片",
                "description": "获取登录二维码图片,需要传递查询参数,参数名为:t(本次登录签发的二维码访问令牌)",
                # 原生图片响应，显式声明类型，避免 OpenAPI 按 JSON 描述
                "response_class": Response,
                "response_model": None,
                "responses": {
                    200: {
                        "content": {
                            "image/png": {"schema": {"type": "string", "format": "binary"}},
                            "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                        }
                    },
                    403: {"description": "二维码访问令牌无效或已过期"},
                    404: {"description": "二维码已失效"},
                },
            },
            {
                "path": "/UpdateIP",
                "endpoint": self.UpdateIp,
                # 会改写企微可信IP，必须用 POST，避免预取或爬虫触发状态变更
                "methods": ["POST"],
                # 前端插件页面通过 api 模块调用时，通常使用 bear
                "auth": "apikey",
                "summary": "更新企业微信IP白名单",
                "description": "更新企业微信IP白名单,需要传递查询参数,参数名为:ip；返回各应用的写入结果",
                "response_model": UpdateIpResult,
                "responses": {400: {"description": "非法 IPv4 地址"}},
            },
        ]

    def UpdateIp(self, ip: str) -> UpdateIpResult:
        """更新指定 IP 的企业微信可信IP配置。"""
        candidate = str(ip or "").strip()
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法 IPv4 地址")
        self._ip = candidate
        results = self._save_ip_config()
        return UpdateIpResult(
            success=bool(results) and all(item.status for item in results),
            ip=candidate,
            updated=len(results),
            failed_app_ids=[item.app_id for item in results if not item.status],
        )

    def get_img(self, uuid: str, t: Optional[str] = None):
        """输出最近一次登录二维码图片，凭据为本次登录签发的令牌 t。"""
        if not self._check_img_token(t):
            raise HTTPException(
                status_code=403,
                detail="二维码访问令牌无效或已过期，请重新执行 /update_wechat_ip"
            )
        with self._qr_image_lock:
            image = self._qr_image
        if not image:
            raise HTTPException(
                status_code=404,
                detail="二维码已失效，请重新执行 /update_wechat_ip"
            )
        content, media_type = image
        # 二维码里带登录凭据，禁止任何中间层缓存
        return Response(content=content, media_type=media_type,
                        headers={"Cache-Control": "no-store"})

    @staticmethod
    def _image_media_type(content: bytes) -> str:
        """按文件头判断图片类型，企业微信返回的二维码实际是 PNG。"""
        return "image/png" if content[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"

    @classmethod
    def _new_img_token(cls) -> str:
        """签发本次登录的二维码图片访问令牌，之前签发的令牌立即失效。"""
        token = secrets.token_urlsafe(16)
        with cls._img_token_lock:
            cls._img_tokens = {token: time.time() + cls._img_token_ttl}
        return token

    @classmethod
    def _check_img_token(cls, token: Optional[str]) -> bool:
        """
        校验二维码图片访问令牌，未登记或已过期时返回 False。

        令牌不在首次访问时消费：浏览器懒加载、页面刷新后重放消息历史都会重复
        请求同一张图片。令牌本身已绑定本次登录，下次生成二维码时会被替换。
        """
        if not token:
            return False
        now = time.time()
        with cls._img_token_lock:
            for registered, expires_at in list(cls._img_tokens.items()):
                if expires_at < now:
                    cls._img_tokens.pop(registered, None)
            return cls._img_tokens.get(str(token), 0) >= now

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回配置页 JSON 和默认配置模型。"""
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
                                            'model': '_enabled',
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
                                            'model': 'onlyonce',
                                            'label': '立即检测一次',
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
                                            'model': '_cron',
                                            'label': '[必填]检测周期',
                                            'placeholder': '*/10 * * * *',
                                            'hint': '5位 cron 表达式，按此周期检测登录状态并更新可信 IP',
                                            'persistent-hint': True
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
                                            'model': '_app_id',
                                            'label': '[必填]应用ID',
                                            'placeholder': '多个应用ID用英文逗号(,)隔开',
                                            'hint': '在企业微信应用页面 URL 末尾获取',
                                            'persistent-hint': True
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': '_ip_urls',
                                            'label': 'IPv4 查询接口（选填）',
                                            'placeholder': 'https://myip.ipip.net,https://ddns.oray.com/checkip',
                                            'hint': '多个地址用英文逗号(,)隔开，按顺序尝试；留空使用内置列表。',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "_enabled": False,
            "_wwrtx_sid": "",
            "_app_id": "",
            "_party_cache_data": {},
            "_cron": '*/10 * * * *',
            "_ip_urls": "",
            "onlyonce": False
        }

    @staticmethod
    def _result_brief(value: str, limit: int = 120) -> str:
        """把接口返回压成单行摘要：JSON 截断，HTML 页面只给长度。"""
        text = str(value or "")
        if text.lstrip().startswith("<"):
            return f"HTML页面({len(text)} 字符)"
        text = " ".join(text.split())
        return text if len(text) <= limit else text[:limit] + "…"

    @staticmethod
    def _wecom_error_reason(result: str) -> str:
        """优先按企业微信 errcode 映射官方错误原因，未知码再回退到接口文本。"""
        text = str(result or "")
        payload = None
        try:
            payload = json.loads(text)
        except Exception:
            payload = None

        candidates = []
        if isinstance(payload, dict):
            candidates.append(payload)
            nested = payload.get("result")
            if isinstance(nested, dict):
                candidates.append(nested)

        code = None
        raw_reason = ""
        for item in candidates:
            if code is None:
                for key in ("errCode", "errcode", "code"):
                    if key in item:
                        try:
                            code = int(item[key])
                        except (TypeError, ValueError):
                            code = None
                        break
            if not raw_reason:
                for key in ("humanMessage", "message", "errmsg", "errMsg"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        raw_reason = value
                        break

        if code is None:
            matched_code = re.search(r'"(?:errCode|errcode|code)"\s*:\s*(-?\d+)', text, re.I)
            if matched_code:
                code = int(matched_code.group(1))
        if not raw_reason:
            matched_reason = re.search(
                r'"(?:humanMessage|message|errmsg|errMsg)"\s*:\s*"([^"]*)"', text, re.I
            )
            raw_reason = matched_reason.group(1).strip() if matched_reason else ""

        known_reasons = {
            -1: "系统繁忙，请稍后重试",
            -3: "登录已失效，请重新登录",
            -30001: "参数错误",
            -80013: "服务器异常，请稍候再试",
            -80037: "应用不存在",
            60020: "不安全的访问IP",
        }
        token_reasons = {
            "outsession": "登录已失效，请重新登录",
            "invalid ip": "不安全的访问IP",
        }
        code_fallbacks = {
            -4: "登录已失效，请重新登录",
        }

        reason = (
            token_reasons.get(raw_reason.lower())
            or known_reasons.get(code)
            or code_fallbacks.get(code)
        )
        return reason or raw_reason

    @staticmethod
    def _log_result_text(status: bool, result: str) -> str:
        """记录表的结果列：成功显示动作结果，失败优先显示接口错误信息。"""
        if status:
            return "已更新"
        reason = UpdateWeChatIp._wecom_error_reason(result)
        return UpdateWeChatIp._result_brief(reason, 80) or "无返回内容"

    def get_page(self) -> List[dict]:
        """返回详情页 JSON。"""
        # ---------- 获取并排序更新日志 ----------
        raw_data = self.get_data(self._UpdateLogKey) or []
        update_log: List[UpdateLogDto] = [UpdateLogDto.from_dict(i) for i in raw_data]
        data_list = sorted(update_log, key=lambda x: x.UpdateTime, reverse=True)[:self._update_log_limit]
        groups: List[Tuple[Tuple[str, str], List[UpdateLogDto]]] = []
        for row in data_list:
            group_key = (row.ip, row.UpdateTime.strftime('%Y-%m-%d %H:%M:%S'))
            if groups and groups[-1][0] == group_key:
                groups[-1][1].append(row)
            else:
                groups.append((group_key, [row]))

        update_log_trs = [
            {
                "component": "div",
                "props": {"class": "d-none d-sm-flex flex-wrap align-baseline px-4 py-2",
                          "style": {"gap": "12px", "rowGap": "4px", "lineHeight": "1.4",
                                    "borderTop": "1px solid rgba(0, 0, 0, 0.08)"}},
                "content": [
                    {"component": "div", "props": {"class": "flex-shrink-0",
                                                   "style": {"width": "64px"}}, "content": [{
                        "component": "VChip",
                        "props": {
                            "size": "x-small",
                            "variant": "flat",
                            "rounded": "pill",
                            "color": "success" if all_ok else ("warning" if any_ok else "error"),
                        },
                        "text": "成功" if all_ok else ("部分失败" if any_ok else "失败")}]},
                    {"component": "div", "props": {"class": "flex-shrink-0",
                                                   "style": {"width": "176px"}}, "content": [{
                        "component": "div",
                        "props": {"class": "d-flex flex-column font-monospace",
                                  "style": {"fontSize": "16px", "lineHeight": "1.4"}},
                        "content": [
                            {"component": "span",
                             "props": {"class": "text-no-wrap" if index == len(group) - 1 else "text-no-wrap mb-1"},
                             "text": row.app_id + ("," if index < len(group) - 1 else "")}
                            for index, row in enumerate(group)
                        ],
                    }]},
                    {"component": "div", "props": {"class": "flex-shrink-0 text-no-wrap font-monospace",
                                                   "style": {"width": "148px", "fontSize": "16px",
                                                             "lineHeight": "1.4"}},
                     "text": group[-1].ip},
                    {"component": "div", "props": {"style": {"width": "320px", "minWidth": "160px"}}, "content": [{
                        "component": "div",
                        "props": {"class": "d-flex flex-column"},
                        "content": [{
                            "component": "span",
                            "props": {
                                "class": f"{'text-success' if row.status else 'text-error'} "
                                         f"{'text-no-wrap' if index == len(group) - 1 else 'text-no-wrap mb-1'}",
                                "style": {"fontSize": "14px", "lineHeight": "1.4",
                                          "whiteSpace": "normal", "overflowWrap": "anywhere"},
                                "title": self._result_brief(row.result, 500),
                            },
                            "text": self._log_result_text(row.status, row.result),
                        } for index, row in enumerate(group)],
                    }]},
                    {"component": "div", "props": {"class": "flex-shrink-0 text-no-wrap "
                                                            "text-medium-emphasis",
                                                   "style": {"width": "158px", "fontSize": "14px",
                                                             "lineHeight": "1.4"}},
                     "text": group[-1].UpdateTime.strftime('%Y-%m-%d %H:%M:%S')},
                ],
            }
            for _, group in groups
            for all_ok, any_ok in [(
                all(row.status for row in group),
                any(row.status for row in group),
            )]
        ]

        update_log_mobile = [
            {
                "component": "div",
                "props": {"class": "d-flex d-sm-none flex-column px-4 py-2",
                          "style": {"gap": "2px", "borderTop": "1px solid rgba(0, 0, 0, 0.08)"}},
                "content": [
                    {"component": "div",
                     "props": {"class": "d-flex flex-wrap align-center", "style": {"gap": "8px"}},
                     "content": [
                         {"component": "VChip",
                          "props": {"size": "x-small", "variant": "flat", "rounded": "pill",
                                    "color": "success" if all_ok else ("warning" if any_ok else "error")},
                          "text": "成功" if all_ok else ("部分失败" if any_ok else "失败")},
                         {"component": "span",
                          "props": {"class": "text-medium-emphasis",
                                    "style": {"marginLeft": "auto", "fontSize": "12px"}},
                          "text": group[-1].UpdateTime.strftime('%Y-%m-%d %H:%M:%S')},
                     ]},
                    {"component": "div",
                     "props": {"class": "d-flex flex-wrap align-center", "style": {"gap": "8px"}},
                     "content": [
                         {"component": "span",
                          "props": {"class": "text-no-wrap font-monospace",
                                    "style": {"fontSize": "13px"}},
                          "text": group[-1].ip},
                         {"component": "span",
                          "props": {"class": "font-monospace",
                                    "style": {"fontSize": "13px"}},
                          "text": "、".join(row.app_id for row in group)},
                     ]},
                    {"component": "div",
                     "props": {"class": "d-flex flex-column"},
                     "content": [{
                         "component": "span",
                         "props": {
                             "class": 'text-success' if row.status else 'text-error',
                             "style": {"fontSize": "13px", "whiteSpace": "normal",
                                       "overflowWrap": "anywhere"},
                             "title": self._result_brief(row.result, 500),
                         },
                         "text": self._log_result_text(row.status, row.result),
                     } for row in group]},
                ],
            }
            for _, group in groups
            for all_ok, any_ok in [(
                all(row.status for row in group),
                any(row.status for row in group),
            )]
        ]

        def _empty_row(display_class: str) -> dict:
            return {"component": "div",
                    "props": {"class": f"{display_class} text-center text-medium-emphasis py-8"},
                    "text": "暂无 IP 更新记录"}

        update_log_trs = update_log_trs or [_empty_row("d-none d-sm-block")]
        update_log_mobile = update_log_mobile or [_empty_row("d-block d-sm-none")]

        log_header = {
            "component": "div",
            "props": {"class": "d-none d-sm-flex flex-wrap px-4 py-2 bg-grey-lighten-5 "
                               "text-medium-emphasis",
                      "style": {"gap": "12px", "rowGap": "4px", "fontSize": "13px"}},
            "content": [
                {"component": "div", "props": {"class": "flex-shrink-0", "style": {"width": "64px"}},
                 "text": "状态"},
                {"component": "div", "props": {"class": "flex-shrink-0", "style": {"width": "176px"}},
                 "text": "应用ID"},
                {"component": "div", "props": {"class": "flex-shrink-0", "style": {"width": "148px"}},
                 "text": "更新IP"},
                {"component": "div", "props": {"style": {"width": "320px", "minWidth": "160px"}},
                 "text": "结果"},
                {"component": "div", "props": {"class": "flex-shrink-0", "style": {"width": "158px"}},
                 "text": "更新时间"},
            ],
        }

        party_name = self._party_name("未知")
        last_update = (
            data_list[0].UpdateTime.strftime('%Y-%m-%d %H:%M') if data_list else "暂无记录"
        )

        # ---------- 构建页面结构 ----------
        return [
            {
                "component": "VRow",
                "props": {"class": "ma-0"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "class": "pa-0"},
                        "content": [
                            {"component": "VCard",
                             "props": {"variant": "tonal", "rounded": "lg", "class": "mb-4"}, "content": [
                                {"component": "VCardText",
                                 "props": {"class": "d-flex flex-wrap align-center justify-space-between ga-4 px-4 py-3"},
                                 "content": [
                                     {"component": "div",
                                      "props": {"class": "d-flex flex-wrap align-center ga-3"},
                                      "content": [
                                          {"component": "VChip",
                                           "props": {"size": "small", "variant": "flat", "rounded": "pill",
                                                     "color": "success" if self._is_login else "error"},
                                           "text": "已登录" if self._is_login else "登录失效"},
                                          {"component": "span", "props": {"class": "text-body-2"},
                                           "text": f"应用：{party_name}"},
                                          {"component": "span", "props": {"class": "text-caption text-medium-emphasis"},
                                           "text": f"当前 IP：{self._ip or '未获取'}"},
                                      ]},
                                     {"component": "span", "props": {"class": "text-caption text-medium-emphasis"},
                                      "text": f"最近更新：{last_update}"},
                                 ]}]},
                            {"component": "VCard", "props": {"variant": "outlined", "rounded": "lg"}, "content": [
                                {"component": "VCardTitle",
                                 "props": {"class": "d-flex align-center justify-space-between flex-wrap ga-3 px-4 py-3"},
                                 "content": [
                                     {"component": "div",
                                      "props": {"class": "d-flex align-center flex-wrap ga-3"},
                                      "content": [
                                          {"component": "span", "props": {"class": "text-subtitle-2"},
                                           "text": "IP 更新记录"},
                                          {"component": "VChip",
                                           "props": {"size": "x-small", "variant": "tonal", "color": "grey"},
                                           "text": f"最近 {len(data_list)} 条"},
                                      ]},
                                     {"component": "span", "props": {"class": "text-caption text-medium-emphasis"},
                                      "text": "同次检测已合并"}]},
                                {"component": "VCardText",
                                 "props": {"class": "px-0 py-0",
                                           "style": {"maxHeight": "420px", "overflow": "auto"}},
                                 "content": [log_header] + update_log_trs + update_log_mobile},
                            ]},
                        ],
                    }
                ],
            }
        ]

    def _get_key(self):
        """获取本次扫码登录的 qrcode_key。"""
        logger.info("开始获取登录二维码key")
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/get_key"
        current_ts = int(time.time() * 1000)
        params = {
            'r': str(random.random()),
            'login_type': "login_admin",
            'callback': f"wwqrloginCallback_{current_ts}",
            'redirect_uri': "https://work.weixin.qq.com/wework_admin/loginpage_wx?_r=234&redirect_uri=https%3A%2F%2Fwork.weixin.qq.com%2Fwework_admin%2Fframe&url_hash=%23%2Fapps#/apps",
            'crossorigin': "1"
        }
        try:
            response = self._se.get_res(url, params=params, timeout=15, raise_exception=True)
            data = response.json()
        except Exception as e:
            logger.error(f"获取登录二维码key失败: {e}")
            return None
        key = (data.get('data') or {}).get('qrcode_key')
        if not key:
            logger.error(f"获取登录二维码key失败，返回值:{self._result_brief(response.text, 120)}")
        return key

    def _qrcode(self, key, channel=None) -> Optional[str]:
        """拉取登录二维码并按渠道返回可访问的图片地址。"""
        if not key:
            return None
        logger.info("开始获取登录二维码图片")
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/qrcode"
        params = {
            'qrcode_key': key,
            'login_type': "login_admin"
        }
        try:
            response = self._se.get_res(url, params=params, timeout=15, raise_exception=True)
        except Exception as e:
            logger.error(f"获取登录二维码图片失败: {e}")
            return None
        content = response.content
        if response.status_code != 200 or not content:
            logger.error(f"获取登录二维码图片失败，HTTP状态码：{response.status_code}")
            return None
        if not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")):
            logger.error(f"登录二维码返回内容不是 PNG/JPEG：{self._result_brief(response.text, 80)}")
            return None
        logger.info("登录二维码图片获取成功")
        with self._qr_image_lock:
            self._qr_image = (content, self._image_media_type(content))
        # 图片地址会进通知，只放本次登录的短期令牌
        uri = (f"/api/v1/plugin/{self.__class__.__name__}/img/"
               f"{uuid.uuid4().hex}?t={self._new_img_token()}")
        if self._is_same_origin_channel(channel):
            # 页面内渲染的渠道用相对地址，跟随用户实际访问入口
            img_url = uri
            source = "站内相对地址"
        else:
            img_url = settings.MP_DOMAIN(uri) or f"http://127.0.0.1:{settings.PORT}{uri}"
            source = "外部域名地址"
        # 地址里的 t 是本次登录的访问令牌，只记录来源形式不落盘
        logger.info(f"登录二维码图片地址已生成（{source}）")
        return img_url

    def _check(self, key, timeout: int = 30) -> Dict:
        """等待手机确认扫码，超时或二维码失效时返回 None。"""
        logger.info("开始获取扫码结果")
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/check"
        params = {
            'qrcode_key': key,
            'status': "QRCODE_SCAN_ING"
        }
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = self._se.get_res(url, params=params, timeout=10, raise_exception=True)
                data = response.json().get('data', {})
            except Exception as e:
                logger.error(f"获取扫码结果异常: {e}")
                return None
            if data.get("status") == "QRCODE_SCAN_SUCC":
                logger.info("扫码已确认")
                return data
            if not data:
                logger.info(f"二维码无效或已过期:{self._result_brief(response.text, 80)}")
                return None
            time.sleep(2)
        logger.info(f"获取扫码结果超时，{timeout} 秒内未确认")
        return None

    def _loginpage_wx(self, key, code) -> RequestsResponse:
        """用扫码返回的 code 完成登录页请求。"""
        logger.info("开始登录")
        url = "https://work.weixin.qq.com/wework_admin/loginpage_wx"
        # 动态生成当前毫秒级时间戳
        now_ms = str(int(time.time() * 1000))
        params = {
            '_r': "234",
            'redirect_uri': "https://work.weixin.qq.com/wework_admin/frame",
            'url_hash': "#/apps",
            'code': code,
            'auth_redirect_time': now_ms,
            'getauth_time': now_ms,
            'wwqrlogin': "1",
            'qrcode_key': key,
            'auth_source': "SOURCE_FROM_WEWORK",
            'confirm_type': "0"
        }
        response = self._se.get_res(url, params=params, timeout=15, raise_exception=True)
        logger.info(f"登录完成，状态码:{response.status_code}，响应长度:{len(response.text)}，"
                    f"需短信验证:{'tl_key' in response.url}")
        return response

    def _confirm_captcha(self, tl_key, captcha):
        """提交短信验证码并完成企业选择。"""
        logger.info("开始提交验证码")
        _url = "https://work.weixin.qq.com/wework_admin/mobile_confirm/confirm_captcha?ajax=1&f=json&d2st="
        _data = {
            "captcha": captcha,
            "tl_key": tl_key
        }
        res = self._se.post_res(_url, json=_data, timeout=15, raise_exception=True)
        logger.info(f"提交验证码返回值:{self._result_brief(res.text)}")
        res = self._se.get_res(
            "https://work.weixin.qq.com/wework_admin/login/choose_corp",
            params={'tl_key': tl_key},
            timeout=15,
            raise_exception=True,
        )
        logger.info(f"choose_corp接口返回值:{self._result_brief(res.text)}")

    def _party_cache(self):
        """拉取企业信息并刷新登录状态。"""
        logger.info("开始获取企业信息,判断是否登录成功")
        if not self._wwrtx_sid:
            return False
        url = "https://work.weixin.qq.com/wework_admin/contacts/party/cache"
        params = {
            'lang': "zh_CN",
            'f': "json",
            'ajax': "1",
            'timeZoneInfo[zone_offset]': "-8",
        }
        self._se.update_cookies({'wwrtx.sid': self._wwrtx_sid})
        try:
            res = self._se.post_res(url, params=params, timeout=10, raise_exception=True)
            if res.status_code == 200:
                data = res.json()
                if self._response_ok(res):
                    self._party_cache_data = data.get('data')
                    self._is_login = True
                    return True
                else:
                    self._party_cache_data = data
            else:
                logger.error(f"获取企业微信部门缓存失败，HTTP状态码：{res.status_code}")
        except Exception as e:
            logger.error(f"获取企业微信部门缓存异常: {e}")
        self._is_login = False
        return False

    def _party_name(self, fallback: str = "") -> str:
        """从企业信息缓存取企业名，结构异常时返回回退值。"""
        cache = self._party_cache_data
        party = cache.get("party_list") if isinstance(cache, dict) else None
        items = party.get("list") if isinstance(party, dict) else None
        first = items[0] if isinstance(items, list) and items else None
        name = first.get("name") if isinstance(first, dict) else None
        return str(name) if name else fallback

    def _notify_quiet(self, channel, userid, title: str, text: str) -> None:
        """发送通知；投递失败只记日志，不打断调用链。"""
        try:
            self.post_message(channel=channel, title=title, userid=userid, text=text)
        except Exception as e:
            logger.warning(f"通知发送失败: {e}")

    def _login(self, channel, userid, source=None, original_message_id=None, original_chat_id=None):
        """接收扫码确认并交给后台线程处理，避免在事件线程里阻塞等待。"""
        logger.info("触发登录回调，开始执行登录步骤")
        qrcode_key = self._qrcode_key
        if not qrcode_key:
            self.post_message(
                channel=channel,
                title="未获取二维码",
                userid=userid,
                text="请先执行 /update_wechat_ip 获取登录二维码。",
            )
            return
        # 扫码确认最多要等 30 秒，放到后台线程，先给用户一个即时回执
        self.post_message(
            channel=channel,
            title="登录中",
            userid=userid,
            text="已收到扫码确认，正在校验登录状态，请稍候…",
        )
        threading.Thread(
            target=self._login_worker,
            args=(channel, userid, qrcode_key, source, original_message_id, original_chat_id),
            name=f"{self.__class__.__name__}-login",
            daemon=True,
        ).start()

    def _login_worker(self, channel, userid, qrcode_key, source=None,
                      original_message_id=None, original_chat_id=None):
        """后台完成扫码确认与登录；异常在本层兜底，避免后台线程静默退出。"""
        try:
            self._login_worker_impl(channel, userid, qrcode_key, source,
                                    original_message_id, original_chat_id)
        except Exception as e:
            logger.exception(f"扫码登录处理异常: {e}")
            self._notify_quiet(channel, userid, "登录失败",
                               "登录处理异常，请重新发送 /update_wechat_ip 扫码。")

    def _login_worker_impl(self, channel, userid, qrcode_key, source=None,
                           original_message_id=None, original_chat_id=None):
        """后台完成扫码确认与登录，需要时下发短信验证码输入交互。"""
        if not self._se:
            logger.warning("网络会话已关闭，跳过本次登录处理")
            return
        check_data = self._check(qrcode_key)
        if check_data:
            # code 为空时 requests 会丢掉该参数，登录页静默失败后可能拿旧 sid 报成功
            code = str(check_data.get('auth_code') or '').strip()
            if not code:
                logger.error("扫码结果缺少 auth_code")
                self.post_message(
                    channel=channel,
                    title="登录失败",
                    userid=userid,
                    text="扫码结果异常（缺少 auth_code），请重新发送 /update_wechat_ip 扫码。",
                )
                return
            try:
                res = self._loginpage_wx(qrcode_key, code)
            except Exception as e:
                logger.error(f"登录请求异常: {e}")
                self.post_message(
                    channel=channel,
                    title="登录失败",
                    userid=userid,
                    text="登录请求异常，请稍后重试；如仍失败请重新发送 /update_wechat_ip 扫码。",
                )
                return
            if 'tl_key' in res.url:
                logger.info("返回值中获取到tl_key,触发短信验证码")
                parsed = urlparse(res.url)
                query_params = parse_qs(parsed.query)
                # 获取 tl_key 的值（parse_qs 返回字典，每个键对应一个列表）
                self._tl_key = query_params.get('tl_key', [None])[0]
                self._start_captcha_input(
                    channel,
                    userid,
                    qrcode_key,
                    source=source,
                    original_message_id=original_message_id,
                    original_chat_id=original_chat_id,
                )
            else:
                self._wwrtx_sid = self._se.get_cookies().get('wwrtx.sid')
                if self._party_cache():
                    logger.info("登录成功")
                    self._login_success()
                    self.post_message(
                        channel=channel,
                        title="登录成功",
                        userid=userid,
                        text=f"成功登录企业:{self._party_name('未知企业')}",
                    )
                else:
                    logger.error(f"登录失败,返回值:{self._party_cache_data}")
                    self.post_message(
                        channel=channel,
                        title="登录失败",
                        userid=userid,
                        text=f"登录失败,返回值:{self._party_cache_data}",
                    )
        else:
            logger.error("未检测到扫码确认，二维码可能已过期")
            self.post_message(
                channel=channel,
                title="登录失败",
                userid=userid,
                text="未检测到扫码确认：二维码可能已过期，或手机上还没点确认。\n"
                     "请重新发送 /update_wechat_ip 获取二维码后再操作。",
            )

    @staticmethod
    def _fail_hint(res) -> str:
        """把失败响应转成可读原因，优先使用接口返回的错误码说明。"""
        reason = UpdateWeChatIp._wecom_error_reason(res.text or "")
        if reason:
            return reason
        if res.status_code in (401, 403):
            return "登录已失效，请重新扫码"
        return "接口返回错误"

    def _fail_state(self) -> Dict[str, Any]:
        """读取连续失败状态：失败次数、上次尝试与上次提醒时间。"""
        return self.get_data(self._fail_state_key) or {}

    def _in_fail_backoff(self) -> bool:
        """连续失败达到阈值后按固定间隔重试，避免每轮都打接口。"""
        state = self._fail_state()
        if int(state.get('count', 0)) < self._fail_backoff_after:
            return False
        try:
            last = datetime.fromisoformat(state.get('last_try') or "")
        except ValueError:
            return False
        return (datetime.now() - last).total_seconds() < self._fail_backoff_minutes * 60

    def _record_fail(self) -> Tuple[bool, bool]:
        """记录一次登录失效，返回（是否需要提醒, 是否首次失败）。"""
        state = self._fail_state()
        now = datetime.now()
        first = int(state.get('count', 0)) == 0
        state['count'] = int(state.get('count', 0)) + 1
        state['last_try'] = now.isoformat()
        try:
            last_notify = datetime.fromisoformat(state.get('last_notify') or "")
        except ValueError:
            last_notify = None
        notify = last_notify is None or (now - last_notify).total_seconds() >= self._fail_backoff_minutes * 60
        if notify:
            state['last_notify'] = now.isoformat()
        self.save_data(self._fail_state_key, state)
        return notify, first

    def _notify_login_invalid(self, first: bool):
        """登录失效提醒交由宿主路由：站内只在首次提醒，其它渠道按间隔重复。"""
        title = "企业微信登录状态失效"
        text = '企业微信登录状态失效，请发送 /update_wechat_ip 获取二维码重新登录'
        if first:
            # 不指定渠道：宿主按各渠道实例投递，NoticeMessage 事件的 channel 为空，
            # 聚合消息通知等第三方渠道插件也能收到
            try:
                self.post_message(title=title, text=text)
            except Exception as e:
                logger.debug(f"首次登录失效提醒失败: {e}")
            return
        for channel in self._enabled_notify_channels():
            try:
                self.post_message(channel=channel, title=title, text=text)
            except Exception as e:
                logger.debug(f"{channel.name} 渠道提醒失败: {e}")

    def _enabled_notify_channels(self) -> List[NotificationChannel]:
        """列出宿主已配置的通知渠道，读取失败时退回全部渠道。"""
        channels: List[NotificationChannel] = []
        try:
            manager = self.chain.modulemanager
            for module in manager.get_running_type_modules(ModuleType.Notification):
                if not module.get_configs():
                    continue
                channel = module.get_subtype()
                if isinstance(channel, NotificationChannel) and channel not in channels:
                    channels.append(channel)
        except Exception as err:
            logger.debug(f"读取已启用通知渠道失败，按全部渠道提醒: {err}")
            return [c for c in NotificationChannel if c.name not in self._notify_silent_channels]
        return [c for c in channels if c.name not in self._notify_silent_channels]

    def _clear_fail(self):
        """登录恢复正常后清除失败计数。"""
        if self._fail_state():
            self.save_data(self._fail_state_key, {})

    @staticmethod
    def _response_ok(res) -> bool:
        """判断管理后台接口是否成功；非 200、非 JSON 或错误码非 0 都算失败。"""
        if res.status_code >= 400:
            return False
        try:
            payload = res.json()
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        nested = payload.get("result")
        for item in (nested, payload):
            if not isinstance(item, dict):
                continue
            for key in ("errCode", "errcode"):
                if key in item:
                    try:
                        if int(item[key]) != 0:
                            return False
                    except (TypeError, ValueError):
                        return False
        return True

    def _save_ip_config(self, app_ids: Optional[List[str]] = None) -> List['UpdateLogDto']:
        """
        把当前公网 IP 写入指定应用的可信IP列表。

        :param app_ids: 待写入的应用 ID；为空时按配置顺序写入全部应用
        :return: 每个应用的写入结果，供调用方按其真实结果通知
        """
        logger.info(f"更新IP为:{self._ip}")
        # 同一次更新共用时间戳，避免逐个应用的写入记录在详情页按秒被拆成多组
        now = datetime.now()
        _update_log: List[UpdateLogDto] = []
        url = 'https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN&f=json&ajax=1'
        for appId in (app_ids or self._app_ids()):
            data = {
                'app_id': appId,
                'ipList[]': self._ip
            }
            try:
                res = self._se.post_res(url, data=data, timeout=15, raise_exception=True)
            except RequestException as e:
                logger.error(f"{appId}更新IP白名单请求异常: {e}")
                _update_log.append(UpdateLogDto(
                    status=False,
                    ip=self._ip,
                    app_id=appId,
                    result=f"请求异常: {e}",
                    UpdateTime=now,
                ))
                continue
            success = self._response_ok(res)
            if not success:
                logger.error(f"{appId}更新IP白名单失败（{self._fail_hint(res)}），返回值：{self._result_brief(res.text)}")
            else:
                logger.info(f'{appId}更新白名单成功，更新IP为：{self._ip}，接口返回值：{self._result_brief(res.text)}')

            result_text = res.text
            if not success and res.status_code >= 400:
                # 记录表里保留状态码，避免空响应或 HTML 错误页只显示长度
                result_text = f"HTTP {res.status_code} {self._result_brief(res.text, 200)}".strip()
            _update_log.append(UpdateLogDto(
                status=success,
                ip=self._ip,
                app_id=appId,
                result=result_text,
                UpdateTime=now,
            ))

        update_log: List[UpdateLogDto] = [UpdateLogDto.from_dict(i) for i in self.get_data(self._UpdateLogKey) or []]
        merged = (update_log + _update_log)[-self._update_log_limit:]
        self.save_data(self._UpdateLogKey, [i.to_dict() for i in merged])
        return _update_log

    def _login_success(self):
        """清理失败状态并把登录凭据写入插件配置。"""
        logger.info("保存配置文件")
        self._clear_fail()
        self._tl_key = None
        config = self.get_config() or {}
        config.update({
            '_enabled': self._enabled,
            '_wwrtx_sid': self._wwrtx_sid,
            '_app_id': self._app_id,
            '_party_cache_data': self._party_cache_data,
            '_cron': self._cron,
        })
        self.update_config(config)

    def _get_buttons(self, qrcode_key: Optional[str] = None):
        """生成短信验证码输入按钮：数字键盘、退格/清空/直接输入、提交。"""
        key = qrcode_key or self._qrcode_key
        buttons = [
            [
                {
                    "text": str(j),
                    "callback_data": f"[PLUGIN]{self.__class__.__name__}|{j}|{key}"
                }
                for j in range(i * 5, (i + 1) * 5)
            ]
            for i in range(2)
        ]
        buttons.append(
            [
                {"text": "退格",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|退格|{key}"},
                {"text": "清空",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|清空|{key}"},
                {"text": "直接输入",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|文本输入|{key}"}
            ]
        )
        buttons.append(
            [{"text": f'输入完毕',
              "callback_data": f"[PLUGIN]{self.__class__.__name__}|输入完毕|{key}"}]
        )
        return buttons

    def _resolve_captcha_key(self, qrcode_key) -> str:
        """解析回调携带的 qrcode_key，缺失或为字面量 None 时回退当前登录会话。"""
        if qrcode_key and str(qrcode_key) != "None":
            return str(qrcode_key)
        return self._qrcode_key

    @staticmethod
    def _digits_of(text) -> str:
        """从输入内容中提取数字，忽略空格、标点和提示前缀。"""
        return re.sub(r'\D', '', str(text or ""))

    @staticmethod
    def _mask_captcha(captcha: str) -> str:
        """脱敏展示已输入的验证码，避免完整短信码留在消息历史中。"""
        if not captcha:
            return "未输入"
        head = captcha[:2]
        return f"{head}{'*' * (len(captcha) - len(head))}（已输入 {len(captcha)} 位）"

    @staticmethod
    def _as_channel(channel) -> Optional[NotificationChannel]:
        """把渠道枚举或字符串归一为 NotificationChannel，无法识别时返回 None。"""
        if not channel:
            return None
        if isinstance(channel, NotificationChannel):
            return channel
        try:
            return NotificationChannel(str(channel))
        except ValueError:
            return None

    @classmethod
    def _is_same_origin_channel(cls, channel) -> bool:
        """判断渠道是否在 MoviePilot 页面内渲染，可使用同源相对地址。"""
        return cls._as_channel(channel) in cls._same_origin_channels

    @classmethod
    def _channel_supports(cls, channel, capability: ChannelCapability) -> bool:
        """判断渠道是否具备指定交互能力，兼容传入渠道枚举或字符串。"""
        resolved = cls._as_channel(channel)
        if not resolved:
            return False
        return ChannelCapabilityManager.supports_capability(resolved, capability)

    @staticmethod
    def _text_input_manager():
        """获取宿主插件文本输入会话管理器，宿主未提供该接口时返回 None。"""
        try:
            from app.application.messaging.plugin import plugin_input_interaction_manager
            return plugin_input_interaction_manager
        except Exception as err:
            logger.debug(f"宿主未提供插件文本输入会话接口: {err}")
            return None

    def _request_text_input(self, channel, userid, source, qrcode_key) -> bool:
        """登记宿主文本输入会话，接管用户在聊天框发送的下一条文本。"""
        manager = self._text_input_manager()
        if not manager:
            return False
        channel_value = self._as_channel(channel)
        try:
            manager.create_or_replace(
                user_id=str(userid),
                plugin_id=self.__class__.__name__,
                channel=channel_value,
                source=source,
                username=None,
                chat_id=None,
                prompt_id=qrcode_key,
                timeout_seconds=self._text_input_timeout,
                payload={"qrcode_key": qrcode_key, "action": "captcha"},
            )
        except Exception as err:
            logger.warning(f"登记短信验证码文本输入会话失败: {err}")
            return False
        return True

    def _captcha_prompt_text(self, qrcode_key, note: str = None) -> str:
        """组装短信验证码输入提示正文。"""
        typed = self._captcha.get(qrcode_key, "")
        lines = [
            "触发验证码：",
            f"验证码内容：{self._mask_captcha(typed)}",
        ]
        if note:
            lines.append(note)
        lines.append("如果按钮不可用，可回复：\n```\n/update_wechat_ip 验证码内容\n```")
        return '\n'.join(lines)

    def _text_input_note(self, channel) -> str:
        """按渠道聊天链路给出一次性输入验证码的引导文案。"""
        if self._as_channel(channel) == NotificationChannel.WebAgent:
            # WebAgent 聊天消息走 Agent 链路，不会消费插件文本输入会话，需使用命令形式一次性提交
            return (
                f"本渠道聊天消息由 Agent 处理，一次性提交请输入：\n"
                f"```\n/update_wechat_ip {self._captcha_length}位完整验证码\n```\n"
                f"可先用退格修改，再一次性发送。"
            )
        return (
            f"请在 {self._text_input_timeout} 秒内直接在聊天框发送完整 {self._captcha_length} 位验证码"
            f"（可先用退格修改再一次性发送），发送“取消”可退回按钮输入。"
        )

    def _send_captcha_prompt(self, channel, userid, qrcode_key, source=None,
                             original_message_id=None, original_chat_id=None,
                             note: str = None) -> None:
        """下发验证码输入提示，渠道支持编辑时优先就地更新原消息。"""
        buttons = self._get_buttons(qrcode_key)
        text = self._captcha_prompt_text(qrcode_key, note=note)
        resolved_channel = self._as_channel(channel)
        if (original_message_id and original_chat_id and resolved_channel
                and self._channel_supports(resolved_channel, ChannelCapability.MESSAGE_EDITING)):
            # WebAgent 没有后端消息模块，编辑事件需要按用户路由
            metadata = {"userid": userid} if resolved_channel == NotificationChannel.WebAgent else None
            try:
                if self.chain.edit_message(
                        channel=resolved_channel,
                        source=source,
                        message_id=original_message_id,
                        chat_id=original_chat_id,
                        title="短信验证码",
                        text=text,
                        buttons=buttons,
                        metadata=metadata):
                    return
            except Exception as err:
                logger.debug(f"编辑短信验证码消息失败，改为发送新消息: {err}")
        self.post_message(
            channel=channel,
            title="短信验证码",
            userid=userid,
            text=text,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id,
        )

    def _start_captcha_input(self, channel, userid, qrcode_key, source=None,
                             original_message_id=None, original_chat_id=None) -> None:
        """下发验证码输入交互：支持按钮的渠道展示键盘，不支持时直接接管聊天文本。"""
        if self._channel_supports(channel, ChannelCapability.INLINE_BUTTONS):
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
                note="可点数字按钮逐位输入（支持退格/清空），也可点“直接输入”后在聊天框一次发送完整验证码。",
            )
            return
        if self._request_text_input(channel, userid, source, qrcode_key):
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
                note=self._text_input_note(channel),
            )
            return
        self._send_captcha_prompt(
            channel=channel,
            userid=userid,
            qrcode_key=qrcode_key,
            source=source,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id,
        )

    def _submit_captcha(self, channel, userid, qrcode_key, source=None) -> None:
        """提交短信验证码并回报登录结果。"""
        if not self._tl_key:
            self.post_message(
                channel=channel,
                title="验证码不可用",
                userid=userid,
                text="未获取到短信验证状态，请重新发送 /update_wechat_ip 扫码登录。",
            )
            return
        captcha = self._captcha.get(qrcode_key) or ""
        if len(captcha) != self._captcha_length:
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                note=(
                    f"当前已输入 {len(captcha)} 位，需要 {self._captcha_length} 位，"
                    f"请用退格/清空修正，或点“直接输入”在聊天框一次发送完整验证码。"
                ),
            )
            return
        # 有处理中状态的渠道由宿主显示等待反馈，其余渠道需要一条文字回执
        if not self._channel_supports(channel, ChannelCapability.PROCESSING_STATUS):
            self._notify_quiet(channel, userid, "验证码已提交", "正在向企业微信提交验证码，请稍候…")
        try:
            self._confirm_captcha(self._tl_key, captcha)
        except Exception as e:
            logger.error(f"提交验证码异常: {e}")
            self.post_message(
                channel=channel,
                title="验证码提交失败",
                userid=userid,
                text="验证码提交请求异常，请稍后重试；如仍失败请重新扫码。",
            )
            return
        self._wwrtx_sid = self._se.get_cookies().get('wwrtx.sid')
        self._captcha.pop(qrcode_key, None)
        if self._party_cache():
            self._login_success()
            self.post_message(
                channel=channel,
                title="登录成功",
                userid=userid,
                text=f"成功登录企业:{self._party_name('未知企业')}",
            )
        else:
            self.post_message(
                channel=channel,
                title="登录失败",
                userid=userid,
                text=f"登录失败,返回值:{self._party_cache_data}",
            )

    def _handle_text_input_event(self, event_data, callback_text: str) -> None:
        """处理宿主文本输入会话回调，支持聊天框一次性输入完整验证码。"""
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        payload = event_data.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        qrcode_key = self._resolve_captcha_key(payload.get("qrcode_key"))
        if callback_text.startswith("plugin_input_cancel"):
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                note="已退出文本输入，可继续使用数字按钮（支持退格/清空）。",
            )
            return
        if callback_text.startswith("plugin_input_expired"):
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                note="文本输入已超时，请点“直接输入”重新发起，或使用数字按钮输入。",
            )
            return
        digits = self._digits_of(event_data.get("input_text"))
        if not digits:
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                note="本次输入未包含数字，已退出文本输入，需要时请点“直接输入”重试。",
            )
            return
        if len(digits) == self._captcha_length:
            self._captcha[qrcode_key] = digits
            self._submit_captcha(channel, userid, qrcode_key, source=source)
            return
        re_registered = self._request_text_input(channel, userid, source, qrcode_key)
        self._send_captcha_prompt(
            channel=channel,
            userid=userid,
            qrcode_key=qrcode_key,
            source=source,
            note=(
                f"识别到 {len(digits)} 位数字，需要 {self._captcha_length} 位，"
                + ("请在聊天框重新发送完整验证码。" if re_registered else "请使用数字按钮输入。")
            ),
        )

    @staticmethod
    def _parse_ip_urls(value) -> List[str]:
        """把英文逗号分隔的接口配置拆成 URL 列表，忽略空项和非 HTTP(S) 地址。"""
        if isinstance(value, (list, tuple)):
            candidates = [str(item) for item in value]
        else:
            candidates = str(value or "").split(",")
        return [item.strip() for item in candidates
                if item.strip().startswith(("http://", "https://"))]

    def get_ip_from_url(self) -> Optional[str]:
        """按候选接口依次查询当前公网 IPv4，全部失败返回 None。"""
        for url in self._ip_urls:
            try:
                response = RequestUtils(headers={'User-Agent': self._headers['User-Agent']},
                                        timeout=3, verify=True).get_res(url, raise_exception=True)
            except Exception as e:
                # 网络波动只记一条，避免每个候选接口都刷屏
                if "104" not in str(e) and 'Read timed out' not in str(e):
                    logger.warning(f"{url} 获取IP失败, Error: {e}")
                continue
            if response.status_code != 200:
                continue
            matched = re.search(self._ip_pattern, response.text or "")
            if not matched:
                continue
            candidate = matched.group()
            try:
                ipaddress.IPv4Address(candidate)
            except ValueError:
                continue
            return candidate
        return None

    def _app_ids(self) -> List[str]:
        """按配置顺序返回去重后的应用 ID。"""
        app_ids: List[str] = []
        for item in (self._app_id or "").split(","):
            app_id = item.strip()
            if app_id and app_id not in app_ids:
                app_ids.append(app_id)
        return app_ids

    def _get_corp_app_v2(self, app_id: Optional[str] = None):
        """读取指定应用（默认首个）的配置，用于比对可信IP列表。"""
        app_ids = self._app_ids()
        target = (app_id or (app_ids[0] if app_ids else "")).strip()
        if not target:
            logger.error("未配置应用ID")
            return {}
        # 多应用逐个校验时只保留一行汇总日志，这里降为 debug 避免刷屏
        logger.debug(f"获取企业应用配置：{target}")
        url = f'https://work.weixin.qq.com/wework_admin/apps/getCorpAppV2?lang=zh_CN&f=json&ajax=1&app_id={target}'
        try:
            res = self._se.get_res(url, timeout=10, raise_exception=True)
            if res.status_code == 200:
                return res.json().get('data', {})
            else:
                logger.error(f"获取企业应用配置失败，HTTP状态码：{res.status_code}")
        except Exception as e:
            logger.error(f"获取企业应用配置异常: {e}")
        return {}

    def _apps_missing_ip(self) -> List[str]:
        """返回可信IP列表未包含当前公网 IP 的应用，读取失败的应用按缺少处理。"""
        logger.info("开始校验各应用的可信IP列表")
        missing: List[str] = []
        for app_id in self._app_ids():
            white_ip_list = (self._get_corp_app_v2(app_id).get('app') or {}).get('white_ip_list') or {}
            if self._ip in (white_ip_list.get('ip') or []):
                continue
            missing.append(app_id)
        return missing

    def _notify_ip_update(self, results: List['UpdateLogDto']) -> None:
        """按各应用的真实结果通知，全部失败时不再报告成功。"""
        if not results:
            return
        failed = [row for row in results if not row.status]
        if not failed:
            text = "触发IP更新,最新IP为：" + self._ip
        elif len(failed) == len(results):
            detail = "；".join(
                f"{row.app_id}：{self._log_result_text(row.status, row.result)}" for row in failed[:3]
            )
            if len(failed) > 3:
                detail += f"；共 {len(failed)} 个应用失败"
            text = f"IP更新失败，最新IP为：{self._ip}\n{detail}"
        else:
            text = (f"IP更新部分失败，最新IP为：{self._ip}；成功 {len(results) - len(failed)} 个，"
                    f"失败 {len(failed)} 个（{'、'.join(row.app_id for row in failed[:3])}）")
        self.post_message(title='企业微信IP更新', text=text)

    def _run_check_safe(self):
        """Timer 线程里安全执行 check()，避免异常导致线程静默退出。"""
        try:
            self.check()
        except Exception as e:
            logger.error(f"立即检测一次执行异常: {e}")
        finally:
            self._timer = None

    def check(self):
        """检查登录状态，并在公网 IP 未登记时更新可信IP。"""
        if not self._enabled:
            logger.error("插件未开启")
            return
        if self._in_fail_backoff():
            logger.debug(f"登录状态仍未恢复，{self._fail_backoff_minutes} 分钟后重试")
            return
        self._party_cache()
        if not self._is_login:
            notify, first = self._record_fail()
            logger.error(f"未登录（登录已失效，请重新扫码），累计失败 {self._fail_state().get('count')} 次")
            if notify:
                self._notify_login_invalid(first)
            return
        self._clear_fail()
        self._ip = self.get_ip_from_url()
        if not self._ip:
            logger.error("获取当前公网IP失败，跳过本次检测")
            return
        if not self._app_ids():
            logger.error("未配置应用ID，跳过可信IP校验")
            return
        missing_apps = self._apps_missing_ip()
        if not missing_apps:
            logger.debug(f"可信IP列表已包含当前IP {self._ip}，无需更新")
            return
        logger.info(f"以下应用缺少当前IP {self._ip}：{','.join(missing_apps)}")
        self._notify_ip_update(self._save_ip_config(missing_apps))


@dataclass
class UpdateLogDto:
    """一条可信IP更新记录。"""
    status: bool
    ip: str
    app_id: str
    result: str
    UpdateTime: Optional[datetime] = None

    def __post_init__(self):
        """补默认更新时间。"""
        if self.UpdateTime is None:
            self.UpdateTime = datetime.now()

    def to_dict(self):
        """转换为可持久化的字典。"""
        return {
            "status": self.status,
            "ip": self.ip,
            "app_id": self.app_id,
            "result": self.result,
            "UpdateTime": self.UpdateTime.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict):
        """从持久化字典还原记录，忽略未知字段并容忍缺失字段。"""
        raw = data if isinstance(data, dict) else {}
        raw_time = raw.get('UpdateTime')
        try:
            update_time = datetime.fromisoformat(raw_time) if raw_time else None
        except (TypeError, ValueError):
            update_time = None
        return cls(
            status=bool(raw.get('status', False)),
            ip=str(raw.get('ip') or ''),
            app_id=str(raw.get('app_id') or ''),
            result=str(raw.get('result') or ''),
            UpdateTime=update_time,
        )


class UpdateIpResult(BaseModel):
    """UpdateIP 接口响应模型。"""

    success: bool = Field(description="是否全部应用更新成功")
    ip: ipaddress.IPv4Address = Field(description="本次写入的可信IP")
    updated: int = Field(description="写入可信IP的应用数量")
    failed_app_ids: List[str] = Field(default_factory=list, description="更新失败的应用ID")
