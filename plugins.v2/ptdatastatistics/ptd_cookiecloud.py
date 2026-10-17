"""Decrypt PT-Depiler backups received by the plugin's compatibility endpoint."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


_METRIC_KEYS = {
    "seedingBonus",
    "bonusPerHour",
    "seedingBonusPerHour",
    "uploads",
    "levelName",
}
_KNOWN_ALIASES = {
    "mteam": ("馒头", "mteam", "m-team"),
    "audiences": ("观众", "audiences", "audience"),
    "rainbow": ("彩虹岛", "rainbow", "chdbits"),
    "hhan": ("憨憨", "hhan", "hhanclub"),
    "spring": ("春天", "spring", "spring-sunday"),
    "hdsky": ("天空", "hdsky", "skyey"),
    "pter": ("猫站", "pter", "pterclub"),
    "pttime": ("PT时间", "PTTime"),
    "hdhome": ("家园", "hdhome"),
    "ourbits": ("我堡", "ourbits"),
}


class PTDCookieCloudError(RuntimeError):
    """A safe, user-facing PTD CookieCloud import failure."""


@dataclass(frozen=True)
class PTDBackup:
    """The current PTD backup and the values used by this plugin."""

    name: str
    metrics: list[dict[str, Any]]
    metadata: dict[str, Any]


def _evp_bytes_to_key(password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """Match the OpenSSL/CryptoJS passphrase derivation used by PTD."""

    derived = b""
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()  # noqa: S324 - protocol compatibility
        derived += previous
    return derived[:32], derived[32:48]


def _decrypt(encrypted: str, *, uuid: str, password: str, crypto_type: str = "") -> dict[str, Any]:
    try:
        ciphertext = base64.b64decode(encrypted, validate=True)
        passphrase = hashlib.md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()  # noqa: S324
        if crypto_type == "aes-128-cbc-fixed":
            key, iv, payload = passphrase, bytes(16), ciphertext
        else:
            if not ciphertext.startswith(b"Salted__") or len(ciphertext) < 32:
                raise ValueError("missing CryptoJS salt")
            key, iv = _evp_bytes_to_key(passphrase, ciphertext[8:16])
            payload = ciphertext[16:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(payload) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        clear = unpadder.update(padded) + unpadder.finalize()
        value = json.loads(clear.decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        raise PTDCookieCloudError("CookieCloud 数据解密失败，请检查 UUID 和密码") from error
    if not isinstance(value, dict):
        raise PTDCookieCloudError("CookieCloud 解密后的数据结构不受支持")
    return value


def _record_score(record: dict[str, Any], day_key: str = "") -> tuple[float, str]:
    try:
        updated = float(record.get("updateAt") or 0)
    except (TypeError, ValueError):
        updated = 0
    return updated, day_key


def _latest_number(
    records: list[tuple[str, dict[str, Any]]], key: str
) -> float | None:
    """Return the newest available value when PTD omits a metric on some days."""

    for _day_key, candidate in sorted(
        records,
        key=lambda item: _record_score(item[1], item[0]),
        reverse=True,
    ):
        value = _number(candidate.get(key))
        if value is not None:
            return value
    return None


def _extract_metrics(user_info: Any) -> list[dict[str, Any]]:
    if isinstance(user_info, dict) and isinstance(user_info.get("userInfo"), (dict, list)):
        user_info = user_info["userInfo"]
    grouped_records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    if isinstance(user_info, list):
        for record in user_info:
            if not isinstance(record, dict):
                continue
            site_key = str(record.get("site") or "").strip()
            if not site_key:
                continue
            grouped_records.setdefault(site_key, []).append(
                (str(record.get("date") or ""), record)
            )
    elif not isinstance(user_info, dict):
        raise PTDCookieCloudError("PTD 用户信息的数据结构不受支持")

    output: list[dict[str, Any]] = []
    histories = grouped_records.items() if isinstance(user_info, list) else user_info.items()
    for site_key, history in histories:
        records: list[tuple[str, dict[str, Any]]] = []
        if isinstance(history, list):
            records.extend(history)
        elif isinstance(history, dict) and (_METRIC_KEYS & set(history)):
            records.append(("", history))
        elif isinstance(history, dict):
            records.extend((str(day), value) for day, value in history.items() if isinstance(value, dict))
        if not records:
            continue
        day_key, record = max(records, key=lambda item: _record_score(item[1], item[0]))
        ptd_site = str(record.get("site") or site_key)
        user_level = str(record.get("levelName") or "").strip()
        seeding_points = _number(record.get("seedingBonus"))
        torrent_uploads = _number(record.get("uploads"))
        if torrent_uploads is None:
            torrent_uploads = _latest_number(records, "uploads")
        # Keep PTD's dedicated rates separate whenever both are available.
        bonus_hourly = _number(record.get("bonusPerHour"))
        seeding_points_hourly = _number(record.get("seedingBonusPerHour"))
        if seeding_points_hourly is None:
            seeding_points_hourly = _latest_number(records, "seedingBonusPerHour")
        # Match PTD's levelRequirementUnMet calculation exactly: prefer the
        # dedicated seeding-points rate and fall back to bonusPerHour when PTD
        # did not store seedingBonusPerHour for the site.
        if seeding_points_hourly is None and bonus_hourly is not None:
            seeding_points_hourly = bonus_hourly
        if (
            seeding_points is None
            and bonus_hourly is None
            and seeding_points_hourly is None
            and torrent_uploads is None
            and not user_level
        ):
            continue
        output.append(
            {
                "ptd_site": ptd_site,
                "site_name": str(record.get("siteName") or record.get("name") or ""),
                "user_level": user_level,
                "seeding_points": seeding_points,
                "estimated_bonus_hourly": bonus_hourly,
                "seeding_points_hourly": seeding_points_hourly,
                "torrent_uploads": torrent_uploads,
                "source_updated_at": str(record.get("updateAt") or day_key or ""),
            }
        )
    if not output:
        raise PTDCookieCloudError("当前 PTD 备份中没有时魔或做种积分数据")
    return output


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _identity(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _hostname(value: Any) -> str:
    text = str(value or "").strip().casefold()
    parsed = urlparse(text if "://" in text else f"//{text}")
    return (parsed.hostname or text.split("/", 1)[0]).removeprefix("www.")


def _find_mapping(value: Any, key_name: str) -> dict[str, Any]:
    if not isinstance(value, (dict, list)):
        return {}
    if isinstance(value, dict):
        direct = value.get(key_name)
        if isinstance(direct, dict):
            return direct
        for nested in value.values():
            found = _find_mapping(nested, key_name)
            if found:
                return found
    else:
        for nested in value:
            found = _find_mapping(nested, key_name)
            if found:
                return found
    return {}


def _mapping_values(mapping: dict[str, Any], site_key: str) -> list[str]:
    values: list[str] = []
    direct = mapping.get(site_key)
    if isinstance(direct, list):
        values.extend(str(item) for item in direct)
    elif direct not in (None, ""):
        values.append(str(direct))
    wanted = _identity(site_key)
    for key, value in mapping.items():
        candidates = value if isinstance(value, list) else [value]
        if any(_identity(candidate) == wanted for candidate in candidates):
            values.append(str(key))
    return values


def _manual_mappings(raw: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for line in str(raw or "").replace(",", "\n").splitlines():
        if "=" not in line:
            continue
        source, target = line.split("=", 1)
        if _identity(source) and target.strip():
            output[_identity(source)] = target.strip()
    return output


def match_metrics(
    metrics: list[dict[str, Any]],
    metadata: dict[str, Any],
    configured_sites: list[dict[str, Any]],
    manual_mappings: str = "",
) -> list[dict[str, Any]]:
    """Match PTD site identifiers to MP sites without importing other fields."""

    host_map = _find_mapping(metadata, "siteHostMap")
    name_map = _find_mapping(metadata, "siteNameMap")
    manual = _manual_mappings(manual_mappings)
    matched: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        ptd_site = str(metric.get("ptd_site") or "")
        ptd_identity = _identity(ptd_site)
        candidates = [ptd_site, metric.get("site_name") or ""]
        candidates.extend(_mapping_values(host_map, ptd_site))
        candidates.extend(_mapping_values(name_map, ptd_site))
        candidates.extend(_KNOWN_ALIASES.get(ptd_identity, ()))
        if ptd_identity in manual:
            candidates.insert(0, manual[ptd_identity])
        identities = {_identity(value) for value in candidates if value}
        hostnames = {_hostname(value) for value in candidates if value}
        selected = None
        for site in configured_sites:
            domain = _hostname(site.get("domain"))
            name = _identity(site.get("name"))
            domain_identity = _identity(domain)
            if (
                domain in hostnames
                or name in identities
                or domain_identity in identities
                or any(identity and identity in domain_identity for identity in identities)
            ):
                selected = site
                break
        if not selected:
            continue
        domain = str(selected.get("domain") or "").casefold()
        matched[domain] = {
            **metric,
            "site_id": selected.get("id"),
            "domain": domain,
            "site_name": selected.get("name") or metric.get("site_name") or ptd_site,
        }
    return list(matched.values())


def _backup_item(data: dict[str, Any], name: str) -> Any:
    for key, value in data.items():
        if str(key).casefold() == name.casefold():
            return value
    return None


def parse_backup_response(*, response: dict[str, Any], uuid: str, password: str) -> PTDBackup:
    """Decrypt one CookieCloud response and extract the PTD metrics we support."""

    if not uuid.strip() or not password:
        raise PTDCookieCloudError("请填写 PTD CookieCloud UUID 和密码")
    encrypted = response.get("encrypted")
    if not isinstance(encrypted, str) or not encrypted:
        raise PTDCookieCloudError("CookieCloud 中没有找到 PTD 备份数据")
    payload = _decrypt(
        encrypted,
        uuid=uuid.strip(),
        password=password,
        crypto_type=str(response.get("crypto_type") or ""),
    )
    ptd_data = payload.get("ptd_data")
    if not isinstance(ptd_data, dict):
        raise PTDCookieCloudError("CookieCloud 当前内容不是 PTD 备份，请为 PTD 使用独立 UUID")
    user_info = _backup_item(ptd_data, "userInfo")
    if user_info is None:
        raise PTDCookieCloudError("PTD 备份中缺少用户信息，请在备份项目中勾选“用户信息”")
    metadata = _backup_item(ptd_data, "metadata")
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    backup_name = str(manifest.get("fileName") or "CookieCloud 当前备份")
    return PTDBackup(
        name=backup_name,
        metrics=_extract_metrics(user_info),
        metadata=metadata if isinstance(metadata, dict) else {},
    )
