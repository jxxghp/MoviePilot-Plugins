import re
from typing import Optional, List, Callable

import dns.asyncresolver
import dns.resolver

from app.log import logger


class DnsHelper:
    def __init__(self, dns_server: str):
        self.method_name = "Local"
        self.doh_url = "https://dns.alidns.com/dns-query"
        self.__resolver = dns.asyncresolver.Resolver()
        self.__dns_query_method = self.__query_method(dns_server)

    def __query_method(self, dns_input: str) -> Callable:
        if not dns_input:
            return self.query_dns_local
        if dns_input.startswith('https://'):
            self.doh_url = dns_input
            self.method_name = dns_input
            return self.query_dns_doh
        udp_match = re.match(r"^(?:udp://)?(\[?.+?]?)(?::(\d+))?$", dns_input)
        if udp_match:
            try:
                self.__resolver.nameservers = [udp_match.group(1).strip('[]')]
                if udp_match.group(2):
                    self.__resolver.port = int(udp_match.group(2))
                self.method_name = f"udp://{self.__resolver.nameservers[0]}:{self.__resolver.port}"
            except Exception as e:
                logger.warn(f'{e}, using default resolver')
                return self.query_dns_local
            return self.query_dns_udp
        logger.warn(f'Unknown method {dns_input}, using default resolver')
        return self.query_dns_local

    async def query_dns(self, domain: str, dns_type: str = "A") -> Optional[List[str]]:
        answers = await self.__dns_query_method(domain, dns_type)
        return answers

    async def query_dns_local(self, domain: str, dns_type: str = "A") -> Optional[List[str]]:
        try:
            answer = await self.__resolver.resolve(domain, dns_type)
            return [record.address for record in answer if hasattr(record, "address")]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return []
        except Exception as e:
            # logger.error(f"本地DNS查询错误: {e} {domain}")
            return None

    async def query_dns_doh(self, domain: str, dns_type: str = 'A') -> Optional[List[str]]:
        """
        使用 DNS-over-HTTPS (DoH) 异步解析域名。

        :param domain: 要解析的域名
        :param dns_type: DNS 记录类型，例如 'A', 'AAAA'
        :return: IP 地址列表，或 None
        """

        try:
            query = dns.message.make_query(domain, dns_type)
            response = await dns.asyncquery.https(query, self.doh_url)
            return [
                item.address for rrset in response.answer for item in rrset.items
                if hasattr(item, "address")
            ]
        except Exception as e:
            return None

    async def query_dns_udp(self, domain: str, dns_type: str = 'A') -> Optional[List[str]]:
        """
        使用 UDP 异步方式解析域名

        :param domain: 域名
        :param dns_type: 记录类型，如 A、AAAA
        :return: IP地址列表 或 None
        """

        try:
            answer = await self.__resolver.resolve(domain, dns_type)
            return [record.address for record in answer]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return []
        except Exception:
            return None
