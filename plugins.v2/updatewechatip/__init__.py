import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import requests
from apscheduler.triggers.cron import CronTrigger
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.notification import ChannelCapability, ChannelCapabilityManager
from app.schemas.types import EventType, NotificationChannel


class UpdateWeChatIp(_PluginBase):
    # 插件在界面中的展示名称
    plugin_name = "动态企微可信IP"
    # 插件描述
    plugin_desc = "修改企微应用可信IP，可本地扫码刷新Cookie"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本，必须和 package.v2.json 中保持一致
    plugin_version = "1.0.10"
    # 作者信息
    plugin_author = "书小白"
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

    _ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip", "https://ip.3322.net", "https://4.ipw.cn",
                'http://v4.666666.host:66/ip', 'https://ipv4.ddnspod.com', 'https://v4.66666.host:66/ip',
                'https://4.ipw.cn', 'https://ip.3322.net', 'https://6.66666.host:66/ip']
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

        self._se = requests.Session()
        self._se.cookies.set('wwrtx.sid', self._wwrtx_sid)

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
                logger.error(f"关闭 requests.Session 失败: {e}")
            finally:
                self._se = None

    def _save_current_config(self):
        self._login_success()

    def get_state(self) -> bool:
        """返回插件当前是否启用。"""
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
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
        if arg_str is not None and str(arg_str).strip():
            arg_text = str(arg_str).strip()
            if arg_text == '扫码完成':
                self._login(channel, user, source=source)
            elif len(self._digits_of(arg_text)) == self._captcha_length:
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
            # 初始化变量
            self._qrcode_key = None
            self._tl_key = None
            self._captcha = {}

            self._qrcode_key = self._get_key()
            image_url = self._qrcode(self._qrcode_key)

            self.post_message(
                channel=channel,
                title="登录二维码",
                text='\n'.join(
                    [
                        "请选择要执行的操作：",
                        f"如果按钮不可用，可回复：\n```\n/update_wechat_ip 扫码完成\n```"
                    ]
                ),
                userid=user,
                buttons=[[{"text": f'扫码完成',
                           "callback_data": f"[PLUGIN]{self.__class__.__name__}|扫码完成|{self._qrcode_key}"}]],
                image=image_url
            )

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
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
            )
        elif text == "清空":
            self._captcha[qrcode_key] = ""
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
                note="已清空输入，可重新输入验证码。",
            )
        elif text == "文本输入":
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
            else:
                self._send_captcha_prompt(
                    channel=channel,
                    userid=userid,
                    qrcode_key=qrcode_key,
                    source=source,
                    original_message_id=original_message_id,
                    original_chat_id=original_chat_id,
                    note="当前宿主未提供文本输入会话接口，请使用数字按钮或 /update_wechat_ip 命令输入。",
                )
        elif len(re.findall('[0-9]', text)) != 0:
            if qrcode_key not in self._captcha.keys():
                self._captcha[qrcode_key] = ""
            self._captcha[qrcode_key] += text
            self._send_captcha_prompt(
                channel=channel,
                userid=userid,
                qrcode_key=qrcode_key,
                source=source,
                original_message_id=original_message_id,
                original_chat_id=original_chat_id,
            )
        else:
            self.post_message(
                channel=channel,
                title="无效的输入",
                userid=userid,
                text="无效的输入",
            )

    def get_api(self) -> List[Dict[str, Any]]:
        """没有插件 API 时直接返回空列表。"""
        return [
            {
                "path": "/img/{uuid}",
                "endpoint": self.get_img,
                "methods": ["GET"],
                # 前端插件页面通过 api 模块调用时，通常使用 bear
                "auth": "apikey",
                "summary": "获取图片",
                "description": "获取图片",
            },
            {
                "path": "/UpdateIP",
                "endpoint": self.UpdateIp,
                "methods": ["GET"],
                # 前端插件页面通过 api 模块调用时，通常使用 bear
                "auth": "apikey",
                "summary": "更新企业微信IP白名单",
                "description": "更新企业微信IP白名单,需要传递查询参数,参数名为:ip",
            },
        ]

    def UpdateIp(self, ip):
        self._ip = ip
        self._save_ip_config()

    def get_img(self, uuid):
        save_path: Path = self.get_data_path() / f"WeChatQr.jpg"
        return FileResponse(
            save_path,
            media_type="image/jpeg"
        )

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
                                            'placeholder': '*/10 * * * *'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': '_app_id',
                                            'label': '[必填]应用ID',
                                            'rows': 1,
                                            'placeholder': '输入应用ID，多个使用英文逗号(,)隔开，在企业微信应用页面URL末尾获取'
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
            "onlyonce": False
        }

    def get_page(self) -> List[dict]:
        """返回详情页 JSON。"""
        # ---------- 获取并排序更新日志 ----------
        raw_data = self.get_data(self._UpdateLogKey) or []
        update_log: List[UpdateLogDto] = [UpdateLogDto.from_dict(i) for i in raw_data]
        data_list = sorted(update_log, key=lambda x: x.UpdateTime, reverse=True)

        update_log_trs = [
            {
                "component": "tr",
                "props": {"class": "text-sm"},
                "content": [
                    {
                        "component": "td",
                        "props": {
                            "style": {"color": "red"} if not data.status else {}
                        },
                        "text": "成功" if data.status else "失败",
                    },
                    {"component": "td", "text": data.app_id},
                    {"component": "td", "text": data.ip},
                    {"component": "td", "text": data.result},
                    {"component": "td",
                     "text": data.UpdateTime.strftime('%Y-%m-%d %H:%M:%S') if data.UpdateTime else ""},
                ],
            }
            for data in data_list
        ]

        # ---------- 安全获取 party 名称 ----------
        party_cache = self._party_cache_data or {}
        party_list = party_cache.get("party_list", {}).get("list") or [{}]
        party_name = party_list[0].get("name", "未知")

        # ---------- 构建页面结构 ----------
        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            # 顶部状态标题
                            {
                                "component": "div",
                                "props": {
                                    "style": {
                                        "display": "flex",
                                        "justifyContent": "center",
                                        "alignItems": "center",
                                        "flexDirection": "column",
                                        "gap": "10px",
                                        "marginBottom": "20px",  # 增加与表格的间距
                                    }
                                },
                                "content": [
                                    {
                                        "component": "div",
                                        "text": f"{party_name}已登录" if self._is_login else "登录失效",
                                        "props": {
                                            "style": {
                                                "fontSize": "22px",
                                                "fontWeight": "bold",
                                                "color": "#ffffff",
                                                "backgroundColor": "#9B50FF",
                                                "padding": "8px 16px",
                                                "borderRadius": "5px",
                                                "textAlign": "center",
                                                "display": "inline-block",
                                            }
                                        },
                                    }
                                ],
                            },
                            # 日志表格
                            {
                                "component": "VTable",
                                "props": {"hover": True},
                                "content": [
                                    {
                                        "component": "thead",
                                        "props": {"class": "text-no-wrap"},
                                        "content": [
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "状态",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "appId",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "更新IP",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "返回值",
                                            },
                                            {
                                                "component": "th",
                                                "props": {"class": "text-start ps-4"},
                                                "text": "更新时间",
                                            },
                                        ],
                                    },
                                    {
                                        "component": "tbody",
                                        "content": update_log_trs,
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        ]

    def _get_key(self):
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
        response = self._se.get(url, params=params, headers=self._headers)
        logger.info(f"获取登录二维码key成功，返回值:{response.text}")

        return response.json().get('data', {}).get('qrcode_key')

    def _qrcode(self, key) -> str:
        logger.info("开始获取登录二维码图片")
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/qrcode"
        params = {
            'qrcode_key': key,
            'login_type': "login_admin"
        }
        response = self._se.get(url, params=params, headers=self._headers)
        logger.info("登录二维码图片获取成功")
        img_path: Path = self.get_data_path() / f"WeChatQr.jpg"
        img_path.write_bytes(response.content)
        logger.info(f"登录二维码已写入文件,路径:{img_path}")
        uri = f"/api/v1/plugin/{self.__class__.__name__}/img/{uuid.uuid4().__str__().replace('-', '')}?apikey={settings.API_TOKEN}"
        img_url = settings.MP_DOMAIN(uri) or f"http://127.0.0.1:{settings.PORT}{uri}"
        logger.info(f"构建二维码地址为:{img_url}")
        return img_url

    def _check(self, key) -> Dict:
        logger.info("开始获取扫码结果")
        for _ in range(2):
            url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/check"
            params = {
                'qrcode_key': key,
                'status': "QRCODE_SCAN_ING"
            }
            response = self._se.get(url, params=params, headers=self._headers)
            data = response.json().get('data', {})
            logger.info(f"扫码结果获取完成:{response.text}")
            if data.get("status") == "QRCODE_SCAN_SUCC":
                return data
            time.sleep(1)
        logger.info("获取扫码结果超时")
        return None

    def _loginpage_wx(self, key, code) -> requests.Response:
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
        response = self._se.get(url, params=params, headers=self._headers)
        logger.info(f"登录完成,返回值:{response.text}")
        return response

    def _confirm_captcha(self, tl_key, captcha):
        logger.info("开始提交验证码")
        _url = "https://work.weixin.qq.com/wework_admin/mobile_confirm/confirm_captcha?ajax=1&f=json&d2st="
        _data = {
            "captcha": captcha,
            "tl_key": tl_key
        }
        res = self._se.post(_url, json=_data, headers=self._headers)
        logger.info(f"提交验证码返回值:{res.text}")
        res = self._se.get(f"https://work.weixin.qq.com/wework_admin/login/choose_corp?tl_key={tl_key}")
        logger.info(f"choose_corp接口返回值:{res.text}")

    def _party_cache(self):
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
        self._se.cookies.set('wwrtx.sid', self._wwrtx_sid)
        try:
            res = self._se.post(url, params=params, headers=self._headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if 'errCode' not in res.text:
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

    def _login(self, channel, userid, source=None, original_message_id=None, original_chat_id=None):
        """执行扫码后的登录步骤，需要时下发短信验证码输入交互。"""
        logger.info("触发登录回调，开始执行登录步骤")
        check_data = self._check(self._qrcode_key)
        if check_data:
            code = check_data.get('auth_code')
            res = self._loginpage_wx(self._qrcode_key, code)
            if 'tl_key' in res.url:
                logger.info("返回值中获取到tl_key,触发短信验证码")
                parsed = urlparse(res.url)
                query_params = parse_qs(parsed.query)
                # 获取 tl_key 的值（parse_qs 返回字典，每个键对应一个列表）
                self._tl_key = query_params.get('tl_key', [None])[0]
                self._start_captcha_input(
                    channel,
                    userid,
                    self._qrcode_key,
                    source=source,
                    original_message_id=original_message_id,
                    original_chat_id=original_chat_id,
                )
            else:
                self._wwrtx_sid = self._se.cookies.get_dict().get('wwrtx.sid')
                if self._party_cache():
                    logger.info("登录成功")
                    self._login_success()
                    self.post_message(
                        channel=channel,
                        title="登录成功",
                        userid=userid,
                        text=f"成功登录企业:{self._party_cache_data.get('party_list', {}).get('list', [{}])[0].get('name')}",
                    )
                else:
                    logger.error(f"登录失败,返回值:{self._party_cache_data}")
                    self.post_message(
                        channel=channel,
                        title="登录失败",
                        userid=userid,
                        text=f"登录失败,返回值:{self._party_cache_data}",
                    )

    def _save_ip_config(self):
        logger.info(f"更新IP为:{self._ip}")
        _update_log = []
        url = 'https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN&f=json&ajax=1'
        for appId in self._app_id.split(','):
            appId = appId.strip()
            if not appId:
                continue
            data = {
                'app_id': appId,
                'ipList[]': self._ip
            }
            res = self._se.post(url, data=data, headers=self._headers)
            if 'err' in res.text:
                logger.error(f"{appId}更新IP白名单失败，返回值：{res.text}")
            else:
                logger.info(f'{appId}更新白名单成功，更新IP为：{self._ip}，接口返回值：{res.text}')

            _update_log.append(UpdateLogDto(
                status='err' not in res.text,
                ip=self._ip,
                app_id=appId,
                result=res.text
            ))

        update_log: List[UpdateLogDto] = [UpdateLogDto.from_dict(i) for i in self.get_data(self._UpdateLogKey) or []]
        self.save_data(self._UpdateLogKey, [i.to_dict() for i in update_log + _update_log])

    def _login_success(self):
        logger.info("保存配置文件")
        self.update_config({
            '_enabled': self._enabled,
            '_wwrtx_sid': self._wwrtx_sid,
            '_app_id': self._app_id,
            '_party_cache_data': self._party_cache_data,
            '_cron': self._cron,
        })

    def _get_buttons(self):
        """生成短信验证码输入按钮：数字键盘、退格/清空/直接输入、提交。"""
        buttons = [
            [
                {
                    "text": str(j),
                    "callback_data": f"[PLUGIN]{self.__class__.__name__}|{j}|{self._qrcode_key}"
                }
                for j in range(i * 5, (i + 1) * 5)
            ]
            for i in range(2)
        ]
        buttons.append(
            [
                {"text": "退格",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|退格|{self._qrcode_key}"},
                {"text": "清空",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|清空|{self._qrcode_key}"},
                {"text": "直接输入",
                 "callback_data": f"[PLUGIN]{self.__class__.__name__}|文本输入|{self._qrcode_key}"}
            ]
        )
        buttons.append(
            [{"text": f'输入完毕',
              "callback_data": f"[PLUGIN]{self.__class__.__name__}|输入完毕|{self._qrcode_key}"}]
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
        buttons = self._get_buttons()
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
        self._confirm_captcha(self._tl_key, captcha)
        self._wwrtx_sid = self._se.cookies.get_dict().get('wwrtx.sid')
        self._captcha.pop(qrcode_key, None)
        if self._party_cache():
            self._login_success()
            self.post_message(
                channel=channel,
                title="登录成功",
                userid=userid,
                text=f"成功登录企业:{self._party_cache_data.get('party_list', {}).get('list', [{}])[0].get('name')}",
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

    def get_ip_from_url(self):
        urls = self._ip_urls
        for url in urls:
            try:
                response = requests.get(url, timeout=3)
                if response.status_code == 200:
                    ip_address = re.search(self._ip_pattern, response.text)
                    if ip_address:
                        return ip_address.group()
            except Exception as e:
                if "104" not in str(e) and 'Read timed out' not in str(e):  # 忽略网络波动,都失败会返回None, "获取IP失败"
                    logger.warning(f"{url} 获取IP失败, Error: {e}")
        return "获取IP失败"

    def _get_corp_app_v2(self):
        logger.info("开始获取企业应用配置")
        if not self._app_id:
            logger.error("未配置应用ID")
            return {}
        app_id = self._app_id.split(",")[0].strip()
        url = f'https://work.weixin.qq.com/wework_admin/apps/getCorpAppV2?lang=zh_CN&f=json&ajax=1&app_id={app_id}'
        try:
            res = self._se.get(url, timeout=10)
            if res.status_code == 200:
                return res.json().get('data', {})
            else:
                logger.error(f"获取企业应用配置失败，HTTP状态码：{res.status_code}")
        except Exception as e:
            logger.error(f"获取企业应用配置异常: {e}")
        return {}

    def _run_check_safe(self):
        """Timer 线程里安全执行 check()，避免异常导致线程静默退出。"""
        try:
            self.check()
        except Exception as e:
            logger.error(f"立即检测一次执行异常: {e}")
        finally:
            self._timer = None

    def check(self):
        if not self._enabled:
            logger.error("插件未开启")
            return
        self._party_cache()
        if not self._is_login:
            logger.error("未登录")
            self.post_message(
                title="企业微信登录状态失效",
                text='企业微信登录状态失效,请重新操作登录'
            )
            return
        self._ip = self.get_ip_from_url()
        if not self._ip or self._ip == "获取IP失败":
            logger.error("获取当前公网IP失败，跳过本次检测")
            return
        app_config = self._get_corp_app_v2()
        app_config_ips = app_config.get('app', {}).get('white_ip_list', {}).get('ip', [])
        if self._ip not in app_config_ips:
            self._save_ip_config()
            self.post_message(
                title='企业微信IP更新',
                text="触发IP更新,最新IP为：" + self._ip
            )


@dataclass
class UpdateLogDto:
    status: bool
    ip: str
    app_id: str
    result: str
    UpdateTime: datetime = None

    def __post_init__(self):
        if self.UpdateTime is None:
            self.UpdateTime = datetime.now()

    def to_dict(self):
        return {
            "status": self.status,
            "ip": self.ip,
            "app_id": self.app_id,
            "result": self.result,
            "UpdateTime": self.UpdateTime.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict):
        # 深拷贝一份，避免修改原字典
        kwargs = dict(data)
        # 将 'UpdateTime' 字符串转为 datetime，注意参数名对应 __init__ 的 update_time
        kwargs['UpdateTime'] = datetime.fromisoformat(kwargs.pop('UpdateTime'))
        return cls(**kwargs)
