"""AutoSubv2 V3 插件目录与导入合同测试。"""

from __future__ import annotations

import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATH = REPO_ROOT / "plugins.v3/autosubv2/__init__.py"


def _imports(source: str) -> list[ast.ImportFrom]:
    """读取插件源码中的 from-import 节点，供导入边界断言使用。"""
    return [
        node
        for node in ast.walk(ast.parse(source, filename=str(SOURCE_PATH)))
        if isinstance(node, ast.ImportFrom)
    ]


def test_v3_metadata_and_source_are_generation_isolated() -> None:
    """V3 索引必须指向 3.1.0 副本，旧命名空间不得进入 V3 实现。"""
    metadata = json.loads((REPO_ROOT / "package.v3.json").read_text(encoding="utf-8"))["AutoSubv2"]
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert metadata["version"] == "3.1.0"
    assert metadata["system_version"] == ">=3.0.0"
    assert metadata["history"]["v3.1.0"]
    assert "plugin_version = \"3.1.0\"" in source

    imports = _imports(source)
    imported_modules = {node.module or "" for node in imports}
    assert "app.sdk.config" in imported_modules
    assert "app.sdk.events" in imported_modules
    assert "app.sdk.logging" in imported_modules
    assert "app.sdk.media" in imported_modules
    assert "app.sdk.utilities" in imported_modules
    assert any(node.level == 1 and node.module == "ffmpeg" for node in imports)
    assert any(node.level == 1 and node.module == "translate.openai_translate" for node in imports)
    assert not any(
        (node.module or "").startswith(("plugins.autosubv2", "app.core.", "app.log", "app.utils."))
        for node in imports
    )
