"""证书管理插件。

面向不熟悉证书部署的用户，提供三种证书获取与维护方式：

1. 手动部署：粘贴证书与私钥 PEM 文本，插件完成校验、落盘与 nginx 重载。
2. 自动申请：填写域名与 DNS 服务商凭据，插件调用 acme.sh 完成 DNS-01 签发。
3. 自动续期：定时调用 acme.sh 检查并续期，续期成功后自动重载 nginx。

插件只负责编排 acme.sh 与 nginx，不实现 ACME 协议本身。
"""

import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.sdk.plugin import _PluginBase
from app.schemas.types import MessageType
from app.sdk.logging import logger


class CertManager(_PluginBase):
    """证书管理插件。

    统一管理证书的手动部署、自动申请与自动续期，降低证书配置门槛。
    """

    # 插件名称
    plugin_name = "证书管理"
    # 插件描述
    plugin_desc = "SSL 证书部署、申请与自动续期。"
    # 插件图标
    plugin_icon = "certmanager.png"
    # 插件版本
    plugin_version = "1.4.1"
    # 插件作者
    plugin_author = "LLL001a"
    # 作者主页
    author_url = "https://github.com/LLL001a"
    # 插件配置项ID前缀
    plugin_config_prefix = "certmanager_"
    # 加载顺序
    plugin_order = 98
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _notify = True
    _cron = "0 4 * * *"
    _acme_home = "/config/acme.sh"
    _cert_dir = "/config/certs/latest"
    _domain = ""
    _dns_provider = "dns_ali"
    _dns_key = ""
    _dns_secret = ""
    _key_length = "ec-256"
    # 证书剩余有效期低于该天数时告警，说明续期未成功
    _warn_days = 20
    # 外部命令执行超时时间（秒）
    _timeout = 600

    # 常用 DNS 服务商预设。使用 {title, value} 对象配合 item-title/item-value，
    # 让下拉框显示中文名称、保存脚本名；VCombobox 允许手动输入，
    # 因此这里只是快捷选项，不限制实际可用的服务商。
    _DNS_PROVIDERS = [
        {"title": "阿里云（Aliyun）", "value": "dns_ali"},
        {"title": "腾讯云 DNSPod", "value": "dns_dp"},
        {"title": "Cloudflare", "value": "dns_cf"},
        {"title": "华为云", "value": "dns_huaweicloud"},
        {"title": "百度云", "value": "dns_baidu"},
        {"title": "GoDaddy", "value": "dns_gd"},
        {"title": "NameSilo", "value": "dns_namesilo"},
        {"title": "Namecheap", "value": "dns_namecheap"},
        {"title": "Porkbun", "value": "dns_porkbun"},
        {"title": "西部数码", "value": "dns_west_cn"},
        {"title": "DNSPod 国际版", "value": "dns_dpi"},
        {"title": "AWS Route53", "value": "dns_aws"},
        {"title": "Azure DNS", "value": "dns_azure"},
        {"title": "Google Cloud DNS", "value": "dns_gcloud"},
    ]

    # 各服务商的凭据字段名与填写说明，用于动态生成两个输入框的提示。
    # key 为 acme.sh 的 dnsapi 脚本名。
    _PROVIDER_CREDENTIALS = {
        "dns_ali": ("Ali_Key", "AccessKey ID", "Ali_Secret", "AccessKey Secret"),
        "dns_dp": ("DP_Id", "DNSPod ID", "DP_Key", "DNSPod Token"),
        "dns_cf": ("CF_Token", "API Token", "CF_Account_ID", "Account ID（可选）"),
        "dns_huaweicloud": (
            "HUAWEICLOUD_Username",
            "账号名",
            "HUAWEICLOUD_Password",
            "密码",
        ),
        "dns_baidu": ("BAIDU_AK", "Access Key", "BAIDU_SK", "Secret Key"),
        "dns_gd": ("GD_Key", "API Key", "GD_Secret", "API Secret"),
        "dns_namesilo": ("Namesilo_Key", "API Key", "Namesilo_Key", "同上（无需第二个）"),
        "dns_namecheap": (
            "NAMECHEAP_API_KEY",
            "API Key",
            "NAMECHEAP_USERNAME",
            "用户名",
        ),
        "dns_porkbun": (
            "PORKBUN_API_KEY",
            "API Key",
            "PORKBUN_SECRET_API_KEY",
            "Secret Key",
        ),
        "dns_west_cn": ("WEST_Username", "用户名", "WEST_ApiKey", "API Key"),
        "dns_dpi": ("DPI_Id", "DNSPod ID", "DPI_Key", "DNSPod Token"),
        "dns_aws": (
            "AWS_ACCESS_KEY_ID",
            "Access Key ID",
            "AWS_SECRET_ACCESS_KEY",
            "Secret Access Key",
        ),
        "dns_azure": (
            "AZUREDNS_SUBSCRIPTIONID",
            "Subscription ID",
            "AZUREDNS_TENANTID",
            "Tenant ID",
        ),
        "dns_gcloud": (
            "GCE_PROJECT",
            "项目 ID",
            "GCE_SERVICE_ACCOUNT_FILE",
            "服务账号 JSON 路径",
        ),
    }

    # 默认凭据字段名，用于未收录的服务商
    _DEFAULT_CREDENTIAL_FIELDS = ("KEY1", "凭据名 1", "KEY2", "凭据名 2")

    # acme.sh 的 dnsapi 脚本下载地址前缀
    _DNSAPI_RAW_URL = (
        "https://api.github.com/repos/acmesh-official/acme.sh/contents/dnsapi/{name}.sh"
    )

    # acme.sh 主脚本下载地址。使用 GitHub API 而非 get.acme.sh，
    # 因为后者在部分网络环境下会被重置。
    _ACME_RAW_URL = (
        "https://api.github.com/repos/acmesh-official/acme.sh/contents/acme.sh"
    )

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """根据插件配置初始化运行状态。"""
        if config:
            self._enabled = bool(config.get("enabled"))
            self._notify = bool(config.get("notify", True))
            self._cron = str(config.get("cron") or "0 4 * * *").strip()
            self._acme_home = str(config.get("acme_home") or "/config/acme.sh").strip()
            self._cert_dir = str(
                config.get("cert_dir") or "/config/certs/latest"
            ).strip()
            self._domain = str(config.get("domain") or "").strip()
            self._dns_provider = self._normalize_provider(config.get("dns_provider"))
            self._dns_key = str(config.get("dns_key") or "").strip()
            self._dns_secret = str(config.get("dns_secret") or "").strip()
            self._key_length = str(config.get("key_length") or "ec-256").strip()

    @staticmethod
    def _normalize_provider(value: Any) -> str:
        """
        规范化服务商配置值

        VCombobox 在旧版本配置中可能存下 ``{title, value}`` 对象，
        这里统一提取脚本名，避免后续拼接出错误的脚本路径。

        :param value: 配置中的原始值
        :return: 服务商脚本名，缺失时返回默认值
        """
        if isinstance(value, dict):
            value = value.get("value") or value.get("title")
        provider = str(value or "").strip()
        return provider or "dns_ali"

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表。"""
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询当前证书状态",
            },
            {
                "path": "/deploy",
                "endpoint": self.api_deploy,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "手动部署证书",
            },
            {
                "path": "/issue",
                "endpoint": self.api_issue,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "自动申请证书",
            },
            {
                "path": "/renew",
                "endpoint": self.api_renew,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行续期检查",
            },
            {
                "path": "/dnsapi",
                "endpoint": self.api_download_dnsapi,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "下载指定服务商的 DNS 插件脚本",
            },
            {
                "path": "/verify",
                "endpoint": self.api_verify,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "检测配置是否正确、服务商是否连通",
            },
            {
                "path": "/install",
                "endpoint": self.api_install_acme,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "一键安装或升级 acme.sh",
            },
            {
                "path": "/credentials",
                "endpoint": self.api_lookup_credentials,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "查询服务商需要的凭据字段",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册证书续期定时服务。"""
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError as error:
            logger.error(f"证书管理插件 cron 表达式无效：{self._cron}，{error}")
            return []
        return [
            {
                "id": "CertManager",
                "name": "证书自动续期服务",
                "trigger": trigger,
                "func": self.renew_cert,
                "kwargs": {},
            }
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "续期检查周期",
                                            "placeholder": "0 4 * * *",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "证书默认部署到 /config/certs/latest/，"
                                            "与 MoviePilot 镜像的 nginx 配置一致。"
                                            "如你的 nginx 使用其他路径，请修改下方证书目录。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "acme_home",
                                            "label": "acme.sh 目录",
                                            "placeholder": "/config/acme.sh",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cert_dir",
                                            "label": "证书部署目录",
                                            "placeholder": "/config/certs/latest",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "flat",
                                            "block": True,
                                            "prepend-icon": "mdi-download-box",
                                            "onclick": "function(e) { "
                                            "if (!confirm('将从 acme.sh 官方仓库下载并"
                                            "安装到指定目录，已安装时执行升级。是否继续？')) "
                                            "return; "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/install', {})"
                                            ".then(function(r) { "
                                            "alert(r && r.message ? r.message "
                                            ": '安装完成') })"
                                            ".catch(function(err) { "
                                            "console.error(err); "
                                            "alert('安装失败，请查看日志') }) }",
                                        },
                                        "text": "一键安装 / 升级 acme.sh",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "acme.sh 是申请证书所需的命令行工具。"
                                            "点击上方按钮即可自动下载安装，"
                                            "无需手动执行命令；已安装时会升级到最新版，"
                                            "原有账号与证书配置会保留。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VDivider",
                                        "props": {"class": "my-2"},
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": "以下配置用于「自动申请」与「自动续期」。"
                                            "只做手动部署的用户可以跳过。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "domain",
                                            "label": "证书域名",
                                            "placeholder": "example.com",
                                            "hint": "多个域名用英文逗号分隔，"
                                            "泛域名写 *.example.com",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VCombobox",
                                        "props": {
                                            "model": "dns_provider",
                                            "label": "DNS 服务商",
                                            "items": self._DNS_PROVIDERS,
                                            "item-title": "title",
                                            "item-value": "value",
                                            "hint": "可从列表选择，也可直接输入 "
                                            "acme.sh 的脚本名（如 dns_xxx）。"
                                            "常用：dns_ali 阿里云、dns_dp 腾讯云、"
                                            "dns_cf Cloudflare",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "凭据字段名随服务商不同。"
                                            "阿里云填 AccessKey ID 与 AccessKey Secret；"
                                            "腾讯云填 DNSPod ID 与 Token；"
                                            "Cloudflare 填 API Token。"
                                            "不确定时点击下方按钮查询。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "info",
                                            "variant": "tonal",
                                            "block": True,
                                            "prepend-icon": "mdi-help-circle-outline",
                                            "onclick": "function(e) { "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/credentials', "
                                            "{provider: model.dns_provider})"
                                            ".then(function(r) { "
                                            "if (!r || r.success === false) { "
                                            "alert(r && r.message "
                                            "? r.message : '查询失败'); return } "
                                            "var lines = [r.message, '']; "
                                            "for (var i = 0; i < r.fields.length; i++) { "
                                            "lines.push((i + 1) + '. ' + r.fields[i]) } "
                                            "lines.push(''); "
                                            "lines.push('按顺序填入下方两个输入框；'); "
                                            "lines.push('超过两个字段时，其余字段请写入脚本的 account.conf。'); "
                                            "alert(lines.join('\\n')) })"
                                            ".catch(function(err) { "
                                            "console.error(err); "
                                            "alert('查询失败，请查看日志') }) }",
                                        },
                                        "text": "查询当前服务商需要哪些凭据",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "dns_key",
                                            "label": "凭据 1（Key / ID / Token）",
                                            "placeholder": "如阿里云的 AccessKey ID",
                                            "hint": "阿里云填 Ali_Key 的值",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "dns_secret",
                                            "label": "凭据 2（Secret / Token）",
                                            "placeholder": "如阿里云的 AccessKey Secret",
                                            "hint": "阿里云填 Ali_Secret 的值",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "success",
                                            "variant": "tonal",
                                            "text": "示例（阿里云）：凭据 1 填 "
                                            "LTAI5tExampleKeyId0000，"
                                            "凭据 2 填 AccessKey Secret。"
                                            "建议使用只有 DNS 解析权限的子账号密钥。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "block": True,
                                            "prepend-icon": "mdi-download",
                                            "onclick": "function(e) { "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/dnsapi', "
                                            "{provider: model.dns_provider})"
                                            ".then(function(r) { "
                                            "alert(r && r.message ? r.message : '下载完成') })"
                                            ".catch(function(err) { "
                                            "console.error(err); alert('下载失败') }) }",
                                        },
                                        "text": "下载 DNS 插件脚本",
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "success",
                                            "variant": "flat",
                                            "block": True,
                                            "prepend-icon": "mdi-check-circle",
                                            "onclick": "function(e) { "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/verify', "
                                            "{domain: model.domain, "
                                            "dns_provider: model.dns_provider, "
                                            "dns_key: model.dns_key, "
                                            "dns_secret: model.dns_secret})"
                                            ".then(function(r) { "
                                            "var lines = []; "
                                            "if (r && r.checks) { "
                                            "for (var i = 0; i < r.checks.length; i++) { "
                                            "var c = r.checks[i]; "
                                            "lines.push((c.ok ? '[通过] ' : '[失败] ') "
                                            "+ c.name + ': ' + c.message) } } "
                                            "if (r && r.message) { lines.push(''); "
                                            "lines.push('结论: ' + r.message) } "
                                            "alert(lines.length ? lines.join('\\n') "
                                            ": '检测未返回结果') })"
                                            ".catch(function(err) { "
                                            "console.error(err); alert('检测失败，请查看日志') }) }",
                                        },
                                        "text": "检测配置",
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "warning",
                                            "variant": "flat",
                                            "block": True,
                                            "prepend-icon": "mdi-certificate",
                                            "onclick": "function(e) { "
                                            "if (!confirm('将向 DNS 服务商写入验证记录"
                                            "并申请证书，过程可能需要 1-3 分钟。"
                                            "是否继续？')) return; "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/issue', "
                                            "{domain: model.domain, "
                                            "dns_provider: model.dns_provider, "
                                            "dns_key: model.dns_key, "
                                            "dns_secret: model.dns_secret})"
                                            ".then(function(r) { "
                                            "alert(r && r.message ? r.message "
                                            ": '申请完成，请查看日志') })"
                                            ".catch(function(err) { "
                                            "console.error(err); "
                                            "alert('申请失败，请查看日志') }) }",
                                        },
                                        "text": "申请证书",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "检测会依次校验域名格式、acme.sh、"
                                            "DNS 插件脚本、凭据填写，"
                                            "最后向 DNS 服务商写入并删除一条测试 TXT 记录，"
                                            "确认凭据真实可用。建议申请证书前先检测一次。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "内置列表只提供常用服务商快捷选项，"
                                            "acme.sh 实际支持 190 多个服务商。"
                                            "若你的服务商不在列表中，"
                                            "直接输入其脚本名并点击上方按钮下载即可。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "key_length",
                                            "label": "密钥类型",
                                            "items": [
                                                {
                                                    "title": "EC 256 位（推荐）",
                                                    "value": "ec-256",
                                                },
                                                {"title": "EC 384 位", "value": "ec-384"},
                                                {"title": "RSA 2048 位", "value": "2048"},
                                                {"title": "RSA 4096 位", "value": "4096"},
                                            ],
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VDivider",
                                        "props": {"class": "my-2"},
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "手动部署证书：如果你已有证书文件，"
                                            "把内容粘贴到下方文本框并点击部署，"
                                            "插件会自动校验匹配性并重载 nginx。"
                                            "使用「申请证书」的用户无需填写这里。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "deploy_cert",
                                            "label": "证书内容（fullchain.pem）",
                                            "rows": 5,
                                            "placeholder": "-----BEGIN CERTIFICATE-----\n"
                                            "...\n-----END CERTIFICATE-----",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "deploy_key",
                                            "label": "私钥内容（privkey.pem）",
                                            "rows": 5,
                                            "placeholder": "-----BEGIN PRIVATE KEY-----\n"
                                            "...\n-----END PRIVATE KEY-----",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "flat",
                                            "block": True,
                                            "prepend-icon": "mdi-upload",
                                            "onclick": "function(e) { "
                                            "if (!model.deploy_cert || !model.deploy_key) { "
                                            "alert('请先粘贴证书内容与私钥内容'); "
                                            "return } "
                                            "window.MoviePilotAPI.post("
                                            "'plugin/CertManager/deploy', "
                                            "{cert: model.deploy_cert, "
                                            "key: model.deploy_key})"
                                            ".then(function(r) { "
                                            "if (r && r.success === false) { "
                                            "alert(r.message || '部署失败') } "
                                            "else { alert(r && r.message "
                                            "? r.message : '部署成功'); "
                                            "model.deploy_cert = ''; "
                                            "model.deploy_key = '' } })"
                                            ".catch(function(err) { "
                                            "console.error(err); "
                                            "alert('部署失败，请查看日志') }) }",
                                        },
                                        "text": "部署证书",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "cron": "0 4 * * *",
            "acme_home": "/config/acme.sh",
            "cert_dir": "/config/certs/latest",
            "domain": "",
            "dns_provider": "dns_ali",
            "dns_key": "",
            "dns_secret": "",
            "key_length": "ec-256",
        }

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页，展示当前证书状态与手动部署入口。"""
        status = self._collect_status()
        content: List[dict] = [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "success" if status["valid"] else "warning",
                                    "variant": "tonal",
                                    "text": status["summary"],
                                },
                            }
                        ],
                    }
                ],
            }
        ]

        if status["valid"]:
            content.append(
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VTable",
                                    "props": {"density": "comfortable"},
                                    "content": [
                                        {
                                            "component": "tbody",
                                            "content": [
                                                self._table_row(
                                                    "证书域名", status["subject"]
                                                ),
                                                self._table_row(
                                                    "签发机构", status["issuer"]
                                                ),
                                                self._table_row(
                                                    "生效时间",
                                                    status["not_before"],
                                                ),
                                                self._table_row(
                                                    "到期时间",
                                                    status["not_after"],
                                                ),
                                                self._table_row(
                                                    "剩余天数",
                                                    f"{status['days_left']} 天",
                                                ),
                                                self._table_row(
                                                    "覆盖域名", status["sans"]
                                                ),
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
            content.append(
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VAlert",
                                    "props": {
                                        "type": "info",
                                        "variant": "tonal",
                                        "density": "compact",
                                        "text": "时间均为北京时间（UTC+8）。",
                                    },
                                }
                            ],
                        }
                    ],
                }
            )

        content.append(
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": "申请证书与手动部署证书请在插件配置页操作。"
                                    "本页仅展示当前证书状态。",
                                },
                            }
                        ],
                    }
                ],
            }
        )

        return content

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """声明插件仪表板组件。"""
        return [{"key": "cert", "name": "证书状态"}]

    def get_dashboard(
        self, key: str, **kwargs: Any
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]]:
        """返回证书状态仪表板。"""
        if key != "cert":
            return None
        status = self._collect_status()
        healthy = status["valid"] and status["days_left"] > self._warn_days
        return (
            {"cols": 12, "md": 6, "lg": 4},
            {"refresh": 3600, "border": True, "title": "证书状态"},
            [
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VAlert",
                                    "props": {
                                        "type": "success" if healthy else "warning",
                                        "variant": "tonal",
                                        "text": status["summary"],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        )

    def stop_service(self) -> None:
        """停止插件后台服务。

        插件只注册定时服务，由宿主调度器统一管理，无需额外清理。
        """

    def api_status(self) -> Dict[str, Any]:
        """返回当前证书状态。"""
        return self._collect_status()

    def api_deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        手动部署证书

        :param payload: 包含 cert 与 key 两个 PEM 文本字段
        :return: 部署结果
        """
        cert_text = str(payload.get("cert") or "").strip()
        key_text = str(payload.get("key") or "").strip()
        if not cert_text or not key_text:
            return {"success": False, "message": "证书内容与私钥内容都不能为空"}

        ok, message = self.deploy_certificate(cert_text, key_text)
        return {"success": ok, "message": message}

    def api_issue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        自动申请证书

        :param payload: 可选覆盖 domain、dns_provider、dns_key、dns_secret
        :return: 申请结果
        """
        domain = str(payload.get("domain") or self._domain).strip()
        provider = self._normalize_provider(
            payload.get("dns_provider") or self._dns_provider
        )
        dns_key = str(payload.get("dns_key") or self._dns_key).strip()
        dns_secret = str(payload.get("dns_secret") or self._dns_secret).strip()
        ok, message = self.issue_certificate(domain, provider, dns_key, dns_secret)
        return {"success": ok, "message": message}

    def api_download_dnsapi(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        下载指定服务商的 DNS 插件脚本

        :param payload: 包含 provider 字段，如 dns_ali
        :return: 下载结果
        """
        provider = self._normalize_provider(
            payload.get("provider") or self._dns_provider
        )
        ok, message = self.download_dnsapi(provider)
        return {"success": ok, "message": message}

    def api_verify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        检测配置是否正确、服务商是否连通

        :param payload: 可选覆盖 domain、dns_provider、dns_key、dns_secret
        :return: 逐项检测结果
        """
        domain = str(payload.get("domain") or self._domain).strip()
        provider = self._normalize_provider(
            payload.get("dns_provider") or self._dns_provider
        )
        dns_key = str(payload.get("dns_key") or self._dns_key).strip()
        dns_secret = str(payload.get("dns_secret") or self._dns_secret).strip()
        return self.verify_config(domain, provider, dns_key, dns_secret)

    def api_install_acme(self) -> Dict[str, Any]:
        """一键安装或升级 acme.sh。"""
        ok, message = self.install_acme()
        return {"success": ok, "message": message}

    def api_lookup_credentials(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        查询指定服务商需要的凭据字段

        :param payload: 包含 provider 字段，如 dns_ali
        :return: 查询结果与字段列表
        """
        provider = self._normalize_provider(
            payload.get("provider") or self._dns_provider
        )
        ok, message, fields = self.lookup_credentials(provider)
        return {"success": ok, "message": message, "fields": fields}

    def api_renew(self) -> Dict[str, Any]:
        """立即执行一次续期检查。"""
        self.renew_cert()
        return {"success": True, "message": "续期检查已执行，请查看日志与通知"}

    def deploy_certificate(self, cert_text: str, key_text: str) -> Tuple[bool, str]:
        """
        校验并部署证书

        :param cert_text: 证书 PEM 文本，可包含完整证书链
        :param key_text: 私钥 PEM 文本
        :return: (是否成功, 结果说明)
        """
        cert_dir = Path(self._cert_dir)
        fullchain = cert_dir / "fullchain.pem"
        privkey = cert_dir / "privkey.pem"

        cert_pem = self._normalize_pem(cert_text, "CERTIFICATE")
        key_pem = self._normalize_pem(key_text, "PRIVATE KEY")
        if not cert_pem:
            return False, "证书格式不正确，需包含 BEGIN/END CERTIFICATE"
        if not key_pem:
            return False, "私钥格式不正确，需包含 BEGIN/END PRIVATE KEY"

        try:
            cert_dir.mkdir(parents=True, exist_ok=True)
            self._backup_current(cert_dir)
            fullchain.write_text(cert_pem, encoding="utf-8")
            privkey.write_text(key_pem, encoding="utf-8")
            privkey.chmod(0o600)
        except OSError as error:
            return False, f"写入证书文件失败：{error}"

        ok, message = self._verify_certificate_pair(fullchain, privkey)
        if not ok:
            self._restore_backup(cert_dir)
            return False, f"证书校验未通过，已回滚：{message}"

        reload_ok, reload_message = self._reload_nginx()
        if not reload_ok:
            return False, f"证书已部署，但 nginx 重载失败：{reload_message}"

        logger.info("证书已手动部署并重载 nginx")
        if self._notify:
            self.post_message(
                mtype=MessageType.Plugin,
                title="【证书管理】部署成功",
                text=f"证书已部署到 {cert_dir}，nginx 已重载。",
            )
        return True, "证书部署成功，nginx 已重载"

    def issue_certificate(
        self,
        domain: str,
        provider: str,
        dns_key: str,
        dns_secret: str,
    ) -> Tuple[bool, str]:
        """
        通过 acme.sh 申请证书

        :param domain: 域名，多个用英文逗号分隔
        :param provider: acme.sh 的 dnsapi 脚本名，如 dns_ali
        :param dns_key: 凭据 1，对应服务商的 Key/ID/Token
        :param dns_secret: 凭据 2，对应服务商的 Secret/Token
        :return: (是否成功, 结果说明)
        """
        if not domain:
            return False, "请先填写证书域名"
        if not provider:
            return False, "请先选择或输入 DNS 服务商"
        if not dns_key:
            return False, "请先填写凭据 1（Key / ID / Token）"

        acme_bin = Path(self._acme_home) / "acme.sh"
        if not acme_bin.is_file():
            return False, f"acme.sh 不存在：{acme_bin}，请先安装 acme.sh"

        hook = Path(self._acme_home) / "dnsapi" / f"{provider}.sh"
        if not hook.is_file():
            return False, (
                f"缺少 DNS 插件 {provider}.sh，"
                "请点击「下载当前服务商的 DNS 插件脚本」按钮后重试"
            )

        env = self._acme_env(provider, dns_key, dns_secret)
        domains = [item.strip() for item in domain.split(",") if item.strip()]
        command = [
            str(acme_bin),
            "--home",
            str(self._acme_home),
            "--issue",
            "--dns",
            provider,
            "--server",
            "letsencrypt",
            "--keylength",
            self._key_length,
        ]
        for item in domains:
            command.extend(["--domain", item])

        output = self._run_command(command, env=env)
        if output is None:
            return False, "acme.sh 执行失败，请查看日志"

        if "Cert success" not in output and "Your cert is in" not in output:
            return False, f"证书申请失败，acme.sh 输出：\n{self._redact(output[-800:])}"

        install_ok, install_message = self._install_certificate(domains[0], env)
        if not install_ok:
            return False, install_message

        logger.info(f"证书申请成功：{domain}")
        if self._notify:
            self.post_message(
                mtype=MessageType.Plugin,
                title="【证书管理】申请成功",
                text=f"域名 {domain} 的证书已申请并部署，nginx 已重载。",
            )
        return True, "证书申请成功，已部署并重载 nginx"

    def download_dnsapi(self, provider: str) -> Tuple[bool, str]:
        """
        从 acme.sh 官方仓库下载指定服务商的 DNS 插件脚本

        :param provider: acme.sh 的 dnsapi 脚本名，如 dns_ali
        :return: (是否成功, 结果说明)
        """
        if not provider:
            return False, "请先选择或输入 DNS 服务商"
        if not re.fullmatch(r"[A-Za-z0-9_]+", provider):
            return False, "服务商名称只能包含字母、数字和下划线"

        dnsapi_dir = Path(self._acme_home) / "dnsapi"
        try:
            dnsapi_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return False, f"创建 dnsapi 目录失败：{error}"

        url = self._DNSAPI_RAW_URL.format(name=provider)
        target = dnsapi_dir / f"{provider}.sh"
        command = [
            "curl",
            "-sSL",
            "--max-time",
            "60",
            "-H",
            "Accept: application/vnd.github.raw",
            url,
            "-o",
            str(target),
        ]
        output = self._run_command(command)
        if output is None:
            return False, "下载失败，请检查网络连接"

        # GitHub API 在脚本不存在时返回 JSON 错误体，需要识别并清理
        if not target.is_file() or target.stat().st_size == 0:
            return False, f"下载失败，服务商 {provider} 可能不存在"
        head = target.read_text(encoding="utf-8", errors="ignore")[:200]
        if "Not Found" in head or head.lstrip().startswith("{"):
            target.unlink(missing_ok=True)
            return False, f"服务商 {provider} 不存在，请检查脚本名"

        target.chmod(0o755)
        logger.info(f"已下载 DNS 插件脚本：{target}")
        return True, f"已下载 {provider}.sh 到 {dnsapi_dir}"

    def install_acme(self) -> Tuple[bool, str]:
        """
        一键安装或升级 acme.sh

        从 acme.sh 官方仓库下载主脚本并初始化目录结构。已安装时执行升级，
        保留原有账号与证书配置。

        :return: (是否成功, 结果说明)
        """
        acme_home = Path(self._acme_home)
        acme_bin = acme_home / "acme.sh"
        existed = acme_bin.is_file()

        try:
            (acme_home / "data").mkdir(parents=True, exist_ok=True)
            (acme_home / "dnsapi").mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return False, f"创建 acme.sh 目录失败：{error}"

        # 升级前备份，下载失败时可回滚，避免破坏正在使用的 acme.sh
        backup = acme_home / "acme.sh.bak"
        if existed:
            try:
                shutil.copy2(acme_bin, backup)
            except OSError as error:
                logger.warning(f"备份 acme.sh 失败，继续安装：{error}")

        command = [
            "curl",
            "-sSL",
            "--max-time",
            "120",
            "-H",
            "Accept: application/vnd.github.raw",
            self._ACME_RAW_URL,
            "-o",
            str(acme_bin),
        ]
        output = self._run_command(command)
        if output is None:
            self._restore_acme_backup(backup, acme_bin, existed)
            return False, "下载失败，请检查网络连接"

        if not self._is_valid_acme_script(acme_bin):
            self._restore_acme_backup(backup, acme_bin, existed)
            return False, "下载的 acme.sh 内容无效，已回滚"

        try:
            acme_bin.chmod(0o755)
        except OSError as error:
            self._restore_acme_backup(backup, acme_bin, existed)
            return False, f"设置执行权限失败：{error}"

        version = self._acme_version(acme_bin)
        backup.unlink(missing_ok=True)

        action = "升级" if existed else "安装"
        logger.info(f"acme.sh {action}成功，版本：{version or '未知'}")
        if self._notify:
            self.post_message(
                mtype=MessageType.Plugin,
                title=f"【证书管理】acme.sh {action}成功",
                text=f"acme.sh 已{action}到 {acme_home}，版本：{version or '未知'}。",
            )
        return True, f"acme.sh {action}成功，版本：{version or '未知'}"

    @staticmethod
    def _is_valid_acme_script(path: Path) -> bool:
        """
        判断下载内容是否为有效的 acme.sh 脚本

        GitHub API 在路径不存在时会返回 JSON 错误体，需要识别并拒绝。

        :param path: 待检查的文件路径
        :return: 是否为有效脚本
        """
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            head = path.read_text(encoding="utf-8", errors="ignore")[:500]
        except OSError:
            return False
        if head.lstrip().startswith("{"):
            return False
        # 有效脚本应包含 shebang 与版本声明
        return head.startswith("#!") and "VER=" in head

    @staticmethod
    def _restore_acme_backup(backup: Path, target: Path, existed: bool) -> None:
        """
        安装失败时恢复原有 acme.sh

        :param backup: 备份文件路径
        :param target: acme.sh 目标路径
        :param existed: 安装前是否已存在
        """
        if existed and backup.is_file():
            try:
                shutil.copy2(backup, target)
                backup.unlink(missing_ok=True)
                logger.info("已恢复原有 acme.sh")
            except OSError as error:
                logger.error(f"恢复 acme.sh 失败：{error}")
        elif not existed:
            target.unlink(missing_ok=True)

    def _acme_version(self, acme_bin: Path) -> str:
        """
        读取 acme.sh 版本号

        :param acme_bin: acme.sh 可执行文件路径
        :return: 版本号，读取失败时返回空字符串
        """
        env = self._acme_env(self._dns_provider, "", "")
        output = self._run_command(
            [str(acme_bin), "--version"], env=env, cwd=self._acme_home
        )
        if not output:
            return ""
        match = re.search(r"v?\d+\.\d+\.\d+", output)
        return match.group(0) if match else ""

    def verify_config(
        self,
        domain: str,
        provider: str,
        dns_key: str,
        dns_secret: str,
    ) -> Dict[str, Any]:
        """
        逐项检测配置是否正确、服务商是否连通

        检测顺序为「本地环境 → 凭据格式 → 真实连通」，任一项失败即停止，
        避免在明显错误的情况下仍然发起外部请求。

        :param domain: 证书域名
        :param provider: acme.sh 的 dnsapi 脚本名
        :param dns_key: 凭据 1
        :param dns_secret: 凭据 2
        :return: 包含 checks 列表与整体结论的字典
        """
        checks: List[Dict[str, Any]] = []

        # 1. 域名格式
        ok, message = self._check_domain(domain)
        checks.append({"name": "证书域名", "ok": ok, "message": message})
        if not ok:
            return self._verify_result(checks)

        # 2. acme.sh 是否安装
        acme_bin = Path(self._acme_home) / "acme.sh"
        ok = acme_bin.is_file()
        checks.append({
            "name": "acme.sh",
            "ok": ok,
            "message": "已安装" if ok else f"未找到 {acme_bin}",
        })
        if not ok:
            return self._verify_result(checks)

        # 3. DNS 插件脚本是否存在
        hook = Path(self._acme_home) / "dnsapi" / f"{provider}.sh"
        ok = hook.is_file()
        checks.append({
            "name": "DNS 插件脚本",
            "ok": ok,
            "message": f"{provider}.sh 已就绪"
            if ok
            else f"缺少 {provider}.sh，请点击下载按钮",
        })
        if not ok:
            return self._verify_result(checks)

        # 4. 凭据是否填写
        key_name, key_label, secret_name, secret_label = self._credential_fields(
            provider
        )
        ok = bool(dns_key)
        checks.append({
            "name": "凭据 1",
            "ok": ok,
            "message": f"{key_name}（{key_label}）已填写" if ok else "未填写",
        })
        if not ok:
            return self._verify_result(checks)

        # 5. 真实连通性：调用 DNS 服务商接口写入并删除一条测试 TXT 记录
        ok, message = self._check_dns_connectivity(
            domain, provider, dns_key, dns_secret
        )
        checks.append({"name": "服务商连通性", "ok": ok, "message": message})

        return self._verify_result(checks)

    @staticmethod
    def _check_domain(domain: str) -> Tuple[bool, str]:
        """
        校验域名格式

        :param domain: 待校验的域名，多个用逗号分隔
        :return: (是否通过, 说明)
        """
        if not domain:
            return False, "未填写域名"
        domains = [item.strip() for item in domain.split(",") if item.strip()]
        if not domains:
            return False, "未填写域名"
        for item in domains:
            # 允许泛域名前缀，其余部分需符合域名规则
            candidate = item[2:] if item.startswith("*.") else item
            if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
                                r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+", candidate):
                return False, f"域名格式不正确：{item}"
        return True, f"共 {len(domains)} 个域名，格式正确"

    def _check_dns_connectivity(
        self,
        domain: str,
        provider: str,
        dns_key: str,
        dns_secret: str,
    ) -> Tuple[bool, str]:
        """
        通过写入并删除测试 TXT 记录验证凭据是否可用

        acme.sh 没有独立的凭据校验命令，因此直接 source 其脚本并调用
        DNS hook 的 add/rm 函数，用真实 API 调用验证凭据。

        :param domain: 用于构造测试记录名的域名
        :param provider: acme.sh 的 dnsapi 脚本名
        :param dns_key: 凭据 1
        :param dns_secret: 凭据 2
        :return: (是否连通, 说明)
        """
        primary = domain.split(",")[0].strip()
        # 去掉泛域名前缀，测试记录用固定子域避免影响真实解析
        base = primary[2:] if primary.startswith("*.") else primary
        test_name = f"_acme-challenge-verify.{base}"
        test_value = f"moviepilot-verify-{int(datetime.now().timestamp())}"

        env = self._acme_env(provider, dns_key, dns_secret)
        script = self._build_verify_script(provider, test_name, test_value)
        output = self._run_command(
            ["/bin/bash", "-c", script],
            env=env,
            cwd=self._acme_home,
        )
        if output is None:
            return False, "检测超时或执行失败，请查看日志"

        if "VERIFY_ADD_OK" not in output:
            reason = self._extract_verify_error(output)
            return False, f"凭据验证失败：{reason}"
        if "VERIFY_RM_OK" not in output:
            # 记录已写入但清理失败，提示用户手动检查
            return True, "凭据有效，但测试记录清理失败，请检查 DNS 解析"

        return True, "凭据有效，服务商连接正常"

    def _build_verify_script(self, provider: str, test_name: str, test_value: str) -> str:
        """
        构造用于验证 DNS 凭据的 shell 脚本

        :param provider: acme.sh 的 dnsapi 脚本名
        :param test_name: 测试 TXT 记录名
        :param test_value: 测试 TXT 记录值
        :return: 可直接交给 bash 执行的脚本
        """
        # 不能加 set -u：acme.sh 内部会引用未定义变量，开启后 source 阶段即失败。
        # _LOG_FILE 让 acme.sh 的日志落到独立文件，便于失败时提取线索。
        return (
            f'_LOG_FILE="{self._verify_log_path()}"\n'
            '. ./acme.sh >/dev/null 2>&1 || exit 1\n'
            f'. ./dnsapi/{provider}.sh || exit 1\n'
            f'if {provider}_add "{test_name}" "{test_value}"; then\n'
            '  echo "VERIFY_ADD_OK"\n'
            f'  if {provider}_rm "{test_name}" "{test_value}"; then\n'
            '    echo "VERIFY_RM_OK"\n'
            '  fi\n'
            'fi\n'
        )

    def _verify_log_path(self) -> str:
        """
        返回凭据检测使用的临时日志路径

        :return: 日志文件绝对路径
        """
        return str(Path(self._acme_home) / "data" / "verify.log")

    def _extract_verify_error(self, output: str) -> str:
        """
        从验证输出与 acme.sh 日志中提取可读的错误原因

        acme.sh 的 DNS 插件在部分失败路径上会吞掉错误详情（例如
        ``_get_root`` 以 ignore 模式调用），此时回退到日志文件，
        仍无有效信息则给出可操作的排查建议。

        :param output: 脚本输出
        :return: 错误摘要
        """
        combined = output + "\n" + self._read_verify_log()

        # 服务商 API 返回的错误码，按常见程度排序
        api_errors = (
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
            "InvalidTimeStamp",
            "Forbidden",
            "Unauthorized",
            "InvalidParameter",
            "DomainRecordDuplicate",
            "InvalidDomainName",
            "NoSuchDomain",
            "AccessDenied",
            "Authentication",
            "invalid_grant",
            "Invalid Token",
            "ErrorCode",
        )
        for keyword in api_errors:
            if keyword in combined:
                return keyword

        # 回退到含错误关键字的行
        keywords = ("error", "Error", "invalid", "Invalid", "denied", "Denied")
        for line in combined.splitlines():
            stripped = line.strip()
            if stripped and any(word in stripped for word in keywords):
                return stripped[:200]

        # acme.sh 未给出具体原因时，给出可操作的排查方向
        return (
            "无法确认凭据有效性。常见原因："
            "① 凭据填写错误或已失效；"
            "② 该凭据没有对应域名的 DNS 解析权限；"
            "③ 域名未托管在当前 DNS 服务商。"
            "请核对后重试，或查看日志中的 acme.sh 输出"
        )

    def _read_verify_log(self) -> str:
        """
        读取凭据检测产生的 acme.sh 日志

        :return: 日志内容，不存在或读取失败时返回空字符串
        """
        log_file = Path(self._verify_log_path())
        if not log_file.is_file():
            return ""
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        # 只保留最后若干行，避免把完整日志塞进界面；同时脱敏凭据
        tail = "\n".join(content.splitlines()[-30:])
        return self._redact(tail)

    @staticmethod
    def _verify_result(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        汇总检测结果

        :param checks: 各项检测结果
        :return: 包含整体结论的字典
        """
        failed = [item for item in checks if not item["ok"]]
        return {
            "success": not failed,
            "checks": checks,
            "message": "配置检测通过，可以申请证书"
            if not failed
            else f"检测未通过：{failed[0]['name']} - {failed[0]['message']}",
        }

    def renew_cert(self) -> None:
        """执行一次证书续期检查。

        acme.sh 未到续期时间时会自行跳过，因此可以按固定周期安全调用。
        """
        acme_bin = Path(self._acme_home) / "acme.sh"
        if not acme_bin.is_file():
            self._notify_failure("执行失败", f"acme.sh 不存在：{acme_bin}")
            return

        env = self._acme_env(self._dns_provider, self._dns_key, self._dns_secret)
        command = [
            str(acme_bin),
            "--home",
            str(self._acme_home),
            "--cron",
            "--server",
            "letsencrypt",
        ]
        output = self._run_command(command, env=env)
        if output is None:
            return

        days_left = self._cert_days_left()
        if days_left is None:
            self._notify_failure("状态异常", "无法读取证书有效期，请检查证书文件")
            return

        if days_left < self._warn_days:
            message = (
                f"证书剩余有效期仅 {days_left} 天，续期可能未成功，"
                "请检查 acme.sh 日志。"
            )
            logger.warning(f"证书续期告警：{message}")
            if self._notify:
                self.post_message(
                    mtype=MessageType.Plugin,
                    title="【证书管理】续期异常",
                    text=message,
                )
            return

        # acme.sh 仅在真正签发或安装证书时输出这两个标记，未到期时不会出现
        if "Cert success" in output or "Installing" in output:
            reload_ok, reload_message = self._reload_nginx()
            if not reload_ok:
                self._notify_failure("重载失败", reload_message)
                return
            logger.info(f"证书已续期，剩余有效期 {days_left} 天")
            if self._notify:
                self.post_message(
                    mtype=MessageType.Plugin,
                    title="【证书管理】续期成功",
                    text=f"证书已续期，剩余有效期 {days_left} 天，nginx 已重载。",
                )
        else:
            logger.info(f"证书无需续期，剩余有效期 {days_left} 天")

    def _install_certificate(self, domain: str, env: Dict[str, str]) -> Tuple[bool, str]:
        """
        把 acme.sh 签发的证书安装到部署目录

        :param domain: 主域名
        :param env: acme.sh 运行环境变量
        :return: (是否成功, 结果说明)
        """
        cert_dir = Path(self._cert_dir)
        try:
            cert_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return False, f"创建证书目录失败：{error}"

        command = [
            str(Path(self._acme_home) / "acme.sh"),
            "--home",
            str(self._acme_home),
            "--install-cert",
            "-d",
            domain,
            "--key-file",
            str(cert_dir / "privkey.pem"),
            "--fullchain-file",
            str(cert_dir / "fullchain.pem"),
        ]
        if self._key_length.startswith("ec"):
            command.append("--ecc")

        output = self._run_command(command, env=env)
        if output is None:
            return False, "安装证书失败，请查看日志"

        reload_ok, reload_message = self._reload_nginx()
        if not reload_ok:
            return False, f"证书已安装，但 nginx 重载失败：{reload_message}"
        return True, "证书安装成功"

    def _acme_env(self, provider: str, dns_key: str, dns_secret: str) -> Dict[str, str]:
        """
        组装 acme.sh 运行环境变量

        :param provider: acme.sh 的 dnsapi 脚本名
        :param dns_key: 凭据 1 的值
        :param dns_secret: 凭据 2 的值
        :return: 环境变量字典
        """
        env = {
            "LE_WORKING_DIR": str(self._acme_home),
            "LE_CONFIG_HOME": str(Path(self._acme_home) / "data"),
            "LE_CERT_HOME": str(Path(self._cert_dir).parent),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        key_name, _, secret_name, _ = self._credential_fields(provider)
        if dns_key:
            env[key_name] = dns_key
        # 部分服务商只需要一个凭据，此时第二个字段与第一个同名，避免覆盖
        if dns_secret and secret_name != key_name:
            env[secret_name] = dns_secret
        return env

    def lookup_credentials(self, provider: str) -> Tuple[bool, str, List[str]]:
        """
        查询指定服务商脚本实际需要的凭据字段

        acme.sh 的 DNS 插件通过 ``_readaccountconf_mutable`` 读取凭据，
        直接解析脚本即可得到准确的字段名，无需维护静态对照表。
        脚本未下载时先自动下载。

        :param provider: acme.sh 的 dnsapi 脚本名，如 dns_ali
        :return: (是否成功, 说明, 字段名列表)
        """
        provider = self._normalize_provider(provider)
        if not re.fullmatch(r"dns_[a-z0-9_]+", provider):
            return False, f"服务商脚本名不合法：{provider}", []

        script = Path(self._acme_home) / "dnsapi" / f"{provider}.sh"
        if not script.is_file():
            ok, message = self.download_dnsapi(provider)
            if not ok:
                return False, message, []

        try:
            content = script.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            return False, f"读取脚本失败：{error}", []

        # 按出现顺序去重，保留脚本中的原始字段名
        fields: List[str] = []
        for name in re.findall(
            r"_readaccountconf_mutable\s+([A-Za-z_][A-Za-z0-9_]*)", content
        ):
            if name not in fields:
                fields.append(name)

        if not fields:
            return (
                False,
                f"{provider} 未声明凭据字段，可能不需要凭据或脚本格式特殊",
                [],
            )
        return True, f"{provider} 需要 {len(fields)} 个凭据字段", fields

    def _credential_fields(self, provider: str) -> Tuple[str, str, str, str]:
        """
        返回服务商对应的凭据字段名与界面提示

        :param provider: acme.sh 的 dnsapi 脚本名
        :return: (凭据1字段名, 凭据1提示, 凭据2字段名, 凭据2提示)
        """
        return self._PROVIDER_CREDENTIALS.get(
            provider, self._DEFAULT_CREDENTIAL_FIELDS
        )

    def _run_command(
        self,
        command: List[str],
        *,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """
        执行外部命令并返回合并输出

        :param command: 命令与参数列表
        :param env: 可选的环境变量
        :param cwd: 可选的工作目录
        :return: 成功时返回合并后的输出，失败时返回 None
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
                cwd=cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._notify_failure("执行超时", f"命令执行超时（{self._timeout} 秒）")
            return None
        except OSError as error:
            self._notify_failure("执行异常", f"命令执行异常：{error}")
            return None

        output = (result.stdout or "") + (result.stderr or "")
        logger.info(
            f"命令执行完成，退出码 {result.returncode}：\n{self._redact(output)}"
        )
        return output

    @staticmethod
    def _redact(text: str) -> str:
        """
        脱敏输出中的凭据

        acme.sh 在 DEBUG 模式或部分错误路径下会把凭据写入输出，
        日志会长期留存，因此记录前统一替换为占位符。

        :param text: 原始输出
        :return: 脱敏后的文本
        """
        # 常见的凭据键名，覆盖 acme.sh 各 DNS 插件使用的变量
        patterns = (
            r"(?i)(Ali_Key|Ali_Secret|DP_Id|DP_Key|CF_Token|CF_Account_ID)"
            r"(=|['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9_\-/+=]{4,})",
            r"(?i)(AccessKeyId|AccessKeySecret|api[_-]?key|api[_-]?secret|token)"
            r"(=|['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9_\-/+=]{4,})",
            r"(?i)(HUAWEICLOUD_Password|GD_Secret|PORKBUN_SECRET_API_KEY)"
            r"(=|['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9_\-/+=]{4,})",
        )
        redacted = text
        for pattern in patterns:
            redacted = re.sub(pattern, r"\1\2***", redacted)
        return redacted

    def _reload_nginx(self) -> Tuple[bool, str]:
        """
        校验并重载 nginx，使新证书生效

        :return: (是否成功, 失败原因)
        """
        try:
            check = subprocess.run(
                ["nginx", "-t"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if check.returncode != 0:
                message = f"nginx 配置校验失败：{check.stderr.strip()}"
                logger.error(message)
                return False, message
            subprocess.run(
                ["nginx", "-s", "reload"],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            message = f"重载 nginx 失败：{error}"
            logger.error(message)
            return False, message

        logger.info("nginx 已重载，新证书生效")
        return True, ""

    @staticmethod
    def _normalize_pem(text: str, label: str) -> str:
        """
        规范化 PEM 文本，统一换行并补齐结尾

        :param text: 原始 PEM 文本
        :param label: PEM 标签，如 CERTIFICATE
        :return: 规范化后的 PEM 文本，格式不合法时返回空字符串
        """
        begin = f"-----BEGIN {label}-----"
        end = f"-----END {label}-----"
        if label == "PRIVATE KEY" and begin not in text:
            # 兼容 RSA 私钥的旧式标签
            begin = "-----BEGIN RSA PRIVATE KEY-----"
            end = "-----END RSA PRIVATE KEY-----"
        if begin not in text or end not in text:
            return ""
        normalized = text.replace("\r\n", "\n").strip()
        return normalized + "\n"

    def _verify_certificate_pair(
        self, fullchain: Path, privkey: Path
    ) -> Tuple[bool, str]:
        """
        校验证书与私钥是否匹配且未过期

        :param fullchain: 证书文件路径
        :param privkey: 私钥文件路径
        :return: (是否通过, 失败原因)
        """
        cert_pub = self._openssl_output(
            ["x509", "-in", str(fullchain), "-noout", "-pubkey"]
        )
        key_pub = self._openssl_output(["pkey", "-in", str(privkey), "-pubout"])
        if cert_pub is None or key_pub is None:
            return False, "无法解析证书或私钥内容"
        if cert_pub.strip() != key_pub.strip():
            return False, "证书与私钥不匹配"

        days_left = self._cert_days_left()
        if days_left is None:
            return False, "无法读取证书有效期"
        if days_left <= 0:
            return False, "证书已过期"
        return True, ""

    @staticmethod
    def _openssl_output(args: List[str]) -> Optional[str]:
        """
        调用 openssl 并返回标准输出

        :param args: openssl 子命令与参数
        :return: 标准输出，失败时返回 None
        """
        try:
            result = subprocess.run(
                ["openssl", *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.error(f"openssl 执行失败：{error}")
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _cert_days_left(self) -> Optional[int]:
        """
        读取证书剩余有效天数

        :return: 剩余天数，无法读取时返回 None
        """
        cert_file = Path(self._cert_dir) / "fullchain.pem"
        if not cert_file.is_file():
            return None
        output = self._openssl_output(
            ["x509", "-in", str(cert_file), "-noout", "-enddate"]
        )
        if not output:
            return None
        try:
            # openssl 输出形如 notAfter=Dec 29 13:44:16 2026 GMT
            end_date = output.strip().split("=", 1)[-1]
            expire = datetime.strptime(end_date, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc
            )
            return (expire - datetime.now(timezone.utc)).days
        except ValueError as error:
            logger.error(f"解析证书有效期失败：{error}")
            return None

    def _collect_status(self) -> Dict[str, Any]:
        """
        汇总当前证书状态

        :return: 包含有效性、域名、有效期等字段的状态字典
        """
        cert_file = Path(self._cert_dir) / "fullchain.pem"
        empty: Dict[str, Any] = {
            "valid": False,
            "summary": f"未检测到证书文件：{cert_file}",
            "subject": "",
            "issuer": "",
            "not_before": "",
            "not_after": "",
            "days_left": 0,
            "sans": "",
        }
        if not cert_file.is_file():
            return empty

        output = self._openssl_output([
            "x509",
            "-in",
            str(cert_file),
            "-noout",
            "-subject",
            "-issuer",
            "-dates",
            "-ext",
            "subjectAltName",
        ])
        if not output:
            return {**empty, "summary": "证书文件存在但无法解析"}

        days_left = self._cert_days_left() or 0
        subject = self._extract_field(output, "subject=")
        sans = ", ".join(re.findall(r"DNS:([^,\s]+)", output))
        valid = days_left > 0

        if not valid:
            summary = "证书已过期，请尽快更新"
        elif days_left <= self._warn_days:
            summary = f"证书剩余 {days_left} 天，即将到期"
        else:
            summary = f"证书正常，剩余 {days_left} 天"

        return {
            "valid": valid,
            "summary": summary,
            "subject": subject,
            "issuer": self._extract_field(output, "issuer="),
            "not_before": self._format_cert_time(
                self._extract_field(output, "notBefore=")
            ),
            "not_after": self._format_cert_time(
                self._extract_field(output, "notAfter=")
            ),
            "days_left": days_left,
            "sans": sans,
        }

    @staticmethod
    def _format_cert_time(raw: str) -> str:
        """
        把 openssl 的证书时间转换为大陆习惯格式

        openssl 输出形如 ``Sep 30 13:44:17 2026 GMT``，这里转换为
        ``2026-09-30 21:44:17（北京时间）``，便于国内用户直接对照。

        :param raw: openssl 的原始时间字符串
        :return: 格式化后的时间，无法解析时原样返回
        """
        if not raw:
            return ""
        try:
            parsed = datetime.strptime(raw.strip(), "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            return raw
        # openssl 输出为 UTC，转换为北京时间（UTC+8）更符合国内使用习惯
        beijing = parsed.replace(tzinfo=timezone.utc).astimezone(
            timezone(timedelta(hours=8))
        )
        return beijing.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _extract_field(output: str, prefix: str) -> str:
        """
        从 openssl 输出中提取指定前缀的字段值

        :param output: openssl 输出文本
        :param prefix: 字段前缀，如 subject=
        :return: 字段值，未找到时返回空字符串
        """
        for line in output.splitlines():
            line = line.strip()
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return ""

    @staticmethod
    def _table_row(label: str, value: str) -> Dict[str, Any]:
        """
        构造详情页表格行

        :param label: 行标题
        :param value: 行内容
        :return: Vuetify 表格行结构
        """
        return {
            "component": "tr",
            "content": [
                {
                    "component": "td",
                    "props": {"class": "text-medium-emphasis"},
                    "text": label,
                },
                {"component": "td", "text": value or "-"},
            ],
        }

    def _backup_current(self, cert_dir: Path) -> None:
        """
        备份当前证书文件，便于部署失败时回滚

        :param cert_dir: 证书目录
        """
        backup_dir = cert_dir / ".backup"
        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            for name in ("fullchain.pem", "privkey.pem"):
                source = cert_dir / name
                if source.is_file():
                    shutil.copy2(source, backup_dir / name)
        except OSError as error:
            logger.warning(f"备份现有证书失败，跳过备份：{error}")

    def _restore_backup(self, cert_dir: Path) -> None:
        """
        从备份恢复证书文件

        :param cert_dir: 证书目录
        """
        backup_dir = cert_dir / ".backup"
        if not backup_dir.is_dir():
            return
        try:
            for name in ("fullchain.pem", "privkey.pem"):
                source = backup_dir / name
                if source.is_file():
                    shutil.copy2(source, cert_dir / name)
            logger.info("已从备份恢复原有证书")
        except OSError as error:
            logger.error(f"恢复备份证书失败：{error}")

    def _notify_failure(self, stage: str, message: str) -> None:
        """
        记录失败日志并按配置发送通知

        :param stage: 失败阶段，用于通知标题
        :param message: 失败原因
        """
        logger.error(f"证书管理失败：{message}")
        if self._notify:
            self.post_message(
                mtype=MessageType.Plugin,
                title=f"【证书管理】{stage}",
                text=message,
            )