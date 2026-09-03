import math
import time
from typing import Any, Optional, List, Dict
from urllib.parse import urlparse


class UtilsProvider:
    @staticmethod
    def filter_empty(original_dict: dict, empty: Optional[List[Any]] = None) -> dict:
        """过滤字典中的空值"""
        return {k: v for k, v in original_dict.items() if v not in (empty or [None, '', [], {}])}

    @staticmethod
    def get_url_domain(url: str) -> str:
        """从 url 中提取域名"""
        if not url:
            return ""
        parsed = urlparse(url)
        if not parsed.netloc:
            parsed = urlparse("https://" + url)
        return parsed.netloc

    @staticmethod
    def find_cycles(graph: Dict[Any, Any]) -> List[List[Any]]:
        """DFS 检测环，并记录路径"""
        visited = set()
        stack = []
        cycles = []

        def dfs(node):
            if node in stack:
                cycle_index = stack.index(node)
                cycles.append(stack[cycle_index:] + [node])
                return
            if node in visited:
                return

            visited.add(node)
            stack.append(node)
            for nei in graph.get(node, []):
                dfs(nei)
            stack.pop()

        for n in graph:
            if n not in visited:
                dfs(n)
        return cycles

    @staticmethod
    def format_bytes(value_bytes):
        if value_bytes == 0:
            return '0 B'
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB', 'TB']
        i = math.floor(math.log(value_bytes) / math.log(k)) if value_bytes > 0 else 0
        return f"{value_bytes / math.pow(k, i):.2f} {sizes[i]}"

    @staticmethod
    def format_expire_time(timestamp):
        seconds_left = timestamp - int(time.time())
        days = seconds_left // 86400
        return f"{days}天后过期" if days > 0 else "已过期"

    @staticmethod
    def update_with_checking(src_dict: Dict[str, Any], dst_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        跳过存在的键合并字典
        """
        for key, value in src_dict.items():
            if key in dst_dict:
                continue
            dst_dict[key] = value
        return dst_dict
