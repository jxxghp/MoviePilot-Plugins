import re
import requests
from app.modules.wechat import WeChat
from app.schemas.types import NotificationType,MessageChannel

import os
import json
import requests
import base64
import hashlib
from typing import Dict, Any
from Crypto import Random
from Crypto.Cipher import AES


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
    def load_cookie_lifetime(settings_file: str = None):    # 返回时间戳 单位秒
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as file:
                settings = json.load(file)
                return settings.get('_cookie_lifetime', 0)
        else:
            return 0

    @staticmethod
    def save_cookie_lifetime(settings_file, cookie_lifetime):  # 传入时间戳 单位秒
        with open(settings_file, 'w') as file:
            json.dump({'_cookie_lifetime': cookie_lifetime}, file)

    @staticmethod
    def increase_cookie_lifetime(settings_file, seconds: int):
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as file:
                settings = json.load(file)
                current_lifetime = settings.get('_cookie_lifetime', 0)
        else:
            current_lifetime = 0
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

    @staticmethod
    def _detect_channel(token):
        """根据 token 确定通知渠道"""
        if "WeChat" in token:
            return "WeChat"

        letters_only = ''.join(re.findall(r'[A-Za-z]', token))
        if token.lower().startswith("sct"):
            return "ServerChan"
        elif letters_only.isupper():
            return "AnPush"
        else:
            return "PushPlus"

    def send(self, title, content=None, image=None, force_send=False, diy_channel=None):
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
            return self._try_send(title, content, image, diy_channel)

        # 尝试按顺序发送，直到成功或遍历所有通道
        for i in range(len(self.tokens)):
            token = self.tokens[self.current_index]
            channel = self.channels[self.current_index]
            try:
                result = self._try_send(title, content, image, channel, token)
                if result is None:  # 成功时返回 None
                    return
            except Exception as e:
                pass     # 忽略单个错误，继续尝试下一个通道
            self.current_index = (self.current_index + 1) % len(self.tokens)
        return f"所有的通知方式都发送失败"

    def _try_send(self, title, content, image, channel, token=None):
        """尝试使用指定通道发送消息"""
        if channel == "WeChat" and self.post_message_func:
            return self._send_v2_wechat(title, content, image, token)
        elif channel == "WeChat":
            return self._send_wechat(title, content, image, token)
        elif channel == "ServerChan":
            return self._send_serverchan(title, content, image)
        elif channel == "AnPush":
            return self._send_anpush(title, content, image)
        elif channel == "PushPlus":
            return self._send_pushplus(title, content, image)
        else:
            raise ValueError(f"Unknown channel: {channel}")

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

        if send_status is None:
            return "微信通知发送错误"
        return None

    def _send_serverchan(self, title, content, image):
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

    def _send_anpush(self, title, content, image):
        token = self.tokens[self.current_index]  # 获取当前通道对应的 token
        if ',' in token:
            channel, token = token.split(',', 1)
        else:
            return "可能AnPush 没有配置消息通道ID"
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

    def _send_pushplus(self, title, content, image):
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
