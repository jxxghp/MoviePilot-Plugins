import binascii
from typing import Dict, Any, Optional
from urllib.parse import parse_qsl

from . import BaseConverter


class SsrConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            _, body = link.split("://", 1)
            try:
                decoded_body = self.decode_base64_urlsafe(body).decode('utf-8')
            except (binascii.Error, UnicodeDecodeError):
                decoded_body = self.decode_base64(body).decode('utf-8')

            parts, _, params_str = decoded_body.partition("/?")

            part_list = parts.split(":", 5)
            if len(part_list) != 6:
                raise ValueError("Invalid SSR link format: incorrect number of parts")

            host, port_str, protocol, method, obfs, password_enc = part_list

            try:
                port = int(port_str)
            except ValueError:
                raise ValueError("Invalid port in SSR link")

            password = self.decode_base64_urlsafe(password_enc).decode('utf-8')
            params = dict(parse_qsl(params_str))
            remarks_b64 = params.get("remarks", "")
            remarks = self.decode_base64_urlsafe(remarks_b64).decode('utf-8') if remarks_b64 else ""

            obfsparam_b64 = params.get("obfsparam", "")
            obfsparam = self.decode_base64_urlsafe(obfsparam_b64).decode(
                'utf-8') if obfsparam_b64 else ""

            protoparam_b64 = params.get("protoparam", "")
            protoparam = self.decode_base64_urlsafe(protoparam_b64).decode(
                'utf-8') if protoparam_b64 else ""

            name = self.unique_name(names, remarks or f"{host}:{port}")

            proxy = {
                "name": name,
                "type": "ssr",
                "server": host,
                "port": port,
                "cipher": method,
                "password": password,
                "obfs": obfs,
                "protocol": protocol,
                "udp": True
            }

            if obfsparam:
                proxy["obfs-param"] = obfsparam
            if protoparam:
                proxy["protocol-param"] = protoparam

            return proxy
        except Exception:
            return None
