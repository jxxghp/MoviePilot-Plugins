"""证书管理插件测试。"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app.plugins.certmanager import CertManager


def _make_plugin() -> CertManager:
    """构造不触发宿主 Chain 依赖的插件实例。"""
    plugin = object.__new__(CertManager)
    plugin._enabled = False
    plugin._notify = True
    plugin._cron = "0 4 * * *"
    plugin._acme_home = "/config/acme.sh"
    plugin._cert_dir = "/config/certs/latest"
    plugin._domain = ""
    plugin._dns_provider = "dns_ali"
    plugin._dns_key = ""
    plugin._dns_secret = ""
    plugin._key_length = "ec-256"
    plugin._warn_days = 20
    plugin._timeout = 600
    return plugin


def test_plugin_metadata() -> None:
    """插件元数据应与市场索引保持一致。"""
    plugin = _make_plugin()
    assert plugin.plugin_name == "证书管理"
    assert plugin.plugin_version == "1.4.1"
    assert plugin.plugin_config_prefix == "certmanager_"
    assert plugin.auth_level == 1


def test_init_plugin_applies_config() -> None:
    """初始化应完整读取配置项，未提供的项保留默认值。"""
    plugin = _make_plugin()
    plugin.init_plugin({
        "enabled": True,
        "notify": False,
        "cron": "30 3 * * *",
        "acme_home": "/custom/acme",
        "cert_dir": "/custom/certs",
        "domain": "example.com",
        "dns_provider": "dns_cf",
        "dns_key": "cf-token-abc",
        "dns_secret": "cf-account-123",
        "key_length": "2048",
    })

    assert plugin.get_state() is True
    assert plugin._notify is False
    assert plugin._cron == "30 3 * * *"
    assert plugin._acme_home == "/custom/acme"
    assert plugin._cert_dir == "/custom/certs"
    assert plugin._domain == "example.com"
    assert plugin._dns_provider == "dns_cf"
    assert plugin._dns_key == "cf-token-abc"
    assert plugin._dns_secret == "cf-account-123"
    assert plugin._key_length == "2048"


def test_init_plugin_without_config_keeps_defaults() -> None:
    """未传入配置时不得改变默认值，也不得抛异常。"""
    plugin = _make_plugin()
    plugin.init_plugin(None)

    assert plugin.get_state() is False
    assert plugin._cron == "0 4 * * *"
    assert plugin._acme_home == "/config/acme.sh"


def test_get_form_returns_config_schema() -> None:
    """配置表单应包含启用开关、路径配置与自动申请配置。"""
    plugin = _make_plugin()
    form, defaults = plugin.get_form()

    assert isinstance(form, list) and form
    assert defaults["enabled"] is False
    assert defaults["cron"] == "0 4 * * *"
    assert defaults["cert_dir"] == "/config/certs/latest"
    assert defaults["dns_provider"] == "dns_ali"
    assert defaults["key_length"] == "ec-256"

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "dns_key" in form_str
    assert "dns_secret" in form_str
    assert "阿里云" in form_str
    assert "Cloudflare" in form_str
    # 服务商选择应支持手动输入
    assert "VCombobox" in form_str


def test_get_service_requires_enabled() -> None:
    """插件未启用时不应注册定时服务。"""
    plugin = _make_plugin()
    plugin.init_plugin({"enabled": False, "cron": "0 4 * * *"})

    assert plugin.get_service() == []


def test_get_service_registers_cron() -> None:
    """启用后应按配置的 cron 注册唯一服务，并绑定续期入口。"""
    plugin = _make_plugin()
    plugin.init_plugin({"enabled": True, "cron": "0 4 * * *"})

    services = plugin.get_service()

    assert len(services) == 1
    assert services[0]["id"] == "CertManager"
    assert services[0]["func"] == plugin.renew_cert
    assert services[0]["trigger"] is not None


def test_get_service_rejects_invalid_cron() -> None:
    """非法 cron 表达式应返回空列表，而不是注册不可用的服务。"""
    plugin = _make_plugin()
    plugin.init_plugin({"enabled": True, "cron": "not-a-cron"})

    assert plugin.get_service() == []


def test_normalize_pem_accepts_standard_certificate() -> None:
    """标准证书 PEM 应被接受并统一换行。"""
    text = "-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"
    result = CertManager._normalize_pem(text, "CERTIFICATE")

    assert result.startswith("-----BEGIN CERTIFICATE-----")
    assert result.endswith("\n")


def test_normalize_pem_accepts_rsa_private_key() -> None:
    """RSA 私钥的旧式标签应被兼容。"""
    text = "-----BEGIN RSA PRIVATE KEY-----\nABC\n-----END RSA PRIVATE KEY-----"
    result = CertManager._normalize_pem(text, "PRIVATE KEY")

    assert result != ""
    assert "RSA PRIVATE KEY" in result


def test_normalize_pem_rejects_invalid_text() -> None:
    """格式不合法的文本应返回空字符串。"""
    assert CertManager._normalize_pem("not a pem", "CERTIFICATE") == ""
    assert CertManager._normalize_pem("", "PRIVATE KEY") == ""


def test_acme_env_maps_aliyun_credentials() -> None:
    """阿里云凭据应映射为 acme.sh 期望的 Ali_Key 与 Ali_Secret。"""
    plugin = _make_plugin()
    env = plugin._acme_env("dns_ali", "test-key", "test-secret")

    assert env["Ali_Key"] == "test-key"
    assert env["Ali_Secret"] == "test-secret"
    assert env["LE_WORKING_DIR"] == "/config/acme.sh"


def test_acme_env_maps_cloudflare_credentials() -> None:
    """Cloudflare 凭据应映射为 CF_Token 与 CF_Account_ID。"""
    plugin = _make_plugin()
    env = plugin._acme_env("dns_cf", "cf-token", "cf-account")

    assert env["CF_Token"] == "cf-token"
    assert env["CF_Account_ID"] == "cf-account"


def test_acme_env_handles_single_credential_provider() -> None:
    """只需一个凭据的服务商不应被第二个字段覆盖。"""
    plugin = _make_plugin()
    env = plugin._acme_env("dns_namesilo", "only-key", "should-be-ignored")

    assert env["Namesilo_Key"] == "only-key"


def test_acme_env_uses_default_fields_for_unknown_provider() -> None:
    """未收录的服务商应使用通用字段名，仍可正常传参。"""
    plugin = _make_plugin()
    env = plugin._acme_env("dns_unknown_xyz", "value1", "value2")

    assert env["KEY1"] == "value1"
    assert env["KEY2"] == "value2"


def test_acme_env_keeps_required_paths() -> None:
    """环境变量应包含 acme.sh 所需的目录配置。"""
    plugin = _make_plugin()
    env = plugin._acme_env("dns_ali", "", "")

    assert env["LE_WORKING_DIR"] == "/config/acme.sh"
    assert env["LE_CONFIG_HOME"] == "/config/acme.sh/data"
    assert "PATH" in env


def test_credential_fields_returns_provider_specific_names() -> None:
    """凭据字段名应随服务商变化。"""
    plugin = _make_plugin()

    key_name, _, secret_name, _ = plugin._credential_fields("dns_ali")
    assert key_name == "Ali_Key"
    assert secret_name == "Ali_Secret"

    key_name, _, secret_name, _ = plugin._credential_fields("dns_dp")
    assert key_name == "DP_Id"
    assert secret_name == "DP_Key"

    # 未收录的服务商回落到通用字段
    key_name, _, secret_name, _ = plugin._credential_fields("dns_unknown")
    assert key_name == "KEY1"
    assert secret_name == "KEY2"


def test_extract_field_parses_openssl_output() -> None:
    """应从 openssl 输出中提取指定字段。"""
    output = "subject=CN=example.com\nissuer=C=US, O=Let's Encrypt\nnotAfter=Dec 29 13:44:16 2026 GMT"

    assert CertManager._extract_field(output, "subject=") == "CN=example.com"
    assert CertManager._extract_field(output, "issuer=") == "C=US, O=Let's Encrypt"
    assert CertManager._extract_field(output, "missing=") == ""


def test_collect_status_without_cert_file(tmp_path: Path) -> None:
    """证书文件缺失时应返回未检测到状态。"""
    plugin = _make_plugin()
    plugin._cert_dir = str(tmp_path / "missing")

    status = plugin._collect_status()

    assert status["valid"] is False
    assert "未检测到证书文件" in status["summary"]


def test_cert_days_left_returns_none_without_file(tmp_path: Path) -> None:
    """证书文件缺失时应返回 None，而不是抛出异常。"""
    plugin = _make_plugin()
    plugin._cert_dir = str(tmp_path / "missing")

    assert plugin._cert_days_left() is None


def test_cert_days_left_parses_openssl_output(tmp_path: Path) -> None:
    """应正确解析 openssl 的 notAfter 输出并换算为剩余天数。"""
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    (cert_dir / "fullchain.pem").write_text("dummy", encoding="utf-8")
    plugin = _make_plugin()
    plugin._cert_dir = str(cert_dir)

    completed = subprocess.CompletedProcess(
        args=["openssl"],
        returncode=0,
        stdout="notAfter=Dec 29 13:44:16 2026 GMT\n",
        stderr="",
    )
    with patch.object(subprocess, "run", return_value=completed):
        days = plugin._cert_days_left()

    assert days is not None
    assert days > 0


def test_deploy_certificate_rejects_empty_input() -> None:
    """空内容应被拒绝，且不写入任何文件。"""
    plugin = _make_plugin()

    ok, message = plugin.deploy_certificate("", "")

    assert ok is False
    assert "不能为空" in message or "格式不正确" in message


def test_deploy_certificate_rejects_invalid_pem() -> None:
    """格式不合法的 PEM 应被拒绝。"""
    plugin = _make_plugin()

    ok, message = plugin.deploy_certificate("bad cert", "bad key")

    assert ok is False
    assert "格式不正确" in message


def test_deploy_certificate_rolls_back_on_mismatch(tmp_path: Path) -> None:
    """证书与私钥不匹配时应回滚，不留下错误文件。"""
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    (cert_dir / "fullchain.pem").write_text("original-cert", encoding="utf-8")
    (cert_dir / "privkey.pem").write_text("original-key", encoding="utf-8")

    plugin = _make_plugin()
    plugin._cert_dir = str(cert_dir)

    cert_pem = "-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----"
    key_pem = "-----BEGIN PRIVATE KEY-----\nBBB\n-----END PRIVATE KEY-----"

    with patch.object(plugin, "_verify_certificate_pair", return_value=(False, "证书与私钥不匹配")):
        ok, message = plugin.deploy_certificate(cert_pem, key_pem)

    assert ok is False
    assert "已回滚" in message
    # 原文件应被恢复
    assert (cert_dir / "fullchain.pem").read_text(encoding="utf-8") == "original-cert"
    assert (cert_dir / "privkey.pem").read_text(encoding="utf-8") == "original-key"


def test_deploy_certificate_success_reloads_nginx(tmp_path: Path) -> None:
    """校验通过时应写入文件并重载 nginx。"""
    cert_dir = tmp_path / "certs"
    plugin = _make_plugin()
    plugin._cert_dir = str(cert_dir)
    plugin._notify = False

    cert_pem = "-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----"
    key_pem = "-----BEGIN PRIVATE KEY-----\nBBB\n-----END PRIVATE KEY-----"

    with patch.object(plugin, "_verify_certificate_pair", return_value=(True, "")), \
         patch.object(plugin, "_reload_nginx", return_value=(True, "")) as mock_reload:
        ok, message = plugin.deploy_certificate(cert_pem, key_pem)

    assert ok is True
    assert "部署成功" in message
    mock_reload.assert_called_once()
    assert (cert_dir / "fullchain.pem").is_file()
    assert (cert_dir / "privkey.pem").is_file()


def test_issue_certificate_requires_domain() -> None:
    """缺少域名时应直接返回失败。"""
    plugin = _make_plugin()

    ok, message = plugin.issue_certificate("", "dns_ali", "key", "secret")

    assert ok is False
    assert "域名" in message


def test_issue_certificate_requires_credentials() -> None:
    """缺少凭据 1 时应直接返回失败。"""
    plugin = _make_plugin()

    ok, message = plugin.issue_certificate("example.com", "dns_ali", "", "")

    assert ok is False
    assert "凭据 1" in message


def test_issue_certificate_requires_provider() -> None:
    """缺少服务商时应直接返回失败。"""
    plugin = _make_plugin()

    ok, message = plugin.issue_certificate("example.com", "", "key", "secret")

    assert ok is False
    assert "服务商" in message


def test_issue_certificate_reports_missing_acme(tmp_path: Path) -> None:
    """acme.sh 不存在时应返回明确提示。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "no-acme")

    ok, message = plugin.issue_certificate("example.com", "dns_ali", "key", "secret")

    assert ok is False
    assert "acme.sh 不存在" in message


