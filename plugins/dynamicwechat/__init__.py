from app.core.event import eventmanager, Event
import re
import time
import requests
import io
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import pytz
from typing import Optional
from app.schemas.types import EventType
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.log import logger
from app.plugins import _PluginBase
from app.core.config import settings
from app.helper.cookiecloud import CookieCloudHelper
from typing import Tuple, List, Dict, Any
from app.plugins.dynamicwechat.update_help import PyCookieCloud


# import UpdateHelp


class DynamicWeChat(_PluginBase):
    # 插件名称
    plugin_name = "修改企业微信可信IP"
    # 插件描述
    plugin_desc = "优先使用cookie，当填写两个第三方token时手机微信可以更新cookie。验证码以？结尾发给企业微信应用。如：110301？"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本
    plugin_version = "1.1.2"
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

    # 私有属性
    _enabled = False  # 开关
    _cron = None
    _onlyonce = False
    # IP更改成功状态,防止检测IP改动但cookie失效的时候_current_ip_address已经更新成新IP导致后面刷新cookie也没有更改企微IP
    _ip_changed = False
    # 强制更改IP
    _forced_update = False
    _cc_server = None
    _push_qr_now = False

    #匹配ip地址的正则
    _ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    # 获取ip地址的网址列表
    _ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip", "https://ip.3322.net", "https://4.ipw.cn"]
    # 当前ip地址
    _current_ip_address = '0.0.0.0'
    #企业微信登录
    _wechatUrl = 'https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome'
    #检测间隔时间,默认10分钟
    _refresh_cron = '*/20 * * * *'
    # _urls = []
    _input_id_list = ''
    _helloimg_s_token = ""
    _pushplus_token = ""
    # _standalone_chrome_address = "http://192.168.1.0:4444/wd/hub"
    _qr_code_image = None
    text = ""
    user_id = ""
    channel = ""
    _app_ids = []

    # -------cookie add------------
    # cookie有效检测
    # _cookie_valid = False
    # 使用CookieCloud开关
    _use_cookiecloud = True
    # 从CookieCloud获取的cookie
    _cookie_from_CC = ""
    # 登录cookie
    _cookie_header = ""
    _server = f'http://localhost:{settings.NGINX_PORT}/cookiecloud'
    # -------cookie END------------

    _cookiecloud = CookieCloudHelper()
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        self._server = f'http://localhost:{settings.NGINX_PORT}/cookiecloud'
        # 清空配置
        # self._wechatUrl = 'https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome'
        # self._urls = []
        self._helloimg_s_token = ''
        self._pushplus_token = ''
        # self._standalone_chrome_address = "http://192.168.1.0:4444/wd/hub"
        self._ip_changed = True
        self._forced_update = False
        # self._cookie_valid = False
        self._use_cookiecloud = True
        self._input_id_list = ''
        self._cookie_header = ""
        self._cookie_from_CC = ""
        self._current_ip_address = self.get_ip_from_url(self._ip_urls[0])
        # logger.info(f"当前公网 IP: {self._current_ip_address}")
        # logger.info(f"server host: {self._server} _uuid: {settings.COOKIECLOUD_KEY} _password: {settings.COOKIECLOUD_PASSWORD}")
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._input_id_list = config.get("input_id_list")
            self._current_ip_address = config.get("current_ip_address")
            self._pushplus_token = config.get("pushplus_token")
            self._helloimg_s_token = config.get("helloimg_s_token")
            self._cookie_from_CC = config.get("cookie_from_CC")
            self._forced_update = config.get("forced_update")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie_header = config.get("cookie_header")
            # self._standalone_chrome_address = config.get("standalone_chrome_address")
            self._ip_changed = config.get("ip_changed")
        if self._use_cookiecloud:
            self._cc_server = PyCookieCloud(url=self._server, uuid=settings.COOKIECLOUD_KEY,
                                            password=settings.COOKIECLOUD_PASSWORD)

        # 停止现有任务
        self.stop_service()
        if self._enabled or self._onlyonce:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 运行一次定时服务
            if self._onlyonce or self._forced_update:
                logger.info("立即检测公网IP")
                self._scheduler.add_job(func=self.check, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="检测公网IP")  # 添加任务
                # 关闭一次性开关
                self._onlyonce = False

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
                if self._forced_update:
                    time.sleep(4)
                    self._forced_update = False
        self.__update_config()

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
            logger.info("收到命令，开始检测公网IP ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始检测公网IP ...",
                              userid=event.event_data.get("user"))

        logger.info("开始检测公网IP")
        if self.CheckIP():
            self.ChangeIP()
            self.__update_config()

        # logger.info("检测公网IP完毕")
        logger.info("----------------------本次任务结束----------------------")
        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="检测公网IP完毕",
                              userid=event.event_data.get("user"))

    def CheckIP(self):
        # if not self._cookie_valid:
        #     self.refresh_cookie()
        #     if not self._cookie_valid:
        #         logger.error("请求企微失败,cookie可能过期,跳过IP检测")
        #         return False
        for url in self._ip_urls:
            ip_address = self.get_ip_from_url(url)
            if ip_address != "获取IP失败" and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
                break
        # if ip_address == "获取IP失败" or not ip_address:
        #     logger.error(f"请求网址失败")

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
            logger.warning(f"{url}获取IP失败,Error: {e}")
            # return "获取IP失败"

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
            return False

    def remote_push_qr(self):
        try:
            with sync_playwright() as p:
                # 启动 Chromium 浏览器并设置语言为中文
                browser = p.chromium.launch(headless=True, args=['--lang=zh-CN'])
                context = browser.new_context()
                # ----------cookie addd-----------------
                # cookie = self.get_cookie()
                # if cookie:
                #     context.add_cookies(cookie)
                # ----------cookie END-----------------
                page = context.new_page()
                page.goto(self._wechatUrl)
                time.sleep(3)
                if self.find_qrc(page):
                    if self._pushplus_token and self._helloimg_s_token:
                        img_src, refuse_time = self.upload_image(self._qr_code_image)
                        self.send_pushplus_message(refuse_time, f"企业微信登录二维码<br/><img src='{img_src}' />")
                        logger.info("二维码已经发送，等待用户 90 秒内扫码登录")
                        logger.info("如收到短信验证码请以？结束，发送到<企业微信应用> 如： 110301？")
                        time.sleep(90)
                        login_status = self.check_login_status(page)
                        if login_status:
                            self._update_cookie(page, context)  # 刷新cookie
                            self.click_app_management_buttons(page)
                else:
                    logger.warning("远程推送任务 未找到二维码")
        except Exception as e:
            logger.error(f"远程推送任务 推送二维码失败: {e}")


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
                        logger.info("二维码已经发送，等待用户 90 秒内扫码登录")
                        logger.info("如收到短信验证码请以？结束，发送到<企业微信应用> 如： 110301？")
                        time.sleep(90)  # 等待用户扫码
                        login_status = self.check_login_status(page)
                        if login_status:
                            self._update_cookie(page, context)  # 刷新cookie
                            self.click_app_management_buttons(page)

                        else:
                            self._ip_changed = False
                    else:
                        logger.info("cookie失效，请使用CookieCloud重新上传。")
                else:  # 如果直接进入企业微信
                    logger.info("尝试cookie登录")
                    # ----------cookie addd-----------------
                    login_status = self.check_login_status(page)
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
        if self._use_cookiecloud:
            logger.info("使用二维码登录成功，开始刷新cookie")
            try:
                # logger.info("debug  开始连接CookieCloud")
                if self._cc_server.check_connection():
                    logger.info("成功连接CookieCloud")
                    current_url = page.url
                    current_cookies = context.cookies(current_url)  # 通过 context 获取 cookies
                    # logger.info("原始 cookies：", current_cookies)
                    formatted_cookies = {}
                    for cookie in current_cookies:
                        domain = cookie['domain']
                        if domain not in formatted_cookies:
                            formatted_cookies[domain] = []
                        formatted_cookies[domain].append(cookie)
                    flag = self._cc_server.update_cookie({'cookie_data': formatted_cookies})
                    if flag:
                        logger.info("更新CookieCloud成功")
                    else:
                        logger.error("更新CookieCloud失败")
                else:
                    logger.error("连接CookieCloud失败", self._server, settings.COOKIECLOUD_KEY,
                                 settings.COOKIECLOUD_PASSWORD)
            except Exception as e:
                logger.error(f"更新cookie发生错误: {e}")
        else:
            logger.info("不使用CookieCloud, 不刷新cookie")

    # ----------cookie addd-----------------
    def get_cookie(self):  # 只有从CookieCloud获取cookie成功才返回True
        try:
            cookie_header = ''
            if self._use_cookiecloud:
                # if self._cookie_valid:  # 如果无效
                # return self._cookie_from_CC
                # return True
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
                cookie_header = self._cookie_header
                # return
            cookie = self.parse_cookie_header(cookie_header)
            self._cookie_from_CC = cookie
            return cookie
        except Exception as e:
            logger.error(f"从CookieCloud获取cookie错误，错误原因:{e}")
            # logger.info("尝试推送登录二维码")
            return

    def parse_cookie_header(self, cookie_header):
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
                browser = p.chromium.launch(headless=False, args=['--lang=zh-CN'])
                context = browser.new_context()
                cookie = self.get_cookie()
                if cookie:
                    context.add_cookies(cookie)
                #     logger.info("给浏览器添加cookie成功")
                # else:
                #     logger.info("给浏览器添加cookie失败")
                page = context.new_page()
                logger.info("延长cookie任务开始")
                page.goto(self._wechatUrl)
                time.sleep(3)
                # 检查登录元素是否可见
                if self.check_login_status(page):
                    logger.info("延长cookie任务成功")
                    # self._cookie_valid = True
                else:
                    logger.info("cookie已失效，下次IP变动推送二维码")
                    # self._cookie_valid = False
                browser.close()
        except Exception as e:
            logger.error(f"cookie校验失败:{e}")
            # self._cookie_valid = False

    #
    def check_login_status(self, page):
        # 等待页面加载
        time.sleep(3)
        # 检查是否需要进行短信验证
        logger.info("检查登录状态...")
        try:
            # 先检查登录成功后的页面状态
            success_element = page.wait_for_selector('#check_corp_info', timeout=5000)  # 检查登录成功的元素
            if success_element:
                logger.info("登录成功！")
                return True
        except Exception as e:
            # logger.error(f"检查登录状态时发生错误: {e}")
            pass

        try:
            # 在这里使用更安全的方式来检查元素是否存在
            captcha_panel = page.wait_for_selector('.receive_captcha_panel', timeout=5000)  # 检查验证码面板
            if captcha_panel:  # 出现了短信验证界面
                time.sleep(30)  # 多等30秒
                if self.text[:6]:
                    logger.info("需要短信验证 收到的短信验证码：" + self.text[:6])
                    for digit in self.text[:6]:
                        page.keyboard.press(digit)
                        time.sleep(0.3)  # 每个数字之间添加少量间隔以确保输入顺利
                    confirm_button = page.wait_for_selector('.confirm_btn', timeout=5000)  # 获取确认按钮
                    confirm_button.click()  # 点击确认
                    time.sleep(3)  # 等待处理
                    # 等待登录成功的元素出现
                    success_element = page.wait_for_selector('#check_corp_info', timeout=10000)
                    if success_element:
                        logger.info("验证码登录成功！")
                        return True
                else:
                    logger.error("未收到短信验证码")
                    return False
        except Exception as e:
            # try:  # 没有登录成功，也没有短信验证码。 查找二维码是否还存在
            if self.find_qrc(page):
                logger.error(f"用户没有扫描二维码")
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
                page.goto(app_url)    # 打开应用详情页
                # logger.info(f"已打开{app_url}")
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
                        logger.info("已输入公网IP：" + self._current_ip_address)
                        confirm.click()  # 点击确认按钮
                        time.sleep(3)  # 等待处理
                        self._ip_changed = True
                    except Exception as e:
                        logger.error(f"未能找打开{app_url}或点击 '{name}' 按钮异常: {e}")
                        self._ip_changed = False
                        if "disabled" in str(e):
                            logger.info("该应用已被禁用,可能是没有设置接收api")
            return
        else:
            logger.error("未找到应用id，修改IP失败")
            return

    def send_pushplus_message(self, title, content):
        pushplus_url = f"http://www.pushplus.plus/send/{self._pushplus_token}"
        pushplus_data = {
            "title": title,
            "content": content,
            "template": "html"
        }
        # if wait_time > 2:
        #     # time.sleep(wait_time)
        #     logger.info(f"pushplus API 调用次数限制，本次不发送 至少间隔 {wait_time} 秒")
        # else:
        response = requests.post(pushplus_url, json=pushplus_data)
        # return response

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
            logger.info("本次操作终止")
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
            "helloimg_s_token": self._helloimg_s_token,
            "pushplus_token": self._pushplus_token,
            "input_id_list": self._input_id_list,
            # "standalone_chrome_address": self._standalone_chrome_address,

            "cookie_from_CC": self._cookie_from_CC,
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
                                            'label': '强制更新',
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
                                            'model': 'cookie_header',
                                            'label': 'COOKIE',
                                            'rows': 1,
                                            'placeholder': '手动填写cookie'
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
                                            'text': '* 强制更新和立即检测按钮属于一次性按钮。使用CookieCloud请到设置打开“本地CookieCloud”。'
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
                                            'text': '本插件优先使用cookie，当需要修改IP时cookie失效填写了两个token时会推送登录二维码到微信。',
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
            "use_cookiecloud": True,  # 新增的模型字段
            # "wechatUrl": "",
            "cookie_header": "",
            "pushplus_token": "",
            "helloimg_token": "",
            "input_id_list": "",
            "standalone_chrome_address": ""
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.PluginAction)
    def push_qr(self, event: Event = None):
        """
        发送二维码
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "push_qrcode":
                return
        logger.info("远程命令开始推送二维码")
        self.remote_push_qr()


    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/push_qr_code",
                "event": EventType.PluginAction,
                "desc": "立即推送登录二维码到微信",
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
        # self.user_id = event.event_data.get("userid")
        # self.channel = event.event_data.get("channel")
        if self.text and len(self.text) == 7:
            logger.info(f"收到验证码：{self.text}")
        else:
            logger.info(f"收到消息：{self.text}")

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
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(str(e))
