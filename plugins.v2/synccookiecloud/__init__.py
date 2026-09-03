import json
from datetime import datetime, timedelta
from hashlib import md5
from urllib.parse import urlparse

import pytz

from app.core.config import settings
from app.db.site_oper import SiteOper
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.utils.crypto import CryptoJsUtils


class SyncCookieCloud(_PluginBase):
    # 插件名称
    plugin_name = "同步CookieCloud"
    # 插件描述
    plugin_desc = "同步MoviePilot站点Cookie到本地CookieCloud。"
    # 插件图标
    plugin_icon = "Cookiecloud_A.png"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "synccookiecloud_"
    # 加载顺序
    plugin_order = 28
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):

        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")

            if self._enabled or self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)

                # 立即运行一次
                if self._onlyonce:
                    logger.info(f"同步CookieCloud服务启动，立即运行一次")
                    self._scheduler.add_job(self.__sync_to_cookiecloud, 'date',
                                            run_date=datetime.now(
                                                tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="同步CookieCloud")
                    # 关闭一次性开关
                    self._onlyonce = False

                    # 保存配置
                    self.__update_config()

                # 周期运行
                if self._cron:
                    try:
                        self._scheduler.add_job(func=self.__sync_to_cookiecloud,
                                                trigger=CronTrigger.from_crontab(self._cron),
                                                name="同步CookieCloud")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{err}")
                        # 推送实时消息
                        self.systemmessage.put(f"执行周期配置错误：{err}")

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def __sync_to_cookiecloud(self):
        """
        同步站点cookie到cookiecloud
        """
        # 获取所有站点
        sites = SiteOper().list_order_by_pri()
        if not sites:
            return

        if not settings.COOKIECLOUD_ENABLE_LOCAL:
            logger.error('本地CookieCloud服务器未启用')
            return

        cookies = {}
        for site in sites:
            domain = urlparse(site.url).netloc
            cookie = site.cookie

            if not cookie:
                logger.error(f"站点 {domain} 无cookie，跳过处理...")
                continue

            # 解析cookie
            site_cookies = []
            for ck in cookie.split(";"):
                kv = ck.split("=")
                if len(kv) < 2:
                    continue
                site_cookies.append({
                    "domain": domain,
                    "name": ck.split("=")[0],
                    "value": ck.split("=")[1]
                })
            # 存储cookies
            cookies[domain] = site_cookies
        if cookies:
            crypt_key = self._get_crypt_key()
            try:
                cookies = {'cookie_data': cookies}
                encrypted_data = CryptoJsUtils.encrypt(json.dumps(cookies).encode('utf-8'), crypt_key).decode('utf-8')
            except Exception as e:
                logger.error(f"CookieCloud加密失败，{e}")
                return
            ck = {'encrypted': encrypted_data}
            cookie_path = settings.COOKIE_PATH / f"{settings.COOKIECLOUD_KEY}.json"
            cookie_path.write_bytes(json.dumps(ck).encode('utf-8'))
            logger.info(f"同步站点cookie到本地CookieCloud成功")
        else:
            logger.error(f"同步站点cookie到本地CookieCloud失败，未获取到站点cookie")

    def __decrypted(self, encrypt_data: dict):
        """
        获取并解密本地CookieCloud数据
        """
        encrypted = encrypt_data.get("encrypted")
        if not encrypted:
            return {}, "未获取到cookie密文"
        else:
            crypt_key = self._get_crypt_key()
            try:
                decrypted_data = CryptoJsUtils.decrypt(encrypted, crypt_key).decode('utf-8')
                result = json.loads(decrypted_data)
            except Exception as e:
                return {}, "cookie解密失败：" + str(e)

        if not result:
            return {}, "cookie解密为空"

        if result.get("cookie_data"):
            contents = result.get("cookie_data")
        else:
            contents = result
        return contents

    @staticmethod
    def _get_crypt_key() -> bytes:
        """
        使用UUID和密码生成CookieCloud的加解密密钥
        """
        md5_generator = md5()
        md5_generator.update(
            (str(settings.COOKIECLOUD_KEY).strip() + '-' + str(settings.COOKIECLOUD_PASSWORD).strip()).encode('utf-8'))
        return (md5_generator.hexdigest()[:16]).encode('utf-8')

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron
        })

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
                                    'md': 6
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
                                    'md': 6
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
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
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
                                            'text': '需要MoviePilot设定-站点启用本地CookieCloud服务器。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "5 1 * * *",
        }

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
