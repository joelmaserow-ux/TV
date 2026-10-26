"""Play YouTube videos via YouTube's Lounge API, the same channel the phone app uses to cast.

Older TV YouTube apps accept a DIAL launch but can't play the video id passed with it. Linking
once with the "Link with TV code" from the TV's YouTube settings gets around that.
"""

from __future__ import annotations

import asyncio
import json
import logging

from .encrypted import credentials_path
from .legacy import TVError

DEVICE_NAME = "Claude TV Remote"
_log = logging.getLogger(__name__)


def _auth_path(host: str):
    return credentials_path(host).with_name(f"{host}.youtube.json")


def is_linked(host: str) -> bool:
    return _auth_path(host).exists()


def _api(listener=None):
    try:
        from pyytlounge import YtLoungeApi
    except ImportError as exc:
        raise TVError("YouTube linking needs the 'pyytlounge' package. Reinstall this project.") from exc
    return YtLoungeApi(DEVICE_NAME, event_listener=listener, logger=_log)


class _NowPlaying:
    """Records the nowPlaying event the TV sends when a remote connects."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.seen = False
        self.video_id = None
        self.state = None

    async def now_playing_changed(self, event):
        self.seen = True
        self.video_id = event.video_id
        self.state = getattr(event.state, "name", None)
        _log.debug("TV reports now playing %s (%s)", self.video_id, self.state)

    def is_playing(self, video_id: str) -> bool:
        # A queued video on the home screen reports our id with state Stopped.
        return self.video_id == video_id and self.state not in ("Stopped", None)

    def __getattr__(self, name):
        # Every other EventListener callback: ignore.
        async def _ignore(*_):
            pass
        return _ignore


def _run(coro):
    try:
        return asyncio.run(coro)
    except TVError:
        raise
    except Exception as exc:  # pyytlounge surfaces raw aiohttp / KeyError failures
        raise TVError(f"YouTube's casting service failed: {exc!r}") from exc


def link(host: str, code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) < 8:
        raise ValueError("Enter the full TV code shown under YouTube > Settings > Link with TV code.")
    return _run(_link(host, code))


async def _link(host: str, code: str) -> str:
    async with _api() as api:
        try:
            ok = await api.pair(code)
        except (KeyError, ValueError) as exc:  # unknown/expired codes come back without a "screen"
            raise TVError("YouTube didn't accept that code. Get a fresh one on the TV and try again.") from exc
        if not ok:
            raise TVError("YouTube didn't accept that code. Get a fresh one on the TV and try again.")
        path = _auth_path(host)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(api.store_auth_state()))
        return api.screen_name or "your TV"


def is_online(host: str) -> bool:
    return _run(_is_online(host))


async def _is_online(host: str) -> bool:
    async with _api() as api:
        api.load_auth_state(json.loads(_auth_path(host).read_text()))
        await api.refresh_auth()
        return await api.is_available()


def play(host: str, video_id: str, start: int | None = None) -> bool:
    """Cast a video. Returns True once the TV confirms it's playing it (False if it can't tell)."""
    return _run(_play(host, video_id, start))


async def _connect(api) -> None:
    if not await api.connect():
        await api.refresh_auth()
        if not await api.connect():
            raise TVError("Couldn't connect to the TV's YouTube app. Make sure it's open, or relink it.")


async def _play(host: str, video_id: str, start: int | None, attempts: int = 4) -> bool:
    # Never send the lounge "terminate" (api.disconnect): older TV apps treat the remote
    # leaving as the end of the session and drop back to the account picker. Sessions we
    # just stop using expire on YouTube's side without touching playback.
    listener = _NowPlaying()
    async with _api(listener) as api:
        api.load_auth_state(json.loads(_auth_path(host).read_text()))
        await api.refresh_auth()
        for attempt in range(attempts + 1):
            listener.reset()
            await _connect(api)
            if attempt:
                if listener.is_playing(video_id):
                    return True
                if not listener.seen:
                    # This TV doesn't report what it's playing; trust the first request.
                    return False
            if attempt == attempts:
                break
            # A freshly opened app reports "online" while still loading and silently drops
            # requests, so send, then reconnect to check, and resend until it sticks.
            ok = await api._command("setPlaylist", {
                "videoId": video_id,
                "videoIds": video_id,
                "currentTime": start or 0,
                "currentIndex": 0,
                "listId": "",
                "audioOnly": "false",
                "params": "",
                "playerParams": "",
            })
            if not ok:
                raise TVError("YouTube refused to start the video.")
            await asyncio.sleep(5)
        raise TVError("The TV's YouTube app kept ignoring the video. Try again in a few seconds.")
