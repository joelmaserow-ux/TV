"""Per-TV button codes, learned by `samsung-tv button-test`.

Samsung models disagree on some key codes (KEY_FF vs KEY_FF_, KEY_POWEROFF vs KEY_POWER...).
The test tries each candidate on the real TV and remembers which one worked, or that none did,
so the family remote only shows buttons that actually do something.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .encrypted import credentials_path
from .legacy import TVError


@dataclass(frozen=True)
class Button:
    key: str  # the code the remote page sends
    label: str
    expect: str  # what the user should see on the TV
    candidates: tuple[str, ...]
    setup: str = ""  # what to have on screen before testing


BUTTONS: list[Button] = [
    Button("KEY_MENU", "Menu", "the Settings menu opens", ("KEY_MENU",),
           "Watch the TV (any normal picture, no menus open)."),
    Button("KEY_DOWN", "Down", "the highlight in the menu moves down", ("KEY_DOWN",)),
    Button("KEY_UP", "Up", "the highlight moves back up", ("KEY_UP",)),
    Button("KEY_RIGHT", "Right", "the highlight moves right / into a submenu", ("KEY_RIGHT",)),
    Button("KEY_LEFT", "Left", "the highlight moves left / back out", ("KEY_LEFT",)),
    Button("KEY_ENTER", "OK", "the highlighted item is selected", ("KEY_ENTER",)),
    Button("KEY_RETURN", "Back", "it goes back one step", ("KEY_RETURN", "KEY_BACK_MHP")),
    Button("KEY_EXIT", "Exit", "the menu closes completely", ("KEY_EXIT",)),
    Button("KEY_SOURCE", "Source", "the input/source list appears", ("KEY_SOURCE", "KEY_HDMI")),
    Button("KEY_CONTENTS", "Smart Hub", "Smart Hub opens", ("KEY_CONTENTS", "KEY_SMART", "KEY_HOME", "KEY_W_LINK"),
           "Press Exit on the TV remote first if the source list is still showing."),
    Button("KEY_GUIDE", "Guide", "the TV programme guide opens", ("KEY_GUIDE", "KEY_EPG"),
           "Exit Smart Hub with the TV remote. The guide may only work while watching the TV tuner."),
    Button("KEY_MUTE", "Mute", "the sound mutes (press again later to unmute)", ("KEY_MUTE",)),
    Button("KEY_CHUP", "Channel +", "the channel goes up", ("KEY_CHUP",),
           "Switch to the TV tuner (aerial) if you watch channels; otherwise answer 's' to skip."),
    Button("KEY_CHDOWN", "Channel −", "the channel goes down", ("KEY_CHDOWN",)),
    Button("KEY_1", "Number keys", "it starts tuning to channel 1", ("KEY_1",)),
    Button("KEY_PAUSE", "Pause", "the video pauses", ("KEY_PAUSE", "KEY_PLAYPAUSE"),
           "PLAY_VIDEO"),
    Button("KEY_PLAY", "Play", "the video plays again", ("KEY_PLAY", "KEY_PLAYPAUSE")),
    Button("KEY_FF", "Fast forward", "the video skips/scrubs forward", ("KEY_FF", "KEY_FF_", "KEY_RIGHT")),
    Button("KEY_REWIND", "Rewind", "the video skips/scrubs back", ("KEY_REWIND", "KEY_REWIND_", "KEY_LEFT")),
    Button("KEY_POWEROFF", "Off", "the TV turns off", ("KEY_POWEROFF", "KEY_POWER"),
           "Last one! This turns the TV off; turn it back on with the TV remote afterwards."),
]

ALIASES = {f"KEY_{n}": "KEY_1" for n in range(10)}  # number keys share one test


def _path(host: str):
    return credentials_path(host).with_name(f"{host}.buttons.json")


def load(host: str) -> dict:
    try:
        return json.loads(_path(host).read_text())
    except (OSError, ValueError):
        return {}


def save(host: str, data: dict) -> None:
    path = _path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def translate(keys: list[str], data: dict) -> list[str]:
    """Swap in the codes this TV answered to; refuse keys it never answered to."""
    mapping = data.get("keys", {})
    out = []
    for key in keys:
        test_key = ALIASES.get(key, key)
        if test_key not in mapping:
            out.append(key)  # untested: send as is
            continue
        found = mapping[test_key]
        if found is None:
            raise TVError(f"This TV doesn't respond to the {key} button (found by the button test).")
        out.append(found if test_key == key else key)
    return out


def unsupported(data: dict) -> list[str]:
    bad = [k for k, v in data.get("keys", {}).items() if v is None]
    if "KEY_1" in bad:
        bad += [f"KEY_{n}" for n in range(10)]
    return sorted(set(bad))
