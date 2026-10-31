"""Standard-library-only installer input, declarative Provider forms and summary."""
import atexit
import codecs
import json
import os
import shutil
from pathlib import Path
import termios
import unicodedata


def _display_width(char):
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


class TerminalUI:
    def __init__(self, device="/dev/tty"):
        self.fd = os.open(device, os.O_RDWR | getattr(os, "O_NOCTTY", 0))
        atexit.register(self.close)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, text):
        data = str(text).encode("utf-8")
        while data:
            count = os.write(self.fd, data)
            data = data[count:]

    def _line(self, prompt, secret=False):
        saved = termios.tcgetattr(self.fd)
        settings = list(saved)
        settings[6] = list(saved[6])
        settings[3] &= ~(termios.ICANON | termios.ECHO | getattr(termios, "ECHONL", 0))
        settings[0] |= termios.ICRNL
        settings[0] &= ~(getattr(termios, "IGNCR", 0) | getattr(termios, "INLCR", 0))
        settings[6][termios.VMIN] = 1
        settings[6][termios.VTIME] = 0
        buffer = []
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        escape = 0

        def erase():
            if buffer:
                char = buffer.pop()
                if not secret:
                    self.write("\b \b" * _display_width(char))

        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, settings)
            self.write(prompt)
            while True:
                byte = os.read(self.fd, 1)
                if not byte:
                    raise EOFError("终端输入已关闭")
                if escape:
                    if escape == 1:
                        escape = 2 if byte in (b"[", b"O") else 0
                    elif 0x40 <= byte[0] <= 0x7e:
                        escape = 0
                    continue
                if byte == b"\x1b":
                    escape = 1
                    continue
                if byte in (b"\n", b"\r"):
                    self.write("\n")
                    return "".join(buffer)
                if byte in (b"\x08", b"\x7f"):
                    decoder.reset()
                    erase()
                    continue
                if byte == b"\x15":  # Ctrl-U
                    decoder.reset()
                    while buffer:
                        erase()
                    continue
                if byte == b"\x17":  # Ctrl-W
                    decoder.reset()
                    while buffer and buffer[-1].isspace():
                        erase()
                    while buffer and not buffer[-1].isspace():
                        erase()
                    continue
                if byte == b"\x03":
                    raise KeyboardInterrupt
                if byte == b"\x04":
                    raise EOFError("用户取消输入")
                if byte[0] < 32:
                    continue
                chars = decoder.decode(byte)
                for char in chars:
                    if char.isprintable():
                        buffer.append(char)
                        if not secret:
                            self.write(char)
        finally:
            termios.tcsetattr(self.fd, termios.TCSANOW, saved)

    def ask(self, label, default="", secret=False, allow_empty=False):
        label = "".join(c for c in str(label) if c.isprintable())
        if secret:
            prompt = str(label) + (" [回车保留]" if default else "") + ": "
        else:
            prompt = str(label) + (f" [{default}]" if default != "" else "") + ": "
        try:
            value = self._line(prompt, secret=secret).strip()
        except (EOFError, KeyboardInterrupt):
            self.write("\n已取消，终端设置已恢复。\n")
            raise SystemExit(1)
        if allow_empty and value == "!clear":
            return ""
        return value if value else default


def _field_type(default):
    if type(default) is bool:
        return "bool"
    if type(default) is int:
        return "int"
    if type(default) is float:
        return "float"
    if isinstance(default, (dict, list)):
        return "json"
    return "str"


