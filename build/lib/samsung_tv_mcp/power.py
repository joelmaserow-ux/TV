"""Ways to wake the TV. The H series powers its network down in standby, so these are best-effort."""

from __future__ import annotations

import re
import shutil
import socket
import subprocess


def magic_packet(mac: str) -> bytes:
    digits = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(digits) != 12:
        raise ValueError(f"Not a MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(digits) * 16


def send_wol(mac: str, host: str) -> None:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in ("255.255.255.255", host):
            for port in (9, 7):
                try:
                    sock.sendto(packet, (target, port))
                except OSError:
                    pass


def cec_power_on() -> str:
    """Wake the TV over HDMI-CEC with libcec's cec-client (e.g. a Raspberry Pi plugged into the TV)."""
    if not shutil.which("cec-client"):
        return "cec-client is not installed"
    try:
        out = subprocess.run(
            ["cec-client", "-s", "-d", "1"], input="on 0\n", capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cec-client failed: {exc}"
    return "sent CEC 'on' to the TV" if out.returncode == 0 else f"cec-client exited {out.returncode}"
