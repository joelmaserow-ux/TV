"""High-level TV operations shared by the MCP server and the command-line tool."""

from __future__ import annotations

import os
import re
import socket
import time
from urllib.parse import parse_qs, urlparse

from .config import Settings
from . import youtube
from .encrypted import EncryptedPairing, EncryptedRemote, credentials_path
from .legacy import LegacyRemote, TVError
from .power import cec_power_on, send_wol
from .upnp import DIAL_ST, RENDERING_CONTROL, Dial, RenderingControl, ssdp_search

# Names the TV's DIAL server registers apps under. Only some apps support DIAL.
APP_ALIASES = {
    "youtube": "YouTube",
    "netflix": "Netflix",
    "plex": "Plex",
    "amazon": "AmazonInstantVideo",
    "prime video": "AmazonInstantVideo",
    "prime": "AmazonInstantVideo",
}

# Apps that are not on DIAL but can be reached with a remote key.
KEY_APPS = {
    "smart hub": ["KEY_CONTENTS"],
    "smarthub": ["KEY_CONTENTS"],
    "source": ["KEY_SOURCE"],
    "tv": ["KEY_TV"],
    "guide": ["KEY_GUIDE"],
    "settings": ["KEY_MENU"],
    "menu": ["KEY_MENU"],
}

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_youtube(video: str) -> tuple[str, int | None]:
    """Return (video_id, start_seconds) from a YouTube URL or a bare video id."""
    video = video.strip()
    if YOUTUBE_ID.match(video):
        return video, None
    url = urlparse(video if "://" in video else "https://" + video)
    query = parse_qs(url.query)
    host = url.netloc.lower().removeprefix("www.").removeprefix("m.")
    video_id = None
    if host == "youtu.be":
        video_id = url.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if "v" in query:
            video_id = query["v"][0]
        else:
            parts = url.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
                video_id = parts[1]
    if not video_id or not YOUTUBE_ID.match(video_id):
        raise ValueError(f"Could not find a YouTube video id in {video!r}")
    start = None
    if "t" in query:
        start = _parse_seconds(query["t"][0])
    return video_id, start


