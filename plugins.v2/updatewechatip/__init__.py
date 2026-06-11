import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
from apscheduler.triggers.cron import CronTrigger
import requests
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.string import StringUtils


class UpdateWeChatIp(_PluginBase):
    # 插件在界面中的展示名称
    plugin_name = "动态企微可信IP"
    # 插件描述
    plugin_desc = "修改企微应用可信IP，可本地扫码刷新Cookie"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本，必须和 package.v2.json 中保持一致
    plugin_version = "1.0.4"
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
    _wwrtx_sid = None
    _party_cache_data = None
    _app_id = ""
    _ip = None
    _is_login = False
    onlyonce = False
    _cron = ""

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
        config = config or {}
        self._enabled = bool(config.get("_enabled"))
        self._wwrtx_sid = config.get("_wwrtx_sid")
        self._app_id = config.get("_app_id")
        self._cron = config.get("_cron")
        self._party_cache_data = config.get("_party_cache_data")

        self._se = requests.Session()
        self._se.cookies.set('wwrtx.sid', self._wwrtx_sid)
        self._ip = self.get_ip_from_url()
        self.check()

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
        if arg_str is not None:
            if arg_str == '扫码完成':
                self._login(channel, user)
            elif len(re.findall('[0-9]', arg_str)) == 6:
                self._captcha[self._qrcode_key] = arg_str
                self._confirm_captcha(self._tl_key, self._captcha.get(self._qrcode_key))
                self._wwrtx_sid = self._se.cookies.get_dict().get('wwrtx.sid')
                if self._party_cache():
                    self._login_success()
                    self.post_message(
                        channel=channel,
                        title="登录成功",
                        userid=user,
                        text=f"成功登录企业:{self._party_cache_data.get('party_list', {}).get('list', [{}])[0].get('name')}",
                    )
                else:
                    self.post_message(
                        channel=channel,
                        title="登录失败",
                        userid=user,
                        text=f"登录失败,返回值:{self._party_cache_data}",
                    )
            else:
                self.post_message(
                    channel=channel,
                    title="无效的输入",
                    userid=user,
                    content="无效的输入",
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
        text, qrcode_key = event_data.get("text", "").split("|")
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        # 获取原始消息ID和聊天ID（用于直接更新原消息）
        original_message_id = event_data.get("original_message_id")
        original_chat_id = event_data.get("original_chat_id")

        if text == "扫码完成":
            self._qrcode_key = qrcode_key
            self._login(channel, userid)
        if text == "输入完毕":
            self._confirm_captcha(self._tl_key, self._captcha.get(self._qrcode_key))
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
        elif len(re.findall('[0-9]', text)) != 0:
            if qrcode_key not in self._captcha.keys():
                self._captcha[qrcode_key] = ""
            self._captcha[qrcode_key] += text
            self.post_message(
                channel=channel,
                title="短信验证码",
                userid=userid,
                buttons=self._get_buttons(),
                text='\n'.join(
                    [
                        "触发验证码：",
                        f"验证码内容:{self._captcha[qrcode_key]}\n"
                        f"如果按钮不可用，可回复：\n```\n/update_wechat_ip 验证码内容\n```"
                    ]
                ),
                original_message_id=original_message_id,
                original_chat_id=original_chat_id
            )
        else:
            self.post_message(
                channel=channel,
                title="无效的输入",
                userid=userid,
                content="无效的输入",
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
                                            'placeholder': '输入应用ID,多个使用(,)英文逗号隔开,在企业微信应用页面URL末尾获取'
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
            "_corn": '*/10 * * * *'
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
                    {"component": "td", "text": data.UpdateTime},
                ],
            }
            for data in data_list
        ]

        # ---------- 安全获取 party 名称 ----------
        party_list = self._party_cache_data.get("party_list", {}).get("list") or [{}]
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

    def stop_service(self):
        """没有后台任务时可以留空。"""
        pass

    def _get_key(self):
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/get_key"
        params = {
            'r': "0.5068683627412351",
            'login_type': "login_admin",
            'callback': "wwqrloginCallback_1780361432492",
            'redirect_uri': "https://work.weixin.qq.com/wework_admin/loginpage_wx?_r=234&redirect_uri=https%3A%2F%2Fwork.weixin.qq.com%2Fwework_admin%2Fframe&url_hash=%23%2Fapps#/apps",
            'crossorigin': "1"
        }
        response = self._se.get(url, params=params, headers=self._headers)

        return response.json().get('data', {}).get('qrcode_key')

    def _qrcode(self, key) -> str:
        url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/qrcode"
        params = {
            'qrcode_key': key,
            'login_type': "login_admin"
        }
        response = self._se.get(url, params=params, headers=self._headers)
        # return response.url
        img_path: Path = self.get_data_path() / f"WeChatQr.jpg"
        img_path.write_bytes(response.content)
        return f'http://127.0.0.1:{settings.PORT}/api/v1/plugin/{self.__class__.__name__}/img/{uuid.uuid4().__str__().replace('-', '')}?apikey={settings.API_TOKEN}'

    def _check(self, key) -> Dict:
        for _ in range(12):
            url = "https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/check"
            params = {
                'qrcode_key': key,
                'status': "QRCODE_SCAN_ING"
            }
            response = self._se.get(url, params=params, headers=self._headers)
            data = response.json().get('data', {})
            if data.get("status") == "QRCODE_SCAN_SUCC":
                return data
            time.sleep(5)
        return None

    def _loginpage_wx(self, key, code) -> requests.Response:
        url = "https://work.weixin.qq.com/wework_admin/loginpage_wx"
        params = {
            '_r': "234",
            'redirect_uri': "https://work.weixin.qq.com/wework_admin/frame",
            'url_hash': "#/apps",
            'code': code,
            'auth_redirect_time': "1780446137000",
            'getauth_time': "1780446137000",
            'wwqrlogin': "1",
            'qrcode_key': key,
            'auth_source': "SOURCE_FROM_WEWORK",
            'confirm_type': "0"
        }
        response = self._se.get(url, params=params, headers=self._headers)
        return response

    def _confirm_captcha(self, tl_key, captcha):
        _url = "https://work.weixin.qq.com/wework_admin/mobile_confirm/confirm_captcha?ajax=1&f=json&d2st="
        _data = {
            "captcha": captcha,
            "tl_key": tl_key
        }
        res = self._se.post(_url, json=_data, headers=self._headers)
        self._se.get(f"https://work.weixin.qq.com/wework_admin/login/choose_corp?tl_key={tl_key}")
        logger.info("提交验证码")

    def _party_cache(self):
        if self._wwrtx_sid is None:
            return False
        url = "https://work.weixin.qq.com/wework_admin/contacts/party/cache"
        params = {
            'lang': "zh_CN",
            'f': "json",
            'ajax': "1",
            'timeZoneInfo[zone_offset]': "-8",
        }
        self._se.cookies.set('wwrtx.sid', self._wwrtx_sid)
        res = self._se.post(url, params=params, headers=self._headers)
        self._party_cache_data = res.json()
        logger.info(res.text)
        if 'errCode' not in res.text:
            self._party_cache_data = res.json().get('data')
            self._is_login = True
            return True
        self._is_login = False
        return False

    def _login(self, channel, userid):
        check_data = self._check(self._qrcode_key)
        if check_data:
            code = check_data.get('auth_code')
            res = self._loginpage_wx(self._qrcode_key, code)
            if 'tl_key' in res.url:
                self.post_message(
                    channel=channel,
                    title="短信验证码",
                    userid=userid,
                    buttons=self._get_buttons(),
                    text='\n'.join(
                        [
                            "触发验证码：",
                            f"如果按钮不可用，可回复：\n```\n/update_wechat_ip 验证码内容\n```"
                        ]
                    ),
                )
                parsed = urlparse(res.url)
                query_params = parse_qs(parsed.query)
                # 获取 tl_key 的值（parse_qs 返回字典，每个键对应一个列表）
                self._tl_key = query_params.get('tl_key', [None])[0]
            else:
                self._wwrtx_sid = self._se.cookies.get_dict().get('wwrtx.sid')
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

    def _save_ip_config(self):
        logger.info(f"更新IP为:{self._ip}")
        _update_log = []
        url = 'https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN&f=json&ajax=1'
        for appId in self._app_id.split(','):
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
            [{"text": f'输入完毕',
              "callback_data": f"[PLUGIN]{self.__class__.__name__}|输入完毕|{self._qrcode_key}"}]
        )
        return buttons

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
        url = f'https://work.weixin.qq.com/wework_admin/apps/getCorpAppV2?lang=zh_CN&f=json&ajax=1&app_id={self._app_id.split(",")[0]}'
        res = self._se.get(url)
        return res.json().get('data', {})

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
        app_config = self._get_corp_app_v2()
        app_config_ips = app_config.get('app', {}).get('white_ip_list', {}).get('ip', [])
        if self._ip not in app_config_ips:
            if self._save_ip_config():
                self.post_message(
                    title='企业微信IP更新成功',
                    text="IP已更新为:" + self._ip
                )


@dataclass
class UpdateLogDto:
    status: bool
    ip: str
    app_id: str
    result: str
    UpdateTime: datetime = datetime.now()

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
