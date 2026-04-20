# 如何扩展内建索引器的索引站点？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

- 通过调用 `SitesHelper().add_indexer(domain: str, indexer: dict)` 方法，新增或修改内建索引器的支持范围，其中`indexer`为站点配置Json，格式示例如下：

  示例一：
  ```json
  {
    "id": "nyaa",
    "name": "Nyaa",
    "domain": "https://nyaa.si/",
    "encoding": "UTF-8",
    "public": true,
    "proxy": true,
    "result_num": 100,
    "timeout": 30,
    "search": {
      "paths": [
        {
          "path": "?f=0&c=0_0&q={keyword}",
          "method": "get"
        }
      ]
    },
    "browse": {
      "path": "?p={page}",
      "start": 1
    },
    "torrents": {
      "list": {
        "selector": "table.torrent-list > tbody > tr"
      },
      "fields": {
        "id": {
          "selector": "a[href*=\"/view/\"]",
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
        "title": {
          "selector": "td:nth-child(2) > a"
        },
        "details": {
          "selector": "td:nth-child(2) > a",
          "attribute": "href"
        },
        "download": {
          "selector": "td:nth-child(3) > a[href*=\"/download/\"]",
          "attribute": "href"
        },
        "date_added": {
          "selector": "td:nth-child(5)"
        },
        "size": {
          "selector": "td:nth-child(4)"
        },
        "seeders": {
          "selector": "td:nth-child(6)"
        },
        "leechers": {
          "selector": "td:nth-child(7)"
        },
        "grabs": {
          "selector": "td:nth-child(8)"
        },
        "downloadvolumefactor": {
          "case": {
            "*": 0
          }
        },
        "uploadvolumefactor": {
          "case": {
            "*": 1
          }
        }
      }
    }
  }
  ```

  示例二：
  ```json
  {
      "id": "xxx",
      "name": "站点名称",
      "domain": "https://www.xxx.com/",
      "ext_domains": [
        "https://www.xxx1.com/",
        "https://www.xxx2.com/"
      ],
      "encoding": "UTF-8",
      "public": false,
      "search": {
        "paths": [
          {
            "path": "torrents.php",
            "method": "get"
          }
        ],
        "params": {
          "search": "{keyword}",
          "search_area": 4
        },
        "batch": {
          "delimiter": " ",
          "space_replace": "_"
        }
      },
      "category": {
        "movie": [
          {
            "id": 401,
            "cat": "Movies",
            "desc": "Movies电影"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          }
        ],
        "tv": [
          {
            "id": 402,
            "cat": "TV",
            "desc": "TV Series电视剧"
          },
          {
            "id": 403,
            "cat": "TV",
            "desc": "TV Shows综艺"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          }
        ]
      },
      "torrents": {
        "list": {
          "selector": "table.torrents > tr:has(\"table.torrentname\")"
        },
        "fields": {
          "id": {
            "selector": "a[href*=\"details.php?id=\"]",
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
          "title_default": {
            "selector": "a[href*=\"details.php?id=\"]"
          },
          "title_optional": {
            "optional": true,
            "selector": "a[title][href*=\"details.php?id=\"]",
            "attribute": "title"
          },
          "title": {
            "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
          },
          "details": {
            "selector": "a[href*=\"details.php?id=\"]",
            "attribute": "href"
          },
          "download": {
            "selector": "a[href*=\"download.php?id=\"]",
            "attribute": "href"
          },
          "imdbid": {
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
            "selector": "td:nth-child(4) > span",
            "optional": true
          },
          "date_added": {
            "selector": "td:nth-child(4) > span",
            "attribute": "title",
            "optional": true
          },
          "size": {
            "selector": "td:nth-child(5)"
          },
          "seeders": {
            "selector": "td:nth-child(6)"
          },
          "leechers": {
            "selector": "td:nth-child(7)"
          },
          "grabs": {
            "selector": "td:nth-child(8)"
          },
          "downloadvolumefactor": {
            "case": {
              "img.pro_free": 0,
              "img.pro_free2up": 0,
              "img.pro_50pctdown": 0.5,
              "img.pro_50pctdown2up": 0.5,
              "img.pro_30pctdown": 0.3,
              "*": 1
            }
          },
          "uploadvolumefactor": {
            "case": {
              "img.pro_50pctdown2up": 2,
              "img.pro_free2up": 2,
              "img.pro_2up": 2,
              "*": 1
            }
          },
          "description": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span[style]",
            "contents": -1
          },
          "labels": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span.tags"
          }
        }
      }
    }
  ```
- 需要注意的是，如果你没有完成用户认证，通过插件配置进去的索引站点也是无法正常使用的。
- **请不要添加对黄赌毒站点的支持，否则随时封闭接口。**
