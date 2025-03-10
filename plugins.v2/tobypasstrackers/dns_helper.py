import socket
import re
from typing import Optional

import dns.resolver

from app.log import logger
from app.utils.http import RequestUtils


class DnsHelper:

    @staticmethod
    def query_dns_udp(domain: str, dns_server: str, port: int =53, dns_type: str ='A') -> list[str]:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]
        resolver.port = port

        try:
            ip_answer = resolver.resolve(domain, dns_type)
            ip_addresses = [record.address for record in ip_answer]
        except dns.resolver.NoAnswer:
            ip_addresses = []
        except:
            return None
        return ip_addresses

    @staticmethod
    def query_doh(domain: str, doh_url: str, dns_type: str = 'A') -> Optional[list]:
        params = {
            'name': domain,
            'type': dns_type,
        }
        headers = {
            'Accept': 'application/dns-json',
        }
        response = RequestUtils().get_res(url=doh_url, headers=headers, params=params)
        if not response.status_code == 200:
            return None
        data = response.json()
        return [answer['data'] for answer in data.get('Answer', []) if
                answer.get('type') == 28 or answer.get('type') == 1]

    @staticmethod
    def parse_dns_input(dns_input: str):
        if not dns_input:
            return 'local', dns_input
        # Check if it's a DoH URL (starts with https://)
        if dns_input.startswith('https://'):
            return 'doh', dns_input

        # Check if it's a UDP DNS with hostname (e.g., udp://unfiltered.adguard-dns.com)
        if dns_input.startswith('udp://'):
            hostname = dns_input[len('udp://'):]
            return 'udp', hostname, 53

        # Check if it's an IP address with port (e.g., 94.140.14.140:53 or [2a10:50c0::1:ff]:53)
        port_match = re.match(r'^(\[?.+?\]?):(\d+)$', dns_input)
        if port_match:
            dns_server = port_match.group(1).strip('[]')
            port = int(port_match.group(2))
            return 'udp', dns_server, port

        # Default to regular DNS over UDP with default port 53
        return 'udp', dns_input, 53

    @staticmethod
    def query_dns_local(domain_name: str, dns_type: str = 'A') -> Optional[list]:
        try:
            # Get address info for both IPv4 and IPv6
            addr_info = socket.getaddrinfo(domain_name, None, socket.AF_UNSPEC, socket.SOCK_STREAM)

            ipv4_addresses = []
            ipv6_addresses = []

            # Iterate over the address info
            for info in addr_info:
                ip_address = info[4][0]

                # Check if the IP address is IPv4 or IPv6
                if '.' in ip_address:
                    ipv4_addresses.append(ip_address)
                elif ':' in ip_address:
                    ipv6_addresses.append(ip_address)
            if dns_type == 'A':
                return ipv4_addresses
            elif dns_type == 'AAAA':
                return ipv6_addresses

        except socket.gaierror as e:
            logger.error(f"本地DNS查询错误: {e} {domain_name}")

    @staticmethod
    def query_domain(domain: str, dns_input: str, dns_type='A') -> Optional[list]:
        method, *args = DnsHelper.parse_dns_input(dns_input)
        if method == 'local':
            return DnsHelper.query_dns_local(domain, dns_type)
        elif method == 'udp':
            dns_server, port = args
            return DnsHelper.query_dns_udp(domain, dns_server, port, dns_type)
        elif method == 'doh':
            doh_url = args[0]
            return DnsHelper.query_doh(domain, doh_url, dns_type)
        else:
            logger.error(f'Unknown method {method}')