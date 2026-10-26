"""Samsung's encrypted remote protocol (PIN pairing on port 8080, commands on port 8000).

Later 2014 H-series and 2015 J-series firmwares replaced the port-55 remote with this. The
crypto is handled by the `samsungtvws` library (the same code Home Assistant uses); this
module adds pairing that survives restarts and a blocking API matching LegacyRemote.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .legacy import AuthPending, TVError, TVUnreachable, normalize_key


def credentials_path(host: str) -> Path:
    base = os.environ.get("SAMSUNG_TV_CONFIG_DIR") or Path.home() / ".samsung-tv-mcp"
    return Path(base) / f"{host}.json"


def load_credentials(host: str) -> tuple[str, str] | None:
    token = os.environ.get("SAMSUNG_TV_TOKEN")
    session_id = os.environ.get("SAMSUNG_TV_SESSION_ID")
    if token and session_id:
        return token, session_id
    try:
        data = json.loads(credentials_path(host).read_text())
        return data["token"], str(data["session_id"])
    except (OSError, ValueError, KeyError):
        return None


def save_credentials(host: str, token: str, session_id: str) -> Path:
    path = credentials_path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "session_id": session_id}))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _imports():
    try:
        import aiohttp
        from samsungtvws.encrypted.authenticator import SamsungTVEncryptedWSAsyncAuthenticator
        from samsungtvws.encrypted.remote import SamsungTVEncryptedWSAsyncRemote, SendRemoteKey
    except ImportError as exc:
        raise TVError(
            "Encrypted pairing needs the 'samsungtvws[async,encrypted]' package. Reinstall this "
            "project (pip install -e .) to get it."
        ) from exc
    return aiohttp, SamsungTVEncryptedWSAsyncAuthenticator, SamsungTVEncryptedWSAsyncRemote, SendRemoteKey


def _run(coro):
    try:
        return asyncio.run(coro)
    except (OSError, asyncio.TimeoutError) as exc:
        raise TVUnreachable(f"Lost contact with the TV: {exc}") from exc


@dataclass
class EncryptedPairing:
    host: str
    timeout: float = 10.0
    pairing_port: int = 8080

    def start(self) -> None:
        """Show a 4-digit PIN on the TV screen."""
        _run(self._start())

    async def _start(self) -> None:
        aiohttp, Auth, _, _ = _imports()
        async with aiohttp.ClientSession() as web:
            await Auth(self.host, web_session=web, port=self.pairing_port, timeout=self.timeout).start_pairing()

    def finish(self, pin: str) -> Path:
        """Exchange the PIN for a token and save it. Returns where the credentials were stored."""
        pin = pin.strip()
        if not (pin.isdigit() and len(pin) == 4):
            raise ValueError("The PIN is the 4 digits shown on the TV screen.")
        token, session_id = _run(self._finish(pin))
        return save_credentials(self.host, token, session_id)

    async def _finish(self, pin: str) -> tuple[str, str]:
        aiohttp, Auth, _, _ = _imports()
        async with aiohttp.ClientSession() as web:
            auth = Auth(self.host, web_session=web, port=self.pairing_port, timeout=self.timeout)
            token = await auth.try_pin(pin)
            if not token:
                raise AuthPending("The TV rejected that PIN. Start pairing again to get a new one.")
            try:
                session_id = await auth.get_session_id_and_close()
            except Exception as exc:  # the library raises several error types here
                raise AuthPending(f"Pairing failed after the PIN was accepted: {exc}") from exc
        return token, session_id


_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    """One long-lived event loop, so a TV connection can outlive a single call."""
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="samsung-tv-encrypted", daemon=True).start()
        return _loop


@dataclass
class EncryptedRemote:
    host: str
    port: int = 8000
    timeout: float = 5.0
    # Reused across presses: this TV's companion service misbehaves when every key press
    # opens and tears down its own socket.io session.
    _remote: object = field(default=None, init=False, repr=False)
    _web: object = field(default=None, init=False, repr=False)
    _creds: tuple | None = field(default=None, init=False, repr=False)
    _last_used: float = field(default=0.0, init=False, repr=False)
    _close_registered: bool = field(default=False, init=False, repr=False)
    # socket.io sessions we don't heartbeat can go stale on the TV without closing cleanly.
    IDLE_RECONNECT = 45.0

    def is_reachable(self, timeout: float | None = None) -> bool:
        if self._remote is not None and self._remote.is_alive():
            return True
        try:
            with socket.create_connection((self.host, self.port), timeout or self.timeout):
                return True
        except OSError:
            return False

    def is_paired(self) -> bool:
        return load_credentials(self.host) is not None

    def send_keys(self, keys: list[str], delay: float = 0.4) -> list[str]:
        normalized = [normalize_key(k) for k in keys]
        creds = load_credentials(self.host)
        if not creds:
            raise AuthPending(
                "This TV uses encrypted pairing and hasn't been paired yet. Run "
                "`samsung-tv pair` (or ask Claude to pair with the TV) and enter the PIN shown on screen."
            )
        future = asyncio.run_coroutine_threadsafe(self._send(normalized, creds, delay), _background_loop())
        try:
            future.result(timeout=self.timeout * 2 + delay * len(normalized) + 5)
        except TVError:
            raise
        except Exception as exc:
            future.cancel()
            raise TVUnreachable(
                f"The TV's remote-control service at {self.host}:{self.port} isn't responding ({exc!r}). "
                "If this keeps happening, unplug the TV at the wall for 30 seconds."
            ) from exc
        return normalized

    async def _connect(self, creds: tuple[str, str], delay: float) -> None:
        aiohttp, _, Remote, _ = _imports()
        await self._reset()
        token, session_id = creds
        self._web = aiohttp.ClientSession()
        remote = Remote(self.host, web_session=self._web, token=token, session_id=session_id,
                        port=self.port, timeout=self.timeout, key_press_delay=delay)
        try:
            await asyncio.wait_for(remote.start_listening(), self.timeout)
        except BaseException:
            await self._reset()
            raise
        self._remote, self._creds = remote, creds
        if not self._close_registered:
            self._close_registered = True
            atexit.register(self.close)

    def close(self) -> None:
        """Close the kept-open TV connection (runs automatically at exit)."""
        if self._remote is None and self._web is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._reset(), _background_loop()).result(timeout=3)
        except Exception:
            pass

    async def _reset(self) -> None:
        remote, web = self._remote, self._web
        self._remote = self._web = self._creds = None
        if remote is not None:
            try:
                await asyncio.wait_for(remote.close(), 3)
            except Exception:
                pass
        if web is not None:
            await web.close()

    async def _send(self, keys: list[str], creds: tuple[str, str], delay: float) -> None:
        _, _, _, SendRemoteKey = _imports()
        commands = [SendRemoteKey.click(k) for k in keys]
        for attempt in (1, 2):
            stale = time.monotonic() - self._last_used > self.IDLE_RECONNECT
            if self._remote is None or not self._remote.is_alive() or self._creds != creds or stale:
                await self._connect(creds, delay)
            try:
                await self._remote.send_commands(commands, key_press_delay=delay)
                self._last_used = time.monotonic()
                return
            except Exception:
                # The TV drops idle sessions; reconnect once and resend.
                await self._reset()
                if attempt == 2:
                    raise

    def send_key(self, key: str) -> str:
        return self.send_keys([key])[0]
