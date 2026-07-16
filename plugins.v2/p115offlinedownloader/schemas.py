from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class NormalizedDownload:
    """Result of converting MoviePilot download input to a v1 magnet."""

    magnet: Optional[str] = None
    info_hash: Optional[str] = None
    source_type: str = ""
    torrent_name: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class SubmitResult:
    success: bool
    message: str


@dataclass(frozen=True)
class ConnectionResult:
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
