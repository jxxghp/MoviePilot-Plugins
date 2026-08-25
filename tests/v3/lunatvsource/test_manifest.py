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

    assert manifest["version"] == "0.4.46"
    assert {
        manifest["version"],
        LunaTVSource.plugin_version,
        package["version"],
        lockfile["version"],
        lockfile["packages"][""]["version"],
    } == {"0.4.46"}

    history = manifest["history"]
    assert next(iter(history)) == "0.4.46"
    assert history["0.4.46"] == (
        "将受管二进制真实性校验改为代码内固定可执行摘要；完善 POSIX 进程组有界终止与"
        "外部进程看门狗，终止宽限期只按进程组状态判定，仅在引擎明确进入封装阶段后停用"
        "下载停滞检查，并先消费本轮进度与缓存活动再判断停滞，不再把单轨 100% 或缓存"
        "文件数当作整体完成证据；修复残留管道、日志绕过停滞及长时间封装误杀；跨文件"
        "系统目标"
        "提交后的源清理失败不再反转成功状态。"
    )
    assert history["0.4.45"] == (
        "修复双引擎发布阶段的容器、缓存和权限边界：N_m3u8DL-RE 固定混流 MP4，"
        "VSD 删除任务时清理阶段目录，跨文件系统移动保留源文件权限。"
    )
    assert history["0.4.44"] == (
        "电视剧整季资源改为每个来源只抽测一个代表集，并移除全季实测提示；"
        "接入受管 N_m3u8DL-RE 与 VSD 双引擎，失败时回退 ffmpeg，支持缓存续传、进度、暂停与安全清理；"
        "固定 LunaTV 下载器及插件下载目录展示元数据。"
    )
    assert history["0.4.43"] == (
        "修复电视剧资源因简繁标题及媒体身份不一致在 MoviePilot 匹配阶段被清空；"
        "桥接本次搜索目标的规范标题、年份与媒体身份，外层资源用于宿主匹配，下载载荷继续保留"
        "资源站标题、来源及分集地址；按目标上下文隔离搜索缓存，电影逻辑保持不变。"
    )
    assert history["0.4.41"] == (
        "修复电视剧分集分页在无年份、年份冲突、无 ID 与无效地址场景下的误聚合或提前停止；"
        "资源站配置加载增加过渡提示；搜索完成后提示资源汇总、清晰度检测与排序，并兼容 "
        "MoviePilot 三位优先级，确保高分辨率资源置顶。"
    )
    assert history["0.4.40"] == (
        "电视剧分集行完整聚合为季卡，补齐长季分页、稀疏详情和多组播放地址；"
        "电影/电视剧在每源限额前过滤；整季下载跳过坏地址并保留有效剧集；"
        "分辨率失败正确标记部分实测；队列保留全部非终态任务并修复删除持久化竞态。"
    )
    assert history["0.4.38"] == (
        "电视剧资源按季聚合，冲突同集自动选择最高画质；大季按首、中、末代表集实测并按该结果排序，"
        "未抽样集明确标记，资源搜索按媒体类型过滤，季订阅不再只刷新首集。"
    )


def test_app_page_shows_loading_state_before_empty_sources():
    project_root = Path(__file__).resolve().parents[3]
    app_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "AppPage.vue"
    ).read_text(encoding="utf-8")

    loading_state = '<div v-if="loading" class="empty">正在读取资源站配置…</div>'
    empty_state = '<div v-else-if="!sources.length" class="empty">暂未读取到资源站配置</div>'

    assert "const loading = ref(true)" in app_page
    assert "{{ loading ? '…' : sources.length }}" in app_page
    assert loading_state in app_page
    assert empty_state in app_page
    assert app_page.index(loading_state) < app_page.index(empty_state)


def test_config_exposes_and_preserves_single_download_directory():
    project_root = Path(__file__).resolve().parents[3]
    config_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "download_root: '/downloads/未整理'" in config_page
    assert 'v-model="config.download_root"' in config_page
    assert "download_root: String(config.download_root || '').trim()" in config_page
