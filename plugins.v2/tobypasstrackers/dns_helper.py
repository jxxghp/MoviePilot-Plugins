import ipaddress
import socket
from urllib.parse import urlparse

from dns import asyncresolver, query
from dns.nameserver import Do53Nameserver, DoHNameserver, DoTNameserver, DoQNameserver
from dns.resolver import NoAnswer, NXDOMAIN

from app.log import logger


class DnsHelper:

    def __init__(self, dns_server: str | None = None):
        self._resolver = asyncresolver.Resolver()
        self._use_tcp: bool = False
        if dns_server:
            self.nameserver = dns_server

    @property
    def nameserver(self) ->str:
        nameserver = self._resolver.nameservers[0]
        return str(nameserver)

    @nameserver.setter
    def nameserver(self, value: str | None):
        if value is None:
            self._resolver = asyncresolver.Resolver()
            return
        self._parse_dns_server(value)

    @staticmethod
    def get_ip_from_hostname(hostname) -> str | None:
        try:
            # 获取IP地址
            ip = socket.gethostbyname(hostname)
            return ip
        except socket.gaierror:
            return None

    @staticmethod
    def is_ip_address(hostname):
        try:
            # 尝试解析为IP地址
            ipaddress.ip_address(hostname)
            return True
        except ValueError:
            return False

    def _parse_dns_server(self, dns_server: str):
        if "://" not in dns_server:
            dns_server = f"udp://{dns_server}"
        parsed = urlparse(dns_server)

        # check and resolve the hostname
        hostname = parsed.hostname
        if hostname is None:
            return
        if DnsHelper.is_ip_address(hostname):
            address = hostname
            hostname = None
        else:
            address = DnsHelper.get_ip_from_hostname(hostname)
            if address is None:
                return

        nameserver =  None
        match parsed.scheme:
            case "udp":
                nameserver = Do53Nameserver(address, parsed.port or 53)
            case "tcp":
                nameserver = Do53Nameserver(address, parsed.port or 53)
                self._use_tcp = True
            case "https":
                nameserver = DoHNameserver(url=dns_server)
            case "tls":
                nameserver = DoTNameserver(address=address, port=parsed.port or 853, hostname=hostname)
            case "h3":
                nameserver = DoHNameserver(url=dns_server.replace("h3://", "https://"),
                                           http_version=query.HTTPVersion.H3)
            case "quic":
                nameserver = DoQNameserver(address=address, port=parsed.port or 853, server_hostname=hostname)
            case _:
                nameserver = None
        if nameserver is None:
            self._resolver = asyncresolver.Resolver()
            return
        self._resolver.nameservers = [nameserver]

    async def resolve_name(self, domain: str, family: int = socket.AF_UNSPEC) -> list[str] | None:
        """
        异步解析域名

        :param domain: 要解析的域名
        :param family: The address family
            - socket.AF_UNSPEC: both IPv4 and IPv6 addresses
            - socket.AF_INET6: IPv6 addresses only
            - socket.AF_INET: IPv4 addresses only
        :return: IP 地址列表，或 None
        """
        try:
            answer = await self._resolver.resolve_name(domain, family=family, tcp=self._use_tcp)
            return [a for a in answer.addresses()]
        except (NoAnswer, NXDOMAIN):
            return []
        except Exception as e:
            logger.debug(f"DNS查询出错 ({domain}): {e} ")
            return None
