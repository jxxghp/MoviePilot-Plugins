from typing import Dict, Any, Optional

from . import BaseConverter


class VmessConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            _, body = link.split("://", 1)
            vmess_data = self.try_decode_base64_json(body)
            # Xray VMessAEAD share link
            if vmess_data is None:
                return self.handle_vshare_link(link, names)

            name = self.unique_name(names, vmess_data.get("ps", "vmess"))
            net = self.lower_string(vmess_data.get("net"))
            fake_type = self.lower_string(vmess_data.get("type"))
            tls_mode = self.lower_string(vmess_data.get("tls"))
            cipher = vmess_data.get("scy", "auto") or "auto"
            alter_id = vmess_data.get("aid", 0)

            # Adjust network type
            if fake_type == "http":
                net = "http"
            elif net == "http":
                net = "h2"

            proxy = {
                "name": name,
                "type": "vmess",
                "server": vmess_data.get("add"),
                "port": vmess_data.get("port"),
                "uuid": vmess_data.get("id"),
                "alterId": alter_id,
                "cipher": cipher,
                "tls": tls_mode.endswith("tls") or tls_mode == "reality",
                "udp": True,
                "xudp": True,
                "skip-cert-verify": False,
                "network": net
            }

            # TLS Reality extension
            if proxy["tls"]:
                proxy["client-fingerprint"] = vmess_data.get("fp", "chrome") or "chrome"
                alpn = vmess_data.get("alpn")
                if alpn:
                    proxy["alpn"] = alpn.split(",") if isinstance(alpn, str) else alpn
                sni = vmess_data.get("sni")
                if sni:
                    proxy["servername"] = sni

                if tls_mode == "reality":
                    proxy["reality-opts"] = {
                        "public-key": vmess_data.get("pbk"),
                        "short-id": vmess_data.get("sid")
                    }

            path = vmess_data.get("path", "/")
            host = vmess_data.get("host")

            # Extension fields for different networks
            if net == "tcp":
                if fake_type == "http":
                    proxy["http-opts"] = {
                        "path": path,
                        "headers": {"Host": host} if host else {}
                    }
            elif net == "http":
                headers = {}
                if host:
                    headers["Host"] = [host]
                proxy["http-opts"] = {"path": [path], "headers": headers}

            elif net == "h2":
                proxy["h2-opts"] = {
                    "path": path,
                    "host": [host] if host else []
                }

            elif net == "ws":
                ws_headers = {"Host": host} if host else {}
                ws_headers["User-Agent"] = self.user_agent
                ws_opts = {
                    "path": path,
                    "headers": ws_headers
                }
                # Add early-data config
                early_data = vmess_data.get("ed")
                if early_data:
                    try:
                        ws_opts["max-early-data"] = int(early_data)
                    except ValueError:
                        pass
                early_data_header = vmess_data.get("edh")
                if early_data_header:
                    ws_opts["early-data-header-name"] = early_data_header
                proxy["ws-opts"] = ws_opts

            elif net == "grpc":
                proxy["grpc-opts"] = {
                    "grpc-service-name": path
                }
            return proxy
        except Exception:
            return None
