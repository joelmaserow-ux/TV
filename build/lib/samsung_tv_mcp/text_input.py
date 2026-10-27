"""Typing text into the TV's on-screen keyboard.

2016+ Samsungs take text over the websocket API on port 8001 (SendInputString). This TV's
H/J firmware also has port 8001 open, so we try it; if the TV rejects it, we say so.
"""

from __future__ import annotations

from .encrypted import credentials_path
from .legacy import TVError


def type_text(host: str, text: str, submit: bool = False, timeout: float = 5.0) -> None:
    if not text:
        return
    try:
        from samsungtvws import SamsungTVWS
    except ImportError as exc:
        raise TVError("Typing needs the 'samsungtvws' package. Reinstall this project.") from exc
    token_file = credentials_path(host).with_name(f"{host}.ws-token")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    tv = SamsungTVWS(host, port=8001, token_file=str(token_file), timeout=timeout, name="Claude TV Remote")
    try:
        tv.send_text(text)
        if submit:
            tv.end_text()
    except Exception as exc:  # websocket/handshake errors of several kinds
        raise TVError(
            "This TV didn't accept typed text over its network API. Use the arrow keys on the "
            f"on-screen keyboard instead. ({type(exc).__name__}: {exc})"
        ) from exc
    finally:
        try:
            tv.close()
        except Exception:
            pass
