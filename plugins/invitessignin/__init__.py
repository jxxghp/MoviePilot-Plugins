import re
import time
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
from app.schemas import NotificationType
from app.utils.http import RequestUtils


class InvitesSignin(_PluginBase):
    # 插件名称
    plugin_name = "药丸签到"
    # 插件描述
    plugin_desc = "药丸论坛签到。"
    # 插件图标
    plugin_icon = "invites.png"
    # 插件版本
    plugin_version = "1.5.2"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "invitessignin_"
    # 加载顺序
    plugin_order = 24
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _cookie = None
    _onlyonce = False
    _notify = False
    _history_days = None
    _username = None
    _user_password = None
    _retry_count = 2
    _retry_interval = 5

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._cookie = config.get("cookie")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._history_days = int(config.get("history_days") or 30)
            self._username = config.get("username")
            self._user_password = config.get("user_password")
            self._retry_count = int(config.get("retry_count") or 2)
            self._retry_interval = int(config.get("retry_interval") or 5)
        if self._onlyonce:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"药丸签到服务启动，立即运行一次")
            self._scheduler.add_job(func=self.__signin, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="药丸签到")
            # 关闭一次性开关
            self._onlyonce = False
            self.update_config({
                "onlyonce": False,
                "cron": self._cron,
                "enabled": self._enabled,
                "cookie": self._cookie,
                "notify": self._notify,
                "history_days": self._history_days,
                "username": self._username,
                "user_password": self._user_password,
                "retry_count": self._retry_count,
                "retry_interval": self._retry_interval
            })

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __get_new_session(self, flarum_remember: str) -> str:
        """获取新的session"""
        headers = {
            "Cookie": f"flarum_remember={flarum_remember}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
        }
        
        response = RequestUtils(headers=headers).get_res(url="https://invites.fun", allow_redirects=False)
        if not response:
            return None
            
        # 从Set-Cookie响应头中提取新的flarum_session
        cookies = response.headers.get('Set-Cookie', '')
        session_match = re.search(r'flarum_session=([^;]+)', cookies)
        
        if session_match:
            return session_match.group(1)
        return None

    def __get_remember_value(self, cookie: str) -> str:
        """从cookie字符串中提取flarum_remember值"""
        remember_match = re.search(r'flarum_remember=([^;]+)', cookie)
        if remember_match:
            return remember_match.group(1)
        return None

    def __login_with_credentials(self) -> dict:
        """使用用户名和密码登录药丸"""
        try:
            # 第一步：获取初始session和csrf token
            headers_get = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'accept-language': 'zh-CN,zh;q=0.9',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
            }
            
            response_get = RequestUtils(headers=headers_get).get_res('https://invites.fun/')
            if not response_get or response_get.status_code != 200:
                logger.error("获取初始session失败")
                return {"success": False, "error": "获取初始session失败"}
            
            # 从响应中提取flarum_session和csrf token
            flarum_session = response_get.cookies.get('flarum_session')
            csrf_token = response_get.headers.get('x-csrf-token')
            
            if not flarum_session:
                logger.error("未获取到flarum_session")
                return {"success": False, "error": "未获取到flarum_session"}
            
            if not csrf_token:
                logger.error("未获取到csrf token")
                return {"success": False, "error": "未获取到csrf token"}
            
            logger.info(f"获取到初始session: {flarum_session}")
            logger.info(f"获取到csrf token: {csrf_token}")
            
            # 第二步：执行登录
            cookies_login = {
                'flarum_session': flarum_session,
            }
            
            headers_login = {
                'accept': '*/*',
                'content-type': 'application/json; charset=UTF-8',
                'origin': 'https://invites.fun',
                'referer': 'https://invites.fun/',
                'x-csrf-token': csrf_token,
                'user-agent': headers_get['user-agent']
            }
            
            json_data_login = {
                'identification': self._username,
                'password': self._user_password,
                'remember': True,
            }
            
            login_response = RequestUtils(cookies=cookies_login, headers=headers_login).post_res(
                'https://invites.fun/login', 
                json=json_data_login
            )
            
            if not login_response or login_response.status_code != 200:
                logger.error(f"登录失败，状态码: {login_response.status_code if login_response else 'None'}")
                return {"success": False, "error": "登录失败"}
            
            # 从登录响应中提取新的cookies和用户信息
            flarum_remember = login_response.cookies.get('flarum_remember')
            flarum_session_new = login_response.cookies.get('flarum_session')
            csrf_token_new = login_response.headers.get('X-CSRF-Token') or csrf_token
            
            if not flarum_remember or not flarum_session_new:
                logger.error("登录后未获取到有效的cookies")
                return {"success": False, "error": "登录后未获取到有效的cookies"}
            
            # 提取用户ID
            user_id = None
            try:
                login_data = login_response.json()
                user_id = login_data.get('userId')
            except Exception as e:
                logger.error(f"解析登录响应失败: {e}")
                return {"success": False, "error": "解析登录响应失败"}
            
            if not user_id:
                logger.error("未获取到用户ID")
                return {"success": False, "error": "未获取到用户ID"}
            
            logger.info(f"登录成功，用户ID: {user_id}")
            
            return {
                "success": True,
                "flarum_remember": flarum_remember,
                "flarum_session": flarum_session_new,
                "csrf_token": csrf_token_new,
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"登录过程中发生异常: {e}")
            return {"success": False, "error": f"登录异常: {e}"}

    def __signin(self):
        """药丸签到"""
        for attempt in range(self._retry_count):
            logger.info(f"开始第 {attempt + 1} 次签到尝试")
            
            # 尝试使用cookie签到
            cookie_success = self.__signin_with_cookie()
            if cookie_success:
                logger.info(f"第 {attempt + 1} 次签到成功（Cookie方式）")
                return
            
            # Cookie签到失败，尝试使用用户名密码登录签到
            logger.info(f"第 {attempt + 1} 次Cookie签到失败，尝试用户名密码登录签到")
            login_success = self.__signin_with_login()
            if login_success:
                logger.info(f"第 {attempt + 1} 次签到成功（登录方式）")
                return
            
            # 两种方式都失败
            logger.warning(f"第 {attempt + 1} 次签到失败")
            
            # 如果不是最后一次尝试，等待重试间隔
            if attempt < self._retry_count - 1:
                logger.info(f"等待 {self._retry_interval} 分钟后进行第 {attempt + 2} 次重试")
                time.sleep(self._retry_interval * 60)  # 转换为秒
        
        # 所有重试都失败
        logger.error(f"所有 {self._retry_count} 次签到尝试都失败了")
        
        # 发送签到失败通知
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title='【💊药丸签到】任务完成',
                text='━━━━━━━━━━━━━━\n'
                     '✨ 状态：❌签到失败\n'
                     '━━━━━━━━━━━━━━\n'
                     f'❗ 原因：已重试{self._retry_count}次，Cookie失效且账号密码登录失败\n'
                     '━━━━━━━━━━━━━━\n'
                     f'🕐 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    def __signin_with_cookie(self) -> bool:
        """使用Cookie进行签到"""
        try:
            # 检查cookie是否配置
            if not self._cookie or not self._cookie.strip():
                logger.info("Cookie未配置，跳过Cookie签到")
                return False
            
            # 1. 从配置的cookie中提取flarum_remember值
            flarum_remember = self.__get_remember_value(self._cookie)
            if not flarum_remember:
                logger.error("无法从cookie中提取flarum_remember值")
                return False

            # 2. 使用flarum_remember获取新的session
            new_session = self.__get_new_session(flarum_remember)
            if not new_session:
                logger.error("获取新session失败")
                return False
                
            # 3. 构建新的cookie
            new_cookie = f"flarum_remember={flarum_remember}; flarum_session={new_session}"
            logger.info("成功刷新session")
            
            # 4. 使用新cookie获取csrfToken和userId
            res = RequestUtils(cookies=new_cookie).get_res(url="https://invites.fun")
            if not res or res.status_code != 200:
                logger.error("请求药丸错误")
                return False

            # 获取csrfToken
            pattern = r'"csrfToken":"(.*?)"'
            csrfToken = re.findall(pattern, res.text)
            if not csrfToken:
                logger.error("请求csrfToken失败")
                return False

            csrfToken = csrfToken[0]
            logger.info(f"获取csrfToken成功 {csrfToken}")

            # 获取userid
            pattern = r'"userId":(\d+)'
            match = re.search(pattern, res.text)

            if match:
                userId = match.group(1)
                logger.info(f"获取userid成功 {userId}")
            else:
                logger.error("未找到userId")
                return False
                
            # 执行签到
            return self.__perform_checkin(userId, new_cookie, csrfToken)
            
        except Exception as e:
            logger.error(f"Cookie签到过程中发生异常: {e}")
            return False

    def __signin_with_login(self) -> bool:
        """使用用户名密码登录进行签到"""
        try:
            # 检查用户名和密码是否配置
            if not self._username or not self._user_password:
                logger.error("用户名或密码未配置，无法使用登录签到")
                return False
            
            # 执行登录
            login_result = self.__login_with_credentials()
            if not login_result.get("success"):
                logger.error(f"登录失败: {login_result.get('error', '未知错误')}")
                return False
            
            # 构建cookie字符串
            cookie_str = f"flarum_remember={login_result['flarum_remember']}; flarum_session={login_result['flarum_session']}"
            
            # 执行签到
            return self.__perform_checkin(
                login_result['user_id'], 
                cookie_str, 
                login_result['csrf_token']
            )
            
        except Exception as e:
            logger.error(f"登录签到过程中发生异常: {e}")
            return False

    def __perform_checkin(self, user_id: str, cookie_str: str, csrf_token: str) -> bool:
        """执行实际的签到操作"""
        try:
            # 构建签到请求的headers
            headers = {
                'accept': '*/*',
                'content-type': 'application/json; charset=UTF-8',
                'origin': 'https://invites.fun',
                'referer': 'https://invites.fun/',
                'x-csrf-token': csrf_token,
                'x-http-method-override': 'PATCH',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
            }
            
            # 构建签到请求的JSON数据
            json_data = {
                'data': {
                    'type': 'users',
                    'attributes': {
                        'canCheckin': False,
                        'totalContinuousCheckIn': 2,
                    },
                    'id': str(user_id),
                },
            }
            
            # 构建cookies
            cookies = {
                'flarum_remember': cookie_str.split('flarum_remember=')[1].split(';')[0],
                'flarum_session': cookie_str.split('flarum_session=')[1].split(';')[0],
            }
            
            # 执行签到请求
            checkin_url = f'https://invites.fun/api/users/{user_id}'
            response = RequestUtils(cookies=cookies, headers=headers).post_res(
                checkin_url, 
                json=json_data
            )
            
            if not response or response.status_code != 200:
                logger.error(f"签到请求失败，状态码: {response.status_code if response else 'None'}")
                return False
            
            # 解析签到响应
            try:
                checkin_data = response.json()
                
                # 提取关键信息
                total_continuous_checkin = checkin_data['data']['attributes']['totalContinuousCheckIn']
                money = checkin_data['data']['attributes']['money']
                
                logger.info("药丸签到成功")
                
                # 发送通知 - 使用原有样式
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="【💊药丸签到】任务完成",
                        text="━━━━━━━━━━━━━━\n"
                             "✨ 状态：✅已签到\n"
                             "━━━━━━━━━━━━━━\n"
                             "📊 数据统计\n"
                             f"💊 剩余药丸：{money}\n"
                             f"📆 累计签到：{total_continuous_checkin}天\n"
                             "━━━━━━━━━━━━━━\n"
                             f"🕐 签到时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # 保存签到历史 - 兼容原有数据格式
                history = self.get_data('history') or []
                history.append({
                    "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                    "totalContinuousCheckIn": total_continuous_checkin,
                    "money": money
                })
                
                # 清理超过保留天数的历史记录
                thirty_days_ago = time.time() - int(self._history_days) * 24 * 60 * 60
                history = [record for record in history if
                           datetime.strptime(record["date"], '%Y-%m-%d %H:%M:%S').timestamp() >= thirty_days_ago]
                
                # 保存签到历史
                self.save_data(key="history", value=history)
                
                return True
                
            except Exception as e:
                logger.error(f"解析签到响应失败: {e}")
                logger.error(f"签到响应内容: {response.text if response else 'None'}")
                return False
                
        except Exception as e:
            logger.error(f"执行签到过程中发生异常: {e}")
            return False

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            return [{
                "id": "InvitesSignin",
                "name": "药丸签到服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__signin,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        version = getattr(settings, "VERSION_FLAG", "v1")
        cron_field_component = "VCronField" if version == "v2" else "VTextField"
        return [
            {
                'component': 'VForm',
                'content': [
                    # 基础设置卡片
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-0'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-cog'},
                                {'component': 'span', 'text': '基础设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件', 'color': 'primary'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'notify', 'label': '开启通知', 'color': 'info'}}]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即运行一次', 'color': 'success'}}]},
                                ]},
                            ]}
                        ]
                    },
                    # 登录设置卡片
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-pill'},
                                {'component': 'span', 'text': '账号设置'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'content': [
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'username',
                                            'label': '药丸用户名',
                                            'placeholder': '请输入用户名',
                                            'prepend-inner-icon': 'mdi-account',
                                            'autocomplete': 'new-username',
                                            'persistent-placeholder': True,
                                            'clearable': True
                                        }}
                                    ]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'user_password',
                                            'label': '药丸密码',
                                            'placeholder': '请输入药丸密码',
                                            'prepend-inner-icon': 'mdi-lock',
                                            'type': 'password',
                                            'autocomplete': 'new-password',
                                            'persistent-placeholder': True,
                                            'clearable': True
                                        }}
                                    ]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': cron_field_component, 'props': {
                                            'model': 'cron',
                                            'label': '签到周期',
                                            'placeholder': '0 9 * * *',
                                            'prepend-inner-icon': 'mdi-clock-outline'
                                        }}
                                    ]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'history_days',
                                            'label': '历史记录保留天数',
                                            'type': 'number',
                                            'placeholder': '默认保留30天',
                                            'prepend-inner-icon': 'mdi-calendar-range'
                                        }}
                                    ]}
                                ]},
                                {'component': 'VRow', 'content': [
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'cookie',
                                            'label': '药丸Cookie',
                                            'placeholder': '需要包含 flarum_remember 值',
                                            'prepend-inner-icon': 'mdi-cookie',
                                            'type': 'password',
                                            'autocomplete': 'new-cookie',
                                            'persistent-placeholder': True,
                                            'clearable': True
                                        }}
                                    ]},
                                    {'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'retry_count',
                                            'label': '失败重试次数',
                                            'placeholder': '默认2次',
                                            'prepend-inner-icon': 'mdi-refresh',
                                            'type': 'number',
                                            'persistent-placeholder': True,
                                            'clearable': True
                                        }}
                                    ]},{'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [
                                        {'component': 'VTextField', 'props': {
                                            'model': 'retry_interval',
                                            'label': '失败重试间隔(分钟)',
                                            'placeholder': '默认5分钟',
                                            'prepend-inner-icon': 'mdi-timer-outline',
                                            'type': 'number',
                                            'persistent-placeholder': True,
                                            'clearable': True
                                        }}
                                    ]}
                                ]}
                            ]}
                        ]
                    },
                    # 使用说明卡片
                    {
                        'component': 'VCard',
                        'props': {'class': 'mt-3'},
                        'content': [
                            {'component': 'VCardTitle', 'props': {'class': 'd-flex align-center'}, 'content': [
                                {'component': 'VIcon', 'props': {'color': 'info', 'class': 'mr-2'}, 'text': 'mdi-information'},
                                {'component': 'span', 'text': '使用说明'}
                            ]},
                            {'component': 'VDivider'},
                            {'component': 'VCardText', 'props': {'class': 'px-6 pb-6'}, 'content': [
                                {
                                    'component': 'VList',
                                    'props': {'lines': 'two', 'density': 'comfortable'},
                                    'content': [
                                        {
                                            'component': 'VListItem',
                                            'props': {'lines': 'two'},
                                            'content': [
                                                {'component': 'div', 'props': {'class': 'd-flex align-items-start'}, 'content': [
                                                    {'component': 'VIcon', 'props': {'color': 'primary', 'class': 'mt-1 mr-2'}, 'text': 'mdi-calendar-clock'},
                                                    {'component': 'div', 'props': {'class': 'text-subtitle-1 font-weight-regular mb-1', 'style': 'color: #444;'}, 'text': '签到周期说明'}
                                                ]},
                                                {'component': 'div', 'props': {'class': 'text-body-2 ml-8'}, 'text': '支持标准cron表达式，建议错开整点，避免服务器高峰。默认09:00签到。'}
                                            ]
                                        },
                                        {
                                            'component': 'VListItem',
                                            'props': {'lines': 'two'},
                                            'content': [
                                                {'component': 'div', 'props': {'class': 'd-flex align-items-start'}, 'content': [
                                                    {'component': 'VIcon', 'props': {'color': 'warning', 'class': 'mt-1 mr-2'}, 'text': 'mdi-cookie'},
                                                    {'component': 'div', 'props': {'class': 'text-subtitle-1 font-weight-regular mb-1', 'style': 'color: #444;'}, 'text': 'Cookie说明'}
                                                ]},
                                                {'component': 'div', 'props': {'class': 'text-body-2 ml-8'}, 'text': '需要包含flarum_remember值，登录获取ck：https://invites.fun，登录时勾选记住我的登录状态。'}
                                            ]
                                        },
                                        {
                                            'component': 'VListItem',
                                            'props': {'lines': 'two'},
                                            'content': [
                                                {'component': 'div', 'props': {'class': 'd-flex align-items-start'}, 'content': [
                                                    {'component': 'VIcon', 'props': {'color': 'success', 'class': 'mt-1 mr-2'}, 'text': 'mdi-check-circle'},
                                                    {'component': 'div', 'props': {'class': 'text-subtitle-1 font-weight-regular mb-1', 'style': 'color: #444;'}, 'text': '功能特点'}
                                                ]},
                                                {'component': 'div', 'props': {'class': 'text-body-2 ml-8'}, 'text': '优先使用填写Cookie进行签到，自动刷新session，如果Cookie签到失败或未设置则尝试进行登陆签到，支持签到历史记录查看。'}
                                            ]
                                        }
                                    ]
                                }
                            ]}
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": False,
            "cookie": "",
            "history_days": 30,
            "cron": "0 9 * * *",
            "username": "",
            "user_password": "",
            "retry_count": 2,
            "retry_interval": 5
        }

    def get_page(self) -> List[dict]:
        # 查询同步详情
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'VCard',
                    'props': {
                        'variant': 'flat',
                        'class': 'mb-4'
                    },
                    'content': [
                        {
                            'component': 'VCardItem',
                            'props': {
                                'class': 'pa-6'
                            },
                            'content': [
                                {
                                    'component': 'VCardTitle',
                                    'props': {
                                        'class': 'd-flex align-center text-h6'
                                    },
                                    'content': [
                                        {
                                            'component': 'VIcon',
                                            'props': {
                                                'color': 'primary',
                                                'class': 'mr-3',
                                                'size': 'default'
                                            },
                                            'text': 'mdi-database-remove'
                                        },
                                        {
                                            'component': 'span',
                                            'text': '暂无签到记录'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]

        if not isinstance(historys, list):
            historys = [historys]

        # 按照签到时间倒序
        historys = sorted(historys, key=lambda x: x.get("date") or 0, reverse=True)

        # 取前N条记录
        max_count = self._history_days or 30
        historys = historys[:max_count]

        return [
            {
                'component': 'VCard',
                'props': {
                    'variant': 'flat',
                    'class': 'mb-4 elevation-2',
                    'style': 'border-radius: 16px;'
                },
                'content': [
                    {
                        'component': 'VCardItem',
                        'props': {
                            'class': 'pa-6'
                        },
                        'content': [
                            {
                                'component': 'VCardTitle',
                                'props': {
                                    'class': 'd-flex align-center text-h6'
                                },
                                'content': [
                                    {
                                        'component': 'VIcon',
                                        'props': {
                                            'color': 'primary',
                                            'class': 'mr-3',
                                            'size': 'default'
                                        },
                                        'text': 'mdi-history'
                                    },
                                    {
                                        'component': 'span',
                                        'text': '签到历史记录'
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-6'
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True,
                                    'density': 'comfortable',
                                    'class': 'rounded-lg'
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'content': [
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-center text-body-1 font-weight-bold'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'info', 'size': 'small', 'class': 'mr-1'}, 'text': 'mdi-clock-time-four-outline'},
                                                            {'component': 'span', 'text': '签到时间'}
                                                        ]
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-center text-body-1 font-weight-bold'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'success', 'size': 'small', 'class': 'mr-1'}, 'text': 'mdi-check-circle'},
                                                            {'component': 'span', 'text': '签到状态'}
                                                        ]
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-center text-body-1 font-weight-bold'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'info', 'size': 'small', 'class': 'mr-1'}, 'text': 'mdi-counter'},
                                                            {'component': 'span', 'text': '签到天数'}
                                                        ]
                                                    },
                                                    {
                                                        'component': 'th',
                                                        'props': {
                                                            'class': 'text-center text-body-1 font-weight-bold'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'warning', 'size': 'small', 'class': 'mr-1'}, 'text': 'mdi-pill'},
                                                            {'component': 'span', 'text': '剩余药丸'}
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': [
                                            {
                                                'component': 'tr',
                                                'props': {
                                                    'class': 'text-sm'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'td',
                                                        'props': {
                                                            'class': 'text-center text-high-emphasis'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'info', 'size': 'x-small', 'class': 'mr-1'}, 'text': 'mdi-clock-time-four-outline'},
                                                            {'component': 'span', 'text': history.get("date", "")}
                                                        ]
                                                    },
                                                    {
                                                        'component': 'td',
                                                        'props': {
                                                            'class': 'text-center text-high-emphasis'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VChip',
                                                                'props': {
                                                                    'color': 'success',
                                                                    'size': 'small',
                                                                    'variant': 'tonal',
                                                                },
                                                                'content': [
                                                                    {
                                                                        'component': 'VIcon',
                                                                        'props': {
                                                                            'size': 'small',
                                                                            'start': True
                                                                        },
                                                                        'text': 'mdi-check-circle'
                                                                    },
                                                                    {
                                                                        'component': 'span',
                                                                        'text': '已签到'
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    },
                                                    {
                                                        'component': 'td',
                                                        'props': {
                                                            'class': 'text-center text-high-emphasis'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'info', 'size': 'x-small', 'class': 'mr-1'}, 'text': 'mdi-counter'},
                                                            {'component': 'span', 'text': f"{history.get('totalContinuousCheckIn', 0)}天"}
                                                        ]
                                                    },
                                                    {
                                                        'component': 'td',
                                                        'props': {
                                                            'class': 'text-center text-high-emphasis'
                                                        },
                                                        'content': [
                                                            {'component': 'VIcon', 'props': {'color': 'warning', 'size': 'x-small', 'class': 'mr-1'}, 'text': 'mdi-pill'},
                                                            {'component': 'span', 'text': f"{history.get('money', 0)}个"}
                                                        ]
                                                    }
                                                ]
                                            } for history in historys
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'text-caption text-grey mt-2',
                                    'style': 'background: #f5f5f7; border-radius: 8px; padding: 6px 12px; display: inline-block;'
                                },
                                'content': [
                                    {'component': 'VIcon', 'props': {'size': 'x-small', 'class': 'mr-1'}, 'text': 'mdi-format-list-bulleted'},
                                    {'component': 'span', 'text': f'共显示 {len(historys)} 条签到记录'}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        """退出插件"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