def _parse_seconds(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s


class TV:
    def __init__(self, settings: Settings):
        self.s = settings
        self.legacy = LegacyRemote(
            settings.host, settings.client_id, settings.client_name, settings.port, settings.timeout
        )
        self.encrypted = EncryptedRemote(settings.host, timeout=settings.timeout)
        self.rendering = RenderingControl(settings.host, settings.rendering_control_url, settings.timeout)
        self.dial = Dial(settings.host, settings.dial_url, settings.timeout)

    @property
    def remote(self) -> LegacyRemote | EncryptedRemote:
        """The remote-key protocol this TV speaks."""
        if self.s.method == "legacy":
            return self.legacy
        if self.s.method == "encrypted" or self.encrypted.is_paired():
            return self.encrypted
        if not self.legacy.is_reachable(timeout=1.5) and self.encrypted.is_reachable(timeout=1.5):
            return self.encrypted
        return self.legacy

    def pair_start(self) -> str:
        if not _port_open(self.s.host, 8080):
            raise TVError("The TV's pairing service (port 8080) isn't answering. Make sure the TV is on.")
        EncryptedPairing(self.s.host).start()
        return "A 4-digit PIN should now be on the TV screen. Call pair_finish with it."

    def pair_finish(self, pin: str) -> str:
        path = EncryptedPairing(self.s.host).finish(pin)
        return f"Paired. Credentials saved to {path}; you won't need to pair again."

    # --- power -------------------------------------------------------------

    def is_on(self) -> bool:
        return self.remote.is_reachable(timeout=1.5)

    def status(self) -> str:
        if self.is_on():
            return f"The TV at {self.s.host} is on and accepting remote commands."
        return f"The TV at {self.s.host} is off, in standby, or unreachable."

    def power_off(self) -> str:
        if not self.is_on():
            return "The TV already looks off (it is not answering on the network)."
        self.remote.send_key("KEY_POWEROFF")
        return "Sent power off."

    def power_on(self, wait: float = 20.0) -> str:
        if self.is_on():
            return "The TV is already on."
        tried = []
        if self.s.mac:
            send_wol(self.s.mac, self.s.host)
            tried.append("Wake-on-LAN")
        if self.s.use_cec:
            tried.append(cec_power_on())
        if not tried:
            return (
                "Can't turn the TV on: 2014 H-series TVs switch their network off in standby, so "
                "there is nothing listening to wake. Options: set SAMSUNG_TV_USE_CEC=1 on a machine "
                "with HDMI-CEC (e.g. a Raspberry Pi plugged into the TV), or set SAMSUNG_TV_MAC to try "
                "Wake-on-LAN (rarely works on this model)."
            )
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.is_on():
                return f"The TV is on (via {', '.join(tried)})."
            time.sleep(2)
        return (
            f"Tried {', '.join(tried)} but the TV did not come up within {wait:.0f}s. "
            "This model often cannot be woken over the network; use the remote, CEC, or an IR blaster."
        )

    # --- volume ------------------------------------------------------------

    def get_volume(self) -> str:
        level = self.rendering.get_volume()
        muted = self.rendering.get_mute()
        return f"Volume is {level}{' (muted)' if muted else ''}."

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, int(level)))
        try:
            self.rendering.set_volume(level)
            return f"Volume set to {level}."
        except TVError as exc:
            return f"Could not set an exact volume ({exc}). Use volume_up/volume_down instead."

    def step_volume(self, steps: int) -> str:
        key = "KEY_VOLUP" if steps > 0 else "KEY_VOLDOWN"
        count = min(abs(int(steps)), 50)
        if count == 0:
            return "Nothing to do."
        self.remote.send_keys([key] * count, delay=0.15)
        return f"Volume {'up' if steps > 0 else 'down'} {count} step(s)."

    def set_mute(self, mute: bool | None) -> str:
        if mute is None:
            self.remote.send_key("KEY_MUTE")
            return "Toggled mute."
        try:
            self.rendering.set_mute(mute)
        except TVError:
            self.remote.send_key("KEY_MUTE")
            return "Toggled mute (exact mute state isn't available over UPnP on this TV)."
        return "Muted." if mute else "Unmuted."

    # --- apps --------------------------------------------------------------

    def open_app(self, app: str, params: str = "") -> str:
        key = app.strip().lower()
        if key in KEY_APPS:
            self.remote.send_keys(KEY_APPS[key])
            return f"Opened {app}."
        name = APP_ALIASES.get(key, app.strip())
        try:
            self.dial.launch(name, params)
            return f"Launched {name}."
        except TVError as exc:
            self.remote.send_key("KEY_CONTENTS")
            return (
                f"Couldn't launch '{name}' directly ({exc}). Opened Smart Hub instead; use send_keys "
                "with KEY_LEFT/RIGHT/UP/DOWN and KEY_ENTER to pick the app."
            )

    def app_status(self, app: str) -> str:
        name = APP_ALIASES.get(app.strip().lower(), app.strip())
        return f"{name}: {self.dial.status(name)}"

    def close_app(self, app: str) -> str:
        name = APP_ALIASES.get(app.strip().lower(), app.strip())
        self.dial.stop(name)
        return f"Asked the TV to close {name}."

    def play_youtube(self, video: str) -> str:
        video_id, start = parse_youtube(video)
        link = f"https://youtu.be/{video_id}{f'?t={start}' if start else ''}"
        if youtube.is_linked(self.s.host):
            self._ensure_youtube_open()
            if youtube.play(self.s.host, video_id, start):
                return f"Playing {link} on the TV."
            return f"Sent {link} to the TV's YouTube app (it doesn't confirm playback)."
        params = f"v={video_id}" + (f"&t={start}" if start else "")
        self.dial.launch("YouTube", params)
        return (
            f"Asked the TV to play {link}. If the TV says 'This video is unavailable', its YouTube app "
            "can't take videos this way: link it once with link_youtube (code from YouTube > Settings "
            "> Link with TV code on the TV)."
        )

    def _ensure_youtube_open(self, wait: float = 25.0) -> None:
        just_opened = self.dial.status("YouTube") != "running"
        if just_opened:
            self.dial.launch("YouTube")
        deadline = time.monotonic() + wait
        while not youtube.is_online(self.s.host):
            if time.monotonic() > deadline:
                raise TVError("The TV's YouTube app opened but never came online for casting.")
            time.sleep(2)
        if just_opened:
            # "Online" comes long before the app can take a video: anything sent while it is
            # still starting up gets replaced by the home screen. youtube.play also retries.
            time.sleep(float(os.environ.get("SAMSUNG_TV_YOUTUBE_STARTUP", "15")))

    def link_youtube(self, code: str) -> str:
        name = youtube.link(self.s.host, code)
        return f"Linked to YouTube on {name}. play_youtube will now cast videos the way the phone app does."

    # --- diagnostics -------------------------------------------------------

    def diagnose(self) -> str:
        lines = [f"TV host: {self.s.host}"]
        for port, what in [
            (55, "legacy remote (needed for keys/power off)"),
            (7676, "UPnP / AllShare"),
            (9197, "UPnP DMR"),
            (8000, "encrypted remote (2014-15 'J/H' pairing)"),
            (8001, "websocket remote (2016+ models)"),
            (8080, "PIN pairing service"),
        ]:
            lines.append(f"  port {port:<5} {'open  ' if _port_open(self.s.host, port) else 'closed'}  {what}")
        for st, label in [(RENDERING_CONTROL, "UPnP volume control"), (DIAL_ST, "DIAL app launching")]:
            hits = ssdp_search(st, self.s.host, timeout=2.5)
            lines.append(f"  {label}: {'found at ' + hits[0].get('location', '?') if hits else 'not found'}")
        try:
            for app in ("YouTube", "Netflix"):
                lines += [f"  app {line}" for line in self.dial.probe(app)]
        except TVError as exc:
            lines.append(f"  apps: {exc}")
        encrypted_ports = _port_open(self.s.host, 8000) or _port_open(self.s.host, 8080)
        if _port_open(self.s.host, 55) and self.s.method != "encrypted" and not self.encrypted.is_paired():
            lines.append(self._test_remote("legacy"))
        elif self.encrypted.is_paired():
            lines.append(self._test_remote(f"encrypted, credentials in {credentials_path(self.s.host)}"))
        elif encrypted_ports:
            lines.append(
                "  This TV uses Samsung's encrypted PIN pairing. Pair once with:  samsung-tv pair\n"
                "  (or ask Claude to pair with the TV). Volume and YouTube work without pairing."
            )
        return "\n".join(lines)


    def _test_remote(self, label: str) -> str:
        try:
            self.remote.send_key("KEY_INFO")
            return f"  remote ({label}): OK, sent KEY_INFO; you should see the info banner on the TV"
        except TVError as exc:
            return f"  remote ({label}): {exc}"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), 1.5):
            return True
    except OSError:
        return False
