# WxPusher 消息通知

将 MoviePilot 的通知（下载、入库、订阅、系统告警等）推送到 **微信** 及 WxPusher 全平台 App（Android / iOS / 鸿蒙 / 桌面）。

[WxPusher](https://wxpusher.zjiecode.com/?utm_source=moviepilot) 是永久免费的实时消息推送服务，与 Server酱 / PushPlus / Bark 同类，免费额度更高（2000 条/天/用户），并支持一对多群发（topic）。

## 两种推送方式

| 方式 | 需要什么 | 适合 |
|---|---|---|
| **极简推送（SPT）** | 一个或多个 `SPT`（下载 App 扫码即得，无需注册） | 「发给我自己」，最低接入成本（推荐） |
| **标准推送（AppToken）** | `AppToken` + 接收者 `UID` 或 `主题ID` | 需要管理接收者 / 群发给一批人 |

## 配置

1. **启用插件**：打开「启用插件」。
2. **推送方式**：
   - 极简推送：下载 [WxPusher App](https://wxpusher.zjiecode.com/download/?utm_source=moviepilot) 或在配置页扫描二维码，获取你的 **SPT**（形如 `SPT_xxx`），填入「SPT」。可填写多个，用英文逗号分隔，**单次最多 10 个**，超过将无法保存生效。
   - 标准推送：微信扫码登录[管理后台](https://wxpusher.zjiecode.com/admin/?utm_source=moviepilot)新建应用，拿到 **AppToken**（形如 `AT_xxx`）与关注用户的 **UID**（形如 `UID_xxx`），分别填入；群发可填「主题 ID」。
3. **消息类型**：勾选需要推送的通知类型；不勾选则推送全部。
4. 勾选「发送测试消息」后点「保存」，微信/App 收到测试消息即接入成功。

> 消息以 HTML 格式发送（内容格式固定，无需选择）。WxPusher 为托管服务，服务地址固定为官方地址，因此配置项中不再提供「服务地址」字段。

> ⚠️ SPT / AppToken 相当于「收件地址 + 密钥」，请妥善保管，不要泄漏或提交到公开仓库。

更多用法见[官方文档](https://wxpusher.zjiecode.com/docs/?utm_source=moviepilot)。
