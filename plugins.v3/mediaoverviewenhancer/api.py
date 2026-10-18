"""插件 API 路由定义：全部使用 Bearer 认证，供联邦前端调用。"""

from __future__ import annotations

from typing import Any, Dict, List


def build_api_routes(owner: Any) -> List[Dict[str, Any]]:
    """构建插件 API 路由清单。"""
    return [
        {
            "path": "/status",
            "endpoint": owner.engine_status,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "读取影视简介增强状态与统计",
        },
        {
            "path": "/config",
            "endpoint": owner.engine_config,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "读取插件当前配置",
        },
        {
            "path": "/servers",
            "endpoint": owner.engine_servers,
            "methods": ["GET"],
            "auth": "bear",
            "summary": "读取可用 Emby 服务器与连接状态",
        },
        {
            "path": "/preview",
            "endpoint": owner.engine_preview,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "试跑：列出待处理条目与处理方式",
        },
        {
            "path": "/run",
            "endpoint": owner.engine_run,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "启动简介补全任务",
        },
        {
            "path": "/cancel",
            "endpoint": owner.engine_cancel,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "停止当前任务",
        },
        {
            "path": "/clear",
            "endpoint": owner.engine_clear,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "清空处理记录",
        },
    ]
