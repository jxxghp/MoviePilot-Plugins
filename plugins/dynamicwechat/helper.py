import re
import os
import json
import requests
import base64
import hashlib
from typing import Dict, Any
from Crypto import Random
from Crypto.Cipher import AES

from app.modules.wechat import WeChat
from app.schemas.types import NotificationType, MessageChannel


def bytes_to_key(data: bytes, salt: bytes, output=48) -> bytes:
    # 兼容v2 将bytes_to_key和encrypt导入
    assert len(salt) == 8, len(salt)
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
    def __init__(self, url: str, uuid: str, password: str):
        self.url: str = url
        self.uuid: str = uuid
        self.password: str = password

    def check_connection(self) -> bool:
        """
        Test the connection to the CookieCloud server.

        :return: True if the connection is successful, False otherwise.
        """
        try:
            resp = requests.get(self.url, timeout=3)  # 设置超时为3秒
            return resp.status_code == 200
        except Exception as e:
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
        cookie_cloud_request = requests.post(self.url + '/update',
                                             json={'uuid': self.uuid, 'encrypted': encrypted_data})
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

        # 只更新 _cookie_lifetime 字段，其它字段保持不变
        data['_cookie_lifetime'] = cookie_lifetime

        with open(settings_file, 'w') as file:
            json.dump(data, file, indent=4)

    @staticmethod
    def increase_cookie_lifetime(settings_file, seconds: int):
        current_lifetime = PyCookieCloud.load_cookie_lifetime(settings_file)
        new_lifetime = current_lifetime + seconds
        # 保存新的 _cookie_lifetime
        PyCookieCloud.save_cookie_lifetime(settings_file, new_lifetime)


class MySender:
    def __init__(self, token=None, func=None):
        self.tokens = token.split('||') if token and '||' in token else [token] if token else []
        self.channels = [MySender._detect_channel(t) for t in self.tokens]
        self.current_index = 0  # 当前使用的 token 和 channel 的索引
        self.first_text_sent = False  # 是否已发送过纯文本消息
        self.init_success = bool(self.tokens)  # 标识初始化是否成功
        self.post_message_func = func  # V2 微信模式的 post_message 方法

    @property
    def other_channel(self):
        """
        返回非 WeChat 通道及其对应 token 的列表
        :return: [(channel, token), ...]
        """
        return [(channel, token) for channel, token in zip(self.channels, self.tokens) if channel.lower() != "wechat"]

    @staticmethod
    def _detect_channel(token):
        """根据 token 确定通知渠道"""
        if "WeChat" in token or "wechat" in token:
            return "WeChat"

        letters_only = ''.join(re.findall(r'[A-Za-z]', token))
        if token.lower().startswith("sct"):
            return "ServerChan"
        elif letters_only.isupper():
            return "AnPush"
        else:
            return "PushPlus"

    def send(self, title, content=None, image=None, force_send=False, diy_channel=None, diy_token=None):
        """发送消息"""
        if not self.init_success:
            return

        # 对纯文本消息进行限制
        if not image and not force_send:
            if self.first_text_sent:
                return
            self.first_text_sent = True

        # 如果指定了自定义通道，直接尝试发送
        if diy_channel:
            return self._try_send(title, content, image, channel=diy_channel, diy_token=diy_token)

        # 尝试按顺序发送，直到成功或遍历所有通道
        for _ in range(len(self.tokens)):
            token = self.tokens[self.current_index]
            channel = self.channels[self.current_index]
            try:
                result = self._try_send(title, content, image, channel, token=token)
                if result is None:  # 成功时返回 None
                    return
            except Exception as e:
                pass     # 忽略单个错误，继续尝试下一个通道
            self.current_index = (self.current_index + 1) % len(self.tokens)
        return f"所有的通知方式都发送失败"

    def _try_send(self, title, content, image, channel, token=None, diy_token=None):
        """尝试使用指定通道发送消息"""
        if channel == "WeChat" and self.post_message_func:
            return self._send_v2_wechat(title, content, image, token)
        elif channel == "WeChat":
            return self._send_wechat(title, content, image, token)
        elif channel == "ServerChan":
            return self._send_serverchan(title, content, image, diy_token)
        elif channel == "AnPush":
            return self._send_anpush(title, content, image, diy_token)
        elif channel == "PushPlus":
            return self._send_pushplus(title, content, image, diy_token)
        else:
            return f"未知的通知方式: {channel}"

    @staticmethod
    def _send_wechat(title, content, image, token):
        wechat = WeChat()
        if token and ',' in token:
            channel, actual_userid = token.split(',', 1)
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
            before_comma, after_comma = tmp_tokens.split(',', 1)
            if before_comma.startswith('sctp') and image:
                token = after_comma  # 图片发到公众号
            else:
                token = before_comma  # 发到 server3
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

    def _send_anpush(self, title, content, image, diy_token=None):
        if diy_token:
            token = diy_token
        else:
            token = self.tokens[self.current_index]  # 获取当前通道对应的 token
        if ',' in token:
            channel, token = token.split(',', 1)
        else:
            return "AnPush可能没有配置消息通道ID"
        url = f"https://api.anpush.com/push/{token}"
        payload = {
            "title": title,
            "content": f"<img src=\"{image}\" width=\"100%\">" if image else content,
            "channel": channel
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, headers=headers, data=payload)
        result = response.json()
        # 判断返回的code和msgIds
        if result.get('code') != 200:
            return f"AnPush: {result.get('msg')}"
        elif not result.get('data') or not result['data'].get('msgIds'):
            return "AnPush 消息通道未找到"
        return None

    def _send_pushplus(self, title, content, image, diy_token=None):
        if diy_token:
            token = diy_token
        else:
            token = self.tokens[self.current_index]  # 获取当前通道对应的 token
        pushplus_url = f"http://www.pushplus.plus/send/{token}"
        # PushPlus发送逻辑
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
        return None  # 由于self.post_message()了None外，没有其他返回值。无法判断是否发送成功，V2直接默认成功

    def reset_limit(self):
        """解除限制，允许再次发送纯文本消息"""
        self.first_text_sent = False


