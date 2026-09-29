"""V3 字幕插件的依赖清单与宿主加载冒烟测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
V3_PLUGINS = ROOT / "plugins.v3"


class PackageTests(unittest.TestCase):
    def test_v3_market_and_dependency_manifests(self) -> None:
        """市场应选 V3 副本，依赖清单可被 V3 解析。"""

        catalog = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        legacy = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        for plugin_id in ("AutoSubtitle", "SubtitleAssistant"):
            with self.subTest(plugin=plugin_id):
                entry = catalog[plugin_id]
                self.assertEqual(entry["version"], "2.0.0")
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
