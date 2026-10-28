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

from . import cancel
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
    # For typing: delete the last letter, and the keyboard's Enter / Search key.
    "KEY_BACKSPACE": "DEL", "KEY_TEXT_ENTER": "ENTER",
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
        _patch_keyboard_tracking()
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

    def box_text(self) -> str | None:
        """What the device last said its open text box reads (None if it hasn't said)."""
        proto = getattr(self._remote, "_remote_message_protocol", None) if self._remote else None
        if proto is None or not getattr(proto, "keyboard_seen", False):
            return None
        return getattr(proto, "ime_value", None)

    def set_text(self, value: str) -> bool:
        """Send `value` to the open text box (how the box takes it depends on the device)."""
        return self.ime_edit(value)

    def ime_edit(self, value: str, start: int | None = None, end: int | None = None,
                 counter_offset: int = 0, field_from_counter: bool = False) -> bool:
        """Send one keyboard edit to the open text box, the way the Google TV app does.

        `start`/`end` default to len(value) - 1 (what androidtvremote2 uses). It quotes the
        device's latest edit counter (plus `counter_offset`), then waits for the device to count
        it, on devices that report one (the TP3 doesn't report anything).
        """
        from androidtvremote2.remotemessage_pb2 import (
            RemoteEditInfo, RemoteImeBatchEdit, RemoteImeObject, RemoteMessage,
        )

        value = value[:200]
        start = len(value) - 1 if start is None else start
        end = start if end is None else end

        async def go():
            remote = await self._connected()
            proto = remote._remote_message_protocol
            if proto is None:
                raise TVUnreachable(f"Lost the connection to the Google TV at {self.host}.")
            counter = getattr(proto, "ime_counter", 0)
            field = counter if field_from_counter else getattr(proto, "ime_field_counter", 0)
            msg = RemoteMessage()
            msg.remote_ime_batch_edit.CopyFrom(RemoteImeBatchEdit(
                ime_counter=counter + counter_offset, field_counter=field,
                edit_info=[RemoteEditInfo(insert=1, text_field_status=RemoteImeObject(start=start, end=end, value=value))],
            ))
            proto._send_message(msg)
            if getattr(proto, "keyboard_seen", False):
                # Devices that report their edit counter: wait for it to count this change.
                for _ in range(40):
                    if getattr(proto, "ime_counter", 0) != counter:
                        break
                    await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.05)  # the TP3 never answers; just keep edits in order
            return True

        return self._run(go())

    def launch(self, app_or_link: str) -> str:
        """Open an app by friendly name or package, or a deep link (https://, market://...).

        Checks what's in front afterwards, so it can say whether the app actually opened.
        """
        name = app_or_link.strip()
        key = ALIASES.get(name.lower(), name.lower())
        link, package = APPS.get(key, ("", ""))
        if not link and not package:
            from urllib.parse import urlparse

            # Anything with a URI scheme (https:, market:, package:...) is a link, not a package.
            if urlparse(name).scheme:
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

    def app_now(self) -> str | None:
        """The app in front as last reported, without waiting (None if not known yet)."""
        return getattr(self._remote, "current_app", None) or None if self._remote else None

    def foreground(self) -> str | None:
        """The app in front, or None if this device doesn't report it."""

        async def get():
            remote = await self._connected()
            for _ in range(20):
                if remote.current_app:
                    break
                await asyncio.sleep(0.1)
            return remote.current_app or None

        return self._run(get())

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

    def send_key(self, key: str, hold: bool = False, fresh: bool = False) -> None:
        """Press one Android key (held for 2 s with `hold`), optionally on a fresh connection."""
        if fresh:
            self.close()

        async def go():
            remote = await self._connected()
            if hold:
                remote.send_key_command(key, "START_LONG")
                await asyncio.sleep(2)
                remote.send_key_command(key, "END_LONG")
            else:
                remote.send_key_command(key)

        self._run(go())

    def wake(self) -> str:
        """Turn the device on from standby.

        A connection kept open across standby can go stale and still say "on", so start a
        fresh one. Then send Android's wake-up key (which never turns it off); if it still
        reports off a few seconds later, press power as well.
        """
        self.close()

        async def go():
            remote = await self._connected()
            if remote.is_on:
                return "The projector is on."
            remote.send_key_command("WAKEUP")
            for _ in range(40):
                await asyncio.sleep(0.1)
                if remote.is_on:
                    return "Turned the projector on."
            remote.send_key_command("POWER")
            for _ in range(40):
                await asyncio.sleep(0.1)
                if remote.is_on:
                    return "Turned the projector on."
            return "Sent power on; the projector may take a few seconds to show a picture."

        try:
            return self._run_slow(go(), 15)
        except TVUnreachable as exc:
            raise TVUnreachable(
                "The projector isn't answering on the network, so it can't be woken from here. "
                "It's probably fully off (switched off at the wall, or its power button held): "
                "turn it on with its own remote once."
            ) from exc

    def _run_slow(self, coro, timeout: float):
        saved, self.timeout = self.timeout, max(self.timeout, timeout)
        try:
            return self._run(coro)
        finally:
            self.timeout = saved

    def power(self, on: bool | None = None) -> str:
        """Toggle power, or set it if `on` is given (needs the device to report its state)."""
        if on:
            return self.wake()
        state = self.status().get("on")
        if on is None or state is None or state != on:
            self.press(["KEY_POWER"])
            return "Sent power."
        return "Already " + ("on." if on else "off.")

    def close(self) -> None:
        if self._remote is not None:
            self._remote.disconnect()
            self._remote = None


