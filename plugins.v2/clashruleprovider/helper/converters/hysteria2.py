from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from app.utils.string import StringUtils
from . import BaseConverter


class Hysteria2Converter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            query = dict(parse_qsl(parsed.query))

            user_info = ""
            if parsed.username:
                if parsed.password:
                    user_info = f"{parsed.username}:{parsed.password}"
                else:
                    user_info = parsed.username
            password = user_info

            server = parsed.hostname
            port = parsed.port or 443
            name = self.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
            proxy = {
                "name": name,
                "type": "hysteria2",
                "server": server,
                "port": port,
                "password": password,
                "obfs": query.get("obfs"),
                "obfs-password": query.get("obfs-password"),
                "sni": query.get("sni"),
                "skip-cert-verify": StringUtils.to_bool(query.get("insecure", "false")),
                "down": query.get("down"),
                "up": query.get("up"),
            }
            if "pinSHA256" in query:
                proxy["fingerprint"] = query.get("pinSHA256")
            if "alpn" in query:
                proxy["alpn"] = query["alpn"].split(",")
            return proxy
        except Exception:
            return None
