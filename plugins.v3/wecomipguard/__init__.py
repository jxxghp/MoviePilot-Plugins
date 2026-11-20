"""
企业微信应用可信 IP 自动维护插件。

设计目标（相对社区版 WeWorkIPCB 的改进）：
1. IP 获取：只使用稳定可用的 IPv4 专用源，并按 IPv4 严格校验，避免拿到 IPv6 或误匹配。
2. Cookie 保活：先用纯 HTTP 探活判断 cookie 是否有效，有效则完全跳过 Chromium 启动，
   把每 5 分钟一次的内核启动开销降到接近 0；只有在 HTTP 探活失败时才启动浏览器复核。
3. IP 同步：cookie 失效不再无声跳过 IP 同步；改为记录待同步状态，cookie 恢复后立即补写。
4. 可观测：内存中保存最近一次 IP 检测/同步结果，插件页面直接展示，便于排查。
5. 可配置：cookie 保活间隔、IP 检测间隔、IP 源、超时时间均可配置。

依赖的浏览器内核 cloakbrowser 由 MoviePilot V3 运行时镜像提供。
"""

import os
import re
import time
import ipaddress
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.sdk.events import eventmanager, Event
from app.schemas.types import EventType, NotificationChannel, MessageType
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase
from app.sdk.config import settings
from app.adapters.external.cookiecloud import CookieCloudHelper

try:
    from cloakbrowser import launch as cloak_launch
    _cloak_import_error = None
except Exception as err:  # pragma: no cover - 取决于运行时镜像
    cloak_launch = None
    _cloak_import_error = err