def _patch_keyboard_tracking() -> None:
    """Remember the text box the device says is open.

    When a keyboard opens, the device sends "show keyboard" with the box's number, and text
    must be addressed to that number. androidtvremote2 only reads it from a different message
    that some devices (like the TP3) never send, so its text went to box 0 and was dropped.
    """
    from androidtvremote2 import remote as rm
    from androidtvremote2.remotemessage_pb2 import RemoteMessage

    if getattr(rm.RemoteProtocol, "_keyboard_tracking", False):
        return
    original = rm.RemoteProtocol._handle_message

    def handle(self, raw_msg):
        original(self, raw_msg)
        try:
            msg = RemoteMessage()
            msg.ParseFromString(raw_msg)
        except Exception:
            return
        if msg.HasField("remote_ime_show_request"):
            box = msg.remote_ime_show_request.remote_text_field_status
            # This number goes up with every change to the box: it's the edit counter our next
            # change has to quote, or the device merges it with an older state of the box.
            self.ime_counter = box.counter_field
            self.ime_value = box.value
            self.keyboard_seen = True
        elif msg.HasField("remote_ime_batch_edit"):
            edit = msg.remote_ime_batch_edit
            values = [e.text_field_status.value for e in edit.edit_info]
            if values:
                self.ime_value = values[-1]
            self.keyboard_seen = True

    rm.RemoteProtocol._handle_message = handle
    rm.RemoteProtocol._keyboard_tracking = True


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


class _AppState:
    """DIAL-like running/stopped answers from the foreground app, for the Netflix routine."""

    def __init__(self, gtv: GoogleTV):
        self.gtv = gtv

    def status(self, name: str) -> str:
        key = ALIASES.get(name.lower(), name.lower())
        package = APPS.get(key, ("", name))[1]
        app = self.gtv.foreground()
        if app is None:
            return "unknown"
        return "running" if app.startswith(package) else "stopped"


class GoogleTVDevice:
    """Makes a Google TV look enough like the Samsung `TV` for the shared Netflix and YouTube
    routines: same Netflix screens, just a different route to Search and a Back-based exit."""

    netflix_layout = {
        # Back doesn't really quit Netflix here, so force-stop it from the Settings panel:
        # Settings, OK, Down 4, Right, Down, OK (Netflix's app info), Down, OK (Force stop),
        # OK (confirm). Each step is (presses, seconds to wait after them).
        "exit": [
            (["KEY_MENU"], 2.0),
            (["KEY_ENTER"], 2.0),
            (["KEY_DOWN"] * 4 + ["KEY_RIGHT", "KEY_DOWN"], 0.5),
            (["KEY_ENTER"], 2.5),
            (["KEY_DOWN"], 0.5),
            (["KEY_ENTER"], 1.5),
            (["KEY_ENTER"], 2.0),
        ],
        # After picking a profile: Up, Left, OK lands on "a" of the search keyboard. Left
        # slides the side menu open, and an OK sent before it settles is ignored, so wait.
        "to_search": [(["KEY_UP"], 1.0), (["KEY_LEFT"], 2.0), (["KEY_ENTER"], 0.8)],
        # Down from the Space bar lands on "b" here (on the Samsung it's "a").
        "space_landing": (0, 1),
    }
    PICK_ACCOUNT_AFTER = 12.0

    def __init__(self, host: str):
        from types import SimpleNamespace

        self.gtv = GoogleTV(host)
        self.s = SimpleNamespace(host=host)
        self.dial = _AppState(self.gtv)

    def press(self, keys: list[str], delay: float = 0.3) -> list[str]:
        return self.gtv.press(keys, delay)

    def _launch(self, name: str, params: str = "") -> None:
        try:
            self.gtv.launch(name)
        except TVError:
            # A launch the device didn't confirm still often worked; the routine checks state.
            pass

    def open_app(self, name: str, params: str = "") -> str:
        return self.gtv.launch(name)

    def link_youtube(self, code: str) -> str:
        from . import youtube

        name = youtube.link(self.s.host, code)
        return f"Linked to YouTube on {name}."

    def play_youtube(self, video: str) -> str:
        """Cast a video to the device's YouTube app (needs a one-time Link with TV code)."""
        import time

        from . import youtube
        from .tv import parse_youtube

        video_id, start = parse_youtube(video)
        link = f"https://youtu.be/{video_id}{f'?t={start}' if start else ''}"
        if not youtube.is_linked(self.s.host):
            # Without a link, open the video's own link. A fresh start stops on "Who's
            # watching?" and drops the video, so pick the account and send the link again.
            watch = "https://www.youtube.com/watch?v=" + video_id + (f"&t={start}s" if start else "")
            just_opened = self.dial.status("YouTube") != "running"
            self.gtv.launch(watch)
            if just_opened:
                cancel.sleep(self.PICK_ACCOUNT_AFTER)
                self.press(["KEY_ENTER"])
                cancel.sleep(6)
                self.gtv.launch(watch)
            return (
                f"Opened {link} on the projector. If it stops on YouTube's home screen, link YouTube "
                "once: on the projector open YouTube > Settings > Link with TV code, and enter the "
                "code under Fix YouTube on the remote's YouTube tab."
            )
        just_opened = self.dial.status("YouTube") != "running"
        if just_opened:
            self._launch("YouTube")
        began, picked = time.monotonic(), False
        while not youtube.is_online(self.s.host) and time.monotonic() - began < 45:
            if just_opened and not picked and time.monotonic() - began >= self.PICK_ACCOUNT_AFTER:
                picked = True  # "Who's watching?" on a fresh start: OK picks the highlighted account
                self.press(["KEY_ENTER"])
            cancel.sleep(2)
        if just_opened:
            cancel.sleep(8)
        if youtube.play(self.s.host, video_id, start):
            return f"Playing {link} on the projector."
        return f"Sent {link} to the projector's YouTube app."


