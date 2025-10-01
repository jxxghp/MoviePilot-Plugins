from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from app.utils.string import StringUtils
from . import BaseConverter


class HysteriaConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            query = dict(parse_qsl(parsed.query))

            name = self.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))
            hysteria: Dict[str, Any] = {
                "name": name,
                "type": "hysteria",
                "server": parsed.hostname,
                "port": parsed.port,
            }

            auth_str = query.get("auth")
            if auth_str:
                hysteria["auth_str"] = auth_str
            obfs = query.get("obfs")
            if obfs:
                hysteria["obfs"] = obfs
            sni = query.get("peer")
            if sni:
                hysteria["sni"] = sni
            protocol = query.get("protocol")
            if protocol:
                hysteria["protocol"] = protocol
            up = query.get("up")
            if not up:
                up = query.get("upmbps")
            if up:
                hysteria["up"] = up
            down = query.get("down")
            if not down:
                down = query.get("downmbps")
            if down:
                hysteria["down"] = down
            alpn = query.get("alpn", "")
            if alpn:
                hysteria["alpn"] = alpn.split(",")

            # skip-cert-verify
            insecure_str = query.get("insecure", "false")
            try:
                skip_cert_verify = StringUtils.to_bool(insecure_str)
                if skip_cert_verify:
                    hysteria["skip-cert-verify"] = skip_cert_verify
            except ValueError:
                pass
            return hysteria
        except Exception:
            return None
