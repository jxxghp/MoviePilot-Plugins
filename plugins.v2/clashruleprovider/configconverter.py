import base64
import binascii
import json

from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse, parse_qs, unquote, parse_qsl, quote


class Converter:
    """
    Converter for V2Ray Subscription

    Reference:
    https://github.com/MetaCubeX/mihomo/blob/Alpha/common/convert/converter.go
    https://github.com/SubConv/SubConv/blob/main/modules/convert/converter.py
    """
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome'

    @staticmethod
    def decode_base64(data):
        # 添加适配不同 padding 的容错机制
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
            return json.loads(Converter.decode_base64(data).decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def unique_name(name_map, name):
        index = name_map.get(name, 0)
        name_map[name] = index + 1
        if index > 0:
            return f"{name}-{index:02d}"
        return name

    @staticmethod
    def strtobool(val):
        val = val.lower()
        if val in ("y", "yes", "t", "true", "on", "1"):
            return True
        elif val in ("n", "no", "f", "false", "off", "0"):
            return False
        else:
            raise ValueError(f"invalid truth value {val!r}")

    @staticmethod
    def convert_v2ray(v2ray_link: Union[list, bytes], skip_exception: bool = True) -> List[Dict[str, Any]]:
        if isinstance(v2ray_link, bytes):
            decoded = Converter.decode_base64(v2ray_link).decode("utf-8")
            lines = decoded.strip().splitlines()
        else:
            lines = v2ray_link
        proxies = []
        names = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue

            if "://" not in line:
                continue

            scheme, body = line.split("://", 1)
            scheme = scheme.lower()

            if scheme == "vmess":
                try:
                    vmess_data = Converter.try_decode_base64_json(body)
                    name = Converter.unique_name(names, vmess_data.get("ps", "vmess"))
                    net = str(vmess_data.get("net", "")).lower()
                    fake_type = str(vmess_data.get("type", "")).lower()
                    tls_mode = str(vmess_data.get("tls", "")).lower()
                    cipher = vmess_data.get("scy", "auto") or "auto"
                    alter_id = vmess_data.get("aid", 0)

                    # 调整 network 类型
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

                    # TLS Reality 扩展
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
                                "public-key": vmess_data.get("pbk", ""),
                                "short-id": vmess_data.get("sid", "")
                            }

                    path = vmess_data.get("path", "/")
                    host = vmess_data.get("host")

                    # 不同 network 的扩展字段处理
                    if net == "tcp":
                        if fake_type == "http":
                            proxy["http-opts"] = {
                                "path": path,
                                "headers": {"Host": host} if host else {}
                            }
                    elif net == "http":
                        proxy["network"] = "http"
                        proxy["http-opts"] = {
                            "path": path,
                            "headers": {"Host": host} if host else {}
                        }
                    elif net == "h2":
                        proxy["h2-opts"] = {
                            "path": path,
                            "host": [host] if host else []
                        }

                    elif net == "ws":
                        ws_headers = {"Host": host} if host else {}
                        ws_headers["User-Agent"] = Converter.user_agent
                        ws_opts = {
                            "path": path,
                            "headers": ws_headers
                        }
                        # 补充 early-data 配置
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
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"VMESS parse error: {e}") from e

            elif scheme == "vless":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))
                    uuid = parsed.username or ""
                    server = parsed.hostname or ""
                    port = parsed.port or 443
                    tls_mode = query.get("security", "").lower()
                    tls = tls_mode == "tls" or tls_mode == "reality"
                    sni = query.get("sni", "")
                    flow = query.get("flow", "")
                    network = query.get("type", "tcp")
                    path = query.get("path", "")
                    host = query.get("host", "")
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy: Dict[str, Any] = {
                        "name": name,
                        "type": "vless",
                        "server": server,
                        "port": port,
                        "uuid": uuid,
                        "tls": tls,
                        "udp": True
                    }

                    if sni:
                        proxy["servername"] = sni
                    if flow:
                        proxy["flow"] = flow
                    if tls:
                        proxy["skip-cert-verify"] = Converter.strtobool(query.get("allowInsecure", "0"))
                    if network:
                        proxy["network"] = network
                        if network in ["ws", "httpupgrade"]:
                            headers = {"User-Agent": Converter.user_agent}
                            if host:
                                headers["Host"] = host
                            ws_opts: Dict[str, Any] = {"path": path, "headers": headers}
                            try:
                                parsed_path = urlparse(path)
                                q = dict(parse_qsl(parsed_path.query))
                                if "ed" in q:
                                    med = int(q["ed"])
                                    if network == "ws":
                                        ws_opts["max-early-data"] = med
                                        ws_opts["early-data-header-name"] = q.get("eh", "Sec-WebSocket-Protocol")
                                elif network == "httpupgrade":
                                    ws_opts["v2ray-http-upgrade-fast-open"] = True
                                if "eh" in q and q["eh"]:
                                    ws_opts["early-data-header-name"] = q["eh"]
                            except Exception:
                                pass
                            proxy["ws-opts"] = ws_opts

                        elif network == "grpc":
                            proxy["grpc-opts"] = {
                                "grpc-service-name": query.get("serviceName", "")

                            }

                    if tls_mode == "reality":
                        proxy["reality-opts"] = {
                            "public-key": query.get("pbk", "")
                        }
                        if query.get("sid"):
                            proxy["reality-opts"]["short-id"] = query.get("sid", "")
                        proxy["client-fingerprint"] = query.get("fp", "chrome")
                        alpn = query.get("alpn", "")
                        if alpn:
                            proxy["alpn"] = alpn.split(",")
                    if tls_mode.endswith("tls"):
                        proxy["client-fingerprint"] = query.get("fp", "chrome")
                        alpn = query.get("alpn", "")
                        if alpn:
                            proxy["alpn"] = alpn.split(",")
                    proxies.append(proxy)

                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"VLESS parse error: {e}") from e

            elif scheme == "trojan":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))

                    trojan = {
                        "name": name,
                        "type": "trojan",
                        "server": parsed.hostname,
                        "port": parsed.port or 443,
                        "password": parsed.username or "",
                        "udp": True,
                    }

                    # skip-cert-verify
                    try:
                        trojan["skip-cert-verify"] = Converter.strtobool(query.get("allowInsecure", "0"))
                    except ValueError:
                        trojan["skip-cert-verify"] = False

                    # optional fields
                    if "sni" in query:
                        trojan["sni"] = query["sni"]

                    alpn = query.get("alpn", "")
                    if alpn:
                        trojan["alpn"] = alpn.split(",")

                    network = query.get("type", "").lower()
                    if network:
                        trojan["network"] = network

                    if network == "ws":
                        headers = {"User-Agent": Converter.user_agent}
                        trojan["ws-opts"] = {
                            "path": query.get("path", "/"),
                            "headers": headers
                        }

                    elif network == "grpc":
                        trojan["grpc-opts"] = {
                            "grpc-service-name": query.get("serviceName", "")
                        }

                    fp = query.get("fp", "")
                    trojan["client-fingerprint"] = fp if fp else "chrome"

                    proxies.append(trojan)

                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Trojan parse error: {e}") from e

            elif scheme == "hysteria":
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{parsed.hostname}:{parsed.port}"))
                    hysteria = {
                        "name": name,
                        "type": "hysteria",
                        "server": parsed.hostname,
                        "port": parsed.port,
                        "auth_str": parsed.username or query.get("auth", ""),
                        "obfs": query.get("obfs", ""),
                        "sni": query.get("peer", ""),
                        "protocol": query.get("protocol", "")
                    }

                    up = query.get("up", "")
                    down = query.get("down", "")
                    if not up:
                        up = query.get("upmbps", "")
                    if not down:
                        down = query.get("downmbps", "")
                    hysteria["up"] = up
                    hysteria["down"] = down

                    # alpn split
                    alpn = query.get("alpn", "")
                    if alpn:
                        hysteria["alpn"] = alpn.split(",")

                    # skip-cert-verify
                    try:
                        hysteria["skip-cert-verify"] = Converter.strtobool(query.get("insecure", "false"))
                    except ValueError:
                        hysteria["skip-cert-verify"] = False

                    proxies.append(hysteria)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Hysteria parse error: {e}") from e

            elif scheme in ("socks", "socks5", "socks5h"):
                try:
                    parsed = urlparse(line)
                    server = parsed.hostname
                    port = parsed.port
                    username = parsed.username or ""
                    password = parsed.password or ""
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))

                    proxy = {
                        "name": name,
                        "type": "socks5",
                        "server": server,
                        "port": port,
                        "username": username,
                        "password": password,
                        "udp": True
                    }
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SOCKS5 parse error: {e}") from e

            elif scheme == "ss":
                try:
                    parsed = urlparse(line)
                    # 兼容 ss://base64 或 ss://base64#name
                    if parsed.fragment:
                        name = Converter.unique_name(names, unquote(parsed.fragment))
                    else:
                        name = Converter.unique_name(names, "ss")
                    if parsed.port is None:
                        base64_body = body.split("#")[0]
                        parsed = urlparse(f"ss://{Converter.decode_base64(base64_body).decode('utf-8')}")
                    cipher_raw = parsed.username
                    cipher = cipher_raw
                    password = parsed.password
                    if not password:
                        dc_buf = Converter.decode_base64(cipher_raw).decode('utf-8')
                        if dc_buf.startswith("ss://"):
                            dc_buf = dc_buf[len("ss://"):]
                            dc_buf = Converter.decode_base64(dc_buf).decode('utf-8')
                        cipher, password = dc_buf.split(":", 1)
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
                    plugin = query.get("plugin")
                    if plugin and ";" in plugin:
                        query_string = "pluginName=" + plugin.replace(";", "&")
                        plugin_info = parse_qs(query_string)
                        plugin_name = plugin_info.get("pluginName", [""])[0]

                        if "obfs" in plugin_name:
                            proxy["plugin"] = "obfs"
                            proxy["plugin-opts"] = {
                                "mode": plugin_info.get("obfs", [""])[0],
                                "host": plugin_info.get("obfs-host", [""])[0],
                            }
                        elif "v2ray-plugin" in plugin_name:
                            proxy["plugin"] = "v2ray-plugin"
                            proxy["plugin-opts"] = {
                                "mode": plugin_info.get("mode", [""])[0],
                                "host": plugin_info.get("host", [""])[0],
                                "path": plugin_info.get("path", [""])[0],
                                "tls": "tls" in plugin,
                            }
                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SS parse error: {e}") from e

            elif scheme == "ssr":
                try:
                    try:
                        decoded = Converter.decode_base64(body).decode()
                    except ValueError:
                        decoded = body
                    parts, _, params_str = decoded.partition("/?")
                    host, port, protocol, method, obfs, password_enc = parts.split(":", 5)
                    password = Converter.decode_base64(password_enc).decode('utf-8')
                    params = parse_qs(params_str)

                    remarks = params.get("remarks", [""])[0]
                    obfsparam = params.get("obfsparam", [""])[0]
                    protoparam = params.get("protoparam", [""])[0]

                    name = Converter.unique_name(names, remarks or f"{host}:{port}")

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

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"SSR parse error: {e}") from e

            elif scheme == "tuic":
                try:
                    parsed = urlparse(line)
                    query = parse_qs(parsed.query)

                    user = parsed.username or ""
                    password = parsed.password or ""
                    server = parsed.hostname
                    port = parsed.port or 443

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
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
                        proxy["congestion-controller"] = query["congestion_control"][0]
                    if "alpn" in query:
                        proxy["alpn"] = query["alpn"][0].split(",")
                    if "sni" in query:
                        proxy["sni"] = query["sni"][0]
                    if query.get("disable_sni", ["0"])[0] == "1":
                        proxy["disable-sni"] = True
                    if "udp_relay_mode" in query:
                        proxy["udp-relay-mode"] = query["udp_relay_mode"][0]

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"TUIC parse error: {e}") from e

            elif scheme == "anytls":
                try:
                    parsed = urlparse(line)
                    query = parse_qs(parsed.query)

                    username = parsed.username or ""
                    password = parsed.password or username
                    server = parsed.hostname
                    port = parsed.port
                    insecure = query.get("insecure", ["0"])[0] == "1"
                    sni = query.get("sni", [""])[0]
                    fingerprint = query.get("hpkp", [""])[0]

                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
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

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"AnyTLS parse error: {e}") from e

            elif scheme in ("hysteria2", "hy2"):
                try:
                    parsed = urlparse(line)
                    query = dict(parse_qsl(parsed.query))
                    password = parsed.username or ""
                    server = parsed.hostname
                    port = parsed.port or 443
                    name = Converter.unique_name(names, unquote(parsed.fragment or f"{server}:{port}"))
                    proxy = {
                        "name": name,
                        "type": "hysteria2",
                        "server": server,
                        "port": port,
                        "password": password,
                        "obfs": query.get("obfs", ""),
                        "obfs-password": query.get("obfs-password", ""),
                        "sni": query.get("sni", ""),
                        "skip-cert-verify": Converter.strtobool(query.get("insecure", "false")),
                        "down": query.get("down", ""),
                        "up": query.get("up", ""),
                    }
                    if "pinSHA256" in query:
                        proxy["fingerprint"] = query.get("pinSHA256", "")
                    if "alpn" in query:
                        proxy["alpn"] = query["alpn"].split(",")

                    proxies.append(proxy)
                except Exception as e:
                    if not skip_exception:
                        raise ValueError(f"Hysteria2 parse error: {e}") from e

        if not proxies:
            if not skip_exception:
                raise ValueError("convert v2ray subscribe error: format invalid")

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
                    # Always add path and host for ws if they exist, even if default, for round-trip consistency
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

            # Security/TLS settings
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

            # Encode password, obfsparam, protoparam, and remarks (name)
            # The password itself is not base64 encoded in the main part of the SSR link.
            # remarks, obfsparam, protoparam are not base64 encoded in the query string.
            # They are directly present.
            # The entire full_ssr_link_body is base64 urlsafe encoded at the end.

            # Construct the main part of the SSR link
            # host:port:protocol:method:obfs:password_enc
            password_enc = base64.b64encode(password.encode("utf-8")).decode("utf-8")
            ssr_main_part = f"{server}:{port}:{protocol}:{cipher}:{obfs}:{password_enc}"

            # Construct query parameters
            query_params = {}
            if proxy_config.get("obfs-param"):
                query_params["obfsparam"] = proxy_config["obfs-param"]
            if proxy_config.get("protocol-param"):
                query_params["protoparam"] = proxy_config["protocol-param"]
            # remarks (name) is always included
            query_params["remarks"] = name
            query_params["group"] = "MoviePilot" # Default group

            query_string = "&".join([f"{k}={quote(str(v))}" for k, v in query_params.items()])

            # Final SSR link: ssr://base64_encoded_main_part?query_string
            full_ssr_link_body = f"{ssr_main_part}/?{query_string}"
            encoded_full_ssr_link_body = base64.b64encode(full_ssr_link_body.encode("utf-8")).decode("utf-8")

            return f"ssr://{encoded_full_ssr_link_body}"

        # Add other proxy types as needed
        return None
