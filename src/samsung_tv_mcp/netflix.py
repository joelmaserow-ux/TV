"""Open Netflix as a chosen profile by driving the profile screen with the remote.

This TV's Netflix app ignores DIAL deep links, so everything happens with key presses: quit
Netflix properly so it starts fresh on "Choose a Profile", reopen it, go to the top of the
(vertical) list, step down to the profile, press OK.
"""

from __future__ import annotations

import json
import os
import time

from .encrypted import credentials_path

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
    # The profile screen draws before it reacts to the remote, so give it longer.
    data.setdefault("profile_wait", float(os.environ.get("SAMSUNG_TV_NETFLIX_PROFILE_WAIT", "20")))
    data.setdefault("home_wait", 10.0)  # after picking a profile, until the home screen reacts
    data.setdefault("keyboard_wait", 4.0)  # after opening Search, until the keyboard shows
    data.setdefault("type_gap", 0.4)  # between key presses while typing
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
    """Presses that pick `name` on the profile screen, whichever profile starts highlighted.

    Down past the end first (one extra for safety) parks the highlight on the last profile
    wherever it started; then Up to the wanted one and OK.
    """
    lowered = [p.lower() for p in profiles]
    if name.strip().lower() not in lowered:
        raise ValueError(f"No Netflix profile called {name!r}. Profiles: {', '.join(profiles)}.")
    index = lowered.index(name.strip().lower())
    return ["KEY_DOWN"] * (len(profiles) + 1) + ["KEY_UP"] * (len(profiles) - 1 - index) + ["KEY_ENTER"]


def _fully_exit(tv, wait: float) -> None:
    """Quit Netflix for real so the next launch starts on "Choose a Profile".

    Neither DIAL's stop nor a bare Exit key really quits Netflix on this TV: Exit asks
    "Are you sure you want to exit Netflix?", which needs Right then OK. Opening Netflix
    first makes sure it's in front to receive that, whatever state it was in.
    """
    tv._launch("Netflix")
    time.sleep(wait)
    tv.press(["KEY_EXIT"])
    time.sleep(1.5)  # let the "Are you sure?" dialog appear
    tv.press(["KEY_RIGHT"])
    time.sleep(0.5)
    tv.press(["KEY_ENTER"])
    time.sleep(3)  # let it finish quitting before relaunching


def open_as(tv, name: str) -> str:
    data = load(tv.s.host)
    keys = profile_keys(data["profiles"], name)
    _fully_exit(tv, float(data["startup_wait"]))
    tv._launch("Netflix")
    time.sleep(float(data["profile_wait"]))
    # One press per connection with a gap, like a person pressing the remote; a burst sent
    # in one go was ignored by the profile screen.
    for key in keys:
        tv.press([key])
        time.sleep(0.6)
    chosen = next(p for p in data["profiles"] if p.lower() == name.strip().lower())
    return f"Opened Netflix as {chosen}."


# --- searching -----------------------------------------------------------------------------

# Netflix's on-screen keyboard on this TV: a wide Space | Backspace row on top, then 6 columns.
KEYBOARD = ["abcdef", "ghijkl", "mnopqr", "stuvwx", "yz1234", "567890"]
MAX_TYPED = 30


def normalize_title(title: str) -> str:
    """What can actually be typed: letters, digits and single spaces."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    plain = plain.replace("&", " and ")
    plain = "".join(ch if ch.isalnum() else " " for ch in plain)
    return " ".join(plain.split())[:MAX_TYPED].strip()


def _find(ch: str) -> tuple[int, int]:
    for row, keys in enumerate(KEYBOARD):
        if ch in keys:
            return row, keys.index(ch)
    raise ValueError(ch)


def _moves(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    (r0, c0), (r1, c1) = start, end
    horizontal = ["KEY_RIGHT" if c1 > c0 else "KEY_LEFT"] * abs(c1 - c0)
    vertical = ["KEY_DOWN" if r1 > r0 else "KEY_UP"] * abs(r1 - r0)
    return horizontal + vertical


def type_keys(text: str) -> list[str]:
    """Presses that type `text`, starting with the highlight on "a"."""
    pos = (0, 0)
    keys: list[str] = []
    for ch in normalize_title(text):
        if ch == " ":
            # Space is a wide key above a/b/c. Go up from the "a" column so that coming back
            # down lands on "a" whether the TV remembers the column or snaps to the left.
            keys += _moves(pos, (0, 0)) + ["KEY_UP", "KEY_ENTER", "KEY_DOWN"]
            pos = (0, 0)
        else:
            target = _find(ch)
            keys += _moves(pos, target) + ["KEY_ENTER"]
            pos = target
    return keys


# From the home screen to the search keyboard, and from the keyboard to the first result.
TO_SEARCH = ["KEY_LEFT", "KEY_UP", "KEY_ENTER"]
TO_FIRST_RESULT = ["KEY_LEFT"] * 7 + ["KEY_RIGHT"] * 7 + ["KEY_ENTER"]


def _press_slowly(tv, keys: list[str], gap: float) -> None:
    for key in keys:
        tv.press([key])
        time.sleep(gap)


def search(tv, title: str) -> str:
    """From Netflix's home screen: open Search, type `title`, open the first result."""
    data = load(tv.s.host)
    typed = normalize_title(title)
    if not typed:
        raise ValueError("Type the name of a show or movie.")
    _press_slowly(tv, TO_SEARCH, 0.8)
    time.sleep(float(data.get("keyboard_wait", 4)))
    _press_slowly(tv, type_keys(typed), float(data.get("type_gap", 0.4)))
    time.sleep(2)  # let the results update after the last letter
    _press_slowly(tv, TO_FIRST_RESULT, 0.5)
    return f"Searched Netflix for “{typed}” and opened the first result."


def watch(tv, profile: str, title: str = "") -> str:
    """Open Netflix as `profile` and, if given, search for `title` and open it."""
    opened = open_as(tv, profile)
    if not title.strip():
        return opened
    time.sleep(float(load(tv.s.host).get("home_wait", 10)))
    return f"{opened} {search(tv, title)}"
