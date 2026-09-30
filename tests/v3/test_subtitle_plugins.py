"""V3 字幕插件的依赖清单与宿主加载冒烟测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
V3_PLUGINS = ROOT / "plugins.v3"


class PackageTests(unittest.TestCase):
    def test_subtitleassistant_frontend_is_published(self) -> None:
        """Vue 联邦入口及其资源必须随插件提交到仓库。"""

        assets = V3_PLUGINS / "subtitleassistant" / "frontend" / "dist" / "assets"
        tracked = set(
            subprocess.check_output(
                ["git", "ls-files", "--", "plugins.v3/subtitleassistant/frontend/dist/assets"],
                cwd=ROOT,
                text=True,
            ).splitlines()
        )
        entry = assets / "remoteEntry.js"
        self.assertIn(entry.relative_to(ROOT).as_posix(), tracked)
        entry_source = entry.read_text(encoding="utf-8")
        self.assertIn("./AppPage", entry_source)
        self.assertIn("./Config", entry_source)
        for asset in assets.iterdir():
            with self.subTest(asset=asset.name):
                self.assertIn(asset.relative_to(ROOT).as_posix(), tracked)

    def test_subtitleassistant_target_package_is_included(self) -> None:
        """字幕助手运行态依赖的 target 包必须随 V3 插件一起发布。"""

        target = V3_PLUGINS / "subtitleassistant" / "target"
        self.assertTrue((target / "__init__.py").is_file())
        for module in ("history.py", "mapping.py", "projection.py"):
            with self.subTest(module=module):
                self.assertTrue((target / module).is_file())

    def test_v3_market_and_dependency_manifests(self) -> None:
        """市场应选 V3 副本，依赖清单可被 V3 解析。"""

        catalog = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        legacy = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        for plugin_id in ("AutoSubtitle", "SubtitleAssistant"):
            with self.subTest(plugin=plugin_id):
                entry = catalog[plugin_id]
                self.assertEqual(entry["version"], "2.0.1" if plugin_id == "SubtitleAssistant" else "2.0.0")
                self.assertEqual(entry["system_version"], ">=3.0.0")
                self.assertFalse(legacy[plugin_id]["v3"])
                manifest = tomllib.loads(
                    (V3_PLUGINS / plugin_id.lower() / "pyproject.toml").read_text(encoding="utf-8")
                )
                self.assertIn("project", manifest)
                self.assertIn("yake>=0.6,<0.8", manifest["project"]["dependencies"])
                self.assertFalse((V3_PLUGINS / plugin_id.lower() / "requirements.txt").exists())

        auto_deps = tomllib.loads((V3_PLUGINS / "autosubtitle/pyproject.toml").read_text(encoding="utf-8"))
        self.assertFalse(any("ffsubsync" in dependency for dependency in auto_deps["project"]["dependencies"]))


@unittest.skipUnless(importlib.util.find_spec("app") is not None, "需要 MoviePilot V3 宿主环境")
class HostSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.testing.bootstrap import ensure_optional_stub

        # 测试环境不安装插件依赖；AutoSubtitle 顶层导入 yake，缺失时补占位，已安装则沿用真实模块
        ensure_optional_stub("yake", KeywordExtractor=MagicMock)
        sys.path.insert(0, str(V3_PLUGINS))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(V3_PLUGINS))

    def test_autosubtitle_loads_with_optional_sync_dependency_absent(self) -> None:
        """未安装 ffsubsync 时插件仍能初始化和显示配置。"""

        from autosubtitle import AutoSubtitle

        with patch("autosubtitle._PluginBase.__init__", return_value=None):
            plugin = AutoSubtitle()
        with patch.object(plugin, "update_config", return_value=True):
            plugin.init_plugin({"enabled": False, "auto_sync": True})
        form, config = plugin.get_form()
        self.assertIsInstance(form, list)
        self.assertTrue(plugin._auto_sync)
        self.assertIn("auto_sync", config)
        with patch("autosubtitle.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            synced = asyncio.run(plugin._AutoSubtitle__sync_subtitle(Path("subtitle.srt"), "video.mkv"))
        self.assertFalse(synced)

    def test_subtitleassistant_initializes_with_isolated_data(self) -> None:
        """V3 宿主 API 可以构建插件运行态，且只写入测试数据。"""

        from subtitleassistant.plugin import build_runtime

        with tempfile.TemporaryDirectory() as data_root:
            class SubtitleAssistant:
                def __init__(self) -> None:
                    self.data: dict[str, object] = {}

                def get_data(self, key: str) -> object:
                    return self.data.get(key)

                async def async_get_data(self, key: str) -> object:
                    return self.get_data(key)

                def save_data(self, key: str, value: object) -> None:
                    self.data[key] = value

                async def async_save_data(self, key: str, value: object) -> None:
                    self.save_data(key, value)

                def get_data_path(self) -> Path:
                    return Path(data_root)

                def update_config(self, config: dict[str, object], plugin_id: str) -> bool:
                    return True

            runtime = build_runtime(
                SubtitleAssistant(),
                {"enabled": False, "moviepilot_enabled": False, "opensubtitles_enabled": False, "assrt_enabled": False},
            )
            self.assertFalse(runtime.get_state())
            self.assertEqual(runtime.get_render_mode()[0], "vue")
            self.assertIsInstance(runtime.get_api(), list)
            runtime.stop_sync()


if __name__ == "__main__":
    unittest.main()
