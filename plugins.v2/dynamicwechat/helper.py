import re
import os
import json
import requests
import base64
import hashlib
import asyncio
from typing import Dict, Any
from Crypto import Random
from Crypto.Cipher import AES

import aiohttp

from app.modules.wechat import WeChat
from app.schemas.types import NotificationType, MessageChannel


def bytes_to_key(data: bytes, salt: bytes, output=48) -> bytes:
    """兼容v2 将bytes_to_key和encrypt导入"""
    if len(salt) != 8:
        raise ValueError(f"salt must be 8 bytes, got {len(salt)}")
    data += salt
    key = hashlib.md5(data).digest()
    final_key = key
    while len(final_key) < output:
        key = hashlib.md5(key + data).digest()
        final_key += key
    return final_key[:output]


def encrypt(message: bytes, passphrase: bytes) -> bytes:
    """
    CryptoJS 加密原文

    This is a modified copy of https://stackoverflow.com/questions/36762098/how-to-decrypt-password-from-javascript-cryptojs-aes-encryptpassword-passphras
    """
    salt = Random.new().read(8)
    key_iv = bytes_to_key(passphrase, salt, 32 + 16)
    key = key_iv[:32]
    iv = key_iv[32:]
    aes = AES.new(key, AES.MODE_CBC, iv)
    length = 16 - (len(message) % 16)
    data = message + (chr(length) * length).encode()
    return base64.b64encode(b"Salted__" + salt + aes.encrypt(data))


