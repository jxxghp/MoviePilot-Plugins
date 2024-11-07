import os
import json
import requests
import base64
import hashlib
from typing import Dict, Any
from Crypto import Random
from Crypto.Cipher import AES

script_dir = os.path.dirname(os.path.abspath(__file__))
settings_file = os.path.join(script_dir, 'settings.json')


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
    def load_cookie_lifetime():    # 返回时间戳 单位秒
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as file:
                settings = json.load(file)
                return settings.get('_cookie_lifetime', 0)
        else:
            return 0

    @staticmethod
    def save_cookie_lifetime(cookie_lifetime):  # 传入时间戳 单位秒
        with open(settings_file, 'w') as file:
            json.dump({'_cookie_lifetime': cookie_lifetime}, file)

    @staticmethod
    def increase_cookie_lifetime(seconds: int):
        current_lifetime = PyCookieCloud.load_cookie_lifetime()
        new_lifetime = current_lifetime + seconds
        # 保存新的 _cookie_lifetime
        PyCookieCloud.save_cookie_lifetime(new_lifetime)
