"""MCP server exposing the TV as tools. Runs over stdio."""

from __future__ import annotations

from functools import partial
from typing import Any, Callable

import anyio

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .config import Settings
from .legacy import COMMON_KEYS, TVError
from .tv import TV

INSTRUCTIONS = """\
Controls a Samsung UA55H6300 (2014 H-series, Orsay OS) Smart TV on the local network.
- Turning the TV ON usually is not possible over the network on this model; power_on explains why.
- To play a YouTube video you need its URL or id: use search_youtube to find it, then play_youtube. If the
  TV shows 'This video is unavailable', ask the user for the code under YouTube > Settings >
  Link with TV code on the TV and call link_youtube once.
- Deep links into a specific show only work for YouTube. For other apps, open_app and then
  navigate with send_keys (KEY_UP/DOWN/LEFT/RIGHT, KEY_ENTER, KEY_RETURN).
- Pairing: older firmwares show an Allow/Deny prompt on the first command; ask the user to press
  Allow. Newer firmwares need PIN pairing once: call pair_start, ask the user for the 4-digit PIN
  shown on the TV, then call pair_finish with it.
"""

mcp = MCPServer("samsung-tv", instructions=INSTRUCTIONS)
_tv: TV | None = None


def tv() -> TV:
    global _tv
    if _tv is None:
        _tv = TV(Settings.from_env())
    return _tv


async def run(fn: Callable[..., Any], *args: Any) -> Any:
    # The TV protocols are blocking sockets; keep them off the event loop.
    try:
        return await anyio.to_thread.run_sync(partial(fn, *args))
    except (TVError, ValueError) as exc:
        # Expected failures (TV off, pairing not allowed, bad URL) go back to the model verbatim.
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def tv_status() -> str:
    """Check whether the TV is on and reachable."""
    return await run(tv().status)


@mcp.tool()
async def power_off() -> str:
    """Turn the TV off."""
    return await run(tv().power_off)


@mcp.tool()
async def power_on() -> str:
    """Try to turn the TV on (HDMI-CEC or Wake-on-LAN, if configured). Often unsupported on this model."""
    return await run(tv().power_on)


@mcp.tool()
async def get_volume() -> str:
    """Read the current volume level (0-100) and mute state."""
    return await run(tv().get_volume)


@mcp.tool()
async def set_volume(level: int) -> str:
    """Set the volume to an exact level from 0 to 100."""
    return await run(tv().set_volume, level)


@mcp.tool()
async def change_volume(steps: int) -> str:
    """Nudge the volume: positive steps turn it up, negative turn it down (max 50 per call)."""
    return await run(tv().step_volume, steps)


@mcp.tool()
async def mute(muted: bool | None = None) -> str:
    """Mute (true), unmute (false), or toggle mute (omit)."""
    return await run(tv().set_mute, muted)


@mcp.tool()
async def open_app(app: str, params: str = "") -> str:
    """Open an app by name, e.g. "YouTube", "Netflix", "Plex", "Smart Hub", "Source", "Guide".

    `params` is an optional DIAL launch string passed to the app (advanced).
    """
    return await run(tv().open_app, app, params)


@mcp.tool()
async def open_netflix(profile: str, show: str = "", season: int | None = None,
                       episode: int | None = None, play: bool = True, from_start: bool = False) -> str:
    """Open Netflix as a profile (Jad, Bianca, Lee, Ben or Joel, unless reconfigured).

    With `show`, it then searches Netflix for it and opens it: with `season` and/or `episode`
    (1-based) it plays that episode, otherwise with `play` it presses Continue/Start Watching
    (play=False stops on the show's page; from_start=True plays it from the beginning instead
    of resuming). This drives the TV's on-screen keyboard and takes
    1-2 minutes; don't send other keys meanwhile.
    """
    from . import netflix

    return await run(netflix.watch, tv(), profile, show, season, episode, play, None, None, from_start)


