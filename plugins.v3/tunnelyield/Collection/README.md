# Tunnel API 采集端

配合 MoviePilot 的 TunnelYield 插件使用，采集 EasyTier、WireGuard 节点状态或 Jellyfin 播放状态，由 MP 执行暂停上传任务／全局限速及恢复。

支持 OpenWrt / ImmortalWrt、Ubuntu、Debian。采集端不直接操作下载器，不负责安装隧道软件或 Jellyfin。

## 文件作用

```text
TunnelYield/
├── tunnel_api.py
├── Tunnel_API_install.sh
├── installer_ui.py
├── readme.md
└── providers/
    ├── __init__.py
    ├── easytier.py
    ├── jellyfin.py
    └── wireguard.py
```

| 文件 | 作用 |
|---|---|
| `tunnel_api.py` | 主程序：加载配置、调度采集、汇总快照、版本管理、推送／重试／保活及查询接口。 |
| `Tunnel_API_install.sh` | 交互安装与更新，生成配置和系统服务，设置开机启动。 |
| `installer_ui.py` | 安装器的参数输入、密钥隐藏、退格编辑和完成摘要，安装时必须与主程序同目录。 |
| `providers/__init__.py` | 驱动包初始化文件，不能遗漏，内容可为空。 |
| `providers/easytier.py` | 读取 EasyTier 节点状态。 |
| `providers/wireguard.py` | 按 WireGuard 最近握手时间判断节点状态。 |
| `providers/jellyfin.py` | 查询 Jellyfin 播放会话，支持用户、暂停策略及 IP／网段排除。 |

保持目录和文件名不变，正式发布包建议保留全部内置驱动。测试文件、测试结果、开发文档和 `__pycache__` 不影响日常运行，可不随精简包发布。

## 安装与更新

将完整目录上传到采集设备，在有交互终端的会话中进入目录，以 root 执行：

```sh
sh ./Tunnel_API_install.sh
```

Ubuntu / Debian 可使用：

```sh
sudo sh ./Tunnel_API_install.sh
```

按提示选择来源（例如 `easytier,jellyfin`）、填写连接信息及通信密钥。安装器逐源试采，至少一项成功才允许继续；输入 `yes` 后才部署和启动服务。最后按摘要填写 MP 插件。

- 首次安装：仅启用试采成功的来源。
- 更新：保留原有参数；需要修改驱动参数时选择重新填写。原启用来源暂时试采失败时保留重试，新增失败来源不启用；全部失败则取消本次安装／更新。
- 更新方式：用新版文件更新源码目录，再运行同一脚本。普通兼容更新无需停用 MP，安装器会重启采集服务。
- 普通输入和密钥输入支持退格；回车保留默认值，`Ctrl-U` 清空当前输入。Provider 可选字段支持 `!clear` 清空，JSON 字段也可填写 `{}` 或 `[]`。
- 地址填写纯 URL，不要粘贴 `[地址](地址)` 形式；密钥使用对应服务创建的值，注意区分 Jellyfin API Key、MP API_TOKEN 和采集端通信密钥。

## MoviePilot 侧配置

| 工作方式 | 采集端选择 | MP 侧填写 |
|---|---|---|
| Webhook（推荐） | `webhook` | 选择 Webhook 推送，填写相同通信密钥、下载器及监控主机。采集端已保活时，主动心跳可设 `0`；API 地址为可选项。 |
| 轮询 | `poll` | 选择轮询，填写采集端 API 地址、相同通信密钥、检测周期、下载器及监控主机。 |

Jellyfin 默认虚拟监控主机名为 `jellyfin-playback`。监控名单不要填写采集端本机节点；遇到重名时使用安装摘要／查询结果给出的最终名称，必要时手动调整。

Jellyfin 排除 IP／网段可填写：

```text
172.16.8.0/24,192.168.1.50
```

配置字段为 `JELLYFIN_EXCLUDE_IPS`，空列表不排除。排除仅代表该会话不触发让位；其他符合条件的播放或隧道节点仍可触发让位。反向代理环境请核对 Jellyfin 返回的客户端地址。

## 安装后生成的文件

| 项目 | OpenWrt / ImmortalWrt | Ubuntu / Debian |
|---|---|---|
| 程序、驱动与配置目录 | `/etc/tunnel-api/` | `/opt/tunnel-api/` |
| 用户配置 | `/etc/tunnel-api/config.json` | `/opt/tunnel-api/config.json` |
| 版本状态 | `/etc/tunnel-api/tunnel_api_state.json` | `/opt/tunnel-api/tunnel_api_state.json` |
| 系统服务文件 | `/etc/init.d/tunnel-api` | `/etc/systemd/system/tunnel-api.service` |

- `config.json`：保存驱动、地址、密钥和周期等配置，不要公开真实文件。
- `tunnel_api_state.json`：运行时维护快照版本号，更新时保留，不要删除、清空或用旧备份覆盖。
- 更新时安装目录下会生成 `backup-*` 备份目录，供异常时人工恢复；不代表已实现自动回滚。
- 当前可用性优先版不再使用 `provider_state.json`，不需要随发布包提供。

源码目录与安装目录不同。只修改上传的源码文件，不会立即改变正在运行的服务；需重新执行安装器部署。

## 服务操作

### OpenWrt / ImmortalWrt

```sh
/etc/init.d/tunnel-api status    # 查看状态
/etc/init.d/tunnel-api restart   # 重启，手动修改已安装配置后执行
/etc/init.d/tunnel-api stop      # 停止
/etc/init.d/tunnel-api start     # 启动
/etc/init.d/tunnel-api enable    # 开机启动
/etc/init.d/tunnel-api disable   # 取消开机启动
logread -e tunnel                # 查看日志
```

### Ubuntu / Debian

```sh
systemctl status tunnel-api
systemctl restart tunnel-api
systemctl stop tunnel-api
systemctl start tunnel-api
systemctl enable tunnel-api
systemctl disable tunnel-api
journalctl -u tunnel-api -f
```

手动修改已安装的 `config.json` 后重启服务；只取消开机启动不会立即停止当前进程。

## 注意事项

- 本版只发布本轮成功来源，失败来源临时剔除、下一轮继续尝试；恢复后自动加入。短暂 API 故障可能造成下载器解除让位后再次让位，这是本版接受的取舍。
- 全部来源失败时不发布空快照，MP 按自身判定有效期和失联释放配置处理。停止采集服务不等于立即恢复下载器。
- 不要向同一个 MoviePilot 插件同时运行两份独立版本号的采集端，需要接收多个采集端时，在MoviePilot启用插件分身功能；不要把隧道采集和 Jellyfin 分成独立发布者互相覆盖。
- HTTP 会明文传输认证信息，仅用于可信网络；安装器不会自动开放防火墙端口。
- 不公开密钥、个人配置或运行状态文件；发布包仅提供占位示例配置。
