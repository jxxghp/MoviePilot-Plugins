# Repository Guidelines

MoviePilot 官方插件市场与插件源码仓库，默认分支为 `main`。新插件开发与当前主线适配统一面向 V3（`plugins.v3/` 与 `package.v3.json`）。

## 文档导航

| 主题 | 文档 |
| --- | --- |
| 仓库职责、目录结构、代际索引与发布流程 | [docs/Repository_Guide.md](docs/Repository_Guide.md) |
| V3 插件从零开发指南 | [docs/Plugin_Development.md](docs/Plugin_Development.md) |
| V2 升级 V3 与接口响应适配 | [docs/V3_Plugin_Adaptation.md](docs/V3_Plugin_Adaptation.md)、[docs/V3_API_Response_Adaptation.md](docs/V3_API_Response_Adaptation.md) |
| 常见能力扩展示例（通知、识别、存储、工作流、Agent 等） | [docs/FAQ.md](docs/FAQ.md) 及 `docs/faq/` |
| 插件单元测试目录、宿主引导与跨平台依赖门禁 | [tests/README.md](tests/README.md) |

## 目录、元数据与文档约定

- 一个插件对应一个与插件类名全小写一致的目录（如 `class AutoSignIn` 对应 `plugins.v3/autosignin/`），主类定义在 `__init__.py` 中。
- 插件类属性（`plugin_name`、`plugin_desc`、`plugin_version` 等）必须与对应代际索引（`package.v3.json`、`package.v2.json`、`package.json`）保持同步，图标放入 `icons/`。存在 V3 专用实现时，旧索引同名条目按需声明 `"v3": false`（或按最低宿主版本保留兼容回退，详见 `docs/Repository_Guide.md`）。
- 新 V3 插件优先使用 `app.sdk` 公开契约，不新增宿主旧兼容路径导入、跨插件导入、`sys.path` 改写或宿主 `SessionFactory` 直连（由 `scripts/check_v3_imports.py` 守门）。
- 插件配置模型、公开接口与关键生命周期逻辑补充简明中文注释。编写或更新插件 `README.md` 时须回读源码，使配置项中文名、表单默认值及可选枚举与 `get_form` 完全一致，不在正文暴露源码行号或内部方法名。
- V3 插件声明额外 Python 依赖使用插件目录下的 `pyproject.toml`（`[project].dependencies`），不提交插件级锁文件。

## 测试与提交前检查

- **测试隔离位置** 所有单元测试统一放在仓库根 `tests/<v1|v2|v3>/<plugin_id>/test_*.py`，严禁放入插件源码目录内（插件按整目录 `copytree` 下发，目录内测试会被带入运行时副本）。
- **测试写法与导入** 统一使用 pytest 风格与 `assert`（不新增 `unittest.TestCase` 执行入口），通过生产命名空间 `app.plugins.<plugin_id>` 导入插件以保证单一模块身份，外部网络与宿主服务一律使用 mock 或共享测试桩隔离。新增 V3 插件必须同步提交 `tests/v3/<plugin_id>/test_*.py`。
- **提交 PR 前本地验证**
  - 校验索引 JSON 与插件版本门禁 `python .github/scripts/check_plugin_versions.py package.json package.v2.json package.v3.json`
  - 校验 V3 插件导入边界 `python scripts/check_v3_imports.py`（需存在同级 `MoviePilot` V3 后端目录或设置 `MOVIEPILOT_BACKEND_PATH`）
  - 涉及模块联邦前端产物时运行 `python .github/scripts/check_federation_css.py` 并确认已提交构建后的 `dist/assets/`
  - 新增插件时运行 `python scripts/check_new_plugin_tests.py --base-ref origin/main`
  - 修改 V3 插件 `pyproject.toml` 或 `package.v3.json` 时按目标平台运行 `uv run --no-project --python 3.14 python scripts/check_v3_dependency_install.py --platform <platform>`（校验自由线程兼容与无编译工具链约束时加 `--abi cp314t`，`<platform>` 取 `linux-x64`、`linux-arm64`、`windows-x64`、`macos-x64`、`macos-arm64`）
  - 配合同级 V3 后端 Python 环境（设置 `MOVIEPILOT_BACKEND_PATH`）运行受影响插件测试或全量 `python tests/run.py`（不同代同名插件分独立 pytest 会话执行）
