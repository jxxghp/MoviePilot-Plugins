# 插件仓单测

测试统一放在仓库根 `tests/` 下，**不放在插件目录内**——插件的本地同步与市场下发按
整目录拷贝（`shutil.copytree`），插件目录内的测试会被一并下发到运行时副本。

## 目录结构

```
tests/
├─ _bootstrap.py   薄壳 shim：定位同级 MoviePilot 后端入 sys.path，引导逻辑委托主程序 app/testing.bootstrap
├─ conftest.py     pytest 引导：按本次运行目标选择 v1/v2 插件环境并注册网络守卫
├─ v2/             v2 插件（plugins.v2/）单测；每个插件按插件 ID 建子目录
│  └─ agenttokens/
└─ v1/             v1 插件（plugins/）单测；每个插件按插件 ID 建子目录
```

## 运行

需要 MoviePilot 后端置于插件仓**同级目录**（或设环境变量 `MOVIEPILOT_BACKEND_PATH`），
并使用带后端依赖的解释器（如 `<workspace>/.venv/bin/python`）。

```bash
# 全量（推荐入口）：v1/v2 各自独立会话依次跑，命令行参数透传给 pytest
<workspace>/.venv/bin/python tests/run.py

# 也可按代单独跑（v1/v2 必须分会话，勿混跑）
<workspace>/.venv/bin/python -m pytest tests/v2
<workspace>/.venv/bin/python -m pytest tests/v1
```

`tests/run.py` 把 v1/v2 放在独立子进程依次运行、无用例的代自动跳过——两代存在同名
插件包（如 `brushflowlowfreq`、`torrentclassifier`），同一解释器进程无法同时加载、混跑
会相互覆盖。隔离 `CONFIG_DIR`、建表、`app.helper.sites` 垫片、插件目录注入、v1/v2 marker、
autouse 网络守卫等引导逻辑统一在主程序 `app/testing`（`bootstrap` / `network_guard`）维护一处；
本仓 `tests/_bootstrap.py` 仅是「定位后端入 `sys.path`」的薄壳 shim，故后端需为含 `app/testing/bootstrap`
的较新 MoviePilot。共享 harness（`stub_modules` 等）在 bootstrap 后可直接复用。

## 提 PR / push 前

先本地 `python tests/run.py` 跑**全量并确认通过**，再 push / 提 PR。

## 新增用例

1. 放到对应代际的插件独立目录：`tests/<v1|v2>/<plugin_id>/`，例如
   `tests/v2/agenttokens/`；所有插件都按插件 ID 建目录，不把用例文件直接平铺在
   `tests/v1/` 或 `tests/v2/` 下；文件名使用 `test_*.py`，在插件独立目录内不再重复插件名前缀；
2. 直接导入 `app.*` 与对应代际插件包；根 conftest 会按本次运行目标在用例导入前完成后端与插件目录注入；
3. 使用 pytest 风格编写测试：普通函数或测试类均可，断言使用 `assert`；不要新增
   `unittest.TestCase`、`unittest.main()` 或 `if __name__ == "__main__"` 入口；
4. `unittest.mock` 可以继续作为 mock 工具使用；“不用 unittest”指测试组织与执行入口不使用
   `unittest` runner；
5. 优先用 `object.__new__` 绕过插件 `__init__`，只测纯逻辑方法，避免依赖完整运行时。