def test_issue_certificate_reports_missing_dns_hook(tmp_path: Path) -> None:
    """缺少 DNS 插件脚本时应返回明确提示。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    ok, message = plugin.issue_certificate("example.com", "dns_ali", "key", "secret")

    assert ok is False
    assert "缺少 DNS 插件" in message
    assert "下载" in message


def test_download_dnsapi_rejects_invalid_name() -> None:
    """服务商名含非法字符时应被拒绝，避免路径穿越。"""
    plugin = _make_plugin()

    ok, message = plugin.download_dnsapi("../etc/passwd")

    assert ok is False
    assert "只能包含字母" in message


def test_download_dnsapi_rejects_empty_name() -> None:
    """服务商名为空时应被拒绝。"""
    plugin = _make_plugin()

    ok, message = plugin.download_dnsapi("")

    assert ok is False
    assert "服务商" in message


def test_download_dnsapi_reports_network_failure(tmp_path: Path) -> None:
    """下载命令失败时应返回网络错误提示。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "acme")

    with patch.object(plugin, "_run_command", return_value=None):
        ok, message = plugin.download_dnsapi("dns_ali")

    assert ok is False
    assert "下载失败" in message


def test_download_dnsapi_rejects_not_found_response(tmp_path: Path) -> None:
    """GitHub 返回 Not Found 时应识别为服务商不存在。"""
    acme_home = tmp_path / "acme"
    dnsapi_dir = acme_home / "dnsapi"
    dnsapi_dir.mkdir(parents=True)
    # 模拟 curl 把 JSON 错误体写入目标文件
    (dnsapi_dir / "dns_notexist.sh").write_text(
        '{"message":"Not Found"}', encoding="utf-8"
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    with patch.object(plugin, "_run_command", return_value=""):
        ok, message = plugin.download_dnsapi("dns_notexist")

    assert ok is False
    assert "不存在" in message
    # 错误文件应被清理
    assert not (dnsapi_dir / "dns_notexist.sh").exists()


def test_download_dnsapi_succeeds(tmp_path: Path) -> None:
    """下载成功时应保留脚本并设置可执行权限。"""
    acme_home = tmp_path / "acme"
    dnsapi_dir = acme_home / "dnsapi"
    dnsapi_dir.mkdir(parents=True)
    (dnsapi_dir / "dns_ali.sh").write_text(
        "#!/usr/bin/env sh\ndns_ali_info='Aliyun'\n", encoding="utf-8"
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    with patch.object(plugin, "_run_command", return_value=""):
        ok, message = plugin.download_dnsapi("dns_ali")

    assert ok is True
    assert "已下载" in message
    target = dnsapi_dir / "dns_ali.sh"
    assert target.is_file()
    # 脚本需要可执行权限
    assert target.stat().st_mode & 0o100


def test_renew_cert_reports_missing_acme(tmp_path: Path) -> None:
    """acme.sh 不存在时应记录失败并发送通知。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "no-acme")
    plugin._notify = True

    with patch.object(plugin, "post_message") as mock_message:
        plugin.renew_cert()

    mock_message.assert_called_once()
    assert "acme.sh 不存在" in mock_message.call_args.kwargs["text"]


def test_renew_cert_skips_when_not_due(tmp_path: Path) -> None:
    """证书剩余有效期充足且未签发时，不应重载 nginx 或发送通知。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)
    plugin._notify = True

    with patch.object(plugin, "_run_command", return_value="Skipping. Next renewal time is: 2026-11-30"), \
         patch.object(plugin, "_cert_days_left", return_value=89), \
         patch.object(plugin, "_reload_nginx") as mock_reload, \
         patch.object(plugin, "post_message") as mock_message:
        plugin.renew_cert()

    mock_reload.assert_not_called()
    mock_message.assert_not_called()


def test_renew_cert_reloads_after_success(tmp_path: Path) -> None:
    """acme.sh 输出签发标记时应重载 nginx 并发送成功通知。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)
    plugin._notify = True

    with patch.object(plugin, "_run_command", return_value="Cert success.\nInstalling key"), \
         patch.object(plugin, "_cert_days_left", return_value=89), \
         patch.object(plugin, "_reload_nginx", return_value=(True, "")) as mock_reload, \
         patch.object(plugin, "post_message") as mock_message:
        plugin.renew_cert()

    mock_reload.assert_called_once()
    mock_message.assert_called_once()
    assert "续期成功" in mock_message.call_args.kwargs["title"]


def test_renew_cert_warns_when_still_expiring(tmp_path: Path) -> None:
    """剩余有效期低于告警阈值时应告警，且不重载 nginx。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)
    plugin._notify = True

    with patch.object(plugin, "_run_command", return_value=""), \
         patch.object(plugin, "_cert_days_left", return_value=5), \
         patch.object(plugin, "_reload_nginx") as mock_reload, \
         patch.object(plugin, "post_message") as mock_message:
        plugin.renew_cert()

    mock_reload.assert_not_called()
    mock_message.assert_called_once()
    assert "续期异常" in mock_message.call_args.kwargs["title"]


