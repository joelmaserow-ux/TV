"""Samsung "legacy" remote-control protocol (TCP port 55).

Used by the 2010-2014 Orsay-based Smart TVs (C/D/E/F and most H models).
Every message is framed as:

    0x00 | len(app) u16le | app | len(payload) u16le | payload

The first connection from a new client pops up an Allow/Deny prompt on the TV.
"""

from __future__ import annotations

import base64
import re
import socket
import struct
import time
from dataclasses import dataclass

APP_STRING = "iphone..iapp.samsung"
TV_APP_STRING = "iphone.UN60D6000.iapp.samsung"

AUTH_GRANTED = b"\x64\x00\x01\x00"
AUTH_DENIED = b"\x64\x00\x00\x00"

KEY_PATTERN = re.compile(r"^KEY_[A-Z0-9_]+$")


class TVError(Exception):
    """Base error for anything that went wrong talking to the TV."""


class TVUnreachable(TVError):
    pass


class AuthDenied(TVError):
    pass


class AuthPending(TVError):
    pass


def _field(data: bytes) -> bytes:
    return struct.pack("<H", len(data)) + data


def _b64(text: str) -> bytes:
    return base64.b64encode(text.encode("utf-8"))


def build_auth_packet(client_ip: str, client_id: str, client_name: str) -> bytes:
    payload = b"\x64\x00" + _field(_b64(client_ip)) + _field(_b64(client_id)) + _field(_b64(client_name))
    return b"\x00" + _field(APP_STRING.encode()) + _field(payload)


def build_key_packet(key: str) -> bytes:
    payload = b"\x00\x00\x00" + _field(_b64(key))
    return b"\x00" + _field(TV_APP_STRING.encode()) + _field(payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise TVError("TV closed the connection")
        buf += chunk
    return buf


def read_message(sock: socket.socket) -> bytes:
    """Read one framed message and return its payload."""
    _recv_exact(sock, 1)
    (app_len,) = struct.unpack("<H", _recv_exact(sock, 2))
    _recv_exact(sock, app_len)
    (payload_len,) = struct.unpack("<H", _recv_exact(sock, 2))
    return _recv_exact(sock, payload_len)


def local_ip_for(host: str) -> str:
    """The address of the network interface this machine uses to reach `host`."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((host, 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def normalize_key(key: str) -> str:
    key = key.strip().upper()
    if not key.startswith("KEY_"):
        key = "KEY_" + key
    if not KEY_PATTERN.match(key):
        raise ValueError(f"Not a valid Samsung key code: {key!r}")
    return key


@dataclass
class LegacyRemote:
    host: str
    client_id: str
    client_name: str
    port: int = 55
    timeout: float = 5.0
    # How long to wait for someone to press "Allow" on the TV the first time.
    auth_wait: float = 30.0

    def is_reachable(self, timeout: float | None = None) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout or self.timeout):
                return True
        except OSError:
            return False

    def _connect(self) -> socket.socket:
        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            raise TVUnreachable(
                f"Cannot reach the TV at {self.host}:{self.port} ({exc}). "
                "It is probably off/in standby, or not on this network."
            ) from exc
        try:
            sock.sendall(build_auth_packet(local_ip_for(self.host), self.client_id, self.client_name))
            self._await_auth(sock)
        except BaseException:
            sock.close()
            raise
        return sock

    def _await_auth(self, sock: socket.socket) -> None:
        deadline = time.monotonic() + self.auth_wait
        while True:
            sock.settimeout(max(0.5, deadline - time.monotonic()))
            try:
                payload = read_message(sock)
            except socket.timeout as exc:
                raise AuthPending(
                    "The TV has not answered the pairing request. Look at the TV screen and "
                    "choose 'Allow', then try again."
                ) from exc
            if payload == AUTH_GRANTED:
                sock.settimeout(self.timeout)
                return
            if payload == AUTH_DENIED:
                raise AuthDenied(
                    "The TV denied this remote. Un-block it under Menu > Network > "
                    "Multimedia Device Settings (or AllShare Settings), then try again."
                )
            if payload.startswith(b"\x65"):
                raise AuthPending("The pairing prompt on the TV timed out or was cancelled.")
            # 0x0a = "waiting for the user to answer the prompt"; anything else is
            # informational. Keep waiting until the deadline.
            if time.monotonic() >= deadline:
                raise AuthPending("Timed out waiting for 'Allow' on the TV.")

    def send_keys(self, keys: list[str], delay: float = 0.4) -> list[str]:
        normalized = [normalize_key(k) for k in keys]
        with self._connect() as sock:
            for i, key in enumerate(normalized):
                sock.sendall(build_key_packet(key))
                try:
                    read_message(sock)
                except (socket.timeout, TVError):
                    # Some firmwares do not acknowledge every key; that's fine.
                    pass
                if i < len(normalized) - 1:
                    time.sleep(delay)
        return normalized

    def send_key(self, key: str) -> str:
        return self.send_keys([key])[0]


COMMON_KEYS: dict[str, str] = {
    "KEY_POWEROFF": "Turn the TV off",
    "KEY_POWER": "Toggle power (some models)",
    "KEY_VOLUP": "Volume up",
    "KEY_VOLDOWN": "Volume down",
    "KEY_MUTE": "Mute toggle",
    "KEY_CHUP": "Channel up",
    "KEY_CHDOWN": "Channel down",
    "KEY_PRECH": "Previous channel",
    "KEY_0..KEY_9": "Number keys",
    "KEY_SOURCE": "Input source menu",
    "KEY_HDMI": "Cycle HDMI inputs",
    "KEY_TV": "Switch to TV tuner",
    "KEY_CONTENTS": "Smart Hub",
    "KEY_MENU": "Settings menu",
    "KEY_HOME": "Home (on some firmwares)",
    "KEY_GUIDE": "Programme guide",
    "KEY_INFO": "Info banner",
    "KEY_TOOLS": "Tools menu",
    "KEY_UP": "D-pad up",
    "KEY_DOWN": "D-pad down",
    "KEY_LEFT": "D-pad left",
    "KEY_RIGHT": "D-pad right",
    "KEY_ENTER": "OK / select",
    "KEY_RETURN": "Back",
    "KEY_EXIT": "Exit",
    "KEY_PLAY": "Play",
    "KEY_PAUSE": "Pause",
    "KEY_STOP": "Stop",
    "KEY_FF": "Fast forward",
    "KEY_REWIND": "Rewind",
    "KEY_RED": "Red (A) button",
    "KEY_GREEN": "Green (B) button",
    "KEY_YELLOW": "Yellow (C) button",
    "KEY_CYAN": "Blue (D) button",
}
