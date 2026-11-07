"""
Sportscult 站点索引器定义。
"""


def build_sportscult_indexer() -> dict:
    """
    构建 Sportscult 站点索引器配置。

    :return: 站点索引器定义
    """
    indexer: dict = {
        "id": "sportscult",
        "name": "Sportscult",
        "domain": "https://sportscult.org/",
        "encoding": "UTF-8",
        "public": False,
        "result_num": 30,
        "timeout": 30,
        "search": {
            "paths": [
                {
                    "path": "index.php?page=torrents&active=1&gold=0&search={keyword}&&order=3&by=2",
                    "method": "get"
                }
            ]
        },
        "browse": {
            "path": "?p={page}",
            "start": 1
        },
        "category": {
            "movie": [

            ],
            "tv": [
                {
                    "id": 43,
                    "cat": "La Liga",
                    "desc": "西甲"
                },
                {
                    "id": 60,
                    "cat": "Champions League",
                    "desc": "欧冠"
                },
            ]
        },
        "torrents": {
            "list": {
                "selector": "table.lista > tr:has(\"td.lista.specialPadding\")"
            },
            "fields": {
                "id": {
                    "selector": "a[href*=\"torrent-details&id=\"]",
                    "attribute": "href",
                    "filters": [
                        {
                            "name": "re_search",
                            "args": [
                                "\\d+",
                                0
                            ]
                        }
                    ]
                },
                "title_optional": {
                    "selector": "a[href*=\"torrent-details&id=\"]"
                },
                "title_default": {
                    "optional": True,
                    "selector": "a[title][href*=\"torrent-details&id=\"]",
                    "attribute": "title"
                },
                "title": {
                    "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
                },
                "details": {
                    "selector": "a[href*=\"torrent-details&id=\"]",
                    "attribute": "href"
                },
                "download": {
                    "selector": "a[href*=\"download.php?id=\"]",
                    "attribute": "href"
                },
                "imdbid": {
                    "optional": True,
                    "selector": "div.imdb_100 > a",
                    "attribute": "href",
                    "filters": [
                        {
                            "name": "re_search",
                            "args": [
                                "tt\\d+",
                                0
                            ]
                        }
                    ]
                },
                "date_elapsed": {
                    "selector": "td:nth-child(5)",
                    "optional": True
                },
                "date_added": {
                    "selector": "td:nth-child(5)",
                    "optional": True
                },
                "size": {
                    "selector": "td:nth-child(4)"
                },
                "seeders": {
                    "selector": "td:nth-child(6) > a"
                },
                "leechers": {
                    "selector": "td:nth-child(7) > a"
                },
                "grabs": {
                    "selector": "td:nth-child(8) > a"
                },
                "downloadvolumefactor": {
                    "case": {
                        "img[alt=\"silver\"]": 0.5,
                        "img[alt=\"gold\"]": 0,
                        "*": 1
                    }
                },
                "uploadvolumefactor": {
                    "case": {
                        "img[alt=\"silver\"]": 1,
                        "img[alt=\"gold\"]": 1,
                        "*": 1
                    }
                },
                "description": {
                    "optional": True,
                    "selector": "a[href*=\"torrent-details&id=\"]",
                    "contents": -1
                },
                "labels": {
                    "optional": True,
                    "selector": "td:nth-child(8) > a",
                    "attribute": "alt"
                },
                "category": {
                    "optional": True,
                    "selector": "td:nth-child(8) > a",
                    "attribute": "alt"
                }
            }
        }
    }

    return indexer
