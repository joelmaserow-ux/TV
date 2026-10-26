"""Settings, read from environment variables so the MCP client config can set them."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_client_id() -> str:
    # Stable per machine, so the TV remembers it after you press "Allow" once.
    return "-".join(f"{(uuid.getnode() >> s) & 0xFF:02x}" for s in range(40, -1, -8))


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    mac: str | None
    client_name: str
    client_id: str
    use_cec: bool
    timeout: float
    rendering_control_url: str | None
    dial_url: str | None
    # "auto", "legacy" (port 55) or "encrypted" (PIN pairing, ports 8000/8080)
    method: str = "auto"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("SAMSUNG_TV_HOST", "192.168.1.106"),
            port=int(os.environ.get("SAMSUNG_TV_PORT", "55")),
            mac=os.environ.get("SAMSUNG_TV_MAC") or None,
            client_name=os.environ.get("SAMSUNG_TV_CLIENT_NAME", "Claude TV Remote"),
            client_id=os.environ.get("SAMSUNG_TV_CLIENT_ID", _default_client_id()),
            use_cec=_env_bool("SAMSUNG_TV_USE_CEC"),
            timeout=float(os.environ.get("SAMSUNG_TV_TIMEOUT", "5")),
            rendering_control_url=os.environ.get("SAMSUNG_TV_RENDERING_CONTROL_URL") or None,
            dial_url=os.environ.get("SAMSUNG_TV_DIAL_URL") or None,
            method=os.environ.get("SAMSUNG_TV_METHOD", "auto").strip().lower(),
        )