class WeComIPGuard(_PluginBase):
    # ---- 插件元数据 ----
    plugin_name = "企业微信可信IP助手"
    plugin_desc = (
        "自动检测动态公网 IP 并同步到企业微信（WeCom / 企微）应用的可信IP白名单，"
        "解决企业微信应用「not allow to access from your ip」报错。"
        "支持 IPv4 严格校验、CookieCloud、扫码登录、手机验证码、Cookie 保活与待同步自动补写。"
    )
    plugin_icon = "wecomipguard.png"
    plugin_version = "1.1.0"
    plugin_author = "workroom2008"
    author_url = "https://github.com/workroom2008"
    plugin_config_prefix = "wecomipguard_"
    plugin_order = 20
    auth_level = 1

    # ---- 常量 ----
    # 只匹配 IPv4，且做范围校验，避免把版本号、时间戳误判成 IP
    _ipv4_pattern = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
    # 默认 IP 源：全部为实测可用的 IPv4 专用/优先接口
    _default_ip_urls = [
        "https://ddns.oray.com/checkip",
        "https://ipv4.icanhazip.com",
        "https://v4.ipip.net",
        "https://ipinfo.io/ip",
    ]
    # 企微管理页登录态特征：未登录时页面会包含该选择器对应节点
    _login_marker = "login_stage_title_text"
    _qr_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "QR.png")

    def __init__(self):
        super().__init__()
        # ---- 配置项 ----
        self._enabled = False
        self._onlyonce = False
        self._notify = True
        self._debug = False
        self._check_cron = "*/11 * * * *"
        self._keepalive_cron = "*/5 * * * *"
        self._status_cron = "0 * * * *"
        self._wechat_url = ""
        self._cookie_header = ""
        self._qr_send_users = ""
        self._overwrite = True
        self._use_cookiecloud = True
        self._schedule_login = False
        self._ip_urls_text = ""
        self._http_timeout = 15
        self._browser_timeout = 180

        # ---- 运行时状态（不持久化）----
        self._urls: List[str] = []
        self._current_ip = ""
        self._cookie_valid = False
        self._cookie_from_cloud: Any = ""
        self._pending_sync = False
        self._code = 0
        self._scheduler: Optional[BackgroundScheduler] = None
        self._cookiecloud = CookieCloudHelper()

        # ---- 最近一次执行结果，用于页面展示 ----
        self._ip_source = ""
        self._ip_checked_at = ""
        self._ip_error = ""
        self._sync_at = ""
        self._sync_result = ""
        self._sync_detail: List[str] = []
        self._last_probe_mode = ""

    # ------------------------------------------------------------------ 生命周期
    def init_plugin(self, config: dict = None):
        """加载配置并启动调度器。"""
        self._reset_config()
        if config:
            self._load_config(config)

        self._urls = [u.strip() for u in (self._wechat_url or "").split(",") if u.strip()]

        self.stop_service()

        if not (self._enabled or self._onlyonce):
            self.__save_config()
            return

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)

        if self._onlyonce:
            self._scheduler.add_job(
                func=self.check_ip,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="立即检测公网IP",
            )
            self._onlyonce = False

        # 保活任务：首次启动若 cookie 未标记有效，先跑一次探活
        if self._cookie_valid:
            self.create_keepalive_job()
        else:
            self._scheduler.add_job(
                func=self.keepalive_cookie,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=2),
                name="初始化探活Cookie",
            )

        if not self._schedule_login:
            self._scheduler.add_job(
                func=self.send_cookie_status,
                trigger=CronTrigger.from_crontab(self._status_cron),
                name="Cookie失效通知",
                id="send_status",
            )
            if not self._cookie_valid:
                self._scheduler.add_job(
                    func=self.send_cookie_status,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=5),
                    name="初始化失效通知",
                )

        if self._scheduler.get_jobs():
            self._scheduler.start()

        self.__save_config()

    def _reset_config(self):
        self._enabled = False
        self._onlyonce = False
        self._notify = True
        self._debug = False
        self._check_cron = "*/11 * * * *"
        self._keepalive_cron = "*/5 * * * *"
        self._status_cron = "0 * * * *"
        self._wechat_url = ""
        self._cookie_header = ""
        self._qr_send_users = ""
        self._overwrite = True
        self._use_cookiecloud = True
        self._schedule_login = False
        self._ip_urls_text = ""
        self._http_timeout = 15
        self._browser_timeout = 180
        self._cookie_valid = False
        self._pending_sync = False
        self._urls = []
        self._cookie_from_cloud = ""
        # 调度器交由 init_plugin/stop_service 管理，这里显式置空便于重复初始化
        self._scheduler = None
        # 运行态字段一并重置，避免复用实例时残留上一轮的展示状态
        self._current_ip = ""
        self._ip_source = ""
        self._ip_checked_at = ""
        self._ip_error = ""
        self._sync_at = ""
        self._sync_result = ""
        self._sync_detail = []
        self._last_probe_mode = ""

    def _load_config(self, config: dict):
        """从持久化配置恢复字段，缺省值保持默认。"""
        self._enabled = bool(config.get("enabled", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._notify = bool(config.get("notify", True))
        self._debug = bool(config.get("debug", False))
        self._check_cron = config.get("check_cron") or "*/11 * * * *"
        self._keepalive_cron = config.get("keepalive_cron") or "*/5 * * * *"
        self._status_cron = config.get("status_cron") or "0 * * * *"
        self._wechat_url = config.get("wechat_url") or ""
        self._cookie_header = config.get("cookie_header") or ""
        self._qr_send_users = config.get("qr_send_users") or ""
        self._overwrite = bool(config.get("overwrite", True))
        self._use_cookiecloud = bool(config.get("use_cookiecloud", True))
        self._schedule_login = bool(config.get("schedule_login", False))
        self._ip_urls_text = config.get("ip_urls") or ""
        self._http_timeout = self._as_int(config.get("http_timeout"), 15)
        self._browser_timeout = self._as_int(config.get("browser_timeout"), 180)
        self._cookie_valid = bool(config.get("cookie_valid", False))
        self._pending_sync = bool(config.get("pending_sync", False))
        self._cookie_from_cloud = config.get("cookie_list") or ""

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number > 0 else default

    def stop_service(self):
        """退出插件，释放调度器与浏览器。"""
        try:
            if self._scheduler:
                if self._scheduler.running:
                    self._scheduler.shutdown(wait=False)
                self._scheduler = None
        except Exception as err:
            logger.error(f"停止企业微信可信IP守护调度器失败：{err}")

    # ------------------------------------------------------------------ IP 获取
    @property
    def _ip_sources(self) -> List[str]:
        """优先使用用户配置的 IP 源，未配置时用内置可用源。"""
        if self._ip_urls_text.strip():
            return [u.strip() for u in self._ip_urls_text.split(",") if u.strip()]
        return list(self._default_ip_urls)

    @staticmethod
    def _parse_ipv4(text: str) -> Optional[str]:
        """从文本中提取第一个合法 IPv4；不做正则就直接相信结果。"""
        if not text:
            return None
        for match in WeComIPGuard._ipv4_pattern.finditer(text):
            candidate = match.group(1)
            try:
                addr = ipaddress.IPv4Address(candidate)
            except ipaddress.AddressValueError:
                continue
            # 过滤保留地址，避免拿到内网/回环/文档地址
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                continue
            if addr.is_multicast or addr.is_reserved or addr.is_unspecified:
                continue
            return str(addr)
        return None

    def fetch_public_ip(self) -> Optional[str]:
        """依次尝试各 IP 源，返回第一个有效 IPv4。"""
        for url in self._ip_sources:
            try:
                response = requests.get(url, timeout=self._http_timeout)
                if response.status_code != 200:
                    if self._debug:
                        logger.warning(f"IP源 {url} 返回状态码 {response.status_code}")
                    continue
                ip = self._parse_ipv4(response.text)
                if ip:
                    self._ip_source = url
                    return ip
                if self._debug:
                    logger.warning(f"IP源 {url} 未解析出IPv4：{response.text[:80]!r}")
            except Exception as err:
                if self._debug:
                    logger.warning(f"IP源 {url} 请求失败：{err}")
                continue
        return None

    def check_ip(self, event: Event = None):
        """IP 检测入口：解析公网 IP，变化则触发同步。"""
        if not self._enabled:
            logger.warning("插件未启用，跳过IP检测")
            return

        self._ip_checked_at = self._now()
        ip = self.fetch_public_ip()
        if not ip:
            self._ip_error = "所有IP源均不可用"
            logger.error("获取公网IP失败：所有IP源均不可用")
            if event and self._notify:
                self.post_message(
                    channel=self._event_channel(event),
                    mtype=MessageType.Plugin,
                    title="公网IP获取失败",
                    text="所有IP源均不可用，请检查网络或在插件配置中更换IP源。",
                    userid=self._qr_send_users,
                )
            return

        self._ip_error = ""
        logger.info(f"当前公网IP：{ip}（来源 {self._ip_source}）")

        if ip == self._current_ip and not self._pending_sync:
            if event and self._notify:
                self.post_message(
                    channel=self._event_channel(event),
                    mtype=MessageType.Plugin,
                    title=f"公网IP未变化：{ip}",
                    userid=self._qr_send_users,
                )
            return

        changed = ip != self._current_ip
        self._current_ip = ip
        if changed:
            logger.info("检测到公网IP变化，准备同步到企业微信")
        elif self._pending_sync:
            logger.info("存在待同步IP，继续尝试同步")

        self._pending_sync = True
        self.__save_config()
        # 只有 IP 真的变化或存在待同步时才写企微，避免无意义地启动浏览器
        self.sync_trusted_ip(notify=False)

        if event and self._notify:
            self.post_message(
                channel=self._event_channel(event),
                mtype=MessageType.Plugin,
                title="IP检测完成",
                text=f"当前IP：{ip}\n同步结果：{self._sync_result or '未执行'}",
                userid=self._qr_send_users,
            )

    # ------------------------------------------------------------------ Cookie
    def _cookie_pairs(self) -> Dict[str, str]:
        """
        汇总当前可用的 cookie。

        优先级：浏览器/CookieCloud 已保存的列表 > 手动填写的 HeaderString。
        两者都没有时，若开启 CookieCloud 则实时拉取一次。
        """
        raw = self._cookie_from_cloud
        pairs: Dict[str, str] = {}
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("name"):
                    pairs[str(item["name"])] = str(item.get("value", ""))
        if pairs:
            return pairs

        if self._cookie_header:
            return self._parse_cookie_header(self._cookie_header)

        if self._use_cookiecloud:
            fetched = self._fetch_cookiecloud()
            if fetched:
                self._cookie_from_cloud = [
                    {
                        "name": name,
                        "value": value,
                        "domain": ".work.weixin.qq.com",
                        "path": "/",
                    }
                    for name, value in fetched.items()
                ]
                self.__save_config()
                return fetched
        return {}

    @staticmethod
    def _parse_cookie_header(header: str) -> Dict[str, str]:
        """把 `a=1; b=2` 形式的 HeaderString 解析成字典。"""
        pairs: Dict[str, str] = {}
        for chunk in (header or "").split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            name, value = chunk.split("=", 1)
            name = name.strip()
            if name:
                pairs[name] = value.strip()
        return pairs

    def _fetch_cookiecloud(self) -> Optional[Dict[str, str]]:
        """从 CookieCloud 拉取企业微信域名的 cookie。"""
        try:
            logger.info("尝试从CookieCloud同步企业微信cookie")
            cookies, message = self._cookiecloud.download()
        except Exception as err:
            logger.error(f"CookieCloud请求异常：{err}")
            return None
        if not cookies:
            logger.warning(f"CookieCloud未返回数据：{message}")
            return None
        for domain, value in cookies.items():
            if "work.weixin.qq.com" not in str(domain):
                continue
            if isinstance(value, str):
                return self._parse_cookie_header(value)
            if isinstance(value, list):
                return {
                    str(item.get("name")): str(item.get("value", ""))
                    for item in value
                    if isinstance(item, dict) and item.get("name")
                }
        logger.warning("CookieCloud中没有企业微信域名的cookie")
        return None

    def probe_cookie_http(self) -> Optional[bool]:
        """
        纯 HTTP 探活：用 cookie 请求管理页，按登录标记判断有效性。

        返回 True=有效，False=失效，None=无法判定（网络异常等）。
        有效时顺手把响应里的 Set-Cookie 合并回本地，实现无需浏览器的 cookie 续期，
        把常态保活成本从一次 Chromium 启动降到一次普通 HTTP 请求。
        """
        pairs = self._cookie_pairs()
        if not pairs or not self._urls:
            return None
        try:
            session = requests.Session()
            session.cookies.update(pairs)
            response = session.get(self._urls[0], timeout=self._http_timeout)
        except Exception as err:
            if self._debug:
                logger.warning(f"HTTP探活失败：{err}")
            return None
        if response.status_code != 200:
            return None

        self._merge_response_cookies(response, pairs)
        return self._login_marker not in response.text

    def _merge_response_cookies(self, response, pairs: Dict[str, str]):
        """把响应 Set-Cookie 中的续期值合并进持久化 cookie。"""
        try:
            refreshed = dict(pairs)
            changed = False
            for name, value in response.cookies.items():
                if not name:
                    continue
                if refreshed.get(name) != value:
                    refreshed[name] = value
                    changed = True
            if not changed:
                return
            self._cookie_from_cloud = [
                {
                    "name": name,
                    "value": value,
                    "domain": ".work.weixin.qq.com",
                    "path": "/",
                }
                for name, value in refreshed.items()
            ]
            self.__save_config()
            if self._debug:
                logger.info(f"HTTP保活已续期cookie，共{len(refreshed)}项")
        except Exception as err:
            if self._debug:
                logger.warning(f"合并响应cookie失败：{err}")

    def keepalive_cookie(self):
        """
        Cookie 保活入口。

        先用 HTTP 探活；有效则直接返回（不启动浏览器）。
        失效或无法判定时，才启动浏览器复核，避免误判导致反复登录。
        """
        if not self._enabled:
            return

        self._last_probe_mode = "HTTP"
        verdict = self.probe_cookie_http()
        if verdict is True:
            self._set_cookie_valid(True)
            logger.info("Cookie保活：HTTP探活有效，跳过浏览器")
            if self._pending_sync and self._current_ip:
                logger.info("Cookie恢复有效，补同步待写入IP")
                self.sync_trusted_ip(notify=False)
            return

        self._last_probe_mode = "浏览器"
        logger.info("Cookie保活：HTTP探活未通过，启动浏览器复核")
        self._browser_keepalive()

    def _browser_keepalive(self):
        """用浏览器打开管理页，确认登录态；必要时保存新 cookie。"""

        def _do():
            browser = None
            try:
                browser = self._launch_browser()
                context = browser.new_context()
                page = context.new_page()
                page.goto(self._urls[0], wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)
                if page.locator(f".{self._login_marker}").count() > 0:
                    logger.warning("Cookie已失效，浏览器复核确认需要重新登录")
                    self._set_cookie_valid(False)
                    self._handle_cookie_invalid()
                    return
                logger.info("Cookie保活：浏览器复核有效")
                self._set_cookie_valid(True)
                self._capture_cookies(context)
                if self._pending_sync and self._current_ip:
                    logger.info("Cookie恢复有效，补同步待写入IP")
                    # 浏览器上下文仍可用，直接在本轮完成同步，避免二次启动
                    self._sync_with_page(page, notify=False)
            except Exception as err:
                logger.error(f"浏览器保活失败：{err}")

        self._run_browser_op(_do)

    def _capture_cookies(self, context):
        """把浏览器上下文里的 cookie 转成持久化列表。"""
        try:
            cookies = context.cookies()
            self._cookie_from_cloud = [
                {
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "domain": item.get("domain", ".work.weixin.qq.com"),
                    "path": item.get("path", "/"),
                }
                for item in cookies
                if item.get("name")
            ]
            self.__save_config()
        except Exception as err:
            logger.error(f"保存浏览器cookie失败：{err}")

    def _set_cookie_valid(self, valid: bool):
        changed = self._cookie_valid != valid
        self._cookie_valid = valid
        if changed:
            self.__save_config()

    def _handle_cookie_invalid(self):
        """cookie 失效后的调度处理：自动登录或退回手动。"""
        if self._schedule_login:
            if self._scheduler:
                job = self._scheduler.get_job("keepalive_cookie")
                if job:
                    self._scheduler.remove_job("keepalive_cookie")
            self.create_login_job()
        else:
            if self._scheduler and not self._scheduler.get_job("keepalive_cookie"):
                self.create_keepalive_job()

    # ------------------------------------------------------------------ IP 同步
    def sync_trusted_ip(self, notify: bool = False):
        """把当前 IP 写入所有配置的应用可信列表。"""
        if not self._urls:
            self._sync_result = "未配置应用网址"
            self._pending_sync = True
            logger.error("未配置企业微信应用网址，无法同步可信IP")
            return

        if not self._current_ip:
            self._sync_result = "当前IP未知"
            self._pending_sync = True
            logger.error("当前公网IP未知，跳过同步")
            return

        def _do():
            browser = None
            try:
                browser = self._launch_browser()
                context = browser.new_context()
                self._apply_cookies(context)
                page = context.new_page()
                page.goto(self._urls[0], wait_until="domcontentloaded", timeout=60000)
                time.sleep(2)
                if page.locator(f".{self._login_marker}").count() > 0:
                    logger.warning("Cookie失效，无法同步可信IP，已标记待同步")
                    self._set_cookie_valid(False)
                    self._sync_result = "Cookie失效，等待恢复后自动补写"
                    self._pending_sync = True
                    self.__save_config()
                    self._handle_cookie_invalid()
                    return
                self._set_cookie_valid(True)
                self._capture_cookies(context)
                # 成功路径下由 _sync_with_page 设置 pending_sync 与结果
                self._sync_with_page(page, notify=notify)
            except Exception as err:
                self._sync_result = f"同步失败：{err}"
                self._pending_sync = True
                logger.error(f"同步可信IP失败：{err}")
            finally:
                self.__save_config()
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass

        self._run_browser_op(_do)

    def _apply_cookies(self, context):
        """把持久化 cookie 注入浏览器上下文。"""
        pairs = self._cookie_pairs()
        if pairs:
            context.add_cookies(
                [
                    {
                        "name": name,
                        "value": value,
                        "domain": ".work.weixin.qq.com",
                        "path": "/",
                    }
                    for name, value in pairs.items()
                ]
            )

    def _sync_with_page(self, page, notify: bool = False):
        """在已登录的页面上逐个应用写入可信 IP。"""
        detail: List[str] = []
        target = self._current_ip
        try:
            for index, url in enumerate(self._urls, start=1):
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(
                    "div.app_card_operate.js_show_ipConfig_dialog", timeout=20000
                )
                page.locator("div.app_card_operate.js_show_ipConfig_dialog").first.click()
                page.wait_for_selector("textarea.js_ipConfig_textarea", timeout=20000)
                area = page.locator("textarea.js_ipConfig_textarea")
                before = area.input_value() or ""
                if self._overwrite:
                    value = target
                else:
                    existing = [x.strip() for x in before.split(";") if x.strip()]
                    value = ";".join(existing) if target in existing else ";".join(existing + [target])
                    value = value or target
                area.fill(value)
                page.locator(".js_ipConfig_confirmBtn").first.click()
                time.sleep(1)

                # 回读校验，避免静默失败
                after = self._readback_ip(page, url)
                ok = after == target
                detail.append(
                    f"应用{index}: {before or '空'} -> {after or '读取失败'} "
                    f"({'成功' if ok else '校验不一致'})"
                )
                logger.info(f"第{index}个应用可信IP写入：{before} -> {after}")
        except Exception as err:
            self._sync_result = f"同步失败：{err}"
            self._sync_detail = detail
            self._pending_sync = True
            logger.error(f"同步可信IP失败：{err}")
            return

        self._sync_at = self._now()
        self._sync_detail = detail
        all_ok = bool(detail) and all("成功" in item for item in detail)
        self._sync_result = "成功" if all_ok else "部分应用校验不一致"
        self._pending_sync = not all_ok
        logger.info(f"可信IP同步完成：{self._sync_result}，明细 {detail}")

        if notify and self._notify:
            self.post_message(
                channel=NotificationChannel.Wechat,
                mtype=MessageType.Plugin,
                title="企业微信可信IP已更新",
                text=f"当前IP：{target}\n" + "\n".join(detail),
                userid=self._qr_send_users,
            )

    def _readback_ip(self, page, url: str) -> Optional[str]:
        """重新打开配置弹窗，读回已保存的可信 IP。"""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(
                "div.app_card_operate.js_show_ipConfig_dialog", timeout=20000
            )
            page.locator("div.app_card_operate.js_show_ipConfig_dialog").first.click()
            page.wait_for_selector("textarea.js_ipConfig_textarea", timeout=20000)
            value = page.locator("textarea.js_ipConfig_textarea").input_value() or ""
            try:
                page.locator(".js_ipConfig_confirmBtn").first.click()
            except Exception:
                pass
            return self._parse_ipv4(value)
        except Exception as err:
            logger.warning(f"回读可信IP失败：{err}")
            return None

    # ------------------------------------------------------------------ 浏览器
    def _launch_browser(self):
        if cloak_launch is None:
            raise RuntimeError(f"cloakbrowser 不可用：{_cloak_import_error}")
        return cloak_launch(headless=True)

    def _run_browser_op(self, operation):
        """
        在独立线程中执行浏览器操作。

        Playwright 同步 API 与 MoviePilot 的 asyncio 事件循环冲突，
        因此有运行中的事件循环时必须丢到线程池里跑。
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return operation()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(operation)
            try:
                return future.result(timeout=self._browser_timeout)
            except Exception as err:
                logger.error(f"浏览器操作超时或异常：{err}")
                return None

    # ------------------------------------------------------------------ 登录
    def login(self):
        """扫码登录企业微信，成功后保存 cookie。"""
        logger.info("开始登录企业微信")
        if self._notify:
            self.post_message(
                channel=NotificationChannel.Wechat,
                mtype=MessageType.Plugin,
                title="开始登录企业微信",
                userid=self._qr_send_users,
            )

        def _do():
            browser = None
            try:
                browser = self._launch_browser()
                context = browser.new_context()
                page = context.new_page()
                page.goto(self._urls[0], wait_until="domcontentloaded", timeout=60000)

                frame = page.frame_locator('iframe[src*="login_qrcode"]')
                qr = frame.locator(".qrcode_login_img")
                qr.wait_for(state="visible", timeout=10000)
                qr_url = qr.get_attribute("src")
                absolute = urljoin(page.url, qr_url)

                if self._notify:
                    self.post_message(
                        channel=NotificationChannel.Wechat,
                        mtype=MessageType.Plugin,
                        title="点击扫描二维码登录企业微信",
                        image=absolute,
                        link=absolute,
                        userid=self._qr_send_users,
                    )
                self._save_qr_image(absolute)

                if not self._wait_for_login(page):
                    self.login_fail()
                    return

                self._capture_cookies(context)
                self._set_cookie_valid(True)
                logger.info("登录企业微信成功")
                if self._notify:
                    self.post_message(
                        channel=NotificationChannel.Wechat,
                        mtype=MessageType.Plugin,
                        title="登录企业微信成功",
                        userid=self._qr_send_users,
                    )
                if self._scheduler:
                    job = self._scheduler.get_job("wwlogin")
                    if job:
                        self._scheduler.remove_job("wwlogin")
                if self._pending_sync and self._current_ip:
                    logger.info("登录成功后补同步待写入IP")
                    self._sync_with_page(page, notify=False)
            except Exception as err:
                logger.error(f"登录失败：{err}")
                self.login_fail()
            finally:
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if os.path.exists(self._qr_path):
                    os.remove(self._qr_path)

        self._run_browser_op(_do)
        self.__save_config()

    def _save_qr_image(self, url: str):
        """下载二维码到插件目录，供页面兜底展示。"""
        try:
            response = requests.get(url, timeout=self._http_timeout)
            if response.status_code == 200:
                with open(self._qr_path, "wb") as file:
                    file.write(response.content)
                logger.info("二维码已保存，可在插件详情页扫描")
        except Exception as err:
            logger.warning(f"下载二维码失败：{err}")

    def _wait_for_login(self, page) -> bool:
        """
        等待扫码完成。

        二维码登录后可能进入手机验证码流程，此时通过 MP 应用回复 #123456 继续。
        """
        navigated = {"done": False}

        def on_navigate(frame):
            if "work.weixin.qq.com" in frame.url:
                navigated["done"] = True

        page.on("framenavigated", on_navigate)

        waited = 0
        while not navigated["done"]:
            page.wait_for_timeout(1000)
            waited += 1
            if waited > 120:
                logger.error("等待扫码超时")
                return False

        if "mobile_confirm" not in page.url:
            return True

        if self._notify:
            self.post_message(
                channel=NotificationChannel.Wechat,
                mtype=MessageType.Plugin,
                title="检测到登录验证，请以 #123456 格式回复验证码，两分钟内有效",
                userid=self._qr_send_users,
            )
        waited = 0
        while "mobile_confirm" in page.url:
            self._code = 0
            code_waited = 0
            while self._code == 0:
                time.sleep(2)
                code_waited += 2
                if code_waited > 120:
                    logger.error("等待验证码超时")
                    return False
            page.locator(".inner_input").type(str(self._code))
            page.wait_for_timeout(3000)
            if "mobile_confirm" in page.url:
                if self._notify:
                    self.post_message(
                        channel=NotificationChannel.Wechat,
                        mtype=MessageType.Plugin,
                        title="验证码可能错误，请重新回复 #123456",
                        userid=self._qr_send_users,
                    )
            waited += 3
            if waited > 180:
                return False
        return True

    def create_login_job(self):
        """安排一次登录任务。"""
        if not self._scheduler:
            return
        try:
            self._scheduler.add_job(
                func=self.login,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=5),
                name="登录企业微信",
                id="wwlogin",
            )
            logger.info("已安排企业微信登录任务")
        except Exception as err:
            logger.error(f"安排登录任务失败：{err}")

    def login_fail(self):
        """登录失败后的通知与重试安排。"""
        self._set_cookie_valid(False)
        if self._schedule_login:
            if self._notify:
                self.post_message(
                    channel=NotificationChannel.Wechat,
                    mtype=MessageType.Plugin,
                    title="登录失败",
                    text="已开启自动登录，稍后重试。",
                    userid=self._qr_send_users,
                )
            self.create_login_job()
        else:
            if self._notify:
                self.post_message(
                    channel=NotificationChannel.Wechat,
                    mtype=MessageType.Plugin,
                    title="登录失败",
                    text="如需再次登录，请回复\n#登录企业微信",
                    userid=self._qr_send_users,
                )

    # ------------------------------------------------------------------ 调度任务
    def create_keepalive_job(self):
        """注册 cookie 保活定时任务（幂等）。"""
        if not self._scheduler:
            return
        if self._scheduler.get_job("keepalive_cookie"):
            return
        try:
            self._scheduler.add_job(
                func=self.keepalive_cookie,
                trigger=CronTrigger.from_crontab(self._keepalive_cron),
                name="Cookie保活",
                id="keepalive_cookie",
            )
            logger.info(f"已注册Cookie保活任务：{self._keepalive_cron}")
        except Exception as err:
            logger.error(f"注册Cookie保活任务失败：{err}")

    def send_cookie_status(self):
        """周期性通知 cookie 失效状态。"""
        if self._cookie_valid or not self._notify:
            return
        self.post_message(
            channel=NotificationChannel.Wechat,
            mtype=MessageType.Plugin,
            title="企业微信Cookie失效",
            text="回复下述指令唤起一次登录\n#登录企业微信",
            userid=self._qr_send_users,
        )

    # ------------------------------------------------------------------ 消息与 API
    @eventmanager.register(EventType.PluginAction)
    def on_plugin_action(self, event: Event):
        """响应 /wecomipguard 远程命令。"""
        if not event or not event.event_data:
            return
        if event.event_data.get("action") != "wecomipguard":
            return
        self.check_ip(event=event)

    @eventmanager.register(EventType.UserMessage)
    def receive_message(self, event: Event):
        """处理 MP 应用发来的验证码与登录指令。"""
        if not self._enabled or not event or not event.event_data:
            return
        text = (event.event_data.get("text") or "").strip()
        if re.match(r"^#\d{6}$", text):
            self._code = text[1:]
            logger.info(f"收到登录验证码：{self._code}")
            return
        if text == "#登录企业微信":
            if self._cookie_valid:
                if self._notify:
                    self.post_message(
                        channel=NotificationChannel.Wechat,
                        mtype=MessageType.Plugin,
                        title="缓存有效，无需登录",
                        userid=self._qr_send_users,
                    )
                return
            self.create_login_job()

    @staticmethod
    def _event_channel(event: Event):
        data = event.event_data or {}
        return data.get("channel") or NotificationChannel.Wechat

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/wecomipguard",
                "event": EventType.PluginAction,
                "desc": "检测并同步企业微信可信IP",
                "category": "",
                "data": {"action": "wecomipguard"},
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册 IP 检测定时服务。"""
        if self._enabled and self._check_cron:
            try:
                trigger = CronTrigger.from_crontab(self._check_cron)
            except Exception as err:
                logger.error(f"IP检测周期配置错误：{err}")
                return []
            return [
                {
                    "id": "WeComIPGuard",
                    "name": "企业微信可信IP自动同步",
                    "trigger": trigger,
                    "func": self.check_ip,
                    "kwargs": {},
                }
            ]
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询当前状态",
                "description": "返回 cookie 状态、当前 IP、最近一次同步结果",
            },
            {
                "path": "/check",
                "endpoint": self.api_check,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即检测IP并同步",
                "description": "手动触发一次检测与同步",
            },
        ]

    def api_status(self) -> dict:
        return {
            "code": 0,
            "data": {
                "enabled": self._enabled,
                "cookie_valid": self._cookie_valid,
                "current_ip": self._current_ip,
                "ip_source": self._ip_source,
                "ip_checked_at": self._ip_checked_at,
                "ip_error": self._ip_error,
                "pending_sync": self._pending_sync,
                "sync_at": self._sync_at,
                "sync_result": self._sync_result,
                "sync_detail": self._sync_detail,
                "probe_mode": self._last_probe_mode,
            },
        }

    def api_check(self) -> dict:
        if not self._enabled:
            return {"code": 1, "message": "插件未启用"}
        self.check_ip()
        return {"code": 0, "data": {"current_ip": self._current_ip, "sync_result": self._sync_result}}

    # ------------------------------------------------------------------ 配置持久化
    def __save_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "notify": self._notify,
                "debug": self._debug,
                "check_cron": self._check_cron,
                "keepalive_cron": self._keepalive_cron,
                "status_cron": self._status_cron,
                "wechat_url": self._wechat_url,
                "cookie_header": self._cookie_header,
                "qr_send_users": self._qr_send_users,
                "overwrite": self._overwrite,
                "use_cookiecloud": self._use_cookiecloud,
                "schedule_login": self._schedule_login,
                "ip_urls": self._ip_urls_text,
                "http_timeout": self._http_timeout,
                "browser_timeout": self._browser_timeout,
                "cookie_valid": self._cookie_valid,
                "pending_sync": self._pending_sync,
                "cookie_list": self._cookie_from_cloud,
            }
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------ 页面
    # ------------------------------------------------------------------ 页面
    def get_page(self) -> List[dict]:
        """
        详情页：状态仪表盘。

        布局：顶部状态环 + 当前IP 主视觉，中部四格指标，底部仅在异常时展开明细。
        全部使用 rgb(var(--v-theme-*)) 令牌，自动跟随明暗主题。
        """
        danger = "rgb(var(--v-theme-error))"
        ok = "rgb(var(--v-theme-success))"
        warn = "rgb(var(--v-theme-warning))"
        primary = "rgb(var(--v-theme-primary))"
        on_surface = "rgb(var(--v-theme-on-surface))"
        surface = "rgb(var(--v-theme-surface))"
        surface_variant = "rgb(var(--v-theme-surface-variant))"

        muted = f"color: {on_surface}; opacity: .62;"
        card_style = (
            f"background-color: {surface}; color: {on_surface}; "
            f"border: 1px solid rgba(var(--v-theme-on-surface), .12); "
            f"border-radius: 14px;"
        )

        # ---- 主状态判定 ----
        if not self._enabled:
            ring_color, ring_text, headline, sub = "#9E9E9E", "—", "插件未启用", "启用后开始守护可信IP"
        elif not self._cookie_valid:
            ring_color, ring_text, headline, sub = "#E53935", "!", "登录态失效", "回复 #登录企业微信 重新扫码"
        elif self._pending_sync:
            ring_color, ring_text, headline, sub = "#FB8C00", "…", "等待同步", "Cookie 恢复后会自动补写"
        elif (self._sync_result or "").startswith("成功"):
            ring_color, ring_text, headline, sub = "#43A047", "✓", "一切正常", "可信IP已与企业微信同步"
        else:
            ring_color, ring_text, headline, sub = "#1E88E5", "•", "运行中", "尚未执行过同步"

        app_count = sum(1 for u in self._urls if u.strip())

        # ---- 状态环（纯 CSS 圆环）----
        ring = {
            "component": "div",
            "props": {
                "style": (
                    f"width: 76px; height: 76px; border-radius: 50%; flex: 0 0 76px; "
                    f"border: 4px solid {ring_color}; "
                    f"display: flex; align-items: center; justify-content: center; "
                    f"font-size: 34px; font-weight: 700; line-height: 1; "
                    f"color: {ring_color};"
                )
            },
            "text": ring_text,
        }

        ip_display = self._current_ip or "未知"
        header = {
            "component": "div",
            "props": {
                "style": (
                    f"{card_style} padding: 18px 20px; "
                    f"display: flex; align-items: center; gap: 18px;"
                )
            },
            "content": [
                ring,
                {
                    "component": "div",
                    "props": {"style": "min-width: 0; flex: 1 1 auto;"},
                    "content": [
                        {
                            "component": "div",
                            "props": {
                                "style": (
                                    f"font-family: ui-monospace, SFMono-Regular, Menlo, monospace; "
                                    f"font-size: 26px; font-weight: 700; letter-spacing: .5px; "
                                    f"color: {primary}; line-height: 1.2; word-break: break-all;"
                                )
                            },
                            "text": ip_display,
                        },
                        {
                            "component": "div",
                            "props": {"style": f"margin-top: 6px; font-size: 14px; font-weight: 600; color: {on_surface};"},
                            "text": headline,
                        },
                        {
                            "component": "div",
                            "props": {"style": f"margin-top: 2px; font-size: 12px; {muted}"},
                            "text": sub,
                        },
                    ],
                },
                {
                    "component": "div",
                    "props": {
                        "style": (
                            f"flex: 0 0 auto; text-align: right; font-size: 12px; {muted} "
                            f"display: flex; flex-direction: column; gap: 4px;"
                        )
                    },
                    "content": [
                        {"component": "div", "text": f"应用 {app_count} 个"},
                        {
                            "component": "div",
                            "text": f"检测 {self._ip_checked_at[11:16] if self._ip_checked_at else '—'}",
                        },
                    ],
                },
            ],
        }

        # ---- 四格指标 ----
        def metric(icon: str, value: str, label: str, color: str) -> dict:
            return {
                "component": "div",
                "props": {
                    "style": (
                        f"{card_style} padding: 12px 14px; "
                        f"display: flex; align-items: center; gap: 10px; min-width: 0;"
                    )
                },
                "content": [
                    {
                        "component": "VIcon",
                        "props": {"size": 22, "style": f"color: {color}; flex: 0 0 auto;"},
                        "text": icon,
                    },
                    {
                        "component": "div",
                        "props": {"style": "min-width: 0;"},
                        "content": [
                            {
                                "component": "div",
                                "props": {
                                    "style": (
                                        f"font-size: 15px; font-weight: 600; color: {on_surface}; "
                                        f"line-height: 1.3; white-space: nowrap; overflow: hidden; "
                                        f"text-overflow: ellipsis;"
                                    )
                                },
                                "text": value,
                            },
                            {
                                "component": "div",
                                "props": {"style": f"font-size: 11px; {muted}"},
                                "text": label,
                            },
                        ],
                    },
                ],
            }

        sync_ok = (self._sync_result or "").startswith("成功")
        metrics = {
            "component": "div",
            "props": {
                "style": (
                    "display: grid; gap: 10px; margin-top: 12px; "
                    "grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));"
                )
            },
            "content": [
                metric(
                    "mdi-check-circle-outline" if sync_ok else "mdi-alert-circle-outline",
                    self._sync_result or "未同步",
                    "同步状态",
                    ok if sync_ok else warn,
                ),
                metric(
                    "mdi-shield-check-outline" if self._cookie_valid else "mdi-shield-alert-outline",
                    "有效" if self._cookie_valid else "失效",
                    "登录态",
                    ok if self._cookie_valid else danger,
                ),
                metric(
                    "mdi-sync" if self._pending_sync else "mdi-sync-off",
                    "待补写" if self._pending_sync else "无",
                    "待同步",
                    warn if self._pending_sync else ok,
                ),
                metric(
                    "mdi-flash-outline",
                    self._last_probe_mode or "—",
                    "保活方式",
                    primary,
                ),
            ],
        }

        blocks: List[dict] = [
            {"component": "div", "props": {"style": "padding: 4px 0;"}, "content": [header, metrics]}
        ]

        # ---- 异常提示（仅异常时出现）----
        if self._ip_error:
            blocks.append(
                {
                    "component": "div",
                    "props": {
                        "style": (
                            f"margin-top: 12px; padding: 12px 14px; border-radius: 10px; "
                            f"background-color: rgba(var(--v-theme-error), .12); "
                            f"border: 1px solid rgba(var(--v-theme-error), .30); "
                            f"color: {danger}; font-size: 13px;"
                        )
                    },
                    "content": [
                        {
                            "component": "div",
                            "text": f"IP 获取异常：{self._ip_error}",
                        }
                    ],
                }
            )

        # ---- 扫码登录区（仅失效时）----
        if self._enabled and not self._cookie_valid and os.path.exists(self._qr_path):
            try:
                import base64

                with open(self._qr_path, "rb") as file:
                    encoded = base64.b64encode(file.read()).decode("utf-8")
                blocks.append(
                    {
                        "component": "div",
                        "props": {"style": "margin-top: 14px; text-align: center;"},
                        "content": [
                            {
                                "component": "div",
                                "props": {"style": f"font-size: 13px; {muted} margin-bottom: 8px;"},
                                "text": "扫描二维码登录企业微信",
                            },
                            {
                                "component": "img",
                                "props": {
                                    "src": f"data:image/png;base64,{encoded}",
                                    "style": (
                                        "max-width: 220px; width: 100%; border-radius: 10px; "
                                        "display: block; margin: 0 auto;"
                                    ),
                                },
                            },
                        ],
                    }
                )
            except Exception:
                pass

        # ---- 明细（可折叠；无明细时隐藏）----
        if self._sync_detail:
            detail_rows = []
            for item in self._sync_detail:
                good = "成功" in item
                detail_rows.append(
                    {
                        "component": "div",
                        "props": {
                            "style": (
                                "display: flex; align-items: flex-start; gap: 8px; "
                                "padding: 7px 0; "
                                "border-bottom: 1px solid rgba(var(--v-theme-on-surface), .07);"
                            )
                        },
                        "content": [
                            {
                                "component": "VIcon",
                                "props": {
                                    "size": 16,
                                    "style": f"color: {ok if good else warn}; margin-top: 2px; flex: 0 0 auto;",
                                },
                                "text": "mdi-check" if good else "mdi-alert",
                            },
                            {
                                "component": "div",
                                "props": {"style": f"font-size: 12.5px; color: {on_surface}; line-height: 1.5;"},
                                "text": item,
                            },
                        ],
                    }
                )
            blocks.append(
                {
                    "component": "div",
                    "props": {
                        "style": (
                            f"margin-top: 14px; padding: 4px 14px 12px; border-radius: 12px; "
                            f"background-color: rgba(var(--v-theme-on-surface), .03); "
                            f"border: 1px solid rgba(var(--v-theme-on-surface), .08);"
                        )
                    },
                    "content": [
                        {
                            "component": "div",
                            "props": {
                                "style": (
                                    f"font-size: 12px; font-weight: 600; {muted} "
                                    f"padding: 8px 0 4px; letter-spacing: .3px;"
                                )
                            },
                            "text": f"同步明细 · {self._sync_at or '—'}",
                        },
                        *detail_rows,
                    ],
                }
            )

        # ---- 来源脚注 ----
        blocks.append(
            {
                "component": "div",
                "props": {"style": f"margin-top: 12px; font-size: 11px; {muted} line-height: 1.7;"},
                "content": [
                    {"component": "div", "text": f"IP 来源：{self._ip_source or '未检测'}"},
                    {
                        "component": "div",
                        "text": f"检测时间：{self._ip_checked_at or '—'}　同步时间：{self._sync_at or '—'}",
                    },
                ],
            }
        )

        return blocks

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """插件配置页：分组卡片 + 折叠次要项。"""
        return [
            {
                "component": "VForm",
                "content": [
                    # ---- 总开关区 ----
                    {
                        "component": "VCard",
                        "props": {"variant": "tonal", "color": "primary", "class": "mb-3"},
                        "content": [
                            {
                                "component": "VCardText",
                                "props": {"class": "d-flex align-center flex-wrap ga-4 py-3"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {"size": 30},
                                        "text": "mdi-shield-check-outline",
                                    },
                                    {
                                        "component": "div",
                                        "props": {"class": "min-w-0"},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {"class": "text-subtitle-1 font-weight-bold"},
                                                "text": "企业微信可信IP助手",
                                            },
                                            {
                                                "component": "div",
                                                "props": {"class": "text-caption"},
                                                "text": "IP 变化时自动写入企业微信应用的可信IP白名单",
                                            },
                                        ],
                                    },
                                ],
                            }
                        ],
                    },
                    # ---- 基础开关 ----
                    self._section(
                        "mdi-cog-outline",
                        "基础设置",
                        [
                            self._switch_col("enabled", "启用插件", 3),
                            self._switch_col("onlyonce", "立即检测一次", 3),
                            self._switch_col("notify", "发送通知", 3),
                            self._switch_col("debug", "调试日志", 3),
                        ],
                    ),
                    # ---- 同步行为 ----
                    self._section(
                        "mdi-swap-vertical",
                        "同步行为",
                        [
                            self._switch_col("overwrite", "覆盖已有IP（关闭则追加）", 6),
                            self._switch_col("use_cookiecloud", "从 CookieCloud 获取 Cookie", 6),
                        ],
                    ),
                    # ---- 必填 ----
                    self._section(
                        "mdi-link-variant",
                        "应用地址（必填）",
                        [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "wechat_url",
                                            "label": "企业微信应用管理网址",
                                            "rows": 2,
                                            "variant": "outlined",
                                            "density": "comfortable",
                                            "placeholder": "多个地址用英文逗号分隔\nhttps://work.weixin.qq.com/wework_admin/frame#/apps/modApiApp/00000000000",
                                            "hint": "在企业微信管理后台 → 应用管理 → 打开任一应用的「网页授权及JS-SDK」页面，复制地址栏",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    ),
                    # ---- 折叠：高级 ----
                    {
                        "component": "VExpansionPanels",
                        "props": {"variant": "accordion", "class": "mb-3"},
                        "content": [
                            {
                                "component": "VExpansionPanel",
                                "props": {"title": "定时与超时", "elevation": 0},
                                "content": [
                                    {
                                        "component": "VExpansionPanelText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    self._text_col("check_cron", "IP 检测周期", "*/11 * * * *", 6),
                                                    self._text_col("keepalive_cron", "Cookie 保活周期", "*/5 * * * *", 6),
                                                ],
                                            },
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    self._text_col("status_cron", "失效通知周期", "0 * * * *", 4),
                                                    self._text_col("http_timeout", "HTTP 超时（秒）", "15", 4),
                                                    self._text_col("browser_timeout", "浏览器超时（秒）", "180", 4),
                                                ],
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "component": "VExpansionPanel",
                                "props": {"title": "Cookie 与登录", "elevation": 0},
                                "content": [
                                    {
                                        "component": "VExpansionPanelText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12},
                                                        "content": [
                                                            {
                                                                "component": "VTextarea",
                                                                "props": {
                                                                    "model": "cookie_header",
                                                                    "label": "手动 Cookie（非必填）",
                                                                    "rows": 2,
                                                                    "variant": "outlined",
                                                                    "placeholder": "HeaderString 格式，如 a=1; b=2",
                                                                    "hint": "仅在 CookieCloud 与自动登录都不方便时填写",
                                                                    "persistent-hint": True,
                                                                },
                                                            }
                                                        ],
                                                    },
                                                ],
                                            },
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    self._switch_col("schedule_login", "Cookie 失效后自动登录", 12),
                                                ],
                                            },
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12},
                                                        "content": [
                                                            {
                                                                "component": "VTextarea",
                                                                "props": {
                                                                    "model": "qr_send_users",
                                                                    "label": "接收登录二维码的成员ID（非必填）",
                                                                    "rows": 1,
                                                                    "variant": "outlined",
                                                                    "placeholder": "留空则发送给全部成员",
                                                                    "hint": "企业微信 → 管理企业 → 成员与部门管理 → 成员详情 → 账号",
                                                                    "persistent-hint": True,
                                                                },
                                                            }
                                                        ],
                                                    }
                                                ],
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "component": "VExpansionPanel",
                                "props": {"title": "高级：自定义 IP 源", "elevation": 0},
                                "content": [
                                    {
                                        "component": "VExpansionPanelText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "content": [
                                                    {
                                                        "component": "VCol",
                                                        "props": {"cols": 12},
                                                        "content": [
                                                            {
                                                                "component": "VTextarea",
                                                                "props": {
                                                                    "model": "ip_urls",
                                                                    "label": "自定义 IP 源",
                                                                    "rows": 2,
                                                                    "variant": "outlined",
                                                                    "placeholder": "ddns.oray.com/checkip、ipv4.icanhazip.com、v4.ipip.net、ipinfo.io/ip",
                                                                    "hint": "留空使用内置 IPv4 专用源；多个用英文逗号分隔",
                                                                    "persistent-hint": True,
                                                                },
                                                            }
                                                        ],
                                                    }
                                                ],
                                            },
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                    # ---- 使用提示 ----
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "class": "mb-2",
                            "text": "登录态失效后，向 MoviePilot 应用回复 #登录企业微信 重新扫码；若需手机验证，按 #123456 格式回复验证码。",
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "Cookie 保活优先使用 HTTP 请求探活，只有探活失败才启动浏览器内核，常态下几乎不占用 CPU。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "debug": False,
            "check_cron": "*/11 * * * *",
            "keepalive_cron": "*/5 * * * *",
            "status_cron": "0 * * * *",
            "wechat_url": "",
            "cookie_header": "",
            "qr_send_users": "",
            "overwrite": True,
            "use_cookiecloud": True,
            "schedule_login": False,
            "ip_urls": "",
            "http_timeout": 15,
            "browser_timeout": 180,
        }

    @staticmethod
    def _section(icon: str, title: str, items: List[dict]) -> dict:
        """生成一个带标题图标的分区卡片。"""
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [
                {
                    "component": "VCardText",
                    "props": {"class": "pa-4"},
                    "content": [
                        {
                            "component": "div",
                            "props": {
                                "class": "d-flex align-center ga-2 mb-3",
                            },
                            "content": [
                                {"component": "VIcon", "props": {"size": 18, "color": "primary"}, "text": icon},
                                {
                                    "component": "div",
                                    "props": {"class": "text-subtitle-2 font-weight-bold"},
                                    "text": title,
                                },
                            ],
                        },
                        {"component": "VRow", "content": items},
                    ],
                }
            ],
        }

    @staticmethod
    def _switch_col(model: str, label: str, md: int = 3) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [
                {"component": "VSwitch", "props": {"model": model, "label": label, "density": "comfortable"}}
            ],
        }

    @staticmethod
    def _text_col(model: str, label: str, placeholder: str, md: int) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [
                {
                    "component": "VTextField",
                    "props": {
                        "model": model,
                        "label": label,
                        "placeholder": placeholder,
                        "variant": "outlined",
                        "density": "comfortable",
                    },
                }
            ],
        }