def test_reload_nginx_skips_on_invalid_config() -> None:
    """nginx 配置校验失败时不得执行重载。"""
    plugin = _make_plugin()
    calls: List[List[str]] = []

    def fake_run(command: List[str], **_kwargs: Any) -> Any:
        """记录调用并让配置校验失败。"""
        calls.append(command)
        return subprocess.CompletedProcess(
            args=command, returncode=1, stdout="", stderr="bad"
        )

    with patch.object(subprocess, "run", side_effect=fake_run):
        ok, message = plugin._reload_nginx()

    assert ok is False
    assert calls == [["nginx", "-t"]]
    assert "校验失败" in message


def test_reload_nginx_succeeds() -> None:
    """配置校验通过时应执行重载。"""
    plugin = _make_plugin()
    calls: List[List[str]] = []

    def fake_run(command: List[str], **_kwargs: Any) -> Any:
        """记录调用并让所有命令成功。"""
        calls.append(command)
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout="", stderr=""
        )

    with patch.object(subprocess, "run", side_effect=fake_run):
        ok, _ = plugin._reload_nginx()

    assert ok is True
    assert calls == [["nginx", "-t"], ["nginx", "-s", "reload"]]


def test_api_deploy_returns_error_for_empty_payload() -> None:
    """API 部署接口对空内容应返回失败。"""
    plugin = _make_plugin()

    result = plugin.api_deploy({})

    assert result["success"] is False
    assert "不能为空" in result["message"]


