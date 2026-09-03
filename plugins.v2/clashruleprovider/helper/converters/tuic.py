from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from . import BaseConverter


class TuicConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            query = dict(parse_qsl(parsed.query))

            user = parsed.username
            password = parsed.password
            server = parsed.hostname
            port = parsed.port

            name = self.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
            proxy = {
                "name": name,
                "type": "tuic",
                "server": server,
                "port": port,
                "udp": True
            }

            if password:
                proxy["uuid"] = user
                proxy["password"] = password
            else:
                proxy["token"] = user

            if "congestion_control" in query:
                proxy["congestion-controller"] = query["congestion_control"]
            if "alpn" in query:
                proxy["alpn"] = query["alpn"].split(",")
            if "sni" in query:
                proxy["sni"] = query["sni"]
            if query.get("disable_sni", "0") == "1":
                proxy["disable-sni"] = True
            if "udp_relay_mode" in query:
                proxy["udp-relay-mode"] = query["udp_relay_mode"]

            return proxy
        except Exception:
            return None
