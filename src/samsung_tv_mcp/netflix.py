"""Open Netflix as a chosen profile by driving the profile screen with the remote.

This TV's Netflix app ignores DIAL deep links, so everything happens with key presses:
close Netflix so it starts fresh on "Choose a Profile", go to the top of the (vertical) list,
step down to the profile, press OK.
"""

from __future__ import annotations

import json
import os
import time

from .encrypted import credentials_path
from .legacy import TVError

DEFAULT_PROFILES = ["Jad", "Bianca", "Lee", "Ben", "Joel"]


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.netflix.json")


def load(host: str) -> dict:
    try:
        data = json.loads(_path(host).read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("profiles", list(DEFAULT_PROFILES))
    data.setdefault("startup_wait", float(os.environ.get("SAMSUNG_TV_NETFLIX_STARTUP", "15")))
    return data


def save(host: str, data: dict) -> None:
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def set_profiles(host: str, names: list[str]) -> list[str]:
    names = [n.strip() for n in names if n.strip()]
    if not names:
        raise ValueError("List the profile names top to bottom, as they appear on the TV.")
    data = load(host)
    data["profiles"] = names
    save(host, data)
    return names


def profile_keys(profiles: list[str], name: str) -> list[str]:
    """Presses that pick `name` on the profile screen, whichever profile starts highlighted."""
    lowered = [p.lower() for p in profiles]
    if name.strip().lower() not in lowered:
        raise ValueError(f"No Netflix profile called {name!r}. Profiles: {', '.join(profiles)}.")
    index = lowered.index(name.strip().lower())
    # Assumes Up stops at the top rather than wrapping, so this lands on the first profile
    # wherever the highlight starts (`samsung-tv netflix <name>` checks it on the real TV).
    return ["KEY_UP"] * len(profiles) + ["KEY_DOWN"] * index + ["KEY_ENTER"]


def open_as(tv, name: str) -> str:
    data = load(tv.s.host)
    keys = profile_keys(data["profiles"], name)
    try:
        if tv.dial.status("Netflix") == "running":
            tv.dial.stop("Netflix")  # restart so it opens on the profile screen
            time.sleep(3)
    except TVError:
        pass
    tv._launch("Netflix")
    time.sleep(float(data["startup_wait"]))
    tv.press(keys, delay=0.5)
    chosen = next(p for p in data["profiles"] if p.lower() == name.strip().lower())
    return f"Opened Netflix as {chosen}."
