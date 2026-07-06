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
    # 主事件循环引用
    _loop: Optional[asyncio.AbstractEventLoop] = None
    # 二维码任务锁
    _qr_lock: Optional[asyncio.Lock] = None

    @staticmethod
    async def _launch_browser_context_async(headless: bool = True):
        """
        使用 CloakBrowser 异步启动企业微信页面上下文，统一注入中文语言环境。
        返回 BrowserContext 对象。
        """
        try:
            context = await asyncio.wait_for(
                launch_context_async(
                    headless=headless,
                    args=['--lang=zh-CN'],
                    extra_http_headers={
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.1'
                    }
                ),
                timeout=30.0
            )
            return context
        except asyncio.TimeoutError:
            logger.error("浏览器启动超时（30秒）")
            raise
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise

    def _safe_run_coro(self, coro):
        """
        安全地运行协程。
        如果主事件循环正在运行，使用 run_coroutine_threadsafe 提交；
        否则使用 asyncio.run 同步执行（兜底）。
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            # 兜底：使用 asyncio.run
            asyncio.run(coro)

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

        # 初始化事件循环和锁
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # 如果没有运行中的循环，获取当前事件循环或创建新的
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        self._qr_lock = asyncio.Lock()

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

        if not self._my_send.init_success:
            self._my_send = None
        if self._my_send and not self._my_send.other_channel:
            self._await_ip = False

        if "||wan" in self._input_id_list:
            last_char = self._input_id_list[-1] if self._input_id_list else None
            if isinstance(last_char, str) and last_char.isdigit():
                max_ips = int(last_char)
            else:
                max_ips = 3
            self.wan2 = IpLocationParser(self._settings_file_path, max_ips=max_ips)
            self._current_ip_address = self.wan2.read_ips("ips")
        else:
            self.wan2 = None
            self._current_ip_address = self.cfg.get("WECHAT_NOW_IP")

        # 停止现有任务
        self.stop_service()

        # 配置检查
        if not self._input_id_list:
            logger.warning("插件未配置应用ID，请填写企业微信应用ID")
            self.__update_config()
            return

        if (self._enabled or self._onlyonce) and self._input_id_list:
            # 定时服务 (改为异步调度器)
            self._scheduler = AsyncIOScheduler(timezone=settings.TZ)

            # 运行一次定时服务
            if self._onlyonce:
                if self.wan2:
                    if not self._forced_update or not self._local_scan:
                        logger.info("多网络出口检查需要时间较长，预计25秒内完成")
                        self._scheduler.add_job(
                            func=self.write_wan2_ip,
                            trigger='date',
                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                            name="多网络出口获取IP"
                        )
                        self._scheduler.add_job(
                            func=self.check,
                            trigger='date',
                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=20),
                            name="多网络出口检查IP"
                        )
                else:
                    if not self._forced_update or not self._local_scan:
                        self._scheduler.add_job(
                            func=self.check,
                            trigger='date',
                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                            name="检测公网IP"
                        )
                self._onlyonce = False

            if self._forced_update:
                if not self._local_scan:
                    logger.info("使用Cookie,强制更新公网IP")
                    self._scheduler.add_job(
                        func=self.forced_change,
                        trigger='date',
                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                        name="强制更新公网IP"
                    )
                self._forced_update = False

            if self._local_scan:
                logger.info("使用本地扫码登陆")
                self._scheduler.add_job(
                    func=self.local_scanning,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="本地扫码登陆"
                )
                self._local_scan = False

            # 固定半小时周期请求一次地址,防止cookie失效
            try:
                self._scheduler.add_job(
                    func=self.refresh_cookie,
                    trigger=CronTrigger.from_crontab(self._refresh_cron),
                    name="延续企业微信cookie有效时间"
                )
            except Exception as err:
                logger.error(f"定时任务配置错误：{err}")
                self.systemmessage.put(f"执行周期配置错误：{err}")

            if self.wan2:
                try:
                    self._scheduler.add_job(
                        func=self.get_ip_from_url,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="多wan口公网IP检测"
                    )
                except Exception as err:
                    logger.error(f"多wan口公网IP检测定时任务配置错误：{err}")
                    self.systemmessage.put(f"执行周期配置错误：{err}")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

        self.__update_config()

    def _send_cookie_false(self):
        """发送cookie失效通知"""
        self._cookie_valid = False

        # 情况1：配置了微信通知且有效
        if self._my_send and not self._await_ip and self._wechat_available:
            error = self._my_send.send(
                title="cookie已失效,请及时更新",
                content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。 如果使用'微信通知'请确保公网IP还没有变动",
                image=None, force_send=False
            )
            if error:
                logger.info(f"cookie失效通知发送失败,原因：{error}")
            return None

        # 情况2：微信通知无效，但有第三方通知
        if self._my_send and not self._wechat_available and self._my_send.other_channel:
            for channel, token in self._my_send.other_channel:
                error = self._my_send.send(
                    title="cookie已失效,且微信通知失效",
                    content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。",
                    image=None, force_send=False, diy_channel=channel, diy_token=token
                )
                if error:
                    logger.error(f"通道 {channel} 发送失败，原因：{error}")
                else:
                    return None
            # 所有通道都失败，记录系统消息
            self.systemmessage.put("cookie已失效，且所有通知方式均发送失败，请手动更新cookie")
            return None

        # 情况3：没有任何通知方式
        if not self._my_send:
            logger.warning("cookie已失效，但未配置任何通知方式，用户可能无法及时感知")
            self.systemmessage.put("cookie已失效，请及时更新，当前未配置通知方式")
            return None

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
            await asyncio.sleep(3)
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
                    await asyncio.sleep(20)
                    if await self.check_login_status(page, task='local_scanning'):
                        await self._update_cookie(page, context)
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
        """多WAN口IP写入"""
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
                # IpLocationParser.get_ipv4 已是异步方法
                china_ips = await self.wan2.get_ipv4(page, url)
                if china_ips:
                    self.wan2.overwrite_ips("url_ip", china_ips)
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
        """检测IP是否变化"""
        if self.wan2:
            ip_address = self.wan2.read_ips("url_ip")
            url = self.wan2_url
        else:
            url, ip_address = await self.get_ip_from_url()

        # 增强空值检查
        if not ip_address or ip_address == "获取IP失败" or not url:
            logger.error("获取IP失败 不操作可信IP")
            return False

        # 成功获取 IP，记录日志
        if url and ip_address:
            logger.info(f"IP获取成功: {url}: {ip_address}")

        # 上次修改 IP 失败时，继续尝试修改
        if not self._ip_changed and func != "public":
            logger.info("上次IP修改IP失败 继续尝试修改IP")
            return True

        # 如果有 wan2，则处理新增的 IP 地址
        if self.wan2:
            if isinstance(ip_address, str):
                url_ips = [ip for ip in ip_address.split(";") if ip]
            else:
                url_ips = [ip for ip in ip_address if ip]

            if not url_ips:
                return False

            saved_ips = self.wan2.read_ips("ips")
            saved_ips_list = [ip for ip in saved_ips.split(";") if ip] if saved_ips else []

            for ip in url_ips:
                if ip not in saved_ips_list:
                    self.wan2.add_ips("ips", ip)
                    return True
        else:
            if ip_address != self._current_ip_address:
                logger.info("检测到IP变化")
                self._wechat_available = False
                return True
        return False

    async def try_connect_cc_async(self):
        """异步连接CookieCloud"""
        if not self._use_cookiecloud:
            self._cc_server = None
            return

        if not settings.COOKIECLOUD_KEY or not settings.COOKIECLOUD_PASSWORD:
            self._cc_server = None
            logger.error("没有配置CookieCloud的用户KEY和PASSWORD")
            return

        if settings.COOKIECLOUD_ENABLE_LOCAL:
            self._cc_server = PyCookieCloud(
                url=self._server,
                uuid=settings.COOKIECLOUD_KEY,
                password=settings.COOKIECLOUD_PASSWORD
            )
            logger.info("使用内建CookieCloud服务器")
        else:
            self._cc_server = PyCookieCloud(
                url=settings.COOKIECLOUD_HOST,
                uuid=settings.COOKIECLOUD_KEY,
                password=settings.COOKIECLOUD_PASSWORD
            )
            logger.info("使用自定义CookieCloud服务器")

        # 异步检查连接
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(self._cc_server.url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status != 200:
                        self._cc_server = None
                        logger.error("没有可用的CookieCloud服务器")
        except Exception as e:
            self._cc_server = None
            logger.error(f"CookieCloud连接失败: {e}")

    def try_connect_cc(self):
        """同步版本（兼容旧调用，实际执行异步）"""
        # 由于在异步环境中不应有同步调用，此方法作为过渡
        # 实际调用已改为 try_connect_cc_async
        asyncio.run_coroutine_threadsafe(self.try_connect_cc_async(), self._loop)

    async def get_ip_from_url(self) -> (str, str):
        """从URL获取IP地址"""
        if isinstance(self._input_id_list, str) and "||" in self._input_id_list:
            _, url_list = self._input_id_list.split("||", 1)
            urls = url_list.split(",")
        elif isinstance(self._input_id_list, list):
            urls = self._input_id_list
        else:
            urls = self._ip_urls

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
                                    return url, ip_address.group()
                    except Exception as e:
                        if "104" not in str(e) and 'Read timed out' not in str(e):
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
                    china_ips = await self.wan2.get_ipv4(page, url)
                    if china_ips:
                        self.wan2_url = url
                        self.wan2.overwrite_ips("url_ip", china_ips)
                        return url, china_ips
                except Exception as e:
                    logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
                finally:
                    if context:
                        await context.close()
            self.wan2_url = None
            return None, "获取IP失败"

    async def find_qrc(self, page):
        """查找二维码"""
        try:
            await page.wait_for_selector("iframe", timeout=5000)
            iframe_element = await page.query_selector("iframe")
            if not iframe_element:
                logger.warning("未找到iframe元素")
                return None, None
            frame = await iframe_element.content_frame()
            if not frame:
                logger.warning("无法获取iframe内容")
                return None, None

            qr_code_element = await frame.query_selector("img.qrcode_login_img")
            if qr_code_element:
                qr_code_url = await qr_code_element.get_attribute('src')
                if qr_code_url.startswith("/"):
                    qr_code_url = "https://work.weixin.qq.com" + qr_code_url

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
        """修改可信IP"""
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
                if self._my_send:
                    self._ip_changed = False
                    self._send_cookie_false()
                    logger.info("已尝试发送cookie失效通知")
                else:
                    self._ip_changed = False
                    self._cookie_valid = False
                    logger.info("cookie已失效,且没有配置通知方式,本次修改可信IP失败")
            else:
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
        """更新cookie"""
        self._future_timestamp = 0
        PyCookieCloud.save_cookie_lifetime(self._settings_file_path, 0)

        if self._use_cookiecloud:
            if not self._cc_server:
                await self.try_connect_cc_async()
                if self._cc_server is None:
                    return

            logger.info("使用二维码登录成功,开始刷新cookie")
            try:
                if not await self._cc_server.check_connection_async():
                    logger.error(f"连接 CookieCloud 失败: {self._cc_server.url}")
                    return

                current_url = page.url
                current_cookies = await context.cookies(current_url)
                if current_cookies is None:
                    logger.error("无法从内置浏览器获取 cookies")
                    self._cookie_valid = False
                    return

                self._saved_cookie = current_cookies
                formatted_cookies = {}
                for cookie in current_cookies:
                    domain = cookie.get('domain')
                    if domain is None:
                        continue
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
                current_cookies = await context.cookies(current_url)
                if current_cookies is None:
                    self._send_cookie_false()
                    logger.error("更新本地 Cookie失败")
                    self._is_special_upload = False
                    return
                else:
                    logger.info("更新本地 Cookie成功，请不要在其他地方登录企业微信")
                    self._is_special_upload = True
                    self._saved_cookie = current_cookies
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
            if not self._use_cookiecloud:
                return None

            # 使用线程池执行同步的 CookieCloud 下载
            import asyncio
            cookies, msg = asyncio.run_coroutine_threadsafe(
                asyncio.to_thread(self._cookiecloud.download),
                self._loop
            ).result(timeout=5)

            if not cookies:
                logger.error(f"CookieCloud获取cookie失败,失败原因：{msg}")
                return None

            cookie_header = ''
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

    def parse_cookie_header(self, cookie_header):
        """解析cookie头"""
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

    async def refresh_cookie(self):
        """保活：刷新cookie"""
        context = None
        try:
            context = await self._launch_browser_context_async(headless=True)
            cookie_used = False

            if self._saved_cookie:
                await context.add_cookies(self._saved_cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                if await self.check_login_status(page, task='refresh_cookie'):
                    self._cookie_valid = True
                    cookie_used = True
                else:
                    self._cookie_valid = False
                    self._saved_cookie = None

            if not cookie_used and self._use_cookiecloud:
                cookie = self.get_cookie()
                if not cookie:
                    self._send_cookie_false()
                    return
                await context.add_cookies(cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                if await self.check_login_status(page, task='refresh_cookie'):
                    self._cookie_valid = True
                    self._saved_cookie = await context.cookies()
                else:
                    self._send_cookie_false()
                    self._saved_cookie = None

            if self._cookie_valid:
                if self._my_send:
                    self._my_send.reset_limit()
                PyCookieCloud.increase_cookie_lifetime(self._settings_file_path, 600)
                self._cookie_lifetime = PyCookieCloud.load_cookie_lifetime(self._settings_file_path)

        except asyncio.TimeoutError:
            self._send_cookie_false()
            self._saved_cookie = None
            logger.error("cookie 校验超时")
        except Exception as e:
            self._send_cookie_false()
            self._saved_cookie = None
            logger.error(f"cookie 校验过程中发生异常: {e}")
        finally:
            if context:
                await context.close()

    async def check_login_status(self, page, task):
        """检查登录状态"""
        await asyncio.sleep(3)
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
                    success_element = await page.wait_for_selector(selector, timeout=3000)
                    if success_element:
                        if task != 'refresh_cookie':
                            logger.info("登录成功！")
                        return True
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"登录检查异常: {e}")

        try:
            captcha_panel = await page.wait_for_selector('.receive_captcha_panel', timeout=5000)
            if captcha_panel:
                if task == 'local_scanning':
                    await asyncio.sleep(3)
                else:
                    logger.info("等待30秒,请将短信验证码请以'？'结束,发送到<企业微信应用> 如： 110301？")
                    await asyncio.sleep(30)

                if self._verification_code:
                    for digit in self._verification_code:
                        await page.keyboard.press(digit)
                        await asyncio.sleep(0.3)
                    confirm_button = await page.wait_for_selector('.confirm_btn', timeout=5000)
                    if confirm_button:
                        await confirm_button.click()
                        await asyncio.sleep(3)

                        for selector in success_selectors:
                            try:
                                success_element = await page.wait_for_selector(selector, timeout=3000)
                                if success_element:
                                    self._verification_code = None
                                    logger.info("验证码登录成功！")
                                    return True
                            except Exception:
                                continue
                else:
                    logger.error("未收到短信验证码，请以问号结尾发送到企业微信应用。如：510010? 使用全局AI助手需使用/wxcode 510010的格式发送验证码")
                    return False
        except Exception:
            if await self.find_qrc(page) and task not in ['refresh_cookie', 'local_scanning']:
                logger.warning("用户没有扫描二维码")
                return False

        return False

    async def click_app_management_buttons(self, page):
        """点击应用管理按钮"""
        self._cookie_valid = True
        if self._my_send:
            self._my_send.reset_limit()

        bash_url = "https://work.weixin.qq.com/wework_admin/frame#apps/modApiApp/"
        buttons = [
            (
                "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
                "配置"
            )
        ]

        if self.wan2:
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
                logger.warning("请根据 https://github.com/RamenRa/MoviePilot-Plugins 的说明进行配置应用ID")
                return

            await page.goto(app_url)
            await asyncio.sleep(2)

            for xpath, name in buttons:
                try:
                    button = await page.wait_for_selector(xpath, timeout=5000)
                    await button.click()
                    await page.wait_for_selector('textarea.js_ipConfig_textarea', timeout=5000)

                    input_area = page.locator('textarea.js_ipConfig_textarea')
                    confirm = page.locator('.js_ipConfig_confirmBtn')
                    await input_area.fill(self._current_ip_address)
                    await confirm.click()
                    await asyncio.sleep(3)
                    self._ip_changed = True
                except Exception as e:
                    logger.error(f"未能找打开{app_url}或点击 '{name}' 按钮异常: {e}")
                    self._ip_changed = False
                    if "disabled" in str(e):
                        logger.info(f"应用{app_id} 已被禁用,可能是没有设置接收api")

            if self._ip_changed:
                self._wechat_available = True
                self._send_notification = False
                self.cfg.update("WECHAT_NOW_IP", self._current_ip_address)

                masked_ips = [self.mask_ip(ip) for ip in self._current_ip_address.split(';')]
                masked_ip_string = ";".join(masked_ips)
                logger.info(f"应用: {app_id} 输入IP：" + self._current_ip_address)

                if self._my_send and not self._my_send.quiet_flag:
                    self._my_send.send(
                        title="更新可信IP成功",
                        content='应用: ' + app_id + ' 输入IP：' + masked_ip_string,
                        force_send=True, diy_channel="WeChat"
                    )

    @staticmethod
    def mask_ip(ip):
        """IP地址脱敏"""
        ip_parts = ip.split('.')
        if len(ip_parts) == 4:
            masked_ip = f"{ip_parts[0]}.{len(ip_parts[1]) * '*'}.{len(ip_parts[2]) * '*'}.{ip_parts[3]}"
            return masked_ip
        return ip

    def __update_config(self):
        """更新配置"""
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "notification_token": self._notification_token,
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
        """拼装插件配置页面"""
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
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
                                'props': {'cols': 12, 'md': 4},
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
                                'props': {'cols': 12, 'md': 4},
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
                                'props': {'cols': 12, 'md': 4},
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
                                'props': {'cols': 12, 'md': 4},
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
                                    'props': {'cols': 12, 'md': 4},
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
                                'props': {'cols': 12, 'md': 6},
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
                                'props': {'cols': 12, 'md': 6},
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
                                'props': {'cols': 12},
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
                                'props': {'cols': 12},
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
                                'props': {'cols': 12},
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
        """插件页面"""
        current_time = datetime.now().timestamp()

        if current_time > self._future_timestamp:
            vaild_text = "二维码已过期或没有扫码任务"
            color = "#9B50FF" if self._enabled else "#bbbbbb"
            self._qr_code_image = None
        else:
            expiration_time = datetime.fromtimestamp(self._future_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            vaild_text = f"二维码有效,过期时间: {expiration_time}"
            color = "#32CD32"

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
            qr_image_data = self._qr_code_image.getvalue()
            base64_image = base64.b64encode(qr_image_data).decode('utf-8')
            img_src = f"data:image/png;base64,{base64_image}"

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
            cookie_lifetime_days = self._cookie_lifetime // 86400
            cookie_lifetime_hours = (self._cookie_lifetime % 86400) // 3600
            cookie_lifetime_minutes = (self._cookie_lifetime % 3600) // 60
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
            cookie_lifetime_component = None

        base_content = [
            {
                "component": "div",
                "props": {"style": {"textAlign": "center"}},
                "content": [
                    {
                        "component": "div",
                        "props": {
                            "style": {
                                "display": "flex",
                                "justifyContent": "center",
                                "alignItems": "center",
                                "flexDirection": "column",
                                "gap": "10px"
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
                    img_component
                ]
            }
        ]

        return base_content

    # ---------- 同步事件入口（用于 PluginAction 回调） ----------
    @eventmanager.register(EventType.PluginAction)
    def forced_change_event(self, event: Event = None):
        """同步入口：强制修改IP"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if event_data and event_data.get("action") != "dynamicwechat":
                return
        self._safe_run_coro(self.forced_change(event))

    @eventmanager.register(EventType.PluginAction)
    def local_scanning_event(self, event: Event = None):
        """同步入口：本地扫码"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if event_data and event_data.get("action") != "dynamicwechat":
                return
        self._safe_run_coro(self.local_scanning(event))

    @eventmanager.register(EventType.PluginAction)
    def write_wan2_ip_event(self, event: Event = None):
        """同步入口：多WAN口IP写入"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if event_data and event_data.get("action") != "dynamicwechat":
                return
        self._safe_run_coro(self.write_wan2_ip(event))

    @eventmanager.register(EventType.PluginAction)
    def check_event(self, event: Event = None):
        """同步入口：检测任务"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if event_data and event_data.get("action") != "dynamicwechat":
                return
        self._safe_run_coro(self.check(event))

    @eventmanager.register(EventType.PluginAction)
    def push_qr_code_event(self, event: Event = None):
        """同步入口：推送二维码"""
        if not self._enabled:
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "push_qrcode":
                return
        self._safe_run_coro(self._push_qr_code_with_lock(event))

    async def _push_qr_code_with_lock(self, event: Event = None):
        """带锁的二维码推送"""
        # 尝试获取锁，若已被占用则直接返回
        if self._qr_lock.locked():
            logger.info("二维码推送任务正在执行，忽略重复触发")
            return

        async with self._qr_lock:
            await self._push_qr_code_async(event)

    async def _push_qr_code_async(self, event: Event = None):
        """异步执行推送二维码"""
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
                        sent = False
                        for channel, token in self._my_send.other_channel:
                            error = self._my_send.send(
                                title="企业微信登录二维码",
                                image=image_src, diy_channel=channel, diy_token=token
                            )
                            if not error:
                                sent = True
                                break
                            logger.warning(f"通道 {channel} 推送二维码失败，原因：{error}")
                        if not sent:
                            logger.warning("所有第三方通知通道推送二维码均失败")
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
                "data": {"action": "push_qrcode"}
            },
            {
                "cmd": "/wxcode",
                "event": EventType.PluginAction,
                "desc": "提交企业微信验证码",
                "category": "",
                "data": {"action": "wxcode"}
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
                logger.info("服务启动")
            else:
                logger.info(f"当前记录的IP：{self._current_ip_address}，首次使用可能为空或检测IP失败")
            return [{
                "id": self.__class__.__name__,
                "name": f"{self.plugin_name}服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.check,
                "kwargs": {}
            }]
        return []

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