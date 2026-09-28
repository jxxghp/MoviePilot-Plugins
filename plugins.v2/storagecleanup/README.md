# 存储清理

MoviePilot V2 的 NAS 清理台插件。插件通过一个带令牌的 PiNAS 清理控制服务读取资源快照、生成清理计划并执行三档安全操作。

## 使用前提

- MoviePilot V2 `>= 2.14.6`
- NAS 上已部署 PiNAS storage-cleanup 控制服务
- MoviePilot 容器能访问控制服务网关，并能只读访问控制令牌文件

安装后先在插件的“设置”页填写：

1. 清理台网关地址
2. MoviePilot 容器内的控制令牌文件路径
3. NAS 拓扑、qBittorrent、Jellyfin/MoviePilot 数据库、允许扫描根目录和同盘隔离目录

保存配置只做结构校验与只读路径探测。探测未通过时资源清单和清理操作保持锁定。

控制令牌只由 MoviePilot 后端读取并放入服务端请求头，不会进入 Vue 页面、浏览器响应、仓库或日志。
