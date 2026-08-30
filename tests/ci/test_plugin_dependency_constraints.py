"""V3 插件依赖必须通过当前主程序的共享运行环境预检。"""

from pathlib import Path

import pytest

from app.adapters.system.plugin.health import PluginRuntimeHealth


REPO_ROOT = Path(__file__).resolve().parents[2]
V3_MANIFESTS = sorted((REPO_ROOT / "plugins.v3").glob("*/pyproject.toml"))


@pytest.mark.parametrize("manifest", V3_MANIFESTS)
def test_v3_manifest_preserves_host_runtime(manifest: Path) -> None:
    """插件清单不得要求覆盖主程序直接或传递运行依赖。"""
    protected_packages = PluginRuntimeHealth._PluginRuntimeHealth__get_protected_runtime_packages()
    valid, message = PluginRuntimeHealth._PluginRuntimeHealth__validate_runtime_dependency_conflicts(
        manifest,
        protected_packages,
    )

    assert valid, f"{manifest.relative_to(REPO_ROOT)}: {message}"
