import base64
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse


HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
BASE32_RE = re.compile(r"^[A-Z2-7a-z2-7]{32}$")


def normalize_info_hash(value: object) -> Optional[str]:
    """Return a 40-character lowercase v1 info hash."""

    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None

    raw_hash = value.strip()
    if HEX40_RE.fullmatch(raw_hash):
        return raw_hash.lower()
    if not BASE32_RE.fullmatch(raw_hash):
        return None

    try:
        decoded = base64.b32decode(raw_hash.upper(), casefold=True)
    except (ValueError, TypeError):
        return None
    return decoded.hex() if len(decoded) == 20 else None


def extract_info_hash(magnet: str) -> Optional[str]:
    """Extract the first valid BTIH from a magnet URI."""

    if not isinstance(magnet, str):
        return None
    parsed = urlparse(magnet.strip())
    if parsed.scheme.lower() != "magnet":
        return None

    for value in parse_qs(parsed.query, keep_blank_values=True).get("xt", []):
        prefix = "urn:btih:"
        if value.lower().startswith(prefix):
            info_hash = normalize_info_hash(value[len(prefix) :])
            if info_hash:
                return info_hash
    return None


def mask_hash(info_hash: Optional[str]) -> str:
    if not info_hash:
        return "unknown"
    return f"{info_hash[:8]}..."
