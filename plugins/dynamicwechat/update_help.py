import hashlib
from typing import Dict, Any
import json
import requests
from app.utils.common import encrypt


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
            resp = requests.get(self.url)
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
        if 'cookie_data' not in cookie:
            cookie = {'cookie_data': cookie}
        raw_data = json.dumps(cookie)
        encrypted_data = encrypt(raw_data.encode('utf-8'), self.get_the_key().encode('utf-8')).decode('utf-8')
        cookie_cloud_request = requests.post(self.url + '/update', json={'uuid': self.uuid, 'encrypted': encrypted_data})
        if cookie_cloud_request.status_code == 200:
            if cookie_cloud_request.json()['action'] == 'done':
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


