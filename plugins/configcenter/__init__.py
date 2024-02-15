import copy
from typing import Any, List, Dict, Tuple

from dotenv import set_key

from app.core.config import settings
from app.core.module import ModuleManager
from app.log import logger
from app.plugins import _PluginBase


class ConfigCenter(_PluginBase):
    # 插件名称
    plugin_name = "配置中心"
    # 插件描述
    plugin_desc = "快速调整部分系统设定。"
    # 插件图标
    plugin_icon = "setting.png"
    # 插件版本
    plugin_version = "2.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "configcenter_"
    # 加载顺序
    plugin_order = 0
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _params = ""
    _writeenv = False
    settings_attributes = [
        "GITHUB_TOKEN", "API_TOKEN", "TMDB_API_DOMAIN", "TMDB_IMAGE_DOMAIN", "WALLPAPER",
        "RECOGNIZE_SOURCE", "SCRAP_FOLLOW_TMDB", "AUTO_DOWNLOAD_USER",
        "OCR_HOST", "DOWNLOAD_SUBTITLE", "PLUGIN_MARKET", "MOVIE_RENAME_FORMAT",
        "TV_RENAME_FORMAT", "FANART_ENABLE"
    ]

    def init_plugin(self, config: dict = None):
        if not config:
            return

        self._enabled = config.get("enabled")
        self._writeenv = config.get("writeenv")
        if not self._enabled:
            return
        logger.info(f"正在应用配置中心配置：{config}")
        for attribute in self.settings_attributes:
            setattr(settings, attribute, config.get(attribute) or getattr(settings, attribute))
        # 自定义配置，以换行分隔
        self._params = config.get("params") or ""
        for key, value in self.__parse_params(self._params):
            if hasattr(settings, key):
                setattr(settings, key, str(value))

        # 重新加载模块
        ModuleManager().stop()
        ModuleManager().load_modules()

        # 如果写入app.env文件，则关闭插件开关
        if self._writeenv:
            # 写入env文件
            self.update_env(config)
            # 自动关闭插件
            self._enabled = False
            logger.info("配置中心设置已写入app.env文件，插件关闭...")
            # 保存配置
            config.update({"enabled": False})
            self.update_config(config)

    def update_env(self, config: dict):
        """
        更新设置到app.env
        """
        if not config:
            return

        # 避免修改原值
        conf = copy.deepcopy(config)

        # 自定义配置，以换行分隔
        config_params = self.__parse_params(conf.get("params"))
        conf.update(config_params)
        # 去掉无效参数
        try:
            conf.pop("enabled")
            conf.pop("writeenv")
            conf.pop("params")
        except KeyError:
            pass
        # 读写app.env
        env_path = settings.CONFIG_PATH / "app.env"
        for key, value in conf.items():
            if not key:
                continue
            if value is None or str(value) == "None":
                value = ''
            else:
                value = str(value)
            set_key(env_path, key, value)
        logger.info("app.env文件写入完成")
        self.systemmessage.put("配置中心设置已写入app.env文件，插件关闭")

    @staticmethod
    def __parse_params(param_str: str) -> dict:
        """
        解析自定义配置
        """
        if not param_str:
            return {}
        result = {}
        params = param_str.split("\n")
        for param in params:
            if not param:
                continue
            if str(param).strip().startswith("#"):
                continue
            parts = param.split("=", 1)
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            value = parts[1].strip()
            if not key:
                continue
            if not value:
                continue
            result[key] = value
        return result

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
        default_settings = {
            "enabled": False,
            "params": "",
        }
        for attribute in self.settings_attributes:
            default_settings[attribute] = getattr(settings, attribute)
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
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "writeenv",
                                            "label": "写入app.env文件"
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
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
                                            "label": "TheMovieDb图片服务器"
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
                                                {"title": "TheMovieDb", "value": "themoviedb"},
                                                {"title": "豆瓣", "value": "douban"}
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
                                            "model": "SCRAP_SOURCE",
                                            "label": "刮削元数据及图片使用的数据源",
                                            "items": [
                                                {"title": "TheMovieDb", "value": "themoviedb"},
                                                {"title": "豆瓣", "value": "douban"},
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
                                            "model": "WALLPAPER",
                                            "label": "登录首页电影海报",
                                            "items": [
                                                {"title": "TheMovieDb电影海报", "value": "tmdb"},
                                                {"title": "Bing每日壁纸", "value": "bing"}
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
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
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "FANART_ENABLE",
                                            "label": "使用Fanart图片数据源"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
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
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
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
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "MOVIE_RENAME_FORMAT",
                                            "label": "电影重命名格式"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "TV_RENAME_FORMAT",
                                            "label": "电视剧重命名格式"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "PLUGIN_MARKET",
                                            "label": "插件市场",
                                            "placeholder": "多个地址使用,分隔"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "params",
                                            "label": "自定义配置",
                                            "placeholder": "每行一个配置项，格式：配置项=值"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：开启写入app.env后将直接修改配置文件，否则只是运行时修改生效对应配置（插件关闭且重启后配置失效）；有些自定义配置需要重启才能生效。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], default_settings

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
