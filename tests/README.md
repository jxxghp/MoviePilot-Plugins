# 插件仓单测

测试统一放在仓库根 `tests/` 下，**不放在插件目录内**——插件的本地同步与市场下发按
整目录拷贝（`shutil.copytree`），插件目录内的测试会被一并下发到运行时副本。

## 目录结构

```
tests/
├─ _bootstrap.py   共享引导：隔离 CONFIG_DIR + 注入后端/插件目录到 sys.path
├─ conftest.py     pytest 引导：收集前隔离 CONFIG_DIR，按目录自动打 v1/v2 marker
├─ v2/             v2 插件（plugins.v2/）单测
└─ v1/             v1 插件（plugins/）单测（当前预留骨架）
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
会相互覆盖。后端依赖（`app.*`）由 `_bootstrap.py` 注入 `sys.path`，并隔离临时 `CONFIG_DIR`
且建表；主程序 `app/testing` 的共享 harness（`stub_modules` 等）在 bootstrap 后可直接复用。

## 提 PR / push 前

先本地 `python tests/run.py` 跑**全量并确认通过**，再 push / 提 PR。

## 新增用例

1. 放到对应代际目录（`tests/v2/` 或 `tests/v1/`），文件名 `test_*.py`；
2. 顶部调用 `prepare_v2_backend()` / `prepare_v1_backend()`（见 `_bootstrap.py`），
   必须早于首个 `import app.*` 或插件包导入；
3. 优先用 `object.__new__` 绕过插件 `__init__`，只测纯逻辑方法，避免依赖完整运行时。
