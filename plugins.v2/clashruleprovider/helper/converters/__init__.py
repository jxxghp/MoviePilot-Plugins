from abc import ABC, abstractmethod
import base64
import binascii
import json
from typing import Dict, Any, Optional
from urllib.parse import unquote, urlparse, parse_qsl


class BaseConverter(ABC):
    """
    Abstract base class for all protocol converters.
    It defines a common interface and provides shared utility methods.
    """
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome'

    @abstractmethod
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        """
        Converts a subscription link to a proxy configuration dictionary.

        :param link: The subscription link string (e.g., "vmess://...").
        :param names: A dictionary to track and ensure unique proxy names.
        :return: A dictionary representing the proxy configuration, or None if conversion fails.
        """
        raise NotImplementedError

    @staticmethod
    def decode_base64(data):
        # Add fault tolerance for different padding
        data = data.strip()
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data)

    @staticmethod
    def decode_base64_urlsafe(data):
        data = data.strip()
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.urlsafe_b64decode(data)

    @staticmethod
    def try_decode_base64_json(data):
        try:
            return json.loads(BaseConverter.decode_base64(data).decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def unique_name(name_map: Dict[str, int], name: str) -> str:
        index = name_map.get(name, 0)
        name_map[name] = index + 1
        if index > 0:
            return f"{name}-{index:02d}"
        return name

    @staticmethod
    def lower_string(string: Optional[str]) -> Optional[str]:
        if isinstance(string, str):
            return string.lower()
        return string

    @staticmethod
    def handle_vshare_link(link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            url_info = urlparse(link)
            query = dict(parse_qsl(url_info.query))
            scheme = url_info.scheme.lower()

            if not url_info.hostname or not url_info.port:
                return None

            proxy: Dict[str, Any] = {
                'name': BaseConverter.unique_name(names,
                                                  unquote(url_info.fragment or f"{url_info.hostname}:{url_info.port}")),
                'type': scheme,
                'server': url_info.hostname,
                'port': url_info.port,
                'uuid': url_info.username,
                'udp': True
            }

            # TLS and Reality settings
            tls_mode = BaseConverter.lower_string(query.get('security'))
            if tls_mode in ['tls', 'reality']:
                proxy['tls'] = True
                proxy['client-fingerprint'] = query.get('fp', 'chrome')
                if 'alpn' in query:
                    proxy['alpn'] = query['alpn'].split(',')
                if 'sni' in query:
                    proxy['servername'] = query['sni']

                if tls_mode == 'reality':
                    proxy['reality-opts'] = {
                        'public-key': query.get('pbk'),
                        'short-id': query.get('sid')
                    }

            # Network settings
            network = BaseConverter.lower_string(query.get('type', 'tcp'))
            header_type = BaseConverter.lower_string(query.get('headerType'))

            if header_type == 'http':
                network = 'http'
            elif network == 'http':
                network = 'h2'

            proxy['network'] = network

            if network == 'tcp' and header_type == 'http':
                proxy['http-opts'] = {
                    'method': query.get('method', 'GET'),
                    'path': [query.get('path', '/')],
                    'headers': {'Host': [query.get('host', url_info.hostname)]}
                }
            elif network == 'h2':
                proxy["h2-opts"] = {
                    "path": query.get("path", "/"),
                    "host": [query.get("host", url_info.hostname)]
                }
            elif network in ['ws', 'httpupgrade']:
                ws_opts: Dict[str, Any] = {
                    'path': query.get('path', '/'),
                    'headers': {
                        'Host': query.get('host', url_info.hostname),
                        'User-Agent': BaseConverter.user_agent
                    }
                }
                if 'ed' in query:
                    try:
                        med = int(query['ed'])
                        if network == 'ws':
                            ws_opts['max-early-data'] = med
                            ws_opts['early-data-header-name'] = query.get('eh', 'Sec-WebSocket-Protocol')
                        elif network == 'httpupgrade':
                            ws_opts['v2ray-http-upgrade-fast-open'] = True
                    except (ValueError, TypeError):
                        pass
                proxy['ws-opts'] = ws_opts
            elif network == 'grpc':
                proxy['grpc-opts'] = {
                    'grpc-service-name': query.get('serviceName', '')
                }

            # Packet Encoding
            packet_encoding = BaseConverter.lower_string(query.get('packetEncoding'))
            if packet_encoding == 'packet':
                proxy['packet-addr'] = True
            elif packet_encoding != 'none':
                proxy['xudp'] = True

            # Encryption
            if 'encryption' in query and query['encryption']:
                proxy['encryption'] = query['encryption']

            if 'flow' in query:
                proxy['flow'] = query['flow']

            return proxy
        except Exception:
            return None
