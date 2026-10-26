"""CMS通知（CMSNotify）的市场索引与插件声明一致性测试。

这里刻意不导入插件模块：插件在运行时依赖宿主 ``app.sdk`` 与第三方包，
而这些依赖只在完整 MoviePilot 环境中可用。市场收录、版本门禁真正关心的是
「索引里的元数据」和「插件源码里的声明」是否一致，用 AST 静态读取即可覆盖。
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
PLUGIN_ID = "CMSNotify"
PLUGIN_DIR = REPO_ROOT / "plugins.v3" / "cmsnotify"
INIT_FILE = PLUGIN_DIR / "__init__.py"
PACKAGE_FILE = REPO_ROOT / "package.v3.json"


def _plugin_class_attrs() -> dict[str, ast.expr]:
    """从插件主类读取类级属性赋值节点，供元数据断言复用。"""
    tree = ast.parse(INIT_FILE.read_text(encoding="utf-8"), filename=str(INIT_FILE))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == PLUGIN_ID:
            return {
                target.id: item.value
                for item in node.body
                if isinstance(item, ast.Assign)
                for target in item.targets
                if isinstance(target, ast.Name)
            }
    raise AssertionError(f"未在 {INIT_FILE} 中找到插件主类 {PLUGIN_ID}")


def _literal(attrs: dict[str, ast.expr], name: str) -> str:
    """读取类级字符串字面量属性，缺失或非字面量时断言失败。"""
    node = attrs.get(name)
    assert node is not None, f"插件主类缺少类级属性 {name}"
    assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
        f"插件类级属性 {name} 必须是字符串字面量，版本门禁与市场索引都直接读取它"
    )
    return node.value


def test_market_index_entry_matches_plugin_declaration():
    """索引条目必须与插件源码自报的名称、版本、作者完全一致。"""
    attrs = _plugin_class_attrs()
    package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
    meta = package[PLUGIN_ID]

    assert meta["name"] == _literal(attrs, "plugin_name")
    assert meta["version"] == _literal(attrs, "plugin_version")
    assert meta["author"] == _literal(attrs, "plugin_author")
    assert meta["icon"] == _literal(attrs, "plugin_icon")


def test_market_index_history_tops_with_current_version():
    """更新日志首项必须是当前版本，且整体按语义版本降序。"""
    package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
    meta = package[PLUGIN_ID]
    version = meta["version"]

    assert list(meta["history"])[0] == f"v{version}", (
        "history 首项必须与当前版本一致，否则市场会继续展示旧版本说明"
    )
    numeric = [tuple(int(part) for part in key.lstrip("v").split(".")) for key in meta["history"]]
    assert numeric == sorted(numeric, reverse=True), "history 必须按语义版本降序排列"


def test_market_index_targets_v3_only():
    """插件未做 V2 适配，索引必须只声明 V3 可用的系统版本范围。"""
    package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
    meta = package[PLUGIN_ID]

    assert meta["system_version"].startswith(">=3"), "V3 专用插件的 system_version 应限定在 3.x"
    assert meta.get("v2") is not True, "未适配 V2 的插件不能在索引中声明兼容 V2"


def test_market_index_has_no_v2_package_entry():
    """本插件只提供 V3 版本，不应出现在 V1/V2 索引中造成重复收录。"""
    for legacy in ("package.json", "package.v2.json"):
        legacy_file = REPO_ROOT / legacy
        if not legacy_file.is_file():
            continue
        legacy_package = json.loads(legacy_file.read_text(encoding="utf-8"))
        assert PLUGIN_ID not in legacy_package, (
            f"{legacy} 中不应包含 {PLUGIN_ID}，该插件仅适配 V3"
        )


def test_pyproject_dependencies_match_requirements():
    """pyproject 与 requirements 的第三方依赖必须一致，避免两条安装路径装出不同环境。"""
    manifest = tomllib.loads((PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    declared = sorted(name.split(">")[0].split("=")[0].strip() for name in manifest["project"]["dependencies"])
    required = sorted(
        line.split(">")[0].split("=")[0].strip()
        for line in (PLUGIN_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )

    assert manifest["project"]["name"] == PLUGIN_DIR.name
    assert declared == required, f"pyproject={declared} 与 requirements={required} 不一致"
