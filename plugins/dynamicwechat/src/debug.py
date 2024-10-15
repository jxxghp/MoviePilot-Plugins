
from Cryptodome import Random
from Cryptodome.Cipher import AES
import base64
import json
import hashlib
import requests
from playwright.sync_api import sync_playwright
from typing import Dict, Any


class PyCookieCloud:
    def __init__(self, url: str, uuid: str, password: str):
        self.url: str = url
        self.uuid: str = uuid
        self.password: str = password
        self.BLOCK_SIZE = 16

    def check_connection(self) -> bool:
        """
        Test the connection to the CookieCloud server.

        :return: True if the connection is successful, False otherwise.
        """
        try:
            resp = requests.get(self.url)
            # print(self.url)
            if resp.status_code == 200:
                return True
            else:
                return False
        except Exception as e:
            return False

    def update_cookie(self, cookie: Dict[str, Any]) -> bool:
        """
        Update cookie data to CookieCloud.

        :param cookie: cookie value to update, if this cookie does not contain 'cookie_data' key, it will be added into 'cookie_data'.
        :return: if update success, return True, else return False.
        """
        # 确保 cookie 是完整的结构，并直接放入 cookie_data 中
        # cookie_data = {
        #     "cookie_data": cookie  # 直接将 cookie 数据放入 cookie_data
        # }
        raw_data = json.dumps(cookie)
        encrypted_data = self.encrypt(raw_data.encode('utf-8'), self.get_the_key().encode('utf-8')).decode('utf-8')

        request_data = {'uuid': self.uuid, 'encrypted': encrypted_data}
        print("请求数据:", request_data)  # 打印请求数据
        # headers = {'Content-Type': 'application/json'}  # 设置请求头为 JSON
        cookie_cloud_request = requests.post(self.url + '/update', json=request_data)
        print(cookie_cloud_request)  # 打印响应对象

        if cookie_cloud_request.status_code != 200:
            print("错误信息:", cookie_cloud_request.text)  # 打印错误信息

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

    def bytes_to_key(self, data, salt, output=48):
        # extended from https://gist.github.com/gsakkis/4546068
        assert len(salt) == 8, len(salt)
        data += salt
        key = hashlib.md5(data).digest()
        final_key = key
        while len(final_key) < output:
            key = hashlib.md5(key + data).digest()
            final_key += key
        return final_key[:output]

    def pad(self, data):
        length = self.BLOCK_SIZE - (len(data) % self.BLOCK_SIZE)
        return data + (chr(length) * length).encode()

    def encrypt(self, message: bytes, passphrase: bytes) -> bytes:
        # 请替换为实际的加密实现，以下是示例
        # 使用 AES 或其他算法进行加密
        # 这里只是一个占位符，实际实现请根据需要修改
        # def encrypt(message, passphrase):
        salt = Random.new().read(8)
        key_iv = self.bytes_to_key(passphrase, salt, 32 + 16)
        key = key_iv[:32]
        iv = key_iv[32:]
        aes = AES.new(key, AES.MODE_CBC, iv)
        return base64.b64encode(b"Salted__" + salt + aes.encrypt(self.pad(message)))
        # return message  # 示例：返回原始消息


def main(server: str, url: str, uuid: str, password: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # 打开指定的 URL
        page.goto(url)

        # 等待 60 秒用户登录
        print("请在30秒内完成登录...")
        page.wait_for_timeout(30000)  # 等待60秒

        # 获取 cookies
        cookies = page.context.cookies()

        # 关闭浏览器
        browser.close()

        # 创建 PyCookieCloud 实例并上传 cookies
        py_cookie_cloud = PyCookieCloud(url=server, uuid=uuid, password=password)
        cookie_data = {cookie['name']: cookie['value'] for cookie in cookies}  # 转换为字典形式
        if (py_cookie_cloud.check_connection()):
            print("连接成功，请稍等片刻...")
            result = py_cookie_cloud.update_cookie(cookie_data)
        else:
            print("连接失败，请检查网络连接")
            result = False

        if result:
            print("Cookies 上传成功！")
        else:
            print("Cookies 上传失败！")


if __name__ == "__main__":
    # 设置参数
    server = "http://172.16.8.110:43000/cookiecloud"
    target_url = "https://work.weixin.qq.com/wework_admin/loginpage_wx?from=myhome"  # 请替换为实际的目标 URL
    uuid = "hFQrymvqMBX11d14TTmKb6"  # 替换为实际的 UUID
    password = "2Bfr3LmzVy3t3bsQ5FLAbZ"  # 替换为实际的密码
    main(server, target_url, uuid, password)
