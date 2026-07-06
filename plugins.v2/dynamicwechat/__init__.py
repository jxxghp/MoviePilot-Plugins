import asyncio
import io
import random
import re
import base64
from datetime import datetime, timedelta
from typing import Optional
from typing import Tuple, List, Dict, Any

import aiohttp
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from cloakbrowser import launch_context_async

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.helper.cookiecloud import CookieCloudHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

from .helper import PyCookieCloud, MySender, IpLocationParser, JsonFieldManager


class DynamicWeChat(_PluginBase):
    # 插件名称
    plugin_name = "动态企微可信IP"
    # 插件描述
    plugin_desc = "修改企微应用可信IP,详细说明查看'作者主页',支持第三方通知。验证码以？结尾发送到企业微信应用"
    # 插件图标
    plugin_icon = "Wecom_A.png"
    # 插件版本 (已升级)
    plugin_version = "2.1.3"
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
    # 检测间隔时间,默认10分钟
    _refresh_cron = '*/10 * * * *'

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
    # 类初始化时添加标记变量
    _is_special_upload = False
    # 聚合通知
    _my_send = None
    # 多wan口支持
    wan2 = None
    # 当前检测url
    wan2_url = None
    # IP变动后发送通知开关
    _await_ip = False
    # 保存cookie
    _saved_cookie = None
    # 通知方式token/api
    _notification_token = ''
    # 标记企业微信通知可用
    _wechat_available = True
    # 仅标记IP变动后 通知发送过了没有
    _send_notification = False

    # 匹配ip地址的正则
    _ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    # 获取ip地址的网址列表
    _ip_urls = ["https://myip.ipip.net", "https://ddns.oray.com/checkip", "https://ip.3322.net", "https://r.inews.qq.com/api/ip2city", "https://uapis.cn/api/v1/network/myip"]
    # 当前ip地址
    _current_ip_address = '0.0.0.0'
    # 企业微信登录
    _wechatUrl = 'https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome'

    # 输入的企业应用id
    _input_id_list = ''
    # 二维码
    _qr_code_image = None
    # 用户消息
    text = ""
    # 手机验证码
    _verification_code = ''
    # 过期时间
    _future_timestamp = 0
    # 配置文件路径
    _settings_file_path = None

    # cookie有效检测
    _cookie_valid = True
    # cookie存活时间
    _cookie_lifetime = 0
    # 使用CookieCloud开关
    _use_cookiecloud = True
    # 登录cookie
    _cookie_header = ""
    # 内建CookieCloud服务器
    _server = f'http://localhost:{settings.NGINX_PORT}/cookiecloud'
    # CookieCloud客户端
    _cookiecloud = CookieCloudHelper()
    # 定时器 (改为异步调度器)
    _scheduler: Optional[AsyncIOScheduler] = None

    @staticmethod
    async def _launch_browser_context_async(headless: bool = True):
        """
        使用 CloakBrowser 异步启动企业微信页面上下文，统一注入中文语言环境。
        返回 BrowserContext 对象。
        """
        context = await launch_context_async(
            headless=headless,
            args=['--lang=zh-CN'],
            extra_http_headers={
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.1'
            }
        )
        return context

    if hasattr(settings, 'VERSION_FLAG'):
        version = settings.VERSION_FLAG  # V2
    else:
        version = "v1"

    def init_plugin(self, config: dict = None):
        # 清空配置
        self._last_code = ""
        self._notification_token = ''
        self._cron = '*/10 * * * *'
        self._ip_changed = True
        self._forced_update = False
        self._use_cookiecloud = True
        self._local_scan = False
        self._input_id_list = ''
        self._cookie_header = ""
        self._settings_file_path = self.get_data_path() / "settings.json"
        self.cfg = JsonFieldManager(self._settings_file_path)
        self._qr_running = False
        if config:
            self._enabled = config.get("enabled")
            self._notification_token = config.get("notification_token")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._input_id_list = config.get("input_id_list")
            self._forced_update = config.get("forced_update")
            self._local_scan = config.get("local_scan")
            self._use_cookiecloud = config.get("use_cookiecloud")
            self._cookie_header = config.get("cookie_header")
            self._await_ip = config.get("await_ip")
        if self.version != "v1":
            self._my_send = MySender(self._notification_token, func=self.post_message)
        else:
            self._my_send = MySender(self._notification_token)
        if not self._my_send.init_success:    # 没有输入通知方式,不通知
            self._my_send = None
        if self._my_send and not self._my_send.other_channel:   # 确保跟随通知配置，一定要配置了第三方才可以使用
            self._await_ip = False
        if "||wan" in self._input_id_list:  # 多wan口
            last_char = self._input_id_list[-1] if self._input_id_list else None
            if isinstance(last_char, str) and last_char.isdigit():
                max_ips = int(last_char)
            else:
                max_ips = 3  # 默认为 3
            self.wan2 = IpLocationParser(self._settings_file_path, max_ips=max_ips)
            self._current_ip_address = self.wan2.read_ips("ips")  # 从文件中读取
        else:
            self.wan2 = None
            # _, self._current_ip_address = self.get_ip_from_url()  # 直接从网页获取 返回URL和IP
            self._current_ip_address = self.cfg.get("WECHAT_NOW_IP")  # 应对MP/NAS长时间关闭后公网IP和可信IP不一致

        # 停止现有任务
        self.stop_service()
        if (self._enabled or self._onlyonce) and self._input_id_list:
            # 定时服务 (改为异步调度器)
            self._scheduler = AsyncIOScheduler(timezone=settings.TZ)
            # 运行一次定时服务
            if self._onlyonce:  # 多网口ip检测禁用立即检测
                if self.wan2:
                    if not self._forced_update or not self._local_scan:
                        logger.info("多网络出口检查需要时间较长，预计25秒内完成")
                        self._scheduler.add_job(func=self.write_wan2_ip, trigger='date',
                                                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(
                                                    seconds=3),
                                                name="多网络出口获取IP")  # 添加任务
                        self._scheduler.add_job(func=self.check, trigger='date',
                                                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(
                                                    seconds=20),
                                                name="多网络出口检查IP")  # 添加任务

                else:
                    if not self._forced_update or not self._local_scan:
                        self._scheduler.add_job(func=self.check, trigger='date',
                                                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                                name="检测公网IP")  # 添加任务
                        # logger.info("启用多网口检测时禁用‘立即检测一次’功能")
                # 关闭一次性开关
                self._onlyonce = False

            if self._forced_update:
                if not self._local_scan:
                    logger.info("使用Cookie,强制更新公网IP")
                    self._scheduler.add_job(func=self.forced_change, trigger='date',
                                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="强制更新公网IP")  # 添加任务
                self._forced_update = False

            if self._local_scan:
                logger.info("使用本地扫码登陆")
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

            if self.wan2:
                try:
                    self._scheduler.add_job(func=self.get_ip_from_url,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="多wan口公网IP检测")
                except Exception as err:
                    logger.error(f"多wan口公网IP检测定时任务配置错误：{err}")
                    self.systemmessage.put(f"执行周期配置错误：{err}")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
        self.__update_config()

    def _send_cookie_false(self):
        self._cookie_valid = False
        if self._my_send and not self._await_ip and self._wechat_available:  # 配置了通知 且 不启用“IP变动后通知 且 微信通知有效
            error = self._my_send.send(
                title="cookie已失效,请及时更新",
                content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。 如果使用’微信通知‘请确保公网IP还没有变动",
                image=None, force_send=False
            )
            if error:
                logger.info(f"cookie失效通知发送失败,原因：{error}")
            return None
        elif self._my_send and not self._wechat_available and self._my_send.other_channel: #  self._my_send 防止空对象
            '''
             # 微信通知无效（IP已不一致） 且 配置了第三方通知 
            '''
            for channel, token in self._my_send.other_channel:
                # logger.info(f"正常尝试：{channel} {token}")
                error = self._my_send.send(
                    title="cookie已失效,且微信通知失效",
                    content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。",
                    image=None, force_send=False, diy_channel=channel, diy_token=token
                )
                if error:
                    logger.error(f"通道 {channel} 发送失败，原因：{error}")
                else:
                    return None
        else:
            # logger.error(f"通道 {self._my_send} 发送失败，原因：{error}")
            return None

    # ---------- 异步核心方法 ----------
    async def forced_change(self, event: Event = None):
        """
        强制修改IP (异步)
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        # 先尝试cookie登陆
        context = None
        try:
            context = await self._launch_browser_context_async(headless=True)
            cookie = self.get_cookie()
            if cookie:
                await context.add_cookies(cookie)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            if await self.check_login_status(page, task='forced_change'):
                await self.click_app_management_buttons(page)
            else:
                logger.error("cookie失效,强制修改IP失败：请使用'本地扫码修改IP'")
                self._cookie_valid = False
        except Exception as err:
            logger.error(f"强制修改IP失败：{err}")
        finally:
            if context:
                await context.close()

        logger.info("----------------------本次任务结束----------------------")

    async def local_scanning(self, event: Event = None):
        """
        本地扫码 (异步)
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        context = None
        self._qr_running = True
        try:
            context = await self._launch_browser_context_async(headless=True)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)  # 页面加载等待时间
            img, _ = await self.find_qrc(page)
            if img:
                current_time = datetime.now()
                future_time = current_time + timedelta(seconds=110)
                self._future_timestamp = int(future_time.timestamp())
                logger.info("请重新进入插件面板扫码! 每20秒检查登录状态,最大尝试5次")
                max_attempts = 5
                attempt = 0
                while attempt < max_attempts:
                    attempt += 1
                    await asyncio.sleep(20)  # 每20秒检查一次
                    if await self.check_login_status(page, task='local_scanning'):
                        await self._update_cookie(page, context)  # 刷新cookie
                        await self.click_app_management_buttons(page)
                        break
                else:
                    logger.info("用户可能没有扫码或登录失败")
            else:
                logger.error("未找到二维码,任务结束")
            logger.info("----------------------本次任务结束----------------------")
        except Exception as e:
            logger.error(f"本地扫码任务: 本地扫码失败: {e}")
        finally:
            self._qr_running = False
            if context:
                await context.close()

    async def write_wan2_ip(self, event: Event = None):
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        urls = ["https://ip.skk.moe/multi", "https://ip.m27.tech", "https://ip.orz.tools"]
        random.shuffle(urls)
        self.wan2_url = None
        for url in urls:
            context = None
            try:
                context = await self._launch_browser_context_async(headless=url != "https://ip.skk.moe/multi")
                page = await context.new_page()
                # 注意：wan2.get_ipv4 需要异步化，请在 helper 中修改为 async def
                china_ips = await self.wan2.get_ipv4(page, url)
                if china_ips:
                    self.wan2.overwrite_ips("url_ip", china_ips)  # 将获取到的IP写入文件 覆盖写入
                    self.wan2_url = url
                    break
            except Exception as e:
                logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
            finally:
                if context:
                    await context.close()

    async def check(self, event: Event = None):
        """
        检测函数 (异步)
        """
        if not self._enabled:
            logger.error("插件未开启")
            return

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return

        # 情况1：cookie有效
        if self._cookie_valid:
            logger.info("开始检测公网IP")
            if await self.CheckIP():
                await self.ChangeIP()
                self.__update_config()
            logger.info("----------------------本次任务结束----------------------")
            return

        # 情况2：cookie失效 + 启用IP变动后通知（有第三方通知）
        if self._await_ip:
            logger.info("开始检测公网IP,等待IP变动后发送通知")
            if await self.CheckIP(func="public"):
                self._send_cookie_false()
            logger.info("----------------------本次任务结束----------------------")
            return

        # 情况3：cookie失效 + 不等待IP变化
        logger.info("Cookie已失效，本次不检查IP")
        self._send_cookie_false()

    async def CheckIP(self, func=None):
        if self.wan2:
            ip_address = self.wan2.read_ips("url_ip")
            url = self.wan2_url
        else:
            url, ip_address = await self.get_ip_from_url()

        if not ip_address or ip_address == "获取IP失败" or not url:
            logger.error("获取IP失败 不操作可信IP")
            return False

        # 成功获取 IP，记录日志
        if url and ip_address:
            logger.info(f"IP获取成功: {url}: {ip_address}")

        # 上次修改 IP 失败时，继续尝试修改
        if not self._ip_changed and func != "public":  # 排除cookie失效 检测公网变动的任务
            logger.info("上次IP修改IP失败 继续尝试修改IP")
            return True

        # 如果有 wan2，则处理新增的 IP 地址
        if self.wan2:
            if isinstance(ip_address, str):
                url_ips = ip_address.split(";")  # 将字符串按分号拆分为多个 IP 地址
            else:
                url_ips = ip_address
            saved_ips = self.wan2.read_ips("ips")

            # 检查每个新 IP 是否存在，若不存在则添加并返回 True
            for ip in url_ips:
                if ip not in saved_ips:
                    self.wan2.add_ips("ips", ip)  # 将url获取到的新IP添加到ips字段
                    return True
        else:
            # 检查 IP 是否变化
            if ip_address != self._current_ip_address:
                logger.info("检测到IP变化")
                self._wechat_available = False
                return True
        return False

    def try_connect_cc(self):
        if not self._use_cookiecloud:  # 不使用CookieCloud
            self._cc_server = None
            return
        if not settings.COOKIECLOUD_KEY or not settings.COOKIECLOUD_PASSWORD:  # 没有设置key和password
            self._cc_server = None
            logger.error("没有配置CookieCloud的用户KEY和PASSWORD")
            return
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

    async def get_ip_from_url(self) -> (str, str):
        # 根据输入解析 URL 列表
        if isinstance(self._input_id_list, str) and "||" in self._input_id_list:
            _, url_list = self._input_id_list.split("||", 1)
            urls = url_list.split(",")
        elif isinstance(self._input_id_list, list):
            urls = self._input_id_list
        else:
            urls = self._ip_urls
        # 随机化 URL 列表
        random.shuffle(urls)
        if not self.wan2:
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                            if response.status == 200:
                                text = await response.text()
                                ip_address = re.search(self._ip_pattern, text)
                                if ip_address:
                                    return url, ip_address.group()  # 返回匹配的 IP 地址
                    except Exception as e:
                        if "104" not in str(e) and 'Read timed out' not in str(e):  # 忽略网络波动,都失败会返回None, "获取IP失败"
                            logger.warning(f"{url} 获取IP失败, Error: {e}")
            return None, "获取IP失败"
        else:
            urls = ["https://ip.skk.moe/multi", "https://ip.m27.tech", "https://ip.orz.tools"]
            random.shuffle(urls)
            for url in urls:
                context = None
                try:
                    context = await self._launch_browser_context_async(headless=url != "https://ip.skk.moe/multi")
                    page = await context.new_page()
                    # 注意：wan2.get_ipv4 需要异步化，请在 helper 中修改为 async def
                    china_ips = await self.wan2.get_ipv4(page, url)
                    if china_ips:
                        self.wan2_url = url
                        self.wan2.overwrite_ips("url_ip", china_ips)  # 将获取到的IP写入文件 覆盖写入
                        return url, china_ips  # 成功获取到IP后返回
                except Exception as e:
                    logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
                finally:
                    if context:
                        await context.close()
            self.wan2_url = None
            return None, "获取IP失败"

    async def find_qrc(self, page):
        # 查找 iframe 元素并切换到它
        try:
            await page.wait_for_selector("iframe", timeout=5000)  # 等待 iframe 加载
            iframe_element = await page.query_selector("iframe")
            frame = await iframe_element.content_frame()

            # 查找二维码图片元素
            qr_code_element = await frame.query_selector("img.qrcode_login_img")
            if qr_code_element:
                # logger.info("找到二维码图片元素")
                # 保存二维码图片
                qr_code_url = await qr_code_element.get_attribute('src')
                if qr_code_url.startswith("/"):
                    qr_code_url = "https://work.weixin.qq.com" + qr_code_url  # 补全二维码 URL

                async with aiohttp.ClientSession() as session:
                    async with session.get(qr_code_url) as resp:
                        qr_code_data = await resp.read()
                self._qr_code_image = io.BytesIO(qr_code_data)
                refuse_time = (datetime.now() + timedelta(seconds=115)).strftime("%Y-%m-%d %H:%M:%S")
                return qr_code_url, refuse_time
            else:
                logger.warning("未找到二维码")
                return None, None
        except Exception as e:
            logger.debug(str(e))
            return None, None

    async def ChangeIP(self):
        logger.info("开始请求企业微信管理更改可信IP")
        context = None
        try:
            context = await self._launch_browser_context_async(headless=True)
            cookie = self.get_cookie()
            if cookie:
                await context.add_cookies(cookie)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            img_src, refuse_time = await self.find_qrc(page)
            if img_src:
                if self._my_send:   # 统一逻辑,只有用户发送'/push_qr'才会发送二维码
                    self._ip_changed = False
                    self._send_cookie_false()
                    logger.info("已尝试发送cookie失效通知")
                else:
                    self._ip_changed = False
                    self._cookie_valid = False
                    logger.info("cookie已失效,且没有配置通知方式,本次修改可信IP失败")
            else:  # 如果直接进入企业微信
                logger.info("尝试cookie登录")
                if await self.check_login_status(page, ""):
                    await self.click_app_management_buttons(page)
                else:
                    logger.info("发生了意料之外的错误,请附上配置信息到github反馈")
                    self._send_cookie_false()
                    self._ip_changed = False
        except Exception as e:
            self._ip_changed = False
            logger.error(f"更改可信IP失败: {e}")
        finally:
            if context:
                await context.close()

    async def _update_cookie(self, page, context):
        self._future_timestamp = 0  # 标记二维码失效
        PyCookieCloud.save_cookie_lifetime(self._settings_file_path, 0)  # 重置cookie存活时间
        if self._use_cookiecloud:
            if not self._cc_server:  # 连接失败返回 False
                self.try_connect_cc()  # 再尝试一次连接
                if self._cc_server is None:
                    return
            logger.info("使用二维码登录成功,开始刷新cookie")
            try:
                if not self._cc_server.check_connection():
                    logger.error("连接 CookieCloud 失败", self._server)
                    return
                current_url = page.url
                current_cookies = await context.cookies(current_url)  # 通过 context 获取 cookies
                if current_cookies is None:
                    logger.error("无法从内置浏览器获取 cookies")
                    self._cookie_valid = False
                    return
                self._saved_cookie = current_cookies
                formatted_cookies = {}
                for cookie in current_cookies:
                    domain = cookie.get('domain')  # 使用 get() 方法避免 KeyError
                    if domain is None:
                        continue  # 跳过没有 domain 的 cookie

                    if domain not in formatted_cookies:
                        formatted_cookies[domain] = []
                    formatted_cookies[domain].append(cookie)
                if self._cc_server.update_cookie(formatted_cookies):
                    logger.info("更新 CookieCloud 成功，如没有CC服务器同步cookie请不要在其他地方登录企业微信")
                    self._cookie_valid = True
                    self._is_special_upload = True
                else:
                    self._send_cookie_false()
                    self._is_special_upload = False
                    logger.error("更新 CookieCloud 失败")

            except Exception as e:
                self._send_cookie_false()
                self._is_special_upload = False
                logger.error(f"CookieCloud更新 cookie 发生错误: {e}")
        else:
            try:
                current_url = page.url
                current_cookies = await context.cookies(current_url)  # 通过 context 获取 cookies
                if current_cookies is None:
                    self._send_cookie_false()
                    logger.error("更新本地 Cookie失败")
                    self._is_special_upload = False
                    return
                else:
                    logger.info("更新本地 Cookie成功，请不要在其他地方登录企业微信")
                    self._is_special_upload = True
                    self._saved_cookie = current_cookies  # 保存
                    self._cookie_valid = True
            except Exception as e:
                self._send_cookie_false()
                logger.error(f"更新本地 cookie 发生错误: {e}")

    def get_cookie(self):
        """
        获取企业微信 Cookie。
        获取优先级：
            1. 本地内存缓存（_saved_cookie 且标记有效）
            2. CookieCloud 中 .work.weixin.qq.com 域名的 cookie
        Returns:
            Playwright 格式的 Cookie 字典列表；获取失败或未启用时返回 None。
        """
        if self._saved_cookie and self._cookie_valid:
            return self._saved_cookie
        try:
            cookie_header = ''
            if not self._use_cookiecloud:
                return None
            cookies, msg = self._cookiecloud.download()
            if not cookies:  # CookieCloud获取cookie失败
                logger.error(f"CookieCloud获取cookie失败,失败原因：{msg}")
                return None
            for domain, cookie in cookies.items():
                if domain == ".work.weixin.qq.com":
                    cookie_header = cookie
                    break
            if cookie_header == '':
                cookie_header = self._cookie_header
            cookie = self.parse_cookie_header(cookie_header)
            return cookie
        except Exception as e:
            logger.error(f"从CookieCloud获取cookie错误,错误原因:{e}")
            return None

    # @staticmethod
    def parse_cookie_header(self, cookie_header):
        cookies = []
        self._is_special_upload = False
        for cookie in cookie_header.split(';'):
            name, value = cookie.strip().split('=', 1)
            if name == '_upload_type' and value == 'A':
                self._is_special_upload = True
                continue
            cookies.append({
                'name': name,
                'value': value,
                'domain': '.work.weixin.qq.com',
                'path': '/'
            })
        return cookies

    async def refresh_cookie(self):  # 保活
        context = None
        try:
            context = await self._launch_browser_context_async(headless=True)
            cookie_used = False
            if self._saved_cookie:
                # logger.info("尝试使用内存保存的 cookie")
                await context.add_cookies(self._saved_cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                if await self.check_login_status(page, task='refresh_cookie'):
                    # logger.info("本地内存保存的 cookie 有效")
                    self._cookie_valid = True
                    cookie_used = True
                else:
                    # logger.warning("本地内存保存的 cookie 无效")
                    self._cookie_valid = False
                    self._saved_cookie = None  # 清空无效的 cookie

            if not cookie_used and self._use_cookiecloud:
                # logger.info("尝试从CookieCloud 获取新的 cookie")
                cookie = self.get_cookie()
                if not cookie:
                    self._send_cookie_false()
                    return
                await context.add_cookies(cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                if await self.check_login_status(page, task='refresh_cookie'):
                    # logger.info("新获取的 cookie 有效")
                    self._cookie_valid = True
                    self._saved_cookie = await context.cookies()  # 保存有效的 cookie
                else:
                    # logger.warning("新获取的 cookie 无效")
                    self._send_cookie_false()
                    self._saved_cookie = None  # 清空无效的 cookie

            if self._cookie_valid:
                if self._my_send:
                    self._my_send.reset_limit()
                PyCookieCloud.increase_cookie_lifetime(self._settings_file_path, 600)
                self._cookie_lifetime = PyCookieCloud.load_cookie_lifetime(self._settings_file_path)
        except Exception as e:
            self._send_cookie_false()
            self._saved_cookie = None  # 异常时清空 cookie
            logger.error(f"cookie 校验过程中发生异常: {e}")
        finally:
            if context:
                await context.close()

    #
    async def check_login_status(self, page, task):
        # 等待页面加载
        await asyncio.sleep(3)
        # 检查是否需要进行短信验证
        if task != 'refresh_cookie':
            logger.info("检查登录状态...")

        success_selectors = [
            "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
            '#_hmt_click > div.index_colRight > div > div.index_info > div > a',
            '/html/body/div/section[3]/div[1]/main/div/div/div[2]/div/div[1]/div/a',
            '#_hmt_click > div.index_colLeft > div.index_greeting.index_explore_text > div:nth-child(1)'
        ]

        try:
            for selector in success_selectors:
                try:
                    # 先检查登录成功后的页面状态
                    success_element = await page.wait_for_selector(selector, timeout=3000)  # 检查登录成功的元素
                    if success_element:
                        if task != 'refresh_cookie':
                            logger.info("登录成功！")
                        return True
                except Exception as e:
                    logger.debug(str(e))
                    pass
        except Exception as e:
            logger.debug(f"登录检查异常: {e}")

        try:
            # 检查是否进入验证码界面
            captcha_panel = await page.wait_for_selector('.receive_captcha_panel', timeout=5000)  # 检查验证码面板
            if captcha_panel:  # 出现了短信验证界面
                if task == 'local_scanning':
                    await asyncio.sleep(3)
                else:
                    logger.info("等待30秒,请将短信验证码请以'？'结束,发送到<企业微信应用> 如： 110301？")
                    await asyncio.sleep(30)  # 多等30秒
                if self._verification_code:
                    # logger.info("输入验证码：" + self._verification_code)
                    for digit in self._verification_code:
                        await page.keyboard.press(digit)
                        await asyncio.sleep(0.3)  # 每个数字之间添加少量间隔以确保输入顺利
                    confirm_button = await page.wait_for_selector('.confirm_btn', timeout=5000)  # 获取确认按钮
                    await confirm_button.click()  # 点击确认
                    await asyncio.sleep(3)  # 等待处理

                    # 再次检查登录状态
                    for selector in success_selectors:
                        try:
                            success_element = await page.wait_for_selector(selector, timeout=3000)
                            if success_element:
                                self._verification_code = None
                                logger.info("验证码登录成功！")
                                return True
                        except:
                            continue
                else:
                    logger.error("未收到短信验证码，请以问号结尾发送到企业微信应用。如：510010? 使用全局AI助手需使用/wxcode 510010的格式发送验证码")
                    return False
        except Exception as e:
            # logger.debug(str(e))  # 基于bug运行,请不要将错误输出到日志
            # try:  # 没有登录成功,也没有短信验证码
            if await self.find_qrc(page) and task not in ['refresh_cookie', 'local_scanning']:  # 延长任务找到的二维码不会被发送,所以不算用户没有扫码
                logger.warning(f"用户没有扫描二维码")
                return False

    async def click_app_management_buttons(self, page):
        self._cookie_valid = True
        if self._my_send:
            self._my_send.reset_limit()  # 解除限制 可以发送cookie失效提醒
        bash_url = "https://work.weixin.qq.com/wework_admin/frame#apps/modApiApp/"
        # 按钮的选择器和名称
        buttons = [
            # ("//span[@class='frame_nav_item_title' and text()='应用管理']", "应用管理"),
            # ("//div[@class='app_index_item_title ' and contains(text(), 'MoviePilot')]", "MoviePilot"),
            (
                "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
                "配置")
        ]
        if self.wan2:  # 多wan口从文件读取 ip
            self._current_ip_address = self.wan2.read_ips("ips")
        else:
            _, self._current_ip_address = await self.get_ip_from_url()
        if "||" in self._input_id_list:
            parts = self._input_id_list.split("||", 1)
            input_id_list = parts[0]
        else:
            input_id_list = self._input_id_list
        id_list = input_id_list.split(",")
        app_urls = [f"{bash_url}{app_id.strip()}" for app_id in id_list]
        for app_url in app_urls:
            app_id = app_url.split("/")[-1]
            if app_id.startswith("100000") and len(app_id) == 7:
                self._ip_changed = False
                logger.warning(f"请根据 https://github.com/RamenRa/MoviePilot-Plugins 的说明进行配置应用ID")
                return
            await page.goto(app_url)  # 打开应用详情页
            await asyncio.sleep(2)
            # 依次点击每个按钮
            for xpath, name in buttons:
                # 等待按钮出现并可点击
                try:
                    button = await page.wait_for_selector(xpath, timeout=5000)  # 等待按钮可点击
                    await button.click()
                    # logger.info(f"已点击 '{name}' 按钮")
                    await page.wait_for_selector('textarea.js_ipConfig_textarea', timeout=5000)
                    # logger.info(f"已找到文本框")
                    input_area = page.locator('textarea.js_ipConfig_textarea')
                    confirm = page.locator('.js_ipConfig_confirmBtn')
                    # logger.info(f"即将输入的内容：'{input_ip}'")
                    await input_area.fill(self._current_ip_address)  # 填充 IP 地址
                    await confirm.click()  # 点击确认按钮
                    await asyncio.sleep(3)  # 等待处理
                    self._ip_changed = True
                except Exception as e:
                    logger.error(f"未能找打开{app_url}或点击 '{name}' 按钮异常: {e}")
                    self._ip_changed = False
                    if "disabled" in str(e):
                        logger.info(f"应用{app_id} 已被禁用,可能是没有设置接收api")
            if self._ip_changed:
                self._wechat_available = True    # 标记微信通知重新有效
                self._send_notification = False  # 重置第三方通知已发送标记
                self.cfg.update("WECHAT_NOW_IP", self._current_ip_address)
                '''
                将填入企业微信的IP写入settings.json 
                应对MP/NAS长时间关闭后公网IP和可信IP不一致
                '''
                # self.wan2 = IpLocationParser(self._settings_file_path, max_ips=1)
                masked_ips = [self.mask_ip(ip) for ip in self._current_ip_address.split(';')]
                masked_ip_string = ";".join(masked_ips)
                logger.info(f"应用: {app_id} 输入IP：" + self._current_ip_address)
                if self._my_send and not self._my_send.quiet_flag:  # 没有开启安静模式才发通知
                    self._my_send.send(title="更新可信IP成功",
                                       content='应用: ' + app_id + ' 输入IP：' + masked_ip_string,
                                       force_send=True, diy_channel="WeChat")

    @staticmethod
    def mask_ip(ip):
        ip_parts = ip.split('.')
        if len(ip_parts) == 4:  # 确保是有效的 IPv4 地址
            # 使用星号替换第二和第三部分
            masked_ip = f"{ip_parts[0]}.{len(ip_parts[1]) * '*'}.{len(ip_parts[2]) * '*'}.{ip_parts[3]}"
            return masked_ip
        return ip  # 如果不是有效的 IP 地址，返回原地址

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "notification_token": self._notification_token,
            # "current_ip_address": self._current_ip_address,
            "await_ip": self._await_ip,
            "forced_update": self._forced_update,
            "local_scan": self._local_scan,
            "input_id_list": self._input_id_list,
            "cookie_header": self._cookie_header,
            "use_cookiecloud": self._use_cookiecloud,
        })

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面,只保留必要的配置项,并添加 token 配置。
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
                            },
                            *(
                                [{
                                    'component': 'VCol',
                                    'props': {
                                        'cols': 12,
                                        'md': 4
                                    },
                                    'content': [
                                        {
                                            'component': 'VSwitch',
                                            'props': {
                                                'model': 'await_ip',
                                                'label': 'IP变动后通知',
                                            }
                                        }
                                    ]
                                }]
                                if self._my_send and self._my_send.other_channel else []
                            )
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
                                            'label': '[必填]检测周期',
                                            'placeholder': '0 * * * *'
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
                                            'model': 'notification_token',
                                            'label': '[可选] 通知方式',
                                            'rows': 1,
                                            'placeholder': '支持微信、Server酱、PushPlus、AnPush等Token或API'
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
                                            'label': '[必填]应用ID',
                                            'rows': 1,
                                            'placeholder': '输入应用ID,多个ID用英文逗号分隔。在企业微信应用页面URL末尾获取'
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
                                            'text': '建议启用内建或自定义CookieCloud。支持微信和Server酱等第三方通知。具体请查看作者主页'
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
                                            'text': 'Cookie失效时通知用户，用户使用/push_qr让插件推送二维码。使用第三方通知时填写对应Token/API'
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
            "use_local_qr": False,
            "await_ip": False,
            "cookie_header": "",
            "notification_token": "",
            "input_id_list": ""
        }

    def get_page(self) -> List[dict]:
        # 获取当前时间戳
        current_time = datetime.now().timestamp()

        # 判断二维码是否过期
        if current_time > self._future_timestamp:
            vaild_text = "二维码已过期或没有扫码任务"
            color = "#9B50FF" if self._enabled else "#bbbbbb"
            self._qr_code_image = None
        else:
            # 二维码有效,格式化过期时间为 年-月-日 时:分:秒
            expiration_time = datetime.fromtimestamp(self._future_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            vaild_text = f"二维码有效,过期时间: {expiration_time}"
            color = "#32CD32"

        # 如果self._qr_code_image为None,返回提示信息
        if self._qr_code_image is None:
            img_component = {
                "component": "div",
                "text": "登录二维码都会在此展示,二维码有6秒延时。 [适用于Docker版]",
                "props": {
                    "style": {
                        "fontSize": "22px",
                        "color": "#FFB90F",
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
        if self._is_special_upload and self._enabled:
            # 计算 cookie_lifetime 的天数、小时数和分钟数
            cookie_lifetime_days = self._cookie_lifetime // 86400  # 一天的秒数为 86400
            cookie_lifetime_hours = (self._cookie_lifetime % 86400) // 3600  # 计算小时数
            cookie_lifetime_minutes = (self._cookie_lifetime % 3600) // 60  # 计算分钟数
            bg_color = "#40bb45" if self._cookie_valid else "#ff0000"
            cookie_lifetime_text = f"Cookie 已使用: {cookie_lifetime_days}天{cookie_lifetime_hours}小时{cookie_lifetime_minutes}分钟"

            cookie_lifetime_component = {
                "component": "div",
                "text": cookie_lifetime_text,
                "props": {
                    "style": {
                        "fontSize": "18px",
                        "color": "#ffffff",
                        "backgroundColor": bg_color,
                        "padding": "10px",
                        "borderRadius": "5px",
                        "textAlign": "center",
                        "marginTop": "10px",
                        "display": "block"
                    }
                }
            }
        else:
            cookie_lifetime_component = None  # 不生成该组件

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
                        "props": {
                            "style": {
                                "display": "flex",
                                "justifyContent": "center",
                                "alignItems": "center",
                                "flexDirection": "column",  # 垂直排列
                                "gap": "10px"  # 控制间距
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
                                        "textAlign": "center",
                                        "marginBottom": "10px",
                                        "display": "inline-block"
                                    }
                                }
                            },
                            cookie_lifetime_component if cookie_lifetime_component else {},
                        ]
                    },
                    img_component  # 二维码图片或提示信息
                ]
            }
        ]

        return base_content

    # ---------- 同步事件入口（用于 PluginAction 回调） ----------
    @eventmanager.register(EventType.PluginAction)
    def forced_change_event(self, event: Event = None):
        """同步入口：强制修改IP"""
        asyncio.create_task(self.forced_change(event))

    @eventmanager.register(EventType.PluginAction)
    def local_scanning_event(self, event: Event = None):
        """同步入口：本地扫码"""
        asyncio.create_task(self.local_scanning(event))

    @eventmanager.register(EventType.PluginAction)
    def write_wan2_ip_event(self, event: Event = None):
        """同步入口：多WAN口IP写入"""
        asyncio.create_task(self.write_wan2_ip(event))

    @eventmanager.register(EventType.PluginAction)
    def check_event(self, event: Event = None):
        """同步入口：检测任务"""
        asyncio.create_task(self.check(event))

    @eventmanager.register(EventType.PluginAction)
    def push_qr_code_event(self, event: Event = None):
        """同步入口：推送二维码"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "push_qrcode":
                return
        asyncio.create_task(self._push_qr_code_async(event))

    async def _push_qr_code_async(self, event: Event = None):
        """异步执行推送二维码"""
        if self._qr_running:
            return
        self._qr_running = True

        context = None
        try:
            context = await self._launch_browser_context_async(headless=True)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            image_src, refuse_time = await self.find_qrc(page)
            if image_src:
                if self._my_send:
                    if not self._wechat_available and self._my_send.other_channel:
                        for channel, token in self._my_send.other_channel:
                            error = self._my_send.send(
                                title="企业微信登录二维码",
                                image=image_src, diy_channel=channel, diy_token=token
                            )
                            if error:
                                logger.warning(f"通道 {channel} 推送二维码失败，原因：{error}")
                            else:
                                break
                    else:
                        error = self._my_send.send("企业微信登录二维码", image=image_src)
                        if error:
                            logger.info(f"远程推送任务: 二维码发送失败,原因：{error}")
                            logger.info("----------------------本次任务结束----------------------")
                            return
                    logger.info("远程推送任务: 二维码发送成功,等待用户 80 秒内扫码登录。V2'微信通知'的用户,此消息并不准确")
                    max_attempts = 4
                    attempt = 0
                    while attempt < max_attempts:
                        await asyncio.sleep(20)
                        attempt += 1
                        if await self.check_login_status(page, 'push_qr_code'):
                            await self._update_cookie(page, context)
                            await self.click_app_management_buttons(page)
                            break
                        else:
                            logger.info("用户可能没有扫码或登录失败")
                else:
                    logger.warning("远程推送任务: 没有找到可用的通知方式")
            else:
                logger.warning("远程推送任务: 未找到二维码")
            logger.info("----------------------本次任务结束----------------------")
        except Exception as e:
            logger.error(f"远程推送任务: 推送二维码失败: {e}")
        finally:
            if context:
                await context.close()
            self._qr_running = False

    # ---------- 事件接收 ----------
    @eventmanager.register(EventType.PluginAction)
    def receive_code(self, event: Event = None):
        """
        接收企业微信验证码
        """
        if not self._enabled or not event:
            return

        event_data = event.event_data or {}

        if event_data.get("action") != "wxcode":
            return
        if not self._qr_running:
            return
        raw = event_data.get("arg_str") or ""

        match = re.search(r"\d{6}", raw)
        if not match:
            logger.warning(f"收到无效验证码: {raw}")
            return

        code = match.group(0)

        if getattr(self, "_last_code", None) == code:
            return

        self._last_code = code
        self._verification_code = code

        logger.info(f"收到验证码：{code}")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/push_qr",
                "event": EventType.PluginAction,
                "desc": "立即推送登录二维码",
                "category": "",
                "data": {
                    "action": "push_qrcode"
                }
            },
            {
                "cmd": "/wxcode",
                "event": EventType.PluginAction,
                "desc": "提交企业微信验证码",
                "category": "",
                "data": {
                    "action": "wxcode"
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
        if not self._qr_running:
            return
        self.text = event.event_data.get("text")
        if len(self.text) == 7 and re.fullmatch(r".*\d{6}.*", self.text):
            match = re.search(r"\d{6}", self.text)
            if match:
                code = match.group(0)
                if code != self._last_code:
                    self._verification_code = code
                    self._last_code = code
                    logger.info(f"收到验证码：{code}")

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        if self._enabled and self._cron:
            if not self.wan2:
                logger.info(f"服务启动")
            else:
                logger.info(f"当前记录的IP：{self._current_ip_address}，首次使用可能为空或检测IP失败")
            return [{
                "id": self.__class__.__name__,
                "name": f"{self.plugin_name}服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.check,  # 异步函数
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