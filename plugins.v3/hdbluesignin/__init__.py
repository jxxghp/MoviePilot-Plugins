"""MoviePilot V3 adapter using the stable host SDK."""
from app.plugins import _PluginBase
from app.schemas.types import NotificationType
from app.sdk.logging import logger

from .core import HDBluePlugin


class HDBlueSignin(HDBluePlugin, _PluginBase):
    plugin_name = "蓝影论坛签到"
    plugin_desc = "使用专用密钥自动签到蓝影论坛，支持随机错峰、结果通知与签到记录。"
    plugin_icon = "https://raw.githubusercontent.com/wzxcom/MoviePilot-Plugins/main/icons/hdblue-logo-004699311fe1.png"
    plugin_version = "2.0.2"
    plugin_author = "wzxcom"
    author_url = "https://github.com/wzxcom"
    plugin_config_prefix = "hdbluesignin_"
    plugin_order = 50
    auth_level = 1
    host_logger = logger
    notification_type = NotificationType.SiteMessage
