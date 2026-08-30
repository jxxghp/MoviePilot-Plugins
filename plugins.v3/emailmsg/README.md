# 邮箱通知

支持通过 SMTP 发送邮件通知，收件人根据通知发送范围设置（all/user/admin）从用户管理邮箱中获取，邮箱为空时跳过。

## 功能说明

- 通过 SMTP 服务器发送邮件通知。
- 收件人根据通知发送范围设置（all/user/admin）从用户管理邮箱中获取。
- 邮箱为空时跳过该用户。
- 支持按消息类型（Download/Organize/Subscribe/SiteMessage/MediaServer/Manual/Plugin/Agent/Other）过滤。

## 配置说明

| 配置项 | 说明 |
|--------|------|
| 启用插件 | 是否启用本插件 |
| SMTP服务器 | 如 `smtp.qq.com` |
| SMTP端口 | 如 `465` |
| 发件人邮箱 | 发件邮箱地址 |
| SMTP授权码/密码 | 邮箱授权码（多数邮箱需使用授权码而非登录密码） |
| 使用SSL加密 | 是否使用 SSL 加密连接 |
| 消息类型 | 需要发送的消息类型 |

## 收件人逻辑

收件人根据通知发送范围设置（all/user/admin）从用户管理邮箱中获取：

- `admin`：发送给管理员（`SUPERUSER`）邮箱。
- `user`：发送给消息关联的用户邮箱。
- `all`：发送给所有用户邮箱。

邮箱为空时跳过该用户。