def configure_provider(driver, old, base, ui):
    """Ask every DEFAULT_CONFIG key; CONFIG_FIELDS only customizes presentation."""
    defaults = driver.DEFAULT_CONFIG
    specs = getattr(driver, "CONFIG_FIELDS", {})
    if not isinstance(specs, dict) or set(specs) - set(defaults):
        raise ValueError("CONFIG_FIELDS必须是DEFAULT_CONFIG字段的子集")
    result = {key: old.get(key, value) for key, value in defaults.items()}
    while True:
        for key, fallback in defaults.items():
            spec = specs.get(key, {})
            if not isinstance(spec, dict):
                raise ValueError("字段声明必须为对象")
            kind = spec.get("type", _field_type(fallback))
            label = spec.get("label", key)
            secret = bool(spec.get("secret", "KEY" in key or "SECRET" in key or "PASSWORD" in key))
            current = result[key]
            if kind == "path" and spec.get("executable") and isinstance(current, str):
                current = shutil.which(current) or current
            if isinstance(current, str) and current.startswith("请"):
                current = ""
            if spec.get("help"):
                ui.write("  " + str(spec["help"]) + "\n")
            while True:
                if kind == "bool":
                    displayed = "y" if current else "n"
                elif kind == "csv":
                    displayed = ",".join(current) if isinstance(current, list) else ""
                elif kind == "json":
                    displayed = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
                else:
                    displayed = "" if current is None else str(current)
                text = ui.ask(label, displayed, secret=secret, allow_empty=not spec.get("required", False))
                try:
                    if kind == "bool":
                        val = str(text).lower()
                        if val not in ("y", "n", "true", "false", "1", "0", "yes", "no"):
                            raise ValueError("请输入y或n")
                        value = val in ("y", "true", "1", "yes")
                    elif kind == "int":
                        value = int(text)
                    elif kind == "float":
                        import math
                        value = float(text)
                        if not math.isfinite(value):
                            raise ValueError("必须为有限数值")
                    elif kind == "json":
                        value = json.loads(text)
                        if isinstance(fallback, (dict, list)) and type(value) is not type(fallback):
                            raise ValueError("JSON类型与默认值不一致")
                    elif kind == "csv":
                        value = [part.strip() for part in str(text).split(",") if part.strip()]
                    elif kind in ("str", "path"):
                        value = str(text)
                    else:
                        raise ValueError("不支持的字段类型：" + str(kind))
                    if spec.get("required") and (value is None or value == "" or value == []):
                        raise ValueError("不能为空")
                    if kind in ("int", "float"):
                        if "min" in spec and value < spec["min"]:
                            raise ValueError("数值低于允许范围")
                        if "max" in spec and value > spec["max"]:
                            raise ValueError("数值高于允许范围")
                    if "choices" in spec and value not in spec["choices"]:
                        raise ValueError("不在允许选项中")
                    if kind == "path" and spec.get("executable"):
                        path = Path(value)
                        if not path.is_absolute() or not path.is_file() or not os.access(str(path), os.X_OK):
                            raise ValueError("请输入存在且可执行的绝对路径")
                    result[key] = value
                    break
                except (ValueError, TypeError):
                    ui.write("  输入无效，请按字段类型和范围重新填写。\n")
        validator = getattr(driver, "validate_config", None)
        merged = dict(base)
        merged.update(result)
        if not callable(validator):
            return result
        try:
            validator(merged)
            return {key: merged[key] for key in defaults}
        except Exception as exc:
            # Don't echo custom-validator exception text: it may contain secrets.
            ui.write("  驱动参数校验未通过（" + type(exc).__name__ + "）。\n")
            if ui.ask("重新填写此驱动？y/n", "y").lower() != "y":
                raise ValueError("驱动配置取消") from None


def summary_text(*, poll, shared_secret, api_url, selected, query_enabled,
                 peers, config_file, platform, unavailable=()):
    """Only MP entries, local config/service commands and brief notices."""
    def safe(value):
        return "".join(c for c in str(value) if c.isprintable())

    lines = ["", "安装完成", "", "【MP 插件填写一次】",
             "检测方式：" + ("轮询" if poll else "Webhook 推送"),
             "通信密钥：" + safe(shared_secret),
             "采集端 API：" + (api_url if query_enabled else "留空（查询未启用）"),
             "检测/补偿周期：*/1 * * * *"]
    if not poll:
        lines.append("主动心跳：0（使用采集端保活）")
    tokens = []
    for peer in peers:
        if peer.get("provider") == "easytier" and peer.get("cost") == "Local":
            continue
        token = peer.get("hostname") or str(peer.get("ipv4") or "").split("/", 1)[0]
        token = safe(token)
        if token and token not in tokens:
            tokens.append(token)
    lines.append("监控主机候选（按需选填，每行一项；排除采集端本机）：")
    lines.extend("  " + token for token in tokens[:20])
    if not tokens:
        lines.append("  暂无；请在来源恢复后通过查询接口查看节点名")
    elif len(tokens) > 20:
        lines.append("  其余节点通过查询接口查看")
    lines.append("下载器及让位方式：在MP按需选择")
    lines += ["", "【采集端管理】", "配置：" + str(config_file)]
    if platform == "openwrt":
        lines += ["操作：/etc/init.d/tunnel-api {start|stop|restart|status}", "日志：logread -e tunnel"]
    else:
        lines += ["操作：systemctl {start|stop|restart|status} tunnel-api", "日志：journalctl -u tunnel-api -f"]
    if unavailable:
        lines.append("暂不可用来源：" + ", ".join(safe(x) for x in unavailable))
    lines.append("提示：普通更新无需停用MP；通信密钥勿公开，监控名称变化时在MP调整。")
    return "\n".join(lines) + "\n"
