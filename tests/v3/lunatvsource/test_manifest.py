import json
from pathlib import Path
from urllib.parse import urlparse

from app.plugins.lunatvsource import LunaTVSource


def test_manifest_and_plugin_icons_use_https_url():
    project_root = Path(__file__).resolve().parents[3]
    package = json.loads((project_root / "package.v3.json").read_text(encoding="utf-8"))

    manifest_icon = package["LunaTVSource"]["icon"]
    plugin_icon = LunaTVSource.plugin_icon
    parsed_icon = urlparse(manifest_icon)

    assert manifest_icon == plugin_icon
    assert parsed_icon.scheme == "https"
    assert Path(parsed_icon.path).name == "lunatvsource.png"
    assert (project_root / "icons" / "lunatvsource.png").is_file()


def test_version_consistency_across_manifest_backend_and_frontend():
    project_root = Path(__file__).resolve().parents[3]
    manifest = json.loads(
        (project_root / "package.v3.json").read_text(encoding="utf-8")
    )["LunaTVSource"]
    package = json.loads(
        (
            project_root
            / "plugins.v3"
            / "lunatvsource"
            / "package.json"
        ).read_text(encoding="utf-8")
    )
    lockfile = json.loads(
        (
            project_root
            / "plugins.v3"
            / "lunatvsource"
            / "package-lock.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["version"] == "0.4.39"
    assert {
        manifest["version"],
        LunaTVSource.plugin_version,
        package["version"],
        lockfile["version"],
        lockfile["packages"][""]["version"],
    } == {"0.4.39"}

    history = manifest["history"]
    assert next(iter(history)) == "0.4.39"
    assert history["0.4.39"] == (
        "搜索按实际 CMS 源显示 X/N 进度，修复欧美剧等分类导致的电视剧 0 结果；"
        "电影与电视剧按实际分辨率降序展示，整季逐集探测并在同集多地址中选择最高画质；"
        "下载入队后立即启动，HLS 分片启用 HTTP/1.1 多连接；"
        "修正插件图标与整理关闭、完成回调串行等边界。"
    )
    assert history["0.4.38"] == (
        "电视剧资源按季聚合，冲突同集自动选择最高画质；大季按首、中、末代表集实测并按该结果排序，"
        "未抽样集明确标记，资源搜索按媒体类型过滤，季订阅不再只刷新首集。"
    )
