"""Control a Google TV / Android TV device (e.g. the TOPTRO TP3 projector).

Uses the Android TV Remote protocol v2 via `androidtvremote2` -- the same protocol as the Google
TV phone app. Pair once with the code shown on screen; after that it can press buttons, set the
volume, type text, launch apps and open deep links (a YouTube video, a Netflix title).
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from .encrypted import credentials_path
from .legacy import TVError, TVUnreachable

CLIENT_NAME = "Claude TV Remote"

# The family remote speaks Samsung key names; these are their Google TV equivalents.
KEYS = {
    "KEY_UP": "DPAD_UP", "KEY_DOWN": "DPAD_DOWN", "KEY_LEFT": "DPAD_LEFT", "KEY_RIGHT": "DPAD_RIGHT",
    "KEY_ENTER": "DPAD_CENTER", "KEY_RETURN": "BACK", "KEY_EXIT": "HOME", "KEY_CONTENTS": "HOME",
    "KEY_HOME": "HOME", "KEY_MENU": "SETTINGS", "KEY_SOURCE": "TV_INPUT", "KEY_GUIDE": "GUIDE",
    "KEY_INFO": "INFO", "KEY_VOLUP": "VOLUME_UP", "KEY_VOLDOWN": "VOLUME_DOWN", "KEY_MUTE": "VOLUME_MUTE",
    "KEY_PLAY": "MEDIA_PLAY", "KEY_PAUSE": "MEDIA_PAUSE", "KEY_PLAYPAUSE": "MEDIA_PLAY_PAUSE",
    "KEY_STOP": "MEDIA_STOP", "KEY_FF": "MEDIA_FAST_FORWARD", "KEY_REWIND": "MEDIA_REWIND",
    "KEY_CHUP": "CHANNEL_UP", "KEY_CHDOWN": "CHANNEL_DOWN", "KEY_POWER": "POWER",
    "KEY_OK": "DPAD_CENTER", "KEY_SELECT": "DPAD_CENTER", "KEY_BACK": "BACK",
    **{f"KEY_{n}": str(n) for n in range(10)},
}

# Apps by friendly name -> (link Google TV hands to the app, Android package). Some devices
# ignore launches by package name (market://launch?id=...) but follow the app's web link.
APPS = {
    "youtube": ("https://www.youtube.com", "com.google.android.youtube.tv"),
    "netflix": ("https://www.netflix.com/title", "com.netflix.ninja"),
    "disney+": ("https://www.disneyplus.com", "com.disney.disneyplus"),
    "prime video": ("https://app.primevideo.com", "com.amazon.amazonvideo.livingroom"),
    "stan": ("https://play.stan.com.au", "au.com.stan.and"),
    "binge": ("https://binge.com.au", "au.com.streamotion.ares.tv"),
    "kayo": ("https://kayosports.com.au", "au.com.streamotion.kayo.tv"),
    "abc iview": ("https://iview.abc.net.au", "au.net.abc.iview"),
    "sbs on demand": ("https://www.sbs.com.au/ondemand", "com.sbs.ondemand.tv"),
    "spotify": ("spotify://", "com.spotify.tv.android"),
    "plex": ("plex://", "com.plexapp.android"),
    "play store": ("", "com.android.vending"),
}
ALIASES = {"disney": "disney+", "disney plus": "disney+", "prime": "prime video", "amazon": "prime video",
           "iview": "abc iview", "sbs": "sbs on demand"}


def _files(host: str) -> tuple[Path, Path]:
    base = credentials_path(host)
    return base.with_name(f"{host}.googletv-cert.pem"), base.with_name(f"{host}.googletv-key.pem")


def is_paired(host: str) -> bool:
    cert, key = _files(host)
    return cert.exists() and key.exists() and cert.with_suffix(".paired").exists()


class GoogleTV:
    """Blocking wrapper that keeps one connection open on a background event loop."""

    def __init__(self, host: str, timeout: float = 8.0):
        self.host = host
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, name="googletv", daemon=True).start()
        self._remote = None

    def _run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(self.timeout + 5)
        except TVError:
            raise
        except Exception as exc:
            future.cancel()
            raise TVError(f"Google TV at {self.host}: {type(exc).__name__}: {exc}") from exc

    def _make(self):
        try:
            from androidtvremote2 import AndroidTVRemote
        except ImportError as exc:
            raise TVError("Google TV control needs the 'androidtvremote2' package. Reinstall this project.") from exc
        cert, key = _files(self.host)
        cert.parent.mkdir(parents=True, exist_ok=True)
        return AndroidTVRemote(CLIENT_NAME, str(cert), str(key), self.host, loop=self._loop)

    # --- pairing ----------------------------------------------------------------------------

    def pair_start(self) -> str:
        """Show a pairing code on the screen."""
        return self._run(self._pair_start())

    async def _pair_start(self) -> str:
        from androidtvremote2 import CannotConnect

        self._pairing = self._make()
        await self._pairing.async_generate_cert_if_missing()
        try:
            await asyncio.wait_for(self._pairing.async_start_pairing(), self.timeout)
        except (CannotConnect, OSError, asyncio.TimeoutError) as exc:
            raise TVUnreachable(
                f"Can't reach the Google TV at {self.host}. Make sure it's on and on this Wi-Fi."
            ) from exc
        return "A code is showing on the screen."

    def pair_finish(self, code: str) -> str:
        return self._run(self._pair_finish(code.strip()))

    async def _pair_finish(self, code: str) -> str:
        from androidtvremote2 import ConnectionClosed, InvalidAuth

        pairing = getattr(self, "_pairing", None)
        if pairing is None:
            raise TVError("Start pairing first, so a code shows on the screen.")
        try:
            await pairing.async_finish_pairing(code)
        except (InvalidAuth, ConnectionClosed) as exc:
            raise TVError("That code didn't work. Start pairing again for a new one.") from exc
        _files(self.host)[0].with_suffix(".paired").write_text("ok")
        return "Paired with the Google TV."

    # --- connection -------------------------------------------------------------------------

    async def _connected(self):
        from androidtvremote2 import CannotConnect, ConnectionClosed, InvalidAuth

        if self._remote is not None:
            return self._remote
        if not is_paired(self.host):
            raise TVError("Not paired with this Google TV yet. Run: samsung-tv gtv pair --ip <its IP>")
        remote = self._make()
        try:
            await asyncio.wait_for(remote.async_connect(), self.timeout)
        except InvalidAuth as exc:
            raise TVError("The Google TV forgot this remote. Pair again: samsung-tv gtv pair --ip <its IP>") from exc
        except (CannotConnect, ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
            raise TVUnreachable(f"Can't reach the Google TV at {self.host}. It may be off.") from exc
        remote.keep_reconnecting()
        self._remote = remote
        return remote

    async def _do(self, fn):
        remote = await self._connected()
        try:
            return fn(remote)
        except Exception:
            # Drop a dead connection and try once more on a fresh one.
            remote.disconnect()
            self._remote = None
            return fn(await self._connected())

    # --- commands ---------------------------------------------------------------------------

    def press(self, keys: list[str], delay: float = 0.3) -> list[str]:
        codes = [to_keycode(k) for k in keys]

        async def go():
            for i, code in enumerate(codes):
                await self._do(lambda r, c=code: r.send_key_command(c))
                if i < len(codes) - 1:
                    await asyncio.sleep(delay)

        self._run(go())
        return codes

    def type_text(self, text: str) -> None:
        self._run(self._do(lambda r: r.send_text(text)))

    def launch(self, app_or_link: str) -> str:
        """Open an app by friendly name or package, or a deep link (https://, market://...).

        Checks what's in front afterwards, so it can say whether the app actually opened.
        """
        name = app_or_link.strip()
        key = ALIASES.get(name.lower(), name.lower())
        link, package = APPS.get(key, ("", ""))
        if not link and not package:
            if "://" in name:
                link = name
            else:
                package = name
        tries = [t for t in (link, package) if t]

        async def go():
            # Only check the result on devices that report which app is in front.
            reports_app = await self._wait_for_app("", 2)
            for target in tries:
                await self._do(lambda r, t=target: r.send_launch_app_command(t))
                if not package:
                    return f"Opened {target}."
                if not reports_app:
                    return f"Asked the Google TV to open {name} (it doesn't report what's on screen)."
                if await self._wait_for_app(package, 6):
                    return f"Opened {name}."
            raise TVError(
                f"Asked the Google TV to open {name}, but it's not showing. Is it installed on the "
                "projector? (Open it once with the projector's remote, then try again.)"
            )

        return self._run(go())

    async def _wait_for_app(self, package: str, timeout: float) -> bool:
        remote = await self._connected()
        for _ in range(int(timeout * 10)):
            if remote.current_app and remote.current_app.startswith(package):
                return True
            await asyncio.sleep(0.1)
        return False

    def set_volume(self, level: int) -> str:
        """Step the volume to `level` on the device's own scale (e.g. 0-15 on the TP3)."""
        info = self.status()
        current, top = info.get("volume"), info.get("volume_max")
        if current is None:
            raise TVError(
                "This Google TV doesn't report its volume (common when it controls the projector's "
                "volume over HDMI). Use volume up/down instead: samsung-tv gtv key volup volup"
            )
        if top and not 0 <= level <= top:
            raise ValueError(f"This device's volume goes from 0 to {top}.")
        steps = level - current
        if steps:
            self.press(["KEY_VOLUP" if steps > 0 else "KEY_VOLDOWN"] * min(abs(steps), 100), delay=0.15)
        return f"Volume set to {level}" + (f" (of {top})." if top else ".")

    def status(self) -> dict:
        async def get():
            remote = await self._connected()
            # Volume and current app arrive a moment after connecting.
            for _ in range(30):
                if remote.volume_info is not None and remote.current_app:
                    break
                await asyncio.sleep(0.1)
            info = remote.device_info or {}
            vol = remote.volume_info or {}
            return {"on": remote.is_on, "app": remote.current_app, "volume": vol.get("level"),
                    "volume_max": vol.get("max"), "muted": vol.get("muted"),
                    "device": " ".join(str(info.get(k, "")) for k in ("manufacturer", "model")).strip()}

        return self._run(get())

    def power(self, on: bool | None = None) -> str:
        """Toggle power, or set it if `on` is given (needs the device to report its state)."""
        state = self.status().get("on")
        if on is None or state is None or state != on:
            self.press(["KEY_POWER"])
            return "Sent power."
        return "Already " + ("on." if on else "off.")

    def close(self) -> None:
        if self._remote is not None:
            self._remote.disconnect()
            self._remote = None


def to_keycode(key: str) -> str:
    """A Samsung-style (KEY_UP), Android (KEYCODE_DPAD_UP) or bare (DPAD_UP) name -> Android name."""
    from androidtvremote2.remotemessage_pb2 import RemoteKeyCode

    name = key.strip().upper()
    code = KEYS.get(name) or KEYS.get("KEY_" + name) or name.removeprefix("KEYCODE_")
    try:
        RemoteKeyCode.Value("KEYCODE_" + code)
    except ValueError:
        raise ValueError(f"Unknown key {key!r}") from None
    return code


def default_host() -> str | None:
    return os.environ.get("GOOGLE_TV_HOST") or None
