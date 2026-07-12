import asyncio
import io
import os
import random
import re
import base64
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

import aiohttp
import pytz
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
    # 插件版本
    plugin_version = "2.1.7"
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

    # ---------- 常量配置 ----------
    BROWSER_LAUNCH_TIMEOUT = 30.0      # 浏览器启动超时（秒）
    BROWSER_RETRY_COUNT = 3            # 浏览器启动重试次数
    BROWSER_RETRY_DELAY = 2.0          # 浏览器启动重试间隔（秒）
    QR_CODE_MAX_ATTEMPTS = 4           # 扫码最大检查次数
    QR_CODE_CHECK_INTERVAL = 20        # 扫码检查间隔（秒）
    QR_CODE_EXPIRE_SECONDS = 110       # 二维码过期时间（秒）
    QR_CODE_REFUSE_OFFSET = 5          # 二维码拒绝时间偏移（秒，用于前端展示）
    FILE_LOCK_TIMEOUT = 5.0            # 文件锁获取超时（秒）
    BACKUP_TASK_JOIN_TIMEOUT = 10      # 停止时等待后台任务超时（秒）

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
    # 当前ip地址（可能为分号分隔的多个IP）
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
    # cookie失效通知已发送标志（防止重复通知）
    _cookie_invalid_notified = False
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
    # 后台任务列表（asyncio.Task）- 实例级，由 init_plugin 初始化
    _bg_tasks: Optional[List[asyncio.Task]] = None
    # 后台线程列表（用于无事件循环时启动）- 实例级
    _bg_threads: Optional[List[threading.Thread]] = None
    # 文件写入锁（线程锁，兼容多线程）
    _file_lock: threading.Lock = None
    # 二维码运行状态锁
    _qr_lock: threading.Lock = None
    # 通知去重锁
    _notify_lock: threading.Lock = None
    # 停止标志
    _stopping = False
    # 后台循环启动标志（防止重复启动）
    _loops_started = False

    # 类级别锁，用于串行化浏览器启动环境变量修改
    _browser_env_lock = threading.Lock()

    if hasattr(settings, 'VERSION_FLAG'):
        version = settings.VERSION_FLAG  # V2
    else:
        version = "v1"

    def init_plugin(self, config: dict = None):
        """
        插件初始化，读取配置，停止旧任务，启动新服务
        :param config: 插件配置字典
        """
        # 清空运行时状态（保留持久化数据）
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
        self._stopping = False
        self._loops_started = False
        self._cookie_invalid_notified = False

        # 初始化实例级后台任务容器
        if self._bg_tasks is None:
            self._bg_tasks = []
        if self._bg_threads is None:
            self._bg_threads = []

        # 初始化线程锁
        if self._file_lock is None:
            self._file_lock = threading.Lock()
        if self._qr_lock is None:
            self._qr_lock = threading.Lock()
        if self._notify_lock is None:
            self._notify_lock = threading.Lock()

        # 读取配置
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

        # 初始化通知发送器（兼容第三方）
        if self.version != "v1":
            self._my_send = MySender(self._notification_token, func=self.post_message)
        else:
            self._my_send = MySender(self._notification_token)

        if not self._my_send.init_success:
            self._my_send = None
        if self._my_send and not self._my_send.other_channel:
            self._await_ip = False

        # 处理多WAN口
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

        # 停止之前残留的任务，若未完全停止则跳过启动
        if not self.stop_service():
            logger.warning("仍有后台任务未退出，跳过启动新后台循环")
            self.__update_config()
            return

        # 重置停止标志，使新任务可以启动
        self._stopping = False
        self._loops_started = False

        # 配置检查
        if not self._input_id_list:
            logger.warning("插件未配置应用ID，请填写企业微信应用ID")
            self.__update_config()
            return

        # 启用插件时启动后台循环和一次性任务
        if (self._enabled or self._onlyonce) and self._input_id_list:
            self._start_background_loops()
            self._handle_once_tasks()

        self.__update_config()

    def _handle_once_tasks(self):
        """
        处理一次性任务（onlyonce / forced_update / local_scan）
        这些任务仅在用户点击保存或手动触发时执行一次
        """
        if self._onlyonce:
            if self.wan2:
                if not self._forced_update or not self._local_scan:
                    logger.info("多网络出口检查需要时间较长，预计25秒内完成")
                    # 顺序执行，避免 check 读取到旧的 wan2_url 或 IP 文件
                    async def run_wan2_once():
                        await self.write_wan2_ip()
                        if not self._stopping:
                            await self.check()
                    self._start_bg_task(run_wan2_once())
            else:
                if not self._forced_update or not self._local_scan:
                    self._start_bg_task(self.check())
            self._onlyonce = False

        if self._forced_update:
            if not self._local_scan:
                logger.info("使用Cookie,强制更新公网IP")
                self._start_bg_task(self.forced_change())
            self._forced_update = False

        if self._local_scan:
            logger.info("使用本地扫码登陆")
            self._start_bg_task(self.local_scanning())
            self._local_scan = False

    def _start_background_loops(self):
        """
        启动周期性后台循环任务（兼容有/无事件循环环境）
        防止重复启动，使用 _loops_started 标志控制
        """
        if self._loops_started:
            logger.debug("后台循环已启动，忽略重复调用")
            return
        self._loops_started = True

        # 无论有无循环，都通过 _start_bg_task 启动，它内部会处理
        self._start_bg_task(self._refresh_cookie_loop())
        if self._cron:
            self._start_bg_task(self._check_ip_loop())

    async def _refresh_cookie_loop(self):
        """
        周期性刷新cookie的后台循环
        使用CronTrigger计算下次执行时间，睡眠期间每1秒检查停止标志
        """
        tz = pytz.timezone(settings.TZ) if settings.TZ else pytz.utc
        try:
            trigger = CronTrigger.from_crontab(self._refresh_cron, timezone=tz)
        except Exception as e:
            logger.error(f"Cookie刷新定时器配置错误: {e}，任务退出")
            return
        while not self._stopping:
            if not self._enabled:
                break
            now = datetime.now(tz)
            next_time = trigger.get_next_fire_time(None, now)
            if not next_time:
                logger.error("无法计算下一次执行时间，Cookie刷新任务退出")
                break
            delay = (next_time - now).total_seconds()
            # 短睡眠轮询，及时响应停止信号
            while delay > 0 and not self._stopping and self._enabled:
                sleep_sec = min(delay, 1.0)
                await asyncio.sleep(sleep_sec)
                delay = (next_time - datetime.now(tz)).total_seconds()
            if self._stopping or not self._enabled:
                break
            try:
                await self.refresh_cookie()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"刷新cookie循环异常: {e}")
        logger.info("Cookie刷新循环已退出")

    async def _check_ip_loop(self):
        """
        周期性检查IP的后台循环
        多WAN模式时先刷新出口IP列表，再执行检查
        """
        tz = pytz.timezone(settings.TZ) if settings.TZ else pytz.utc
        try:
            trigger = CronTrigger.from_crontab(self._cron, timezone=tz)
        except Exception as e:
            logger.error(f"IP检测定时器配置错误: {e}，任务退出")
            return
        while not self._stopping:
            if not self._enabled:
                break
            now = datetime.now(tz)
            next_time = trigger.get_next_fire_time(None, now)
            if not next_time:
                logger.error("无法计算下一次执行时间，IP检测任务退出")
                break
            delay = (next_time - now).total_seconds()
            while delay > 0 and not self._stopping and self._enabled:
                sleep_sec = min(delay, 1.0)
                await asyncio.sleep(sleep_sec)
                delay = (next_time - datetime.now(tz)).total_seconds()
            if self._stopping or not self._enabled:
                break
            try:
                # 多WAN模式：先刷新出口IP
                if self.wan2:
                    await self.write_wan2_ip()
                await self.check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"IP检测循环异常: {e}")
        logger.info("IP检测循环已退出")

    def _start_bg_task(self, coro):
        """
        启动一个后台协程并自动跟踪（兼容有/无事件循环）
        有循环时创建Task，无循环时在新线程中运行并监控停止标志
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            self._bg_tasks.append(task)
            def cleanup(t):
                try:
                    if t in self._bg_tasks:
                        self._bg_tasks.remove(t)
                except ValueError:
                    pass
            task.add_done_callback(cleanup)
        except RuntimeError:
            # 无循环，在新线程中运行，并主动监控 _stopping 以取消协程
            def run():
                async def runner():
                    task = asyncio.create_task(coro)
                    try:
                        while not task.done():
                            if self._stopping:
                                task.cancel()
                                break
                            await asyncio.sleep(0.5)
                        await task
                    except asyncio.CancelledError:
                        logger.debug("后台协程已取消")
                    except Exception as e:
                        logger.error(f"后台协程执行失败: {e}")

                asyncio.run(runner())

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self._bg_threads.append(thread)

    async def _acquire_file_lock(self):
        """
        带超时的文件锁获取（非阻塞轮询）
        避免协程取消后锁未释放导致永久阻塞
        """
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.FILE_LOCK_TIMEOUT
            while not self._file_lock.acquire(blocking=False):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.warning("获取文件锁超时")
                    return False
                await asyncio.sleep(min(0.1, remaining))
            return True
        except Exception as e:
            logger.warning(f"获取文件锁异常: {e}")
            return False

    # ---------- 异步核心方法 ----------

    async def forced_change(self, event: Event = None):
        """
        强制修改IP（使用已保存的Cookie）
        事件触发入口，需检查 event_data 中的 action
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
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie = await self.get_cookie_async()
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
                self._cookie_invalid_notified = False
        except Exception as err:
            logger.error(f"强制修改IP失败: {err}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)
        logger.info("----------------------本次任务结束----------------------")

    async def local_scanning(self, event: Event = None):
        """
        本地扫码登录
        生成二维码并等待用户扫码，成功登录后更新Cookie并修改可信IP
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
            context = await self._launch_browser_context_with_retry(headless=True)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            img, _ = await self.find_qrc(page)
            if img:
                self.systemmessage.put("✅ 二维码已生成，请点击插件面板查看扫码")
                current_time = datetime.now()
                future_time = current_time + timedelta(seconds=self.QR_CODE_EXPIRE_SECONDS)
                self._future_timestamp = int(future_time.timestamp())
                logger.info("请重新进入插件面板扫码! 每20秒检查登录状态,最大尝试5次")
                for attempt in range(self.QR_CODE_MAX_ATTEMPTS):
                    # 短轮询，每1秒检查一次停止信号
                    for _ in range(self.QR_CODE_CHECK_INTERVAL):
                        if self._stopping:
                            logger.debug("收到停止信号，退出扫码等待")
                            return
                        await asyncio.sleep(1)
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
            logger.error(f"本地扫码任务失败: {e}")
        finally:
            self._qr_running = False
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def write_wan2_ip(self, event: Event = None):
        """
        获取多WAN出口IP并写入配置文件
        从多个IP检测网站轮流获取，成功则更新 wan2_url
        """
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
                context = await self._launch_browser_context_with_retry(headless=url != "https://ip.skk.moe/multi")
                page = await context.new_page()
                china_ips = await self.wan2.get_ipv4(page, url)
                if china_ips:
                    if await self._acquire_file_lock():
                        try:
                            await self.wan2.overwrite_ips_async("url_ip", china_ips)
                            self.wan2_url = url
                            break
                        finally:
                            self._file_lock.release()
                    else:
                        logger.warning(f"获取文件锁超时，放弃写入 {url} 的IP，尝试下一个")
                        continue
            except asyncio.CancelledError:
                logger.debug("任务被取消，放弃写入多WAN IP")
                return
            except asyncio.TimeoutError as e:
                logger.warning(f"{url} 多出口IP获取超时, Error: {e}")
                continue
            except Exception as e:
                logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
            finally:
                if context:
                    await context.close()
                    await asyncio.sleep(0.5)

    async def check(self, event: Event = None):
        """
        主检测任务（定时执行）
        根据cookie有效性决定是否检查IP，并依据配置决定是否立即通知
        """
        if not self._enabled:
            logger.error("插件未开启")
            return
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "dynamicwechat":
                return
        # 情况1：cookie有效，正常检测IP并更新
        if self._cookie_valid:
            logger.info("开始检测公网IP")
            if await self.CheckIP():
                await self.ChangeIP()
                self.__update_config()
            logger.info("----------------------本次任务结束----------------------")
            return
        # 情况2：cookie失效但启用了"IP变动后通知"
        if self._await_ip:
            logger.info("开始检测公网IP,等待IP变动后发送通知")
            if await self.CheckIP(func="public"):
                await self._send_cookie_false()
            logger.info("----------------------本次任务结束----------------------")
            return
        # 情况3：cookie失效且未启用延迟通知，立即通知
        logger.info("Cookie已失效，本次不检查IP")
        await self._send_cookie_false()

    async def CheckIP(self, func=None):
        """
        检测IP是否变化
        多WAN模式从配置文件读取已保存的IP列表，单IP模式直接从网络获取
        返回True表示IP已变化需要更新，否则False
        """
        if self.wan2:
            # 多WAN模式：读取保存的url_ip和ips
            if not await self._acquire_file_lock():
                logger.warning("获取文件锁超时，跳过IP检查")
                return False
            try:
                ip_address = await self.wan2.read_ips_async("url_ip")
                url = self.wan2_url
                saved_ips = await self.wan2.read_ips_async("ips")
            finally:
                self._file_lock.release()
            if not ip_address or ip_address == "获取IP失败" or not url:
                logger.error("获取IP失败 不操作可信IP")
                return False
            if url and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
            if not self._ip_changed and func != "public":
                logger.info("上次IP修改IP失败 继续尝试修改IP")
                return True
            if isinstance(ip_address, str):
                url_ips = [ip for ip in ip_address.split(";") if ip]
            else:
                url_ips = [ip for ip in ip_address if ip]
            if not url_ips:
                return False
            saved_ips_list = [ip for ip in saved_ips.split(";") if ip] if saved_ips else []
            need_add = False
            for ip in url_ips:
                if ip not in saved_ips_list:
                    need_add = True
                    break
            if need_add:
                if not await self._acquire_file_lock():
                    logger.warning("获取文件锁超时，无法添加新IP")
                    return False
                try:
                    for ip in url_ips:
                        if ip not in saved_ips_list:
                            await self.wan2.add_ips_async("ips", ip)
                finally:
                    self._file_lock.release()
                # 检测到IP变化，与单IP分支一致，标记微信通知不可用并重置通知标志
                self._wechat_available = False
                self._cookie_invalid_notified = False
                return True
            return False
        else:
            # 单IP模式：从网络获取当前公网IP
            url, ip_address = await self.get_ip_from_url()
            if not ip_address or ip_address == "获取IP失败" or not url:
                logger.error("获取IP失败 不操作可信IP")
                return False
            if url and ip_address:
                logger.info(f"IP获取成功: {url}: {ip_address}")
            if not self._ip_changed and func != "public":
                logger.info("上次IP修改IP失败 继续尝试修改IP")
                return True
            if ip_address != self._current_ip_address:
                logger.info("检测到IP变化")
                self._wechat_available = False
                self._cookie_invalid_notified = False  # 重置通知标志
                return True
        return False

    async def try_connect_cc_async(self):
        """异步连接CookieCloud服务器"""
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
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._cc_server.url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status != 200:
                        self._cc_server = None
                        logger.error("没有可用的CookieCloud服务器")
        except Exception as e:
            self._cc_server = None
            logger.error(f"CookieCloud连接失败: {e}")

    async def get_ip_from_url(self) -> (str, str):
        """
        从URL获取IP地址
        多WAN分支：锁失败则继续尝试下一个URL，避免返回未保存的数据
        """
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
                    context = await self._launch_browser_context_with_retry(headless=url != "https://ip.skk.moe/multi")
                    page = await context.new_page()
                    china_ips = await self.wan2.get_ipv4(page, url)
                    if china_ips:
                        if await self._acquire_file_lock():
                            try:
                                await self.wan2.overwrite_ips_async("url_ip", china_ips)
                                self.wan2_url = url
                                return url, china_ips
                            finally:
                                self._file_lock.release()
                        else:
                            logger.warning(f"获取文件锁超时，放弃写入 {url} 的IP，尝试下一个")
                            continue
                except asyncio.CancelledError:
                    logger.debug("任务被取消，放弃获取多WAN IP")
                    return None, "获取IP失败"
                except asyncio.TimeoutError as e:
                    logger.warning(f"{url} 多出口IP获取超时, Error: {e}")
                except Exception as e:
                    logger.warning(f"{url} 多出口IP获取失败, Error: {e}")
                finally:
                    if context:
                        await context.close()
                        await asyncio.sleep(0.5)
            self.wan2_url = None
            return None, "获取IP失败"

    async def find_qrc(self, page):
        """
        查找二维码图片
        返回二维码URL和过期时间，同时将图片数据保存到 _qr_code_image
        """
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
                refuse_time = (datetime.now() + timedelta(seconds=self.QR_CODE_EXPIRE_SECONDS + self.QR_CODE_REFUSE_OFFSET)).strftime("%Y-%m-%d %H:%M:%S")
                return qr_code_url, refuse_time
            else:
                logger.warning("未找到二维码")
                return None, None
        except asyncio.TimeoutError:
            logger.debug("iframe 等待超时（正常）")
            return None, None
        except Exception as e:
            logger.warning(f"查找二维码异常: {e}")
            return None, None

    async def ChangeIP(self):
        """
        修改可信IP
        若二维码出现说明cookie失效，转通知用户；否则直接修改
        """
        logger.info("开始请求企业微信管理更改可信IP")
        context = None
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie = await self.get_cookie_async()
            if cookie:
                await context.add_cookies(cookie)
            page = await context.new_page()
            await page.goto(self._wechatUrl)
            await asyncio.sleep(3)
            img_src, refuse_time = await self.find_qrc(page)
            if img_src:
                if self._my_send:
                    self._ip_changed = False
                    await self._send_cookie_false()
                    logger.info("已尝试发送cookie失效通知")
                else:
                    self._ip_changed = False
                    self._cookie_valid = False
                    self._cookie_invalid_notified = False
                    logger.info("cookie已失效,且没有配置通知方式,本次修改可信IP失败")
            else:
                logger.info("尝试cookie登录")
                if await self.check_login_status(page, ""):
                    await self.click_app_management_buttons(page)
                else:
                    logger.info("发生了意料之外的错误,请附上配置信息到github反馈")
                    await self._send_cookie_false()
                    self._ip_changed = False
        except Exception as e:
            self._ip_changed = False
            logger.error(f"更改可信IP失败: {e}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def _update_cookie(self, page, context):
        """
        更新cookie（使用线程锁保护文件操作）
        先从浏览器获取当前cookie，然后重置生命周期并同步到CookieCloud
        """
        self._future_timestamp = 0
        # 1. 先从浏览器获取cookie（即使云端更新失败，也标记cookie有效）
        try:
            current_url = page.url
            current_cookies = await context.cookies(current_url)
            if current_cookies:
                self._saved_cookie = current_cookies
                self._cookie_valid = True
                self._cookie_invalid_notified = False
                self._is_special_upload = True
                logger.info("从浏览器获取cookie成功")
            else:
                logger.error("无法从内置浏览器获取 cookies")
                self._cookie_valid = False
                self._cookie_invalid_notified = False
                return
        except Exception as e:
            logger.error(f"获取浏览器cookie失败: {e}")
            self._cookie_valid = False
            self._cookie_invalid_notified = False
            return
        # 2. 重置Cookie生命周期（可选步骤，超时不阻断）
        if await self._acquire_file_lock():
            try:
                await PyCookieCloud.save_cookie_lifetime_async(self._settings_file_path, 0)
            finally:
                self._file_lock.release()
        else:
            logger.warning("获取文件锁超时，跳过Cookie生命周期重置")
        # 3. 更新到CookieCloud（如果启用）
        if self._use_cookiecloud:
            if not self._cc_server:
                await self.try_connect_cc_async()
                if self._cc_server is None:
                    logger.warning("CookieCloud不可用，但本地cookie已保存")
                    return
            try:
                if not await self._cc_server.check_connection_async():
                    logger.error(f"连接 CookieCloud 失败: {self._cc_server.url}")
                    return
                formatted_cookies = {}
                for cookie in current_cookies:
                    domain = cookie.get('domain')
                    if domain is None:
                        continue
                    if domain not in formatted_cookies:
                        formatted_cookies[domain] = []
                    formatted_cookies[domain].append(cookie)
                update_success = await asyncio.to_thread(self._cc_server.update_cookie, formatted_cookies)
                if update_success:
                    logger.info("更新 CookieCloud 成功")
                    self._is_special_upload = True
                else:
                    logger.error("更新 CookieCloud 失败，但本地cookie已有效")
                    self._is_special_upload = False
            except Exception as e:
                logger.error(f"CookieCloud更新 cookie 发生错误: {e}")
        else:
            self._is_special_upload = False
            logger.info("更新本地 Cookie成功")

    async def _send_cookie_false(self):
        """
        发送cookie失效通知（异步版本），线程安全去重
        仅当某个通道发送成功后才持久标记，失败时保持可重试。
        """
        with self._notify_lock:
            if getattr(self, "_cookie_invalid_notified", False):
                return None
            # 占位，防止并发
            self._cookie_invalid_notified = True
            self._cookie_valid = False

        notified = False
        try:
            # 优先尝试微信通知（如果可用）
            if self._my_send and self._wechat_available:
                error = await asyncio.to_thread(
                    self._my_send.send,
                    title="cookie已失效,请及时更新",
                    content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。 如果使用'微信通知'请确保公网IP还没有变动",
                    image=None, force_send=False
                )
                if error:
                    logger.info(f"cookie失效通知发送失败,原因：{error}")
                else:
                    notified = True
                    return None

            # 如果微信不可用或发送失败，尝试第三方通知
            if self._my_send and self._my_send.other_channel:
                for channel, token in self._my_send.other_channel:
                    error = await asyncio.to_thread(
                        self._my_send.send,
                        title="cookie已失效,且微信通知失效",
                        content="请在企业微信应用发送/push_qr, 验证码以'？'结束发送到企业微信应用。",
                        image=None, force_send=False, diy_channel=channel, diy_token=token
                    )
                    if error:
                        logger.error(f"通道 {channel} 发送失败，原因：{error}")
                        continue
                    notified = True
                    return None
                self.systemmessage.put("cookie已失效，且所有通知方式均发送失败，请手动更新cookie")
                return None

            # 如果微信不可用且没有第三方通道，补充系统消息和日志，避免静默丢失
            if self._my_send and not self._wechat_available and not self._my_send.other_channel:
                logger.warning("微信通知不可用且未配置第三方通知通道，无法发送cookie失效通知")
                self.systemmessage.put("cookie已失效，但微信通知不可用且未配置第三方通知通道，请手动更新cookie")
                return None

            if not self._my_send:
                logger.warning("cookie已失效，但未配置任何通知方式，用户可能无法及时感知")
                self.systemmessage.put("cookie已失效，请及时更新，当前未配置通知方式")
                return None

            return None
        finally:
            if not notified:
                with self._notify_lock:
                    self._cookie_invalid_notified = False

    async def _push_qr_code_async(self, event: Event = None):
        """
        异步推送二维码（使用线程锁保护状态）
        生成二维码并通过配置的通知渠道发送给用户
        """
        if not self._enabled or not event:
            return
        if not self._qr_lock.acquire(blocking=False):
            logger.info("二维码推送任务正在执行，忽略重复触发")
            return
        try:
            self._qr_running = True
            context = None
            try:
                context = await self._launch_browser_context_with_retry(headless=True)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                image_src, refuse_time = await self.find_qrc(page)
                if image_src:
                    if self._my_send:
                        # 微信可用时直接发送，不可用时尝试第三方
                        if self._wechat_available:
                            error = await asyncio.to_thread(self._my_send.send, "企业微信登录二维码", image=image_src)
                            if error:
                                logger.info(f"远程推送任务: 二维码发送失败,原因：{error}")
                                logger.info("----------------------本次任务结束----------------------")
                                return
                        else:
                            # 微信不可用，检查是否有第三方通道
                            if not self._my_send.other_channel:
                                logger.warning("微信通知不可用且未配置第三方通知通道，无法推送二维码")
                                self.systemmessage.put("微信通知不可用且未配置第三方通知通道，无法推送二维码")
                                logger.info("----------------------本次任务结束----------------------")
                                return
                            # 尝试所有第三方通道
                            sent = False
                            for channel, token in self._my_send.other_channel:
                                error = await asyncio.to_thread(
                                    self._my_send.send,
                                    title="企业微信登录二维码",
                                    image=image_src, diy_channel=channel, diy_token=token
                                )
                                if not error:
                                    sent = True
                                    break
                                logger.warning(f"通道 {channel} 推送二维码失败，原因：{error}")
                            if not sent:
                                logger.warning("所有第三方通知通道推送二维码均失败")
                                logger.info("----------------------本次任务结束----------------------")
                                return
                        # 发送成功，开始等待扫码
                        logger.info("远程推送任务: 二维码发送成功,等待用户 80 秒内扫码登录。V2'微信通知'的用户,此消息并不准确")
                        for attempt in range(self.QR_CODE_MAX_ATTEMPTS):
                            # 短轮询检查停止信号
                            for _ in range(self.QR_CODE_CHECK_INTERVAL):
                                if self._stopping:
                                    logger.debug("收到停止信号，退出扫码等待")
                                    return
                                await asyncio.sleep(1)
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
                logger.error(f"远程推送任务失败: {e}")
            finally:
                if context:
                    await context.close()
                    await asyncio.sleep(0.5)
                self._qr_running = False
        finally:
            self._qr_lock.release()

    async def get_cookie_async(self):
        """
        异步获取企业微信 Cookie
        优先使用本地缓存，否则从CookieCloud下载
        """
        if self._saved_cookie and self._cookie_valid:
            return self._saved_cookie
        try:
            if not self._use_cookiecloud:
                return None
            cookies, msg = await asyncio.to_thread(self._cookiecloud.download)
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
        """解析cookie头，返回格式化的cookie列表"""
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
        """
        保活：刷新cookie（增强重试逻辑）
        若本地cookie失效，从CookieCloud获取新cookie；若仍无效，根据 _await_ip 决定是否立即通知
        """
        context = None
        try:
            context = await self._launch_browser_context_with_retry(headless=True)
            cookie_used = False
            # 尝试使用本地保存的cookie
            if self._saved_cookie:
                await context.add_cookies(self._saved_cookie)
                page = await context.new_page()
                await page.goto(self._wechatUrl)
                await asyncio.sleep(3)
                if await self.check_login_status(page, task='refresh_cookie'):
                    self._cookie_valid = True
                    self._cookie_invalid_notified = False
                    cookie_used = True
                else:
                    self._cookie_valid = False
                    self._saved_cookie = None
                    # 本地失效，若启用CookieCloud则暂不通知，等待云端尝试
                    if self._use_cookiecloud:
                        logger.info("本地缓存 Cookie 失效，尝试从 CookieCloud 获取")
                    elif self._await_ip and self._wechat_available:
                        logger.info("Cookie失效，等待公网IP变动后再通知")
                    else:
                        await self._send_cookie_false()
            # 若本地cookie无效，尝试从CookieCloud获取
            if not cookie_used and self._use_cookiecloud:
                cookie = await self.get_cookie_async()
                if cookie:
                    await context.add_cookies(cookie)
                    page = await context.new_page()
                    await page.goto(self._wechatUrl)
                    await asyncio.sleep(3)
                    if await self.check_login_status(page, task='refresh_cookie'):
                        self._cookie_valid = True
                        self._cookie_invalid_notified = False
                        self._saved_cookie = await context.cookies()
                    else:
                        self._cookie_valid = False
                        self._saved_cookie = None
                        if self._await_ip and self._wechat_available:
                            logger.info("Cookie失效，等待公网IP变动后再通知")
                        else:
                            await self._send_cookie_false()
                else:
                    self._cookie_valid = False
                    self._saved_cookie = None
                    if self._await_ip and self._wechat_available:
                        logger.info("Cookie失效，等待公网IP变动后再通知")
                    else:
                        await self._send_cookie_false()
            # 如果cookie有效，延长生命周期
            if self._cookie_valid:
                if self._my_send:
                    self._my_send.reset_limit()
                if await self._acquire_file_lock():
                    try:
                        await PyCookieCloud.increase_cookie_lifetime_async(self._settings_file_path, 600)
                    finally:
                        self._file_lock.release()
                else:
                    logger.warning("获取文件锁超时，跳过增加Cookie生命周期")
                self._cookie_lifetime = await PyCookieCloud.load_cookie_lifetime_async(self._settings_file_path)
        except Exception as e:
            logger.error(f"cookie 校验过程中发生异常: {e}")
        finally:
            if context:
                await context.close()
                await asyncio.sleep(0.5)

    async def check_login_status(self, page, task):
        """
        检查登录状态，支持验证码输入
        根据任务类型（refresh_cookie / local_scanning / push_qr_code）执行不同逻辑
        """
        await asyncio.sleep(3)
        if task != 'refresh_cookie':
            logger.info("检查登录状态...")
        # 移除无效的XPath选择器，仅保留有效CSS或XPath
        success_selectors = [
            "//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']",
            '#_hmt_click > div.index_colRight > div > div.index_info > div > a',
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
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"选择器查询异常: {e}")
                    continue
        except Exception as e:
            logger.debug(f"登录检查异常: {e}")
        try:
            captcha_panel = await page.wait_for_selector('.receive_captcha_panel', timeout=5000)
            if captcha_panel:
                if task == 'local_scanning':
                    await asyncio.sleep(3)
                else:
                    logger.info("等待30秒,请将短信验证码请以'？'结束,发送到<企业微信应用> 如： 110301？")
                    for _ in range(30):
                        if self._stopping:
                            return False
                        await asyncio.sleep(1)
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
                            except asyncio.TimeoutError:
                                continue
                            except Exception:
                                continue
                else:
                    logger.error("未收到短信验证码，请以问号结尾发送到企业微信应用。如：510010? 使用全局AI助手需使用/wxcode 510010的格式发送验证码")
                    return False
        except asyncio.TimeoutError:
            pass
        except Exception:
            img_src, _ = await self.find_qrc(page)
            if img_src and task not in ['refresh_cookie', 'local_scanning']:
                logger.warning("用户没有扫描二维码")
                return False
        return False

    async def click_app_management_buttons(self, page):
        """
        点击应用管理按钮，填入可信IP
        多WAN口时将所有出口IP用分号拼接，符合企业微信支持多IP的格式（最多120个）
        若获取IP失败则中止更新
        """
        self._cookie_valid = True
        self._cookie_invalid_notified = False
        if self._my_send:
            self._my_send.reset_limit()
        bash_url = "https://work.weixin.qq.com/wework_admin/frame#apps/modApiApp/"
        buttons = [
            ("//div[contains(@class, 'js_show_ipConfig_dialog')]//a[contains(@class, '_mod_card_operationLink') and text()='配置']", "配置")
        ]
        # 获取当前IP地址
        if self.wan2:
            ips_str = await self.wan2.read_ips_async("ips")
            ips_list = [ip for ip in ips_str.split(";") if ip] if ips_str else []
            if ips_list:
                self._current_ip_address = ";".join(ips_list)
                logger.info(f"多WAN口检测到 {len(ips_list)} 个出口IP，全部填入可信IP")
            else:
                _, self._current_ip_address = await self.get_ip_from_url()
                logger.warning("多WAN口未检测到有效IP，重新获取")
        else:
            _, self._current_ip_address = await self.get_ip_from_url()

        # 校验IP有效性
        ip_values = [ip for ip in str(self._current_ip_address).split(";") if ip]
        if not ip_values or self._current_ip_address == "获取IP失败":
            self._ip_changed = False
            logger.error("未获取到有效公网IP，取消更新可信IP")
            self.systemmessage.put("未获取到有效公网IP，取消更新可信IP，请检查网络或稍后重试")
            return

        # 解析应用ID列表
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
                # 保存到配置文件
                if await self._acquire_file_lock():
                    try:
                        await self.cfg.aupdate("WECHAT_NOW_IP", self._current_ip_address)
                    finally:
                        self._file_lock.release()
                else:
                    logger.warning("获取文件锁超时，跳过更新本地配置")
                self._wechat_available = True
                self._send_notification = False
                masked_ips = [self.mask_ip(ip) for ip in self._current_ip_address.split(';')]
                masked_ip_string = ";".join(masked_ips)
                logger.info(f"应用: {app_id} 输入IP：" + self._current_ip_address)
                if self._my_send and not self._my_send.quiet_flag:
                    await asyncio.to_thread(
                        self._my_send.send,
                        title="更新可信IP成功",
                        content='应用: ' + app_id + ' 输入IP：' + masked_ip_string,
                        force_send=True, diy_channel="WeChat"
                    )

    @staticmethod
    def mask_ip(ip):
        """IP地址脱敏，保留第一段和最后一段，中间用星号代替"""
        ip_parts = ip.split('.')
        if len(ip_parts) == 4:
            masked_ip = f"{ip_parts[0]}.{len(ip_parts[1]) * '*'}.{len(ip_parts[2]) * '*'}.{ip_parts[3]}"
            return masked_ip
        return ip

    def __update_config(self):
        """保存插件配置到系统"""
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
        """返回插件启用状态"""
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，返回页面JSON和默认模型
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
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即检测一次'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'forced_update', 'label': '强制更新IP'}}
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
                                    {'component': 'VSwitch', 'props': {'model': 'use_cookiecloud', 'label': '使用CookieCloud'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 4},
                                'content': [
                                    {'component': 'VSwitch', 'props': {'model': 'local_scan', 'label': '本地扫码修改IP'}}
                                ]
                            },
                            *(
                                [{
                                    'component': 'VCol',
                                    'props': {'cols': 12, 'md': 4},
                                    'content': [
                                        {'component': 'VSwitch', 'props': {'model': 'await_ip', 'label': 'IP变动后通知'}}
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
                                    {'component': 'VTextField', 'props': {'model': 'cron', 'label': '[必填]检测周期', 'placeholder': '0 * * * *'}}
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {'component': 'VTextarea', 'props': {'model': 'notification_token', 'label': '[可选] 通知方式', 'rows': 1, 'placeholder': '支持微信、Server酱、PushPlus、AnPush等Token或API'}}
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
                                    {'component': 'VTextarea', 'props': {'model': 'input_id_list', 'label': '[必填]应用ID', 'rows': 1, 'placeholder': '输入应用ID,多个ID用英文逗号分隔。在企业微信应用页面URL末尾获取'}}
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
                                    {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal', 'text': '建议启用内建或自定义CookieCloud。支持微信和Server酱等第三方通知。具体请查看作者主页'}}
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
                                    {'component': 'VAlert', 'props': {'type': 'info', 'text': 'Cookie失效时通知用户，用户使用/push_qr让插件推送二维码。使用第三方通知时填写对应Token/API'}}
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
            "forced_update": False,
            "use_cookiecloud": True,
            "local_scan": False,
            "await_ip": False,
            "cookie_header": "",
            "notification_token": "",
            "input_id_list": ""
        }

    def get_page(self) -> List[dict]:
        """
        生成插件详情页（显示二维码和Cookie寿命）
        """
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

    # ---------- 统一事件入口 ----------
    @eventmanager.register(EventType.PluginAction)
    def dynamicwechat_event(self, event: Event = None):
        """
        统一事件分发入口，根据 sub_action 调用不同方法
        """
        if not self._enabled or not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "dynamicwechat":
            return
        sub_action = event_data.get("sub_action", "check")
        if sub_action == "forced_change":
            self._start_bg_task(self.forced_change(None))
        elif sub_action == "local_scanning":
            self._start_bg_task(self.local_scanning(None))
        elif sub_action == "write_wan2_ip":
            self._start_bg_task(self.write_wan2_ip(None))
        elif sub_action == "wxcode":
            raw = event_data.get("arg_str") or ""
            match = re.search(r"\d{6}", raw)
            if match and self._qr_running:
                code = match.group(0)
                if getattr(self, "_last_code", None) != code:
                    self._last_code = code
                    self._verification_code = code
                    logger.info(f"收到验证码：{code}")
        else:
            self._start_bg_task(self.check(None))

    @eventmanager.register(EventType.PluginAction)
    def push_qr_code_event(self, event: Event = None):
        """
        立即推送二维码的事件入口
        """
        if not self._enabled or not event:
            return
        event_data = event.event_data
        if not event_data or event_data.get("action") != "push_qrcode":
            return
        self._start_bg_task(self._push_qr_code_async(event))

    @eventmanager.register(EventType.UserMessage)
    def talk(self, event: Event):
        """
        监听用户消息，接收验证码（以问号结尾）
        """
        if not self._enabled:
            return
        if not self._qr_running:
            return
        text = (event.event_data or {}).get("text") or ""
        # 严格匹配以 ? 或 ？ 结尾的6位数字验证码
        match = re.fullmatch(r"(\d{6})[?？]", text.strip())
        if match:
            code = match.group(1)
            if code != self._last_code:
                self._verification_code = code
                self._last_code = code
                logger.info(f"收到验证码：{code}")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册插件命令
        """
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
                "data": {"action": "dynamicwechat", "sub_action": "wxcode"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self) -> bool:
        """
        停止所有后台任务和线程。
        对于当前事件循环中的任务，取消并加入 pending，确保旧任务清理完成前不会启动新循环。
        返回 True 表示认为所有任务已清理（可重载），False 表示仍有残留。
        """
        self._stopping = True

        # 检测当前事件循环
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # 收集按事件循环分组的未完成任务
        tasks_by_loop = {}
        for task in list(getattr(self, "_bg_tasks", []) or []):
            if not task.done():
                try:
                    loop = task.get_loop()
                    tasks_by_loop.setdefault(loop, []).append(task)
                except RuntimeError:
                    # 无法获取循环，直接取消并视为 pending
                    task.cancel()
                    if not task.done():
                        tasks_by_loop.setdefault(None, []).append(task)

        pending_tasks = []
        async def cancel_and_wait(tasks):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        for loop, tasks in tasks_by_loop.items():
            if loop is None or loop.is_closed() or not loop.is_running():
                # 循环不可用，仅取消
                for task in tasks:
                    task.cancel()
                pending_tasks.extend([task for task in tasks if not task.done()])
                continue

            if loop is current_loop:
                # 当前循环无法同步等待，保留为 pending，避免旧任务清理完成前启动新循环
                for task in tasks:
                    def cleanup(t):
                        try:
                            if t in self._bg_tasks:
                                self._bg_tasks.remove(t)
                        except ValueError:
                            pass
                    task.cancel()
                    task.add_done_callback(cleanup)
                pending_tasks.extend([task for task in tasks if not task.done()])
                continue

            # 不同循环，可安全等待
            try:
                future = asyncio.run_coroutine_threadsafe(cancel_and_wait(tasks), loop)
                future.result(timeout=self.BACKUP_TASK_JOIN_TIMEOUT)
            except Exception:
                pending_tasks.extend([task for task in tasks if not task.done()])

        self._bg_tasks = pending_tasks

        # 等待后台线程退出
        alive_threads = []
        for thread in list(getattr(self, "_bg_threads", []) or []):
            if thread.is_alive():
                thread.join(timeout=self.BACKUP_TASK_JOIN_TIMEOUT)
            if thread.is_alive():
                alive_threads.append(thread)
        self._bg_threads = alive_threads

        if pending_tasks:
            logger.warning(f"{len(pending_tasks)} 个异步任务尚未完成取消")
        if alive_threads:
            logger.warning(f"{len(alive_threads)} 个后台线程未在超时时间内退出")
        if pending_tasks or alive_threads:
            return False
        return True

    async def _launch_browser_context_with_retry(self, headless: bool = True):
        """
        使用 CloakBrowser 异步启动企业微信页面上下文，支持重试机制。
        使用类级别锁串行化环境变量修改，避免并发冲突。
        锁等待时间计入总超时预算。
        """
        last_exception = None
        env_lock = self.__class__._browser_env_lock
        for attempt in range(1, self.BROWSER_RETRY_COUNT + 1):
            lock_acquired = False
            original_dbus = None
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.BROWSER_LAUNCH_TIMEOUT
                # 非阻塞轮询获取锁，计入超时预算
                while not env_lock.acquire(blocking=False):
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    await asyncio.sleep(min(0.1, remaining))
                lock_acquired = True
                # 计算剩余超时预算
                remaining_timeout = deadline - loop.time()
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError
                # 临时置空 D-Bus 地址，避免 Docker 中无服务报错
                original_dbus = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
                os.environ['DBUS_SESSION_BUS_ADDRESS'] = ''
                # 启动浏览器
                context = await asyncio.wait_for(
                    launch_context_async(
                        headless=headless,
                        args=['--lang=zh-CN'],
                        extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.1'}
                    ),
                    timeout=remaining_timeout
                )
                if attempt > 1:
                    logger.info(f"浏览器启动成功 (第 {attempt} 次尝试)")
                return context
            except asyncio.TimeoutError:
                last_exception = Exception("浏览器启动超时（30秒）")
                logger.warning(f"浏览器启动超时 (尝试 {attempt}/{self.BROWSER_RETRY_COUNT})")
            except Exception as e:
                last_exception = e
                logger.warning(f"浏览器启动失败 (尝试 {attempt}/{self.BROWSER_RETRY_COUNT}): {e}")
            finally:
                if lock_acquired:
                    # 恢复 D-Bus 环境变量
                    if original_dbus is not None:
                        os.environ['DBUS_SESSION_BUS_ADDRESS'] = original_dbus
                    else:
                        os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)
                    env_lock.release()
            if attempt < self.BROWSER_RETRY_COUNT:
                await asyncio.sleep(self.BROWSER_RETRY_DELAY)
                logger.info(f"等待 {self.BROWSER_RETRY_DELAY} 秒后重试...")
        logger.error(f"浏览器启动失败，已重试 {self.BROWSER_RETRY_COUNT} 次: {last_exception}")
        raise last_exception