"""Release 工作流按索引代际选择唯一源码目录。"""

from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SELECTOR = REPO_ROOT / ".github/scripts/select_plugin_release_dir.sh"
WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"


def _select(tmp_path: Path, package_file: str) -> subprocess.CompletedProcess[str]:
    """在临时仓库中运行代际目录选择器。"""
    return subprocess.run(
        ["bash", str(SELECTOR), package_file, "example"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_directory_selects_each_generation_source(tmp_path: Path) -> None:
    """三个索引必须分别打包各自代际目录。"""
    (tmp_path / "plugins/example").mkdir(parents=True)
    (tmp_path / "plugins.v2/example").mkdir(parents=True)
    (tmp_path / "plugins.v3/example").mkdir(parents=True)

    assert _select(tmp_path, "package.json").stdout.strip() == "plugins/example"
    assert _select(tmp_path, "package.v2.json").stdout.strip() == "plugins.v2/example"
    assert _select(tmp_path, "package.v3.json").stdout.strip() == "plugins.v3/example"


def test_release_directory_never_falls_back_between_generations(tmp_path: Path) -> None:
    """缺少目标代目录时不得打包同名旧代源码。"""
    (tmp_path / "plugins/example").mkdir(parents=True)
    (tmp_path / "plugins.v2/example").mkdir(parents=True)

    assert _select(tmp_path, "package.v2.json").returncode == 0
    assert _select(tmp_path, "package.v3.json").returncode != 0


def test_release_directory_rejects_unknown_package_file(tmp_path: Path) -> None:
    """未知索引文件不得隐式回退到默认目录。"""
    result = _select(tmp_path, "package.beta.json")

    assert result.returncode == 2
    assert "Unsupported package file" in result.stderr


def test_release_workflow_preserves_all_generation_releases() -> None:
    """官方仓对三个索引中的 release 条目都保留独立发版能力。"""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'select_plugin_release_dir.sh "$pkg_file" "$plugin_id_lc"' in workflow
    assert 'process_package "package.json"' in workflow
    assert 'process_package "package.v2.json"' in workflow
    assert 'process_package "package.v3.json"' in workflow
    assert "select(.value.release == true)" in workflow
    assert ".value.v3 == true or .value.v2 == true" not in workflow
    assert ".value.release == true and .value.v3 != false" not in workflow
    assert "Missing plugin directory" in workflow
    assert 'git rev-parse -q --verify "refs/tags/$tag"' in workflow
