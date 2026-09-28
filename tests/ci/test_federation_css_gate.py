"""联邦插件 CSS 宿主污染门禁。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / ".github/scripts/check_federation_css.py"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-gate.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"
PRE_PUSH = REPO_ROOT / ".githooks/pre-push"


def _fixture(tmp_path: Path, css: str, *, shared: bool = False) -> Path:
    """创建一个最小联邦插件及其构建产物。"""
    plugin_dir = tmp_path / "plugins.v3/example"
    assets_dir = plugin_dir / "dist/assets"
    assets_dir.mkdir(parents=True)
    (plugin_dir / "vite.config.js").write_text(
        "import federation from '@originjs/vite-plugin-federation'\n"
        "export default { plugins: [federation({ name: 'Example' })] }\n",
        encoding="utf-8",
    )
    (tmp_path / "package.v3.json").write_text(
        json.dumps({"Example": {"version": "1.0.0", "release": True}}),
        encoding="utf-8",
    )
    css_file = assets_dir / "example.css"
    css_file.write_text(css, encoding="utf-8")
    (assets_dir / "remoteEntry.js").write_text(
        'dynamicLoadingCss(["example.css"], false, "./Page")\n',
        encoding="utf-8",
    )
    if shared:
        shared_dir = assets_dir / "__federation_shared_vuetify"
        shared_dir.mkdir()
        (shared_dir / "styles-test.css").write_text(".rounded { border-radius: 4px }\n")
    return tmp_path


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    """运行 CSS 门禁并返回完整输出。"""
    return subprocess.run(
        ["python3", str(CHECKER), "--root", str(root)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_checker_accepts_plugin_scoped_vuetify_override(tmp_path: Path) -> None:
    """插件根节点或 Vue scoped 标记限定的 Vuetify 覆盖不会污染宿主。"""
    root = _fixture(
        tmp_path,
        ".plugin-root .v-btn { border-radius: 8px }\n"
        ".panel[data-v-abcd1234] .v-card { padding: 8px }\n",
    )

    result = _run_checker(root)

    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_rejects_global_vuetify_selector(tmp_path: Path) -> None:
    """直接命中宿主 Vuetify 组件的选择器必须失败。"""
    root = _fixture(tmp_path, ".v-card { border-radius: 0 }\n")

    result = _run_checker(root)

    assert result.returncode == 1
    assert "未限定作用域" in result.stdout
    assert ".v-card" in result.stdout


def test_checker_rejects_shared_vuetify_stylesheet(tmp_path: Path) -> None:
    """即使 remoteEntry 尚未引用，也不允许把整包 Vuetify CSS 放进发布目录。"""
    root = _fixture(tmp_path, ".plugin-root { display: grid }\n", shared=True)

    result = _run_checker(root)

    assert result.returncode == 1
    assert "不得发布 Vuetify 共享基础样式" in result.stdout


def test_checker_rejects_federation_plugin_without_release_packaging(tmp_path: Path) -> None:
    """联邦插件必须明确进入 Release workflow 的资产打包列表。"""
    root = _fixture(tmp_path, ".plugin-root { display: grid }\n")
    (root / "package.v3.json").write_text(
        json.dumps({"Example": {"version": "1.0.0", "release": False}}),
        encoding="utf-8",
    )

    result = _run_checker(root)

    assert result.returncode == 1
    assert "必须设置 release=true" in result.stdout


def test_current_repository_passes_federation_css_gate() -> None:
    """真实仓库基线必须通过，避免门禁启用后阻断全部插件 PR。"""
    result = _run_checker(REPO_ROOT)

    assert result.returncode == 0, result.stdout + result.stderr


def test_css_gate_is_used_by_pr_release_and_pre_push() -> None:
    """本地、PR 与发布入口必须使用同一检查器。"""
    checker_path = ".github/scripts/check_federation_css.py"
    assert checker_path in PR_WORKFLOW.read_text(encoding="utf-8")
    assert checker_path in RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert checker_path in PRE_PUSH.read_text(encoding="utf-8")