class PyCookieCloud:
    """CookieCloud 客户端，提供同步和异步两种操作方式"""

    def __init__(self, url: str, uuid: str, password: str):
        self.url: str = url
        self.uuid: str = uuid
        self.password: str = password

    def check_connection(self) -> bool:
        """同步检查连接（保留兼容）"""
        try:
            resp = requests.get(self.url, timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    async def check_connection_async(self) -> bool:
        """异步检查连接"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    def update_cookie(self, formatted_cookies: Dict[str, Any]) -> bool:
        """
        Update cookie data to CookieCloud.

        :param formatted_cookies: cookie value to update.
        :return: if update success, return True, else return False.
        """
        if '.work.weixin.qq.com' not in formatted_cookies:
            formatted_cookies['.work.weixin.qq.com'] = []
        formatted_cookies['.work.weixin.qq.com'].append({
            'name': '_upload_type',
            'value': 'A',
            'domain': '.work.weixin.qq.com',
            'path': '/',
            'expires': -1,
            'httpOnly': False,
            'secure': False,
            'sameSite': 'Lax'
        })

        cookie = {'cookie_data': formatted_cookies}
        raw_data = json.dumps(cookie)
        encrypted_data = encrypt(raw_data.encode('utf-8'), self.get_the_key().encode('utf-8')).decode('utf-8')
        cookie_cloud_request = requests.post(
            self.url + '/update',
            json={'uuid': self.uuid, 'encrypted': encrypted_data}
        )
        if cookie_cloud_request.status_code == 200:
            if cookie_cloud_request.json().get('action') == 'done':
                return True
        return False

    def get_the_key(self) -> str:
        """
        Get the key used to encrypt and decrypt data.

        :return: the key.
        """
        md5 = hashlib.md5()
        md5.update((self.uuid + '-' + self.password).encode('utf-8'))
        return md5.hexdigest()[:16]

    # ---------- 同步文件操作方法（保留兼容） ----------
    @staticmethod
    def load_cookie_lifetime(settings_file: str = None):
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as file:
                settings = json.load(file)
                return settings.get('_cookie_lifetime', 0)
        else:
            return 0

    @staticmethod
    def save_cookie_lifetime(settings_file, cookie_lifetime):
        data = {}
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as file:
                data = json.load(file)

        data['_cookie_lifetime'] = cookie_lifetime

        with open(settings_file, 'w') as file:
            json.dump(data, file, indent=4)

    @staticmethod
    def increase_cookie_lifetime(settings_file, seconds: int):
        current_lifetime = PyCookieCloud.load_cookie_lifetime(settings_file)
        new_lifetime = current_lifetime + seconds
        PyCookieCloud.save_cookie_lifetime(settings_file, new_lifetime)

    # ---------- 异步文件操作方法（新增） ----------
    @staticmethod
    async def load_cookie_lifetime_async(settings_file: str = None):
        return await asyncio.to_thread(PyCookieCloud.load_cookie_lifetime, settings_file)

    @staticmethod
    async def save_cookie_lifetime_async(settings_file, cookie_lifetime):
        await asyncio.to_thread(PyCookieCloud.save_cookie_lifetime, settings_file, cookie_lifetime)

    @staticmethod
    async def increase_cookie_lifetime_async(settings_file, seconds: int):
        await asyncio.to_thread(PyCookieCloud.increase_cookie_lifetime, settings_file, seconds)


class MySender:
    """
    多渠道消息发送器
    注意：所有网络请求是同步的，在异步上下文中调用时需用 asyncio.to_thread 包裹
    """

    def __init__(self, token=None, func=None):
        self.raw_token = token or ""

        self.quiet_flag = False
        if self.raw_token.endswith("||Q") or self.raw_token.endswith("||q"):
            self.quiet_flag = True
            token = self.raw_token.rsplit("||", 1)[0]
        else:
            token = self.raw_token

        self.tokens = token.split('||') if token and '||' in token else [token] if token else []
        self.channels = [MySender._detect_channel(t) for t in self.tokens]
        self.current_index = 0
        self.first_text_sent = False
        self.init_success = bool(self.tokens)
        self.post_message_func = func

    @property
    def other_channel(self):
        """
        返回非 WeChat 通道及其对应 token 的列表
        :return: [(channel, token), ...]
        """
        return [(channel, token) for channel, token in zip(self.channels, self.tokens) if channel.lower() != "wechat"]

    @staticmethod
    def _detect_channel(token):
        """根据 token 判断通知渠道"""
        token = token.lower()

        if "wechat" in token:
            return "WeChat"
        if token.startswith("sct"):
            return "ServerChan"
        elif "iyuu" in token:
            return "IYUU"
        else:
            return "PushPlus"

    def send(self, title, content=None, image=None, force_send=False, diy_channel=None, diy_token=None):
        """发送消息（同步方法，在异步上下文中请用 to_thread 包裹）"""
        if not self.init_success:
            return

        if not image and not force_send:
            if self.first_text_sent:
                return
            self.first_text_sent = True

        if diy_channel:
            return self._try_send(title, content, image, channel=diy_channel, diy_token=diy_token)

        for _ in range(len(self.tokens)):
            token = self.tokens[self.current_index]
            channel = self.channels[self.current_index]
            try:
                result = self._try_send(title, content, image, channel, token=token)
                if result is None:
                    return
            except Exception:
                pass
            self.current_index = (self.current_index + 1) % len(self.tokens)
        return "所有的通知方式都发送失败"

    def _try_send(self, title, content, image, channel, token=None, diy_token=None):
        """尝试使用指定通道发送消息"""
        if channel == "WeChat" and self.post_message_func:
            return self._send_v2_wechat(title, content, image, token)
        elif channel == "WeChat":
            return self._send_wechat(title, content, image, token)
        elif channel == "ServerChan":
            return self._send_serverchan(title, content, image, diy_token)
        elif channel == "IYUU":
            return self._send_iyuu(title, content, image, diy_token)
        elif channel == "PushPlus":
            return self._send_pushplus(title, content, image, diy_token)
        else:
            return f"未知的通知方式: {channel}"

    @staticmethod
    def _send_wechat(title, content, image, token):
        wechat = WeChat()
        if token and ',' in token:
            _, actual_userid = token.split(',', 1)
        else:
            actual_userid = None
        if image:
            send_status = wechat.send_msg(title='企业微信登录二维码', image=image, link=image, userid=actual_userid)
        else:
            send_status = wechat.send_msg(title=title, text=content, userid=actual_userid)

        if not send_status:
            return "微信通知发送错误"
        return None

    def _send_serverchan(self, title, content, image, diy_token=None):
        if diy_token:
            tmp_tokens = diy_token
        else:
            tmp_tokens = self.tokens[self.current_index]
        if ',' in tmp_tokens:
            first_part, second_part = tmp_tokens.split(',', 1)
            if first_part.startswith('sctp') and image:
                token = second_part
            else:
                token = first_part
        else:
            token = tmp_tokens

        if token.startswith('sctp'):
            match = re.match(r'sctp(\d+)t', token)
            if match:
                num = match.group(1)
                url = f'https://{num}.push.ft07.com/send/{token}.send'
            else:
                return '错误的Server3 Sendkey'
        else:
            url = f'https://sctapi.ftqq.com/{token}.send'

        params = {'title': title, 'desp': f'![img]({image})' if image else content}
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        response = requests.post(url, json=params, headers=headers)
        result = response.json()
        if result.get('code') != 0:
            return f"Server酱通知错误: {result.get('message')}"
        return None

    def _send_iyuu(self, title, content, image, diy_token=None):
        if diy_token:
            token = diy_token
        else:
            token = self.tokens[self.current_index]

        url = f"https://iyuu.cn/{token}.send"
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        if image:
            desp = f'<img src="{image}" style="max-width: 100%; height: auto;" />'
        else:
            desp = content
        payload = {"text": title, "desp": desp}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            result = response.json()
            if result.get("errcode") != 0:
                return f"爱语飞飞通知错误: {result.get('errmsg')}"
            return None
        except Exception as e:
            return f"爱语飞飞请求异常: {str(e)}"

    def _send_pushplus(self, title, content, image, diy_token=None):
        if diy_token:
            token = diy_token
        else:
            token = self.tokens[self.current_index]
        pushplus_url = f"http://www.pushplus.plus/send/{token}"
        data = {
            "title": title,
            "content": f"企业微信登录二维码<br/><img src='{image}' />" if image else content,
            "template": "html"
        }
        response = requests.post(pushplus_url, json=data)
        result = response.json()
        if result.get('code') != 200:
            return f"PushPlus send failed: {result.get('msg')}"
        return None

    def _send_v2_wechat(self, title, content, image, token):
        """V2 微信通知发送"""
        if token and ',' in token:
            _, actual_userid = token.split(',', 1)
        else:
            actual_userid = None
        self.post_message_func(
            channel=MessageChannel.Wechat,
            mtype=NotificationType.Plugin,
            title=title,
            text=content,
            image=image,
            link=image,
            userid=actual_userid
        )
        return None

    def reset_limit(self):
        """解除限制，允许再次发送纯文本消息"""
        self.first_text_sent = False


class IpLocationParser:
    """
    IP 地址解析器，支持多 WAN 口
    所有文件操作提供同步和异步两种版本
    """

    def __init__(self, settings_file_path, max_ips=3):
        self._settings_file_path = settings_file_path
        self._max_ips = max_ips
        self._ips = self.read_ips("ips")

    @staticmethod
    async def _parse(page, url):
        """异步解析页面，返回 IP 和归属地列表"""
        parser_methods = {
            "https://ip.orz.tools": IpLocationParser._parse_ip_orz_tools,
            "https://ip.skk.moe/multi": IpLocationParser._parse_ip_skk_moe,
            "https://ip.m27.tech": IpLocationParser._parse_ip_m27,
        }
        parser_method = parser_methods.get(url)
        if parser_method is None:
            return [], []
        return await parser_method(page)

    @staticmethod
    def _remove_duplicates(ipv4_addresses, locations):
        """去重并保持 IP 地址和归属地的对应关系"""
        seen = set()
        unique_ipv4 = []
        unique_locations = []

        for ip, location in zip(ipv4_addresses, locations):
            if ip not in seen:
                seen.add(ip)
                unique_ipv4.append(ip)
                unique_locations.append(location)

        return unique_ipv4, unique_locations

    @staticmethod
    def _is_valid_ipv4(ip):
        """验证是否是合法的 IPv4 地址"""
        return re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) is not None

    @staticmethod
    async def _parse_ip_orz_tools(page):
        """异步解析 https://ip.orz.tools"""
        try:
            await page.wait_for_selector('#results3 .row', timeout=10000)
        except Exception:
            return [], []

        rows = await page.query_selector_all('#results3 .row')
        ipv4_addresses, locations = [], []

        for row in rows:
            row_html = await row.inner_html()

            ip_match = re.search(r'data-name="([^"]+)"', row_html)
            if ip_match:
                ip = ip_match.group(1).strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
            else:
                continue

            loc_element = await row.query_selector('.loc.cell')
            location = await loc_element.inner_text() if loc_element else "未知"

            ipv4_addresses.append(ip)
            locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    async def _parse_ip_skk_moe(page):
        """异步解析 https://ip.skk.moe/multi"""
        try:
            await page.wait_for_selector(
                'body > div > section > div.x1n2onr6.xw2csxc.x10fe3q7.x116uinm.xdpxx8g > table > tbody > tr',
                timeout=10000
            )
        except Exception:
            return [], []

        rows = await page.query_selector_all(
            'body > div > section > div.x1n2onr6.xw2csxc.x10fe3q7.x116uinm.xdpxx8g > table > tbody > tr'
        )
        ipv4_addresses, locations = [], []

        for row in rows:
            ip_element = await row.query_selector('th')
            loc_element = await row.query_selector('td:nth-child(3)')

            if ip_element and loc_element:
                ip = await ip_element.inner_text()
                ip = ip.strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
                location = await loc_element.inner_text()
                location = location.strip()

                ipv4_addresses.append(ip)
                locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    async def _parse_ip_m27(page):
        """异步解析 https://ip.m27.tech"""
        try:
            await page.wait_for_selector(
                'body > div > div.panel.panel-success > div.panel-body > table > tbody > tr',
                timeout=10000
            )
        except Exception:
            return [], []

        rows = await page.query_selector_all(
            'body > div > div.panel.panel-success > div.panel-body > table > tbody > tr'
        )
        ipv4_addresses, locations = [], []

        for row in rows:
            row_text = await row.inner_text()
            row_text = row_text.strip()

            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', row_text)
            if ip_match:
                ip = ip_match.group(1).strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
            else:
                continue

            location_match = re.search(r'(China|中国).*', row_text)
            location = location_match.group(0).strip() if location_match else "未知"

            ipv4_addresses.append(ip)
            locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    async def get_ipv4(page, url: str) -> str:
        """
        返回多个中国 IP 地址，分号分隔（异步版本）
        :param page: CloakBrowser 异步 Page 对象
        :param url: 目标 URL
        :return: 分号分隔的 IPv4 地址字符串
        """
        try:
            await page.goto(url)
            await page.wait_for_timeout(8000)

            ipv4_addresses, locations = await IpLocationParser._parse(page, url)

            china_ips = [
                ip for ip, location in zip(ipv4_addresses, locations)
                if 'China' in location or '中国' in location
            ]
            return ';'.join(china_ips)
        except Exception as e:
            return ""

    # ---------- 同步文件操作方法（保留兼容） ----------
    def _limit_and_deduplicate_ips(self, ips):
        """去重并限制 IP 地址数量，最多保存 _max_ips 个 IP 地址"""
        unique_ips = list(dict.fromkeys(ips))
        return unique_ips[:self._max_ips]

    def _read_ips_from_json(self, field):
        """从 JSON 文件中读取指定字段的 IP 地址"""
        if not os.path.exists(self._settings_file_path):
            return ""

        try:
            with open(self._settings_file_path, 'r') as f:
                data = json.load(f)
                return ";".join(data.get(field, []))
        except (json.JSONDecodeError, IOError):
            return ""

    def _overwrite_ips_in_json(self, field, new_ips):
        """覆盖写入指定字段的 IP 地址"""
        if isinstance(new_ips, str):
            new_ips = new_ips.split(";")

        new_ips = self._limit_and_deduplicate_ips(new_ips)

        if os.path.exists(self._settings_file_path):
            try:
                with open(self._settings_file_path, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}
        else:
            data = {}

        data[field] = new_ips

        with open(self._settings_file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def read_ips(self, field) -> str:
        """获取 JSON 文件中指定字段的所有 IP 地址，返回分号分隔的字符串"""
        return self._read_ips_from_json(field)

    def overwrite_ips(self, field, new_ips):
        """覆盖写入指定字段的新 IP 地址"""
        self._overwrite_ips_in_json(field, new_ips)

    def add_ips(self, field, new_ips):
        """增量添加指定字段中的 IP 地址"""
        current_ips = self.read_ips(field).split(";") if self.read_ips(field) else []

        updated_ips = self._limit_and_deduplicate_ips(new_ips.split(";") + current_ips)

        self.overwrite_ips(field, updated_ips)

    # ---------- 异步文件操作方法（新增） ----------
    async def read_ips_async(self, field) -> str:
        return await asyncio.to_thread(self.read_ips, field)

    async def overwrite_ips_async(self, field, new_ips):
        await asyncio.to_thread(self.overwrite_ips, field, new_ips)

    async def add_ips_async(self, field, new_ips):
        await asyncio.to_thread(self.add_ips, field, new_ips)


class JsonFieldManager:
    """
    通用 JSON 配置文件字段管理器。
    所有操作均遵循「读-改-写」模式，确保不修改无关字段。
    提供同步和异步两种操作方式。
    """

    def __init__(self, settings_file_path: str):
        self._settings_file_path = settings_file_path

    def _load(self) -> dict:
        """读取完整 JSON 内容；若文件损坏或不存在则返回空字典"""
        try:
            with open(self._settings_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save(self, data: dict) -> None:
        """直接写入原文件"""
        with open(self._settings_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # ---------- 同步操作方法 ----------
    def get(self, field: str, default: Any = None) -> Any:
        """读取指定字段的值"""
        return self._load().get(field, default)

    def add(self, field: str, value: Any) -> bool:
        """添加新字段。若字段已存在则返回 False"""
        data = self._load()
        if field in data:
            return False
        data[field] = value
        self._save(data)
        return True

    def update(self, field: str, value: Any) -> None:
        """修改指定字段的值；若字段不存在则自动创建"""
        data = self._load()
        data[field] = value
        self._save(data)

    # ---------- 异步操作方法（新增） ----------
    async def aget(self, field: str, default: Any = None) -> Any:
        return await asyncio.to_thread(self.get, field, default)

    async def aadd(self, field: str, value: Any) -> bool:
        return await asyncio.to_thread(self.add, field, value)

    async def aupdate(self, field: str, value: Any) -> None:
        await asyncio.to_thread(self.update, field, value)