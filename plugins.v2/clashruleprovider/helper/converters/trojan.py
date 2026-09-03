from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qsl, unquote

from app.utils.string import StringUtils
from . import BaseConverter


class TrojanConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            parsed = urlparse(link)
            query = dict(parse_qsl(parsed.query))

            name = self.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))

            trojan: Dict[str, Any] = {
                "name": name,
                "type": "trojan",
                "server": parsed.hostname,
                "port": parsed.port or 443,
                "password": parsed.username or "",
                "udp": True,
                "tls": True
            }

            # skip-cert-verify
            try:
                trojan["skip-cert-verify"] = StringUtils.to_bool(query.get("allowInsecure", "0"))
            except ValueError:
                trojan["skip-cert-verify"] = False

            # optional fields
            if "sni" in query:
                trojan["sni"] = query["sni"]

            alpn = query.get("alpn")
            if alpn:
                trojan["alpn"] = alpn.split(",")

            network = query.get("type", "").lower()
            if network:
                trojan["network"] = network

            if network == "ws":
                headers = {"User-Agent": self.user_agent}
                trojan["ws-opts"] = {
                    "path": query.get("path", "/"),
                    "headers": headers
                }

            elif network == "grpc":
                trojan["grpc-opts"] = {
                    "grpc-service-name": query.get("serviceName")
                }

            fp = query.get("fp")
            trojan["client-fingerprint"] = fp if fp else "chrome"
            return trojan
        except Exception:
            return None