def test_api_issue_uses_config_fallback() -> None:
    """API 申请接口未传参时应回落到插件配置。"""
    plugin = _make_plugin()
    plugin._domain = ""
    plugin._dns_provider = "dns_ali"
    plugin._dns_key = ""
    plugin._dns_secret = ""

    result = plugin.api_issue({})

    assert result["success"] is False
    assert "域名" in result["message"]


def test_api_issue_prefers_payload_over_config() -> None:
    """API 申请接口传入参数时应覆盖插件配置。"""
    plugin = _make_plugin()
    plugin._domain = "config.example.com"
    plugin._dns_provider = "dns_ali"
    plugin._dns_key = "config-key"
    plugin._dns_secret = "config-secret"

    with patch.object(
        plugin, "issue_certificate", return_value=(True, "ok")
    ) as mock_issue:
        result = plugin.api_issue({
            "domain": "payload.example.com",
            "dns_provider": "dns_cf",
            "dns_key": "payload-key",
            "dns_secret": "payload-secret",
        })

    assert result["success"] is True
    mock_issue.assert_called_once_with(
        "payload.example.com", "dns_cf", "payload-key", "payload-secret"
    )


def test_api_download_dnsapi_uses_config_provider() -> None:
    """下载接口未传参时应使用配置中的服务商。"""
    plugin = _make_plugin()
    plugin._dns_provider = "dns_cf"

    with patch.object(
        plugin, "download_dnsapi", return_value=(True, "ok")
    ) as mock_download:
        result = plugin.api_download_dnsapi({})

    assert result["success"] is True
    mock_download.assert_called_once_with("dns_cf")


def test_api_renew_returns_success() -> None:
    """API 续期接口应触发续期并返回成功。"""
    plugin = _make_plugin()

    with patch.object(plugin, "renew_cert") as mock_renew:
        result = plugin.api_renew()

    assert result["success"] is True
    mock_renew.assert_called_once()


def test_check_domain_rejects_empty() -> None:
    """空域名应被拒绝。"""
    ok, message = CertManager._check_domain("")

    assert ok is False
    assert "未填写" in message


def test_check_domain_rejects_invalid_format() -> None:
    """格式不合法的域名应被拒绝。"""
    ok, message = CertManager._check_domain("not a domain")

    assert ok is False
    assert "格式不正确" in message


def test_check_domain_accepts_wildcard_and_multiple() -> None:
    """泛域名与多域名应被接受。"""
    ok, message = CertManager._check_domain("example.com,*.example.com")

    assert ok is True
    assert "2 个域名" in message


def test_verify_config_stops_at_invalid_domain() -> None:
    """域名不合法时应立即返回，不继续后续检测。"""
    plugin = _make_plugin()

    result = plugin.verify_config("bad domain", "dns_ali", "key", "secret")

    assert result["success"] is False
    assert len(result["checks"]) == 1
    assert result["checks"][0]["name"] == "证书域名"


def test_verify_config_reports_missing_acme(tmp_path: Path) -> None:
    """acme.sh 不存在时应停止在第二步。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "no-acme")

    result = plugin.verify_config("example.com", "dns_ali", "key", "secret")

    assert result["success"] is False
    assert len(result["checks"]) == 2
    assert result["checks"][1]["name"] == "acme.sh"
    assert result["checks"][1]["ok"] is False


def test_verify_config_reports_missing_dns_hook(tmp_path: Path) -> None:
    """缺少 DNS 插件脚本时应停止在第三步。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    result = plugin.verify_config("example.com", "dns_ali", "key", "secret")

    assert result["success"] is False
    assert len(result["checks"]) == 3
    assert result["checks"][2]["name"] == "DNS 插件脚本"
    assert "下载" in result["checks"][2]["message"]


