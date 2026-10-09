# 插件仓单测

测试统一放在仓库根 `tests/` 下，**不放在插件目录内**——插件的本地同步与市场下发按
整目录拷贝（`shutil.copytree`），插件目录内的测试会被一并下发到运行时副本。

## 目录结构

```
tests/
├─ _bootstrap.py   薄壳 shim：定位同级 MoviePilot 后端入 sys.path，引导逻辑委托主程序 app/testing.bootstrap
├─ conftest.py     pytest 引导：按本次运行目标选择 v1/v2/v3 插件环境并注册网络守卫
├─ v3/             v3 插件（plugins.v3/）单测；每个插件按插件 ID 建子目录
├─ v2/             v2 插件（plugins.v2/）单测；每个插件按插件 ID 建子目录
│  └─ agenttokens/
└─ v1/             v1 插件（plugins/）单测；每个插件按插件 ID 建子目录
```

## 运行

需要 MoviePilot 后端置于插件仓**同级目录**（或设环境变量 `MOVIEPILOT_BACKEND_PATH`），
并使用带后端依赖的解释器（如 `<workspace>/.venv/bin/python`）。

```bash
# 当前 V3 运行环境回归：CI 工具、V3 专用实现、仍兼容 V3 的 V2 实现分会话运行
<workspace>/.venv/bin/python tests/run.py

# 指定代际时仍须独立运行，勿与其他代混跑
<workspace>/.venv/bin/python -m pytest tests/v3
<workspace>/.venv/bin/python -m pytest tests/v2
<workspace>/.venv/bin/python -m pytest tests/v1
```

`tests/run.py` 默认验证当前 V3 运行环境：CI 工具、V3 专用实现和仍兼容 V3 的 V2
实现分别在独立子进程运行；
`package.v2.json` 中显式声明 `v3: false` 的历史实现不进入 V3 主程序回归。不同代存在同名
插件包，同一解释器进程无法同时加载。隔离 `CONFIG_DIR`、建表、`app.helper.sites` 垫片、
插件目录注入和网络守卫等引导逻辑统一在主程序 `app/testing` 维护一处；
本仓 `tests/_bootstrap.py` 仅是「定位后端入 `sys.path`」的薄壳 shim，故后端需为含 `app/testing/bootstrap`
的较新 MoviePilot。共享 harness（`stub_modules` 等）在 bootstrap 后可直接复用。

测试必须通过生产命名空间 `app.plugins.<plugin_id>` 导入插件及子模块，不要把插件目录加入
`sys.path` 后使用顶层包名。单一模块身份可避免同一源码被重复执行，并防止事件订阅、类状态
或插件实例因双重导入而重复创建。

V1/V2 历史实现可能依赖对应宿主版本的运行时合同。需要维护完整历史行为时，应使用匹配的
MoviePilot 环境；默认 V3 回归只承诺覆盖仍声明兼容 V3 的 V2 测试。

## 提 PR / push 前

提交前运行受影响插件或代际的测试，以及版本、新增插件等适用门禁。涉及跨插件共享脚手架、测试基础
设施、跨代兼容索引、多插件公共行为，或受影响范围无法由局部测试充分覆盖时，运行
`python tests/run.py` 完成本地全量。验证说明应准确标注执行范围；上游 `Plugin Gate` 继续运行完整
回归。

新增 V3 插件必须同时增加 `tests/v3/<plugin_id>/test_*.py`；V1/V2 历史实现仍可维护和
发版，不受这个新增插件测试门禁约束。

## 依赖清单

V3 插件有额外依赖时使用 `pyproject.toml` 的 `[project].dependencies`，不提交插件级锁文件。
PR 修改 V3 依赖清单或依赖门禁本身时，CI 会在 Python 3.14 的 Linux x64/arm64、Windows x64、
macOS Intel/ARM runner 中创建隔离环境，按宿主的 `uv pip install -r pyproject.toml` 语义真实安装
并执行 `uv pip check`。

普通清单默认覆盖五个平台。插件仅支持其中一部分平台时，在清单中声明安装门禁范围：

```toml
[tool.moviepilot.dependency-gate]
platforms = ["linux-x64"]
```

本地可按目标平台执行同一入口：

```bash
uv run --no-project --python 3.14 python scripts/check_v3_dependency_install.py \
  --python 3.14 --platform macos-arm64
```

## 新增用例

1. 放到对应代际的插件独立目录：`tests/<v1|v2|v3>/<plugin_id>/`，例如
   `tests/v2/agenttokens/`；所有插件都按插件 ID 建目录，不把用例文件直接平铺在
   `tests/v1/` 或 `tests/v2/` 下；文件名使用 `test_*.py`，在插件独立目录内不再重复插件名前缀；
2. 使用 `app.plugins.<plugin_id>` 生产路径导入插件；根 conftest 会按本次运行目标在用例导入前完成后端与插件目录注入；
3. 使用 pytest 风格编写测试：普通函数或测试类均可，断言使用 `assert`；不要新增
   `unittest.TestCase`、`unittest.main()` 或 `if __name__ == "__main__"` 入口；
4. `unittest.mock` 可以继续作为 mock 工具使用；“不用 unittest”指测试组织与执行入口不使用
   `unittest` runner；
5. 优先用 `object.__new__` 绕过插件 `__init__`，只测纯逻辑方法，避免依赖完整运行时。
