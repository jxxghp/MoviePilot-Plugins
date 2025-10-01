import base64
import importlib
import json
import os
from typing import List, Dict, Any, Optional, Union
from urllib.parse import quote

from .converters import BaseConverter


class Converter:
    """
    A refactored converter for V2Ray subscriptions that uses a strategy pattern.
    It dynamically loads protocol-specific converters from the 'converters' directory.
    """

    def __init__(self):
        self._converters: Dict[str, BaseConverter] = self._load_converters()

    def _load_converters(self) -> Dict[str, BaseConverter]:
        """
        Dynamically discovers and loads all converter classes from the .py files
        in the 'converters' directory.
        """
        converters: Dict[str, BaseConverter] = {}
        converter_dir = os.path.dirname(__file__)
        module_names = [f.replace('.py', '') for f in os.listdir(os.path.join(converter_dir, 'converters'))
                        if f.endswith('.py') and not f.startswith('__')]

        for module_name in module_names:
            try:
                module = importlib.import_module(f".converters.{module_name}", package=__package__)
                class_name = f"{module_name.capitalize()}Converter"
                converter_class = getattr(module, class_name, None)

                if converter_class and issubclass(converter_class, BaseConverter):
                    instance = converter_class()
                    # Determine the protocol scheme based on the module name
                    scheme = module_name
                    if scheme == 'http':
                        converters['http'] = instance
                        converters['https'] = instance
                    elif scheme == 'socks':
                        converters['socks'] = instance
                        converters['socks5'] = instance
                        converters['socks5h'] = instance
                    elif scheme == 'hysteria2':
                        converters['hysteria2'] = instance
                        converters['hy2'] = instance
                    else:
                        converters[scheme] = instance
            except (ImportError, AttributeError) as e:
                # Log this error appropriately in a real application
                print(f"Could not load converter for {module_name}: {e}")
        return converters

    def convert_line(self, line: str, names: Optional[Dict[str, int]] = None, skip_exception: bool = True
                     ) -> Optional[Dict[str, Any]]:
        """
        Parses a single subscription link and converts it to a proxy dictionary.
        """
        if names is None:
            names = {}

        if "://" not in line:
            return None

        scheme, _ = line.split("://", 1)
        scheme = scheme.lower()

        converter = self._converters.get(scheme)
        if converter:
            try:
                return converter.convert(line, names)
            except Exception as e:
                if not skip_exception:
                    raise ValueError(f"{scheme.upper()} parse error: {e}") from e
                return None
        return None

    def convert_v2ray(self, v2ray_link: Union[list, bytes], skip_exception: bool = True) -> List[Dict[str, Any]]:
        """
        Converts a base64 encoded V2Ray subscription content or a list of links
        into a list of proxy dictionaries.
        """
        if isinstance(v2ray_link, bytes):
            decoded = BaseConverter.decode_base64(v2ray_link).decode("utf-8")
            lines = decoded.strip().splitlines()
        else:
            lines = v2ray_link

        proxies = []
        names = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            proxy = self.convert_line(line, names, skip_exception=skip_exception)
            if proxy:
                proxies.append(proxy)
            elif not skip_exception:
                raise ValueError("Failed to convert one of the links in the subscription.")
        return proxies

    @staticmethod
    def convert_to_share_link(proxy_config: Dict[str, Any]) -> Optional[str]:
        proxy_type = proxy_config.get("type")
        name = proxy_config.get("name", "proxy")

        if proxy_type == "vmess":
            vmess_config = {
                "v": "2",
                "ps": name,
                "add": proxy_config.get("server", ""),
                "port": str(proxy_config.get("port", "")),
                "id": proxy_config.get("uuid", ""),
                "aid": str(proxy_config.get("alterId", 0)),
                "scy": proxy_config.get("cipher", "auto"),
                "net": proxy_config.get("network", "tcp"),
                "type": "none",
                "tls": "tls" if proxy_config.get("tls") else "",
                "host": "",
                "path": "/",
            }

            if proxy_config.get("network") == "http":
                vmess_config["type"] = "http"

            network = proxy_config.get("network")
            if network == "ws":
                ws_opts = proxy_config.get("ws-opts", {})
                vmess_config["host"] = ws_opts.get("headers", {}).get("Host", "")
                vmess_config["path"] = ws_opts.get("path", "/")
            elif network == "http":
                http_opts = proxy_config.get("http-opts", {})
                vmess_config["host"] = http_opts.get("headers", {}).get("Host", "")
                vmess_config["path"] = http_opts.get("path", "/")
            elif network == "h2":
                h2_opts = proxy_config.get("h2-opts", {})
                vmess_config["host"] = h2_opts.get("host")[0] if h2_opts.get("host") else ""
                vmess_config["path"] = h2_opts.get("path", "/")
            # Remove empty values to keep the JSON clean
            vmess_config = {k: v for k, v in vmess_config.items() if v not in ["", None]}
            encoded_str = base64.b64encode(json.dumps(vmess_config).encode("utf-8")).decode("utf-8")
            return f"vmess://{encoded_str}"

        elif proxy_type == "ss":
            method = proxy_config.get("cipher")
            password = proxy_config.get("password")
            server = proxy_config.get("server")
            port = proxy_config.get("port")
            if not all([method, password, server, port]):
                return None
            credentials = f"{method}:{password}@{server}:{port}"
            encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
            return f"ss://{encoded_credentials}#{quote(name)}"

        elif proxy_type == "trojan":
            password = proxy_config.get("password")
            server = proxy_config.get("server")
            port = proxy_config.get("port")
            if not all([password, server, port]):
                return None

            query_params = {}
            if proxy_config.get("sni"):
                query_params["sni"] = proxy_config["sni"]
            if proxy_config.get("alpn"):
                query_params["alpn"] = ",".join(proxy_config["alpn"])
            if proxy_config.get("skip-cert-verify"):
                query_params["allowInsecure"] = "1"

            network = proxy_config.get("network")
            if network:
                query_params["type"] = network
                if network == "ws":
                    ws_opts = proxy_config.get("ws-opts", {})
                    path = ws_opts.get("path", "/")
                    host = ws_opts.get("headers", {}).get("Host", "")
                    # Always add path and host for ws if they exist, even if defaulted, for round-trip consistency
                    if path:
                        query_params["path"] = path
                    if host:
                        query_params["host"] = host
                elif network == "grpc":
                    grpc_opts = proxy_config.get("grpc-opts", {})
                    service_name = grpc_opts.get("grpc-service-name", "")
                    if service_name:
                        query_params["serviceName"] = service_name

            client_fingerprint = proxy_config.get("client-fingerprint")
            # Always add fp if it exists, to ensure round-trip consistency, as convert_v2ray defaults to "chrome"
            if client_fingerprint:
                query_params["fp"] = client_fingerprint

            query_string = "&".join([f"{k}={quote(str(v))}" for k, v in query_params.items()])

            base_link = f"trojan://{password}@{server}:{port}"
            if query_string:
                return f"{base_link}?{query_string}#{quote(name)}"
            else:
                return f"{base_link}#{quote(name)}"
        elif proxy_type == "vless":
            uuid = proxy_config.get("uuid")
            server = proxy_config.get("server")
            port = proxy_config.get("port")
            if not all([uuid, server, port]):
                return None

            query_params = {}
            name = proxy_config.get("name", f"{server}:{port}")

            tls = proxy_config.get("tls", False)
            if tls:
                if "reality-opts" in proxy_config:
                    query_params["security"] = "reality"
                    reality_opts = proxy_config["reality-opts"]
                    if reality_opts.get("public-key"):
                        query_params["pbk"] = reality_opts["public-key"]
                    if reality_opts.get("short-id"):
                        query_params["sid"] = reality_opts["short-id"]
                else:
                    query_params["security"] = "tls"

                if proxy_config.get("client-fingerprint"):
                    query_params["fp"] = proxy_config["client-fingerprint"]
                if proxy_config.get("alpn"):
                    query_params["alpn"] = ",".join(proxy_config["alpn"])
                if proxy_config.get("skip-cert-verify"):
                    query_params["allowInsecure"] = "1"

            if proxy_config.get("servername"):
                query_params["sni"] = proxy_config["servername"]

            # Network settings
            network = proxy_config.get("network", "tcp")
            query_params["type"] = network

            if network == "ws":
                ws_opts = proxy_config.get("ws-opts", {})
                path = ws_opts.get("path", "")
                host = ws_opts.get("headers", {}).get("Host", "")
                if path:
                    query_params["path"] = path
                if host:
                    query_params["host"] = host
            elif network == "grpc":
                grpc_opts = proxy_config.get("grpc-opts", {})
                service_name = grpc_opts.get("grpc-service-name", "")
                if service_name:
                    query_params["serviceName"] = service_name

            if proxy_config.get("flow"):
                query_params["flow"] = proxy_config["flow"]

            query_string = "&".join([f"{k}={quote(str(v))}" for k, v in query_params.items()])

            base_link = f"vless://{uuid}@{server}:{port}"
            if query_string:
                return f"{base_link}?{query_string}#{quote(name)}"
            else:
                return f"{base_link}#{quote(name)}"

        elif proxy_type == "ssr":
            server = proxy_config.get("server")
            port = proxy_config.get("port")
            protocol = proxy_config.get("protocol", "origin")
            cipher = proxy_config.get("cipher")
            obfs = proxy_config.get("obfs", "plain")
            password = proxy_config.get("password")
            name = proxy_config.get("name", f"{server}:{port}")

            if not all([server, port, protocol, cipher, obfs, password]):
                return None

            password_enc = base64.urlsafe_b64encode(password.encode("utf-8")).decode("utf-8").rstrip('=')
            ssr_main_part = f"{server}:{port}:{protocol}:{cipher}:{obfs}:{password_enc}"

            query_params = {}
            if proxy_config.get("obfs-param"):
                query_params["obfsparam"] = base64.urlsafe_b64encode(
                    proxy_config["obfs-param"].encode("utf-8")).decode("utf-8").rstrip('=')
            if proxy_config.get("protocol-param"):
                query_params["protoparam"] = base64.urlsafe_b64encode(
                    proxy_config["protocol-param"].encode("utf-8")).decode("utf-8").rstrip('=')

            query_params["remarks"] = base64.urlsafe_b64encode(name.encode("utf-8")).decode("utf-8").rstrip('=')
            query_params["group"] = base64.urlsafe_b64encode("MoviePilot".encode("utf-8")).decode("utf-8").rstrip('=')

            query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])

            full_ssr_link_body = f"{ssr_main_part}/?{query_string}"
            encoded_full_ssr_link_body = base64.urlsafe_b64encode(
                full_ssr_link_body.encode("utf-8")).decode("utf-8").rstrip('=')

            return f"ssr://{encoded_full_ssr_link_body}"

        return None
