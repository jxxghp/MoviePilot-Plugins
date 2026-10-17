"""两代刷流界面必须按文件完成度显示状态，并兼容尚未刷新的旧记录。"""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("generation", ["v2", "v3"])
def test_brushflow_frontend_progress(generation):
    """执行真实 JS 工具函数，覆盖零流量、高流量及舍入边界。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("JS 行为测试需要 Node.js")
    source = Path(__file__).resolve().parents[2] / f"plugins.{generation}/brushflow/src/utils.js"
    script = '''
import assert from 'node:assert/strict';
const {torrentProgress} = await import(process.argv[1]);
assert.equal(torrentProgress({size: 101, downloaded: 0, progress: 1}), 100);
assert.equal(torrentProgress({size: 100, downloaded: 200, progress: .5}), 50);
assert.equal(torrentProgress({progress: .9999}), 99);
assert.equal(torrentProgress({size: 100, downloaded: 50}), 50);
assert.equal(torrentProgress({size: 100, downloaded: 100}), 100);
assert.equal(torrentProgress({}), 0);
assert.equal(torrentProgress({progress: 0, downloaded: 100, size: 100}), 0);
assert.equal(torrentProgress({progress: -1}), 0);
assert.equal(torrentProgress({progress: 'bad'}), 0);
'''
    subprocess.run([node, "--input-type=module", "-e", script, source.as_uri()], check=True)
