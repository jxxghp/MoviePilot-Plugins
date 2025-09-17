from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from . import BaseConverter


class AnytlsConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            query = dict(parse_qsl(parsed.query))

            username = parsed.username
            password = parsed.password or username
            server = parsed.hostname
            port = parsed.port
            insecure = query.get("insecure", "0") == "1"
            sni = query.get("sni")
            fingerprint = query.get("hpkp")

            name = self.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
            proxy = {
                "name": name,
                "type": "anytls",
                "server": server,
                "port": port,
                "username": username,
                "password": password,
                "sni": sni,
                "fingerprint": fingerprint,
                "skip-cert-verify": insecure,
                "udp": True
            }
            return proxy
        except Exception:
            return None
