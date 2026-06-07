# OidcAuth 更新日志

## v0.3.1

### 后端 `__init__.py`（Code Review 修复）

- 修复回调事件类型不匹配：绑定流程错误时 `event_type` 动态设为 `oidcauth_bind_callback`，避免前端仅显示通用提示
- 移除解绑方法中多余的 `_ensure_login_ready()` 检查，允许 OIDC 关闭状态下正常解绑

---

## v0.3.0

### 前端 `AppPage.vue`（完全重构）

- **双栏布局重构**：废弃旧版单页卡片，改为左侧特性介绍 + 右侧绑定状态的现代化双栏布局
- **动态背景装饰**：渐变光斑、浮动光点动画组成的沉浸式背景层
- **三步绑定可视化**：绑定流程拆分为 3 步（跳转 IdP → 完成认证 → 自动绑定），每步支持 pending / loading / done / error 四种状态 + 动态图标
- **深色/浅色主题自适应**：`MutationObserver` 监听 Vuetify 主题变化，自动切换完整深/浅配色方案
- **postMessage 通信增强**：弹窗绑定改用 `postMessage` 事件驱动 + 1s 轮询兜底，替换旧版纯轮询方式
- **已绑定详情卡片**：展示绑定用户、OIDC Subject（脱敏截断）、认证状态（绿色"有效"标识）+ 用户名备注
- **解绑确认流程**：新增两步确认（点击解绑 → 确认/取消），防止误操作
- **功能开关感知**：OIDC 关闭时显式展示黄色警告条 + 绑定/解绑按钮自动 disabled
- **四个特性介绍卡片**：左侧新增单点登录、免密认证、统一账号、安全可靠四张彩色特性卡片
- **底部信息栏**：版权提示 + 插件版本号展示

### 后端 `__init__.py`

- 图标由 `Authelia_A.png` 改为 `Oidcauth_A.png`
- 版本号 `0.2.0` → `0.3.0`

---

## v0.2.0

### 后端 `__init__.py`

- **修复 PROXY_HOST 为空时崩溃**：所有 `proxy=settings.PROXY_HOST` 改为 `proxy=settings.PROXY_HOST or None`（3 处）
- **回调 HTML 美化**：从极简白屏升级为带关闭按钮 ✕、居中排版、200ms 延迟自动关闭的友好页面
- **补充配置表单使用指南**：`status()` 接口新增 `redirect_uri`、`masked_sub` 等字段

### 前端 `AuthPage.vue`

- **挂载后自动跳转 OIDC 授权**：`onMounted` 自动调用 `checkAndStart()`，免去手动点击按钮
- **加载动画**：新增 `checking` 状态 + `VProgressCircular` 旋转指示器
- **错误重试机制**：错误时展示"重试"按钮，点击可重新发起认证
- **增强错误信息**：新增"管理员未启用 OIDC 认证"、"无法连接到认证服务"等精确提示
- **`messageReceived` 防误判**：弹窗关闭时检查是否已收到 postMessage，避免误报"认证窗口已关闭"

---

## v0.1.0

### 首次发布

- **OIDC 授权码流程登录**：支持标准 OIDC Authorization Code Flow
- **账号绑定/解绑**：已登录用户可绑定 OIDC 身份，支持解绑
- **Provider 配置**：支持任意兼容标准 OIDC 协议的服务（Authelia、Keycloak、Casdoor 等）
- **联邦认证界面**：基于 Vue 3 + Vite Federation 的前端组件
- **登录票据认证桥接**：`create_plugin_auth_ticket` 与 MoviePilot 认证系统集成
- **图标**：`plugin_icon` 为 `Authelia_A.png`
- **作者信息**：`plugin_author` 为 `ui-beam-9,jxxghp`