def test_verify_config_reports_missing_credentials(tmp_path: Path) -> None:
    """凭据未填写时应停止在第四步。"""
    acme_home = tmp_path / "acme"
    dnsapi_dir = acme_home / "dnsapi"
    dnsapi_dir.mkdir(parents=True)
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (dnsapi_dir / "dns_ali.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    result = plugin.verify_config("example.com", "dns_ali", "", "")

    assert result["success"] is False
    assert len(result["checks"]) == 4
    assert result["checks"][3]["name"] == "凭据 1"
    assert result["checks"][3]["ok"] is False


def test_verify_config_succeeds_when_connectivity_ok(tmp_path: Path) -> None:
    """全部检测通过时应返回成功。"""
    acme_home = tmp_path / "acme"
    dnsapi_dir = acme_home / "dnsapi"
    dnsapi_dir.mkdir(parents=True)
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (dnsapi_dir / "dns_ali.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    with patch.object(
        plugin, "_check_dns_connectivity", return_value=(True, "凭据有效")
    ):
        result = plugin.verify_config("example.com", "dns_ali", "key", "secret")

    assert result["success"] is True
    assert len(result["checks"]) == 5
    assert result["checks"][4]["name"] == "服务商连通性"
    assert "通过" in result["message"]


def test_verify_config_reports_connectivity_failure(tmp_path: Path) -> None:
    """连通性检测失败时应返回失败并给出原因。"""
    acme_home = tmp_path / "acme"
    dnsapi_dir = acme_home / "dnsapi"
    dnsapi_dir.mkdir(parents=True)
    (acme_home / "acme.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (dnsapi_dir / "dns_ali.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    with patch.object(
        plugin,
        "_check_dns_connectivity",
        return_value=(False, "凭据验证失败：InvalidAccessKeyId"),
    ):
        result = plugin.verify_config("example.com", "dns_ali", "bad", "bad")

    assert result["success"] is False
    assert "InvalidAccessKeyId" in result["message"]


def test_check_dns_connectivity_uses_test_record(tmp_path: Path) -> None:
    """连通性检测应使用固定测试子域，且不触碰真实域名。"""
    plugin = _make_plugin()
    captured: Dict[str, Any] = {}

    def fake_run(command: List[str], **kwargs: Any) -> str:
        """捕获脚本内容以便断言。"""
        captured["script"] = command[-1]
        captured["cwd"] = kwargs.get("cwd")
        return "VERIFY_ADD_OK\nVERIFY_RM_OK\n"

    with patch.object(plugin, "_run_command", side_effect=fake_run):
        ok, message = plugin._check_dns_connectivity(
            "*.example.com", "dns_ali", "key", "secret"
        )

    assert ok is True
    assert "连接正常" in message
    # 泛域名前缀应被剥离
    assert "_acme-challenge-verify.example.com" in captured["script"]
    assert "dns_ali_add" in captured["script"]
    assert "dns_ali_rm" in captured["script"]
    assert captured["cwd"] == "/config/acme.sh"


def test_check_dns_connectivity_reports_add_failure() -> None:
    """写入测试记录失败时应返回失败并提取错误原因。"""
    plugin = _make_plugin()

    with patch.object(
        plugin,
        "_run_command",
        return_value="error: InvalidAccessKeyId.NotFound",
    ):
        ok, message = plugin._check_dns_connectivity(
            "example.com", "dns_ali", "bad", "bad"
        )

    assert ok is False
    assert "InvalidAccessKeyId" in message


def test_check_dns_connectivity_warns_when_cleanup_fails() -> None:
    """记录写入成功但清理失败时应提示用户手动检查。"""
    plugin = _make_plugin()

    with patch.object(plugin, "_run_command", return_value="VERIFY_ADD_OK\n"):
        ok, message = plugin._check_dns_connectivity(
            "example.com", "dns_ali", "key", "secret"
        )

    assert ok is True
    assert "清理失败" in message


def test_extract_verify_error_finds_keyword() -> None:
    """应从输出中提取含错误关键字的行。"""
    output = "some info\nerror: InvalidAccessKeyId\nmore info"

    plugin = _make_plugin()
    with patch.object(plugin, "_read_verify_log", return_value=""):
        result = plugin._extract_verify_error(output)

    assert "InvalidAccessKeyId" in result


def test_extract_verify_error_reads_log_file() -> None:
    """输出无线索时应回退到 acme.sh 日志。"""
    plugin = _make_plugin()

    with patch.object(
        plugin, "_read_verify_log", return_value="SignatureDoesNotMatch"
    ):
        result = plugin._extract_verify_error("no useful info")

    assert "SignatureDoesNotMatch" in result


def test_extract_verify_error_gives_actionable_hint() -> None:
    """完全无线索时应给出可操作的排查建议，而不是「未知错误」。"""
    plugin = _make_plugin()

    with patch.object(plugin, "_read_verify_log", return_value=""):
        result = plugin._extract_verify_error("")

    assert "常见原因" in result
    assert "未知错误" not in result


def test_read_verify_log_returns_empty_when_missing(tmp_path: Path) -> None:
    """日志文件不存在时应返回空字符串，不抛异常。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "no-acme")

    assert plugin._read_verify_log() == ""


def test_read_verify_log_keeps_tail(tmp_path: Path) -> None:
    """日志过长时应只保留末尾若干行。"""
    acme_home = tmp_path / "acme"
    data_dir = acme_home / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "verify.log").write_text(
        "\n".join(f"line{i}" for i in range(100)), encoding="utf-8"
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    result = plugin._read_verify_log()

    assert "line99" in result
    assert "line0\n" not in result


def test_api_verify_uses_config_fallback() -> None:
    """检测接口未传参时应回落到插件配置。"""
    plugin = _make_plugin()
    plugin._domain = "config.example.com"
    plugin._dns_provider = "dns_cf"
    plugin._dns_key = "cf-key"
    plugin._dns_secret = "cf-secret"

    with patch.object(
        plugin, "verify_config", return_value={"success": True}
    ) as mock_verify:
        result = plugin.api_verify({})

    assert result["success"] is True
    mock_verify.assert_called_once_with(
        "config.example.com", "dns_cf", "cf-key", "cf-secret"
    )


def test_normalize_provider_handles_plain_string() -> None:
    """纯字符串应原样返回。"""
    assert CertManager._normalize_provider("dns_cf") == "dns_cf"


def test_normalize_provider_extracts_from_dict() -> None:
    """旧版 VCombobox 存下的对象应被提取为脚本名。"""
    value = {"title": "阿里云（Aliyun）", "value": "dns_ali"}

    assert CertManager._normalize_provider(value) == "dns_ali"


def test_normalize_provider_falls_back_to_default() -> None:
    """空值应回落到默认服务商。"""
    assert CertManager._normalize_provider(None) == "dns_ali"
    assert CertManager._normalize_provider("") == "dns_ali"
    assert CertManager._normalize_provider({}) == "dns_ali"


def test_init_plugin_normalizes_provider_object() -> None:
    """初始化时应把对象形式的服务商配置规范化为脚本名。"""
    plugin = _make_plugin()
    plugin.init_plugin({
        "enabled": True,
        "dns_provider": {"title": "Cloudflare", "value": "dns_cf"},
    })

    assert plugin._dns_provider == "dns_cf"


def test_dns_providers_have_title_and_value() -> None:
    """服务商列表应带中文名称与脚本名，供 item-title/item-value 使用。"""
    for item in CertManager._DNS_PROVIDERS:
        assert isinstance(item, dict), f"{item!r} 不是对象"
        assert item.get("title"), f"{item!r} 缺少中文名称"
        assert item.get("value", "").startswith("dns_"), f"{item!r} 脚本名不合法"


def test_dns_providers_have_unique_values() -> None:
    """服务商脚本名不应重复。"""
    values = [item["value"] for item in CertManager._DNS_PROVIDERS]

    assert len(values) == len(set(values))


def test_redact_masks_aliyun_credentials() -> None:
    """阿里云凭据应被脱敏。"""
    text = "Ali_Key=LTAI5tExampleKeyId0000\nAli_Secret=ExampleSecretValue0000000000000000"

    result = CertManager._redact(text)

    assert "LTAI5tExampleKeyId0000" not in result
    assert "ExampleSecretValue0000000000000000" not in result
    assert "Ali_Key=***" in result
    assert "Ali_Secret=***" in result


def test_redact_masks_quoted_values() -> None:
    """带引号的凭据值也应被脱敏。"""
    text = 'Ali_Secret="secret-value-here"'

    result = CertManager._redact(text)

    assert "secret-value-here" not in result


def test_redact_masks_various_providers() -> None:
    """各服务商的凭据字段都应被覆盖。"""
    cases = [
        "CF_Token=abcdef123456",
        "DP_Key=dnspod-token",
        "HUAWEICLOUD_Password=mypassword",
        "PORKBUN_SECRET_API_KEY=sk_live_abc",
        "GD_Secret=godaddy-secret",
        "AccessKeyId=AKIAIOSFODNN7EXAMPLE",
    ]

    for case in cases:
        result = CertManager._redact(case)
        assert "***" in result, f"未脱敏：{case}"
        # 原始值不应残留
        original_value = case.split("=", 1)[1]
        assert original_value not in result, f"残留原值：{case}"


def test_redact_keeps_normal_lines() -> None:
    """不含凭据的普通日志行应保持原样。"""
    text = "证书无需续期，剩余有效期 89 天"

    assert CertManager._redact(text) == text


def test_redact_handles_empty_input() -> None:
    """空输入应返回空字符串。"""
    assert CertManager._redact("") == ""


def test_read_verify_log_redacts_credentials(tmp_path: Path) -> None:
    """读取检测日志时也应脱敏，避免凭据进入界面。"""
    acme_home = tmp_path / "acme"
    data_dir = acme_home / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "verify.log").write_text(
        "Ali_Key=LTAI5tExampleKeyId0000\nsome other line",
        encoding="utf-8",
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    result = plugin._read_verify_log()

    assert "LTAI5tExampleKeyId0000" not in result
    assert "***" in result


def test_format_cert_time_converts_to_beijing() -> None:
    """openssl 的 UTC 时间应转换为北京时间（UTC+8）。"""
    result = CertManager._format_cert_time("Sep 30 13:44:17 2026 GMT")

    assert result == "2026-09-30 21:44:17"


def test_format_cert_time_handles_single_digit_day() -> None:
    """个位数日期（openssl 用空格补齐）应正确解析。"""
    result = CertManager._format_cert_time("Jan  5 00:00:00 2027 GMT")

    assert result == "2027-01-05 08:00:00"


def test_format_cert_time_crosses_day_boundary() -> None:
    """UTC 晚间时间转换后应正确跨日。"""
    result = CertManager._format_cert_time("Dec 31 20:00:00 2026 GMT")

    assert result == "2027-01-01 04:00:00"


def test_format_cert_time_returns_empty_for_empty_input() -> None:
    """空输入应返回空字符串。"""
    assert CertManager._format_cert_time("") == ""


def test_format_cert_time_keeps_unparsable_input() -> None:
    """无法解析的输入应原样返回，不抛异常。"""
    assert CertManager._format_cert_time("invalid") == "invalid"


def test_collect_status_formats_times(tmp_path: Path) -> None:
    """状态汇总中的生效与到期时间应是北京时间格式。"""
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    (cert_dir / "fullchain.pem").write_text("dummy", encoding="utf-8")

    plugin = _make_plugin()
    plugin._cert_dir = str(cert_dir)

    openssl_output = (
        "subject=CN=example.com\n"
        "issuer=C=US, O=Let's Encrypt\n"
        "notBefore=Sep 30 13:44:17 2026 GMT\n"
        "notAfter=Dec 29 13:44:16 2026 GMT\n"
        "X509v3 Subject Alternative Name:\n"
        "    DNS:example.com\n"
    )

    with patch.object(plugin, "_openssl_output", return_value=openssl_output), \
         patch.object(plugin, "_cert_days_left", return_value=89):
        status = plugin._collect_status()

    assert status["not_before"] == "2026-09-30 21:44:17"
    assert status["not_after"] == "2026-12-29 21:44:16"
    # 不应残留英文月份或 GMT 字样
    assert "GMT" not in status["not_before"]
    assert "Sep" not in status["not_before"]


def test_install_acme_creates_directories(tmp_path: Path) -> None:
    """全新安装应创建 acme.sh、data、dnsapi 目录结构。"""
    acme_home = tmp_path / "acme"
    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)
    plugin._notify = False

    def fake_run(command, env=None, cwd=None):
        # 版本查询调用不含 -o，直接返回版本号
        if "-o" not in command:
            return "v3.1.6"
        # 模拟 curl 成功写入有效脚本
        target = Path(command[command.index("-o") + 1])
        target.write_text("#!/usr/bin/env sh\nVER=3.1.6\n", encoding="utf-8")
        return ""

    with patch.object(plugin, "_run_command", side_effect=fake_run):
        ok, message = plugin.install_acme()

    assert ok is True
    assert "安装成功" in message
    assert (acme_home / "data").is_dir()
    assert (acme_home / "dnsapi").is_dir()
    assert (acme_home / "acme.sh").is_file()


def test_install_acme_reports_upgrade_when_exists(tmp_path: Path) -> None:
    """已安装时应报告升级而非安装。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    (acme_home / "acme.sh").write_text("#!/usr/bin/env sh\nVER=3.0.0\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)
    plugin._notify = False

    def fake_run(command, env=None, cwd=None):
        if "-o" not in command:
            return "v3.1.6"
        target = Path(command[command.index("-o") + 1])
        target.write_text("#!/usr/bin/env sh\nVER=3.1.6\n", encoding="utf-8")
        return ""

    with patch.object(plugin, "_run_command", side_effect=fake_run):
        ok, message = plugin.install_acme()

    assert ok is True
    assert "升级成功" in message


def test_install_acme_rolls_back_on_invalid_download(tmp_path: Path) -> None:
    """下载内容无效时应回滚，保留原有 acme.sh。"""
    acme_home = tmp_path / "acme"
    acme_home.mkdir()
    original = "#!/usr/bin/env sh\nVER=3.0.0\n# original\n"
    (acme_home / "acme.sh").write_text(original, encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    def fake_run(command, env=None, cwd=None):
        # 模拟 GitHub API 返回 JSON 错误体
        target = Path(command[command.index("-o") + 1])
        target.write_text('{"message": "Not Found"}', encoding="utf-8")
        return ""

    with patch.object(plugin, "_run_command", side_effect=fake_run):
        ok, message = plugin.install_acme()

    assert ok is False
    assert "回滚" in message
    assert (acme_home / "acme.sh").read_text(encoding="utf-8") == original
    assert not (acme_home / "acme.sh.bak").exists()


def test_install_acme_removes_file_when_fresh_install_fails(tmp_path: Path) -> None:
    """全新安装失败时不应留下无效文件。"""
    acme_home = tmp_path / "acme"
    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    def fake_run(command, env=None, cwd=None):
        target = Path(command[command.index("-o") + 1])
        target.write_text('{"message": "Not Found"}', encoding="utf-8")
        return ""

    with patch.object(plugin, "_run_command", side_effect=fake_run):
        ok, _ = plugin.install_acme()

    assert ok is False
    assert not (acme_home / "acme.sh").exists()


def test_install_acme_reports_network_failure(tmp_path: Path) -> None:
    """下载命令失败时应返回网络错误提示。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path / "acme")

    with patch.object(plugin, "_run_command", return_value=None):
        ok, message = plugin.install_acme()

    assert ok is False
    assert "网络" in message


def test_is_valid_acme_script_rejects_json(tmp_path: Path) -> None:
    """GitHub API 的 JSON 错误体不应被当作有效脚本。"""
    bad = tmp_path / "bad.sh"
    bad.write_text('{"message": "Not Found"}', encoding="utf-8")

    assert CertManager._is_valid_acme_script(bad) is False


def test_is_valid_acme_script_rejects_empty(tmp_path: Path) -> None:
    """空文件不应被当作有效脚本。"""
    empty = tmp_path / "empty.sh"
    empty.write_text("", encoding="utf-8")

    assert CertManager._is_valid_acme_script(empty) is False


def test_is_valid_acme_script_accepts_real_script(tmp_path: Path) -> None:
    """含 shebang 与版本声明的脚本应被接受。"""
    good = tmp_path / "acme.sh"
    good.write_text("#!/usr/bin/env sh\n\nVER=3.1.6\n", encoding="utf-8")

    assert CertManager._is_valid_acme_script(good) is True


def test_acme_version_extracts_number(tmp_path: Path) -> None:
    """应从 --version 输出中提取版本号。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path)

    with patch.object(
        plugin,
        "_run_command",
        return_value="https://github.com/acmesh-official/acme.sh\nv3.1.6",
    ):
        version = plugin._acme_version(tmp_path / "acme.sh")

    assert version == "v3.1.6"


def test_api_install_acme_returns_result() -> None:
    """安装接口应返回 install_acme 的结果。"""
    plugin = _make_plugin()

    with patch.object(
        plugin, "install_acme", return_value=(True, "acme.sh 安装成功")
    ):
        result = plugin.api_install_acme()

    assert result["success"] is True
    assert "安装成功" in result["message"]


def test_config_form_has_issue_button() -> None:
    """配置页应提供「申请证书」入口。"""
    plugin = _make_plugin()
    form, _ = plugin.get_form()

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "申请证书" in form_str
    assert "plugin/CertManager/issue" in form_str


def test_config_form_has_deploy_section() -> None:
    """配置页应提供手动部署证书的输入框与按钮。"""
    plugin = _make_plugin()
    form, _ = plugin.get_form()

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "deploy_cert" in form_str
    assert "deploy_key" in form_str
    assert "plugin/CertManager/deploy" in form_str


def test_config_form_issue_passes_model_values() -> None:
    """申请按钮应把配置页的域名与凭据传给接口。"""
    plugin = _make_plugin()
    form, _ = plugin.get_form()

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "model.domain" in form_str
    assert "model.dns_provider" in form_str
    assert "model.dns_key" in form_str
    assert "model.dns_secret" in form_str


def test_detail_page_has_no_buttons() -> None:
    """详情页不支持 model 绑定，不应包含按钮。"""
    plugin = _make_plugin()
    page = plugin.get_page()

    import json

    page_str = json.dumps(page, ensure_ascii=False)
    assert '"VBtn"' not in page_str
    assert "onclick" not in page_str


def test_detail_page_points_to_config() -> None:
    """详情页应引导用户到配置页操作。"""
    plugin = _make_plugin()
    page = plugin.get_page()

    import json

    page_str = json.dumps(page, ensure_ascii=False)
    assert "配置页" in page_str


def test_plugin_desc_covers_core_capabilities() -> None:
    """插件描述应简洁并覆盖核心能力。"""
    desc = CertManager.plugin_desc
    assert "证书" in desc
    assert "部署" in desc
    assert "申请" in desc
    assert "续期" in desc


def test_plugin_icon_is_local_file() -> None:
    """插件图标应指向仓库内的图标文件，而非不存在的远程路径。"""
    assert CertManager.plugin_icon == "certmanager.png"
    assert not CertManager.plugin_icon.startswith("http")


def test_lookup_credentials_extracts_fields(tmp_path: Path) -> None:
    """应从脚本中提取凭据字段名。"""
    acme_home = tmp_path / "acme"
    dnsapi = acme_home / "dnsapi"
    dnsapi.mkdir(parents=True)
    (dnsapi / "dns_test.sh").write_text(
        'Ali_Key="${Ali_Key:-$(_readaccountconf_mutable Ali_Key)}"\n'
        'Ali_Secret="${Ali_Secret:-$(_readaccountconf_mutable Ali_Secret)}"\n',
        encoding="utf-8",
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    ok, message, fields = plugin.lookup_credentials("dns_test")

    assert ok is True
    assert fields == ["Ali_Key", "Ali_Secret"]
    assert "2 个" in message


def test_lookup_credentials_deduplicates_fields(tmp_path: Path) -> None:
    """重复出现的字段名应去重且保持顺序。"""
    acme_home = tmp_path / "acme"
    dnsapi = acme_home / "dnsapi"
    dnsapi.mkdir(parents=True)
    (dnsapi / "dns_test.sh").write_text(
        "_readaccountconf_mutable CF_Token\n"
        "_readaccountconf_mutable CF_Account_ID\n"
        "_readaccountconf_mutable CF_Token\n",
        encoding="utf-8",
    )

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    _, _, fields = plugin.lookup_credentials("dns_test")

    assert fields == ["CF_Token", "CF_Account_ID"]


def test_lookup_credentials_rejects_invalid_name(tmp_path: Path) -> None:
    """非法脚本名应被拒绝，不发起下载。"""
    plugin = _make_plugin()
    plugin._acme_home = str(tmp_path)

    ok, message, fields = plugin.lookup_credentials("bad name")

    assert ok is False
    assert "不合法" in message
    assert fields == []


def test_lookup_credentials_downloads_when_missing(tmp_path: Path) -> None:
    """脚本不存在时应先自动下载。"""
    acme_home = tmp_path / "acme"
    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    def fake_download(provider: str):
        dnsapi = acme_home / "dnsapi"
        dnsapi.mkdir(parents=True, exist_ok=True)
        (dnsapi / f"{provider}.sh").write_text(
            "_readaccountconf_mutable DP_Id\n_readaccountconf_mutable DP_Key\n",
            encoding="utf-8",
        )
        return True, "已下载"

    with patch.object(plugin, "download_dnsapi", side_effect=fake_download):
        ok, _, fields = plugin.lookup_credentials("dns_dp")

    assert ok is True
    assert fields == ["DP_Id", "DP_Key"]


def test_lookup_credentials_reports_no_fields(tmp_path: Path) -> None:
    """脚本未声明凭据字段时应给出说明。"""
    acme_home = tmp_path / "acme"
    dnsapi = acme_home / "dnsapi"
    dnsapi.mkdir(parents=True)
    (dnsapi / "dns_test.sh").write_text("# 无凭据\n", encoding="utf-8")

    plugin = _make_plugin()
    plugin._acme_home = str(acme_home)

    ok, message, fields = plugin.lookup_credentials("dns_test")

    assert ok is False
    assert "未声明凭据字段" in message
    assert fields == []


def test_api_lookup_credentials_returns_fields(tmp_path: Path) -> None:
    """查询接口应返回字段列表。"""
    plugin = _make_plugin()

    with patch.object(
        plugin, "lookup_credentials", return_value=(True, "ok", ["A", "B"])
    ):
        result = plugin.api_lookup_credentials({"provider": "dns_ali"})

    assert result["success"] is True
    assert result["fields"] == ["A", "B"]


def test_config_form_has_credential_lookup_button() -> None:
    """配置页应提供凭据字段查询入口。"""
    plugin = _make_plugin()
    form, _ = plugin.get_form()

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "查询当前服务商需要哪些凭据" in form_str
    assert "plugin/CertManager/credentials" in form_str


def test_config_form_has_no_static_table() -> None:
    """配置页不应再包含静态对照表。"""
    plugin = _make_plugin()
    form, _ = plugin.get_form()

    import json

    form_str = json.dumps(form, ensure_ascii=False)
    assert "VExpansionPanels" not in form_str
    assert "对照表" not in form_str