LABELS = {
    "youtube": "YouTube", "netflix": "Netflix", "disney+": "Disney+", "prime video": "Prime Video",
    "stan": "Stan", "binge": "Binge", "kayo": "Kayo", "abc iview": "ABC iview",
    "sbs on demand": "SBS On Demand", "spotify": "Spotify", "plex": "Plex",
}


NO_POWER = ("This projector's power can't be switched from its Google TV stick (the power test "
            "found no way). Use the projector's own remote for on and off; everything else works here.")


NO_POWER_ON = ("The projector can be turned off from here but not on: while it's off, its Google TV "
               "stick has no power, so nothing on the Wi-Fi can reach it. Turn it on with its own remote.")


class Projector(GoogleTVDevice):
    """The Google TV device with the same methods the family remote calls on the Samsung TV."""

    name = "projector"

    def set_volume(self, level: int) -> str:
        return self.gtv.set_volume(level)

    def step_volume(self, steps: int) -> str:
        count = min(abs(int(steps)), 30)
        if count:
            self.press(["KEY_VOLUP" if steps > 0 else "KEY_VOLDOWN"] * count, delay=0.15)
        return ""

    def get_volume(self) -> str:
        info = self.gtv.status()
        if info.get("volume") is None:
            raise TVError("The projector isn't reporting its volume right now.")
        return f"Volume is {info['volume']}{' (muted)' if info.get('muted') else ''}."

    def volume_max(self) -> int:
        try:
            return int(self.gtv.status().get("volume_max") or 15)
        except TVError:
            return 15

    def set_mute(self, mute: bool | None) -> str:
        self.press(["KEY_MUTE"])
        return "Toggled mute."

    _typed = ""  # what we've typed into the projector's open box so far

    def type_text(self, text: str) -> str:
        """Make the projector's open text box read `text`, sent live as the phone's box changes.

        Uses the way of typing `samsung-tv gtv typetest` found works on this device.
        """
        from . import typing_methods

        text = text[:200]
        # Each app's search box can want a different way of typing (see typing_methods).
        app = self.gtv.app_now() if hasattr(self.gtv, "app_now") else None
        chosen = typing_methods.settings(self.s.host, app)
        # Work from what the projector says its box reads, so a box changed or cleared with the
        # projector's own remote (or a new search box) doesn't throw the letters off.
        box = self.gtv.box_text() if hasattr(self.gtv, "box_text") else None
        before = box if box is not None else self._typed
        typing_methods.send(self, chosen["method"], before, text, chosen["delete"], chosen["chunk"])
        self._typed = text
        return ""

    def power_off(self) -> str:
        from . import power_methods

        name = power_methods.saved(self.s.host)["off"]
        if name == "none":
            raise TVError(NO_POWER)
        power_methods.send(self.gtv, power_methods.OFF, name)
        return "Turned the projector off."

    def power_on(self) -> str:
        from . import power_methods

        name = power_methods.saved(self.s.host)["on"]
        if name == "none":
            raise TVError(NO_POWER_ON if power_methods.saved(self.s.host)["off"] != "none" else NO_POWER)
        if name == power_methods.DEFAULT_ON:
            return self.gtv.wake()  # wake-up key, then power if it still reports off
        try:
            power_methods.send(self.gtv, power_methods.ON, name, fresh=True)
        except TVUnreachable as exc:
            raise TVUnreachable(
                "The projector isn't answering on the network, so it can't be turned on from here. "
                "Turn it on with its own remote."
            ) from exc
        return "Turned the projector on."

    def is_on(self) -> bool:
        try:
            return bool(self.gtv.status().get("on"))
        except TVError:
            return False

    def status(self) -> str:
        return f"The projector is {'on' if self.is_on() else 'off'}."

    def apps(self) -> list[dict]:
        return [{"id": key, "name": label} for key, label in LABELS.items()]
