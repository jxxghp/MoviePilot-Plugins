import json, pytz
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional, Union
from requests import get as req_get
from requests import post as req_post
from urllib.parse import urljoin

from app.core.config import settings
from app.plugins import _PluginBase
from app.log import logger
from app.utils.string import StringUtils
from app.chain.site import SiteChain
from app.scheduler import Scheduler
from app.core.config import settings

from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler


class GistSyncCK(_PluginBase):
    # 插件名称
    plugin_name = "Gist同步CK"
    # 插件描述
    plugin_desc = "以Gist方式同步cookie，搭配sync-my-cookie浏览器插件。"
    # 插件图标
    plugin_icon = "Github_C.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "jeblove"
    # 作者主页
    author_url = "https://github.com/jeblove"
    # 插件配置项ID前缀
    plugin_config_prefix = "gsck_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled: bool = False
    _cron_switch: bool = False
    _onlyonce: bool = False
    _notify: bool = False
    _base_url = None
    _cron = None
    _token = None
    _password = None
    _gistid = None
    _filename = None
    _blacklist = None
    _whitelist = None
    _cc_switch: bool = False

    _api_name = [
        "get_domain_list",
        "get_cookie",
        "get_all_cookie",
        "update_gist"
    ]
    _api_header = {
        "token": None,
        "password": None,
        "gistid": None,
        "filename": None
    }
    # 请求超时时间
    _timeout = 20
    _ignore_cookies: list = ["CookieAutoDeleteBrowsingDataCleanup", "CookieAutoDeleteCleaningDiscarded"]

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    # 开启自启（启动插件状态下）
    _auto_run_switch: bool = False
    _first_auto: bool = True

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._cron_switch = config.get("cron_switch")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._base_url = config.get("base_url")
            self._cron = config.get("cron")
            self._token = config.get("token")
            self._password = config.get("password")
            self._gistid = config.get("gistid")
            self._filename = config.get("filename")
            self._blacklist = config.get("blacklist")
            self._whitelist = config.get("whitelist")
            self._cc_switch = config.get("cc_switch")
            self._auto_run_switch = config.get("auto_run")

        __auto_run = self._enabled and self._auto_run_switch and self._first_auto

        if self._onlyonce or __auto_run:
            # 运行一次 or 开机运行一次
            if __auto_run:
                self._first_auto = False
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"Gist同步CK服务启动，立刻运行一次")
            self._scheduler.add_job(func=self.run, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="Gist同步CK")

            # 关闭一次性开关
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "cron_switch": self._cron_switch,
                "onlyonce": False,
                "notify": self._notify,
                "base_url": self._base_url,
                "cron": self._cron,
                "token": self._token,
                "password": self._password,
                "gistid": self._gistid,
                "filename": self._filename,
                "blacklist": self._blacklist,
                "whitelist": self._whitelist,
                "cc_switch": self._cc_switch,
                "auto_run": self._auto_run_switch
            })

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron and self._cron_switch:
            return [{
                "id": "GistSyncCK",
                "name": "Gist同步CK定时服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.run,
                "kwargs": {}
            }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cron_switch',
                                            'label': '周期模式',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'base_url',
                                            'label': '*gist-sync-api服务器地址',
                                            'placeholder': 'http://172.17.0.1:9300'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '检测执行周期',
                                            'placeholder': '30 */6 * * *'
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'token',
                                            'label': '*GitHub token(gist)'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'password',
                                            'label': '*加密密码'
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'gistid',
                                            'label': '*gist ID'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'filename',
                                            'label': '*gist 文件名',
                                            'placeholder': 'kevast-gist-default.json'
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
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'blacklist',
                                            'label': '黑名单列表',
                                            'placeholder': '暂未支持'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'whitelist',
                                            'label': '白名单列表',
                                            'placeholder': '暂未支持'
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cc_switch',
                                            'label': '运行时移除CookieCloud定时服务?'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'cols': 6,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '仅在插件运行时生效，即想要恢复CookieCloud定时服务：关闭左侧开关，打开【立刻运行一次】',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'auto_run',
                                            'label': '开机自启'
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
                                        },
                                        'html': "<div class='v-alert__content'>详细教程请参考：<a href='https://github.com/jeblove/MoviePilot-Plugins/blob/main/plugins/gistsyncck/README.md' target='_blank'>https://github.com/jeblove/MoviePilot-Plugins/blob/main/plugins/gistsyncck/README.md</a></div>"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cron_switch": True,
            "onlyonce": False,
            "notify": False,
            "base_url": "",
            "cron": "30 */6 * * *",
            "token": "",
            "password": "",
            "gistid": "",
            "filename": "",
            "blacklist": "",
            "whitelist": "",
            "cc_switch": True,
            "auto_run": True
        }

    def req_gsck(self, api_name: str, params: dict=None, data: dict=None, method: str='get', add_json_header: bool=False) -> Union[Any, False]:
        """封装requests

        :param api_name: 接口名
        :param params: get方法参数, defaults to None
        :param data: post方法参数, defaults to None
        :param method: 方法, defaults to 'get'
        :param add_json_header: 是否添加application/json, defaults to False
        :return: response or False
        """
        formatted_base_url = urljoin(self._base_url, '').rstrip('/')
        params = params if params else {}

        self._api_header["password"] = self._password
        if add_json_header:
            self._api_header["Content-Type"] = "application/json"

        if api_name in self._api_name:
            __api_endpoint = api_name
            __full_url = f"{formatted_base_url}/api/{__api_endpoint}"

            if not (__full_url.startswith('http://') or __full_url.startswith('https://')):
                __full_url = 'http://' + __full_url

            __res = None
            try:
                if method == 'get':
                    __res = req_get(__full_url, params=params, headers=self._api_header, timeout=self._timeout)
                elif method == 'post':
                    __res = req_post(__full_url, json=data, headers=self._api_header, timeout=self._timeout)
                else:
                    logger.error("请求方法异常")
                    return False

                if __res:
                    # 正常请求
                    return __res
                else:
                    # logger.error("请求失败，{}请求返回状态码：{}".format(method, __res.status_code if __res else '未知'))
                    logger.error("请求失败，{}请求返回状态码：{}".format(method, __res.status_code))
                    # __res : False
                    return __res
            except Exception as e:
                logger.error("请求失败，错误信息：{}".format(e))
                return False
        else:
            logger.error("没有该api:{}".format(api_name))
            return False

    def get_gist(self) -> Union[str, False]:
        """获取gist文件内容

        :return: gist内容
        """
        __header = {
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {self._token}',
        }
        __url = f'https://api.github.com/gists/{self._gistid}'
        try:
            __res = req_get(url=__url, headers=__header, timeout=self._timeout*1.5)
            __data = __res.json()
            __gist_name, __gist_value = list(__data['files'].items())[0]
            return json.loads(__gist_value['content'])
        except Exception as e:
            logger.error("获取gist失败，请检测参数，错误信息：{}".format(e))
            return False

    def push_gist(self, content: Union[str, Dict[str, Any]]) -> bool:
        """推送内容到目标服务器

        :param content: 内容
        :return: True or False
        """
        data = { 'content': content }
        try:
            res = self.req_gsck("update_gist", data=data, method='post', add_json_header=True)
        except Exception as e:
            logger.error("推送gist失败，请检测参数，错误信息：{}".format(e))
            return False
        if res and res.status_code == 200:
            logger.info("推送gist成功")
            return True
        else:
            logger.error("推送gist失败")
            return False

    def check_env(self) -> bool:
        """检查api服务端环境
        利用请求gist文件中的域名列表接口作为测试
        :return: True or False
        """
        logger.info("检测环境中...")

        if not any([self._base_url, self._token, self._password, self._gistid, self._filename]):
            logger.error("必要参数不能为空")
            return False

        res = self.req_gsck('get_domain_list')
        if res != False:
            # if res.status_code == 404:
                # 404：api服务器环境缺文件
            logger.info("准备推送gist文件到api服务器")
            __content = self.get_gist()
            if __content != False:
                if self.push_gist(__content):
                    return True
                return False
            else:
                logger.error("gist文件有异常，无法推送")
                return False
        else:
            logger.error("确保api服务端正常运行中")
            return False

    def get_all_cookie(self) -> Union[Dict[str, Any], False]:
        """获取所有ck

        :return: json or False
        """
        res = self.req_gsck('get_all_cookie')
        if res:
            if res.status_code == 200:
                return res.json()
            else:
                logger.error("请求get_all_cookie接口错误：{}".format(res))
                return False

    def get_cookie(self, domain: str) -> Union[Dict[str, Any], False]:
        """获取指定域名的ck

        :param domain: 域名"github.com"
        :return: json or False
        """
        params = {
            "domain": domain
        }
        res = self.req_gsck('get_cookie', params)
        if res:
            if res.status_code == 200:
                return res.json()
            else:
                logger.error("请求get_cookie[{}]接口错误：{}".format(domain, res))
                return False

    def normalize_cookie(self, contents: Dict[str, Any]) -> Dict[str, str]:
        """cookie数据标准化处理
            整理cookie数据,使用domain域名的最后两级作为分组依据;
            与cookiecloud.py中一致;
            此处被normalize_output调用。
        :param contents: cookie_list_json, from "get_all_cookie"
        :return: cookies, 可直接应用于保存到站点
        """

        domain_groups = {}
        for site, cookies in contents.items():
            for cookie in cookies:
                domain_key = StringUtils.get_url_domain(cookie.get("domain"))
                if not domain_groups.get(domain_key):
                    domain_groups[domain_key] = [cookie]
                else:
                    domain_groups[domain_key].append(cookie)
        # 返回错误
        ret_cookies = {}
        # 索引器
        for domain, content_list in domain_groups.items():
            if not content_list:
                continue
            # 只有cf的cookie过滤掉
            cloudflare_cookie = True
            for content in content_list:
                if content["name"] != "cf_clearance":
                    cloudflare_cookie = False
                    break
            if cloudflare_cookie:
                continue
            # 站点Cookie
            cookie_str = ";".join(
                [f"{content.get('name')}={content.get('value')}"
                 for content in content_list
                 if content.get("name") and content.get("name") not in self._ignore_cookies]
            )
            ret_cookies[domain] = cookie_str
        return ret_cookies

    def normalize_output(self) -> Tuple[Optional[dict], str]:
        """cookies标准化输出
            直接调用该方法得到可用于站点设置的cookies
        :return: cookies
        """
        check_env_state = self.check_env()
        logger.info("环境状态：{}".format(check_env_state))

        if check_env_state:
            ck_contents = self.get_all_cookie()
            if ck_contents:
                ret_cookies = self.normalize_cookie(ck_contents)
                return ret_cookies, ""
            else:
                logger.error("获取解密cookie出错")
                return {}, "获取解密cookie出错"
        return {}, "环境异常"

    def run(self):
        """主运行方法
        """
        logger.info(f"是否关闭CookieCloud: {self._cc_switch}")
        # 定时任务管理实例化
        self.sys_scheduler = Scheduler()

        if self._cc_switch:
            # 关闭CookieCloud
            self.stop_cookiecloud()
        else:
            self.keep_cookiecloud()

        sitechain = SiteChain()
        # 以插件自身cookies运行同步cookie方法
        ret_cookies, ret_msg = self.normalize_output()
        if ret_cookies:
            sync_state, sync_msg = sitechain.sync_cookies(custom_cookie=(ret_cookies, ret_msg))
        else:
            sync_msg = f"cookies获取错误，未能同步，{ret_msg}"
            logger.error(sync_msg)
        
        if self._notify:
            self.post_message(title=f"【Gist同步CK】", text=sync_msg)

    def stop_cookiecloud(self):
        """停止CookieCloud
        """
        self.sys_scheduler.remove_id_job("cookiecloud")

    def keep_cookiecloud(self):
        """恢复/保持运行CookieCloud
        """
        for scheduleJ_info in self.sys_scheduler.list():
            if scheduleJ_info.id == 'cookiecloud':
                logger.info("CookieCloud正常运行中")
            else:
                logger.info("初始化定时服务")
                self.sys_scheduler.init()

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
