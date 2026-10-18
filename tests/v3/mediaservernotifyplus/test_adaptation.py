import ast
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }


class AdaptationTests(unittest.TestCase):
    def test_versions_and_manifests_match(self):
        v2_package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        v3_package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        self.assertFalse(v2_package["MediaServerNotifyPlus"]["v3"])
        self.assertEqual(v3_package["MediaServerNotifyPlus"]["system_version"], ">=3.0.0")
        for generation, package in (("plugins.v2", v2_package), ("plugins.v3", v3_package)):
            metadata = package["MediaServerNotifyPlus"]
            plugin = ROOT / generation / "mediaservernotifyplus"
            tree = ast.parse((plugin / "__init__.py").read_text(encoding="utf-8"))
            version = next(
                ast.literal_eval(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets)
            )
            frontend = json.loads((plugin / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["version"], version)
            self.assertEqual(frontend["version"], version)
            self.assertIn(f"v{version}", metadata["history"])
            self.assertEqual(metadata["description"], "极简配置可自定义的媒体库通知消息")
            self.assertEqual(metadata["author"], "changzhanghs")

    def test_v2_uses_v2_host_contracts(self):
        source = ROOT / "plugins.v2" / "mediaservernotifyplus" / "__init__.py"
        modules = imports(source)
        self.assertIn("app.core.event", modules)
        self.assertIn("app.helper.mediaserver", modules)
        self.assertNotIn("app.modules.themoviedb", modules)
        self.assertNotIn("app.sdk.media", modules)

    def test_v3_uses_public_sdk_and_unified_identity(self):
        source = ROOT / "plugins.v3" / "mediaservernotifyplus" / "__init__.py"
        modules = imports(source)
        self.assertIn("app.sdk.events", modules)
        self.assertIn("app.sdk.media", modules)
        self.assertIn("app.sdk.plugin", modules)
        self.assertNotIn("app.sdk.classification", modules)
        self.assertFalse(any(module.startswith("app.db.") for module in modules))
        text = source.read_text(encoding="utf-8")
        self.assertIn("resolve_media_identity", text)
        self.assertIn("media_source", text)
        self.assertIn("media_id", text)
        self.assertIn("MessageType", text)
        self.assertNotIn("NotificationType", text)

    def test_shared_core_is_identical(self):
        v2 = (ROOT / "plugins.v2" / "mediaservernotifyplus" / "core.py").read_bytes()
        v3 = (ROOT / "plugins.v3" / "mediaservernotifyplus" / "core.py").read_bytes()
        self.assertEqual(v2, v3)
        for relative in ("src/previewModel.js", "src/assets/preview-fantasy-banner.jpg"):
            self.assertEqual(
                (ROOT / "plugins.v2" / "mediaservernotifyplus" / relative).read_bytes(),
                (ROOT / "plugins.v3" / "mediaservernotifyplus" / relative).read_bytes(),
            )

    def test_both_versions_ship_vue_config_runtime(self):
        for generation in ("plugins.v2", "plugins.v3"):
            plugin = ROOT / generation / "mediaservernotifyplus"
            self.assertTrue((plugin / "src/components/Config.vue").is_file())
            self.assertTrue((plugin / "src/previewModel.js").is_file())
            self.assertTrue((plugin / "src/assets/preview-fantasy-banner.jpg").is_file())
            self.assertTrue((plugin / "dist/assets/remoteEntry.js").is_file())
            config_bundles = list((plugin / "dist/assets").glob("__federation_expose_Config-*.js"))
            self.assertEqual(len(config_bundles), 1)
            self.assertIn("data:image/jpeg;base64", config_bundles[0].read_text(encoding="utf-8"))
            source = (plugin / "src/components/Config.vue").read_text(encoding="utf-8")
            self.assertIn("可通知内容", source)
            self.assertIn("媒体服务器", source)
            self.assertIn('class="workspace"', source)
            self.assertIn("{ label: '播放相关', actions: ['playback_started', 'playback_stopped', 'playback_paused', 'playback_resumed', 'rated'] }", source)
            self.assertIn('class="content-editor"', source)
            self.assertNotIn('v-model="editorOpen"', source)
            self.assertIn('v-for="row in previewRows"', source)
            self.assertNotIn('refreshPreview', source)
            self.assertNotIn('换一组示例', source)
            self.assertIn('const previewRows = computed(() => buildPreviewRows(', source)
            self.assertNotIn('.slice(0, 4)', source)
            app_source = (plugin / "src/App.vue").read_text(encoding="utf-8")
            self.assertEqual(app_source.count("[...mediaFields]"), 5)
            self.assertEqual(app_source.count("[...libraryFields]"), 2)
            self.assertNotIn("查询媒体元数据", source)
            self.assertNotIn("查询 IP 归属地", source)
            self.assertIn("消息渠道遵循 MoviePilot 全局设置", source)
            self.assertIn("通知类型固定为“媒体服务器”", source)
            self.assertIn("http://localhost:3000/api/v1/webhook?token=API_TOKEN&amp;source=媒体服务器名:3001", source)
            self.assertNotIn("localhost:3001", source)
            self.assertIn('<div class="info-panel" role="note">', source)
            self.assertIn('class="info-panel webhook-guide"', source)
            self.assertIn('需在所选媒体服务器中设置 Webhooks，并勾选对应的通知项。', source)
            self.assertNotIn('msnp-note-card', source)
            self.assertIn('v-if="row.key === \'server\'"', source)
            self.assertIn('v-model="draft.mediaservers"', source)
            self.assertIn('label="选择媒体服务器"', source)
            self.assertIn("<h1>媒体库通知</h1>", source)
            page = (plugin / "src/components/Page.vue").read_text(encoding="utf-8")
            self.assertIn("emit('switch')", page)
            self.assertIn("onMounted(() => emit('switch'))", page)
            self.assertNotIn("plugin/form/", page)
            self.assertNotIn("detail-grid", page)
            self.assertNotIn("@click=\"$emit('action')\"", page)
            shared = (plugin / "src/notificationModel.js").read_text(encoding="utf-8")
            self.assertIn("['user', 'device', 'progress', 'ip']", shared)
            self.assertIn("normalizeNotificationModel", source)
            self.assertIn("['client', 'year', 'channel', 'ip_location', 'play_link']", shared)

    def test_notification_type_is_fixed_to_media_server(self):
        v2 = (ROOT / "plugins.v2/mediaservernotifyplus/__init__.py").read_text(encoding="utf-8")
        v3 = (ROOT / "plugins.v3/mediaservernotifyplus/__init__.py").read_text(encoding="utf-8")
        self.assertIn("NotificationType.MediaServer", v2)
        self.assertIn("MessageType.MediaServer", v3)


if __name__ == "__main__":
    unittest.main()
