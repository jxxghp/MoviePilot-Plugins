from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.plugins import _PluginBase


class ConfigCenter(_PluginBase):
    # 插件名称
    plugin_name = "配置中心"
    # 插件描述
    plugin_desc = "快速调整部分系统设定。"
    # 插件图标
    plugin_icon = "setting.png"
    # 主题色
    plugin_color = "#FC6220"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "configcenter_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            settings.GITHUB_TOKEN = config.get("GITHUB_TOKEN", settings.GITHUB_TOKEN)
            settings.API_TOKEN = config.get("API_TOKEN", settings.API_TOKEN)
            settings.TMDB_API_DOMAIN = config.get("TMDB_API_DOMAIN", settings.TMDB_API_DOMAIN)
            settings.TMDB_IMAGE_DOMAIN = config.get("TMDB_IMAGE_DOMAIN", settings.TMDB_IMAGE_DOMAIN)
            settings.WALLPAPER = config.get("WALLPAPER", settings.WALLPAPER)
            settings.RECOGNIZE_SOURCE = config.get("RECOGNIZE_SOURCE", "")
            settings.SCRAP_METADATA = config.get("SCRAP_METADATA", settings.SCRAP_METADATA)
            settings.SCRAP_FOLLOW_TMDB = config.get("SCRAP_FOLLOW_TMDB", settings.SCRAP_FOLLOW_TMDB)
            settings.LIBRARY_PATH = config.get("LIBRARY_PATH", settings.LIBRARY_PATH)
            settings.LIBRARY_MOVIE_NAME = config.get("LIBRARY_MOVIE_NAME", settings.LIBRARY_MOVIE_NAME)
            settings.LIBRARY_TV_NAME = config.get("LIBRARY_TV_NAME", settings.LIBRARY_TV_NAME)
            settings.LIBRARY_ANIME_NAME = config.get("LIBRARY_ANIME_NAME", settings.LIBRARY_ANIME_NAME)
            settings.LIBRARY_CATEGORY = config.get("LIBRARY_CATEGORY", settings.LIBRARY_CATEGORY)
            settings.TRANSFER_TYPE = config.get("TRANSFER_TYPE", settings.TRANSFER_TYPE)
            settings.OVERWRITE_MODE = config.get("OVERWRITE_MODE", settings.OVERWRITE_MODE)
            settings.COOKIECLOUD_HOST = config.get("COOKIECLOUD_HOST", settings.COOKIECLOUD_HOST)
            settings.COOKIECLOUD_KEY = config.get("COOKIECLOUD_KEY", settings.COOKIECLOUD_KEY)
            settings.COOKIECLOUD_PASSWORD = config.get("COOKIECLOUD_PASSWORD", settings.COOKIECLOUD_PASSWORD)
            settings.COOKIECLOUD_INTERVAL = config.get("COOKIECLOUD_INTERVAL", settings.COOKIECLOUD_INTERVAL)
            settings.USER_AGENT = config.get("USER_AGENT", settings.USER_AGENT)
            settings.SUBSCRIBE_MODE = config.get("SUBSCRIBE_MODE", settings.SUBSCRIBE_MODE)
            settings.SUBSCRIBE_RSS_INTERVAL = config.get("SUBSCRIBE_RSS_INTERVAL", settings.SUBSCRIBE_RSS_INTERVAL)
            settings.SUBSCRIBE_SEARCH = config.get("SUBSCRIBE_SEARCH", settings.SUBSCRIBE_SEARCH)
            settings.AUTO_DOWNLOAD_USER = config.get("AUTO_DOWNLOAD_USER", settings.AUTO_DOWNLOAD_USER)
            settings.OCR_HOST = config.get("OCR_HOST", settings.OCR_HOST)
            messagers = config.get("MESSAGER") or []
            if messagers:
                settings.MESSAGER = ",".join(messagers)
            settings.DOWNLOAD_PATH = config.get("DOWNLOAD_PATH", settings.DOWNLOAD_PATH)
            settings.DOWNLOAD_MOVIE_PATH = config.get("DOWNLOAD_MOVIE_PATH", settings.DOWNLOAD_MOVIE_PATH)
            settings.DOWNLOAD_TV_PATH = config.get("DOWNLOAD_TV_PATH", settings.DOWNLOAD_TV_PATH)
            settings.DOWNLOAD_ANIME_PATH = config.get("DOWNLOAD_ANIME_PATH", settings.DOWNLOAD_ANIME_PATH)
            settings.DOWNLOAD_CATEGORY = config.get("DOWNLOAD_CATEGORY", settings.DOWNLOAD_CATEGORY)
            settings.DOWNLOAD_SUBTITLE = config.get("DOWNLOAD_SUBTITLE", settings.DOWNLOAD_SUBTITLE)
            settings.DOWNLOADER = config.get("DOWNLOADER", settings.DOWNLOADER)
            settings.DOWNLOADER_MONITOR = config.get("DOWNLOADER_MONITOR", settings.DOWNLOADER_MONITOR)
            settings.TORRENT_TAG = config.get("TORRENT_TAG", settings.TORRENT_TAG)
            media_servers = config.get("MEDIASERVER") or []
            if media_servers:
                settings.MEDIASERVER = ",".join(media_servers)
            settings.MEDIASERVER_SYNC_INTERVAL = config.get("MEDIASERVER_SYNC_INTERVAL",
                                                            settings.MEDIASERVER_SYNC_INTERVAL)
            settings.MEDIASERVER_SYNC_BLACKLIST = config.get("MEDIASERVER_SYNC_BLACKLIST",
                                                             settings.MEDIASERVER_SYNC_BLACKLIST)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        request_options = ["POST", "GET"]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "GITHUB_TOKEN",
                                            "label": "Github Token"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "API_TOKEN",
                                            "label": "API密钥"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "TMDB_API_DOMAIN",
                                            "label": "TMDB API地址"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "TMDB_IMAGE_DOMAIN",
                                            "label": "TheMovieDb图片代理"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "WALLPAPER",
                                            "label": "登录首页电影海报",
                                            "items": [
                                                {"title": "TheMovieDb电影海报", "value": "tmdb"},
                                                {"title": "Bing每日壁纸", "value": "bing"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "RECOGNIZE_SOURCE",
                                            "label": "媒体信息识别来源",
                                            "items": [
                                                {"title": "themoviedb", "value": "TheMovieDb"},
                                                {"title": "douban", "value": "豆瓣"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "SCRAP_METADATA",
                                            "label": "刮削入库的媒体文件"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "SCRAP_SOURCE",
                                            "label": "刮削元数据及图片使用的数据源",
                                            "items": [
                                                {"title": "themoviedb", "value": "TheMovieDb"},
                                                {"title": "douban", "value": "豆瓣"},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "SCRAP_FOLLOW_TMDB",
                                            "label": "新增入库跟随TMDB信息变化"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "LIBRARY_PATH",
                                            "label": "媒体库目录"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "LIBRARY_MOVIE_NAME",
                                            "label": "电影目录名称"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "LIBRARY_TV_NAME",
                                            "label": "电视剧目录名称"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "LIBRARY_ANIME_NAME",
                                            "label": "动漫目录名称"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "LIBRARY_CATEGORY",
                                            "label": "开启媒体库二级分类"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "TRANSFER_TYPE",
                                            "label": "整理转移方式",
                                            "items": [
                                                {"title": "硬链接", "value": "link"},
                                                {"title": "复制", "value": "copy"},
                                                {"title": "移动", "value": "move"},
                                                {"title": "软链接", "value": "softlink"},
                                                {"title": "rclone复制", "value": "rclone_copy"},
                                                {"title": "rclone移动", "value": "rclone_move"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "OVERWRITE_MODE",
                                            "label": "转移覆盖模式",
                                            "items": [
                                                {"title": "从不覆盖", "value": "never"},
                                                {"title": "按大小覆盖", "value": "size"},
                                                {"title": "总是覆盖", "value": "always"},
                                                {"title": "仅保留最新版本", "value": "latest"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "COOKIECLOUD_HOST",
                                            "label": "CookieCloud服务器地址"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "COOKIECLOUD_KEY",
                                            "label": "CookieCloud用户KEY"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "COOKIECLOUD_PASSWORD",
                                            "label": "CookieCloud端对端加密密码"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "COOKIECLOUD_INTERVAL",
                                            "label": "CookieCloud同步间隔（分钟）"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "USER_AGENT",
                                            "label": "CookieCloud浏览器UA"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "SUBSCRIBE_MODE",
                                            "label": "订阅模式",
                                            "items": [
                                                {"title": "站点RSS", "value": "rss"},
                                                {"title": "自动", "value": "spider"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "SUBSCRIBE_RSS_INTERVAL",
                                            "label": "RSS订阅刷新间隔（分钟）"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "SUBSCRIBE_SEARCH",
                                            "label": "开启订阅搜索"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "AUTO_DOWNLOAD_USER",
                                            "label": "自动择优下载用户列表"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "OCR_HOST",
                                            "label": "验证码识别服务器"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "MESSAGER",
                                            "label": "消息通知渠道",
                                            "items": [
                                                {"title": "Telegram", "value": "telegram"},
                                                {"title": "微信", "value": "wechat"},
                                                {"title": "Slack", "value": "slack"},
                                                {"title": "SynologyChat", "value": "synologychat"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "DOWNLOAD_PATH",
                                            "label": "下载保存目录"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "DOWNLOAD_MOVIE_PATH",
                                            "label": "电影下载保存目录"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "DOWNLOAD_TV_PATH",
                                            "label": "电视剧下载保存目录"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "DOWNLOAD_ANIME_PATH",
                                            "label": "动漫下载保存目录"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "DOWNLOAD_CATEGORY",
                                            "label": "开启下载二级分类"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "DOWNLOAD_SUBTITLE",
                                            "label": "自动下载站点字幕"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "DOWNLOADER",
                                            "label": "下载器",
                                            "items": [
                                                {"title": "QBittorrent", "value": "qbittorrent"},
                                                {"title": "Transmission", "value": "transmission"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "DOWNLOADER_MONITOR",
                                            "label": "开启下载器监控"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "TORRENT_TAG",
                                            "label": "下载器种子标签"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "MEDIASERVER",
                                            "label": "媒体服务器",
                                            'chips': True,
                                            'multiple': True,
                                            "items": [
                                                {"title": "Emby", "value": "emby"},
                                                {"title": "Jellyfin", "value": "jellyfin"},
                                                {"title": "Plex", "value": "plex"}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "MEDIASERVER_SYNC_INTERVAL",
                                            "label": "媒体服务器同步间隔（小时）"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 6
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "MEDIASERVER_SYNC_BLACKLIST",
                                            "label": "媒体服务器同步黑名单"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "GITHUB_TOKEN": settings.GITHUB_TOKEN,
            "API_TOKEN": settings.API_TOKEN,
            "TMDB_API_DOMAIN": settings.TMDB_API_DOMAIN,
            "TMDB_IMAGE_DOMAIN": settings.TMDB_IMAGE_DOMAIN,
            "WALLPAPER": settings.WALLPAPER,
            "RECOGNIZE_SOURCE": settings.RECOGNIZE_SOURCE,
            "SCRAP_METADATA": settings.SCRAP_METADATA,
            "SCRAP_SOURCE": settings.SCRAP_SOURCE,
            "SCRAP_FOLLOW_TMDB": settings.SCRAP_FOLLOW_TMDB,
            "LIBRARY_PATH": settings.LIBRARY_PATH,
            "LIBRARY_MOVIE_NAME": settings.LIBRARY_MOVIE_NAME,
            "LIBRARY_TV_NAME": settings.LIBRARY_TV_NAME,
            "LIBRARY_ANIME_NAME": settings.LIBRARY_ANIME_NAME,
            "LIBRARY_CATEGORY": settings.LIBRARY_CATEGORY,
            "TRANSFER_TYPE": settings.TRANSFER_TYPE,
            "OVERWRITE_MODE": settings.OVERWRITE_MODE,
            "COOKIECLOUD_HOST": settings.COOKIECLOUD_HOST,
            "COOKIECLOUD_KEY": settings.COOKIECLOUD_KEY,
            "COOKIECLOUD_PASSWORD": settings.COOKIECLOUD_PASSWORD,
            "COOKIECLOUD_INTERVAL": settings.COOKIECLOUD_INTERVAL,
            "USER_AGENT": settings.USER_AGENT,
            "SUBSCRIBE_MODE": settings.SUBSCRIBE_MODE,
            "SUBSCRIBE_RSS_INTERVAL": settings.SUBSCRIBE_RSS_INTERVAL,
            "SUBSCRIBE_SEARCH": settings.SUBSCRIBE_SEARCH,
            "AUTO_DOWNLOAD_USER": settings.AUTO_DOWNLOAD_USER,
            "OCR_HOST": settings.OCR_HOST,
            "MESSAGER": settings.MESSAGER.split(","),
            "DOWNLOAD_PATH": settings.DOWNLOAD_PATH,
            "DOWNLOAD_MOVIE_PATH": settings.DOWNLOAD_MOVIE_PATH,
            "DOWNLOAD_TV_PATH": settings.DOWNLOAD_TV_PATH,
            "DOWNLOAD_ANIME_PATH": settings.DOWNLOAD_ANIME_PATH,
            "DOWNLOAD_CATEGORY": settings.DOWNLOAD_CATEGORY,
            "DOWNLOAD_SUBTITLE": settings.DOWNLOAD_SUBTITLE,
            "DOWNLOADER": settings.DOWNLOADER,
            "DOWNLOADER_MONITOR": settings.DOWNLOADER_MONITOR,
            "TORRENT_TAG": settings.TORRENT_TAG,
            "MEDIASERVER": settings.MEDIASERVER.split(","),
            "MEDIASERVER_SYNC_INTERVAL": settings.MEDIASERVER_SYNC_INTERVAL,
            "MEDIASERVER_SYNC_BLACKLIST": settings.MEDIASERVER_SYNC_BLACKLIST
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