class IpLocationParser:
    def __init__(self, settings_file_path, max_ips=3):
        self._settings_file_path = settings_file_path
        self._max_ips = max_ips  # 最大历史IP数量
        self._ips = self.read_ips("ips")  # 初始化时读取已存储的 IP 地址

    @staticmethod
    def _parse(page, url):
        # 定义 URL 到解析函数的映射
        parser_methods = {
            "https://ip.orz.tools": IpLocationParser._parse_ip_orz_tools,
            "https://ip.skk.moe/multi": IpLocationParser._parse_ip_skk_moe,
            "https://ip.m27.tech": IpLocationParser._parse_ip_m27,
        }
        parser_method = parser_methods.get(url)
        if parser_method is None:
            return [], []
        return parser_method(page)

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
    def _parse_ip_orz_tools(page):
        rows = page.query_selector_all('#results3 .row')
        # print(f"ip_orz_tools共找到 {len(rows)} 行数据")
        ipv4_addresses, locations = [], []

        for i, row in enumerate(rows):
            row_html = row.inner_html()

            # 提取 IP 地址
            ip_match = re.search(r'data-name="([^"]+)"', row_html)
            if ip_match:
                ip = ip_match.group(1).strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
            else:
                continue

            # 提取位置数据
            loc_element = row.query_selector('.loc.cell')
            location = loc_element.inner_text().strip() if loc_element else "未知"

            ipv4_addresses.append(ip)
            locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    def _parse_ip_skk_moe(page):
        rows = page.query_selector_all(
            'body > div > section > div.x1n2onr6.xw2csxc.x10fe3q7.x116uinm.xdpxx8g > table > tbody > tr'
        )
        # print(f"skk共找到 {len(rows)} 行数据")
        ipv4_addresses, locations = [], []

        for i, row in enumerate(rows):
            ip_element = row.query_selector('th')
            loc_element = row.query_selector('td:nth-child(3)')  # 假设归属地在第 3 列

            if ip_element and loc_element:
                ip = ip_element.inner_text().strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
                location = loc_element.inner_text().strip()

                ipv4_addresses.append(ip)
                locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    def _parse_ip_m27(page):
        """解析 https://ip.m27.tech 页面中的 IP 和归属地"""
        rows = page.query_selector_all(
            'body > div > div.panel.panel-success > div.panel-body > table > tbody > tr'
        )
        # print(f"共找到 {len(rows)} 行数据")
        ipv4_addresses, locations = [], []

        for row in rows:
            row_text = row.inner_text().strip()
            # 提取 IP 地址
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', row_text)
            if ip_match:
                ip = ip_match.group(1).strip()
                if not IpLocationParser._is_valid_ipv4(ip):
                    continue
            else:
                continue
        #
            # 提取归属地
            location_match = re.search(r'(China|中国).*', row_text)
            location = location_match.group(0).strip() if location_match else "未知"

            ipv4_addresses.append(ip)
            locations.append(location)

        return IpLocationParser._remove_duplicates(ipv4_addresses, locations)

    @staticmethod
    def get_ipv4(page, url: str) -> str:
        """返回多个中国 IP 地址，逗号分隔"""
        # 导航到目标页面
        page.goto(url)
        # 等待一段时间，让所有动态渲染的内容加载完成
        page.wait_for_timeout(8000)  # 等待 8 秒钟
        # 调用解析器解析数据
        ipv4_addresses, locations = IpLocationParser._parse(page, url)
        # 筛选出属于中国的 IP 地址
        china_ips = [
            ip for ip, location in zip(ipv4_addresses, locations)
            if 'China' in location or '中国' in location
        ]
        # 返回逗号分隔的字符串
        return ';'.join(china_ips)

    def _limit_and_deduplicate_ips(self, ips):
        """
        去重并限制 IP 地址数量，最多保存 _max_ips 个 IP 地址。
        """
        # 去重并保留顺序
        unique_ips = list(dict.fromkeys(ips))
        return unique_ips[:self._max_ips]  # 保留最多 _max_ips 个 IP 地址

    def _read_ips_from_json(self, field):
        """
        从 JSON 文件中读取指定字段的 IP 地址。
        """
        if not os.path.exists(self._settings_file_path):
            return ""  # 文件不存在，返回空字符串

        try:
            with open(self._settings_file_path, 'r') as f:
                data = json.load(f)
                # 获取字段内容并返回分号分隔的字符串
                return ";".join(data.get(field, []))
        except (json.JSONDecodeError, IOError):
            return ""  # 读取失败，返回空字符串

    def _overwrite_ips_in_json(self, field, new_ips):
        """
        覆盖写入指定字段的 IP 地址。
        :param field: 要更新的字段名
        :param new_ips: 新的 IP 地址列表或分号分隔的字符串
        """
        # 如果输入是字符串，将其转换为列表
        if isinstance(new_ips, str):
            new_ips = new_ips.split(";")

        # 去重并限制 IP 数量
        new_ips = self._limit_and_deduplicate_ips(new_ips)

        # 读取现有数据（如果文件不存在，则初始化空数据）
        if os.path.exists(self._settings_file_path):
            try:
                with open(self._settings_file_path, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}
        else:
            data = {}

        # 更新指定字段
        data[field] = new_ips

        # 写入文件
        with open(self._settings_file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def read_ips(self, field) -> str:
        """
        获取 JSON 文件中指定字段的所有 IP 地址，返回分号分隔的字符串。
        """
        return self._read_ips_from_json(field)

    def overwrite_ips(self, field, new_ips):
        """
        覆盖写入指定字段的新 IP 地址。
        """
        self._overwrite_ips_in_json(field, new_ips)

    def add_ips(self, field, new_ips):
        """
        增量添加指定字段中的 IP 地址。
        :param field: 要更新的字段名
        :param new_ips: 要添加的 IP 地址列表或分号分隔的字符串
        """
        # 获取当前的 IP 地址
        current_ips = self.read_ips(field).split(";") if self.read_ips(field) else []

        # 合并新 IP 地址并去重、限制数量
        updated_ips = self._limit_and_deduplicate_ips(new_ips.split(";") + current_ips)

        # 写入更新后的 IP 地址
        self.overwrite_ips(field, updated_ips)

