import io
import random
import re
import time
import base64
from datetime import datetime, timedelta
from typing import Optional
from typing import Tuple, List, Dict, Any

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.cookiecloud import CookieCloudHelper
from app.log import logger
from app.plugins import _PluginBase
from app.plugins.dynamicwechat.update_help import PyCookieCloud
from app.schemas.types import EventType, NotificationType


class DynamicWeChat(_PluginBase):
    # 插件名称
    plugin_name = "修改企业微信可信IP"
    # 插件描述
    plugin_desc = "优先使用cookie，可本地扫码刷新Cookie，当填写两个第三方token时手机微信可以更新cookie。"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本
    plugin_version = "1.4.0"
    # 插件作者
    plugin_author = "RamenRa"
    # 作者主页
    author_url = "https://github.com/RamenRa/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "dynamicwechat_"
    # 加载顺序
    plugin_order = 47
    # 可使用的用户级别
    auth_level = 2

    # ------------------------------------------私有属性------------------------------------------
    _enabled = False  # 开关
    _cron = None
    _onlyonce = False
    # IP更改成功状态
    _ip_changed = False
    # 强制更改IP
    _forced_update = False
    # CloudCookie服务器
    _cc_server = None
    # 本地扫码开关
    _local_scan = False

    # 匹配ip地址的正则
    _ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    # 获取ip地址的网址列表
    _ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip", "https://ip.3322.net", "https://4.ipw.cn"]
    # 当前ip地址
    _current_ip_address = '0.0.0.0'
    # 企业微信登录
    _wechatUrl = 'https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome'
    # 检测间隔时间,默认10分钟
    _refresh_cron = '*/20 * * * *'
    # 输入的企业应用id
    _input_id_list = ''
    # helloimg的token
    _helloimg_s_token = ""
    # pushplus的token
    _pushplus_token = ""
    # 二维码
    _qr_code_image = None
    text = ""
    # 手机验证码
    _verification_code = ''
    # 过期时间
    _future_timestamp = 0

    # cookie有效检测
    _cookie_valid = True
    # cookie存活时间
    _cookie_lifetime = 0
    # 使用CookieCloud开关
    _use_cookiecloud = True
    # 登录cookie
    _cookie_header = ""
    _server = f'http://localhost:{settings.NGINX_PORT}/cookiecloud'

    _cookiecloud = CookieCloudHelper()
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 清空配置
        self._helloimg_s_token = ''
        self._pushplus_token = ''
        self._ip_changed = True
        self._forced_update = False
        self._use_cookiecloud = True
        self._local_scan = False
        self._input_id_list = ''
        self._cookie_header = ""
        self._current_ip_address = self.get_ip_from_url(self._ip_urls[0])
        self._cookie_lifetime = PyCookieCloud.load_cookie_lifetime()
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._input_id_list = config.get("input_id_list")
            self._current_ip_address = config.get("current_ip_address")
            self._pushplus_token = config.get("pushplus_token")
            self._helloimg_s_token = config.get("helloimg_s_token")
            self._forced_update = config.get("forced_update")
            self._local_scan = config.get("local_scan")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie_header = config.get("cookie_header")
            self._ip_changed = config.get("ip_changed")

        # 停止现有任务
        self.stop_service()
        if (self._enabled or self._onlyonce) and self._input_id_list:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 运行一次定时服务
            if self._onlyonce:
                logger.info("立即检测公网IP")
                self._scheduler.add_job(func=self.check, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="检测公网IP")  # 添加任务
                # 关闭一次性开关
                self._onlyonce = False

            if self._forced_update:
                self._scheduler.add_job(func=self.forced_change, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="强制更新公网IP")  # 添加任务
                self._forced_update = False

            if self._local_scan:
                self._scheduler.add_job(func=self.local_scanning, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="本地扫码登陆")  # 添加任务
                self._local_scan = False

            # 固定半小时周期请求一次地址,防止cookie失效
            try:
                self._scheduler.add_job(func=self.refresh_cookie,
                                        trigger=CronTrigger.from_crontab(self._refresh_cron),
                                        name="延续企业微信cookie有效时间")
            except Exception as err:
                logger.error(f"定时任务配置错误：{err}")
                self.systemmessage.put(f"执行周期配置错误：{err}")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
        self.__update_config()

    @eventmanager.register(EventType.PluginAction)
    def forced_change(self, event: Event = None):
        """
        强制修改IP
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        self.ChangeIP()
        self.__update_config()
        logger.info("----------------------本次任务结束----------------------")

    @eventmanager.register(EventType.PluginAction)
    def local_scanning(self, event: Event = None):
        """
        本地扫码
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--lang=zh-CN'])
                context = browser.new_context()
                page = context.new_page()
                page.goto(self._wechatUrl)
                time.sleep(3)  # 页面加载等待时间

                if self.find_qrc(page):
                    current_time = datetime.now()
                    future_time = current_time + timedelta(seconds=110)
                    self._future_timestamp = int(future_time.timestamp())
                    logger.info("请重新进入插件面板扫码! 每20秒检查登录状态，最大尝试5次")
                    max_attempts = 5
                    attempt = 0
                    while attempt < max_attempts:
                        attempt += 1
                        # logger.info(f"第 {attempt} 次检查登录状态...")
                        time.sleep(20)  # 每20秒检查一次
                        if self.check_login_status(page, task='local_scanning'):
                            self._update_cookie(page, context)  # 刷新cookie
                            self.click_app_management_buttons(page)
                            break
                    else:
                        logger.info("用户可能没有扫码或登录失败")
                else:
                    logger.error("未找到二维码，任务结束")
                logger.info("----------------------本次任务结束----------------------")
                browser.close()
        except Exception as e:
            logger.error(f"本地扫码任务: 本地扫码失败: {e}")

    @eventmanager.register(EventType.PluginAction)
    def check(self, event: Event = None):
        """
        检测函数
        """
        if not self._enabled:
            logger.error("插件未开启")
            return

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return

        logger.info("开始检测公网IP")
        if self.CheckIP():
            self.ChangeIP()
            self.__update_config()

        # logger.info("检测公网IP完毕")
        logger.info("----------------------本次任务结束----------------------")
        # if event:
        #     self.post_message(channel=event.event_data.get("channel"),
        #                       title="检测公网IP完毕",
        #                       userid=event.event_data.get("user"))

    def CheckIP(self):
        retry_urls = random.sample(self._ip_urls, len(self._ip_urls))
        ip_address = None

        for url in retry_urls:
            ip_address = self.get_ip_from_url(url)
            if ip_address != "获取IP失败" and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
                break

        # 如果所有 URL 请求失败
        if ip_address == "获取IP失败" or not ip_address:
            logger.error("获取IP失败 不操作IP")
            return False

        if self._forced_update:
            logger.info("强制更新IP")
            self._current_ip_address = ip_address
            return True
        elif not self._ip_changed:  # 上次修改IP失败
            logger.info("上次IP修改IP没有成功 继续尝试修改IP")
            self._current_ip_address = ip_address
            return True

        # 检查 IP 是否变化
        if ip_address != self._current_ip_address:
            logger.info("检测到IP变化")
            self._current_ip_address = ip_address
            # self._ip_changed = False
            return True
        else:
            return False

    def try_connect_cc(self):
        if self._use_cookiecloud:
            if settings.COOKIECLOUD_KEY and settings.COOKIECLOUD_PASSWORD:  # 使用设置里的cookieCloud
                if settings.COOKIECLOUD_ENABLE_LOCAL:
                    self._cc_server = PyCookieCloud(url=self._server, uuid=settings.COOKIECLOUD_KEY,
                                                    password=settings.COOKIECLOUD_PASSWORD)
                    logger.info("使用内建CookieCloud服务器")
                else:  # 使用设置里的cookieCloud
                    self._cc_server = PyCookieCloud(url=settings.COOKIECLOUD_HOST, uuid=settings.COOKIECLOUD_KEY,
                                                    password=settings.COOKIECLOUD_PASSWORD)
                    logger.info("使用自定义CookieCloud服务器")
                if not self._cc_server.check_connection():
                    self._cc_server = None
                    logger.error("没有可用的CookieCloud服务器")
            else:  # 未设置cookieCloud
                self._cc_server = None
                logger.error("没有配置CookieCloud的用户KEY和PASSWORD")

    def get_ip_from_url(self, url):
        try:
            # 发送 GET 请求
            response = requests.get(url)
            # 检查响应状态码是否为 200
            if response.status_code == 200:
                # 解析响应 JSON 数据并获取 IP 地址
                ip_address = re.search(self._ip_pattern, response.text)
                if ip_address:
                    return ip_address.group()
                else:
                    return "获取IP失败"
            else:
                return "获取IP失败"
        except Exception as e:
            if "104" in str(e):
                pass
            else:
                logger.warning(f"{url} 获取IP失败,Error: {e}")

    def find_qrc(self, page):
        # 查找 iframe 元素并切换到它
        try:
            page.wait_for_selector("iframe", timeout=5000)  # 等待 iframe 加载
            iframe_element = page.query_selector("iframe")
            frame = iframe_element.content_frame()

            # 查找二维码图片元素
            qr_code_element = frame.query_selector("img.qrcode_login_img")
            if qr_code_element:
                # logger.info("找到二维码图片元素")
                # 保存二维码图片
                qr_code_url = qr_code_element.get_attribute('src')
                if qr_code_url.startswith("/"):
                    qr_code_url = "https://work.weixin.qq.com" + qr_code_url  # 补全二维码 URL

                qr_code_data = requests.get(qr_code_url).content
                self._qr_code_image = io.BytesIO(qr_code_data)
                return True
            else:
                logger.warning("未找到二维码")
                return False
        except Exception as e:
            logger.debug(str(e))
            return False

    def send_pushplus_message(self, title, content):
        pushplus_url = f"http://www.pushplus.plus/send/{self._pushplus_token}"
        pushplus_data = {
            "title": title,
            "content": content,
            "template": "html"
        }
        response = requests.post(pushplus_url, json=pushplus_data)


    def ChangeIP(self):
        logger.info("开始请求企业微信管理更改可信IP")
        try:
            with sync_playwright() as p:
                # 启动 Chromium 浏览器并设置语言为中文
                browser = p.chromium.launch(headless=True, args=['--lang=zh-CN'])
                context = browser.new_context()
                # ----------cookie addd-----------------
                cookie = self.get_cookie()
                if cookie:
                    context.add_cookies(cookie)
                # ----------cookie END-----------------
                page = context.new_page()
                page.goto(self._wechatUrl)
                time.sleep(3)
                if self.find_qrc(page):
                    if self._pushplus_token and self._helloimg_s_token:
                        img_src, refuse_time = self.upload_image(self._qr_code_image)
                        self.send_pushplus_message(refuse_time, f"企业微信登录二维码<br/><img src='{img_src}' />")
                        # if img_src:
                        #     self.post_message(
                        #         mtype=NotificationType.Plugin,
                        #         title="企业微信登录二维码",
                        #         text=refuse_time,
                        #         image=img_src
                        #     )
                        logger.info("二维码已经发送，等待用户 90 秒内扫码登录")
                        # logger.info("如收到短信验证码请以？结束，发送到<企业微信应用> 如： 110301？")
                        time.sleep(90)  # 等待用户扫码
                        login_status = self.check_login_status(page, "")
                        if login_status:
                            self._update_cookie(page, context)  # 刷新cookie
                            self.click_app_management_buttons(page)
                        else:
                            self._ip_changed = False
                    else:
                        logger.info("cookie失效，请重新上传或者配置pushplus_token和helloimg_s_token。")
                else:  # 如果直接进入企业微信
                    logger.info("尝试cookie登录")
                    # ----------cookie addd-----------------
                    login_status = self.check_login_status(page, "")
                    if login_status:
                        self.click_app_management_buttons(page)
                    else:
                        # ----------cookie END-----------------
                        self._ip_changed = False
                        return
                browser.close()

        except Exception as e:
            logger.error(f"更改可信IP失败: {e}")
        finally:
            pass

    def _update_cookie(self, page, context):
        self._future_timestamp = 0  # 标记二维码失效
        PyCookieCloud.save_cookie_lifetime(0)  # 重置cookie存活时间
        if self._use_cookiecloud:
            if not self._cc_server:  # 连接失败返回 False
                self.try_connect_cc()  # 再尝试一次连接
                if self._cc_server is None:
                    return
            logger.info("使用二维码登录成功，开始刷新cookie")
            try:
                if self._cc_server.check_connection():
                    current_url = page.url
                    current_cookies = context.cookies(current_url)  # 通过 context 获取 cookies
                    if current_cookies is None:
                        logger.error("无法获取当前 cookies")
                        return

                    formatted_cookies = {}
                    for cookie in current_cookies:
                        domain = cookie.get('domain')  # 使用 get() 方法避免 KeyError
                        if domain is None:
                            continue  # 跳过没有 domain 的 cookie

                        if domain not in formatted_cookies:
                            formatted_cookies[domain] = []
                        formatted_cookies[domain].append(cookie)
                    flag = self._cc_server.update_cookie({'cookie_data': formatted_cookies})
                    if flag:
                        logger.info("更新 CookieCloud 成功")
                    else:
                        logger.error("更新 CookieCloud 失败")
                else:
                    logger.error("连接 CookieCloud 失败", self._server)
            except Exception as e:
                logger.error(
                    f"更新 cookie 发生错误: {e}")
        else:
            logger.error("CookieCloud没有启用或配置错误, 不刷新cookie")

    def get_cookie(self):  # 只有从CookieCloud获取cookie成功才返回True
        try:
            cookie_header = ''
            if self._use_cookiecloud:
                cookies, msg = self._cookiecloud.download()
                if not cookies:  # CookieCloud获取cookie失败
                    logger.error(f"CookieCloud获取cookie失败,失败原因：{msg}")
                    return
                    # cookie_header = self._cookie_header
                else:
                    for domain, cookie in cookies.items():
                        if domain == ".work.weixin.qq.com":
                            cookie_header = cookie
                            break
                    if cookie_header == '':
                        cookie_header = self._cookie_header
            else:  # 不使用CookieCloud
                return
            cookie = self.parse_cookie_header(cookie_header)
            return cookie
        except Exception as e:
            logger.error(f"从CookieCloud获取cookie错误，错误原因:{e}")
            # logger.info("尝试推送登录二维码")
            return

    @staticmethod
    def parse_cookie_header(cookie_header):
        cookies = []
        for cookie in cookie_header.split(';'):
            name, value = cookie.strip().split('=', 1)
            cookies.append({
                'name': name,
                'value': value,
                'domain': '.work.weixin.qq.com',
                'path': '/'
            })
        return cookies

    def refresh_cookie(self):  # 保活
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--lang=zh-CN'])
                context = browser.new_context()
                cookie = self.get_cookie()
                if cookie:
                    context.add_cookies(cookie)
                page = context.new_page()
                page.goto(self._wechatUrl)
                time.sleep(3)
                if not self.check_login_status(page, task='refresh_cookie'):
                    self._cookie_valid = False
                    logger.info("cookie已失效，下次IP变动推送二维码")
                else:
                    PyCookieCloud.increase_cookie_lifetime(1200)
                    self._cookie_lifetime = PyCookieCloud.load_cookie_lifetime()
                browser.close()
        except Exception as e:
            logger.error(f"cookie校验失败:{e}")

    #
    def check_login_status(self, page, task):
        # 等待页面加载
        time.sleep(3)
        # 检查是否需要进行短信验证
        if task != 'refresh_cookie':
            logger.info("检查登录状态...")
        try:
            # 先检查登录成功后的页面状态
            success_element = page.wait_for_selector('#check_corp_info', timeout=5000)  # 检查登录成功的元素
            if success_element:
                if task != 'refresh_cookie':
                    logger.info("登录成功！")
                return True
        except Exception as e:
            logger.debug(str(e))
            pass

        try:
            # 在这里使用更安全的方式来检查元素是否存在
            captcha_panel = page.wait_for_selector('.receive_captcha_panel', timeout=5000)  # 检查验证码面板
            if captcha_panel:  # 出现了短信验证界面
                if task == 'local_scanning':
                    time.sleep(6)
                else:
                    logger.info("等待30秒，请将短信验证码请以'？'结束，发送到<企业微信应用> 如： 110301？")
                    time.sleep(30)  # 多等30秒
                if self._verification_code:
                    # logger.info("输入验证码：" + self._verification_code)
                    for digit in self._verification_code:
                        page.keyboard.press(digit)
                        time.sleep(0.3)  # 每个数字之间添加少量间隔以确保输入顺利
                    confirm_button = page.wait_for_selector('.confirm_btn', timeout=5000)  # 获取确认按钮
                    confirm_button.click()  # 点击确认
                    time.sleep(3)  # 等待处理
                    # 等待登录成功的元素出现
                    success_element = page.wait_for_selector('#check_corp_info', timeout=5000)
                    if success_element:
                        logger.info("验证码登录成功！")
                        return True
                else:
                    logger.error("未收到短信验证码")
                    return False
        except Exception as e:
            # logger.debug(str(e))  # 基于bug运行，请不要将错误输出到日志
            # try:  # 没有登录成功，也没有短信验证码
            if self.find_qrc(page) and not task == 'refresh_cookie' and not task == 'local_scanning':  # 延长任务找到的二维码不会被发送，所以不算用户没有扫码
                logger.warning(f"用户没有扫描二维码")
                return False

    def click_app_management_buttons(self, page):
        bash_url = "https://work.weixin.qq.com/wework_admin/frame#apps/modApiApp/"
        # 按钮的选择器和名称
        buttons = [
            # ("//span[@class='frame_nav_item_title' and text()='应用管理']", "应用管理"),
            # ("//div[@class='app_index_item_title ' and contains(text(), 'MoviePilot')]", "MoviePilot"),
            (
            "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
            "配置")
        ]
        if self._input_id_list:
            id_list = self._input_id_list.split(",")
            app_urls = [f"{bash_url}{app_id.strip()}" for app_id in id_list]
            for app_url in app_urls:
                page.goto(app_url)  # 打开应用详情页
                app_id = app_url.split("/")[-1]
                time.sleep(2)
                # 依次点击每个按钮
                for xpath, name in buttons:
                    # 等待按钮出现并可点击
                    try:
                        button = page.wait_for_selector(xpath, timeout=5000)  # 等待按钮可点击
                        button.click()
                        # logger.info(f"已点击 '{name}' 按钮")
                        page.wait_for_selector('textarea.js_ipConfig_textarea', timeout=5000)
                        # logger.info(f"已找到文本框")
                        input_area = page.locator('textarea.js_ipConfig_textarea')
                        confirm = page.locator('.js_ipConfig_confirmBtn')
                        input_area.fill(self._current_ip_address)  # 填充 IP 地址
                        confirm.click()  # 点击确认按钮
                        time.sleep(3)  # 等待处理
                        self._ip_changed = True
                    except Exception as e:
                        logger.error(f"未能找打开{app_url}或点击 '{name}' 按钮异常: {e}")
                        self._ip_changed = False
                        if "disabled" in str(e):
                            logger.info(f"应用{app_id} 已被禁用,可能是没有设置接收api")
                if self._ip_changed:
                    logger.info(f"应用: {app_id} 输入IP：" + self._current_ip_address)
                    ip_parts = self._current_ip_address.split('.')
                    masked_ip = f"{ip_parts[0]}.{len(ip_parts[1]) * '*'}.{len(ip_parts[2]) * '*'}.{ip_parts[3]}"
                    self.post_message(
                        mtype=NotificationType.Plugin,
                        title="更新可信IP成功",
                        text='应用: ' + app_id + ' 输入IP：' + masked_ip,
                        # image=img_src
                    )
            return
        else:
            logger.error("未找到应用id，修改IP失败")
            return

    def upload_image(self, file_obj, permission=1, strategy_id=1, album_id=1):
        """
        上传图片到 helloimg 图床，支持传入文件路径或 BytesIO 对象。

        :param file_obj: 文件对象，可以是路径 (str) 或 BytesIO 对象
        :param permission: 上传图片的权限设置，默认 1
        :param strategy_id: 上传策略 ID，默认 1
        :param album_id: 相册 ID，默认 1
        :return: 上传成功返回图片链接，失败返回 None
        """
        helloimg_token = "Bearer " + self._helloimg_s_token
        helloimg_url = "https://www.helloimg.com/api/v1/upload"
        headers = {
            "Authorization": helloimg_token,
            "Accept": "application/json",
        }

        # 构造上传的文件，支持传入 BytesIO 或文件路径
        if isinstance(file_obj, io.BytesIO):
            # 如果是 BytesIO 对象，直接使用
            files = {
                "file": ('qr_code.png', file_obj, 'image/png')
            }
        else:
            # 如果是文件路径，打开文件进行读取
            files = {
                "file": open(file_obj, "rb")
            }

        expired_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        helloimg_data = {
            "token": "你的临时上传 Token",  # 确保这里的 token 是有效的
            "permission": permission,
            "strategy_id": strategy_id,
            "album_id": album_id,
            "expired_at": expired_at
        }
        refuse_time = (datetime.now() + timedelta(seconds=110)).strftime("%Y-%m-%d %H:%M:%S")

        # 发送上传请求
        response = requests.post(helloimg_url, headers=headers, files=files, data=helloimg_data)

        # 检查响应内容是否符合预期
        response_data = None
        try:
            response_data = response.json()
            if not response_data['status']:
                if response_data['message'] == "Unauthenticated.":
                    logger.error("Token失效，无法上传图片。请检查你的上传Token。")
                    logger.info(f"使用的Token: {helloimg_token}")
                    # self._ip_changed = False
                    return
                else:
                    logger.error(f"上传到图床失败: {response_data['message']}")
                self._ip_changed = False
                return

            img_src = response_data['data']['links']['html']
            return img_src.split('"')[1], refuse_time  # 提取 img src
        except KeyError as e:
            logger.error(f"上传图片时解析响应失败: {e}, 响应内容: {response_data}")
            self._ip_changed = False
            return

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            # "wechatUrl": self._wechatUrl,
            "current_ip_address": self._current_ip_address,
            "ip_changed": self._ip_changed,
            "forced_update": self._forced_update,
            "local_scan": self._local_scan,
            "helloimg_s_token": self._helloimg_s_token,
            "pushplus_token": self._pushplus_token,
            "input_id_list": self._input_id_list,
            "cookie_header": self._cookie_header,
            "use_cookiecloud": self._use_cookiecloud,
        })

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，只保留必要的配置项，并添加 token 配置。
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
                                            'model': 'onlyonce',
                                            'label': '立即检测一次',
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
                                            'model': 'forced_update',
                                            'label': '强制更新IP',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    # 添加 "使用CookieCloud获取cookie" 开关按钮
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
                                            'model': 'use_cookiecloud',
                                            'label': '使用CookieCloud',
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
                                            'model': 'local_scan',
                                            'label': '本地扫码修改IP',
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
                                            'model': 'cron',
                                            'label': '检测周期',
                                            'placeholder': '0 * * * *'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'input_id_list',
                                            'label': '应用ID',
                                            'rows': 1,
                                            'placeholder': '输入应用ID，多个ID用英文逗号分隔。在企业微信应用页面URL末尾获取'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'pushplus_token',
                                            'label': 'pushplus_token',
                                            'rows': 1,
                                            'placeholder': '[可选] 请输入 pushplus_token'
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
                                            'model': 'helloimg_s_token',
                                            'label': 'helloimg_s_token',
                                            'rows': 1,
                                            'placeholder': '[可选] 请输入 helloimg_token'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '使用内建CookieCloud 或 自定义 或 填写两个token 至少三选一。任何扫码操作都会更新Cookie！'
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
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'text': '优先使用cookie，当IP变动 且 cookie失效 且 填写两个token才会调用API推送登录二维码。',
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
            "cron": "",
            "onlyonce": False,
            "forceUpdate": False,
            "use_cookiecloud": True,
            "use_local_qr": False,  # 默认关闭本地扫码
            "cookie_header": "",
            "pushplus_token": "",
            "helloimg_token": "",
            "input_id_list": "",
        }

    def get_page(self) -> List[dict]:
        # 获取当前时间戳
        current_time = datetime.now().timestamp()

        # 判断二维码是否过期
        if current_time > self._future_timestamp:
            vaild_text = "二维码已过期"
            color = "#ff0000"
            self._qr_code_image = None
        else:
            # 二维码有效，格式化过期时间为 年-月-日 时:分:秒
            expiration_time = datetime.fromtimestamp(self._future_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            vaild_text = f"二维码有效，过期时间: {expiration_time}"
            color = "#32CD32"

        # 如果self._qr_code_image为None，返回提示信息
        if self._qr_code_image is None:
            img_component = {
                "component": "div",
                "text": "登录二维码都会在此展示，二维码有6秒延时，过期时间仅对应‘本地扫码功能’",
                "props": {
                    "style": {
                        "fontSize": "22px",
                        "color": "#ff0000",
                        "textAlign": "center",
                        "margin": "20px"
                    }
                }
            }
        else:
            # 获取二维码图片数据
            qr_image_data = self._qr_code_image.getvalue()
            # 将图片数据转为 base64 编码
            base64_image = base64.b64encode(qr_image_data).decode('utf-8')
            img_src = f"data:image/png;base64,{base64_image}"

            # 生成图片组件
            img_component = {
                "component": "img",
                "props": {
                    "src": img_src,
                    "style": {
                        "width": "auto",
                        "height": "auto",
                        "maxWidth": "100%",
                        "maxHeight": "100%",
                        "display": "block",
                        "margin": "0 auto"
                    }
                }
            }

        # 计算 cookie_lifetime 的天数、小时数和分钟数
        cookie_lifetime_days = self._cookie_lifetime // 86400  # 一天的秒数为 86400
        cookie_lifetime_hours = (self._cookie_lifetime % 86400) // 3600  # 计算小时数
        cookie_lifetime_minutes = (self._cookie_lifetime % 3600) // 60  # 计算分钟数
        if self._cookie_valid:
            bg_color = "#40bb45"
        else:
            bg_color = "#ff0000"
        cookie_lifetime_text = (
            f"Cookie 已使用: {cookie_lifetime_days}天{cookie_lifetime_hours}小时{cookie_lifetime_minutes}分钟"
        )
        cookie_lifetime_component = {
            "component": "div",
            "text": cookie_lifetime_text,
            "props": {
                "style": {
                    "fontSize": "18px",
                    "color": "#ffffff",  # 白色字体
                    "backgroundColor": bg_color,
                    "padding": "10px",
                    "borderRadius": "5px",
                    "textAlign": "center",
                    "marginTop": "10px",
                    "display": "inline-block"
                }
            }
        }

        # 页面内容，显示二维码状态信息和二维码图片或提示信息
        base_content = [
            {
                "component": "div",
                "props": {
                    "style": {
                        "textAlign": "center"
                    }
                },
                "content": [
                    {
                        "component": "div",
                        "text": vaild_text,
                        "props": {
                            "style": {
                                "fontSize": "22px",
                                "fontWeight": "bold",
                                "color": "#ffffff",
                                "backgroundColor": color,
                                "padding": "8px",
                                "borderRadius": "5px",
                                "display": "inline-block",
                                "textAlign": "center",
                                "marginBottom": "10px"
                            }
                        }
                    },
                    {
                        "component": "div",
                        "content": [cookie_lifetime_component],
                        "props": {
                            "style": {
                                "textAlign": "center",
                                "marginBottom": "10px"
                            }
                        }
                    },
                    img_component  # 二维码图片或提示信息
                ]
            }
        ]

        return base_content

    @eventmanager.register(EventType.PluginAction)
    def push_qr_code(self, event: Event = None):
        """
        立即发送二维码
        """
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "push_qrcode":
                return
        try:
            with sync_playwright() as p:
                # 启动 Chromium 浏览器并设置语言为中文
                browser = p.chromium.launch(headless=True, args=['--lang=zh-CN'])
                context = browser.new_context()
                page = context.new_page()
                page.goto(self._wechatUrl)
                time.sleep(3)
                if self.find_qrc(page):
                    if self._pushplus_token and self._helloimg_s_token:
                        img_src, refuse_time = self.upload_image(self._qr_code_image)
                        self.send_pushplus_message(refuse_time, f"企业微信登录二维码<br/><img src='{img_src}' />")
                        logger.info("远程推送任务: 二维码已经发送，等待用户 90 秒内扫码登录")
                        # logger.info("远程推送任务: 如收到短信验证码请以？结束，发送到<企业微信应用> 如： 110301？")
                        time.sleep(90)
                        login_status = self.check_login_status(page, 'push_qr_code')
                        if login_status:
                            self._update_cookie(page, context)  # 刷新cookie
                            # logger.info("远程推送任务: 没有可用的CookieCloud服务器，只修改可信IP")
                            self.click_app_management_buttons(page)
                    else:
                        logger.warning("远程推送任务: 未配置pushplus_token和helloimg_s_token")
                else:
                    logger.warning("远程推送任务: 未找到二维码")
        except Exception as e:
            logger.error(f"远程推送任务: 推送二维码失败: {e}")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/push_qr",
                "event": EventType.PluginAction,
                "desc": "立即推送登录二维码到pushplus",
                "category": "",
                "data": {
                    "action": "push_qrcode"
                }
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    @eventmanager.register(EventType.UserMessage)
    def talk(self, event: Event):
        """
        监听用户消息
        """
        if not self._enabled:
            return
        self.text = event.event_data.get("text")
        if self.text[:6].isdigit() and len(self.text) == 7:
            self._verification_code = self.text[:6]
            logger.info(f"收到验证码：{self._verification_code}")
        # else:
        #     logger.info(f"收到消息：{self.text}")

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
            logger.info(f"{self.plugin_name}定时服务启动，时间间隔 {self._cron} ")
            return [{
                "id": self.__class__.__name__,
                "name": f"{self.plugin_name}服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.check,
                "kwargs": {}
            }]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(str(e))