@mcp.tool()
async def list_episodes(show: str) -> str:
    """List a series' seasons and episode titles (from TVmaze), to pick one for open_netflix."""
    from .episodes import seasons

    data = await run(seasons, show)
    return "\n".join(
        f"Season {s['number']}: " + "; ".join(f"E{e['number']} {e['name']}" for e in s["episodes"])
        for s in data["seasons"]
    ) or "No episodes found."


@mcp.tool()
async def search_netflix(query: str) -> str:
    """Look up what's on Netflix matching `query` (via JustWatch), to pick a title for open_netflix."""
    from .netflix_search import search as find

    found = await run(find, query)
    if not found:
        return "Nothing on Netflix matches that."
    return "\n".join(f"{r['title']} ({r['kind']}, {r['year']})" for r in found)


@mcp.tool()
async def list_apps() -> str:
    """List the apps this TV can open directly with open_app (others are reached via Smart Hub)."""
    from .apps import find_apps

    found = await run(find_apps, tv().dial)
    if not found:
        return "No directly-openable apps found. Use open_app('Smart Hub') and navigate with send_keys."
    return "Apps this TV can open: " + ", ".join(f"{a['name']} (open_app '{a['id']}')" for a in found)


@mcp.tool()
async def app_status(app: str) -> str:
    """Check whether an app is running, stopped, or unavailable on the TV."""
    return await run(tv().app_status, app)


@mcp.tool()
async def close_app(app: str) -> str:
    """Close an app that was launched by name (e.g. "YouTube")."""
    return await run(tv().close_app, app)


@mcp.tool()
async def play_youtube(video: str) -> str:
    """Play a YouTube video on the TV. Accepts a youtube.com / youtu.be URL (with optional ?t=) or an 11-char id."""
    return await run(tv().play_youtube, video)


@mcp.tool()
async def search_youtube(query: str, limit: int = 8) -> str:
    """Search YouTube and list matching videos with their links, to pick one for play_youtube."""
    from .youtube_search import search

    results = await run(search, query, limit)
    if not results:
        return "No videos found."
    return "\n".join(
        f"{r['title']} — {r['channel']}{' (' + r['duration'] + ')' if r['duration'] else ''}: https://youtu.be/{r['id']}"
        for r in results
    )


@mcp.tool()
async def link_youtube(code: str) -> str:
    """Link the TV's YouTube app once, using the code from YouTube > Settings > Link with TV code.

    Needed when play_youtube opens YouTube but the TV says 'This video is unavailable'.
    """
    return await run(tv().link_youtube, code)


@mcp.tool()
async def send_keys(keys: list[str], delay_seconds: float = 0.4) -> str:
    """Press remote-control buttons in order, e.g. ["KEY_CONTENTS", "KEY_RIGHT", "KEY_ENTER"].

    Use list_keys for the common key names. Good for navigating menus, channels and apps.
    """
    if not keys:
        return "No keys given."
    if len(keys) > 60:
        raise ToolError("Send at most 60 keys per call.")
    sent = await run(tv().press, keys, max(0.1, min(delay_seconds, 5.0)))
    return "Pressed " + ", ".join(sent)


@mcp.tool()
async def list_keys() -> str:
    """List common remote-control key names for send_keys."""
    return "\n".join(f"{k}: {v}" for k, v in COMMON_KEYS.items())


@mcp.tool()
async def pair_start() -> str:
    """Begin PIN pairing (needed once on TVs with encrypted firmware). Shows a 4-digit PIN on the TV."""
    return await run(tv().pair_start)


@mcp.tool()
async def pair_finish(pin: str) -> str:
    """Finish PIN pairing with the 4-digit PIN the user reads off the TV screen."""
    return await run(tv().pair_finish, pin)


@mcp.tool()
async def diagnose() -> str:
    """Probe the TV's network services and report what works. Run this first if anything fails."""
    return await run(tv().diagnose)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
