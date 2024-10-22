from typing import Any, List, Dict, Tuple

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
    plugin_version = "3.2"
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

    def init_plugin(self, config: dict = None):
        if not config:
            return

        # 清理插件配置，从而实现默认使用.env中的数据源
        self._params = config.pop("params", "")
        if "undefined" in config:
            del config["undefined"]
        if "_tabs" in config:
            del config["_tabs"]
        self.update_config(config={})

        # 将自定义配置存储到 __ConfigCenter__
        self.update_config(plugin_id="__ConfigCenter__", config={"params": self._params})

        logger.info(f"正在应用配置中心配置：{config}")

        # 追加自定义配置中的内容
        params = self.__parse_params(self._params) or {}
        config.update(**params)

        # 批量更新配置，并获取更新结果
        update_results = settings.update_settings(config)

        # 遍历更新结果
        for key, (success, message) in update_results.items():
            if not success:
                self.__log_and_notify_error(f"配置项 '{key}' 更新失败：{message}")
            elif message:
                self.__log_and_notify_error(f"配置项 '{key}' 更新时出现警告：{message}")

        # 重新加载模块
        ModuleManager().reload()

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message, title=self.plugin_name)

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
        return True

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        default_settings = {}
        settings_model = self.get_settings_model()
        keys = self.extract_keys(settings_model)
        for key in keys:
            if hasattr(settings, key):
                default_settings[key] = getattr(settings, key)

        config = self.get_config(plugin_id="__ConfigCenter__") or {}
        params_str = config.get("params") or ""
        params = self.__parse_params(params_str) or {}
        updated_params = {key: getattr(settings, key) for key in params if hasattr(settings, key)}
        params_str = "\n".join(f"{key}={value}" for key, value in updated_params.items())
        default_settings["params"] = params_str

        return [
            {
                "component": "VForm",
                "content": settings_model
            }
        ], default_settings

    def extract_keys(self, components: List[dict]) -> List[str]:
        """
        递归提取所有组件中的model键
        """
        models = []
        for component in components:
            # 检查当前组件的props中是否有model
            props = component.get("props", {})
            model = props.get("model")
            if model:
                models.append(model)

            # 如果当前组件有嵌套的content，递归提取
            nested_content = component.get("content", [])
            if isinstance(nested_content, list):
                models.extend(self.extract_keys(nested_content))
            elif isinstance(nested_content, dict):
                models.extend(self.extract_keys([nested_content]))

        return models

    @staticmethod
    def get_settings_model() -> List[dict]:
        """
        获取配置项模型
        """
        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "warning",
                                    "variant": "tonal",
                                    "text": "注意：部分配置项的更改可能需要重启服务才能生效，为确保配置一致性，已在环境变量中的相关配置项，请手动更新"
                                }
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VTabs",
                "props": {
                    "model": "_tabs",
                    "height": 72,
                    "fixed-tabs": True,
                    "style": {
                        "margin-top": "8px",
                        "margin-bottom": "10px",
                    }
                },
                "content": [
                    {
                        "component": "VTab",
                        "props": {
                            "value": "basic_tab",
                            "style": {
                                "padding-top": "10px",
                                "padding-bottom": "10px",
                                "font-size": "16px"
                            },
                        },
                        "text": "基础设置"
                    },
                    {
                        "component": "VTab",
                        "props": {
                            "value": "network_tab",
                            "style": {
                                "padding-top": "10px",
                                "padding-bottom": "10px",
                                "font-size": "16px"
                            },
                        },
                        "text": "网络设置"
                    },
                    {
                        "component": "VTab",
                        "props": {
                            "value": "media_and_download_tab",
                            "style": {
                                "padding-top": "10px",
                                "padding-bottom": "10px",
                                "font-size": "16px"
                            },
                        },
                        "text": "媒体与下载"
                    },
                    {
                        "component": "VTab",
                        "props": {
                            "value": "search_and_transfer_tab",
                            "style": {
                                "padding-top": "10px",
                                "padding-bottom": "10px",
                                "font-size": "16px"
                            },
                        },
                        "text": "搜索与整理"
                    },
                    {
                        "component": "VTab",
                        "props": {
                            "value": "params_tab",
                            "style": {
                                "padding-top": "10px",
                                "padding-bottom": "10px",
                                "font-size": "16px"
                            },
                        },
                        "text": "自定义配置"
                    },
                ]
            },
            {
                "component": "VWindow",
                "props": {
                    "model": "_tabs",
                },
                "content": [
                    # 备份分类块
                    # {
                    #     "component": "VWindowItem",
                    #     "props": {
                    #         "value": "client_setting",
                    #         "style": {
                    #             "padding-top": "20px",
                    #             "padding-bottom": "20px"
                    #         },
                    #     },
                    #     "content": [
                    #         {
                    #             "component": "VRow",
                    #             "props": {
                    #                 "align": "center"
                    #             },
                    #             "content": []
                    #         }
                    #     ]
                    # },
                    # 基础
                    {
                        "component": "VWindowItem",
                        "props": {
                            "value": "basic_tab",
                            "style": {
                                "padding-top": "20px",
                                "padding-bottom": "20px"
                            },
                        },
                        "content": [
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center"
                                },
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6,
                                        },
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "AUXILIARY_AUTH_ENABLE",
                                                    "label": "启用用户辅助认证",
                                                    "hint": "启用后允许通过外部服务进行认证、单点登录以及自动创建用户",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6,
                                        },
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "GLOBAL_IMAGE_CACHE",
                                                    "label": "全局图片缓存",
                                                    "hint": "是否启用全局图片缓存，将媒体图片缓存到本地",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6.
                                        },
                                        "content": [
                                            {
                                                "component": "VSelect",
                                                "props": {
                                                    "model": "WALLPAPER",
                                                    "label": "登录首页电影海报",
                                                    "items": [
                                                        {
                                                            "title": "TheMovieDb电影海报",
                                                            "value": "tmdb"
                                                        },
                                                        {
                                                            "title": "Bing每日壁纸",
                                                            "value": "bing"
                                                        }
                                                    ],
                                                    "hint": "登录首页电影海报",
                                                    "persistent-hint": True,
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6,
                                        },
                                        "content": [
                                            {
                                                "component": "VTextField",
                                                "props": {
                                                    "model": "API_TOKEN",
                                                    "label": "API密钥",
                                                    "hint": "用于Jellyseerr/Overseerr、媒体服务器Webhook等配置以及部分支持API_TOKEN的API请求",
                                                    "persistent-hint": True,
                                                    "clearable": True,
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12
                                        },
                                        "content": [
                                            {
                                                "component": "VTextarea",
                                                "props": {
                                                    "model": "PLUGIN_MARKET",
                                                    "label": "插件市场",
                                                    "hint": "插件市场仓库地址，多个地址使用逗号分隔，确保每个地址以/结尾",
                                                    "persistent-hint": True,
                                                    "clearable": True,
                                                }
                                            }
                                        ]
                                    },

                                ]
                            }
                        ]
                    },
                    # 网络
                    {
                        "component": "VWindowItem",
                        "props": {
                            "value": "network_tab",
                            "style": {
                                "padding-top": "20px",
                                "padding-bottom": "20px"
                            },
                        },
                        "content": [
                            # DOH
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center",
                                },
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
                                                    "model": "DOH_ENABLE",
                                                    "label": "启用DNS over HTTPS",
                                                    "hint": "启用后对特定域名使用DOH解析以避免DNS污染",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "info",
                                                    "variant": "tonal",
                                                    "style": "white-space: pre-line;",
                                                    "text": "如果已经配置好 'PROXY_HOST' ，建议关闭 'DOH' ",
                                                },
                                            },
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
                                                    "model": "DOH_DOMAINS",
                                                    "label": "DOH解析的域名",
                                                    "hint": "DOH解析的域名列表，多个域名使用逗号分隔",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "model": "DOH_RESOLVERS",
                                                    "label": "DOH解析服务器",
                                                    "hint": "DOH解析服务器列表，多个服务器使用逗号分隔",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "label": "GitHub Token",
                                                    "placeholder": "格式: ghp_**** 或 github_pat_****",
                                                    "hint": "GitHub Token，提高请求API限流阈值",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "label": "验证码识别服务器",
                                                    "hint": "验证码识别服务器地址",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "model": "GITHUB_PROXY",
                                                    "label": "GitHub加速服务器",
                                                    "placeholder": "格式: https://mirror.ghproxy.com/",
                                                    "hint": "留空则不使用GitHub加速服务器，(注意末尾需要带/)",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "model": "PIP_PROXY",
                                                    "label": "PIP加速服务器",
                                                    "hint": "留空则不使用PIP加速服务器",
                                                    "placeholder": "格式: https://pypi.tuna.tsinghua.edu.cn/simple",
                                                    "persistent-hint": True,
                                                    "clearable": True,
                                                }
                                            }
                                        ]
                                    },
                                ]
                            },
                            # Tmdb相关
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center"
                                },
                                "content": [
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
                                                    "label": "TMDB API地址",
                                                    "hint": "访问正常时无需更改；无法访问时替换为其他中转服务地址，确保连通性",
                                                    "persistent-hint": True,
                                                    "clearable": True,
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
                                                    "label": "TheMovieDb图片服务器",
                                                    "placeholder": "例如：static-mdb.v.geilijiasu.com",
                                                    "hint": "访问正常时无需更改；无法访问时可替换为其他可用地址，确保连通性",
                                                    "persistent-hint": True,
                                                    "clearable": True,
                                                }
                                            }
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                    # 媒体与下载
                    {
                        "component": "VWindowItem",
                        "props": {
                            "value": "media_and_download_tab",
                            "style": {
                                "padding-top": "20px",
                                "padding-bottom": "20px"
                            },
                        },
                        "content": [
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center",
                                },
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 9,
                                        },
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "DOWNLOAD_SUBTITLE",
                                                    "label": "自动下载站点字幕",
                                                    "hint": "自动下载站点字幕（如有）",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 3,
                                        },
                                        "content": [
                                            {
                                                "component": "VTextField",
                                                "props": {
                                                    "model": "MEDIASERVER_SYNC_INTERVAL",
                                                    "label": "媒体服务器同步间隔",
                                                    "hint": "媒体服务器同步间隔",
                                                    "persistent-hint": True,
                                                    "prefix": "每",
                                                    "suffix": "小时",
                                                    "type": "number",
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VTextField",
                                                "props": {
                                                    "model": "AUTO_DOWNLOAD_USER",
                                                    "label": "交互搜索自动下载用户ID",
                                                    "hint": "使用,分割，设置为 all 代表所有用户自动择优下载，未设置需要用户手动选择资源或者回复`0`才自动择优下载",
                                                    "persistent-hint": True,
                                                    "clearable": True,
                                                }
                                            }
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                    # 搜索与整理
                    {
                        "component": "VWindowItem",
                        "props": {
                            "value": "search_and_transfer_tab",
                            "style": {
                                "padding-top": "20px",
                                "padding-bottom": "20px"
                            },
                        },
                        "content": [
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center"
                                },
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 6,
                                        },
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "SEARCH_MULTIPLE_NAME",
                                                    "label": "资源搜索整合多名称结果",
                                                    "hint": "搜索多个名称时是整合多名称的结果",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 3,
                                        },
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "FANART_ENABLE",
                                                    "label": "使用Fanart图片数据源",
                                                    "hint": "启用Fanart图片数据源",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 3,
                                        },
                                        "content": [
                                            {
                                                "component": "VTextField",
                                                "props": {
                                                    "model": "META_CACHE_EXPIRE",
                                                    "label": "元数据缓存时间",
                                                    "hint": "0或负值时，使用系统默认缓存时间",
                                                    "persistent-hint": True,
                                                    "prefix": "每",
                                                    "suffix": "小时",
                                                    "type": "number",
                                                }
                                            }
                                        ]
                                    },
                                ]
                            },
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center"
                                },
                                "content": [
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
                                                        {
                                                            "title": "TheMovieDb",
                                                            "value": "themoviedb"
                                                        },
                                                        {
                                                            "title": "豆瓣",
                                                            "value": "douban"
                                                        }
                                                    ],
                                                    "hint": "媒体信息识别来源",
                                                    "persistent-hint": True
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
                                                        {
                                                            "title": "TheMovieDb",
                                                            "value": "themoviedb"
                                                        },
                                                        {
                                                            "title": "豆瓣",
                                                            "value": "douban"
                                                        }
                                                    ],
                                                    "hint": "刮削元数据及图片使用的数据源",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12
                                        },
                                        "content": [
                                            {
                                                "component": "VTextarea",
                                                "props": {
                                                    "model": "MOVIE_RENAME_FORMAT",
                                                    "label": "电影重命名格式",
                                                    "hint": "电影重命名格式，使用Jinja2语法，每行一个配置项，参考：https://jinja.palletsprojects.com/en/3.0.x/templates/",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12
                                        },
                                        "content": [
                                            {
                                                "component": "VTextarea",
                                                "props": {
                                                    "model": "TV_RENAME_FORMAT",
                                                    "label": "电视剧重命名格式",
                                                    "hint": "电视剧重命名格式，使用Jinja2语法",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                            "md": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "warning",
                                                    "variant": "tonal",
                                                    "style": "white-space: pre-line;",
                                                    "text": "Jinja2语法参考："
                                                },
                                                "content": [
                                                    {
                                                        "component": "a",
                                                        "props": {
                                                            "href": "https://jinja.palletsprojects.com/en/3.0.x/templates/",
                                                            "target": "_blank"
                                                        },
                                                        "content": [
                                                            {
                                                                "component": "u",
                                                                "text": "https://jinja.palletsprojects.com/en/3.0.x/templates/"
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 自定义
                    {
                        "component": "VWindowItem",
                        "props": {
                            "value": "params_tab",
                            "style": {
                                "padding-top": "20px",
                                "padding-bottom": "20px"
                            },
                        },
                        "content": [
                            {
                                "component": "VRow",
                                "props": {
                                    "align": "center",
                                },
                                "content": [
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
                                                    "hint": "自定义配置，每行一个配置项，格式：配置项=值",
                                                    "persistent-hint": True
                                                }
                                            }
                                        ]
                                    }
                                ]
                            },
                        ]
                    }
                ]
            },
        ]

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
