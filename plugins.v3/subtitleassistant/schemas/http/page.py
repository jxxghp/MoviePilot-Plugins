"""HTTP 分页契约。"""

from enum import IntEnum

__all__ = ["PageSize"]


class PageSize(IntEnum):
    """分页查询允许的每页记录数。"""

    ITEMS_25 = 25
    ITEMS_50 = 50
    ITEMS_100 = 100
