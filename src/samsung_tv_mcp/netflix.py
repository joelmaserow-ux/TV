"""Open Netflix as a chosen profile by driving the profile screen with the remote.

This TV's Netflix app ignores DIAL deep links, so everything happens with key presses: quit
Netflix properly so it starts fresh on "Choose a Profile", reopen it, go to the top of the
(vertical) list, step down to the profile, press OK.
"""

from __future__ import annotations

import json
import os
import time

from . import cancel
from .encrypted import credentials_path
from .legacy import TVError

DEFAULT_PROFILES = ["Jad", "Bianca", "Lee", "Ben", "Joel"]


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.netflix.json")


def defaults() -> dict:
    return {
        "profiles": list(DEFAULT_PROFILES),
        "startup_wait": float(os.environ.get("SAMSUNG_TV_NETFLIX_STARTUP", "15")),
        # The profile screen draws before it reacts to the remote, so give it longer.
        "profile_wait": float(os.environ.get("SAMSUNG_TV_NETFLIX_PROFILE_WAIT", "20")),
        "home_wait": 15.0,  # after picking a profile, until the home screen reacts to Left/Up
        "keyboard_wait": 4.0,  # after opening Search, until the keyboard shows
        "type_gap": 0.4,  # between key presses while typing
        "title_wait": 6.0,  # after opening a show from search, until its page reacts
        "episodes_wait": 4.0,  # after Down, Down, OK, until the episodes view shows
        "step_wait": 1.5,  # after Left onto the season list
        "season_wait": 3.0,  # after choosing a season, until its episodes load
    }


# Earlier versions saved every default, so a saved value equal to an old default wasn't
# chosen by anyone; drop it so the current default applies.
_OLD_DEFAULTS = {"home_wait": 10.0}


def load(host: str) -> dict:
    try:
        saved = json.loads(_path(host).read_text())
    except (OSError, ValueError):
        saved = {}
    for key, old in _OLD_DEFAULTS.items():
        if saved.get(key) == old:
            del saved[key]
    return {**defaults(), **saved}


def save(host: str, data: dict) -> None:
    """Save only what differs from the defaults, so later default changes still apply."""
    base = defaults()
    changed = {k: v for k, v in data.items() if base.get(k) != v}
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(changed, indent=2))


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


# The few presses that differ between devices; everything else (profile list, keyboard,
# results, episodes) is the same Netflix layout. Devices can override via `netflix_layout`.
SAMSUNG_LAYOUT = {
    # Exit asks "Are you sure you want to exit Netflix?": Right is Yes.
    # Each step is (presses, seconds to wait after them).
    "exit": [(["KEY_EXIT"], 1.5), (["KEY_RIGHT"], 0.5), (["KEY_ENTER"], 0)],
    # From the home screen to "a" on the search keyboard: (presses, seconds to wait after them).
    "to_search": [(["KEY_LEFT"], 0.8), (["KEY_UP"], 0.8), (["KEY_ENTER"], 0.8)],
}


def layout(tv) -> dict:
    return {**SAMSUNG_LAYOUT, **(getattr(tv, "netflix_layout", None) or {})}


def _state(tv) -> str:
    try:
        return tv.dial.status("Netflix")
    except TVError:
        return "unknown"


