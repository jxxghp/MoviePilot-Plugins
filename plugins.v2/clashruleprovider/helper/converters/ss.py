import binascii
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from . import BaseConverter


class SsConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)

            if parsed.port is None and parsed.netloc:
                base64_body = parsed.netloc
                decoded_body = self.decode_base64_urlsafe(base64_body).decode('utf-8')

                new_line = f"ss://{decoded_body}"
                if parsed.fragment:
                    new_line += f"#{parsed.fragment}"
                parsed = urlparse(new_line)

            name = self.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))

            cipher_raw = parsed.username
            password = parsed.password
            cipher = cipher_raw

            if not password and cipher_raw:
                try:
                    decoded_user = self.decode_base64_urlsafe(cipher_raw).decode('utf-8')
                except (binascii.Error, UnicodeDecodeError):
                    decoded_user = self.decode_base64(cipher_raw).decode('utf-8')

                if ":" in decoded_user:
                    cipher, password = decoded_user.split(":", 1)
                else:
                    cipher = decoded_user

            server = parsed.hostname
            port = parsed.port
            query = dict(parse_qsl(parsed.query))
            proxy = {
                "name": name,
                "type": "ss",
                "server": server,
                "port": port,
                "cipher": cipher,
                "password": password,
                "udp": True
            }
            if query.get("udp-over-tcp") == "true" or query.get("uot") == "1":
                proxy["udp-over-tcp"] = True
            plugin = query.get("plugin")
            if plugin and ";" in plugin:
                query_string = "pluginName=" + plugin.replace(";", "&")
                plugin_info = dict(parse_qsl(query_string))
                plugin_name = plugin_info.get("pluginName", "")

                if "obfs" in plugin_name:
                    proxy["plugin"] = "obfs"
                    proxy["plugin-opts"] = {
                        "mode": plugin_info.get("obfs"),
                        "host": plugin_info.get("obfs-host"),
                    }
                elif "v2ray-plugin" in plugin_name:
                    proxy["plugin"] = "v2ray-plugin"
                    proxy["plugin-opts"] = {
                        "mode": plugin_info.get("mode"),
                        "host": plugin_info.get("host"),
                        "path": plugin_info.get("path"),
                        "tls": "tls" in plugin,
                    }
            return proxy
        except Exception:
            return None
