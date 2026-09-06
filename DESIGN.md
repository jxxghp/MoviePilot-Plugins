# MediaGovernor 界面合同

### UI decision: v5 逐作品对账台

- 用户与目标：用户只需要看到已经证明的整理失败与假成功，在歧义时确认一次作品身份，并在逐文件预览后安全重建。
- 信息层级：首页依次显示后台任务、四个摘要数字、已经证明的问题、需要确认、本轮没读完；“完整重建”只在高级操作中出现。
- 数据与权限：浏览器只调用六类 bearer API，不扫描目录、不保存地图、不调用 AI 或 MoviePilot 整理接口；私有路径只在用户打开单项详情后返回。
- 状态合同：覆盖 idle、running、completed、failed、cancelled、empty、identity confirmation、read error、preview expired 和最终写入确认。读取失败不得显示成正常。
- 技术选择：沿用 Vue 3 和现有联邦构建，不增加组件库、外部资产、账号或动效依赖。
- 响应式与无障碍：760px 以下改为单列；按钮使用原生禁用态，任务状态使用 `aria-live`，弹层声明 dialog，遵守 `prefers-reduced-motion`。
- 性能预算：页面只轮询小型状态和结论；首次完整扫描由后端持久任务完成，日常无变化检查不得调用 AI 或生成全库预览。
- 安全与回滚：修复必须重新读取、生成带 token 的冻结预览并二次确认；旧 `media_map.json` 保留但不采信，回滚到 4.6 不需要迁移数据库。
- 验收：真实原始回放、API/任务生命周期、刷新续跑、Vue 构建、浏览器交互、NAS 只读 shadow 和隔离目录重建均需绑定同一候选 SHA。
