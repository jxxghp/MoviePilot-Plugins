"""V3 插件导入边界门禁：Compat 旧导入只减不增，越界访问直接禁止。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts/check_v3_imports.py"


def _load_checker():
    """按文件加载检查脚本，避免依赖 scripts 目录成为包。"""
    spec = importlib.util.spec_from_file_location("check_v3_imports", CHECKER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    """加载检查脚本。"""
    return _load_checker()


@pytest.fixture(scope="module")
def matcher(checker):
    """基于宿主 Compat 清单的旧导入匹配器。"""
    return checker._LegacyMatcher(checker.load_compat_manifest())


def _plugin(root: Path, plugin_id: str, source: str) -> Path:
    """在临时仓库中创建只含入口文件的 V3 插件。"""
    plugin_dir = root / "plugins.v3" / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text(source, encoding="utf-8")
    return plugin_dir


def test_repository_matches_baseline(checker) -> None:
    """当前仓库没有越界访问，存量与基线完全一致。"""
    assert checker.main([]) == 0


def test_legacy_imports_follow_compat_manifest(checker, matcher, tmp_path: Path) -> None:
    """经 Compat 解析的旧模块和旧符号计入存量，canonical 与 SDK 路径不计入。"""
    plugin_dir = _plugin(
        tmp_path,
        "demo",
        "from app.plugins import _PluginBase\n"
        "from app.log import logger\n"
        "import app.core.config\n"
        "from app.sdk.plugin import _PluginBase as Base\n"
        "from app.sdk.logging import logger as sdk_logger\n"
        "from app.chain.search import SearchChain\n",
    )

    sections, violations = checker.scan_plugin(plugin_dir, matcher, tmp_path)

    assert violations == []
    assert dict(sections[checker.LEGACY_SECTION]) == {
        "app.plugins._PluginBase": 1,
        "app.log": 1,
        "app.core.config": 1,
    }


def test_host_data_access_is_counted(checker, matcher, tmp_path: Path) -> None:
    """直接导入宿主 Model 与 Session 工厂计入宿主数据直连存量。"""
    plugin_dir = _plugin(
        tmp_path,
        "demo",
        "from app.db import SessionFactory\n"
        "from app.db.models.user import User\n"
        "from app.db.oper.site import SiteOper\n",
    )

    sections, violations = checker.scan_plugin(plugin_dir, matcher, tmp_path)

    assert violations == []
    assert dict(sections[checker.HOST_DATA_SECTION]) == {
        "app.db.SessionFactory": 1,
        "app.db.models.user": 1,
    }


@pytest.mark.parametrize(
    "source, message",
    [
        ("from app.plugins.otherplugin.service import servicer\n", "导入其他插件的模块"),
        ("import importlib\nimportlib.import_module('app.plugins.otherplugin.service')\n", "引用其他插件的模块"),
        ("import sys\nsys.path.append('/config/plugins')\n", "修改 sys.path"),
        ("import sys\nsys.path.insert(0, '/app')\n", "修改 sys.path"),
        ("from pathlib import Path\nDB = Path('/config/user.db')\n", "直接访问宿主数据库文件"),
        ("from app.sdk._legacy.workflow import start\n", "导入 SDK Legacy"),
    ],
)
def test_boundary_violations_are_forbidden(checker, matcher, tmp_path: Path, source: str, message: str) -> None:
    """跨插件导入、修改 sys.path、打开宿主数据库文件和 SDK Legacy 直接判定违规。"""
    plugin_dir = _plugin(tmp_path, "demo", source)

    _sections, violations = checker.scan_plugin(plugin_dir, matcher, tmp_path)

    assert len(violations) == 1
    assert violations[0].message.startswith(message)
    assert violations[0].path == "plugins.v3/demo/__init__.py"


def test_own_plugin_package_imports_are_allowed(checker, matcher, tmp_path: Path) -> None:
    """插件导入自己包内模块不算跨插件访问。"""
    plugin_dir = _plugin(
        tmp_path,
        "demo",
        "from app.plugins.demo.service import helper\n"
        "import importlib\n"
        "importlib.import_module('app.plugins.demo.api')\n",
    )

    _sections, violations = checker.scan_plugin(plugin_dir, matcher, tmp_path)

    assert violations == []


def test_baseline_only_allows_decrease(checker) -> None:
    """超出基线判定为新增，低于基线要求同步下调，新插件不得带入存量。"""
    baseline = {
        checker.LEGACY_SECTION: {"old": {"app.log": 2}},
        checker.HOST_DATA_SECTION: {},
    }
    current = {
        checker.LEGACY_SECTION: {"old": {"app.log": 1}, "new": {"app.plugins._PluginBase": 1}},
        checker.HOST_DATA_SECTION: {"old": {"app.db.models.user": 1}},
    }

    increased, stale = checker.compare_baseline(current, baseline)

    assert increased == [
        "[legacy_imports] plugins.v3/new: app.plugins._PluginBase 0 -> 1",
        "[host_data_access] plugins.v3/old: app.db.models.user 0 -> 1",
    ]
    assert stale == ["[legacy_imports] plugins.v3/old: app.log 2 -> 1"]