def _wait_for_state(tv, wanted: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _state(tv) == wanted:
            return True
        cancel.sleep(1)
    return _state(tv) == wanted


def _fully_exit(tv, wait: float, attempts: int = 3) -> None:
    """Quit Netflix for real so the next launch starts on "Choose a Profile".

    Neither DIAL's stop nor a bare Exit key really quits Netflix on this TV: Exit asks
    "Are you sure you want to exit Netflix?", which needs Right then OK. Opening Netflix
    first makes sure it's in front to receive that. Exit pressed while Netflix is still
    loading is ignored, so wait until the TV reports it running, and check it reports
    stopped afterwards, trying again if not.
    """
    tv._launch("Netflix")
    # Only trust the TV's running/stopped report for Netflix if it ever says "running".
    reports_state = _wait_for_state(tv, "running", 30)
    cancel.sleep(wait)
    steps = layout(tv)["exit"]
    gap = float(layout(tv).get("exit_gap", 0.6))  # between presses within a step
    for _ in range(attempts):
        for keys, pause in steps:
            for i, key in enumerate(keys):
                if i:
                    cancel.sleep(gap)
                tv.press([key])
            if pause:
                cancel.sleep(pause)
        if not reports_state:
            cancel.sleep(3)
            return
        if _wait_for_state(tv, "stopped", 6):
            cancel.sleep(2)  # let it finish quitting before relaunching
            return
        cancel.sleep(3)  # still open: probably still loading; give it a moment and retry
    raise TVError(
        "Netflix didn't quit, so it can't be opened on the profile screen. Exit Netflix with the "
        "TV remote (Exit, then Yes) and try again."
    )


def close(tv) -> str:
    """Fully quit Netflix (so it next opens on "Choose a Profile")."""
    _fully_exit(tv, float(load(tv.s.host)["startup_wait"]))
    return "Closed Netflix."


def open_as(tv, name: str) -> str:
    data = load(tv.s.host)
    keys = profile_keys(data["profiles"], name)
    _fully_exit(tv, float(data["startup_wait"]))
    tv._launch("Netflix")
    cancel.sleep(float(data["profile_wait"]))
    # One press per connection with a gap, like a person pressing the remote; a burst sent
    # in one go was ignored by the profile screen.
    for key in keys:
        tv.press([key])
        cancel.sleep(0.6)
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


def _type(text: str, space_landing: tuple[int, int] = (0, 0)) -> tuple[list[str], tuple[int, int]]:
    """Presses that type `text` from "a", and where the highlight ends up.

    `space_landing` is the key Down lands on after pressing Space ("a" on the Samsung, "b" on
    the projector's Netflix).
    """
    pos = (0, 0)
    keys: list[str] = []
    for ch in normalize_title(text):
        if ch == " ":
            # Space is a wide key above a/b/c: go up onto it from the "a" column, press it,
            # come back down, and carry on from wherever this device puts the highlight.
            keys += _moves(pos, (0, 0)) + ["KEY_UP", "KEY_ENTER", "KEY_DOWN"]
            pos = space_landing
        else:
            target = _find(ch)
            keys += _moves(pos, target) + ["KEY_ENTER"]
            pos = target
    return keys, pos


def type_keys(text: str, space_landing: tuple[int, int] = (0, 0)) -> list[str]:
    """Presses that type `text`, starting with the highlight on "a"."""
    return _type(text, space_landing)[0]


def to_first_result(pos: tuple[int, int]) -> list[str]:
    """From the last typed key to the first search result, without leaving the keyboard.

    Up from the "a" column onto Space (not pressed), Right onto Backspace, Right onto the
    first result. Going out to the left menu and back lands on Space unpredictably instead.
    """
    return _moves(pos, (0, 0)) + ["KEY_UP", "KEY_RIGHT", "KEY_RIGHT", "KEY_ENTER"]


# From the home screen to the search keyboard (on the Samsung).
TO_SEARCH = ["KEY_LEFT", "KEY_UP", "KEY_ENTER"]


def _press_slowly(tv, keys: list[str], gap: float) -> None:
    for key in keys:
        tv.press([key])
        cancel.sleep(gap)


def search(tv, title: str) -> str:
    """From Netflix's home screen: open Search, type `title`, open the first result."""
    data = load(tv.s.host)
    typed = normalize_title(title)
    if not typed:
        raise ValueError("Type the name of a show or movie.")
    for keys, pause in layout(tv)["to_search"]:
        _press_slowly(tv, keys, pause)
    cancel.sleep(float(data.get("keyboard_wait", 4)))
    keys, end = _type(typed, tuple(layout(tv).get("space_landing", (0, 0))))
    _press_slowly(tv, keys, float(data.get("type_gap", 0.4)))
    cancel.sleep(2)  # let the results update after the last letter
    _press_slowly(tv, to_first_result(end), 0.6)
    return f"Searched Netflix for “{typed}” and opened the first result."


def episode_steps(season: int, episode: int, seasons: int | None = None) -> list[tuple[list[str], str]]:
    """(presses, pause-setting) pairs from a show's page to playing season/episode.

    Down 7 (to the bottom of the show page's menu, wherever the highlight started), Up 4 and
    OK opens the episodes view; Left goes to the season list, which doesn't always start on
    Season 1. Up past the top leaves the list, but Down past the bottom stays on the last
    season, so with `seasons` (how many Netflix has) go Down past the end, then Up to the wanted
    one. Then Right lands on that season's first episode; Down to the episode; OK plays it.
    Without `seasons`, assume the list starts on Season 1.
    """
    if season < 1 or episode < 1:
        raise ValueError("Season and episode start at 1.")
    if seasons is not None and season > seasons:
        raise ValueError(f"Netflix only has {seasons} season{'s' if seasons != 1 else ''} of this here.")
    if seasons:
        to_season = ["KEY_DOWN"] * (seasons + 3) + ["KEY_UP"] * (seasons - season)
    else:
        to_season = ["KEY_DOWN"] * (season - 1)
    return [
        (["KEY_DOWN"] * 7 + ["KEY_UP"] * 4 + ["KEY_ENTER"], "episodes_wait"),
        (["KEY_LEFT"], "step_wait"),
        (to_season + ["KEY_RIGHT"], "season_wait"),
        (["KEY_DOWN"] * (episode - 1) + ["KEY_ENTER"], ""),
    ]


def open_episode(tv, season: int, episode: int, seasons: int | None = None) -> str:
    """From a show's page (just opened from search), play the given episode."""
    data = load(tv.s.host)
    for keys, pause in episode_steps(season, episode, seasons):
        _press_slowly(tv, keys, 0.6)
        if pause:
            cancel.sleep(float(data[pause]))
    return f"Playing season {season}, episode {episode}."


def season_count(title: str, year=None) -> int | None:
    """How many seasons Netflix has of `title` here: JustWatch's Netflix list, else TVmaze."""
    from .netflix_search import netflix_seasons

    numbers = netflix_seasons(title, year)
    if numbers:
        return len(numbers)
    try:
        from .episodes import seasons

        return len(seasons(title, year)["seasons"]) or None
    except TVError:
        return None


def watch(tv, profile: str, title: str = "", season: int | None = None, episode: int | None = None,
          play: bool = False, year=None, seasons: int | None = None, from_start: bool = False) -> str:
    """Open Netflix as `profile`; if given, find `title`.

    Then either play `season`/`episode` of it, or with `play` press OK on its page, which is
    Netflix's Continue Watching / Start Watching button, or with `from_start` press Up then
    OK, which is the button above it (play from the beginning). Otherwise it stops on the page.
    `seasons` is how many seasons Netflix has of it (looked up if not given).
    """
    wants_episode = season is not None or episode is not None
    if wants_episode:
        if not title.strip():
            raise ValueError("Say which show the season and episode are for.")
        season = 1 if season is None else season
        episode = 1 if episode is None else episode
        if seasons is None:
            seasons = season_count(title, year)
            if seasons is not None and season > seasons:
                seasons = None  # the lookup is behind Netflix; fall back to counting from Season 1
        episode_steps(season, episode, seasons)  # validate before touching the TV
    typed = title
    if title.strip():
        from .netflix_search import short_query

        typed = short_query(title, year)
    opened = open_as(tv, profile)
    if not title.strip():
        return opened
    data = load(tv.s.host)
    cancel.sleep(float(data["home_wait"]))
    found = search(tv, typed)
    if wants_episode:
        cancel.sleep(float(data["title_wait"]))
        return f"{opened} {found} {open_episode(tv, season, episode, seasons)}"
    if from_start:
        cancel.sleep(float(data["title_wait"]))
        _press_slowly(tv, ["KEY_UP", "KEY_ENTER"], 0.6)
        return f"{opened} {found} Playing from the beginning."
    if play:
        cancel.sleep(float(data["title_wait"]))
        tv.press(["KEY_ENTER"])
        return f"{opened} {found} Pressed Play (Continue / Start Watching)."
    return f"{opened} {found}"
