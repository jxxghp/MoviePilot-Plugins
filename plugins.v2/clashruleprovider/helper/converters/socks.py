import binascii
from typing import Dict, Any, Optional
from urllib.parse import urlparse, unquote

from . import BaseConverter


class SocksConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            server = parsed.hostname
            port = parsed.port
            name = self.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))

            username = None
            password = None
            if parsed.username:
                try:
                    # The userinfo part might be base64 encoded
                    decoded_userinfo = self.decode_base64(parsed.username.encode('utf-8')).decode('utf-8')
                    if ":" in decoded_userinfo:
                        username, password = decoded_userinfo.split(":", 1)
                    else:
                        username = decoded_userinfo
                except (binascii.Error, UnicodeDecodeError):
                    # If not base64 encoded, use directly
                    username = parsed.username
                    password = parsed.password if parsed.password else ""

            proxy = {
                "name": name,
                "type": "socks5",
                "server": server,
                "port": port,
                "username": username,
                "password": password,
                "skip-cert-verify": True
            }
            return proxy
        except Exception:
            return None
