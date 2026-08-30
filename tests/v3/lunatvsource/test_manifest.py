import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from app.plugins.lunatvsource import LunaTVSource
from app.plugins.lunatvsource.m3u8_engine import N_M3U8DL_RE_SPEC


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


def test_linux_engine_archives_and_license_are_bundled_and_verified():
    project_root = Path(__file__).resolve().parents[3]
    vendor_dir = (
        project_root
        / "plugins.v3"
        / "lunatvsource"
        / "vendor"
        / "n_m3u8dl_re"
    )

    assert (vendor_dir / "LICENSE").is_file()
    assert (vendor_dir / "README.md").is_file()
    for platform_key in (("linux", "x86_64"), ("linux", "aarch64")):
        asset = N_M3U8DL_RE_SPEC.assets[platform_key]
        archive = vendor_dir / asset.filename
        assert archive.is_file()
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == asset.sha256


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

    assert manifest["version"] == "0.4.59"
    assert {
        manifest["version"],
        LunaTVSource.plugin_version,
        package["version"],
        lockfile["version"],
        lockfile["packages"][""]["version"],
    } == {"0.4.59"}

    history = manifest["history"]
    assert next(iter(history)) == "0.4.59"
    assert history["0.4.59"] == (
        "新增可选的 NFO 元数据开关，默认关闭；启用后下载完成并由 MoviePilot 原生整理时生成标准 "
        "NFO，关闭时明确不触发刮削。"
    )
    assert history["0.4.58"] == (
        "识别 CMS API 1002 关键词搜索禁用响应，明确显示源站在线但禁止搜索并自动排除，"
        "避免误报为缺少 list/data。"
    )
    assert history["0.4.57"] == (
        "修复立即健康检查每 2 秒完整刷新来源表导致页面闪烁；"
        "检查期间仅静默轮询运行状态，完成后一次性刷新缓存结果。"
    )
    assert history["0.4.56"] == (
        "修复来源重新启用、换址及检查/搜索并发时旧健康结果回写或旧搜索结果进入订阅队列；"
        "重新启用后必须复检成功才参与搜索，周期全量检查可在单源复检后排队执行。"
    )
    assert history["0.4.55"] == (
        "来源清单与搜索健康改为按可配置间隔后台刷新（默认 60 分钟），插件页只读持久化缓存；"
        "未检查、已知或实时检查失败的来源退出所有搜索与订阅追更并定时复测，恢复后自动启用；"
        "支持手动永久停用、重新启用和单源立即复检。"
    )
    assert history["0.4.54"] == (
        "修复 MoviePilot 原生下载链未调用 LunaTV 队列的问题；整季下载保持单行并显示正在整理"
        "第 x/n 集、稳定统计总大小，整理成功后清除空目录且隐藏无意义上传速度；失败任务原地重试"
        "并清理重复记录；内置经固定 SHA-256 校验的 N_m3u8DL-RE Linux x64/arm64 官方包，离线 "
        "NAS 首次安装无需访问 GitHub；未完结电视剧订阅兼容 MoviePilot TV 枚举，只追加身份匹配且"
        "位于订阅集数范围内的缺失新集，并把历史已完成集计入整季单任务；普通磁力和种子保持原逻辑。"
    )
    assert history["0.4.53"] == (
        "插件工作台跟随 MoviePilot/Vuetify 的主题色、深浅色与透明效果，移除 1200px 固定宽度以修复"
        "宽屏弹窗两侧漏白；构建时过滤共享 Vuetify 基础样式，避免覆盖宿主主题。"
    )
    assert history["0.4.50"] == (
        "LunaTV 下载队列接入 MoviePilot 原生下载管理，支持进度展示及暂停、继续、删除；"
        "客户端仅在内存中注册且按下载器隔离，未显式配置目录时复用 MoviePilot 本地下载目录。"
    )
    assert history["0.4.49"] == (
        "电视剧原生资源按标准作品、年份和季聚合，同季来源保持清晰度降序并保留整季下载身份；"
        "插件工作台仅保留状态与配置，不再提供独立搜索旁路；清晰度探测兼容中文 URL 和无扩展名分片。"
    )
    assert history["0.4.48"] == (
        "修复 LunaTV 资源下载被 MoviePilot 目录白名单提前拦截，现由插件在校验前接管并进入"
        "串行队列；N_m3u8DL-RE 解析 ffmpeg 绝对路径，稳定启用 16 线程下载；受管引擎包"
        "遇临时连接错误有限重试，HTTP 确定性错误不重试。"
    )
    assert history["0.4.47"] == (
        "电视剧搜索结果统一使用同一次匹配得到的标准作品标题与年份，使同一作品同一季的"
        "不同来源与不同分辨率归入同一 MoviePilot 资源卡；仍按分辨率从高到低排序，最高分辨率"
        "作为主项，其余归入“更多来源”；不同季和不同作品/年份保持隔离。"
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


def test_app_page_follows_moviepilot_theme_and_fills_plugin_dialog():
    project_root = Path(__file__).resolve().parents[3]
    app_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "AppPage.vue"
    ).read_text(encoding="utf-8")
    vite_config = (
        project_root / "plugins.v3" / "lunatvsource" / "vite.config.js"
    ).read_text(encoding="utf-8")

    assert "width: 100%" in app_page
    assert "max-width: none" in app_page
    assert "rgb(var(--v-theme-background" in app_page
    assert "rgb(var(--v-theme-primary" in app_page
    assert "#101018" not in app_page
    assert "postcssPlugin: 'vuetify-filter'" in vite_config
    assert not list(
        (project_root / "plugins.v3" / "lunatvsource" / "dist" / "assets").glob(
            "__federation_shared_vuetify/styles-*.css"
        )
    )


def test_config_exposes_download_directory_and_nfo_switch():
    project_root = Path(__file__).resolve().parents[3]
    config_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "download_root: '/downloads/未整理'" in config_page
    assert 'v-model="config.download_root"' in config_page
    assert "download_root: String(config.download_root || '').trim()" in config_page
    assert "generate_nfo: false" in config_page
    assert 'v-model="config.generate_nfo"' in config_page
    assert "生成 NFO 元数据" in config_page


def test_source_health_ui_uses_cached_reads_and_persists_interval():
    project_root = Path(__file__).resolve().parents[3]
    app_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "AppPage.vue"
    ).read_text(encoding="utf-8")
    config_page = (
        project_root / "plugins.v3" / "lunatvsource" / "src" / "components" / "Config.vue"
    ).read_text(encoding="utf-8")

    assert "onMounted(load)" in app_page
    assert "onMounted(startHealthCheck)" not in app_page
    assert "'/sources/refresh'" in app_page
    assert "'/sources/state'" in app_page
    assert "const silent = options?.silent === true" in app_page
    assert "await loadHealthStatus()" in app_page
    assert "await load({ silent: true })" in app_page
    assert "打开页面仅读取缓存" in app_page
    assert "搜索仅使用健康且已启用的来源" in app_page
    assert "source.manual_disabled ? '重新启用' : '永久停用'" in app_page
    assert '@click="recheckSource(source)"' in app_page
    assert "source_check_minutes: 60" in config_page
    assert 'v-model="config.source_check_minutes"' in config_page
    assert "来源健康检查间隔（分钟）" in config_page
    assert "15–1440" in config_page
