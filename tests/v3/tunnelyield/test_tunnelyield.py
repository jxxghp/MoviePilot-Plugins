from plugins.v3.tunnelyield import TunnelYield


def test_plugin_metadata():
    """插件基础元信息校验"""
    assert TunnelYield.plugin_name == "隧道在线带宽释放"
    assert TunnelYield.plugin_version
    assert TunnelYield.plugin_config_prefix == "tunnelyield_"
